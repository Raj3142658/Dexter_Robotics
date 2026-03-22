"""
HUD Title Banner Widget
A futuristic HUD-styled title banner for the dashboard with hover effects.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen, QBrush, QMouseEvent, QFont
from .resize_handle import ResizeHandle


class HudTitleBanner(QWidget):
    """
    A futuristic HUD-styled title banner with hover effects.
    Displays "DEXTER ARM" with a sci-fi aesthetic.
    """
    
    def __init__(self, parent=None, title: str = "DEXTER ARM"):
        super().__init__(parent)
        self.title = title
        self.title_color = '#00F3FF'  # Default cyan
        self.hover_text = "Dexter Arm - Robotic Manipulation System"
        self._hovered = False
        self.glow_intensity = 0
        
        self._setup_ui()
        self._start_glow_animation()
    
    def _setup_ui(self):
        """Setup the UI components."""
        self.setFixedHeight(60)
        
        # Main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        
        # Title label
        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: #00F3FF;
                font-size: 22px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 4px;
                text-shadow: 0 0 10px #00F3FF, 0 0 20px #00F3FF;
            }}
        """)
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Version/info label
        self.info_label = QLabel("v1.0.0")
        self.info_label.setStyleSheet("""
            QLabel {
                color: #4488AA;
                font-size: 11px;
                font-family: "Courier New", monospace;
                letter-spacing: 1px;
            }
        """)
        layout.addWidget(self.info_label)
        
        # Apply widget styling
        self.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(0, 40, 80, 200),
                    stop: 0.3 rgba(0, 60, 100, 150),
                    stop: 0.7 rgba(0, 40, 80, 150),
                    stop: 1 rgba(0, 30, 60, 200)
                );
                border-bottom: 2px solid #00F3FF;
            }}
        """)
        
        # Enable mouse tracking for hover effect
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    
    def _start_glow_animation(self):
        """Start the glow animation."""
        self.glow_direction = 1
        self.glow_timer = QTimer(self)
        self.glow_timer.timeout.connect(self._update_glow)
        self.glow_timer.start(50)
    
    def _update_glow(self):
        """Update the glow effect."""
        if self._hovered:
            self.glow_intensity = min(1.0, self.glow_intensity + 0.05)
        else:
            self.glow_intensity = max(0.3, self.glow_intensity - 0.02)
        
        # Update text shadow based on glow intensity
        intensity = int(10 + self.glow_intensity * 15)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: #00F3FF;
                font-size: 22px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 4px;
                text-shadow: 0 0 {intensity}px #00F3FF, 0 0 {intensity * 2}px #00F3FF;
            }}
        """)
    
    def set_hover_text(self, text: str):
        """
        Set the hover tooltip text.
        
        Args:
            text: The hover text to display
        """
        self.hover_text = text
        self.setToolTip(text)
    
    def set_title(self, title: str):
        """
        Set the main title text.
        
        Args:
            title: The title to display
        """
        self.title = title
        self.title_label.setText(title)
    
    def set_version(self, version: str):
        """
        Set the version text.
        
        Args:
            version: Version string
        """
        self.info_label.setText(version)
    
    def enterEvent(self, event):
        """Handle mouse enter."""
        self._hovered = True
        self.setToolTip(self.hover_text)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Handle mouse leave."""
        self._hovered = False
        super().leaveEvent(event)


class AnimatedHudBanner(QWidget):
    """
    An animated version of the HUD banner with scanline effects.
    """
    
    EDIT_STYLE = "\nborder: 2px dashed #00FFFF; background-color: rgba(255, 255, 255, 20);"
    geometryChanged = pyqtSignal()  # Signal emitted when geometry changes
    
    def __init__(self, parent=None, title: str = "DEXTER ARM"):
        super().__init__(parent)
        self.title = title
        self.title_color = '#00F3FF'  # Default cyan
        self.glow_intensity = 0.3  # Default glow intensity
        self.scanline_pos = 0
        
        # Edit mode properties
        self.movable = False
        self.is_dragging = False
        self.drag_start_pos = QPoint()
        self._locked = True  # Start locked
        
        self._setup_ui()
        self._start_animation()
    
    def moveEvent(self, event):
        """Override move event to emit geometryChanged signal."""
        super().moveEvent(event)
        if hasattr(self, 'geometryChanged'):
            self.geometryChanged.emit()
    
    def resizeEvent(self, event):
        """Override resize event to emit geometryChanged signal."""
        super().resizeEvent(event)
        if hasattr(self, 'geometryChanged'):
            self.geometryChanged.emit()
    
    def set_locked(self, locked: bool):
        """
        Set the locked state for edit mode.
        
        Args:
            locked: If True, banner cannot be moved/resized
        """
        self._locked = locked
        self.movable = not locked
        if locked:
            self.setStyleSheet(self._normal_style)
            if hasattr(self, 'resize_handle'):
                self.resize_handle.hide()
        else:
            self.setStyleSheet(self._normal_style + self.EDIT_STYLE)
            if hasattr(self, 'resize_handle'):
                self.resize_handle.show()
    
    def mousePressEvent(self, event: QMouseEvent):
        if self.movable:
            if event.button() == Qt.MouseButton.LeftButton:
                self.is_dragging = True
                self.drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.movable and self.is_dragging:
            if event.buttons() & Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self.drag_start_pos
                self.move(new_pos.x(), new_pos.y())
                event.accept()
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.movable and self.is_dragging:
            self.is_dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def _setup_ui(self):
        """Setup UI."""
        self.setMinimumHeight(50)
        
        # Store normal style for edit mode toggle
        self._normal_style = """
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(0, 20, 40, 240),
                    stop: 0.2 rgba(0, 50, 90, 180),
                    stop: 0.5 rgba(0, 80, 130, 160),
                    stop: 0.8 rgba(0, 50, 90, 180),
                    stop: 1 rgba(0, 20, 40, 240)
                );
                border-bottom: 2px solid #00F3FF;
                border-image: none;
            }
        """
        self.setStyleSheet(self._normal_style)
        
        from PyQt6.QtWidgets import QVBoxLayout, QLabel, QSizePolicy
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(0)
        
        # Main title
        self.title_label = QLabel(self.title, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #00F3FF;
                font-size: 24px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", sans-serif;
                letter-spacing: 8px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.title_label)
        
        # Subtitle/status
        self.subtitle_label = QLabel("ROBOTIC MANIPULATION SYSTEM", self)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 14px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 3px;
                text-shadow: 0 0 5px #00D4FF;
            }
        """)
        layout.addWidget(self.subtitle_label)
        
        # Resize handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()
        
        # Set tooltip
        self.setToolTip("Dexter Arm - ROS 2 Robotic Manipulation System\nVersion 1.0.0")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    
    def _start_animation(self):
        """Start scanline animation."""
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animate)
        self.animation_timer.start(100)
    
    def _animate(self):
        """Animate scanline effect."""
        self.scanline_pos = (self.scanline_pos + 2) % self.height()
        self.update()
    
    def paintEvent(self, event):
        """Paint scanline effect."""
        super().paintEvent(event)
        
        # Draw scanline
        painter = QPainter(self)
        painter.setPen(QPen(QColor(0, 243, 255, 30), 1))
        y = self.scanline_pos
        while y < self.height():
            painter.drawLine(0, y, self.width(), y)
            y += 20
    
    def set_title(self, title: str):
        """Set the title text."""
        self.title = title
        self.title_label.setText(title)
    
    def set_subtitle(self, subtitle: str):
        """Set the subtitle text."""
        self.subtitle_label.setText(subtitle)
        # Update stylesheet for better visibility
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 14px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 3px;
                text-shadow: 0 0 5px #00D4FF;
            }
        """)
    
    def set_hover_text(self, text: str):
        """
        Set the hover tooltip text with HUD styling.
        
        Args:
            text: The hover text to display
        """
        self.setToolTip(text)
        # Apply HUD-style tooltip styling
        self.setToolTipDuration(-1)  # Show tooltip instantly, no delay
        # Enable hover events for immediate tooltip
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        tooltip_style = """
            QToolTip {
                background-color: rgba(0, 20, 40, 240);
                color: #00F3FF;
                border: 1px solid #00F3FF;
                border-radius: 4px;
                padding: 8px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                font-size: 13px;
            }
        """
        # Apply tooltip style globally
        self.setStyleSheet(tooltip_style)
    
    def set_status(self, status: str, color: str = "#00FF00"):
        """
        Set status text with color.
        
        Args:
            status: Status text
            color: Status color (hex)
        """
        self.subtitle_label.setText(status)
        self.subtitle_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 10px;
                font-family: "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 3px;
            }}
        """)

    def set_font(self, font_family: str, font_size: int):
        """
        Set the font family and size for the title.
        
        Args:
            font_family: Font family name (e.g., 'Orbitron', 'Arial')
            font_size: Font size in points
        """
        self.title_label.setFont(QFont(font_family, font_size))
        self.subtitle_label.setFont(QFont(font_family, max(10, font_size - 6)))

    def set_title_color(self, color: str):
        """
        Set the title color.
        
        Args:
            color: Hex color code (e.g., '#00F3FF')
        """
        self.title_color = color
        # Update title label stylesheet with new color
        intensity = int(10 + self.glow_intensity * 15)
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                font-size: 22px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", "Segoe UI", sans-serif;
                letter-spacing: 4px;
                text-shadow: 0 0 {intensity}px {color}, 0 0 {intensity * 2}px {color};
            }}
        """)
        # Also update border color
        self.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(0, 40, 80, 200),
                    stop: 0.3 rgba(0, 60, 100, 150),
                    stop: 0.7 rgba(0, 40, 80, 150),
                    stop: 1 rgba(0, 30, 60, 200)
                );
                border-bottom: 2px solid {color};
            }}
        """)
