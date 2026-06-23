"""
Checklist Grid Panel
=====================
Lower-tier inspection checklist — a compact, text-only grid of checkbox
rows below the camera feed and chassis reference image. No photos here
by design: the reference photos live on the chassis panel (right side),
this panel is a fast, scan-free "all items visible at a glance" list.

The grid auto-balances its row/column count against the available width
so the *entire* checklist for the active vehicle model is visible without
scrolling for normal checklist lengths (a scroll fallback only engages
for pathologically long lists).

Each row shows:
  • a checkbox synced to detection state (operator can confirm/override)
  • a small status dot — RED = not detected, GREEN = detected
  • the part name (numbered, matching the master reference deck) and a
    dim caption with its id / qty / fitment location

The checklist is vehicle-model specific: calling :meth:`load_vehicle`
rebuilds the grid from ``VehicleModel.checklist``, so a different VC
prefix (different model) shows a different set of rows automatically.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from src.logger import get_logger
from src.models import VehicleModel

logger = get_logger("checklist")

# ── Palette ──────────────────────────────────────────────────────────────
_OK_COLOR       = "#00e676"   # detected — green
_NOT_OK_COLOR   = "#ff5252"   # not detected — red
_NA_COLOR       = "#ffb300"   # not applicable — amber
_PANEL_BG       = "#0a0c14"
_ROW_BG         = "#11141f"
_ROW_BG_OK      = "#06190f"
_ROW_BG_NA      = "#1a1400"
_TEXT_PRIMARY   = "#dde2f0"
_TEXT_DIM       = "#7c8aa3"

_MIN_ROW_WIDTH  = 300
_ROW_HEIGHT     = 48
_MAX_ROWS_CAP   = 8


def _checkpoint_number(item_id: str) -> str:
    """Extract a clean leading number from an item id like 'CL-07' → '7'."""
    digits = "".join(ch for ch in item_id if ch.isdigit())
    return str(int(digits)) if digits else item_id


class StatusDot(QWidget):
    """Small status indicator — pulsing red (not detected) / solid green (detected) / amber (NA)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(13, 13)
        self._status = "PENDING"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(110)

    def _tick(self):
        if self._status == "PENDING":
            self._phase = (self._phase + 0.04) % 1.0
            self.update()
        elif self._status == "NA":
            self._phase = (self._phase + 0.03) % 1.0
            self.update()

    def set_status(self, status: str):
        if self._status != status:
            self._status = status
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        if self._status == "OK":
            p.setBrush(QColor(_OK_COLOR))
            p.setPen(Qt.NoPen)
            p.drawEllipse(center, 5.5, 5.5)
        elif self._status == "NA":
            p.setBrush(QColor(_NA_COLOR))
            p.setPen(Qt.NoPen)
            p.drawEllipse(center, 5.5, 5.5)
        else:
            pulse = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi)
            p.setBrush(QColor(_NOT_OK_COLOR))
            p.setPen(Qt.NoPen)
            p.drawEllipse(center, 3.6 + 1.2 * pulse, 3.6 + 1.2 * pulse)
        p.end()


