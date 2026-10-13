"""Bounded Watch analysis owner; no production activation or file operations."""
from __future__ import annotations
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
import math
import os
import stat
import threading
import time
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer, QCoreApplication
from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.batch_analysis import BatchAnalysisService, BatchAnalysisError
from src.core.processing_analysis import AnalysisOutcome, CloudAnalysisCoverage
from src.core.processing_authority import (
    ProcessingMode, ProcessingSuperseded, LocalProcessingUnavailable, CloudDispatchBlocked,
)
from src.core.watch_work import StableWatchEvent, WatchAdmissionFailure
from src.core.managed_watch_metadata import metadata_from_outcome
from src.core.rename_plan import SourceFingerprint
from src.core.filename_validator import validate_filename
from src.core.watch_resource_guard import WatchResourceGuard
from src.services.local_ai.preparation_protocol import PreparationCoverage


@dataclass(frozen=True)
class ManagedWatchAnalysisResult:
    event: object = field(repr=False)
    outcome: AnalysisOutcome | None = field(default=None, repr=False)
    metadata: object = None
    failure: str = ""


@dataclass(eq=False)
class _Owner:
    event: StableWatchEvent | WatchAdmissionFailure
    future: object = None
    bridge_done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    issued: object = None
    acked: bool = False
    in_callback: bool = False
    published_result: object = None
    result_claimed: bool = False
    execution_owned: bool = False
    admitting: bool = False
    blocked_reason: str = ""


@dataclass(frozen=True)
class _Completion:
    owner: _Owner = field(repr=False)
    outcome: object = field(default=None, repr=False)
    failure: str = ""


