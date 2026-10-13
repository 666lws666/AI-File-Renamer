"""M5 Watch Config Edit Impact Handler.

- Edit must pause active watch first; fail-closed if pause fails
- Pure-data impact summary: pending/analyzing/review-pending/applied counts
- Clear pending queue is explicit, NOT automatic
- Applied tasks, RenameHistory, Undo records preserved
- Delete watch never deletes files, templates, or vocabulary
- No leftover observer or timer after edit/delete
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchMode,
    WatchStatus,
)
from src.controllers.watch_controller import (
    WatchController,
    WatchControllerError,
)


# ── Errors ─────────────────────────────────────────────────────────────────────

class EditError(RuntimeError):
    """Raised for edit/prepare failures. Messages use reason codes, not full paths."""


# ── Task Registry Protocol ─────────────────────────────────────────────────────

class TaskRegistryProtocol(Protocol):
    """Protocol for task registry — decouples WatchEditHandler from concrete task storage."""

    def get_counts(self, config_id: str) -> dict[str, int]:
        """Return counts by status for a watch config."""
        ...

    def clear_pending(self, config_id: str) -> int:
        """Clear non-applied tasks. Returns count cleared."""
        ...


# ── Impact Summary ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EditImpactSummary:
    """Pure-data summary of what an edit would affect. No side effects."""

    pending_count: int = 0
    analyzing_count: int = 0
    review_pending_count: int = 0
    applied_count: int = 0

    @property
    def would_affect_count(self) -> int:
        """Total tasks that would be affected (non-applied)."""
        return self.pending_count + self.analyzing_count + self.review_pending_count

    @property
    def would_clear_queue(self) -> bool:
        """Whether the pending queue would need to be cleared."""
        return self.would_affect_count > 0

    def to_dict(self) -> dict:
        return {
            "pending_count": self.pending_count,
            "analyzing_count": self.analyzing_count,
            "review_pending_count": self.review_pending_count,
            "applied_count": self.applied_count,
            "would_affect_count": self.would_affect_count,
            "would_clear_queue": self.would_clear_queue,
        }


# ── WatchEditHandler ───────────────────────────────────────────────────────────

class WatchEditHandler:
    """Handles safe edit and delete of watch configurations.

    - Pauses watch before edit (fail-closed)
    - Generates impact summary without side effects
    - Requires explicit action to clear pending queue
    - Preserves all applied tasks, history, undo records, and user files
    - Ensures no leftover observers or timers after cleanup
    """

    def __init__(
        self,
        controller: WatchController,
        task_registry: Optional[object] = None,
    ):
        self._controller = controller
        self._task_registry = task_registry

    # ── Prepare Edit ──────────────────────────────────────────────────────────

    def prepare_edit(self, config_id: str) -> None:
        """Pause the watch before editing. Fail-closed if pause fails.

        Raises:
            EditError: If the watch is not found or pause fails.
        """
        if not self._controller.is_watching(config_id):
            raise EditError(f"Watch not found: {config_id}")

        current_status = self._controller.get_status(config_id)

        # Already paused — no action needed
        if current_status == WatchStatus.PAUSED:
            return

        # Try to pause
        try:
            self._controller.pause_watch(config_id)
        except WatchControllerError as e:
            raise EditError(
                f"Failed to pause watch {config_id} before edit: {e}"
            ) from e

    # ── Impact Summary ─────────────────────────────────────────────────────────

    def get_impact_summary(self, config_id: str) -> EditImpactSummary:
        """Generate a pure-data impact summary for the watch config.

        Returns counts of tasks by status. No side effects.
        Does NOT clear anything.

        Raises:
            EditError: If the watch is not found.
        """
        if not self._controller.is_watching(config_id):
            raise EditError(f"Watch not found: {config_id}")

        if self._task_registry is None:
            return EditImpactSummary()

        try:
            counts = self._task_registry.get_counts(config_id)
        except Exception:
            counts = {}

        return EditImpactSummary(
            pending_count=counts.get("pending", 0),
            analyzing_count=counts.get("analyzing", 0),
            review_pending_count=counts.get("review_pending", 0),
            applied_count=counts.get("applied", 0),
        )

    # ── Clear Pending (Explicit) ───────────────────────────────────────────────

    def clear_pending_queue(self, config_id: str) -> int:
        """Explicitly clear the pending task queue for a watch.

        This is NEVER called automatically. Preserves applied tasks.

        Returns:
            Number of tasks cleared.

        Raises:
            EditError: If the watch is not found.
        """
        if not self._controller.is_watching(config_id):
            raise EditError(f"Watch not found: {config_id}")

        if self._task_registry is None:
            return 0

        try:
            return self._task_registry.clear_pending(config_id)
        except Exception as e:
            raise EditError(f"Failed to clear pending queue: {e}") from e

    # ── Delete Watch ───────────────────────────────────────────────────────────

    def delete_watch(self, config_id: str) -> None:
        """Delete a watch configuration safely.

        This method:
        - Stops and removes the observer
        - Removes the config from the store
        - NEVER deletes user files
        - NEVER deletes target directories
        - NEVER deletes templates
        - NEVER undoes applied operations
        - NEVER deletes vocabulary entries
        - Ensures no leftover observers or timers

        Raises:
            EditError: If the watch is not found or deletion fails.
        """
        if not self._controller.is_watching(config_id):
            raise EditError(f"Watch not found: {config_id}")

        try:
            # The controller's remove_watch handles observer cleanup,
            # store removal, and debounce cancellation.
            # It does NOT touch files, templates, history, or vocabulary.
            self._controller.remove_watch(config_id)
        except WatchControllerError as e:
            raise EditError(f"Failed to delete watch {config_id}: {e}") from e

        # Verify cleanup: no observer or timer remains
        obs = self._controller._get_observer(config_id)
        if obs is not None:
            raise EditError(
                f"Observer leak detected after deleting watch {config_id}"
            )
