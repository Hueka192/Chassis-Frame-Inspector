"""
Detection Engine v4
====================
Key improvements:
  1. Frame presence detection  — checks if a long member frame is in FOV before
     running checkpoint detection. Uses large green-steel contour area threshold.
  2. Anti-flicker temporal smoothing — each checkpoint requires N_CONFIRM
     consecutive positive detections before being marked DETECTED, and once
     confirmed it STAYS confirmed (no downgrade mid-frame).
  3. Stable checkpoint locking — confirmed checkpoints are never reverted to
     PENDING within the same inspection frame cycle.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import numpy as np
import cv2
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

from src.checkpoints import CHECKPOINTS, CheckStatus
from src.config_manager import ConfigManager, DetectionConfig
from src.logger import get_logger

logger = get_logger("detector")

# How many consecutive positive frames before a checkpoint is CONFIRMED
N_CONFIRM = 4

# Minimum green-frame coverage ratio to consider a frame present in FOV
# Scaled dynamically based on frame resolution (2% of total pixels)
FRAME_PRESENT_MIN_RATIO = 0.02


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BBox:
    x1: int; y1: int; x2: int; y2: int
    label: str = ""
    confidence: float = 0.0
    color: Tuple[int, int, int] = (0, 255, 0)

    @property
    def cx(self): return (self.x1 + self.x2) // 2
    @property
    def cy(self): return (self.y1 + self.y2) // 2
    @property
    def w(self): return self.x2 - self.x1
    @property
    def h(self): return self.y2 - self.y1


@dataclass
class DetectionResult:
    cam_id: int
    frame_id: int
    timestamp: float
    frame_present: bool = False          # ← NEW: is the long member in view?
    boxes: List[BBox] = field(default_factory=list)
    matched_checkpoints: List[int] = field(default_factory=list)
    annotated_frame: Optional[np.ndarray] = None
    inference_ms: float = 0.0


# ── Colour signatures (HSV) ───────────────────────────────────────────────────

COLOUR_SIGNATURES = {
    "green_frame":    ((35,  35,  35), (85, 255, 255)),
    "grey_bracket":   ((0,   0,  70),  (180, 28, 210)),
    "orange_bracket": ((8,  100,  80), (22, 255, 255)),
    "blue_bracket":   ((95, 100,  50), (130, 255, 255)),
    "purple_bracket": ((128, 55,  50), (160, 255, 255)),
    "yellow_label":   ((22,  70,  80), (35, 255, 255)),
    "black_pipe":     ((0,   0,   0),  (180, 255,  45)),
    "silver_valve":   ((0,   0, 135),  (180,  22, 215)),
}

COLOUR_CP_MAP: Dict[str, List[int]] = {
    "green_frame":    [1, 2, 3, 4, 5, 6, 7, 8],
    "grey_bracket":   [4, 5, 7],
    "orange_bracket": [2, 6],
    "blue_bracket":   [1, 4],
    "purple_bracket": [5, 3],
    "yellow_label":   [],
    "silver_valve":   [7],
    "black_pipe":     [8],
}

COLOUR_DRAW = {
    "green_frame":    (0, 200, 80),
    "grey_bracket":   (180, 180, 180),
    "orange_bracket": (0, 140, 255),
    "blue_bracket":   (255, 100, 0),
    "purple_bracket": (200, 0, 200),
    "yellow_label":   (0, 230, 230),
    "black_pipe":     (80, 80, 80),
    "silver_valve":   (200, 200, 220),
}


# ── Rule-based detector ───────────────────────────────────────────────────────

class RuleBasedDetector:
    """
    Colour-segmentation detector with temporal smoothing.
    Maintains per-checkpoint hit counters across frames within one inspection
    cycle.  Checkpoints only flip DETECTED→PENDING on explicit reset().
    """

    def __init__(self, cfg: DetectionConfig):
        self.cfg = cfg
        self._frame_id = 0
        # Temporal hit counters: cp_id → consecutive positive frame count
        self._hit_buf: Dict[int, int] = {cp.id: 0 for cp in CHECKPOINTS}
        # Locked confirmed checkpoints (won't revert until reset)
        self._confirmed: set[int] = set()

    def reset(self):
        """Call at the start of every new inspection frame."""
        self._hit_buf = {cp.id: 0 for cp in CHECKPOINTS}
        self._confirmed.clear()

    # ── Frame presence ────────────────────────────────────────────────────
    def check_frame_present(self, frame: np.ndarray) -> Tuple[bool, float]:
        """
        Returns (present, coverage_ratio).
        Detects the long green steel member spanning a large horizontal area.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blur = cv2.GaussianBlur(hsv, (7, 7), 0)

        lo, hi = COLOUR_SIGNATURES["green_frame"]
        mask = cv2.inRange(blur, np.array(lo, np.uint8), np.array(hi, np.uint8))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)

        total_px   = frame.shape[0] * frame.shape[1]
        green_px   = int(np.sum(mask > 0))
        ratio      = green_px / max(total_px, 1)
        min_area   = int(total_px * FRAME_PRESENT_MIN_RATIO)

        # Also require at least one wide horizontal contour
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        wide_found = False
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            _, _, rw, rh = cv2.boundingRect(cnt)
            aspect = rw / max(rh, 1)
            if aspect > 3.0:          # clearly a long horizontal member
                wide_found = True
                break

        present = wide_found and green_px > min_area
        return present, ratio

    # ── Main detect ───────────────────────────────────────────────────────
    def detect(self, frame: np.ndarray, cam_id: int) -> DetectionResult:
        t0 = time.perf_counter()
        self._frame_id += 1

        result = DetectionResult(
            cam_id=cam_id,
            frame_id=self._frame_id,
            timestamp=time.time(),
        )

        # Step 1: Is the chassis frame present?
        present, _ratio = self.check_frame_present(frame)
        result.frame_present = present

        if not present:
            # Draw "waiting" overlay and return early — no part detection
            ann = frame.copy()
            _draw_waiting(ann)
            result.annotated_frame = ann
            result.inference_ms = (time.perf_counter() - t0) * 1000
            # Decay all hit buffers so stale counts don't persist
            for k in self._hit_buf:
                self._hit_buf[k] = max(0, self._hit_buf[k] - 1)
            return result

        # Step 2: Checkpoint detection via colour segmentation
        h, w = frame.shape[:2]
        y1 = int(h * self.cfg.roi_top_pct)
        y2 = int(h * self.cfg.roi_bottom_pct)
        x1 = int(w * self.cfg.roi_left_pct)
        x2 = int(w * self.cfg.roi_right_pct)
        roi = frame[y1:y2, x1:x2]

        hsv    = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        blurred = cv2.GaussianBlur(hsv, (5, 5), 0)

        raw_hits: Dict[int, float] = {}    # cp_id → max confidence this frame
        all_boxes: List[BBox] = []

        for colour_name, (lo, hi) in COLOUR_SIGNATURES.items():
            if colour_name == "green_frame":
                continue   # frame rail itself — not a checkpoint part
            mask = cv2.inRange(blurred,
                               np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                            cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 900:
                    continue
                rx, ry, rw, rh = cv2.boundingRect(cnt)
                aspect = rw / max(rh, 1)
                if aspect > 12 or aspect < 0.08:
                    continue
                conf = min(0.97, area / 6000.0)
                draw_color = COLOUR_DRAW.get(colour_name, (0, 255, 0))
                all_boxes.append(BBox(
                    x1=rx + x1, y1=ry + y1,
                    x2=rx + rw + x1, y2=ry + rh + y1,
                    label=colour_name.replace("_", " ").title(),
                    confidence=conf,
                    color=draw_color,
                ))
                for cp_id in COLOUR_CP_MAP.get(colour_name, []):
                    if conf >= self.cfg.confidence_threshold:
                        raw_hits[cp_id] = max(raw_hits.get(cp_id, 0.0), conf)

        # Step 3: Temporal smoothing — update hit buffers
        confirmed_this_call: List[int] = []

        for cp_id in list(self._hit_buf.keys()):
            if cp_id in self._confirmed:
                continue   # already locked — don't touch
            if cp_id in raw_hits:
                self._hit_buf[cp_id] += 1
            else:
                # Decay slowly (don't zero immediately — reduces flicker)
                self._hit_buf[cp_id] = max(0, self._hit_buf[cp_id] - 1)

            if self._hit_buf[cp_id] >= N_CONFIRM:
                self._confirmed.add(cp_id)
                confirmed_this_call.append(cp_id)

        result.boxes = _nms(all_boxes)
        result.matched_checkpoints = sorted(confirmed_this_call)
        result.annotated_frame = _annotate(frame.copy(), result.boxes, present)
        result.inference_ms = (time.perf_counter() - t0) * 1000
        return result


# ── Optional YOLO wrapper ─────────────────────────────────────────────────────

class YOLODetector:
    def __init__(self, model_path: str, cfg: DetectionConfig):
        self.cfg = cfg
        self._fb = RuleBasedDetector(cfg)
        self._model = None
        self._frame_id = 0
        try:
            from ultralytics import YOLO
            self._model = YOLO(model_path)
            if not cfg.use_gpu:
                self._model.to("cpu")
            logger.info(f"YOLO loaded: {model_path} (gpu={cfg.use_gpu})")
        except Exception as e:
            logger.warning(f"YOLO failed ({e}) — using rule-based")

    def reset(self):
        self._fb.reset()

    def detect(self, frame: np.ndarray, cam_id: int) -> DetectionResult:
        if self._model is None:
            return self._fb.detect(frame, cam_id)
        self._frame_id += 1
        t0 = time.perf_counter()
        try:
            results = self._model(
                frame, conf=self.cfg.confidence_threshold,
                iou=self.cfg.nms_threshold, verbose=False
            )
            boxes: List[BBox] = []
            matched = set()
            for r in results:
                for box in r.boxes:
                    xyxy = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0])
                    cls  = int(box.cls[0])
                    name = self._model.names.get(cls, f"cls{cls}")
                    b = BBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3],
                             label=name, confidence=conf,
                             color=(0, int(255*conf), int(255*(1-conf))))
                    boxes.append(b)
                    for cp in CHECKPOINTS:
                        if any(kw in name.lower() for kw in cp.keywords):
                            matched.add(cp.id)
            present, _ = self._fb.check_frame_present(frame)
            ann = _annotate(frame.copy(), boxes, present)
            return DetectionResult(
                cam_id=cam_id, frame_id=self._frame_id, timestamp=time.time(),
                frame_present=present, boxes=boxes,
                matched_checkpoints=sorted(matched),
                annotated_frame=ann,
                inference_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as e:
            logger.error(f"YOLO error: {e}")
            return self._fb.detect(frame, cam_id)


# ── Detection worker thread ───────────────────────────────────────────────────

class DetectionWorker(QThread):
    """
    Background thread — receives frames via enqueue(), emits results.
    Supports per-camera YOLO models via CameraConfig.model_path.
    """
    result_ready   = pyqtSignal(object)    # DetectionResult
    checkpoint_hit = pyqtSignal(int, int)  # (cam_id, cp_id)
    frame_presence = pyqtSignal(bool)      # True = frame in view

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: list = []
        self._mutex = QMutex()
        self._stop  = False
        self._skip_ctr: Dict[int, int] = {}
        self._detectors: Dict[int, object] = {}
        self._last_presence = None
        self._paused = False

    def _get_detector(self, cam_id: int):
        """Return detector for a given camera — lazy per-camera init."""
        if cam_id not in self._detectors:
            cfg = ConfigManager.instance().cfg
            global_mp = cfg.detection.model_path
            cam_cfg = cfg.camera1 if cam_id == 1 else cfg.camera2
            mp = cam_cfg.model_path or global_mp
            if mp and os.path.exists(mp):
                self._detectors[cam_id] = YOLODetector(mp, cfg.detection)
            else:
                self._detectors[cam_id] = RuleBasedDetector(cfg.detection)
        return self._detectors[cam_id]

    def reset_detector(self):
        """Call when new inspection frame starts — clears temporal buffers."""
        for d in self._detectors.values():
            d.reset()

    def enqueue(self, cam_id: int, frame: np.ndarray):
        skip = ConfigManager.instance().cfg.detection.frame_skip
        cnt  = self._skip_ctr.get(cam_id, 0)
        self._skip_ctr[cam_id] = (cnt + 1) % max(1, skip)
        if cnt != 0:
            return
        with QMutexLocker(self._mutex):
            if len(self._queue) > 3:
                self._queue.pop(0)
            self._queue.append((cam_id, frame.copy()))

    def stop(self):
        self._stop = True
        self.wait(1000)

    def reload_detector(self):
        self._detectors.clear()

    def reset_presence(self):
        """Force frame_presence signal on next frame regardless of previous state."""
        self._last_presence = None

    def pause_detection(self, paused: bool):
        """Pause/resume emitting checkpoint hits (keep frame presence detection)."""
        with QMutexLocker(self._mutex):
            self._paused = paused
        if paused:
            # Drain queue when pausing
            with QMutexLocker(self._mutex):
                self._queue.clear()

    def run(self):
        while not self._stop:
            item = None
            with QMutexLocker(self._mutex):
                if self._queue:
                    item = self._queue.pop(0)
            if item is None:
                self.msleep(10)
                continue
            cam_id, frame = item
            try:
                result = self._get_detector(cam_id).detect(frame, cam_id)
                self.result_ready.emit(result)

                # Emit frame presence only on change
                if result.frame_present != self._last_presence:
                    self._last_presence = result.frame_present
                    self.frame_presence.emit(result.frame_present)

                # Emit confirmed checkpoints (only when not paused)
                if not self._paused:
                    for cp_id in result.matched_checkpoints:
                        self.checkpoint_hit.emit(cam_id, cp_id)

            except Exception as e:
                logger.error(f"Detection error: {e}")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _nms(boxes: List[BBox], iou_thresh: float = 0.4) -> List[BBox]:
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b.confidence, reverse=True)
    kept, supp = [], set()
    for i, b in enumerate(boxes):
        if i in supp:
            continue
        kept.append(b)
        for j, b2 in enumerate(boxes[i+1:], i+1):
            if j not in supp and _iou(b, b2) > iou_thresh:
                supp.add(j)
    return kept


def _iou(a: BBox, b: BBox) -> float:
    ix1 = max(a.x1, b.x1); iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2); iy2 = min(a.y2, b.y2)
    inter = max(0, ix2-ix1) * max(0, iy2-iy1)
    if inter == 0:
        return 0.0
    return inter / (a.w*a.h + b.w*b.h - inter)


def _annotate(frame: np.ndarray, boxes: List[BBox], frame_present: bool) -> np.ndarray:
    for b in boxes:
        cv2.rectangle(frame, (b.x1, b.y1), (b.x2, b.y2), b.color, 2)
        lbl = f"{b.label} {b.confidence:.0%}"
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
        ty = max(b.y1 - 4, th + 4)
        cv2.rectangle(frame, (b.x1, ty-th-4), (b.x1+tw+4, ty), b.color, -1)
        cv2.putText(frame, lbl, (b.x1+2, ty-2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0,0,0), 1, cv2.LINE_AA)
    return frame


def _draw_waiting(frame: np.ndarray):
    pass
