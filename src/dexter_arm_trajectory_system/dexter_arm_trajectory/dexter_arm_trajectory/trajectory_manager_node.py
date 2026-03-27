"""
Trajectory Manager Node - Core component of teach-repeat system.

Responsibilities:
1. Capture MoveIt planned trajectories from /move_group/display_planned_path
2. Store and manage trajectory segments in memory
3. Concatenate multiple segments into a single smooth trajectory
4. Apply time parameterization for optimal velocity profiles
5. Save/load trajectories to/from YAML files
6. Execute compiled trajectories via ros2_control
7. Publish preview visualizations to RViz
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

import os
import yaml
from pathlib import Path
from datetime import datetime
import copy
from ament_index_python.packages import get_package_share_directory

from moveit_msgs.msg import DisplayTrajectory, RobotTrajectory
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from control_msgs.action import FollowJointTrajectory
from std_srvs.srv import Trigger
from dexter_arm_trajectory_msgs.srv import (
    CaptureSegment, CompileTrajectory, SaveTrajectory, 
    LoadTrajectory, GetStatus, ExecuteTrajectory, InjectTrajectory
)
from dexter_arm_trajectory_msgs.msg import ExecutionProgress
from .safety_zone import SafetyZoneStore, validate_joint_trajectory


class TrajectoryManager(Node):
    """
    Main trajectory management node for teach-repeat system.
    """
    
    def __init__(self):
        super().__init__('trajectory_manager')
        
        # Declare parameters
        self.declare_parameter('planning_group', 'dexter_arm')
        self.declare_parameter('end_effector_link', 'end_effector_link')
        self.declare_parameter('controller_name', 'joint_trajectory_controller')
        self.declare_parameter('trajectory_storage_dir', '~/.ros/dexter_trajectories')
        self.declare_parameter('velocity_scaling', 0.8)
        self.declare_parameter('acceleration_scaling', 0.8)
        self.declare_parameter('time_parameterization_algorithm', 'totg')
        self.declare_parameter('moveit_display_planned_path_topic', '/move_group/display_planned_path')
        self.declare_parameter('remove_duplicate_boundaries', True)
        self.declare_parameter('auto_backup', True)
        self.declare_parameter('min_waypoint_time', 0.01)
        self.declare_parameter('safety_config_file', '')
        
        # Get parameters
        self.planning_group = self.get_parameter('planning_group').value
        self.end_effector_link = self.get_parameter('end_effector_link').value
        self.storage_dir = os.path.expanduser(
            self.get_parameter('trajectory_storage_dir').value
        )
        self.velocity_scaling = self.get_parameter('velocity_scaling').value
        self.acceleration_scaling = self.get_parameter('acceleration_scaling').value
        self.moveit_topic = self.get_parameter('moveit_display_planned_path_topic').value

        safety_cfg = str(self.get_parameter('safety_config_file').value).strip()
        if safety_cfg:
            safety_path = Path(safety_cfg).expanduser()
        else:
            safety_path = (
                Path(get_package_share_directory('dexter_arm_trajectory'))
                / 'config'
                / 'safety_zones.yaml'
            )
        self.safety_store = SafetyZoneStore(safety_path)
        self.safety_store.load()

        min_waypoint_time = float(self.get_parameter('min_waypoint_time').value)
        self.min_waypoint_dt_sec = min_waypoint_time if min_waypoint_time > 0.0 else self.safety_store.min_waypoint_dt_sec()
        
        # Controller mapping for multi-arm support
        self.controller_mapping = {
            'left_arm_controller': ['j1l', 'j2l', 'j3l', 'j4l', 'j5l', 'j6l'],
            'right_arm_controller': ['j1r', 'j2r', 'j3r', 'j4r', 'j5r', 'j6r'],
            'left_arm_gripper': ['j7l1', 'j7l2'],
            'right_arm_gripper': ['j7r1', 'j7r2']
        }
        
        # Create storage directory if it doesn't exist
        Path(self.storage_dir).mkdir(parents=True, exist_ok=True)
        self.get_logger().info(f'Trajectory storage: {self.storage_dir}')
        self.get_logger().info(f'Listening for MoveIt plans on: {self.moveit_topic}')
        self.get_logger().info(f'Safety zones loaded from: {safety_path}')
        self.get_logger().info(f'Min waypoint dt: {self.min_waypoint_dt_sec:.4f}s')
        
        # State management
        self.segment_buffer = []  # List of captured trajectory segments
        self.compiled_trajectory = None  # Final compiled trajectory
        self.last_planned_trajectory = None  # Most recent from MoveIt
        self.status = 'idle'  # idle, capturing, compiling, executing
        self.current_filename = ''
        
        # Callback groups for concurrent execution
        self.callback_group = ReentrantCallbackGroup()
        
        # Subscriber: Listen to MoveIt planned trajectories
        self.moveit_sub = self.create_subscription(
            DisplayTrajectory,
            self.moveit_topic,
            self.moveit_trajectory_callback,
            10,
            callback_group=self.callback_group
        )
        
        # Publisher: Preview compiled trajectories in RViz
        self.preview_pub = self.create_publisher(
            DisplayTrajectory,
            '/trajectory_preview',
            10
        )
        
        # Publisher: Execution progress feedback
        self.progress_pub = self.create_publisher(
            ExecutionProgress,
            '/trajectory_manager/execution_progress',
            10
        )
        
        # Services for GUI control
        self.capture_srv = self.create_service(
            CaptureSegment,
            '/trajectory_manager/capture_segment',
            self.capture_segment_callback,
            callback_group=self.callback_group
        )
        
        self.clear_srv = self.create_service(
            Trigger,
            '/trajectory_manager/clear_buffer',
            self.clear_buffer_callback,
            callback_group=self.callback_group
        )
        
        self.compile_srv = self.create_service(
            CompileTrajectory,
            '/trajectory_manager/compile',
            self.compile_trajectory_callback,
            callback_group=self.callback_group
        )
        
        self.save_srv = self.create_service(
            SaveTrajectory,
            '/trajectory_manager/save',
            self.save_trajectory_callback,
            callback_group=self.callback_group
        )
        
        self.load_srv = self.create_service(
            LoadTrajectory,
            '/trajectory_manager/load',
            self.load_trajectory_callback,
            callback_group=self.callback_group
        )
        
        self.status_srv = self.create_service(
            GetStatus,
            '/trajectory_manager/get_status',
            self.get_status_callback,
            callback_group=self.callback_group
        )
        
        self.execute_srv = self.create_service(
            ExecuteTrajectory,
            '/trajectory_manager/execute',
            self.execute_trajectory_callback,
            callback_group=self.callback_group
        )
        
        self.inject_srv = self.create_service(
            InjectTrajectory,
            '/trajectory_manager/inject_trajectory',
            self.inject_trajectory_callback,
            callback_group=self.callback_group
        )
        
        # Action clients for multi-controller execution
        self.active_action_clients = {}  # controller_name -> ActionClient
        self.active_goal_handles = {}     # controller_name -> goal_handle
        self.execution_start_time = None
        
        self.get_logger().info('Trajectory Manager initialized successfully')
        self.get_logger().info(f'Planning group: {self.planning_group}')
        self.get_logger().info('Ready to capture MoveIt trajectories')
    
    
    def moveit_trajectory_callback(self, msg: DisplayTrajectory):
        """
        Callback when MoveIt publishes a planned trajectory.
        Store it in memory for potential capture.
        """
        if len(msg.trajectory) > 0:
            self.last_planned_trajectory = msg.trajectory[0]
            point_count = len(self.last_planned_trajectory.joint_trajectory.points)
            joint_count = len(self.last_planned_trajectory.joint_trajectory.joint_names)
            
            self.get_logger().info(
                f'Received MoveIt trajectory: {point_count} points, {joint_count} joints. '
                f'Ready to capture.'
            )
        else:
            self.get_logger().warn('Received empty DisplayTrajectory message')
    
    
    def capture_segment_callback(self, request, response):
        """
        Service callback: Capture the last planned trajectory as a segment.
        """
        if self.last_planned_trajectory is None:
            response.success = False
            response.message = 'No planned trajectory available to capture'
            response.segment_count = len(self.segment_buffer)
            return response
        
        # Deep copy to avoid reference issues
        segment = copy.deepcopy(self.last_planned_trajectory.joint_trajectory)
        self.segment_buffer.append(segment)
        
        response.success = True
        response.message = f'Captured segment {len(self.segment_buffer)}'
        response.segment_count = len(self.segment_buffer)
        
        self.get_logger().info(
            f'✓ Captured segment {len(self.segment_buffer)} with '
            f'{len(segment.points)} waypoints'
        )
        
        return response
    
    
    def clear_buffer_callback(self, request, response):
        """
        Service callback: Clear all captured segments.
        """
        count = len(self.segment_buffer)
        self.segment_buffer.clear()
        self.compiled_trajectory = None
        self.current_filename = ''
        
        response.success = True
        response.message = f'Cleared {count} segments'
        
        self.get_logger().info(f'Buffer cleared ({count} segments removed)')
        
        return response
    
    
    def inject_trajectory_callback(self, request, response):
        """
        Service callback: Accept an externally-built JointTrajectory and store
        it as the compiled trajectory, ready for save / execute.
        """
        traj = request.trajectory
        if len(traj.points) == 0:
            response.success = False
            response.message = 'Injected trajectory has no waypoints'
            return response

        errors = validate_joint_trajectory(traj, self.min_waypoint_dt_sec)
        if errors:
            response.success = False
            response.message = f'Injected trajectory invalid: {errors[0]}'
            self.get_logger().error(response.message)
            return response

        self.compiled_trajectory = traj
        self.status = 'compiled'
        self.current_filename = ''

        # Publish preview
        preview_msg = DisplayTrajectory()
        rt = RobotTrajectory()
        rt.joint_trajectory = traj
        preview_msg.trajectory.append(rt)
        self.preview_pub.publish(preview_msg)

        desc = request.description or 'shape trajectory'
        self.get_logger().info(
            f'✓ Injected trajectory: {len(traj.points)} waypoints, '
            f'description="{desc}"'
        )

        response.success = True
        response.message = (
            f'Trajectory injected: {len(traj.points)} waypoints'
        )
        return response
    
    
    def compile_trajectory_callback(self, request, response):
        """
        Service callback: Concatenate and smooth all segments.
        """
        if len(self.segment_buffer) == 0:
            response.success = False
            response.message = 'No segments to compile'
            response.total_waypoints = 0
            response.duration = 0.0
            return response
        
        self.status = 'compiling'
        self.get_logger().info('Starting trajectory compilation...')
        
        try:
            # Concatenate segments
            merged_trajectory = self._concatenate_segments()

            validation_errors = validate_joint_trajectory(merged_trajectory, self.min_waypoint_dt_sec)
            if validation_errors:
                response.success = False
                response.message = f'Compilation produced invalid trajectory: {validation_errors[0]}'
                response.total_waypoints = 0
                response.duration = 0.0
                self.get_logger().error(response.message)
                return response
            
            # Apply time parameterization (placeholder - needs MoveIt Python API)
            # For now, we'll use the existing time stamps
            self.compiled_trajectory = merged_trajectory
            
            duration = merged_trajectory.points[-1].time_from_start.sec + \
                      merged_trajectory.points[-1].time_from_start.nanosec * 1e-9
            
            response.success = True
            response.message = f'Compiled {len(self.segment_buffer)} segments'
            response.total_waypoints = len(merged_trajectory.points)
            response.duration = duration
            
            self.get_logger().info(
                f'✓ Compilation complete: {response.total_waypoints} waypoints, '
                f'{duration:.2f}s duration'
            )
            
            # Publish preview
            self._publish_preview()
            
        except Exception as e:
            response.success = False
            response.message = f'Compilation failed: {str(e)}'
            response.total_waypoints = 0
            response.duration = 0.0
            self.get_logger().error(f'Compilation error: {str(e)}')
        
        finally:
            self.status = 'idle'
        
        return response
    
    
    def _concatenate_segments(self):
        """
        Concatenate multiple trajectory segments into one smooth path.
        """
        if len(self.segment_buffer) == 1:
            return self.segment_buffer[0]
        
        merged = JointTrajectory()
        merged.joint_names = self.segment_buffer[0].joint_names
        
        time_offset_sec = 0.0
        remove_duplicates = self.get_parameter('remove_duplicate_boundaries').value
        
        for i, segment in enumerate(self.segment_buffer):
            if i == 0:
                # Add all points from first segment
                for pt in segment.points:
                    merged.points.append(copy.deepcopy(pt))
                
                last_pt = segment.points[-1]
                time_offset_sec = last_pt.time_from_start.sec + \
                                 last_pt.time_from_start.nanosec * 1e-9
            else:
                # Skip first point if it's a duplicate boundary
                start_idx = 1 if remove_duplicates else 0
                
                for pt in segment.points[start_idx:]:
                    new_pt = copy.deepcopy(pt)
                    
                    # Adjust time offset
                    pt_time = pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9
                    new_time = time_offset_sec + pt_time
                    
                    new_pt.time_from_start.sec = int(new_time)
                    new_pt.time_from_start.nanosec = int((new_time % 1) * 1e9)
                    
                    merged.points.append(new_pt)
                
                last_pt = segment.points[-1]
                time_offset_sec += last_pt.time_from_start.sec + \
                                  last_pt.time_from_start.nanosec * 1e-9
        
        self.get_logger().info(
            f'Concatenated {len(self.segment_buffer)} segments → '
            f'{len(merged.points)} total waypoints'
        )
        
        return merged
    
    
    def _publish_preview(self):
        """
        Publish compiled trajectory as DisplayTrajectory for RViz preview.
        """
        if self.compiled_trajectory is None:
            return
        
        display_traj = DisplayTrajectory()
        display_traj.model_id = 'dexter_arm'
        
        robot_traj = RobotTrajectory()
        robot_traj.joint_trajectory = self.compiled_trajectory
        
        display_traj.trajectory.append(robot_traj)
        
        self.preview_pub.publish(display_traj)
        self.get_logger().info('Published trajectory preview to RViz')
    
    
    def save_trajectory_callback(self, request, response):
        """
        Service callback: Save compiled trajectory to YAML file.
        """
        if self.compiled_trajectory is None:
            response.success = False
            response.message = 'No compiled trajectory to save'
            response.full_path = ''
            return response
        
        try:
            filename = request.filename if request.filename else \
                      f"trajectory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
            
            filepath = os.path.join(self.storage_dir, filename)
            
            # Convert trajectory to dict for YAML serialization
            traj_dict = self._trajectory_to_dict(
                self.compiled_trajectory,
                request.description
            )
            
            with open(filepath, 'w') as f:
                yaml.dump(traj_dict, f, default_flow_style=False)
            
            self.current_filename = filename
            response.success = True
            response.message = f'Saved trajectory to {filename}'
            response.full_path = filepath
            
            self.get_logger().info(f'✓ Saved trajectory: {filepath}')
            
        except Exception as e:
            response.success = False
            response.message = f'Save failed: {str(e)}'
            response.full_path = ''
            self.get_logger().error(f'Save error: {str(e)}')
        
        return response
    
    
    def load_trajectory_callback(self, request, response):
        """
        Service callback: Load trajectory from YAML file.
        """
        try:
            if os.path.isabs(request.filename):
                filepath = request.filename
            else:
                filepath = os.path.join(self.storage_dir, request.filename)
            
            if not os.path.exists(filepath):
                response.success = False
                response.message = f'File not found: {request.filename}'
                response.waypoint_count = 0
                response.duration = 0.0
                return response
            
            with open(filepath, 'r') as f:
                traj_dict = yaml.safe_load(f)
            
            self.compiled_trajectory = self._dict_to_trajectory(traj_dict)

            validation_errors = validate_joint_trajectory(self.compiled_trajectory, self.min_waypoint_dt_sec)
            if validation_errors:
                response.success = False
                response.message = f'Loaded trajectory invalid: {validation_errors[0]}'
                response.waypoint_count = 0
                response.duration = 0.0
                self.get_logger().error(response.message)
                self.compiled_trajectory = None
                return response

            self.current_filename = request.filename
            
            duration = traj_dict['duration']
            waypoint_count = len(self.compiled_trajectory.points)
            
            response.success = True
            response.message = f'Loaded trajectory from {request.filename}'
            response.waypoint_count = waypoint_count
            response.duration = duration
            
            self.get_logger().info(
                f'✓ Loaded trajectory: {filepath} '
                f'({waypoint_count} waypoints, {duration:.2f}s)'
            )
            
            # Publish preview
            self._publish_preview()
            
        except Exception as e:
            response.success = False
            response.message = f'Load failed: {str(e)}'
            response.waypoint_count = 0
            response.duration = 0.0
            self.get_logger().error(f'Load error: {str(e)}')
        
        return response
    
    
    def execute_trajectory_callback(self, request, response):
        """
        Service callback: Execute the compiled trajectory with multi-arm support.
        """
        if self.compiled_trajectory is None:
            response.success = False
            response.message = 'No compiled trajectory to execute'
            return response
        
        if self.status == 'executing':
            response.success = False
            response.message = 'Already executing a trajectory'
            return response
        
        self.get_logger().info('Preparing trajectory execution...')
        
        # Detect required controllers
        required_controllers = self._detect_required_controllers(self.compiled_trajectory)
        self.get_logger().info(f'Detected required controllers: {required_controllers}')
        
        # Split trajectory by controller
        controller_trajectories = self._split_trajectory_by_controller(self.compiled_trajectory)
        
        # Create action clients and send goals
        self.active_action_clients.clear()
        self.active_goal_handles.clear()
        self.execution_start_time = self.get_clock().now()
        
        for controller_name in required_controllers:
            # Create action client
            client = ActionClient(
                self,
                FollowJointTrajectory,
                f'/{controller_name}/follow_joint_trajectory',
                callback_group=self.callback_group
            )
            
            # Wait for server
            if not client.wait_for_server(timeout_sec=2.0):
                response.success = False
                response.message = f'Controller {controller_name} not available'
                self.get_logger().error(f'Action server for {controller_name} not available')
                return response
            
            self.active_action_clients[controller_name] = client
        
        # Send goals to all controllers
        self.status = 'executing'
        for controller_name in required_controllers:
            goal = FollowJointTrajectory.Goal()
            goal.trajectory = controller_trajectories[controller_name]
            
            client = self.active_action_clients[controller_name]
            self.get_logger().info(
                f'Sending trajectory ({len(goal.trajectory.points)} points) to {controller_name}...'
            )
            
            send_goal_future = client.send_goal_async(
                goal,
                feedback_callback=lambda fb, cn=controller_name: self.goal_feedback_callback(fb, cn)
            )
            send_goal_future.add_done_callback(
                lambda future, cn=controller_name: self.goal_response_callback(future, cn)
            )
        
        response.success = True
        response.message = f'Executing on {len(required_controllers)} controller(s)'
        
        return response
    
    
    def goal_response_callback(self, future, controller_name):
        """Handle goal response from a controller."""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error(f'Trajectory execution rejected by {controller_name}')
            self.status = 'idle'
            return
        
        self.get_logger().info(f'Trajectory accepted by {controller_name}, executing...')
        self.active_goal_handles[controller_name] = goal_handle
        
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(
            lambda future, cn=controller_name: self.get_result_callback(future, cn)
        )
    
    
    def goal_feedback_callback(self, feedback_msg, controller_name):
        """Receive and publish execution progress feedback."""
        if self.compiled_trajectory is None or self.execution_start_time is None:
            return
        
        # Calculate progress based on time
        total_duration_sec = (
            self.compiled_trajectory.points[-1].time_from_start.sec +
            self.compiled_trajectory.points[-1].time_from_start.nanosec * 1e-9
        )
        
        elapsed = (self.get_clock().now() - self.execution_start_time).nanoseconds * 1e-9
        progress_percent = min(100.0, (elapsed / total_duration_sec) * 100.0)
        
        # Publish progress
        progress_msg = ExecutionProgress()
        progress_msg.progress_percent = progress_percent
        progress_msg.current_time = elapsed
        progress_msg.total_duration = total_duration_sec
        progress_msg.status = 'executing'
        
        # Get current waypoint from feedback
        if hasattr(feedback_msg.feedback, 'actual') and hasattr(feedback_msg.feedback.actual, 'positions'):
            progress_msg.current_waypoint = list(feedback_msg.feedback.actual.positions)
        
        self.progress_pub.publish(progress_msg)
    
    
    
    def get_result_callback(self, future, controller_name):
        """Handle execution result from a controller."""
        result = future.result().result
        status = future.result().status
        
        if result.error_code == FollowJointTrajectory.Result.SUCCESSFUL:
            self.get_logger().info(f'✓ Trajectory execution completed successfully on {controller_name}')
        else:
            self.get_logger().error(f'Trajectory execution failed on {controller_name} with error code: {result.error_code}')
        
        # Remove from active handles
        if controller_name in self.active_goal_handles:
            del self.active_goal_handles[controller_name]
        
        # Check if all controllers finished
        if len(self.active_goal_handles) == 0:
            self.status = 'idle'
            self.execution_start_time = None
            self.get_logger().info('✓ All controllers completed execution')
            
            # Publish final progress
            progress_msg = ExecutionProgress()
            progress_msg.progress_percent = 100.0
            progress_msg.current_time = 0.0
            progress_msg.total_duration = 0.0
            progress_msg.status = 'completed'
            progress_msg.current_waypoint = []
            self.progress_pub.publish(progress_msg)
    
    
    def get_status_callback(self, request, response):
        """
        Service callback: Get current manager status.
        """
        response.status = self.status
        response.segment_count = len(self.segment_buffer)
        response.has_compiled_trajectory = (self.compiled_trajectory is not None)
        response.current_filename = self.current_filename
        
        if self.compiled_trajectory:
            response.total_waypoints = len(self.compiled_trajectory.points)
            last_pt = self.compiled_trajectory.points[-1]
            response.trajectory_duration = (
                last_pt.time_from_start.sec + 
                last_pt.time_from_start.nanosec * 1e-9
            )
        else:
            response.total_waypoints = 0
            response.trajectory_duration = 0.0
        
        return response
    
    
    def _trajectory_to_dict(self, trajectory, description=''):
        """
        Convert JointTrajectory to dictionary for YAML serialization.
        """
        return {
            'name': self.current_filename.replace('.yaml', ''),
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'joint_names': trajectory.joint_names,
            'duration': (
                trajectory.points[-1].time_from_start.sec +
                trajectory.points[-1].time_from_start.nanosec * 1e-9
            ),
            'waypoint_count': len(trajectory.points),
            'points': [
                {
                    'positions': list(pt.positions),
                    'velocities': list(pt.velocities) if pt.velocities else [],
                    'accelerations': list(pt.accelerations) if pt.accelerations else [],
                    'time_from_start': (
                        pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9
                    )
                }
                for pt in trajectory.points
            ]
        }
    
    
    def _dict_to_trajectory(self, traj_dict):
        """
        Convert dictionary to JointTrajectory.
        """
        trajectory = JointTrajectory()
        trajectory.joint_names = traj_dict['joint_names']
        
        for pt_dict in traj_dict['points']:
            pt = JointTrajectoryPoint()
            pt.positions = pt_dict['positions']
            pt.velocities = pt_dict.get('velocities', [])
            pt.accelerations = pt_dict.get('accelerations', [])
            
            time_sec = pt_dict['time_from_start']
            pt.time_from_start.sec = int(time_sec)
            pt.time_from_start.nanosec = int((time_sec % 1) * 1e9)
            
            trajectory.points.append(pt)
        
        return trajectory
    
    
    def _detect_required_controllers(self, trajectory):
        """
        Analyze trajectory joints and return list of required controllers.
        """
        joint_names = set(trajectory.joint_names)
        required_controllers = []
        
        for controller, joints in self.controller_mapping.items():
            if any(j in joint_names for j in joints):
                required_controllers.append(controller)
        
        return required_controllers
    
    
    def _split_trajectory_by_controller(self, trajectory):
        """
        Split trajectory into per-controller sub-trajectories.
        Returns dict: {controller_name: JointTrajectory}
        """
        controller_trajectories = {}
        
        for controller, joints in self.controller_mapping.items():
            # Find indices of joints for this controller
            indices = [i for i, j in enumerate(trajectory.joint_names) if j in joints]
            if not indices:
                continue
            
            # Create sub-trajectory
            sub_traj = JointTrajectory()
            sub_traj.joint_names = [trajectory.joint_names[i] for i in indices]
            
            for pt in trajectory.points:
                new_pt = JointTrajectoryPoint()
                new_pt.positions = [pt.positions[i] for i in indices]
                new_pt.velocities = [pt.velocities[i] for i in indices] if pt.velocities else []
                new_pt.accelerations = [pt.accelerations[i] for i in indices] if pt.accelerations else []
                new_pt.time_from_start = pt.time_from_start
                sub_traj.points.append(new_pt)
            
            controller_trajectories[controller] = sub_traj
        
        return controller_trajectories


def main(args=None):
    rclpy.init(args=args)
    
    node = TrajectoryManager()
    
    # Use MultiThreadedExecutor for concurrent service handling
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
