# Industrial-Grade Trajectory Execution Architecture
**Date Created**: March 24, 2026  
**Status**: Design Document (Ready for Implementation)

---

## 1. INDUSTRY STANDARD RESEARCH

### 1.1 ROS/MoveIt Trajectory Standard (REP-47)
**Source**: trajectory_msgs package (de-facto standard for robotics)

The industry-standard format for trajectory execution is the **JointTrajectory Message** from ROS trajectory_msgs:

```yaml
# Conceptual YAML representation of trajectory_msgs/JointTrajectory
std_msgs/Header:
  frame_id: "base_link"
  stamp: 1234567890

# CRITICAL: Joint names define ORDER of all value arrays
joint_names:
  - "j1l"
  - "j2l"
  - "j3l"
  - "j4l"
  - "j5l"
  - "j6l"
  - "gripper_l_servo"
  - "j1r"
  - "j2r"
  - "j3r"
  - "j4r"
  - "j5r"
  - "j6r"
  - "gripper_r_servo"

points:
  - positions:      [0.0, 0.5, -0.2, 0.1, ...]  # Position at this waypoint
    velocities:     [0.1, 0.2, -0.15, 0.05, ...]  # Velocity command (optional)
    accelerations:  [0.5, 0.3, 0.2, 0.4, ...]  # Accel command (optional)
    effort:         [0.0, 0.0, 0.0, 0.0, ...]  # Torque/force (optional)
    time_from_start: 0.0  # When to reach this point

  - positions:      [0.1, 0.6, -0.15, 0.15, ...]
    velocities:     [0.15, 0.25, -0.12, 0.08, ...]
    accelerations:  [0.4, 0.35, 0.25, 0.35, ...]
    time_from_start: 1.5  # 1.5 seconds after start

  # ... more waypoints
```

**Key Principles**:
1. **Array Order Matters**: Every value array MUST match `joint_names` order
2. **Time Explicit**: Each waypoint specifies exact time from start (enables deterministic playback)
3. **Multi-Level Info**: positions (required) + velocities/accel (optional) for control quality
4. **Hardware Agnostic**: Format works for any motor type (servo, stepper, motor controller)

### 1.2 Hardware Execution Layer Pattern (Industry Standard)

```
┌─────────────────────────────────────────────────────────────┐
│ TRAJECTORY GENERATION (MoveIt/Planning)                     │
│ Output: trajectory_msgs/JointTrajectory                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ TRAJECTORY CONTROLLER (ros2_controllers)                    │
│ - Validates shape (joint names, sizes match)                │
│ - Interpolates between waypoints                            │
│ - Handles pause/resume/stop                                 │
│ - Enforces velocity/accel limits                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ HARDWARE INTERFACE (Device-Specific)                        │
│ - Maps joint positions → device commands                    │
│ - PCA9685: joint_value (rad) → PWM duty cycle              │
│ - Motor Controller: joint_value → voltage/current           │
│ - Position validation: within joint limits?                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ACTUATORS (Physical Motors/Servos)                          │
│ - Execute PWM/control commands in real-time                 │
│ - Send back position/current feedback                       │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Why This Matters for Your Setup

Your current architecture:
```
┌─────────────────────────────────────┐
│ Middleware                          │
│ execute.yaml GENERATED              │  ← You are here
│ (contains points but NOT executed)  │
└─────────────────────────────────────┘
                ↓ [GAP - NO EXECUTOR]
┌─────────────────────────────────────┐
│ Hardware (ESP32 + PCA9685 + Motors) │
│ (waiting for commands)              │
└─────────────────────────────────────┘
```

**What's missing**: The **Trajectory Controller** + **Hardware Interface** layer that:
1. Reads execute.yaml
2. Validates waypoints
3. Interpolates smoothly
4. Maps joint values to PCA9685 PWM commands
5. Sends via UDP to ESP32

---

## 2. YOUR SYSTEM: CURRENT STATE vs. NEEDED STATE

### Current State (After Artifact Implementation)
✅ **Trajectory Generation**: MoveIt generates plan YAML  
✅ **Execute Artifact**: generate execute.yaml with 14 joints  
✅ **Bundle Storage**: Both plan.yaml + execute.yaml stored together  
✅ **Naming**: Systematic naming with timestamps  

❌ **Hardware Execution**: No code path from execute.yaml → ESP32  
❌ **Interpolation**: No waypoint interpolation  
❌ **PWM Mapping**: No joint → PWM conversion  
❌ **Real-time Control**: No periodic trajectory playback  

### Target State (Industrial Standard)
```yaml
execute.yaml
  ├─ trajectory_name: "demo_left_circle"
  ├─ hardware_joint_order: [j1l, j2l, ...]
  ├─ points:
  │   ├─ positions: [0.0, 0.5, ...]
  │   ├─ time_from_start: 0.0
  │   ├─ velocities: [0.1, 0.2, ...]
  │   └─ accelerations: [0.5, 0.3, ...]
  │
  └─ [HARDWARE EXECUTOR]
      ├─ Load execute.yaml
      ├─ Validate all waypoints
      ├─ For each waypoint:
      │   ├─ Current time T
      │   ├─ Find surrounding waypoints (T_prev, T_next)
      │   ├─ Interpolate joint values at T
      │   ├─ Convert to PCA9685 PWM values
      │   └─ Send to ESP32 via UDP
      └─ [RESULT] Smooth trajectory on real hardware
