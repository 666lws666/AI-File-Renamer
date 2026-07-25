"""Application entry point."""

import sys
import os
import traceback
from pathlib import Path
from datetime import datetime

# ── EARLY CRASH CAPTURE ────────────────────────────────────────────────────
# pythonw has no console, so we MUST log all errors to a file.
_CRASH_LOG = Path(r"D:\文件AI-AGENT\logs\_crash.log")

def _crash_log(msg: str) -> None:
    """Write to crash log immediately."""
    try:
        _CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

# Log early startup info
_crash_log(f"=== STARTUP === python={sys.executable} cwd={os.getcwd()} argv={sys.argv}")

try:
    from .app import RenamerApp
    from .ui.main_window import MainWindow
    _crash_log("imports OK")
except Exception:
    _crash_log(f"IMPORT FAILED:\n{traceback.format_exc()}")
    raise


def main() -> int:
    """Launch the AI File Renamer application."""
    try:
        _crash_log("main() entered")
        app = RenamerApp(sys.argv)
        _crash_log("RenamerApp created")

        window = MainWindow(app)
        _crash_log("MainWindow created")
        window.show()
        _crash_log("window.show() done")

        exit_code = app.exec()
        _crash_log(f"event loop exited: {exit_code}")

        app.save_config()
        _crash_log("config saved")

        return exit_code

    except Exception:
        _crash_log(f"CRASH in main():\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
