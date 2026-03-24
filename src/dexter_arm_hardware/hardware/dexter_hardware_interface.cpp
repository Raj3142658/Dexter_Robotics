#include "dexter_hardware_interface.hpp"

#include <chrono>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "rclcpp/rclcpp.hpp"

namespace dexter_arm_hardware
{

namespace {
constexpr double PI = 3.14159;
constexpr double TWO_PI = 2.0 * PI;
constexpr double LEFT_GRIPPER_TRAVEL_M = 0.04;  // 0.0=open, -0.04=closed
constexpr size_t NUM_HW_JOINTS = 14;
constexpr size_t HEALTH_MSG_FIELDS = 11;
constexpr double STATE_STALE_TIMEOUT_S = 0.8;
constexpr double HEALTH_STALE_TIMEOUT_S = 1.2;
constexpr double MAX_HOST_CMD_DELTA_RAD = 0.35;
}  // namespace

hardware_interface::CallbackReturn DexterHardwareInterface::on_init(
  const hardware_interface::HardwareComponentInterfaceParams & params)
{
  if (
    hardware_interface::SystemInterface::on_init(params) !=
    hardware_interface::CallbackReturn::SUCCESS)
  {
    return hardware_interface::CallbackReturn::ERROR;
  }

  // Expect 16 joints (6 Arm L + 6 Arm R + 2 Gripper L + 2 Gripper R)
  if (info_.joints.size() != 16)
  {
    RCLCPP_ERROR(
      rclcpp::get_logger("DexterHardwareInterface"),
      "Expected 16 joints (12 Arm + 4 Gripper Fingers), got %zu", info_.joints.size());
    return hardware_interface::CallbackReturn::ERROR;
  }

  // Initialize storage
  hw_positions_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_velocities_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());
  hw_commands_.resize(info_.joints.size(), std::numeric_limits<double>::quiet_NaN());

  for (const hardware_interface::ComponentInfo & joint : info_.joints)
  {
    if (joint.command_interfaces.size() != 1)
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("DexterHardwareInterface"),
        "Joint '%s' has %zu command interfaces. Expected 1.", joint.name.c_str(),
        joint.command_interfaces.size());
      return hardware_interface::CallbackReturn::ERROR;
    }

    if (joint.command_interfaces[0].name != hardware_interface::HW_IF_POSITION)
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("DexterHardwareInterface"),
        "Joint '%s' has command interface '%s'. Expected position.",
        joint.name.c_str(), joint.command_interfaces[0].name.c_str());
      return hardware_interface::CallbackReturn::ERROR;
    }

    if (joint.state_interfaces.size() != 2)
    {
      RCLCPP_ERROR(
        rclcpp::get_logger("DexterHardwareInterface"),
        "Joint '%s' has %zu state interfaces. Expected 2.", joint.name.c_str(),
        joint.state_interfaces.size());
      return hardware_interface::CallbackReturn::ERROR;
    }
  }

  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Successfully initialized!");
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn DexterHardwareInterface::on_configure(
  const rclcpp_lifecycle::State & /*previous_state*/)
{
  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Configuring hardware...");
  
  // Create ROS node for micro-ROS communication
  if (!node_) {
    node_ = rclcpp::Node::make_shared("dexter_hardware_interface_node");
  }
  
  // Optimized QoS for low-latency real-time communication
  auto qos = rclcpp::QoS(rclcpp::KeepLast(1))  // Depth 1 - only latest message
    .best_effort()                              // Don't wait for ACK
    .durability_volatile();                     // Don't store history
  
  // Publisher for commands to ESP32 (12 joints)
  command_pub_ = node_->create_publisher<std_msgs::msg::Float64MultiArray>(
    "/esp32/joint_commands", qos);
  
  // Subscriber for states from ESP32 (12 joints)  
  state_sub_ = node_->create_subscription<std_msgs::msg::Float64MultiArray>(
    "/esp32/joint_states", qos,
    std::bind(&DexterHardwareInterface::state_callback, this, std::placeholders::_1));

  // Subscriber for ESP32 link health telemetry (11 fields)
  health_sub_ = node_->create_subscription<std_msgs::msg::Float64MultiArray>(
    "/esp32/link_health", qos,
    std::bind(&DexterHardwareInterface::health_callback, this, std::placeholders::_1));
  
  // Initialize all positions to NaN (will be updated by first state message from ESP32)
  for (size_t i = 0; i < hw_positions_.size(); i++)
  {
    hw_positions_[i] = std::numeric_limits<double>::quiet_NaN();
    hw_velocities_[i] = 0.0;
    hw_commands_[i] = std::numeric_limits<double>::quiet_NaN();
  }
  
  latest_state_msg_.data.resize(12, 0.0);

  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Successfully configured!");
  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Optimized QoS: depth=1, best_effort");
  RCLCPP_WARN(rclcpp::get_logger("DexterHardwareInterface"),
    "Positions initialized to NaN - will be updated by first state message from ESP32");
  return hardware_interface::CallbackReturn::SUCCESS;
}

void DexterHardwareInterface::state_callback(
  const std_msgs::msg::Float64MultiArray::SharedPtr msg)
{
  // Store received states from ESP32 
  // Supports both 14-joint (new) and 12-joint (old) firmware
  if (msg->data.size() == 14 || msg->data.size() == 12)
  {
    for (double value : msg->data) {
      if (!std::isfinite(value)) {
        RCLCPP_WARN(
          rclcpp::get_logger("DexterHardwareInterface"),
          "Dropped state frame with non-finite values");
        return;
      }
    }
    latest_state_msg_ = *msg;
    state_received_ = true;
    if (node_) {
      last_state_rx_time_ = node_->now();
    }
  }
  else
  {
    RCLCPP_WARN(
      rclcpp::get_logger("DexterHardwareInterface"),
      "Received state with wrong size: %zu (expected 14 or 12)", msg->data.size());
  }
}

void DexterHardwareInterface::health_callback(
  const std_msgs::msg::Float64MultiArray::SharedPtr msg)
{
  if (msg->data.size() < HEALTH_MSG_FIELDS) {
    return;
  }

  for (size_t i = 0; i < HEALTH_MSG_FIELDS; ++i) {
    if (!std::isfinite(msg->data[i])) {
      return;
    }
  }

  // Firmware health payload fields:
  // [0]=uptime_ms, [1]=cmd_age_ms, [7]=timeout_events, [10]=wifi_connected
  const double cmd_age_ms = msg->data[1];
  const uint32_t timeout_events = static_cast<uint32_t>(std::max(0.0, msg->data[7]));
  const bool wifi_connected = msg->data[10] >= 0.5;

  if (timeout_events > last_timeout_events_) {
    RCLCPP_WARN(
      rclcpp::get_logger("DexterHardwareInterface"),
      "ESP32 reported stale command timeout event (%u -> %u)",
      last_timeout_events_, timeout_events);
  }
  last_timeout_events_ = timeout_events;

  link_healthy_ = wifi_connected && (cmd_age_ms < 450.0);
  link_health_received_ = true;
  if (node_) {
    last_health_rx_time_ = node_->now();
  }
}

std::vector<hardware_interface::StateInterface>
DexterHardwareInterface::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> state_interfaces;
  for (size_t i = 0; i < info_.joints.size(); i++)
  {
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_POSITION, &hw_positions_[i]));
    state_interfaces.emplace_back(hardware_interface::StateInterface(
      info_.joints[i].name, hardware_interface::HW_IF_VELOCITY, &hw_velocities_[i]));
  }
  return state_interfaces;
}

std::vector<hardware_interface::CommandInterface>
DexterHardwareInterface::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> command_interfaces;
  for (size_t i = 0; i < info_.joints.size(); i++)
  {
    command_interfaces.emplace_back(hardware_interface::CommandInterface(
      info_.joints[i].name, hardware_interface::HW_IF_POSITION, &hw_commands_[i]));
  }
  return command_interfaces;
}

hardware_interface::CallbackReturn DexterHardwareInterface::on_activate(
  const rclcpp_lifecycle::State & /*previous_state*/)
{
  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Activating hardware...");
  
  if (!state_received_) {
    RCLCPP_WARN(rclcpp::get_logger("DexterHardwareInterface"),
      "\n" 
      "╔════════════════════════════════════════════════════════╗\n"
      "║         ⚠️  STATE SYNCHRONIZATION WARNING  ⚠️          ║\n"
      "╠════════════════════════════════════════════════════════╣\n"
      "║ No state message received from ESP32 yet!              ║\n"
      "║                                                        ║\n"
      "║ This means:                                            ║\n"
      "║ 1. ESP32 may not have started yet                      ║\n"
      "║ 2. WiFi connection to micro-ROS agent is failing      ║\n"
      "║ 3. ROS cannot read actual motor positions              ║\n"
      "║                                                        ║\n"
      "║ RESULT: Robot position in RViz will NOT match          ║\n"
      "║ actual physical position!                              ║\n"
      "║                                                        ║\n"
      "║ ACTION: Check that:                                    ║\n"
      "║ • ESP32 is powered and connected to WiFi               ║\n"
      "║ • micro-ROS agent is running: /esp32/joint_states      ║\n"
      "║ • Network connectivity is stable                       ║\n"
      "╚════════════════════════════════════════════════════════╝");
  }
  
  // Set commands to current positions (from first state, or NaN if no state yet)
  for (size_t i = 0; i < hw_positions_.size(); i++)
  {
    if (std::isnan(hw_positions_[i])) {
      // No state received - use safe default to avoid dangerous jumps
      hw_commands_[i] = 0.0;
      RCLCPP_WARN_ONCE(rclcpp::get_logger("DexterHardwareInterface"),
        "Position for joint %zu is NaN (no state); using 0.0 as fallback", i);
    }
    else {
      hw_commands_[i] = hw_positions_[i];
    }
  }

  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Successfully activated!");
  if (state_received_) {
    RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), 
      "✓ Hardware state synchronized with ESP32");
  }
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn DexterHardwareInterface::on_deactivate(
  const rclcpp_lifecycle::State & /*previous_state*/)
{
  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Deactivating hardware...");
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::return_type DexterHardwareInterface::read(
  const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
{
  // Spin node to process callbacks
  if (node_) {
    rclcpp::spin_some(node_);
  }
  
  if (state_received_ && latest_state_msg_.data.size() == 14)
  {
    // ABSTRACTION LAYER: Map Hardware (14 Revolute) -> ROS (16 Prismatic)
    // ESP32 Indices: 0-5 (Left Arm), 6 (Left Gripper Servo), 7-12 (Right Arm), 13 (Right Gripper Servo)
    // ROS Indices: 0-5 (Left Arm), 6-11 (Right Arm), 12-13 (Left Gripper Fingers), 14-15 (Right Gripper Fingers)
    
    // Left Arm (ESP 0-5 -> ROS 0-5)
    for (size_t i = 0; i < 6; i++) {
      hw_positions_[i] = latest_state_msg_.data[i];
      hw_velocities_[i] = 0.0;
    }

    // Right Arm (ESP 7-12 -> ROS 8-13)
    for (size_t i = 0; i < 6; i++) {
      hw_positions_[i + 8] = latest_state_msg_.data[i + 7];
      hw_velocities_[i + 8] = 0.0;
    }
    
    // GRIPPER CONVERSION: Revolute (0..2*pi rad) -> Prismatic (0.0..-0.04 m)
    
    // Left Gripper: ESP Index 6 -> ROS Indices 6 (j7l1) and 7 (j7l2)
    double left_servo_rad = latest_state_msg_.data[6];
    // 0 rad -> 0.0 m (open), 2*pi rad -> -0.04 m (closed)
    double left_prism_m = -((left_servo_rad / TWO_PI) * LEFT_GRIPPER_TRAVEL_M);
    left_prism_m = std::max(-LEFT_GRIPPER_TRAVEL_M, std::min(0.0, left_prism_m));
    hw_positions_[6] = left_prism_m;  // j7l1
    hw_positions_[7] = left_prism_m;  // j7l2
    hw_velocities_[6] = 0.0;
    hw_velocities_[7] = 0.0;

    // Right Gripper: ESP Index 13 -> ROS Indices 14 (j7r1) and 15 (j7r2)
    double right_servo_rad = latest_state_msg_.data[13];
    double right_prism_m = (right_servo_rad / 3.14159) * -0.022;
    hw_positions_[14] = right_prism_m;  // j7r1
    hw_positions_[15] = right_prism_m;  // j7r2
    hw_velocities_[14] = 0.0;
    hw_velocities_[15] = 0.0;
  }
  else
  {
    // No state received yet, mirror all commands
    for (size_t i = 0; i < hw_positions_.size(); i++)
    {
      hw_positions_[i] = hw_commands_[i];
      hw_velocities_[i] = 0.0;
    }
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::return_type DexterHardwareInterface::write(
  const rclcpp::Time & /*time*/, const rclcpp::Duration & /*period*/)
{
  if (!command_pub_) {
    return hardware_interface::return_type::OK;
  }

  std_msgs::msg::Float64MultiArray cmd_msg;
  cmd_msg.data.resize(16);  // [14 joints] + [sequence] + [sender monotonic ms]

  auto sanitize_joint = [this](size_t idx) {
      const double cmd = hw_commands_[idx];
      if (std::isfinite(cmd)) {
        return cmd;
      }
      if (std::isfinite(hw_positions_[idx])) {
        return hw_positions_[idx];
      }
      return 0.0;
    };

  // ABSTRACTION LAYER: Map ROS (16 Prismatic) -> Hardware (14 Revolute)
  // ROS Indices: 0-5 (Left Arm), 6-7 (Left Gripper), 8-13 (Right Arm), 14-15 (Right Gripper)
  // ESP32 Indices: 0-5 (Left Arm), 6 (Left Gripper Servo), 7-12 (Right Arm), 13 (Right Gripper Servo)

  // Left Arm (ROS 0-5 -> ESP 0-5)
  for (size_t i = 0; i < 6; i++) {
    cmd_msg.data[i] = sanitize_joint(i);
  }

  // Right Arm (ROS 8-13 -> ESP 7-12)
  for (size_t i = 0; i < 6; i++) {
    cmd_msg.data[i + 7] = sanitize_joint(i + 8);
  }

  // GRIPPER CONVERSION: Prismatic -> Revolute
  // Map ONLY primary joints: j7l1 (Index 6) and j7r1 (Index 14)

  // Left Gripper: j7l1 (ROS Index 6) -> ESP Index 6
  double left_cmd_m = sanitize_joint(6);  // j7l1
  left_cmd_m = std::max(-LEFT_GRIPPER_TRAVEL_M, std::min(0.0, left_cmd_m));
  // 0.0 m -> 0 rad, -0.04 m -> 2*pi rad
  double left_servo_rad = ((-left_cmd_m) / LEFT_GRIPPER_TRAVEL_M) * TWO_PI;
  left_servo_rad = std::max(0.0, std::min(TWO_PI, left_servo_rad));
  cmd_msg.data[6] = left_servo_rad;

  // Right Gripper: j7r1 (ROS Index 14) -> ESP Index 13
  double right_cmd_m = sanitize_joint(14);  // j7r1
  double right_servo_rad = (right_cmd_m / -0.022) * PI;
  right_servo_rad = std::max(0.0, std::min(PI, right_servo_rad));
  cmd_msg.data[13] = right_servo_rad;

  // Host-side per-frame clamp to reject sudden target jumps before they hit firmware.
  if (last_targets_initialized_) {
    for (size_t i = 0; i < NUM_HW_JOINTS; ++i) {
      const double delta = cmd_msg.data[i] - last_published_targets_[i];
      if (delta > MAX_HOST_CMD_DELTA_RAD) {
        cmd_msg.data[i] = last_published_targets_[i] + MAX_HOST_CMD_DELTA_RAD;
      } else if (delta < -MAX_HOST_CMD_DELTA_RAD) {
        cmd_msg.data[i] = last_published_targets_[i] - MAX_HOST_CMD_DELTA_RAD;
      }
    }
  }

  bool state_fresh = state_received_;
  bool health_fresh = true;
  if (node_) {
    const auto now = node_->now();
    if (state_received_) {
      state_fresh = (now - last_state_rx_time_) < rclcpp::Duration::from_seconds(STATE_STALE_TIMEOUT_S);
    }
    if (link_health_received_) {
      health_fresh = (now - last_health_rx_time_) <
        rclcpp::Duration::from_seconds(HEALTH_STALE_TIMEOUT_S);
    }
  }

  // Degraded mode: hold last published targets when link/state freshness is lost.
  const bool can_track_commands = state_fresh && health_fresh && link_healthy_;
  if (!can_track_commands && last_targets_initialized_) {
    for (size_t i = 0; i < NUM_HW_JOINTS; ++i) {
      cmd_msg.data[i] = last_published_targets_[i];
    }
    if (node_) {
      RCLCPP_WARN_THROTTLE(
        rclcpp::get_logger("DexterHardwareInterface"), *node_->get_clock(), 2000,
        "Degraded command mode active (state_fresh=%d, health_fresh=%d, link_healthy=%d)",
        state_fresh ? 1 : 0, health_fresh ? 1 : 0, link_healthy_ ? 1 : 0);
    }
  }

  for (size_t i = 0; i < NUM_HW_JOINTS; ++i) {
    last_published_targets_[i] = cmd_msg.data[i];
  }
  last_targets_initialized_ = true;

  // Metadata for firmware stale/out-of-order rejection.
  command_sequence_++;
  cmd_msg.data[14] = static_cast<double>(command_sequence_);
  const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
  cmd_msg.data[15] = static_cast<double>(now_ms);

  command_pub_->publish(cmd_msg);

  return hardware_interface::return_type::OK;
}

}  // namespace dexter_arm_hardware

#include "pluginlib/class_list_macros.hpp"
PLUGINLIB_EXPORT_CLASS(
  dexter_arm_hardware::DexterHardwareInterface, hardware_interface::SystemInterface)
