## Unified Trajectory Contract (execute14)

This workspace standardizes **runtime execution** on a single artifact:
`dexter.trajectory.execute14.v1`. It is the **hardware-facing** format used
by the middleware executor and matches the ESP32 firmware’s 14‑joint payload.

### Why execute14?
- The firmware consumes **exactly 14 joint targets** per frame.
- The middleware executor (`trajectory_executor.py`) requires a fixed 14‑joint order.
- This removes ambiguity across Shape, Teach, and Execute Saved workflows.

### Fixed Joint Order (14)
```
[
  "j1l","j2l","j3l","j4l","j5l","j6l","gripper_l_servo",
  "j1r","j2r","j3r","j4r","j5r","j6r","gripper_r_servo"
]
```

### execute14 Schema (minimum required)
```yaml
schema_version: dexter.trajectory.execute14.v1
kind: dexter_trajectory_execute_hw14
trajectory_name: <string>
job_id: <string>
generated_at: <UTC ISO8601>
hardware_joint_order: [14 joint names above]
point_count: <int>
ready_for_hardware: <bool>
points:
  - time_from_start_sec: <float>
    positions: [14 floats]
```

### Mapping Rules from JointTrajectory YAML
Input YAML is expected to follow the old **JointTrajectory-style** format:
```
joint_names: [...]
points:
  - positions: [...]
    velocities: [...]   # optional
    accelerations: [...] # optional
    time_from_start: <float seconds>
```

**Conversion rules:**
1. **Arm joints** map directly by name (`j1l..j6l`, `j1r..j6r`).
2. **Grippers**:
   - If input provides `gripper_l_servo` / `gripper_r_servo` (revolute rad), pass through.
   - If input provides prismatic grippers (`j7l1`,`j7l2`,`j7r1`,`j7r2`), convert using:
     ```
     servo_rad = (prismatic_m / -0.022) * pi
     clamp to [0, pi]
     ```
3. **Missing joints** are filled with defaults (0.0 rad) and recorded in metadata.
4. **Timing** uses `time_from_start` (seconds). If absent, times are inferred.

### Notes & Safety
- **execute14 is NOT per‑arm**. If you only have one arm’s joints,
  the other arm joints must still be populated (usually hold‑position or zero).
- The current converter defaults missing joints to `0.0`, which can
  move unused joints. A safer policy is to fill from live state at runtime.

