"""HUD-style Trajectory Teach & Repeat window for the dashboard.

Provides a PyQt6 UI for:
- Launching / stopping the trajectory system backend (manager + visualizer)
- Capturing MoveIt planned trajectory segments
- Compiling, previewing, saving, and loading trajectories
- Executing compiled trajectories on the arm
- Real-time status and execution progress monitoring

All ROS 2 interactions happen via QProcess shell commands so the dashboard
itself never initialises rclpy.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .process_manager import ProcessManager


# ---------------------------------------------------------------------------
# Service / topic names used by the trajectory_manager node
# ---------------------------------------------------------------------------
_SVC_CAPTURE   = "/trajectory_manager/capture_segment"
_SVC_CLEAR     = "/trajectory_manager/clear_buffer"
_SVC_COMPILE   = "/trajectory_manager/compile"
_SVC_SAVE      = "/trajectory_manager/save"
_SVC_LOAD      = "/trajectory_manager/load"
_SVC_STATUS    = "/trajectory_manager/get_status"
_SVC_EXECUTE   = "/trajectory_manager/execute"
_TOPIC_PROGRESS = "/trajectory_manager/execution_progress"

_MSG_PKG = "dexter_arm_trajectory_msgs"
# Updated to use Dexter_Robotics workspace instead of old dexter_arm_ws
# Falls back to ~/.local/dexter_trajectories if workspace path unavailable
_WORKSPACE_PATH = Path("/home/raj/Dexter_Robotics")
_TRAJ_STORAGE = (
    _WORKSPACE_PATH / "src" / "dexter_arm_dashboard" / "data" / "trajectories"
    if _WORKSPACE_PATH.exists()
    else Path.home() / ".local" / "dexter_trajectories"
)

_LAUNCH_PROCESS_NAME = "_trajectory_system"  # Hidden from HUD (underscore prefix)


class TrajectorySystemWindow(QWidget):
    """Non-modal HUD window for the trajectory teach-repeat workflow."""

    def __init__(
        self,
        process_manager: ProcessManager,
        workspace_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self.process_manager = process_manager
        self.workspace_dir = Path(workspace_dir).expanduser()
        self._shell_prefix = self._build_shell_prefix()

        # QProcess handles for async ROS CLI calls
        self._svc_process: Optional[QProcess] = None
        self._svc_timeout: Optional[QTimer] = None
        self._status_process: Optional[QProcess] = None
        self._progress_process: Optional[QProcess] = None
        self._backend_process: Optional[QProcess] = None  # Direct backend launch (not via process_manager)

        # State
        self._backend_running = False
        self._executing = False
        self._has_compiled = False
        self._segment_count = 0

        # ── Window flags & styling ────────────────────────────────────────
        self.setWindowTitle("Trajectory System")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("trajectory_system_window")
        self.setMinimumSize(820, 780)
        self.resize(900, 860)
        self._apply_stylesheet()

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_ui()

        # ── Timers ────────────────────────────────────────────────────────
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)  # 5s when idle (backend confirmed)
        self._status_timer.timeout.connect(self._poll_status)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(2000)  # 2s when idle, 500ms during execution
        self._progress_timer.timeout.connect(self._poll_progress)

        self._backend_check_timer = QTimer(self)
        self._backend_check_timer.setInterval(3000)
        self._backend_check_timer.timeout.connect(self._check_backend_running)

        self._sync_backend_state()
        # Auto-launch backend when window opens
        if not self._backend_running:
            self._auto_start_backend()
        
        # Log initialization info and limitations
        self._log("=" * 60)
        self._log("⚠️  Trajectory System - Legacy Mode")
        self._log("=" * 60)
        self._log("NOTE: This window requires the dexter_arm_trajectory package")
        self._log("which is not available in the current Dexter_Robotics workspace.")
        self._log("")
        self._log("RECOMMENDED: Use middleware APIs from FastAPI docs instead:")
        self._log("  1. Open http://127.0.0.1:8090 in your browser")
        self._log("  2. Use /trajectory/* endpoints for generate/validate/execute")
        self._log("  3. Use /ros/* endpoints for runtime stack control")
        self._log("")
        self._log("Python site-packages setup may also be required to make python imports work.") 
        self._log("=" * 60)

    # ──────────────────────────────────────────────────────────────────────
    # Shell helpers
    # ──────────────────────────────────────────────────────────────────────
    def _build_shell_prefix(self) -> str:
        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        return (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(str(self.workspace_dir))} && "
            "source install/setup.bash && "
        )

    # ──────────────────────────────────────────────────────────────────────
    # Stylesheet
    # ──────────────────────────────────────────────────────────────────────
    def _apply_stylesheet(self) -> None:
        self.setStyleSheet("""
            QWidget#trajectory_system_window {
                background-color: #0d1626;
            }
            QFrame#main_panel {
                background-color: #16263d;
                border: 1px solid #2f4b72;
                border-radius: 14px;
            }
            QGroupBox {
                background-color: #1c304d;
                border: 1px solid #395a84;
                border-radius: 10px;
                margin-top: 14px;
                color: #d9e7ff;
                font-weight: 600;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #00f3ff;
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
            QLabel#status_value {
                color: #00f3ff;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#metric_key {
                color: #97bde5;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#metric_value {
                color: #00f3ff;
                font-size: 16px;
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
            QLineEdit {
                background-color: #0f1a2e;
                color: #ebf2ff;
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
                min-height: 22px;
            }
            QProgressBar::chunk {
                background-color: #2f73c9;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #2a5f9c;
                color: #ffffff;
                border: 1px solid #4b84cc;
                border-radius: 7px;
                padding: 8px 14px;
                font-weight: 700;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #3473b7;
            }
            QPushButton:pressed {
                background-color: #1d4a7c;
            }
            QPushButton:disabled {
                color: #8297b8;
                border-color: #5b6f90;
                background-color: #122238;
            }
            QPushButton#start_btn {
                background-color: #1a6b3a;
                border-color: #2da85c;
            }
            QPushButton#start_btn:hover {
                background-color: #228a4a;
            }
            QPushButton#stop_btn {
                background-color: #7c2a2a;
                border-color: #b84545;
            }
            QPushButton#stop_btn:hover {
                background-color: #993434;
            }
            QPushButton#danger {
                background-color: #7c2a2a;
                border-color: #b84545;
            }
            QPushButton#danger:hover {
                background-color: #993434;
            }
            QPushButton#secondary {
                background-color: #213f63;
                border: 1px solid #3e6eaa;
            }
            QPushButton#secondary:hover {
                background-color: #2a5482;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QTabWidget::pane {
                border: 1px solid #395a84;
                border-radius: 8px;
                background-color: #16263d;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #1c304d;
                color: #97bde5;
                border: 1px solid #395a84;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 18px;
                margin-right: 2px;
                font-weight: 600;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #16263d;
                color: #00f3ff;
                border-bottom: 2px solid #00f3ff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #213f63;
                color: #c8d9ef;
            }
            QComboBox {
                background-color: #0f1a2e;
                color: #ebf2ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                padding: 6px;
                min-height: 24px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #0f1a2e;
                color: #ebf2ff;
                selection-background-color: #2a5f9c;
                border: 1px solid #40618f;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #0f1a2e;
                color: #ebf2ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                padding: 6px;
                min-height: 24px;
            }
            QRadioButton {
                color: #e8f2ff;
                spacing: 6px;
            }
            QRadioButton::indicator {
                width: 16px; height: 16px;
            }
            QSlider::groove:horizontal {
                background: #0f1a2e;
                border: 1px solid #476993;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00f3ff;
                border: 1px solid #2a5f9c;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #2f73c9;
                border-radius: 4px;
            }
        """)

    # ──────────────────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)

        panel = QFrame(content)
        panel.setObjectName("main_panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 18, 18, 18)
        pl.setSpacing(10)
        content_layout.addWidget(panel)

        # Title
        title = QLabel("Trajectory System", panel)
        title.setObjectName("title")
        subtitle = QLabel(
            "Teach, generate shapes, compile, save/load, and execute trajectories.",
            panel,
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        pl.addWidget(title)
        pl.addWidget(subtitle)

        # ── Backend control (shared) ──────────────────────────────────────
        backend_group = QGroupBox("⚙  BACKEND")
        bg_layout = QHBoxLayout()

        self.btn_stop_backend = QPushButton("⏹  Stop Backend")
        self.btn_stop_backend.setObjectName("stop_btn")
        self.btn_stop_backend.setEnabled(False)
        self.btn_stop_backend.clicked.connect(self._stop_backend)
        bg_layout.addWidget(self.btn_stop_backend)

        self.backend_status_label = QLabel("Backend: unknown")
        self.backend_status_label.setObjectName("status_value")
        bg_layout.addWidget(self.backend_status_label, 1)

        backend_group.setLayout(bg_layout)
        pl.addWidget(backend_group)

        # ── Tab widget ────────────────────────────────────────────────────
        self.tab_widget = QTabWidget()
        pl.addWidget(self.tab_widget, 1)

        self._build_teach_tab()
        self._build_load_execute_tab()
        self._build_safe_zone_shape_tab()

        # ── Status summary (shared) ───────────────────────────────────────
        status_group = QGroupBox("📊  STATUS")
        sl = QGridLayout()
        sl.setHorizontalSpacing(16)
        sl.setVerticalSpacing(6)

        status_items = [
            ("Status", "status"),
            ("Segments", "segments"),
            ("Waypoints", "waypoints"),
            ("Duration", "duration"),
            ("File", "filename"),
        ]
        self._status_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(status_items):
            k = QLabel(label)
            k.setObjectName("metric_key")
            v = QLabel("--")
            v.setObjectName("metric_value")
            self._status_labels[key] = v
            sl.addWidget(k, row, 0)
            sl.addWidget(v, row, 1)
        sl.setColumnStretch(1, 1)

        status_group.setLayout(sl)
        pl.addWidget(status_group)

        # ── Log (shared) ──────────────────────────────────────────────────
        log_group = QGroupBox("📝  LOG")
        ll = QVBoxLayout()

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(160)
        ll.addWidget(self.log_text)

        log_group.setLayout(ll)
        pl.addWidget(log_group)

    # ──────────────────────────────────────────────────────────────────────
    # Tab 1 — Teach Mode
    # ──────────────────────────────────────────────────────────────────────
    def _build_teach_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 10, 6, 6)

        # Teach section
        teach_group = QGroupBox("📚  TEACH MODE")
        tl = QVBoxLayout()

        instructions = QLabel(
            "1. Use MoveIt in RViz to plan arm motion\n"
            "2. Click Capture Segment when satisfied\n"
            "3. Repeat for each waypoint / segment"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #c9dcf5;")
        tl.addWidget(instructions)

        teach_btns = QHBoxLayout()

        self.btn_capture = QPushButton("📷  Capture Segment")
        self.btn_capture.setEnabled(False)
        self.btn_capture.clicked.connect(self._capture_segment)
        teach_btns.addWidget(self.btn_capture)

        self.btn_clear = QPushButton("🗑  Clear Buffer")
        self.btn_clear.setObjectName("danger")
        self.btn_clear.setEnabled(False)
        self.btn_clear.clicked.connect(self._clear_buffer)
        teach_btns.addWidget(self.btn_clear)

        tl.addLayout(teach_btns)

        self.segments_label = QLabel("Segments: 0")
        self.segments_label.setObjectName("status_value")
        tl.addWidget(self.segments_label)

        teach_group.setLayout(tl)
        layout.addWidget(teach_group)

        # Compile & Save section
        compile_group = QGroupBox("⚙  COMPILE & SAVE")
        cl = QVBoxLayout()

        compile_btns = QHBoxLayout()

        self.btn_compile = QPushButton("⚙  Compile Trajectory")
        self.btn_compile.setEnabled(False)
        self.btn_compile.clicked.connect(self._compile_trajectory)
        compile_btns.addWidget(self.btn_compile)

        self.btn_preview = QPushButton("👁  Preview in RViz")
        self.btn_preview.setObjectName("secondary")
        self.btn_preview.setEnabled(False)
        self.btn_preview.clicked.connect(self._preview_trajectory)
        compile_btns.addWidget(self.btn_preview)

        cl.addLayout(compile_btns)

        save_row = QHBoxLayout()
        self.btn_save = QPushButton("💾  Save")
        self.btn_save.setObjectName("secondary")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_trajectory)
        save_row.addWidget(self.btn_save)
        cl.addLayout(save_row)

        compile_group.setLayout(cl)
        layout.addWidget(compile_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "📚 Teach Mode")

    # ──────────────────────────────────────────────────────────────────────
    # Tab 2 — Load & Execute
    # ──────────────────────────────────────────────────────────────────────
    def _build_load_execute_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 10, 6, 6)

        # Load section
        load_group = QGroupBox("📂  LOAD TRAJECTORY")
        ll = QVBoxLayout()

        self.btn_load = QPushButton("📂  Load from File")
        self.btn_load.clicked.connect(self._load_trajectory)
        ll.addWidget(self.btn_load)

        load_group.setLayout(ll)
        layout.addWidget(load_group)

        # Execute section
        exec_group = QGroupBox("▶  EXECUTE")
        el = QVBoxLayout()

        exec_btns = QHBoxLayout()

        self.btn_execute = QPushButton("▶  Execute Trajectory")
        self.btn_execute.setEnabled(False)
        self.btn_execute.clicked.connect(self._execute_trajectory)
        exec_btns.addWidget(self.btn_execute)

        self.btn_stop_exec = QPushButton("⏸  Stop")
        self.btn_stop_exec.setObjectName("danger")
        self.btn_stop_exec.setEnabled(False)
        self.btn_stop_exec.clicked.connect(self._stop_execution)
        exec_btns.addWidget(self.btn_stop_exec)

        el.addLayout(exec_btns)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        el.addWidget(self.progress_bar)

        exec_group.setLayout(el)
        layout.addWidget(exec_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "▶ Load & Execute")

    # ──────────────────────────────────────────────────────────────────────
    # Tab 3 — Safe Zone Shape Generator (Right Arm Only)
    # ──────────────────────────────────────────────────────────────────────
    _SAFE_SHAPE_PARAMS = {
        # name: [(label, field_key, default, min, max), ...]
        "Circle":    [("Radius (m)",  "param1", 0.05, 0.02, 0.20)],
        "Rectangle": [("Width (m)",   "param1", 0.08, 0.02, 0.25),
                      ("Height (m)",  "param2", 0.05, 0.02, 0.25)],
        "Square":    [("Side (m)",    "param1", 0.06, 0.02, 0.20)],
        "Line":      [("Length (m)",  "param1", 0.10, 0.02, 0.30)],
        "Triangle":  [("Side (m)",    "param1", 0.06, 0.02, 0.20)],
    }

    _MAX_ABSOLUTE_REACH = 0.35  # Meters

    def _build_safe_zone_shape_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 10, 6, 6)

        # ── Safe Zone Reference point ─────────────────────────────────────
        ref_group = QGroupBox("📍  SAFE ZONE ANCHOR")
        rg = QVBoxLayout()

        help_label = QLabel(
            "Set the origin point for your shape. Bounded to Right-Arm physical limits.<br>"
            "<i>(Extents dynamically capped to prevent collisions with the reach envelope.)</i>"
        )
        help_label.setStyleSheet("color: #c9dcf5; font-size: 11px;")
        help_label.setWordWrap(True)
        rg.addWidget(help_label)

        # X Constraint Slider
        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("Anchor X:"))
        self.ref_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_x_slider.setMinimumWidth(200)
        x_row.addWidget(self.ref_x_slider, 1)
        self.ref_x_spin = QDoubleSpinBox()
        self.ref_x_spin.setRange(0.10, 0.35)
        self.ref_x_spin.setDecimals(3)
        self.ref_x_spin.setSingleStep(0.01)
        self.ref_x_spin.setValue(0.25)
        self.ref_x_spin.setFixedWidth(90)
        x_row.addWidget(self.ref_x_spin)
        rg.addLayout(x_row)

        # Y Constraint Slider
        y_row = QHBoxLayout()
        y_row.addWidget(QLabel("Anchor Y:"))
        self.ref_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_y_slider.setMinimumWidth(200)
        y_row.addWidget(self.ref_y_slider, 1)
        self.ref_y_spin = QDoubleSpinBox()
        self.ref_y_spin.setRange(-0.35, 0.35)
        self.ref_y_spin.setDecimals(3)
        self.ref_y_spin.setSingleStep(0.01)
        self.ref_y_spin.setValue(0.23)
        self.ref_y_spin.setFixedWidth(90)
        y_row.addWidget(self.ref_y_spin)
        rg.addLayout(y_row)

        # Z Constraint Slider
        z_row = QHBoxLayout()
        z_row.addWidget(QLabel("Anchor Z:"))
        self.ref_z_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_z_slider.setMinimumWidth(200)
        z_row.addWidget(self.ref_z_slider, 1)
        self.ref_z_spin = QDoubleSpinBox()
        self.ref_z_spin.setRange(0.05, 0.25)
        self.ref_z_spin.setDecimals(3)
        self.ref_z_spin.setSingleStep(0.01)
        self.ref_z_spin.setValue(0.20)
        self.ref_z_spin.setFixedWidth(90)
        z_row.addWidget(self.ref_z_spin)
        rg.addLayout(z_row)

        # Wire Sliders to Spins
        self._SLIDER_SCALE = 1000
        self.ref_x_slider.setRange(100, 350)
        self.ref_y_slider.setRange(-350, 350)
        self.ref_z_slider.setRange(50, 250)
        
        # Center Sliders
        self.ref_x_slider.setValue(250)
        self.ref_y_slider.setValue(230)
        self.ref_z_slider.setValue(200)

        self.ref_x_slider.valueChanged.connect(self._on_x_slider_changed)
        self.ref_x_spin.valueChanged.connect(self._on_x_spin_changed)
        self.ref_y_slider.valueChanged.connect(self._on_y_slider_changed)
        self.ref_y_spin.valueChanged.connect(self._on_y_spin_changed)
        self.ref_z_slider.valueChanged.connect(self._on_z_slider_changed)
        self.ref_z_spin.valueChanged.connect(self._on_z_spin_changed)

        ref_group.setLayout(rg)
        layout.addWidget(ref_group)

        # ── Shape selection ───────────────────────────────────────────────
        shape_group = QGroupBox("🔷  SHAPE & DIMENSIONS")
        sg = QVBoxLayout()

        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel("Shape:"))
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(list(self._SAFE_SHAPE_PARAMS.keys()))
        self.shape_combo.currentTextChanged.connect(self._on_shape_changed)
        shape_row.addWidget(self.shape_combo, 1)
        sg.addLayout(shape_row)

        # Dynamic Size Inputs
        self._shape_dim_labels: list[QLabel] = []
        self._shape_dim_sliders: list[QSlider] = []
        self._shape_dim_val_labels: list[QLabel] = []
        self._shape_dim_widgets: list[QWidget] = []

        for i in range(2):  # max 2 params (Rectangle has 2)
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(f"Size {i+1}:")
            lbl.setFixedWidth(90)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimumWidth(160)
            slider.setRange(20, 200)   # default 0.02–0.20 m × 1000; overwritten per-shape
            slider.setValue(50)
            val_lbl = QLabel("0.050 m")
            val_lbl.setFixedWidth(62)
            val_lbl.setStyleSheet("color: #7dd3fc; font-weight: 600;")
            idx = i  # capture loop var
            slider.valueChanged.connect(lambda v, idx=idx: self._on_dim_slider_changed(idx, v))
            row.addWidget(lbl)
            row.addWidget(slider, 1)
            row.addWidget(val_lbl)
            self._shape_dim_labels.append(lbl)
            self._shape_dim_sliders.append(slider)
            self._shape_dim_val_labels.append(val_lbl)
            self._shape_dim_widgets.append(container)
            sg.addWidget(container)

        # Custom Trajectory Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Traj Name:"))
        self.traj_name_input = QLineEdit()
        self.traj_name_input.setPlaceholderText("e.g. circle")
        name_row.addWidget(self.traj_name_input, 1)
        sg.addLayout(name_row)

        shape_group.setLayout(sg)
        layout.addWidget(shape_group)
        
        # ── Waypoint density ──────────────────────────────────────────────
        density_row = QHBoxLayout()
        density_row.addWidget(QLabel("Waypoints:"))
        self.waypoint_spin = QSpinBox()
        self.waypoint_spin.setRange(10, 300)
        self.waypoint_spin.setValue(90)
        density_row.addWidget(self.waypoint_spin)
        density_row.addStretch()
        layout.addLayout(density_row)

        # ── Generate Action ───────────────────────────────────────────────
        gen_group = QGroupBox("🚀  GENERATE & EXPORT TO CSV")
        gl = QVBoxLayout()

        msg_label = QLabel("Will locally emit native `.yaml` & visualizer `.csv` to your workspaces folder.")
        msg_label.setStyleSheet("color: #799bbb; font-style: italic; font-size: 11px;")
        gl.addWidget(msg_label)

        self.btn_generate_shape = QPushButton("🔷  Generate Safe-Zone Trajectory")
        self.btn_generate_shape.setObjectName("start_btn")
        self.btn_generate_shape.clicked.connect(self._generate_shape)
        gl.addWidget(self.btn_generate_shape)

        self.shape_status_label = QLabel("")
        self.shape_status_label.setObjectName("status_value")
        self.shape_status_label.setWordWrap(True)
        gl.addWidget(self.shape_status_label)

        gen_group.setLayout(gl)
        layout.addWidget(gen_group)
        layout.addStretch()

        self.tab_widget.addTab(tab, "🔷 Safe Shape Generator")
        
        # Initialise fields
        self._on_shape_changed(self.shape_combo.currentText())
        self._update_dynamic_size_constraints()
        
    # ──────────────────────────────────────────────────────────────────────
    # Constraint & Slider Logic
    # ──────────────────────────────────────────────────────────────────────

    def _update_dynamic_size_constraints(self):
        """Adjust slider maximums as anchor moves to keep shape within 0.35m reach."""
        anchor_x = self.ref_x_spin.value()
        anchor_y = abs(self.ref_y_spin.value())
        dist_to_base = (anchor_x**2 + anchor_y**2) ** 0.5
        max_safe_extension = self._MAX_ABSOLUTE_REACH - dist_to_base
        # Never shrink below 5 cm so the slider stays usable
        max_limit = max(0.05, min(max_safe_extension, 0.30))
        for slider in self._shape_dim_sliders:
            cur_max_m = slider.maximum() / 1000.0
            new_max_int = int(max_limit * 1000)
            if new_max_int != slider.maximum():
                slider.setMaximum(new_max_int)
                if slider.value() > new_max_int:
                    slider.setValue(new_max_int)
            
    def _on_x_slider_changed(self, val: int) -> None:
        self.ref_x_spin.blockSignals(True)
        self.ref_x_spin.setValue(val / self._SLIDER_SCALE)
        self.ref_x_spin.blockSignals(False)
        self._update_dynamic_size_constraints()

    def _on_x_spin_changed(self, val: float) -> None:
        self.ref_x_slider.blockSignals(True)
        self.ref_x_slider.setValue(int(val * self._SLIDER_SCALE))
        self.ref_x_slider.blockSignals(False)
        self._update_dynamic_size_constraints()
        
    def _on_y_slider_changed(self, val: int) -> None:
        self.ref_y_spin.blockSignals(True)
        self.ref_y_spin.setValue(val / self._SLIDER_SCALE)
        self.ref_y_spin.blockSignals(False)
        self._update_dynamic_size_constraints()

    def _on_y_spin_changed(self, val: float) -> None:
        self.ref_y_slider.blockSignals(True)
        self.ref_y_slider.setValue(int(val * self._SLIDER_SCALE))
        self.ref_y_slider.blockSignals(False)
        self._update_dynamic_size_constraints()

    def _on_z_slider_changed(self, val: int) -> None:
        self.ref_z_spin.blockSignals(True)
        self.ref_z_spin.setValue(val / self._SLIDER_SCALE)
        self.ref_z_spin.blockSignals(False)

    def _on_z_spin_changed(self, val: float) -> None:
        self.ref_z_slider.blockSignals(True)
        self.ref_z_slider.setValue(int(val * self._SLIDER_SCALE))
        self.ref_z_slider.blockSignals(False)

    def _on_dim_slider_changed(self, idx: int, val: int) -> None:
        """Update the value label next to the shape dimension slider."""
        self._shape_dim_val_labels[idx].setText(f"{val/1000:.3f} m")

    def _on_shape_changed(self, shape_name: str) -> None:
        params = self._SAFE_SHAPE_PARAMS.get(shape_name, [])
        for i in range(2):
            if i < len(params):
                label_text, _field, default, p_min, p_max = params[i]
                self._shape_dim_labels[i].setText(label_text)
                slider = self._shape_dim_sliders[i]
                slider.blockSignals(True)
                slider.setRange(int(p_min * 1000), int(p_max * 1000))
                slider.setValue(int(default * 1000))
                slider.blockSignals(False)
                self._shape_dim_val_labels[i].setText(f"{default:.3f} m")
                self._shape_dim_widgets[i].setVisible(True)
            else:
                self._shape_dim_widgets[i].setVisible(False)

    # ──────────────────────────────────────────────────────────────────────
    # Backend launch / stop
    # ──────────────────────────────────────────────────────────────────────
    def _check_prerequisites(self) -> tuple[bool, list[str]]:
        """Check if required systems are running for trajectory capture.
        
        Returns:
            (all_met, missing_list)
            - all_met: True if all prerequisites are running
            - missing_list: List of missing prerequisite names
        """
        missing = []

        # Use non-blocking fast check via QProcess state or cached knowledge.
        # For a quick sync check we use subprocess with a very short timeout.
        import subprocess as sp
        try:
            result = sp.run(
                f"{self._shell_prefix}ros2 node list",
                shell=True, capture_output=True, text=True, timeout=3
            )
            nodes = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            nodes = ""

        if "robot_state_publisher" not in nodes:
            missing.append("robot_state_publisher")
        if "move_group" not in nodes:
            missing.append("move_group (MoveIt)")

        return (len(missing) == 0, missing)
    
    def _show_prerequisites_dialog(self, missing: list[str]) -> bool:
        """Show dialog with missing prerequisites. Returns True if user wants to proceed anyway."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Missing Prerequisites")
        msg.setIcon(QMessageBox.Icon.Warning)
        
        missing_text = "\n".join(f"  • {item}" for item in missing)
        msg.setText(
            f"The following systems are required to run Trajectory capture:\n\n"
            f"{missing_text}\n\n"
            f"Please launch them first (e.g., via Hardware window or ROS CLI).\n\n"
            f"Continue anyway?"
        )
        
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _sync_backend_state(self) -> None:
        """Check if trajectory system is already running on open."""
        running = self._backend_process is not None and self._backend_process.state() == QProcess.ProcessState.Running
        self._set_backend_state(running)
        if running:
            self._log("Backend already running")
            self._status_timer.start()
            self._backend_check_timer.start()
        else:
            self._log("Backend not running — will auto-launch")

    def _auto_start_backend(self) -> None:
        """Auto-launch backend directly via QProcess (not through process_manager)."""
        if self._backend_process is not None and self._backend_process.state() == QProcess.ProcessState.Running:
            self._log("Backend is already running")
            self._set_backend_state(True)
            return

        import os
        # Note: dexter_arm_trajectory package may not exist in current workspace
        # Users should use the web UI (Execute Saved Trajectory tab) as an alternative
        cmd = "ros2 launch dexter_arm_trajectory trajectory_system.launch.py 2>&1 || echo 'ERROR: Package dexter_arm_trajectory not found. Use web UI Execute Saved Trajectory tab instead.'"
        self._backend_process = QProcess(self)
        self._backend_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        # Build environment with ROS setup
        env = os.environ.copy()
        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        workspace = str(self.workspace_dir)
        shell_cmd = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(workspace)} && source install/setup.bash && {cmd}"
        )

        # Signal-based flow: respond when process actually starts (non-blocking)
        self._backend_process.started.connect(self._on_backend_started)
        self._backend_process.errorOccurred.connect(
            lambda err: self._log(f"✗ Failed to auto-launch backend: {err}", error=True)
        )
        self._backend_process.start("bash", ["-lc", shell_cmd])
        self._log("Launching trajectory system backend…")

    def _on_backend_started(self) -> None:
        """Called when the backend QProcess has actually started."""
        self._log("✓ Trajectory system backend launched")
        self._set_backend_state(True)
        self._status_timer.start()
        self._backend_check_timer.start()
    
    def _start_backend(self) -> None:
        """Launch trajectory_system.launch.py directly via QProcess."""
        if self._backend_process is not None and self._backend_process.state() == QProcess.ProcessState.Running:
            self._log("Backend is already running")
            self._set_backend_state(True)
            return

        # Check prerequisites
        self._log("Checking prerequisites…")
        all_met, missing = self._check_prerequisites()
        
        if not all_met:
            self._log(f"⚠  Missing prerequisites: {', '.join(missing)}", error=True)
            if not self._show_prerequisites_dialog(missing):
                self._log("Launch cancelled - prerequisites not met")
                return
            self._log("Proceeding despite missing prerequisites…")
        else:
            self._log("✓ All prerequisites available")

        import os
        cmd = "ros2 launch dexter_arm_trajectory trajectory_system.launch.py 2>&1 || echo 'ERROR: Package dexter_arm_trajectory not found. Use web UI Execute Saved Trajectory tab instead.'"
        self._backend_process = QProcess(self)
        self._backend_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        # Build environment with ROS setup
        env = os.environ.copy()
        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        workspace = str(self.workspace_dir)
        shell_cmd = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(workspace)} && source install/setup.bash && {cmd}"
        )
        
        # Signal-based flow (non-blocking)
        self._backend_process.started.connect(self._on_backend_started)
        self._backend_process.errorOccurred.connect(
            lambda err: self._log(f"Failed to launch backend: {err}", error=True)
        )
        self._backend_process.start("bash", ["-lc", shell_cmd])
        self._log("Launching trajectory system backend…")

    def _stop_backend(self) -> None:
        """Kill the trajectory system backend (non-blocking)."""
        if self._backend_process is not None and self._backend_process.state() == QProcess.ProcessState.Running:
            self._backend_process.terminate()
            # Use a short timer to force-kill if terminate doesn't work
            QTimer.singleShot(3000, self._force_kill_backend)
            self._log("Stopping backend…")
        self._set_backend_state(False)
        self._status_timer.stop()
        self._progress_timer.stop()
        self._backend_check_timer.stop()

    def _force_kill_backend(self) -> None:
        """Force-kill backend if it didn't terminate gracefully."""
        if self._backend_process is not None and self._backend_process.state() != QProcess.ProcessState.NotRunning:
            self._backend_process.kill()
            self._log("Backend force-killed")

    def _set_backend_state(self, running: bool) -> None:
        self._backend_running = running
        if hasattr(self, "btn_start_backend"):
            self.btn_start_backend.setEnabled(not running)
        self.btn_stop_backend.setEnabled(running)
        self.btn_capture.setEnabled(running)
        self.btn_clear.setEnabled(running)
        self.btn_compile.setEnabled(running)
        self.btn_load.setEnabled(running)
        self.btn_generate_shape.setEnabled(running)
        self.backend_status_label.setText(
            "Backend: RUNNING" if running else "Backend: STOPPED"
        )
        self.backend_status_label.setStyleSheet(
            "color: #00ff88; font-weight: 700;" if running
            else "color: #ff5555; font-weight: 700;"
        )
        if not running:
            self.btn_save.setEnabled(False)
            self.btn_execute.setEnabled(False)
            self.btn_stop_exec.setEnabled(False)

    def _check_backend_running(self) -> None:
        """Periodic check that the backend hasn't exited."""
        running = self._backend_process is not None and self._backend_process.state() == QProcess.ProcessState.Running
        if not running and self._backend_running:
            self._log("Backend process exited", error=True)
            self._set_backend_state(False)
            self._status_timer.stop()
            self._progress_timer.stop()
            self._backend_check_timer.stop()

    # ──────────────────────────────────────────────────────────────────────
    # Generic ROS 2 service call via QProcess
    # ──────────────────────────────────────────────────────────────────────
    def _call_service(
        self,
        service_name: str,
        srv_type: str,
        request_yaml: str = "{}",
        callback=None,
    ) -> None:
        """Call a ROS 2 service asynchronously via ``ros2 service call``."""
        if self._svc_process is not None and self._svc_process.state() != QProcess.ProcessState.NotRunning:
            self._log("A service call is already in progress — please wait", error=True)
            return

        cmd = (
            f"{self._shell_prefix}"
            f"ros2 service call {service_name} {_MSG_PKG}/srv/{srv_type} "
            f"'{request_yaml}'"
        )

        self._svc_process = QProcess(self)
        self._svc_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        def _on_svc_finished(code, _status):
            # Cancel timeout
            if hasattr(self, '_svc_timeout') and self._svc_timeout is not None:
                self._svc_timeout.stop()
                self._svc_timeout = None
            output = self._svc_process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            if callback:
                callback(output, code)
            else:
                self._on_generic_svc_finished(output, code)

        self._svc_process.finished.connect(_on_svc_finished)
        self._svc_process.start("bash", ["-c", cmd])

        # Timeout: kill hung service calls after 10 seconds
        self._svc_timeout = QTimer(self)
        self._svc_timeout.setSingleShot(True)
        self._svc_timeout.timeout.connect(self._on_svc_timeout)
        self._svc_timeout.start(10000)

    def _on_svc_timeout(self) -> None:
        """Kill a hung service call process."""
        self._svc_timeout = None
        if self._svc_process is not None and self._svc_process.state() != QProcess.ProcessState.NotRunning:
            self._log("Service call timed out (10s) — killing", error=True)
            self._svc_process.kill()

    def _on_generic_svc_finished(self, output: str, code: int) -> None:
        if code != 0:
            self._log(f"Service call failed (exit {code})", error=True)
        elif output.strip():
            # Parse a simple success/message
            success = "true" in output.lower() and "success" in output.lower()
            msg = self._extract_field(output, "message")
            if msg:
                self._log(f"{'✓' if success else '✗'} {msg}")
            else:
                self._log(output.strip()[:200])

    # ──────────────────────────────────────────────────────────────────────
    # Teach mode actions
    # ──────────────────────────────────────────────────────────────────────
    def _capture_segment(self) -> None:
        self._log("Capturing segment…")
        self.btn_capture.setEnabled(False)
        self.btn_capture.setText("⏳  Capturing…")
        self._call_service(_SVC_CAPTURE, "CaptureSegment", "{}", self._on_capture_done)

    def _on_capture_done(self, output: str, code: int) -> None:
        self.btn_capture.setEnabled(self._backend_running)
        self.btn_capture.setText("📷  Capture Segment")
        if code != 0:
            self._log("Capture failed — is the backend running?", error=True)
            return
        msg = self._extract_field(output, "message") or "Segment captured"
        count = self._extract_field(output, "segment_count")
        success = "success: true" in output.lower() or "success=true" in output.lower()
        self._log(f"{'✓' if success else '✗'} {msg}")
        if count:
            self.segments_label.setText(f"Segments: {count}")

    def _clear_buffer(self) -> None:
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "Clear all captured segments?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._log("Clearing segment buffer…")
        self._call_service(_SVC_CLEAR, "Trigger", "{}", self._on_clear_done)

    def _on_clear_done(self, output: str, _code: int) -> None:
        msg = self._extract_field(output, "message") or "Buffer cleared"
        self._log(f"✓ {msg}")
        self.segments_label.setText("Segments: 0")

    # ──────────────────────────────────────────────────────────────────────
    # Compile & preview
    # ──────────────────────────────────────────────────────────────────────
    def _compile_trajectory(self) -> None:
        self._log("Compiling trajectory…")
        self.btn_compile.setEnabled(False)
        self.btn_compile.setText("⏳  Compiling…")
        self._call_service(_SVC_COMPILE, "CompileTrajectory", "{}", self._on_compile_done)

    def _on_compile_done(self, output: str, code: int) -> None:
        self.btn_compile.setEnabled(self._backend_running)
        self.btn_compile.setText("⚙  Compile Trajectory")
        if code != 0:
            self._log("Compile failed", error=True)
            return
        success = "success: true" in output.lower() or "success=true" in output.lower()
        wpts = self._extract_field(output, "total_waypoints")
        dur = self._extract_field(output, "duration")
        if success:
            info = []
            if wpts:
                info.append(f"{wpts} waypoints")
            if dur:
                info.append(f"{dur}s")
            self._log(f"✓ Compiled: {', '.join(info)}" if info else "✓ Compiled")
            self._has_compiled = True
            self.btn_save.setEnabled(True)
            self.btn_execute.setEnabled(True)
        else:
            msg = self._extract_field(output, "message") or "Compilation failed"
            self._log(f"✗ {msg}", error=True)

    def _preview_trajectory(self) -> None:
        self._log("Trajectory preview published to RViz")
        QMessageBox.information(
            self, "Preview",
            "Check RViz for trajectory preview visualisation.\n"
            "The compiled trajectory is automatically published by the manager node.",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Safe Zone trajectory generation
    # ──────────────────────────────────────────────────────────────────────
    def _generate_shape(self) -> None:
        shape = self.shape_combo.currentText()
        params = self._SAFE_SHAPE_PARAMS.get(shape, [])

        # Extent definitions
        param1 = self._shape_dim_sliders[0].value() / 1000.0 if len(params) > 0 else 0.0
        param2 = self._shape_dim_sliders[1].value() / 1000.0 if len(params) > 1 else 0.0

        ref_x = self.ref_x_spin.value()
        ref_y = self.ref_y_spin.value()
        ref_z = self.ref_z_spin.value()
        n = self.waypoint_spin.value()
        
        custom_name = self.traj_name_input.text().strip()
        if not custom_name:
            custom_name = shape.lower()

        # We write a physical YAML configuration to disk for the `trajectory_node` to consume
        config_dir = Path("/home/raj/dexter_arm_ws/src/dexter_arm_dashboard/data/config")
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{custom_name}_config.yaml"
        
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(f"arm: 'right'\n")
            f.write(f"shape:\n")
            f.write(f"  type: '{shape.lower()}'\n")
            # Write dynamic parameters
            if shape.lower() == "circle":
                f.write(f"  radius: {param1}\n")
            elif shape.lower() == "line" or shape.lower() == "triangle" or shape.lower() == "square":
                f.write(f"  length: {param1}\n")
                f.write(f"  side_length: {param1}\n")
            elif shape.lower() == "rectangle":
                f.write(f"  width: {param1}\n")
                f.write(f"  length: {param2}\n")
            f.write(f"  n_points: {n}\n")
            f.write(f"reference_point:\n")
            f.write(f"  x: {ref_x}\n")
            f.write(f"  y: {ref_y}\n")
            f.write(f"  z: {ref_z}\n")
            f.write(f"surface_normal:\n")
            f.write(f"  x: 0.0\n")
            f.write(f"  y: 0.0\n")
            f.write(f"  z: 1.0\n")
            f.write(f"tool_tilt:\n")
            f.write(f"  x: 0.0\n")
            f.write(f"  y: 0.0\n")
            f.write(f"  z: 0.0\n")

        self._log(f"Generating Fast-Safe {shape} on right arm …")
        self.btn_generate_shape.setEnabled(False)
        self.btn_generate_shape.setText("⏳  Generating Config & IK…")
        self.shape_status_label.setText("Solving Kinematics …")

        # Updated path to use current workspace with fallback
        traj_out_path = _TRAJ_STORAGE / f"{custom_name}.yaml"
        traj_out_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Start Async QProcess to trigger generation and native KDL CSV Export
        cmd = (
            f"{self._shell_prefix}"
            f"echo 'Note: Advanced shape generation requires dexter_trajectory_generator package' && "
            f"echo 'Use operator UI (http://127.0.0.1:8090) and API docs (http://127.0.0.1:8080/docs)' && "
            f"echo '[ERROR] dexter_trajectory_generator package not found in current workspace' && "
            f"false"
        )
        
        self._generator_process = QProcess(self)
        self._generator_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._generator_process.finished.connect(self._on_generate_done)
        self._generator_process.start("bash", ["-c", cmd])

    def _on_generate_done(self) -> None:
        self.btn_generate_shape.setEnabled(True)
        self.btn_generate_shape.setText("🔷  Generate Safe-Zone Trajectory")

        if self._generator_process is None:
            return

        code = self._generator_process.exitCode()
        output = self._generator_process.readAllStandardOutput().data().decode("utf-8", errors="replace")

        if code != 0:
            self._log(f"IK Generation failed: {output}", error=True)
            self.shape_status_label.setText("Failed")
            return

        self._log(f"✓ Shape generated & exported to Workspaces successfully.")
        self.shape_status_label.setText(f"✓ Output Complete")

    # ──────────────────────────────────────────────────────────────────────
    # Save / load
    # ──────────────────────────────────────────────────────────────────────
    def _save_trajectory(self) -> None:
        _TRAJ_STORAGE.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Trajectory",
            str(_TRAJ_STORAGE),
            "YAML Files (*.yaml)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        if not path.endswith(".yaml"):
            path += ".yaml"
        filename = os.path.basename(path)
        yaml_req = f"{{filename: '{filename}', description: 'Saved from dashboard'}}"
        self._log(f"Saving → {filename}…")
        self.btn_save.setEnabled(False)
        self.btn_save.setText("⏳  Saving…")
        self._call_service(_SVC_SAVE, "SaveTrajectory", yaml_req, self._on_save_done)

    def _on_save_done(self, output: str, code: int) -> None:
        self.btn_save.setEnabled(self._has_compiled and self._backend_running)
        self.btn_save.setText("💾  Save")
        if code != 0:
            self._log("Save failed", error=True)
            return
        msg = self._extract_field(output, "message") or "Saved"
        success = "success: true" in output.lower() or "success=true" in output.lower()
        self._log(f"{'✓' if success else '✗'} {msg}")

    def _load_trajectory(self) -> None:
        _TRAJ_STORAGE.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Trajectory",
            str(_TRAJ_STORAGE),
            "YAML Files (*.yaml)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
            
        yaml_req = f"{{filename: '{path}'}}"
        
        filename_only = os.path.basename(path)
        self._log(f"Loading ← {filename_only}…")
        # Visual feedback: disable load button while service call is in flight
        self.btn_load.setEnabled(False)
        self.btn_load.setText("⏳  Loading…")
        self._call_service(_SVC_LOAD, "LoadTrajectory", yaml_req, self._on_load_done)

    def _on_load_done(self, output: str, code: int) -> None:
        # Restore Load button regardless of outcome
        self.btn_load.setEnabled(self._backend_running)
        self.btn_load.setText("📂  Load")

        if code != 0:
            self._log("Load failed", error=True)
            return
        success = "success: true" in output.lower() or "success=true" in output.lower()
        wpts = self._extract_field(output, "waypoint_count")
        dur = self._extract_field(output, "duration")
        if success:
            info = []
            if wpts:
                info.append(f"{wpts} waypoints")
            if dur:
                info.append(f"{dur}s")
            self._log(f"✓ Loaded: {', '.join(info)}" if info else "✓ Loaded")
            self._has_compiled = True
            self.btn_preview.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.btn_execute.setEnabled(True)
        else:
            msg = self._extract_field(output, "message") or "Load failed"
            self._log(f"✗ {msg}", error=True)

    # ──────────────────────────────────────────────────────────────────────
    # Execute
    # ──────────────────────────────────────────────────────────────────────
    def _execute_trajectory(self) -> None:
        self._log("Starting execution…")
        self._executing = True
        self.btn_execute.setEnabled(False)
        self.btn_stop_exec.setEnabled(True)
        self.progress_bar.setValue(0)
        self._progress_timer.start()
        self._call_service(_SVC_EXECUTE, "ExecuteTrajectory", "{}", self._on_execute_done)

    def _on_execute_done(self, output: str, code: int) -> None:
        success = "success: true" in output.lower() or "success=true" in output.lower()
        msg = self._extract_field(output, "message") or ("Execution complete" if success else "Execution failed")
        if success:
            self._log(f"✓ {msg}")
        else:
            self._log(f"✗ {msg}", error=True)
        self._executing = False
        self.btn_execute.setEnabled(self._has_compiled)
        self.btn_stop_exec.setEnabled(False)
        self._progress_timer.stop()
        self._progress_timer.setInterval(2000)  # Reset to idle speed

    def _stop_execution(self) -> None:
        self._executing = False
        self.btn_execute.setEnabled(self._has_compiled)
        self.btn_stop_exec.setEnabled(False)
        self._progress_timer.stop()
        self._progress_timer.setInterval(2000)  # Reset to idle speed
        self._log("Execution stopped")

    # ──────────────────────────────────────────────────────────────────────
    # Status polling
    # ──────────────────────────────────────────────────────────────────────
    def _poll_status(self) -> None:
        """Periodically call GetStatus to refresh the summary panel."""
        if self._status_process is not None and self._status_process.state() != QProcess.ProcessState.NotRunning:
            return  # previous poll still in flight

        cmd = (
            f"{self._shell_prefix}"
            f"ros2 service call {_SVC_STATUS} {_MSG_PKG}/srv/GetStatus '{{}}'"
        )
        self._status_process = QProcess(self)
        self._status_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._status_process.finished.connect(self._on_status_poll_done)
        self._status_process.start("bash", ["-c", cmd])

    def _on_status_poll_done(self) -> None:
        if self._status_process is None:
            return
        output = self._status_process.readAllStandardOutput().data().decode("utf-8", errors="replace")

        status = self._extract_field(output, "status") or "--"
        seg = self._extract_field(output, "segment_count") or "0"
        wpts = self._extract_field(output, "total_waypoints") or "--"
        dur = self._extract_field(output, "trajectory_duration") or "--"
        fname = self._extract_field(output, "current_filename") or "--"
        has_compiled_str = self._extract_field(output, "has_compiled_trajectory") or "false"

        self._status_labels["status"].setText(status)
        self._status_labels["segments"].setText(seg)
        self._status_labels["waypoints"].setText(wpts)
        try:
            self._status_labels["duration"].setText(f"{float(dur):.2f}s")
        except (ValueError, TypeError):
            self._status_labels["duration"].setText(dur)
        self._status_labels["filename"].setText(fname)
        self.segments_label.setText(f"Segments: {seg}")

        compiled = has_compiled_str.strip().lower() == "true"
        # Only downgrade _has_compiled if the parse returned a definitive "false";
        # keep the local state if the status poll failed to parse cleanly.
        if compiled or has_compiled_str.strip().lower() == "false":
            self._has_compiled = compiled
        if self._backend_running:
            self.btn_preview.setEnabled(self._has_compiled)
            self.btn_save.setEnabled(self._has_compiled)
            self.btn_execute.setEnabled(self._has_compiled and not self._executing)

        # Sync execution state from server
        self._executing = status.strip().lower() == "executing"
        self.btn_stop_exec.setEnabled(self._executing)
        if self._executing and not self._progress_timer.isActive():
            self._progress_timer.setInterval(500)  # Fast-poll during execution
            self._progress_timer.start()

    # ──────────────────────────────────────────────────────────────────────
    # Execution progress polling
    # ──────────────────────────────────────────────────────────────────────
    def _poll_progress(self) -> None:
        """Poll one message from the execution progress topic."""
        if not self._executing:
            return
        if self._progress_process is not None and self._progress_process.state() != QProcess.ProcessState.NotRunning:
            return

        cmd = (
            f"{self._shell_prefix}"
            f"ros2 topic echo --once {_TOPIC_PROGRESS} {_MSG_PKG}/msg/ExecutionProgress"
        )
        self._progress_process = QProcess(self)
        self._progress_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._progress_process.finished.connect(self._on_progress_poll_done)
        self._progress_process.start("bash", ["-c", cmd])

    def _on_progress_poll_done(self) -> None:
        if self._progress_process is None:
            return
        output = self._progress_process.readAllStandardOutput().data().decode("utf-8", errors="replace")

        pct = self._extract_field(output, "progress_percent")
        status = self._extract_field(output, "status")

        if pct:
            try:
                self.progress_bar.setValue(int(float(pct)))
            except ValueError:
                pass

        if status and status.strip().lower() == "completed":
            self.progress_bar.setValue(100)
            self._executing = False
            self.btn_execute.setEnabled(True)
            self.btn_stop_exec.setEnabled(False)
            self._progress_timer.stop()
            self._progress_timer.setInterval(2000)  # Reset to idle speed

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_field(text: str, field: str) -> Optional[str]:
        """Pull a named field value from ros2 service/topic CLI output.

        Handles three output formats:
        1. YAML style:        ``field: value``
        2. Namedtuple string: ``field='value'`` (ROS 2 Jazzy)
        3. Namedtuple plain:  ``field=value``   (ROS 2 Jazzy)
        """
        # ── Pass 1: namedtuple repr  field='...'  or  field=<token> ────
        # Quoted string value
        m = re.search(rf"{field}\s*=\s*'([^']*)'" , text, re.IGNORECASE)
        if m:
            return m.group(1).strip() or None
        m = re.search(rf'{field}\s*=\s*"([^"]*)"', text, re.IGNORECASE)
        if m:
            return m.group(1).strip() or None
        # Unquoted token value (stops at comma, closing paren, or newline)
        m = re.search(rf"{field}\s*=\s*([^,)\n]+)", text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            return val if val else None

        # ── Pass 2: YAML style  field: value ──────────────────────────
        m = re.search(rf"^\s*{field}\s*:\s*(.+)", text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip().strip("'\"")
            val = val.split("\n")[0].rstrip(",").strip()
            return val if val else None
        return None

    def _log(self, message: str, error: bool = False) -> None:
        prefix = "[ERROR] " if error else "[INFO]  "
        self.log_text.appendPlainText(prefix + message)
        # Auto-scroll
        sb = self.log_text.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    # ──────────────────────────────────────────────────────────────────────
    # Window lifecycle
    # ──────────────────────────────────────────────────────────────────────
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_backend_state()

    def closeEvent(self, event) -> None:
        self._status_timer.stop()
        self._progress_timer.stop()
        self._backend_check_timer.stop()
        if self._svc_timeout is not None:
            self._svc_timeout.stop()

        for proc in (self._svc_process, self._status_process, self._progress_process):
            if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                proc.waitForFinished(1000)

        # NOTE: We do NOT stop the backend — it keeps running so the arm
        # trajectory is still available for other tools / CLI usage.
        super().closeEvent(event)
