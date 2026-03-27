#!/usr/bin/env python3
"""
TCP Path Visualizer Node - Generates end-effector path visualization.

Uses MoveIt's /compute_fk service to compute TCP positions from joint trajectories
and publishes LINE_STRIP markers for visualization in RViz.
"""

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

import numpy as np
from pathlib import Path
import time

from moveit_msgs.msg import DisplayTrajectory, RobotState
from moveit_msgs.srv import GetPositionFK
from visualization_msgs.msg import Marker
from std_msgs.msg import ColorRGBA, Header
from geometry_msgs.msg import Point
from sensor_msgs.msg import JointState

class TCPVisualizer(Node):
    """
    Visualizes end-effector TCP path using MoveIt's FK service.
    """
    
    def __init__(self):
        super().__init__('tcp_visualizer')
        
        # Parameters
        self.declare_parameter('end_effector_link', 'end_effector_link')
        self.declare_parameter('frame_id', 'world')
        self.declare_parameter('line_width', 0.003)
        self.declare_parameter('export_csv', False)
        self.declare_parameter('csv_output_dir', '~/.ros/dexter_trajectories/tcp_paths')
        
        self.end_effector_link = self.get_parameter('end_effector_link').value
        self.frame_id = self.get_parameter('frame_id').value
        self.line_width = self.get_parameter('line_width').value
        self.export_csv = self.get_parameter('export_csv').value
        self.csv_output_dir = self.get_parameter('csv_output_dir').value
        
        # Service Client for FK
        self.fk_client = self.create_client(
            GetPositionFK, 
            'compute_fk',
            callback_group=ReentrantCallbackGroup()
        )
        
        # Subscription for preview
        self.preview_sub = self.create_subscription(
            DisplayTrajectory,
            '/trajectory_preview',
            self.preview_callback,
            10,
            callback_group=ReentrantCallbackGroup()
        )
        
        # Publisher
        self.marker_pub = self.create_publisher(
            Marker,
            '/tcp_path_marker',
            10
        )
        
        self.get_logger().info('TCP Visualizer initialized (Waiting for compute_fk service...)')
        
        # Wait for FK service (timeout 5s)
        if not self.fk_client.wait_for_service(timeout_sec=5.0):
             self.get_logger().warn('compute_fk service not available! Visualizer will fail.')

    def preview_callback(self, msg: DisplayTrajectory):
        """
        Callback when trajectory preview is published.
        """
        if len(msg.trajectory) == 0:
            return
        
        trajectory_msg = msg.trajectory[0].joint_trajectory
        point_count = len(trajectory_msg.points)
        
        self.get_logger().info(f'Computing TCP path for {point_count} points...')
        
        tcp_points = []
        joint_names = trajectory_msg.joint_names
        
        # Subsample to avoid DDOSing the FK service (Max 50 points or Step 10)
        # We want enough density for curve but not too slow.
        step = max(1, point_count // 50) 
        
        for i in range(0, point_count, step):
            point = trajectory_msg.points[i]
            
            # Prepare FK request
            req = GetPositionFK.Request()
            req.header.frame_id = self.frame_id
            req.fk_link_names = [self.end_effector_link]
            
            # Construct RobotState
            rs = RobotState()
            js = JointState()
            js.name = joint_names
            js.position = point.positions
            rs.joint_state = js
            req.robot_state = rs
            
            # Call service synchronously
            try:
                response = self.fk_client.call(req)
                if response.error_code.val == 1: # SUCCESS
                    # response.pose_stamped is list of PoseStamped
                    if len(response.pose_stamped) > 0:
                        p = response.pose_stamped[0].pose.position
                        tcp_points.append(p)
                else:
                    self.get_logger().warn(f'FK failed for point {i}: code {response.error_code.val}')
            except Exception as e:
                self.get_logger().error(f'Service call failed: {e}')
                break
        
        # Publish
        if tcp_points:
            self._publish_marker(tcp_points)
            if self.export_csv:
                self._export_csv(tcp_points)

    def _publish_marker(self, tcp_points):
        marker = Marker()
        marker.header.frame_id = self.frame_id
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = 'tcp_path'
        marker.id = 0
        marker.type = Marker.LINE_STRIP
        marker.action = Marker.ADD
        marker.scale.x = self.line_width
        marker.color = ColorRGBA(r=1.0, g=0.5, b=0.0, a=1.0)
        marker.points = tcp_points
        marker.lifetime = rclpy.duration.Duration(seconds=0).to_msg() # Forever
        
        self.marker_pub.publish(marker)
        self.get_logger().info(f'Published path marker with {len(tcp_points)} points')

    def _export_csv(self, tcp_points):
        try:
            import os
            from datetime import datetime
            output_dir = os.path.expanduser(self.csv_output_dir)
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            filename = f"tcp_path_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(os.path.join(output_dir, filename), 'w') as f:
                f.write('x,y,z\n')
                for p in tcp_points:
                    f.write(f'{p.x},{p.y},{p.z}\n')
            self.get_logger().info(f'Saved CSV to {filename}')
        except Exception as e:
            self.get_logger().error(f'CSV export error: {e}')

def main(args=None):
    rclpy.init(args=args)
    node = TCPVisualizer()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
