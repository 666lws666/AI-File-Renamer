"""Recursive directory scanner with file type filtering."""

import os
from pathlib import Path
from typing import Generator
from loguru import logger

from ..models.file_item import FileItem
from ..utils.constants import SUPPORTED_EXTENSIONS


class FileScanner:
    """Scans directories for supported files and creates FileItem objects."""

    def __init__(self, max_file_size_mb: int = 50, recursive: bool = True):
        self.max_size_bytes = max_file_size_mb * 1024 * 1024
        self.recursive = recursive

    def scan_directory(self, root_dir: str | Path) -> list[FileItem]:
        """Scan a directory and return FileItem list.

        Args:
            root_dir: Root directory to scan.

        Returns:
            List of FileItem objects for supported files.
        """
        items = list(self._walk(Path(root_dir)))
        logger.info(f"扫描完成: {root_dir} → {len(items)} 个文件")
        return items

    def scan_files(self, file_paths: list[str]) -> list[FileItem]:
        """Create FileItem objects from a list of specific file paths.

        Args:
            file_paths: List of file paths.

        Returns:
            List of FileItem objects for supported files.
        """
        items = []
        for fp in file_paths:
            path = Path(fp)
            if not path.is_file():
                continue
            item = self._create_item(path)
            if item:
                items.append(item)
        return items

    def _walk(self, root: Path) -> Generator[FileItem, None, None]:
        """Walk directory tree and yield FileItems."""
        pattern = "**/*" if self.recursive else "*"
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            item = self._create_item(path)
            if item:
                yield item

    def _create_item(self, path: Path) -> FileItem | None:
        """Create a FileItem from a path if it's valid and supported.

        Returns None if the file should be skipped.
        """
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return None

        try:
            stat = path.stat()
        except OSError as e:
            logger.warning(f"无法读取文件信息: {path} — {e}")
            return None

        if stat.st_size > self.max_size_bytes:
            logger.debug(f"文件过大，跳过: {path} ({stat.st_size} bytes)")
            return None

        if stat.st_size == 0:
            logger.debug(f"空文件，跳过: {path}")
            return None

        from datetime import datetime

        return FileItem(
            original_path=path,
            file_type=ext.lstrip("."),
            file_size=stat.st_size,
            file_mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )
