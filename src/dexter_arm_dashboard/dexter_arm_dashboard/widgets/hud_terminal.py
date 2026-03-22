"""
HUD Terminal Widget
A terminal-like widget with HUD theme for displaying logs within the dashboard.
Supports color-coded logging (error, warning, info) and status bar with counts.
"""

import re
from collections import Counter
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QLabel,
    QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QPalette


class HudTerminal(QWidget):
    """
    A terminal-like widget with HUD theming for displaying process output.
    """
    
    # Signal emitted when log count changes
    logCountChanged = pyqtSignal(dict)  # dict with 'error', 'warning', 'critical', 'info' counts
    
    _MIN_FONT_SIZE = 12
    _DEFAULT_FONT_SIZE = 14
    _MAX_FONT_SIZE = 22

    def __init__(self, parent=None, max_lines: int = 5000):
        super().__init__(parent)
        self.max_lines = max_lines
        self.log_counts = Counter()
        self._font_size = self._DEFAULT_FONT_SIZE

        # Output batching buffer — lines are queued and flushed every 100ms
        self._line_buffer: list = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(100)
        self._flush_timer.timeout.connect(self._flush_buffer)
        
        # Color scheme - HUD theme
        self.colors = {
            'error': '#FF4444',      # Red for errors
            'warning': '#FFAA00',    # Orange/yellow for warnings
            'critical': '#FF0088',   # Magenta for critical
            'info': '#00F3FF',       # Cyan for info
            'debug': '#88FF88',      # Green for debug
            'normal': '#AAAAAA',     # Gray for normal text
        }
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the HUD terminal UI."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Terminal output area
        self.terminal = QPlainTextEdit(self)
        self.terminal.setReadOnly(True)
        self.terminal.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.terminal.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Apply terminal styling
        self.terminal.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: rgba(0, 10, 26, 240);
                border: 1px solid #1a4a6e;
                border-radius: 4px;
                font-family: "Courier New", "Ubuntu Mono", monospace;
                font-size: {self._font_size}px;
                color: {self.colors['normal']};
            }}
            QScrollBar:vertical {{
                background: rgba(0, 20, 40, 180);
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00F3FF, stop:1 #0088AA);
                border-radius: 5px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #44FFFF, stop:1 #00AAAA);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        layout.addWidget(self.terminal, 1)
        
        # Status bar for log counts
        self.status_bar = QFrame(self)
        self.status_bar.setFixedHeight(28)
        self.status_bar.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(0, 20, 40, 220);
                border-top: 1px solid #1a4a6e;
                border-radius: 0px;
            }}
        """)
        
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(15)
        
        # Status labels
        self.status_labels = {}
        
        # Title/Label for the terminal
        self.title_label = QLabel("TERMINAL OUTPUT")
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: #00F3FF;
                font-size: 11px;
                font-weight: bold;
                font-family: "Orbitron", "Rajdhani", sans-serif;
                letter-spacing: 2px;
            }}
        """)
        status_layout.addWidget(self.title_label)
        
        status_layout.addStretch()
        
        # Status indicators
        status_items = [
            ('critical', 'CRIT'),
            ('error', 'ERR'),
            ('warning', 'WARN'),
            ('info', 'INFO'),
        ]
        
        for key, label in status_items:
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(5, 2, 5, 2)
            container_layout.setSpacing(5)
            
            # Colored dot
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {self.colors[key]}; font-size: 10px;")
            
            # Count label
            count_label = QLabel(f"0")
            count_label.setObjectName(f"count_{key}")
            count_label.setStyleSheet(f"""
                QLabel {{
                    color: {self.colors[key]};
                    font-size: 11px;
                    font-weight: bold;
                    font-family: "Courier New", monospace;
                    min-width: 30px;
                }}
            """)
            
            container_layout.addWidget(dot)
            container_layout.addWidget(count_label)
            
            self.status_labels[key] = count_label
            status_layout.addWidget(container)
        
        layout.addWidget(self.status_bar)
        
        # Default format for text
        self.default_format = QTextCharFormat()
        self.default_format.setForeground(QColor(self.colors['normal']))
    
    def append_log(self, text: str):
        """
        Queue a log line for batched rendering (flushed every 100ms).
        
        Args:
            text: The log text to append
        """
        log_level = self._detect_log_level(text)
        self.log_counts[log_level] += 1
        self._line_buffer.append((text, log_level))
        # Start the flush timer if not already running
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_buffer(self):
        """Flush all queued lines in a single cursor batch (one repaint)."""
        if not self._line_buffer:
            self._flush_timer.stop()
            return

        lines = self._line_buffer
        self._line_buffer = []

        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Batch-insert all lines under one cursor operation
        for text, log_level in lines:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.colors.get(log_level, self.colors['normal'])))
            cursor.insertText(text + '\n', fmt)

        # Single scroll + trim after the batch
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        self._trim_lines()
        self._update_status_bar()

        # Stop timer if buffer is empty
        if not self._line_buffer:
            self._flush_timer.stop()
    
    def append_plain(self, text: str):
        """
        Append plain text without color detection.
        
        Args:
            text: The text to append
        """
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + '\n', self.default_format)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        self._trim_lines()
    
    def _detect_log_level(self, text: str) -> str:
        """
        Detect log level from text content.
        
        Args:
            text: The log text
            
        Returns:
            Log level string: 'critical', 'error', 'warning', 'info', 'debug', or 'normal'
        """
        text_lower = text.lower()
        
        # Check for critical
        if any(keyword in text_lower for keyword in ['fatal', 'critical', 'crit']):
            return 'critical'
        
        # Check for error
        if any(keyword in text_lower for keyword in ['error', 'err', 'failed', 'failure', 'exception']):
            return 'error'
        
        # Check for warning
        if any(keyword in text_lower for keyword in ['warn', 'warning', 'warn:']):
            return 'warning'
        
        # Check for info
        if any(keyword in text_lower for keyword in ['info', 'info:']):
            return 'info'
        
        # Check for debug
        if any(keyword in text_lower for keyword in ['debug', 'dbg']):
            return 'debug'
        
        return 'normal'
    
    def _trim_lines(self):
        """Trim old lines if exceeding max_lines."""
        doc = self.terminal.document()
        if doc.blockCount() > self.max_lines:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(doc.blockCount() - self.max_lines):
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
    
    def _update_status_bar(self):
        """Update the status bar with current counts."""
        for key, label in self.status_labels.items():
            count = self.log_counts.get(key, 0)
            label.setText(str(count))
        
        # Emit signal with counts
        self.logCountChanged.emit(dict(self.log_counts))
    
    def clear(self):
        """Clear the terminal output and reset counts."""
        self.terminal.clear()
        self.log_counts.clear()
        self._update_status_bar()
    
    def set_title(self, title: str):
        """
        Set the terminal title.
        
        Args:
            title: New title for the terminal
        """
        self.title_label.setText(title.upper())
    
    def get_counts(self) -> dict:
        """
        Get current log counts.
        
        Returns:
            Dictionary with log level counts
        """
        return dict(self.log_counts)
    
    def set_max_lines(self, max_lines: int):
        """
        Set maximum number of lines to keep.
        
        Args:
            max_lines: Maximum number of lines
        """
        self.max_lines = max_lines
        self._trim_lines()

    def set_font_size(self, size: int) -> None:
        """Set terminal font size."""
        size = max(self._MIN_FONT_SIZE, min(self._MAX_FONT_SIZE, size))
        if size == self._font_size:
            return
        self._font_size = size
        font = self.terminal.font()
        font.setPointSize(size)
        self.terminal.setFont(font)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Dynamically scale font with widget height."""
        super().resizeEvent(event)
        h = event.size().height()
        # Scale: 14px at ≤500px height → up to 20px at 1200px height
        new_size = int(self._DEFAULT_FONT_SIZE + max(0, h - 500) * 6 / 700)
        new_size = max(self._MIN_FONT_SIZE, min(self._MAX_FONT_SIZE, new_size))
        if new_size != self._font_size:
            self._font_size = new_size
            font = self.terminal.font()
            font.setPointSize(new_size)
            self.terminal.setFont(font)


class HudTerminalWindow(QWidget):
    """
    A standalone window version of HUD Terminal that can be embedded 
    or shown as a separate window.
    """
    
    def __init__(self, title: str = "Terminal Output", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(800, 500)
        self.resize(900, 600)
        
        # Apply HUD theme
        self.setStyleSheet(f"""
            QWidget {{
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.2, radius: 1.1,
                    fx: 0.5, fy: 0.05,
                    stop: 0 #142742,
                    stop: 0.55 #0d1626,
                    stop: 1 #070c16
                );
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.terminal = HudTerminal(self)
        layout.addWidget(self.terminal)
    
    def append_log(self, text: str):
        """Append log with auto color detection."""
        self.terminal.append_log(text)
    
    def append_plain(self, text: str):
        """Append plain text."""
        self.terminal.append_plain(text)
    
    def clear(self):
        """Clear terminal."""
        self.terminal.clear()
    
    def set_title(self, title: str):
        """Set terminal title."""
        self.terminal.set_title(title)
        self.setWindowTitle(title)
