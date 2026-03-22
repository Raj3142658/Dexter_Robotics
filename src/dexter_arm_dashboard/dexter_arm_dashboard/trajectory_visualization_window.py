"""Trajectory visualization window for CSV waypoint marker publishing."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .process_manager import ProcessManager


def _workspace_data_dir(workspace_dir: Optional[Path] = None) -> Path:
    """Return dashboard workspace data directory used by waypoint CSV tools."""
    candidates = []
    if workspace_dir is not None:
        candidates.append(workspace_dir / "src" / "dexter_arm_dashboard" / "data" / "workspaces")

    # Fallback for source-tree runs without explicit workspace_dir.
    candidates.append(Path(__file__).resolve().parents[1] / "data" / "workspaces")

    # Last-resort fallback keeps previous behavior if source path is not writable.
    candidates.append(Path.home() / ".dexter_arm_dashboard" / "data" / "workspaces")

    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue

    raise RuntimeError("Unable to create workspace data directory for trajectory CSV files.")


class TrajectoryVisualizationWindow(QWidget):
    """UI for selecting generated CSV files and launching RViz visualization."""

    PROCESS_NAME = "trajectory_csv_visualizer"

    def __init__(self, process_manager: ProcessManager, workspace_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.process_manager = process_manager
        self.workspace_dir = Path(workspace_dir).expanduser() if workspace_dir else None

        self.data_dir = _workspace_data_dir(self.workspace_dir)

        self.setWindowTitle("Trajectory Visualization")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("trajectory_visualization_window")
        self.setMinimumSize(900, 420)
        self.resize(980, 480)
        self.setStyleSheet(
            """
            QWidget#trajectory_visualization_window {
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
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QLabel {
                color: #d9e7ff;
            }
            QComboBox {
                background-color: #0f1a2e;
                color: #ebf2ff;
                border: 1px solid #40618f;
                border-radius: 6px;
                padding: 4px;
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
                color: #f3f8ff;
                border: 1px solid #40618f;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
                outline: 0;
            }
            QPushButton {
                background-color: #2a5f9c;
                color: #f7fbff;
                border: 1px solid #3f7ac2;
                border-radius: 7px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background-color: #3473b7;
            }
            """
        )

        self._build_ui()
        self._refresh_csv_files()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("main_panel")
        panel.setMinimumSize(860, 380)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)

        layout.addWidget(panel, 1)

        selection_box = QGroupBox("CSV Selection", panel)
        selection_layout = QGridLayout(selection_box)

        self.file_combo = QComboBox(selection_box)
        self.file_combo.view().setStyleSheet(
            """
            QListView {
                background-color: #0f1a2e;
                color: #f3f8ff;
                border: 1px solid #40618f;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
                outline: 0;
            }
            """
        )

        self.path_label = QLabel("", selection_box)
        self.path_label.setWordWrap(True)

        refresh_btn = QPushButton("Refresh", selection_box)
        refresh_btn.clicked.connect(self._refresh_csv_files)

        browse_btn = QPushButton("Browse", selection_box)
        browse_btn.clicked.connect(self._browse_for_csv)

        self.file_combo.currentIndexChanged.connect(self._update_path_label)

        selection_layout.addWidget(QLabel("Generated Files:"), 0, 0)
        selection_layout.addWidget(self.file_combo, 0, 1)
        selection_layout.addWidget(refresh_btn, 0, 2)
        selection_layout.addWidget(browse_btn, 0, 3)
        selection_layout.addWidget(QLabel("Selected Path:"), 1, 0)
        selection_layout.addWidget(self.path_label, 1, 1, 1, 3)

        controls_layout = QHBoxLayout()
        self.visualize_btn = QPushButton("Visualize in RViz", panel)
        self.visualize_btn.clicked.connect(self._visualize_in_rviz)

        self.stop_btn = QPushButton("Stop Visualizer", panel)
        self.stop_btn.clicked.connect(self._stop_visualizer)

        controls_layout.addWidget(self.visualize_btn)
        controls_layout.addWidget(self.stop_btn)

        self.status_label = QLabel(
            "Start RViz and add a MarkerArray display on topic /workspace_csv_markers.",
            panel,
        )
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: 600;")

        panel_layout.addWidget(selection_box)
        panel_layout.addLayout(controls_layout)
        panel_layout.addWidget(self.status_label)

    def _refresh_csv_files(self) -> None:
        self.file_combo.clear()

        csv_files = sorted(
            self.data_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not csv_files:
            self.file_combo.addItem("No CSV files found", None)
            self.path_label.setText(str(self.data_dir))
            return

        for csv_path in csv_files:
            self.file_combo.addItem(csv_path.name, str(csv_path))

        self._update_path_label()

    def _browse_for_csv(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select Trajectory CSV",
            str(self.data_dir),
            "CSV Files (*.csv)",
        )
        if not selected:
            return

        selected_path = str(Path(selected))
        current_paths = [self.file_combo.itemData(i) for i in range(self.file_combo.count())]

        if selected_path not in current_paths:
            self.file_combo.addItem(Path(selected).name, selected_path)
        self.file_combo.setCurrentIndex(self.file_combo.findData(selected_path))
        self._update_path_label()

    def _selected_csv_path(self) -> Optional[Path]:
        selected = self.file_combo.currentData()
        if not selected:
            return None
        return Path(selected)

    def _update_path_label(self) -> None:
        selected = self._selected_csv_path()
        if selected:
            self.path_label.setText(str(selected))
        else:
            self.path_label.setText(str(self.data_dir))

    def _visualize_in_rviz(self) -> None:
        csv_path = self._selected_csv_path()
        if csv_path is None:
            QMessageBox.warning(self, "No File Selected", "Please select a CSV file first.")
            return

        if not csv_path.exists():
            QMessageBox.warning(self, "Missing File", f"File not found:\n{csv_path}")
            self._refresh_csv_files()
            return

        if self.process_manager.is_running(self.PROCESS_NAME):
            self.process_manager.kill_process(self.PROCESS_NAME)

        csv_arg = shlex.quote(str(csv_path))
        command = (
            "ros2 run dexter_arm_utilities csv_visualizer "
            f"--ros-args -p csv_path:={csv_arg}"
        )

        launched = self.process_manager.launch_command(
            self.PROCESS_NAME,
            command,
            use_terminal=True,
            display_name=f"CSV Visualizer ({csv_path.name})",
        )

        if launched:
            self.status_label.setText(
                f"Visualizer launched for {csv_path.name}. "
                "Check RViz MarkerArray topic /workspace_csv_markers."
            )
        else:
            QMessageBox.critical(
                self,
                "Launch Failed",
                "Failed to launch csv_visualizer. Check terminal output.",
            )

    def _stop_visualizer(self) -> None:
        if self.process_manager.is_running(self.PROCESS_NAME):
            self.process_manager.kill_process(self.PROCESS_NAME)
            self.status_label.setText("CSV visualizer stopped.")
        else:
            self.status_label.setText("CSV visualizer is not running.")

    def closeEvent(self, event) -> None:
        """
        Stop csv_visualizer on close so its terminal/process is not left running.
        """
        if self.process_manager.is_running(self.PROCESS_NAME):
            self.process_manager.kill_process(self.PROCESS_NAME)
        self.status_label.setText(
            "Start RViz and add a MarkerArray display on topic /workspace_csv_markers."
        )
        super().closeEvent(event)
