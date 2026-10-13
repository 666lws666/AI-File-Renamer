"""RenameRecord — immutable log of a single rename operation for undo support."""

import json
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from src.core.rename_plan import (FileMoveEvidence, validate_move_evidence,
                                  encode_move_evidence, decode_move_evidence)


class RenameRecord(BaseModel):
    """Immutable record of one rename operation."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    batch_id: str = ""            # Groups renames from one "Apply" click
    task_id: str = ""             # Links to FileTask for per-task tracking
    old_path: Path
    new_path: Path
    file_size: int = 0
    undone: bool = False
    move_evidence: FileMoveEvidence | None = None

    class Config:
        arbitrary_types_allowed = True

    @field_validator("move_evidence", mode="before")
    @classmethod
    def _validate_move_evidence(cls, value):
        if value is not None:
            validate_move_evidence(value)
        return value

    def to_json_line(self) -> str:
        """Serialize to a single JSON line for JSONL storage."""
        return json.dumps({
            "id": self.id,
            "timestamp": self.timestamp,
            "batch_id": self.batch_id,
            "task_id": self.task_id,
            "old_path": str(self.old_path),
            "new_path": str(self.new_path),
            "file_size": self.file_size,
            "undone": self.undone,
            "move_evidence": None if self.move_evidence is None else encode_move_evidence(self.move_evidence),
        }, ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> "RenameRecord":
        """Deserialize from a JSONL line."""
        d = json.loads(line)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            batch_id=d["batch_id"],
            task_id=d.get("task_id", ""),
            old_path=Path(d["old_path"]),
            new_path=Path(d["new_path"]),
            file_size=d.get("file_size", 0),
            undone=d.get("undone", False),
            move_evidence=None if d.get("move_evidence") is None else decode_move_evidence(d["move_evidence"]),
        )
