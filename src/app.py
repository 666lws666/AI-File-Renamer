"""Application singleton and lifecycle management."""

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from loguru import logger

from .config import load_config, save_config
from .models.app_config import AppConfig
from .utils.logger import setup_logging


class RenamerApp(QApplication):
    """Main application class — holds global singletons."""

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self.setApplicationName("AI File Renamer")
        self.setApplicationVersion("0.1.0")
        self.setOrganizationName("AIRenamer")

        # Setup logging
        setup_logging()

        # Load config
        self.app_config: AppConfig = load_config()
        logger.info(f"AI File Renamer v{self.applicationVersion()} 启动")

    def save_config(self) -> None:
        """Persist current configuration."""
        save_config(self.app_config)
