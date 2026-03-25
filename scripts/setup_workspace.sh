#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get workspace directory
WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIDDLEWARE_DIR="$WORKSPACE_DIR/src/dexter_middleware"

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Dexter Robotics Workspace Setup (Ubuntu 24.04)    ║${NC}"
echo -e "${BLUE}║     ROS2 Jazzy + Hardware Interface + Middleware      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# STEP 1: Check Python3 Installation
# ============================================================================
echo -e "${BLUE}[1/7] Checking Python3 installation...${NC}"
if ! command -v python3 &> /dev/null; then
  echo -e "${YELLOW}⚠️  Python3 not found. Installing Python3.12...${NC}"
  sudo apt-get update
  sudo apt-get install -y python3.12 python3.12-venv python3-pip
  echo -e "${GREEN}✓ Python3.12 installed${NC}"
else
  PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
  echo -e "${GREEN}✓ Python3 found (v$PYTHON_VERSION)${NC}"
fi

# Verify python3 is executable
if ! python3 -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}')" &> /dev/null; then
  echo -e "${RED}✗ Python3 verification failed${NC}"
  exit 1
fi
echo ""

# ============================================================================
# STEP 2: Check ROS2 Installation
# ============================================================================
echo -e "${BLUE}[2/7] Checking ROS2 installation...${NC}"
if [ -z "${ROS_DISTRO:-}" ]; then
  echo -e "${YELLOW}⚠️  ROS2 environment not sourced. Attempting to source Jazzy...${NC}"
  if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    source /opt/ros/jazzy/setup.bash
    echo -e "${GREEN}✓ ROS2 Jazzy sourced${NC}"
  else
    echo -e "${RED}✗ ROS2 Jazzy not found at /opt/ros/jazzy/setup.bash${NC}"
    echo "Please install ROS2 Jazzy first:"
    echo "  https://docs.ros.org/en/jazzy/Installation.html"
    exit 1
  fi
else
  echo -e "${GREEN}✓ ROS2 already sourced (${ROS_DISTRO})${NC}"
fi

# Verify it's Jazzy
if [ "$ROS_DISTRO" != "jazzy" ]; then
  echo -e "${YELLOW}⚠️  ROS_DISTRO is '${ROS_DISTRO}' but 'jazzy' is recommended${NC}"
fi
echo ""

# ============================================================================
# STEP 3: Check Essential Build Tools
# ============================================================================
echo -e "${BLUE}[3/7] Checking build tools...${NC}"
MISSING_TOOLS=()

if ! command -v colcon &> /dev/null; then
  MISSING_TOOLS+=("ros-jazzy-colcon-common-extensions")
fi

if ! command -v gcc &> /dev/null; then
  MISSING_TOOLS+=("build-essential")
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
  echo -e "${YELLOW}Installing missing tools: ${MISSING_TOOLS[@]}${NC}"
  sudo apt-get update
  sudo apt-get install -y "${MISSING_TOOLS[@]}"
  echo -e "${GREEN}✓ Build tools installed${NC}"
else
  echo -e "${GREEN}✓ All build tools present (colcon, gcc)${NC}"
fi
echo ""

# ============================================================================
# STEP 4: Install ROS2 Package Dependencies
# ============================================================================
echo -e "${BLUE}[4/7] Installing ROS2 package dependencies...${NC}"
if ! command -v rosdep &> /dev/null; then
  echo -e "${YELLOW}Installing rosdep...${NC}"
  sudo apt-get install -y python3-rosdep2
fi

# Ensure rosdep is initialized
if [ ! -d "/etc/ros/rosdep" ]; then
  echo -e "${YELLOW}Initializing rosdep database...${NC}"
  sudo rosdep init
fi
rosdep update

# Install dependencies from package.xml files
echo -e "${YELLOW}Running rosdep install...${NC}"
cd "$WORKSPACE_DIR"
rosdep install --from-paths src --ignore-src -r -y
echo -e "${GREEN}✓ ROS2 dependencies installed${NC}"
echo ""

