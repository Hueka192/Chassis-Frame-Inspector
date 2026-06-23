"""
Database layer — SQLite
========================
Tables:
  vehicles     — one row per scanned VC number
  checklist    — one row per checklist item result per vehicle
  sessions     — shift/session metadata

All DB access is synchronous (called from main thread after detection).
Thread-safe via a single connection with WAL mode.
"""

from __future__ import annotations
import sqlite3
import os
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from src.logger import get_logger

logger = get_logger("database")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "logs", "inspector.db"
)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


class Database:
    _instance: Optional["Database"] = None

    def __init__(self):
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info(f"Database ready: {DB_PATH}")

    @classmethod
    def instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Schema ────────────────────────────────────────────────────────────

    def _create_tables(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time  TEXT NOT NULL,
            end_time    TEXT,
            line_id     TEXT,
            station_id  TEXT,
            operator    TEXT DEFAULT 'OPERATOR'
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER REFERENCES sessions(id),
            vc_number       TEXT NOT NULL,
            vin_number      TEXT DEFAULT '',
            model_code      TEXT NOT NULL,
            model_name      TEXT NOT NULL,
            scan_time       TEXT NOT NULL,
            finalise_time   TEXT,
            verdict         TEXT DEFAULT 'IN_PROGRESS',
            ok_count        INTEGER DEFAULT 0,
            ng_count        INTEGER DEFAULT 0,
            total_items     INTEGER DEFAULT 0,
            operator_notes  TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS checklist_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
            item_id     TEXT NOT NULL,
            item_name   TEXT NOT NULL,
            status      TEXT DEFAULT 'PENDING',
            checked_at  TEXT,
            auto_detect INTEGER DEFAULT 0,
            notes       TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_vehicles_vc  ON vehicles(vc_number);
        CREATE INDEX IF NOT EXISTS idx_vehicles_ses ON vehicles(session_id);
        CREATE INDEX IF NOT EXISTS idx_cl_vehicle   ON checklist_results(vehicle_id);
        """)
        self._conn.commit()

        # Migration: add vin_number column if missing (older DBs)
        try:
            self._conn.execute("ALTER TABLE vehicles ADD COLUMN vin_number TEXT DEFAULT ''")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    # ── Sessions ──────────────────────────────────────────────────────────

    def start_session(self, line_id: str, station_id: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions(start_time, line_id, station_id) VALUES(?,?,?)",
            (datetime.now().isoformat(), line_id, station_id)
        )
        self._conn.commit()
        sid = cur.lastrowid
        logger.info(f"Session {sid} started")
        return sid

    def end_session(self, session_id: int):
        self._conn.execute(
            "UPDATE sessions SET end_time=? WHERE id=?",
            (datetime.now().isoformat(), session_id)
        )
        self._conn.commit()

    # ── Vehicles ──────────────────────────────────────────────────────────

    def create_vehicle(self, session_id: int, vc_number: str,
                       vin_number: str, model_code: str, model_name: str,
                       total_items: int) -> int:
        cur = self._conn.execute(
            """INSERT INTO vehicles
               (session_id, vc_number, vin_number, model_code, model_name,
                scan_time, total_items)
               VALUES(?,?,?,?,?,?,?)""",
            (session_id, vc_number.upper(), vin_number.upper(), model_code, model_name,
             datetime.now().isoformat(), total_items)
        )
        self._conn.commit()
        vid = cur.lastrowid
        logger.info(f"Vehicle {vc_number} → DB id={vid}")
        return vid

    def save_checklist_item(self, vehicle_id: int, item_id: str,
                            item_name: str, status: str,
                            auto_detect: bool = False):
        # Upsert
        existing = self._conn.execute(
            "SELECT id FROM checklist_results WHERE vehicle_id=? AND item_id=?",
            (vehicle_id, item_id)
        ).fetchone()
        ts = datetime.now().isoformat() if status != "PENDING" else None
        if existing:
            self._conn.execute(
                """UPDATE checklist_results
                   SET status=?, checked_at=?, auto_detect=?
                   WHERE vehicle_id=? AND item_id=?""",
                (status, ts, int(auto_detect), vehicle_id, item_id)
            )
        else:
            self._conn.execute(
                """INSERT INTO checklist_results
                   (vehicle_id, item_id, item_name, status, checked_at, auto_detect)
                   VALUES(?,?,?,?,?,?)""",
                (vehicle_id, item_id, item_name, status, ts, int(auto_detect))
            )
        self._conn.commit()

    def finalise_vehicle(self, vehicle_id: int, verdict: str,
                         ok_count: int, ng_count: int, na_count: int = 0):
        self._conn.execute(
            """UPDATE vehicles
               SET verdict=?, finalise_time=?, ok_count=?, ng_count=?
               WHERE id=?""",
            (verdict, datetime.now().isoformat(), ok_count, ng_count, vehicle_id)
        )
        self._conn.commit()
        logger.info(f"Vehicle id={vehicle_id} finalised → {verdict}")

    # ── Queries ───────────────────────────────────────────────────────────

    def get_session_stats(self, session_id: int) -> Dict:
        row = self._conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict='OK' THEN 1 ELSE 0 END) as ok,
                SUM(CASE WHEN verdict='NG' THEN 1 ELSE 0 END) as ng,
                SUM(CASE WHEN verdict='NA' THEN 1 ELSE 0 END) as na,
                SUM(CASE WHEN verdict='IN_PROGRESS' THEN 1 ELSE 0 END) as inprog
               FROM vehicles WHERE session_id=?""",
            (session_id,)
        ).fetchone()
        total = row["total"] or 0
        ok    = row["ok"]    or 0
        ng    = row["ng"]    or 0
        na    = row["na"]    or 0
        return {
            "total": total,
            "ok":    ok,
            "ng":    ng,
            "na":    na,
            "yield": (ok / total * 100) if total else 0.0,
        }

    def get_recent_vehicles(self, session_id: int, limit: int = 100) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT v.*, GROUP_CONCAT(cr.item_id||':'||cr.status) as items
               FROM vehicles v
               LEFT JOIN checklist_results cr ON cr.vehicle_id=v.id
               WHERE v.session_id=?
               GROUP BY v.id
               ORDER BY v.id DESC LIMIT ?""",
            (session_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_vehicle_checklist(self, vehicle_id: int) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM checklist_results WHERE vehicle_id=? ORDER BY item_id",
            (vehicle_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_stats(self) -> Dict:
        """Overall totals across all sessions."""
        row = self._conn.execute(
            """SELECT COUNT(*) as total,
                SUM(CASE WHEN verdict='OK' THEN 1 ELSE 0 END) as ok,
                SUM(CASE WHEN verdict='NG' THEN 1 ELSE 0 END) as ng,
                SUM(CASE WHEN verdict='NA' THEN 1 ELSE 0 END) as na
               FROM vehicles"""
        ).fetchone()
        total = row["total"] or 0
        ok    = row["ok"]    or 0
        ng    = row["ng"]    or 0
        na    = row["na"]    or 0
        return {
            "total": total, "ok": ok, "ng": ng, "na": na,
            "yield": (ok / total * 100) if total else 0.0,
        }

    def close(self):
        self._conn.close()
