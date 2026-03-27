cmake_minimum_required(VERSION 3.8)
project(dexter_arm_trajectory_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(trajectory_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/ExecutionProgress.msg"
  "srv/CaptureSegment.srv"
  "srv/CompileTrajectory.srv"
  "srv/SaveTrajectory.srv"
  "srv/LoadTrajectory.srv"
  "srv/GetStatus.srv"
  "srv/ExecuteTrajectory.srv"
  "srv/GenerateShapeTrajectory.srv"
  "srv/InjectTrajectory.srv"
  DEPENDENCIES trajectory_msgs
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()
