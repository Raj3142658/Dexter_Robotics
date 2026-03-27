#!/usr/bin/env python3
"""
Gazebo-only simulation launch for Dexter arm.
Starts Gazebo + robot spawn + clock bridge without controllers, RViz, or MoveIt.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def _launch_gz_sim(context, world_file):
    gui_enabled = LaunchConfiguration("gui").perform(context).lower() == "true"
    gz_args_prefix = "-r " if gui_enabled else "-r -s "

    return [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    FindPackageShare("ros_gz_sim"),
                    "launch",
                    "gz_sim.launch.py",
                ])
            ),
            launch_arguments={"gz_args": [gz_args_prefix, world_file]}.items(),
        )
    ]


def generate_launch_description():
    pkg_dexter_arm_share = os.path.dirname(get_package_share_directory("dexter_arm_description"))

    gz_resource_path = SetEnvironmentVariable(
        name="GZ_SIM_RESOURCE_PATH",
        value=pkg_dexter_arm_share,
    )

    declare_gui = DeclareLaunchArgument(
        "gui",
        default_value="true",
        description="Start Gazebo GUI (false for headless server mode)",
    )

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
        value_type=str,
    )

    world_file = PathJoinSubstitution(
        [
            FindPackageShare("dexter_arm_gazebo"),
            "worlds",
            "empty.world",
        ]
    )

    gazebo = OpaqueFunction(function=lambda context: _launch_gz_sim(context, world_file))

    robot_state_publisher_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both",
        parameters=[
            {"robot_description": robot_description_content},
            {"use_sim_time": True},
        ],
    )

    spawn_entity = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=[
            "-topic",
            "robot_description",
            "-name",
            "dexter_arm",
            "-z",
            "0.0",
        ],
        output="screen",
    )

    gz_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
        ],
        output="screen",
    )

    return LaunchDescription(
        [
            declare_gui,
            gz_resource_path,
            gazebo,
            robot_state_publisher_node,
            gz_bridge,
            spawn_entity,
        ]
    )