```

---

## 3. IMPLEMENTATION ARCHITECTURE

### 3.1 Execute YAML Schema (Extended)

```yaml
# File: .runtime/trajectory_native/library/demo_left_circle_20260324_094839/demo_left_circle.execute.yaml
schema_version: dexter.trajectory.execute14.v1
kind: dexter_trajectory_execute_hw14
trajectory_name: demo_left_circle
job_id: native_daea1c002693
generated_at: "2026-03-24T09:48:39Z"

# Hardware configuration (for safety + mapping)
hardware_config:
  actuator_type: "pca9685_servo"  # servo | motor | custom
  control_frequency_hz: 50         # Update rate for hardware
  joint_limits:
    j1l: { min_rad: -3.14, max_rad: 3.14, max_vel_rad_s: 1.5 }
    j2l: { min_rad: -1.57, max_rad: 1.57, max_vel_rad_s: 1.5 }
    # ... rest of limits
  gripper_servo_range_us: [500, 2500]  # PWM microseconds for min/max

# Joint-to-hardware mapping
joint_to_hardware:
  j1l: { pca_channel: 0, pwm_min_us: 500, pwm_max_us: 2500 }
  j2l: { pca_channel: 1, pwm_min_us: 500, pwm_max_us: 2500 }
  gripper_l_servo: { pca_channel: 6, pwm_min_us: 500, pwm_max_us: 2500 }
  # ... 14 joints total

# Trajectory waypoints (CRITICAL EXECUTION DATA)
trajectory:
  total_duration_sec: 12.5
  point_count: 50

  points:
    - time_from_start_sec: 0.0
      positions:       [0.0, 0.5, -0.2, 0.1, 0.0, 0.0, 0.0, 0.0, 0.5, -0.2, 0.1, 0.0, 0.0, 0.0]
      velocities:      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
      accelerations:   null  # Optional
      
    - time_from_start_sec: 0.5
      positions:       [0.05, 0.55, -0.18, 0.12, 0.0, 0.0, 0.0, 0.05, 0.55, -0.18, 0.12, 0.0, 0.0, 0.0]
      velocities:      [0.1, 0.1, 0.04, 0.04, 0.0, 0.0, 0.0, 0.1, 0.1, 0.04, 0.04, 0.0, 0.0, 0.0]
      accelerations:   null

    # ... 48 more waypoints

    - time_from_start_sec: 12.5
      positions:       [0.0, 0.5, -0.2, 0.1, 0.0, 0.0, 0.0, 0.0, 0.5, -0.2, 0.1, 0.0, 0.0, 0.0]
      velocities:      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
      accelerations:   null

# Execution metadata
execution_metadata:
  loop_mode: "once"  # once | loop
  halt_on_loss_of_sync: true
  sync_threshold_sec: 0.1  # Max time drift before error
```

## 3.2 Hardware Executor Component (Python)

**File Location**: `src/dexter_middleware/app/trajectory_executor.py`

**Responsibilities**:
1. Load execute YAML from filesystem
2. Validate waypoint structure + joint values
3. Interpolate positions based on wall-clock time
4. Convert joint radians → PCA9685 PWM commands
5. Stream waypoints to ESP32 over UDP
6. Handle real-time deadline misses gracefully
7. Report execution status/errors

**Key Functions**:

```python
class HardwareTrajectoryExecutor:
    def __init__(self, esp32_host: str, esp32_port: int):
        """Initialize executor targeting ESP32."""
        
    async def load_trajectory(self, execute_yaml_path: Path) -> TrajectoryArtifact:
        """Load and validate execute.yaml."""
        
    async def execute(self, trajectory: TrajectoryArtifact) -> ExecutionResult:
        """Execute trajectory on real hardware with interpolation."""
        
    def _interpolate_waypoint(self, t: float, traj: TrajectoryArtifact) -> np.ndarray:
        """Interpolate joint positions at time t using cubic/linear interpolation."""
        
    def _joint_to_pwm(self, joint_name: str, joint_value_rad: float) -> int:
        """Convert joint radian value to PCA9685 PWM duty cycle."""