class ChecklistRow(QFrame):
    """A single text-only checklist row: checkbox + status dot + name/id."""

    def __init__(self, item, on_toggle: Callable[[str, str], None],
                 scale: float = 1.0,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self._on_toggle = on_toggle
        self._status = "PENDING"
        rh = max(36, int(_ROW_HEIGHT * scale))

        self.setFixedHeight(rh)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(f"{item.id} — {item.description or item.name}")

        row = QHBoxLayout(self)
        row.setContentsMargins(max(6, int(10 * scale)), max(2, int(4 * scale)),
                               max(6, int(10 * scale)), max(2, int(4 * scale)))
        row.setSpacing(max(4, int(8 * scale)))

        cbsz = max(14, int(18 * scale))
        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(cbsz, cbsz)
        self._checkbox.clicked.connect(self._on_checkbox_clicked)
        row.addWidget(self._checkbox)

        self._dot = StatusDot()
        self._dot.setFixedSize(max(10, int(13 * scale)), max(10, int(13 * scale)))
        row.addWidget(self._dot)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)

        num = _checkpoint_number(item.id)
        full_label = f"{num}. {item.name}"
        display_label = (full_label if len(full_label) <= 42
                         else full_label[:40].rstrip() + "…")
        nfsz = max(9, int(11 * scale))
        self._name_lbl = QLabel(display_label)
        self._name_lbl.setStyleSheet(
            f"color:{_TEXT_PRIMARY}; font-size:{nfsz}px; font-weight:600; "
            "background:transparent;"
        )
        self._name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        text_box.addWidget(self._name_lbl)

        qty_txt = f"×{item.qty}  " if getattr(item, "qty", 1) and item.qty > 1 else ""
        ffsz = max(7, int(8 * scale))
        foot = QLabel(f"{item.id}  ·  {qty_txt}{item.location or '—'}")
        foot.setStyleSheet(
            f"color:{_TEXT_DIM}; font-size:{ffsz}px; font-family:Consolas; "
            "background:transparent;"
        )
        text_box.addWidget(foot)

        row.addLayout(text_box, stretch=1)
        self._apply_row_style()

    # -- Public API -------------------------------------------------------
    def set_status(self, status: str):
        """status in {'PENDING', 'OK', 'NG', 'NA'}."""
        self._status = status
        self._dot.set_status(status)
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(status == "OK")
        self._checkbox.blockSignals(False)
        self._apply_row_style()

    @property
    def status(self) -> str:
        return self._status

    # -- Internal -----------------------------------------------------------
    def _apply_row_style(self):
        if self._status == "OK":
            bg, border = _ROW_BG_OK, _OK_COLOR + "77"
        elif self._status == "NA":
            bg, border = _ROW_BG_NA, _NA_COLOR + "77"
        else:
            bg, border = _ROW_BG, _NOT_OK_COLOR + "44"
        self.setStyleSheet(
            f"ChecklistRow{{background:{bg}; border:1px solid {border}; "
            "border-radius:6px;}"
        )

    def _on_checkbox_clicked(self, checked: bool):
        new_status = "OK" if checked else "PENDING"
        self.set_status(new_status)
        self._on_toggle(self.item.id, new_status)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._checkbox.setChecked(not self._checkbox.isChecked())
            self._on_checkbox_clicked(self._checkbox.isChecked())
        super().mousePressEvent(event)


