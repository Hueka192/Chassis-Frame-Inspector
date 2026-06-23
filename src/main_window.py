from __future__ import annotations
import os, time, cv2
import numpy as np
from datetime import datetime
from typing import Dict

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QLineEdit, QStackedWidget, QFrame,
    QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QRect, QPoint
from PyQt5.QtGui import QFont, QFontMetrics, QPixmap, QPainter, QColor, QPen, QBrush, QImage

from .camera_worker    import CameraWorker, DemoFrameWorker
from .camera_widget    import CameraWidget
from .detector         import DetectionWorker
from .stats_bar        import StatsBar
from .checklist_panel  import ChecklistGridPanel
from .settings_dialog  import SettingsDialog
from .config_manager   import ConfigManager
from .serial_reader    import SerialReader
from .vc_lookup        import VCLookupWorker

from .database         import Database
from .models           import VehicleModel, resolve_model
from .logger           import get_logger

logger = get_logger("main_window")

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
NG_DIR  = os.path.join(LOG_DIR, "ng_frames")
os.makedirs(NG_DIR, exist_ok=True)

STATE_SCAN_VC = "SCAN_VC"
STATE_INSPECT = "INSPECT"
STATE_DONE    = "DONE"

# Valid VC numbers for this model — any VC outside this list is NA
_VALID_VC_NUMBERS = {
    "51621768000R", "51621668000R", "51622268000R", "51622568000R",
    "51622668000R", "51621970000R", "51622070000R", "51621870000R",
    "51622170000R", "51622270000R", "51621170000R", "51620970000R",
    "51621070000R", "51621270000R",
}

_SLIDE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "assets", "checkpoint_slides")

# Status colours used throughout the chassis overlay and checklist —
# binary scheme: RED = not detected yet, GREEN = confirmed detected.
_MARKER_LABEL_BG = "rgba(0, 0, 0, 160)"
_AUTO_FINALISE_DELAY_MS = 10000  # finalise after 10s of inactivity
_SCREEN_SCALE = 1.0


def _btn(text, color, slot, tip=""):
    s = _SCREEN_SCALE
    b = QPushButton(text)
    b.setFixedHeight(max(24, int(28 * s)))
    b.setToolTip(tip)
    b.setStyleSheet(
        f"QPushButton{{background:{color}22;color:{color};"
        f"border:1px solid {color}55;border-radius:4px;"
        f"padding:0 {max(8, int(14 * s))}px;font-size:{max(9, int(10 * s))}px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{color}44;}}"
    )
    b.clicked.connect(slot)
    return b


def _vsep() -> QLabel:
    """Thin vertical divider used between dashboard control groups."""
    s = _SCREEN_SCALE
    sep = QLabel("│")
    sep.setStyleSheet(f"color:#2a2d3a; font-size:{max(16, int(22 * s))}px; background:transparent;")
    sep.setAlignment(Qt.AlignCenter)
    return sep


class ToastPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        s = _SCREEN_SCALE
        self.setFixedHeight(max(28, int(36 * s)))
        self.setStyleSheet("background:#0f1220; border:1px solid #00e67655; border-radius:6px;")
        self.setVisible(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(max(6, int(10 * s)), max(2, int(4 * s)), max(6, int(10 * s)), max(2, int(4 * s)))
        self._lbl = QLabel("")
        tfsz = max(9, int(10 * s))
        self._lbl.setStyleSheet(f"color:#00e676; font-size:{tfsz}px; font-weight:bold; font-family:Consolas;")
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
    _settings_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        s = _SCREEN_SCALE
        self.setFixedHeight(max(60, int(76 * s)))
        self.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #080a12,stop:1 #0f1430);"
        )
        lay = QHBoxLayout(self)
        m = max(8, int(14 * s))
        lay.setContentsMargins(m, 0, m, 0)

        def _make_white_semi_transparent(px: QPixmap, tolerance: int = 30, alpha: int = 160) -> QPixmap:
            img = px.toImage().convertToFormat(QImage.Format_ARGB32)
            for y in range(img.height()):
                for x in range(img.width()):
                    c = QColor(img.pixel(x, y))
                    if (c.red() > 255 - tolerance and c.green() > 255 - tolerance
                            and c.blue() > 255 - tolerance):
                        img.setPixelColor(x, y, QColor(c.red(), c.green(), c.blue(), alpha))
            return QPixmap.fromImage(img)

        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "assets", "TATA_MOTORS_LOGO.jpg")
        logo_lw = max(160, int(240 * s))
        logo_lh = max(44, int(68 * s))
        logo = QLabel()
        logo.setFixedSize(logo_lw, logo_lh)
        logo.setStyleSheet("background:#000; border-radius:4px; padding:2px;")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path)
            if not px.isNull():
                px = _make_white_semi_transparent(px)
                logo.setPixmap(px.scaled(logo_lw, logo_lh, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)

        sp = max(10, int(16 * s))
        lay.addSpacing(sp)

        ico = QLabel("◈")
        ico.setStyleSheet(f"color:#00bcd4; font-size:{max(16, int(22 * s))}px;")
        lay.addWidget(ico)

        ttl = QLabel("SMART QUALITY GATE INSPECTION")
        tsz = max(13, int(17 * s))
        ttl.setStyleSheet(
            f"color:#dde2f0; font-size:{tsz}px; font-weight:bold; letter-spacing:3px;"
        )
        lay.addWidget(ttl)
        lay.addStretch()

        cfg = ConfigManager.instance().cfg
        isz = max(9, int(11 * s))
        info = QLabel(f"LINE: {cfg.line_id}  |  STATION: {cfg.station_id}")
        info.setStyleSheet(f"color:#667799; font-size:{isz}px; font-family:Consolas; font-weight:bold;")
        lay.addWidget(info)
        lay.addSpacing(max(12, int(20 * s)))

        self._clk = QLabel()
        self._clk.setStyleSheet(f"color:#8899aa; font-size:{isz}px; font-family:Consolas; font-weight:bold;")
        lay.addWidget(self._clk)

        t = QTimer(self)
        t.timeout.connect(
            lambda: self._clk.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        )
        t.start(1000)
        t.timeout.emit()

        lay.addSpacing(max(12, int(20 * s)))

        sb = max(26, int(32 * s))
        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFixedSize(sb, sb)
        self._settings_btn.setToolTip("Open settings")
        self._settings_btn.setStyleSheet(
            f"QPushButton{{background:#1c2050;color:#8899ff;border:none;border-radius:6px;font-size:{max(12, int(16 * s))}px;}}"
            f"QPushButton:hover{{background:#2a30a0;}}"
        )
        self._settings_btn.clicked.connect(self._settings_clicked.emit)
        lay.addWidget(self._settings_btn)


class ChassisPhotoWidget(QWidget):
    """
    Right-panel widget showing the full chassis reference image with
    live detection-status markers overlaid. Image and checkpoint positions
    are loaded from ConfigManager.

    Checkpoint names are baked into the reference image. Detection markers
    (dashed bounding boxes) are red by default and turn green on detection.
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
            self.width() - 20, self.height() - 20,
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
            painter.setPen(QPen(QColor(30, 35, 50), 1))
            for gx in range(0, W, 60):
                painter.drawLine(gx, 0, gx, H - 30)
            for gy in range(0, H - 30, 60):
                painter.drawLine(0, gy, W, gy)
            painter.setPen(QColor(60, 65, 85))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "Chassis reference\n(no image loaded)")

        phase = self._anim_phase

        for item_id, (fx, fy) in self._checkpoint_positions.items():
            status = self._statuses.get(item_id, "PENDING")
            box_fw, box_fh = self._checkpoint_boxes.get(item_id, (0.09, 0.10))

            mx = ix + int(img_w * fx)
            my = iy + int(img_h * fy)
            bw = max(24, int(img_w * box_fw))
            bh = max(20, int(img_h * box_fh))
            bx0, by0 = mx - bw // 2, my - bh // 2
            bx1, by1 = bx0 + bw, by0 + bh

            is_detected = status == "OK"
            status_color = QColor("#00e676") if is_detected else QColor("#ff5252")

            if is_detected:
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

            if is_detected:
                bcx, bcy = bx1, by0
                painter.setBrush(QColor(6, 8, 18))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPoint(bcx, bcy), 10, 10)
                painter.setBrush(status_color)
                painter.drawEllipse(QPoint(bcx, bcy), 8, 8)
                painter.setPen(QPen(QColor(4, 20, 10), 2.2, cap=Qt.RoundCap))
                painter.drawLine(bcx - 3, bcy + 1, bcx - 1, bcy + 3)
                painter.drawLine(bcx - 1, bcy + 3, bcx + 4, bcy - 3)

        # Legend strip at bottom
        lh = max(22, int(28 * _SCREEN_SCALE))
        ly = H - lh
        lfsz = max(7, int(8 * _SCREEN_SCALE))
        painter.fillRect(0, ly, W, lh, QColor(10, 12, 22))
        legend_items = [
            ("▭ NOT DETECTED", "#ff5252"),
            ("▣ DETECTED", "#00e676"),
        ]
        lx_start = max(8, int(10 * _SCREEN_SCALE))
        for text, col in legend_items:
            painter.setPen(QColor(col))
            painter.setFont(QFont("Consolas", lfsz, QFont.Bold))
            painter.drawText(lx_start, ly + lh - max(6, int(8 * _SCREEN_SCALE)), text)
            lx_start += painter.fontMetrics().horizontalAdvance(text) + max(12, int(20 * _SCREEN_SCALE))

        total = len(self._statuses)
        done = sum(1 for s in self._statuses.values() if s == "OK")
        count_text = f"{done}/{total} detected"
        painter.setPen(QColor("#00bcd4"))
        painter.setFont(QFont("Consolas", lfsz, QFont.Bold))
        cw = painter.fontMetrics().horizontalAdvance(count_text)
        painter.drawText(W - cw - max(8, int(12 * _SCREEN_SCALE)), ly + lh - max(6, int(8 * _SCREEN_SCALE)), count_text)





class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Quality Gate Inspection")

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        scr_w, scr_h = geo.width(), geo.height()
        self._s = _SCREEN_SCALE = max(0.5, min(1.5, min(scr_w / 1920, scr_h / 1080)))

        self.showFullScreen()

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
        self._pending_vin     = None

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

        # Demo auto-detect timer — marks checkpoints green one by one
        self._demo_detect_timer = QTimer(self)
        self._demo_detect_timer.timeout.connect(self._demo_auto_detect)
        self._demo_checkpoint_idx = 0

        self._build_ui()
        self._connect_signals()
        self._det_worker.start()
        self._start_cameras()
        self._serial_reader.start()
        self._enter_state(STATE_SCAN_VC)
        self._apply_theme()

        logger.info("MainWindow ready")

    def _build_ui(self):
        s = self._s
        root_w = QWidget()
        self.setCentralWidget(root_w)
        root = QVBoxLayout(root_w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._title_bar = TitleBar()
        self._title_bar._settings_clicked.connect(self._open_settings)
        root.addWidget(self._title_bar)
        self._dash_bar = self._build_dashboard()
        root.addWidget(self._dash_bar)

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
        tog.setFixedHeight(max(28, int(32 * s)))
        tog.setStyleSheet("background:#0d0f18; border-radius:6px;")
        tog_lay = QHBoxLayout(tog)
        tog_lay.setContentsMargins(max(4, int(6 * s)), 2, max(4, int(6 * s)), 2)
        tog_lay.setSpacing(4)

        tfsz = max(8, int(10 * s))
        tp = max(8, int(14 * s))
        self._btn_left = QPushButton("◀  LEFT VIEW")
        self._btn_left.setFixedHeight(max(24, int(30 * s)))
        self._btn_left.setCheckable(True)
        self._btn_left.setChecked(True)
        self._btn_left.setStyleSheet(
            f"QPushButton{{background:#00bcd433;color:#00bcd4;"
            f"border:2px solid #00bcd466;border-radius:6px;"
            f"font-size:{tfsz}px;font-weight:bold;padding:0 {tp}px;}}"
            f"QPushButton:checked{{background:#00bcd4;color:#ffffff;border:2px solid #00bcd4;}}"
            f"QPushButton:hover{{background:#00bcd444;}}"
        )
        self._btn_left.clicked.connect(lambda: self._toggle_camera(1))

        self._btn_right = QPushButton("RIGHT VIEW  ▶")
        self._btn_right.setFixedHeight(max(24, int(30 * s)))
        self._btn_right.setCheckable(True)
        self._btn_right.setChecked(False)
        self._btn_right.setStyleSheet(
            f"QPushButton{{background:#aa88ff33;color:#aa88ff;"
            f"border:2px solid #aa88ff66;border-radius:6px;"
            f"font-size:{tfsz}px;font-weight:bold;padding:0 {tp}px;}}"
            f"QPushButton:checked{{background:#aa88ff;color:#ffffff;border:2px solid #aa88ff;}}"
            f"QPushButton:hover{{background:#aa88ff44;}}"
        )
        self._btn_right.clicked.connect(lambda: self._toggle_camera(2))

        tog_lay.addWidget(self._btn_left)
        tog_lay.addWidget(self._btn_right)
        tog_lay.addStretch()

        zoom_hint = QLabel("ZOOM: Scroll on camera")
        zoom_hint.setStyleSheet(f"color:#556677; font-size:{max(7, int(8 * s))}px;")
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
        self._frame_status_label.setFixedHeight(max(20, int(24 * s)))
        ffsz = max(8, int(9 * s))
        self._frame_status_label.setStyleSheet(
            f"color:#667799; background:#0a0c14; border-top:1px solid #1a1d28;"
            f"font-size:{ffsz}px; font-weight:bold; letter-spacing:1px;"
        )
        cam_box.addWidget(self._frame_status_label)

        # ── SCAN VC prompt banner — sits below the camera feed, never
        #    obscures the image. Slow-pulses purple while waiting for a
        #    VIN/VC scan; hidden during active inspection.
        self._scan_banner = QLabel("▶  SCAN VC / ENTER VIN + VC NUMBER TO BEGIN")
        self._scan_banner.setAlignment(Qt.AlignCenter)
        self._scan_banner.setFixedHeight(max(22, int(26 * s)))
        bfsz = max(9, int(10 * s))
        self._scan_banner.setStyleSheet(
            f"color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
            f"font-size:{bfsz}px; font-weight:bold; letter-spacing:1.5px;"
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
        screen = QApplication.primaryScreen()
        scr_w = screen.availableGeometry().width() if screen else 1920
        sw = self.width() or scr_w
        cam_w = max(240, int(sw * 0.30))
        ref_w = max(240, int(sw * 0.70))
        self._h_split.setSizes([cam_w, ref_w])

        self._toast_popup = ToastPopup(self)
        self._toast_popup.setVisible(False)

        # Lower tier — full-width checklist grid panel, shown below both
        # the camera feed and the chassis reference image.
        self._checklist = ChecklistGridPanel(scale=s)
        self._checklist.setMinimumHeight(max(80, int(140 * s)))

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

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showMaximized()
            else:
                self.showFullScreen()
        else:
            super().keyPressEvent(event)

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
        combines the scan controls (VIN / VC / Scan / Demo) with
        the live KPI tiles + verdict badge in a single row, so an operator
        never has to look in two places.
        """
        s = _SCREEN_SCALE
        bh = max(60, int(76 * s))
        bar = QWidget()
        bar.setFixedHeight(bh)
        bar.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #0d0f18,stop:1 #11162a);"
            "border-bottom:1px solid #2a2d3a;"
        )
        m = max(8, int(12 * s))
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(m, max(4, int(6 * s)), m, max(4, int(6 * s)))
        lay.setSpacing(max(6, int(10 * s)))

        # --- VIN input (labelled block) ---
        vin_block = QVBoxLayout()
        vin_block.setSpacing(2)
        vin_lbl = QLabel("VIN NUMBER")
        vfsz = max(7, int(8 * s))
        vin_lbl.setStyleSheet(
            f"color:#ffd740; font-size:{vfsz}px; font-weight:bold; letter-spacing:1px;"
        )
        vin_block.addWidget(vin_lbl)
        iw = max(140, int(200 * s))
        ih = max(26, int(32 * s))
        ifs = max(11, int(13 * s))
        self._vin_input = QLineEdit()
        self._vin_input.setPlaceholderText("17-digit VIN (MAT…)")
        self._vin_input.setFixedWidth(iw)
        self._vin_input.setFixedHeight(ih)
        self._vin_input.setMaxLength(17)
        self._vin_input.setStyleSheet(
            f"QLineEdit{{background:#0f1120;color:#ffd740;border:2px solid #ffd74055;"
            f"border-radius:6px;font-size:{ifs}px;font-weight:bold;font-family:Consolas;padding:2px 10px;}}"
            f"QLineEdit:focus{{border:2px solid #ffd740;background:#151830;}}"
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
            f"color:#00bcd4; font-size:{vfsz}px; font-weight:bold; letter-spacing:1px;"
        )
        vc_block.addWidget(vc_lbl)
        self._vc_input = QLineEdit()
        self._vc_input.setPlaceholderText("12-digit VC…")
        self._vc_input.setFixedWidth(max(130, int(190 * s)))
        self._vc_input.setFixedHeight(ih)
        self._vc_input.setMaxLength(12)
        self._vc_input.setStyleSheet(
            f"QLineEdit{{background:#0f1120;color:#00bcd4;border:2px solid #00bcd455;"
            f"border-radius:6px;font-size:{ifs}px;font-weight:bold;font-family:Consolas;padding:2px 10px;}}"
            f"QLineEdit:focus{{border:2px solid #00bcd4;background:#151830;}}"
        )
        self._vc_input.returnPressed.connect(self._submit_scan)
        self._vc_input.textChanged.connect(self._on_vc_changed)
        vc_block.addWidget(self._vc_input)
        lay.addLayout(vc_block)

        sw = max(60, int(80 * s))
        self._scan_btn = QPushButton("▶ SCAN")
        self._scan_btn.setFixedSize(sw, ih)
        sfsz = max(9, int(11 * s))
        self._scan_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #00bcd433,stop:1 #0088aa33);color:#00bcd4;"
            f"border:2px solid #00bcd466;border-radius:6px;"
            f"font-size:{sfsz}px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#00bcd466;border:2px solid #00bcd4;}}"
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
        self.stats_bar = StatsBar(scale=s)
        lay.addWidget(self.stats_bar, alignment=Qt.AlignVCenter)

        self._submit_timer = QTimer(self)
        self._submit_timer.setSingleShot(True)
        self._submit_timer.timeout.connect(self._submit_scan)
        return bar

    def _enter_state(self, state: str):
        self._state = state
        self._finalise_timer.stop()
        self._demo_detect_timer.stop()

        if state == STATE_SCAN_VC:
            self._clear_inputs()
            self._frame_status_label.setText("")
            ffsz = max(8, int(9 * _SCREEN_SCALE))
            self._frame_status_label.setStyleSheet(
                f"color:#667799; background:#0a0c14; border-top:1px solid #1a1d28;"
                f"font-size:{ffsz}px; font-weight:bold; letter-spacing:1px;"
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

            # Start demo auto-detect if in demo mode
            if self._demo_mode and self._current_model:
                self._demo_checkpoint_idx = 0
                self._demo_detect_timer.start(800)

        elif state == STATE_DONE:
            self.stats_bar.on_verdict("OK")
            self._show_toast("✔ Inspection saved — ready for next vehicle", 2000)

    def _banner_tick(self):
        """Slow pulse for the SCAN VC banner — 1.1s bright / 0.9s dim."""
        if not self._scan_banner.isVisible():
            return
        self._banner_bright = not self._banner_bright
        bfsz = max(9, int(10 * _SCREEN_SCALE))
        if self._banner_bright:
            self._scan_banner.setStyleSheet(
                f"color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
                f"font-size:{bfsz}px; font-weight:bold; letter-spacing:1.5px;"
            )
            self._banner_timer.start(1100)
        else:
            self._scan_banner.setStyleSheet(
                f"color:#aa88ff33; background:#0a0c14; border-top:1px solid #aa88ff22;"
                f"font-size:{bfsz}px; font-weight:bold; letter-spacing:1.5px;"
            )
            self._banner_timer.start(900)

    def _show_scan_banner(self, visible: bool):
        """Show or hide the SCAN VC banner below the camera feed."""
        self._scan_banner.setVisible(visible)
        if visible:
            self._banner_bright = True
            bfsz = max(9, int(10 * _SCREEN_SCALE))
            self._scan_banner.setStyleSheet(
                f"color:#aa88ff; background:#12001a; border-top:1px solid #aa88ff44;"
                f"font-size:{bfsz}px; font-weight:bold; letter-spacing:1.5px;"
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
        if self._demo_mode:
            if not vin:
                vin = f"DEMO{vc or 'VIN'}000001"
            if not vc:
                vc = "4832TK000001"
            self._on_scan_submitted(vin, vc)
        elif len(vin) == 17 and vin.startswith("MAT") and len(vc) >= 4:
            self._on_scan_submitted(vin, vc)

    def _clear_inputs(self):
        self._vin_input.clear()
        self._vc_input.clear()

    def _on_scan_submitted(self, vin: str, vc: str):
        # Skip NA check in demo mode
        if not self._demo_mode and vc not in _VALID_VC_NUMBERS:
            self._on_vc_not_applicable(vin, vc)
            return
        model = resolve_model(vc)
        self._on_vc_accepted(vin, vc, model)

    def _on_vc_not_applicable(self, vin: str, vc: str):
        """Handle a VC that is not in the valid list — mark everything NA."""
        if self._state in (STATE_INSPECT, STATE_DONE):
            self._auto_finalise()

        model = resolve_model(vc)
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
                self._current_veh_id, item.id, item.name, "NA"
            )

        total = len(model.checklist)
        self._db.finalise_vehicle(self._current_veh_id, "NA", 0, 0)

        # Update stats with NA count
        stats = self._db.get_session_stats(self._session_id)
        self.stats_bar.on_stats(stats)
        self.stats_bar.on_verdict("NA")

        self.statusBar().showMessage(
            f"VC {vc} not applicable for this model — marked NA"
        )
        self._show_toast(f"✖ VC {vc} not applicable for this model", 4000)

        # Log and reset
        logger.info(f"VC={vc} not in valid list → NA")
        self._current_vin     = ""
        self._current_vc      = ""
        self._current_model   = None
        self._current_veh_id  = 0
        self._frame_in_view   = False
        self._enter_state(STATE_SCAN_VC)

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
            ffsz = max(9, int(10 * _SCREEN_SCALE))
            if present:
                self._frame_status_label.setText("●  FRAME IN VIEW")
                self._frame_status_label.setStyleSheet(
                    f"color:#00e676; background:#001a0a; border-top:1px solid #00e67644;"
                    f"font-size:{ffsz}px; font-weight:bold; letter-spacing:1.5px;"
                )
            else:
                self._frame_status_label.setText("●  WAITING FOR FRAME")
                self._frame_status_label.setStyleSheet(
                    f"color:#ffc107; background:#1a0f00; border-top:1px solid #ffc10744;"
                    f"font-size:{ffsz}px; font-weight:bold; letter-spacing:1.5px;"
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
        for w in list(self._cam_workers.values()):
            w.stop()
        self._cam_workers.clear()
        for cam_id in (1, 2):
            self._launch_camera(cam_id)
        cfg2 = self._cfg.camera2
        if not cfg2.enabled:
            self._btn_right.setEnabled(False)
            self._btn_right.setText("RIGHT VIEW (OFF)")

    def _launch_camera(self, cam_id: int):
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
            self._apply_theme()

    def _apply_theme(self):
        cfg = ConfigManager.instance().cfg
        app = QApplication.instance()
        qss_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "assets", f"style_{cfg.theme}.qss")
        if not os.path.exists(qss_path):
            qss_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    "assets", "style.qss")
        try:
            with open(qss_path, encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as e:
            logger.warning(f"Failed to load theme QSS ({qss_path}): {e}")

        is_dark = cfg.theme == "dark"
        if hasattr(self, '_title_bar'):
            self._title_bar.setStyleSheet(
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #080a12,stop:1 #0f1430);"
                if is_dark else
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #e8ecf4,stop:1 #d0d8e8);"
            )
            self._title_bar._settings_btn.setStyleSheet(
                "QPushButton{background:#1c2050;color:#8899ff;border:none;border-radius:6px;font-size:16px;}"
                "QPushButton:hover{background:#2a30a0;}"
            )

        # Update dashboard bar style
        if hasattr(self, '_dash_bar'):
            self._dash_bar.setStyleSheet(
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #0d0f18,stop:1 #11162a);"
                "border-bottom:1px solid #2a2d3a;"
                if is_dark else
                "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #f0f2f8,stop:1 #e4e8f0);"
                "border-bottom:1px solid #c0c4d0;"
            )

        # Update splitter styles
        splitter_color = "#2a2d3a" if is_dark else "#c0c4d0"
        splitter_hover = "#00bcd4" if is_dark else "#0097a7"
        splitter_qss = (
            f"QSplitter::handle{{background:{splitter_color};}}"
            f"QSplitter::handle:hover{{background:{splitter_hover};}}"
        )
        for splitter in self.findChildren(QSplitter):
            splitter.setStyleSheet(splitter_qss)

    @pyqtSlot()
    def _demo_auto_detect(self):
        """In demo mode, progressively mark checkpoints as detected."""
        if not self._demo_mode or self._state != STATE_INSPECT:
            self._demo_detect_timer.stop()
            return
        if not self._current_model or not self._current_model.checklist:
            return
        items = self._current_model.checklist
        if self._demo_checkpoint_idx < len(items):
            item = items[self._demo_checkpoint_idx]
            self._on_checkpoint_hit(int(item.id.split("-")[1]))
            self._demo_checkpoint_idx += 1
        else:
            self._demo_detect_timer.stop()
            self._show_toast("✔ All checkpoints detected in demo!", 2000)

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
        self._banner_timer.stop()
        self._demo_detect_timer.stop()
        self._submit_timer.stop()

        self._db.end_session(self._session_id)

        for w in self._cam_workers.values():
            if hasattr(w, '_cap') and w._cap is not None:
                try: w._cap.release()
                except: pass
            w.stop()

        self._det_worker.stop()
        self._serial_reader.stop()

        ConfigManager.instance().save()
        self._db.close()
        event.accept()


