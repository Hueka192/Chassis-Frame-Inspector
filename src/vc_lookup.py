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
        from psycopg2 import sql as pysql
        cfg = ConfigManager.instance().cfg.database
        conn = None
        try:
            conn = psycopg2.connect(
                host=cfg.host,
                port=cfg.port,
                dbname=cfg.database,
                user=cfg.user,
                password=cfg.password,
                connect_timeout=5,
            )
            with conn.cursor() as cur:
                query = pysql.SQL(
                    'SELECT {vc_col} FROM {table} WHERE {vin_col} = %s LIMIT 1'
                ).format(
                    vc_col=pysql.Identifier(cfg.vc_column),
                    table=pysql.Identifier(cfg.table),
                    vin_col=pysql.Identifier(cfg.vin_column),
                )
                cur.execute(query, (vin,))
                row = cur.fetchone()
                if row:
                    return str(row[0]).strip()
                return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
