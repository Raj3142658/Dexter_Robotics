from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    # Declare arguments
    declared_arguments = []
    declared_arguments.append(
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation clock",
        )
    )

    # Build MoveIt config
    moveit_config = (
        MoveItConfigsBuilder("dexter_arm", package_name="dexter_arm_moveit_config")
        .robot_description(file_path="config/dexter_arm.urdf.xacro")
        .robot_description_semantic(file_path="config/dexter_arm.srdf")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .planning_pipelines(pipelines=["ompl", "chomp", "pilz_industrial_motion_planner"])
        .to_moveit_configs()
    )

    # Robot State Publisher
    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[moveit_config.robot_description, {"use_sim_time": LaunchConfiguration("use_sim_time")}],
    )

    # Static TF for virtual joint (world -> base_link)
    static_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="virtual_joint_broadcaster",
        arguments=["0", "0", "0", "0", "0", "0", "world", "base_link"],
        parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
    )

    # Joint State Publisher (for fake execution)
    joint_state_publisher = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        parameters=[
            moveit_config.robot_description,
            {"use_sim_time": LaunchConfiguration("use_sim_time")},
        ],
    )

    # Move Group (planning only in demo mode)
    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[
            moveit_config.to_dict(),
            {
                "use_sim_time": LaunchConfiguration("use_sim_time"),
                # Disable execution in demo mode (planning visualization only)
                "allow_trajectory_execution": False,
            }
        ],
    )

    # RViz
    rviz_config = PathJoinSubstitution(
        [FindPackageShare("dexter_arm_moveit_config"), "config", "moveit.rviz"]
    )
    
    rviz = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="log",
        arguments=["-d", rviz_config],
        parameters=[
            moveit_config.robot_description,
            moveit_config.robot_description_semantic,
            moveit_config.robot_description_kinematics,
            moveit_config.planning_pipelines,
            {"use_sim_time": LaunchConfiguration("use_sim_time")},
        ],
    )

    return LaunchDescription(
        declared_arguments
        + [
            robot_state_publisher,
            static_tf,
            joint_state_publisher,
            move_group,
            rviz,
        ]
    )
