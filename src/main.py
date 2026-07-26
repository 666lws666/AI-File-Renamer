"""Application entry point."""

import sys
import os
import traceback
from pathlib import Path
from datetime import datetime

# ── EARLY CRASH CAPTURE ────────────────────────────────────────────────────
# When launched via pythonw.exe, there's no console. Log startup errors to file.
_CRASH_LOG = Path(r"D:\文件AI-AGENT\logs\_startup.log")

def _startup_log(msg: str) -> None:
    """Write startup message to log file immediately."""
    try:
        _CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def main() -> int:
    """Launch the AI File Renamer application."""
    try:
        _startup_log(f"STARTUP python={sys.executable} cwd={os.getcwd()}")

        from .app import RenamerApp
        from .ui.main_window import MainWindow

        app = RenamerApp(sys.argv)
        window = MainWindow(app)
        window.show()

        exit_code = app.exec()
        app.save_config()

        return exit_code

    except Exception:
        _startup_log(f"CRASH:\n{traceback.format_exc()}")
        raise  # Re-raise so pythonw at least shows something


if __name__ == "__main__":
    sys.exit(main())
