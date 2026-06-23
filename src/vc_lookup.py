from __future__ import annotations
from typing import Optional
from PyQt5.QtCore import QThread, pyqtSignal
from src.config_manager import ConfigManager
from src.logger import get_logger

logger = get_logger("vc_lookup")


class VCLookupWorker(QThread):
    result_ready = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, vin: str, parent=None):
        super().__init__(parent)
        self._vin = vin

    def run(self):
        try:
            vc = self._lookup_vc(self._vin)
            if vc:
                logger.info(f"VC lookup success: VIN={self._vin} -> VC={vc}")
                self.result_ready.emit(self._vin, vc)
            else:
                msg = f"No VC found for VIN: {self._vin}"
                logger.warning(msg)
                self.error.emit(msg)
        except Exception as e:
            msg = f"VC lookup error: {e}"
            logger.error(msg)
            self.error.emit(msg)

    def _lookup_vc(self, vin: str) -> Optional[str]:
        import psycopg2
        cfg = ConfigManager.instance().cfg.database
        conn = psycopg2.connect(
            host=cfg.host,
            port=cfg.port,
            dbname=cfg.database,
            user=cfg.user,
            password=cfg.password,
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                sql = f'SELECT "{cfg.vc_column}" FROM "{cfg.table}" WHERE "{cfg.vin_column}" = %s LIMIT 1'
                cur.execute(sql, (vin,))
                row = cur.fetchone()
                if row:
                    return str(row[0]).strip()
                return None
        finally:
            conn.close()
