#!/usr/bin/env python3
"""
Launch file for gripper mimic controller

Starts the gripper mimic controller node that synchronizes
finger sliders with j7l/j7r joints.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='dexter_arm_control',
            executable='gripper_mimic_controller.py',
            name='gripper_mimic_controller',
            output='screen',
            parameters=[],
        ),
    ])
