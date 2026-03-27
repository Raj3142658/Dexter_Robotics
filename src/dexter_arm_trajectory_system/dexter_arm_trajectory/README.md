# Dexter Arm Trajectory System - Teach & Repeat

## Overview

A professional teach-repeat trajectory system that allows you to record MoveIt-planned motions and replay them with high fidelity on both simulation and hardware.

**Architecture:**

- **Trajectory Manager Node**: Captures, concatenates, and manages trajectory segments
- **TCP Visualizer Node**: Shows end-effector path visualization
- **GUI**: PyQt5-based interface for teach-repeat workflow

---

## Quick Start

### 1. Launch the Full System

```bash
# Terminal 1: Start the robot system (Gazebo or Hardware)
cd /home/raj/dexter_arm_ws
source install/setup.bash
ros2 launch dexter_arm_moveit_config full_system.launch.py  # Or your preferred launch file

# Terminal  2: Launch trajectory system
ros2 launch dexter_arm_trajectory teach_mode.launch.py
```

### 2. Teach Workflow

1. **Plan in RViz**: Use MoveIt's "Plan" button to plan a motion
2. **Capture**: Click "📷 Capture Segment" in the GUI when you like the plan
3. **Repeat**: Plan and capture more segments (e.g., pick → move → place)
4. **Compile**: Click "⚙️ Compile Trajectory" to concatenate and smooth all segments
5. **Preview**: Click "👁️ Preview" to see the full path in RViz
6. **Save**: Click "💾 Save" to store the trajectory
7. **Execute**: Click "▶️ Execute" to replay the motion

---

## System Components

### Trajectory Manager Node

**Executable:** `trajectory_manager`

Captures MoveIt trajectories from `/move_group/display_planned_path` and manages:

- Segment buffering
- Concatenation with boundary smoothing
- YAML save/load
- Execution via ros2_control

**Services:**

- `/trajectory_manager/capture_segment` (Trigger-like)
- `/trajectory_manager/clear_buffer` (Trigger)
- `/trajectory_manager/compile` (Trigger-like)
- `/trajectory_manager/save` (custom)
- `/trajectory_manager/load` (custom)
- `/trajectory_manager/get_status` (custom)

### TCP Visualizer

**Executable:** `tcp_visualizer`

Computes and visualizes end-effector path using forward kinematics.

**Topics:**

- Subscribes: `/trajectory_preview`
- Publishes: `/tcp_path_marker`

### GUI Application

**Executable:** `trajectory_gui`

PyQt5 interface for controlling the teach-repeat system.

---

## Configuration

Edit `config/trajectory_params.yaml` to customize:

```yaml
planning_group: "dexter_arm"
end_effector_link: "end_effector_link"
controller_name: "joint_trajectory_controller"
trajectory_storage_dir: "~/.ros/dexter_trajectories"
velocity_scaling: 0.8
acceleration_scaling: 0.8
```

---

## Trajectory Storage

Trajectories are saved in **YAML format** at:

```
~/.ros/dexter_trajectories/
├── motion_1.yaml
├── motion_2.yaml
└── pick_place_sequence.yaml
```

Example structure:

```yaml
name: "pick_place"
description: "Pick and place demo"
duration: 8.5
waypoint_count: 247
joint_names: [joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
points:
  -positions: [0.0, -0.5, 1.2, ...]
    velocities: [0.0, 0.1, ...]
    time_from_start: 0.0
  - ...
```

---

## Manual Usage (Without GUI)

### Capture a Segment

```bash
ros2 service call /trajectory_manager/capture_segment std_srvs/srv/Trigger
```

### Compile Trajectory

```bash
ros2 service call /trajectory_manager/compile std_srvs/srv/Trigger
```

### Check Status

```bash
ros2 service call /trajectory_manager/get_status dexter_arm_trajectory/srv/GetStatus
```

---

## Troubleshooting

### GUI Not Showing

- Install PyQt5: `pip3 install PyQt5`
- Check if X11 forwarding is enabled (if using SSH)

### Trajectory Manager Not Receiving Plans

- Verify MoveIt is running: `ros2 topic echo /move_group/display_planned_path`
- Check planning group name in config matches SRDF

### Execution Fails

- Ensure `joint_trajectory_controller` is active:
  ```bash
  ros2 control list_controllers
  ```

---

## Advanced Features

### TCP Path Export

Enable CSV export in config:

```yaml
tcp_marker:
  export_csv: true
  csv_output_dir: "~/.ros/dexter_trajectories/tcp_paths"
```

TCP paths will be saved for plotting in MATLAB/Python.

### Auto-Backup

Segments are auto-backed up before compilation if enabled:

```yaml
auto_backup: true
backup_dir: "~/.ros/dexter_trajectories/backups"
```

---

## Design Philosophy

**Why teach-repeat?**

- MoveIt handles IK, collision, and constraints during teaching
- Execution is deterministic (same input → same motion)
- No online planning overhead during replay
- Industry-standard approach for repetitive tasks

**Why joint-space replay?**

- Faster than Cartesian replanning
- Guaranteed smooth motion
- Works identically in sim and hardware

---

## Next Steps

- Implement trajectory execution action client (currently placeholder)
- Add MoveIt Python bindings for accurate FK in TCP visualizer
- Implement loop/repeat functionality
- Add trajectory editing (delete segments, reorder)

---

## File Structure

```
dexter_arm_trajectory/
├── dexter_arm_trajectory/
│   ├── __init__.py
│   ├── trajectory_manager_node.py
│   ├── tcp_visualizer_node.py
│   └── trajectory_teach_gui.py
├── launch/
│   ├── trajectory_system.launch.py
│   └── teach_mode.launch.py
├── config/
│   └── trajectory_params.yaml
├── trajectories/
│   ├── example_pick_place.yaml
│   └── README.md
├── package.xml
├── setup.py
└── setup.cfg
```

---

## License

MIT

---

**Built for the Dexter Arm - January 2026**
