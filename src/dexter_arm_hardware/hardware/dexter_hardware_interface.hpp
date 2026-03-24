#ifndef DEXTER_ARM_HARDWARE__DEXTER_HARDWARE_INTERFACE_HPP_
#define DEXTER_ARM_HARDWARE__DEXTER_HARDWARE_INTERFACE_HPP_

#include <memory>
#include <string>
#include <array>
#include <cstdint>
#include <vector>

#include "hardware_interface/handle.hpp"
#include "hardware_interface/hardware_info.hpp"
#include "hardware_interface/system_interface.hpp"
#include "hardware_interface/types/hardware_interface_return_values.hpp"
#include "rclcpp/macros.hpp"
#include "rclcpp_lifecycle/node_interfaces/lifecycle_node_interface.hpp"
#include "rclcpp_lifecycle/state.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/float64_multi_array.hpp"

namespace dexter_arm_hardware
{

class DexterHardwareInterface : public hardware_interface::SystemInterface
{
public:
  RCLCPP_SHARED_PTR_DEFINITIONS(DexterHardwareInterface)

  hardware_interface::CallbackReturn on_init(
    const hardware_interface::HardwareComponentInterfaceParams & params) override;

  hardware_interface::CallbackReturn on_configure(
    const rclcpp_lifecycle::State & previous_state) override;

  std::vector<hardware_interface::StateInterface> export_state_interfaces() override;

  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override;

  hardware_interface::CallbackReturn on_activate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::CallbackReturn on_deactivate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::return_type read(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

  hardware_interface::return_type write(
    const rclcpp::Time & time, const rclcpp::Duration & period) override;

private:
  // 16 joints total, but only 12 controlled (grippers excluded)
  std::vector<double> hw_positions_;
  std::vector<double> hw_velocities_;
  std::vector<double> hw_commands_;
  
  // micro-ROS communication (Phase 3)
  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr command_pub_;
  rclcpp::Subscription<std_msgs::msg::Float64MultiArray>::SharedPtr state_sub_;
  rclcpp::Subscription<std_msgs::msg::Float64MultiArray>::SharedPtr health_sub_;
  
  std_msgs::msg::Float64MultiArray latest_state_msg_;
  bool state_received_ = false;
  bool link_health_received_ = false;
  bool link_healthy_ = true;
  uint32_t command_sequence_ = 0;
  uint32_t last_timeout_events_ = 0;
  std::array<double, 14> last_published_targets_{};
  bool last_targets_initialized_ = false;
  rclcpp::Time last_state_rx_time_{0, 0, RCL_ROS_TIME};
  rclcpp::Time last_health_rx_time_{0, 0, RCL_ROS_TIME};
  
  void state_callback(const std_msgs::msg::Float64MultiArray::SharedPtr msg);
  void health_callback(const std_msgs::msg::Float64MultiArray::SharedPtr msg);
};

}  // namespace dexter_arm_hardware

#endif  // DEXTER_ARM_HARDWARE__DEXTER_HARDWARE_INTERFACE_HPP_
