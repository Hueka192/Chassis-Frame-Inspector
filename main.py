#!/usr/bin/env python3
"""
Smart Quality Gate Inspection v6.1
Real-time quality inspection — multi-camera RTSP + computer-vision Poka-Yoke.
"""

import os
import signal
import sys
import traceback

# ── Fix OpenCV/PyQt5 Qt platform plugin issues (Linux only) ────────────────
# On Linux, OpenCV's wheel ships its own (often incompatible) Qt plugins and
# can overwrite QT_QPA_PLATFORM_PLUGIN_PATH when imported. We import our
# modules first (triggering `import cv2`), then sanitise the environment
# before QApplication is created. This step is a no-op on Windows/macOS,
# where the system Qt platform plugin (windows/cocoa) is used as-is —
# forcing "xcb" there would prevent the app from starting at all.

# Ensure root package is importable regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Step 1: import our modules (this triggers `import cv2`, which on Linux may
# clobber the Qt plugin search path).
from src.main_window import MainWindow
from src.logger import get_logger

logger = get_logger("main")

# Step 2: fix env on Linux only.
if sys.platform.startswith("linux"):
    for k in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH"):
        os.environ.pop(k, None)
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    _sys_qt5_plugins = "/usr/lib/x86_64-linux-gnu/qt5/plugins"
    if os.path.isdir(_sys_qt5_plugins):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _sys_qt5_plugins

# Step 3: now safe to import Qt and create QApplication.
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

APP_VERSION = "6.1.0"


def _install_crash_handler(app: QApplication) -> None:
    """
    Catch any otherwise-uncaught exception, log it with a full traceback,
    and show a operator-friendly error dialog instead of letting the
    process die silently (critical on an unattended production line PC
    where nobody is watching a console window).
    """
    def _handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical(f"UNHANDLED EXCEPTION:\n{tb_text}")
        try:
            QMessageBox.critical(
                None,
                "Smart Quality Gate Inspection — Unexpected Error",
                "An unexpected error occurred and has been logged.\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                "The application will keep running where possible. "
                "If the problem persists, restart the application and "
                "check the logs/ folder for details.",
            )
        except Exception:
            # If even the dialog fails (e.g. during shutdown), don't recurse.
            pass

    sys.excepthook = _handle


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Smart Quality Gate Inspection")
    app.setApplicationVersion(APP_VERSION)

    _install_crash_handler(app)

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    if "QT_QPA_PLATFORM_PLUGIN_PATH" in os.environ:
        logger.info(f"QT_QPA_PLATFORM_PLUGIN_PATH={os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']}")

    from src.config_manager import ConfigManager
    theme = getattr(ConfigManager.instance().cfg, "theme", "dark")
    qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", f"style_{theme}.qss")
    if not os.path.exists(qss_path):
        qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "assets", "style.qss")
    try:
        if os.path.exists(qss_path):
            with open(qss_path, encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        else:
            logger.warning(f"Stylesheet not found at {qss_path} — using default Qt theme")
    except Exception as e:
        logger.warning(f"Failed to load stylesheet ({qss_path}): {e}")

    try:
        window = MainWindow()
    except Exception:
        logger.critical("Fatal error during startup:\n" + traceback.format_exc())
        QMessageBox.critical(
            None, "Startup Failed",
            "The application failed to start. Please check logs/ for details, "
            "verify config/settings.yaml, and confirm the database is reachable.",
        )
        sys.exit(1)

    window.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    logger.info(f"Application started — v{APP_VERSION}")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

