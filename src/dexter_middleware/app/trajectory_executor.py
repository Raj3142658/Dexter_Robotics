import asyncio
import json
import os
import socket
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml


class ExecuteArtifactError(ValueError):
    """Raised when execute artifact payload is invalid for runtime execution."""


@dataclass
class ExecutePoint:
    time_from_start_sec: float
    positions: list[float]


@dataclass
class LoadedExecuteArtifact:
    file_path: str
    schema_version: str
    job_id: str
    trajectory_name: str
    hardware_joint_order: list[str]
    points: list[ExecutePoint]
    total_duration_sec: float


DEFAULT_JOINT_MIN_14 = [
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    0.0,
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    -1.57,
    0.0,
]

DEFAULT_JOINT_MAX_14 = [
    1.57,
    1.57,
    1.57,
    1.57,
    1.57,
    1.57,
    6.28318,
    1.57,
    1.57,
    1.57,
    1.57,
    1.57,
    1.57,
    3.14159,
]


class _BaseSender:
    def send_positions(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def send_stop(self, payload: dict[str, Any]) -> None:
        return

    def close(self) -> None:
        return


class _UdpJsonSender(_BaseSender):
    def __init__(self, host: str, port: int, timeout_sec: float) -> None:
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(timeout_sec)
        self._require_ack = os.getenv("DEXTER_TRAJECTORY_EXECUTE_UDP_REQUIRE_ACK", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._retries = max(0, int(_coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_UDP_RETRIES", "0"), 0.0)))

    def _try_recv_ack(self) -> dict[str, Any] | None:
        try:
            raw, _ = self._sock.recvfrom(4096)
        except socket.timeout:
            if self._require_ack:
                raise RuntimeError("UDP ack timeout from hardware endpoint")
            return None
        except Exception as exc:
            if self._require_ack:
                raise RuntimeError(f"UDP ack receive error: {exc}") from exc
            return None

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            if self._require_ack:
                raise RuntimeError("UDP ack payload is not valid JSON")
            return None

        if isinstance(data, dict) and str(data.get("status") or "").lower() in {"error", "failed", "fail"}:
            detail = str(data.get("message") or "hardware endpoint reported error")
            raise RuntimeError(detail)
        return data if isinstance(data, dict) else None

    def send_positions(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        last_exc: Exception | None = None
        expected_seq = payload.get("seq")
        for attempt in range(self._retries + 1):
            try:
                self._sock.sendto(body, self._addr)
                ack = self._try_recv_ack()
                if isinstance(ack, dict) and expected_seq is not None and "seq" in ack:
                    try:
                        ack_seq = int(ack.get("seq"))
                        exp_seq = int(expected_seq)
                        if ack_seq != exp_seq:
                            raise RuntimeError(f"stale ack sequence: expected {exp_seq}, got {ack_seq}")
                    except ValueError as exc:
                        raise RuntimeError("invalid ack seq value") from exc
                return ack
            except Exception as exc:
                last_exc = exc
                if attempt >= self._retries:
                    raise
                time.sleep(0.005)
        if last_exc is not None:
            raise RuntimeError(str(last_exc))
        return None

    def send_stop(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with suppress(Exception):
            self._sock.sendto(body, self._addr)
            self._try_recv_ack()

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class _RosTopicSender(_BaseSender):
    def __init__(self) -> None:
        import rclpy  # type: ignore
        from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy  # type: ignore
        from std_msgs.msg import Float64MultiArray  # type: ignore

        self._rclpy = rclpy
        self._Float64MultiArray = Float64MultiArray
        self._owned_context = not bool(rclpy.ok())
        if self._owned_context:
            rclpy.init(args=None)

        self._node = rclpy.create_node("dexter_trajectory_execute_sender")

        depth = max(1, int(_coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_ROS_QUEUE_DEPTH", "10"), 10)))
        qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=depth,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
        )

        topic = os.getenv("DEXTER_TRAJECTORY_EXECUTE_ROS_TOPIC", "/esp32/joint_commands").strip() or "/esp32/joint_commands"
        self._pub = self._node.create_publisher(Float64MultiArray, topic, qos)

        self._enable_health = _truthy_env("DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_CHECK", True)
        self._health_topic = os.getenv("DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_TOPIC", "/esp32/link_health").strip() or "/esp32/link_health"
        self._health_timeout_sec = max(0.05, _coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_ROS_HEALTH_TIMEOUT_SEC", "1.0"), 1.0))
        self._health_required = _truthy_env("DEXTER_TRAJECTORY_EXECUTE_ROS_REQUIRE_HEALTH", True)
        self._health_last_seen = 0.0
        self._health_last_data: list[float] = []
        self._health_sub = None

        if self._enable_health:
            def _on_health(msg: Any) -> None:
                data = getattr(msg, "data", [])
                self._health_last_data = [float(x) for x in data] if isinstance(data, (list, tuple)) else []
                self._health_last_seen = time.monotonic()

            self._health_sub = self._node.create_subscription(Float64MultiArray, self._health_topic, _on_health, qos)

    def _spin_once(self) -> None:
        self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def _validate_health(self) -> None:
        if not self._enable_health:
            return

        age = time.monotonic() - self._health_last_seen if self._health_last_seen > 0.0 else float("inf")
        if self._health_required and age > self._health_timeout_sec:
            raise RuntimeError(f"ROS link health is stale (age={age:.3f}s)")

        # Firmware publishes wifi_connected at index 10 when available.
        if len(self._health_last_data) >= 11:
            wifi_connected = float(self._health_last_data[10])
            if wifi_connected < 0.5:
                raise RuntimeError("ESP link health reports WiFi disconnected")

    def send_positions(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self._spin_once()
        self._validate_health()

        msg = self._Float64MultiArray()
        positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        seq = int(payload.get("seq", 0) or 0)
        msg.data = [float(v) for v in positions] + [float(seq)]
        self._pub.publish(msg)

        return {
            "status": "published",
            "seq": seq,
            "transport": "ros2_topic",
            "topic": self._pub.topic_name,
        }

    def send_stop(self, payload: dict[str, Any]) -> None:
        # Holding current command stream is enough for firmware-side freeze behavior on stale input.
        _ = payload
        self._spin_once()

    def close(self) -> None:
        try:
            if self._health_sub is not None:
                self._node.destroy_subscription(self._health_sub)
        except Exception:
            pass
        try:
            self._node.destroy_publisher(self._pub)
        except Exception:
            pass
        try:
            self._node.destroy_node()
        except Exception:
            pass
        if self._owned_context:
            with suppress(Exception):
                self._rclpy.shutdown()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _artifact_joint_limits(artifact: LoadedExecuteArtifact) -> tuple[list[float], list[float]]:
    count = len(artifact.hardware_joint_order)
    if count == len(DEFAULT_JOINT_MIN_14):
        return list(DEFAULT_JOINT_MIN_14), list(DEFAULT_JOINT_MAX_14)
    # Conservative generic fallback if a future schema changes joint count.
    return ([-3.2] * count, [3.2] * count)


def _validate_joint_ranges(artifact: LoadedExecuteArtifact) -> None:
    mins, maxs = _artifact_joint_limits(artifact)
    margin = max(0.0, _coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_LIMIT_MARGIN_RAD", "0.05"), 0.05))
    for pidx, point in enumerate(artifact.points):
        for jidx, val in enumerate(point.positions):
            lo = mins[jidx] - margin
            hi = maxs[jidx] + margin
            if float(val) < lo or float(val) > hi:
                raise ExecuteArtifactError(
                    f"point {pidx} joint {jidx} out of limits: {val:.6f} not in [{lo:.6f}, {hi:.6f}]"
                )


def _validate_step_deltas(artifact: LoadedExecuteArtifact) -> None:
    max_step = max(0.01, _coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_MAX_STEP_RAD", "0.6"), 0.6))
    for pidx in range(1, len(artifact.points)):
        prev = artifact.points[pidx - 1].positions
        curr = artifact.points[pidx].positions
        for jidx, value in enumerate(curr):
            if abs(float(value) - float(prev[jidx])) > max_step:
                raise ExecuteArtifactError(
                    f"point delta too large at point {pidx}, joint {jidx}: {abs(float(value)-float(prev[jidx])):.6f} rad"
                )


def _normalize_timed_points(raw_points: list[dict[str, Any]], fallback_duration_sec: float) -> list[ExecutePoint]:
    normalized: list[ExecutePoint] = []
    for point in raw_points:
        positions = point.get("positions") if isinstance(point.get("positions"), list) else []
        if not positions:
            continue
        time_raw = point.get("time_from_start")
        if time_raw is None:
            time_raw = point.get("time_from_start_sec")
        t = _coerce_float(time_raw, 0.0)
        normalized.append(
            ExecutePoint(
                time_from_start_sec=max(0.0, t),
                positions=[_coerce_float(v, 0.0) for v in positions],
            )
        )

    if not normalized:
        raise ExecuteArtifactError("execute artifact has no usable points")

    # Enforce non-decreasing time values.
    for idx in range(1, len(normalized)):
        if normalized[idx].time_from_start_sec < normalized[idx - 1].time_from_start_sec:
            normalized[idx].time_from_start_sec = normalized[idx - 1].time_from_start_sec

    total_duration = normalized[-1].time_from_start_sec
    if total_duration <= 0.0 and len(normalized) > 1:
        # Fallback for artifacts where upstream did not provide point timing.
        duration = max(0.05, float(fallback_duration_sec))
        step = duration / float(len(normalized) - 1)
        for idx, point in enumerate(normalized):
            point.time_from_start_sec = round(step * idx, 6)

    return normalized


def load_execute_artifact(file_path: Path, fallback_duration_sec: float) -> LoadedExecuteArtifact:
    if not file_path.exists():
        raise ExecuteArtifactError(f"execute artifact not found: {file_path}")

    try:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ExecuteArtifactError(f"failed to parse execute artifact YAML: {exc}") from exc

    if not isinstance(payload, dict):
        raise ExecuteArtifactError("execute artifact must be a YAML object")

    schema_version = str(payload.get("schema_version") or "")
    if not schema_version:
        raise ExecuteArtifactError("execute artifact missing schema_version")

    job_id = str(payload.get("job_id") or "")
    trajectory_name = str(payload.get("trajectory_name") or "")
    joint_order = payload.get("hardware_joint_order") if isinstance(payload.get("hardware_joint_order"), list) else []
    joint_order = [str(j) for j in joint_order if str(j).strip()]
    if not joint_order:
        raise ExecuteArtifactError("execute artifact missing hardware_joint_order")

    raw_points = payload.get("points") if isinstance(payload.get("points"), list) else []
    points = _normalize_timed_points([p for p in raw_points if isinstance(p, dict)], fallback_duration_sec=fallback_duration_sec)

    expected_joints = len(joint_order)
    for idx, point in enumerate(points):
        if len(point.positions) != expected_joints:
            raise ExecuteArtifactError(
                f"point {idx} has {len(point.positions)} positions, expected {expected_joints}"
            )

    total_duration_sec = max(0.0, points[-1].time_from_start_sec)
    artifact = LoadedExecuteArtifact(
        file_path=str(file_path),
        schema_version=schema_version,
        job_id=job_id,
        trajectory_name=trajectory_name,
        hardware_joint_order=joint_order,
        points=points,
        total_duration_sec=total_duration_sec,
    )
    _validate_joint_ranges(artifact)
    _validate_step_deltas(artifact)
    return artifact


def _interpolate_positions(points: list[ExecutePoint], t: float) -> list[float]:
    if t <= points[0].time_from_start_sec:
        return list(points[0].positions)
    if t >= points[-1].time_from_start_sec:
        return list(points[-1].positions)

    for idx in range(1, len(points)):
        right = points[idx]
        left = points[idx - 1]
        if t > right.time_from_start_sec:
            continue

        span = max(1e-9, right.time_from_start_sec - left.time_from_start_sec)
        alpha = (t - left.time_from_start_sec) / span
        return [
            float(left.positions[j]) + (float(right.positions[j]) - float(left.positions[j])) * alpha
            for j in range(len(left.positions))
        ]

    return list(points[-1].positions)


def _build_sender() -> _BaseSender:
    mode = os.getenv("DEXTER_TRAJECTORY_EXECUTE_TRANSPORT", "dry_run").strip().lower()
    if mode in {"", "dry_run", "none", "noop"}:
        return _BaseSender()
    if mode == "udp_json":
        host = os.getenv("DEXTER_TRAJECTORY_EXECUTE_UDP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = int(_coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_UDP_PORT", "5005"), 5005))
        timeout_sec = max(0.01, _coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_UDP_TIMEOUT_SEC", "0.1"), 0.1))
        return _UdpJsonSender(host=host, port=port, timeout_sec=timeout_sec)
    if mode == "ros2_topic":
        return _RosTopicSender()

    raise ExecuteArtifactError(
        "Unsupported DEXTER_TRAJECTORY_EXECUTE_TRANSPORT; expected dry_run, udp_json, or ros2_topic"
    )


async def run_loaded_execute_artifact(
    artifact: LoadedExecuteArtifact,
    *,
    pause_checker: Callable[[], bool],
    on_progress: Callable[[float], Awaitable[None]],
) -> dict[str, Any]:
    hz = max(5.0, _coerce_float(os.getenv("DEXTER_TRAJECTORY_EXECUTE_HZ", "50"), 50.0))
    period = 1.0 / hz
    emit_stop = _truthy_env("DEXTER_TRAJECTORY_EXECUTE_EMIT_STOP", True)

    sender = _build_sender()
    started = time.monotonic()
    loop_count = 0
    ack_count = 0
    last_ack: dict[str, Any] | None = None
    stop_reason = "completed"
    sequence_id = 0

    try:
        while True:
            while pause_checker():
                await asyncio.sleep(0.05)

            elapsed = time.monotonic() - started
            clamped = min(elapsed, artifact.total_duration_sec)
            positions = _interpolate_positions(artifact.points, clamped)

            ack = sender.send_positions(
                {
                    "cmd": "trajectory_waypoint",
                    "job_id": artifact.job_id,
                    "trajectory_name": artifact.trajectory_name,
                    "schema_version": artifact.schema_version,
                    "seq": sequence_id,
                    "time_from_start_sec": round(clamped, 6),
                    "joint_names": artifact.hardware_joint_order,
                    "positions": [round(float(v), 6) for v in positions],
                }
            )
            if isinstance(ack, dict):
                ack_count += 1
                last_ack = ack
            sequence_id += 1

            progress = 1.0 if artifact.total_duration_sec <= 0 else min(1.0, clamped / artifact.total_duration_sec)
            await on_progress(progress)

            if clamped >= artifact.total_duration_sec:
                break

            loop_count += 1
            next_tick = started + loop_count * period
            sleep_for = max(0.0, next_tick - time.monotonic())
            await asyncio.sleep(sleep_for)

        return {
            "duration_sec": round(max(0.0, time.monotonic() - started), 6),
            "point_count": len(artifact.points),
            "transport": os.getenv("DEXTER_TRAJECTORY_EXECUTE_TRANSPORT", "dry_run").strip().lower() or "dry_run",
            "ack_count": ack_count,
            "last_ack": last_ack,
        }
    except asyncio.CancelledError:
        stop_reason = "cancelled"
        raise
    except Exception:
        stop_reason = "failed"
        raise
    finally:
        if emit_stop:
            sender.send_stop(
                {
                    "cmd": "trajectory_stop",
                    "job_id": artifact.job_id,
                    "trajectory_name": artifact.trajectory_name,
                    "reason": stop_reason,
                    "seq": sequence_id,
                }
            )
        sender.close()