class ChecklistGridPanel(QWidget):
    """
    Full-width lower-tier checklist panel. Lays out checkpoint rows in a
    compact, width-aware grid (no images) so the *whole* checklist for the
    active vehicle model fits on screen without scrolling under normal
    conditions; a scroll fallback only engages for unusually long lists.
    """

    item_changed = pyqtSignal(str, str)

    def __init__(self, scale: float = 1.0, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scale = scale
        self.setStyleSheet(f"background:{_PANEL_BG};")
        self._rows: Dict[str, ChecklistRow] = {}
        self._row_order: List[str] = []
        self._model: Optional[VehicleModel] = None
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)
        self._build()

    # -- UI construction ----------------------------------------------------
    def _build(self):
        s = self._scale
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hh = max(22, int(28 * s))
        header = QWidget()
        header.setFixedHeight(hh)
        header.setStyleSheet(f"background:{_PANEL_BG}; border-top:1px solid #1a1d28;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(max(8, int(12 * s)), max(1, int(2 * s)), max(8, int(12 * s)), max(1, int(2 * s)))
        hl.setSpacing(max(6, int(10 * s)))

        tfsz = max(9, int(10 * s))
        title = QLabel("☑ INSPECTION CHECKLIST")
        title.setStyleSheet(
            f"color:#aa88ff; font-size:{tfsz}px; font-weight:bold; "
            "letter-spacing:1.5px; background:transparent;"
        )
        hl.addWidget(title)

        mfsz = max(9, int(10 * s))
        self._model_lbl = QLabel("— scan VIN / VC to load checklist —")
        self._model_lbl.setStyleSheet(
            f"color:{_TEXT_DIM}; font-size:{mfsz}px; background:transparent;"
        )
        hl.addWidget(self._model_lbl, stretch=1)

        lfsz = max(8, int(9 * s))
        legend = QLabel()
        legend.setTextFormat(Qt.RichText)
        legend.setText(
            f'<span style="color:{_NOT_OK_COLOR}">●</span> NOT DETECTED &nbsp;&nbsp; '
            f'<span style="color:{_OK_COLOR}">●</span> DETECTED'
        )
        legend.setStyleSheet(f"font-size:{lfsz}px; font-weight:bold; background:transparent;")
        hl.addWidget(legend)

        pfsz = max(10, int(11 * s))
        self._progress_lbl = QLabel("0 / 0")
        self._progress_lbl.setStyleSheet(
            f"color:#00bcd4; font-size:{pfsz}px; font-weight:bold; "
            "font-family:Consolas; background:transparent;"
        )
        self._progress_lbl.setFixedWidth(max(50, int(60 * s)))
        self._progress_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(self._progress_lbl)

        root.addWidget(header)

        # Grid host — no scrollbar in normal operation (sized to fit), but
        # wrapped in a QScrollArea as a defensive fallback for unusually
        # long checklists so the UI degrades gracefully instead of clipping.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"QScrollArea{{background:{_PANEL_BG}; border:none;}}")

        self._grid_host = QWidget()
        self._grid_host.setStyleSheet(f"background:{_PANEL_BG};")
        self._grid = QGridLayout(self._grid_host)
        gm = max(6, int(10 * s))
        self._grid.setContentsMargins(gm, max(4, int(8 * s)), gm, max(4, int(8 * s)))
        gs = max(4, int(8 * s))
        self._grid.setHorizontalSpacing(gs)
        self._grid.setVerticalSpacing(gs)
        self._scroll.setWidget(self._grid_host)
        root.addWidget(self._scroll, stretch=1)

        # Idle placeholder (shown when no vehicle is loaded)
        ifsz = max(10, int(11 * s))
        self._idle_lbl = QLabel(
            "Scan or enter a VIN / VC number in the dashboard above to load "
            "the model-specific inspection checklist."
        )
        self._idle_lbl.setAlignment(Qt.AlignCenter)
        self._idle_lbl.setWordWrap(True)
        self._idle_lbl.setStyleSheet(
            f"color:{_TEXT_DIM}; font-size:{ifsz}px; background:transparent;"
        )
        self._grid.addWidget(self._idle_lbl, 0, 0)

    # -- Public API ----------------------------------------------------------
    def load_vehicle(self, vc: str, model: VehicleModel, vin: str = ""):
        """Rebuild the checklist grid for the resolved vehicle model."""
        self._model = model
        self._clear_grid()
        self._idle_lbl.setVisible(False)

        self._model_lbl.setText(f"{model.name}  ({model.code})")

        for item in model.checklist:
            row_widget = ChecklistRow(item, self._handle_row_toggle, scale=self._scale)
            self._rows[item.id] = row_widget
            self._row_order.append(item.id)

        self._relayout()
        self._update_progress()
        # The panel may not have its final on-screen height yet (e.g. right
        # after the splitter is constructed) — re-flow once more on the next
        # event-loop tick so the row/column count reflects real geometry.
        QTimer.singleShot(0, self._relayout)
        logger.info(
            f"Checklist loaded: model={model.code} items={len(model.checklist)} "
            f"vc={vc} vin={vin}"
        )

    def clear_vehicle(self):
        """Return to the idle state (no vehicle loaded)."""
        self._model = None
        self._clear_grid()
        self._model_lbl.setText("— scan VIN / VC to load checklist —")
        self._idle_lbl.setVisible(True)
        self._grid.addWidget(self._idle_lbl, 0, 0)
        self._update_progress()

    def auto_detect_item(self, item_id: str):
        """Called by the vision pipeline when a checkpoint is confirmed."""
        row = self._rows.get(item_id)
        if row is not None:
            row.set_status("OK")
            self._update_progress()

    def reset(self):
        """Reset all current rows back to NOT DETECTED (used pre-next-vehicle)."""
        for row in self._rows.values():
            row.set_status("PENDING")
        self._update_progress()

    def get_results(self) -> Dict[str, str]:
        """Return {item_id: status} for the currently loaded checklist."""
        return {iid: row.status for iid, row in self._rows.items()}

    # -- Internal --------------------------------------------------------
    def _clear_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._idle_lbl:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._row_order.clear()

    def _handle_row_toggle(self, item_id: str, status: str):
        self._update_progress()
        self.item_changed.emit(item_id, status)

    def _update_progress(self):
        total = len(self._rows)
        done = sum(1 for r in self._rows.values() if r.status == "OK")
        self._progress_lbl.setText(f"{done} / {total}" if total else "0 / 0")
        color = "#00e676" if total and done == total else "#00bcd4"
        self._progress_lbl.setStyleSheet(
            f"color:{color}; font-size:11px; font-weight:bold; "
            "font-family:Consolas; background:transparent;"
        )

    def _compute_grid_dims(self, n: int, avail_w: int, avail_h: int) -> tuple[int, int]:
        """
        Pick (rows, cols) so the whole checklist fits the panel **without
        scrolling**. The available height is the hard constraint (that's
        what determines whether a scrollbar would appear), so we first work
        out the most rows that can fit vertically, then use the fewest rows
        within that budget — maximising columns — so each row stays as wide
        (and readable) as the available width allows.
        """
        if n <= 0:
            return 1, 1

        row_unit = int(_ROW_HEIGHT * self._scale) + int(8 * self._scale)
        max_rows_h = max(1, (avail_h + int(8 * self._scale)) // row_unit)
        max_rows_h = min(max_rows_h, _MAX_ROWS_CAP)

        col_unit = int(_MIN_ROW_WIDTH * self._scale) + int(8 * self._scale)
        max_cols_w = max(1, (avail_w + int(8 * self._scale)) // col_unit)

        # Use as many columns as width comfortably allows (minimises rows),
        # then clamp to what actually fits vertically without a scrollbar.
        cols = max(1, min(n, max_cols_w))
        rows = math.ceil(n / cols)
        if rows > max_rows_h:
            rows = max_rows_h
            cols = math.ceil(n / rows)  # may exceed max_cols_w — narrower
                                         # columns are preferable to scrolling
        return max(1, rows), max(1, cols)

    def _relayout(self):
        """Re-flow existing row widgets into a width-and-height-aware grid."""
        if not self._row_order:
            return

        # Detach widgets without deleting them.
        while self._grid.count():
            self._grid.takeAt(0)

        avail_w = self._grid_host.width() or self.width() or 1200
        avail_h = (self._scroll.viewport().height()
                   or self._grid_host.height()
                   or self.height() or 200)
        rows, cols = self._compute_grid_dims(len(self._row_order), avail_w, avail_h)

        for col in range(cols):
            self._grid.setColumnStretch(col, 1)

        for idx, item_id in enumerate(self._row_order):
            r, c = divmod(idx, cols)
            self._grid.addWidget(self._rows[item_id], r, c)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Debounce re-layout while the splitter/window is actively resizing.
        self._relayout_timer.start(60)


# Backward-compatible alias — earlier builds referenced ``ChecklistBar``.
ChecklistBar = ChecklistGridPanel
