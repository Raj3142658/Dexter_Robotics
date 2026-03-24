# Trajectory Execution Implementation Checklist

## Phase 1: Extend Execute YAML Schema (2-3 hours)

- [ ] **1.1** Update `_native_execute_payload()` in middleware to add:
  - `hardware_config` section (actuator_type, control_frequency_hz, joint_limits)
  - `joint_to_hardware` mapping (PCA channel, PWM range for each joint)
  - `trajectory.total_duration_sec`
  - Extend each point with `velocity` and `acceleration` arrays

- [ ] **1.2** Create example execute.yaml file showing new format
  - Store in `.runtime/examples/` for documentation

- [ ] **1.3** Verify schema doesn't break existing code
  - Run precheck endpoint with new execute.yaml
  - Confirm download endpoint still works

---

## Phase 2: Build Hardware Trajectory Executor (6-8 hours)

### 2.1 Core Executor Module
- [ ] **2.1.1** Create `src/dexter_middleware/app/trajectory_executor.py`:
  - `TrajectoryArtifact` dataclass (pydantic model)
  - `ExecutionResult` dataclass (success/error tracking)
  - `HardwareTrajectoryExecutor` class

- [ ] **2.1.2** Implement validation pipeline:
  - `validate_schema_version()` - check execute.yaml format
  - `validate_waypoint_structure()` - 14 joints per point?
  - `validate_joint_bounds()` - all positions in limits?
  - `validate_time_monotonic()` - times always increasing?

### 2.2 Interpolation Engine
- [ ] **2.2.1** Implement waypoint search:
  - Find surrounding waypoints for current time T
  - Handle edge cases (T < first point, T > last point)

- [ ] **2.2.2** Implement interpolation methods:
  - Linear interpolation (simple + fast)
  - Cubic interpolation (smoother motion, optional)
  - Velocity-aware interpolation (use velocity arrays if present)

- [ ] **2.2.3** Test interpolation:
  - Unit tests: verify interpolated values make sense
  - Edge case: stopping (velocity → 0 smoothly)

### 2.3 Joint ↔ PWM Conversion
- [ ] **2.3.1** Implement `JointToPWMConverter`:
  - Read joint_to_hardware mapping from execute.yaml
  - Convert joint_rad (float) → pwm_us (int, 500-2500 typical)
  - Handle gripper servo specially (prismatic → servo)

- [ ] **2.3.2** Add calibration support:
  - Allow user-provided PWM min/max per joint
  - Document servo calibration procedure

### 2.4 Real-Time Executor
- [ ] **2.4.1** Implement `async def execute()`:
  - Start wall-clock timer
  - Execute 50Hz control loop (20ms cycle)
  - Interpolate positions for current time
  - Convert to PWM
  - Send to ESP32 via UDP

- [ ] **2.4.2** Add sync monitoring:
  - Track deadline misses
  - Configurable sync_threshold (default 100ms)
  - Option to halt on sync loss

---

## Phase 3: UDP Transport Protocol (4-5 hours)

### 3.1 Middleware Side
- [ ] **3.1.1** Implement UDP client in executor:
  - Connect to ESP32 socket (configurable host:port)
  - Serialize waypoint to JSON
  - Send/receive with timeout handling

- [ ] **3.1.2** Define command format:
  - trajectory_waypoint command (waypoint index, timestamp, PWM values)
  - heartbeat command (keep-alive during long trajectories)

- [ ] **3.1.3** Define response format:
  - ack response (status, current motor positions)
  - error response (joint limit hit, comm error, etc.)

### 3.2 ESP32 Firmware
- [ ] **3.2.1** Create micro-ROS UDP receiver:
  - Listen on port 5005
  - Parse incoming JSON waypoint commands
  - Update PCA9685 PWM channels 0-13

