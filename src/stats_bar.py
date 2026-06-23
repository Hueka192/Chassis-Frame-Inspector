from __future__ import annotations
import time
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont


class KPITile(QFrame):
    def __init__(self, title, value="0", color="#00bcd4", big=False, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            f"background:#141828; border-radius:8px; border-left:3px solid {color};"
        )
        self.setFixedHeight(64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(1)
        self._t = QLabel(title)
        self._t.setStyleSheet(
            f"color:{color}; font-size:10px; font-weight:bold; letter-spacing:1.5px;"
        )
        sz = "22px" if big else "18px"
        self._v = QLabel(value)
        self._v.setStyleSheet(
            f"color:#e0e6ff; font-size:{sz}; font-weight:bold; font-family:Consolas;"
        )
        lay.addWidget(self._t)
        lay.addWidget(self._v)

    def set_value(self, v: str, color: str = "#e0e6ff"):
        self._v.setText(v)
        self._v.setStyleSheet(
            f"color:{color}; font-size:{'22px' if 'OK' in v or 'NG' in v else '18px'}; font-weight:bold; font-family:Consolas;"
        )


class VerdictBadge(QLabel):
    STYLES = {
        "OK":          ("OK",                "#00e676", "#0d2a1a"),
        "NG":          ("NG",                "#ff5252", "#2a0d0d"),
        "IN_PROGRESS": ("IN PROGRESS",       "#ffd740", "#1a1600"),
        "WAITING":     ("WAITING",           "#00bcd4", "#001a20"),
        "SCAN_VC":     ("SCAN VC",           "#aa88ff", "#12001a"),
        "IDLE":        ("IDLE",              "#445566", "#0d0f14"),
    }

    # Slow flash cycle: visible for 1.1s, dim for 0.9s.
    # QTimer fires every half-cycle so we toggle on/off.
    _FLASH_ON_MS  = 1100
    _FLASH_OFF_MS = 900

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(62)
        self.setFont(QFont("Segoe UI", 14, QFont.Bold))

        self._current_state = "SCAN_VC"
        self._flash_visible = True

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._flash_tick)

        self._set("SCAN_VC")

    def _set(self, state: str, bright: bool = True):
        text, fg, bg = self.STYLES.get(state, self.STYLES["IDLE"])
        self.setText(text)
        if bright:
            self.setStyleSheet(
                f"color:{fg}; background:{bg}; border-radius:8px; border:2px solid {fg};"
            )
        else:
            # Dim version — faded text, no border, slightly darker bg for clear contrast
            self.setStyleSheet(
                f"color:{fg}44; background:#0a0c14; border-radius:8px; "
                f"border:2px solid {fg}22;"
            )

    def _flash_tick(self):
        """Toggle badge visibility and reschedule — slow relaxed cadence."""
        if self._current_state != "SCAN_VC":
            return
        self._flash_visible = not self._flash_visible
        self._set("SCAN_VC", bright=self._flash_visible)
        interval = self._FLASH_ON_MS if self._flash_visible else self._FLASH_OFF_MS
        self._flash_timer.start(interval)

    @pyqtSlot(str)
    def on_verdict(self, verdict: str):
        self._current_state = verdict
        self._flash_timer.stop()
        self._flash_visible = True

        if verdict == "SCAN_VC":
            self._set("SCAN_VC", bright=True)
            # Start the first OFF tick after the ON phase
            self._flash_timer.start(self._FLASH_ON_MS)
        else:
            self._set(verdict, bright=True)


class StatsBar(QWidget):
    """KPI dashboard bar with scanned VIN/VC info on the left side."""
    scan_submitted = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(66)
        self.setStyleSheet("background:#0d0f14;")
        self._start = time.time()
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        # Scanned VIN/VC info (left side)
        self._vin_info = QLabel("")
        self._vin_info.setStyleSheet(
            "color:#ffd740; font-size:13px; font-weight:bold; font-family:Consolas; background:transparent;"
        )
        self._vin_info.setFixedWidth(160)
        self._vc_info = QLabel("")
        self._vc_info.setStyleSheet(
            "color:#00bcd4; font-size:13px; font-weight:bold; font-family:Consolas; background:transparent;"
        )
        self._vc_info.setFixedWidth(160)

        self._vin_info.setVisible(False)
        self._vc_info.setVisible(False)

        info_sep = QLabel("│")
        info_sep.setStyleSheet("color:#2a2d3a; font-size:16px; background:transparent;")
        info_sep.setVisible(False)
        self._info_sep = info_sep

        lay.addWidget(self._vin_info)
        lay.addWidget(self._vc_info)
        lay.addWidget(info_sep)

        self.verdict  = VerdictBadge()
        self.verdict.setFixedWidth(150)

        self.tile_veh = KPITile("VEHICLES TESTED", "0", "#aa88ff", big=True)
        self.tile_veh.setFixedWidth(150)

        self.tile_ok  = KPITile("OK",  "0", "#00e676", big=True)
        self.tile_ok.setFixedWidth(86)

        self.tile_ng  = KPITile("NG",  "0", "#ff5252", big=True)
        self.tile_ng.setFixedWidth(86)

        for w in [self.verdict, self.tile_veh, self.tile_ok, self.tile_ng]:
            lay.addWidget(w)

        lay.addStretch()

    def show_scan_info(self, vin: str, vc: str):
        self._vin_info.setText(vin)
        self._vc_info.setText(vc)
        self._vin_info.setVisible(True)
        self._vc_info.setVisible(True)
        self._info_sep.setVisible(True)

    def clear_scan_info(self):
        self._vin_info.setVisible(False)
        self._vc_info.setVisible(False)
        self._info_sep.setVisible(False)

    @pyqtSlot(dict)
    def on_stats(self, stats: dict):
        self.tile_veh.set_value(str(stats.get("total", 0)), "#aa88ff")
        ok = stats.get("ok", 0)
        ng = stats.get("ng", 0)
        self.tile_ok.set_value(str(ok), "#00e676")
        self.tile_ng.set_value(str(ng), "#ff5252" if ng > 0 else "#445566")

    @pyqtSlot(str)
    def on_verdict(self, verdict: str):
        self.verdict.on_verdict(verdict)
