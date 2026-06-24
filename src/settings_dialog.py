"""
Settings Dialog — configure cameras, detection, alerts, and chassis overlay.
"""

from __future__ import annotations

import os, shutil

from PyQt5.QtWidgets import (
    QDialog, QTabWidget, QWidget, QFormLayout, QLineEdit,
    QCheckBox, QDoubleSpinBox, QSpinBox, QComboBox, QDialogButtonBox,
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
    """Displays the reference image with draggable red checkpoint rectangles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._checkpoints: dict[str, dict] = {}
        self._click_callback = None
        self._move_callback = None
        self._ix = self._iy = 0
        self.setMinimumSize(300, 200)
        self.setStyleSheet("background:#060812;")
        self.setMouseTracking(True)
        self._active: str | None = None
        self._drag_mode: str | None = None
        self._hovered: str | None = None
        self._hover_corner: str | None = None
        self._resize_init: tuple | None = None

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

    def set_move_callback(self, cb):
        self._move_callback = cb

    def _rect_px(self, cid: str) -> tuple[int, int, int, int]:
        cp = self._checkpoints[cid]
        fx, fy = cp.get("x", 0.5), cp.get("y", 0.5)
        mx = int(self._ix + fx * self._scaled.width())
        my = int(self._iy + fy * self._scaled.height())
        rw = max(16, int(self._scaled.width() * cp.get("w", 0.06)))
        rh = max(12, int(self._scaled.height() * cp.get("h", 0.06)))
        return mx, my, rw, rh

    def _corner_at(self, x: int, y: int, mx: int, my: int, rw: int, rh: int) -> str | None:
        hs = 5
        for corner, cx, cy in [("tl", mx - rw // 2, my - rh // 2),
                                ("tr", mx + rw // 2, my - rh // 2),
                                ("bl", mx - rw // 2, my + rh // 2),
                                ("br", mx + rw // 2, my + rh // 2)]:
            if cx - hs <= x <= cx + hs and cy - hs <= y <= cy + hs:
                return corner
        return None

    def _marker_at(self, x: int, y: int) -> str | None:
        if self._scaled is None:
            return None
        for cid in self._checkpoints:
            mx, my, rw, rh = self._rect_px(cid)
            if mx - rw // 2 <= x <= mx + rw // 2 and my - rh // 2 <= y <= my + rh // 2:
                return cid
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if self._scaled is None or self._pix is None:
            return
        x, y = event.x(), event.y()
        if self._active:
            mx, my, rw, rh = self._rect_px(self._active)
            corner = self._corner_at(x, y, mx, my, rw, rh)
            if corner:
                self._drag_mode = corner
                self._resize_init = (mx, my, rw, rh)
                if corner in ("tl", "bl"):
                    self.setCursor(Qt.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.SizeBDiagCursor)
                return
            if self._marker_at(x, y) == self._active:
                self._drag_mode = "move"
                self.setCursor(Qt.ClosedHandCursor)
                return
        cid = self._marker_at(x, y)
        if cid:
            self._active = cid
            self._drag_mode = "move"
            self.setCursor(Qt.ClosedHandCursor)
            return
        self._active = None
        self._drag_mode = None
        lx = x - self._ix
        ly = y - self._iy
        if 0 <= lx < self._scaled.width() and 0 <= ly < self._scaled.height():
            fx = lx / self._scaled.width()
            fy = ly / self._scaled.height()
            if self._click_callback:
                self._click_callback(fx, fy)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._scaled is None:
            return
        x, y = event.x(), event.y()
        mode = self._drag_mode

        if mode in ("tl", "tr", "bl", "br") and self._active:
            mx0, my0, rw0, rh0 = self._resize_init
            cp = self._checkpoints[self._active]
            nw = max(16, int(abs(x - mx0) * 2))
            nh = max(12, int(abs(y - my0) * 2))
            cp["w"] = nw / self._scaled.width()
            cp["h"] = nh / self._scaled.height()
            if self._move_callback:
                self._move_callback(self._active, cp.get("x"), cp.get("y"))
            self.update()

        elif mode == "move" and self._active:
            lx = x - self._ix
            ly = y - self._iy
            fx = max(0, min(1, lx / self._scaled.width()))
            fy = max(0, min(1, ly / self._scaled.height()))
            self._checkpoints[self._active]["x"] = fx
            self._checkpoints[self._active]["y"] = fy
            if self._move_callback:
                self._move_callback(self._active, fx, fy)
            self.update()

        else:
            self._hovered = self._marker_at(x, y)
            self._hover_corner = None
            if self._active and self._hovered == self._active:
                mx, my, rw, rh = self._rect_px(self._active)
                self._hover_corner = self._corner_at(x, y, mx, my, rw, rh)
            if self._hover_corner:
                if self._hover_corner in ("tl", "br"):
                    self.setCursor(Qt.SizeFDiagCursor)
                else:
                    self.setCursor(Qt.SizeBDiagCursor)
            elif self._hovered:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._drag_mode:
            self._drag_mode = None
            self._resize_init = None
            self.setCursor(Qt.ArrowCursor)
            if self._move_callback:
                self._move_callback(None, None, None)

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

        # Draw checkpoint rectangles
        for cid, cp in self._checkpoints.items():
            fx, fy = cp.get("x", 0.5), cp.get("y", 0.5)
            name = cp.get("name", cid)
            mx = int(self._ix + fx * px.width())
            my = int(self._iy + fy * px.height())

            rw = max(16, int(px.width() * cp.get("w", 0.06)))
            rh = max(12, int(px.height() * cp.get("h", 0.06)))
            rx, ry = mx - rw // 2, my - rh // 2

            is_active = cid == self._active
            is_hovered = cid == self._hovered and self._drag_mode is None

            base = QColor("#ff5252")
            fill = QColor(base)
            fill.setAlpha(30)
            bw = 2.6 if not (is_hovered or is_active) else 3.6

            painter.setBrush(fill)
            pen = QPen(base, bw)
            if is_active:
                pen.setStyle(Qt.SolidLine)
            else:
                pen.setStyle(Qt.DashLine)
                pen.setDashPattern([4, 3])
            painter.setPen(pen)
            painter.drawRect(QRect(rx, ry, rw, rh))

            painter.setPen(base)
            painter.setFont(QFont("Consolas", 7, QFont.Bold))
            painter.drawText(QRect(rx, ry, rw, rh), Qt.AlignCenter, cid.replace("CL-", ""))

            if is_active and self._drag_mode:
                lbl = f"{name}  ({fx:.3f}, {fy:.3f})"
            else:
                lbl = name[:16] + (".." if len(name) > 16 else "")

            painter.setFont(QFont("Segoe UI", 6))
            lx2 = mx + rw // 2 + 6
            ly2 = my - 5
            tw = painter.fontMetrics().horizontalAdvance(lbl) + 6
            th = 12
            painter.setBrush(QColor(0, 0, 0, 180))
            col = QColor("#ffd740") if is_active and self._drag_mode else QColor("#ff5252")
            painter.setPen(QPen(col, 1))
            painter.drawRoundedRect(lx2, ly2, tw, th, 3, 3)
            painter.setPen(col)
            painter.drawText(QRect(lx2 + 2, ly2, tw - 4, th),
                             Qt.AlignLeft | Qt.AlignVCenter, lbl)

        # Resize handles on active marker
        if self._active and self._active in self._checkpoints:
            amx, amy, arw, arh = self._rect_px(self._active)
            hs = 6
            hhs = hs // 2
            for cx, cy in [(amx - arw // 2, amy - arh // 2),
                           (amx + arw // 2, amy - arh // 2),
                           (amx - arw // 2, amy + arh // 2),
                           (amx + arw // 2, amy + arh // 2)]:
                painter.fillRect(cx - hhs, cy - hhs, hs, hs, QColor("#ff5252"))
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawRect(cx - hhs, cy - hhs, hs, hs)

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
        self._preview.set_move_callback(self._on_marker_moved)
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
            "💡 Click on the image to add a marker. Drag existing markers to reposition them. "
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

    def _on_marker_moved(self, cid: str | None, fx: float | None, fy: float | None):
        if cid is None:
            self._refresh_list()
        elif cid in self._checkpoints:
            self._checkpoints[cid]["x"] = fx
            self._checkpoints[cid]["y"] = fy

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

        # Theme selector row
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(12, 4, 12, 4)
        theme_lbl = QLabel("Appearance:")
        theme_lbl.setStyleSheet("color:#aabbcc; font-size:10px; font-weight:bold;")
        theme_row.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        self._theme_combo.setCurrentText(self._cfg.theme)
        self._theme_combo.setStyleSheet(
            "QComboBox{background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
            "border-radius:4px; padding:4px 8px;}"
            "QComboBox::drop-down{background:#2a2d3a; border:none; width:20px;}"
        )
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        root.addLayout(theme_row)

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

        self.__dict__[f"c{idx}_model"]   = _line(cfg.model_path)
        browse_btn = QPushButton("Browse…")
        browse_btn.setStyleSheet("background:#1c2050; color:#8899ff; border:none; border-radius:4px; padding:4px 10px;")
        browse_btn.clicked.connect(lambda: self._browse_cam_model(idx))
        model_row = QHBoxLayout()
        model_row.addWidget(self.__dict__[f"c{idx}_model"])
        model_row.addWidget(browse_btn)

        form.addRow("", self.__dict__[f"c{idx}_enabled"])
        form.addRow(QLabel("RTSP URL:", styleSheet=FORM_LBL),  self.__dict__[f"c{idx}_url"])
        form.addRow(QLabel("Label:", styleSheet=FORM_LBL),     self.__dict__[f"c{idx}_label"])
        form.addRow(QLabel("Digital Zoom:", styleSheet=FORM_LBL), self.__dict__[f"c{idx}_zoom"])
        form.addRow(QLabel("Target FPS:", styleSheet=FORM_LBL),   self.__dict__[f"c{idx}_fps"])
        form.addRow(QLabel("Reconnect (s):", styleSheet=FORM_LBL),self.__dict__[f"c{idx}_recon"])
        form.addRow(QLabel("YOLO Model (.pt):", styleSheet=FORM_LBL), model_row)

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

        if idx == 1:
            demo_lbl = QLabel("Demo Mode:", styleSheet=FORM_LBL)
            self._demo_combo = QComboBox()
            self._demo_combo.addItems(["Off (RTSP)", "Recorded (video files)", "Simulation (synthetic)"])
            dm = self._cfg.demo_mode
            self._demo_combo.setCurrentIndex(0 if dm == "off" else (1 if dm == "recorded" else 2))
            self._demo_combo.setStyleSheet(
                "QComboBox{background:#1c1f2e; color:#dde2f0; border:1px solid #2a2d3a;"
                "border-radius:4px; padding:4px 8px;}"
                "QComboBox::drop-down{background:#2a2d3a; border:none; width:20px;}"
            )
            form.addRow(demo_lbl, self._demo_combo)

        return w

    def _detection_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)
        d = self._cfg.detection

        self.d_nms   = _spin(d.nms_threshold, 0.1, 1.0)
        self.d_skip  = _ispin(d.frame_skip, 1, 10)
        self.d_model = _line(d.model_path)
        self.d_auto_zoom = _check(d.auto_zoom, "Auto-zoom camera on detected part")

        browse = QPushButton("Browse…")
        browse.setStyleSheet("background:#1c2050; color:#8899ff; border:none; border-radius:4px; padding:4px 10px;")
        browse.clicked.connect(self._browse_model)

        model_row = QHBoxLayout()
        model_row.addWidget(self.d_model)
        model_row.addWidget(browse)

        # ── Confidence threshold with +/- buttons ──
        conf_row = QHBoxLayout()
        self.d_conf = _spin(d.confidence_threshold, 0.01, 1.0, 0.01)
        self.d_conf.setFixedWidth(100)
        conf_dec_btn = QPushButton("−")
        conf_dec_btn.setFixedSize(32, 28)
        conf_dec_btn.setStyleSheet(
            "QPushButton{background:#2a0d0d; color:#ff5252; border:none; border-radius:4px; font-size:14px; font-weight:bold;}"
            "QPushButton:hover{background:#4a1a1a;}"
            "QPushButton:pressed{background:#6a2020;}"
        )
        conf_inc_btn = QPushButton("+")
        conf_inc_btn.setFixedSize(32, 28)
        conf_inc_btn.setStyleSheet(
            "QPushButton{background:#0d3320; color:#00e676; border:none; border-radius:4px; font-size:14px; font-weight:bold;}"
            "QPushButton:hover{background:#1a4a30;}"
            "QPushButton:pressed{background:#206040;}"
        )
        conf_dec_btn.clicked.connect(lambda: self._adjust_confidence(-0.05))
        conf_inc_btn.clicked.connect(lambda: self._adjust_confidence(0.05))

        self._conf_val_lbl = QLabel(f"{d.confidence_threshold:.2f}")
        self._conf_val_lbl.setFixedWidth(48)
        self._conf_val_lbl.setStyleSheet(
            "color:#00bcd4; font-size:13px; font-weight:bold; font-family:Consolas;"
            "background:#0d0f18; border:1px solid #2a2d3a; border-radius:4px; padding:2px 6px;"
        )
        self._conf_val_lbl.setAlignment(Qt.AlignCenter)
        conf_row.addWidget(conf_dec_btn)
        conf_row.addWidget(self._conf_val_lbl)
        conf_row.addWidget(conf_inc_btn)
        conf_row.addStretch()

        self.d_conf.valueChanged.connect(lambda v: self._conf_val_lbl.setText(f"{v:.2f}"))

        # Quick-preset buttons
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for label, val in [("LOW (0.25)", 0.25), ("MED (0.45)", 0.45), ("HIGH (0.70)", 0.70), ("MAX (0.90)", 0.90)]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton{background:#141828; color:#8899aa; border:1px solid #2a2d3a; border-radius:4px; font-size:8px; font-weight:bold; padding:0 8px;}"
                "QPushButton:hover{background:#1c2050; color:#8899ff;}"
            )
            btn.clicked.connect(lambda _, v=val: self._set_confidence(v))
            presets.addWidget(btn)
        presets.addStretch()

        conf_top = QVBoxLayout()
        conf_top.addLayout(conf_row)
        conf_top.addLayout(presets)

        form.addRow(QLabel("Confidence Threshold:", styleSheet=FORM_LBL), conf_top)
        form.addRow(QLabel("NMS Threshold:", styleSheet=FORM_LBL),        self.d_nms)
        form.addRow(QLabel("Frame Skip (1=every):", styleSheet=FORM_LBL), self.d_skip)
        form.addRow(QLabel("YOLO Model (.pt):", styleSheet=FORM_LBL),     model_row)
        form.addRow(QLabel("", styleSheet=FORM_LBL),
                    QLabel("Leave model path empty to use built-in rule-based detector.",
                           styleSheet="color:#667788; font-size:9px;"))
        form.addRow("", self.d_auto_zoom)
        return w

    def _adjust_confidence(self, delta: float):
        new_val = round(min(1.0, max(0.01, self.d_conf.value() + delta)), 2)
        self.d_conf.setValue(new_val)

    def _set_confidence(self, val: float):
        self.d_conf.setValue(val)

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

        form.addRow(QLabel("", styleSheet=FORM_LBL), QLabel("", styleSheet=FORM_LBL))
        form.addRow(QLabel("APPLICABLE VC NUMBERS", styleSheet="color:#00bcd4; font-size:10px; font-weight:bold;"))

        vc_list_row = QHBoxLayout()
        self._vc_list = QListWidget()
        self._vc_list.setStyleSheet(
            "QListWidget{background:#0d0f18; border:1px solid #2a2d3a; "
            "border-radius:4px; color:#dde2f0; font-size:9px;}"
            "QListWidget::item{ padding:4px 6px; }"
            "QListWidget::item:selected{ background:#1c2050; }"
        )
        vc_list_row.addWidget(self._vc_list, stretch=1)

        vc_btn_col = QVBoxLayout()
        vc_add_btn = QPushButton("+ Add")
        vc_add_btn.setStyleSheet("background:#0d3320; color:#00e676; border:none; border-radius:3px; padding:6px 10px;")
        vc_add_btn.clicked.connect(self._add_vc_number)
        vc_del_btn = QPushButton("✘ Delete")
        vc_del_btn.setStyleSheet("background:#2a0d0d; color:#ff5252; border:none; border-radius:3px; padding:6px 10px;")
        vc_del_btn.clicked.connect(self._delete_vc_number)
        vc_btn_col.addWidget(vc_add_btn)
        vc_btn_col.addWidget(vc_del_btn)
        vc_btn_col.addStretch()
        vc_list_row.addLayout(vc_btn_col)
        form.addRow(vc_list_row)

        self._refresh_vc_list()

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

    def _refresh_vc_list(self):
        self._vc_list.clear()
        for vc in sorted(self._cfg.valid_vc_numbers):
            QListWidgetItem(vc, self._vc_list)

    def _add_vc_number(self):
        vc, ok = QInputDialog.getText(
            self, "Add VC Number",
            "Enter applicable VC number:"
        )
        if ok and vc.strip():
            vc = vc.strip().upper()
            if vc in self._cfg.valid_vc_numbers:
                QMessageBox.warning(self, "Duplicate", f"VC {vc} already exists.")
                return
            self._cfg.valid_vc_numbers.append(vc)
            self._refresh_vc_list()

    def _delete_vc_number(self):
        item = self._vc_list.currentItem()
        if not item:
            return
        vc = item.text().strip()
        if vc in self._cfg.valid_vc_numbers:
            self._cfg.valid_vc_numbers.remove(vc)
            self._refresh_vc_list()

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

    def _browse_cam_model(self, idx: int):
        path, _ = QFileDialog.getOpenFileName(self, f"Select YOLO Model for Camera {idx}", "", "PyTorch Model (*.pt)")
        if path:
            self.__dict__[f"c{idx}_model"].setText(path)

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
            cam_cfg.model_path     = self.__dict__[f"c{idx}_model"].text().strip()

        cfg.detection.confidence_threshold = self.d_conf.value()
        cfg.detection.nms_threshold        = self.d_nms.value()
        cfg.detection.frame_skip           = self.d_skip.value()
        cfg.detection.model_path           = self.d_model.text().strip()
        cfg.detection.auto_zoom            = self.d_auto_zoom.isChecked()

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

        cfg.theme = self._theme_combo.currentText()

        dm_idx = self._demo_combo.currentIndex()
        cfg.demo_mode = ["off", "recorded", "simulation"][dm_idx]

        ConfigManager.instance().save()
        logger.info("Settings saved from dialog")
        self.accept()
