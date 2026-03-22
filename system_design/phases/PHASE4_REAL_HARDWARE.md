# Phase 4: Real Hardware + RViz + MoveIt

**Status**: Planning / Implementation in progress  
**Scope**: RViz + MoveIt control of physical Dexter Arm via micro-ROS  
**Complexity**: HIGH (multi-stage bootstrap + connection resilience)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ Middleware (FastAPI) - hardware_bootstrap_service.py            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
┌──────────────────────┐             ┌──────────────────────┐
│   micro-ROS Agent    │             │ hardware_bringup     │
│   (Stage 1)          │             │ (Stage 2)            │
│                      │             │                      │
│ • Subprocess mgmt    │(depends on) │ • Controller spawn   │
│ • Log monitoring     │             │ • MoveIt move_group  │
│ • Session validation │             │ • RViz visualization │
│ • Serial/UDP select  │             │ • Real robot control │
└──────────────────────┘             └──────────────────────┘
        ↓                                       ↓
┌──────────────────────┐             ┌──────────────────────┐
│   ESP32 (Serial or   │←────ROS────→│ Joint Trajectory     │
│   WiFi UDP)          │  net comm   │ Controllers (100Hz)  │
│                      │             │                      │
│ • 14 joint servo     │             │ • left_arm_ctrl      │
│ • Firmware control   │             │ • right_arm_ctrl     │
│ • State feedback     │             │ • gripper_ctrl       │
│ • 500Hz servo loop   │             │ • state_broadcaster  │
└──────────────────────┘             └──────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────┐
│  Dexter Arm (Physical Robot)                                 │
│  ├─ Left Arm (6 DOF)                                         │
│  ├─ Right Arm (6 DOF)                                        │
│  ├─ Left Gripper (2 DOF)                                     │
│  └─ Right Gripper (2 DOF)                                    │
└──────────────────────────────────────────────────────────────┘
```

## Two-Phase Bootstrap Sequence

### **Stage 1: Micro-ROS Agent Connection** ⚡ (CRITICAL)

```
[Middleware receives: POST /ros/hardware/start]
  ↓
[Create micro-ROS agent subprocess with transport config]
  
  if transport == "serial":
    Command: ros2 run micro_ros_agent micro_ros_agent serial \
             --dev {device_port} -b 115200
    Example: /dev/ttyUSB0
  
  else (transport == "udp"):
    Command: ros2 run micro_ros_agent micro_ros_agent udp4 \
             --port {port}
    Example: 8888
  ↓
[Monitor agent process stdout/stderr for session marker]
  
  Poll loop (0-30 seconds):
  ├─ Scan logs for: "New session" OR "RUNNING"
  ├─ If found: → Stage 2 (proceed)
  ├─ If timeout (30s): → Try reset + retry (up to 3 times)
  └─ After 3 retries: → FAILED (rollback)
  ↓
[ON SUCCESS: Agent subprocess locked, ready for ROS comms]
[Connected: /esp32/joint_commands ↔ /esp32/joint_states]
```

**Why This Matters:**
- ESP32 takes 5-30 seconds to establish micro-ROS session
- If you launch hardware_bringup.launch.py before agent is ready, nodes will stall
- Dashboard already has this logic in `hardware_full_system_window.py` (we're porting it to middleware)

### **Stage 2: Hardware Bringup Launch** ⚙️

```
[Stage 1 completed and confirmed]
  ↓
[Start hardware_bringup.launch.py subprocess]
  
  Command:
    ros2 launch dexter_arm_hardware hardware_bringup.launch.py \
      use_rviz={use_rviz} \
      load_moveit={load_moveit}
  ↓
[Launch executes internal sequence with delays]
  
  t=0s:   Start controller_manager, robot_state_publisher
  t+6s:   Spawn controllers (joint_state_broadcaster, arm/gripper controllers)
  t+8s:   Start MoveIt move_group (if load_moveit=true)
  t+10s:  Start RViz2 visualization (if use_rviz=true)
  ↓
[ON SUCCESS: Both processes running, joint control active]
[Ready for trajectory commands from MoveIt]
```

**Why Staggered Timing:**
- Hardware interface needs time to establish micro-ROS subscriptions
- Controllers need hardware interface ready before spawning
- MoveIt depends on controller_manager + joint definitions

---

## API Endpoints

### **GET /ros/hardware/status**
Returns connection + launch status.

**Response** (200 OK):
```json
{
  "agent_running": true,
  "agent_pid": 1234,
  "agent_transport": "serial",
  "agent_device": "/dev/ttyUSB0",
  "agent_session_established": true,
  "agent_session_markers": ["New session", "RUNNING"],
  
  "launch_running": true,
  "launch_pid": 5678,
  "hardware_connected": true,
  
  "use_rviz": true,
  "load_moveit": true,
  
  "joint_states_received": 342,
  "last_update_ms": 15,
  "errors": []
}
```

### **POST /ros/hardware/start**
Bootstrap both stages: agent → validation → hardware_bringup.

**Request Body**:
```json
{
  "transport": "serial",           # "serial" or "udp"
  "device_port": "/dev/ttyUSB0",   # serial device or port number
  "use_rviz": true,
  "load_moveit": true,
  "agent_timeout_sec": 30,
  "agent_max_retries": 3
}
```

**Response** (202 Accepted):
```json
{
  "status": "bootstrapping",
  "stage": 1,
  "message": "Connecting micro-ROS agent..."
}
```

**Long-Poll Until Ready**:
```bash
# Poll until both stages complete (typically 30-45 seconds)
while true; do
  curl -s http://127.0.0.1:8080/ros/hardware/status | jq '.agent_session_established'
  sleep 2
