from __future__ import annotations
import re
from PyQt5.QtCore import QThread, pyqtSignal
from src.config_manager import ConfigManager
from src.logger import get_logger

logger = get_logger("serial_reader")

VIN_RE = re.compile(rb"[A-HJ-NPR-Z0-9]{17}")


class SerialReader(QThread):
    vin_detected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False
        self._serial = None

    def stop(self):
        self._stop = True
        self.wait(3000)

    def run(self):
        cfg = ConfigManager.instance().cfg.serial
        if not cfg.enabled:
            logger.info("Serial reader disabled")
            return

        import serial
        import serial.tools.list_ports

        port = self._resolve_port(cfg.port)
        logger.info(f"Serial reader starting on {port} ({cfg.baudrate} baud)")

        while not self._stop:
            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=cfg.baudrate,
                    bytesize=cfg.bytesize,
                    parity=cfg.parity,
                    stopbits=cfg.stopbits,
                    timeout=0.5,
                )
                logger.info(f"Serial connected on {port}")
                self._read_loop()
            except serial.SerialException as e:
                logger.warning(f"Serial error: {e} — retrying in 3s")
                self.msleep(3000)
            except Exception as e:
                logger.error(f"Serial unexpected error: {e}")
                self.msleep(3000)
            finally:
                if self._serial and self._serial.is_open:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                self._serial = None

    def _read_loop(self):
        buf = b""
        while not self._stop and self._serial and self._serial.is_open:
            try:
                data = self._serial.read(64)
                if not data:
                    self.msleep(50)
                    continue
                buf += data
                buf = self._scan_buffer(buf)
            except serial.SerialException as e:
                logger.warning(f"Serial read error: {e}")
                break
            except Exception as e:
                logger.error(f"Serial read unexpected: {e}")
                break

    def _scan_buffer(self, buf: bytes) -> bytes:
        while len(buf) >= 17:
            match = VIN_RE.search(buf)
            if not match:
                buf = buf[-16:] if len(buf) > 16 else b""
                continue
            raw = match.group().decode("ascii", errors="replace")
            if raw.startswith("MAT"):
                logger.info(f"VIN detected from serial: {raw}")
                self.vin_detected.emit(raw)
            buf = buf[match.end():]
        return buf

    @staticmethod
    def _resolve_port(port: str) -> str:
        import sys
        if sys.platform.startswith("win"):
            return port
        port = port.upper()
        if port.startswith("COM"):
            num = port[3:]
            return f"/dev/ttyS{num}"
        return port
