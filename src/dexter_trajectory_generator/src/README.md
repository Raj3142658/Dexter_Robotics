# DEXTER Shape Trajectory Generator

A ROS2 Jazzy package that generates industrial-grade shape trajectories
for the Dexter dual-arm robot. The output YAML matches the teach-and-repeat
format exactly.

---

## Pipeline

```
shape_config.yaml
       │
       ▼
ShapeGenerator          (parametric 3-D position waypoints)
       │
       ▼
FrenetSerretFrames      (correct end-effector orientation at every point)
       │  tool_z = -surface_normal (tool points into workpiece)
       │  tool_x = path tangent    (travel direction)
       │  tool_y = binormal        (lateral)
       ▼
geometry_msgs/Pose[]    (position + quaternion for each waypoint)
       │
       ▼
MoveIt2 computeCartesianPath()   ← IK solved here, joint continuity kept
       │
       ▼
Time Parameterization (TOTG or ruckig)   ← velocities + accelerations filled
       │
       ▼
output_trajectory.yaml  (same format as teach-and-repeat)
```

---

## Install

```bash
cd ~/ros2_ws/src
# copy or clone this package here
cd ~/ros2_ws
colcon build --packages-select dexter_trajectory_generator
source install/setup.bash
```

---

## Quick Start

```bash
# Edit the config file
nano ~/ros2_ws/src/dexter_trajectory_generator/config/shape_config.yaml

# Run (MoveIt2 + Gazebo must already be running)
ros2 run dexter_trajectory_generator trajectory_node \
    --ros-args \
    -p config_file:=$HOME/ros2_ws/src/dexter_trajectory_generator/config/shape_config.yaml \
    -p output_file:=$HOME/my_circle_trajectory.yaml \
    -p description:="Circle 80mm radius - left arm - table surface" \
    -p max_velocity_scaling:=0.3 \
    -p max_acceleration_scaling:=0.1 \
    -p time_param_method:=totg
```

---

## Config Reference

```yaml
arm: left                        # 'left' | 'right'

surface:
  normal: [0.0, 0.0, 1.0]       # surface normal (tool points opposite)
  tool_tilt_deg: 0.0             # forward tilt in travel direction

reference_point:                 # world frame, meters
  x: -0.250                      # For circle/rect/arc/spiral: CENTER
  y:  0.000                      # For line/zigzag: START POINT
  z:  0.200

shape:
  type: circle                   # circle | line | rectangle | arc | zigzag | spiral
  radius: 0.08
  n_points: 100
```

### Shape Parameters

| Shape       | Required keys                                          |
|-------------|--------------------------------------------------------|
| `circle`    | `radius`                                               |
| `line`      | `length`, `direction_u`, `direction_v`                 |
| `rectangle` | `width`, `height`                                      |
| `arc`       | `radius`, `start_angle_deg`, `end_angle_deg`           |
| `zigzag`    | `length`, `zag_width`, `steps`                         |
| `spiral`    | `inner_radius`, `outer_radius`, `turns`                |

All shapes accept `n_points` (waypoint density, default ~80–120).

---

## Surface Normals

| Work surface       | Normal          | Use case                        |
|--------------------|-----------------|---------------------------------|
| Horizontal table   | `[0, 0, 1]`     | Flat welding, dispensing        |
| Vertical wall      | `[0, -1, 0]`    | Wall welding, painting          |
| Side wall          | `[1, 0, 0]`     | Side-facing surfaces            |
| 45° inclined       | `[0, -0.707, 0.707]` | Inclined trays, angled seams |

---

## Workspace Limits (from URDF)

| Arm   | Shoulder (world)      | Effective reach |
|-------|-----------------------|-----------------|
| Left  | (-0.185, 0, 0.4755)   | ~0.390 m        |
| Right | ( 0.185, 0, 0.4755)   | ~0.390 m        |

Use the **DEXTER Workspace Analyzer** HTML tool to visually validate your
reference point and shape dimensions before running this node.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Fraction < 100% | Shape partially out of reach — reduce size or move reference point |
| `jump_threshold` errors | Set `jump_threshold: 3.0` (allows some joint jumps) |
| Slow/jerky trajectory | Reduce `max_velocity_scaling`, increase `n_points` |
| Wrist singularity | Move reference point away from shoulder axis; check Z height |
| Wrong orientation | Check `surface.normal` direction — should point AWAY from surface |

---

## Output YAML Format

Matches teach-and-repeat exactly:

```yaml
description: Circle 80mm - left arm
duration: 45.23
joint_names: [j1l, j2l, j3l, j4l, j5l, j6l, j1r, j2r, j3r, j4r, j5r, j6r]
name: ''
points:
  - positions:     [0.123, -0.456, ...]   # 12 values
    velocities:    [0.001, -0.002, ...]   # 12 values
    accelerations: [0.000,  0.001, ...]   # 12 values
    time_from_start: 0.0
  ...
timestamp: '2026-03-07T12:00:00'
waypoint_count: 452
```
