"""Simplified selective process-kill window for dashboard cleanup."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .process_manager import ProcessManager


class KillProcessWindow(QWidget):
    """Non-modal window for selective ROS/process cleanup."""

    BASE_TARGETS = [
        ("ros2", "ROS 2"),
        ("gazebo", "Gazebo"),
        ("rviz", "RViz"),
        ("move_group", "MoveIt"),
        ("controller_manager", "Controller Manager"),
        ("micro_ros_agent", "micro-ROS Agent"),
    ]

    def __init__(self, process_manager: ProcessManager, serial_port: str = "/dev/ttyUSB0", parent=None):
        super().__init__(parent)
        self.process_manager = process_manager
        self.serial_port = serial_port or "/dev/ttyUSB0"

        self.setWindowTitle("Kill Processes")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("kill_process_window")
        self.setMinimumSize(920, 620)
        self.resize(980, 680)
        self.setStyleSheet(
            """
            QWidget#kill_process_window {
                background-color: #0d1626;
            }
            QFrame#main_panel {
                background-color: #16263d;
                border: 1px solid #2f4b72;
                border-radius: 14px;
            }
            QLabel {
                color: #eef4ff;
                font-size: 14px;
            }
            QLabel#title {
                font-size: 21px;
                font-weight: 700;
                color: #ffffff;
            }
            QListWidget {
                background-color: #0f1a2e;
                border: 1px solid #4d6fa0;
                border-radius: 8px;
                color: #f4f8ff;
                padding: 6px;
                outline: none;
            }
            QListWidget::item {
                background-color: #12213a;
                color: #f4f8ff;
                border: 1px solid #39557c;
                border-radius: 6px;
                margin: 3px 0px;
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: #2f73c9;
                color: #ffffff;
                border: 1px solid #6ea2ef;
            }
            QPlainTextEdit {
                background-color: #0f1a2e;
                color: #f4f8ff;
                border: 1px solid #4d6fa0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #2a5f9c;
                color: #ffffff;
                border: 1px solid #4b84cc;
                border-radius: 7px;
                padding: 8px 14px;
                font-weight: 700;
                min-width: 110px;
            }
            QPushButton:hover {
                background-color: #3473b7;
            }
            QPushButton#danger {
                background-color: #8b2a2a;
                border-color: #b14444;
            }
            QPushButton#danger:hover {
                background-color: #a13333;
            }
            """
        )

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("main_panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)

        outer.addWidget(panel, 1)

        title = QLabel("Kill Processes", panel)
        title.setObjectName("title")

        brief = QLabel(
            "Select one or more lines and click Kill to force-stop selected process groups.",
            panel,
        )

        self.process_list = QListWidget(panel)
        self.process_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.process_list.setAlternatingRowColors(False)
        self._populate_targets()

        button_row = QHBoxLayout()
        self.btn_kill = QPushButton("Kill", panel)
        self.btn_kill.setObjectName("danger")
        self.btn_kill.clicked.connect(self._kill_selected)

        self.btn_kill_all = QPushButton("Kill All", panel)
        self.btn_kill_all.setObjectName("danger")
        self.btn_kill_all.clicked.connect(self._kill_all)

        self.btn_close = QPushButton("Close", panel)
        self.btn_close.clicked.connect(self._close_and_reset)

        button_row.addWidget(self.btn_kill)
        button_row.addWidget(self.btn_kill_all)
        button_row.addStretch()
        button_row.addWidget(self.btn_close)

        self.output = QPlainTextEdit(panel)
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(190)

        panel_layout.addWidget(title)
        panel_layout.addWidget(brief)
        panel_layout.addWidget(self.process_list)
        panel_layout.addLayout(button_row)
        panel_layout.addWidget(self.output)

    def _populate_targets(self) -> None:
        self.process_list.clear()

        for target_id, label in self.BASE_TARGETS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, target_id)
            self.process_list.addItem(item)

        port_item = QListWidgetItem(f"Port Occupied - {self.serial_port}")
        port_item.setData(Qt.ItemDataRole.UserRole, "port_users")
        self.process_list.addItem(port_item)

        # Default state: nothing selected.
        self.process_list.clearSelection()

    def _selected_target_ids(self):
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.process_list.selectedItems()
        ]

    def _all_target_ids(self):
        ids = []
        for i in range(self.process_list.count()):
            item = self.process_list.item(i)
            ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _kill_selected(self) -> None:
        selected = self._selected_target_ids()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Select at least one process line.")
            return

        if not self._confirm_kill(selected):
            self._log("Cancelled")
            return

        self._run_kill(selected)

    def _kill_all(self) -> None:
        all_ids = self._all_target_ids()
        if not self._confirm_kill(all_ids):
            self._log("Cancelled")
            return

        self._run_kill(all_ids)

    def _run_kill(self, target_ids) -> None:
        self._log("Killing processes...")
        report = self.process_manager.kill_selected_targets(target_ids, serial_port=self.serial_port)
        for _target, line in report:
            self._log(line)
        self._log("Done")

    def _reset_window_state(self) -> None:
        """Reset UI state so reopening starts clean."""
        self.process_list.clearSelection()
        self.output.clear()

    def _close_and_reset(self) -> None:
        self._reset_window_state()
        self.close()

    def _confirm_kill(self, target_ids) -> bool:
        labels = [self._label_for_target_id(tid) for tid in target_ids]
        labels = [label for label in labels if label]

        if len(labels) == 1:
            question = "Do you want to kill this process?"
        else:
            question = "Do you want to kill these processes?"

        details = "\n".join(f"- {label}" for label in labels)

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Kill")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(question)
        msg.setInformativeText(details)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setStyleSheet(
            """
            QMessageBox {
                background-color: #0f1a2e;
            }
            QMessageBox QLabel {
                color: #f4f8ff;
                font-size: 14px;
            }
            QMessageBox QPushButton {
                background-color: #2a5f9c;
                color: #ffffff;
                border: 1px solid #4b84cc;
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background-color: #3473b7;
            }
            """
        )
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _label_for_target_id(self, target_id: str) -> str:
        for tid, label in self.BASE_TARGETS:
            if tid == target_id:
                return label
        if target_id == "port_users":
            return f"Port Occupied - {self.serial_port}"
        return target_id

    def _log(self, message: str) -> None:
        self.output.appendPlainText(message)

    def closeEvent(self, event) -> None:
        # Also reset when user closes via window controls (X button).
        self._reset_window_state()
        super().closeEvent(event)
