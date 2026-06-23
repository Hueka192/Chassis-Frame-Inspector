"""
Vehicle history log table — one row per finalised VC.
"""
from __future__ import annotations
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QColor, QFont


class HistoryPanel(QWidget):
    MAX_ROWS = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QLabel("  VEHICLE INSPECTION LOG")
        hdr.setFixedHeight(26)
        hdr.setStyleSheet(
            "background:#141828; color:#667799; font-size:9px;"
            "font-weight:bold; letter-spacing:1px;"
            "border-bottom:1px solid #2a2d3a; padding-left:4px;"
        )
        root.addWidget(hdr)

        cols = ["VC Number", "Model", "Scan Time", "Verdict",
                "OK Items", "NG / Pending", "Duration"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget{background:#12141e; color:#ccd0e0;"
            "border:none; font-size:9px;}"
            "QTableWidget::item{padding:3px 6px;}"
            "QTableWidget::item:alternate{background:#141828;}"
            "QTableWidget::item:selected{background:#1c2050;}"
            "QHeaderView::section{background:#141828; color:#667799;"
            "font-size:9px; font-weight:bold; border:none; padding:4px;"
            "border-bottom:1px solid #2a2d3a;}"
            "QScrollBar:vertical{width:6px; background:#0d0f14;}"
            "QScrollBar::handle:vertical{background:#2a2d3a; border-radius:3px;}"
        )
        root.addWidget(self._table)

    def add_vehicle(self, vc: str, model_name: str, scan_time: str,
                    verdict: str, ok: int, ng: int, duration: float):
        if self._table.rowCount() >= self.MAX_ROWS:
            self._table.removeRow(self._table.rowCount() - 1)
        self._table.insertRow(0)

        vals = [
            vc, model_name, scan_time[-8:],
            verdict, str(ok), str(ng),
            f"{duration:.0f}s"
        ]
        for col, val in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            if col == 3:
                if val == "OK":
                    item.setForeground(QColor("#00e676"))
                    item.setFont(QFont("Consolas", 9, QFont.Bold))
                elif val == "NG":
                    item.setForeground(QColor("#ff5252"))
                    item.setFont(QFont("Consolas", 9, QFont.Bold))
            self._table.setItem(0, col, item)
