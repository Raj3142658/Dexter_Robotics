"""
Shape Trajectory Node — generates Cartesian waypoints for geometric shapes
and converts them to joint-space via MoveIt's compute_cartesian_path service.

Supported shapes (MVP): arc, line
Future: square, rectangle, triangle, oval

All shapes are generated in the y=0 plane with a fixed (home-position)
end-effector orientation.
"""

import math
import numpy as np
from scipy.spatial.transform import Rotation as R
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from ament_index_python.packages import get_package_share_directory

from geometry_msgs.msg import Pose, Point, Quaternion, PoseStamped
from moveit_msgs.msg import RobotState
from moveit_msgs.srv import GetCartesianPath, GetPositionFK
from sensor_msgs.msg import JointState
from std_msgs.msg import Header
from trajectory_msgs.msg import JointTrajectory

from dexter_arm_trajectory_msgs.srv import (
    GenerateShapeTrajectory,
    InjectTrajectory,
)
from .safety_zone import SafetyZoneStore


# ─── Arm configuration ──────────────────────────────────────────────────
_ARM_CONFIG = {
    "left": {
        "planning_group": "left_arm",
        "ee_link": "tool0_left",
        "joint_names": ["j1l", "j2l", "j3l", "j4l", "j5l", "j6l"],
        "home_positions": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    },
    "right": {
        "planning_group": "right_arm",
        "ee_link": "tool0_right",
        "joint_names": ["j1r", "j2r", "j3r", "j4r", "j5r", "j6r"],
        "home_positions": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    },
}

# Fallback orientation — only used if FK call fails.
# Will be replaced at runtime by the real FK-computed orientation.
_FALLBACK_ORIENTATION = Quaternion(x=0.0, y=0.0, z=0.0, w=1.0)


