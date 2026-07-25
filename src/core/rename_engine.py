"""Rename engine — executes batch file renames with validation and conflict handling."""

import os
from uuid import uuid4
from pathlib import Path
from loguru import logger

from ..models.file_item import FileItem, FileStatus
from ..models.rename_record import RenameRecord
from ..utils.file_utils import sanitize_filename, resolve_conflict
from .rename_history import RenameHistory


class RenameEngine:
    """Executes batch file renames with validation and undo support."""

    def __init__(self, history: RenameHistory = None):
        self.history = history or RenameHistory()
        self._last_batch_id: str | None = None

    @property
    def last_batch_id(self) -> str | None:
        return self._last_batch_id

    def execute(self, items: list[FileItem], target_dir: str = None) -> str:
        """Execute batch rename on confirmed items.

        Args:
            items: FileItems to rename. Only items with status SUGGESTED
                   and not IGNORED will be processed.
            target_dir: Optional target directory. If None, rename in place.

        Returns:
            batch_id for undo reference.

        Raises:
            ValueError: If no items to rename or validation fails.
        """
        batch_id = str(uuid4())
        self._last_batch_id = batch_id

        # Filter items to rename
        active = [i for i in items if i.status == FileStatus.SUGGESTED and i.final_name]
        if not active:
            raise ValueError("没有可重命名的文件")

        logger.info(f"开始批量重命名: {len(active)} 个文件, 批次 {batch_id}")

        # Phase 1: Sanitize all names
        for item in active:
            item.final_name = sanitize_filename(item.final_name)

        # Phase 2: Detect and resolve name conflicts
        self._resolve_conflicts(active, target_dir)

        # Phase 3: Execute renames
        success = 0
        failed = 0

        for item in active:
            try:
                old_path = item.original_path
                parent = Path(target_dir) if target_dir else old_path.parent

                # Ensure target directory exists
                parent.mkdir(parents=True, exist_ok=True)

                new_path = parent / item.final_name

                # Safety check: don't rename if new path already exists
                if new_path.exists() and new_path.resolve() != old_path.resolve():
                    item.final_name = resolve_conflict(parent, item.final_name)
                    new_path = parent / item.final_name

                # Execute rename
                os.rename(str(old_path), str(new_path))

                # Record for undo
                self.history.record(RenameRecord(
                    batch_id=batch_id,
                    old_path=old_path,
                    new_path=new_path,
                    file_size=item.file_size,
                ))

                # Update item
                item.original_path = new_path
                item.status = FileStatus.APPLIED
                success += 1
                logger.debug(f"已重命名: {old_path.name} → {item.final_name}")

            except Exception as e:
                logger.error(f"重命名失败: {item.original_name} — {e}")
                item.status = FileStatus.FAILED
                item.error_message = str(e)
                failed += 1

        logger.info(f"批量重命名完成: {success} 成功, {failed} 失败")
        return batch_id

    def _resolve_conflicts(self, items: list[FileItem], target_dir: str = None) -> None:
        """Resolve duplicate filenames by appending counters."""
        used_names: dict[str, list[FileItem]] = {}

        for item in items:
            name = item.final_name.lower()
            if name not in used_names:
                used_names[name] = []
            used_names[name].append(item)

        for name, group in used_names.items():
            if len(group) > 1:
                logger.warning(f"检测到文件名冲突: {name} ({len(group)} 个文件)")
                for i, item in enumerate(group):
                    if i > 0:
                        base, ext = os.path.splitext(item.final_name)
                        item.final_name = f"{base}_{i}{ext}"

    def undo_last(self) -> int:
        """Undo the most recent batch operation.

        Returns:
            Number of files restored.
        """
        batch_id = self.history.get_last_batch_id()
        if not batch_id:
            logger.info("没有可撤销的操作")
            return 0

        return self.history.undo_batch(batch_id)

    def get_history_summary(self) -> list[dict]:
        """Get a summary of recent operations for display."""
        records = self.history.get_all()
        # Group by batch_id
        batches: dict[str, dict] = {}
        for r in records:
            if r.batch_id not in batches:
                batches[r.batch_id] = {
                    "batch_id": r.batch_id,
                    "timestamp": r.timestamp,
                    "count": 0,
                    "undone": r.undone,
                }
            batches[r.batch_id]["count"] += 1

        return sorted(batches.values(), key=lambda b: b["timestamp"], reverse=True)
