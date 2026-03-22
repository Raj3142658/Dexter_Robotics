from PyQt6.QtWidgets import QPushButton, QWidget, QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QLabel
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, Qt, pyqtProperty, QSequentialAnimationGroup, pyqtSignal, QPointF, QRectF, QSize, QPoint
from PyQt6.QtGui import QColor, QPixmap, QIcon, QPainter, QRadialGradient, QPainterPath
from .resize_handle import ResizeHandle

class GradientOverlay(QWidget):
    """Overlay widget that draws a radial gradient."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._radius_factor = 0.0
        self._opacity = 1.0
        
    @pyqtProperty(float)
    def radiusFactor(self): return self._radius_factor
    
    @radiusFactor.setter
    def radiusFactor(self, value):
        self._radius_factor = value
        self.update()
        
    @pyqtProperty(float)
    def opacityValue(self): return self._opacity
    
    @opacityValue.setter
    def opacityValue(self, value):
        self._opacity = value
        self.update()
        
    def paintEvent(self, event):
        if self._radius_factor <= 0.01 or self._opacity <= 0.005: return
        painter = QPainter()
        if not painter.begin(self): return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setOpacity(self._opacity)
            rect = self.rect()
            center = QPointF(rect.center())
            # Use icon size for gradient scaling
            icon_size = self.parent().size() if self.parent() else rect.size()
            max_radius = min(icon_size.width(), icon_size.height()) / 2.0
            radius = max_radius * self._radius_factor
            gradient = QRadialGradient(center, radius)
            gradient.setColorAt(0.0, QColor("#24e4f5")) 
            gradient.setColorAt(0.5, QColor("#19a7dd")) 
            gradient.setColorAt(1.0, QColor("#24008d")) 
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addEllipse(center, radius, radius)
            painter.setClipPath(path)
            painter.drawEllipse(rect.center(), int(radius), int(radius))
        finally:
            painter.end()

class SettingsButton(QPushButton):
    """Settings button with Double-Wrap Stability Architecture."""
    
    def __init__(self, icon_pre_path: str, icon_main_path: str, parent=None):
        super().__init__(parent)
        
        self.icon_pre = QPixmap(icon_pre_path)
        self.icon_main = QPixmap(icon_main_path)
        self.current_state = 'pre'
        self._glow_radius = 0.01
        self.movable = False
        self.is_dragging = False
        
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background-color: transparent; border: none; }")
        
        # --- STABILITY WRAPPER ARCHITECTURE ---
        # 1. Opacity Wrapper
        self.opacity_wrapper = QWidget(self)
        self.opacity_wrapper.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # 2. Content Container (Holds Icon and Glow)
        self.content_container = QWidget(self.opacity_wrapper)
        self.content_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # 3. Label for the actual Icon
        self.icon_label = QLabel(self.content_container)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setScaledContents(True)
        self.icon_label.setPixmap(self.icon_pre)
        
        # 4. Effects
        self.opacity_effect = QGraphicsOpacityEffect(self.opacity_wrapper)
        self.opacity_effect.setOpacity(0.8)
        self.opacity_wrapper.setGraphicsEffect(self.opacity_effect)
        
        self.glow_effect = QGraphicsDropShadowEffect(self.content_container)
        self.glow_effect.setColor(QColor(0, 243, 255))
        self.glow_effect.setBlurRadius(0.01)
        self.glow_effect.setOffset(0, 0)
        self.content_container.setGraphicsEffect(self.glow_effect)
        # ----------------------------------------
        
        # Create Overlay (Special effect)
        self.overlay = GradientOverlay(self.content_container)
        self.overlay.hide()
        
        # Animations
        self.radius_anim = QPropertyAnimation(self.overlay, b"radiusFactor")
        self.opacity_anim = QPropertyAnimation(self.overlay, b"opacityValue")
        
        self.glow_anim = QPropertyAnimation(self, b"glowRadius")
        self.glow_anim.setDuration(400)
        self.glow_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        
        # Resize Handle
        self.resize_handle = ResizeHandle(self)
        self.resize_handle.hide()

    @pyqtProperty(float)
    def glowRadius(self): return self._glow_radius

    @glowRadius.setter
    def glowRadius(self, value):
        self._glow_radius = max(0.01, value)
        self.glow_effect.setBlurRadius(self._glow_radius)

    def _max_glow_radius(self) -> float:
        """Return 0.88x of the icon radius based on current size."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return 22.0
        return 0.88 * (min(w, h) / 2.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, 'opacity_wrapper'):
            self.opacity_wrapper.setGeometry(0, 0, w, h)
        if hasattr(self, 'content_container'):
            self.content_container.setGeometry(0, 0, w, h)
        if hasattr(self, 'icon_label'):
            padding = 20
            self.icon_label.setGeometry(padding//2, padding//2, w - padding, h - padding)
        if hasattr(self, 'overlay'):
            self.overlay.setGeometry(0, 0, w, h)
        if hasattr(self, 'resize_handle'):
            self.resize_handle.move(w - 20, h - 20)
        
    def swap_icon(self, state):
        self.current_state = state
        self.icon_label.setPixmap(self.icon_main if state == 'main' else self.icon_pre)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.opacity_effect.setOpacity(0.999)
        
        if getattr(self, 'anim_group', None):
            self.anim_group.stop()
            
        self.overlay.show()
        self.overlay.opacityValue = 1.0 
        self.overlay.radiusFactor = 0.0 
        
        # Growth Animation
        self.radius_anim.setDuration(600)
        self.radius_anim.setStartValue(0.0)
        self.radius_anim.setEndValue(0.88)
        
        # Fade Out Animation
        self.opacity_anim.setDuration(800)
        self.opacity_anim.setStartValue(1.0)
        self.opacity_anim.setEndValue(0.0)
        
        # Glow Animation
        self.glow_anim.setStartValue(self._glow_radius)
        self.glow_anim.setEndValue(self._max_glow_radius())
        
        from PyQt6.QtCore import QParallelAnimationGroup
        self.anim_group = QParallelAnimationGroup(self)
        self.anim_group.addAnimation(self.radius_anim)
        self.anim_group.addAnimation(self.opacity_anim)
        self.anim_group.addAnimation(self.glow_anim)
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, lambda: self.swap_icon('main'))
        self.anim_group.start()
        
    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.opacity_effect.setOpacity(0.8)
        
        if getattr(self, 'anim_group', None):
            self.anim_group.stop()
            
        self.overlay.show()
        # Group 1: Fade In & Glow Out
        self.opacity_anim.setStartValue(self.overlay.opacityValue)
        self.opacity_anim.setEndValue(1.0)
        
        self.glow_anim.setStartValue(self._glow_radius)
        self.glow_anim.setEndValue(0.01)
        
        # Group 2: Shrink
        self.radius_anim.setStartValue(1.0)
        self.radius_anim.setEndValue(0.0)
        
        self.anim_group = QSequentialAnimationGroup(self)
        self.anim_group.addAnimation(self.opacity_anim)
        self.anim_group.addAnimation(self.radius_anim)
        
        # Start glow reduction in parallel with sequences
        self.glow_anim.start()
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, lambda: self.swap_icon('pre'))
        self.anim_group.start()
        
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

    def mouseMoveEvent(self, event):
        if getattr(self, 'movable', False) and getattr(self, 'is_dragging', False):
            if event.buttons() & Qt.MouseButton.LeftButton:
                new_pos = event.globalPosition().toPoint() - self.drag_start_pos
                self.move(new_pos.x(), new_pos.y())
                event.accept()

    def wheelEvent(self, event):
        if getattr(self, 'movable', False):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
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

            delta = event.angleDelta().y()
            if delta != 0:
                factor = 1.05 if delta > 0 else 0.95
                self.resize(int(self.width()*factor), int(self.height()*factor))
                self.positionChanged.emit()
                event.accept()
                return
        event.ignore()
                    
    positionChanged = pyqtSignal()
    
    def mouseReleaseEvent(self, event):
        if getattr(self, 'movable', False) and getattr(self, 'is_dragging', False):
            self.is_dragging = False
            self.positionChanged.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
