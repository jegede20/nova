#!/usr/bin/env python3
"""Nova launcher.

    python run_nova.py           start with the window open
    python run_nova.py --tray    start hidden in the system tray (used at Windows login)
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from nova.core.logging_setup import get_logger
    from nova.core.nova_core import NovaCore
    from nova.ui import theme
    from nova.ui.main_window import MainWindow

    log = get_logger("main")

    app = QApplication(sys.argv)
    app.setApplicationName("Nova")
    app.setOrganizationName("Nova")
    app.setQuitOnLastWindowClosed(False)   # keep running in the tray
    app.setStyleSheet(theme.STYLESHEET)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("No system tray is available; Nova will run as a normal window.")

    try:
        core = NovaCore()
    except Exception as e:
        log.exception("Nova failed to start")
        QMessageBox.critical(None, "Nova could not start", f"{type(e).__name__}: {e}")
        return 1

    start_hidden = "--tray" in sys.argv
    window = MainWindow(core, start_hidden=start_hidden)

    try:
        core.start()
    except Exception:
        log.exception("Some subsystems failed to start")
        window.dashboard.add_activity("Some subsystems failed to start. See the log.", "failed")

    if core.settings.get("voice_activation", True) and not core.listening:
        window.dashboard.add_activity(
            "Voice activation is off: install faster-whisper and sounddevice to enable it.", "denied")

    if start_hidden:
        window.tray.notify("Nova is running", "Say “Hey Nova” or open Nova from the tray.")

    log.info("Nova ready")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
