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
        self._pan_offset_x = 0.0
        self._pan_offset_y = 0.0
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._pan_start_x = 0.0
        self._pan_start_y = 0.0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background:#0d0f14; border:1px solid #2a2d3a;")
        self.setFocusPolicy(Qt.WheelFocus)
        self.setMouseTracking(True)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom = min(self._max_zoom, self._zoom + 0.25)
        else:
            self._zoom = max(self._min_zoom, self._zoom - 0.25)
        # Clamp pan offsets after zoom change
        self._clamp_pan()
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._zoom > 1.0 and self._pixmap is not None:
            self._dragging = True
            self._drag_start_x = event.x()
            self._drag_start_y = event.y()
            self._pan_start_x = self._pan_offset_x
            self._pan_start_y = self._pan_offset_y
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            dx = event.x() - self._drag_start_x
            dy = event.y() - self._drag_start_y
            self._pan_offset_x = self._pan_start_x + dx
            self._pan_offset_y = self._pan_start_y + dy
            self._clamp_pan()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _clamp_pan(self):
        if self._pixmap is None:
            return
        W, H = self.width(), self.height()
        # Calculate the max pan offset (negative = left/up, positive = right/down)
        zoomed_w = self._pixmap.width() * self._zoom
        zoomed_h = self._pixmap.height() * self._zoom
        if zoomed_w > W:
            max_pan = (zoomed_w - W) // 2
            self._pan_offset_x = max(-max_pan, min(max_pan, self._pan_offset_x))
        else:
            self._pan_offset_x = 0
        if zoomed_h > H:
            max_pan = (zoomed_h - H) // 2
            self._pan_offset_y = max(-max_pan, min(max_pan, self._pan_offset_y))
        else:
            self._pan_offset_y = 0

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
                cx = pm.width() // 2
                cy = pm.height() // 2
                # Apply pan offset to the crop center
                pan_scale = 1.0 / self._zoom
                offset_x = int(self._pan_offset_x * pan_scale)
                offset_y = int(self._pan_offset_y * pan_scale)
                sx = cx - sw // 2 - offset_x
                sy = cy - sh // 2 - offset_y
                sx = max(0, min(sx, pm.width() - sw))
                sy = max(0, min(sy, pm.height() - sh))
                pm = pm.copy(sx, sy, sw, sh)
                pm = pm.scaled(W, H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                pm = pm.scaled(W, H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._pan_offset_x = 0
                self._pan_offset_y = 0
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