done
```

### **POST /ros/hardware/stop**
Teardown in reverse order: hardware_bringup → agent.

**Request Body**: (empty)

**Response** (200 OK):
```json
{
  "agent_terminated": true,
  "launch_terminated": true,
  "message": "Hardware disconnected gracefully"
}
```

---

## Implementation Plan

### **New Files to Create:**

1. **`dexter_middleware/app/services/hardware_bootstrap_service.py`** (200+ lines)
   - `HardwareBootstrapService` class
   - Methods:
     - `start(transport, device_port, use_rviz, load_moveit, agent_timeout_sec, agent_max_retries)`
     - `stop()`
     - `status()`
     - `_wait_for_agent_session(process, timeout)` (log monitoring)
     - `_cleanup_agent_children()` (signal cascade)
     - `_start_hardware_bringup()` (spawn launch process)

2. **`dexter_middleware/app/models.py` (append)**
   - `HardwareBootstrapStartRequest` (transport, device_port, use_rviz, load_moveit, timeouts)
   - `HardwareBootstrapStatusResponse` (full state snapshot)

### **Modified Files:**

3. **`dexter_middleware/app/main.py`** (patch)
   - Import `HardwareBootstrapService`, `HardwareBootstrapStartRequest`
   - Add `hardware_lock` and `hardware_service` instance
   - Add endpoints:
     - `GET /ros/hardware/status`
     - `POST /ros/hardware/start`
     - `POST /ros/hardware/stop`
   - Update `snapshot()` to include hardware status block
   - Update `disconnect()` to stop hardware_service
   - Add safety cleanup: hardware start() stops all simulation (Track 1 + Track 2)

4. **`dexter_temp_ui/index.html`** (patch)
   - Add Phase 4 panel:
     - Transport dropdown: "Serial" / "UDP"
     - Device/Port input: text field for `/dev/ttyUSB0` or `8888`
     - use_rviz checkbox
     - load_moveit checkbox
     - Start / Stop / Status Refresh buttons
     - Status display: connection state + session markers + error messages

5. **`dexter_temp_ui/app.js`** (patch)
   - `getHardwareStatus()` function
   - `startHardware()` / `stopHardware()` event handlers
   - Poll interval: 2s (faster refresh for hardware connection feedback)

### **Documentation:**

6. **`system_design/phases/PHASE4_REAL_HARDWARE.md`** (this file - updated with implementation notes)

7. **`INSTALL.md` (append Phase 4 section)**
   - Prerequisite: micro-ROS workspace setup
   - Step 1: Build Dexter Arm packages
   - Step 2: Flash ESP32 firmware (serial vs WiFi choice)
   - Step 3: Configure WiFi SSID/password (if UDP selected)
   - Step 4: Start middleware with hardware service
   - Step 5: Open UI and bootstrap

---

## Critical Implementation Details

### **Agent Session Detection**

The Explore agent found logs show these patterns:
```
Option 1 (Connected):
[URP] Serial port connected: /dev/ttyUSB0 @ 115200 baud
[DDS] New session: session_id = 0x...
[DDS] RUNNING

Option 2 (Timeout):
[URP] Waiting for serial connection...
(hangs for 30 seconds)

Option 3 (Disconnected):
[URP] Serial port error: Device not found
```

**Service must**:
1. Capture stdout/stderr in real-time (streaming, not end-of-process)
2. Regex-match for "New session" OR "RUNNING" OR "Client connected"
3. Implement timeout (~30s per attempt, 3 retries max = 90s total worst case)
4. Log all session markers to status for UI feedback

### **Process Cascade Cleanup**

When hardware_bringup.launch.py runs, it spawns:
```
launch (PID=1000)
├─ controller_manager (PID=1001)
├─ robot_state_publisher (PID=1002)
├─ rviz2 (PID=1003)
├─ move_group (PID=1004)
└─ /opt/ros/jazzy/lib/ros_launch/... (children)
```

**SIGTERM to top-level launch should cascade kill all children** (via ProcessGroup).
Verify with `ps tree` if any orphans remain.

### **Safety Rules**

Phase 4 cannot run simultaneously with:
- Phase 1 (RViz-only)
- Phase 2 (RViz + MoveIt demo)
- Phase 3 Track 1 (Gazebo-only)
- Phase 3 Track 2 (Full simulation)

**Implementation**:
```python
# In hardware_service.start():
async with hardware_lock:
    # Stop all simulation phases
    await rviz_service.stop()
    await moveit_service.stop()
    await gazebo_service.stop()
    await full_stack_service.stop()
    await asyncio.sleep(2)  # Wait for cleanup
    
    # Now start agent
    self._start_agent()
    ...
