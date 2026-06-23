"""
Camera feed display widget.
Renders BGR numpy frames efficiently via QImage, with overlay info.
Supports digital zoom via config and mouse wheel on the widget.
"""

from __future__ import annotations

import cv2
import numpy as np
import time
from PyQt5.QtWidgets import QWidget, QSizePolicy, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QPen

from src.logger import get_logger

logger = get_logger("cam_widget")


class CameraWidget(QWidget):
    """
    High-performance camera feed widget.
    • Uses QImage with BGR→RGB conversion (zero-copy when possible)
    • Maintains aspect ratio
    • Draws overlay: camera label, FPS, status badge, zoom level
    • Mouse wheel zooms in/out on the widget (digital zoom)
    """

    def __init__(self, cam_id: int, label: str = "", parent=None):
        super().__init__(parent)
        self.cam_id = cam_id
        self._label = label
        self._pixmap: QPixmap | None = None
        self._status = "Disconnected"
        self._connected = False
        self._fps = 0.0
        self._last_frame_time = 0.0
        self._fps_buf = []
        self._zoom = 1.0
        self._min_zoom = 1.0
        self._max_zoom = 4.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background:#0d0f14; border:1px solid #2a2d3a;")
        self.setFocusPolicy(Qt.WheelFocus)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom = min(self._max_zoom, self._zoom + 0.25)
        else:
            self._zoom = max(self._min_zoom, self._zoom - 0.25)
        self.update()
        event.accept()

    @pyqtSlot(np.ndarray)
    def update_frame(self, frame_bgr: np.ndarray):
        """Accept a BGR frame and refresh the display."""
        now = time.monotonic()
        dt = now - self._last_frame_time
        if dt > 0:
            self._fps_buf.append(1.0 / dt)
            if len(self._fps_buf) > 20:
                self._fps_buf.pop(0)
            self._fps = sum(self._fps_buf) / len(self._fps_buf)
        self._last_frame_time = now

        # BGR → RGB
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def set_status(self, message: str, connected: bool):
        self._status = message
        self._connected = connected
        self.update()

    def set_label(self, label: str):
        self._label = label
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        W, H = self.width(), self.height()

        if self._pixmap is None:
            painter.fillRect(0, 0, W, H, QColor(13, 15, 20))
            painter.setPen(QColor(60, 65, 85))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             f"Camera {self.cam_id}\nNo Signal")
        else:
            pm = self._pixmap
            if self._zoom > 1.0:
                sw = int(pm.width() / self._zoom)
                sh = int(pm.height() / self._zoom)
                sx = (pm.width() - sw) // 2
                sy = (pm.height() - sh) // 2
                pm = pm.copy(sx, sy, sw, sh)
                pm = pm.scaled(W, H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                pm = pm.scaled(W, H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x  = (W - pm.width())  // 2
            y  = (H - pm.height()) // 2
            painter.drawPixmap(x, y, pm)

        # Top-left: camera label
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        painter.setPen(QColor(220, 220, 255))
        painter.drawText(8, 20, self._label or f"CAM {self.cam_id}")

        # Top-right: FPS
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor(100, 220, 120))
        fps_txt = f"{self._fps:.1f} fps"
        painter.drawText(W - 70, 20, fps_txt)

        # Zoom indicator (top-right below FPS)
        if self._zoom > 1.0:
            painter.setPen(QColor(255, 215, 64))
            painter.drawText(W - 65, 34, f"Z:{self._zoom:.1f}x")

        # Bottom-left: status badge
        badge_color = QColor(0, 200, 80) if self._connected else QColor(220, 50, 50)
        painter.setBrush(badge_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(8, H - 20, 10, 10)
        painter.setPen(QColor(220, 220, 220))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(24, H - 10, self._status)

        painter.end()