class ManagedWatchAnalysisDelivery(QObject):
    _incoming = Signal(object)
    _completed = Signal(object)

    def __init__(self, service, authority, *, capture_guard, is_binding_current,
                 on_result, max_workers=2, pending_limit=1000, can_start=None,
                 resource_guard=None, on_resource_blocked=None):
        super().__init__()
        if resource_guard is not None and type(resource_guard) is not WatchResourceGuard:
            raise ValueError("invalid_watch_resource_guard")
        if resource_guard is not None and not callable(on_resource_blocked):
            raise TypeError("invalid_managed_watch_resource_observer")
        if can_start is not None and not callable(can_start):
            raise TypeError("invalid_managed_watch_start_predicate")
        if (not isinstance(service, BatchAnalysisService) or not service._managed
                or service._authority is not authority
                or not callable(capture_guard) or not callable(is_binding_current)
                or not callable(on_result) or type(max_workers) is not int
                or not 1 <= max_workers <= 2 or type(pending_limit) is not int
                or not 1 <= pending_limit <= 1000):
            raise ValueError("invalid_managed_watch_owner")
        self._ident = threading.get_ident()
        self._service, self._authority = service, authority
        self._binding, self._consume = is_binding_current, on_result
        self._can_start = can_start
        self._resource_guard, self._resource_blocked = resource_guard, on_resource_blocked
        self._max_workers = max_workers
        self._closed = self._publication_failed = self._pumping = False
        self._callbacks = 0
        self._queued, self._owners = [], {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._incoming.connect(self._accept_event, Qt.QueuedConnection)
        self._completed.connect(self._accept_completion, Qt.QueuedConnection)
        self.ingress = ManagedWatchIngress(service, authority, capture_guard=capture_guard,
            post_event=self._incoming.emit, resource_guard=resource_guard)
        self.ingress.MAX_OWNED = pending_limit
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self.poll)
        self._timer.start()

    def _require_owner(self):
        if threading.get_ident() != self._ident or not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")

    def _current(self, event):
        if self._closed or not self.ingress.is_current(event):
            return False
        try:
            bound = self._binding(event) is True
        except Exception:
            bound = False
        return bound and not self._closed and self.ingress.is_current(event)

    @Slot(object)
    def _accept_event(self, event):
        self._require_owner()
        # Duplicate delivery must not withdraw a live worker or reentrant callback.
        # Its original owner alone retires the ingress after the acknowledged tail.
        if id(event) in self._owners:
            return
        if not self.ingress.is_current(event):
            self.ingress.retire(event)
            return
        current = self._current(event)
        # The binding predicate can pump Qt and install this exact owner in
        # nested intake. Its lifetime wins even if the outer check went stale.
        if id(event) in self._owners:
            return
        if not current:
            self.ingress.retire(event)
            return
        if type(event) is WatchAdmissionFailure:
            safe = event.reason if event.reason in {
                "invalid_settings", "local_unavailable", "cloud_unavailable", "superseded",
                "global_pending_limit", "watch_pending_limit", "global_size_limit",
                "watch_size_limit", "resource_unavailable", "queue_full"
            } else "analysis_failed"
            owner = _Owner(event)
            self._owners[id(event)] = owner
            owner.bridge_done.set()  # No worker is submitted for an admitted failure.
            owner.in_callback = True
            try:
                self._deliver(ManagedWatchAnalysisResult(event, failure=safe))
            finally:
                owner.acked = True
                owner.in_callback = False
                self.poll()
            return
        if type(event) is not StableWatchEvent:
            self.ingress.retire(event)
            return
        if id(event) in self._owners:
            return
        owner = _Owner(event)
        self._owners[id(event)] = owner
        self._queued.append(owner)
        self.poll()

    @staticmethod
    def _fingerprint(path):
        value = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("source_changed")
        return SourceFingerprint(value.st_size, value.st_mtime_ns)

    @classmethod
    def _run(cls, service, owner):
        event, work = owner.event, owner.event.admission.work
        try:
            if cls._fingerprint(work.source_path) != event.fingerprint:
                return _Completion(owner, failure="source_changed")
            outcome = service.run_prepared(work)
            if cls._fingerprint(work.source_path) != event.fingerprint:
                return _Completion(owner, failure="source_changed")
            return _Completion(owner, outcome=outcome)
        except (ProcessingSuperseded, CancelledError):
            return _Completion(owner, failure="superseded")
        except LocalProcessingUnavailable:
            return _Completion(owner, failure="local_unavailable")
        except CloudDispatchBlocked:
            return _Completion(owner, failure="cloud_unavailable")
        except (OSError, ValueError):
            return _Completion(owner, failure="source_changed")
        except Exception as error:
            reason = "analysis_failed"
            if isinstance(error, BatchAnalysisError):
                if str(error) in {"Local analysis timed out", "Cloud analysis queue timed out"}:
                    reason = "timeout"
                elif str(error) in {"Local analysis queue is full", "Cloud analysis queue is full"}:
                    reason = "queue_full"
            return _Completion(owner, failure=reason)

    def _emit(self, owner, future):
        try:
            try:
                completion = future.result()
            except BaseException:
                completion = _Completion(owner, failure="analysis_failed")
            with owner.lock:
                owner.issued = completion
            self._completed.emit(completion)
        finally:
            # No worker Qt call after this final synchronized tail fact.
            owner.bridge_done.set()

    def _prune(self):
        for key, owner in tuple(self._owners.items()):
            if (owner.acked and not owner.in_callback and not owner.admitting
                    and owner.bridge_done.is_set()
                    and (owner.future is None or owner.future.done())):
                if not self._release_execution(owner):
                    continue
                self.ingress.retire(owner.event)
                self._owners.pop(key, None)

    def _release_execution(self, owner):
        # A denied stale acquisition can still retain a receipt when cleanup
        # refused. Inspect actual ingress ownership, never the permission bit.
        owner.execution_owned = self.ingress.has_execution(owner.event)
        if owner.execution_owned:
            if not self.ingress.release_execution(owner.event):
                return False
            owner.execution_owned = False
        return True

    def _retire_unsubmitted(self, owner):
        owner.acked = True
        owner.bridge_done.set()
        self._prune()

    def _sealed_current(self, owner):
        return (not self._closed and self._owners.get(id(owner.event)) is owner
                and self.ingress.is_current(owner.event))

    def _ready(self, owner):
        if self._can_start is None:
            return True
        try:
            return self._can_start(owner.event) is True
        except Exception:
            return False

    def _queue_completion(self, owner, failure):
        completion = _Completion(owner, failure=failure)
        with owner.lock:
            owner.issued = completion
        try:
            self._completed.emit(completion)
        finally:
            # Even without a Future, retain the real emission/Qt ack bridge.
            owner.bridge_done.set()

    def _guarded_ready(self, owner):
        """One bounded admission attempt, including external observer tails."""
        owner.admitting = True
        hold = False
        try:
            if not self._current(owner.event) or not self._sealed_current(owner):
                self._retire_unsubmitted(owner)
                return False
            # Retry refused cleanup even while readiness remains HELD. This
            # retained ownership can never serve as this pass's permission.
            if not self._release_execution(owner):
                hold = True
                return False
            ready = self._ready(owner)
            if not self._sealed_current(owner) or not self._current(owner.event):
                self._retire_unsubmitted(owner)
                return False
            if not ready:
                hold = True
                return False
            try:
                decision = self.ingress.try_acquire_execution(owner.event)
            except Exception:
                self._queue_completion(owner, "analysis_failed")
                return False
            owner.execution_owned = self.ingress.has_execution(owner.event)
            if not self._sealed_current(owner):
                self._retire_unsubmitted(owner)
                return False
            if decision.allowed and owner.execution_owned:
                owner.blocked_reason = ""
                # Refresh binding before the final trusted readiness query;
                # after that query only sealed facts may revoke permission.
                if not self._current(owner.event) or not self._sealed_current(owner):
                    self._retire_unsubmitted(owner)
                    return False
                ready = self._ready(owner)
                if not self._sealed_current(owner):
                    self._retire_unsubmitted(owner)
                    return False
                if not ready:
                    self._release_execution(owner)
                    hold = True
                    return False
                return True
            reason = decision.reason
            if reason in {
                "global_pending_limit", "watch_pending_limit", "global_concurrency_limit",
                "watch_concurrency_limit", "manually_paused", "failure_backoff",
                "cooldown", "resource_unavailable"
            }:
                if owner.blocked_reason != reason:
                    owner.blocked_reason = reason
                    self._callbacks += 1
                    try:
                        self._resource_blocked(owner.event, reason)
                    except Exception:
                        self._publication_failed = True
                        self.begin_close()
                    finally:
                        self._callbacks -= 1
                if not self._sealed_current(owner):
                    self._retire_unsubmitted(owner)
                else:
                    hold = True
                return False
            self._queue_completion(owner, reason if reason in {
                "global_size_limit", "watch_size_limit"
            } else "analysis_failed")
            return False
        finally:
            owner.admitting = False
            if (owner.future is None and owner.issued is None
                    and not self._sealed_current(owner)):
                self._retire_unsubmitted(owner)
            elif hold and not owner.acked:
                self._queued.append(owner)
            self._prune()

    @Slot()
    def poll(self):
        self._require_owner()
        if self._pumping:
            return
        self._pumping = True
        try:
            self._prune()
            if self._closed:
                if not self._owners and self.ingress.workers_idle and not self._callbacks:
                    self._timer.stop()
                return
            running = sum(owner.future is not None or owner.issued is not None
                          for owner in self._owners.values())
            attempts = len(self._queued)
            while self._queued and running < self._max_workers and attempts:
                attempts -= 1
                owner = self._queued.pop(0)
                if self._resource_guard is not None:
                    if not self._guarded_ready(owner):
                        continue
                    self._submit(owner)
                    running += 1
                    continue
                current = self._current(owner.event)
                # Fallible/reentrant predicates may withdraw this exact owner.
                if self._closed or self._owners.get(id(owner.event)) is not owner:
                    continue
                if not current:
                    self.ingress.retire(owner.event)
                    self._owners.pop(id(owner.event), None)
                    continue
                if self._can_start is not None:
                    try:
                        allowed = self._can_start(owner.event) is True
                    except Exception:
                        allowed = False
                    if self._closed or self._owners.get(id(owner.event)) is not owner:
                        continue
                    current = self._current(owner.event)
                    if self._closed or self._owners.get(id(owner.event)) is not owner:
                        continue
                    if not current:
                        self.ingress.retire(owner.event)
                        self._owners.pop(id(owner.event), None)
                        continue
                    if not allowed:
                        self._queued.append(owner)
                        continue
                    # The last binding callback may have changed READY to HELD
                    # without cancelling this authentic work. Refresh readiness
                    # once, then check only sealed ingress/owner facts: another
                    # arbitrary binding callback could stale this permission too.
                    try:
                        allowed = self._can_start(owner.event) is True
                    except Exception:
                        allowed = False
                    if self._closed or self._owners.get(id(owner.event)) is not owner:
                        continue
                    if not self.ingress.is_current(owner.event):
                        self.ingress.retire(owner.event)
                        self._owners.pop(id(owner.event), None)
                        continue
                    if not allowed:
                        self._queued.append(owner)
                        continue
                self._submit(owner)
                running += 1
        finally:
            self._pumping = False

    def _submit(self, owner):
        try:
            owner.future = self._pool.submit(self._run, self._service, owner)
        except Exception:
            self._queue_completion(owner, "analysis_failed")
        else:
            owner.future.add_done_callback(lambda done, owned=owner: self._emit(owned, done))

    def _deliver(self, result):
        self._callbacks += 1
        try:
            if self._current(result.event):
                owner = self._owners.get(id(result.event))
                if (owner is not None and owner.event is result.event
                        and owner.in_callback and owner.published_result is None):
                    owner.published_result = result
                    owner.result_claimed = False
                    try:
                        self._consume(result)
                    finally:
                        owner.published_result = None
        except Exception:
            self._publication_failed = True
            self.begin_close()
        finally:
            self._callbacks -= 1

    def is_publishing_result(self, result):
        self._require_owner()
        if type(result) is not ManagedWatchAnalysisResult or self._closed:
            return False
        owner = self._owners.get(id(result.event))
        return (owner is not None and owner.event is result.event
                and owner.in_callback and owner.published_result is result
                and self.ingress.is_current(owner.event))

    def claim_result(self, result):
        if not self.is_publishing_result(result):
            return False
        owner = self._owners[id(result.event)]
        if owner.result_claimed:
            return False
        owner.result_claimed = True
        return True

    @Slot(object)
    def _accept_completion(self, completion):
        self._require_owner()
        if type(completion) is not _Completion:
            return
        owner = completion.owner
        if self._owners.get(id(owner.event)) is not owner or owner.acked or owner.in_callback:
            return
        with owner.lock:
            if owner.issued is not completion:
                return
        owner.in_callback = True
        try:
            if not self._current(owner.event):
                return
            work, outcome = owner.event.admission.work, completion.outcome
            metadata, failure = None, completion.failure
            if type(failure) is not str or failure not in {
                "", "source_changed", "superseded", "local_unavailable",
                "cloud_unavailable", "analysis_failed", "timeout", "queue_full",
                "global_size_limit", "watch_size_limit"
            } or (outcome is None and not failure) or (outcome is not None and failure):
                outcome, failure = None, "invalid_outcome"
            if outcome is not None:
                try:
                    expected = PreparationCoverage if work.context.mode is ProcessingMode.LOCAL else CloudAnalysisCoverage
                    if (type(outcome) is not AnalysisOutcome or outcome.context is not work.context
                            or type(outcome.coverage) is not expected
                            or type(outcome.suggested_name) is not str):
                        raise ValueError("invalid_outcome")
                    parts = outcome.suggested_name.split("/")
                    if (not parts or any(not validate_filename(p).is_valid for p in parts[:-1])
                            or not validate_filename(parts[-1], owner.event.protected_extension).is_valid):
                        raise ValueError("invalid_outcome")
                    metadata = metadata_from_outcome(outcome, work.settings.quality_mode)
                except Exception:
                    outcome, metadata, failure = None, None, "invalid_outcome"
            self._deliver(ManagedWatchAnalysisResult(owner.event, outcome, metadata, failure))
        finally:
            owner.acked = True
            owner.in_callback = False
            self.poll()

    @property
    def owned_count(self):
        self._require_owner()
        self._prune()
        return self.ingress.owned_count

    @property
    def workers_idle(self):
        self._require_owner()
        self._prune()
        return not self._owners and self.ingress.workers_idle and not self._callbacks

    @property
    def publication_failed(self):
        self._require_owner()
        return self._publication_failed

    def begin_close(self):
        self._require_owner()
        if self._closed:
            return
        self._closed = True
        self.ingress.begin_close()
        # A scheduling predicate may close us after its owner was popped from
        # the queue. Retire only genuinely unsubmitted stable work; submitted
        # Futures, issued completions and admitted-failure callbacks keep their
        # existing acknowledgement/emission-tail ownership.
        for owner in tuple(self._owners.values()):
            if (type(owner.event) is StableWatchEvent and owner.future is None
                    and owner.issued is None and not owner.in_callback and not owner.admitting):
                self._retire_unsubmitted(owner)
        self._queued.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.poll()

    def drain(self, deadline):
        self._require_owner()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or deadline - time.monotonic() > 30):
            raise ValueError("invalid_watch_drain_deadline")
        while time.monotonic() < deadline:
            self.poll()
            if self.workers_idle:
                return True
            QCoreApplication.processEvents()
            time.sleep(0.005)
        return self.workers_idle
