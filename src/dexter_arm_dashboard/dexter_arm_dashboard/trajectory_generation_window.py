"""Trajectory generation window for FK workspace CSV creation."""

from __future__ import annotations

import csv
import itertools
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


def _workspace_data_dir(workspace_dir: Optional[Path] = None) -> Path:
    """Return dashboard workspace data directory for generated CSV files."""
    candidates: List[Path] = []
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


def _build_angle_values(min_deg: float, max_deg: float, step_deg: float) -> List[float]:
    """Return inclusive angle values with bounded floating-point drift."""
    if step_deg <= 0:
        raise ValueError("Step must be greater than zero")
    if min_deg > max_deg:
        raise ValueError("Min angle must be less than or equal to max angle")

    values: List[float] = []
    value = float(min_deg)
    limit = float(max_deg)

    # Keep stable decimal output for CSV and predictable permutation counts.
    while value <= limit + 1e-9:
        values.append(round(value, 6))
        value += step_deg

    if not values:
        values.append(round(min_deg, 6))

    return values


class TrajectoryGenerationWorker(QObject):
    """Background worker for FK permutation generation."""

    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str, int)
    failed = pyqtSignal(str)

    def __init__(
        self,
        arm_selection: str,
        joint_configs: Sequence[Dict[str, Union[int, float]]],
        output_path: Path,
        workspace_dir: Optional[Path] = None,
    ):
        super().__init__()
        self.arm_selection = arm_selection
        self.joint_configs = list(joint_configs)
        self.output_path = output_path
        self.workspace_dir = workspace_dir

    def run(self) -> None:
        """Generate FK waypoints and write CSV output."""
        try:
            from urdf_parser_py.urdf import URDF
            import PyKDL
        except Exception as exc:
            self.failed.emit(
                "Missing FK dependencies. Install PyKDL and urdf_parser_py. "
                f"Details: {exc}"
            )
            return

        try:
            robot = self._load_robot_model(URDF)
            tree = self._urdf_to_kdl_tree(robot, PyKDL)
            arm_specs = self._arm_specs()

            base_joint_values = [[0.0] for _ in range(6)]
            for cfg in self.joint_configs:
                idx = int(cfg["index"])
                base_joint_values[idx] = _build_angle_values(
                    cfg["min_deg"],
                    cfg["max_deg"],
                    cfg["step_deg"],
                )

            permutation_count = 1
            for joint_values in base_joint_values:
                permutation_count *= len(joint_values)
            total_rows = permutation_count * len(arm_specs)

            self.log.emit(f"Selected arms: {', '.join(spec[0] for spec in arm_specs)}")
            self.log.emit(f"Joint permutations per arm: {permutation_count}")
            self.log.emit(f"Expected total FK evaluations: {total_rows}")

            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            processed = 0
            written = 0
            last_progress = -1

            with self.output_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "x",
                        "y",
                        "z",
                        "arm_id",
                        "arm",
                        "j1_deg",
                        "j2_deg",
                        "j3_deg",
                        "j4_deg",
                        "j5_deg",
                        "j6_deg",
                    ]
                )

                for arm_name, arm_id, base_link, tip_link in arm_specs:
                    self.log.emit(f"Building KDL chain for {arm_name}: {base_link} -> {tip_link}")
                    chain = tree.getChain(base_link, tip_link)
                    fk_solver = PyKDL.ChainFkSolverPos_recursive(chain)
                    max_joints = min(chain.getNrOfJoints(), 6)

                    for joint_combo in itertools.product(*base_joint_values):
                        q = PyKDL.JntArray(chain.getNrOfJoints())
                        for joint_index in range(max_joints):
                            q[joint_index] = math.radians(joint_combo[joint_index])

                        frame = PyKDL.Frame()
                        result = fk_solver.JntToCart(q, frame)
                        processed += 1

                        if result >= 0:
                            p = frame.p
                            writer.writerow(
                                [
                                    p.x(),
                                    p.y(),
                                    p.z(),
                                    arm_id,
                                    arm_name,
                                    *joint_combo,
                                ]
                            )
                            written += 1

                        if total_rows > 0:
                            progress = int((processed / total_rows) * 100)
                            if progress != last_progress:
                                self.progress.emit(progress)
                                last_progress = progress

            self.progress.emit(100)
            self.log.emit(f"Saved CSV: {self.output_path}")
            self.log.emit(f"Waypoints written: {written}")
            self.finished.emit(str(self.output_path), written)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _arm_specs(self) -> List[Tuple[str, int, str, str]]:
        specs: List[Tuple[str, int, str, str]] = []
        if self.arm_selection in ("left", "both"):
            specs.append(("left", 0, "base_link", "tool0_left"))
        if self.arm_selection in ("right", "both"):
            specs.append(("right", 1, "base_link", "tool0_right"))
        return specs

    def _load_robot_model(self, urdf_cls):
        """Load URDF from /robot_description first, then local workspace file."""
        xml = self._load_robot_description_from_topic(timeout_sec=3.0)
        if xml:
            self.log.emit("Loaded URDF from /robot_description topic.")
            return urdf_cls.from_xml_string(xml)

        candidates: List[Path] = []
        if self.workspace_dir:
            candidates.append(
                self.workspace_dir
                / "src"
                / "dexter_arm_description"
                / "urdf"
                / "dexter_arm.urdf.xacro"
            )

        try:
            from ament_index_python.packages import get_package_share_directory

            share_dir = Path(get_package_share_directory("dexter_arm_description"))
            candidates.append(share_dir / "urdf" / "dexter_arm.urdf.xacro")
        except Exception:
            pass

        for candidate in candidates:
            if candidate.exists():
                self.log.emit(f"Loaded URDF from file: {candidate}")
                return urdf_cls.from_xml_file(str(candidate))

        raise RuntimeError(
            "Unable to load robot model. Start robot_state_publisher or ensure "
            "dexter_arm_description/urdf/dexter_arm.urdf.xacro is available."
        )

    def _load_robot_description_from_topic(self, timeout_sec: float) -> Optional[str]:
        """Attempt to read latched /robot_description with a transient-local sub."""
        try:
            import rclpy
            from rclpy.qos import DurabilityPolicy, QoSProfile
            from std_msgs.msg import String
        except Exception:
            return None

        msg_holder: Dict[str, Optional[str]] = {"xml": None}
        created_context = False
        node = None

        try:
            if not rclpy.ok():
                rclpy.init(args=None)
                created_context = True

            node = rclpy.create_node(f"trajectory_urdf_loader_{os.getpid()}")
            qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)

            def _callback(msg: String) -> None:
                msg_holder["xml"] = msg.data

            node.create_subscription(String, "/robot_description", _callback, qos)

            deadline = time.time() + timeout_sec
            while time.time() < deadline and msg_holder["xml"] is None:
                rclpy.spin_once(node, timeout_sec=0.15)

            return msg_holder["xml"]
        except Exception:
            return None
        finally:
            if node is not None:
                node.destroy_node()
            if created_context and rclpy.ok():
                rclpy.shutdown()

    def _urdf_to_kdl_tree(self, robot_model, pykdl):
        """Build KDL tree from URDF model."""
        tree = pykdl.Tree(robot_model.get_root())

        def add_children_to_tree(kdl_tree, link_name):
            if link_name not in robot_model.child_map:
                return

            for joint_name, child_link_name in robot_model.child_map[link_name]:
                joint_urdf = robot_model.joint_map[joint_name]
                kdl_joint = self._urdf_joint_to_kdl(joint_urdf, pykdl)
                kdl_origin = self._urdf_pose_to_kdl(joint_urdf.origin, pykdl)

                if kdl_joint.getType() != pykdl.Joint.Fixed:
                    pre_link_name = child_link_name + "_pre_kdl"
                    pre_joint = pykdl.Joint(joint_name + "_pre", pykdl.Joint.Fixed)
                    pre_segment = pykdl.Segment(pre_link_name, pre_joint, kdl_origin)
                    kdl_tree.addSegment(pre_segment, link_name)

                    msg_segment = pykdl.Segment(child_link_name, kdl_joint, pykdl.Frame())
                    kdl_tree.addSegment(msg_segment, pre_link_name)
                else:
                    segment = pykdl.Segment(child_link_name, kdl_joint, kdl_origin)
                    kdl_tree.addSegment(segment, link_name)

                add_children_to_tree(kdl_tree, child_link_name)

        add_children_to_tree(tree, robot_model.get_root())
        return tree

    @staticmethod
    def _urdf_joint_to_kdl(joint, pykdl):
        origin = pykdl.Vector(0.0, 0.0, 0.0)
        axis = (
            pykdl.Vector(joint.axis[0], joint.axis[1], joint.axis[2])
            if joint.axis
            else pykdl.Vector(0.0, 0.0, 1.0)
        )
        if joint.type == "fixed":
            return pykdl.Joint(joint.name, pykdl.Joint.Fixed)
        if joint.type in ("revolute", "continuous"):
            return pykdl.Joint(joint.name, origin, axis, pykdl.Joint.RotAxis)
        if joint.type == "prismatic":
            return pykdl.Joint(joint.name, origin, axis, pykdl.Joint.TransAxis)
        return pykdl.Joint(joint.name, pykdl.Joint.Fixed)

    @staticmethod
    def _urdf_pose_to_kdl(pose, pykdl):
        pos = pykdl.Vector(0.0, 0.0, 0.0)
        rot = pykdl.Rotation.Identity()
        if pose:
            if pose.xyz:
                pos = pykdl.Vector(*pose.xyz)
            if pose.rpy:
                rot = pykdl.Rotation.RPY(*pose.rpy)
        return pykdl.Frame(rot, pos)


