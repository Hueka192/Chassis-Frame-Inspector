"""
Configuration manager — reads/writes config/settings.yaml
Falls back to sensible defaults if the file is missing.
"""

import os
import yaml
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, List
from src.logger import get_logger

logger = get_logger("config")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")


@dataclass
class CameraConfig:
    enabled: bool = False
    rtsp_url: str = ""
    label: str = ""
    width: int = 3072    # 6MP @ 3072×2048
    height: int = 2048
    fps: int = 15
    reconnect_delay: int = 3
    digital_zoom: float = 1.0
    buffer_size: int = 1


@dataclass
class DetectionConfig:
    confidence_threshold: float = 0.45
    nms_threshold: float = 0.4
    frame_skip: int = 3          # process every Nth frame
    roi_top_pct: float = 0.0     # crop ROI (fraction of height)
    roi_bottom_pct: float = 1.0
    roi_left_pct: float = 0.0
    roi_right_pct: float = 1.0
    use_gpu: bool = False
    model_path: str = ""         # empty = use rule-based detector


@dataclass
class AlertConfig:
    missing_part_sound: bool = True
    log_missing_frames: bool = True
    auto_save_ng_frames: bool = True
    ng_save_dir: str = "logs/ng_frames"


@dataclass
class SerialConfig:
    enabled: bool = True
    port: str = "COM4"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    flow_control: str = "none"


@dataclass
class DatabaseConfig:
    host: str = "192.168.11.199"
    port: int = 5432
    database: str = "kitting_zone_4"
    user: str = "postgres"
    password: str = "postgres"
    table: str = "kitting_zone_4"
    vin_column: str = "VIN_no"
    vc_column: str = "VC_no"


_DEFAULT_CHECKPOINTS: Dict[str, dict] = {
    "CL-01": {"name": "Trunnion Bracket – Long Member",          "x": 0.30, "y": 0.55, "w": 0.10, "h": 0.16},
    "CL-02": {"name": "V-Rod Corner Bracket – Frame",            "x": 0.72, "y": 0.42, "w": 0.09, "h": 0.10},
    "CL-03": {"name": "Articulation Stopper – Frame",            "x": 0.78, "y": 0.58, "w": 0.07, "h": 0.09},
    "CL-04": {"name": "Trunnion Bracket – Cross Member",         "x": 0.38, "y": 0.50, "w": 0.09, "h": 0.12},
    "CL-05": {"name": "Anti-Roll Bar Sub-Assembly",              "x": 0.62, "y": 0.62, "w": 0.14, "h": 0.10},
    "CL-06": {"name": "V-Rod Mounting – Corner Bracket",         "x": 0.72, "y": 0.50, "w": 0.08, "h": 0.09},
    "CL-07": {"name": "Parking Relay Valve – Fitment",           "x": 0.50, "y": 0.58, "w": 0.07, "h": 0.08},
    "CL-08": {"name": "Parking Relay Valve – Pipe Connection",   "x": 0.50, "y": 0.62, "w": 0.06, "h": 0.07},
    "CL-09": {"name": "PTC Connector – Rear Brake Pipe",         "x": 0.85, "y": 0.38, "w": 0.06, "h": 0.07},
    "CL-10": {"name": "Resilience Brackets – Frame (×5)",        "x": 0.25, "y": 0.45, "w": 0.18, "h": 0.08},
    "CL-11": {"name": "Front Shock Absorber Brackets (×4)",      "x": 0.12, "y": 0.52, "w": 0.16, "h": 0.08},
}


@dataclass
class AppConfig:
    camera1: CameraConfig = field(default_factory=lambda: CameraConfig(
        enabled=True,
        label="Left View",
        rtsp_url="rtsp://admin:admin123@192.168.1.64/Streaming/Channels/101"
    ))
    camera2: CameraConfig = field(default_factory=lambda: CameraConfig(
        enabled=True,
        label="Right View",
        rtsp_url="rtsp://admin:admin123@192.168.1.65/Streaming/Channels/101"
    ))
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    theme: str = "dark"
    conveyor_direction: str = "left_to_right"
    line_id: str = "LINE-03"
    station_id: str = "01_VIN_Scan"
    reference_image: str = "slide_10.png"
    checkpoints: Dict[str, dict] = field(default_factory=lambda: dict(_DEFAULT_CHECKPOINTS))


class ConfigManager:
    _instance: Optional["ConfigManager"] = None

    def __init__(self):
        self._cfg = AppConfig()
        self.load()

    @classmethod
    def instance(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def cfg(self) -> AppConfig:
        return self._cfg

    def load(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    data = yaml.safe_load(f) or {}
                self._apply_dict(data)
                logger.info(f"Config loaded from {CONFIG_PATH}")
            except Exception as e:
                logger.warning(f"Config load error: {e} — using defaults")
        else:
            self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                yaml.dump(self._to_dict(), f, default_flow_style=False, allow_unicode=True)
            logger.info("Config saved")
        except Exception as e:
            logger.error(f"Config save error: {e}")

    def _to_dict(self) -> dict:
        return {
            "camera1": asdict(self._cfg.camera1),
            "camera2": asdict(self._cfg.camera2),
            "detection": asdict(self._cfg.detection),
            "alert": asdict(self._cfg.alert),
            "serial": asdict(self._cfg.serial),
            "database": asdict(self._cfg.database),
            "theme": self._cfg.theme,
            "conveyor_direction": self._cfg.conveyor_direction,
            "line_id": self._cfg.line_id,
            "station_id": self._cfg.station_id,
            "reference_image": self._cfg.reference_image,
            "checkpoints": self._cfg.checkpoints,
        }

    def _apply_dict(self, data: dict):
        def _update(obj, d):
            for k, v in d.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

        if "camera1" in data:
            _update(self._cfg.camera1, data["camera1"])
        if "camera2" in data:
            _update(self._cfg.camera2, data["camera2"])
        if "detection" in data:
            _update(self._cfg.detection, data["detection"])
        if "alert" in data:
            _update(self._cfg.alert, data["alert"])
        if "serial" in data:
            _update(self._cfg.serial, data["serial"])
        if "database" in data:
            _update(self._cfg.database, data["database"])
        for k in ("theme", "conveyor_direction", "line_id", "station_id",
                  "reference_image", "checkpoints"):
            if k in data:
                setattr(self._cfg, k, data[k])
