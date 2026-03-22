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
  
  // Initialize all positions to zero (safe start position)
  for (size_t i = 0; i < hw_positions_.size(); i++)
  {
    hw_positions_[i] = 0.0;
    hw_velocities_[i] = 0.0;
    hw_commands_[i] = 0.0;
  }
  
  latest_state_msg_.data.resize(12, 0.0);

  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Successfully configured!");
  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Optimized QoS: depth=1, best_effort");
  return hardware_interface::CallbackReturn::SUCCESS;
}

void DexterHardwareInterface::state_callback(
  const std_msgs::msg::Float64MultiArray::SharedPtr msg)
{
  // Store received states from ESP32 
  // Supports both 14-joint (new) and 12-joint (old) firmware
  if (msg->data.size() == 14 || msg->data.size() == 12)
  {
    latest_state_msg_ = *msg;
    state_received_ = true;
  }
  else
  {
    RCLCPP_WARN(
      rclcpp::get_logger("DexterHardwareInterface"),
      "Received state with wrong size: %zu (expected 14 or 12)", msg->data.size());
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
  
  // Set commands to current positions to avoid jump
  for (size_t i = 0; i < hw_positions_.size(); i++)
  {
    hw_commands_[i] = hw_positions_[i];
  }

  RCLCPP_INFO(rclcpp::get_logger("DexterHardwareInterface"), "Successfully activated!");
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
    
    // GRIPPER CONVERSION: Revolute (0..3.14 rad) -> Prismatic (0..-0.022 m)
    
    // Left Gripper: ESP Index 6 -> ROS Indices 6 (j7l1) and 7 (j7l2)
    double left_servo_rad = latest_state_msg_.data[6];
    double left_prism_m = (left_servo_rad / 3.14159) * -0.022;
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
  if (command_pub_) {
    std_msgs::msg::Float64MultiArray cmd_msg;
    cmd_msg.data.resize(14);  // Hardware expects 14 joints
    
    // ABSTRACTION LAYER: Map ROS (16 Prismatic) -> Hardware (14 Revolute)
    // ROS Indices: 0-5 (Left Arm), 6-11 (Right Arm), 12-13 (Left Gripper), 14-15 (Right Gripper)
    // ESP32 Indices: 0-5 (Left Arm), 6 (Left Gripper Servo), 7-12 (Right Arm), 13 (Right Gripper Servo)
    
    // Left Arm (ROS 0-5 -> ESP 0-5)
    for (size_t i = 0; i < 6; i++) {
      cmd_msg.data[i] = hw_commands_[i];
    }

    // Right Arm (ROS 8-13 -> ESP 7-12)
    for (size_t i = 0; i < 6; i++) {
      cmd_msg.data[i + 7] = hw_commands_[i + 8];
    }
    
    // GRIPPER CONVERSION: Prismatic -> Revolute
    // Map ONLY primary joints: j7l1 (Index 6) and j7r1 (Index 14)
    
    // Left Gripper: j7l1 (ROS Index 6) -> ESP Index 6
    double left_cmd_m = hw_commands_[6];  // j7l1
    double left_servo_rad = (left_cmd_m / -0.022) * 3.14159;
    left_servo_rad = std::max(0.0, std::min(3.14159, left_servo_rad));
    cmd_msg.data[6] = left_servo_rad;

    // Right Gripper: j7r1 (ROS Index 14) -> ESP Index 13
    double right_cmd_m = hw_commands_[14];  // j7r1
    double right_servo_rad = (right_cmd_m / -0.022) * 3.14159;
    right_servo_rad = std::max(0.0, std::min(3.14159, right_servo_rad));
    cmd_msg.data[13] = right_servo_rad;
    
    command_pub_->publish(cmd_msg);
  }

  return hardware_interface::return_type::OK;
}

}  // namespace dexter_arm_hardware

#include "pluginlib/class_list_macros.hpp"
PLUGINLIB_EXPORT_CLASS(
  dexter_arm_hardware::DexterHardwareInterface, hardware_interface::SystemInterface)
