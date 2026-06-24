"""
Camera worker thread.
Connects to Hikvision RTSP streams (6MP), handles reconnection,
digital zoom crop, and emits frames via Qt signals.
"""

import os
import cv2
import numpy as np
import time
import traceback
from urllib.parse import urlparse, urlunparse
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from src.logger import get_logger
from src.config_manager import CameraConfig

logger = get_logger("camera")


def _mask_url(url: str) -> str:
    """Strip password from RTSP URL for safe logging."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


_STALE_FRAME_TIMEOUT = 5.0  # seconds without a frame before declaring stream stale


class CameraWorker(QThread):
    """Captures frames from RTSP and emits them as numpy arrays."""

    frame_ready   = pyqtSignal(int, np.ndarray)   # (cam_id, frame_bgr)
    status_change = pyqtSignal(int, str, bool)     # (cam_id, message, is_connected)
    error         = pyqtSignal(int, str)           # (cam_id, message)

    def __init__(self, cam_id: int, cfg: CameraConfig, parent=None):
        super().__init__(parent)
        self.cam_id = cam_id
        self.cfg    = cfg
        self._stop  = False
        self._pause = False
        self._mutex = QMutex()
        self._cap: cv2.VideoCapture | None = None
        self.connected = False
        self.fps_actual = 0.0
        self._frame_count = 0
        self._last_frame_time = 0.0

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #
    def stop(self):
        with QMutexLocker(self._mutex):
            self._stop = True

    def pause(self):
        with QMutexLocker(self._mutex):
            self._pause = True

    def resume(self):
        with QMutexLocker(self._mutex):
            self._pause = False

    def update_config(self, cfg: CameraConfig):
        with QMutexLocker(self._mutex):
            self.cfg = cfg

    # ------------------------------------------------------------------ #
    #  Thread entry                                                        #
    # ------------------------------------------------------------------ #
    def run(self):
        safe_url = _mask_url(self.cfg.rtsp_url)
        logger.info(f"[CAM{self.cam_id}] Thread started — {safe_url}")
        while not self._should_stop():
            if self._is_paused():
                time.sleep(0.1)
                continue
            if not self._connect():
                self.status_change.emit(self.cam_id, "Reconnecting…", False)
                time.sleep(self.cfg.reconnect_delay)
                continue
            try:
                self._capture_loop()
            except Exception as e:
                logger.error(f"[CAM{self.cam_id}] Capture loop crashed: {e}")
                traceback.print_exc()
            finally:
                self._release()

        self._release()
        logger.info(f"[CAM{self.cam_id}] Thread stopped")

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #
    def _should_stop(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stop

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._pause

    def _connect(self) -> bool:
        self._release()
        url = self.cfg.rtsp_url
        safe_url = _mask_url(url)
        logger.info(f"[CAM{self.cam_id}] Connecting → {safe_url}")
        cap = None
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, self.cfg.buffer_size)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"H264"))
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            if not cap.isOpened():
                logger.warning(f"[CAM{self.cam_id}] cap not opened")
                cap.release()
                return False
            self._cap = cap
            self._last_frame_time = time.time()
            self.connected = True
            self.status_change.emit(self.cam_id, "Connected", True)
            logger.info(f"[CAM{self.cam_id}] Connected OK")
            return True
        except Exception as e:
            logger.error(f"[CAM{self.cam_id}] Connect exception: {e}")
            if cap is not None:
                cap.release()
            return False

    def _capture_loop(self):
        fps_timer = time.time()
        fps_frames = 0
        consecutive_fails = 0

        while not self._should_stop():
            if self._is_paused():
                time.sleep(0.05)
                continue

            if self._cap is None or not self._cap.isOpened():
                break

            # Stale frame watchdog
            if time.time() - self._last_frame_time > _STALE_FRAME_TIMEOUT:
                logger.warning(f"[CAM{self.cam_id}] No frame for {_STALE_FRAME_TIMEOUT}s — reconnecting")
                self.connected = False
                self.status_change.emit(self.cam_id, "Stream stalled", False)
                break

            try:
                ret, frame = self._cap.read()
            except Exception as e:
                logger.error(f"[CAM{self.cam_id}] Read exception: {e}")
                consecutive_fails += 1
                if consecutive_fails >= 10:
                    self.connected = False
                    self.status_change.emit(self.cam_id, "Stream lost", False)
                    break
                time.sleep(0.05)
                continue

            if not ret or frame is None:
                consecutive_fails += 1
                logger.warning(f"[CAM{self.cam_id}] Read fail #{consecutive_fails}")
                if consecutive_fails >= 10:
                    self.connected = False
                    self.status_change.emit(self.cam_id, "Stream lost", False)
                    break
                time.sleep(0.05)
                continue

            consecutive_fails = 0
            self._frame_count += 1
            fps_frames += 1
            self._last_frame_time = time.time()

            # Compute actual FPS every second
            elapsed = time.time() - fps_timer
            if elapsed >= 1.0:
                self.fps_actual = fps_frames / elapsed
                fps_frames = 0
                fps_timer = time.time()

            # Apply digital zoom (centre crop)
            frame = self._apply_zoom(frame)

            self.frame_ready.emit(self.cam_id, frame)

    def _apply_zoom(self, frame: np.ndarray) -> np.ndarray:
        z = max(1.0, self.cfg.digital_zoom)
        if z == 1.0:
            return frame
        h, w = frame.shape[:2]
        new_w = int(w / z)
        new_h = int(h / z)
        x1 = (w - new_w) // 2
        y1 = (h - new_h) // 2
        cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    def _release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self.connected = False


# ------------------------------------------------------------------ #
#  Video-file worker (loops a local mp4 for recorded feeds)          #
# ------------------------------------------------------------------ #
class VideoFileWorker(QThread):
    """Reads frames from a local video file and loops it forever.
    Frame rate is throttled to prevent flooding the pipeline and crashing."""

    frame_ready   = pyqtSignal(int, np.ndarray)
    status_change = pyqtSignal(int, str, bool)
    error         = pyqtSignal(int, str)

    _TARGET_FPS = 15

    def __init__(self, cam_id: int, path: str, cfg=None, parent=None):
        super().__init__(parent)
        self.cam_id = cam_id
        self.path   = path
        self._cfg   = cfg
        self._stop  = False
        self.connected = True
        self.fps_actual = 0.0
        self._frame_count = 0

    def stop(self):
        self._stop = True

    def pause(self): pass
    def resume(self): pass

    def _apply_zoom(self, frame):
        z = max(1.0, getattr(self._cfg, 'digital_zoom', 1.0))
        if z == 1.0:
            return frame
        h, w = frame.shape[:2]
        nw, nh = int(w / z), int(h / z)
        x1, y1 = (w - nw) // 2, (h - nh) // 2
        return cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h), interpolation=cv2.INTER_LINEAR)

    def run(self):
        self.status_change.emit(self.cam_id, f"Playing {os.path.basename(self.path)}", True)
        while not self._stop:
            cap = None
            try:
                cap = cv2.VideoCapture(self.path)
                if not cap.isOpened():
                    self.error.emit(self.cam_id, f"Cannot open {self.path}")
                    self.status_change.emit(self.cam_id, "File error", False)
                    return
                t0 = time.time()
                frame_idx = 0
                while not self._stop:
                    t_frame = time.time()
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break
                    self._frame_count += 1
                    frame_idx += 1
                    if frame_idx % 30 == 0:
                        elapsed = time.time() - t0
                        self.fps_actual = frame_idx / elapsed if elapsed > 0 else 0
                    self.frame_ready.emit(self.cam_id, self._apply_zoom(frame))
                    # Throttle to target FPS to prevent flooding the pipeline
                    elapsed_frame = time.time() - t_frame
                    sleep_needed = (1.0 / self._TARGET_FPS) - elapsed_frame
                    if sleep_needed > 0:
                        time.sleep(sleep_needed)
            except Exception as e:
                logger.error(f"[VIDEO{self.cam_id}] Error: {e}")
                traceback.print_exc()
            finally:
                if cap is not None:
                    try: cap.release()
                    except: pass
        self.status_change.emit(self.cam_id, "Stopped", False)

# ------------------------------------------------------------------ #
#  Demo / test frame generator (used when no camera is connected)     #
# ------------------------------------------------------------------ #
class DemoFrameWorker(QThread):
    """
    Generates synthetic frames that simulate a moving chassis frame
    on a conveyor belt. Used when no real RTSP camera is available.
    """

    frame_ready   = pyqtSignal(int, np.ndarray)
    status_change = pyqtSignal(int, str, bool)
    error         = pyqtSignal(int, str)

    def __init__(self, cam_id: int, parent=None):
        super().__init__(parent)
        self.cam_id = cam_id
        self._stop  = False
        self.connected = True
        self.fps_actual = 15.0
        self._frame_count = 0

    def stop(self):
        self._stop = True

    def pause(self): pass
    def resume(self): pass

    def run(self):
        self.status_change.emit(self.cam_id, "DEMO MODE", True)
        offset = 0
        hold_frames = 0
        while not self._stop:
            frame = self._generate_frame(offset)
            self.frame_ready.emit(self.cam_id, frame)
            bx = (1280 - offset) % 1680 - 200
            if hold_frames > 0:
                hold_frames -= 1
            elif 140 < bx < 240:
                hold_frames = 90  # detection window ~6s (90 frames @ 15fps)
            offset = (offset + 6) % 3072
            self._frame_count += 1
            time.sleep(1 / 15)

    def _generate_frame(self, offset: int) -> np.ndarray:
        W, H = 1280, 720
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        frame[:] = (18, 20, 25)

        # Conveyor belt surface
        cv2.rectangle(frame, (0, 260), (W, 460), (40, 38, 35), -1)

        # Simulate long member frame (moving left)
        bx = (W - offset) % (W + 400) - 200
        by = 280

        # Frame rail top
        cv2.rectangle(frame, (bx, by), (bx + 900, by + 30), (34, 85, 34), -1)
        # Frame rail bottom
        cv2.rectangle(frame, (bx, by + 120), (bx + 900, by + 150), (34, 85, 34), -1)
        # Cross members
        for cx in [bx + 100, bx + 300, bx + 500, bx + 700]:
            cv2.rectangle(frame, (cx, by), (cx + 20, by + 150), (50, 100, 50), -1)

        # Brackets (coloured blobs)
        parts = [
            ((bx + 30,  by + 60), (60, 40), (0, 180, 255), "B/S Bumper"),
            ((bx + 200, by + 10), (50, 30), (255, 140, 0), "Resilience"),
            ((bx + 350, by + 55), (55, 45), (180, 0, 255), "Articulation"),
            ((bx + 500, by + 30), (45, 35), (0, 220, 180), "B/S Trunnion"),
            ((bx + 700, by + 60), (40, 30), (220, 220, 0), "B/S ARB"),
        ]
        for (px, py), (pw, ph), color, lbl in parts:
            if 0 < px < W and 0 < py < H:
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), color, -1)
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (255, 255, 255), 1)
                tx = max(0, px)
                cv2.putText(frame, lbl, (tx, max(14, py - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

        # DEMO watermark
        cv2.putText(frame, f"DEMO  CAM{self.cam_id}  frame#{self._frame_count}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 120, 255), 2)

        return frame
