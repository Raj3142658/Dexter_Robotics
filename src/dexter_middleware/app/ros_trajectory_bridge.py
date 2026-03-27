from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Type
import uuid


class RosTrajectoryBridgeError(RuntimeError):
    pass


@dataclass
class RosServiceCallResult:
    success: bool
    message: str
    payload: Any


class RosTrajectoryBridge:
    """Lightweight ROS2 service client for Dexter trajectory helpers."""

    def __init__(self, *, node_name: str = "dexter_ros_trajectory_bridge") -> None:
        try:
            import rclpy  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on ROS env
            raise RosTrajectoryBridgeError(
                "rclpy is not available. Source the ROS workspace before using ROS trajectory services."
            ) from exc

        self._rclpy = rclpy
        self._owned_context = not bool(rclpy.ok())
        if self._owned_context:
            rclpy.init(args=None)

        unique_name = f"{node_name}_{uuid.uuid4().hex[:6]}"
        self._node = rclpy.create_node(unique_name)

    def close(self) -> None:
        try:
            self._node.destroy_node()
        except Exception:
            pass
        if self._owned_context:
            try:
                self._rclpy.shutdown()
            except Exception:
                pass

    def _call_service(
        self,
        *,
        srv_type: Type[Any],
        srv_name: str,
        request: Any,
        timeout_sec: float,
        success_predicate: Callable[[Any], bool] | None = None,
        message_attr: str = "message",
    ) -> RosServiceCallResult:
        client = self._node.create_client(srv_type, srv_name)
        if not client.wait_for_service(timeout_sec=timeout_sec):
            raise RosTrajectoryBridgeError(
                f"ROS service {srv_name} not available. Start dexter_arm_trajectory/trajectory_system.launch.py."
            )

        future = client.call_async(request)
        self._rclpy.spin_until_future_complete(self._node, future, timeout_sec=timeout_sec)
        if not future.done():
            raise RosTrajectoryBridgeError(f"ROS service {srv_name} timed out after {timeout_sec:.1f}s")

        result = future.result()
        if result is None:
            raise RosTrajectoryBridgeError(f"ROS service {srv_name} returned no response")

        success = True
        if success_predicate is not None:
            try:
                success = bool(success_predicate(result))
            except Exception:
                success = False

        message = ""
        if hasattr(result, message_attr):
            try:
                message = str(getattr(result, message_attr))
            except Exception:
                message = ""

        return RosServiceCallResult(success=success, message=message, payload=result)

    def generate_shape(
        self,
        *,
        arm: str,
        shape: str,
        param1: float,
        param2: float,
        param3: float,
        ref_x: float,
        ref_z: float,
        num_waypoints: int,
        timeout_sec: float = 15.0,
    ) -> RosServiceCallResult:
        from dexter_arm_trajectory_msgs.srv import GenerateShapeTrajectory  # type: ignore

        req = GenerateShapeTrajectory.Request()
        req.arm = arm
        req.shape = shape
        req.param1 = float(param1)
        req.param2 = float(param2)
        req.param3 = float(param3)
        req.ref_x = float(ref_x)
        req.ref_z = float(ref_z)
        req.num_waypoints = int(num_waypoints)

        return self._call_service(
            srv_type=GenerateShapeTrajectory,
            srv_name="/shape_trajectory/generate",
            request=req,
            timeout_sec=timeout_sec,
            success_predicate=lambda r: bool(getattr(r, "success", False)),
        )

    def capture_segment(self, *, timeout_sec: float = 8.0) -> RosServiceCallResult:
        from dexter_arm_trajectory_msgs.srv import CaptureSegment  # type: ignore

        req = CaptureSegment.Request()
        return self._call_service(
            srv_type=CaptureSegment,
            srv_name="/trajectory_manager/capture_segment",
            request=req,
            timeout_sec=timeout_sec,
            success_predicate=lambda r: bool(getattr(r, "success", False)),
        )

    def compile_trajectory(self, *, timeout_sec: float = 15.0) -> RosServiceCallResult:
        from dexter_arm_trajectory_msgs.srv import CompileTrajectory  # type: ignore

        req = CompileTrajectory.Request()
        return self._call_service(
            srv_type=CompileTrajectory,
            srv_name="/trajectory_manager/compile",
            request=req,
            timeout_sec=timeout_sec,
            success_predicate=lambda r: bool(getattr(r, "success", False)),
        )

    def save_trajectory(
        self,
        *,
        filename: str,
        description: str,
        timeout_sec: float = 12.0,
    ) -> RosServiceCallResult:
        from dexter_arm_trajectory_msgs.srv import SaveTrajectory  # type: ignore

        req = SaveTrajectory.Request()
        req.filename = filename
        req.description = description

        return self._call_service(
            srv_type=SaveTrajectory,
            srv_name="/trajectory_manager/save",
            request=req,
            timeout_sec=timeout_sec,
            success_predicate=lambda r: bool(getattr(r, "success", False)),
        )

    def clear_buffer(self, *, timeout_sec: float = 6.0) -> RosServiceCallResult:
        from std_srvs.srv import Trigger  # type: ignore

        req = Trigger.Request()
        return self._call_service(
            srv_type=Trigger,
            srv_name="/trajectory_manager/clear_buffer",
            request=req,
            timeout_sec=timeout_sec,
            success_predicate=lambda r: bool(getattr(r, "success", False)),
        )
