"""Qt-owner durable publication of genuine managed Watch metadata only."""
from __future__ import annotations

import os
import threading
from types import MappingProxyType, MethodType
from uuid import uuid4

from PySide6.QtCore import QObject

from src.controllers.managed_watch_analysis import ManagedWatchAnalysisDelivery
from src.core.watch_resource_guard import WatchResourceGuard
from src.core.watch_review_queue import (
    ACTIVE_STATES, ReviewItem, ReviewItemState, ReviewQueue, ReviewQueueError,
)
from src.core.watch_work import StableWatchEvent, WatchAdmissionFailure


class ManagedWatchResultsError(RuntimeError):
    """Fixed boundary failure; no underlying exception or source details."""


_NOTICE_CODES = frozenset({
    "invalid_settings", "local_unavailable", "cloud_unavailable", "superseded",
    "global_pending_limit", "watch_pending_limit", "global_size_limit",
    "watch_size_limit", "resource_unavailable", "queue_full", "analysis_failed",
    "queue_unavailable", "self_event_held", "recovery_required",
    "global_concurrency_limit", "watch_concurrency_limit", "failure_backoff", "cooldown",
})
_FAILURE_CODES = _NOTICE_CODES | {"source_changed", "timeout", "invalid_outcome"}
_INFERENCE_FAILURES = frozenset({
    "analysis_failed", "timeout", "invalid_outcome", "local_unavailable", "cloud_unavailable",
})
_CANCELLABLE = frozenset({ReviewItemState.PENDING, ReviewItemState.ANALYZING,
    ReviewItemState.AWAITING_APPROVAL, ReviewItemState.FAILED})
_IGNORABLE = _CANCELLABLE | {ReviewItemState.CANCELLED}


