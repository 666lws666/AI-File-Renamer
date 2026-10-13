"""M2 FileTask — strict state machine with eight display states."""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class FileTaskState(Enum):
    PENDING = auto()
    EXTRACTING = auto()
    EXTRACTED = auto()
    SUGGESTING = auto()
    SUGGESTED = auto()
    APPLIED = auto()
    FAILED = auto()
    CANCELLED = auto()
    IGNORED = auto()
    UNDONE = auto()


DISPLAY_MAP = {
    FileTaskState.PENDING: "pending",
    FileTaskState.EXTRACTING: "analyzing",
    FileTaskState.EXTRACTED: "analyzing",
    FileTaskState.SUGGESTING: "analyzing",
    FileTaskState.SUGGESTED: "review_pending",
    FileTaskState.UNDONE: "undone",
    FileTaskState.APPLIED: "applied",
    FileTaskState.FAILED: "failed",
    FileTaskState.CANCELLED: "cancelled",
    FileTaskState.IGNORED: "ignored",
}

VALID_TRANSITIONS = {
    FileTaskState.PENDING: {FileTaskState.EXTRACTING, FileTaskState.CANCELLED, FileTaskState.IGNORED},
    FileTaskState.EXTRACTING: {FileTaskState.EXTRACTED, FileTaskState.FAILED, FileTaskState.CANCELLED, FileTaskState.IGNORED},
    FileTaskState.EXTRACTED: {FileTaskState.SUGGESTING, FileTaskState.FAILED, FileTaskState.CANCELLED, FileTaskState.IGNORED},
    FileTaskState.SUGGESTING: {FileTaskState.SUGGESTED, FileTaskState.FAILED, FileTaskState.CANCELLED, FileTaskState.IGNORED},
    FileTaskState.SUGGESTED: {FileTaskState.SUGGESTING, FileTaskState.APPLIED, FileTaskState.IGNORED},
    FileTaskState.FAILED: {FileTaskState.PENDING, FileTaskState.IGNORED},
    FileTaskState.CANCELLED: {FileTaskState.PENDING, FileTaskState.IGNORED},
    FileTaskState.IGNORED: {FileTaskState.PENDING},
    FileTaskState.APPLIED: {FileTaskState.UNDONE},
    FileTaskState.UNDONE: {FileTaskState.PENDING},
}


class InvalidStateTransitionError(ValueError):
    """Raised when attempting an illegal state transition."""
    pass


@dataclass(frozen=True)
class FileTask:
    task_id: str
    original_path: str
    display_name: str
    extension: str
    size_bytes: int
    modified_ns: int
    state: FileTaskState = FileTaskState.PENDING
    suggested_name: str = ""
    error_message: str = ""

    def transition(self, new_state: FileTaskState) -> "FileTask":
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition from {self.state.name} to {new_state.name}"
            )
        return FileTask(
            task_id=self.task_id,
            original_path=self.original_path,
            display_name=self.display_name,
            extension=self.extension,
            size_bytes=self.size_bytes,
            modified_ns=self.modified_ns,
            state=new_state,
            suggested_name=self.suggested_name,
            error_message=self.error_message,
        )

    @property
    def display_state(self) -> str:
        return DISPLAY_MAP.get(self.state, "pending")