class TrajectoryGenerationWindow(QWidget):
    """UI for generating waypoint permutations and FK CSV output."""

    def __init__(self, workspace_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.workspace_dir = Path(workspace_dir).expanduser() if workspace_dir else None
        self.data_dir = _workspace_data_dir(self.workspace_dir)

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[TrajectoryGenerationWorker] = None

        self.setWindowTitle("Trajectory Generation")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("trajectory_generation_window")
        self.setMinimumSize(940, 740)
        self.resize(1020, 820)
        self.setStyleSheet(
            """
            QWidget#trajectory_generation_window {
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
            QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit, QProgressBar {
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
            QProgressBar {
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #2f73c9;
                border-radius: 4px;
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

        self.joint_rows: List[Dict[str, object]] = []
        self.joint_limits_by_arm = self._load_joint_limits_from_urdf()

        self._build_ui()
        self._apply_joint_defaults()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("main_panel")
        panel.setMinimumSize(860, 680)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)

        layout.addWidget(panel, 1)

        options_box = QGroupBox("Generation Options", panel)
        options_layout = QGridLayout(options_box)

        self.arm_combo = QComboBox(options_box)
        self.arm_combo.addItem("Left Arm", "left")
        self.arm_combo.addItem("Right Arm", "right")
        self.arm_combo.addItem("Both Arms", "both")
        self.arm_combo.currentIndexChanged.connect(self._apply_joint_defaults)
        self.arm_combo.view().setStyleSheet(
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

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.filename_edit = QLineEdit(f"workspace_data_{timestamp}.csv", options_box)

        self.dir_label = QLabel(str(self.data_dir), options_box)

        browse_dir_btn = QPushButton("Browse Folder", options_box)
        browse_dir_btn.clicked.connect(self._choose_output_directory)

        options_layout.addWidget(QLabel("Arm Selection:"), 0, 0)
        options_layout.addWidget(self.arm_combo, 0, 1)
        options_layout.addWidget(QLabel("Output File:"), 1, 0)
        options_layout.addWidget(self.filename_edit, 1, 1, 1, 2)
        options_layout.addWidget(QLabel("Save Folder:"), 2, 0)
        options_layout.addWidget(self.dir_label, 2, 1)
        options_layout.addWidget(browse_dir_btn, 2, 2)

        joints_box = QGroupBox("Joint Permutations", self)
        joints_layout = QGridLayout(joints_box)
        headers = ["Enable", "Joint", "Min (deg)", "Max (deg)", "Step (deg)"]
        for col, header in enumerate(headers):
            joints_layout.addWidget(QLabel(header), 0, col)

        for i in range(6):
            enable = QCheckBox(joints_box)
            enable.setChecked(i < 2)

            joint_label = QLabel(f"J{i + 1}", joints_box)

            min_spin = QDoubleSpinBox(joints_box)
            min_spin.setRange(-360.0, 360.0)
            min_spin.setDecimals(3)

            max_spin = QDoubleSpinBox(joints_box)
            max_spin.setRange(-360.0, 360.0)
            max_spin.setDecimals(3)

            step_spin = QDoubleSpinBox(joints_box)
            step_spin.setRange(0.001, 360.0)
            step_spin.setDecimals(3)
            step_spin.setValue(15.0)

            row = i + 1
            joints_layout.addWidget(enable, row, 0)
            joints_layout.addWidget(joint_label, row, 1)
            joints_layout.addWidget(min_spin, row, 2)
            joints_layout.addWidget(max_spin, row, 3)
            joints_layout.addWidget(step_spin, row, 4)

            self.joint_rows.append(
                {
                    "enable": enable,
                    "label": joint_label,
                    "min": min_spin,
                    "max": max_spin,
                    "step": step_spin,
                }
            )

        action_layout = QHBoxLayout()
        self.generate_btn = QPushButton("Generate CSV", panel)
        self.generate_btn.clicked.connect(self._start_generation)
        self.progress_bar = QProgressBar(panel)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        action_layout.addWidget(self.generate_btn)
        action_layout.addWidget(self.progress_bar)

        self.log_output = QPlainTextEdit(panel)
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(190)

        panel_layout.addWidget(options_box)
        panel_layout.addWidget(joints_box)
        panel_layout.addLayout(action_layout)
        panel_layout.addWidget(self.log_output)

    def _choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            str(self.data_dir),
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontUseNativeDialog,
        )
        if selected:
            self.data_dir = Path(selected)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.dir_label.setText(str(self.data_dir))

    def _load_joint_limits_from_urdf(self) -> Dict[str, List[Tuple[float, float, str]]]:
        """Load joint limits for left/right arm from local URDF file when possible."""
        defaults = {
            "left": [
                (0.0, 180.0, "j1l"),
                (-90.0, 90.0, "j2l"),
                (-90.0, 90.0, "j3l"),
                (-90.0, 90.0, "j4l"),
                (-90.0, 90.0, "j5l"),
                (-90.0, 90.0, "j6l"),
            ],
            "right": [
                (0.0, 180.0, "j1r"),
                (-90.0, 90.0, "j2r"),
                (-90.0, 90.0, "j3r"),
                (-90.0, 90.0, "j4r"),
                (-90.0, 90.0, "j5r"),
                (-90.0, 90.0, "j6r"),
            ],
        }

        try:
            from urdf_parser_py.urdf import URDF
        except Exception:
            return defaults

        candidates: List[Path] = []
        if self.workspace_dir:
            candidates.append(
                self.workspace_dir
                / "src"
                / "dexter_arm_description"
                / "urdf"
                / "dexter_arm.urdf.xacro"
            )

        try:
            from ament_index_python.packages import get_package_share_directory

            share_dir = Path(get_package_share_directory("dexter_arm_description"))
            candidates.append(share_dir / "urdf" / "dexter_arm.urdf.xacro")
        except Exception:
            pass

        urdf_path = next((p for p in candidates if p.exists()), None)
        if urdf_path is None:
            return defaults

        try:
            robot = URDF.from_xml_file(str(urdf_path))
        except Exception:
            return defaults

        parsed = {"left": [], "right": []}
        for side, suffix in (("left", "l"), ("right", "r")):
            for index in range(1, 7):
                joint_name = f"j{index}{suffix}"
                joint = robot.joint_map.get(joint_name)
                if (
                    joint
                    and joint.limit
                    and joint.limit.lower is not None
                    and joint.limit.upper is not None
                ):
                    lower = math.degrees(float(joint.limit.lower))
                    upper = math.degrees(float(joint.limit.upper))
                    parsed[side].append((lower, upper, joint_name))
                else:
                    parsed[side].append(defaults[side][index - 1])

        return parsed

    def _apply_joint_defaults(self) -> None:
        arm_key = self.arm_combo.currentData()
        if arm_key == "right":
            limits = self.joint_limits_by_arm.get("right", [])
        else:
            limits = self.joint_limits_by_arm.get("left", [])

        for index, row in enumerate(self.joint_rows):
            label = row["label"]
            min_spin = row["min"]
            max_spin = row["max"]
            step_spin = row["step"]

            if index < len(limits):
                min_deg, max_deg, joint_name = limits[index]
            else:
                min_deg, max_deg, joint_name = (-90.0, 90.0, f"J{index + 1}")

            label.setText(joint_name if arm_key in ("left", "right") else f"J{index + 1}")
            min_spin.setValue(min_deg)
            max_spin.setValue(max_deg)
            if step_spin.value() <= 0:
                step_spin.setValue(15.0)

    def _start_generation(self) -> None:
        if self.worker_thread is not None:
            QMessageBox.information(self, "In Progress", "Generation is already running.")
            return

        filename = self.filename_edit.text().strip()
        if not filename:
            QMessageBox.warning(self, "Invalid Filename", "Please enter an output filename.")
            return
        if not filename.lower().endswith(".csv"):
            filename = f"{filename}.csv"

        output_path = self.data_dir / filename

        joint_configs: List[Dict[str, Union[int, float]]] = []
        permutation_count = 1

        for idx, row in enumerate(self.joint_rows):
            enabled = row["enable"].isChecked()
            min_deg = row["min"].value()
            max_deg = row["max"].value()
            step_deg = row["step"].value()

            if enabled:
                try:
                    values = _build_angle_values(min_deg, max_deg, step_deg)
                except ValueError as exc:
                    QMessageBox.warning(self, "Invalid Joint Range", str(exc))
                    return

                permutation_count *= len(values)
                joint_configs.append(
                    {
                        "index": idx,
                        "min_deg": min_deg,
                        "max_deg": max_deg,
                        "step_deg": step_deg,
                    }
                )

        if not joint_configs:
            QMessageBox.warning(self, "No Joints Selected", "Enable at least one joint.")
            return

        selected_arms = self.arm_combo.currentData()
        arm_multiplier = 2 if selected_arms == "both" else 1
        expected_rows = permutation_count * arm_multiplier

        if expected_rows > 200000:
            reply = QMessageBox.question(
                self,
                "Large Generation",
                f"This will evaluate about {expected_rows} FK points. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if output_path.exists():
            reply = QMessageBox.question(
                self,
                "Overwrite File",
                f"{output_path.name} already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.progress_bar.setValue(0)
        self.log_output.clear()
        self._log(f"Output file: {output_path}")
        self._log(f"Estimated FK points: {expected_rows}")

        self.generate_btn.setEnabled(False)

        self.worker_thread = QThread(self)
        self.worker = TrajectoryGenerationWorker(
            arm_selection=selected_arms,
            joint_configs=joint_configs,
            output_path=output_path,
            workspace_dir=self.workspace_dir,
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.log.connect(self._log)
        self.worker.finished.connect(self._on_generation_finished)
        self.worker.failed.connect(self._on_generation_failed)
        self.worker.finished.connect(lambda _path, _count: self._cleanup_worker())
        self.worker.failed.connect(lambda _msg: self._cleanup_worker())

        self.worker_thread.start()

    def _cleanup_worker(self) -> None:
        self.generate_btn.setEnabled(True)
        if self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait(2000)
            self.worker_thread.deleteLater()
        self.worker_thread = None
        self.worker = None

    def _on_generation_finished(self, output_path: str, count: int) -> None:
        self._log(f"Generation complete. {count} waypoints written.")
        QMessageBox.information(
            self,
            "Trajectory Generation",
            f"CSV generated successfully:\n{output_path}\n\nWaypoints: {count}",
        )

    def _on_generation_failed(self, message: str) -> None:
        self._log(f"Generation failed: {message}")
        QMessageBox.critical(self, "Trajectory Generation Failed", message)

    def _log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def closeEvent(self, event) -> None:
        """Prevent closing while generation is in progress."""
        if self.worker_thread is not None:
            QMessageBox.warning(
                self,
                "Generation Running",
                "Wait for generation to finish before closing this window.",
            )
            event.ignore()
            return
        self.progress_bar.setValue(0)
        self.log_output.clear()
        super().closeEvent(event)
