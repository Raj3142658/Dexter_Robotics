#!/usr/bin/env python3
"""
Trajectory Teach GUI - PyQt5-based interface for teach-repeat system.

Provides intuitive controls for:
- Capturing MoveIt planned trajectories
- Compiling trajectories with smoothing
- Previewing in RViz
- Saving/loading trajectory files
- Executing compiled trajectories
"""

import sys
import os
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QFileDialog, QMessageBox,
    QProgressBar, QTextEdit, QLineEdit
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

from std_srvs.srv import Trigger
from control_msgs.action import FollowJointTrajectory
from dexter_arm_trajectory_msgs.srv import (
    CaptureSegment, CompileTrajectory, SaveTrajectory,
    LoadTrajectory, GetStatus, ExecuteTrajectory
)
from dexter_arm_trajectory_msgs.msg import ExecutionProgress


class TrajectoryTeachGUI(QMainWindow):
    """
    Main GUI for trajectory teach-repeat system.
    """
    
    def __init__(self):
        super().__init__()
        
        # Initialize ROS2 node
        rclpy.init()
        self.node = rclpy.create_node('trajectory_gui')
        
        # Service clients
        self.capture_client = self.node.create_client(
            CaptureSegment, '/trajectory_manager/capture_segment'
        )
        self.clear_client = self.node.create_client(
            Trigger, '/trajectory_manager/clear_buffer'
        )
        self.compile_client = self.node.create_client(
            CompileTrajectory, '/trajectory_manager/compile'
        )
        self.save_client = self.node.create_client(
            SaveTrajectory, '/trajectory_manager/save'
        )
        self.load_client = self.node.create_client(
            LoadTrajectory, '/trajectory_manager/load'
        )
        self.status_client = self.node.create_client(
            GetStatus, '/trajectory_manager/get_status'
        )
        self.execute_client = self.node.create_client(
            ExecuteTrajectory, '/trajectory_manager/execute'
        )
        
        # Action client for execution
        self.execute_action_client = ActionClient(
            self.node,
            FollowJointTrajectory,
            '/joint_trajectory_controller/follow_joint_trajectory'
        )
        
        # Subscribe to execution progress
        self.progress_sub = self.node.create_subscription(
            ExecutionProgress,
            '/trajectory_manager/execution_progress',
            self.progress_callback,
            10
        )
        
        # State
        self.current_status = None
        self.executing = False
        
        # Setup UI
        self.init_ui()
        
        # ROS2 spin timer (20Hz)
        self.ros_timer = QTimer()
        self.ros_timer.timeout.connect(self.spin_ros)
        self.ros_timer.start(50)
        
        # Status update timer (2Hz)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(500)
        
        self.log('Trajectory Teach GUI initialized')
    
    
    def init_ui(self):
        """
        Initialize the user interface.
        """
        self.setWindowTitle('Dexter Arm - Teach & Repeat System')
        self.setGeometry(100, 100, 760, 820)

        # HUD-style theme to match dashboard windows.
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0d1626;
            }
            QWidget {
                background-color: #0d1626;
                color: #eef4ff;
                font-size: 14px;
            }
            QLabel {
                color: #eef4ff;
            }
            QGroupBox {
                background-color: #16263d;
                border: 1px solid #2f4b72;
                border-radius: 10px;
                margin-top: 14px;
                color: #ffffff;
                font-weight: 700;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #00f3ff;
            }
            QPushButton {
                background-color: #1f3b5e;
                color: #f7fbff;
                border: 1px solid #3f7ac2;
                border-radius: 7px;
                padding: 8px 10px;
                font-weight: 600;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #2a537f;
            }
            QPushButton:pressed {
                background-color: #18324f;
            }
            QPushButton:disabled {
                color: #8297b8;
                border-color: #5b6f90;
                background-color: #122238;
            }
            QLineEdit, QTextEdit {
                background-color: #0f1a2e;
                color: #f4f8ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                padding: 6px;
            }
            QProgressBar {
                background-color: #0f1a2e;
                color: #f4f8ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                text-align: center;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background-color: #2f73c9;
                border-radius: 5px;
            }
            """
        )
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Header
        header = QLabel('DEXTER ARM - Teach & Repeat')
        header.setFont(QFont('Arial', 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #00f3ff;")
        main_layout.addWidget(header)
        
        # === TEACH MODE ===
        teach_group = QGroupBox('📚 TEACH MODE')
        teach_layout = QVBoxLayout()
        
        instructions = QLabel(
            '1. Use MoveIt in RViz to plan motion\n'
            '2. Click "Capture Segment" when satisfied\n'
            '3. Repeat for multiple waypoints'
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #d4e4ff;")
        teach_layout.addWidget(instructions)
        
        teach_buttons = QHBoxLayout()
        
        self.capture_btn = QPushButton('📷 Capture Segment')
        self.capture_btn.clicked.connect(self.capture_segment)
        teach_buttons.addWidget(self.capture_btn)
        
        self.clear_btn = QPushButton('🗑️ Clear Buffer')
        self.clear_btn.clicked.connect(self.clear_buffer)
        teach_buttons.addWidget(self.clear_btn)
        
        teach_layout.addLayout(teach_buttons)
        
        self.segments_label = QLabel('Segments: 0')
        self.segments_label.setFont(QFont('Arial', 12))
        self.segments_label.setStyleSheet("color: #00f3ff; font-weight: 600;")
        teach_layout.addWidget(self.segments_label)
        
        teach_group.setLayout(teach_layout)
        main_layout.addWidget(teach_group)
        
        # === COMP ILE & PREVIEW ===
        compile_group = QGroupBox('⚙️ COMPILE & PREVIEW')
        compile_layout = QVBoxLayout()
        
        compile_buttons = QHBoxLayout()
        
        self.compile_btn = QPushButton('⚙️ Compile Trajectory')
        self.compile_btn.clicked.connect(self.compile_trajectory)
        compile_buttons.addWidget(self.compile_btn)
        
        self.preview_btn = QPushButton('👁️ Preview in RViz')
        self.preview_btn.clicked.connect(self.preview_trajectory)
        self.preview_btn.setEnabled(False)
        compile_buttons.addWidget(self.preview_btn)
        
        compile_layout.addLayout(compile_buttons)
        
        file_buttons = QHBoxLayout()
        
        self.save_btn = QPushButton('💾 Save')
        self.save_btn.clicked.connect(self.save_trajectory)
        self.save_btn.setEnabled(False)
        file_buttons.addWidget(self.save_btn)
        
        self.load_btn = QPushButton('📂 Load')
        self.load_btn.clicked.connect(self.load_trajectory)
        file_buttons.addWidget(self.load_btn)
        
        compile_layout.addLayout(file_buttons)
        
        compile_group.setLayout(compile_layout)
        main_layout.addWidget(compile_group)
        
        # === EXECUTE ===
        execute_group = QGroupBox('▶️ EXECUTE')
        execute_layout = QVBoxLayout()
        
        exec_buttons = QHBoxLayout()
        
        self.execute_btn = QPushButton('▶️ Execute')
        self.execute_btn.clicked.connect(self.execute_trajectory)
        self.execute_btn.setEnabled(False)
        exec_buttons.addWidget(self.execute_btn)
        
        self.stop_btn = QPushButton('⏸️ Stop')
        self.stop_btn.clicked.connect(self.stop_execution)
        self.stop_btn.setEnabled(False)
        exec_buttons.addWidget(self.stop_btn)
        
        execute_layout.addLayout(exec_buttons)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        execute_layout.addWidget(self.progress_bar)
        
        execute_group.setLayout(execute_layout)
        main_layout.addWidget(execute_group)
        
        # === STATUS ===
        status_group = QGroupBox('📊 STATUS')
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel('Status: Initializing...')
        self.status_label.setFont(QFont('Arial', 10))
        self.status_label.setStyleSheet("color: #00f3ff; font-weight: 600;")
        status_layout.addWidget(self.status_label)
        
        self.duration_label = QLabel('Duration: --')
        self.duration_label.setStyleSheet("color: #dbe8ff;")
        status_layout.addWidget(self.duration_label)
        
        self.waypoints_label = QLabel('Waypoints: --')
        self.waypoints_label.setStyleSheet("color: #dbe8ff;")
        status_layout.addWidget(self.waypoints_label)
        
        self.filename_label = QLabel('File: --')
        self.filename_label.setStyleSheet("color: #dbe8ff;")
        status_layout.addWidget(self.filename_label)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        # === LOG ===
        log_group = QGroupBox('📝 LOG')
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet(
            """
            QTextEdit {
                background-color: #0a1323;
                color: #c8dcff;
                border: 1px solid #3a5d8a;
                border-radius: 6px;
            }
            """
        )
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
    
    
    def spin_ros(self):
        """Spin ROS2 node in Qt event loop."""
        rclpy.spin_once(self.node, timeout_sec=0)
    
    
    def update_status(self):
        """Update status display from trajectory manager."""
        if not self.status_client.wait_for_service(timeout_sec=0.1):
            return
        
        request = GetStatus.Request()
        future = self.status_client.call_async(request)
        future.add_done_callback(self.handle_status_response)
    
    
    def handle_status_response(self, future):
        """Handle status service response."""
        try:
            response = future.result()
            self.current_status = response
            
            # Update UI
            self.segments_label.setText(f'Segments: {response.segment_count}')
            self.status_label.setText(f'Status: {response.status}')
            self.duration_label.setText(f'Duration: {response.trajectory_duration:.2f}s')
            self.waypoints_label.setText(f'Waypoints: {response.total_waypoints}')
            self.filename_label.setText(f'File: {response.current_filename or "--"}')
            
            # Sync execution state with server
            self.executing = (response.status == 'executing')
            
            # Enable/disable buttons based on state
            has_compiled = response.has_compiled_trajectory
            self.preview_btn.setEnabled(has_compiled)
            self.save_btn.setEnabled(has_compiled)
            self.execute_btn.setEnabled(has_compiled and not self.executing)
            self.stop_btn.setEnabled(self.executing)
            
        except Exception as e:
            self.log(f'Status update error: {str(e)}', error=True)
    
    
    def capture_segment(self):
        """Capture current MoveIt planned trajectory."""
        if not self.capture_client.wait_for_service(timeout_sec=1.0):
            self.log('Trajectory manager not available', error=True)
            return
        
        request = CaptureSegment.Request()
        future = self.capture_client.call_async(request)
        future.add_done_callback(self.handle_capture_response)
        self.log('Capturing segment...')
    
    
    def handle_capture_response(self, future):
        """Handle capture service response."""
        try:
            response = future.result()
            if response.success:
                self.log(f'✓ {response.message}')
            else:
                self.log(f'✗ {response.message}', error=True)
        except Exception as e:
            self.log(f'Capture error: {str(e)}', error=True)
    
    
    def clear_buffer(self):
        """Clear all captured segments."""
        reply = QMessageBox.question(
            self, 'Confirm Clear',
            'Clear all captured segments?',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        if not self.clear_client.wait_for_service(timeout_sec=1.0):
            return
        
        request = Trigger.Request()
        future = self.clear_client.call_async(request)
        future.add_done_callback(lambda f: self.log(f.result().message))
        self.log('Clearing buffer...')
    
    
    def compile_trajectory(self):
        """Compile and smooth trajectory segments."""
        if not self.compile_client.wait_for_service(timeout_sec=1.0):
            self.log('Trajectory manager not available', error=True)
            return
        
        # use simplified compile handler or restore specific one if response differs significantly
        # but CompileTrajectory response matches what handle_compile_response expects
        request = CompileTrajectory.Request()
        future = self.compile_client.call_async(request)
        future.add_done_callback(self.handle_compile_response)
        self.log('Compiling trajectory...')
    
    
    def handle_compile_response(self, future):
        """Handle compile service response."""
        try:
            response = future.result()
            if response.success:
                self.log(
                    f'✓ Compilation complete: {response.total_waypoints} waypoints, '
                    f'{response.duration:.2f}s'
                )
            else:
                self.log(f'✗ {response.message}', error=True)
        except Exception as e:
            self.log(f'Compilation error: {str(e)}', error=True)
    
    
    def preview_trajectory(self):
        """Trigger trajectory preview (already published by manager)."""
        self.log('Trajectory preview published to /trajectory_preview')
        QMessageBox.information(
            self, 'Preview',
            'Check RViz for trajectory preview visualization'
        )
    
    
    def save_trajectory(self):
        """Save compiled trajectory to file."""
        filename, _ = QFileDialog.getSaveFileName(
            self, 'Save Trajectory',
            os.path.expanduser('~/.ros/dexter_trajectories/'),
            'YAML Files (*.yaml)'
        )
        
        if not filename:
            return
        
        if not filename.endswith('.yaml'):
            filename += '.yaml'
        
        if not self.save_client.wait_for_service(timeout_sec=1.0):
            return
        
        request = SaveTrajectory.Request()
        request.filename = os.path.basename(filename)
        request.description = 'Trajectory created via GUI'
        
        future = self.save_client.call_async(request)
        future.add_done_callback(
            lambda f: self.log(
                f.result().message,
                error=not f.result().success
            )
        )
        self.log(f'Saving to {request.filename}...')
    
    
    def load_trajectory(self):
        """Load trajectory from file."""
        filename, _ = QFileDialog.getOpenFileName(
            self, 'Load Trajectory',
            os.path.expanduser('~/.ros/dexter_trajectories/'),
            'YAML Files (*.yaml)'
        )
        
        if not filename:
            return
        
        if not self.load_client.wait_for_service(timeout_sec=1.0):
            return
        
        request = LoadTrajectory.Request()
        request.filename = os.path.basename(filename)
        
        future = self.load_client.call_async(request)
        future.add_done_callback(self.handle_load_response)
        self.log(f'Loading {request.filename}...')
    
    
    def handle_load_response(self, future):
        """Handle load service response."""
        try:
            response = future.result()
            if response.success:
                self.log(
                    f'✓ Loaded: {response.waypoint_count} waypoints, '
                    f'{response.duration:.2f}s'
                )
            else:
                self.log(f'✗ {response.message}', error=True)
        except Exception as e:
            self.log(f'Load error: {str(e)}', error=True)
    
    
    def execute_trajectory(self):
        """Execute the compiled trajectory."""
        if not self.execute_client.wait_for_service(timeout_sec=1.0):
            self.log('Trajectory manager not available', error=True)
            return
        
        request = ExecuteTrajectory.Request()
        future = self.execute_client.call_async(request)
        future.add_done_callback(self.handle_execute_response)
        
        self.executing = True
        self.execute_btn.setEnabled(False)
        self.log('Starting execution...')
    
    
    def handle_execute_response(self, future):
        """Handle execute service response."""
        try:
            response = future.result()
            if response.success:
                self.log(f'✓ {response.message}')
            else:
                self.log(f'✗ {response.message}', error=True)
                self.executing = False
                self.update_status()  # Check status immediately to reset button
        except Exception as e:
            self.log(f'Execution error: {str(e)}', error=True)
            self.executing = False
    
    
    def stop_execution(self):
        """Stop current trajectory execution."""
        self.executing = False
        self.log('Execution stopped')
    
    
    def log(self, message, error=False):
        """Append message to log window."""
        prefix = '[ERROR] ' if error else '[INFO] '
        self.log_text.append(prefix + message)
        self.node.get_logger().info(message)
    
    
    def closeEvent(self, event):
        """Clean up on window close."""
        self.ros_timer.stop()
        self.status_timer.stop()
        self.node.destroy_node()
        rclpy.shutdown()
        event.accept()


    def progress_callback(self, msg):
        """Handle execution progress updates."""
        self.progress_bar.setValue(int(msg.progress_percent))
        
        if msg.status == 'executing':
            self.status_label.setText(f'Status: Executing ({msg.progress_percent:.1f}%)')
            self.duration_label.setText(
                f'Time: {msg.current_time:.1f}s / {msg.total_duration:.1f}s'
            )
            self.executing = True
            
            # Update buttons state if needed
            if self.execute_btn.isEnabled():
                self.execute_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
        elif msg.status == 'completed':
            self.status_label.setText('Status: Completed')
            self.progress_bar.setValue(100)
            self.executing = False
            self.execute_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    gui = TrajectoryTeachGUI()
    gui.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
