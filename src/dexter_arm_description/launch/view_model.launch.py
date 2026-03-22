from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch.conditions import IfCondition, UnlessCondition
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import FindExecutable
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():

    gui = LaunchConfiguration("gui")

    declare_gui_arg = DeclareLaunchArgument(
        "gui",
        default_value="true",
        description="Use joint_state_publisher_gui"
    )

    robot_description_content = ParameterValue(
        Command([
            FindExecutable(name="xacro"),
            " ",
            PathJoinSubstitution([
                FindPackageShare("dexter_arm_description"),
                "urdf",
                "dexter_arm.urdf.xacro"
            ])
        ]),
        value_type=str
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        parameters=[{"robot_description": robot_description_content}]
    )

    joint_state_publisher = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        condition=UnlessCondition(gui)
    )

    joint_state_publisher_gui = Node(
        package="joint_state_publisher_gui",
        executable="joint_state_publisher_gui",
        condition=IfCondition(gui)
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        arguments=[
            "-d",
            PathJoinSubstitution([
                FindPackageShare("dexter_arm_description"),
                "rviz",
                "model.rviz"
            ])
        ]
    )

    return LaunchDescription([
        declare_gui_arg,
        robot_state_publisher,
        joint_state_publisher,
        joint_state_publisher_gui,
        rviz
    ])