```

---

## Testing Strategy

### **Stage 1 Testing** (Agent Connection)

```bash
# Manual: Run agent in terminal, verify session marker appears
ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyUSB0 -b 115200

# Expected within 10s:
# [URP] Serial port connected: /dev/ttyUSB0 @ 115200 baud
# [DDS] New session: session_id = ...
# [DDS] RUNNING
```

### **Stage 2 Testing** (Hardware Bringup)

```bash
# After agent is running (Stage 1 done):
ros2 launch dexter_arm_hardware hardware_bringup.launch.py use_rviz:=true load_moveit:=true

# Verify:
# 1. ROS nodes appear: ros2 node list
# 2. Topics appear: ros2 topic list | grep -E "joint|command|state"
# 3. Hardware interface connected: ros2 service list | grep controller
```

### **Middleware Testing** (Phase 4)

```bash
# 1. Start middleware on :8080
cd src/dexter_middleware && uvicorn app.main:app --app-dir . --port 8080

# 2. Check status (should show agent/launch both not running)
curl -s http://127.0.0.1:8080/ros/hardware/status | jq '.'

# 3. Start hardware bootstrap
curl -X POST http://127.0.0.1:8080/ros/hardware/start \
  -H "Content-Type: application/json" \
  -d '{
    "transport": "serial",
    "device_port": "/dev/ttyUSB0",
    "use_rviz": true,
    "load_moveit": true,
    "agent_timeout_sec": 30,
    "agent_max_retries": 3
  }'

# 4. Poll status until both stages complete
for i in {1..20}; do
  curl -s http://127.0.0.1:8080/ros/hardware/status | jq '.agent_session_established, .launch_running'
  sleep 3
done

# 5. Open UI browser to http://127.0.0.1:8090, click Phase 4 Start
# 6. Verify: Gazebo does NOT appear; RViz opens; MoveIt controller pane shows
# 7. Try MoveIt motion planning: plan + execute on real arm (CAREFUL!)
```

### **UI Testing**

```
Phase 4 Panel:
├─ Transport selector
│  ├─ Serial → /dev/ttyUSB0 input field
│  └─ UDP → 8888 (or configurable port)
├─ Checkboxes: use_rviz, load_moveit
├─ Start button → POST /hardware/start
├─ Stop button → POST /hardware/stop
├─ Status refresh → GET /hardware/status (poll loop 2s)
└─ Error display: Show session markers + errors
```

---

## Known Challenges & Mitigations

| Challenge | Root Cause | Mitigation |
|-----------|-----------|-----------|
| **Agent timeout (>30s)** | ESP32 not responding or wrong baud rate | Retry logic with 3 attempts; pre-validate device presence |
| **Launch stalls after agent connected** | Hardware interface can't find micro-ROS topics | Add timeout in hardware_bringup; log topic availability |
| **RViz/MoveIt don't start** | Timing issues; controller manager not ready | Use staggered launch (already in hardware_bringup.launch.py) |
| **Orphaned processes after crash** | Launch process tree not killed | Use process group cleanup (ps tree descent) |
| **Real robot jerky motion** | Network latency or QoS mismatch | Monitor latency; document SLO targets (Phase 4b) |

---

## Files & Dependencies

**ROS Launch**:
- `/src/dexter_arm_hardware/launch/hardware_bringup.launch.py` (existing)
- `/src/dexter_arm_hardware/urdf/dexter_arm_hardware.xacro` (existing)

**Configuration**:
- `/src/dexter_arm_control/config/controllers.yaml` (existing)
- `/src/dexter_arm_moveit_config/config/moveit_controllers.yaml` (existing)

**Hardware Plugin (C++)**: 
- `/src/dexter_arm_hardware/hardware/dexter_hardware_interface.cpp` (existing)

**Middleware Components** (to be created):
- `hardware_bootstrap_service.py` (new)
- `models.py` → `HardwareBootstrapStartRequest` (append)
- `main.py` → endpoints + locks (patch)

**Temporary UI** (to be updated):
- `index.html` → Phase 4 panel (patch)
- `app.js` → hardware handlers (patch)

---

## Success Criteria

✅ **Passed**: Phase 4 implementation is **DONE** when:
1. micro-ROS agent successfully connects (session marker appears in logs)
2. hardware_bringup.launch.py launches after agent confirmed
3. RViz window opens (if use_rviz=true)
4. MoveIt move_group appears (if load_moveit=true)
5. real robot arm responds to MoveIt trajectory commands
6. `/ros/hardware/status` endpoint shows `agent_running=true`, `launch_running=true`, `hardware_connected=true`
7. UI Phase 4 panel displays connection state and accepts start/stop
8. Stopping Phase 4 cleanly tears down both processes without orphans

---

## Next Phase (Phase 5): Production Hardening

Once Phase 4 proven stable on real hardware:
- HA: Automatic reconnection on agent/launch crash
- Observability: Structured logging, metrics export
- Safety: E2E fault injection tests, SLO monitoring
- Docs: Deployment guide, troubleshooting manual

