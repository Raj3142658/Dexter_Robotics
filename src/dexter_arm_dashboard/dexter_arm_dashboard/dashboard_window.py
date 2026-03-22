"""
Main Dashboard Window
HUD interface for Dexter Arm control system.
"""

from PyQt6.QtWidgets import QMainWindow, QWidget, QLabel, QMessageBox, QGraphicsOpacityEffect, QFrame, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPointF, QObject, QEvent, QProcess
from PyQt6.QtGui import QPixmap, QAction, QKeySequence, QColor
from pathlib import Path
import yaml
import subprocess

from .widgets.video_background import VideoBackground
from .widgets.background_fill import BackgroundFill
from .widgets.animated_button import AnimatedButton
from .widgets.settings_button import SettingsButton
from .widgets.movable_label import MovableLabel
from .config_loader import ConfigLoader
from .process_manager import ProcessManager
from .widgets.settings_dialog import SettingsDialog
from .widgets.connector_line import ConnectorLine
from .widgets.display_panel import DisplayPanel
from .widgets.firmware_dialog import FirmwareDialog
from .trajectory_generation_window import TrajectoryGenerationWindow
from .trajectory_visualization_window import TrajectoryVisualizationWindow
from .kill_process_window import KillProcessWindow
from .hardware_full_system_window import HardwareFullSystemWindow
from .system_monitor_window import SystemMonitorWindow
from .trajectory_system_window import TrajectorySystemWindow
from .launch_terminal_window import LaunchTerminalWindow


class SettingsHoverEventFilter(QObject):
    """Dedicated event filter for settings button hover menu."""

    def __init__(self, dashboard, watched_widget, is_menu=False):
        super().__init__(dashboard)
        self.dashboard = dashboard
        self.is_menu = is_menu

    def eventFilter(self, obj, event):
        if self.is_menu:
            if event.type() == QEvent.Type.Enter:
                self.dashboard._settings_menu_hovered = True
                if hasattr(self.dashboard, '_settings_menu_hide_timer'):
                    self.dashboard._settings_menu_hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self.dashboard._settings_menu_hovered = False
                self.dashboard._schedule_hide_settings_hover_menu()
        else:  # settings button
            if event.type() == QEvent.Type.Enter:
                self.dashboard._show_settings_hover_menu()
            elif event.type() == QEvent.Type.Leave:
                self.dashboard._schedule_hide_settings_hover_menu()
        return False


class IconGroupEventFilter(QObject):
    """Event filter to handle icon group hover and click behavior."""

    def __init__(self, dashboard, group_config, main_widget):
        super().__init__(dashboard)
        self.dashboard = dashboard
        self.group = group_config
        self.main_widget = main_widget
        self._prev_cursor = None
        self._pressed = False

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Enter:
            self.dashboard._show_group_overlay(self.group, self.main_widget)
            self.dashboard._set_group_highlight(self.group, True)
            if not self.dashboard.edit_mode:
                self._prev_cursor = self.main_widget.cursor()
                self.main_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        elif event.type() == QEvent.Type.Leave:
            self.dashboard._hide_group_overlay(self.group)
            self.dashboard._set_group_highlight(self.group, False)
            if self._prev_cursor is not None:
                self.main_widget.setCursor(self._prev_cursor)
                self._prev_cursor = None
        elif event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.dashboard.edit_mode:
                    self._pressed = True
                    event.accept()
                    return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.dashboard.edit_mode and self._pressed:
                    self._pressed = False
                    self.dashboard._execute_group_command(self.group)
                    event.accept()
                    return True
                self._pressed = False
        elif event.type() == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                if not self.dashboard.edit_mode:
                    self.dashboard._execute_group_command(self.group)
                    event.accept()
                    return True
        return False


