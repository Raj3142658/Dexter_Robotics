from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPixmap
from PyQt6.QtCore import Qt
from pathlib import Path


class BackgroundFill(QWidget):
    """Background fill layer supporting color, gradient, or image - fills ONLY the letterbox margins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.mode = "color"
        self.color = QColor("#0A0E1A")
        self.color2 = QColor("#000000")
        self.image_path = None
        self.pixmap = None
        self.background_rect = None  # 16:10 letterbox rect

    def set_fill(self, mode, color, color2, image_path):
        self.mode = mode or "color"
        self.color = QColor(color) if color else QColor("#0A0E1A")
        self.color2 = QColor(color2) if color2 else QColor("#000000")
        self.image_path = Path(image_path) if image_path else None
        if self.mode == "image" and self.image_path and self.image_path.exists():
            self.pixmap = QPixmap(str(self.image_path))
        else:
            self.pixmap = None
        self.update()

    def set_background_rect(self, x, y, w, h):
        """Set the 16:10 background rect - fill will only paint outside this area."""
        self.background_rect = (x, y, w, h)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        full_rect = self.rect()
        
        # Fill the entire widget first
        if self.mode == "gradient":
            gradient = QLinearGradient(0, 0, 0, full_rect.height())
            gradient.setColorAt(0.0, self.color)
            gradient.setColorAt(1.0, self.color2)
            painter.fillRect(full_rect, gradient)
        elif self.mode == "image" and self.pixmap and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                full_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = int((full_rect.width() - scaled.width()) / 2)
            y = int((full_rect.height() - scaled.height()) / 2)
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(full_rect, self.color)