class ShapeTrajectoryNode(Node):
    """Generates shape-based trajectories via MoveIt Cartesian planning."""

    def __init__(self):
        super().__init__("shape_trajectory_node")

        self.callback_group = ReentrantCallbackGroup()

        self.declare_parameter("safety_config_file", "")
        safety_cfg = str(self.get_parameter("safety_config_file").value).strip()
        if safety_cfg:
            safety_path = Path(safety_cfg).expanduser()
        else:
            safety_path = (
                Path(get_package_share_directory("dexter_arm_trajectory"))
                / "config"
                / "safety_zones.yaml"
            )

        self.safety_store = SafetyZoneStore(safety_path)
        self.safety_store.load()
        self.get_logger().info(f"Loaded safety zones from: {safety_path}")

        # MoveIt compute_cartesian_path service client
        self._cartesian_client = self.create_client(
            GetCartesianPath,
            "/compute_cartesian_path",
            callback_group=self.callback_group,
        )

        # MoveIt compute_fk service client (to resolve real TCP orientation)
        self._fk_client = self.create_client(
            GetPositionFK,
            "/compute_fk",
            callback_group=self.callback_group,
        )

        # Inject trajectory into the manager
        self._inject_client = self.create_client(
            InjectTrajectory,
            "/trajectory_manager/inject_trajectory",
            callback_group=self.callback_group,
        )

        # Service: generate shape trajectory
        self.create_service(
            GenerateShapeTrajectory,
            "/shape_trajectory/generate",
            self._generate_callback,
            callback_group=self.callback_group,
        )

        # Cache for home-position TCP orientation per arm (populated on first use)
        self._orientation_cache: dict[str, Quaternion] = {}

        self.get_logger().info("Shape Trajectory Node initialized")

    # ──────────────────────────────────────────────────────────────────────
    # Shape generators — return list of (x, y=0, z) tuples
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _generate_arc(cx: float, cz: float, radius: float,
                      start_deg: float, end_deg: float, n: int) -> list[tuple]:
        """Arc/circle in the y=0 (XZ) plane centred at (cx, cz)."""
        points = []
        start_rad = math.radians(start_deg)
        end_rad = math.radians(end_deg)
        for i in range(n):
            t = start_rad + (end_rad - start_rad) * i / max(n - 1, 1)
            x = cx + radius * math.cos(t)
            z = cz + radius * math.sin(t)
            points.append((x, 0.0, z))
        return points

    @staticmethod
    def _generate_line(x1: float, z1: float, x2: float, z2: float,
                       n: int) -> list[tuple]:
        """Straight line from (x1,z1) to (x2,z2) in y=0 plane."""
        points = []
        for i in range(n):
            t = i / max(n - 1, 1)
            x = x1 + (x2 - x1) * t
            z = z1 + (z2 - z1) * t
            points.append((x, 0.0, z))
        return points

    @staticmethod
    def _generate_square(corner_x: float, corner_z: float, side: float,
                         n: int) -> list[tuple]:
        """Square starting at corner going CW in XZ plane."""
        pts_per_side = max(n // 4, 2)
        points = []
        corners = [
            (corner_x, corner_z),
            (corner_x + side, corner_z),
            (corner_x + side, corner_z + side),
            (corner_x, corner_z + side),
        ]
        for i in range(4):
            x1, z1 = corners[i]
            x2, z2 = corners[(i + 1) % 4]
            for j in range(pts_per_side):
                t = j / max(pts_per_side - 1, 1)
                points.append((x1 + (x2 - x1) * t, 0.0, z1 + (z2 - z1) * t))
        return points

    @staticmethod
    def _generate_rectangle(corner_x: float, corner_z: float,
                            width: float, height: float, n: int) -> list[tuple]:
        """Rectangle starting at corner going CW in XZ plane."""
        perimeter = 2 * (width + height)
        points = []
        corners = [
            (corner_x, corner_z),
            (corner_x + width, corner_z),
            (corner_x + width, corner_z + height),
            (corner_x, corner_z + height),
        ]
        sides = [width, height, width, height]
        for i in range(4):
            pts_this_side = max(int(n * sides[i] / perimeter), 2)
            x1, z1 = corners[i]
            x2, z2 = corners[(i + 1) % 4]
            for j in range(pts_this_side):
                t = j / max(pts_this_side - 1, 1)
                points.append((x1 + (x2 - x1) * t, 0.0, z1 + (z2 - z1) * t))
        return points

    @staticmethod
    def _generate_triangle(corner_x: float, corner_z: float,
                           base: float, height: float, n: int) -> list[tuple]:
        """Isoceles triangle, bottom-left corner at (corner_x, corner_z)."""
        pts_per_side = max(n // 3, 2)
        corners = [
            (corner_x, corner_z),
            (corner_x + base, corner_z),
            (corner_x + base / 2.0, corner_z + height),
        ]
        points = []
        for i in range(3):
            x1, z1 = corners[i]
            x2, z2 = corners[(i + 1) % 3]
            for j in range(pts_per_side):
                t = j / max(pts_per_side - 1, 1)
                points.append((x1 + (x2 - x1) * t, 0.0, z1 + (z2 - z1) * t))
        return points

    @staticmethod
    def _generate_oval(cx: float, cz: float, rx: float, rz: float,
                       n: int) -> list[tuple]:
        """Ellipse in XZ plane centred at (cx, cz)."""
        points = []
        for i in range(n):
            t = 2.0 * math.pi * i / max(n - 1, 1)
            x = cx + rx * math.cos(t)
            z = cz + rz * math.sin(t)
            points.append((x, 0.0, z))
        return points

    @staticmethod
    def _generate_zigzag(x1: float, z1: float, length: float, zag_width: float, steps: int, n: int) -> list[tuple]:
        """Zigzag along X axis in XZ plane starting at (x1, z1)."""
        points = []
        corners = []
        for i in range(steps + 1):
            x_val = x1 + length * i / max(steps, 1)
            z_val = z1 + (zag_width if i % 2 != 0 else -zag_width)
            corners.append((x_val, 0.0, z_val))
            
        n_per = max(n // max(steps, 1), 2)
        for i in range(len(corners) - 1):
            cx1, cy1, cz1 = corners[i]
            cx2, cy2, cz2 = corners[i+1]
            for j in range(n_per):
                t = j / max(n_per - 1, 1)
                points.append((cx1 + (cx2 - cx1)*t, 0.0, cz1 + (cz2 - cz1)*t))
        return points

    @staticmethod
    def _generate_spiral(cx: float, cz: float, inner_radius: float, outer_radius: float, turns: float, n: int) -> list[tuple]:
        """Spiral in XZ plane centred at (cx,cz)."""
        points = []
        for i in range(n):
            t = i / max(n - 1, 1)
            r = inner_radius + (outer_radius - inner_radius) * t
            a = t * turns * 2.0 * math.pi
            x = cx + r * math.cos(a)
            z = cz + r * math.sin(a)
            points.append((x, 0.0, z))
        return points

    # ──────────────────────────────────────────────────────────────────────
    # Validation
    # ──────────────────────────────────────────────────────────────────────
    def _validate_points(self, points: list[tuple], arm: str) -> str | None:
        """Return error message if any point violates shared safety-zone rules."""
        return self.safety_store.validate_cartesian_points(arm, points)

    # ──────────────────────────────────────────────────────────────────────
    # Resolve real TCP orientation via FK
    # ──────────────────────────────────────────────────────────────────────
    def _resolve_orientation(self, arm: str) -> Quaternion:
        """Get the real TCP orientation at home position via compute_fk.

        Calls the MoveIt FK service with home joint positions and extracts
        the resulting end-effector orientation.  The result is cached so
        subsequent calls for the same arm are instant.
        """
        if arm in self._orientation_cache:
            return self._orientation_cache[arm]

        cfg = _ARM_CONFIG[arm]

        if not self._fk_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn(
                "compute_fk service not available — using fallback orientation"
            )
            return _FALLBACK_ORIENTATION

        fk_req = GetPositionFK.Request()
        fk_req.header = Header(frame_id="world")
        fk_req.fk_link_names = [cfg["ee_link"]]

        # Build a RobotState with home joint positions
        fk_req.robot_state = RobotState()
        fk_req.robot_state.joint_state = JointState()
        fk_req.robot_state.joint_state.name = cfg["joint_names"]
        fk_req.robot_state.joint_state.position = [
            float(p) for p in cfg["home_positions"]
        ]

        future = self._fk_client.call_async(fk_req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if future.result() is None:
            self.get_logger().warn("FK call returned None — using fallback orientation")
            return _FALLBACK_ORIENTATION

        fk_resp = future.result()
        if fk_resp.error_code.val != 1:  # SUCCESS = 1
            self.get_logger().warn(
                f"FK failed (code {fk_resp.error_code.val}) — using fallback orientation"
            )
            return _FALLBACK_ORIENTATION

        if not fk_resp.pose_stamped:
            self.get_logger().warn("FK returned no poses — using fallback orientation")
            return _FALLBACK_ORIENTATION

        orientation = fk_resp.pose_stamped[0].pose.orientation
        self._orientation_cache[arm] = orientation
        self.get_logger().info(
            f"Resolved {arm} arm TCP orientation via FK: "
            f"x={orientation.x:.4f} y={orientation.y:.4f} "
            f"z={orientation.z:.4f} w={orientation.w:.4f}"
        )
        return orientation

    # ──────────────────────────────────────────────────────────────────────
    # Build Cartesian poses from points
    # ──────────────────────────────────────────────────────────────────────
    def _build_poses(self, points: list[tuple], arm: str) -> list[Pose]:
        """Convert points to Pose messages using Frenet-Serret framing logic."""
        if len(points) < 2:
            return []

        # Default fallback to FK orientation if we only have 1 point or some logic fails
        orientation = self._resolve_orientation(arm)
        poses = []
        
        # We always assume the surface normal is [0, 1, 0] since shapes are in XZ plane (y=0)
        # Note: the old generator used surface normal = [0,0,1], but here the workspace is the Y=0 plane
        N = np.array([0.0, 1.0, 0.0])
        tool_z = N

        points_array = np.array(points)
        num_pts = len(points_array)
        tangents = np.zeros((num_pts, 3))

        for i in range(num_pts):
            if i == 0:
                raw = points_array[1] - points_array[0]
            elif i == num_pts - 1:
                raw = points_array[-1] - points_array[-2]
            else:
                raw = points_array[i + 1] - points_array[i - 1]

            norm = np.linalg.norm(raw)
            if norm < 1e-9:
                tangents[i] = tangents[i - 1] if i > 0 else np.array([1.0, 0.0, 0.0])
            else:
                tangents[i] = raw / norm

        for i, pos in enumerate(points):
            T = tangents[i]
            # Planar robot correction: tool_x points radially outward from shoulder X offset
            # (Assuming base offset logic from frenet_serret.py)
            dist_xy = math.hypot(pos[0], pos[1])
            if dist_xy > 1e-4:
                radial_x = pos[0] / dist_xy
                radial_y = pos[1] / dist_xy
            else:
                radial_x, radial_y = 1.0, 0.0
                
            tool_x = np.array([radial_x, radial_y, 0.0])
            tool_y = np.cross(tool_z, tool_x)
            
            n_tool_y = np.linalg.norm(tool_y)
            if n_tool_y > 1e-9:
                tool_y = tool_y / n_tool_y
            else:
                tool_y = np.array([0.0, 1.0, 0.0])
                
            rot_mat = np.column_stack([tool_x, tool_y, tool_z])
            rotation = R.from_matrix(rot_mat)
            q = rotation.as_quat()

            p = Pose()
            p.position = Point(x=pos[0], y=pos[1], z=pos[2])
            p.orientation = Quaternion(x=float(q[0]), y=float(q[1]), z=float(q[2]), w=float(q[3]))
            poses.append(p)

        return poses

    # ──────────────────────────────────────────────────────────────────────
    # Main service callback
    # ──────────────────────────────────────────────────────────────────────
    def _generate_callback(self, request, response):
        arm = request.arm.lower().strip()
        shape = request.shape.lower().strip()
        n = request.num_waypoints if request.num_waypoints > 0 else 50

        # ── Validate arm ──────────────────────────────────────────────────
        if arm not in _ARM_CONFIG:
            response.success = False
            response.message = f"Unknown arm '{arm}'. Use 'left' or 'right'."
            return response

        cfg = _ARM_CONFIG[arm]

        # ── Generate points ───────────────────────────────────────────────
        ref_x = request.ref_x
        ref_z = request.ref_z

        if shape == "arc":
            radius = request.param1
            arc_angle = request.param3 if request.param3 > 0 else 360.0
            start_deg = 0.0
            end_deg = arc_angle
            if radius <= 0:
                response.success = False
                response.message = "Arc radius must be > 0"
                return response
            points = self._generate_arc(ref_x, ref_z, radius, start_deg, end_deg, n)

        elif shape == "line":
            length = request.param1
            if length <= 0:
                response.success = False
                response.message = "Line length must be > 0"
                return response
            # Horizontal line starting at ref point
            points = self._generate_line(ref_x, ref_z, ref_x + length, ref_z, n)

        elif shape == "square":
            side = request.param1
            if side <= 0:
                response.success = False
                response.message = "Square side must be > 0"
                return response
            points = self._generate_square(ref_x, ref_z, side, n)

        elif shape == "rectangle":
            width = request.param1
            height = request.param2
            if width <= 0 or height <= 0:
                response.success = False
                response.message = "Rectangle width and height must be > 0"
                return response
            points = self._generate_rectangle(ref_x, ref_z, width, height, n)

        elif shape == "triangle":
            base = request.param1
            height = request.param2
            if base <= 0 or height <= 0:
                response.success = False
                response.message = "Triangle base and height must be > 0"
                return response
            points = self._generate_triangle(ref_x, ref_z, base, height, n)

        elif shape == "oval":
            rx = request.param1
            rz = request.param2
            if rx <= 0 or rz <= 0:
                response.success = False
                response.message = "Oval radii must be > 0"
                return response
            points = self._generate_oval(ref_x, ref_z, rx, rz, n)

        elif shape == "zigzag":
            length = request.param1
            zag_width = request.param2
            steps = int(request.param3) if request.param3 > 0 else 6
            if length <= 0 or zag_width <= 0:
                response.success = False
                response.message = "Zigzag length and width must be > 0"
                return response
            points = self._generate_zigzag(ref_x, ref_z, length, zag_width, steps, n)

        elif shape == "spiral":
            inner_radius = request.param1
            outer_radius = request.param2
            turns = request.param3 if request.param3 > 0 else 2.5
            if outer_radius <= 0 or inner_radius < 0:
                response.success = False
                response.message = "Spiral radii must be valid"
                return response
            points = self._generate_spiral(ref_x, ref_z, inner_radius, outer_radius, turns, n)

        else:
            response.success = False
            response.message = f"Unknown shape '{shape}'. Supported: arc, line, square, rectangle, triangle, oval, zigzag, spiral"
            return response

        self.get_logger().info(
            f"Generated {len(points)} waypoints for {shape} on {arm} arm"
        )

        # ── Validate reachability ─────────────────────────────────────────
        err = self._validate_points(points, arm)
        if err:
            response.success = False
            response.message = f"Out of reach: {err}"
            return response

        # ── Call MoveIt compute_cartesian_path ────────────────────────────
        if not self._cartesian_client.wait_for_service(timeout_sec=5.0):
            response.success = False
            response.message = "MoveIt compute_cartesian_path service not available (is move_group running?)"
            return response

        poses = self._build_poses(points, arm)

        cart_req = GetCartesianPath.Request()
        cart_req.header.frame_id = "world"
        cart_req.group_name = cfg["planning_group"]
        cart_req.link_name = cfg["ee_link"]
        cart_req.waypoints = poses
        cart_req.max_step = 0.005  # 5mm interpolation
        cart_req.avoid_collisions = True

        # Use is_diff=True so MoveIt uses its current known state
        # rather than us specifying exact joint positions
        cart_req.start_state = RobotState()
        cart_req.start_state.is_diff = True

        self.get_logger().info("Calling compute_cartesian_path …")
        future = self._cartesian_client.call_async(cart_req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=30.0)

        if future.result() is None:
            response.success = False
            response.message = "compute_cartesian_path call failed (no response)"
            return response

        cart_resp = future.result()
        fraction = cart_resp.fraction

        self.get_logger().info(f"Cartesian path fraction: {fraction:.2%}")

        if fraction < 0.90:
            response.success = False
            response.message = (
                f"MoveIt could only plan {fraction:.0%} of the path. "
                f"The shape may be partially unreachable. Adjust position or size."
            )
            return response

        joint_traj = cart_resp.solution.joint_trajectory
        if len(joint_traj.points) == 0:
            response.success = False
            response.message = "MoveIt returned an empty trajectory"
            return response

        # ── Inject into trajectory manager ────────────────────────────────
        if not self._inject_client.wait_for_service(timeout_sec=5.0):
            response.success = False
            response.message = "trajectory_manager inject_trajectory service not available"
            return response

        inject_req = InjectTrajectory.Request()
        inject_req.trajectory = joint_traj
        inject_req.description = f"{shape} shape ({arm} arm)"

        inject_future = self._inject_client.call_async(inject_req)
        rclpy.spin_until_future_complete(self, inject_future, timeout_sec=10.0)

        if inject_future.result() is None:
            response.success = False
            response.message = "inject_trajectory call failed (no response)"
            return response

        inject_resp = inject_future.result()
        if not inject_resp.success:
            response.success = False
            response.message = f"Injection failed: {inject_resp.message}"
            return response

        # ── Success ───────────────────────────────────────────────────────
        duration = 0.0
        if joint_traj.points:
            last = joint_traj.points[-1].time_from_start
            duration = last.sec + last.nanosec * 1e-9

        response.success = True
        response.waypoint_count = len(joint_traj.points)
        response.duration = duration
        response.message = (
            f"Generated {shape}: {len(joint_traj.points)} waypoints, "
            f"{duration:.2f}s, fraction={fraction:.0%}"
        )
        self.get_logger().info(f"✓ {response.message}")
        return response


def main(args=None):
    rclpy.init(args=args)
    node = ShapeTrajectoryNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
