"""
VC Scan Widget
==============
Shown when no vehicle is loaded. Operator either:
  a) Scans a barcode (auto-fills the field)
  b) Types the VC number manually and presses Enter / Submit

On submit:
  • Resolves model from VC prefix
  • Emits  vc_accepted(vc_number, VehicleModel)
"""

from __future__ import annotations
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QKeySequence

from src.models import resolve_model, VehicleModel, VEHICLE_MODELS
from src.logger import get_logger

logger = get_logger("vc_scan")


class VCScanWidget(QWidget):
    """
    Full-screen overlay widget — prompts for VC / barcode.
    Disappears once a valid VC is accepted.
    """
    vc_accepted = pyqtSignal(str, str, object)  # (vin, vc_number, VehicleModel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#080b14;")
        self._build()
        # Auto-focus input so barcode scanner fires straight in
        QTimer.singleShot(100, self._input.setFocus)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setMaximumWidth(600)
        card.setMinimumWidth(300)
        card.setStyleSheet(
            "QFrame{"
            "  background:#0f1220;"
            "  border:1px solid #2a2d4a;"
            "  border-radius:16px;"
            "}"
        )
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 188, 212, 80))
        shadow.setOffset(0, 0)
        card.setGraphicsEffect(shadow)

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(40, 36, 40, 36)
        card_lay.setSpacing(12)

        # Icon + Title
        ico = QLabel("◈")
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet("color:#00bcd4; font-size:32px;")
        card_lay.addWidget(ico)

        ttl = QLabel("SMART QUALITY GATE INSPECTION")
        ttl.setAlignment(Qt.AlignCenter)
        ttl.setStyleSheet(
            "color:#dde2f0; font-size:16px; font-weight:bold; letter-spacing:2px;"
        )
        card_lay.addWidget(ttl)

        sub = QLabel("Scan VIN & VC number or enter manually to begin inspection")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#667799; font-size:10px;")
        card_lay.addWidget(sub)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background:#2a2d3a; max-height:1px;")
        card_lay.addWidget(div)

        # VIN scan input
        vin_lbl = QLabel("🔍  VIN / BARCODE SCAN")
        vin_lbl.setAlignment(Qt.AlignCenter)
        vin_lbl.setStyleSheet(
            "color:#ffd740; font-size:10px; font-weight:bold; letter-spacing:1px;"
        )
        card_lay.addWidget(vin_lbl)

        self._vin_input = QLineEdit()
        self._vin_input.setPlaceholderText("Scan or type VIN / Barcode")
        self._vin_input.setFixedHeight(40)
        self._vin_input.setAlignment(Qt.AlignCenter)
        self._vin_input.setStyleSheet(
            "QLineEdit{"
            "  background:#141828;"
            "  color:#ffffff;"
            "  border:2px solid #00bcd4;"
            "  border-radius:8px;"
            "  font-size:14px;"
            "  font-family:Consolas;"
            "  padding:0 12px;"
            "  letter-spacing:2px;"
            "}"
            "QLineEdit:focus{"
            "  border:2px solid #ffd740;"
            "  background:#1a1d28;"
            "}"
        )
        self._vin_input.returnPressed.connect(self._submit)
        card_lay.addWidget(self._vin_input)

        # Divider
        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setStyleSheet("background:#2a2d3a; max-height:1px;")
        card_lay.addWidget(div2)

        # VC number input
        vc_lbl = QLabel("VC / CHASSIS NUMBER")
        vc_lbl.setAlignment(Qt.AlignCenter)
        vc_lbl.setStyleSheet(
            "color:#00bcd4; font-size:10px; font-weight:bold; letter-spacing:1px;"
        )
        card_lay.addWidget(vc_lbl)

        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g.  4832TK0012345")
        self._input.setFixedHeight(40)
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setStyleSheet(
            "QLineEdit{"
            "  background:#141828;"
            "  color:#ffffff;"
            "  border:2px solid #aa88ff;"
            "  border-radius:8px;"
            "  font-size:14px;"
            "  font-family:Consolas;"
            "  padding:0 12px;"
            "  letter-spacing:2px;"
            "}"
            "QLineEdit:focus{"
            "  border:2px solid #ffd740;"
            "  background:#1a1d28;"
            "}"
        )
        self._input.returnPressed.connect(self._submit)
        card_lay.addWidget(self._input)

        # Submit button
        self._submit_btn = QPushButton("▶  START INSPECTION")
        self._submit_btn.setFixedHeight(40)
        self._submit_btn.setStyleSheet(
            "QPushButton{"
            "  background:#00bcd422;"
            "  color:#00bcd4;"
            "  border:1px solid #00bcd455;"
            "  border-radius:8px;"
            "  font-size:11px;"
            "  font-weight:bold;"
            "  letter-spacing:1px;"
            "}"
            "QPushButton:hover{background:#00bcd444;}"
            "QPushButton:pressed{background:#00bcd466;}"
        )
        self._submit_btn.clicked.connect(self._submit)
        card_lay.addWidget(self._submit_btn)

        # Error label
        self._err = QLabel("")
        self._err.setAlignment(Qt.AlignCenter)
        self._err.setStyleSheet("color:#ff5252; font-size:10px;")
        card_lay.addWidget(self._err)

        # Model hint
        hint_lbl = QLabel("Recognised model prefixes:")
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setStyleSheet("color:#445566; font-size:9px;")
        card_lay.addWidget(hint_lbl)

        prefixes = "  |  ".join(
            f"{k}: {v.name}"
            for k, v in VEHICLE_MODELS.items()
            if k != "DEFAULT"
        )
        pfx_lbl = QLabel(prefixes)
        pfx_lbl.setAlignment(Qt.AlignCenter)
        pfx_lbl.setWordWrap(True)
        pfx_lbl.setStyleSheet("color:#334455; font-size:8px; font-family:Consolas;")
        card_lay.addWidget(pfx_lbl)

        root.addWidget(card)

    def _submit(self):
        vin = self._vin_input.text().strip().upper()
        vc  = self._input.text().strip().upper()
        if len(vc) < 4:
            self._err.setText("⚠  Please enter a valid VC number (min 4 characters)")
            self._input.setFocus()
            return
        if len(vin) < 4:
            self._err.setText("⚠  Please enter a valid VIN number (min 4 characters)")
            self._vin_input.setFocus()
            return
        model = resolve_model(vc)
        logger.info(f"VIN={vin}, VC={vc} → model {model.code}")
        self._err.setText("")
        self.vc_accepted.emit(vin, vc, model)

    def clear_and_refocus(self):
        if hasattr(self, '_vin_input'):
            self._vin_input.clear()
        self._input.clear()
        self._err.setText("")
        QTimer.singleShot(100, self._input.setFocus)
