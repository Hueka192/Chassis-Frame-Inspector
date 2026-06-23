"""
Settings Dialog — configure cameras, detection, alerts, and chassis overlay.
"""

from __future__ import annotations

import os, shutil

from PyQt5.QtWidgets import (
    QDialog, QTabWidget, QWidget, QFormLayout, QLineEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox, QDialogButtonBox,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QListWidget, QListWidgetItem, QGridLayout, QSplitter, QFrame,
    QAbstractItemView, QInputDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QRect, QPoint
from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QBrush, QMouseEvent

from src.config_manager import ConfigManager
from src.logger import get_logger

logger = get_logger("settings")

_SLIDE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "assets", "checkpoint_slides")


def _line(val: str) -> QLineEdit:
    w = QLineEdit(val)
    w.setStyleSheet(
        "background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
        "border-radius:4px; padding:4px 6px;"
    )
    return w


def _spin(val: float, lo: float, hi: float, step: float = 0.05) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi); w.setSingleStep(step); w.setValue(val)
    w.setStyleSheet(
        "background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
        "border-radius:4px; padding:4px;"
    )
    return w


def _ispin(val: int, lo: int, hi: int) -> QSpinBox:
    w = QSpinBox()
    w.setRange(lo, hi); w.setValue(val)
    w.setStyleSheet(
        "background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
        "border-radius:4px; padding:4px;"
    )
    return w


def _check(val: bool, label: str) -> QCheckBox:
    w = QCheckBox(label)
    w.setChecked(val)
    w.setStyleSheet("color:#aabbcc;")
    return w


FORM_LBL = "color:#8899aa; font-size:10px;"


# ── Clickable image preview for checkpoint marking ──────────────────────────

