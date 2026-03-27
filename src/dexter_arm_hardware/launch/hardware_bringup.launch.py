#!/usr/bin/env python3
"""
Hardware bringup launch for Real Dexter Arm (ESP32 + micro-ROS).
Uses dexter_arm_hardware.xacro which includes base URDF + adds ros2_control for real hardware.

Prerequisites:
  Terminal 1: Run micro-ROS agent
    source ~/microros_ws/install/setup.bash
    ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyUSB0 -b 115200
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution, LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    # Declare arguments
    declared_arguments = []
    
    declared_arguments.append(
        DeclareLaunchArgument(
            "use_rviz",
            default_value="true",
            description="Start RViz for visualization"
        )
    )
    
    declared_arguments.append(
        DeclareLaunchArgument(
            "load_moveit",
            default_value="true",
            description="Load MoveIt move_group"
        )
    )

    declared_arguments.append(
        DeclareLaunchArgument(
            "load_trajectory_system",
            default_value="true",
            description="Start dexter_arm_trajectory manager + shape generator"
        )
    )
    
    # Get configurations
    use_rviz = LaunchConfiguration("use_rviz")
    load_moveit = LaunchConfiguration("load_moveit")
    load_trajectory_system = LaunchConfiguration("load_trajectory_system")
    
    # Build MoveIt configuration
    moveit_config = (
        MoveItConfigsBuilder("dexter_arm", package_name="dexter_arm_moveit_config")
        .robot_description(file_path="config/dexter_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/dexter_arm.srdf")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .planning_pipelines(pipelines=["ompl", "chomp", "pilz_industrial_motion_planner"])
        .to_moveit_configs()
    )
    
    # Get URDF via xacro (Hardware overlay)
    robot_description_content = ParameterValue(
        Command([
            PathJoinSubstitution([FindExecutable(name="xacro")]),
            " ",
            PathJoinSubstitution([
                FindPackageShare("dexter_arm_hardware"),
                "urdf",
                "dexter_arm_hardware.xacro",
            ]),
        ]),
        value_type=str
    )
    
    # Controllers
    robot_controllers = PathJoinSubstitution([
        FindPackageShare("dexter_arm_control"),
        "config",
        "controllers.yaml"
    ])
    
    # ros2_control node
    control_node = Node(
        package="controller_manager",
        executable="ros2_control_node",
        parameters=[{"robot_description": robot_description_content}, robot_controllers, {"use_sim_time": False}],
        output="both",
    )
    
    # Robot state publisher
    robot_state_pub_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both",
        parameters=[{"robot_description": robot_description_content}, {"use_sim_time": False}],
    )
    
    # Static transform publisher
    static_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="virtual_joint_broadcaster",
        arguments=["0", "0", "0", "0", "0", "0", "world", "base_link"],
        parameters=[{"use_sim_time": False}],
    )
    
    # Spawn controllers after 6 seconds
    spawn_controllers = TimerAction(
        period=6.0,
        actions=[
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["joint_state_broadcaster", "left_arm_controller", "right_arm_controller", "left_arm_gripper", "right_arm_gripper"],
                output="screen",
            )
        ],
    )
    
    # MoveIt move_group
    move_group_node = TimerAction(
        period=8.0,
        actions=[
            Node(
                package="moveit_ros_move_group",
                executable="move_group",
                output="screen",
                parameters=[
                    moveit_config.to_dict(),
                    {"use_sim_time": False},
                ],
                condition=IfCondition(load_moveit),
            )
        ],
    )
    
    # RViz
    rviz_config_file = PathJoinSubstitution([
        FindPackageShare("dexter_arm_moveit_config"),
        "config",
        "moveit.rviz"
    ])
    
    rviz_node = TimerAction(
        period=10.0,
        actions=[
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                output="log",
                arguments=["-d", rviz_config_file],
                parameters=[
                    moveit_config.robot_description,
                    moveit_config.robot_description_semantic,
                    moveit_config.robot_description_kinematics,
                    moveit_config.planning_pipelines,
                    moveit_config.joint_limits,
                    {"use_sim_time": False},
                ],
                condition=IfCondition(use_rviz),
            )
        ],
    )

    trajectory_params = PathJoinSubstitution([
        FindPackageShare("dexter_arm_trajectory"),
        "config",
        "trajectory_params.yaml",
    ])

    trajectory_manager = Node(
        package="dexter_arm_trajectory",
        executable="trajectory_manager",
        name="trajectory_manager",
        output="screen",
        parameters=[trajectory_params],
        condition=IfCondition(load_trajectory_system),
    )

    shape_trajectory = Node(
        package="dexter_arm_trajectory",
        executable="shape_trajectory",
        name="shape_trajectory_node",
        output="screen",
        parameters=[trajectory_params],
        condition=IfCondition(load_trajectory_system),
    )
    
    return LaunchDescription(
        declared_arguments + [
            control_node,
            robot_state_pub_node,
            static_tf,
            trajectory_manager,
            shape_trajectory,
            spawn_controllers,
            move_group_node,
            rviz_node,
        ]
    )
