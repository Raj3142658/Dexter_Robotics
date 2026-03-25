# Dexter Robotics - Transfer Setup Guide

Complete instructions for transferring the Dexter Robotics project to another Ubuntu 24.04 laptop with ROS2 Jazzy.

## System Requirements

Before starting, verify your target laptop has:

| Component | Version | Check |
|-----------|---------|-------|
| **OS** | Ubuntu 24.04 LTS | `lsb_release -a` |
| **ROS2** | Jazzy | `echo $ROS_DISTRO` or install from https://docs.ros.org/en/jazzy/Installation.html |
| **Python** | 3.12+ | Script will auto-install if missing |
| **Internet** | Connected | Required for apt-get and pip downloads |

## Quick Start (One Command)

If your target laptop already has **ROS2 Jazzy installed**:

```bash
# 1. Clone the project
git clone https://github.com/Raj3142658/Dexter_Robotics.git
cd Dexter_Robotics

# 2. Run automated setup
bash scripts/setup_workspace.sh
```

That's it! The script handles everything else automatically.

---

## What the Setup Script Does

### Step 1: Python3 Verification
- Checks if Python3 is installed
- If missing, automatically installs `python3.12` + `python3-venv`
- Verifies installation works

### Step 2: ROS2 Verification
- Checks if ROS2 Jazzy is already sourced
- If not, sources `/opt/ros/jazzy/setup.bash`
- Validates ROS2 Jazzy installation
- ⚠️ If Jazzy not installed, script will exit with installation link

### Step 3: Build Tools Check
- Verifies `colcon` (ROS2 build system)
- Verifies `gcc` (C++ compiler)
- Installs missing tools automatically

### Step 4: ROS2 Dependencies
- Initializes `rosdep` database
- Scans all `package.xml` files in `src/`
- Installs all system dependencies (moveit, hardware_interface, controllers, etc.)

### Step 5: Colcon Build
- Cleans previous build artifacts
- Compiles all ROS2 packages with `colcon build --symlink-install`
- Generates `install/setup.bash` activation script

### Step 6: Hardware Interface Verification
- Checks if gripper controller plugin compiled successfully
- Located at: `install/dexter_arm_hardware/lib/libdexter_hardware_interface.so`

### Step 7: Middleware Setup
- Creates isolated Python virtual environment in `src/dexter_middleware/.venv/`
- Installs FastAPI + Uvicorn + PyYAML
- Ready for API server startup

---

## Manual Setup (If Script Fails)

If the automated script encounters issues, follow these manual steps:

### 1. Source ROS2
```bash
source /opt/ros/jazzy/setup.bash
```

### 2. Install Dependencies
```bash
cd /path/to/Dexter_Robotics
rosdep install --from-paths src --ignore-src -r -y
```

### 3. Build Workspace
```bash
colcon build --symlink-install
```

### 4. Setup Middleware
```bash
cd src/dexter_middleware
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
cd ../..
```

### 5. Activate Workspace
```bash
source install/setup.bash
```

---

## After Setup: Launching the System

### Start the Control Center (Web UI + Middleware API)
```bash
bash scripts/launch_control_center.sh
```

**This launches:**
- FastAPI middleware on `http://127.0.0.1:8080`
- Web UI on `http://127.0.0.1:8090`
- Auto-opens browser to the UI

### Check Middleware API
```bash
# Health check
curl http://127.0.0.1:8080/health

# API documentation
# Open: http://127.0.0.1:8080/docs (in browser)
```

### Stop Services
```bash
bash scripts/stop_control_center.sh
```

---

## File Structure After Setup

```
Dexter_Robotics/
├── src/
│   ├── dexter_arm_hardware/          ← Hardware interface plugin
│   │   └── firmware/
│   │       └── esp32_firmware_wireless.ino  (Flash this to ESP32)
│   ├── dexter_arm_control/           ← Joint controllers
│   ├── dexter_arm_moveit_config/     ← Motion planning configs
│   ├── dexter_arm_dashboard/         ← RViz dashboard
│   ├── dexter_arm_description/       ← URDF + meshes
│   └── dexter_middleware/            ← FastAPI web service
│       ├── app/
│       │   ├── main.py              ← API server
│       │   ├── models.py            ← Data models
│       │   └── trajectory_executor.py
│       ├── requirements.txt
│       └── .venv/                   ← Python environment (created by setup)
│
├── build/                            ← ROS2 build outputs (created by colcon)
├── install/                          ← ROS2 install files (created by colcon)
│   ├── setup.bash                   ← ACTIVATE THIS: source install/setup.bash
│   ├── dexter_arm_hardware/
│   │   └── lib/libdexter_hardware_interface.so
│   └── ... (other installed packages)
│
├── log/                              ← Build logs (created by colcon)
├── scripts/
│   ├── setup_workspace.sh            ← MAIN SETUP SCRIPT
│   ├── launch_control_center.sh      ← Start web UI + API
│   ├── stop_control_center.sh
│   ├── trajectory_smoke_test.sh
│   └── trajectory_qualification_run.sh
│
└── docs/
    └── TRAJECTORY_QUALIFICATION_MATRIX.md
```

