"""Rename history — append-only JSONL log for undo support."""

import json
import threading
from pathlib import Path
from loguru import logger

from ..models.rename_record import RenameRecord


class RenameHistory:
    """Append-only operation log stored as JSONL.

    Thread-safe via a lock. Supports reading all records,
    getting records by batch, and marking batches as undone.
    """

    def __init__(self, file_path: str | Path = None):
        if file_path is None:
            file_path = Path("D:/文件AI-AGENT/rename_history/history.jsonl")
        self._file = Path(file_path)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, record: RenameRecord) -> None:
        """Append a rename record to the log."""
        line = record.to_json_line()
        with self._lock:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.debug(f"记录重命名: {record.old_path.name} → {record.new_path.name}")

    def get_all(self) -> list[RenameRecord]:
        """Read all rename records."""
        if not self._file.exists():
            return []
        records = []
        with self._lock:
            with open(self._file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(RenameRecord.from_json_line(line))
                        except Exception as e:
                            logger.warning(f"解析记录失败: {e}")
        return records

    def get_by_batch(self, batch_id: str) -> list[RenameRecord]:
        """Get all records for a specific batch."""
        return [r for r in self.get_all() if r.batch_id == batch_id]

    def get_last_batch_id(self) -> str | None:
        """Get the batch ID of the most recent operation."""
        records = self.get_all()
        if not records:
            return None
        return records[-1].batch_id

    def undo_batch(self, batch_id: str) -> int:
        """Reverse all renames in a batch (LIFO order).

        Args:
            batch_id: The batch to undo.

        Returns:
            Number of renames successfully undone.
        """
        records = self.get_by_batch(batch_id)
        active_records = [r for r in records if not r.undone]

        if not active_records:
            logger.info(f"批次 {batch_id} 没有可撤销的记录")
            return 0

        logger.info(f"撤销批次 {batch_id}: {len(active_records)} 个文件")
        count = 0

        # Reverse: undo in LIFO order
        for record in reversed(active_records):
            try:
                new_exists = record.new_path.exists()
                old_exists = record.old_path.exists()

                if not new_exists:
                    logger.warning(f"文件不存在，无法撤销: {record.new_path}")
                    continue

                if old_exists and old_exists != record.new_path:
                    logger.warning(f"目标路径已存在，跳过: {record.old_path}")
                    continue

                import os
                os.rename(str(record.new_path), str(record.old_path))
                record.undone = True
                count += 1
                logger.debug(f"已撤销: {record.new_path.name} → {record.old_path.name}")

            except Exception as e:
                logger.error(f"撤销失败: {record.new_path} — {e}")

        # Rewrite file with updated undone flags
        self._rewrite_with_undone(batch_id)
        logger.info(f"撤销完成: {count}/{len(active_records)} 个文件")
        return count

    def _rewrite_with_undone(self, batch_id: str) -> None:
        """Rewrite history file, marking records in a batch as undone."""
        all_records = self.get_all()
        with self._lock:
            with open(self._file, "w", encoding="utf-8") as f:
                for r in all_records:
                    if r.batch_id == batch_id:
                        r.undone = True
                    f.write(r.to_json_line() + "\n")
