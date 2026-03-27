"""Shared safety-zone and trajectory validation utilities.

This module centralizes Cartesian safety bounds and generic trajectory quality
checks so both teach-repeat and shape-generated flows use a single source.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

import yaml


class SafetyZoneStore:
    """Loads arm safety-zone definitions and validates Cartesian waypoints."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._zones: dict[str, dict[str, Any]] = {}
        self._defaults: dict[str, Any] = {
            "reach_soft_ratio": 0.95,
            "min_waypoint_dt_sec": 0.01,
        }

    def load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Safety config not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        root = data.get("safety_zones", {})
        defaults = root.get("defaults", {})
        if isinstance(defaults, dict):
            self._defaults.update(defaults)

        zones: dict[str, dict[str, Any]] = {}
        for arm in ("left", "right"):
            cfg = root.get(arm)
            if isinstance(cfg, dict):
                zones[arm] = cfg

        if not zones:
            raise ValueError("No arm safety zones found in safety config")

        self._zones = zones

    def get_zone(self, arm: str) -> dict[str, Any]:
        arm_key = arm.lower().strip()
        if arm_key not in self._zones:
            raise KeyError(f"Unknown safety-zone arm '{arm}'")
        return self._zones[arm_key]

    def min_waypoint_dt_sec(self) -> float:
        value = self._defaults.get("min_waypoint_dt_sec", 0.01)
        return float(value) if value is not None else 0.01

    def validate_cartesian_points(self, arm: str, points: list[tuple[float, float, float]]) -> Optional[str]:
        """Return first validation error string, or None when all points are valid."""
        zone = self.get_zone(arm)
        x_lo, x_hi = _tuple2(zone.get("x_range"))
        y_lo, y_hi = _tuple2(zone.get("y_range"), default=(-1.0, 1.0))
        z_lo, z_hi = _tuple2(zone.get("z_range"))
        sx, sy, sz = _tuple3(zone.get("shoulder"))
        reach_m = float(zone.get("reach_m"))
        ratio = float(zone.get("reach_soft_ratio", self._defaults.get("reach_soft_ratio", 0.95)))

        for idx, (px, py, pz) in enumerate(points):
            if px < x_lo or px > x_hi:
                return f"Waypoint {idx}: x={px:.3f} out of range [{x_lo}, {x_hi}]"
            if py < y_lo or py > y_hi:
                return f"Waypoint {idx}: y={py:.3f} out of range [{y_lo}, {y_hi}]"
            if pz < z_lo or pz > z_hi:
                return f"Waypoint {idx}: z={pz:.3f} out of range [{z_lo}, {z_hi}]"

            dist = math.sqrt((px - sx) ** 2 + (py - sy) ** 2 + (pz - sz) ** 2)
            if dist > reach_m * ratio:
                return (
                    f"Waypoint {idx}: distance {dist:.3f}m from shoulder exceeds "
                    f"{ratio * 100:.1f}% of reach ({reach_m:.3f}m)"
                )

        return None


def validate_joint_trajectory(trajectory, min_dt_sec: float) -> list[str]:
    """Validate generic trajectory quality checks shared by teach/shape flows."""
    errors: list[str] = []

    points = getattr(trajectory, "points", None)
    joint_names = getattr(trajectory, "joint_names", None)

    if not points:
        return ["Trajectory has no waypoints"]
    if not joint_names:
        errors.append("Trajectory has no joint names")
        return errors

    expected_len = len(joint_names)
    prev_t = -1.0

    for idx, point in enumerate(points):
        positions = list(getattr(point, "positions", []))
        if len(positions) != expected_len:
            errors.append(
                f"Point {idx}: position count {len(positions)} does not match joint count {expected_len}"
            )

        for p_idx, value in enumerate(positions):
            if not math.isfinite(float(value)):
                errors.append(f"Point {idx}: non-finite position at joint index {p_idx}")

        t = float(point.time_from_start.sec) + float(point.time_from_start.nanosec) * 1e-9
        if idx == 0 and abs(t) > 1e-6:
            errors.append(f"Point 0: time_from_start should be 0.0, got {t:.6f}")

        if idx > 0:
            dt = t - prev_t
            if dt <= 0:
                errors.append(f"Point {idx}: non-increasing time_from_start (dt={dt:.6f})")
            elif dt < min_dt_sec:
                errors.append(
                    f"Point {idx}: waypoint dt={dt:.6f}s below minimum {min_dt_sec:.6f}s"
                )

        prev_t = t

    return errors


def _tuple2(value: Any, default: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (float(value[0]), float(value[1]))
    return default


def _tuple3(value: Any) -> tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    raise ValueError("Invalid shoulder configuration in safety zone")
