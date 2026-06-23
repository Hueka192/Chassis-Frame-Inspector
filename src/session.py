"""
Inspection Session v4
======================
State machine for one production run.

Key changes:
  • Tracks total frames inspected (displayed in GUI)
  • Auto-reset when new frame detected by detector
  • mark_detected is idempotent once DETECTED (no flicker reversion)
  • Emits frame_count_changed signal
"""

from __future__ import annotations

import csv, copy, os, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from src.checkpoints import CHECKPOINTS, Checkpoint, CheckStatus, CHECKPOINT_MAP
from src.logger import get_logger

logger = get_logger("session")

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


@dataclass
class FrameRecord:
    frame_no: int
    timestamp: str
    line_id: str
    station_id: str
    result: str
    detected_cps: List[int] = field(default_factory=list)
    missing_cps:  List[int] = field(default_factory=list)
    duration_sec: float = 0.0

    def to_csv_row(self):
        return [self.frame_no, self.timestamp, self.line_id, self.station_id,
                self.result,
                ";".join(str(x) for x in self.detected_cps),
                ";".join(str(x) for x in self.missing_cps),
                f"{self.duration_sec:.1f}"]

    @staticmethod
    def csv_header():
        return ["FrameNo","Timestamp","LineID","StationID",
                "Result","DetectedCPs","MissingCPs","DurationSec"]


class InspectionSession(QObject):

    checkpoint_updated  = pyqtSignal(int, str, float)  # cp_id, status, conf
    verdict_ready       = pyqtSignal(str)              # OK | NG | IN_PROGRESS
    stats_updated       = pyqtSignal(dict)
    frame_logged        = pyqtSignal(object)           # FrameRecord
    frame_count_changed = pyqtSignal(int)              # total frames inspected

    def __init__(self, line_id="LINE-01", station_id="ST-01", parent=None):
        super().__init__(parent)
        self.line_id    = line_id
        self.station_id = station_id

        self._checkpoints: Dict[int, Checkpoint] = {
            cp.id: copy.deepcopy(cp) for cp in CHECKPOINTS
        }
        self._frame_counter = 0
        self._ok_count = 0
        self._ng_count = 0
        self._session_start = time.time()
        self._frame_start: Optional[float] = None
        self._active = False     # True when a frame is in the inspection zone

        self._csv_path = os.path.join(
            LOG_DIR,
            f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        self._init_csv()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def checkpoints(self):
        return self._checkpoints

    @property
    def frame_counter(self):
        return self._frame_counter

    @property
    def is_active(self):
        return self._active

    def start_new_frame(self):
        """Call when a new frame enters the inspection zone."""
        self._frame_counter += 1
        self._frame_start = time.time()
        self._active = True
        for cp in self._checkpoints.values():
            cp.reset()
        # Emit resets to UI
        for cp_id in self._checkpoints:
            self.checkpoint_updated.emit(cp_id, CheckStatus.PENDING.value, 0.0)
        self.verdict_ready.emit("IN_PROGRESS")
        self._emit_stats()
        self.frame_count_changed.emit(self._frame_counter)
        logger.info(f"[SESSION] Frame #{self._frame_counter} started")

    def mark_detected(self, cp_id: int, confidence: float = 0.8):
        """Mark a checkpoint as detected. Once DETECTED it never reverts."""
        if not self._active:
            return
        cp = self._checkpoints.get(cp_id)
        if cp is None or cp.status == CheckStatus.DETECTED:
            return    # already locked — ignore repeat signals (no flicker)
        cp.detected_count += 1
        if confidence > cp.confidence:
            cp.confidence = confidence
        if cp.detected_count >= 1:           # detector already did N_CONFIRM
            cp.status = CheckStatus.DETECTED
        self.checkpoint_updated.emit(cp_id, cp.status.value, cp.confidence)
        self._emit_stats()
        self._evaluate_verdict()

    def set_waiting(self):
        """Frame left the zone — pause detection, show waiting state."""
        self._active = False
        self.verdict_ready.emit("WAITING")
        self._emit_stats()

    def mark_missing(self, cp_id: int):
        cp = self._checkpoints.get(cp_id)
        if cp and cp.status == CheckStatus.PENDING:
            cp.status = CheckStatus.MISSING
            self.checkpoint_updated.emit(cp_id, cp.status.value, 0.0)
            self._emit_stats()
            self._evaluate_verdict()

    def finalise_frame(self) -> FrameRecord:
        detected = [cp.id for cp in self._checkpoints.values()
                    if cp.status == CheckStatus.DETECTED]
        missing  = [cp.id for cp in self._checkpoints.values()
                    if cp.status != CheckStatus.DETECTED]
        verdict  = "OK" if not missing else "NG"
        if verdict == "OK": self._ok_count += 1
        else:               self._ng_count += 1
        self._active = False

        duration = time.time() - (self._frame_start or time.time())
        rec = FrameRecord(
            frame_no=self._frame_counter,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            line_id=self.line_id, station_id=self.station_id,
            result=verdict, detected_cps=detected,
            missing_cps=missing, duration_sec=duration,
        )
        self._log_csv(rec)
        self.frame_logged.emit(rec)
        self.verdict_ready.emit(verdict)
        self._emit_stats()
        logger.info(f"[SESSION] Frame #{self._frame_counter} → {verdict} "
                    f"({len(detected)}/{len(self._checkpoints)} detected)")
        return rec

    def reset(self):
        self._active = False
        for cp in self._checkpoints.values():
            cp.reset()
        for cp_id in self._checkpoints:
            self.checkpoint_updated.emit(cp_id, CheckStatus.PENDING.value, 0.0)
        self.verdict_ready.emit("WAITING")
        self._emit_stats()

    def get_stats(self) -> dict:
        total = self._ok_count + self._ng_count
        return {
            "total":    total,
            "ok":       self._ok_count,
            "ng":       self._ng_count,
            "yield":    (self._ok_count / total * 100) if total else 0.0,
            "uptime":   time.time() - self._session_start,
            "frame_no": self._frame_counter,
            "active":   self._active,
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _evaluate_verdict(self):
        if not self._active:
            return
        all_done = all(cp.status == CheckStatus.DETECTED
                       for cp in self._checkpoints.values())
        self.verdict_ready.emit("OK" if all_done else "IN_PROGRESS")

    def _emit_stats(self):
        self.stats_updated.emit(self.get_stats())

    def _init_csv(self):
        try:
            with open(self._csv_path, "w", newline="") as f:
                csv.writer(f).writerow(FrameRecord.csv_header())
        except Exception as e:
            logger.error(f"CSV init: {e}")

    def _log_csv(self, rec: FrameRecord):
        try:
            with open(self._csv_path, "a", newline="") as f:
                csv.writer(f).writerow(rec.to_csv_row())
        except Exception as e:
            logger.error(f"CSV write: {e}")
