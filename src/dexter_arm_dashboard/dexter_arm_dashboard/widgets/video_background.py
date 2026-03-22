"""
Video Background Widget
Plays looping background video for the dashboard using OpenCV for reliable rendering.
Frame decoding runs on a worker thread to avoid blocking the UI.
"""

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QImage, QPixmap
from pathlib import Path
import cv2


class _VideoDecoder(QObject):
    """Decodes video frames on a background thread."""
    frameReady = pyqtSignal(QImage)

    def __init__(self, video_path: str, fps: float = 15.0):
        super().__init__()
        self._video_path = video_path
        self._interval = max(1, int(1000 / fps))
        self._cap = None
        self._timer = None
        self._running = False

    def start(self):
        self._cap = cv2.VideoCapture(self._video_path)
        if not self._cap.isOpened():
            print(f"[ERROR] Decoder: Failed to open video: {self._video_path}")
            return
        self._running = True
        self._timer = QTimer()
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self._decode_frame)
        self._timer.start()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.stop()
        if self._cap:
            self._cap.release()
            self._cap = None

    def set_fps(self, fps: float):
        self._interval = max(1, int(1000 / fps))
        if self._timer and self._timer.isActive():
            self._timer.setInterval(self._interval)

    def _decode_frame(self):
        if not self._running or self._cap is None or not self._cap.isOpened():
            return
        ret, frame = self._cap.read()
        if not ret:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        # QImage needs the data to stay alive; .copy() ensures ownership
        qi = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        self.frameReady.emit(qi)


class VideoBackground(QWidget):
    """Widget that plays a looping video using OpenCV frames on a QLabel.

    Decoding runs on a dedicated QThread at 15 FPS (configurable).
    Only the cheap setPixmap() runs on the main thread.
    """

    _TARGET_FPS = 15  # Background ambiance doesn't need 30 FPS

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)

        self.video_path = Path(video_path)

        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel(self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setScaledContents(True)
        self.layout.addWidget(self.video_label)

        # Worker thread for decoding
        self._thread = QThread()
        self._decoder = _VideoDecoder(str(self.video_path), self._TARGET_FPS)
        self._decoder.moveToThread(self._thread)

        self._thread.started.connect(self._decoder.start)
        self._decoder.frameReady.connect(self._on_frame)

        if self.video_path.exists():
            print(f"[INFO] Video loaded: {self.video_path.name} ({self._TARGET_FPS} FPS, threaded)")
        else:
            print(f"[ERROR] Video not found: {self.video_path}")

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_frame(self, image: QImage):
        """Receive decoded frame on main thread — cheap setPixmap only."""
        self.video_label.setPixmap(QPixmap.fromImage(image))

    # ── public API ────────────────────────────────────────────────────────

    def play(self):
        """Start playing."""
        if not self._thread.isRunning():
            self._thread.start()

    def pause(self):
        """Pause decoding (thread stays alive)."""
        self._decoder.stop()

    def resume(self):
        """Resume decoding after pause."""
        self._decoder.start()

    def stop(self):
        """Stop video and shut down thread."""
        self._decoder.stop()
        self._thread.quit()
        self._thread.wait(2000)

    def set_fps(self, fps: float):
        """Change decode FPS at runtime (e.g., slow down when trajectory active)."""
        self._decoder.set_fps(fps)

    def __del__(self):
        self.stop()
