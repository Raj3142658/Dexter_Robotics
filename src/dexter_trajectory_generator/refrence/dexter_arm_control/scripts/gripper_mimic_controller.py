#!/usr/bin/env python3
"""
Gripper Mimic Controller Node

This node subscribes to j7l and j7r joint states and publishes 
synchronized commands to the finger slider joints to simulate 
mimic joint behavior in Gazebo.

Author: Dexter Arm Team
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray


class GripperMimicController(Node):
    def __init__(self):
        super().__init__('gripper_mimic_controller')
        
        # Multipliers for finger movement (22mm / π radians ≈ 0.007)
        self.multiplier_positive = 0.007  # For j6l_finger_slide, j6r_finger_slide
        self.multiplier_negative = -0.007  # For j6l_finger2_slide, j6r_finger2_slide
        
        # Store latest j7 positions
        self.j7l_position = 0.0
        self.j7r_position = 0.0
        
        # Subscribe to joint states
        self.joint_state_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            10
        )
        
        # Publishers for finger commands
        self.left_finger_pub = self.create_publisher(
            Float64MultiArray,
            '/left_gripper_controller/commands',
            10
        )
        
        self.right_finger_pub = self.create_publisher(
            Float64MultiArray,
            '/right_gripper_controller/commands',
            10
        )
        
        # Timer to publish finger commands at 50Hz
        self.timer = self.create_timer(0.02, self.publish_finger_commands)
        
        self.get_logger().info('Gripper Mimic Controller started')
    
    def joint_state_callback(self, msg):
        """Extract j7l and j7r positions from joint states"""
        try:
            if 'j7l' in msg.name:
                idx = msg.name.index('j7l')
                self.j7l_position = msg.position[idx]
            
            if 'j7r' in msg.name:
                idx = msg.name.index('j7r')
                self.j7r_position = msg.position[idx]
        except (ValueError, IndexError) as e:
            pass  # Joint not in message
    
    def publish_finger_commands(self):
        """Calculate and publish finger positions based on j7 positions"""
        # Left gripper fingers
        left_finger1_pos = self.j7l_position * self.multiplier_positive
        left_finger2_pos = self.j7l_position * self.multiplier_negative
        
        left_msg = Float64MultiArray()
        left_msg.data = [left_finger1_pos, left_finger2_pos]
        self.left_finger_pub.publish(left_msg)
        
        # Right gripper fingers
        right_finger1_pos = self.j7r_position * self.multiplier_positive
        right_finger2_pos = self.j7r_position * self.multiplier_negative
        
        right_msg = Float64MultiArray()
        right_msg.data = [right_finger1_pos, right_finger2_pos]
        self.right_finger_pub.publish(right_msg)


def main(args=None):
    rclpy.init(args=args)
    node = GripperMimicController()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
