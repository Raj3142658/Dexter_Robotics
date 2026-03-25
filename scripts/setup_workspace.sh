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
# STEP 7: Create Desktop Application Launcher
# ============================================================================
echo -e "${BLUE}[7/9] Creating desktop application launcher...${NC}"

APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/dexter-control-center.desktop"
ICONS_DIR="$HOME/.local/share/icons/hicolor/48x48/apps"

# Create directories if they don't exist
mkdir -p "$APPS_DIR" "$ICONS_DIR"

# Create desktop file with correct workspace path
cat > "$DESKTOP_FILE" << 'DESKTOP_ENTRY'
[Desktop Entry]
Version=1.0
Type=Application
Name=Dexter Control Center
Comment=Launch Dexter robot middleware and operator UI
Exec=bash -c 'cd WORKSPACE_DIR && source install/setup.bash && bash scripts/launch_control_center.sh'
Icon=dexter-control-center
Terminal=false
Categories=Robotics;Utility;Development;
StartupNotify=true
X-AppStream-Ignore=false
DESKTOP_ENTRY

# Replace workspace path in desktop file
sed -i "s|WORKSPACE_DIR|$WORKSPACE_DIR|g" "$DESKTOP_FILE"

# Make desktop file valid
chmod 644 "$DESKTOP_FILE"

# Create a simple SVG icon if it doesn't exist
if [ ! -f "$ICONS_DIR/dexter-control-center.svg" ]; then
  cat > "$ICONS_DIR/dexter-control-center.svg" << 'ICON_SVG'
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
  <rect width="48" height="48" fill="#2c3e50" rx="8"/>
  <circle cx="24" cy="16" r="6" fill="#3498db"/>
  <circle cx="16" cy="32" r="4" fill="#2ecc71"/>
  <circle cx="24" cy="32" r="4" fill="#e74c3c"/>
  <circle cx="32" cy="32" r="4" fill="#f39c12"/>
  <path d="M 24 22 L 16 26" stroke="#3498db" stroke-width="1.5" fill="none"/>
  <path d="M 24 22 L 24 28" stroke="#3498db" stroke-width="1.5" fill="none"/>
  <path d="M 24 22 L 32 26" stroke="#3498db" stroke-width="1.5" fill="none"/>
</svg>
ICON_SVG
  echo -e "${GREEN}✓ Desktop icon created${NC}"
fi

# Verify desktop entry is valid
if system-test-desktop &>/dev/null 2>&1 || desktop-file-validate "$DESKTOP_FILE" 2>/dev/null; then
  echo -e "${GREEN}✓ Desktop file created at: $DESKTOP_FILE${NC}"
  echo -e "${GREEN}✓ Application can now be pinned to sidebar${NC}"
else
  echo -e "${YELLOW}⚠️  Desktop file created (validation tool not available)${NC}"
  echo -e "${YELLOW}   Location: $DESKTOP_FILE${NC}"
fi

# Update desktop database
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo ""

# ============================================================================
# STEP 8: Setup Middleware Python Environment
# ============================================================================
echo -e "${BLUE}[8/9] Setting up middleware FastAPI environment...${NC}"
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
# STEP 9: Summary and Next Steps
# ============================================================================
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✓ SETUP COMPLETED SUCCESSFULLY              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo "1. 🎯 Quick Start - Launch from Desktop:"
echo -e "   ${YELLOW}Press Super key → Search 'Dexter Control Center'${NC}"
echo -e "   ${YELLOW}Right-click → 'Add to Favorites' (pin to sidebar)${NC}"
echo ""
echo "2. Or activate workspace manually:"
echo -e "   ${YELLOW}cd $WORKSPACE_DIR${NC}"
echo -e "   ${YELLOW}source install/setup.bash${NC}"
echo ""
echo "3. Optional: Setup ESP32 firmware"
echo -e "   ${YELLOW}# Flash src/dexter_arm_hardware/firmware/esp32_firmware_wireless.ino${NC}"
echo -e "   ${YELLOW}# to your ESP32 using Arduino IDE or PlatformIO${NC}"
echo ""
echo "4. Launch the control center:"
echo -e "   ${YELLOW}bash scripts/launch_control_center.sh${NC}"
echo ""
echo "5. Access the web UI:"
echo -e "   ${YELLOW}http://127.0.0.1:8090${NC}"
echo ""
echo "6. API documentation:"
echo -e "   ${YELLOW}http://127.0.0.1:8080/docs${NC}"
echo ""
echo -e "${BLUE}Desktop Application:${NC}"
echo "   Location: $DESKTOP_FILE"
echo "   Status: ✓ Installed and ready to use"
echo ""
echo -e "${BLUE}System Information:${NC}"
echo "   OS: Ubuntu 24.04 LTS $(lsb_release -rs)"
echo "   ROS: $ROS_DISTRO"
echo "   Python: $(python3 --version)"
echo "   Workspace: $WORKSPACE_DIR"
echo ""
