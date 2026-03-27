#!/usr/bin/env python3
"""
DEXTER Shape Trajectory Generator Node
=======================================
Reads a shape config YAML, generates Frenet-Serret Cartesian poses,
calls MoveIt2's computeCartesianPath(), time-parameterizes the result,
then serializes it to a YAML matching the teach-and-repeat format.

Run:
    ros2 run dexter_trajectory_generator trajectory_node \
        --ros-args -p config_file:=/path/to/shape_config.yaml \
                   -p output_file:=/path/to/output.yaml
"""

import rclpy
from rclpy.node import Node
from rclpy.logging import get_logger

import numpy as np
import yaml
import os
from datetime import datetime
from typing import List, Tuple

# MoveIt2 Python bindings
from moveit.planning import MoveItPy
from moveit.core.robot_state import RobotState
from moveit.core.kinematic_constraints import construct_joint_constraint

# ROS2 message types
from geometry_msgs.msg import Pose, Point, Quaternion
from moveit_msgs.msg import RobotTrajectory
from moveit_msgs.srv import GetCartesianPath
from std_msgs.msg import Header
from trajectory_msgs.msg import JointTrajectoryPoint

from .frenet_serret import FrenetSerretFrames
from .shape_generator import ShapeGenerator


class DexterTrajectoryGeneratorNode(Node):
    """
    ROS2 node that:
      1. Loads a shape config YAML
      2. Generates dense Cartesian waypoints with correct orientations
      3. Calls MoveIt2 computeCartesianPath for the selected arm
      4. Saves the resulting joint trajectory as a YAML
    """

    # Joint names in the exact order the YAML expects
    ALL_JOINT_NAMES = [
        'j1l', 'j2l', 'j3l', 'j4l', 'j5l', 'j6l',
        'j1r', 'j2r', 'j3r', 'j4r', 'j5r', 'j6r',
    ]

    # MoveIt planning group names (must match your MoveIt config)
    PLANNING_GROUPS = {
        'left':  'left_arm',
        'right': 'right_arm',
        'dual':  'dual_arm',
    }

    # End-effector link names (must match your MoveIt config)
    EEF_LINKS = {
        'left':  'tool0_left',
        'right': 'tool0_right',
    }

    def __init__(self):
        super().__init__('dexter_trajectory_generator')

        # ── Parameters ──────────────────────────────────────────────────────
        self.declare_parameter('config_file',  '')
        self.declare_parameter('output_file',  '')
        self.declare_parameter('description',  'Shape trajectory - Dexter')
        self.declare_parameter('eef_step',     0.005)   # 5 mm Cartesian resolution
        self.declare_parameter('jump_threshold', 0.0)   # 0 = disable jump check (use with care)
        self.declare_parameter('max_velocity_scaling',     0.3)
        self.declare_parameter('max_acceleration_scaling', 0.1)
        self.declare_parameter('avoid_collisions', True)
        self.declare_parameter('time_param_method', 'totg')  # 'totg' or 'ruckig'

        config_file  = self.get_parameter('config_file').value
        output_file  = self.get_parameter('output_file').value
        description  = self.get_parameter('description').value

        if not config_file:
            self.get_logger().error('No config_file parameter provided. Shutting down.')
            raise SystemExit(1)

        # ── Load shape config ────────────────────────────────────────────────
        self.get_logger().info(f'Loading shape config: {config_file}')
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)

        # ── Init MoveItPy ────────────────────────────────────────────────────
        self.get_logger().info('Initializing MoveItPy...')
        self.moveit = MoveItPy(node_name='dexter_trajectory_generator')
        self.get_logger().info('MoveItPy ready.')

        # ── Create Cartesian path service client ─────────────────────────────
        self._cartesian_client = self.create_client(
            GetCartesianPath,
            '/compute_cartesian_path'
        )

        # ── Generate & save trajectory ───────────────────────────────────────
        try:
            trajectory_yaml = self._run_pipeline()
        except Exception as e:
            self.get_logger().error(f'Pipeline failed: {e}')
            raise

        # ── Write output ─────────────────────────────────────────────────────
        if not output_file:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            shape = self.config.get('shape', {}).get('type', 'shape')
            arm   = self.config.get('arm', 'left')
            output_file = f'dexter_{arm}_{shape}_{ts}.yaml'

        trajectory_yaml['description'] = description
        trajectory_yaml['timestamp']   = datetime.now().isoformat()

        with open(output_file, 'w') as f:
            yaml.dump(trajectory_yaml, f, default_flow_style=False, sort_keys=False)

        self.get_logger().info(
            f'Trajectory saved → {output_file}  '
            f'({trajectory_yaml["waypoint_count"]} waypoints, '
            f'{trajectory_yaml["duration"]:.3f}s)'
        )

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN PIPELINE
    # ─────────────────────────────────────────────────────────────────────────

    def _run_pipeline(self) -> dict:
        cfg = self.config

        arm          = cfg.get('arm', 'left')           # 'left' | 'right'
        shape_cfg    = cfg['shape']
        ref_cfg      = cfg['reference_point']
        surface_cfg  = cfg.get('surface', {'normal': [0, 0, 1]})

        # ── 1. Build reference pose ──────────────────────────────────────────
        ref_pos    = np.array([ref_cfg['x'], ref_cfg['y'], ref_cfg['z']])
        surface_normal = np.array(surface_cfg.get('normal', [0, 0, 1]), dtype=float)
        surface_normal /= np.linalg.norm(surface_normal)

        tool_tilt_deg  = surface_cfg.get('tool_tilt_deg', 0.0)   # approach tilt

        self.get_logger().info(
            f'Arm: {arm} | Shape: {shape_cfg["type"]} | '
            f'Ref: {ref_pos} | Surface normal: {surface_normal}'
        )

        # ── 2. Generate 3-D position waypoints ──────────────────────────────
        gen   = ShapeGenerator(shape_cfg, ref_pos, surface_normal)
        positions = gen.generate()   # np.ndarray (N, 3)
        self.get_logger().info(f'Generated {len(positions)} position waypoints.')

        # ── 3. Attach Frenet-Serret orientation to each waypoint ─────────────
        fs    = FrenetSerretFrames(surface_normal, tool_tilt_deg)
        poses = fs.build_pose_list(positions)    # list of geometry_msgs/Pose
        self.get_logger().info(f'Frenet-Serret frames computed for {len(poses)} poses.')

        # ── 4. Call MoveIt2 computeCartesianPath ─────────────────────────────
        robot_trajectory = self._compute_cartesian_path(arm, poses)

        # ── 5. Serialize RobotTrajectory → YAML dict ─────────────────────────
        return self._robot_trajectory_to_yaml(robot_trajectory)

    # ─────────────────────────────────────────────────────────────────────────
    # MOVEIT2 CARTESIAN PATH
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_cartesian_path(self, arm: str, poses: list) -> RobotTrajectory:
        """
        Calls MoveIt2's /compute_cartesian_path service for the given arm and list of poses.
        Time-parameterizes the result (TOTG or ruckig).
        Returns a fully time-parameterized RobotTrajectory.
        """
        group_name = self.PLANNING_GROUPS[arm]
        eef_link   = self.EEF_LINKS[arm]

        eef_step         = self.get_parameter('eef_step').value
        jump_threshold   = self.get_parameter('jump_threshold').value
        avoid_collisions = self.get_parameter('avoid_collisions').value
        vel_scale        = self.get_parameter('max_velocity_scaling').value
        acc_scale        = self.get_parameter('max_acceleration_scaling').value
        time_method      = self.get_parameter('time_param_method').value

        self.get_logger().info(
            f'Computing Cartesian path: {len(poses)} waypoints, '
            f'eef_step={eef_step}m, group={group_name}, eef={eef_link}'
        )

        # ── Call the /compute_cartesian_path service ─────────────────────────
        if not self._cartesian_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError('MoveIt /compute_cartesian_path service not available')

        cart_req = GetCartesianPath.Request()
        cart_req.header.frame_id = "world"
        cart_req.group_name = group_name
        cart_req.link_name = eef_link
        cart_req.waypoints = poses
        cart_req.max_step = eef_step
        cart_req.jump_threshold = jump_threshold
        cart_req.avoid_collisions = avoid_collisions
        cart_req.start_state = RobotState()
        cart_req.start_state.is_diff = True

        future = self._cartesian_client.call_async(cart_req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=30.0)

        if future.result() is None:
            raise RuntimeError('compute_cartesian_path service call failed')

        cart_resp = future.result()
        fraction = cart_resp.fraction
        robot_trajectory = cart_resp.solution

        if fraction < 0.99:
            self.get_logger().warn(
                f'Cartesian path only {fraction*100:.1f}% complete. '
                f'Check workspace / singularities / joint limits.'
            )
        else:
            self.get_logger().info(f'Cartesian path: {fraction*100:.1f}% achieved.')

        if robot_trajectory is None or len(robot_trajectory.joint_trajectory.points) == 0:
            raise RuntimeError('computeCartesianPath returned empty trajectory.')

        # ── Time parameterization ────────────────────────────────────────────
        self.get_logger().info(
            f'Time-parameterizing with {time_method.upper()} '
            f'(vel={vel_scale}, acc={acc_scale})...'
        )

        if time_method == 'ruckig':
            robot_trajectory.apply_ruckig_time_parameterization(
                max_velocity_scaling_factor     = vel_scale,
                max_acceleration_scaling_factor = acc_scale,
            )
        else:  # totg (default, more conservative, always works)
            robot_trajectory.apply_totg_time_parameterization(
                velocity_scaling_factor     = vel_scale,
                acceleration_scaling_factor = acc_scale,
            )

        return robot_trajectory

    # ─────────────────────────────────────────────────────────────────────────
    # SERIALIZER: RobotTrajectory → YAML dict (matches teach-and-repeat format)
    # ─────────────────────────────────────────────────────────────────────────

    def _robot_trajectory_to_yaml(self, robot_trajectory: RobotTrajectory) -> dict:
        """
        Converts a MoveIt2 RobotTrajectory into the exact YAML dict structure
        used by the teach-and-repeat system:

            joint_names: [j1l..j6l, j1r..j6r]
            points:
              - positions: [12 values]
                velocities: [12 values]
                accelerations: [12 values]
                time_from_start: float
            duration: float
            waypoint_count: int
        """
        jt = robot_trajectory.joint_trajectory

        # Joint order in this trajectory (may not be full 12-joint order)
        traj_joint_names = list(jt.joint_names)

        # Build index map: ALL_JOINT_NAMES position → index in trajectory
        # Joints NOT in this trajectory stay at 0.0 (they are the other arm, stationary)
        idx_map = {}
        for i, jn in enumerate(self.ALL_JOINT_NAMES):
            if jn in traj_joint_names:
                idx_map[i] = traj_joint_names.index(jn)
            else:
                idx_map[i] = None   # will be filled with 0.0

        points = []
        for pt in jt.points:
            # pt.time_from_start is a rclpy Duration
            t = pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9

            pos   = list(pt.positions)
            vel   = list(pt.velocities)    if pt.velocities    else [0.0] * len(pos)
            accel = list(pt.accelerations) if pt.accelerations else [0.0] * len(pos)

            # Expand to full 12-joint order
            full_pos   = []
            full_vel   = []
            full_accel = []
            for i in range(12):
                j = idx_map[i]
                if j is not None:
                    full_pos.append(float(pos[j]))
                    full_vel.append(float(vel[j]))
                    full_accel.append(float(accel[j]))
                else:
                    full_pos.append(0.0)
                    full_vel.append(0.0)
                    full_accel.append(0.0)

            points.append({
                'positions':      full_pos,
                'velocities':     full_vel,
                'accelerations':  full_accel,
                'time_from_start': t,
            })

        duration = points[-1]['time_from_start'] if points else 0.0

        return {
            'description':   '',   # filled by caller
            'duration':      duration,
            'joint_names':   self.ALL_JOINT_NAMES,
            'name':          '',
            'points':        points,
            'timestamp':     '',   # filled by caller
            'waypoint_count': len(points),
        }


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    try:
        node = DexterTrajectoryGeneratorNode()
    except SystemExit:
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
