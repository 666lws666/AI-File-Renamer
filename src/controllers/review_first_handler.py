"""Review First watch pipeline — detect → analyze → await approval → apply.

All execution goes through the SHARED Batch engine chain:
- the injectable analysis service (same protocol as Auto Apply);
- FileTask metadata + RenamePlan;
- PreflightService;
- RenameExecutor (same instance the Batch page uses);
- RenameHistory (written by the executor);
- the main UndoManager can undo approved items via the shared history.

Invariants:
- NO rename happens before approval;
- Approve re-verifies the source fingerprint against the review-time
  fingerprint — a changed file makes the suggestion stale (fail-closed);
- Ignore performs zero file I/O;
- the queue is persistent and fail-closed: a corrupted queue never allows
  auto-apply;
- errors are recorded as short reason codes, never full paths or content.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from src.core.filename_validator import validate_filename
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.core.watch_analysis import AnalysisResult
from src.core.watch_review_queue import (
    ReviewItem,
    ReviewItemState,
    ReviewQueue,
    ReviewQueueError,
)
from src.core.usage import error_category_for

# Error reason codes (persisted; never raw messages or full paths).
ERR_FINGERPRINT_CHANGED = "fingerprint_changed"
ERR_QUEUE_UNAVAILABLE = "queue_unavailable"
ERR_ANALYSIS = "analysis_failed"
ERR_PREFLIGHT = "preflight_rejected"
ERR_APPLY = "apply_failed"
ERR_CAPABILITY = "capability_unsupported"
ERR_NOT_FOUND = "source_missing"
ERR_INVALID_STATE = "invalid_state"


class ReviewFirstHandler:
    """One handler per watch controller.  Dependencies are all injectable."""

    def __init__(
        self,
        *,
        queue: ReviewQueue,
        analysis_service: object,
        executor: object,
        preflight: object,
        config_provider: Callable[[str], object | None],
        clock: Callable[[float], float] | None = None,
        default_quality_mode: str = "balanced",
        on_state_changed: Callable[[], None] | None = None,
        resource_guard: object | None = None,
        on_resource_pause: Callable[[str], None] | None = None,
    ) -> None:
        self._queue = queue
        self._analysis = analysis_service
        self._executor = executor
        self._preflight = preflight
        self._config_provider = config_provider
        self._default_quality_mode = default_quality_mode
        self._on_state_changed = on_state_changed or (lambda: None)
        self._resource_guard = resource_guard
        self._on_resource_pause = on_resource_pause or (lambda watch_id: None)
        self._queue_available = True
        self._queue_error = ""
        try:
            self._queue.items()  # probe: corrupted queue → fail-closed
        except ReviewQueueError as error:
            self._queue_available = False
            self._queue_error = error_category_for(error)
        # Self-wiring: the guard aggregates EVERY registered pipeline's
        # pending counts.  Review registers its APPROVAL backlog as the
        # per-watch pending (held PENDING items are not counted so they
        # never block themselves) and its queue-wide total as the global
        # pending.  A shared guard sums this with Auto Apply's contribution
        # — registration order never matters.
        if self._resource_guard is not None:
            if hasattr(self._resource_guard, "register_pending_source"):
                self._resource_guard.register_pending_source(
                    "review_first",
                    per_watch_counter=lambda wid: len(self._queue.items(
                        wid, states=frozenset({ReviewItemState.AWAITING_APPROVAL}))),
                    global_counter=lambda: len(self._queue.items(
                        states=frozenset({ReviewItemState.AWAITING_APPROVAL}))),
                )
            elif hasattr(self._resource_guard, "set_pending_counter"):
                self._resource_guard.set_pending_counter(
                    lambda wid: len(self._queue.items(
                        wid, states=frozenset({ReviewItemState.AWAITING_APPROVAL})))
                )
                # The GLOBAL pending limit compares against the pipeline-wide
                # total (all watches of this queue), never one watch's count.
                if hasattr(self._resource_guard, "set_global_pending_counter"):
                    self._resource_guard.set_global_pending_counter(
                        lambda: len(self._queue.items(
                            states=frozenset({ReviewItemState.AWAITING_APPROVAL})))
                    )

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def queue_available(self) -> bool:
        return self._queue_available

    @property
    def queue_error(self) -> str:
        return self._queue_error

    def handle_file_ready(self, watch_id: str, source_path: str) -> None:
        """A stable file event — enter the review pipeline.

        Dedupes by (watch_id, source_path): an already-active item is never
        duplicated.
        """
        if not self._queue_available:
            return
        config = self._config_provider(watch_id)
        if config is None:
            return

        try:
            stat = os.stat(source_path)
        except OSError:
            return  # file gone — nothing to review

        if not os.path.isfile(source_path):
            return

        # Dedupe: an active item for this path already occupies the slot
        existing = self._queue.active_for_path(watch_id, source_path)
        if existing is not None:
            return

        name = os.path.basename(source_path)
        stem, ext = os.path.splitext(name)
        target_parent = config.target_dir or str(Path(source_path).parent)

        item = ReviewItem(
            id="",
            watch_id=watch_id,
            source_path=source_path,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            extension=ext,
            display_name=stem,
            state=ReviewItemState.PENDING,
            target_parent=target_parent,
        )
        item = self._queue.add(item)
        self._maybe_analyze(item)

    def approve(self, item_id: str) -> ReviewItem | None:
        """Approve a review item: re-verify, preflight, execute via the
        shared RenameExecutor.  Returns the final item or None."""
        item = self._queue.get(item_id)
        if item is None:
            return None
        if item.state != ReviewItemState.AWAITING_APPROVAL:
            return None

        # Fingerprint must still match the review-time snapshot
        current = self._stat_fingerprint(item.source_path)
        if current is None:
            return self._fail(item, ERR_NOT_FOUND)
        if current != item.fingerprint():
            return self._fail(item, ERR_FINGERPRINT_CHANGED)

        if not item.suggested_name or not item.target_parent:
            return self._fail(item, ERR_INVALID_STATE)

        plan = RenamePlan(
            task_id=item.id,
            source_path=item.source_path,
            source_fingerprint=SourceFingerprint(*item.fingerprint()),
            target_name=item.suggested_name,
            target_parent=item.target_parent,
            extension=item.extension,
            batch_id=item.batch_id or f"watch-review-{item.id}",
        )

        # Preflight must pass against the CURRENT file state — this is the
        # mandatory re-verification before any disk mutation.
        try:
            pf = self._preflight.check(plan)
        except Exception as error:
            return self._fail(item, error_category_for(error))
        if not pf.can_execute:
            return self._fail(item, ERR_PREFLIGHT)

        item = self._queue.update(item.with_state(ReviewItemState.APPLYING))

        try:
            results = self._executor.execute([plan], batch_id=plan.batch_id)
        except Exception as error:
            return self._fail(item, error_category_for(error))

        result = results[0] if results else None
        if result is not None and result.success:
            final = item.with_state(
                ReviewItemState.APPLIED,
                batch_id=plan.batch_id,
                error_category="history_unavailable" if result.recovery_required else "",
            )
            try:
                final = self._queue.update(final)
            except ReviewQueueError:
                # Disk/history are already authoritative.  Startup
                # reconciliation will persist APPLIED instead of cancelling it.
                pass
            self._note_success(item.watch_id)
            return final
        detail = result.error if result is not None and result.error else ""
        return self._fail(item, ERR_APPLY, detail_hint=detail)

    def ignore(self, item_id: str) -> ReviewItem | None:
        """Mark ignored — zero file I/O, no history entry."""
        item = self._queue.get(item_id)
        if item is None:
            return None
        if item.state in (ReviewItemState.APPLIED, ReviewItemState.IGNORED):
            return item
        return self._queue.update(item.with_state(ReviewItemState.IGNORED))

    def retry(self, item_id: str) -> ReviewItem | None:
        """Retry only failed/cancelled items — never creates a duplicate."""
        item = self._queue.get(item_id)
        if item is None:
            return None
        if item.state not in (ReviewItemState.FAILED, ReviewItemState.CANCELLED):
            return item
        item = self._queue.update(item.with_state(ReviewItemState.PENDING, error_category=""))
        self._maybe_analyze(item)
        return self._queue.get(item_id)

    def on_watch_removed(self, watch_id: str) -> None:
        """Watch config deleted: never touch files or undo history — cancel
        unapplied review items per the edit-impact policy."""
        for item in self._queue.items(watch_id=watch_id):
            if item.state not in (ReviewItemState.APPLIED, ReviewItemState.IGNORED):
                try:
                    self._queue.update(item.with_state(ReviewItemState.CANCELLED))
                except ReviewQueueError:
                    return

    def on_watch_resumed(self, watch_id: str) -> None:
        """Resource recovery / manual resume: re-process held (PENDING)
        items in deterministic FIFO order.  Never creates duplicates — the
        existing items are re-checked against the resource guard, and
        fingerprints are re-verified downstream."""
        for item in self._queue.items(
            watch_id=watch_id, states=frozenset({ReviewItemState.PENDING})
        ):
            self._maybe_analyze(item)

    def restore_after_restart(self) -> int:
        """Interrupted analysis/apply → cancelled (safe recovery).  Returns
        the number of items recovered."""
        recovered = 0
        history = getattr(self._executor, "history", None)
        for item in self._queue.items():
            if item.state in (ReviewItemState.ANALYZING, ReviewItemState.APPLYING, ReviewItemState.PENDING):
                try:
                    record = history.get_latest_for_task(item.id) if history is not None else None
                    if (
                        item.state == ReviewItemState.APPLYING
                        and record is not None
                        and os.path.isfile(str(record.new_path))
                        and not os.path.exists(str(record.old_path))
                    ):
                        self._queue.update(item.with_state(
                            ReviewItemState.APPLIED, batch_id=record.batch_id))
                    else:
                        self._queue.update(item.with_state(ReviewItemState.CANCELLED))
                    recovered += 1
                except ReviewQueueError:
                    return recovered
        self._on_state_changed()
        return recovered

    # ── Internal ──────────────────────────────────────────────────────────

    def _maybe_analyze(self, item: ReviewItem) -> None:
        """Resource-gated analysis: while the guard blocks, the item stays
        PENDING (held) — never analyzed, never applied, never lost."""
        if not self._queue_available:
            return
        if self._resource_guard is not None:
            # check + slot are ONE atomic operation under the guard's lock
            decision = self._resource_guard.try_acquire_analysis(item.watch_id, item.size_bytes)
            if decision.blocked:
                self._on_resource_pause(item.watch_id)
                return  # held: item remains PENDING
            try:
                self._analyze(item)
            finally:
                self._resource_guard.release_analysis(item.watch_id)
        else:
            self._analyze(item)

    def _analyze(self, item: ReviewItem) -> None:
        if not self._queue_available:
            return
        config = self._config_provider(item.watch_id)
        template_id = config.template_id if config is not None else ""
        item = self._queue.update(item.with_state(ReviewItemState.ANALYZING))
        try:
            result = self._analysis.analyze(
                item.source_path,
                template_id=template_id,
                quality_mode=self._default_quality_mode,
            )
        except Exception as error:
            category = error_category_for(error)
            if category == "capability_unsupported":
                self._queue.update(item.with_state(
                    ReviewItemState.FAILED, error_category=ERR_CAPABILITY))
            else:
                self._queue.update(item.with_state(
                    ReviewItemState.FAILED, error_category=ERR_ANALYSIS))
            self._note_failure(item.watch_id)
            self._on_state_changed()
            return

        if not isinstance(result, AnalysisResult) or not result.ok:
            category = result.error_category if isinstance(result, AnalysisResult) else ""
            self._queue.update(item.with_state(
                ReviewItemState.FAILED,
                error_category=ERR_CAPABILITY if category == "capability_unsupported" else ERR_ANALYSIS,
            ))
            self._note_failure(item.watch_id)
            self._on_state_changed()
            return

        # Validate the suggestion through the shared filename validator
        validation = validate_filename(result.suggested_name, item.extension)
        if not validation.is_valid:
            self._queue.update(item.with_state(
                ReviewItemState.FAILED, error_category="invalid_suggestion"))
            self._note_failure(item.watch_id)
            self._on_state_changed()
            return

        self._queue.update(item.with_state(
            ReviewItemState.AWAITING_APPROVAL,
            suggested_name=result.suggested_name,
            confidence=result.confidence,
            content_kind=result.content_kind,
        ))
        self._note_success(item.watch_id)
        self._on_state_changed()

    def _note_failure(self, watch_id: str) -> None:
        """Record one failed operation on the guard (consecutive failures
        trip the failure backoff)."""
        if self._resource_guard is not None:
            self._resource_guard.note_failure(watch_id)

    def _note_success(self, watch_id: str) -> None:
        """Record one successful operation — resets the failure count under
        the unified semantic: any completed operation either fails once or
        succeeds."""
        if self._resource_guard is not None:
            self._resource_guard.note_success(watch_id)

    def _fail(self, item: ReviewItem, category: str, detail_hint: str = "") -> ReviewItem:
        # reason codes only; the executor's message may contain paths →
        # keep a stable category and never persist the raw message
        self._note_failure(item.watch_id)
        return self._queue.update(item.with_state(
            ReviewItemState.FAILED, error_category=category))

    def _stat_fingerprint(self, source_path: str) -> tuple[int, int] | None:
        try:
            stat = os.stat(source_path)
            if not os.path.isfile(source_path):
                return None
            return (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return None

    # ── Test helpers ──────────────────────────────────────────────────────

    def items(self, watch_id: str | None = None) -> list[ReviewItem]:
        return self._queue.items(watch_id=watch_id)

    def item(self, item_id: str) -> ReviewItem | None:
        return self._queue.get(item_id)
