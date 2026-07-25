"""Folder watcher — monitors directories for new files using watchdog."""

import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from loguru import logger

from ..models.watch_config import WatchConfig, WatchMode
from ..models.file_item import FileItem, FileStatus
from ..core.file_scanner import FileScanner


try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


class FolderWatcher(QObject):
    """Monitors directories and emits signals when new files appear.

    Uses watchdog for efficient filesystem monitoring.
    """

    new_file_detected = Signal(str)     # file path
    file_ready = Signal(FileItem)        # FileItem after debounce
    error_occurred = Signal(str)         # error message

    def __init__(self, max_file_size_mb: int = 50):
        super().__init__()
        self._configs: dict[str, WatchConfig] = {}
        self._observer = None
        self._handlers: dict[str, "WatchHandler"] = {}
        self._scanner = FileScanner(max_file_size_mb=max_file_size_mb)
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def add_watch(self, config: WatchConfig) -> None:
        """Add a folder to monitor.

        Args:
            config: WatchConfig with source_dir, mode, etc.
        """
        if config.id in self._configs:
            logger.warning(f"已存在监控: {config.source_dir}")
            return

        self._configs[config.id] = config

        if self._running:
            self._start_watch(config)

        logger.info(f"添加监控: {config.source_dir} (模式: {config.mode.value})")

    def remove_watch(self, config_id: str) -> None:
        """Stop monitoring a folder."""
        if config_id not in self._configs:
            return

        config = self._configs.pop(config_id)

        if config_id in self._handlers:
            self._observer.unschedule(self._handlers[config_id])
            del self._handlers[config_id]

        logger.info(f"移除监控: {config.source_dir}")

    def start(self) -> None:
        """Start all folder watches."""
        if not HAS_WATCHDOG:
            raise RuntimeError("watchdog 库未安装")

        if self._running:
            return

        self._observer = Observer()

        for config in self._configs.values():
            if config.active:
                self._start_watch(config)

        self._observer.start()
        self._running = True
        logger.info(f"文件夹监控已启动: {len(self._configs)} 个监控")

    def stop(self) -> None:
        """Stop all folder watches."""
        if not self._running:
            return

        self._observer.stop()
        self._observer.join(timeout=5)
        self._handlers.clear()
        self._running = False
        logger.info("文件夹监控已停止")

    def get_watched_folders(self) -> list[WatchConfig]:
        """Get all monitored folder configs."""
        return list(self._configs.values())

    def _start_watch(self, config: WatchConfig):
        """Start watching a single directory."""
        if not Path(config.source_dir).exists():
            logger.warning(f"监控目录不存在: {config.source_dir}")
            return

        handler = WatchHandler(config, self)
        self._handlers[config.id] = handler
        self._observer.schedule(
            handler,
            config.source_dir,
            recursive=config.recursive,
        )


class WatchHandler(FileSystemEventHandler):
    """watchdog event handler with debounce for file completion."""

    DEBOUNCE_SECONDS = 2.0

    def __init__(self, config: WatchConfig, watcher: FolderWatcher):
        super().__init__()
        self.config = config
        self.watcher = watcher
        self._pending: dict[str, float] = {}  # path → first seen time

    def on_created(self, event):
        if event.is_directory:
            return

        path = event.src_path

        # Skip temp and lock files
        name = Path(path).name
        if name.startswith("~") or name.startswith(".") or name.endswith(".tmp") or name.endswith(".lock"):
            return

        now = time.time()

        if path in self._pending:
            # File already pending, check if debounce period passed
            if now - self._pending[path] >= self.DEBOUNCE_SECONDS:
                del self._pending[path]
                self._handle_ready(path)
        else:
            # First detection — start debounce timer
            self._pending[path] = now
            # Schedule a check
            from threading import Timer
            Timer(self.DEBOUNCE_SECONDS + 0.5, self._check_ready, args=[path, now]).start()

    def on_modified(self, event):
        if event.is_directory:
            return
        # Reset debounce timer on modification
        self._pending[event.src_path] = time.time()

    def _check_ready(self, path: str, first_seen: float):
        """Check if file is ready to process after debounce."""
        if path not in self._pending:
            return

        if self._pending[path] == first_seen:
            # File hasn't been modified since first seen
            del self._pending[path]
            self._handle_ready(path)

    def _handle_ready(self, path: str):
        """Handle a file that is ready for processing."""
        try:
            # Verify file exists and is stable
            file_path = Path(path)
            if not file_path.exists():
                return

            stat = file_path.stat()
            if stat.st_size == 0:
                return

            # Create FileItem
            items = self.watcher._scanner.scan_files([path])
            if not items:
                return

            item = items[0]
            self.watcher.file_ready.emit(item)
            self.watcher.new_file_detected.emit(path)

            logger.info(f"检测到新文件: {file_path.name}")

            # Auto-apply mode: trigger processing
            if self.config.mode == WatchMode.AUTO_APPLY:
                logger.info(f"自动处理模式: {file_path.name}")

        except Exception as e:
            logger.error(f"处理新文件失败: {path} — {e}")
