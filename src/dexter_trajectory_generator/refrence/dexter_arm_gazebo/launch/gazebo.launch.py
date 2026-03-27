#!/usr/bin/env python3
"""
Gazebo Harmonic simulation launch file for Dexter arm.
Starts Gazebo, spawns robot, and loads controllers.
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription, TimerAction, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    # Set Gazebo resource path to find meshes
    pkg_dexter_arm_share = os.path.dirname(
        get_package_share_directory('dexter_arm_description')
    )

    gz_resource_path = SetEnvironmentVariable(
        name='GZ_SIM_RESOURCE_PATH',
        value=pkg_dexter_arm_share
    )


    # Get URDF via xacro (Gazebo overlay)
    robot_description_content = ParameterValue(
        Command(
            [
                PathJoinSubstitution([FindExecutable(name="xacro")]),
                " ",
                PathJoinSubstitution(
                    [
                        FindPackageShare("dexter_arm_gazebo"),
                        "urdf",
                        "dexter_arm_gazebo.xacro",
                    ]
                ),
            ]
        ),
        value_type=str
    )

    # World file
    world_file = PathJoinSubstitution(
        [
            FindPackageShare("dexter_arm_gazebo"),
            "worlds",
            "empty.world",
        ]
    )

    # Start Gazebo Harmonic
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("ros_gz_sim"),
                "launch",
                "gz_sim.launch.py"
            ])
        ),
        launch_arguments={"gz_args": ["-r ", world_file]}.items(),
    )

    # Robot state publisher
    robot_state_publisher_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both",
        parameters=[{"robot_description": robot_description_content}],
    )

    # Spawn robot in Gazebo using gz service
    spawn_entity = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=[
            "-topic", "robot_description",
            "-name", "dexter_arm",
            "-z", "0.0",  # Spawn at ground level
        ],
        output="screen",
    )

    # Bridge to connect Gazebo and ROS topics
    gz_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
        ],
        output="screen",
    )

    # Spawn joint_state_broadcaster after 4 seconds
    spawn_joint_state_broadcaster = TimerAction(
        period=4.0,
        actions=[
            ExecuteProcess(
                cmd=[
                    "ros2",
                    "control",
                    "load_controller",
                    "--set-state",
                    "active",
                    "joint_state_broadcaster",
                ],
                output="screen",
            )
        ],
    )


    return LaunchDescription(
        [
            gz_resource_path,
            gazebo,
            robot_state_publisher_node,
            gz_bridge,
            spawn_entity,
            spawn_joint_state_broadcaster,
        ]
    )

