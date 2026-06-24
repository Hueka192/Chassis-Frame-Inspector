from __future__ import annotations
import time
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont


class KPITile(QFrame):
    def __init__(self, title, value="0", color="#00bcd4", big=False, parent=None, scale=1.0):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #141828,stop:1 #10141e);"
            f"border-radius:8px;"
        )
        self.setFixedHeight(max(52, int(72 * scale)))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(2)
        self._t = QLabel(title)
        self._t.setStyleSheet(
            f"color:{color}; font-size:{'13px' if big else '11px'}; font-weight:bold; letter-spacing:2px; background:transparent;"
        )
        sz = "26px" if big else "22px"
        self._v = QLabel(value)
        self._v.setStyleSheet(
            f"color:#e0e6ff; font-size:{sz}; font-weight:bold; font-family:Consolas; background:transparent;"
        )
        lay.addWidget(self._t)
        lay.addWidget(self._v)

    def set_value(self, v: str, color: str = "#e0e6ff"):
        self._v.setText(v)
        self._v.setStyleSheet(
            f"color:{color}; font-size:{'26px' if 'OK' in v or 'NG' in v else '22px'}; font-weight:bold; font-family:Consolas; background:transparent;"
        )


class VerdictBadge(QLabel):
    STYLES = {
        "OK":          ("OK",                "#00e676", "#0d2a1a"),
        "NG":          ("NG",                "#ff5252", "#2a0d0d"),
        "NA":          ("NA",                "#ffb300", "#1a1400"),
        "IN_PROGRESS": ("IN PROGRESS",       "#ffd740", "#1a1600"),
        "WAITING":     ("WAITING",           "#00bcd4", "#001a20"),
        "SCAN_VC":     ("SCAN VC",           "#aa88ff", "#12001a"),
        "IDLE":        ("IDLE",              "#445566", "#0d0f14"),
    }

    # Slow flash cycle: visible for 1.1s, dim for 0.9s.
    # QTimer fires every half-cycle so we toggle on/off.
    _FLASH_ON_MS  = 1100
    _FLASH_OFF_MS = 900

    def __init__(self, parent=None, scale=1.0):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(max(52, int(66 * scale)))
        self.setFont(QFont("Segoe UI", max(13, int(16 * scale)), QFont.Bold))

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
                f"color:{fg}; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 {bg},stop:1 #0d0f18);"
                f"border-radius:10px;"
                f"padding:0 14px;"
            )
        else:
            self.setStyleSheet(
                f"color:{fg}44; background:#0a0c14; border-radius:10px;"
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

    def __init__(self, parent=None, scale=1.0):
        super().__init__(parent)
        self._scale = scale
        self.setFixedHeight(max(60, int(78 * scale)))
        self.setStyleSheet("background:#0d0f14;")
        self._start = time.time()
        self._build()

    def _build(self):
        s = self._scale
        lay = QHBoxLayout(self)
        m = max(8, int(12 * s))
        lay.setContentsMargins(m, max(4, int(6 * s)), m, max(4, int(6 * s)))
        lay.setSpacing(max(6, int(10 * s)))

        # Scanned VIN/VC info (left side)
        ifsz = max(13, int(15 * s))
        iw = max(140, int(180 * s))
        self._vin_info = QLabel("")
        self._vin_info.setStyleSheet(
            f"color:#ffd740; font-size:{ifsz}px; font-weight:bold; font-family:Consolas; background:transparent;"
        )
        self._vin_info.setFixedWidth(iw)
        self._vc_info = QLabel("")
        self._vc_info.setStyleSheet(
            f"color:#00bcd4; font-size:{ifsz}px; font-weight:bold; font-family:Consolas; background:transparent;"
        )
        self._vc_info.setFixedWidth(iw)

        self._vin_info.setVisible(False)
        self._vc_info.setVisible(False)

        info_sep = QLabel("│")
        info_sep.setStyleSheet(f"color:#2a2d3a; font-size:{max(12, int(16 * s))}px; background:transparent;")
        info_sep.setVisible(False)
        self._info_sep = info_sep

        lay.addWidget(self._vin_info)
        lay.addWidget(self._vc_info)
        lay.addWidget(info_sep)

        self.verdict  = VerdictBadge(scale=s)
        self.verdict.setFixedWidth(max(140, int(170 * s)))

        self.tile_veh = KPITile("Tested", "0", "#aa88ff", big=True, scale=s)
        self.tile_veh.setFixedWidth(max(140, int(170 * s)))

        self.tile_ok  = KPITile("OK",  "0", "#00e676", big=True, scale=s)
        self.tile_ok.setFixedWidth(max(80, int(100 * s)))

        self.tile_ng  = KPITile("NG",  "0", "#ff5252", big=True, scale=s)
        self.tile_ng.setFixedWidth(max(80, int(100 * s)))

        self.tile_na  = KPITile("NA",  "0", "#ffb300", big=True, scale=s)
        self.tile_na.setFixedWidth(max(80, int(100 * s)))

        for w in [self.verdict, self.tile_veh, self.tile_ok, self.tile_ng, self.tile_na]:
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
        na = stats.get("na", 0)
        self.tile_ok.set_value(str(ok), "#00e676")
        self.tile_ng.set_value(str(ng), "#ff5252" if ng > 0 else "#445566")
        self.tile_na.set_value(str(na), "#ffb300" if na > 0 else "#445566")

    @pyqtSlot(str)
    def on_verdict(self, verdict: str):
        self.verdict.on_verdict(verdict)
