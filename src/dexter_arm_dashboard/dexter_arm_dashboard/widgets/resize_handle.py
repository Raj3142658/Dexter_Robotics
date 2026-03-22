
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor

class ResizeHandle(QWidget):
    """Small handle for resizing widgets interactively."""
    
    # Signal emitted when parent should be resized (relative delta)
    resizeRequested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setStyleSheet("background: transparent;")
        self._dragging = False
        self._last_pos = QPoint()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Use a more visible cyan with slight opacity
        painter.setPen(QPen(QColor(0, 255, 255, 200), 2))
        # Draw techy triangular corner lines
        w, h = self.width(), self.height()
        # Three diagonal lines in the corner
        painter.drawLine(w-4, h-12, w-12, h-4)
        painter.drawLine(w-4, h-8, w-8, h-4)
        painter.drawPoint(w-4, h-4)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.globalPosition().toPoint()
            event.accept()
            
    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._last_pos
            self._last_pos = event.globalPosition().toPoint()
            
            p = self.parentWidget()
            if p:
                new_w = max(40, p.width() + delta.x())
                new_h = max(30, p.height() + delta.y())
                p.resize(new_w, new_h)
                # Emit signal if needed for saving
                if hasattr(p, 'positionChanged'):
                    p.positionChanged.emit()
            event.accept()
            
    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()