class ImagePreview(QWidget):
    """Displays the reference image and emits clicked fraction coordinates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._checkpoints: dict[str, dict] = {}
        self._click_callback = None
        self._ix = self._iy = 0
        self.setMinimumSize(300, 200)
        self.setStyleSheet("background:#060812;")
        self.setMouseTracking(True)
        self._hover_pos: QPoint | None = None

    def set_image(self, path: str):
        if os.path.exists(path):
            px = QPixmap(path)
            if not px.isNull():
                self._pix = px
                self._scale()
                self.update()

    def set_checkpoints(self, cps: dict[str, dict]):
        self._checkpoints = dict(cps)
        self.update()

    def get_checkpoints(self) -> dict[str, dict]:
        return dict(self._checkpoints)

    def set_click_callback(self, cb):
        self._click_callback = cb

    def _scale(self):
        if self._pix is None:
            return
        m = min((self.width() - 20) / self._pix.width(),
                (self.height() - 20) / self._pix.height(), 1.0)
        nw = int(self._pix.width() * m)
        nh = int(self._pix.height() * m)
        self._scaled = self._pix.scaled(nw, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._ix = (self.width() - nw) // 2
        self._iy = (self.height() - nh) // 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale()

    def mousePressEvent(self, event: QMouseEvent):
        if self._scaled is None or self._pix is None:
            return
        lx = event.x() - self._ix
        ly = event.y() - self._iy
        if 0 <= lx < self._scaled.width() and 0 <= ly < self._scaled.height():
            fx = lx / self._scaled.width()
            fy = ly / self._scaled.height()
            if self._click_callback:
                self._click_callback(fx, fy)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._hover_pos = event.pos()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        painter.fillRect(0, 0, W, H, QColor(6, 8, 18))

        if self._pix is None or self._scaled is None:
            painter.setPen(QColor(60, 65, 85))
            painter.setFont(QFont("Consolas", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, "No reference image loaded\nUpload one below")
            painter.end()
            return

        self._scale()
        px = self._scaled
        painter.drawPixmap(self._ix, self._iy, px)

        # Draw checkpoints
        for cid, cp in self._checkpoints.items():
            fx, fy = cp.get("x", 0.5), cp.get("y", 0.5)
            name = cp.get("name", cid)
            mx = int(self._ix + fx * px.width())
            my = int(self._iy + fy * px.height())
            r = 7
            painter.setBrush(QColor("#00bcd4"))
            painter.setPen(QPen(QColor("#00e676"), 2))
            painter.drawEllipse(QPoint(mx, my), r, r)
            painter.setPen(QColor("#00e676"))
            painter.setFont(QFont("Consolas", 7, QFont.Bold))
            painter.drawText(QRect(mx - r, my - r, r * 2, r * 2),
                             Qt.AlignCenter, cid.replace("CL-", ""))
            lbl = name[:16] + (".." if len(name) > 16 else "")
            painter.setFont(QFont("Segoe UI", 6))
            lx2 = mx + 10
            ly2 = my - 5
            tw = painter.fontMetrics().horizontalAdvance(lbl) + 6
            th = 12
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.setPen(QPen(QColor("#00e676"), 1))
            painter.drawRoundedRect(lx2, ly2, tw, th, 3, 3)
            painter.setPen(QColor("#00e676"))
            painter.drawText(QRect(lx2 + 2, ly2, tw - 4, th),
                             Qt.AlignLeft | Qt.AlignVCenter, lbl)

        painter.end()


# ── Overlay / Checkpoint Tab ───────────────────────────────────────────────

class OverlayTab(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self._checkpoints: dict[str, dict] = {}
        self._ref_path = ""
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Reference image row ──
        img_row = QHBoxLayout()
        self._img_lbl = QLabel(f"Current image: {self._cfg.reference_image}")
        self._img_lbl.setStyleSheet("color:#aabbcc; font-size:10px;")
        img_row.addWidget(self._img_lbl)
        img_row.addStretch()
        upload_btn = QPushButton("📁  Upload Reference Image")
        upload_btn.setStyleSheet(
            "QPushButton{background:#1c2050; color:#8899ff; border:none; "
            "border-radius:4px; padding:6px 14px;}"
            "QPushButton:hover{background:#2a30a0;}"
        )
        upload_btn.clicked.connect(self._upload_image)
        img_row.addWidget(upload_btn)
        root.addLayout(img_row)

        # ── Splitter: preview left, list right ──
        split = QSplitter(Qt.Horizontal)

        self._preview = ImagePreview()
        self._preview.set_click_callback(self._on_preview_click)
        split.addWidget(self._preview)

        # Right: checkpoint list + controls
        right = QWidget()
        right.setMinimumWidth(260)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        rl.addWidget(QLabel("Checkpoint Markers:", styleSheet="color:#00bcd4; font-size:10px; font-weight:bold;"))

        self._cp_list = QListWidget()
        self._cp_list.setStyleSheet(
            "QListWidget{background:#0d0f18; border:1px solid #2a2d3a; "
            "border-radius:4px; color:#dde2f0; font-size:9px;}"
            "QListWidget::item{ padding:4px 6px; }"
            "QListWidget::item:selected{ background:#1c2050; }"
        )
        rl.addWidget(self._cp_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.setStyleSheet("background:#0d3320; color:#00e676; border:none; border-radius:3px; padding:4px 10px;")
        btn_add.clicked.connect(self._add_checkpoint)
        btn_del = QPushButton("✘ Delete")
        btn_del.setStyleSheet("background:#2a0d0d; color:#ff5252; border:none; border-radius:3px; padding:4px 10px;")
        btn_del.clicked.connect(self._delete_checkpoint)
        btn_ren = QPushButton("✎ Rename")
        btn_ren.setStyleSheet("background:#1c1f2e; color:#ffd740; border:none; border-radius:3px; padding:4px 10px;")
        btn_ren.clicked.connect(self._rename_checkpoint)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_ren)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        rl.addLayout(btn_row)

        split.addWidget(right)
        split.setSizes([400, 280])
        root.addWidget(split, stretch=1)

        # Instructions
        inst = QLabel(
            "💡 Click on the image to add a checkpoint marker at that position. "
            "Use the list to rename or delete markers. Changes take effect after clicking OK."
        )
        inst.setWordWrap(True)
        inst.setStyleSheet("color:#667788; font-size:8px; padding:4px;")
        root.addWidget(inst)

        # Load current data
        self._load_config()

    def _load_config(self):
        self._checkpoints = {}
        for cid, cp in self._cfg.checkpoints.items():
            self._checkpoints[cid] = dict(cp)
        self._ref_path = os.path.join(_SLIDE_DIR, self._cfg.reference_image)
        self._preview.set_image(self._ref_path)
        self._preview.set_checkpoints(self._checkpoints)
        self._refresh_list()

    def _refresh_list(self):
        self._cp_list.clear()
        for cid in sorted(self._checkpoints.keys()):
            cp = self._checkpoints[cid]
            name = cp.get("name", cid)
            x, y = cp.get("x", 0), cp.get("y", 0)
            QListWidgetItem(f"{cid}  |  {name}  ({x:.2f}, {y:.2f})", self._cp_list)

    def _upload_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        dst = os.path.join(_SLIDE_DIR, os.path.basename(path))
        try:
            shutil.copy2(path, dst)
        except shutil.SameFileError:
            pass
        self._cfg.reference_image = os.path.basename(path)
        self._ref_path = dst
        self._img_lbl.setText(f"Current image: {self._cfg.reference_image}")
        self._preview.set_image(dst)
        self._preview.set_checkpoints(self._checkpoints)

    def _on_preview_click(self, fx: float, fy: float):
        """User clicked on the image → add marker prompted."""
        cid, ok = QInputDialog.getText(
            self, "New Checkpoint Marker",
            "Enter checkpoint ID (e.g. CL-12):",
            text=f"CL-{len(self._checkpoints)+1:02d}"
        )
        if not ok or not cid.strip():
            return
        cid = cid.strip().upper()
        name, ok2 = QInputDialog.getText(
            self, "Checkpoint Name",
            "Enter checkpoint name:",
            text="New Checkpoint"
        )
        if not ok2:
            return
        self._checkpoints[cid] = {"name": name.strip(), "x": fx, "y": fy}
        self._preview.set_checkpoints(self._checkpoints)
        self._refresh_list()

    def _add_checkpoint(self):
        """Manually add via ID input."""
        cid, ok = QInputDialog.getText(
            self, "Add Checkpoint", "Enter checkpoint ID (e.g. CL-12):",
            text=f"CL-{len(self._checkpoints)+1:02d}"
        )
        if not ok or not cid.strip():
            return
        cid = cid.strip().upper()
        if cid in self._checkpoints:
            QMessageBox.warning(self, "Duplicate", f"{cid} already exists.")
            return
        name, ok2 = QInputDialog.getText(self, "Checkpoint Name", "Enter name:")
        if not ok2:
            return
        x, ok3 = QInputDialog.getDouble(self, "X Position", "X (0.00–1.00):", 0.5, 0.0, 1.0, 2)
        if not ok3:
            return
        y, ok4 = QInputDialog.getDouble(self, "Y Position", "Y (0.00–1.00):", 0.5, 0.0, 1.0, 2)
        if not ok4:
            return
        self._checkpoints[cid] = {"name": name.strip(), "x": x, "y": y}
        self._preview.set_checkpoints(self._checkpoints)
        self._refresh_list()

    def _delete_checkpoint(self):
        item = self._cp_list.currentItem()
        if not item:
            return
        txt = item.text()
        cid = txt.split("  |")[0].strip()
        if cid in self._checkpoints:
            del self._checkpoints[cid]
            self._preview.set_checkpoints(self._checkpoints)
            self._refresh_list()

    def _rename_checkpoint(self):
        item = self._cp_list.currentItem()
        if not item:
            return
        txt = item.text()
        cid = txt.split("  |")[0].strip()
        if cid not in self._checkpoints:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Checkpoint", "New name:",
            text=self._checkpoints[cid]["name"]
        )
        if ok and name.strip():
            self._checkpoints[cid]["name"] = name.strip()
            self._preview.set_checkpoints(self._checkpoints)
            self._refresh_list()

    def get_data(self):
        return self._checkpoints, self._cfg.reference_image


# ── Main Settings Dialog ───────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — Chassis Frame Inspector")
        self.setMinimumSize(800, 560)
        self.setStyleSheet(
            "QDialog{background:#0d0f14; color:#dde2f0;}"
            "QTabWidget::pane{background:#12141e; border:1px solid #2a2d3a;}"
            "QTabBar::tab{background:#141828; color:#8899aa; padding:6px 16px;}"
            "QTabBar::tab:selected{background:#1c1f2e; color:#dde2f0;}"
            "QLabel{color:#8899aa;}"
        )
        self._cfg = ConfigManager.instance().cfg
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._camera_tab(1), "Camera 1")
        tabs.addTab(self._camera_tab(2), "Camera 2")
        tabs.addTab(self._detection_tab(), "Detection")
        tabs.addTab(self._serial_db_tab(), "Serial & DB")
        tabs.addTab(self._alert_tab(), "Alerts")
        self._overlay_tab = OverlayTab(self._cfg)
        tabs.addTab(self._overlay_tab, "Chassis Overlay")
        root.addWidget(tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet(
            "QPushButton{background:#1c2050; color:#8899ff; border:none;"
            "border-radius:4px; padding:6px 18px;}"
            "QPushButton:hover{background:#2a30a0;}"
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _camera_tab(self, idx: int) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)
        cfg = self._cfg.camera1 if idx == 1 else self._cfg.camera2

        self.__dict__[f"c{idx}_enabled"] = _check(cfg.enabled, "Enable Camera")
        self.__dict__[f"c{idx}_url"]     = _line(cfg.rtsp_url)
        self.__dict__[f"c{idx}_label"]   = _line(cfg.label)
        self.__dict__[f"c{idx}_zoom"]    = _spin(cfg.digital_zoom, 1.0, 4.0, 0.1)
        self.__dict__[f"c{idx}_fps"]     = _ispin(cfg.fps, 1, 30)
        self.__dict__[f"c{idx}_recon"]   = _ispin(cfg.reconnect_delay, 1, 30)

        form.addRow("", self.__dict__[f"c{idx}_enabled"])
        form.addRow(QLabel("RTSP URL:", styleSheet=FORM_LBL),  self.__dict__[f"c{idx}_url"])
        form.addRow(QLabel("Label:", styleSheet=FORM_LBL),     self.__dict__[f"c{idx}_label"])
        form.addRow(QLabel("Digital Zoom:", styleSheet=FORM_LBL), self.__dict__[f"c{idx}_zoom"])
        form.addRow(QLabel("Target FPS:", styleSheet=FORM_LBL),   self.__dict__[f"c{idx}_fps"])
        form.addRow(QLabel("Reconnect (s):", styleSheet=FORM_LBL),self.__dict__[f"c{idx}_recon"])

        test_btn = QPushButton(f"Test Camera {idx}")
        test_btn.setStyleSheet(
            "background:#0d3320; color:#00e676; border:none; border-radius:4px; padding:6px 14px;"
        )
        test_btn.clicked.connect(lambda: self._test_camera(idx))
        self.__dict__[f"c{idx}_test_lbl"] = QLabel("")
        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self.__dict__[f"c{idx}_test_lbl"])
        row.addStretch()
        form.addRow("", row)

        return w

    def _detection_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)
        d = self._cfg.detection

        self.d_conf  = _spin(d.confidence_threshold, 0.1, 1.0)
        self.d_nms   = _spin(d.nms_threshold, 0.1, 1.0)
        self.d_skip  = _ispin(d.frame_skip, 1, 10)
        self.d_model = _line(d.model_path)

        browse = QPushButton("Browse…")
        browse.setStyleSheet("background:#1c2050; color:#8899ff; border:none; border-radius:4px; padding:4px 10px;")
        browse.clicked.connect(self._browse_model)

        model_row = QHBoxLayout()
        model_row.addWidget(self.d_model)
        model_row.addWidget(browse)

        form.addRow(QLabel("Confidence Threshold:", styleSheet=FORM_LBL), self.d_conf)
        form.addRow(QLabel("NMS Threshold:", styleSheet=FORM_LBL),        self.d_nms)
        form.addRow(QLabel("Frame Skip (1=every):", styleSheet=FORM_LBL), self.d_skip)
        form.addRow(QLabel("YOLO Model (.pt):", styleSheet=FORM_LBL),     model_row)
        form.addRow(QLabel("", styleSheet=FORM_LBL),
                    QLabel("Leave model path empty to use built-in rule-based detector.",
                           styleSheet="color:#667788; font-size:9px;"))
        return w

    def _serial_db_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(16, 16, 16, 16)
        s = self._cfg.serial
        d = self._cfg.database

        form.addRow(QLabel("SERIAL PORT", styleSheet="color:#00bcd4; font-size:10px; font-weight:bold;"))

        self.s_enabled  = _check(s.enabled, "Enable Serial Reader")
        self.s_port     = _line(s.port)
        self.s_baud     = _ispin(s.baudrate, 110, 115200)
        self.s_parity   = _line(s.parity)

        form.addRow("", self.s_enabled)
        form.addRow(QLabel("Port:", styleSheet=FORM_LBL),       self.s_port)
        form.addRow(QLabel("Baud Rate:", styleSheet=FORM_LBL),  self.s_baud)
        form.addRow(QLabel("Parity:", styleSheet=FORM_LBL),     self.s_parity)

        form.addRow(QLabel("", styleSheet=FORM_LBL),
                    QLabel("Format: 9600 8N-1, flow none",
                           styleSheet="color:#667788; font-size:9px;"))

        form.addRow(QLabel("DATABASE", styleSheet="color:#00bcd4; font-size:10px; font-weight:bold;"))

        self.db_host = _line(d.host)
        self.db_port = _ispin(d.port, 1, 65535)
        self.db_name = _line(d.database)
        self.db_user = _line(d.user)
        self.db_pass = QLineEdit(d.password)
        self.db_pass.setEchoMode(QLineEdit.Password)
        self.db_pass.setStyleSheet(
            "background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
            "border-radius:4px; padding:4px 6px;"
        )

        form.addRow(QLabel("Host:", styleSheet=FORM_LBL),      self.db_host)
        form.addRow(QLabel("Port:", styleSheet=FORM_LBL),      self.db_port)
        form.addRow(QLabel("Database:", styleSheet=FORM_LBL),  self.db_name)
        form.addRow(QLabel("User:", styleSheet=FORM_LBL),      self.db_user)
        form.addRow(QLabel("Password:", styleSheet=FORM_LBL),  self.db_pass)

        form.addRow(QLabel("TABLE MAPPING", styleSheet="color:#00bcd4; font-size:10px; font-weight:bold;"))

        self.db_table   = _line(d.table)
        self.db_vin_col = _line(d.vin_column)
        self.db_vc_col  = _line(d.vc_column)

        form.addRow(QLabel("Table:", styleSheet=FORM_LBL),       self.db_table)
        form.addRow(QLabel("VIN Column:", styleSheet=FORM_LBL),  self.db_vin_col)
        form.addRow(QLabel("VC Column:", styleSheet=FORM_LBL),   self.db_vc_col)

        test_btn = QPushButton("Test Connection")
        test_btn.setStyleSheet(
            "background:#0d3320; color:#00e676; border:none; border-radius:4px; padding:6px 14px;"
        )
        test_btn.clicked.connect(self._test_db_connection)
        self._db_test_lbl = QLabel("")
        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self._db_test_lbl)
        row.addStretch()
        form.addRow("", row)

        return w

    def _test_db_connection(self):
        self._db_test_lbl.setText("Testing…")
        self._db_test_lbl.setStyleSheet("color:#ffd740;")
        QDialog.repaint(self)
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=self.db_host.text().strip(),
                port=self.db_port.value(),
                dbname=self.db_name.text().strip(),
                user=self.db_user.text().strip(),
                password=self.db_pass.text().strip(),
                connect_timeout=5,
            )
            conn.close()
            self._db_test_lbl.setText("✔ Connected")
            self._db_test_lbl.setStyleSheet("color:#00e676;")
        except Exception as e:
            self._db_test_lbl.setText(f"✘ {e}")
            self._db_test_lbl.setStyleSheet("color:#ff5252;")

    def _alert_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)
        a = self._cfg.alert

        self.a_sound  = _check(a.missing_part_sound, "Play sound on missing part")
        self.a_log    = _check(a.log_missing_frames, "Log frames with missing parts")
        self.a_save   = _check(a.auto_save_ng_frames, "Auto-save NG frame images")

        form.addRow("", self.a_sound)
        form.addRow("", self.a_log)
        form.addRow("", self.a_save)
        return w

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select YOLO Model", "", "PyTorch Model (*.pt)")
        if path:
            self.d_model.setText(path)

    def _test_camera(self, idx: int):
        import cv2
        url = self.__dict__[f"c{idx}_url"].text().strip()
        lbl = self.__dict__[f"c{idx}_test_lbl"]
        lbl.setText("Testing…")
        lbl.setStyleSheet("color:#ffd740;")
        QDialog.repaint(self)
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    lbl.setText("✔ OK")
                    lbl.setStyleSheet("color:#00e676;")
                    return
            lbl.setText("✘ Failed")
            lbl.setStyleSheet("color:#ff5252;")
        except Exception as e:
            lbl.setText(f"✘ {e}")
            lbl.setStyleSheet("color:#ff5252;")

    def _save(self):
        cfg = self._cfg
        for idx, cam_cfg in [(1, cfg.camera1), (2, cfg.camera2)]:
            cam_cfg.enabled        = self.__dict__[f"c{idx}_enabled"].isChecked()
            cam_cfg.rtsp_url       = self.__dict__[f"c{idx}_url"].text().strip()
            cam_cfg.label          = self.__dict__[f"c{idx}_label"].text().strip()
            cam_cfg.digital_zoom   = self.__dict__[f"c{idx}_zoom"].value()
            cam_cfg.fps            = self.__dict__[f"c{idx}_fps"].value()
            cam_cfg.reconnect_delay= self.__dict__[f"c{idx}_recon"].value()

        cfg.detection.confidence_threshold = self.d_conf.value()
        cfg.detection.nms_threshold        = self.d_nms.value()
        cfg.detection.frame_skip           = self.d_skip.value()
        cfg.detection.model_path           = self.d_model.text().strip()

        cfg.alert.missing_part_sound   = self.a_sound.isChecked()
        cfg.alert.log_missing_frames   = self.a_log.isChecked()
        cfg.alert.auto_save_ng_frames  = self.a_save.isChecked()

        cfg.serial.enabled   = self.s_enabled.isChecked()
        cfg.serial.port      = self.s_port.text().strip()
        cfg.serial.baudrate  = self.s_baud.value()
        cfg.serial.parity    = self.s_parity.text().strip().upper()

        cfg.database.host       = self.db_host.text().strip()
        cfg.database.port       = self.db_port.value()
        cfg.database.database   = self.db_name.text().strip()
        cfg.database.user       = self.db_user.text().strip()
        cfg.database.password   = self.db_pass.text().strip()
        cfg.database.table      = self.db_table.text().strip()
        cfg.database.vin_column = self.db_vin_col.text().strip()
        cfg.database.vc_column  = self.db_vc_col.text().strip()

        # Save overlay data
        cps, ref_img = self._overlay_tab.get_data()
        cfg.checkpoints = cps
        cfg.reference_image = ref_img

        ConfigManager.instance().save()
        logger.info("Settings saved from dialog")
        self.accept()
