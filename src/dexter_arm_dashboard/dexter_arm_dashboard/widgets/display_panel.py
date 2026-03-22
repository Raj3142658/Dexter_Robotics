
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect, QFrame, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QTimer, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QCursor
from ..data_source_manager import DataSourceManager

from .resize_handle import ResizeHandle

class DisplayPanel(QWidget):
    """
    A futuristic display panel with a title and value field.
    Visual style: Glass/Grid background with cyan accents.
    Supports a special 'Title Banner' mode for the main dashboard title.
    """
    
    # Signal emitted when position changes (for saving layout)
    positionChanged = pyqtSignal()

    def __init__(self, parent=None, title="Status", value="Ready", x=100, y=100,
                 width=220, height=60,
                 font_size=12, text_color="#00FFFF", title_color=None, value_color=None,
                 data_source="Static", fixed_opacity=None, launched_apps_provider=None,
                 subtitle_text="", hover_text="", font_family="Orbitron", visible=True):
        super().__init__(parent)
        
        self.fixed_opacity = fixed_opacity
        
        # Backward compatibility
        if title_color is None:
            title_color = text_color
        if value_color is None:
            value_color = "#FFFFFF" # Default white for value if not specified

        self.title_color = title_color
        self.value_color = value_color
        
        # 1. Initialize State (MUST be before geometry/resize)
        self._drag_active = False
        self._drag_pos = QPoint()
        self._locked = True  # Locked by default
        self.data_source_key = data_source
        self.static_value = value
        self.current_value = value
        self.title_text = title  # FIX: Needed for saving state
        self.font_size = font_size  # FIX: Needed for saving state
        self.is_static_display_only = (data_source == "Static")  # Mark as static-only display
        self._is_launched_apps = (data_source.lower() == "launched apps")
        self._is_title_banner = (data_source == "Title Banner")
        self._launched_apps_provider = launched_apps_provider
        
        # Title Banner properties
        self.subtitle_text = subtitle_text
        self.hover_text = hover_text
        self.font_family = font_family
        self.banner_visible = visible
        
        # Opacity Effect (HUD Style)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        initial_opacity = self.fixed_opacity if self.fixed_opacity is not None else 0.8
        self.base_opacity = initial_opacity
        self.opacity_effect.setOpacity(initial_opacity)
        self.setGraphicsEffect(self.opacity_effect)
        
        # Glow Effect (Cyan Bloom)
        self.glow_effect = QGraphicsDropShadowEffect(self)
        self.glow_effect.setColor(QColor(0, 243, 255))
        self.glow_effect.setBlurRadius(0.01)
        self.glow_effect.setOffset(0, 0)
        # Note: We cannot set two effects on one widget!
        # For DisplayPanel, we'll apply the glow to the border via stylesheet or better,
        # apply the opacity to the WHOLE widget and the glow to an inner content frame.
        
        # 2. Setup UI
        self._setup_ui(title, value, font_size, title_color, value_color)

        # Resize Handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()
        
        # Animations
        self._glow_radius = 0.01
        self.glow_anim = QPropertyAnimation(self, b"glowRadius")
        self.glow_anim.setDuration(300)
        self.glow_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Data update timer — use a slower 2000ms interval to reduce overhead.
        # For dashboards with many panels, consider calling update_data() from
        # a single external timer instead of per-panel timers.
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_data)
        self.update_timer.start(2000)
        self._update_data()

    @pyqtProperty(float)
    def glowRadius(self): return self._glow_radius

    @glowRadius.setter
    def glowRadius(self, value):
        self._glow_radius = max(0.01, value)
        self.glow_effect.setBlurRadius(self._glow_radius)

    def _setup_ui(self, title, value, font_size, title_color, value_color):
        """Initialize labels and styling with stability wrap."""
        # Frame for content (Isolates glow from opacity)
        self.content_frame = QFrame(self)
        self.content_frame.setObjectName("content_frame")
        self.content_frame.setGeometry(0, 0, self.width(), self.height())
        
        # Apply Glow to Frame
        self.content_frame.setGraphicsEffect(self.glow_effect)
        
        if self._is_title_banner:
            self._setup_banner_ui(title, font_size, title_color)
        else:
            self._setup_standard_ui(title, value, font_size, title_color, value_color)

    def _setup_banner_ui(self, title, font_size, title_color):
        """Setup UI for Title Banner mode."""
        layout = QVBoxLayout(self.content_frame)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)
        
        from PyQt6.QtWidgets import QSizePolicy
        
        # Main title
        self.title_label = QLabel(title, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {title_color};
                font-size: {font_size}px;
                font-weight: bold;
                font-family: "{self.font_family}", "Rajdhani", sans-serif;
                letter-spacing: 8px;
                padding: 5px;
                background: transparent;
            }}
        """)
        layout.addWidget(self.title_label)
        
        # Subtitle
        self.subtitle_label = QLabel(self.subtitle_text, self)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_size = max(10, font_size - 10)
        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                color: #00D4FF;
                font-size: {sub_size}px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 3px;
                background: transparent;
            }}
        """)
        layout.addWidget(self.subtitle_label)
        
        # Value label (hidden in banner mode but needed for compatibility)
        self.value_label = QLabel("", self)
        self.value_label.hide()
        
        # Set tooltip with HUD styling
        if self.hover_text:
            self.setToolTip(self.hover_text)
            self.setToolTipDuration(-1)  # Show instantly, no delay
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        # Enable hover on child labels too so tooltip works everywhere
        self.title_label.setMouseTracking(True)
        self.subtitle_label.setMouseTracking(True)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        # Banner style with HUD tooltip
        self._banner_base_style = f"""
            QFrame#content_frame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(0, 20, 40, 240),
                    stop: 0.2 rgba(0, 50, 90, 180),
                    stop: 0.5 rgba(0, 80, 130, 160),
                    stop: 0.8 rgba(0, 50, 90, 180),
                    stop: 1 rgba(0, 20, 40, 240)
                );
                border-bottom: 2px solid {title_color};
                border-image: none;
            }}
            QToolTip {{
                background-color: rgba(0, 16, 32, 245);
                color: #00F3FF;
                border: 1px solid #00F3FF;
                border-radius: 4px;
                padding: 10px 14px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                font-size: 13px;
                letter-spacing: 1px;
            }}
        """
        self.setStyleSheet(self._banner_base_style)
        
        # Visibility
        if not self.banner_visible:
            self.hide()

    def _setup_standard_ui(self, title, value, font_size, title_color, value_color):
        """Setup UI for standard panel mode."""
        # Main Layout inside Frame
        layout = QVBoxLayout(self.content_frame)
        layout.setContentsMargins(10, 5, 20, 10)
        layout.setSpacing(2)
        
        # Title Label (hidden for static-display-only panels)
        self.title_label = QLabel(f"[ {title} ]")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_font_size = max(8, int(font_size * 0.8))
        self.title_label.setStyleSheet(f"color: {title_color}; font-family: 'Orbitron', sans-serif; font-size: {title_font_size}px; font-weight: bold; background: transparent;")
        
        # Hide title label for static-display-only panels
        if self.is_static_display_only:
            self.title_label.hide()
        
        # Value Label
        self.value_label = QLabel(value)
        # Use left-aligned multi-line display for Launched Apps, centered for others
        if self.is_static_display_only or not self._is_launched_apps:
            self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.value_label.setWordWrap(True)
        self.value_label.setStyleSheet(f"color: {value_color}; font-family: 'Roboto Mono', monospace; font-size: {font_size}px; background: rgba(0, 255, 255, 0.1); border: 1px solid rgba(0, 255, 255, 0.3); border-radius: 4px;")
        
        # Subtitle label placeholder (hidden for standard panels)
        self.subtitle_label = QLabel("", self)
        self.subtitle_label.hide()
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        
        self.setStyleSheet(f"""
            QFrame#content_frame {{
                background-color: rgba(10, 10, 30, 0.85);
                border: 1px solid {title_color};
                border-radius: 5px;
            }}
        """)

    def apply_scale(self, scale: float):
        """Scale label font sizes to match the dashboard scaling."""
        if self._is_title_banner:
            title_size = max(12, int(self.font_size * scale))
            sub_size = max(8, int((self.font_size - 10) * scale))
            self.title_label.setStyleSheet(
                f"color: {self.title_color}; font-size: {title_size}px; font-weight: bold; "
                f"font-family: '{self.font_family}', 'Rajdhani', sans-serif; "
                f"letter-spacing: 8px; padding: 5px; background: transparent;"
            )
            if hasattr(self, 'subtitle_label') and self.subtitle_label.isVisible():
                self.subtitle_label.setStyleSheet(
                    f"color: #00D4FF; font-size: {sub_size}px; "
                    f"font-family: 'Rajdhani', 'Segoe UI', sans-serif; "
                    f"letter-spacing: 3px; background: transparent;"
                )
        else:
            value_size = max(8, int(self.font_size * scale))
            title_size = max(8, int(self.font_size * 0.8 * scale))
            self.title_label.setStyleSheet(
                f"color: {self.title_color}; font-family: 'Orbitron', sans-serif; "
                f"font-size: {title_size}px; font-weight: bold; background: transparent;"
            )
            self.value_label.setStyleSheet(
                f"color: {self.value_color}; font-family: 'Roboto Mono', monospace; "
                f"font-size: {value_size}px; background: rgba(0, 255, 255, 0.1); "
                f"border: 1px solid rgba(0, 255, 255, 0.3); border-radius: 4px;"
            )
        
    def _update_data(self):
        """Fetch new data from DataSourceManager and update label."""
        if self._is_title_banner:
            # Title Banner doesn't need dynamic data updates
            return
        if self._is_launched_apps:
            if self._launched_apps_provider is not None:
                apps = self._launched_apps_provider()
                if apps:
                    self.current_value = "\n".join(f"● {name}" for name in apps)
                else:
                    self.current_value = "— no active apps —"
            else:
                self.current_value = "— no active apps —"
        else:
            new_value = DataSourceManager.get_data(self.data_source_key, self.static_value)
            self.current_value = str(new_value)
        self.value_label.setText(self.current_value)

    def set_locked(self, locked: bool):
        print(f"[DEBUG] DisplayPanel.set_locked({locked}) for '{self.title_text}'")
        self._locked = locked
        if locked:
            self.resize_handle.hide()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            # Title Banner keeps mouse events for tooltip; others pass through
            if self._is_title_banner:
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            else:
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        else:
            self.resize_handle.show()
            # In unlocked mode, panel can receive mouse events
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.resize_handle.move(self.width() - 15, self.height() - 15)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.resize_handle.raise_()
            # Bring to front so it's clickable
            self.raise_()
        self.resize_handle.raise_()
        self.update()

    def enterEvent(self, event):
        """HUD Opacity Effect - Fade In"""
        super().enterEvent(event)
        if self.fixed_opacity is None:
            self.glow_anim.setStartValue(self._glow_radius)
            self.glow_anim.setEndValue(15.0) # Subtle glow for panels
            self.glow_anim.start()
        
    def leaveEvent(self, event):
        """HUD Opacity Effect - Fade Out"""
        super().leaveEvent(event)
        if self.fixed_opacity is None:
            self.opacity_effect.setOpacity(self.base_opacity)
            self.glow_anim.setStartValue(self._glow_radius)
            self.glow_anim.setEndValue(0.01)
            self.glow_anim.start()

    def resizeEvent(self, event):
        if hasattr(self, 'content_frame'):
            self.content_frame.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, 'resize_handle'):
             self.resize_handle.move(self.width() - 15, self.height() - 15)
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            
    def mouseReleaseEvent(self, event):
        if self._drag_active:
            self._drag_active = False
            self.positionChanged.emit()
            event.accept()

    def wheelEvent(self, event):
        if not self._locked and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y()
            current_opacity = self.opacity_effect.opacity()
            step = 0.05
            if delta > 0:
                new_opacity = min(0.999, current_opacity + step)
            else:
                new_opacity = max(0.1, current_opacity - step)
            self.opacity_effect.setOpacity(new_opacity)
            self.base_opacity = new_opacity
            event.accept()
            return
        super().wheelEvent(event)
