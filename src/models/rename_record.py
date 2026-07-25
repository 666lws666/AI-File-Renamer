"""RenameRecord — immutable log of a single rename operation for undo support."""

import json
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field


class RenameRecord(BaseModel):
    """Immutable record of one rename operation."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    batch_id: str = ""            # Groups renames from one "Apply" click
    old_path: Path
    new_path: Path
    file_size: int = 0
    undone: bool = False

    class Config:
        arbitrary_types_allowed = True

    def to_json_line(self) -> str:
        """Serialize to a single JSON line for JSONL storage."""
        return json.dumps({
            "id": self.id,
            "timestamp": self.timestamp,
            "batch_id": self.batch_id,
            "old_path": str(self.old_path),
            "new_path": str(self.new_path),
            "file_size": self.file_size,
            "undone": self.undone,
        }, ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> "RenameRecord":
        """Deserialize from a JSONL line."""
        d = json.loads(line)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            batch_id=d["batch_id"],
            old_path=Path(d["old_path"]),
            new_path=Path(d["new_path"]),
            file_size=d.get("file_size", 0),
            undone=d.get("undone", False),
        )
