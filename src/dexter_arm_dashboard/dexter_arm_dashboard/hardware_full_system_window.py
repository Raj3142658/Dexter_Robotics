"""
Hardware Full System launch window.

Implements the dexter_arm_base.sh hardware workflow:
1) Select micro-ROS transport (serial / UDP)
2) Start micro-ROS agent in background
3) Wait for session establishment (with timeout + EN tip)
4) Launch hardware bringup
5) Stop agent when hardware launch exits
"""

from pathlib import Path
import os
import signal
import shlex
import shutil
import subprocess
from typing import Optional

from PyQt6.QtCore import Qt, QProcess, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .process_manager import ProcessManager


class HardwareFullSystemWindow(QWidget):
    """Non-modal window for Hardware + micro-ROS full launch workflow."""

    HARDWARE_PROCESS_NAME = "hardware_full_system"
    _SESSION_MARKERS = ("session established", "establish_session")

    def __init__(
        self,
        process_manager: ProcessManager,
        workspace_dir: str,
        microros_workspace: str,
        serial_port: str,
        serial_baud: int,
        parent=None,
    ):
        super().__init__(parent)
        self.process_manager = process_manager
        self.workspace_dir = Path(workspace_dir).expanduser()
        self.microros_workspace = Path(microros_workspace).expanduser()
        self.default_serial_port = serial_port
        self.default_serial_baud = str(serial_baud)

        self.agent_process: Optional[QProcess] = None
        self.hardware_process: Optional[QProcess] = None
        self.agent_started_by_window = False
        self.waiting_for_session = False
        self.session_established = False
        self.wait_elapsed_seconds = 0
        self.hardware_started_by_window = False
        self._stopping_agent = False
        self._recent_agent_lines = []

        self.agent_wait_timer = QTimer(self)
        self.agent_wait_timer.setInterval(1000)
        self.agent_wait_timer.timeout.connect(self._on_agent_wait_tick)

        self.hardware_watch_timer = QTimer(self)
        self.hardware_watch_timer.setInterval(1000)
        self.hardware_watch_timer.timeout.connect(self._watch_hardware_process)

        self.setWindowTitle("Hardware Full System")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("hardware_full_window")
        self.setMinimumSize(1040, 760)
        self.resize(1120, 840)
        self.setStyleSheet(
            """
            QWidget#hardware_full_window {
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.2, radius: 1.1,
                    fx: 0.5, fy: 0.05,
                    stop: 0 #142742,
                    stop: 0.55 #0d1626,
                    stop: 1 #070c16
                );
            }
            QFrame#main_panel {
                background-color: rgba(14, 29, 49, 242);
                border: 1px solid #3b6aa3;
                border-radius: 14px;
            }
            QLabel#title {
                color: #8ad4ff;
                font-size: 21px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#hint {
                color: #bed4f2;
                font-size: 13px;
            }
            QLabel#status_ok {
                color: #87ffbf;
                font-weight: 600;
            }
            QLabel#status_warn {
                color: #ffd98a;
                font-weight: 600;
            }
            QLabel#status_err {
                color: #ff9e9e;
                font-weight: 600;
            }
            QLabel {
                color: #d9e7ff;
            }
            QLineEdit, QComboBox, QPlainTextEdit {
                background-color: #0f1a2e;
                color: #ebf2ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                padding: 5px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #5da4ff;
            }
            QComboBox::drop-down {
                background-color: #17304e;
                border-left: 1px solid #3b6aa3;
                width: 24px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #0f1a2e;
                color: #f4f8ff;
                border: 1px solid #40618f;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
                outline: 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 26px;
                color: #f4f8ff;
                background-color: #0f1a2e;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #2f73c9;
                color: #ffffff;
            }
            QPlainTextEdit {
                font-family: "Courier New", monospace;
                font-size: 12px;
            }
            QPushButton {
                background-color: #224f82;
                color: #f1f8ff;
                border: 1px solid #4b8ed8;
                border-radius: 7px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #2f6db1;
            }
            QPushButton#danger {
                background-color: #8f3838;
                border-color: #d97878;
            }
            QPushButton#danger:hover {
                background-color: #a64646;
            }
            """
        )

        self._build_ui()
        self._set_status("Ready.", "ok")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("main_panel")
        panel.setMinimumSize(960, 700)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(10)

        title = QLabel("Hardware Full System Launch", panel)
        title.setObjectName("title")
        panel_layout.addWidget(title)

        hint = QLabel(
            "Starts micro-ROS agent, waits for session, then launches hardware bringup.",
            panel,
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        panel_layout.addWidget(hint)

        transport_row = QHBoxLayout()
        transport_row.addWidget(QLabel("Transport:", panel))
        self.transport_combo = QComboBox(panel)
        self.transport_combo.addItem("Serial (USB)", "serial")
        self.transport_combo.addItem("WiFi (UDP)", "udp")
        self.transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        self.transport_combo.view().setStyleSheet(
            """
            QListView {
                background-color: #0f1a2e;
                color: #f4f8ff;
                border: 1px solid #40618f;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
                outline: 0;
            }
            QListView::item {
                min-height: 26px;
                color: #f4f8ff;
                background-color: #0f1a2e;
            }
            QListView::item:selected {
                background-color: #2f73c9;
                color: #ffffff;
            }
            """
        )
        transport_row.addWidget(self.transport_combo, 2)
        transport_row.addSpacing(16)
        self.wifi_port_label = QLabel("WiFi UDP Port:", panel)
        transport_row.addWidget(self.wifi_port_label)
        self.wifi_port_edit = QLineEdit("8888", panel)
        self.wifi_port_edit.setFixedWidth(120)
        transport_row.addWidget(self.wifi_port_edit)
        transport_row.addStretch(1)
        panel_layout.addLayout(transport_row)

        serial_row = QHBoxLayout()
        serial_row.addWidget(QLabel("Serial Port:", panel))
        self.serial_port_edit = QLineEdit(self.default_serial_port, panel)
        self.serial_port_edit.setFixedWidth(200)
        serial_row.addWidget(self.serial_port_edit)
        serial_row.addSpacing(16)
        serial_row.addWidget(QLabel("Baud:", panel))
        self.serial_baud_edit = QLineEdit(self.default_serial_baud, panel)
        self.serial_baud_edit.setFixedWidth(120)
        serial_row.addWidget(self.serial_baud_edit)
        serial_row.addStretch(1)
        panel_layout.addLayout(serial_row)

        self.status_label = QLabel("", panel)
        self.status_label.setObjectName("status_ok")
        self.status_label.setWordWrap(True)
        panel_layout.addWidget(self.status_label)

        self.log_output = QPlainTextEdit(panel)
        self.log_output.setReadOnly(True)
        panel_layout.addWidget(self.log_output, 1)

        buttons = QHBoxLayout()
        self.btn_launch_full = QPushButton("Launch Full System", panel)
        self.btn_launch_full.clicked.connect(self._launch_full_system)
        buttons.addWidget(self.btn_launch_full)

        self.btn_launch_hw_only = QPushButton("Launch Hardware Only", panel)
        self.btn_launch_hw_only.clicked.connect(self._launch_hardware_only)
        buttons.addWidget(self.btn_launch_hw_only)

        self.btn_stop = QPushButton("Stop", panel)
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self._stop_all)
        buttons.addWidget(self.btn_stop)

        self.btn_close = QPushButton("Close", panel)
        self.btn_close.clicked.connect(self.close)
        buttons.addWidget(self.btn_close)
        panel_layout.addLayout(buttons)

        root.addWidget(panel, 1)

        self._on_transport_changed()

    def _on_transport_changed(self) -> None:
        transport = self.transport_combo.currentData()
        is_udp = transport == "udp"
        self.wifi_port_label.setVisible(is_udp)
        self.wifi_port_edit.setVisible(is_udp)

    def _set_status(self, message: str, level: str) -> None:
        obj = "status_ok"
        if level == "warn":
            obj = "status_warn"
        elif level == "err":
            obj = "status_err"
        self.status_label.setObjectName(obj)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setText(message)

    def _log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _message_box_style(self) -> str:
        return """
            QMessageBox {
                background-color: #0d1626;
            }
            QMessageBox QLabel {
                color: #e7f1ff;
                font-size: 14px;
                min-width: 420px;
            }
            QMessageBox QPushButton {
                background-color: #224f82;
                color: #f1f8ff;
                border: 1px solid #4b8ed8;
                border-radius: 6px;
                padding: 6px 16px;
                min-width: 86px;
            }
            QMessageBox QPushButton:hover {
                background-color: #2f6db1;
            }
        """

    def _show_message(
        self,
        title: str,
        text: str,
        icon: QMessageBox.Icon,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
    ) -> QMessageBox.StandardButton:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(icon)
        box.setStandardButtons(buttons)
        if default_button != QMessageBox.StandardButton.NoButton:
            box.setDefaultButton(default_button)
        box.setStyleSheet(self._message_box_style())
        result = box.exec()
        return QMessageBox.StandardButton(result)

    def _launch_full_system(self) -> None:
        if self.process_manager.is_running(self.HARDWARE_PROCESS_NAME):
            self._show_message(
                "Already Running",
                "Hardware bringup is already running.",
                QMessageBox.Icon.Warning,
            )
            return
        if self.waiting_for_session:
            self._show_message(
                "In Progress",
                "Already waiting for micro-ROS session.",
                QMessageBox.Icon.Information,
            )
            return

        transport = self.transport_combo.currentData()
        if transport == "serial" and not self._verify_serial_prerequisites():
            return
        if not self._confirm_full_launch():
            return
        if not self._start_agent():
            return

        self.agent_started_by_window = True
        self.waiting_for_session = True
        self.session_established = False
        self.wait_elapsed_seconds = 0
        self._set_status("Waiting for ESP32 micro-ROS session...", "warn")
        self._log("Waiting for ESP32 connection...")
        self.agent_wait_timer.start()

    def _launch_hardware_only(self) -> None:
        if self.process_manager.is_running(self.HARDWARE_PROCESS_NAME):
            self._show_message(
                "Already Running",
                "Hardware bringup is already running.",
                QMessageBox.Icon.Warning,
            )
            return
        if self.waiting_for_session:
            self._show_message(
                "Busy",
                "Stop current full-system flow first.",
                QMessageBox.Icon.Warning,
            )
            return

        launched = self._start_hardware_process("Hardware Bringup")
        if launched:
            self.hardware_started_by_window = True
            self._set_status("Hardware bringup running.", "ok")
            self._log("Launched hardware_bringup.launch.py")
            self.hardware_watch_timer.start()
        else:
            self._set_status("Failed to launch hardware bringup.", "err")
            self._log("Launch failed for hardware bringup.")

    def _confirm_full_launch(self) -> bool:
        text = (
            "1. Make sure ESP32 is powered and firmware is uploaded.\n"
            "2. micro-ROS agent will start in background.\n"
            "3. You may need to press EN on ESP32 for connection.\n"
            "4. Hardware bringup will start after session is ready.\n\n"
            "Continue?"
        )
        reply = self._show_message(
            "Hardware Full System",
            text,
            QMessageBox.Icon.Question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _verify_serial_prerequisites(self) -> bool:
        port = self.serial_port_edit.text().strip() or self.default_serial_port
        baud = self.serial_baud_edit.text().strip() or self.default_serial_baud
        self.serial_port_edit.setText(port)
        self.serial_baud_edit.setText(baud)

        self._log("=== Hardware Verification ===")

        all_ok = True

        port_path = Path(port)
        if port_path.exists():
            self._log(f"[OK] Serial port exists: {port}")
        else:
            all_ok = False
            self._log(f"[ERR] Serial port not found: {port}")
            tty_usb = sorted(Path("/dev").glob("ttyUSB*"))
            tty_acm = sorted(Path("/dev").glob("ttyACM*"))
            if tty_usb or tty_acm:
                listed = [str(p) for p in tty_usb + tty_acm]
                self._log("Available ports: " + ", ".join(listed))
            else:
                self._log("Available ports: none found (/dev/ttyUSB* or /dev/ttyACM*)")

        if port_path.exists() and os.access(port, os.R_OK | os.W_OK):
            self._log("[OK] Port permissions are read/write")
        else:
            all_ok = False
            self._log(f"[ERR] No read/write permissions on {port}")
            self._log("Fix: sudo chmod 666 <port> or add user to dialout group")

        detected = self._detect_esp32_adapter()
        if detected is True:
            self._log("[OK] ESP32 USB adapter detected")
        elif detected is False:
            self._log("[WARN] ESP32 USB adapter not clearly detected")
        else:
            self._log("[WARN] Could not run lsusb to detect ESP32 adapter")

        if self._validate_microros_workspace():
            self._log(f"[OK] micro-ROS workspace found: {self.microros_workspace}")
        else:
            all_ok = False
            self._log(f"[ERR] micro-ROS workspace invalid: {self.microros_workspace}")

        if all_ok:
            self._set_status("Hardware checks passed.", "ok")
            return True

        self._set_status("Hardware verification reported issues.", "warn")
        reply = self._show_message(
            "Hardware Verification Failed",
            "One or more checks failed. Continue anyway?",
            QMessageBox.Icon.Warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _detect_esp32_adapter(self) -> Optional[bool]:
        if not shutil.which("lsusb"):
            return None
        try:
            result = subprocess.run(
                ["lsusb"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        text = (result.stdout or "").lower()
        markers = ("cp210", "ch340", "ftdi", "silicon labs")
        return any(marker in text for marker in markers)

    def _validate_microros_workspace(self) -> bool:
        setup_file = self.microros_workspace / "install" / "setup.bash"
        return self.microros_workspace.is_dir() and setup_file.exists()

    def _start_agent(self) -> bool:
        if not self._validate_microros_workspace():
            self._set_status("micro-ROS workspace is missing install/setup.bash.", "err")
            self._log(f"Invalid micro-ROS workspace: {self.microros_workspace}")
            return False

        transport = self.transport_combo.currentData()
        if transport == "udp":
            udp_port = self.wifi_port_edit.text().strip() or "8888"
            self.wifi_port_edit.setText(udp_port)
            if not udp_port.isdigit():
                self._set_status("WiFi UDP port must be numeric.", "err")
                self._log(f"[ERR] Invalid UDP port: {udp_port}")
                return False
            agent_cmd = f"ros2 run micro_ros_agent micro_ros_agent udp4 --port {shlex.quote(udp_port)}"
            self._log(f"Starting micro-ROS agent on UDP port {udp_port}...")
        else:
            port = self.serial_port_edit.text().strip() or self.default_serial_port
            baud = self.serial_baud_edit.text().strip() or self.default_serial_baud
            self.serial_port_edit.setText(port)
            self.serial_baud_edit.setText(baud)
            agent_cmd = (
                "ros2 run micro_ros_agent micro_ros_agent serial "
                f"--dev {shlex.quote(port)} -b {shlex.quote(baud)}"
            )
            self._log(f"Starting micro-ROS agent on {port} @ {baud} baud...")

        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        microros_setup = self.microros_workspace / "install" / "setup.bash"
        full_command = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(str(self.microros_workspace))} && "
            f"source {shlex.quote(str(microros_setup))} && "
            f"{agent_cmd}"
        )

        self._cleanup_agent_process()

        self.agent_process = QProcess(self)
        self.agent_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.agent_process.readyRead.connect(self._on_agent_output)
        self.agent_process.finished.connect(self._on_agent_finished)
        self.agent_process.setProgram("/bin/bash")
        self.agent_process.setArguments(["-lc", full_command])
        self.agent_process.start()

        if not self.agent_process.waitForStarted(3000):
            self._set_status("Failed to start micro-ROS agent.", "err")
            self._log("Failed to start micro-ROS agent process.")
            self._cleanup_agent_process()
            return False

        self._set_status("micro-ROS agent started. Waiting for session...", "warn")
        return True

    def _on_agent_output(self) -> None:
        if self.agent_process is None:
            return
        data = bytes(self.agent_process.readAll()).decode("utf-8", errors="replace")
        for raw_line in data.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            self._recent_agent_lines.append(line)
            if len(self._recent_agent_lines) > 40:
                self._recent_agent_lines = self._recent_agent_lines[-40:]
            self._log(f"[agent] {line}")

            ll = line.lower()
            if not self.session_established and any(marker in ll for marker in self._SESSION_MARKERS):
                self.session_established = True
                self._log("[OK] Session established.")

    def _on_agent_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._cleanup_agent_process()
        if self._stopping_agent:
            self._stopping_agent = False
            return

        if self.waiting_for_session:
            self.waiting_for_session = False
            self.agent_wait_timer.stop()
            self._set_status("micro-ROS agent exited before session was established.", "err")
            self._log(f"[ERR] micro-ROS agent exited with code {exit_code}.")
            return

        if self.hardware_started_by_window:
            self._set_status("micro-ROS agent stopped unexpectedly while hardware is running.", "warn")
            self._log(f"[WARN] micro-ROS agent exited with code {exit_code}.")

    def _on_agent_wait_tick(self) -> None:
        if not self.waiting_for_session:
            self.agent_wait_timer.stop()
            return

        self.wait_elapsed_seconds += 1

        if self.session_established:
            self.waiting_for_session = False
            self.agent_wait_timer.stop()
            self._set_status("Session established. Launching hardware bringup...", "ok")
            if self._recent_agent_lines:
                self._log("Agent connection status:")
                for line in self._recent_agent_lines[-5:]:
                    self._log(f"[agent-tail] {line}")
            self._log("Connection stabilizing...")
            QTimer.singleShot(2000, self._start_hardware_bringup)
            return

        if self.wait_elapsed_seconds % 5 == 0:
            self._log(f"[wait] Still waiting... ({self.wait_elapsed_seconds}s)")
            if self.wait_elapsed_seconds == 10:
                self._log("Connection tip: press EN (reset) on ESP32, wait 2-3 seconds.")

        if self.wait_elapsed_seconds >= 30:
            self.waiting_for_session = False
            self.agent_wait_timer.stop()
            self._set_status("Timeout: micro-ROS session not established in 30s.", "err")
            self._log("[ERR] Timeout waiting for session.")
            for line in self._recent_agent_lines[-10:]:
                self._log(f"[agent-tail] {line}")
            self._log("Try pressing EN on ESP32 and launch again.")
            self._stop_agent()

    def _start_hardware_bringup(self) -> None:
        if self._is_hardware_running():
            self._set_status("Hardware bringup already running.", "warn")
            self._log("Hardware bringup already running.")
            return

        launched = self._start_hardware_process("Hardware Full System")
        if not launched:
            self._set_status("Failed to launch hardware bringup.", "err")
            self._log("[ERR] Failed to launch hardware_bringup.launch.py")
            self._stop_agent()
            return

        self.hardware_started_by_window = True
        self._set_status("Hardware bringup running.", "ok")
        self._log("Launched hardware bringup. Agent will stop when bringup exits.")
        self.hardware_watch_timer.start()

    def _start_hardware_process(self, display_name: str) -> bool:
        """Start hardware bringup as a QProcess with output piped to the log."""
        if self._is_hardware_running():
            return False

        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        full_command = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(str(self.workspace_dir))} && "
            "source install/setup.bash && "
            "ros2 launch dexter_arm_hardware hardware_bringup.launch.py"
        )

        self.hardware_process = QProcess(self)
        self.hardware_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.hardware_process.readyRead.connect(self._on_hardware_output)
        self.hardware_process.finished.connect(self._on_hardware_finished)
        self.hardware_process.setProgram("/bin/bash")
        self.hardware_process.setArguments(["-lc", full_command])
        self.hardware_process.start()

        if not self.hardware_process.waitForStarted(5000):
            self._log(f"[ERR] Failed to start {display_name}")
            self._cleanup_hardware_process()
            return False

        self._log(f"[OK] {display_name} process started (PID {self.hardware_process.processId()})")
        return True

    def _is_hardware_running(self) -> bool:
        """Check if the hardware process is currently running."""
        return (
            self.hardware_process is not None
            and self.hardware_process.state() != QProcess.ProcessState.NotRunning
        )

    def _on_hardware_output(self) -> None:
        if self.hardware_process is None:
            return
        data = bytes(self.hardware_process.readAll()).decode("utf-8", errors="replace")
        for raw_line in data.splitlines():
            line = raw_line.strip()
            if line:
                self._log(f"[hw] {line}")

    def _on_hardware_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._log(f"Hardware bringup exited with code {exit_code}")
        self._cleanup_hardware_process()
        # Let the watch timer detect exit and stop the agent

    def _cleanup_hardware_process(self) -> None:
        if self.hardware_process is None:
            return
        try:
            self.hardware_process.deleteLater()
        except Exception:
            pass
        self.hardware_process = None

    def _watch_hardware_process(self) -> None:
        if not self.hardware_started_by_window:
            self.hardware_watch_timer.stop()
            return

        if self._is_hardware_running():
            return

        self.hardware_watch_timer.stop()
        self.hardware_started_by_window = False
        self._set_status("Hardware bringup exited.", "warn")
        self._log("Hardware bringup exited.")

        if self.agent_started_by_window:
            self._log("Stopping micro-ROS agent...")
            self._stop_agent()
            self.agent_started_by_window = False

    def _stop_agent(self) -> None:
        if self.agent_process is None:
            self.agent_started_by_window = False
            return
        if self.agent_process.state() == QProcess.ProcessState.NotRunning:
            self._cleanup_agent_process()
            self.agent_started_by_window = False
            return

        self._stopping_agent = True
        self.agent_process.terminate()
        if not self.agent_process.waitForFinished(2000):
            self.agent_process.kill()
            self.agent_process.waitForFinished(1000)
        self._cleanup_agent_process()
        self.agent_started_by_window = False
        self._log("micro-ROS agent stopped.")

    def _cleanup_agent_process(self) -> None:
        if self.agent_process is None:
            return
        try:
            self.agent_process.deleteLater()
        except Exception:
            pass
        self.agent_process = None

    def _stop_all(self) -> None:
        self.agent_wait_timer.stop()
        self.hardware_watch_timer.stop()
        self.waiting_for_session = False
        self.session_established = False
        self.wait_elapsed_seconds = 0

        # Stop hardware bringup process
        if self._is_hardware_running():
            pid = self.hardware_process.processId()
            self._signal_tree(pid, signal.SIGINT)
            self.hardware_process.waitForFinished(2000)
            if self._is_hardware_running():
                self._signal_tree(pid, signal.SIGKILL)
                self.hardware_process.kill()
                self.hardware_process.waitForFinished(1000)
            self._log("Stopped hardware bringup.")
        self._cleanup_hardware_process()
        self.hardware_started_by_window = False

        if self.agent_started_by_window:
            self._stop_agent()
        else:
            self._cleanup_agent_process()

        self._set_status("Stopped.", "warn")

    def _reset_ui(self) -> None:
        self.transport_combo.setCurrentIndex(0)
        self.serial_port_edit.setText(self.default_serial_port)
        self.serial_baud_edit.setText(self.default_serial_baud)
        self.wifi_port_edit.setText("8888")
        self.log_output.clear()
        self._recent_agent_lines = []
        self._set_status("Ready.", "ok")

    def closeEvent(self, event) -> None:
        self._stop_all()
        self._reset_ui()
        super().closeEvent(event)

    @staticmethod
    def _signal_tree(pid: int, sig: int) -> None:
        """Send a signal to a process and all its descendants."""
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
