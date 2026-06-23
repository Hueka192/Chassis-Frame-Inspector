from __future__ import annotations
import os, time, cv2
import numpy as np
from datetime import datetime
from typing import Dict

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QLineEdit, QStackedWidget, QFrame,
    QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QRect, QPoint
from PyQt5.QtGui import QFont, QFontMetrics, QPixmap, QPainter, QColor, QPen, QBrush

from src.camera_worker    import CameraWorker, DemoFrameWorker
from src.camera_widget    import CameraWidget
from src.detector         import DetectionWorker
from src.stats_bar        import StatsBar
from src.checklist_panel  import ChecklistGridPanel
from src.settings_dialog  import SettingsDialog
from src.config_manager   import ConfigManager
from src.serial_reader    import SerialReader
from src.vc_lookup        import VCLookupWorker

from src.database         import Database
from src.models           import VehicleModel, resolve_model
from src.logger           import get_logger

logger = get_logger("main_window")

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
NG_DIR  = os.path.join(LOG_DIR, "ng_frames")
os.makedirs(NG_DIR, exist_ok=True)

STATE_SCAN_VC = "SCAN_VC"
STATE_INSPECT = "INSPECT"
STATE_DONE    = "DONE"

_SLIDE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "assets", "checkpoint_slides")

# Status colours used throughout the chassis overlay and checklist —
# binary scheme: RED = not detected yet, GREEN = confirmed detected.
_MARKER_LABEL_BG = "rgba(0, 0, 0, 160)"
_AUTO_FINALISE_DELAY_MS = 10000  # finalise after 10s of inactivity


def _btn(text, color, slot, tip=""):
    b = QPushButton(text)
    b.setFixedHeight(28)
    b.setToolTip(tip)
    b.setStyleSheet(
        f"QPushButton{{background:{color}22;color:{color};"
        f"border:1px solid {color}55;border-radius:4px;"
        f"padding:0 14px;font-size:10px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{color}44;}}"
    )
    b.clicked.connect(slot)
    return b


def _vsep() -> QLabel:
    """Thin vertical divider used between dashboard control groups."""
    sep = QLabel("│")
    sep.setStyleSheet("color:#2a2d3a; font-size:22px; background:transparent;")
    sep.setAlignment(Qt.AlignCenter)
    return sep


class ToastPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet("background:#0f1220; border:1px solid #00e67655; border-radius:6px;")
        self.setVisible(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#00e676; font-size:10px; font-weight:bold; font-family:Consolas;")
        lay.addWidget(self._lbl)
        lay.addStretch()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide)
        self._queue = []

    def show_toast(self, text: str, duration_ms: int = 2500):
        self._queue.append((text, duration_ms))
        if not self.isVisible():
            self._show_next()

    def _show_next(self):
        if not self._queue:
            self._hide()
            return
        text, dur = self._queue.pop(0)
        self._lbl.setText(f"✔  {text}")
        self.setVisible(True)
        self.raise_()
        self._timer.start(dur)

    def _hide(self):
        self.setVisible(False)
        QTimer.singleShot(100, self._show_next)