# ============================================================================
# STEP 5: Clean and Build with Colcon
# ============================================================================
echo -e "${BLUE}[5/7] Building ROS2 packages with colcon...${NC}"
cd "$WORKSPACE_DIR"

# Clean old build artifacts
if [ -d "build" ] || [ -d "install" ]; then
  echo -e "${YELLOW}Cleaning previous build artifacts...${NC}"
  rm -rf build install log
  echo -e "${GREEN}✓ Cleaned${NC}"
fi

# Build
echo -e "${YELLOW}Running: colcon build --symlink-install${NC}"
if colcon build --symlink-install; then
  echo -e "${GREEN}✓ Build completed successfully${NC}"
else
  echo -e "${RED}✗ Build failed. Check logs above.${NC}"
  exit 1
fi
echo ""

# ============================================================================
# STEP 6: Verify Hardware Interface Plugin
# ============================================================================
echo -e "${BLUE}[6/7] Verifying hardware interface plugin...${NC}"
if [ -f "$WORKSPACE_DIR/install/dexter_arm_hardware/lib/libdexter_hardware_interface.so" ]; then
  echo -e "${GREEN}✓ Hardware interface plugin built successfully${NC}"
else
  echo -e "${YELLOW}⚠️  Hardware interface plugin not found (may be expected on first build)${NC}"
fi
echo ""

# ============================================================================
# STEP 7: Setup Middleware Python Environment
# ============================================================================
echo -e "${BLUE}[7/7] Setting up middleware FastAPI environment...${NC}"
if [ ! -d "$MIDDLEWARE_DIR" ]; then
  echo -e "${RED}✗ Middleware directory not found at: $MIDDLEWARE_DIR${NC}"
  exit 1
fi

cd "$MIDDLEWARE_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
  echo -e "${YELLOW}Creating Python virtual environment...${NC}"
  python3 -m venv .venv
  echo -e "${GREEN}✓ Virtual environment created${NC}"
else
  echo -e "${GREEN}✓ Virtual environment already exists${NC}"
fi

# Activate and install requirements
echo -e "${YELLOW}Installing middleware dependencies...${NC}"
source .venv/bin/activate

# Upgrade pip first
pip install --upgrade pip setuptools wheel > /dev/null 2>&1

# Install requirements
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
  echo -e "${GREEN}✓ Middleware dependencies installed${NC}"
else
  echo -e "${YELLOW}⚠️  requirements.txt not found${NC}"
fi

deactivate
echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✓ SETUP COMPLETED SUCCESSFULLY              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo "1. Activate the workspace:"
echo -e "   ${YELLOW}cd $WORKSPACE_DIR${NC}"
echo -e "   ${YELLOW}source install/setup.bash${NC}"
echo ""
echo "2. Optional: Setup ESP32 firmware"
echo -e "   ${YELLOW}# Flash src/dexter_arm_hardware/firmware/esp32_firmware_wireless.ino${NC}"
echo -e "   ${YELLOW}# to your ESP32 using Arduino IDE or PlatformIO${NC}"
echo ""
echo "3. Launch the control center:"
echo -e "   ${YELLOW}bash scripts/launch_control_center.sh${NC}"
echo ""
echo "4. Access the web UI:"
echo -e "   ${YELLOW}http://127.0.0.1:8090${NC}"
echo ""
echo "5. API documentation:"
echo -e "   ${YELLOW}http://127.0.0.1:8080/docs${NC}"
echo ""
echo -e "${BLUE}System Information:${NC}"
echo "   OS: Ubuntu 24.04 LTS $(lsb_release -rs)"
echo "   ROS: $ROS_DISTRO"
echo "   Python: $(python3 --version)"
echo "   Workspace: $WORKSPACE_DIR"
echo ""
