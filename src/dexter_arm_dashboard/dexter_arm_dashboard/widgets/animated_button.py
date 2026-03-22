"""
Animated Button Base Class
Provides base functionality for all animated buttons in the dashboard.
"""

from PyQt6.QtWidgets import QPushButton, QGraphicsDropShadowEffect, QLabel, QGraphicsOpacityEffect, QWidget, QVBoxLayout
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, Qt, pyqtProperty, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QIcon
from pathlib import Path
from .resize_handle import ResizeHandle


class AnimatedButton(QPushButton):
    """Base class for animated buttons with glow effects."""
    
    def __init__(self, icon_path: str = None, parent=None, icon_size: tuple = None):
        """
        Initialize animated button.
        """
        super().__init__(parent)
        
        self.icon_path = Path(icon_path) if icon_path else None
        self.target_icon_size = icon_size
        self._glow_radius = 0.01  # Never exactly 0
        self._scale = 1.0
        self._is_active = False 
        self._glow_locked = False
        self.movable = False
        self.is_dragging = False
        self.drag_start_pos = QPoint()
        
        # Set up button appearance - completely transparent
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background-color: transparent; border: none; }")
        
        # --- STABILITY WRAPPER ARCHITECTURE ---
        # 1. First Child: Opacity Wrapper (No effect on parent button!)
        self.opacity_wrapper = QWidget(self)
        self.opacity_wrapper.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # 2. Second Child: Icon Label (Inside wrapper)
        self.icon_label = QLabel(self.opacity_wrapper)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setScaledContents(True)
        
        # 3. Apply Opacity Effect to Wrapper
        self.opacity_effect = QGraphicsOpacityEffect(self.opacity_wrapper)
        self.opacity_effect.setOpacity(0.8)
        self.opacity_wrapper.setGraphicsEffect(self.opacity_effect)
        
        # 4. Apply Glow Effect to Icon Label (Nested)
        self.glow_effect = QGraphicsDropShadowEffect(self.icon_label)
        self.glow_effect.setColor(QColor(0, 243, 255))
        self.glow_effect.setBlurRadius(0.01)
        self.glow_effect.setOffset(0, 0)
        self.icon_label.setGraphicsEffect(self.glow_effect)
        # ----------------------------------------
        
        # Resize Handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()
        
        # Animations
        self.glow_animation = QPropertyAnimation(self, b"glowRadius")
        self.glow_animation.setDuration(300)
        self.glow_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        self.scale_animation = QPropertyAnimation(self, b"buttonScale")
        self.scale_animation.setDuration(200)
        self.scale_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        # Load icon if provided
        if self.icon_path and self.icon_path.exists():
            self.original_pixmap = QPixmap(str(self.icon_path))
        else:
            self.original_pixmap = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_geometry()

    def setGeometry(self, *args):
        super().setGeometry(*args)
        self._sync_geometry()

    def _sync_geometry(self):
        """Update child geometry to match button size."""
        w, h = self.width(), self.height()
        if hasattr(self, 'opacity_wrapper'):
            self.opacity_wrapper.setGeometry(0, 0, w, h)
        if hasattr(self, 'icon_label'):
            self.icon_label.setGeometry(0, 0, w, h)
        if hasattr(self, 'resize_handle'):
            self.resize_handle.move(w - 20, h - 20)
        self._update_icon()

    def _update_icon(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            padding = max(6, int(min(self.width(), self.height()) * 0.12))
            w = max(10, self.width() - padding)
            h = max(10, self.height() - padding)
            
            scaled_pixmap = self.original_pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.icon_label.setPixmap(scaled_pixmap)

    @pyqtProperty(float)
    def glowRadius(self): return self._glow_radius
    
    @glowRadius.setter
    def glowRadius(self, value):
        self._glow_radius = max(0.01, value)
        self.glow_effect.setBlurRadius(self._glow_radius)
    
    @pyqtProperty(float)
    def buttonScale(self): return self._scale
    
    @buttonScale.setter
    def buttonScale(self, value):
        self._scale = value
    
    def enterEvent(self, event):
        super().enterEvent(event)
        # Use 0.999 instead of 1.0 for driver stability
        self.opacity_effect.setOpacity(0.999)
        
        if not self._is_active and not self._glow_locked:
            self.glow_animation.setStartValue(self._glow_radius)
            self.glow_animation.setEndValue(20.0)
            self.glow_animation.start()
    
    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._is_active:
            self.opacity_effect.setOpacity(0.8)
            
        if not self._is_active and not self._glow_locked:
            self.glow_animation.setStartValue(self._glow_radius)
            self.glow_animation.setEndValue(0.01)
            self.glow_animation.start()
    
    def set_movable(self, movable: bool):
        self.movable = movable
        if movable:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.setStyleSheet("QPushButton { background-color: rgba(0, 255, 255, 30); border: 2px dashed #00FFFF; }")
            self.resize_handle.show()
            self.resize_handle.raise_()
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setStyleSheet("QPushButton { background-color: transparent; border: none; }")
            self.resize_handle.hide()
            
    def mousePressEvent(self, event):
        if getattr(self, 'movable', False):
            if event.button() == Qt.MouseButton.LeftButton:
                self.is_dragging = True
                self.drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
        else:
            super().mousePressEvent(event)
            self.scale_animation.setStartValue(self._scale)
            self.scale_animation.setEndValue(0.9)
            self.scale_animation.start()
            
    def mouseMoveEvent(self, event):
        if getattr(self, 'movable', False) and getattr(self, 'is_dragging', False):
            if event.buttons() & Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self.drag_start_pos
                self.move(new_pos.x(), new_pos.y())
                event.accept()
        else:
            super().mouseMoveEvent(event)
            
    positionChanged = pyqtSignal()

    def wheelEvent(self, event):
        if self.movable and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y()
            current_opacity = self.opacity_effect.opacity()
            step = 0.05
            if delta > 0:
                new_opacity = min(0.999, current_opacity + step)
            else:
                new_opacity = max(0.1, current_opacity - step)
            self.opacity_effect.setOpacity(new_opacity)
            event.accept()
            return
        event.ignore()
            
    def mouseReleaseEvent(self, event):
        if getattr(self, 'movable', False) and getattr(self, 'is_dragging', False):
            self.is_dragging = False
            self.positionChanged.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            self.scale_animation.setStartValue(self._scale)
            self.scale_animation.setEndValue(1.0)
            self.scale_animation.start()

    def set_active(self, active: bool):
        self._is_active = active
        self._glow_locked = active
        self.glowRadius = 20.0 if active else 0.01
        self.opacity_effect.setOpacity(0.999 if active else 0.8)