class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background:#080a12;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)

        # Tata Motors logo
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "assets", "tatamotors_logo.png")
        logo = QLabel()
        logo.setFixedSize(120, 40)
        logo.setStyleSheet("background:transparent;")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path)
            if not px.isNull():
                logo.setPixmap(px.scaled(120, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)

        # Brand name beside logo
        brand = QLabel("TATA MOTORS")
        brand.setStyleSheet(
            "color:#aa88ff; font-size:12px; font-weight:bold; letter-spacing:2px;"
        )
        lay.addWidget(brand)

        lay.addSpacing(16)

        ico = QLabel("◈")
        ico.setStyleSheet("color:#00bcd4; font-size:22px;")
        lay.addWidget(ico)

        ttl = QLabel("SMART QUALITY GATE INSPECTION")
        ttl.setStyleSheet(
            "color:#dde2f0; font-size:16px; font-weight:bold; letter-spacing:2px;"
        )
        lay.addWidget(ttl)
        lay.addStretch()

        cfg = ConfigManager.instance().cfg
        info = QLabel(f"LINE: {cfg.line_id}  |  STATION: {cfg.station_id}")
        info.setStyleSheet("color:#667799; font-size:11px; font-family:Consolas; font-weight:bold;")
        lay.addWidget(info)
        lay.addSpacing(20)

        self._clk = QLabel()
        self._clk.setStyleSheet("color:#8899aa; font-size:11px; font-family:Consolas; font-weight:bold;")
        lay.addWidget(self._clk)

        t = QTimer(self)
        t.timeout.connect(
            lambda: self._clk.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        )
        t.start(1000)
        t.timeout.emit()


class ChassisPhotoWidget(QWidget):
    """
    Right-panel widget showing the full chassis reference image with
    live detection-status markers overlaid. Image and checkpoint positions
    are loaded from ConfigManager.

    Detected part labels appear outside the image edges with animated
    connecting arrows for a clean, readable layout.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#060812; border:1px solid #1a1d28; border-radius:4px;")
        self._statuses: Dict[str, str] = {}
        self._item_names: Dict[str, str] = {}
        self._ref_pix: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._checkpoint_positions: Dict[str, tuple[float, float]] = {}
        self._checkpoint_boxes: Dict[str, tuple[float, float]] = {}
        self._anim_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_timer.start(100)
        self._load_config()

    def _anim_tick(self):
        self._anim_phase = (self._anim_phase + 0.06) % 1.0
        self.update()

    def _load_config(self):
        cfg = ConfigManager.instance().cfg
        self._checkpoint_positions = {}
        self._checkpoint_boxes = {}
        for cid, cp in cfg.checkpoints.items():
            self._checkpoint_positions[cid] = (cp["x"], cp["y"])
            # Optional per-checkpoint bounding-box size (normalised fraction
            # of the image). Falls back to a sensible default footprint so
            # existing configs without w/h keep working unmodified.
            self._checkpoint_boxes[cid] = (
                float(cp.get("w", 0.09)),
                float(cp.get("h", 0.10)),
            )
        path = os.path.join(_SLIDE_DIR, cfg.reference_image)
        if not os.path.exists(path):
            path = os.path.join(_SLIDE_DIR, "slide_10.png")
        if os.path.exists(path):
            px = QPixmap(path)
            if not px.isNull():
                self._ref_pix = px
        self.update()

    def load_checklist(self, names: Dict[str, str]):
        self._item_names = dict(names)
        self._statuses = {iid: "PENDING" for iid in names}
        self.update()

    def update_status(self, item_id: str, status: str):
        if item_id in self._statuses:
            self._statuses[item_id] = status
            self.update()

    def get_statuses(self) -> Dict[str, str]:
        return dict(self._statuses)

    def reset(self):
        self._statuses = {}
        self._item_names = {}
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_image()

    def _scale_image(self):
        if self._ref_pix is None:
            return
        self._scaled = self._ref_pix.scaled(
            self.width() - 20, self.height() - 50,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            self._do_paint(painter)
        finally:
            painter.end()

    def _do_paint(self, painter: QPainter):
        W, H = self.width(), self.height()
        painter.fillRect(0, 0, W, H, QColor(6, 8, 18))

        img_w, img_h = W - 40, H - 80
        ix, iy = 20, 20
        if self._ref_pix is not None:
            if self._scaled is None or self._scaled.isNull():
                self._scale_image()
            if self._scaled is not None:
                px = self._scaled
                ix = (W - px.width()) // 2
                iy = (H - 50 - px.height()) // 2
                painter.drawPixmap(ix, iy, px)
                img_w = px.width()
                img_h = px.height()
        else:
            # Draw placeholder grid when no reference image
            painter.setPen(QPen(QColor(30, 35, 50), 1))
            for gx in range(0, W, 60):
                painter.drawLine(gx, 0, gx, H - 30)
            for gy in range(0, H - 30, 60):
                painter.drawLine(0, gy, W, gy)
            painter.setPen(QColor(60, 65, 85))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "Chassis reference\n(no image loaded)")

        font_label = QFont("Segoe UI", 9, QFont.Bold)
        label_fm = QFontMetrics(font_label)
        anim_ms = int(time.time() * 1000) % 2000
        phase = self._anim_phase

        _LABEL_BG = QColor("#ffd400")     # highlighter yellow, like the reference deck
        _LABEL_BORDER = QColor("#5c4400")
        _LABEL_TEXT = QColor("#1a1400")

        label_jobs = []  # collected here, drawn after collision resolution

        for item_id, (fx, fy) in self._checkpoint_positions.items():
            status = self._statuses.get(item_id, "PENDING")
            name = self._item_names.get(item_id, item_id)
            box_fw, box_fh = self._checkpoint_boxes.get(item_id, (0.09, 0.10))

            mx = ix + int(img_w * fx)
            my = iy + int(img_h * fy)
            bw = max(24, int(img_w * box_fw))
            bh = max(20, int(img_h * box_fh))
            bx0, by0 = mx - bw // 2, my - bh // 2
            bx1, by1 = bx0 + bw, by0 + bh

            is_ok = status == "OK"
            status_color = QColor("#00e676") if is_ok else QColor("#ff5252")

            # ── Dashed bounding-box around the part (red = not detected,
            #    green = detected) — mirrors the master checkpoint deck's
            #    hand-drawn red/yellow callout boxes.
            if is_ok:
                fill = QColor(status_color)
                fill.setAlpha(40)
                painter.setBrush(fill)
            else:
                pulse = 0.5 + 0.5 * abs(phase - 0.5) * 2
                fill = QColor(status_color)
                fill.setAlpha(int(18 + 22 * pulse))
                painter.setBrush(fill)

            pen = QPen(status_color, 2.6, Qt.DashLine)
            pen.setDashPattern([6, 4])
            painter.setPen(pen)
            painter.drawRect(QRect(bx0, by0, bw, bh))

            if is_ok:
                # Small confirmed checkmark badge at the box's top-right corner.
                bcx, bcy = bx1, by0
                painter.setBrush(QColor(6, 8, 18))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(bcx, bcy), 10, 10)
                painter.setBrush(status_color)
                painter.drawEllipse(QPoint(bcx, bcy), 8, 8)
                painter.setPen(QPen(QColor(4, 20, 10), 2.2, cap=Qt.RoundCap))
                painter.drawLine(bcx - 3, bcy + 1, bcx - 1, bcy + 3)
                painter.drawLine(bcx - 1, bcy + 3, bcx + 4, bcy - 3)

            # ── Queue the yellow label for this checkpoint — drawn in a
            #    second pass once vertical collisions are resolved, so
            #    closely-spaced checkpoints never produce overlapping tags.
            num = "".join(ch for ch in item_id if ch.isdigit())
            num = str(int(num)) if num else item_id
            lbl = f"{num}. {name}"
            lbl = lbl[:34] + (".." if len(lbl) > 34 else "")

            tw = label_fm.horizontalAdvance(lbl) + 14
            th = 17
            side = "left" if fx < 0.5 else "right"

            label_margin = 6
            if side == "left":
                lx = label_margin
                line_end_x, line_end_y = bx0, my
            else:
                lx = W - label_margin - tw
                line_end_x, line_end_y = bx1, my
            lx = max(label_margin, min(lx, W - label_margin - tw))

            ideal_ly = max(label_margin, min(my - th // 2, H - 50 - th - label_margin))

            label_jobs.append({
                "side": side, "lx": lx, "ly": ideal_ly, "tw": tw, "th": th,
                "line_end": (line_end_x, line_end_y), "color": status_color,
                "text": lbl,
            })

        # ── Resolve vertical overlaps independently for each side, so a
        #    cluster of nearby checkpoints stacks its tags cleanly instead
        #    of drawing on top of each other.
        gap = 3
        for side in ("left", "right"):
            jobs = sorted((j for j in label_jobs if j["side"] == side),
                          key=lambda j: j["ly"])
            last_bottom = -1
            for j in jobs:
                if j["ly"] < last_bottom + gap:
                    j["ly"] = last_bottom + gap
                last_bottom = j["ly"] + j["th"]
            # If the stack ran past the bottom of the image area, shift the
            # whole stack up so the last tag still stays on-screen.
            overflow = (jobs[-1]["ly"] + jobs[-1]["th"]) - (H - 50 - label_margin) if jobs else 0
            if overflow > 0:
                for j in jobs:
                    j["ly"] = max(label_margin, j["ly"] - overflow)

        # ── Draw all labels + leader lines on top of the boxes.
        for j in label_jobs:
            lx, ly, tw, th = j["lx"], j["ly"], j["tw"], j["th"]
            line_end_x, line_end_y = j["line_end"]
            color = j["color"]
            line_start_x = lx + tw if j["side"] == "left" else lx

            painter.setPen(QPen(color, 1.4))
            painter.drawLine(line_start_x, ly + th // 2, line_end_x, line_end_y)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(line_end_x, line_end_y), 3, 3)

            painter.setBrush(_LABEL_BG)
            painter.setPen(QPen(_LABEL_BORDER, 1))
            painter.drawRect(lx, ly, tw, th)

            painter.setPen(_LABEL_TEXT)
            painter.setFont(font_label)
            painter.drawText(QRect(lx + 2, ly, tw - 4, th),
                             Qt.AlignLeft | Qt.AlignVCenter, j["text"])

        # Legend strip at bottom
        ly = H - 28
        painter.fillRect(0, ly, W, 28, QColor(10, 12, 22))
        legend_items = [
            ("▭ NOT DETECTED", "#ff5252"),
            ("▣ DETECTED", "#00e676"),
        ]
        lx_start = 10
        for text, col in legend_items:
            painter.setPen(QColor(col))
            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            painter.drawText(lx_start, ly + 18, text)
            lx_start += painter.fontMetrics().horizontalAdvance(text) + 20

        total = len(self._statuses)
        done = sum(1 for s in self._statuses.values() if s == "OK")
        count_text = f"{done}/{total} detected"
        painter.setPen(QColor("#00bcd4"))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        cw = painter.fontMetrics().horizontalAdvance(count_text)
        painter.drawText(W - cw - 12, ly + 18, count_text)





class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Quality Gate Inspection")
        self.showMaximized()

        self._cfg        = ConfigManager.instance().cfg
        self._demo_mode  = False
        self._state      = STATE_SCAN_VC

        self._db = Database.instance()
        self._session_id = self._db.start_session(
            self._cfg.line_id, self._cfg.station_id
        )

        self._current_vin     = ""
        self._current_vc      = ""
        self._current_model: VehicleModel | None = None
        self._current_veh_id  = 0
        self._scan_start      = 0.0

        self._cam_workers: dict[int, object] = {}
        self._last_frames: dict[int, np.ndarray] = {}
        self._det_worker  = DetectionWorker()
        self._frame_in_view = False
        self._active_cam = 1

        # Serial reader for VIN input
        self._serial_reader = SerialReader()
        self._serial_reader.vin_detected.connect(self._on_serial_vin)

        # Auto-finalise inactivity timer
        self._finalise_timer = QTimer(self)
        self._finalise_timer.setSingleShot(True)
        self._finalise_timer.timeout.connect(self._auto_finalise)

        self._build_ui()
        self._connect_signals()
        self._det_worker.start()
        self._start_cameras()
        self._serial_reader.start()
        self._enter_state(STATE_SCAN_VC)

        logger.info("MainWindow ready")

    def _build_ui(self):
        root_w = QWidget()
        self.setCentralWidget(root_w)
        root = QVBoxLayout(root_w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(TitleBar())
        root.addWidget(self._build_dashboard())

        self._h_split = QSplitter(Qt.Horizontal)
        self._h_split.setHandleWidth(3)
        self._h_split.setStyleSheet(
            "QSplitter::handle{background:#2a2d3a;}"
            "QSplitter::handle:hover{background:#00bcd4;}"
        )

        cam_cont = QWidget()
        cam_cont.setStyleSheet("background:#0a0c14;")
        cam_box = QVBoxLayout(cam_cont)
        cam_box.setContentsMargins(6, 6, 6, 6)
        cam_box.setSpacing(4)

        tog = QWidget()
        tog.setFixedHeight(32)
        tog.setStyleSheet("background:#0d0f18; border-radius:6px;")
        tog_lay = QHBoxLayout(tog)
        tog_lay.setContentsMargins(6, 2, 6, 2)
        tog_lay.setSpacing(4)

        self._btn_left = QPushButton("◀  LEFT VIEW")
        self._btn_left.setFixedHeight(26)
        self._btn_left.setCheckable(True)
        self._btn_left.setChecked(True)
        self._btn_left.setStyleSheet(
            "QPushButton{background:#00bcd433;color:#00bcd4;"
            "border:1px solid #00bcd466;border-radius:4px;"
            "font-size:9px;font-weight:bold;padding:0 10px;}"
            "QPushButton:checked{background:#00bcd455;}"
            "QPushButton:hover{background:#00bcd444;}"
        )
        self._btn_left.clicked.connect(lambda: self._toggle_camera(1))

        self._btn_right = QPushButton("RIGHT VIEW  ▶")
        self._btn_right.setFixedHeight(26)
        self._btn_right.setCheckable(True)
        self._btn_right.setChecked(False)
        self._btn_right.setStyleSheet(
            "QPushButton{background:#aa88ff33;color:#aa88ff;"
            "border:1px solid #aa88ff66;border-radius:4px;"
            "font-size:9px;font-weight:bold;padding:0 10px;}"
            "QPushButton:checked{background:#aa88ff55;}"
            "QPushButton:hover{background:#aa88ff44;}"
        )
        self._btn_right.clicked.connect(lambda: self._toggle_camera(2))

        tog_lay.addWidget(self._btn_left)
        tog_lay.addWidget(self._btn_right)
        tog_lay.addStretch()

        zoom_hint = QLabel("ZOOM: Scroll on camera")
        zoom_hint.setStyleSheet("color:#556677; font-size:8px;")
        tog_lay.addWidget(zoom_hint)

        cam_box.addWidget(tog)

        self._cam_stack = QStackedWidget()
        self._cam_w1 = CameraWidget(1, self._cfg.camera1.label or "Left View")
        self._cam_w2 = CameraWidget(2, self._cfg.camera2.label or "Right View")
        self._cam_stack.addWidget(self._cam_w1)
        self._cam_stack.addWidget(self._cam_w2)
        cam_box.addWidget(self._cam_stack, stretch=1)

        # ── Frame status label — sits below the camera feed, never
        #    obscures the image. Shows frame presence status during inspection.
        self._frame_status_label = QLabel("")
        self._frame_status_label.setAlignment(Qt.AlignCenter)
        self._frame_status_label.setFixedHeight(24)
        self._frame_status_label.setStyleSheet(
            "color:#667799; background:#0a0c14; border-top:1px solid #1a1d28;"
            "font-size:9px; font-weight:bold; letter-spacing:1px;"
        )
        cam_box.addWidget(self._frame_status_label)

        # ── SCAN VC prompt banner — sits below the camera feed, never
        #    obscures the image. Slow-pulses purple while waiting for a
        #    VIN/VC scan; hidden during active inspection.
        self._scan_banner = QLabel("▶  SCAN VC / ENTER VIN + VC NUMBER TO BEGIN")
        self._scan_banner.setAlignment(Qt.AlignCenter)
        self._scan_banner.setFixedHeight(26)
        self._scan_banner.setStyleSheet(
            "color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
            "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
        )
        cam_box.addWidget(self._scan_banner)

        # Timer for the slow banner pulse
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._banner_tick)
        self._banner_bright = True
        self._banner_timer.start(1100)

        self._h_split.addWidget(cam_cont)

        self._chassis_photo = ChassisPhotoWidget()
        # Load default checkpoint display at startup
        self._chassis_photo.load_checklist({
            cid: cp.get("name", cid)
            for cid, cp in self._cfg.checkpoints.items()
        })

        self._h_split.addWidget(self._chassis_photo)
        self._h_split.setSizes([300, 700])

        self._toast_popup = ToastPopup(self)
        self._toast_popup.setVisible(False)

        # Lower tier — full-width checklist grid panel, shown below both
        # the camera feed and the chassis reference image.
        self._checklist = ChecklistGridPanel()
        self._checklist.setMinimumHeight(140)

        self._v_split = QSplitter(Qt.Vertical)
        self._v_split.setHandleWidth(3)
        self._v_split.setChildrenCollapsible(False)
        self._v_split.setStyleSheet(
            "QSplitter::handle{background:#2a2d3a;}"
            "QSplitter::handle:hover{background:#00bcd4;}"
        )
        self._v_split.addWidget(self._h_split)
        self._v_split.addWidget(self._checklist)
        self._v_split.setStretchFactor(0, 6)
        self._v_split.setStretchFactor(1, 1)
        self._v_split.setSizes([840, 170])

        root.addWidget(self._v_split, stretch=1)

        self.statusBar().setStyleSheet(
            "QStatusBar{background:#080a12; color:#667799; font-size:9px;"
            "font-family:Consolas; border-top:1px solid #1a1d28;}"
        )
        self.statusBar().showMessage("Ready — scan VIN / VC to begin")

        # The splitter/camera widget doesn't have its final on-screen geometry
        # until the layout engine has run at least one pass — defer the first
        # toast-position calculation to the next event-loop tick so it isn't
        # computed against stale (0,0) coordinates.
        QTimer.singleShot(0, self._position_toast)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_h_split'):
            self._position_toast()

    def _position_toast(self):
        if not hasattr(self, '_h_split'):
            return
        cam_w = self._h_split.widget(0)
        if cam_w and cam_w.width() > 0:
            self._toast_popup.setFixedWidth(max(100, cam_w.width() - 20))
            top_left = cam_w.mapTo(self, cam_w.rect().topLeft())
            self._toast_popup.move(top_left.x() + 10, top_left.y() + 60)

    def _show_toast(self, text: str, duration_ms: int = 2500):
        """Reposition defensively, then queue the toast — avoids stale
        coordinates if this is the very first toast shown after startup."""
        self._position_toast()
        self._toast_popup.show_toast(text, duration_ms)

    def _build_dashboard(self) -> QWidget:
        """
        Unified upper dashboard bar — sits directly below the title bar and
        combines the scan controls (Settings / VIN / VC / Scan / Demo) with
        the live KPI tiles + verdict badge in a single row, so an operator
        never has to look in two places.
        """
        bar = QWidget()
        bar.setFixedHeight(76)
        bar.setStyleSheet("background:#0d0f18; border-bottom:1px solid #2a2d3a;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        lay.addWidget(
            _btn("⚙  SETTINGS", "#8899ff", self._open_settings,
                 "Camera & detection settings"),
            alignment=Qt.AlignVCenter,
        )

        lay.addWidget(_vsep())

        # --- VIN input (labelled block) ---
        vin_block = QVBoxLayout()
        vin_block.setSpacing(2)
        vin_lbl = QLabel("VIN NUMBER")
        vin_lbl.setStyleSheet(
            "color:#ffd740; font-size:8px; font-weight:bold; letter-spacing:1px;"
        )
        vin_block.addWidget(vin_lbl)
        self._vin_input = QLineEdit()
        self._vin_input.setPlaceholderText("17-digit VIN (MAT…)")
        self._vin_input.setFixedWidth(180)
        self._vin_input.setFixedHeight(30)
        self._vin_input.setMaxLength(17)
        self._vin_input.setStyleSheet(
            "QLineEdit{background:#0f1120;color:#ffd740;border:1px solid #ffd74055;"
            "border-radius:4px;font-size:13px;font-weight:bold;font-family:Consolas;padding:2px 8px;}"
            "QLineEdit:focus{border:1px solid #ffd740;}"
        )
        self._vin_input.returnPressed.connect(self._submit_scan)
        self._vin_input.textChanged.connect(self._on_vin_changed)
        vin_block.addWidget(self._vin_input)
        lay.addLayout(vin_block)

        # --- VC input (labelled block) ---
        vc_block = QVBoxLayout()
        vc_block.setSpacing(2)
        vc_lbl = QLabel("VC NUMBER")
        vc_lbl.setStyleSheet(
            "color:#00bcd4; font-size:8px; font-weight:bold; letter-spacing:1px;"
        )
        vc_block.addWidget(vc_lbl)
        self._vc_input = QLineEdit()
        self._vc_input.setPlaceholderText("12-digit VC…")
        self._vc_input.setFixedWidth(170)
        self._vc_input.setFixedHeight(30)
        self._vc_input.setMaxLength(12)
        self._vc_input.setStyleSheet(
            "QLineEdit{background:#0f1120;color:#00bcd4;border:1px solid #00bcd455;"
            "border-radius:4px;font-size:13px;font-weight:bold;font-family:Consolas;padding:2px 8px;}"
            "QLineEdit:focus{border:1px solid #00bcd4;}"
        )
        self._vc_input.returnPressed.connect(self._submit_scan)
        self._vc_input.textChanged.connect(self._on_vc_changed)
        vc_block.addWidget(self._vc_input)
        lay.addLayout(vc_block)

        self._scan_btn = QPushButton("▶ SCAN")
        self._scan_btn.setFixedSize(70, 30)
        self._scan_btn.setStyleSheet(
            "QPushButton{background:#00bcd433;color:#00bcd4;border:1px solid #00bcd466;"
            "border-radius:4px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#00bcd466;}"
        )
        self._scan_btn.setToolTip("Submit VIN / VC (or press Enter)")
        self._scan_btn.clicked.connect(self._submit_scan)
        lay.addWidget(self._scan_btn, alignment=Qt.AlignBottom)

        lay.addWidget(_vsep())

        self._demo_btn = _btn("DEMO MODE: OFF", "#ff9800", self._toggle_demo,
                              "Toggle live RTSP / demo simulation")
        lay.addWidget(self._demo_btn, alignment=Qt.AlignVCenter)

        lay.addStretch(1)

        # KPI tiles + verdict badge (same widget as before, now embedded here)
        self.stats_bar = StatsBar()
        lay.addWidget(self.stats_bar, alignment=Qt.AlignVCenter)

        self._submit_timer = QTimer(self)
        self._submit_timer.setSingleShot(True)
        self._submit_timer.timeout.connect(self._submit_scan)
        return bar

    def _enter_state(self, state: str):
        self._state = state
        self._finalise_timer.stop()

        if state == STATE_SCAN_VC:
            self._clear_inputs()
            self._frame_status_label.setText("")
            self._frame_status_label.setStyleSheet(
                "color:#667799; background:#0a0c14; border-top:1px solid #1a1d28;"
                "font-size:9px; font-weight:bold; letter-spacing:1px;"
            )
            self.stats_bar.clear_scan_info()
            self.stats_bar.on_verdict("SCAN_VC")
            self.statusBar().showMessage("Scan or enter VIN / VC number to begin inspection")
            self._det_worker.pause_detection(True)
            self._show_toast("Ready — scan VIN / VC to begin", 2000)
            self._chassis_photo.load_checklist({
                cid: cp.get("name", cid)
                for cid, cp in self._cfg.checkpoints.items()
            })
            self._show_scan_banner(True)

        elif state == STATE_INSPECT:
            self._show_scan_banner(False)
            self.stats_bar.show_scan_info(self._current_vin, self._current_vc)
            info = f"VC: {self._current_vc}"
            if self._current_vin:
                info += f"  VIN: {self._current_vin}"
            self.statusBar().showMessage(f"{info} — inspecting")
            self._det_worker.pause_detection(False)
            self._det_worker.reset_detector()

            if self._current_model:
                names = {it.id: it.name for it in self._current_model.checklist}
                self._chassis_photo.load_checklist(names)
                self._checklist.load_vehicle(self._current_vc, self._current_model, self._current_vin)

            self._finalise_timer.start(_AUTO_FINALISE_DELAY_MS)

        elif state == STATE_DONE:
            self.stats_bar.on_verdict("OK")
            self._show_toast("✔ Inspection saved — ready for next vehicle", 2000)

    def _banner_tick(self):
        """Slow pulse for the SCAN VC banner — 1.1s bright / 0.9s dim."""
        if not self._scan_banner.isVisible():
            return
        self._banner_bright = not self._banner_bright
        if self._banner_bright:
            self._scan_banner.setStyleSheet(
                "color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
                "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
            )
            self._banner_timer.start(1100)
        else:
            self._scan_banner.setStyleSheet(
                "color:#aa88ff33; background:#0a0c14; border-top:1px solid #aa88ff22;"
                "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
            )
            self._banner_timer.start(900)

    def _show_scan_banner(self, visible: bool):
        """Show or hide the SCAN VC banner below the camera feed."""
        self._scan_banner.setVisible(visible)
        if visible:
            self._banner_bright = True
            self._scan_banner.setStyleSheet(
                "color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
                "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
            )
            self._banner_timer.start(1100)
        else:
            self._banner_timer.stop()

    def _connect_signals(self):
        self._checklist.item_changed.connect(self._on_item_changed)
        self._det_worker.result_ready.connect(self._on_det_result)
        self._det_worker.frame_presence.connect(self._on_frame_presence)
        self._det_worker.checkpoint_hit.connect(self._on_checkpoint_hit)

    def _on_vin_changed(self, text: str):
        txt = text.strip()
        if len(txt) >= 17:
            self._vc_input.setFocus()
            self._vc_input.selectAll()

    def _on_vc_changed(self, text: str):
        if len(text.strip()) >= 12:
            self._submit_timer.start(300)

    def _submit_scan(self):
        self._submit_timer.stop()
        vin = self._vin_input.text().strip().upper()
        vc  = self._vc_input.text().strip().upper()
        if len(vin) == 17 and vin.startswith("MAT") and len(vc) >= 4:
            self._on_scan_submitted(vin, vc)

    def _clear_inputs(self):
        self._vin_input.clear()
        self._vc_input.clear()

    def _on_scan_submitted(self, vin: str, vc: str):
        model = resolve_model(vc)
        self._on_vc_accepted(vin, vc, model)

    def _on_vc_accepted(self, vin: str, vc: str, model: VehicleModel):
        if self._state in (STATE_INSPECT, STATE_DONE):
            self._auto_finalise()

        self._current_vin    = vin
        self._current_vc     = vc
        self._current_model  = model
        self._scan_start     = time.time()
        self._frame_in_view  = False

        self._current_veh_id = self._db.create_vehicle(
            self._session_id, vc, vin,
            model.code, model.name,
            len(model.checklist)
        )
        for item in model.checklist:
            self._db.save_checklist_item(
                self._current_veh_id, item.id, item.name, "PENDING"
            )

        self._checklist.load_vehicle(vc, model, vin)

        logger.info(f"VIN={vin} VC={vc} → model {model.code}, db_id={self._current_veh_id}")
        self._enter_state(STATE_INSPECT)

    def _auto_finalise(self):
        if self._state not in (STATE_INSPECT, STATE_DONE) or not self._current_veh_id:
            return
        self._finalise_timer.stop()

        results  = self._chassis_photo.get_statuses()
        ok_items = sum(1 for s in results.values() if s == "OK")
        ng_items = sum(1 for s in results.values() if s != "OK")
        verdict  = "OK" if ng_items == 0 else "NG"
        duration = time.time() - self._scan_start

        model = self._current_model
        if model:
            for item in model.checklist:
                st = results.get(item.id, "PENDING")
                self._db.save_checklist_item(
                    self._current_veh_id, item.id, item.name, st
                )

        self._db.finalise_vehicle(
            self._current_veh_id, verdict, ok_items, ng_items
        )

        if verdict == "NG" and self._cfg.alert.auto_save_ng_frames:
            self._save_ng_frames(self._current_vc)

        stats = self._db.get_session_stats(self._session_id)
        self.stats_bar.on_stats(stats)
        self.stats_bar.on_verdict(verdict)

        logger.info(
            f"Auto-finalised VC={self._current_vc} verdict={verdict} "
            f"ok={ok_items} ng={ng_items}"
        )

        self._current_vin     = ""
        self._current_vc      = ""
        self._current_model   = None
        self._current_veh_id  = 0
        self._frame_in_view   = False

        self._enter_state(STATE_SCAN_VC)

    @pyqtSlot(str)
    def _on_serial_vin(self, vin: str):
        """Called when a VIN is received from the serial reader."""
        self._vin_input.setText(vin)
        self._vc_input.clear()
        self._vc_input.setEnabled(False)
        self._vc_input.setPlaceholderText("Looking up VC…")
        self._show_toast(f"VIN received: {vin} — looking up VC…", 5000)
        self._pending_vin = vin
        worker = VCLookupWorker(vin)
        worker.result_ready.connect(self._on_vc_lookup_result)
        worker.error.connect(self._on_vc_lookup_error)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    @pyqtSlot(str, str)
    def _on_vc_lookup_result(self, vin: str, vc: str):
        if getattr(self, '_pending_vin', None) != vin:
            return
        self._pending_vin = None
        self._vc_input.setText(vc)
        self._vc_input.setEnabled(True)
        self._show_toast(f"VC found: {vc}", 2500)
        self._submit_scan()

    @pyqtSlot(str)
    def _on_vc_lookup_error(self, msg: str):
        self._pending_vin = None
        self._vc_input.setEnabled(True)
        self._vc_input.setPlaceholderText("12-digit VC…")
        self._show_toast(f"VC lookup failed: {msg}", 5000)

    @pyqtSlot(str, str)
    def _on_item_changed(self, item_id: str, status: str):
        if self._current_veh_id:
            self._chassis_photo.update_status(item_id, status)

    @pyqtSlot(bool)
    def _on_frame_presence(self, present: bool):
        self._frame_in_view = present
        if self._state == STATE_INSPECT:
            if present:
                self._frame_status_label.setText("●  FRAME IN VIEW")
                self._frame_status_label.setStyleSheet(
                    "color:#00e676; background:#001a0a; border-top:1px solid #00e67644;"
                    "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
                )
            else:
                self._frame_status_label.setText("●  WAITING FOR FRAME")
                self._frame_status_label.setStyleSheet(
                    "color:#ffc107; background:#1a0f00; border-top:1px solid #ffc10744;"
                    "font-size:10px; font-weight:bold; letter-spacing:1.5px;"
                )
            self.statusBar().showMessage(
                "Frame in view — scanning…" if present
                else f"VC {self._current_vc} — waiting for frame in camera view"
            )

    @pyqtSlot(int)
    def _on_checkpoint_hit(self, cp_id: int):
        if self._state != STATE_INSPECT or not self._frame_in_view:
            return
        item_id = f"CL-{cp_id:02d}"

        # Look up the item name from the current model
        item_name = item_id
        if self._current_model:
            for item in self._current_model.checklist:
                if item.id == item_id:
                    item_name = item.name
                    break

        self._chassis_photo.update_status(item_id, "OK")
        self._checklist.auto_detect_item(item_id)
        self._show_toast(f"[{item_id}] {item_name}", 2500)

        # Reset inactivity timer on each detection
        self._finalise_timer.start(_AUTO_FINALISE_DELAY_MS)

    @pyqtSlot(object)
    def _on_det_result(self, result):
        if result.annotated_frame is not None:
            w1 = self._cam_w1 if result.cam_id == 1 else self._cam_w2
            w1.update_frame(result.annotated_frame)
        self.statusBar().showMessage(
            f"CAM{result.cam_id} | {result.inference_ms:.0f}ms | "
            f"frame={'YES' if result.frame_present else 'NO'} | "
            f"boxes:{len(result.boxes)}"
        )

    def _toggle_camera(self, cam_id: int):
        self._active_cam = cam_id
        idx = 0 if cam_id == 1 else 1
        self._cam_stack.setCurrentIndex(idx)
        self._btn_left.setChecked(cam_id == 1)
        self._btn_right.setChecked(cam_id == 2)
        lbl = self._cfg.camera1.label if cam_id == 1 else self._cfg.camera2.label
        self._show_toast(f"Viewing: {lbl}", 1500)

    def _start_cameras(self):
        for cam_id in (1, 2):
            self._launch_camera(cam_id)
        cfg2 = self._cfg.camera2
        if not cfg2.enabled:
            self._btn_right.setEnabled(False)
            self._btn_right.setText("RIGHT VIEW (OFF)")

    def _launch_camera(self, cam_id: int):
        existing = self._cam_workers.get(cam_id)
        if existing:
            existing.stop()

        cfg = self._cfg.camera1 if cam_id == 1 else self._cfg.camera2
        if cam_id == 2 and not cfg.enabled:
            return

        if self._demo_mode or not cfg.enabled or not cfg.rtsp_url.strip():
            worker = DemoFrameWorker(cam_id)
        else:
            worker = CameraWorker(cam_id, cfg)

        worker.frame_ready.connect(self._on_frame)
        worker.status_change.connect(self._on_cam_status)
        self._cam_workers[cam_id] = worker
        worker.start()

    @pyqtSlot(int, np.ndarray)
    def _on_frame(self, cam_id: int, frame: np.ndarray):
        self._last_frames[cam_id] = frame
        self._det_worker.enqueue(cam_id, frame)

    @pyqtSlot(int, str, bool)
    def _on_cam_status(self, cam_id: int, msg: str, ok: bool):
        w1 = self._cam_w1 if cam_id == 1 else self._cam_w2
        w1.set_status(msg, ok)

    @pyqtSlot()
    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_():
            self._cfg = ConfigManager.instance().cfg
            self._start_cameras()
            self._det_worker.reload_detector()
            # Reload chassis overlay config
            self._chassis_photo._load_config()

    @pyqtSlot()
    def _toggle_demo(self):
        self._demo_mode = not self._demo_mode
        self._demo_btn.setText(
            f"DEMO MODE: {'ON' if self._demo_mode else 'OFF'}"
        )
        self._start_cameras()

    def _save_ng_frames(self, vc: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_vc = vc.replace("/", "_").replace("\\", "_")
        for cam_id, frame in self._last_frames.items():
            path = os.path.join(NG_DIR, f"NG_{safe_vc}_cam{cam_id}_{ts}.jpg")
            cv2.imwrite(path, frame)
            logger.info(f"NG frame saved: {path}")

    def closeEvent(self, event):
        self._finalise_timer.stop()
        self._db.end_session(self._session_id)
        self._det_worker.stop()
        self._serial_reader.stop()
        for w in self._cam_workers.values():
            w.stop()
        ConfigManager.instance().save()
        event.accept()


