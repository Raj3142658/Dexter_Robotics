#!/usr/bin/env python3
"""Launch file for complete trajectory teach-repeat system."""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Generate launch description for trajectory system."""
    
    # Launch arguments
    config_file = PathJoinSubstitution([
        FindPackageShare('dexter_arm_trajectory'),
        'config',
        'trajectory_params.yaml'
    ])
    
    # Trajectory Manager Node
    trajectory_manager = Node(
        package='dexter_arm_trajectory',
        executable='trajectory_manager',
        name='trajectory_manager',
        output='screen',
        parameters=[config_file],
        emulate_tty=True
    )
    
    # TCP Visualizer Node
    tcp_visualizer = Node(
        package='dexter_arm_trajectory',
        executable='tcp_visualizer',
        name='tcp_visualizer',
        output='screen',
        parameters=[config_file],
        emulate_tty=True
    )
    
    # Shape Trajectory Node
    shape_trajectory = Node(
        package='dexter_arm_trajectory',
        executable='shape_trajectory',
        name='shape_trajectory_node',
        output='screen',
        parameters=[config_file],
        emulate_tty=True
    )
    
    return LaunchDescription([
        trajectory_manager,
        tcp_visualizer,
        shape_trajectory,
    ])
