"""
Launch file for Dexter Arm Dashboard
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for dashboard."""
    
    return LaunchDescription([
        Node(
            package='dexter_arm_dashboard',
            executable='dashboard',
            name='dexter_arm_dashboard',
            output='screen',
            emulate_tty=True,
        )
    ])
