"""
trajectory_node.launch.py
=========================
Launches the DexterTrajectoryGeneratorNode with all MoveIt2 parameters
(robot_description, SRDF, kinematics, planning pipelines) so MoveItPy
can initialize correctly.

Usage (direct):
    ros2 launch dexter_trajectory_generator trajectory_node.launch.py \
        config_file:=/path/to/shape_config.yaml \
        output_file:=/path/to/output.yaml

Usage (via bridge_server - called automatically):
    bridge_server passes all params as launch arguments.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():

    # ── MoveIt config (URDF + SRDF + kinematics + planning pipelines) ────────
    moveit_config = (
        MoveItConfigsBuilder(
            "dexter_arm",
            package_name="dexter_arm_moveit_config",
        )
        .robot_description(file_path="config/dexter_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/dexter_arm.srdf")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .planning_pipelines(pipelines=["ompl"])
        .to_moveit_configs()
    )

    # ── Declare all trajectory-node parameters as launch arguments ────────────
    declared = [
        DeclareLaunchArgument("config_file",                default_value=""),
        DeclareLaunchArgument("output_file",                default_value=""),
        DeclareLaunchArgument("description",                default_value="Shape trajectory - Dexter"),
        DeclareLaunchArgument("eef_step",                   default_value="0.005"),
        DeclareLaunchArgument("jump_threshold",             default_value="0.0"),
        DeclareLaunchArgument("max_velocity_scaling",       default_value="0.3"),
        DeclareLaunchArgument("max_acceleration_scaling",   default_value="0.1"),
        DeclareLaunchArgument("avoid_collisions",           default_value="true"),
        DeclareLaunchArgument("time_param_method",          default_value="totg"),
    ]

    # ── Trajectory generator node ─────────────────────────────────────────────
    # Use to_dict() to ensure ALL MoveIt params are passed as a single flat dict.
    moveit_params = moveit_config.to_dict()

    # to_dict() collapses planning_pipelines to a flat list (e.g. ['ompl']).
    # MoveItCpp requires it as {"pipeline_names": [...]} so it can find
    # the "planning_pipelines.pipeline_names" ROS parameter.
    moveit_params["planning_pipelines"] = {
        "pipeline_names": moveit_params["planning_pipelines"]
    }

    moveit_params.update({
        "config_file":                  LaunchConfiguration("config_file"),
        "output_file":                  LaunchConfiguration("output_file"),
        "description":                  LaunchConfiguration("description"),
        "eef_step":                     LaunchConfiguration("eef_step"),
        "jump_threshold":               LaunchConfiguration("jump_threshold"),
        "max_velocity_scaling":         LaunchConfiguration("max_velocity_scaling"),
        "max_acceleration_scaling":     LaunchConfiguration("max_acceleration_scaling"),
        "avoid_collisions":             LaunchConfiguration("avoid_collisions"),
        "time_param_method":            LaunchConfiguration("time_param_method"),
    })

    trajectory_node = Node(
        package="dexter_trajectory_generator",
        executable="trajectory_node",
        name="dexter_trajectory_generator",
        output="screen",
        parameters=[moveit_params],
    )

    return LaunchDescription(declared + [trajectory_node])