```

## 3.3 UDP Protocol (ESP32 ↔ Middleware)

**Endpoint**: ESP32 listening on UDP port 5005

**Command Format** (JSON over UDP):
```json
{
  "cmd": "trajectory_waypoint",
  "waypoint_idx": 0,
  "time_from_start_ms": 0,
  "pwm_values": [1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500],
  "expected_next_update_ms": 50
}
```

**Response Format** (ESP32 → Middleware):
```json
{
  "status": "ack",
  "waypoint_idx": 0,
  "current_position_rad": [0.0, 0.5, -0.2, ...],
  "current_time_ms": 123456
}
```

---

## 4. EXECUTION FLOW (WALL-CLOCK TIME)

```
User: POST /trajectory/execute with job_id=native_daea1c002693
  │
  ├─ [Middleware] Load execute.yaml from filesystem
  ├─ [Middleware] Validate: joint_names match? positions in bounds?
  ├─ [Middleware] Initialize HardwareTrajectoryExecutor
  ├─ [Middleware] Start wall-clock timer: T_start = now()
  │
  └─ [Executor] For each update cycle (50Hz = 20ms):
       │
       ├─ T_now = now() - T_start
       ├─ Find waypoints around T_now:
       │   └─ waypoint_prev @ 0.4s, waypoint_next @ 0.6s
       │   └─ At T_now=0.5s, interpolate 50% between them
       │
       ├─ For each of 14 joints:
       │   └─ interpolated_rad = linear_interp(prev, next, T_now)
       │   └─ pwm_value = joint_to_pwm(joint_name, interpolated_rad)
       │
       ├─ Send UDP packet to ESP32: { waypoint, pwm_values }
       ├─ [ESP32] Update PCA9685 channels 0-13 with new PWM values
       ├─ [ESP32] Motors start moving smoothly
       │
       └─ Continue until T_now >= trajectory.total_duration

[Result] Hardware executes trajectory smoothly without blocking
```

---

## 5. SAFETY MECHANISMS

### 5.1 Pre-Execution Validation (Middleware)
```python
def validate_trajectory(execute_yaml):
    # ✓ Schema version matches expected
    # ✓ All 14 joints present in hardware_joint_order
    # ✓ Every waypoint has 14 position values
    # ✓ Time is monotonically increasing
    # ✓ All positions within joint limits
    # ✓ Time deltas reasonable (not >1s jumps)
    # ✓ Velocities plausible (not sudden jumps)
```

### 5.2 Runtime Safety (Executor)
```python
async def execute_with_safety(trajectory):
    T_start = now()
    
    for T_cycle in range(0, trajectory.duration_ms, cycle_time_ms):
        # Deadline check: are we behind?
        T_now = (now() - T_start).ms
        if T_now - T_cycle > SYNC_THRESHOLD_MS:
            if HALT_ON_LOSS_OF_SYNC:
                raise ExecutorSyncError("Trajectory playback fell behind")
        
        # Interpolate & send
        waypoint = interpolate(T_now, trajectory)
        pwm_cmds = convert_to_pwm(waypoint)
        await send_to_esp32(pwm_cmds)
        
        # Wait for next cycle (not busy-wait)
        await asyncio.sleep(cycle_time_ms)
```

### 5.3 Graceful Degradation
- If UDP packet dropped: ESP32 continues with last PWM values
- If executor falls behind: Signal error and **decelerate to stop** (don't jerk)
- If joint limit violated: Stop before sending to hardware

---

## 6. COMPARISON: Current vs. Proposed

| Aspect | Current | Proposed (Industrial Standard) |
|--------|---------|--------------------------------|
| **Trajectory Format** | Custom YAML | ROS JointTrajectory-compatible YAML |
| **Execution** | Simulated (sleep loop) | Real hardware with interpolation |
| **Waypoint Timing** | N/A | Explicit `time_from_start_sec` |
| **Interpolation** | N/A | Cubic/Linear between waypoints |
| **PWM Mapping** | N/A | Joint-to-PWM conversion table |
| **Transport** | N/A | UDP batch commands to ESP32 |
| **Safety** | N/A | Pre-flight validation + runtime guards |
| **Sync Tolerance** | N/A | Configurable (default 100ms) |
| **Error Recovery** | N/A | Graceful degradation / safe stop |

---

## 7. NEXT STEPS (IMPLEMENTATION ROADMAP)

1. **Extend Execute YAML Schema** (50 lines Python)
   - Add `hardware_config`, `joint_to_hardware`, interpolation metadata

2. **Build HardwareTrajectoryExecutor** (200-300 lines Python)
   - Load + validate YAML
   - Implement cubic interpolation
   - Joint → PWM conversion

3. **Implement UDP Protocol** (100 lines Python + 50 lines ESP32 C++)
   - Middleware: send waypoints
   - ESP32: receive and update PCA9685

4. **Integrate with `/trajectory/execute` Endpoint** (50 lines)
   - Replace simulated `_run_trajectory` with real executor

5. **Testing & Validation** (iterative)
   - Unit tests for interpolation
   - Hardware-in-loop with ESP32
   - Smoke tests on real motors

---

## 8. REFERENCES

- **ROS Standard**: trajectory_msgs/JointTrajectory (trajectory_msgs package)
- **Controller Pattern**: ros2_controllers/joint_trajectory_controller
- **Hardware Interface**: hardware_interface package (ros2_control)
- **Your Hardware**: ESP32 + PCA9685 + micro-ROS + UDP transport
- **Industry Adoption**: Used by Clearpath, ABB, FANUC, Universal Robots

This design bridges the gap between high-level trajectory planning and low-level hardware execution using proven industry patterns.
