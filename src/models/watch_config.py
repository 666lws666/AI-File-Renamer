"""WatchConfig — configuration for a monitored folder."""

from enum import Enum
from uuid import uuid4
from pydantic import BaseModel, Field


class WatchMode(str, Enum):
    REVIEW_FIRST = "review_first"   # Generate suggestion, wait for user review
    AUTO_APPLY = "auto_apply"       # Automatically rename without review


class WatchConfig(BaseModel):
    """Configuration for one watched folder."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_dir: str = ""
    template_id: str = ""
    target_dir: str = ""             # Optional: where to move renamed files
    mode: WatchMode = WatchMode.REVIEW_FIRST
    active: bool = True
    recursive: bool = True           # Watch subdirectories
    file_types: list[str] = Field(default_factory=list)  # Empty = all supported
