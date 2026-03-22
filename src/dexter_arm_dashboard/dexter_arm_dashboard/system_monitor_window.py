"""HUD-style live system monitor window for dashboard operations."""

from __future__ import annotations

import datetime as dt
import os
import platform
import re
import shlex
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import psutil
from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .process_manager import ProcessManager


def _fmt_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _fmt_percent(value: float) -> str:
    return f"{value:.1f}%"


class SystemMonitorWindow(QWidget):
    """Detailed system monitor with HUD styling and live refresh."""

    def __init__(self, process_manager: ProcessManager, workspace_dir: str,
                 active_apps_provider=None, parent=None):
        super().__init__(parent)
        self.process_manager = process_manager
        self.workspace_dir = Path(workspace_dir).expanduser()
        self._active_apps_provider = active_apps_provider

        self.metric_values: Dict[str, QLabel] = {}
        self._prev_net = psutil.net_io_counters()
        self._prev_net_time = time.monotonic()
        self._ros_topics: Set[str] = set()
        self._ros_nodes: Set[str] = set()
        self._ros_graph_ready = False
        self._last_ros_probe_time = 0.0
        self._ros_probe_interval_s = 6.0
        self._last_hw_diag_refresh = 0.0
        self._hw_diag_refresh_interval_s = 10.0
        self._last_top_refresh = 0.0
        self._top_refresh_interval_s = 4.0
        self._last_launch_count_refresh = 0.0
        self._launch_count_interval_s = 3.0
        self._cached_active_count = 0
        self._last_hw_query_time = 0.0
        self._hw_query_interval_s = 10.0
        self._controllers_cache = ""
        self._hardware_components_cache = ""
        self._shell_prefix = self._build_shell_prefix()
        self._ros_graph_process: Optional[QProcess] = None
        self._hw_diag_process: Optional[QProcess] = None
        self._tcp_fetch_process: Optional[QProcess] = None
        self._ros_graph_timeout = QTimer(self)
        self._ros_graph_timeout.setSingleShot(True)
        self._ros_graph_timeout.timeout.connect(self._on_ros_graph_timeout)
        self._hw_diag_timeout = QTimer(self)
        self._hw_diag_timeout.setSingleShot(True)
        self._hw_diag_timeout.timeout.connect(self._on_hw_diag_timeout)
        self._tcp_fetch_timeout = QTimer(self)
        self._tcp_fetch_timeout.setSingleShot(True)
        self._tcp_fetch_timeout.timeout.connect(self._on_tcp_fetch_timeout)

        self._prime_counters()

        self.setWindowTitle("System Monitor")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("system_monitor_window")
        self.setMinimumSize(1220, 900)
        self.resize(1320, 980)
        self.setStyleSheet(
            """
            QWidget#system_monitor_window {
                background-color: #0d1626;
            }
            QFrame#main_panel {
                background-color: #16263d;
                border: 1px solid #2f4b72;
                border-radius: 14px;
            }
            QFrame#metric_card {
                background-color: rgba(9, 18, 32, 210);
                border: 1px solid rgba(0, 243, 255, 90);
                border-radius: 8px;
            }
            QFrame#diag_panel {
                background-color: rgba(11, 21, 36, 225);
                border: 1px solid #355780;
                border-radius: 8px;
            }
            QLabel {
                color: #e8f2ff;
            }
            QLabel#title {
                font-size: 22px;
                font-weight: 700;
                color: #f2f8ff;
            }
            QLabel#subtitle {
                color: #c8d9ef;
                font-size: 13px;
            }
            QLabel#metric_key {
                color: #97bde5;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.6px;
            }
            QLabel#metric_value {
                color: #00f3ff;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#section {
                color: #b8dcff;
                font-size: 13px;
                font-weight: 700;
            }
            QPlainTextEdit {
                background-color: #0f1a2e;
                color: #e9f3ff;
                border: 1px solid #476993;
                border-radius: 6px;
                padding: 6px;
                font-family: "Courier New", monospace;
                font-size: 12px;
            }
            QTableWidget {
                background-color: #0f1a2e;
                color: #e9f3ff;
                gridline-color: #325077;
                border: 1px solid #476993;
                border-radius: 6px;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1b304d;
                color: #d9ebff;
                border: 1px solid #3f628d;
                padding: 4px;
                font-weight: 700;
            }
            QPushButton {
                background-color: #2a5f9c;
                color: #ffffff;
                border: 1px solid #4b84cc;
                border-radius: 7px;
                padding: 7px 14px;
                font-weight: 700;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #3473b7;
            }
            QPushButton#secondary {
                min-width: 140px;
                background-color: #213f63;
                border: 1px solid #3e6eaa;
            }
            QPushButton#secondary:hover {
                background-color: #2a5482;
            }
            """
        )

        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1500)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start()

        self._refresh()

    def _prime_counters(self) -> None:
        """Prime psutil counters so first displayed sample is meaningful."""
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        for proc in psutil.process_iter(["pid"]):
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll, 1)

        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        panel = QFrame(content)
        self.main_panel = panel
        panel.setObjectName("main_panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(10)
        content_layout.addWidget(panel)
        scroll.setWidget(content)

        title = QLabel("System Monitor", panel)
        title.setObjectName("title")
        subtitle = QLabel(
            "Live host metrics, ROS process snapshot, hardware diagnostics, and TCP pose checks.",
            panel,
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(8)
        summary_grid.setVerticalSpacing(8)
        cards: List[Tuple[str, str]] = [
            ("Time", "time"),
            ("Uptime", "uptime"),
            ("CPU", "cpu"),
            ("RAM", "ram"),
            ("Disk /", "disk_root"),
            ("Disk Workspace", "disk_ws"),
            ("Network Up/Down", "net"),
            ("Tracked Launches", "launches"),
        ]
        for idx, (label, key) in enumerate(cards):
            row, col = divmod(idx, 4)
            summary_grid.addWidget(self._create_metric_card(label, key, panel), row, col)
        panel_layout.addLayout(summary_grid)

        details_row = QHBoxLayout()
        details_row.setSpacing(8)

        left_col = QVBoxLayout()
        cpu_label = QLabel("CPU Core Usage", panel)
        cpu_label.setObjectName("section")
        left_col.addWidget(cpu_label)
        self.cpu_details = QPlainTextEdit(panel)
        self.cpu_details.setReadOnly(True)
        self.cpu_details.setMinimumHeight(160)
        left_col.addWidget(self.cpu_details)
        details_row.addLayout(left_col, 1)

        right_col = QVBoxLayout()
        ros_label = QLabel("ROS Process Snapshot", panel)
        ros_label.setObjectName("section")
        right_col.addWidget(ros_label)
        self.ros_details = QPlainTextEdit(panel)
        self.ros_details.setReadOnly(True)
        self.ros_details.setMinimumHeight(160)
        right_col.addWidget(self.ros_details)
        details_row.addLayout(right_col, 1)

        panel_layout.addLayout(details_row)

        self.hardware_diag_panel = QFrame(panel)
        self.hardware_diag_panel.setObjectName("diag_panel")
        hardware_layout = QVBoxLayout(self.hardware_diag_panel)
        hardware_layout.setContentsMargins(10, 10, 10, 10)
        hardware_layout.setSpacing(6)

        hw_title = QLabel("Hardware ROS Diagnostics", self.hardware_diag_panel)
        hw_title.setObjectName("section")
        hardware_layout.addWidget(hw_title)

        hw_subtitle = QLabel(
            "Visible only when full hardware launch is active.",
            self.hardware_diag_panel,
        )
        hw_subtitle.setObjectName("subtitle")
        hw_subtitle.setWordWrap(True)
        hardware_layout.addWidget(hw_subtitle)

        self.hardware_diag_text = QPlainTextEdit(self.hardware_diag_panel)
        self.hardware_diag_text.setReadOnly(True)
        self.hardware_diag_text.setMinimumHeight(150)
        hardware_layout.addWidget(self.hardware_diag_text)

        hw_buttons = QHBoxLayout()
        self.btn_hw_refresh = QPushButton("Refresh Hardware", self.hardware_diag_panel)
        self.btn_hw_refresh.setObjectName("secondary")
        self.btn_hw_refresh.clicked.connect(lambda: self._update_hardware_diagnostics(force=True))
        hw_buttons.addStretch()
        hw_buttons.addWidget(self.btn_hw_refresh)
        hardware_layout.addLayout(hw_buttons)

        panel_layout.addWidget(self.hardware_diag_panel)
        self.hardware_diag_panel.setVisible(False)

        self.tcp_pose_panel = QFrame(panel)
        self.tcp_pose_panel.setObjectName("diag_panel")
        tcp_layout = QVBoxLayout(self.tcp_pose_panel)
        tcp_layout.setContentsMargins(10, 10, 10, 10)
        tcp_layout.setSpacing(6)

        tcp_title = QLabel("Get TCP Poses", self.tcp_pose_panel)
        tcp_title.setObjectName("section")
        tcp_layout.addWidget(tcp_title)

        tcp_subtitle = QLabel(
            "Visible when robot_state_publisher and TF are available.",
            self.tcp_pose_panel,
        )
        tcp_subtitle.setObjectName("subtitle")
        tcp_subtitle.setWordWrap(True)
        tcp_layout.addWidget(tcp_subtitle)

        self.tcp_pose_text = QPlainTextEdit(self.tcp_pose_panel)
        self.tcp_pose_text.setReadOnly(True)
        self.tcp_pose_text.setMinimumHeight(120)
        tcp_layout.addWidget(self.tcp_pose_text)

        tcp_buttons = QHBoxLayout()
        self.btn_tcp_fetch = QPushButton("Get TCP Poses", self.tcp_pose_panel)
        self.btn_tcp_fetch.setObjectName("secondary")
        self.btn_tcp_fetch.clicked.connect(self._fetch_tcp_poses)
        tcp_buttons.addStretch()
        tcp_buttons.addWidget(self.btn_tcp_fetch)
        tcp_layout.addLayout(tcp_buttons)

        panel_layout.addWidget(self.tcp_pose_panel)
        self.tcp_pose_panel.setVisible(False)

        table_title = QLabel("Top Processes", panel)
        table_title.setObjectName("section")
        panel_layout.addWidget(table_title)

        self.top_table = QTableWidget(panel)
        self.top_table.setColumnCount(5)
        self.top_table.setHorizontalHeaderLabels(["PID", "Name", "CPU %", "MEM %", "Status"])
        self.top_table.verticalHeader().setVisible(False)
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.top_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.top_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.top_table.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.top_table.setMinimumHeight(220)
        panel_layout.addWidget(self.top_table)

        host_info = QLabel("", panel)
        host_info.setObjectName("subtitle")
        host_info.setText(
            f"Host: {platform.node()}  |  OS: {platform.system()} {platform.release()}  |  "
            f"Python: {platform.python_version()}  |  Workspace: {self.workspace_dir}"
        )
        host_info.setWordWrap(True)
        panel_layout.addWidget(host_info)

        buttons = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh Now", panel)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_close = QPushButton("Close", panel)
        self.btn_close.clicked.connect(self.close)
        buttons.addWidget(self.btn_refresh)
        buttons.addStretch()
        buttons.addWidget(self.btn_close)
        panel_layout.addLayout(buttons)

    def _create_metric_card(self, title: str, key: str, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("metric_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        key_lbl = QLabel(title, card)
        key_lbl.setObjectName("metric_key")
        value_lbl = QLabel("--", card)
        value_lbl.setObjectName("metric_value")

        layout.addWidget(key_lbl)
        layout.addWidget(value_lbl)
        self.metric_values[key] = value_lbl
        return card

    def _build_shell_prefix(self) -> str:
        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        return (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(str(self.workspace_dir))} && "
            "source install/setup.bash && "
        )

    def _refresh(self) -> None:
        process_snapshot = self._collect_process_snapshot()
        self._update_summary_metrics()
        self._update_cpu_details()
        self._update_ros_details(process_snapshot)
        self._update_top_processes(process_snapshot)
        self._update_conditional_sections(process_snapshot)

    def _collect_process_snapshot(self) -> List[Dict[str, object]]:
        snapshot: List[Dict[str, object]] = []
        for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_percent", "status"]):
            try:
                name = proc.info.get("name") or ""
                cmdline_list = proc.info.get("cmdline") or []
                cmdline = " ".join(cmdline_list)
                snapshot.append(
                    {
                        "pid": proc.info.get("pid", 0),
                        "name": name,
                        "name_l": name.lower(),
                        "cmdline": cmdline,
                        "cmdline_l": cmdline.lower(),
                        "memory_percent": float(proc.info.get("memory_percent") or 0.0),
                        "status": proc.info.get("status", "") or "",
                        "proc": proc,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return snapshot

    def _update_summary_metrics(self) -> None:
        now = dt.datetime.now()
        self.metric_values["time"].setText(now.strftime("%H:%M:%S"))

        boot = dt.datetime.fromtimestamp(psutil.boot_time())
        uptime = now - boot
        uptime_text = str(uptime).split(".")[0]
        self.metric_values["uptime"].setText(uptime_text)

        cpu = psutil.cpu_percent(interval=None)
        self.metric_values["cpu"].setText(_fmt_percent(cpu))

        mem = psutil.virtual_memory()
        self.metric_values["ram"].setText(
            f"{_fmt_percent(mem.percent)} ({_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)})"
        )

        disk_root = psutil.disk_usage("/")
        self.metric_values["disk_root"].setText(
            f"{_fmt_percent(disk_root.percent)} ({_fmt_bytes(disk_root.used)})"
        )

        if self.workspace_dir.exists():
            try:
                disk_ws = psutil.disk_usage(str(self.workspace_dir))
                ws_text = f"{_fmt_percent(disk_ws.percent)} ({_fmt_bytes(disk_ws.used)})"
            except Exception:
                ws_text = "N/A"
        else:
            ws_text = "N/A"
        self.metric_values["disk_ws"].setText(ws_text)

        now_t = time.monotonic()
        net = psutil.net_io_counters()
        dt_s = max(0.001, now_t - self._prev_net_time)
        up_rate = (net.bytes_sent - self._prev_net.bytes_sent) / dt_s
        down_rate = (net.bytes_recv - self._prev_net.bytes_recv) / dt_s
        self.metric_values["net"].setText(f"U {_fmt_bytes(up_rate)}/s | D {_fmt_bytes(down_rate)}/s")
        self._prev_net = net
        self._prev_net_time = now_t

        if (now_t - self._last_launch_count_refresh) >= self._launch_count_interval_s:
            if self._active_apps_provider:
                self._cached_active_count = len(self._active_apps_provider())
            else:
                self._cached_active_count = self.process_manager.get_active_count()
            self._last_launch_count_refresh = now_t
        self.metric_values["launches"].setText(str(self._cached_active_count))

    def _update_cpu_details(self) -> None:
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        lines: List[str] = []
        for idx, value in enumerate(per_core):
            bars = int(value / 5.0)
            bar_text = "#" * bars + "." * (20 - bars)
            lines.append(f"Core {idx:02d}: [{bar_text}] {value:5.1f}%")

        load_avg = "N/A"
        if hasattr(os, "getloadavg"):
            try:
                l1, l5, l15 = os.getloadavg()
                load_avg = f"{l1:.2f} / {l5:.2f} / {l15:.2f}"
            except Exception:
                pass

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        lines.append("")
        lines.append(f"Load Avg (1/5/15): {load_avg}")
        lines.append(
            f"Memory: used {_fmt_bytes(mem.used)} / total {_fmt_bytes(mem.total)} ({mem.percent:.1f}%)"
        )
        lines.append(
            f"Swap: used {_fmt_bytes(swap.used)} / total {_fmt_bytes(swap.total)} ({swap.percent:.1f}%)"
        )

        self._set_plain_text_if_changed(self.cpu_details, "\n".join(lines))

    def _update_ros_details(self, process_snapshot: List[Dict[str, object]]) -> None:
        groups = {
            "ros2": 0,
            "gazebo": 0,
            "rviz": 0,
            "move_group": 0,
            "controller_manager": 0,
            "micro_ros_agent": 0,
        }

        for proc_data in process_snapshot:
            target = f"{proc_data['name_l']} {proc_data['cmdline_l']}"
            if "ros2" in target:
                groups["ros2"] += 1
            if any(term in target for term in ("gazebo", "gzserver", "gzclient")):
                groups["gazebo"] += 1
            if "rviz" in target:
                groups["rviz"] += 1
            if "move_group" in target:
                groups["move_group"] += 1
            if "controller_manager" in target:
                groups["controller_manager"] += 1
            if "micro_ros_agent" in target:
                groups["micro_ros_agent"] += 1

        tracked = (
            self._active_apps_provider()
            if self._active_apps_provider
            else self.process_manager.get_active_processes()
        )
        lines = [
            f"ROS 2 processes:           {groups['ros2']}",
            f"Gazebo-related:            {groups['gazebo']}",
            f"RViz-related:              {groups['rviz']}",
            f"MoveIt (move_group):       {groups['move_group']}",
            f"Controller manager:        {groups['controller_manager']}",
            f"micro-ROS agent:           {groups['micro_ros_agent']}",
            "",
            f"Dashboard tracked launches: {len(tracked)}",
        ]
        if tracked:
            lines.append("Tracked names:")
            for name in tracked[:8]:
                lines.append(f"  - {name}")
            if len(tracked) > 8:
                lines.append(f"  ... +{len(tracked) - 8} more")

        self._set_plain_text_if_changed(self.ros_details, "\n".join(lines))

    def _refresh_ros_graph_cache(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_ros_probe_time) < self._ros_probe_interval_s:
            return
        if self._ros_graph_process is not None:
            return

        self._last_ros_probe_time = now
        command = "ros2 topic list 2>/dev/null; echo __DASH_SPLIT__; ros2 node list 2>/dev/null"
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setProgram("/bin/bash")
        proc.setArguments(["-lc", f"{self._shell_prefix}{command}"])
        proc.finished.connect(self._on_ros_graph_finished)
        self._ros_graph_process = proc
        proc.start()
        self._ros_graph_timeout.start(2200)

    def _on_ros_graph_finished(self, _exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        proc = self._ros_graph_process
        self._ros_graph_timeout.stop()
        self._ros_graph_process = None
        if proc is None:
            return

        output = bytes(proc.readAll()).decode("utf-8", errors="replace")
        proc.deleteLater()

        topic_part = output
        node_part = ""
        if "__DASH_SPLIT__" in output:
            topic_part, node_part = output.split("__DASH_SPLIT__", 1)

        topics = {line.strip() for line in topic_part.splitlines() if line.strip().startswith("/")}
        nodes = {line.strip() for line in node_part.splitlines() if line.strip().startswith("/")}
        self._ros_topics = topics
        self._ros_nodes = nodes
        self._ros_graph_ready = bool(topics or nodes)

        if self.hardware_diag_panel.isVisible():
            self._render_hardware_diagnostics()

    def _on_ros_graph_timeout(self) -> None:
        if self._ros_graph_process is None:
            return
        try:
            self._ros_graph_process.kill()
        except Exception:
            pass

    def _process_exists(
        self,
        *terms: str,
        process_snapshot: Optional[List[Dict[str, object]]] = None,
    ) -> bool:
        lowered = [term.lower() for term in terms if term]
        if not lowered:
            return False
        if process_snapshot is not None:
            for proc_data in process_snapshot:
                target = f"{proc_data['name_l']} {proc_data['cmdline_l']}"
                if all(term in target for term in lowered):
                    return True
            return False

        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                target = f"{name} {cmdline}"
                if all(term in target for term in lowered):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def _is_full_hardware_active(self, process_snapshot: List[Dict[str, object]]) -> bool:
        hardware_running = self.process_manager.is_running("hardware_full_system") or self._process_exists(
            "dexter_arm_hardware",
            "hardware_bringup.launch.py",
            process_snapshot=process_snapshot,
        )
        agent_running = self._process_exists("micro_ros_agent", process_snapshot=process_snapshot)
        esp_topics_present = any(
            topic in self._ros_topics
            for topic in ("/esp32/joint_commands", "/esp32/joint_states", "/esp32/pca9685_status")
        )
        return hardware_running and (agent_running or esp_topics_present)

    def _is_tcp_pose_source_available(self, process_snapshot: List[Dict[str, object]]) -> bool:
        if not self._process_exists("robot_state_publisher", process_snapshot=process_snapshot):
            return False
        if not self._ros_graph_ready:
            return True
        return "/tf" in self._ros_topics or "/tf_static" in self._ros_topics

    def _update_conditional_sections(self, process_snapshot: List[Dict[str, object]]) -> None:
        # ROS graph probing is expensive; refresh it only periodically and only
        # when we might need node/topic-level gating.
        if self._process_exists("robot_state_publisher", process_snapshot=process_snapshot) or self.hardware_diag_panel.isVisible():
            self._refresh_ros_graph_cache()

        hardware_visible = self._is_full_hardware_active(process_snapshot)
        changed = self.hardware_diag_panel.isVisible() != hardware_visible
        self.hardware_diag_panel.setVisible(hardware_visible)
        if hardware_visible:
            self._update_hardware_diagnostics()
        else:
            self._set_plain_text_if_changed(self.hardware_diag_text, "")

        tcp_visible = self._is_tcp_pose_source_available(process_snapshot)
        if self.tcp_pose_panel.isVisible() != tcp_visible:
            changed = True
        self.tcp_pose_panel.setVisible(tcp_visible)
        if not tcp_visible:
            self._set_plain_text_if_changed(self.tcp_pose_text, "")
        elif not self.tcp_pose_text.toPlainText().strip():
            self._set_plain_text_if_changed(
                self.tcp_pose_text,
                "TCP pose source is ready.\nClick 'Get TCP Poses' to fetch current left/right tool poses."
            )

        if changed:
            self.main_panel.updateGeometry()

    def _update_hardware_diagnostics(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or (now - self._last_hw_query_time) >= self._hw_query_interval_s:
            self._start_hw_diag_query(force=force)
        self._render_hardware_diagnostics()

    def _start_hw_diag_query(self, force: bool = False) -> None:
        if self._hw_diag_process is not None:
            return

        now = time.monotonic()
        if not force and (now - self._last_hw_query_time) < self._hw_query_interval_s:
            return

        self._last_hw_query_time = now
        command = (
            "ros2 control list_controllers 2>/dev/null; "
            "echo __HW_SPLIT__; "
            "ros2 control list_hardware_components 2>/dev/null"
        )
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setProgram("/bin/bash")
        proc.setArguments(["-lc", f"{self._shell_prefix}{command}"])
        proc.finished.connect(self._on_hw_diag_finished)
        self._hw_diag_process = proc
        proc.start()
        self._hw_diag_timeout.start(3000)

    def _on_hw_diag_finished(self, _exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        proc = self._hw_diag_process
        self._hw_diag_timeout.stop()
        self._hw_diag_process = None
        if proc is None:
            return

        output = bytes(proc.readAll()).decode("utf-8", errors="replace")
        proc.deleteLater()

        controllers = output
        hardware_components = ""
        if "__HW_SPLIT__" in output:
            controllers, hardware_components = output.split("__HW_SPLIT__", 1)

        self._controllers_cache = controllers.strip()
        self._hardware_components_cache = hardware_components.strip()
        self._last_hw_diag_refresh = time.monotonic()
        if self.hardware_diag_panel.isVisible():
            self._render_hardware_diagnostics()

    def _on_hw_diag_timeout(self) -> None:
        if self._hw_diag_process is None:
            return
        try:
            self._hw_diag_process.kill()
        except Exception:
            pass

    def _render_hardware_diagnostics(self) -> None:
        lines = [f"Snapshot: {dt.datetime.now().strftime('%H:%M:%S')}", ""]
        topic_rows = [
            "/esp32/joint_commands",
            "/esp32/joint_states",
            "/esp32/pca9685_status",
        ]
        lines.append("ESP32 Topics:")
        for topic in topic_rows:
            status = "available" if topic in self._ros_topics else "missing"
            lines.append(f"  {topic}: {status}")

        lines.append("")
        lines.append("Controllers:")
        if self._hw_diag_process is not None and not self._controllers_cache:
            lines.append("  Loading...")
        else:
            lines.extend(self._compact_lines(self._controllers_cache, max_lines=8))

        lines.append("")
        lines.append("Hardware Components:")
        if self._hw_diag_process is not None and not self._hardware_components_cache:
            lines.append("  Loading...")
        else:
            lines.extend(self._compact_lines(self._hardware_components_cache, max_lines=8))

        self._set_plain_text_if_changed(self.hardware_diag_text, "\n".join(lines))

    def _fetch_tcp_poses(self) -> None:
        process_snapshot = self._collect_process_snapshot()
        self._refresh_ros_graph_cache(force=True)
        if not self._is_tcp_pose_source_available(process_snapshot):
            self.tcp_pose_text.setPlainText(
                "TCP poses are not available.\nrobot_state_publisher and TF publishers are required."
            )
            return

        if self._tcp_fetch_process is not None:
            return

        self.btn_tcp_fetch.setEnabled(False)
        self._set_plain_text_if_changed(self.tcp_pose_text, "Fetching TCP poses...")

        command = (
            "timeout 2.2s ros2 run tf2_ros tf2_echo world tool0_left 2>&1 || true; "
            "echo __TCP_SPLIT_1__; "
            "timeout 2.2s ros2 run tf2_ros tf2_echo base_link tool0_left 2>&1 || true; "
            "echo __TCP_SPLIT_2__; "
            "timeout 2.2s ros2 run tf2_ros tf2_echo world tool0_right 2>&1 || true; "
            "echo __TCP_SPLIT_3__; "
            "timeout 2.2s ros2 run tf2_ros tf2_echo base_link tool0_right 2>&1 || true"
        )

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setProgram("/bin/bash")
        proc.setArguments(["-lc", f"{self._shell_prefix}{command}"])
        proc.finished.connect(self._on_tcp_fetch_finished)
        self._tcp_fetch_process = proc
        proc.start()
        self._tcp_fetch_timeout.start(11000)

    def _on_tcp_fetch_finished(self, _exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        proc = self._tcp_fetch_process
        self._tcp_fetch_timeout.stop()
        self._tcp_fetch_process = None
        self.btn_tcp_fetch.setEnabled(True)
        if proc is None:
            return

        output = bytes(proc.readAll()).decode("utf-8", errors="replace")
        proc.deleteLater()

        left_world = ""
        left_base = ""
        right_world = ""
        right_base = ""
        p1 = output.split("__TCP_SPLIT_1__", 1)
        if len(p1) == 2:
            left_world = p1[0]
            p2 = p1[1].split("__TCP_SPLIT_2__", 1)
            if len(p2) == 2:
                left_base = p2[0]
                p3 = p2[1].split("__TCP_SPLIT_3__", 1)
                if len(p3) == 2:
                    right_world = p3[0]
                    right_base = p3[1]

        left_pose = self._parse_tf2_echo(left_world)
        if left_pose is not None:
            left_pose["source"] = "world"
        else:
            left_pose = self._parse_tf2_echo(left_base)
            if left_pose is not None:
                left_pose["source"] = "base_link"

        right_pose = self._parse_tf2_echo(right_world)
        if right_pose is not None:
            right_pose["source"] = "world"
        else:
            right_pose = self._parse_tf2_echo(right_base)
            if right_pose is not None:
                right_pose["source"] = "base_link"

        lines = [f"Snapshot: {dt.datetime.now().strftime('%H:%M:%S')}", ""]
        if left_pose:
            lx, ly, lz = left_pose["translation"]
            lines.append(f"Left TCP (tool0_left) wrt {left_pose['source']}:")
            lines.append(f"  Position (m): X={lx:.3f}  Y={ly:.3f}  Z={lz:.3f}")
            if left_pose.get("rpy_deg") is not None:
                lr, lp, lyaw = left_pose["rpy_deg"]
                lines.append(f"  RPY (deg):   R={lr:.1f}  P={lp:.1f}  Y={lyaw:.1f}")
        else:
            lines.append("Left TCP (tool0_left): unavailable")

        lines.append("")
        if right_pose:
            rx, ry, rz = right_pose["translation"]
            lines.append(f"Right TCP (tool0_right) wrt {right_pose['source']}:")
            lines.append(f"  Position (m): X={rx:.3f}  Y={ry:.3f}  Z={rz:.3f}")
            if right_pose.get("rpy_deg") is not None:
                rr, rp, ryaw = right_pose["rpy_deg"]
                lines.append(f"  RPY (deg):   R={rr:.1f}  P={rp:.1f}  Y={ryaw:.1f}")
        else:
            lines.append("Right TCP (tool0_right): unavailable")

        self._set_plain_text_if_changed(self.tcp_pose_text, "\n".join(lines))

    def _on_tcp_fetch_timeout(self) -> None:
        if self._tcp_fetch_process is None:
            return
        try:
            self._tcp_fetch_process.kill()
        except Exception:
            pass
        self._tcp_fetch_process = None
        self.btn_tcp_fetch.setEnabled(True)
        self._set_plain_text_if_changed(
            self.tcp_pose_text,
            "TCP pose fetch timed out.\nTry again when TF is stable.",
        )

    def _parse_tf2_echo(self, output: str) -> Optional[Dict[str, object]]:
        if not output:
            return None

        translations = re.findall(r"Translation:\s*\[([^\]]+)\]", output)
        if not translations:
            return None

        translation = self._parse_triplet(translations[-1])
        if translation is None:
            return None

        rpy_deg = None
        rpy_matches = re.findall(r"RPY \(degree\)\s*\[([^\]]+)\]", output)
        if rpy_matches:
            rpy_deg = self._parse_triplet(rpy_matches[-1])

        return {
            "translation": translation,
            "rpy_deg": rpy_deg,
        }

    @staticmethod
    def _parse_triplet(value: str) -> Optional[Tuple[float, float, float]]:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) < 3:
            return None
        try:
            return float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            return None

    @staticmethod
    def _compact_lines(text: str, max_lines: int = 6) -> List[str]:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ["  No data"]
        if len(lines) <= max_lines:
            return [f"  {line}" for line in lines]
        visible = [f"  {line}" for line in lines[:max_lines]]
        visible.append(f"  ... +{len(lines) - max_lines} more")
        return visible

    def _update_top_processes(self, process_snapshot: List[Dict[str, object]]) -> None:
        now = time.monotonic()
        if (now - self._last_top_refresh) < self._top_refresh_interval_s:
            return
        self._last_top_refresh = now

        # Preselect by memory usage to avoid calling cpu_percent on all processes.
        candidates = sorted(
            process_snapshot,
            key=lambda item: item.get("memory_percent", 0.0),
            reverse=True,
        )[:30]

        rows = []
        for proc_data in candidates:
            try:
                proc = proc_data["proc"]
                cpu_val = proc.cpu_percent(interval=None)
                mem_val = float(proc_data.get("memory_percent") or 0.0)
                if cpu_val < 0.1 and mem_val < 0.1:
                    continue
                rows.append(
                    (
                        int(proc_data.get("pid", 0) or 0),
                        str(proc_data.get("name", "") or ""),
                        float(cpu_val),
                        mem_val,
                        str(proc_data.get("status", "") or ""),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        rows.sort(key=lambda item: (item[2], item[3]), reverse=True)
        rows = rows[:12]

        self.top_table.setRowCount(len(rows))
        for r, (pid, name, cpu_v, mem_v, status) in enumerate(rows):
            values = [
                str(pid),
                name,
                f"{cpu_v:.1f}",
                f"{mem_v:.1f}",
                status,
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.top_table.setItem(r, c, item)

    @staticmethod
    def _set_plain_text_if_changed(widget: QPlainTextEdit, text: str) -> None:
        if widget.toPlainText() != text:
            widget.setPlainText(text)

    def closeEvent(self, event) -> None:
        if hasattr(self, "refresh_timer") and self.refresh_timer.isActive():
            self.refresh_timer.stop()
        self._ros_graph_timeout.stop()
        self._hw_diag_timeout.stop()
        self._tcp_fetch_timeout.stop()
        for proc in (self._ros_graph_process, self._hw_diag_process, self._tcp_fetch_process):
            if proc is None:
                continue
            try:
                proc.kill()
            except Exception:
                pass
        self._ros_graph_process = None
        self._hw_diag_process = None
        self._tcp_fetch_process = None
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        if hasattr(self, "refresh_timer") and not self.refresh_timer.isActive():
            self.refresh_timer.start()
        self._refresh()
        super().showEvent(event)
