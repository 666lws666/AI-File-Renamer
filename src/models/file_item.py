"""FileItem — the central data model flowing through the rename pipeline."""

from enum import Enum
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    PENDING = "pending"          # Just scanned, not yet processed
    EXTRACTING = "extracting"    # Content extraction in progress
    EXTRACTED = "extracted"      # Content extracted, ready for AI
    SUGGESTING = "suggesting"    # AI suggestion in progress
    SUGGESTED = "suggested"      # AI suggestion ready
    APPLIED = "applied"          # Rename applied
    FAILED = "failed"            # Processing failed
    IGNORED = "ignored"          # User chose to skip


class FileItem(BaseModel):
    """Represents a single file going through the rename pipeline."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    original_path: Path
    file_type: str = ""  # e.g. "pdf", "docx", "jpg"
    file_size: int = 0   # bytes
    file_mtime: str = ""  # ISO format modification time

    # Extracted content
    extracted_text: str = ""
    metadata: dict = Field(default_factory=dict)

    # AI suggestion
    ai_fields: dict = Field(default_factory=dict)       # Raw AI JSON response
    suggested_name: str = ""                             # AI-suggested filename
    final_name: str = ""                                 # User-confirmed filename (may differ)

    # Status tracking
    status: FileStatus = FileStatus.PENDING
    error_message: str = ""

    class Config:
        arbitrary_types_allowed = True

    @property
    def original_name(self) -> str:
        return self.original_path.name

    @property
    def original_ext(self) -> str:
        return self.original_path.suffix.lower()

    @property
    def parent_dir(self) -> Path:
        return self.original_path.parent
