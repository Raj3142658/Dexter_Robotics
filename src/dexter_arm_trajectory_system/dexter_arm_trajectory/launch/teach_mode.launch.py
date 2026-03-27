#!/usr/bin/env python3
"""Launch file for teach mode (system + GUI)."""

from launch import LaunchDescription
from launch.actions import Shutdown
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Generate launch description for teach mode."""
    
    # Include trajectory system launch
    trajectory_system = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('dexter_arm_trajectory'),
                'launch',
                'trajectory_system.launch.py'
            ])
        ])
    )
    
    # GUI Node
    gui_node = Node(
        package='dexter_arm_trajectory',
        executable='trajectory_gui',
        name='trajectory_gui',
        output='screen',
        emulate_tty=True,
        on_exit=Shutdown(reason='Trajectory GUI closed')
    )
    
    return LaunchDescription([
        trajectory_system,
        gui_node,
    ])
