"""
Launch Terminal Window
A window that displays process output using the HUD Terminal widget.
This replaces separate terminal windows for launch system commands.
"""

import os
import signal
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QProcess, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QWidget,
    QMessageBox,
)

from .widgets.hud_terminal import HudTerminal
from .process_manager import ProcessManager


class LaunchTerminalWindow(QWidget):
    """
    A window for launching ROS commands with HUD-themed terminal output.
    Replaces separate terminal windows for the 5 launch system commands.
    """
    
    # Signal emitted when launch completes
    launchFinished = pyqtSignal(bool, str)  # success, message
    
    def __init__(
        self,
        title: str,
        command: str,
        process_manager: ProcessManager,
        workspace_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self.title = title
        self.command = command
        self.process_manager = process_manager
        self.workspace_dir = Path(workspace_dir).expanduser()
        
        self.process: Optional[QProcess] = None
        self.ros_distro = self._detect_ros_distro()
        
        self._setup_ui()
        self._setup_window()
    
    def _detect_ros_distro(self) -> str:
        """Detect ROS distribution."""
        import os
        if 'ROS_DISTRO' in os.environ:
            return os.environ['ROS_DISTRO']
        
        ros_path = Path('/opt/ros')
        if ros_path.exists():
            try:
                distros = sorted([d.name for d in ros_path.iterdir() if d.is_dir()])
                if distros:
                    return distros[-1]
            except:
                pass
        return "jazzy"
    
    def _setup_window(self):
        """Setup window properties."""
        self.setWindowTitle(self.title)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(800, 500)
        self.resize(1100, 750)
        
        # Apply HUD theme
        self.setStyleSheet(f"""
            QWidget {{
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.2, radius: 1.1,
                    fx: 0.5, fy: 0.05,
                    stop: 0 #142742,
                    stop: 0.55 #0d1626,
                    stop: 1 #070c16
                );
            }}
            QFrame#title_bar {{
                background-color: rgba(0, 30, 60, 200);
                border-bottom: 1px solid #1a5a8e;
            }}
            QLabel#window_title {{
                color: #00F3FF;
                font-size: 16px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", sans-serif;
            }}
            QLabel#status_label {{
                color: #8ad4ff;
                font-size: 12px;
            }}
            QPushButton {{
                background-color: rgba(0, 80, 120, 180);
                color: #00F3FF;
                border: 1px solid #00F3FF;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 120, 180, 220);
                border: 2px solid #00F3FF;
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 60, 100, 200);
            }}
            QPushButton#stop_button {{
                background-color: rgba(180, 40, 40, 180);
                border-color: #FF4444;
                color: #FF4444;
            }}
            QPushButton#stop_button:hover {{
                background-color: rgba(220, 60, 60, 220);
                border: 2px solid #FF6666;
                color: #FF6666;
            }}
        """)
    
    def _setup_ui(self):
        """Setup the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar
        title_bar = QFrame(self)
        title_bar.setObjectName("title_bar")
        title_bar.setFixedHeight(50)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(15, 0, 15, 0)
        
        # Window title
        title_label = QLabel(self.title)
        title_label.setObjectName("window_title")
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        # Status indicator
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_label")
        title_layout.addWidget(self.status_label)
        
        layout.addWidget(title_bar)
        
        # Terminal output
        self.terminal = HudTerminal(self)
        self.terminal.set_title(self.title)
        layout.addWidget(self.terminal, 1)
        
        # Control bar
        control_bar = QFrame(self)
        control_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 30, 50, 200);
                border-top: 1px solid #1a5a8e;
            }
        """)
        control_bar.setFixedHeight(50)
        control_layout = QHBoxLayout(control_bar)
        control_layout.setContentsMargins(15, 0, 15, 0)
        
        control_layout.addStretch()
        
        # Launch button
        self.launch_button = QPushButton("▶ LAUNCH")
        self.launch_button.clicked.connect(self._start_process)
        control_layout.addWidget(self.launch_button)
        
        # Stop button
        self.stop_button = QPushButton("■ STOP")
        self.stop_button.setObjectName("stop_button")
        self.stop_button.clicked.connect(self._stop_process)
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button)
        
        # Clear button
        clear_button = QPushButton("CLEAR")
        clear_button.clicked.connect(self.terminal.clear)
        control_layout.addWidget(clear_button)
        
        layout.addWidget(control_bar)
    
    def _start_process(self):
        """Start the ROS launch process."""
        if self.process is not None:
            return
        
        self.terminal.clear()
        self.terminal.append_log(f"[INFO] Starting: {self.title}")
        self.terminal.append_log(f"[INFO] Command: {self.command}")
        self.terminal.append_log("-" * 50)
        
        # Build full command with ROS sourcing
        ros_setup = f"/opt/ros/{self.ros_distro}/setup.bash"
        full_command = f"source {ros_setup} && cd {self.workspace_dir} && source install/setup.bash && {self.command}"
        
        self.process = QProcess(self)
        self.process.setProgram("/bin/bash")
        self.process.setArguments(["-lc", full_command])
        
        # Connect signals
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        
        # Update UI
        self.launch_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Running...")
        self.status_label.setStyleSheet("color: #00FF00; font-size: 12px;")
        
        # Start process
        self.process.start()
        
        self.terminal.append_log("[INFO] Process started")
    
    def _handle_stdout(self):
        """Handle standard output — passes chunked output to terminal."""
        if self.process:
            output = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
            if output:
                self.terminal.append_log(output.rstrip())
    
    def _handle_stderr(self):
        """Handle standard error — passes chunked error to terminal."""
        if self.process:
            output = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
            if output:
                # To maintain formatting, split lines, prefix, then join
                lines = [f"[ERROR] {line.strip()}" for line in output.splitlines() if line.strip()]
                if lines:
                    self.terminal.append_log("\n".join(lines))
    
    def _process_finished(self, exit_code, exit_status):
        """Handle process finished."""
        self.terminal.append_log("-" * 50)

        # Update UI
        self.launch_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        user_stopped = getattr(self, '_user_stopped', False)
        self._user_stopped = False
        # Signal-based exits: SIGTERM=15, SIGINT=2, SIGKILL=9
        signal_exit = exit_code in (2, 9, 15, 143)

        if exit_code == 0 or (user_stopped and signal_exit):
            if user_stopped:
                self.terminal.append_log("[INFO] Process stopped by user")
                self.status_label.setText("Stopped")
            else:
                self.terminal.append_log("[INFO] Process finished successfully")
                self.status_label.setText("Completed")
            self.status_label.setStyleSheet("color: #00FF00; font-size: 12px;")
            self.launchFinished.emit(True, "Process completed successfully")
        else:
            self.terminal.append_log(f"[INFO] Process finished with exit code: {exit_code}")
            self.status_label.setText(f"Exited ({exit_code})")
            self.status_label.setStyleSheet("color: #FF4444; font-size: 12px;")
            self.launchFinished.emit(False, f"Process exited with code {exit_code}")
        
        self.process = None
    
    def _process_error(self, error):
        """Handle process error."""
        # "Crashed" is Qt's way of saying the process was killed by a signal.
        # If the user clicked Stop, this is expected — not an error.
        if error == QProcess.ProcessError.Crashed and getattr(self, '_user_stopped', False):
            return  # _process_finished will handle the UI update

        error_strs = {
            QProcess.ProcessError.FailedToStart: "Failed to start",
            QProcess.ProcessError.Crashed: "Crashed",
            QProcess.ProcessError.Timedout: "Timed out",
            QProcess.ProcessError.WriteError: "Write error",
            QProcess.ProcessError.ReadError: "Read error",
            QProcess.ProcessError.UnknownError: "Unknown error",
        }
        
        error_msg = error_strs.get(error, "Unknown error")
        self.terminal.append_log(f"[CRITICAL] Process error: {error_msg}")
        
        self.launch_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("color: #FF0088; font-size: 12px;")
        
        self.process = None
        self.launchFinished.emit(False, error_msg)
    
    def _stop_process(self):
        """Stop the running process gracefully (SIGTERM, then SIGKILL if needed)."""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self._user_stopped = True
            pid = self.process.processId()
            self.terminal.append_log("[INFO] Stopping process (graceful)...")

            # Send SIGTERM to the process tree for graceful shutdown
            self._signal_tree(pid, signal.SIGTERM)

            # Give 3s for graceful shutdown, then SIGKILL the tree
            QTimer.singleShot(3000, lambda: self._force_kill_tree(pid))
    
    def _force_kill(self):
        """Force kill the process if still running."""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            pid = self.process.processId()
            self._force_kill_tree(pid)

    def _force_kill_tree(self, pid: int):
        """Kill the entire process tree."""
        if self.process is None or self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self._signal_tree(pid, signal.SIGKILL)
        # Fallback: QProcess.kill()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self.terminal.append_log("[WARN] Process force killed")

    @staticmethod
    def _signal_tree(pid: int, sig: int) -> None:
        """Send a signal to a process and all its descendants."""
        import subprocess
        # Use pkill to signal the entire tree rooted at pid
        try:
            subprocess.run(
                ["pkill", f"-{sig.value if hasattr(sig, 'value') else sig}", "-P", str(pid)],
                check=False, timeout=2,
            )
        except Exception:
            pass
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    
    def closeEvent(self, event):
        """Handle window close."""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            reply = QMessageBox.question(
                self,
                "Process Running",
                "A process is still running. Do you want to stop it and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                pid = self.process.processId()
                self._signal_tree(pid, signal.SIGKILL)
                self.process.kill()
                self.process.waitForFinished(1000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
