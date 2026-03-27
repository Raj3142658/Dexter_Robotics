#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dexter_middleware.app.trajectory_convert import convert_joint_trajectory_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert JointTrajectory YAML to execute14 format.")
    parser.add_argument("input", type=Path, help="Path to JointTrajectory-style YAML")
    parser.add_argument("output", type=Path, help="Path to write execute14 YAML")
    parser.add_argument("--job-id", dest="job_id", default=None, help="Override job_id")
    parser.add_argument("--name", dest="name", default=None, help="Override trajectory_name")
    parser.add_argument("--default-missing", dest="default_missing", type=float, default=0.0,
                        help="Default value for missing joints (rad)")
    args = parser.parse_args()

    result = convert_joint_trajectory_file(
        args.input,
        args.output,
        job_id=args.job_id,
        trajectory_name=args.name,
        default_missing=args.default_missing,
    )
    missing = ", ".join(result.missing_joints) if result.missing_joints else "none"
    print(f"[OK] Wrote execute14: {args.output}")
    print(f"[INFO] Missing joints filled: {missing}")
    print(f"[INFO] Used prismatic gripper: {result.used_gripper_prismatic}")


if __name__ == "__main__":
    main()
