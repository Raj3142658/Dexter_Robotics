#!/usr/bin/env python3
"""
Complete Gazebo System Bringup for Dexter Arm
Launches: Gazebo + Controllers + MoveIt + RViz
"""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction, DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    """
    Full Gazebo system: Simulation + MoveIt + RViz
    """
    
    # Launch arguments
    declared_arguments = []
    
    declared_arguments.append(
        DeclareLaunchArgument(
            "use_rviz",
            default_value="true",
            description="Start RViz"
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
            "gazebo_gui",
            default_value="true",
            description="Start Gazebo GUI (false for headless server mode)",
        )
    )

    declared_arguments.append(
        DeclareLaunchArgument(
            "load_trajectory_system",
            default_value="true",
            description="Start dexter_arm_trajectory manager + shape generator"
        )
    )
    
    use_rviz = LaunchConfiguration("use_rviz")
    load_moveit = LaunchConfiguration("load_moveit")
    load_trajectory_system = LaunchConfiguration("load_trajectory_system")
    gazebo_gui = LaunchConfiguration("gazebo_gui")
    
    # MoveIt configuration
    moveit_config = (
        MoveItConfigsBuilder("dexter_arm", package_name="dexter_arm_moveit_config")
        .robot_description(file_path="config/dexter_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/dexter_arm.srdf")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .planning_pipelines(pipelines=["ompl", "chomp", "pilz_industrial_motion_planner"])
        .to_moveit_configs()
    )
    
    # Launch Gazebo (includes robot spawning and basic controllers)
    gazebo_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("dexter_arm_gazebo"),
                "launch",
                "gazebo.launch.py"
            ])
        ),
        launch_arguments={"gui": gazebo_gui}.items(),
    )

    trajectory_system = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("dexter_arm_trajectory"),
                "launch",
                "trajectory_system.launch.py",
            ])
        ),
        condition=IfCondition(load_trajectory_system),
    )
    
    # Spawn arm controllers after Gazebo stabilizes
    spawn_arm_controllers = TimerAction(
        period=6.0,
        actions=[
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["left_arm_controller", "right_arm_controller", "left_arm_gripper", "right_arm_gripper"],
                output="screen",
            )
        ]
    )
    
    # MoveIt move_group
    move_group = TimerAction(
        period=8.0,
        actions=[
            Node(
                package="moveit_ros_move_group",
                executable="move_group",
                parameters=[
                    moveit_config.to_dict(),
                    {"use_sim_time": True}
                ],
                output="screen",
            )
        ],
        condition=IfCondition(load_moveit)
    )
    
    # RViz
    rviz_config = PathJoinSubstitution([
        FindPackageShare("dexter_arm_moveit_config"),
        "config",
        "moveit.rviz"
    ])
    
    rviz = TimerAction(
        period=10.0,
        actions=[
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                output="log",
                arguments=["-d", rviz_config],
                parameters=[
                    moveit_config.robot_description,
                    moveit_config.robot_description_semantic,
                    moveit_config.planning_pipelines,
                    moveit_config.robot_description_kinematics,
                    {"use_sim_time": True}
                ]
            )
        ],
        condition=IfCondition(use_rviz)
    )
    
    return LaunchDescription(
        declared_arguments + [
            gazebo_launch,
            trajectory_system,
            spawn_arm_controllers,
            move_group,
            rviz
        ]
    )
