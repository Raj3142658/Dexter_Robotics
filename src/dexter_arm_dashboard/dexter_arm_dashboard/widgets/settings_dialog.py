
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                             QWidget, QLabel, QListWidget, QPushButton,
                             QLineEdit, QFormLayout, QComboBox, QSpinBox,
                             QDialogButtonBox, QMessageBox, QListWidgetItem,
                             QAbstractItemView, QCheckBox, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from pathlib import Path

class SettingsDialog(QDialog):
    """
    Settings dialog to manage dashboard components.
    Tabs: Welcome, Connectors, Display Panels, Icons, Icon Groups, Background.
    """
    
    configChanged = pyqtSignal()  # Emitted when config is saved
    editModeToggled = pyqtSignal(bool)  # Emitted when edit mode toggle changes

    def __init__(self, parent=None, config_loader=None):
        super().__init__(parent)
        self.setWindowTitle("Dashboard Settings")
        self.setObjectName("settings_dialog")
        self.resize(960, 700)
        self.config_loader = config_loader
        self.dashboard_window = parent  # Reference to dashboard for accessing visible icons/connectors
        self.resource_dir = Path(__file__).resolve().parent.parent / "resources"
        # Support multiple background folder names
        candidates = [
            self.resource_dir / "background",  # New simplified name
            self.resource_dir / "layer_3_Global_background",  # Old casing variants
            self.resource_dir / "layer_3_global_background"
        ]
        self.background_dir = None
        for candidate in candidates:
            if candidate.exists():
                self.background_dir = candidate
                break
        if self.background_dir is None:
            self.background_dir = self.resource_dir / "background"  # Default fallback
        self.selected_group_index = None
        
        self.setup_ui()
        self._apply_hud_theme()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        panel = QFrame(self)
        panel.setObjectName("settings_main_panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(10)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_general_settings_tab(), "Welcome")
        self.tabs.addTab(self.create_connectors_tab(), "Connectors")
        self.tabs.addTab(self.create_panels_tab(), "Display Panels")
        self.tabs.addTab(self.create_icons_tab(), "Icons")
        self.tabs.addTab(self.create_icon_groups_tab(), "Icon Groups")
        self.tabs.addTab(self.create_background_tab(), "Background")
        
        panel_layout.addWidget(self.tabs)
        
        # Dialog Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        panel_layout.addWidget(buttons)
        layout.addWidget(panel)

    def _apply_hud_theme(self):
        """Apply futuristic HUD theme to settings dialog."""
        self.setStyleSheet(
            """
            QDialog#settings_dialog {
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.2, radius: 1.15,
                    fx: 0.5, fy: 0.05,
                    stop: 0 #153152,
                    stop: 0.55 #0d1626,
                    stop: 1 #060b15
                );
                color: #d8e9ff;
            }
            QFrame#settings_main_panel {
                background-color: rgba(14, 29, 49, 242);
                border: 1px solid #3f6da5;
                border-radius: 14px;
            }
            QTabWidget::pane {
                border: 1px solid #3b5f8b;
                border-radius: 10px;
                background: rgba(12, 25, 43, 235);
                top: -1px;
            }
            QTabBar::tab {
                background: #173150;
                color: #c9e5ff;
                border: 1px solid #3f6da5;
                border-bottom: none;
                padding: 8px 14px;
                margin-right: 3px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #265184;
                color: #f3f9ff;
            }
            QTabBar::tab:hover:!selected {
                background: #1e426c;
            }
            QLabel {
                color: #d8e9ff;
            }
            QLabel#welcome_title {
                color: #8ad4ff;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#welcome_subtitle {
                color: #b7d5f7;
                font-size: 13px;
            }
            QLabel#welcome_heading {
                color: #95d8ff;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#welcome_key {
                color: #00f3ff;
                font-family: 'Orbitron', sans-serif;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#welcome_text {
                color: #dcecff;
                font-size: 13px;
            }
            QLabel#welcome_value {
                color: #eaf6ff;
                background: rgba(0, 255, 255, 0.10);
                border: 1px solid rgba(0, 255, 255, 0.32);
                border-radius: 4px;
                padding: 8px;
                font-family: 'Roboto Mono', monospace;
                font-size: 12px;
            }
            QFrame#welcome_panel {
                background-color: rgba(10, 10, 30, 0.86);
                border: 1px solid #00d7ff;
                border-radius: 8px;
            }
            QFrame#welcome_divider {
                background: rgba(0, 243, 255, 0.35);
                border: none;
                min-height: 1px;
                max-height: 1px;
            }
            QScrollArea#welcome_scroll {
                border: none;
                background: transparent;
            }
            QWidget#welcome_content {
                background: transparent;
            }
            QLineEdit, QComboBox, QSpinBox, QListWidget {
                background-color: #0f1a2e;
                color: #eaf3ff;
                border: 1px solid #416491;
                border-radius: 6px;
                padding: 4px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #63a9ff;
            }
            QComboBox QAbstractItemView {
                background-color: #0f1a2e;
                color: #eaf3ff;
                border: 1px solid #416491;
                selection-background-color: #2f73c9;
                selection-color: #ffffff;
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
            QPushButton:pressed {
                background-color: #265a93;
            }
            QCheckBox {
                color: #d8e9ff;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #4f84be;
                border-radius: 3px;
                background: #0f1a2e;
            }
            QCheckBox::indicator:checked {
                background: #2f73c9;
                border-color: #63a9ff;
            }
            QDialogButtonBox QPushButton {
                min-width: 90px;
            }
            """
        )

    def create_general_settings_tab(self):
        """Welcome tab with dashboard overview and core settings guidance."""
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        scroll = QScrollArea(widget)
        scroll.setObjectName("welcome_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("welcome_content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(10)

        panel = QFrame(content)
        panel.setObjectName("welcome_panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(8)

        title_label = QLabel("Welcome To Dexter Arm HUD Settings", panel)
        title_label.setObjectName("welcome_title")
        subtitle_label = QLabel(
            "This settings panel controls dashboard behavior, layout tools, and visual configuration.",
            panel,
        )
        subtitle_label.setObjectName("welcome_subtitle")
        subtitle_label.setWordWrap(True)
        panel_layout.addWidget(title_label)
        panel_layout.addWidget(subtitle_label)

        # Requested: keep edit-mode control near the top.
        control_heading = QLabel("Quick Control", panel)
        control_heading.setObjectName("welcome_heading")
        panel_layout.addWidget(control_heading)
        self.toggle_edit_mode = QCheckBox("Enable Edit Mode hotkey (Ctrl+E)", panel)
        is_enabled = self.config_loader.get_edit_mode_enabled()
        self.toggle_edit_mode.setChecked(is_enabled)
        self.toggle_edit_mode.stateChanged.connect(self._on_edit_mode_toggle_changed)
        panel_layout.addWidget(self.toggle_edit_mode)
        panel_layout.addWidget(
            self._create_welcome_value(
                "When enabled, press Ctrl+E to move/edit dashboard elements while maximized."
            )
        )

        panel_layout.addWidget(self._create_welcome_divider())

        usage_heading = QLabel("How To Use This Panel", panel)
        usage_heading.setObjectName("welcome_heading")
        panel_layout.addWidget(usage_heading)
        panel_layout.addWidget(
            self._create_welcome_value(
                "Open a tab, adjust values, add or remove items, then close settings. "
                "Changes are stored in dashboard config and refreshed after settings close."
            )
        )

        panel_layout.addWidget(self._create_welcome_divider())

        guide_heading = QLabel("Tab Guide", panel)
        guide_heading.setObjectName("welcome_heading")
        panel_layout.addWidget(guide_heading)
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Welcome",
            "Overview, quick controls, and usage guidance for the full settings workflow."
        ))
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Connectors",
            "Create or delete connector lines and tune line thickness/glow settings."
        ))
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Display Panels",
            "Add runtime status cards (static/time/CPU/RAM/launched apps), and configure colors/position."
        ))
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Icons",
            "Add custom PNG icons to layers, manage icon names, and remove existing custom icons."
        ))
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Icon Groups",
            "Build grouped interactions with hover effects, command triggers, and wake opacity behavior."
        ))
        panel_layout.addWidget(self._create_tab_guide_entry(
            "Background",
            "Select video/image background, fallback fill mode, opacity, and aspect ratio."
        ))

        panel_layout.addWidget(self._create_welcome_divider())

        shortcuts_heading = QLabel("Keyboard Shortcuts", panel)
        shortcuts_heading.setObjectName("welcome_heading")
        panel_layout.addWidget(shortcuts_heading)
        panel_layout.addWidget(
            self._create_welcome_value(
                "F11: Maximize/Restore\n"
                "Esc: Minimize\n"
                "Ctrl+E: Toggle Edit Mode (when enabled)"
            )
        )

        content_layout.addWidget(panel)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll)
        return widget

    def _create_welcome_value(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("welcome_value")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _create_welcome_divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("welcome_divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        return divider

    def _create_tab_guide_entry(self, tab_name: str, description: str) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(3)

        name_label = QLabel(f"[ {tab_name.upper()} ]", row)
        name_label.setObjectName("welcome_key")
        desc_label = self._create_welcome_value(description)

        row_layout.addWidget(name_label)
        row_layout.addWidget(desc_label)
        return row

    def _on_edit_mode_toggle_changed(self, checked):
        """Handle edit mode toggle change - save to config and emit signal."""
        is_enabled = bool(checked)
        self.config_loader.set_edit_mode_enabled(is_enabled)
        self.editModeToggled.emit(is_enabled)

    def create_buttons_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # Left: List
        self.btn_list = QListWidget()
        self.btn_list.itemClicked.connect(self.load_button_details)
        layout.addWidget(self.btn_list, 1)
        
        # Right: Details & Actions (Read-only for now for existing, can be expanded)
        details_layout = QVBoxLayout()
        details_layout.addWidget(QLabel("Button Management coming soon..."))
        # Placeholder for button editing
        
        layout.addLayout(details_layout, 2)
        return widget

    def create_connectors_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # Left: List
        self.conn_list = QListWidget()
        layout.addWidget(self.conn_list, 1)
        
        # Right: Form
        form_widget = QWidget()
        form = QFormLayout(form_widget)

        self.conn_name = QLineEdit()
        
        self.conn_thickness = QSpinBox()
        self.conn_thickness.setRange(1, 20)
        self.conn_glow_radius = QSpinBox()
        self.conn_glow_radius.setRange(0, 50)
        
        self.conn_color_btn = QPushButton("Select Line Color")
        self.conn_color_btn.clicked.connect(lambda: self._pick_color(self.conn_color_btn))
        self.conn_glow_btn = QPushButton("Select Glow Color")
        self.conn_glow_btn.clicked.connect(lambda: self._pick_color(self.conn_glow_btn))
        
        form.addRow("Name:", self.conn_name)
        form.addRow("Line Thickness:", self.conn_thickness)
        form.addRow("Glow Radius:", self.conn_glow_radius)
        form.addRow(self.conn_color_btn)
        form.addRow(self.conn_glow_btn)
        
        add_btn = QPushButton("Add New Connector")
        add_btn.clicked.connect(self.add_connector)
        
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self.delete_connector)
        
        form.addRow(add_btn)
        form.addRow(del_btn)
        form.addRow(QLabel("Default color is Cyan (#00FFFF)"))
        
        layout.addWidget(form_widget, 1)
        return widget

    def create_panels_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # Left: List
        self.panel_list = QListWidget()
        self.panel_list.itemClicked.connect(self._load_panel_details)
        layout.addWidget(self.panel_list, 1)
        
        # Right: Form
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        
        self.panel_title = QLineEdit()
        self.panel_value = QLineEdit() # Static value
        self.panel_data_source = QComboBox()
        self.panel_data_source.addItems(["Static", "Time", "CPU", "RAM", "Launched Apps", "Title Banner"])
        self.panel_data_source.currentTextChanged.connect(self._toggle_panel_type_fields)
        
        self.panel_font_size = QSpinBox()
        self.panel_font_size.setRange(8, 72)
        self.panel_font_size.setValue(12)
        
        self.panel_width = QSpinBox()
        self.panel_width.setRange(50, 3000)
        self.panel_width.setValue(220)
        
        self.panel_height = QSpinBox()
        self.panel_height.setRange(30, 2000)
        self.panel_height.setValue(60)

        self.panel_color_btn = QPushButton("Select Title Color")
        self.panel_color_btn.clicked.connect(lambda: self._pick_color(self.panel_color_btn))
        
        self.panel_value_color_btn = QPushButton("Select Value Color")
        self.panel_value_color_btn.clicked.connect(lambda: self._pick_color(self.panel_value_color_btn))
        
        # Default Coords (visible area)
        self.panel_x = QSpinBox()
        self.panel_x.setRange(0, 3000)
        self.panel_x.setValue(400)  # Default to visible area
        self.panel_y = QSpinBox()
        self.panel_y.setRange(0, 3000)
        self.panel_y.setValue(300)  # Default to visible area

        # === Title Banner specific fields ===
        self.panel_subtitle_text = QLineEdit()
        self.panel_subtitle_text.setPlaceholderText("ROBOTIC MANIPULATION SYSTEM")
        
        self.panel_hover_text = QLineEdit()
        self.panel_hover_text.setPlaceholderText("Hover tooltip text")
        
        self.panel_banner_font = QComboBox()
        self.panel_banner_font.addItems(["Orbitron", "Rajdhani", "Segoe UI", "Arial", "Courier New", "Ubuntu"])
        
        self.panel_banner_visible = QCheckBox("Visible")
        self.panel_banner_visible.setChecked(True)
        
        # Build form rows
        form.addRow("Title:", self.panel_title)
        form.addRow("Data Source:", self.panel_data_source)
        
        # Standard panel fields
        self._panel_static_value_label = QLabel("Static Value:")
        form.addRow(self._panel_static_value_label, self.panel_value)
        
        form.addRow("Font Size:", self.panel_font_size)
        form.addRow("Title Color:", self.panel_color_btn)
        
        self._panel_value_color_label = QLabel("Value Color:")
        form.addRow(self._panel_value_color_label, self.panel_value_color_btn)
        
        form.addRow("Init X:", self.panel_x)
        form.addRow("Init Y:", self.panel_y)
        form.addRow("Width:", self.panel_width)
        form.addRow("Height:", self.panel_height)
        
        # Title Banner fields (hidden by default)
        self._panel_subtitle_label = QLabel("Subtitle:")
        form.addRow(self._panel_subtitle_label, self.panel_subtitle_text)
        
        self._panel_hover_label = QLabel("Hover Text:")
        form.addRow(self._panel_hover_label, self.panel_hover_text)
        
        self._panel_font_label = QLabel("Font Family:")
        form.addRow(self._panel_font_label, self.panel_banner_font)
        
        self._panel_visible_label = QLabel("Visibility:")
        form.addRow(self._panel_visible_label, self.panel_banner_visible)
        
        # Buttons
        add_btn = QPushButton("Add Panel")
        add_btn.clicked.connect(self.add_panel)
        
        self.panel_save_btn = QPushButton("Save Selected")
        self.panel_save_btn.clicked.connect(self._save_selected_panel)
        
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self.delete_panel)
        
        form.addRow(add_btn)
        form.addRow(self.panel_save_btn)
        form.addRow(del_btn)
        
        layout.addWidget(form_widget, 1)
        
        # Initialize field visibility
        self._toggle_panel_type_fields(self.panel_data_source.currentText())
        
        return widget

    def _toggle_panel_type_fields(self, source_type):
        """Show/hide fields based on the selected data source type."""
        is_banner = (source_type == "Title Banner")
        # Show banner-specific fields
        for w in [self.panel_subtitle_text, self._panel_subtitle_label,
                   self.panel_hover_text, self._panel_hover_label,
                   self.panel_banner_font, self._panel_font_label,
                   self.panel_banner_visible, self._panel_visible_label]:
            w.setVisible(is_banner)
        # Hide standard-only fields when Title Banner is selected
        self._panel_static_value_label.setVisible(not is_banner)
        self.panel_value.setVisible(not is_banner)
        self._panel_value_color_label.setVisible(not is_banner)
        self.panel_value_color_btn.setVisible(not is_banner)
        # Set defaults for banner
        if is_banner:
            if not self.panel_title.text():
                self.panel_title.setText("DEXTER ARM")
            self.panel_font_size.setValue(24)
            self.panel_width.setValue(1280)
            self.panel_height.setValue(70)
            self.panel_x.setValue(0)
            self.panel_y.setValue(0)

    def _load_panel_details(self, item):
        """Load selected panel details into the form for viewing/editing."""
        row = self.panel_list.currentRow()
        panels = self.config_loader.get_display_panels()
        if row < 0 or row >= len(panels):
            return
        p = panels[row]
        
        # Set data source first (triggers field visibility)
        source = p.get('data_source', 'Static')
        idx = self.panel_data_source.findText(source)
        if idx >= 0:
            self.panel_data_source.setCurrentIndex(idx)
        
        self.panel_title.setText(p.get('title', ''))
        self.panel_value.setText(p.get('value', ''))
        self.panel_font_size.setValue(p.get('font_size', 12))
        self.panel_x.setValue(p.get('x', 0))
        self.panel_y.setValue(p.get('y', 0))
        self.panel_width.setValue(p.get('width', 220))
        self.panel_height.setValue(p.get('height', 60))
        
        title_color = p.get('title_color', '#00FFFF')
        self.panel_color_btn.setText(title_color)
        self.panel_color_btn.setProperty("color", title_color)
        
        value_color = p.get('value_color', '#FFFFFF')
        self.panel_value_color_btn.setText(value_color)
        self.panel_value_color_btn.setProperty("color", value_color)
        
        # Title Banner fields
        if source == 'Title Banner':
            self.panel_subtitle_text.setText(p.get('subtitle_text', 'ROBOTIC MANIPULATION SYSTEM'))
            self.panel_hover_text.setText(p.get('hover_text', ''))
            font_fam = p.get('font_family', 'Orbitron')
            fidx = self.panel_banner_font.findText(font_fam)
            if fidx >= 0:
                self.panel_banner_font.setCurrentIndex(fidx)
            self.panel_banner_visible.setChecked(p.get('visible', True))

    def _save_selected_panel(self):
        """Save edited fields back to the selected panel in config."""
        row = self.panel_list.currentRow()
        panels = self.config_loader.get_display_panels()
        if row < 0 or row >= len(panels):
            QMessageBox.warning(self, "Error", "No panel selected")
            return
        
        title = self.panel_title.text()
        if not title:
            QMessageBox.warning(self, "Error", "Title is required")
            return
        
        title_color = self.panel_color_btn.property("color") or "#00FFFF"
        value_color = self.panel_value_color_btn.property("color") or "#FFFFFF"
        
        def get_color_str(c):
            if isinstance(c, QColor):
                return c.name()
            return str(c)
        
        data_source = self.panel_data_source.currentText()
        
        # Start with existing data to preserve runtime fields (x_pct, y_pct, etc)
        updated = dict(panels[row])
        updated.update({
            'title': title,
            'value': self.panel_value.text() or "N/A",
            'x': self.panel_x.value(),
            'y': self.panel_y.value(),
            'width': self.panel_width.value(),
            'height': self.panel_height.value(),
            'font_size': self.panel_font_size.value(),
            'title_color': get_color_str(title_color),
            'value_color': get_color_str(value_color),
            'data_source': data_source
        })
        
        # Title Banner specific fields
        if data_source == 'Title Banner':
            updated['subtitle_text'] = self.panel_subtitle_text.text() or 'ROBOTIC MANIPULATION SYSTEM'
            updated['hover_text'] = self.panel_hover_text.text()
            updated['font_family'] = self.panel_banner_font.currentText()
            updated['visible'] = self.panel_banner_visible.isChecked()
        
        panels[row] = updated
        self.config_loader.update_panels(panels)
        QMessageBox.information(self, "Success", f"Panel '{title}' saved!")
        self.configChanged.emit()
        self.load_data()

    def create_icons_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # Left: available icons grouped by folder
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Available PNG Icons"))
        self.icon_search = QLineEdit()
        self.icon_search.setPlaceholderText("Search icons...")
        self.icon_search.textChanged.connect(self._filter_icon_list)
        left_layout.addWidget(self.icon_search)

        self.available_icon_list = QListWidget()
        left_layout.addWidget(self.available_icon_list, 1)
        layout.addLayout(left_layout, 2)

        # Right: add custom icons with layer selector
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Add New Icon"))

        form = QFormLayout()
        self.new_icon_name = QLineEdit()
        self.new_icon_name.setPlaceholderText("Enter icon name (must be unique)")
        form.addRow("Icon Name:", self.new_icon_name)
        
        self.new_icon_layer = QComboBox()
        self.new_icon_layer.addItems(["layer_1", "layer_2", "layer_3"])
        self.new_icon_layer.setCurrentText("layer_1")
        form.addRow("Layer:", self.new_icon_layer)
        
        right_layout.addLayout(form)

        add_btn = QPushButton("Add Icon")
        add_btn.clicked.connect(self.add_custom_icon)
        right_layout.addWidget(add_btn)

        right_layout.addWidget(QLabel("Custom Icons (Currently Added)"))
        self.custom_icon_list = QListWidget()
        right_layout.addWidget(self.custom_icon_list, 1)

        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self.delete_custom_icon)
        right_layout.addWidget(del_btn)

        layout.addLayout(right_layout, 2)
        return widget

    def create_icon_groups_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # Left: list of groups
        self.group_list = QListWidget()
        self.group_list.itemClicked.connect(self.load_group_details)
        layout.addWidget(self.group_list, 1)

        # Right: group details
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        form = QFormLayout()

        self.group_name = QLineEdit()
        self.group_main_icon = QComboBox()

        self.group_items = QListWidget()
        self.group_items.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        self.group_hover_text = QLineEdit()
        self.group_command = QLineEdit()

        self.group_hover_effect = QComboBox()
        self.group_hover_effect.addItems(["glow", "wake_up", "glow+wake_up"])

        self.group_glow_radius = QSpinBox()
        self.group_glow_radius.setRange(1, 60)
        self.group_glow_radius.setValue(25)
        self.group_glow_color_btn = QPushButton("Select Glow Color")
        self.group_glow_color_btn.clicked.connect(lambda: self._pick_color(self.group_glow_color_btn))

        self.group_wake_opacity = QSpinBox()
        self.group_wake_opacity.setRange(10, 100)
        self.group_wake_opacity.setValue(60)

        form.addRow("Group Name:", self.group_name)
        form.addRow("Main Icon:", self.group_main_icon)
        form.addRow(QLabel("Group Items:"))
        form.addRow(self.group_items)
        form.addRow("Hover Text:", self.group_hover_text)
        form.addRow("Command:", self.group_command)
        form.addRow("Hover Effect:", self.group_hover_effect)
        form.addRow("Glow Radius:", self.group_glow_radius)
        form.addRow(self.group_glow_color_btn)
        form.addRow("Wake Opacity (%):", self.group_wake_opacity)

        details_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Group")
        save_btn.clicked.connect(self.save_group)
        delete_btn = QPushButton("Delete Group")
        delete_btn.clicked.connect(self.delete_group)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(delete_btn)
        details_layout.addLayout(btn_layout)

        layout.addWidget(details_widget, 2)
        return widget

    def create_background_tab(self):
        """Tab for configuring background image/video and fallback color."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        self.bg_type = QComboBox()
        self.bg_type.addItems(["video", "image", "none"])
        self.bg_type.currentTextChanged.connect(self._load_background_media_list)
        form.addRow("Background Type:", self.bg_type)

        self.bg_media_list = QListWidget()
        form.addRow(QLabel("Background File:"))
        form.addRow(self.bg_media_list)

        self.bg_fill_mode = QComboBox()
        self.bg_fill_mode.addItems(["color", "gradient", "image"])
        self.bg_fill_mode.currentTextChanged.connect(self._toggle_background_fill_controls)
        form.addRow("Fill Mode:", self.bg_fill_mode)

        self.bg_fill_color_btn = QPushButton("Select Fill Color")
        self.bg_fill_color_btn.clicked.connect(lambda: self._pick_color(self.bg_fill_color_btn))
        form.addRow(self.bg_fill_color_btn)

        self.bg_fill_color2_btn = QPushButton("Select Gradient Color")
        self.bg_fill_color2_btn.clicked.connect(lambda: self._pick_color(self.bg_fill_color2_btn))
        form.addRow(self.bg_fill_color2_btn)

        self.bg_fill_image_list = QListWidget()
        form.addRow(QLabel("Fill Image:"))
        form.addRow(self.bg_fill_image_list)

        # Background opacity slider
        self.bg_opacity_slider = QSpinBox()
        self.bg_opacity_slider.setMinimum(5)
        self.bg_opacity_slider.setMaximum(100)
        self.bg_opacity_slider.setValue(70)
        self.bg_opacity_slider.setSuffix("%")
        form.addRow("Background Opacity:", self.bg_opacity_slider)

        # Aspect ratio dropdown
        self.bg_aspect_ratio = QComboBox()
        self.bg_aspect_ratio.addItems(["16:10", "16:9"])
        form.addRow("Background Aspect Ratio:", self.bg_aspect_ratio)

        save_btn = QPushButton("Save Background")
        save_btn.clicked.connect(self.save_background_settings)
        form.addRow(save_btn)

        # Note: Title Banner settings have been moved to the Display Panels tab
        # as a "Title Banner" data source type.

        layout.addLayout(form)
        layout.addStretch()

        return widget
    
    def save_title_banner_settings(self):
        """Legacy method kept for compatibility - title banner is now a Display Panel type."""
        pass

    def _list_background_files(self, extensions):
        files = []
        search_dirs = []
        
        # Check all possible background folder locations
        candidates = [
            self.resource_dir / "background",
            self.resource_dir / "layer_3_Global_background",
            self.resource_dir / "layer_3_global_background"
        ]
        
        for candidate in candidates:
            if candidate.exists() and candidate not in search_dirs:
                search_dirs.append(candidate)
        
        if not search_dirs:
            return files

        for base in search_dirs:
            for p in base.glob("**/*"):
                if p.is_file() and p.suffix.lower().lstrip(".") in extensions:
                    rel_path = p.relative_to(self.resource_dir).as_posix()
                    files.append(rel_path)
        return sorted(files)

    def _load_background_media_list(self):
        self.bg_media_list.clear()
        bg_type = self.bg_type.currentText()
        if bg_type == "video":
            files = self._list_background_files({"mp4", "avi", "mov", "mkv"})
        elif bg_type == "image":
            files = self._list_background_files({"png", "jpg", "jpeg", "bmp"})
        else:
            files = []
        for f in files:
            self.bg_media_list.addItem(f)
        
        # Select the first item by default if nothing is selected
        if self.bg_media_list.count() > 0 and self.bg_media_list.currentItem() is None:
            self.bg_media_list.setCurrentRow(0)

    def _load_background_fill_image_list(self):
        self.bg_fill_image_list.clear()
        files = self._list_background_files({"png", "jpg", "jpeg", "bmp"})
        for f in files:
            self.bg_fill_image_list.addItem(f)

    def _toggle_background_fill_controls(self):
        mode = self.bg_fill_mode.currentText()
        self.bg_fill_color_btn.setEnabled(mode in {"color", "gradient"})
        self.bg_fill_color2_btn.setEnabled(mode == "gradient")
        self.bg_fill_image_list.setEnabled(mode == "image")

    def save_background_settings(self):
        bg_type = self.bg_type.currentText()
        bg_item = self.bg_media_list.currentItem()
        bg_file = bg_item.text() if bg_item else ""

        fill_mode = self.bg_fill_mode.currentText()
        fill_color = self.bg_fill_color_btn.property("color") or "#0A0E1A"
        fill_color2 = self.bg_fill_color2_btn.property("color") or "#000000"
        fill_item = self.bg_fill_image_list.currentItem()
        fill_image = fill_item.text() if fill_item else ""

        opacity = self.bg_opacity_slider.value() / 100.0
        aspect_ratio = self.bg_aspect_ratio.currentText()

        settings = {
            'type': bg_type,
            'file': bg_file,
            'opacity': opacity,
            'aspect_ratio': aspect_ratio,
            'fill': {
                'mode': fill_mode,
                'color': fill_color,
                'color2': fill_color2,
                'image': fill_image
            }
        }
        self.config_loader.set_background_settings(settings)
        self.configChanged.emit()

    def _load_background_settings(self):
        settings = self.config_loader.get_background_settings()
        bg_type = settings.get('type', 'video')
        bg_file = settings.get('file', '')
        fill = settings.get('fill', {})

        self.bg_type.setCurrentText(bg_type)
        self._load_background_media_list()
        self._load_background_fill_image_list()

        # Select current background file
        if bg_file:
            for i in range(self.bg_media_list.count()):
                if self.bg_media_list.item(i).text() == bg_file:
                    self.bg_media_list.setCurrentRow(i)
                    break

        fill_mode = fill.get('mode', 'color')
        self.bg_fill_mode.setCurrentText(fill_mode)
        self._toggle_background_fill_controls()

        fill_color = fill.get('color', '#0A0E1A')
        self.bg_fill_color_btn.setText(fill_color)
        self.bg_fill_color_btn.setProperty("color", fill_color)

        fill_color2 = fill.get('color2', '#000000')
        self.bg_fill_color2_btn.setText(fill_color2)
        self.bg_fill_color2_btn.setProperty("color", fill_color2)

        fill_image = fill.get('image', '')
        if fill_image:
            for i in range(self.bg_fill_image_list.count()):
                if self.bg_fill_image_list.item(i).text() == fill_image:
                    self.bg_fill_image_list.setCurrentRow(i)
                    break
        
        # Load opacity
        opacity = settings.get('opacity', 0.7)
        self.bg_opacity_slider.setValue(int(opacity * 100))
        
        # Load aspect ratio
        aspect_ratio = settings.get('aspect_ratio', '16:10')
        self.bg_aspect_ratio.setCurrentText(aspect_ratio)
        
    def _pick_color(self, btn):
        from PyQt6.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            btn.setText(color.name())
            btn.setProperty("color", color.name()) # Store for access

    def _filter_icon_list(self, text):
        self._load_available_icons(filter_text=text)

    def _load_available_icons(self, filter_text=""):
        self.available_icon_list.clear()
        if not self.resource_dir.exists():
            return
        
        files = []
        for p in self.resource_dir.glob("**/*.png"):
            rel_path = p.relative_to(self.resource_dir).as_posix()
            files.append(rel_path)
        files = sorted(files)
        
        if filter_text:
            filter_lower = filter_text.lower()
            files = [f for f in files if filter_lower in f.lower()]
        
        # Group by folder
        folders = {}
        for name in files:
            parts = name.split("/")
            if len(parts) > 1:
                folder = parts[0]
            else:
                folder = "root"
            if folder not in folders:
                folders[folder] = []
            folders[folder].append(name)
        
        # Add folder headers and icons
        for folder in sorted(folders.keys()):
            for icon_path in sorted(folders[folder]):
                display_text = f"  {icon_path}"  # Indent for hierarchy
                self.available_icon_list.addItem(display_text)
                # Store actual path in UserRole
                item = self.available_icon_list.item(self.available_icon_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, icon_path)

    def _get_existing_icon_names(self):
        if not self.config_loader:
            return set()
        reserved = {
            'window', 'connectors', 'display_panels', 'buttons', 'combos', 'utilities',
            'layer_order', 'opacity_defaults', 'icon_groups', 'custom_icons',
            'workspace', 'microros_workspace', 'esp32_port', 'esp32_baud'
        }
        names = set()
        for key, value in self.config_loader.config.items():
            if key in reserved:
                continue
            if isinstance(value, dict) and any(k in value for k in ("x", "x_pct")):
                names.add(key)
        for icon in self.config_loader.get_custom_icons():
            name = icon.get('name')
            if name:
                names.add(name)
        return names

    def add_custom_icon(self):
        name = self.new_icon_name.text().strip()
        item = self.available_icon_list.currentItem()
        if not name:
            QMessageBox.warning(self, "Error", "Icon name is required")
            return
        if not item:
            QMessageBox.warning(self, "Error", "Select a PNG icon from the list")
            return

        existing = self._get_existing_icon_names()
        if name in existing:
            QMessageBox.warning(self, "Error", "Icon name already exists")
            return

        # Get actual path from UserRole data
        filename = item.data(Qt.ItemDataRole.UserRole)
        if not filename:
            filename = item.text().strip()  # Fallback to displayed text
        
        layer = self.new_icon_layer.currentText()  # Use selected layer
        icon_data = {
            'name': name,
            'file': filename,
            'layer': layer,
            'x': 200,
            'y': 200
        }
        self.config_loader.add_custom_icon(icon_data)
        self.configChanged.emit()
        self.load_data()
        self.new_icon_name.clear()

    def delete_custom_icon(self):
        current_item = self.custom_icon_list.currentItem()
        if current_item is None:
            return
        index = current_item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            # Header row selected — nothing to delete
            return
        self.config_loader.remove_custom_icon(index)
        self.configChanged.emit()
        self.load_data()

    def load_group_details(self, item):
        index = self.group_list.row(item)
        groups = self.config_loader.get_icon_groups()
        if index < 0 or index >= len(groups):
            return
        group = groups[index]
        self.selected_group_index = index

        self.group_name.setText(group.get('name', ''))
        main_icon = group.get('main_icon', '')
        self._refresh_group_main_icon_list(current_main_icon=main_icon)
        self.group_main_icon.setCurrentText(main_icon)
        self.group_hover_text.setText(group.get('hover_text', ''))
        self.group_command.setText(group.get('command', ''))
        effects = group.get('hover_effects') or []
        if isinstance(effects, str):
            effects = [effects]
        if effects:
            self.group_hover_effect.setCurrentText(effects[0])
        self.group_glow_radius.setValue(int(group.get('glow_radius', 25)))
        glow_color = group.get('glow_color', '#00F3FF')
        self.group_glow_color_btn.setText(glow_color)
        self.group_glow_color_btn.setProperty("color", glow_color)
        self.group_wake_opacity.setValue(int(group.get('wake_opacity', 60)))

        # Select group items
        selected_items = set(group.get('items') or group.get('group_items') or [])
        for i in range(self.group_items.count()):
            list_item = self.group_items.item(i)
            value = list_item.data(Qt.ItemDataRole.UserRole)
            list_item.setSelected(value in selected_items)

    def save_group(self):
        name = self.group_name.text().strip()
        main_icon = self.group_main_icon.currentText().strip()
        if not name or not main_icon:
            QMessageBox.warning(self, "Error", "Group name and main icon are required")
            return

        groups = self.config_loader.get_icon_groups()
        for i, g in enumerate(groups):
            if g.get('main_icon') == main_icon and i != self.selected_group_index:
                QMessageBox.warning(self, "Error", "Main icon must be unique")
                return

        items = []
        for list_item in self.group_items.selectedItems():
            value = list_item.data(Qt.ItemDataRole.UserRole)
            if value:
                items.append(value)

        group_data = {
            'name': name,
            'main_icon': main_icon,
            'items': items,
            'hover_text': self.group_hover_text.text().strip(),
            'hover_effects': [self.group_hover_effect.currentText()],
            'command': self.group_command.text().strip(),
            'glow_radius': self.group_glow_radius.value(),
            'glow_color': self.group_glow_color_btn.property("color") or "#00F3FF",
            'wake_opacity': self.group_wake_opacity.value()
        }

        if self.selected_group_index is None:
            self.config_loader.add_icon_group(group_data)
        else:
            self.config_loader.update_icon_group(self.selected_group_index, group_data)

        self.configChanged.emit()
        self.load_data()

    def delete_group(self):
        row = self.group_list.currentRow()
        if row >= 0:
            self.config_loader.remove_icon_group(row)
            self.selected_group_index = None
            self.configChanged.emit()
            self.load_data()

    def _refresh_group_main_icon_list(self, current_main_icon: str = ""):
        """Populate main icon dropdown, excluding icons already used by other groups."""
        self.group_main_icon.clear()
        # Only allow icons added from the custom icon section
        icon_names = sorted({i.get('name') for i in self.config_loader.get_custom_icons() if i.get('name')})

        groups = self.config_loader.get_icon_groups()
        used_main_icons = set()
        for i, group in enumerate(groups):
            main_icon = group.get('main_icon')
            if main_icon and i != self.selected_group_index:
                used_main_icons.add(main_icon)

        if current_main_icon and current_main_icon not in icon_names:
            icon_names.insert(0, current_main_icon)

        for name in icon_names:
            if name == current_main_icon or name not in used_main_icons:
                self.group_main_icon.addItem(name)



    def load_data(self):
        if not self.config_loader:
            return

        self.selected_group_index = None
            
        # Load Connectors
        self.conn_list.clear()
        connectors = self.config_loader.get_connectors()
        for i, c in enumerate(connectors):
            name = c.get('name', f"connector_{i + 1}")
            if 'points' in c:
                pts = c['points']
                p_start = f"{int(pts[0][0])},{int(pts[0][1])}"
                p_end = f"{int(pts[-1][0])},{int(pts[-1][1])}"
                self.conn_list.addItem(f"{name}: {len(pts)} pts ({p_start}) -> ({p_end})")
            else:
                self.conn_list.addItem(f"{name}: Legacy Connector")
            
        # Load Panels
        self.panel_list.clear()
        panels = self.config_loader.get_display_panels()
        for i, p in enumerate(panels):
            ds = p.get('data_source', 'Static')
            label = f"[{ds}] {p.get('title', 'Untitled')}"
            self.panel_list.addItem(label)
            
        # Load Buttons list only if legacy buttons tab exists
        if hasattr(self, 'btn_list'):
            self.btn_list.clear()
            buttons = self.config_loader.get_all_buttons()
            for name in buttons:
                self.btn_list.addItem(name)

        # Load available icons
        self._load_available_icons(filter_text=self.icon_search.text() if hasattr(self, 'icon_search') else "")

        # Load custom icons (grouped by assigned layer)
        if hasattr(self, 'custom_icon_list'):
            self.custom_icon_list.clear()
            custom_icons = self.config_loader.get_custom_icons()
            
            # Group icons by layer, tracking original config index
            icons_by_layer = {'layer_1': [], 'layer_2': [], 'layer_3': []}
            for i, icon in enumerate(custom_icons):
                layer = icon.get('layer', 'layer_1')
                name = icon.get('name', 'unnamed')
                file = icon.get('file', 'unknown')
                if layer not in icons_by_layer:
                    icons_by_layer[layer] = []
                icons_by_layer[layer].append((name, file, i))  # include original index
            
            # Display grouped by layer (layer_1 front, layer_3 back)
            for layer in ['layer_1', 'layer_2', 'layer_3']:
                if icons_by_layer[layer]:
                    # Add layer header (not selectable)
                    header_item = QListWidgetItem(f"\n=== {layer.upper()} ===")
                    header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    header_item.setBackground(QColor(0, 60, 80))
                    self.custom_icon_list.addItem(header_item)
                    
                    # Add icons in this layer, storing the real config index as UserRole
                    for name, file, original_idx in sorted(icons_by_layer[layer]):
                        item_text = f"  • {name} ({file})"
                        list_item = QListWidgetItem(item_text)
                        list_item.setData(Qt.ItemDataRole.UserRole, original_idx)
                        self.custom_icon_list.addItem(list_item)

        # Load groups
        if hasattr(self, 'group_list'):
            self.group_list.clear()
            groups = self.config_loader.get_icon_groups()
            for group in groups:
                display = group.get('name') or group.get('main_icon') or 'unnamed'
                self.group_list.addItem(display)

        # Load group icon list (main icon dropdown)
        if hasattr(self, 'group_main_icon'):
            self._refresh_group_main_icon_list()

        # Load group items list - ONLY show dashboard icons/connectors
        if hasattr(self, 'group_items'):
            self.group_items.clear()
            
            # Add icons currently on the dashboard
            dashboard_icons = set()
            if self.dashboard_window and hasattr(self.dashboard_window, 'custom_icon_widgets'):
                dashboard_icons = set(self.dashboard_window.custom_icon_widgets.keys())
            
            for name in sorted(dashboard_icons):
                item = QListWidgetItem(f"Icon: {name}")
                item.setData(Qt.ItemDataRole.UserRole, f"icon:{name}")
                self.group_items.addItem(item)

            # Add connectors currently on the dashboard
            if self.dashboard_window and hasattr(self.dashboard_window, 'connectors'):
                for i, conn in enumerate(self.dashboard_window.connectors):
                    # Try to get name from connector object
                    conn_name = getattr(conn, 'name', None) or getattr(conn, '_name', None)
                    if not conn_name:
                        # Fall back to config
                        config_conns = self.config_loader.get_connectors()
                        if i < len(config_conns):
                            conn_name = config_conns[i].get('name', f"connector_{i + 1}")
                        else:
                            conn_name = f"connector_{i + 1}"
                    
                    item = QListWidgetItem(f"Connector: {conn_name}")
                    item.setData(Qt.ItemDataRole.UserRole, f"connector:{conn_name}")
                    self.group_items.addItem(item)
            else:
                # Fallback if dashboard not available: use all from config
                connectors = self.config_loader.get_connectors()
                for i, c in enumerate(connectors):
                    conn_name = c.get('name', f"connector_{i + 1}")
                    item = QListWidgetItem(f"Connector: {conn_name}")
                    item.setData(Qt.ItemDataRole.UserRole, f"connector:{conn_name}")
                    self.group_items.addItem(item)
            
            # Add settings button as special option
            item = QListWidgetItem("[Settings Button] (Global)")
            item.setData(Qt.ItemDataRole.UserRole, "icon:settings")
            self.group_items.addItem(item)

        if hasattr(self, 'bg_type'):
            self._load_background_settings()



    def load_button_details(self, item):
        pass

    def add_connector(self):
        # Read from form
        name = self.conn_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Connector name is required")
            return
        color = self.conn_color_btn.property("color") or "#00FFFF"
        glow_color = self.conn_glow_btn.property("color") or "#00FFFF"
        
        data = {
            'name': name,
            'points': [[100, 100], [300, 300]],
            'line_color': color,
            'glow_color': glow_color,
            'thickness': self.conn_thickness.value(),
            'glow_radius': self.conn_glow_radius.value()
        }
        self.config_loader.add_connector(data)
        self.configChanged.emit()
        self.load_data()

    def delete_connector(self):
        row = self.conn_list.currentRow()
        if row >= 0:
            self.config_loader.remove_connector(row)
            self.configChanged.emit()
            self.load_data()

    def add_panel(self):
        title = self.panel_title.text()
        if not title:
            QMessageBox.warning(self, "Error", "Title is required")
            return
            
        # Get Colors
        title_color = self.panel_color_btn.property("color") or "#00FFFF"
        value_color = self.panel_value_color_btn.property("color") or "#FFFFFF"
        
        # Helper to ensure string format
        def get_color_str(c):
            if isinstance(c, QColor):
                return c.name()
            return str(c)

        data_source = self.panel_data_source.currentText()

        data = {
            'title': title,
            'value': self.panel_value.text() or "N/A",
            'x': self.panel_x.value(),
            'y': self.panel_y.value(),
            'width': self.panel_width.value(),
            'height': self.panel_height.value(),
            'font_size': self.panel_font_size.value(),
            'title_color': get_color_str(title_color),
            'value_color': get_color_str(value_color),
            'data_source': data_source
        }
        
        # Title Banner specific fields
        if data_source == 'Title Banner':
            data['subtitle_text'] = self.panel_subtitle_text.text() or 'ROBOTIC MANIPULATION SYSTEM'
            data['hover_text'] = self.panel_hover_text.text() or '⚙ DEXTER ARM  ━━━━━━━━━━━━━━━━━━━━\n\n▸ Platform     ROS 2 Jazzy · Gazebo Harmonic\n▸ Simulation   MoveIt 2 · RViz2 · Gazebo Physics\n▸ Planning     OMPL · Servo · MoveGroup\n\n◈ Hardware     ESP32 Controller + micro-ROS Agent\n◈ Control      Real-time Joint via Serial/WiFi\n◈ Firmware     Flash & OTA Update Support\n\n◇ Dashboard    PyQt6 HUD Control Interface\n◇ Trajectory   FK/IK Workspace Generation\n◇ Monitor      System Process & Resource Tracking'
            data['font_family'] = self.panel_banner_font.currentText()
            data['visible'] = self.panel_banner_visible.isChecked()
            data['title_color'] = get_color_str(title_color) if title_color != '#00FFFF' else '#00F3FF'
        
        self.config_loader.add_display_panel(data)
        self.configChanged.emit()
        self.load_data()

    def delete_panel(self):
        row = self.panel_list.currentRow()
        if row >= 0:
            self.config_loader.remove_display_panel(row)
            self.configChanged.emit()
            self.load_data()