- [ ] **3.2.2** Implement PCA9685 update routine:
  - Set frequency: 50Hz
  - Write PWM values for 14 channels
  - Non-blocking write (don't stall on I2C issues)

- [ ] **3.2.3** Add heartbeat timeout:
  - If no command received for >500ms, enter safe stop
  - Graceful deceleration (not hard stop)

---

## Phase 4: Integrate with Middleware API (3-4 hours)

- [ ] **4.1** Modify `/trajectory/execute` endpoint:
  - Replace simulated `_run_trajectory()` call
  - Instantiate `HardwareTrajectoryExecutor`
  - Load execute.yaml from job_id
  - Call `executor.execute()` → real hardware

- [ ] **4.2** Add new endpoint: `POST /trajectory/execute/precheck-hardware`
  - Simulate playback without sending to ESP32
  - Verify interpolation works
  - Show predicted timeline

- [ ] **4.3** Add status reporting:
  - `/trajectory/status` returns current waypoint index
  - Real-time progress (% complete + current joint positions)

---

## Phase 5: Safety & Error Handling (2-3 hours)

- [ ] **5.1** Pre-execution checks:
  - All joint limits respected?
  - ESP32 reachable and responsive?
  - Trajectory duration reasonable?

- [ ] **5.2** Runtime error handling:
  - UDP packet loss → retry with backoff
  - Deadline miss → graceful deceleration
  - Joint limit violation → emergency stop

- [ ] **5.3** Recovery mechanisms:
  - Pause/resume trajectory
  - Stop trajectory (safe deceleration)
  - Abort and return to neutral

---

## Phase 6: Testing & Validation (4-6 hours)

### 6.1 Unit Tests
- [ ] **6.1.1** Interpolation tests:
  - Linear interpolation correctness
  - Cubic interpolation smoothness
  - Edge cases (T=0, T=duration, T > duration)

- [ ] **6.1.2** Validation tests:
  - Valid execute.yaml passes all checks
  - Invalid YAML caught early
  - Joint limits enforced

- [ ] **6.1.3** PWM conversion tests:
  - Joint value → PWM maps correctly
  - Gripper conversion works
  - Calibration values applied

### 6.2 Hardware-in-Loop Tests
- [ ] **6.2.1** Middleware ↔ ESP32 communication:
  - Send waypoint command
  - Receive ack response
  - Verify UDP packet format

- [ ] **6.2.2** Motor behavior:
  - Smooth motion (no jerkiness)
  - Correct direction
  - Respect velocity limits

- [ ] **6.2.3** End-to-end trajectory:
  - Generate trajectory (shape generation)
  - Execute on real hardware
  - Motors follow expected path

### 6.3 Smoke Tests
- [ ] **6.3.1** Circle trajectory (small radius, fast)
- [ ] **6.3.2** Line trajectory (slow, controlled)
- [ ] **6.3.3** Stop/pause/resume during execution
- [ ] **6.3.4** Large trajectory (10+ seconds)

---

## Phase 7: Documentation & Deployment (1-2 hours)

- [ ] **7.1** User Documentation:
  - How to execute a saved trajectory
  - API endpoints for execution
  - Monitoring real-time progress

- [ ] **7.2** Operator Guide:
  - Safe operation procedures
  - Emergency stop procedures
  - Troubleshooting common issues

- [ ] **7.3** Developer Documentation:
  - Executor architecture overview
  - Extending interpolation methods
  - Custom hardware interface examples

---

## Estimated Total Timeline

| Phase | Hours | Status |
|-------|-------|--------|
| 1. Schema Extension | 2-3 | ⏳ Not Started |
| 2. Executor Module | 6-8 | ⏳ Not Started |
| 3. UDP Protocol | 4-5 | ⏳ Not Started |
| 4. API Integration | 3-4 | ⏳ Not Started |
| 5. Safety/Error Handling | 2-3 | ⏳ Not Started |
| 6. Testing | 4-6 | ⏳ Not Started |
| 7. Documentation | 1-2 | ⏳ Not Started |
| **TOTAL** | **22-31 hours** | - |

---

## Milestones

### MVP (7-10 hours)
✓ Extended execute.yaml with joint_to_hardware mapping  
✓ Linear interpolation working  
✓ UDP basic send/receive working  
✓ One motor successfully executed via trajectory  

### Beta (15-18 hours)
✓ All 14 joints executing smoothly  
✓ Cubic interpolation optional  
✓ Real-time monitoring working  
✓ Safety validation in place  

### Production (22-31 hours)
✓ Full test coverage  
✓ Error recovery robust  
✓ Documentation complete  
✓ Hardware qualification on actual Dexter arm  

---

## Notes

- ESP32 firmware updates may require separate branch/repo
- Coordinate with hardware team on PCA9685 I2C stability
- Schedule hardware test time slots to avoid conflicts
- Consider simulation testing before real motors (use hardware emulator)
