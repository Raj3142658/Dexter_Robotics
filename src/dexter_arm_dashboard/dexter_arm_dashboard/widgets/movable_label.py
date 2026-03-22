from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect, QWidget, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QMouseEvent, QColor
from .resize_handle import ResizeHandle

class MovableLabel(QLabel):
    """
    A stable HUD label that can be dragged and positioned manually.
    Supports "Double-Wrap" architecture for nested graphics effects (Opacity + Glow).
    """
    
    EDIT_STYLE = "\nborder: 2px dashed #00FFFF; background-color: rgba(255, 255, 255, 20);"
    
    def __init__(self, parent=None, fixed_opacity=None, enable_glow=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setScaledContents(True)
        self.movable = False
        self.is_dragging = False
        self.drag_start_pos = QPoint()
        self.fixed_opacity = fixed_opacity
        self._glow_radius = 0.01
        self.enable_glow = enable_glow
        
        # --- STABILITY WRAPPER ARCHITECTURE ---
        # 1. Opacity Wrapper
        self.opacity_wrapper = QWidget(self)
        self.opacity_wrapper.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # 2. Content Label (Nested inside wrapper)
        # We use a separate label for content to isolate the glow effect
        self.content_label = QLabel(self.opacity_wrapper)
        self.content_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.content_label.setScaledContents(True)
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 3. Apply Opacity Effect to whole widget (match DisplayPanel behavior)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        initial_opacity = fixed_opacity if fixed_opacity is not None else 0.8
        self.base_opacity = initial_opacity
        self.opacity_effect.setOpacity(initial_opacity)
        self.setGraphicsEffect(self.opacity_effect)

        # 4. Apply Glow Effect to Content (only when enabled)
        self.glow_effect = None
        if self.enable_glow:
            self.glow_effect = QGraphicsDropShadowEffect(self.content_label)
            self.glow_effect.setColor(QColor(0, 243, 255)) # Cyan
            self.glow_effect.setBlurRadius(0.01)
            self.glow_effect.setOffset(0, 0)
            self.content_label.setGraphicsEffect(self.glow_effect)
        # ----------------------------------------
        
        # Resize Handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()
        
        # Glow Animation
        self.glow_anim = QPropertyAnimation(self, b"glowRadius")
        self.glow_anim.setDuration(300)
        self.glow_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    @pyqtProperty(float)
    def glowRadius(self): return self._glow_radius
    
    @glowRadius.setter
    def glowRadius(self, value):
        self._glow_radius = max(0.01, value)
        if self.glow_effect is not None:
            self.glow_effect.setBlurRadius(self._glow_radius)

    def setPixmap(self, pixmap):
        """Forward pixmap to inner content label."""
        self.content_label.setPixmap(pixmap)
        super().setPixmap(pixmap) # Still set it on parent so sizeHint works if needed

    def setText(self, text):
        """Forward text to inner content label."""
        self.content_label.setText(text)
        super().setText(text)

    def set_movable(self, movable: bool):
        self.movable = movable
        current_style = self.styleSheet().replace(self.EDIT_STYLE, "")
        if movable:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.setStyleSheet(current_style + self.EDIT_STYLE)
            self.resize_handle.show()
            self.resize_handle.raise_()
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setStyleSheet(current_style)
            self.resize_handle.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, 'opacity_wrapper'):
            self.opacity_wrapper.setGeometry(0, 0, w, h)
        if hasattr(self, 'content_label'):
            self.content_label.setGeometry(0, 0, w, h)
        if hasattr(self, 'resize_handle'):
            self.resize_handle.move(w - 20, h - 20)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.fixed_opacity is None and self.enable_glow:
            self.glow_anim.setStartValue(self._glow_radius)
            self.glow_anim.setEndValue(20.0)
            self.glow_anim.start()
        
    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.fixed_opacity is None and self.enable_glow:
            self.glow_anim.setStartValue(self._glow_radius)
            self.glow_anim.setEndValue(0.01)
            self.glow_anim.start()

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

    positionChanged = pyqtSignal()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.movable and self.is_dragging:
            self.is_dragging = False
            self.positionChanged.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.movable:
            delta = event.angleDelta().y()
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                current_opacity = self.opacity_effect.opacity()
                step = 0.05
                if delta > 0:
                    new_opacity = min(0.999, current_opacity + step)
                else:
                    new_opacity = max(0.1, current_opacity - step)
                self.opacity_effect.setOpacity(new_opacity)
                self.base_opacity = new_opacity
                event.accept()
            else:
                super().wheelEvent(event)
        else:
            super().wheelEvent(event)
