"""Logging configuration using loguru."""

import sys
from pathlib import Path
from loguru import logger


def setup_logging(log_dir: str | Path = None, level: str = "INFO") -> None:
    """Configure loguru with console and file sinks.

    Args:
        log_dir: Directory for log files. Defaults to D:\\文件AI-AGENT\\logs\\
        level: Minimum log level for console output.
    """
    logger.remove()

    # Console sink — skip if stderr is None (pythonw.exe with no console)
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level=level,
            colorize=True,
        )

    # File sink
    if log_dir is None:
        log_dir = Path("D:/文件AI-AGENT/logs")
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path / "renamer_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
    )

    logger.info("日志系统初始化完成")
