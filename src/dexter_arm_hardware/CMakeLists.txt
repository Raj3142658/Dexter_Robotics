cmake_minimum_required(VERSION 3.22)
project(dexter_arm_hardware)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(hardware_interface REQUIRED)
find_package(pluginlib REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(std_msgs REQUIRED)

# Build hardware interface library
add_library(
  dexter_arm_hardware
  SHARED
  hardware/dexter_hardware_interface.cpp
)
target_include_directories(
  dexter_arm_hardware
  PRIVATE
  hardware
)
target_compile_features(dexter_arm_hardware PUBLIC cxx_std_17)
ament_target_dependencies(
  dexter_arm_hardware
  hardware_interface
  pluginlib
  rclcpp
  rclcpp_lifecycle
  std_msgs
)

# Export plugin description
pluginlib_export_plugin_description_file(hardware_interface hardware/dexter_hardware.xml)

# Install library
install(
  TARGETS dexter_arm_hardware
  DESTINATION lib
)

# Install header
install(
  DIRECTORY hardware/
  DESTINATION include/dexter_arm_hardware
  FILES_MATCHING PATTERN "*.hpp"
)

# Install launch and config files
install(DIRECTORY
  launch
  urdf
  config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