class DashboardWindow(QMainWindow):
    """Main HUD dashboard window."""
    
    def __init__(self):
        """Initialize dashboard window."""
        super().__init__()
        
        # Load configuration
        self.config = ConfigLoader()
        self.opacity_defaults = self.config.get_opacity_defaults()
        
        # Initialize process manager
        workspace = self.config.get_workspace()
        self.process_manager = ProcessManager(workspace)
        
        # Get resource paths - Relative to package
        current_dir = Path(__file__).parent.resolve()
        self.resource_dir = current_dir / "resources"
        self.icons_dir = self.resource_dir
        self.panels_dir = self.resource_dir
        
        # Layout Config Path
        self.layout_config_path = self.config.config_path

        # Setup window
        # Setup window
        self.setWindowTitle("Dexter Arm - HUD Interface")
        self.resize(1280, 720)  # Default size (resizable)
        
        # Permanently frameless (no title bar)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)

        # Base layout scaling settings
        self.base_width = 1280
        self.base_height = 720
        self.keep_aspect = True
        self._layout_normalized = {}
        self._panel_normalized = {}
        self._layout_ready = False
        
        # Create central widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.all_buttons = {}  # name -> widget
        self.custom_icon_widgets = {}
        self.custom_icon_layers = {}
        self.icon_group_overlays = {}
        self.icon_group_filters = {}
        self.group_highlight_state = {}
        self.group_wake_state = {}
        self.group_launch_counter = 0
        self.firmware_dialog_window = None
        self.kill_process_window = None
        self.system_monitor_window = None
        self.hardware_full_window = None
        self.trajectory_system_window = None
        self.trajectory_generation_window = None
        self.trajectory_visualization_window = None
        self.settings_window = None
        self.launch_terminal_windows = {}  # Track HUD terminal launch windows
        self.edit_mode = False
        self.edit_connectors_mode = False  # False = edit items, True = edit connectors
        self._layout_dirty = False
        self._layout_discarded = False
        # Load edit_mode_enabled from config (defaults to True)
        self.edit_mode_enabled = self.config.get_edit_mode_enabled()
        print(f"[INFO] Edit Mode (Ctrl+E) is {'ENABLED' if self.edit_mode_enabled else 'DISABLED'}")
        
        # Setup UI
        self._setup_background()
        self._setup_custom_icons()
        self._setup_settings_button()
        self._setup_status_label()

        # Include non-movable overlays in scaling (except banner, will add later)
        self._fixed_widgets = {
            'status_label': self.status_label
        }

        # Capture default layout before loading overrides
        self._capture_default_layout()
        
        # Initialize dynamic widget lists BEFORE loading
        self.connectors = []
        self.display_panels = []
        self.dynamic_widgets = []
        self.hud_title_banner = None  # Will be set when a Title Banner panel is loaded
        
        # Load saved layout
        self._load_layout()
        
        # Load dynamic components (Connectors, Panels)
        self._load_dynamic_components()

        # Load icon group behaviors
        self._load_icon_groups()

        # Apply scaled layout after everything is created
        self._layout_ready = True
        self._apply_scaled_layout()
        
        # Setup Edit Mode shortcuts
        self._setup_edit_shortcuts()
        
        # Start update timer for active process count
        # (removed — psutil scanning now runs in process_manager background thread)
        
        # Connect process manager signals
        self.process_manager.processStarted.connect(self._on_process_started)
        self.process_manager.processFinished.connect(self._on_process_finished)
        self.process_manager.processError.connect(self._on_process_error)
        
    def _setup_edit_shortcuts(self):
        """Setup keyboard shortcuts for layout editing."""
        # Toggle Edit Mode (Ctrl+E)
        self.edit_action = QAction("Toggle Edit Mode", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.triggered.connect(self._on_edit_mode_shortcut)
        self.addAction(self.edit_action)
        
        # Toggle Maximize/Restore (F11)
        self.maximize_action = QAction("Toggle Maximize", self)
        self.maximize_action.setShortcut(QKeySequence("F11"))
        self.maximize_action.triggered.connect(self.toggle_maximize)
        self.addAction(self.maximize_action)
        
        # Save Layout (Ctrl+S)
        self.save_action = QAction("Save Layout", self)
        self.save_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_action.triggered.connect(lambda: self._save_all_layout(force=True))
        self.addAction(self.save_action)
        
        # Toggle Edit Sub-Mode (Tab)
        self.toggle_submode_action = QAction("Toggle Edit Mode", self)
        self.toggle_submode_action.setShortcut(QKeySequence("Tab"))
        self.toggle_submode_action.triggered.connect(self.toggle_edit_submode)
        self.addAction(self.toggle_submode_action)

    def toggle_edit_mode(self):
        """Toggle button movability."""
        if not self.isMaximized():
            print("[INFO] Edit mode only available in maximized window")
            if hasattr(self, 'status_label'):
                self.status_label.setText("Edit mode requires maximized window (F11 or [] button)")
                self.status_label.show()
                QTimer.singleShot(3000, self.status_label.hide)
            return

        decision = None
        # Exiting edit mode: always ask whether to save current layout.
        if self.edit_mode:
            decision = self._prompt_save_layout_changes("exit edit mode")
            if decision == "cancel":
                return

        scale, offset_x, offset_y = self._get_scale_and_offset()

        self.edit_mode = not self.edit_mode
        print(f"[INFO] Edit Mode: {'ON' if self.edit_mode else 'OFF'}")

        # Show specific message
        if self.edit_mode:
            # Start in items mode by default
            self.edit_connectors_mode = False
            self._layout_dirty = False
            self._layout_discarded = False
            self._update_edit_status_label()
            self.status_label.show()
            self.status_label.raise_()
        else:
            self.status_label.hide()

        # Apply edit mode based on current sub-mode
        self._apply_edit_mode_state(scale, offset_x, offset_y)

        # If user selected "No", restore last saved layout from config.
        if not self.edit_mode and decision == "discarded":
            self._revert_to_saved_layout()

    def _on_edit_mode_shortcut(self):
        """Handle Ctrl+E shortcut - only works if edit_mode_enabled is True."""
        if self.edit_mode_enabled:
            self.toggle_edit_mode()
        else:
            print("[INFO] Edit Mode is disabled. Enable it in Settings > Welcome.")

    def _mark_layout_dirty(self):
        """Mark layout changes as unsaved while editing."""
        if self.edit_mode:
            self._layout_dirty = True
            self._layout_discarded = False

    def _save_all_layout(self, force: bool = False):
        """Save connectors, panels, and button layout together."""
        self._save_connectors_state(force=force)
        self._save_panels_state(force=force)
        self.save_layout(force=force)
        self._layout_discarded = False

    def _prompt_save_layout_changes(self, context: str) -> str:
        """
        Ask whether to save current layout changes.
        Returns one of: saved, discarded, cancel.
        """
        if self._layout_dirty:
            msg = (
                "You have unsaved layout changes.\n\n"
                f"Do you want to save before {context}?"
            )
        else:
            msg = f"Do you want to save the current layout before {context}?"
        reply = QMessageBox.question(
            self,
            "Save Layout Changes",
            msg,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._save_all_layout(force=True)
            self._layout_dirty = False
            self._layout_discarded = False
            return "saved"
        if reply == QMessageBox.StandardButton.No:
            self._layout_dirty = False
            self._layout_discarded = True
            return "discarded"
        return "cancel"

    def _revert_to_saved_layout(self):
        """Reload last saved layout/config state and refresh the dashboard."""
        print("[INFO] Reverting to last saved layout")
        self.config.reload_config()
        self.opacity_defaults = self.config.get_opacity_defaults()

        # Reset normalized caches before reading persisted layout.
        self._layout_normalized = {}
        self._panel_normalized = {}

        self._load_layout()
        self._refresh_components()
        if self._layout_ready:
            self._apply_scaled_layout()
        self._apply_layer_order()

        self._layout_dirty = False
        self._layout_discarded = False
    
    def set_edit_mode_enabled(self, enabled: bool):
        """Set whether Ctrl+E shortcut is allowed to toggle edit mode."""
        self.edit_mode_enabled = enabled
        print(f"[INFO] Edit Mode Key (Ctrl+E) {'ENABLED' if enabled else 'DISABLED'}")

    def toggle_edit_submode(self):
        """Toggle between editing connectors vs other items."""
        if not self.edit_mode:
            return  # Only works when in edit mode
        
        self.edit_connectors_mode = not self.edit_connectors_mode
        print(f"[INFO] Edit Sub-Mode: {'CONNECTORS' if self.edit_connectors_mode else 'ITEMS'}")
        
        scale, offset_x, offset_y = self._get_scale_and_offset()
        self._apply_edit_mode_state(scale, offset_x, offset_y)
        self._update_edit_status_label()

    def _update_edit_status_label(self):
        """Update status label based on current edit mode."""
        if self.edit_connectors_mode:
            self.status_label.setText("EDIT MODE: CONNECTORS\nDrag lines • Tab to switch • Ctrl+S to Save")
            self.status_label.setStyleSheet("QLabel { color: #00FF00; font-size: 14px; font-weight: bold; background: rgba(0,0,0,200); border: 3px dashed green; padding: 10px; border-radius: 8px; }")
        else:
            self.status_label.setText("EDIT MODE: ITEMS\nDrag icons/panels • Tab to switch • Ctrl+S to Save")
            self.status_label.setStyleSheet("QLabel { color: #FF0000; font-size: 14px; font-weight: bold; background: rgba(0,0,0,200); border: 3px dashed red; padding: 10px; border-radius: 8px; }")
        self._reposition_status_label()

    def _reposition_status_label(self):
        """Center status label horizontally within the current window width."""
        target = self.central_widget if hasattr(self, 'central_widget') else self
        window_w = max(400, target.width())
        label_w = min(880, window_w - 40)  # max 880px, 20px padding each side
        label_x = (window_w - label_w) // 2
        self.status_label.setGeometry(label_x, 30, label_w, 80)

    def _apply_edit_mode_state(self, scale, offset_x, offset_y):
        """Apply lock/unlock state based on current edit mode and sub-mode."""
        if self.edit_mode:
            if self.edit_connectors_mode:
                # CONNECTORS MODE: Lock all items, unlock connectors
                for name, btn in self.all_buttons.items():
                    if hasattr(btn, 'set_movable'):
                        btn.set_movable(False)
                
                if hasattr(self, 'dynamic_widgets'):
                    for widget in self.dynamic_widgets:
                        if isinstance(widget, ConnectorLine):
                            widget.set_locked(False)
                            target = self.central_widget if hasattr(self, 'central_widget') else self
                            widget.setGeometry(0, 0, target.width(), target.height())
                            widget.set_view_transform(scale, offset_x, offset_y, self.base_width, self.base_height)
                            widget.update_geometry()
                            if hasattr(widget, 'raise_hit_layer'):
                                widget.raise_hit_layer()
                        elif isinstance(widget, DisplayPanel):
                            widget.set_locked(True)
            else:
                # ITEMS MODE: Lock connectors, unlock all items
                for name, btn in self.all_buttons.items():
                    if hasattr(btn, 'set_movable'):
                        btn.set_movable(True)
                
                # Unlock title banner panels for editing
                if hasattr(self, 'hud_title_banner') and self.hud_title_banner is not None:
                    self.hud_title_banner.set_locked(False)
                
                if hasattr(self, 'dynamic_widgets'):
                    for widget in self.dynamic_widgets:
                        if isinstance(widget, ConnectorLine):
                            widget.set_locked(True)
                            target = self.central_widget if hasattr(self, 'central_widget') else self
                            widget.setGeometry(0, 0, target.width(), target.height())
                            widget.set_view_transform(scale, offset_x, offset_y, self.base_width, self.base_height)
                            widget.update_geometry()
                        elif isinstance(widget, DisplayPanel):
                            widget.set_locked(False)
        else:
            # NORMAL MODE: Lock everything
            for name, btn in self.all_buttons.items():
                if hasattr(btn, 'set_movable'):
                    btn.set_movable(False)
            
            # Lock title banner panel
            if hasattr(self, 'hud_title_banner') and self.hud_title_banner is not None:
                self.hud_title_banner.set_locked(True)
            
            if hasattr(self, 'dynamic_widgets'):
                for widget in self.dynamic_widgets:
                    if hasattr(widget, 'set_locked'):
                        widget.set_locked(True)
                    if isinstance(widget, ConnectorLine):
                        target = self.central_widget if hasattr(self, 'central_widget') else self
                        widget.setGeometry(0, 0, target.width(), target.height())
                        widget.set_view_transform(scale, offset_x, offset_y, self.base_width, self.base_height)
                        widget.update_geometry()

        self._apply_layer_order()

    def _get_scale_and_offset(self):
        """Return scale and letterbox offset based on current window size."""
        target = self.central_widget if hasattr(self, 'central_widget') else self
        window_w = max(1, target.width())
        window_h = max(1, target.height())
        scale_x = window_w / self.base_width
        scale_y = window_h / self.base_height

        if self.keep_aspect:
            scale = min(scale_x, scale_y)
            offset_x = (window_w - (self.base_width * scale)) / 2.0
            offset_y = (window_h - (self.base_height * scale)) / 2.0
            return scale, offset_x, offset_y

        # Fallback: uniform scale without letterboxing
        scale = min(scale_x, scale_y)
        return scale, 0.0, 0.0

    def _get_scale_and_offset_for_size(self, window_w, window_h):
        """Return scale and letterbox offset for a specific window size."""
        window_w = max(1, window_w)
        window_h = max(1, window_h)
        scale_x = window_w / self.base_width
        scale_y = window_h / self.base_height

        if self.keep_aspect:
            scale = min(scale_x, scale_y)
            offset_x = (window_w - (self.base_width * scale)) / 2.0
            offset_y = (window_h - (self.base_height * scale)) / 2.0
            return scale, offset_x, offset_y

        scale = min(scale_x, scale_y)
        return scale, 0.0, 0.0

    def _normalize_point_for_window(self, point, window_w, window_h):
        """Normalize a window-space point using a specific window size."""
        scale, offset_x, offset_y = self._get_scale_and_offset_for_size(window_w, window_h)
        base_x = (point.x() - offset_x) / scale
        base_y = (point.y() - offset_y) / scale
        return [base_x / self.base_width, base_y / self.base_height]

    def _denormalize_point_for_window(self, point_pct, window_w, window_h):
        """Denormalize a base point using a specific window size."""
        scale, offset_x, offset_y = self._get_scale_and_offset_for_size(window_w, window_h)
        base_x = point_pct[0] * self.base_width
        base_y = point_pct[1] * self.base_height
        x = offset_x + (base_x * scale)
        y = offset_y + (base_y * scale)
        return QPointF(x, y)

    def _get_letterbox_rect(self):
        """Return the letterboxed rect for the base canvas."""
        scale, offset_x, offset_y = self._get_scale_and_offset()
        width = int(self.base_width * scale)
        height = int(self.base_height * scale)
        return int(offset_x), int(offset_y), width, height

    def _to_normalized_rect(self, x, y, w, h):
        """Convert window-space rect to normalized base coordinates."""
        scale, offset_x, offset_y = self._get_scale_and_offset()
        base_x = (x - offset_x) / scale
        base_y = (y - offset_y) / scale
        base_w = w / scale
        base_h = h / scale
        return {
            'x_pct': base_x / self.base_width,
            'y_pct': base_y / self.base_height,
            'w_pct': base_w / self.base_width,
            'h_pct': base_h / self.base_height
        }

    def _from_normalized_rect(self, norm):
        """Convert normalized base coordinates to window-space rect."""
        scale, offset_x, offset_y = self._get_scale_and_offset()
        base_x = norm['x_pct'] * self.base_width
        base_y = norm['y_pct'] * self.base_height
        base_w = norm['w_pct'] * self.base_width
        base_h = norm['h_pct'] * self.base_height
        x = offset_x + (base_x * scale)
        y = offset_y + (base_y * scale)
        w = max(1, base_w * scale)
        h = max(1, base_h * scale)
        return int(x), int(y), int(w), int(h)

    def _normalize_point(self, point):
        """Convert window-space point to normalized base coordinates."""
        scale, offset_x, offset_y = self._get_scale_and_offset()
        base_x = (point.x() - offset_x) / scale
        base_y = (point.y() - offset_y) / scale
        return [base_x / self.base_width, base_y / self.base_height]

    def _denormalize_point(self, point_pct):
        """Convert normalized base point to window-space coordinates."""
        scale, offset_x, offset_y = self._get_scale_and_offset()
        base_x = point_pct[0] * self.base_width
        base_y = point_pct[1] * self.base_height
        x = offset_x + (base_x * scale)
        y = offset_y + (base_y * scale)
        return int(x), int(y)

    def _capture_default_layout(self):
        """Capture current geometry as normalized defaults."""
        for name, widget in self.all_buttons.items():
            self._layout_normalized[name] = self._to_normalized_rect(
                widget.x(), widget.y(), widget.width(), widget.height()
            )

        for name, widget in self._fixed_widgets.items():
            self._layout_normalized[name] = self._to_normalized_rect(
                widget.x(), widget.y(), widget.width(), widget.height()
            )

    def _extract_normalized_rect(self, data, fallback_width, fallback_height):
        """Extract normalized geometry from config data with fallback."""
        if not data:
            return None

        if all(k in data for k in ('x_pct', 'y_pct', 'w_pct', 'h_pct')):
            return {
                'x_pct': float(data.get('x_pct', 0.0)),
                'y_pct': float(data.get('y_pct', 0.0)),
                'w_pct': float(data.get('w_pct', 0.0)),
                'h_pct': float(data.get('h_pct', 0.0))
            }

        if all(k in data for k in ('x', 'y', 'width', 'height')):
            return {
                'x_pct': float(data.get('x', 0.0)) / fallback_width,
                'y_pct': float(data.get('y', 0.0)) / fallback_height,
                'w_pct': float(data.get('width', 0.0)) / fallback_width,
                'h_pct': float(data.get('height', 0.0)) / fallback_height
            }

        return None

    def _apply_scaled_layout(self):
        """Apply normalized geometry to widgets based on current size."""
        if not self._layout_normalized:
            return

        scale, offset_x, offset_y = self._get_scale_and_offset()

        for name, widget in self.all_buttons.items():
            norm = self._layout_normalized.get(name)
            if not norm:
                norm = self._to_normalized_rect(widget.x(), widget.y(), widget.width(), widget.height())
                self._layout_normalized[name] = norm
            x, y, w, h = self._from_normalized_rect(norm)
            # Settings button is scaled at 0.88x to match desired visual weight.
            # Use float arithmetic + round() to avoid integer rounding drift.
            if name == 'settings':
                scale_f = 0.88
                cx_f = x + w / 2.0
                cy_f = y + h / 2.0
                w_f = max(1.0, w * scale_f)
                h_f = max(1.0, h * scale_f)
                x = round(cx_f - w_f / 2.0)
                y = round(cy_f - h_f / 2.0)
                w = round(w_f)
                h = round(h_f)
            widget.setGeometry(x, y, w, h)

        for name, widget in self._fixed_widgets.items():
            norm = self._layout_normalized.get(name)
            if not norm:
                norm = self._to_normalized_rect(widget.x(), widget.y(), widget.width(), widget.height())
                self._layout_normalized[name] = norm
            x, y, w, h = self._from_normalized_rect(norm)
            widget.setGeometry(x, y, w, h)

        for panel in self.display_panels:
            norm = self._panel_normalized.get(panel)
            if not norm:
                norm = self._to_normalized_rect(panel.x(), panel.y(), panel.width(), panel.height())
                self._panel_normalized[panel] = norm
            x, y, w, h = self._from_normalized_rect(norm)
            panel.setGeometry(x, y, w, h)
            if hasattr(panel, 'apply_scale'):
                panel.apply_scale(scale)

        for i, conn in enumerate(self.connectors):
            target = self.central_widget if hasattr(self, 'central_widget') else self
            conn.setGeometry(0, 0, target.width(), target.height())
            print(f"[CONN{i}] Setting view transform: scale={scale:.3f}, offset=({offset_x:.1f},{offset_y:.1f}), base=({self.base_width}x{self.base_height})")
            if hasattr(conn, 'points_normalized') and conn.points_normalized:
                print(f"[CONN{i}] Normalized points[0]={conn.points_normalized[0]}")
                pixel = conn._normalized_to_pixel(conn.points_normalized[0][0], conn.points_normalized[0][1])
                print(f"[CONN{i}] Should render at pixel ({pixel.x():.1f}, {pixel.y():.1f})")
            conn.set_view_transform(scale, offset_x, offset_y, self.base_width, self.base_height)
            if hasattr(conn, 'apply_scale'):
                conn.apply_scale(scale)
            conn.update_geometry()

        self._apply_scaled_text(scale)
        self._apply_layer_order()

    def _apply_layer_order(self):
        """Apply z-order based on config layer ordering (front to back)."""
        layer_order = self.config.get_layer_order()
        groups = self._get_layer_groups()

        # Start by lowering everything to avoid stale ordering
        for widget_list in groups.values():
            for widget in widget_list:
                widget.lower()

        # Raise from back to front (excluding video, which should stay behind)
        for layer_name in reversed(layer_order):
            if layer_name != "video":
                for widget in groups.get(layer_name, []):
                    widget.raise_()

        # Always lower video to back at the end
        video_list = groups.get("video", [])
        for video in video_list:
            video.lower()

        # IMPORTANT: Ensure background_fill is at the VERY BACK
        # background_media is in the video_layer and will be above it after lower() calls
        if hasattr(self, 'background_fill') and self.background_fill is not None:
            self.background_fill.lower()

        # In connector edit mode, ensure hit-layers are on top for interaction
        if self.edit_mode and self.edit_connectors_mode:
            for conn in self.connectors:
                if hasattr(conn, 'raise_hit_layer'):
                    conn.raise_hit_layer()

    def _get_layer_groups(self):
        """Collect widgets by layer category."""
        connectors = list(self.connectors)
        display_panels = list(self.display_panels)

        layer_groups = {
            "layer_1": [],
            "layer_2": [],
            "layer_3": []
        }

        for name, widget in self.custom_icon_widgets.items():
            layer = self.custom_icon_layers.get(name, "layer_1")
            if layer not in layer_groups:
                layer_groups[layer] = []
            layer_groups[layer].append(widget)

        # Keep settings button on top of the icon layers
        if 'settings' in self.all_buttons:
            layer_groups.setdefault("layer_3", []).append(self.all_buttons['settings'])

        video_layer = []
        if hasattr(self, 'background_media') and self.background_media is not None:
            video_layer.append(self.background_media)
        if hasattr(self, 'background_fill') and self.background_fill is not None:
            video_layer.append(self.background_fill)
        if hasattr(self, 'video_bg'):
            video_layer.append(self.video_bg)

        groups = {
            "connectors": connectors,
            "display_panels": display_panels,
            "video": video_layer
        }
        groups.update(layer_groups)
        return groups

    def _apply_scaled_text(self, scale):
        """Scale text and padding for key labels."""
        if hasattr(self, 'active_counter'):
            font_size = max(8, int(self.active_counter_base_font * scale))
            target = self.active_counter.content_label if hasattr(self.active_counter, 'content_label') else self.active_counter
            style = (
                "QLabel { color: #00F3FF; font-size: "
                + str(font_size)
                + "px; font-weight: bold; background: transparent; }"
            )
            target.setStyleSheet(style)
            if target is not self.active_counter:
                self.active_counter.setStyleSheet(style)

        if hasattr(self, 'title_label'):
            font_size = max(10, int(self.title_label_base_font * scale))
            padding = max(4, int(self.title_label_base_padding * scale))
            border = max(1, int(self.title_label_base_border * scale))
            target = self.title_label.content_label if hasattr(self.title_label, 'content_label') else self.title_label
            style = (
                "QLabel { color: #00F3FF; font-size: "
                + str(font_size)
                + "px; font-weight: bold; background: rgba(0, 0, 0, 150); border: "
                + str(border)
                + "px solid #00F3FF; border-radius: 10px; padding: "
                + str(padding)
                + "px; }"
            )
            target.setStyleSheet(style)
            if target is not self.title_label:
                self.title_label.setStyleSheet(style)
    
    def resizeEvent(self, event):
        """Handle window resize to scale background."""
        super().resizeEvent(event)
        self._update_background_geometry()
        # Note: Title banner position is now persistent - don't reset on resize
        # Skip layout application while minimized — the reported size is wrong.
        if self.isMinimized():
            return
        if self._layout_ready:
            self._apply_scaled_layout()
        if hasattr(self, 'status_label') and self.status_label.isVisible():
            self._reposition_status_label()
        if hasattr(self, 'settings_hover_menu'):
            self._update_settings_hover_menu_position()

    def changeEvent(self, event):
        """Re-apply layout after restoring from minimized state."""
        super().changeEvent(event)
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange:
            if not self.isMinimized() and self._layout_ready:
                # Delay one event loop tick so Qt has settled the final size.
                QTimer.singleShot(50, self._apply_scaled_layout)

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for window control."""
        if event.key() == Qt.Key.Key_F11:
            # F11 to toggle maximize
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            # ESC to minimize
            self.showMinimized()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _update_background_geometry(self):
        """Update video background to match current scaling mode."""
        if hasattr(self, 'background_fill'):
            self.background_fill.setGeometry(0, 0, self.central_widget.width(), self.central_widget.height())

        if not hasattr(self, 'background_media') or self.background_media is None:
            return

        x, y, w, h = self._get_background_rect()
        self.background_media.setGeometry(x, y, w, h)

    def toggle_maximize(self):
        """Toggle between maximized and default size."""
        if self.isMaximized():
            self.showNormal()
            self.resize(1280, 720)
        else:
            self.showMaximized()
            
    def save_layout(self, force: bool = False):
        """Save current button positions to YAML."""
        # Only save when maximized — non-maximized geometry causes rounding drift.
        if not self.isMaximized():
            print("[INFO] save_layout skipped: window is not maximized")
            return

        # During edit mode, don't auto-save on every movement.
        # Save only when explicitly requested (Ctrl+S / prompt / close flow).
        if self.edit_mode and not force:
            self._mark_layout_dirty()
            return

        layout_data = dict(self.config.config) if hasattr(self, 'config') else {}

        # Always record as maximized so reopen is always maximized
        layout_data['window'] = {
            'maximized': True,
            'width': self.width(),
            'height': self.height(),
            'base_width': self.base_width,
            'base_height': self.base_height,
            'keep_aspect': self.keep_aspect
        }

        for name, btn in self.all_buttons.items():
            if name == 'rviz':
                print(f"[DEBUG] Saving rviz position: {btn.x()}, {btn.y()}")
            # In edit mode the user may have dragged the widget — re-derive
            # from its actual pixel position (truth).
            # Outside edit mode the position was set by _apply_scaled_layout
            # using int() truncation; using the cached float normalised values
            # avoids accumulating rounding drift across close/reopen cycles.
            if self.edit_mode:
                if name == 'settings':
                    # The button is displayed at 0.88x. Reconstruct the full-size
                    # geometry (same center, un-shrunk dims) before normalizing so
                    # that x_pct/y_pct/w_pct/h_pct are all self-consistent.
                    # Saving the 0.88 top-left with the full-size dims causes the
                    # center to shift by +0.06*full_w on every save/reload cycle.
                    cx = btn.x() + btn.width() / 2.0
                    cy = btn.y() + btn.height() / 2.0
                    fw = btn.width() / 0.88
                    fh = btn.height() / 0.88
                    fx = cx - fw / 2.0
                    fy = cy - fh / 2.0
                    btn_data = self._to_normalized_rect(fx, fy, fw, fh)
                else:
                    btn_data = self._to_normalized_rect(btn.x(), btn.y(), btn.width(), btn.height())
            else:
                btn_data = dict(self._layout_normalized.get(
                    name,
                    self._to_normalized_rect(btn.x(), btn.y(), btn.width(), btn.height())
                ))
            if hasattr(btn, 'opacity_effect'):
                btn_data['opacity'] = btn.opacity_effect.opacity()

            self._layout_normalized[name] = btn_data
            layout_data[name] = btn_data

        for name, widget in self._fixed_widgets.items():
            if self.edit_mode:
                fixed_data = self._to_normalized_rect(widget.x(), widget.y(), widget.width(), widget.height())
            else:
                fixed_data = dict(self._layout_normalized.get(
                    name,
                    self._to_normalized_rect(widget.x(), widget.y(), widget.width(), widget.height())
                ))
            self._layout_normalized[name] = fixed_data
            layout_data[name] = fixed_data
        
        try:
            # Ensure config dir exists
            self.layout_config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.layout_config_path, 'w') as f:
                yaml.dump(layout_data, f)
            
            if hasattr(self, 'config'):
                self.config.config = layout_data
            self._layout_dirty = False
            self._layout_discarded = False
            print(f"[INFO] Layout saved to {self.layout_config_path}")
            self.status_label.setText("Layout Saved!")
            QTimer.singleShot(2000, lambda: self.status_label.setText("EDIT MODE: Drag icons. Shift+Scroll for Opacity. Ctrl+S to Save."))
            
        except Exception as e:
            print(f"[ERROR] Failed to save layout: {e}")

    def _load_layout(self):
        """Load saved button positions."""
        if not self.layout_config_path.exists():
            return
            
        try:
            with open(self.layout_config_path, 'r') as f:
                layout_data = yaml.safe_load(f)
            
            if not layout_data:
                return

            print(f"[INFO] Loading layout from {self.layout_config_path}")
            
            # Restore window state
            window_config = layout_data.get('window')
            if window_config:
                print(f"[DEBUG] Found window config: {window_config}")
                if window_config.get('maximized', False):
                    print("[DEBUG] Restoring Maximized State")
                    self.showMaximized()
                else:
                    w = window_config.get('width', 1280)
                    h = window_config.get('height', 720)
                    print(f"[DEBUG] Restoring Window Size: {w}x{h}")
                    self.resize(w, h)

                self.base_width = int(window_config.get('base_width', self.base_width))
                self.base_height = int(window_config.get('base_height', self.base_height))
                self.keep_aspect = bool(window_config.get('keep_aspect', self.keep_aspect))

            fallback_width = window_config.get('width', self.base_width) if window_config else self.base_width
            fallback_height = window_config.get('height', self.base_height) if window_config else self.base_height
            
            for name, data in layout_data.items():
                if name in self.all_buttons:
                    btn = self.all_buttons[name]
                    norm = self._extract_normalized_rect(data, fallback_width, fallback_height)
                    if norm:
                        self._layout_normalized[name] = norm

                    if hasattr(btn, 'opacity_effect'):
                        opacity = data.get('opacity')
                        if opacity is not None:
                            btn.opacity_effect.setOpacity(opacity)
                        elif isinstance(btn, MovableLabel) and btn.fixed_opacity is not None:
                            btn.opacity_effect.setOpacity(btn.fixed_opacity)

                    if isinstance(btn, MovableLabel):
                        btn.setScaledContents(True)

                if name in self._fixed_widgets:
                    norm = self._extract_normalized_rect(data, fallback_width, fallback_height)
                    if norm:
                        self._layout_normalized[name] = norm
                    
        except Exception as e:
            print(f"[ERROR] Failed to load layout: {e}")
    
    def _setup_background(self):
        """Setup background (video or image) with fill layer."""
        self.background_fill = BackgroundFill(self.central_widget)
        self.background_fill.lower()
        self.background_media = None
        self._apply_background_settings()
        print("[DEBUG] Background setup complete")

    def _get_background_rect(self):
        """Return letterbox rect using configured aspect ratio (16:10 or 16:9)."""
        settings = self.config.get_background_settings()
        aspect_ratio = settings.get('aspect_ratio', '16:10')
        
        if aspect_ratio == '16:9':
            aspect = 16.0 / 9.0
        else:  # Default to 16:10
            aspect = 16.0 / 10.0
        
        target = self.central_widget
        window_w = max(1, target.width())
        window_h = max(1, target.height())
        
        if (window_w / window_h) > aspect:
            new_w = int(window_h * aspect)
            new_h = window_h
            x = int((window_w - new_w) / 2)
            y = 0
        else:
            new_w = window_w
            new_h = int(window_w / aspect)
            x = 0
            y = int((window_h - new_h) / 2)
        return x, y, new_w, new_h

    def _clear_background_media(self):
        if hasattr(self, 'background_media') and self.background_media is not None:
            if isinstance(self.background_media, VideoBackground):
                self.background_media.stop()
            self.background_media.hide()
            self.background_media.deleteLater()
            self.background_media = None

    def _apply_background_settings(self):
        settings = self.config.get_background_settings()
        bg_type = settings.get('type', 'video')
        bg_file = settings.get('file', 'dashboard_bg.mp4')
        fill = settings.get('fill', {})
        fill_mode = fill.get('mode', 'color')
        fill_color = fill.get('color', '#0A0E1A')
        fill_color2 = fill.get('color2', '#000000')
        fill_image = fill.get('image', '')

        # Apply fill layer
        fill_path = (self.resource_dir / fill_image) if fill_image else None
        self.background_fill.set_fill(fill_mode, fill_color, fill_color2, str(fill_path) if fill_path else '')

        # Clear any existing media
        self._clear_background_media()

        if bg_type == 'none':
            self._update_background_geometry()
            return

        # Resolve background media path
        bg_path = self.resource_dir / bg_file
        
        if not bg_path.exists():
            bg_path = self.resource_dir / 'dashboard_bg.mp4'

        if bg_type == 'image':
            label = QLabel(self.central_widget)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setScaledContents(True)
            label.setStyleSheet("background: transparent;")
            pixmap = QPixmap(str(bg_path)) if bg_path.exists() else QPixmap()
            label.setPixmap(pixmap)
            self.background_media = label
        else:
            self.background_media = VideoBackground(str(bg_path), self.central_widget)
            self.background_media.video_label.setStyleSheet("background: transparent;")
            self.background_media.play()

        # Use opacity from background settings
        video_opacity = settings.get('opacity', 0.7)
        video_opacity = max(0.05, min(1.0, video_opacity))
        self.video_bg_opacity = QGraphicsOpacityEffect(self.background_media)
        self.video_bg_opacity.setOpacity(video_opacity)
        self.background_media.setGraphicsEffect(self.video_bg_opacity)
        self.background_media.show()  # Explicitly show the widget
        
        self._update_background_geometry()
        
        # Tell fill layer the background media dimensions (for proper letterbox rendering)
        x, y, w, h = self._get_background_rect()
        self.background_fill.set_background_rect(x, y, w, h)
    
    def _setup_panels(self):
        """Setup transparent panel overlays."""
        print("[DEBUG] Setting up panels...")
        
        # Sidebar panel (right side)
        sidebar_path = self.panels_dir / "sidebar.png"
        print(f"[DEBUG] Sidebar path: {sidebar_path}, exists: {sidebar_path.exists()}")
        
        if sidebar_path.exists():
            # Default opacity for background panel
            panel_opacity = float(self.opacity_defaults.get('panels', 0.5))
            self.sidebar = MovableLabel(self.central_widget, fixed_opacity=panel_opacity)
            self.sidebar.setObjectName("sidebar")
            self.sidebar.setPixmap(QPixmap(str(sidebar_path)))
            self.sidebar.setGeometry(720, 0, 560, 812)  # Position from CSS
            self.sidebar.raise_()  # Bring to front
            self.all_buttons['sidebar'] = self.sidebar
            print("[DEBUG] Sidebar created as MovableLabel (Fixed 0.6 Opacity)")
        
        # Display bar (top)
        displaybar_path = self.panels_dir / "displaybar.png"
        print(f"[DEBUG] Displaybar path: {displaybar_path}, exists: {displaybar_path.exists()}")
        
        if displaybar_path.exists():
            # Default opacity for background panel
            panel_opacity = float(self.opacity_defaults.get('panels', 0.5))
            self.displaybar = MovableLabel(self.central_widget, fixed_opacity=panel_opacity)
            self.displaybar.setObjectName("displaybar")
            self.displaybar.setPixmap(QPixmap(str(displaybar_path)))
            self.displaybar.setGeometry(462, 50, 356, 159)  # Position from CSS
            self.displaybar.raise_()  # Bring to front
            self.all_buttons['displaybar'] = self.displaybar
            print("[DEBUG] Displaybar created as MovableLabel (Fixed 0.6 Opacity)")
    
    def _setup_static_icons(self):
        """Setup additional static icons and glass backgrounds (Movable)."""
        print("[DEBUG] Setting up static icons...")
        
        # Helper to add movable icon
        def add_icon(name, filename, x, y, w=None, h=None, fixed_opacity=None):
            path = self.icons_dir / filename
            if not path.exists():
                path = self.panels_dir / filename # Check panels if not in icons
            
            if path.exists():
                lbl = MovableLabel(self.central_widget, fixed_opacity=fixed_opacity)
                lbl.setObjectName(name)
                pixmap = QPixmap(str(path))
                if w and h:
                    pixmap = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                lbl.setPixmap(pixmap)
                lbl.setGeometry(x, y, pixmap.width(), pixmap.height())
                lbl.raise_()
                lbl.positionChanged.connect(self.save_layout)
                self.all_buttons[name] = lbl
                return lbl
            print(f"[WARNING] Static icon not found: {filename}")
            return None

        # Glass Backgrounds (Default opacity)
        shape_opacity = float(self.opacity_defaults.get('shapes', 0.5))
        add_icon("glass_circle_1", "neon-glass-circle.png", 260, 110, 180, 180, fixed_opacity=shape_opacity) # Behind Combo 1
        add_icon("glass_oval", "neon-glass-oval.png", 260, 440, 180, 180, fixed_opacity=shape_opacity) # Behind Combo 2
        add_icon("glass_circle_2", "neon-glass-circle.png", 440, 590, 180, 180, fixed_opacity=shape_opacity) # Behind Combo 3
        
        # Extra Glass Elements (Generic Palette)
        for i in range(11):
            # Create extra glass circles, stacked initially - Default opacity
            add_icon(f"extra_glass_circle_{i}", "neon-glass-circle.png", 50 + (i*20), 50, 100, 100, fixed_opacity=shape_opacity)
            # Ovals removed per request

        # Gazebo Text (gaze.png or gazebo.png text variant)
        # User said "gazebo text - gazebo.png", but usually gazebo.png is the text logo
        # Let's try gazebo.png as text, since we used Gazebo_icon.png for the button
        add_icon("gazebo_text", "gazebo.png", 50, 620) 

        # MoveIt Text & Icon
        add_icon("moveit_text", "moveit-white.png", 300, 380)
        add_icon("moveit_logo", "moveit_icon.png", 350, 300)

        # MicroROS
        add_icon("microros_text", "microros_white.png", 500, 550)
        add_icon("microros_logo", "microros_icon.png", 500, 480)
        
        # Hardware Interface
        add_icon("hardware_logo", "hardware_interface.png", 650, 500)
        
        print("[DEBUG] Static icons setup complete")

    def _setup_custom_icons(self):
        """Setup user-added custom icons from config."""
        custom_icons = self.config.get_custom_icons()
        if not custom_icons:
            return

        default_opacity = float(self.opacity_defaults.get('icons', 1.0))
        for icon_data in custom_icons:
            name = icon_data.get('name')
            filename = icon_data.get('file')
            if not name or not filename:
                continue
            if name in self.all_buttons:
                continue

            path = self.icons_dir / filename
            if not path.exists():
                print(f"[WARNING] Custom icon not found: {filename}")
                continue

            lbl = MovableLabel(self.central_widget, enable_glow=True)
            lbl.setObjectName(name)
            pixmap = QPixmap(str(path))
            lbl.setPixmap(pixmap)

            x = int(icon_data.get('x', 200))
            y = int(icon_data.get('y', 200))
            w = int(icon_data.get('width', pixmap.width()))
            h = int(icon_data.get('height', pixmap.height()))
            lbl.setGeometry(x, y, w, h)

            opacity = icon_data.get('opacity', default_opacity)
            if hasattr(lbl, 'opacity_effect'):
                lbl.opacity_effect.setOpacity(float(opacity))

            lbl.positionChanged.connect(self.save_layout)
            self.all_buttons[name] = lbl
            self.custom_icon_widgets[name] = lbl
            self.custom_icon_layers[name] = icon_data.get('layer') or self._infer_layer_from_file(filename)
            lbl.raise_()
    
    def _setup_buttons(self):
        """Setup all interactive buttons."""
        # Main launch buttons
        self._setup_main_buttons()
        
        # Plus combo buttons
        self._setup_combo_buttons()
        
        # Utility buttons (right panel)
        self._setup_utility_buttons()
        
        # Settings button (bottom center)
        self._setup_settings_button()
    
    def _setup_main_buttons(self):
        """Setup main launch buttons (RViz, Gazebo, etc.)."""
        print("[DEBUG] Setting up main buttons...")
        
        # RViz button (Group 1)
        # CSS Group: 167x170, Icon: 153x90
        rviz_icon = self.icons_dir / "rviz2.png"
        print(f"[DEBUG] RViz icon: {rviz_icon}, exists: {rviz_icon.exists()}")
        
        self.btn_rviz = AnimatedButton(str(rviz_icon), self.central_widget, icon_size=(153, 90))
        self.btn_rviz.setGeometry(50, 120, 167, 170)
        self.btn_rviz.clicked.connect(lambda: self._launch_button("rviz"))
        self.btn_rviz.positionChanged.connect(self.save_layout) # Connect signal
        self.btn_rviz.raise_()
        self.all_buttons['rviz'] = self.btn_rviz # Register
        
        # Gazebo button (Group 3)
        # CSS Group: 161x165, Icon (Gazebo-n): 105x95
        # Using Gazebo_icon.png as it matches 105x95
        gazebo_icon = self.icons_dir / "Gazebo_icon.png" 
        print(f"[DEBUG] Gazebo icon: {gazebo_icon}, exists: {gazebo_icon.exists()}")
        
        self.btn_gazebo = AnimatedButton(str(gazebo_icon), self.central_widget, icon_size=(105, 95))
        self.btn_gazebo.setGeometry(50, 450, 161, 165)
        self.btn_gazebo.clicked.connect(lambda: self._launch_button("gazebo"))
        self.btn_gazebo.positionChanged.connect(self.save_layout) # Connect signal
        self.btn_gazebo.raise_()
        self.all_buttons['gazebo'] = self.btn_gazebo # Register
        
        print("[DEBUG] Main buttons created")
    
    def _setup_combo_buttons(self):
        """Setup plus icon combo buttons."""
        # Plus buttons (Group 12, 14, 17)
        # CSS Group: 161x165, Icon (plus++): 96x96
        plus_icon = self.icons_dir / "plus++.png"
        w, h = 96, 96
        
        # Combo 1 (RViz + Gazebo) - Top Plus
        self.btn_combo1 = AnimatedButton(str(plus_icon), self.central_widget, icon_size=(w, h))
        self.btn_combo1.setGeometry(270, 120, 161, 165)
        self.btn_combo1.clicked.connect(lambda: self._launch_button("all"))
        self.btn_combo1.positionChanged.connect(self.save_layout)
        self.btn_combo1.raise_()
        self.all_buttons['combo1'] = self.btn_combo1 # Register
        
        # Combo 2 (RViz + MoveIt) - Middle Plus? (Layout guess)
        self.btn_combo2 = AnimatedButton(str(plus_icon), self.central_widget, icon_size=(w, h))
        self.btn_combo2.setGeometry(270, 450, 161, 165) # Adjusted position
        self.btn_combo2.clicked.connect(lambda: self._launch_button("moveit"))
        self.btn_combo2.positionChanged.connect(self.save_layout)
        self.btn_combo2.raise_()
        self.all_buttons['combo2'] = self.btn_combo2 # Register
        
        # Combo 3 - Bottom/Right Plus
        self.btn_combo3 = AnimatedButton(str(plus_icon), self.central_widget, icon_size=(w, h))
        self.btn_combo3.setGeometry(450, 600, 161, 165) # Adjusted position
        self.btn_combo3.clicked.connect(lambda: self._launch_button("sim"))
        self.btn_combo3.positionChanged.connect(self.save_layout)
        self.btn_combo3.raise_()
        self.all_buttons['combo3'] = self.btn_combo3 # Register
    
    def _setup_utility_buttons(self):
        """Setup utility buttons in right panel."""
        # Common group size: 139x142
        gw, gh = 139, 142
        
        # Kill all processes (Group 6: killprocess 91x91)
        kill_icon = self.icons_dir / "killprocess.png"
        self.btn_kill = AnimatedButton(str(kill_icon), self.central_widget, icon_size=(91, 91))
        self.btn_kill.setGeometry(750, 120, gw, gh)
        self.btn_kill.clicked.connect(self._kill_all_processes)
        self.btn_kill.positionChanged.connect(self.save_layout)
        self.btn_kill.raise_()
        self.all_buttons['kill'] = self.btn_kill # Register
        
        # Trajectory system (Group 7: trajectory 100x92)
        traj_icon = self.icons_dir / "trajectory.png.png"
        self.btn_trajectory = AnimatedButton(str(traj_icon), self.central_widget, icon_size=(100, 92))
        self.btn_trajectory.setGeometry(920, 120, gw, gh)
        self.btn_trajectory.clicked.connect(lambda: self._launch_utility("trajectory"))
        self.btn_trajectory.positionChanged.connect(self.save_layout)
        self.btn_trajectory.raise_()
        self.all_buttons['trajectory'] = self.btn_trajectory # Register
        
        # System monitor (Group 11: system_monitor 87x87)
        monitor_icon = self.icons_dir / "system_monitor.png"
        self.btn_monitor = AnimatedButton(str(monitor_icon), self.central_widget, icon_size=(87, 87))
        self.btn_monitor.setGeometry(1090, 120, gw, gh)
        self.btn_monitor.clicked.connect(self._open_system_monitor)
        self.btn_monitor.positionChanged.connect(self.save_layout)
        self.btn_monitor.raise_()
        self.all_buttons['monitor'] = self.btn_monitor # Register
        
        # Firmware flash (Group 8: firmware 95x96)
        firmware_icon = self.icons_dir / "firmware.png"
        self.btn_firmware = AnimatedButton(str(firmware_icon), self.central_widget, icon_size=(95, 96))
        self.btn_firmware.setGeometry(750, 290, gw, gh)
        self.btn_firmware.positionChanged.connect(self.save_layout)
        self.btn_firmware.clicked.connect(self._open_firmware_dialog)
        self.btn_firmware.raise_()
        self.all_buttons['firmware'] = self.btn_firmware # Register
        
        # Waypoint generator (Group 9: wg 81x81)
        wg_icon = self.icons_dir / "wg.png"
        self.btn_wg = AnimatedButton(str(wg_icon), self.central_widget, icon_size=(81, 81))
        self.btn_wg.setGeometry(920, 290, gw, gh)
        self.btn_wg.clicked.connect(self._open_waypoint_generator)
        self.btn_wg.positionChanged.connect(self.save_layout)
        self.btn_wg.raise_()
        self.all_buttons['wg'] = self.btn_wg # Register
        
        # Waypoint visualizer (Group 10: wv 74x74)
        wv_icon = self.icons_dir / "wv.png"
        self.btn_wv = AnimatedButton(str(wv_icon), self.central_widget, icon_size=(74, 74))
        self.btn_wv.setGeometry(1090, 290, gw, gh)
        self.btn_wv.clicked.connect(self._open_waypoint_visualizer)
        self.btn_wv.positionChanged.connect(self.save_layout)
        self.btn_wv.raise_()
        self.all_buttons['wv'] = self.btn_wv # Register
    
    def _setup_settings_button(self):
        """Setup settings button with 720° rotation."""
        # Use layer_1_app subdirectory
        icon_pre = self.resource_dir / "layer_1_app" / "setting-pre.png"
        icon_main = self.resource_dir / "layer_1_app" / "setting-main.png"
        
        print(f"[DEBUG] Settings icon_pre: {icon_pre}, exists: {icon_pre.exists()}")
        print(f"[DEBUG] Settings icon_main: {icon_main}, exists: {icon_main.exists()}")
        
        self.btn_settings = SettingsButton(str(icon_pre), str(icon_main), self.central_widget)
        self.btn_settings.setGeometry(572, 600, 137, 137)  # Bottom center
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_settings.clicked.connect(lambda: print("[DEBUG] Settings button clicked!"))
        self.btn_settings.positionChanged.connect(self.save_layout)
        self.btn_settings.positionChanged.connect(self._update_settings_hover_menu_position)
        self.all_buttons['settings'] = self.btn_settings # Register
        self._setup_settings_hover_menu()

    def _setup_status_label(self):
        """Setup the edit mode status label."""
        self.status_label = QLabel(self.central_widget)
        self.status_label.setObjectName("status_label")
        self.status_label.setGeometry(200, 30, 880, 80)  # Wider and taller to fit text
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setWordWrap(True)
        self.status_label.hide()

    def _setup_settings_hover_menu(self):
        """Create the minimal HUD menu shown on settings hover."""
        self.settings_hover_menu = QFrame(self.central_widget)
        self.settings_hover_menu.setObjectName("settings_hover_menu")
        self.settings_hover_menu.setStyleSheet(
            "QFrame#settings_hover_menu {"
            "background: rgba(0, 0, 0, 190);"
            "border: 1px solid #00F3FF;"
            "border-radius: 10px;"
            "}"
            "QPushButton {"
            "color: #00F3FF;"
            "background: transparent;"
            "border: 1px solid rgba(0, 243, 255, 120);"
            "border-radius: 6px;"
            "padding: 8px 12px;"
            "font-size: 14px;"
            "}"
            "QPushButton:hover {"
            "background: rgba(0, 243, 255, 40);"
            "}"
        )

        layout = QHBoxLayout(self.settings_hover_menu)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.settings_menu_close = QPushButton("X", self.settings_hover_menu)
        self.settings_menu_close.setToolTip("Close Dashboard")
        self.settings_menu_close.setMinimumSize(36, 28)
        self.settings_menu_close.clicked.connect(self.close)

        self.settings_menu_minimize = QPushButton("_", self.settings_hover_menu)
        self.settings_menu_minimize.setToolTip("Minimize")
        self.settings_menu_minimize.setMinimumSize(36, 28)
        self.settings_menu_minimize.clicked.connect(self.showMinimized)

        self.settings_menu_maximize = QPushButton("[ ]", self.settings_hover_menu)
        self.settings_menu_maximize.setToolTip("Maximize / Restore")
        self.settings_menu_maximize.setMinimumSize(44, 28)
        self.settings_menu_maximize.clicked.connect(self.toggle_maximize)

        layout.addWidget(self.settings_menu_minimize)
        layout.addWidget(self.settings_menu_maximize)
        layout.addWidget(self.settings_menu_close)

        self._settings_menu_hovered = False
        self._settings_menu_hide_timer = QTimer(self)
        self._settings_menu_hide_timer.setSingleShot(True)
        self._settings_menu_hide_timer.timeout.connect(self._maybe_hide_settings_hover_menu)
        self.settings_hover_menu.hide()
        self._settings_btn_hover_filter = SettingsHoverEventFilter(self, self.btn_settings, is_menu=False)
        self._settings_menu_hover_filter = SettingsHoverEventFilter(self, self.settings_hover_menu, is_menu=True)
        self.btn_settings.installEventFilter(self._settings_btn_hover_filter)
        self.settings_hover_menu.installEventFilter(self._settings_menu_hover_filter)
        self._update_settings_hover_menu_position()

    def _update_settings_hover_menu_position(self):
        if not hasattr(self, 'settings_hover_menu') or not hasattr(self, 'btn_settings'):
            return
        self.settings_hover_menu.adjustSize()
        menu_w = self.settings_hover_menu.width()
        menu_h = self.settings_hover_menu.height()

        btn = self.btn_settings
        x = btn.x() + int((btn.width() - menu_w) / 2)
        y = btn.y() - int(menu_h * 0.65)
        x = max(10, min(x, self.central_widget.width() - menu_w - 10))
        y = max(10, y)
        self.settings_hover_menu.move(x, y)

    def _show_settings_hover_menu(self):
        if not hasattr(self, 'settings_hover_menu'):
            return
        if hasattr(self, '_settings_menu_hide_timer'):
            self._settings_menu_hide_timer.stop()
        self._update_settings_hover_menu_position()
        self.settings_hover_menu.raise_()
        self.settings_hover_menu.show()

    def _schedule_hide_settings_hover_menu(self):
        if not hasattr(self, '_settings_menu_hide_timer'):
            return
        self._settings_menu_hide_timer.start(250)

    def _maybe_hide_settings_hover_menu(self):
        if not hasattr(self, 'settings_hover_menu'):
            return
        if self._settings_menu_hovered:
            return
        if self.btn_settings.underMouse() or self.settings_hover_menu.underMouse():
            return
        self.settings_hover_menu.hide()
    
    def _setup_active_counter(self):
        """Setup active tool counter display."""
        self.active_counter = MovableLabel(self.central_widget)
        self.active_counter.setObjectName("active_counter")
        self.active_counter.setText("0")
        self.active_counter.setGeometry(600, 80, 80, 60)
        self.active_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.active_counter_base_font = 48
        self.active_counter.setStyleSheet("""
            QLabel {
                color: #00F3FF;
                font-size: 48px;
                font-weight: bold;
                background: transparent;
            }
        """)
        self.active_counter.raise_()
        self.all_buttons['active_counter'] = self.active_counter
        
        # DEXTER ARM HUD Title (Movable)
        self.title_label = MovableLabel(self.central_widget)
        self.title_label.setObjectName("title_label")
        self.title_label.setText("DEXTER ARM HUD")
        self.title_label.setGeometry(400, 300, 480, 100)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label_base_font = 36
        self.title_label_base_padding = 20
        self.title_label_base_border = 2
        self.title_label.setStyleSheet("""
            QLabel {
                color: #00F3FF;
                font-size: 36px;
                font-weight: bold;
                background: rgba(0, 0, 0, 150);
                border: 2px solid #00F3FF;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        self.title_label.raise_()
        self.all_buttons['title_label'] = self.title_label
        
        # Status Label (Hidden by default, used for Edit Mode messages)
        self.status_label = QLabel(self.central_widget)
        self.status_label.setObjectName("status_label")
        self.status_label.setGeometry(400, 50, 480, 50) # Top center
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        
        print("[DEBUG] Active counter and labels created")
    
    def _update_active_count(self):
        """Update active process counter — work moved to ProcessManager background scan."""
        pass
        pass
    
    def _launch_button(self, button_name: str):
        """Launch or kill a main button command (toggle behavior)."""
        # Check if already running
        if self.process_manager.is_running(button_name):
            print(f"[INFO] Stopping process: {button_name}")
            self.process_manager.kill_process(button_name)
        else:
            config = self.config.get_button(button_name)
            if config:
                action = config.get('action')
                if self._handle_action(action):
                    return
                command = config.get('command')
                if command and "ros2 launch dexter_arm_hardware hardware_bringup.launch.py" in command:
                    self._open_hardware_full_window()
                    return
                use_terminal = config.get('terminal', True)
                display_name = config.get('hover_text') or button_name
                print(f"[INFO] Starting process: {button_name}")
                self.process_manager.launch_command(button_name, command, use_terminal, display_name=display_name)
    
    
    def _launch_combo(self, combo_name: str):
        """Launch or kill a combo button command (toggle behavior)."""
        if self.process_manager.is_running(combo_name):
            print(f"[INFO] Stopping combo: {combo_name}")
            self.process_manager.kill_process(combo_name)
        else:
            config = self.config.get_combo(combo_name)
            if config:
                action = config.get('action')
                if self._handle_action(action):
                    return
                command = config.get('command')
                if command and "ros2 launch dexter_arm_hardware hardware_bringup.launch.py" in command:
                    self._open_hardware_full_window()
                    return
                use_terminal = config.get('terminal', True)
                display_name = config.get('hover_text') or combo_name
                print(f"[INFO] Starting combo: {combo_name}")
                self.process_manager.launch_command(combo_name, command, use_terminal, display_name=display_name)
    
    
    def _launch_utility(self, utility_name: str):
        """Launch or kill a utility command (toggle behavior)."""
        if self.process_manager.is_running(utility_name):
            print(f"[INFO] Stopping utility: {utility_name}")
            self.process_manager.kill_process(utility_name)
        else:
            config = self.config.get_utility(utility_name)
            if config:
                action = config.get('action')
                if self._handle_action(action):
                    return
                command = config.get('command')
                use_terminal = config.get('terminal', True)
                display_name = config.get('hover_text') or utility_name
                print(f"[INFO] Starting utility: {utility_name}")
                self.process_manager.launch_command(utility_name, command, use_terminal, display_name=display_name)

    def _handle_action(self, action: str) -> bool:
        """Handle configured action name. Returns True if handled."""
        if not action:
            return False
        if action == 'firmware_dialog':
            self._open_firmware_dialog()
            return True
        if action == 'open_kill_processes':
            self._open_kill_process_window()
            return True
        if action == 'open_hardware_full_window':
            self._open_hardware_full_window()
            return True
        if action == 'open_waypoint_generator':
            self._open_waypoint_generator()
            return True
        if action == 'open_waypoint_visualizer':
            self._open_waypoint_visualizer()
            return True
        if action == 'open_system_monitor':
            self._open_system_monitor()
            return True
        if action == 'open_trajectory_generation':
            self._open_trajectory_generation_window()
            return True
        if action == 'open_trajectory_system':
            self._open_trajectory_system_window()
            return True
        return False
    
    def _kill_all_processes(self):
        """Open kill process workflow window."""
        self._open_kill_process_window()

    def _open_kill_process_window(self):
        """Open non-modal kill process workflow window."""
        if self.kill_process_window is None:
            esp32_cfg = self.config.get_esp32_config()
            self.kill_process_window = KillProcessWindow(
                process_manager=self.process_manager,
                serial_port=esp32_cfg.get('port', '/dev/ttyUSB0'),
                parent=self,
            )
            self.kill_process_window.destroyed.connect(
                lambda: setattr(self, 'kill_process_window', None)
            )

        self.kill_process_window.show()
        self.kill_process_window.raise_()
        self.kill_process_window.activateWindow()
    
    def _open_system_monitor(self):
        """Open non-modal system monitor window."""
        if self.system_monitor_window is None:
            workspace = self.config.get_workspace()
            self.system_monitor_window = SystemMonitorWindow(
                process_manager=self.process_manager,
                workspace_dir=workspace,
                active_apps_provider=self._get_all_active_apps,
                parent=self,
            )
            self.system_monitor_window.destroyed.connect(
                lambda: setattr(self, 'system_monitor_window', None)
            )

        self.system_monitor_window.show()
        self.system_monitor_window.raise_()
        self.system_monitor_window.activateWindow()
    
    def _open_firmware_dialog(self):
        """Open firmware upload window as a movable non-modal panel."""
        if self.firmware_dialog_window is None:
            workspace = self.config.get_workspace()
            esp32_cfg = self.config.get_esp32_config()
            self.firmware_dialog_window = FirmwareDialog(
                workspace,
                esp32_cfg.get('port', '/dev/ttyUSB0'),
                parent=self,
            )
            self.firmware_dialog_window.destroyed.connect(
                lambda: setattr(self, 'firmware_dialog_window', None)
            )

        self.firmware_dialog_window.show()
        self.firmware_dialog_window.raise_()
        self.firmware_dialog_window.activateWindow()

    def _open_hardware_full_window(self):
        """Open hardware full-system launch window."""
        if self.hardware_full_window is None:
            workspace = self.config.get_workspace()
            microros_workspace = self.config.get_microros_workspace()
            esp32_cfg = self.config.get_esp32_config()
            self.hardware_full_window = HardwareFullSystemWindow(
                process_manager=self.process_manager,
                workspace_dir=workspace,
                microros_workspace=microros_workspace,
                serial_port=esp32_cfg.get('port', '/dev/ttyUSB0'),
                serial_baud=esp32_cfg.get('baud', 115200),
                parent=self,
            )
            self.hardware_full_window.destroyed.connect(
                lambda: setattr(self, 'hardware_full_window', None)
            )

        self.hardware_full_window.show()
        self.hardware_full_window.raise_()
        self.hardware_full_window.activateWindow()
    
    def _get_ros_node_list(self) -> list[str]:
        """Return current ROS node list (sync fallback — prefer async version)."""
        import shlex
        import subprocess as sp

        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        workspace = str(self.config.get_workspace())
        command = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(workspace)} && "
            "source install/setup.bash && "
            "ros2 node list"
        )

        result = sp.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if stderr:
                print(f"[DEBUG] ros2 node list failed: {stderr}")
            return []

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _get_ros_node_list_async(self, callback) -> None:
        """Fetch ROS node list via QProcess (non-blocking).

        Args:
            callback: Called with list[str] of node names when done.
        """
        import shlex

        ros_setup = f"/opt/ros/{self.process_manager.ros_distro}/setup.bash"
        workspace = str(self.config.get_workspace())
        command = (
            f"source {shlex.quote(ros_setup)} && "
            f"cd {shlex.quote(workspace)} && "
            "source install/setup.bash && "
            "ros2 node list"
        )

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        timed_out = {"value": False}

        def on_finished():
            timeout_timer.stop()
            if timed_out["value"]:
                return  # Already handled by timeout
            output = proc.readAllStandardOutput().data().decode('utf-8', errors='replace')
            nodes = [line.strip() for line in output.splitlines() if line.strip()]
            proc.deleteLater()
            callback(nodes)

        def on_timeout():
            timed_out["value"] = True
            print("[WARN] ros2 node list timed out (5s), treating as no nodes")
            proc.kill()
            proc.deleteLater()
            callback([])

        proc.finished.connect(on_finished)
        proc.start("bash", ["-lc", command])

        # Timeout so the UI doesn't hang forever if ros2 daemon is down
        timeout_timer = QTimer(self)
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(on_timeout)
        timeout_timer.start(5000)

        # Store refs so they don't get GC'd
        self._node_list_proc = proc
        self._node_list_timeout = timeout_timer

    def _check_trajectory_prerequisites(self) -> tuple[bool, list[str]]:
        """Check required ROS nodes for trajectory capture workflow (sync)."""
        nodes = self._get_ros_node_list()
        return self._evaluate_prerequisites(nodes)

    def _check_trajectory_prerequisites_async(self, callback) -> None:
        """Check prerequisites without blocking the UI thread.

        Args:
            callback: Called with (all_met: bool, missing: list[str]).
        """
        def on_nodes(nodes):
            result = self._evaluate_prerequisites(nodes)
            callback(*result)

        self._get_ros_node_list_async(on_nodes)

    @staticmethod
    def _evaluate_prerequisites(nodes: list[str]) -> tuple[bool, list[str]]:
        """Evaluate node list against required prerequisites."""
        has_rsp = any("robot_state_publisher" in node for node in nodes)
        has_move_group = any("move_group" in node for node in nodes)

        missing = []
        if not has_rsp:
            missing.append("robot_state_publisher (TF broadcaster)")
        if not has_move_group:
            missing.append("move_group (MoveIt planning)")

        return len(missing) == 0, missing

    def _ensure_button_running(self, button_name: str) -> bool:
        """Start a launch target if needed, but never toggle-stop it."""
        if self.process_manager.is_running(button_name):
            return True

        config = self.config.get_button(button_name)
        if not config:
            config = self.config.get_combo(button_name)

        if not config:
            fallback_map = {
                "gazebo": {
                    "command": "ros2 launch dexter_arm_gazebo gazebo.launch.py",
                    "terminal": False,
                    "display_name": "Gazebo Simulation",
                },
                "sim": {
                    "command": "ros2 launch dexter_arm_gazebo gazebo_bringup.launch.py",
                    "terminal": False,
                    "display_name": "Full Simulation",
                },
                "gazebo_full": {
                    "command": "ros2 launch dexter_arm_gazebo gazebo_bringup.launch.py",
                    "terminal": False,
                    "display_name": "Full Simulation",
                },
            }
            fallback = fallback_map.get(button_name)
            if not fallback:
                print(f"[WARN] Missing button config: {button_name}")
                return False

            print(f"[INFO] Using fallback launch config for: {button_name}")
            launched = self.process_manager.launch_command(
                button_name,
                fallback["command"],
                fallback["terminal"],
                display_name=fallback["display_name"],
            )
            if not launched:
                print(f"[WARN] Failed to launch fallback process: {button_name}")
            return launched

        action = config.get('action')
        if self._handle_action(action):
            return True

        command = config.get('command')
        if not command:
            print(f"[WARN] Missing command for button: {button_name}")
            return False

        use_terminal = config.get('terminal', True)
        display_name = config.get('hover_text') or button_name
        launched = self.process_manager.launch_command(
            button_name,
            command,
            use_terminal,
            display_name=display_name,
        )
        if not launched:
            print(f"[WARN] Failed to launch button process: {button_name}")
        return launched

    def _open_trajectory_system_window(self):
        """Open trajectory teach & repeat system window with async prerequisite check."""
        # Show a brief "checking..." status so the user sees something immediately
        print("[INFO] Checking trajectory prerequisites (async)...")
        self._check_trajectory_prerequisites_async(self._on_trajectory_prereqs_checked)

    def _on_trajectory_prereqs_checked(self, all_met: bool, missing: list) -> None:
        """Callback after async prerequisite check completes."""
        if all_met:
            self._open_trajectory_system_window_internal()
            return

        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Trajectory System - Requirements")
        msg.setIcon(QMessageBox.Icon.Information)

        missing_text = "\n".join(f"  • {item}" for item in missing)
        msg.setText(
            f"To teach and execute trajectories, you need:\n\n"
            f"{missing_text}\n\n"
            f"Please launch one of the following first:"
        )

        gazebo_btn = msg.addButton("🎮  Gazebo Simulation", QMessageBox.ButtonRole.AcceptRole)
        hardware_btn = msg.addButton("⚙  Full Hardware", QMessageBox.ButtonRole.ApplyRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(cancel_btn)

        msg.exec()
        clicked = msg.clickedButton()

        if clicked == gazebo_btn:
            print("[INFO] User selected Full Simulation from trajectory dialog")
            self._open_launch_terminal_window(
                "Full Simulation",
                "ros2 launch dexter_arm_gazebo gazebo_bringup.launch.py",
            )
            window_key = "full_simulation"
            if window_key in self.launch_terminal_windows:
                self.launch_terminal_windows[window_key]._start_process()
            self._open_trajectory_system_window_internal()
            return
        if clicked == hardware_btn:
            print("[INFO] User selected Hardware from trajectory dialog")
            self._open_hardware_full_window()
            if (
                self.hardware_full_window is not None
                and not self.process_manager.is_running("hardware_full_system")
            ):
                self.hardware_full_window._launch_full_system()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(8000, self._open_trajectory_with_retry)
            return
    
    def _open_trajectory_with_retry(self):
        """Re-check prerequisites asynchronously after waiting for systems to initialize."""

        def on_check(all_met, missing):
            if all_met:
                print("[INFO] Prerequisites now met, opening trajectory window")
                self._open_trajectory_system_window_internal()
            else:
                missing_text = ", ".join(missing)
                print(f"[WARN] Prerequisites still not met: {missing_text}")
                print("[INFO] Opening trajectory dialog again for manual selection")
                self._open_trajectory_system_window()

        self._check_trajectory_prerequisites_async(on_check)
    
    def _open_trajectory_system_window_internal(self):
        """Internal method to open trajectory window (assumes prerequisites are met)."""
        if self.trajectory_system_window is None:
            workspace = self.config.get_workspace()
            self.trajectory_system_window = TrajectorySystemWindow(
                process_manager=self.process_manager,
                workspace_dir=workspace,
                parent=self,
            )
            self.trajectory_system_window.destroyed.connect(
                lambda: setattr(self, 'trajectory_system_window', None)
            )

        self.trajectory_system_window.show()
        self.trajectory_system_window.raise_()
        self.trajectory_system_window.activateWindow()

    def _open_waypoint_generator(self):
        """Open trajectory generation window."""
        self._open_trajectory_generation_window()
    
    def _open_trajectory_generation_window(self):
        """Open trajectory generation window (Trajectory System)."""
        if self.trajectory_generation_window is None:
            workspace = self.config.get_workspace()
            self.trajectory_generation_window = TrajectoryGenerationWindow(
                workspace_dir=workspace,
                parent=self,
            )
            self.trajectory_generation_window.destroyed.connect(
                lambda: setattr(self, 'trajectory_generation_window', None)
            )

        self.trajectory_generation_window.show()
        self.trajectory_generation_window.raise_()
        self.trajectory_generation_window.activateWindow()
    
    def _open_waypoint_visualizer(self):
        """Open trajectory visualization window."""
        if self.trajectory_visualization_window is None:
            workspace = self.config.get_workspace()
            self.trajectory_visualization_window = TrajectoryVisualizationWindow(
                process_manager=self.process_manager,
                workspace_dir=workspace,
                parent=self,
            )
            self.trajectory_visualization_window.destroyed.connect(
                lambda: setattr(self, 'trajectory_visualization_window', None)
            )

        self.trajectory_visualization_window.show()
        self.trajectory_visualization_window.raise_()
        self.trajectory_visualization_window.activateWindow()
    
    def _open_settings(self):
        """Open the Settings as a separate window."""
        print("[DEBUG] _open_settings called")
        
        # Check if settings window already exists
        if self.settings_window is None:
            print("[DEBUG] Creating new SettingsWindow")
            self.settings_window = SettingsDialog(self, self.config)
            self.settings_window.setWindowTitle("Dashboard Settings")
            self.settings_window.editModeToggled.connect(self.set_edit_mode_enabled)
            self.settings_window.configChanged.connect(self._refresh_components)
            self.settings_window.destroyed.connect(
                lambda: setattr(self, 'settings_window', None)
            )
        else:
            print("[DEBUG] Using existing SettingsWindow")
        
        print("[DEBUG] Showing SettingsWindow")
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _refresh_from_settings_close(self):
        """Reload config and refresh elements after settings dialog closes."""
        self.config.reload_config()
        self.opacity_defaults = self.config.get_opacity_defaults()
        if hasattr(self, 'video_bg_opacity'):
            video_opacity = float(self.opacity_defaults.get('video', 0.7))
            video_opacity = max(0.05, min(1.0, video_opacity))
            self.video_bg_opacity.setOpacity(video_opacity)
        if hasattr(self, '_apply_background_settings'):
            self._apply_background_settings()
        self._refresh_custom_icons()
        self._load_icon_groups()
        self._refresh_components()
        self._apply_layer_order()

    def _refresh_custom_icons(self):
        """Add or remove custom icons to match config."""
        custom_icons = self.config.get_custom_icons()
        desired_names = {c.get('name') for c in custom_icons if c.get('name')}

        # Remove icons no longer in config
        for name in list(self.custom_icon_widgets.keys()):
            if name not in desired_names:
                widget = self.custom_icon_widgets.pop(name)
                widget.hide()
                widget.deleteLater()
                self.all_buttons.pop(name, None)
                self.custom_icon_layers.pop(name, None)
                self._layout_normalized.pop(name, None)

        # Add missing icons
        for icon_data in custom_icons:
            name = icon_data.get('name')
            if not name or name in self.all_buttons:
                continue
            filename = icon_data.get('file')
            if not filename:
                continue

            path = self.icons_dir / filename
            if not path.exists():
                continue

            lbl = MovableLabel(self.central_widget, enable_glow=True)
            lbl.setObjectName(name)
            pixmap = QPixmap(str(path))
            lbl.setPixmap(pixmap)

            x = int(icon_data.get('x', 200))
            y = int(icon_data.get('y', 200))
            w = int(icon_data.get('width', pixmap.width()))
            h = int(icon_data.get('height', pixmap.height()))
            lbl.setGeometry(x, y, w, h)

            opacity = icon_data.get('opacity', self.opacity_defaults.get('icons', 1.0))
            lbl.opacity_effect.setOpacity(float(opacity))

            lbl.positionChanged.connect(self.save_layout)
            self.all_buttons[name] = lbl
            self.custom_icon_widgets[name] = lbl
            self.custom_icon_layers[name] = icon_data.get('layer') or self._infer_layer_from_file(filename)
            self._layout_normalized[name] = self._to_normalized_rect(x, y, w, h)
            lbl.raise_()

    def _infer_layer_from_file(self, filename):
        parts = str(filename).split("/")
        if len(parts) >= 2:
            return parts[0]
        return "layer_1"

    def _load_icon_groups(self):
        """Attach hover/click behaviors to icon groups."""
        # Restore any previous wake_up base opacity overrides
        if self.group_wake_state:
            for key, prev in list(self.group_wake_state.items()):
                widget = prev.get('widget')
                base_opacity = prev.get('base_opacity')
                if widget and hasattr(widget, 'opacity_effect') and base_opacity is not None:
                    widget.opacity_effect.setOpacity(base_opacity)
                if widget and hasattr(widget, 'base_opacity') and base_opacity is not None:
                    widget.base_opacity = base_opacity
            self.group_wake_state.clear()

        # Clear existing overlays and filters
        for group_id, label in self.icon_group_overlays.items():
            label.hide()
            label.deleteLater()
        self.icon_group_overlays = {}

        for group_id, filter_obj in self.icon_group_filters.items():
            main_widget = filter_obj.main_widget
            main_widget.removeEventFilter(filter_obj)
        self.icon_group_filters = {}

        self.icon_groups = self.config.get_icon_groups()
        for group in self.icon_groups:
            main_icon = group.get('main_icon')
            if not main_icon or main_icon not in self.all_buttons:
                continue

            group_id = group.get('name') or main_icon
            label = QLabel(self.central_widget)
            label.setObjectName(f"group_hover_{group_id}")
            label.setStyleSheet(
                "QLabel { color: #00F3FF; font-size: 13px; font-weight: bold; "
                "background: rgba(0, 5, 20, 210); border: 1px solid #00F3FF; "
                "border-radius: 4px; padding: 5px 12px; letter-spacing: 1px; }"
            )
            label.hide()
            self.icon_group_overlays[group_id] = label

            main_widget = self.all_buttons[main_icon]
            filter_obj = IconGroupEventFilter(self, group, main_widget)
            main_widget.installEventFilter(filter_obj)
            self.icon_group_filters[group_id] = filter_obj

            effects = group.get('hover_effects') or []
            if any("wake_up" in e for e in effects):
                self._apply_group_wake_opacity(group, hovered=False)

    def _show_group_overlay(self, group, main_widget):
        group_id = group.get('name') or group.get('main_icon')
        label = self.icon_group_overlays.get(group_id)
        if not label:
            return
        hover_text = group.get('hover_text', '')
        if not hover_text:
            label.hide()
            return
        label.setText(hover_text)
        label.adjustSize()

        # Position above the icon, centered horizontally
        x = main_widget.x() + int((main_widget.width() - label.width()) / 2)
        y = main_widget.y() - label.height() - 12
        # Clamp so it stays within the central widget
        x = max(10, min(x, self.central_widget.width() - label.width() - 10))
        y = max(10, y)  # If no room above, push to 10px from top
        label.move(x, y)
        label.raise_()
        label.show()

    def _hide_group_overlay(self, group):
        group_id = group.get('name') or group.get('main_icon')
        label = self.icon_group_overlays.get(group_id)
        if label:
            label.hide()

    def _set_group_highlight(self, group, enabled):
        effects = group.get('hover_effects') or ["glow"]
        if isinstance(effects, str):
            effects = [effects]
        has_glow = any("glow" in e for e in effects)
        has_wake = any("wake_up" in e for e in effects)
        if not has_glow:
            if has_wake:
                self._apply_group_wake_opacity(group, hovered=enabled)
            return

        glow_radius = group.get('glow_radius', 25)
        glow_color = group.get('glow_color')

        items = group.get('items') or group.get('group_items') or []
        for item in items:
            item_type = "icon"
            item_name = item
            if ":" in item:
                item_type, item_name = item.split(":", 1)

            if item_type == "connector":
                for conn in self.connectors:
                    if conn.name == item_name:
                        conn.set_group_highlight_config(enabled, glow_radius, glow_color)
                continue

            widget = self.all_buttons.get(item_name)
            if not widget:
                continue

            key = (id(widget), item_name)
            if enabled:
                if key not in self.group_highlight_state:
                    self.group_highlight_state[key] = {
                        'opacity': widget.opacity_effect.opacity() if hasattr(widget, 'opacity_effect') else None,
                        'glow': widget.glowRadius if hasattr(widget, 'glowRadius') else None,
                        'glow_color': widget.glow_effect.color().name() if hasattr(widget, 'glow_effect') else None
                    }
                if hasattr(widget, 'glowRadius'):
                    widget.glowRadius = float(glow_radius)
                if hasattr(widget, 'glow_effect') and glow_color:
                    widget.glow_effect.setColor(QColor(glow_color))
                if hasattr(widget, 'opacity_effect'):
                    widget.opacity_effect.setOpacity(0.999)
            else:
                prev = self.group_highlight_state.pop(key, {})
                if hasattr(widget, 'glowRadius') and prev.get('glow') is not None:
                    widget.glowRadius = prev.get('glow')
                if hasattr(widget, 'glow_effect') and prev.get('glow_color'):
                    widget.glow_effect.setColor(QColor(prev.get('glow_color')))
                if hasattr(widget, 'opacity_effect') and prev.get('opacity') is not None:
                    widget.opacity_effect.setOpacity(prev.get('opacity'))

        if has_wake:
            # Ensure wake_up opacity is applied after any glow restore
            self._apply_group_wake_opacity(group, hovered=enabled)

    def _apply_group_wake_opacity(self, group, hovered=False):
        wake_opacity = float(group.get('wake_opacity', 60)) / 100.0
        target_opacity = 0.999 if hovered else wake_opacity
        items = group.get('items') or group.get('group_items') or []

        for item in items:
            item_type = "icon"
            item_name = item
            if ":" in item:
                item_type, item_name = item.split(":", 1)

            if item_type == "connector":
                for conn in self.connectors:
                    if conn.name == item_name:
                        conn.opacity_effect.setOpacity(target_opacity)
                continue

            widget = self.all_buttons.get(item_name)
            if widget and hasattr(widget, 'opacity_effect'):
                # On initial wake state, override base opacity for grouped icons only
                if not hovered and hasattr(widget, 'base_opacity'):
                    key = (id(widget), item_name)
                    if key not in self.group_wake_state:
                        self.group_wake_state[key] = {
                            'widget': widget,
                            'base_opacity': getattr(widget, 'base_opacity', None)
                        }
                    widget.base_opacity = wake_opacity
                widget.opacity_effect.setOpacity(target_opacity)

    def _execute_group_command(self, group):
        command = group.get('command')
        action  = group.get('action', '')
        group_id = group.get('name') or group.get('main_icon') or "group"
        display_name = group.get('hover_text') or group_id
        group_name_l = str(group.get('name', '')).strip().lower()
        main_icon_l = str(group.get('main_icon', '')).strip().lower()

        # ── configured actions ────────────────────────────────────────────────
        if self._handle_action(action):
            return

        if (
            "kill" in group_name_l
            and ("process" in group_name_l or "kill" in main_icon_l)
        ):
            self._open_kill_process_window()
            return

        # Backward-compatible fallback for legacy configs that define waypoint
        # groups with empty command/action fields.
        if not action and not command:
            if (
                ("system" in group_name_l and "monitor" in group_name_l)
                or ("sys" in main_icon_l and "monitor" in main_icon_l)
            ):
                self._open_system_monitor()
                return
            if (
                "trajectory" in group_name_l
                and ("system" in group_name_l or "trajectory" in main_icon_l)
            ):
                self._open_trajectory_system_window()
                return
            if (
                "waypoint" in group_name_l
                and ("generator" in group_name_l or "wg" in main_icon_l)
            ):
                self._open_waypoint_generator()
                return
            if (
                "waypoint" in group_name_l
                and (
                    "visualizer" in group_name_l
                    or "vizualizer" in group_name_l
                    or "viz" in group_name_l
                    or "wv" in main_icon_l
                )
            ):
                self._open_waypoint_visualizer()
                return

        # Trajectory system now runs via dedicated UI window
        # rather than launching in a terminal.
        if command and "ros2 launch dexter_arm_trajectory" in command:
            self._open_trajectory_system_window()
            return

        # Hardware full-system workflow now runs via dedicated UI window
        # rather than launching hardware bringup directly.
        if command and "ros2 launch dexter_arm_hardware hardware_bringup.launch.py" in command:
            self._open_hardware_full_window()
            return

        if not command:
            return

        # If show_output is set, run inline and show result in an alert dialog
        if group.get('show_output', False):
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                output_lines = []
                if result.stdout.strip():
                    output_lines.append(result.stdout.strip())
                if result.stderr.strip():
                    output_lines.append(result.stderr.strip())
                output_text = '\n'.join(output_lines) if output_lines else 'Done — no output.'

                dlg = QMessageBox(self)
                dlg.setWindowTitle(display_name)
                dlg.setText(output_text)
                dlg.setIcon(QMessageBox.Icon.Information)
                dlg.setStyleSheet(
                    "QMessageBox { background-color: #000a1a; color: #00F3FF; font-family: monospace; }"
                    "QLabel { color: #00F3FF; font-size: 13px; font-family: monospace; }"
                    "QPushButton { background: #001a2e; color: #00F3FF; border: 1px solid #00F3FF; "
                    "border-radius: 4px; padding: 4px 16px; }"
                    "QPushButton:hover { background: #003355; }"
                )
                dlg.exec()
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, display_name, "Command timed out after 30 seconds.")
            except Exception as e:
                QMessageBox.critical(self, display_name, f"Error running command:\n{e}")
            return

        self.group_launch_counter += 1
        process_name = f"group_{group_id}_{self.group_launch_counter}"
        
        # Check if this is a launch system command that should use HUD terminal
        if self._should_use_hud_terminal(command):
            self._open_launch_terminal_window(display_name, command)
            return
        
        # Fallback: launch in separate terminal (for backward compatibility)
        launched = self.process_manager.launch_command(process_name, command, True, display_name=display_name)
        if not launched:
            print(f"[WARN] Failed to launch group command: {command}")
    
    def _get_all_active_apps(self) -> list:
        """Unified list of every active app / window launched from the dashboard.

        Sources
        -------
        1. process_manager tracked processes  (QProcess-based terminal launches)
        2. HUD terminal launch windows        (RViz, Gazebo, MoveIt, etc.)
        3. Dashboard tool windows             (any  self.*_window  attribute)

        Automatically discovers new windows — no hard-coded list needed.
        """
        apps: list = []
        seen: set = set()

        def _add(name: str) -> None:
            if name and name not in seen:
                apps.append(name)
                seen.add(name)

        # 1. Process-manager tracked processes
        for name in self.process_manager.get_active_processes():
            _add(name)

        # 2. HUD terminal windows (RViz, Gazebo, MoveIt launches via groups)
        for key, window in list(self.launch_terminal_windows.items()):
            if window is not None and window.isVisible():
                _add(window.windowTitle() or key)

        # 3. Auto-discover all dashboard tool windows (*_window attrs)
        for attr_name, obj in self.__dict__.items():
            if not attr_name.endswith('_window'):
                continue
            if obj is None:
                continue
            if not isinstance(obj, QWidget):
                continue
            if not obj.isVisible():
                continue
            title = (
                obj.windowTitle()
                or attr_name.replace('_window', '').replace('_', ' ').title()
            )
            _add(title)

        return apps

    def _should_use_hud_terminal(self, command: str) -> bool:
        """
        Check if the command should use the HUD terminal window.
        
        Args:
            command: The command to check
            
        Returns:
            True if HUD terminal should be used
        """
        if not command:
            return False
        
        # Check if it's a launch system command (rviz, gazebo, moveit, etc.)
        launch_patterns = [
            'ros2 launch dexter_arm_description',
            'ros2 launch dexter_arm_gazebo',
            'ros2 launch dexter_arm_moveit_config',
        ]
        
        return any(pattern in command for pattern in launch_patterns)
    
    def _open_launch_terminal_window(self, title: str, command: str):
        """
        Open a HUD terminal window for the launch command.
        
        Args:
            title: Window title
            command: ROS launch command
        """
        # Use existing window if already open for this command type
        window_key = title.lower().replace(' ', '_')
        
        if window_key in self.launch_terminal_windows:
            window = self.launch_terminal_windows[window_key]
            if window.isVisible():
                window.raise_()
                window.activateWindow()
                return
            else:
                # Window was closed, remove from dict
                del self.launch_terminal_windows[window_key]
        
        # Get workspace from config
        workspace = self.config.get_workspace()
        
        # Create new HUD terminal window
        window = LaunchTerminalWindow(
            title=title,
            command=command,
            process_manager=self.process_manager,
            workspace_dir=workspace,
            parent=self
        )
        
        # Connect close signal
        window.destroyed.connect(lambda: self._on_launch_window_closed(window_key))
        
        # Store and show
        self.launch_terminal_windows[window_key] = window
        window.show()
        
        print(f"[INFO] Opened HUD terminal window: {title}")
    
    def _on_launch_window_closed(self, window_key: str):
        """
        Handle launch window closed.
        
        Args:
            window_key: Key of the closed window
        """
        if window_key in self.launch_terminal_windows:
            del self.launch_terminal_windows[window_key]
            print(f"[INFO] Closed HUD terminal window: {window_key}")
    
    def _refresh_components(self):
        """Reload connectors and panels from config."""
        print("[INFO] Refreshing dynamic components")
        self.config.reload_config()
        self.opacity_defaults = self.config.get_opacity_defaults()
        if hasattr(self, '_apply_background_settings'):
            self._apply_background_settings()
        self._refresh_custom_icons()
        self._load_icon_groups()
        # Clear existing dynamic components
        if hasattr(self, 'dynamic_widgets'):
            for widget in self.dynamic_widgets:
                widget.hide()  # Hide immediately to avoid blocking
                widget.deleteLater()
        self.dynamic_widgets = []
        self.connectors = []
        self.display_panels = []
        self.hud_title_banner = None
        
        self._load_dynamic_components()
        if self._layout_ready:
            self._apply_scaled_layout()
        self._apply_layer_order()
        self._load_icon_groups()
        if hasattr(self, 'edit_mode') and self.edit_mode:
            scale, offset_x, offset_y = self._get_scale_and_offset()
            self._apply_edit_mode_state(scale, offset_x, offset_y)
            if self.edit_connectors_mode:
                for conn in self.connectors:
                    conn.set_locked(False)
                    if hasattr(conn, 'raise_hit_layer'):
                        conn.raise_hit_layer()

    def _load_dynamic_components(self):
        """Load and render connectors and panels."""
        if not hasattr(self, 'dynamic_widgets'):
            self.dynamic_widgets = []

        window_config = getattr(self.config, 'config', {}).get('window', {})
        fallback_width = window_config.get('width', self.base_width)
        fallback_height = window_config.get('height', self.base_height)

        # Load Connectors
        # Load Connectors
        try:
            connectors = self.config.get_connectors()
            for index, conn_data in enumerate(connectors):
                points = conn_data.get('points')
                points_pct = conn_data.get('points_pct')

                if not points and not points_pct:
                    start = conn_data.get('start', [0, 0])
                    end = conn_data.get('end', [100, 100])
                    points = [start, end]

                normalized = None
                print(f"[LOAD_CONN] points_pct={points_pct[0] if points_pct else None}")

                # Always prefer points_pct — it is the authoritative normalised source.
                # Re-normalising from raw pixel points is unreliable when the
                # window size at close differs from the size at the last
                # _save_connectors_state call.
                if points_pct:
                    print(f"[LOAD_CONN] Using points_pct")
                    normalized = points_pct
                elif points:
                    # Points without points_pct are assumed to be on the base canvas
                    print(f"[LOAD_CONN] Normalizing from pixel points only (using base canvas {self.base_width}x{self.base_height})")
                    normalized = [
                        [p[0] / self.base_width, p[1] / self.base_height]
                        for p in points
                    ]
                    print(f"[LOAD_CONN] Normalized[0]={normalized[0]}")
                else:
                    print(f"[LOAD_CONN] Using default normalized points")
                    normalized = [[0.078125, 0.1388888], [0.234375, 0.416666]]

                conn_name = conn_data.get('name') or f"connector_{index + 1}"
                conn = ConnectorLine(self.central_widget, points_normalized=normalized,
                                     line_color=conn_data.get('line_color', "#00FFFF"),
                                     glow_color=conn_data.get('glow_color', "#00FFFF"),
                                     thickness=conn_data.get('thickness', 2.0),
                                     glow_radius=conn_data.get('glow_radius', 10.0),
                                     base_width=self.base_width,
                                     base_height=self.base_height,
                                     name=conn_name)
                default_conn_opacity = float(self.opacity_defaults.get('connectors', 1.0))
                conn_opacity = conn_data.get('opacity', default_conn_opacity)
                conn.opacity_effect.setOpacity(float(conn_opacity))
                conn.setGeometry(0, 0, self.central_widget.width(), self.central_widget.height())
                scale, offset_x, offset_y = self._get_scale_and_offset()
                # Set transform BEFORE show() to ensure first paint is correct
                conn.set_view_transform(scale, offset_x, offset_y, self.base_width, self.base_height)
                print(f"[CREATE_CONN] Created with transform: scale={scale:.3f}, offset=({offset_x:.1f},{offset_y:.1f})")
                conn.show()
                self.connectors.append(conn)
                self.dynamic_widgets.append(conn)

                locked_state = not self.edit_mode
                conn.set_locked(locked_state)
                if self.edit_mode:
                    conn.raise_()
                conn.configChanged.connect(self._save_connectors_state)
        except Exception as e:
            print(f"[ERROR] Failed to load connectors: {e}")

        # Load Display Panels
        try:
            panels = self.config.get_display_panels()
            print(f"[DEBUG] Loading {len(panels)} display panels from config")
            for i, panel_data in enumerate(panels):
                print(f"[DEBUG] Creating panel {i}: {panel_data.get('title', 'Untitled')} at ({panel_data.get('x', 100)}, {panel_data.get('y', 100)})")
                norm = self._extract_normalized_rect(panel_data, fallback_width, fallback_height)
                panel_source = panel_data.get('data_source', 'Static')
                panel = DisplayPanel(self.central_widget,
                                     title=panel_data.get('title', "Status"),
                                     value=panel_data.get('value', "Ready"),
                                     x=panel_data.get('x', 100),
                                     y=panel_data.get('y', 100),
                                     width=panel_data.get('width', 220),
                                     height=panel_data.get('height', 60),
                                     font_size=panel_data.get('font_size', 12),
                                     text_color=panel_data.get('text_color', "#00FFFF"),
                                     title_color=panel_data.get('title_color'),
                                     value_color=panel_data.get('value_color'),
                                     data_source=panel_source,
                                     subtitle_text=panel_data.get('subtitle_text', 'ROBOTIC MANIPULATION SYSTEM'),
                                     hover_text=panel_data.get('hover_text', ''),
                                     font_family=panel_data.get('font_family', 'Orbitron'),
                                     visible=panel_data.get('visible', True),
                                     launched_apps_provider=(
                                         self._get_all_active_apps
                                         if panel_source.lower() == 'launched apps' else None
                                     ))
                default_panel_opacity = float(self.opacity_defaults.get('panels', 0.8))
                panel_opacity = panel_data.get('opacity', default_panel_opacity)
                panel.opacity_effect.setOpacity(float(panel_opacity))
                if norm:
                    self._panel_normalized[panel] = norm
                    x, y, w, h = self._from_normalized_rect(norm)
                    panel.setGeometry(x, y, w, h)
                else:
                    panel.setGeometry(
                        panel_data.get('x', 100),
                        panel_data.get('y', 100),
                        panel_data.get('width', 220),
                        panel_data.get('height', 60)
                    )
                panel.show()
                self.display_panels.append(panel)
                self.dynamic_widgets.append(panel)
                locked_state = not self.edit_mode
                panel.set_locked(locked_state)
                
                # Track Title Banner panels for edit mode
                if panel_source == 'Title Banner':
                    self.hud_title_banner = panel
                
                # Connect resize/move signal to save
                panel.positionChanged.connect(self._save_panels_state)
                print(f"[DEBUG] Panel {i} created and shown at position ({panel.x()}, {panel.y()})")
        except Exception as e:
            print(f"[ERROR] Failed to load panels: {e}")
                
    def _save_connectors_state(self, force: bool = False):
        """Update config with current connector states."""
        if not self.isMaximized():
            return
        if self.edit_mode and not force:
            self._mark_layout_dirty()
            return
        new_list = []
        for w in self.dynamic_widgets:
            if isinstance(w, ConnectorLine):
                points_pct = [[p[0], p[1]] for p in w.points_normalized]
                pixel_points = w.get_pixel_points()
                new_list.append({
                    'name': w.name,
                    'points': [[p.x(), p.y()] for p in pixel_points],
                    'points_pct': points_pct,
                    'line_color': w.line_color.name(),
                    'glow_color': w.glow_color.name(),
                    'thickness': w.line_thickness,
                    'glow_radius': w.glow_radius,
                    'opacity': w.opacity_effect.opacity()
                })
        self.config.update_connectors(new_list)
        
    def _save_panels_state(self, force: bool = False):
        """Update config with current panel states."""
        if not self.isMaximized():
            return
        if self.edit_mode and not force:
            self._mark_layout_dirty()
            return
        new_list = []
        for w in self.dynamic_widgets:
            if isinstance(w, DisplayPanel):
                # Helper to get color string safely
                def get_col_name(c):
                    return c.name() if hasattr(c, 'name') else str(c)
                    
                norm = self._to_normalized_rect(w.x(), w.y(), w.width(), w.height())
                self._panel_normalized[w] = norm
                new_list.append({
                    'title': w.title_text, 
                    'value': w.static_value,
                    'current_value': w.current_value,
                    'x': w.x(),
                    'y': w.y(),
                    'width': w.width(),
                    'height': w.height(),
                    'x_pct': norm['x_pct'],
                    'y_pct': norm['y_pct'],
                    'w_pct': norm['w_pct'],
                    'h_pct': norm['h_pct'],
                    'font_size': w.font_size,
                    'title_color': get_col_name(w.title_label.palette().color(w.title_label.foregroundRole())),
                    'value_color': get_col_name(w.value_label.palette().color(w.value_label.foregroundRole())),
                    'data_source': w.data_source_key,
                    'opacity': w.opacity_effect.opacity(),
                    # Title Banner fields
                    'subtitle_text': getattr(w, 'subtitle_text', ''),
                    'hover_text': getattr(w, 'hover_text', ''),
                    'font_family': getattr(w, 'font_family', 'Orbitron'),
                    'visible': getattr(w, 'banner_visible', True)
                })
        self.config.update_panels(new_list)
    
    def _on_process_started(self, process_name: str):
        """Handle process started signal - update button state."""
        if process_name in self.all_buttons:
            button = self.all_buttons[process_name]
            if hasattr(button, 'set_active'):
                button.set_active(True)
                print(f"[DEBUG] Button '{process_name}' set to active state")
    
    def _on_process_finished(self, process_name: str, exit_code: int):
        """Handle process finished signal - update button state."""
        if process_name in self.all_buttons:
            button = self.all_buttons[process_name]
            if hasattr(button, 'set_active'):
                button.set_active(False)
                print(f"[DEBUG] Button '{process_name}' set to inactive state")
    
    def _on_process_error(self, process_name: str, error_message: str):
        """Handle process error signal."""
        print(f"[ERROR] Process '{process_name}' error: {error_message}")
        # Also clear button state on error
        if process_name in self.all_buttons:
            button = self.all_buttons[process_name]
            if hasattr(button, 'set_active'):
                button.set_active(False)
    
    def closeEvent(self, event):
        """Handle window close event."""
        print("[INFO] Closing dashboard...")
        # Ask to save current layout on dashboard close.
        if self.edit_mode or self._layout_dirty:
            decision = self._prompt_save_layout_changes("closing the dashboard")
            if decision == "cancel":
                event.ignore()
                return
            if decision == "discarded":
                # User chose not to save layout edits.
                pass
        elif not self._layout_discarded:
            # Persist non-edit-mode updates.
            self._save_all_layout(force=False)

        # Close non-modal utility windows first so their own close handlers run.
        aux_windows = [
            self.firmware_dialog_window,
            self.kill_process_window,
            self.system_monitor_window,
            self.hardware_full_window,
            self.trajectory_system_window,
            self.trajectory_generation_window,
            self.trajectory_visualization_window,
        ]
        for window in aux_windows:
            if window is None:
                continue
            if window.isVisible():
                window.close()
            # If any child rejects close (e.g., generator still running), abort shutdown.
            if window.isVisible():
                event.ignore()
                return
        
        if hasattr(self, 'video_bg'):
             self.video_bg.stop()
        self.process_manager.cleanup()
        event.accept()
