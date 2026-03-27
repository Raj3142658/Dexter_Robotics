from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


HARDWARE_JOINT_ORDER_14 = [
    "j1l",
    "j2l",
    "j3l",
    "j4l",
    "j5l",
    "j6l",
    "gripper_l_servo",
    "j1r",
    "j2r",
    "j3r",
    "j4r",
    "j5r",
    "j6r",
    "gripper_r_servo",
]


PRISMATIC_GRIPPER_RANGE_M = 0.025  # Matches URDF prismatic travel (0.0=open, -0.025=closed).


@dataclass
class ConvertResult:
    payload: dict[str, Any]
    missing_joints: list[str]
    used_gripper_prismatic: bool


def _iso_utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        sec = float(value.get("sec", 0.0) or 0.0)
        nsec = float(value.get("nanosec", 0.0) or 0.0)
        return sec + nsec * 1e-9
    return 0.0


def _prismatic_to_servo_rad(value_m: float) -> float:
    rad = (float(value_m) / -PRISMATIC_GRIPPER_RANGE_M) * math.pi
    return max(0.0, min(math.pi, rad))


def _normalize_joint_name(raw: str) -> str:
    key = str(raw or "").strip().lower()
    aliases = {
        "left_gripper": "j7l1",
        "left_gripper_finger": "j7l1",
        "left_gripper_servo": "gripper_l_servo",
        "right_gripper": "j7r1",
        "right_gripper_finger": "j7r1",
        "right_gripper_servo": "gripper_r_servo",
    }
    return aliases.get(key, key)


def _build_index_maps(joint_names: Iterable[str]) -> tuple[dict[str, int], list[int], list[int]]:
    index_map: dict[str, int] = {}
    left_prismatic: list[int] = []
    right_prismatic: list[int] = []
    for idx, raw in enumerate(joint_names):
        name = _normalize_joint_name(raw)
        if name in {"j7l1", "j7l2"}:
            left_prismatic.append(idx)
            continue
        if name in {"j7r1", "j7r2"}:
            right_prismatic.append(idx)
            continue
        if name and name not in index_map:
            index_map[name] = idx
    return index_map, left_prismatic, right_prismatic


def _resolve_gripper_value(
    *,
    servo_name: str,
    index_map: dict[str, int],
    prismatic_indices: list[int],
    positions: list[float],
    default_value: float,
) -> tuple[float, bool]:
    if servo_name in index_map and index_map[servo_name] < len(positions):
        return float(positions[index_map[servo_name]]), False
    for idx in prismatic_indices:
        if idx < len(positions):
            return _prismatic_to_servo_rad(float(positions[idx])), True
    return float(default_value), False


def convert_joint_trajectory_yaml_to_execute14(
    source: dict[str, Any],
    *,
    job_id: str | None = None,
    trajectory_name: str | None = None,
    default_missing: float = 0.0,
) -> ConvertResult:
    joint_names = source.get("joint_names") if isinstance(source.get("joint_names"), list) else []
    joint_names = [str(j) for j in joint_names if str(j).strip()]
    points = source.get("points") if isinstance(source.get("points"), list) else []
    points = [p for p in points if isinstance(p, dict)]

    if not job_id:
        job_id = f"convert_{uuid.uuid4().hex[:12]}"

    name = str(trajectory_name or source.get("name") or source.get("trajectory_name") or "trajectory").strip()
    if not name:
        name = "trajectory"

    index_map, left_prismatic, right_prismatic = _build_index_maps(joint_names)
    missing: set[str] = set()
    used_gripper_prismatic = False

    out_points: list[dict[str, Any]] = []
    for point in points:
        raw_positions = point.get("positions") if isinstance(point.get("positions"), list) else []
        positions = [float(v) for v in raw_positions]
        t = _parse_time(point.get("time_from_start"))

        out_positions: list[float] = []
        for hw_name in HARDWARE_JOINT_ORDER_14:
            if hw_name == "gripper_l_servo":
                value, used = _resolve_gripper_value(
                    servo_name="gripper_l_servo",
                    index_map=index_map,
                    prismatic_indices=left_prismatic,
                    positions=positions,
                    default_value=default_missing,
                )
                used_gripper_prismatic = used_gripper_prismatic or used
                out_positions.append(round(float(value), 6))
                continue
            if hw_name == "gripper_r_servo":
                value, used = _resolve_gripper_value(
                    servo_name="gripper_r_servo",
                    index_map=index_map,
                    prismatic_indices=right_prismatic,
                    positions=positions,
                    default_value=default_missing,
                )
                used_gripper_prismatic = used_gripper_prismatic or used
                out_positions.append(round(float(value), 6))
                continue

            if hw_name in index_map and index_map[hw_name] < len(positions):
                out_positions.append(round(float(positions[index_map[hw_name]]), 6))
            else:
                missing.add(hw_name)
                out_positions.append(round(float(default_missing), 6))

        out_points.append(
            {
                "time_from_start_sec": round(max(0.0, float(t)), 6),
                "positions": out_positions,
            }
        )

    has_arm_joint = any(
        name in index_map for name in ("j1l", "j2l", "j3l", "j4l", "j5l", "j6l", "j1r", "j2r", "j3r", "j4r", "j5r", "j6r")
    )
    ready = bool(out_points) and has_arm_joint

    payload: dict[str, Any] = {
        "schema_version": "dexter.trajectory.execute14.v1",
        "kind": "dexter_trajectory_execute_hw14",
        "trajectory_name": name,
        "job_id": job_id,
        "generated_at": _iso_utc_now(),
        "hardware_joint_order": HARDWARE_JOINT_ORDER_14,
        "point_count": len(out_points),
        "plan_waypoint_count": len(out_points),
        "ready_for_hardware": ready,
        "note": "Converted from JointTrajectory-style YAML.",
        "points": out_points,
        "conversion": {
            "source_joint_names": joint_names,
            "missing_joints_filled": sorted(missing),
            "used_prismatic_gripper": bool(used_gripper_prismatic),
        },
    }

    return ConvertResult(payload=payload, missing_joints=sorted(missing), used_gripper_prismatic=used_gripper_prismatic)


def load_joint_trajectory_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_execute14_yaml(path: Path, payload: dict[str, Any]) -> None:
    body = "---\n" + yaml.safe_dump(payload, sort_keys=False)
    path.write_text(body, encoding="utf-8")


def convert_joint_trajectory_file(
    input_path: Path,
    output_path: Path,
    *,
    job_id: str | None = None,
    trajectory_name: str | None = None,
    default_missing: float = 0.0,
) -> ConvertResult:
    source = load_joint_trajectory_yaml(input_path)
    result = convert_joint_trajectory_yaml_to_execute14(
        source,
        job_id=job_id,
        trajectory_name=trajectory_name,
        default_missing=default_missing,
    )
    write_execute14_yaml(output_path, result.payload)
    return result

