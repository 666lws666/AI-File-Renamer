"""Application configuration persistence.

Stores settings as JSON in the project directory to keep everything on D: drive.
"""

import json
import os
from pathlib import Path
from loguru import logger
from .models.app_config import AppConfig


# Config lives in the project directory on D: drive, not in %APPDATA%
CONFIG_DIR = Path("D:/文件AI-AGENT/config")
CONFIG_FILE = CONFIG_DIR / "settings.json"
TEMPLATES_DIR = CONFIG_DIR / "templates"


def _ensure_dirs() -> None:
    """Create config directories if they don't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    """Load application configuration from disk.

    Returns default config on first run.
    """
    _ensure_dirs()
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = AppConfig(**data)
            logger.info(f"配置已加载: {CONFIG_FILE}")
            return config
    except Exception as e:
        logger.warning(f"配置加载失败，使用默认配置: {e}")

    return AppConfig()


def save_config(config: AppConfig) -> None:
    """Persist application configuration to disk."""
    _ensure_dirs()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        logger.info("配置已保存")
    except Exception as e:
        logger.error(f"配置保存失败: {e}")
        raise


def get_templates_dir() -> Path:
    """Get the directory where user templates are stored."""
    _ensure_dirs()
    return TEMPLATES_DIR