---

## Troubleshooting

### Error: "ROS2 Jazzy not found"
**Solution:** Install ROS2 Jazzy first
```bash
# Follow official installation guide
https://docs.ros.org/en/jazzy/Installation.html
```

### Error: "colcon: command not found"
**Solution:** Install ROS2 build tools
```bash
sudo apt-get install python3-colcon-common-extensions
source /opt/ros/jazzy/setup.bash
```

### Build Fails: "hardware_interface not found"
**Solution:** Ensure rosdep dependencies installed
```bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select dexter_arm_hardware
```

### Middleware won't start (port 8080 already in use)
**Solution:** Kill existing process
```bash
lsof -ti tcp:8080 | xargs kill -9
bash scripts/launch_control_center.sh
```

### Python venv activation issues
**Solution:** Ensure Python3 installed
```bash
python3 --version  # Should be 3.10+
python3 -m venv --help  # Should work
```

---

## Post-Setup: Hardware Connection

### 1. Flash ESP32 Firmware
Upload `src/dexter_arm_hardware/firmware/esp32_firmware_wireless.ino` to your ESP32:

**Using Arduino IDE:**
- Open Arduino IDE
- Load the `.ino` file
- Select ESP32 board
- Click Upload

**Using PlatformIO:**
```bash
cd src/dexter_arm_hardware/firmware
pio run -t upload
```

### 2. Connect ESP32 to Network
- ESP32 should be on same WiFi as control laptop
- Verify connectivity (ESP32 should respond to `/esp32/joint_commands` topic)

### 3. Launch Hardware Bringup
```bash
source install/setup.bash
ros2 launch dexter_arm_hardware hardware_bringup.launch.py
```

---

## System Architecture Overview

```
┌─────────────────────────────────────┐
│   Control Center (Port 8090)        │
│   - Web UI Dashboard                │
│   - Shape trajectory builder        │
│   - ROS session management          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Middleware API (Port 8080)        │
│   - FastAPI endpoints               │
│   - ROS bridge commands             │
│   - Trajectory execution            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   ROS2 Control Center (Jazzy)       │
│   - Joint trajectory controllers    │
│   - MoveIt motion planning          │
│   - ros2_control framework          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│   Hardware Interface Plugin         │
│   - Command/state translation       │
│   - Prismatic↔Revolute conversion   │
│   - 16→14 joint frame conversion    │
└──────────────┬──────────────────────┘
               │
    ╔══════════▼══════════╗
    │  ESP32 (Micro-ROS) │
    │  - UDP/WiFi bridge │
    │  - PWM servo driver│
    ╚══════════┬══════════╝
               │
    ┌──────────▼──────────┐
    │  Dexter Arm Robot   │
    │  - 6 DOF arm        │
    │  - 2 grippers       │
    │  - 14 servo motors  │
    └─────────────────────┘
```

---

## Next Steps

1. **Verify workspace:** `source install/setup.bash && ros2 pkg list | grep dexter`
2. **Check middleware:** `bash scripts/launch_control_center.sh`
3. **Test MoveIt:** `ros2 launch dexter_arm_moveit_config moveit.launch.py`
4. **Upload firmware:** Flash ESP32 with updated firmware
5. **Run smoke test:** `bash scripts/trajectory_smoke_test.sh`

---

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review setup script output for error messages
3. Check build logs: `cat log/latest_build/*/stdout`
4. Verify ROS2 installation: `ros2 doctor`

---

## Version Information

- **Project:** Dexter Robotics
- **OS:** Ubuntu 24.04 LTS
- **ROS2:** Jazzy
- **Python:** 3.12+
- **Build System:** colcon
- **Middleware:** FastAPI + Uvicorn

Last updated: March 25, 2026
