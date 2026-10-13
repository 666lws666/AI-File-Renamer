"""M4 Vocabulary Undo Manager — LIFO, per-record outcomes, fully independent of file undo."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)


class VocabActionType(str, Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE_TOMBSTONE = "delete_tombstone"
    RESTORE = "restore"
    ACCEPT_SUGGESTION = "accept_suggestion"
    AUTO_CREATE = "auto_create"


@dataclass
class VocabUndoResult:
    """Per-record outcome of a vocabulary undo operation."""

    action_type: VocabActionType
    entry_id: str
    success: bool
    error: str = ""


@dataclass
class _UndoRecord:
    """Internal record of an undoable vocabulary action."""

    action_type: VocabActionType
    entry_id: str
    # For ADD/ACCEPT_SUGGESTION/AUTO_CREATE: the full entry that was added
    previous_entry: Optional[VocabularyEntry] = None
    # For EDIT: the previous display_name (or full entry before edit)
    previous_display_name: Optional[str] = None
    # For RESTORE: the override that was in place before restore
    previous_override: Optional[str] = None


class VocabularyUndoManager:
    """Independent undo stack for vocabulary operations.

    Completely isolated from file RenameHistory and UndoManager.
    Does NOT read or write file rename undo history.
    All operations go through the VocabularyStore for proper versioning.
    """

    def __init__(self, store: VocabularyStore):
        self._store = store
        self._stack: list[_UndoRecord] = []

    # ── Record actions ────────────────────────────────────────────────────

    def record_action(
        self,
        action_type: VocabActionType,
        entry_id: str,
        previous_entry: Optional[VocabularyEntry] = None,
        previous_display_name: Optional[str] = None,
        previous_override: Optional[str] = None,
    ) -> None:
        """Record an undoable vocabulary action."""
        self._stack.append(_UndoRecord(
            action_type=action_type,
            entry_id=entry_id,
            previous_entry=previous_entry,
            previous_display_name=previous_display_name,
            previous_override=previous_override,
        ))

    # ── Undo ──────────────────────────────────────────────────────────────

    def undo_last(self) -> list[VocabUndoResult]:
        """Undo the most recent action (LIFO). Returns per-record outcomes."""
        if not self._stack:
            return []
        record = self._stack.pop()
        result = self._execute_undo(record)
        return [result]

    def undo_all(self) -> list[VocabUndoResult]:
        """Undo all recorded actions in LIFO order. Returns per-record outcomes."""
        results = []
        while self._stack:
            record = self._stack.pop()
            result = self._execute_undo(record)
            results.append(result)
        return results

    def get_undoable_count(self) -> int:
        """Return the number of actions available for undo."""
        return len(self._stack)

    # ── Internal undo execution ───────────────────────────────────────────

    def _execute_undo(self, record: _UndoRecord) -> VocabUndoResult:
        """Execute a single undo operation. Never raises — returns failure result."""
        try:
            if record.action_type == VocabActionType.ADD:
                return self._undo_add(record)
            elif record.action_type == VocabActionType.EDIT:
                return self._undo_edit(record)
            elif record.action_type == VocabActionType.DELETE_TOMBSTONE:
                return self._undo_tombstone(record)
            elif record.action_type == VocabActionType.RESTORE:
                return self._undo_restore(record)
            elif record.action_type == VocabActionType.ACCEPT_SUGGESTION:
                return self._undo_accept_suggestion(record)
            elif record.action_type == VocabActionType.AUTO_CREATE:
                return self._undo_auto_create(record)
            else:
                return VocabUndoResult(
                    action_type=record.action_type,
                    entry_id=record.entry_id,
                    success=False,
                    error=f"Unknown action type: {record.action_type}",
                )
        except Exception as e:
            return VocabUndoResult(
                action_type=record.action_type,
                entry_id=record.entry_id,
                success=False,
                error=str(e),
            )

    def _undo_add(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo an ADD: remove the entry from store."""
        try:
            self._store.remove_entry(record.entry_id)
            return VocabUndoResult(
                action_type=VocabActionType.ADD,
                entry_id=record.entry_id,
                success=True,
            )
        except KeyError:
            return VocabUndoResult(
                action_type=VocabActionType.ADD,
                entry_id=record.entry_id,
                success=False,
                error="Entry no longer exists in store",
            )

    def _undo_edit(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo an EDIT: restore previous state."""
        try:
            # Check if entry still exists
            if record.entry_id not in self._store._entries:
                return VocabUndoResult(
                    action_type=VocabActionType.EDIT,
                    entry_id=record.entry_id,
                    success=False,
                    error="Entry no longer exists in store",
                )

            entry = self._store._entries[record.entry_id]

            # If we have a full previous_entry, replace entirely
            if record.previous_entry is not None:
                # Remove current, add previous
                self._store.remove_entry(record.entry_id)
                try:
                    self._store.add_entry(record.previous_entry)
                except Exception:
                    # Best effort: try adding with original concept_id
                    self._store.add_entry(VocabularyEntry(
                        id=record.previous_entry.id,
                        category=record.previous_entry.category,
                        concept_id=record.previous_entry.concept_id,
                        display_name=record.previous_entry.display_name,
                        locale=record.previous_entry.locale,
                        source=record.previous_entry.source,
                        confidence=record.previous_entry.confidence,
                        created_by_model=record.previous_entry.created_by_model,
                        created_at=record.previous_entry.created_at,
                    ))
            elif record.previous_display_name is not None:
                # For system presets: restore override or remove it
                if entry.source == VocabularySource.SYSTEM:
                    current_overrides = dict(self._store._overrides)
                    if record.entry_id in current_overrides:
                        if record.previous_display_name == "":
                            # Was no override → restore to preset
                            self._store.restore_entry(record.entry_id)
                        else:
                            # Set override back to previous display_name
                            self._store.override_entry(
                                record.entry_id, record.previous_display_name
                            )
                    else:
                        # No current override — the original must have been the display_name
                        if record.previous_display_name != entry.display_name:
                            self._store.override_entry(
                                record.entry_id, record.previous_display_name
                            )
                else:
                    # For user entries, we can't easily undo without full previous_entry
                    return VocabUndoResult(
                        action_type=VocabActionType.EDIT,
                        entry_id=record.entry_id,
                        success=False,
                        error="Cannot undo edit of user entry without previous_entry",
                    )

            return VocabUndoResult(
                action_type=VocabActionType.EDIT,
                entry_id=record.entry_id,
                success=True,
            )
        except Exception as e:
            return VocabUndoResult(
                action_type=VocabActionType.EDIT,
                entry_id=record.entry_id,
                success=False,
                error=str(e),
            )

    def _undo_tombstone(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo a DELETE_TOMBSTONE: restore the entry."""
        try:
            self._store.restore_entry(record.entry_id)
            return VocabUndoResult(
                action_type=VocabActionType.DELETE_TOMBSTONE,
                entry_id=record.entry_id,
                success=True,
            )
        except KeyError:
            return VocabUndoResult(
                action_type=VocabActionType.DELETE_TOMBSTONE,
                entry_id=record.entry_id,
                success=False,
                error="Entry not found for restore",
            )
        except Exception as e:
            return VocabUndoResult(
                action_type=VocabActionType.DELETE_TOMBSTONE,
                entry_id=record.entry_id,
                success=False,
                error=str(e),
            )

    def _undo_restore(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo a RESTORE: re-apply the previous override."""
        try:
            if record.previous_override is not None:
                self._store.override_entry(record.entry_id, record.previous_override)
            return VocabUndoResult(
                action_type=VocabActionType.RESTORE,
                entry_id=record.entry_id,
                success=True,
            )
        except Exception as e:
            return VocabUndoResult(
                action_type=VocabActionType.RESTORE,
                entry_id=record.entry_id,
                success=False,
                error=str(e),
            )

    def _undo_accept_suggestion(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo an ACCEPT_SUGGESTION: remove the accepted entry."""
        try:
            self._store.remove_entry(record.entry_id)
            return VocabUndoResult(
                action_type=VocabActionType.ACCEPT_SUGGESTION,
                entry_id=record.entry_id,
                success=True,
            )
        except KeyError:
            return VocabUndoResult(
                action_type=VocabActionType.ACCEPT_SUGGESTION,
                entry_id=record.entry_id,
                success=False,
                error="Entry no longer exists",
            )

    def _undo_auto_create(self, record: _UndoRecord) -> VocabUndoResult:
        """Undo an AUTO_CREATE: remove the created entry."""
        try:
            self._store.remove_entry(record.entry_id)
            return VocabUndoResult(
                action_type=VocabActionType.AUTO_CREATE,
                entry_id=record.entry_id,
                success=True,
            )
        except KeyError:
            return VocabUndoResult(
                action_type=VocabActionType.AUTO_CREATE,
                entry_id=record.entry_id,
                success=False,
                error="Entry no longer exists",
            )