class ManagedWatchResults(QObject):
    MAX_NOTICES = 1000

    def __init__(self, *, queue, resource_guard, on_changed=None, on_published=None, parent=None):
        # No contributor registration or delivery mutation before validation.
        if (type(queue) is not ReviewQueue or type(resource_guard) is not WatchResourceGuard
                or (on_changed is not None and not callable(on_changed))
                or (on_published is not None and not callable(on_published))):
            raise ManagedWatchResultsError("invalid_managed_watch_results")
        super().__init__(parent)
        self._ident = threading.get_ident()
        self._queue, self._guard, self._changed = queue, resource_guard, on_changed
        self._published = on_published
        self._source_id = "managed-watch-results-" + uuid4().hex
        self._delivery = None
        self._closed = False
        self._available, self._error = True, ""
        self._depth = 0
        self._notices = {}
        self._require_owner()
        try:
            self._publish_counts()
        except Exception:
            self._fail_store()

    def _require_owner(self):
        if threading.get_ident() != self._ident or not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")

    @staticmethod
    def _require_id(value):
        if type(value) is not str or not value:
            raise ManagedWatchResultsError("invalid_managed_watch_results")

    def _require_action(self):
        self._require_owner()
        if not self._available:
            raise ManagedWatchResultsError("queue_unavailable")
        if self._closed:
            raise ManagedWatchResultsError("invalid_managed_watch_results")

    def _publish_counts(self):
        counts = {}
        for item in self._queue.items(states=ACTIVE_STATES):
            counts[item.watch_id] = counts.get(item.watch_id, 0) + 1
        snapshot = MappingProxyType(counts)
        total = sum(counts.values())
        self._guard.register_pending_source(self._source_id,
            per_watch_counter=lambda watch_id, saved=snapshot: saved.get(watch_id, 0),
            global_counter=lambda saved=total: saved)

    def _fail_store(self):
        self._available, self._error = False, "queue_unavailable"
        def unavailable(*args):
            raise ValueError("resource_unavailable")
        self._guard.register_pending_source(self._source_id,
            per_watch_counter=unavailable, global_counter=unavailable)
        raise ManagedWatchResultsError("queue_unavailable") from None

    def _write(self, item, *, add=False):
        try:
            saved = self._queue.add(item) if add else self._queue.update(item)
            self._publish_counts()
            return saved
        except Exception:
            self._fail_store()

    def _notify(self):
        if self._changed is not None:
            self._changed()

    def _replace_for_file_operation(self, changes, *, notify=False):
        """Owner-only atomic metadata transition, including committed close tails."""
        self._require_owner()
        if not self._available:
            raise ManagedWatchResultsError("queue_unavailable")
        self._depth += 1
        try:
            try:
                saved = self._queue.replace_many(changes)
            except ReviewQueueError as error:
                if str(error) == "review queue conflict":
                    raise
                self._fail_store()
            except Exception:
                self._fail_store()
            try:
                self._publish_counts()
            except Exception:
                self._fail_store()
            # Notification failures never turn a successful durable write into
            # a store failure. New actions select their final notify boundary.
            if notify:
                self._notify()
            return saved
        finally:
            self._depth -= 1

    def attach_delivery(self, delivery):
        self._require_action()
        callback = getattr(delivery, "_consume", None) if isinstance(delivery, ManagedWatchAnalysisDelivery) else None
        if (self._delivery is not None or not isinstance(delivery, ManagedWatchAnalysisDelivery)
                or delivery._ident != self._ident or delivery.thread() != self.thread()
                or delivery._resource_guard is not self._guard
                or type(callback) is not MethodType
                or getattr(callback, "__self__", None) is not self
                or getattr(callback, "__func__", None) is not ManagedWatchResults.consume_result
                or delivery._closed or delivery._owners or not delivery.ingress.workers_idle):
            raise ManagedWatchResultsError("invalid_managed_watch_results")
        self._delivery = delivery

    def _withdraw(self, item):
        if item is not None:
            current = self._queue.get(item.id)
            if current is not None and current.state in _CANCELLABLE:
                self._write(current.with_state(ReviewItemState.CANCELLED, error_category="superseded"))

    def consume_result(self, result):
        self._require_owner()
        delivery = self._delivery
        if self._closed or not self._available or delivery is None or not delivery.claim_result(result):
            return
        self._depth += 1
        try:
            event = result.event
            if type(event) is WatchAdmissionFailure:
                reason = result.failure if type(result.failure) is str and result.failure in _NOTICE_CODES else "analysis_failed"
                self._notices.pop(event.watch_id, None)
                if len(self._notices) >= self.MAX_NOTICES:
                    self._notices.pop(next(iter(self._notices)))
                self._notices[event.watch_id] = reason
                self._notify()
                return
            if type(event) is not StableWatchEvent:
                return
            work, watch_id = event.admission.work, event.admission.watch_id
            created = None
            try:
                existing = self._queue.active_for_path(watch_id, work.source_path)
            except Exception:
                self._fail_store()
            if existing is None:
                success = result.outcome is not None and result.metadata is not None and result.failure == ""
                reason = result.failure if type(result.failure) is str and result.failure in _FAILURE_CODES else "invalid_outcome"
                created = self._write(ReviewItem(
                    id="", watch_id=watch_id, source_path=work.source_path,
                    size_bytes=event.fingerprint.size_bytes, mtime_ns=event.fingerprint.mtime_ns,
                    extension=event.protected_extension,
                    display_name=os.path.splitext(os.path.basename(work.source_path))[0],
                    target_parent=event.target_dir,
                    state=ReviewItemState.AWAITING_APPROVAL if success else ReviewItemState.FAILED,
                    suggested_name=result.outcome.suggested_name if success else "",
                    confidence=None, managed_metadata=result.metadata if success else None,
                    content_kind=result.metadata.content_kind if success else "",
                    error_category="" if success else reason), add=True)
            if not delivery.is_publishing_result(result):
                self._withdraw(created)
                return
            self._notices.pop(watch_id, None)
            if result.outcome is not None and result.metadata is not None and result.failure == "":
                self._guard.note_success(watch_id)
            elif result.failure in _INFERENCE_FAILURES:
                self._guard.note_failure(watch_id)
            if not delivery.is_publishing_result(result):
                self._withdraw(created)
                return
            if (created is not None and created.state is ReviewItemState.AWAITING_APPROVAL
                    and self._published is not None):
                # Private ephemeral permission boundary. A refresh, restored row,
                # or deduplicated path cannot reconstruct genuine publication.
                self._published(result, created)
            self._notify()
        finally:
            self._depth -= 1

    def items(self, watch_id=None):
        self._require_owner()
        if watch_id is not None:
            self._require_id(watch_id)
        return self._queue.items(watch_id=watch_id)

    def item(self, item_id):
        self._require_owner()
        self._require_id(item_id)
        return self._queue.get(item_id)

    def notice(self, watch_id):
        self._require_owner()
        self._require_id(watch_id)
        return self._notices.get(watch_id, "")

    def publish_notice(self, watch_id, reason):
        self._require_owner()
        self._require_id(watch_id)
        if self._closed: return
        safe = reason if type(reason) is str and reason in _NOTICE_CODES else "resource_unavailable"
        if self._notices.get(watch_id) == safe: return
        self._depth += 1
        try:
            if len(self._notices) >= self.MAX_NOTICES and watch_id not in self._notices:
                self._notices.pop(next(iter(self._notices)))
            self._notices[watch_id] = safe
            self._notify()
        finally: self._depth -= 1

    def ignore(self, item_id):
        self._require_action()
        self._require_id(item_id)
        self._depth += 1
        try:
            item = self._queue.get(item_id)
            if item is not None and item.state in _IGNORABLE:
                item = self._write(item.with_state(ReviewItemState.IGNORED))
                self._notify()
            return item
        finally:
            self._depth -= 1

    def cancel_watch(self, watch_id):
        self._require_action()
        self._require_id(watch_id)
        self._depth += 1
        try:
            for item in self._queue.items(watch_id=watch_id):
                if item.state in _CANCELLABLE:
                    self._write(item.with_state(ReviewItemState.CANCELLED))
            self._notify()
        finally:
            self._depth -= 1

    def restore_interrupted(self):
        self._require_action()
        if self._delivery is not None:
            raise ManagedWatchResultsError("invalid_managed_watch_results")
        self._depth += 1
        try:
            recovered = 0
            for item in self._queue.items():
                if item.state in {ReviewItemState.PENDING, ReviewItemState.ANALYZING}:
                    self._write(item.with_state(ReviewItemState.CANCELLED, error_category="interrupted"))
                    recovered += 1
            self._notify()
            return recovered
        finally:
            self._depth -= 1

    def begin_close(self):
        self._require_owner()
        self._closed = True

    @property
    def available(self):
        self._require_owner()
        return self._available

    @property
    def error(self):
        self._require_owner()
        return self._error

    @property
    def workers_idle(self):
        self._require_owner()
        return self._depth == 0
