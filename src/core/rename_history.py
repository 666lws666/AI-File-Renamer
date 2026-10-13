"""Rename history — append-only JSONL log for undo support."""

import json
import os
import tempfile
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
            import os as _os
            base = _os.environ.get("LOCALAPPDATA", _os.path.expanduser("~"))
            file_path = Path(base) / "Xuxia" / "rename_history" / "history.jsonl"
        self._file = Path(file_path)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, record: RenameRecord) -> None:
        """Append a rename record to the log."""
        line = record.to_json_line()
        with self._lock:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        try:
            logger.debug(f"记录重命名: {record.old_path.name} → {record.new_path.name}")
        except Exception:
            pass  # Persistence is confirmed; logging cannot cause compensation.

    @staticmethod
    def _unique_object(pairs):
        values = {}
        for key, value in pairs:
            if key in values: raise ValueError('duplicate_history_key')
            values[key] = value
        return values

    def _read_strict_unlocked(self):
        """Repair must preserve every unrelated raw field and reject corruption."""
        rows, ids = [], set()
        try:
            stream = self._file.open('r', encoding='utf-8')
        except FileNotFoundError:
            return []  # Actual open proves absence; an existence probe cannot.
        except (OSError, UnicodeError, ValueError):
            raise OSError('fileops.error.historySaveRecovery') from None
        try:
            with stream:
                for line in stream:
                    if not line.strip(): continue
                    raw = json.loads(line, object_pairs_hook=self._unique_object)
                    if (type(raw) is not dict
                            or any(type(raw.get(key)) is not str for key in
                                   ('id', 'timestamp', 'batch_id', 'old_path', 'new_path'))
                            or not raw['id'] or not raw['old_path'] or not raw['new_path']
                            or type(raw.get('task_id', '')) is not str
                            or type(raw.get('file_size', 0)) is not int or raw.get('file_size', 0) < 0
                            or type(raw.get('undone', False)) is not bool
                            or raw['id'] in ids):
                        raise ValueError()
                    record = RenameRecord.from_json_line(line)
                    ids.add(record.id)
                    rows.append((raw, record))
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
            raise OSError('fileops.error.historySaveRecovery') from None
        return rows

    def _write_strict_unlocked(self, rows):
        # Serialize the complete candidate BEFORE creating any replacement file.
        try:
            lines = [json.dumps(raw, ensure_ascii=False, allow_nan=False) + '\n' for raw, _ in rows]
        except (ValueError, TypeError):
            raise OSError('fileops.error.historySaveRecovery') from None
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(self._file.parent),
                    suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                stream.writelines(lines)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(self._file))
        except OSError:
            if temporary is not None:
                try: os.unlink(temporary)
                except OSError: pass
            raise OSError('fileops.error.historySaveRecovery') from None

    def finalize_rolled_back_record(self, record: RenameRecord) -> None:
        """Strict metadata-only disposition after confirmed physical compensation."""
        try:
            expected = json.loads(record.to_json_line())
        except (ValueError, TypeError, AttributeError):
            raise OSError('fileops.error.historySaveRecovery') from None
        with self._lock:
            rows = self._read_strict_unlocked()
            matches = [(raw, existing) for raw, existing in rows if existing.id == record.id]
            if not matches: return  # Proven absent after a complete strict read.
            raw, _ = matches[0]
            if any(raw.get(key, None) != expected[key] for key in
                   ('task_id', 'batch_id', 'old_path', 'new_path', 'file_size', 'move_evidence')):
                raise OSError('fileops.error.historySaveRecovery')
            raw['undone'] = True
            self._write_strict_unlocked(rows)

    def _get_all_unlocked(self) -> list[RenameRecord]:
        if not self._file.exists():
            return []
        records = []
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(RenameRecord.from_json_line(line))
                    except Exception as e:
                        logger.warning(f"解析记录失败: {e}")
        return records

    def get_all(self) -> list[RenameRecord]:
        """Read all rename records."""
        with self._lock:
            return self._get_all_unlocked()

    def get_by_batch(self, batch_id: str) -> list[RenameRecord]:
        """Get all records for a specific batch."""
        return [r for r in self.get_all() if r.batch_id == batch_id]

    def get_latest_for_task(self, task_id: str, *, active_only: bool = True) -> RenameRecord | None:
        """Return the newest record for a task, optionally excluding undone records."""
        for record in reversed(self.get_all()):
            if record.task_id == task_id and (not active_only or not record.undone):
                return record
        return None

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

    def mark_records_undone(self, batch_id: str, record_ids: list[str]) -> None:
        """Mark specific records as undone without file I/O. Only marks, doesn't move files."""
        id_set = set(record_ids)
        with self._lock:
            rows = self._read_strict_unlocked()
            for raw, record in rows:
                if record.batch_id == batch_id and record.id in id_set:
                    raw['undone'] = True
            self._write_strict_unlocked(rows)

    def _rewrite_with_undone(self, batch_id: str) -> None:
        """Rewrite history file, marking all records in a batch as undone."""
        with self._lock:
            all_records = self._get_all_unlocked()
            with open(self._file, "w", encoding="utf-8") as f:
                for r in all_records:
                    if r.batch_id == batch_id:
                        r.undone = True
                    f.write(r.to_json_line() + "\n")
