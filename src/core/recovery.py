"""Fail-closed recovery for versioned JSON stores and Undo history."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RecoveryState(str, Enum):
    HEALTHY = "healthy"
    RESTORED = "restored"
    DEFAULTED = "defaulted"
    CLEARED = "cleared"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RecoveryResult:
    state: RecoveryState
    data: Any = None
    quarantined_path: Path | None = None
    user_message_id: str = ""


class RecoveryManager:
    def __init__(self, credential_store: Any = None) -> None:
        self.credential_store = credential_store
        self.apply_allowed = True

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _quarantine(path: Path) -> Path:
        candidate = path.with_suffix(".corrupted")
        index = 1
        while candidate.exists():
            candidate = path.with_name(f"{path.stem}.{index}.corrupted")
            index += 1
        os.replace(path, candidate)
        return candidate

    def recover_json(self, path: str | Path, *, snapshot_path: str | Path | None = None,
                     safe_default: Any = None, kind: str = "data") -> RecoveryResult:
        target = Path(path)
        try:
            return RecoveryResult(RecoveryState.HEALTHY, self._read_json(target))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            quarantined = self._quarantine(target) if target.exists() else None
        if snapshot_path is not None:
            try:
                data = self._read_json(Path(snapshot_path))
                self.write_json_atomic(target, data)
                return RecoveryResult(
                    RecoveryState.RESTORED, data, quarantined,
                    f"recovery.{kind}.restored",
                )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        data = safe_default
        self.write_json_atomic(target, data)
        return RecoveryResult(
            RecoveryState.DEFAULTED, data, quarantined,
            f"recovery.{kind}.defaulted",
        )

    def recover_cache(self, path: str | Path) -> RecoveryResult:
        target = Path(path)
        try:
            self._read_json(target)
            return RecoveryResult(RecoveryState.HEALTHY)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            if target.exists():
                target.unlink()
            return RecoveryResult(
                RecoveryState.CLEARED, user_message_id="recovery.cache.cleared"
            )

    def recover_undo(self, path: str | Path) -> RecoveryResult:
        target = Path(path)
        try:
            data = self._read_json(target)
            return RecoveryResult(RecoveryState.HEALTHY, data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            quarantined = self._quarantine(target) if target.exists() else None
            self.apply_allowed = False
            return RecoveryResult(
                RecoveryState.BLOCKED, quarantined_path=quarantined,
                user_message_id="recovery.undo.blocked",
            )

    @staticmethod
    def write_json_atomic(path: str | Path, data: Any) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise