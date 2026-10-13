"""Plain Python, bounded authentic admission and private queued-delivery owner.

No observers, Qt, pool, source I/O, inference or file operations belong here.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from threading import Event, Lock
from uuid import uuid4

from src.core.batch_analysis import BatchAnalysisError
from src.core.processing_authority import (
    CloudDispatchBlocked, LocalProcessingUnavailable, ProcessingSuperseded,
)
from src.core.rename_plan import SourceFingerprint
from src.core.smart_naming import SmartNamingError
from src.core.watch_resource_guard import (
    R_GLOBAL_PENDING, R_GLOBAL_SIZE, R_RESOURCE_UNAVAILABLE, R_WATCH_PENDING,
    R_WATCH_SIZE, R_INVALID_OWNER, ResourceDecision, WatchResourceGuard,
)
from src.core.watch_work import (
    StableWatchEvent, WatchAdmission, WatchAdmissionFailure, valid_admission_fields,
)


@dataclass
class _Owned:
    cancel: Event
    watch_id: str
    incarnation: str
    event: object = None
    capturing: bool = True
    posting: bool = False
    delivered: bool = False
    retired: bool = False
    pending_token: object = None
    resource_notice: bool = False
    execution_token: object = None
    resource_call: bool = False


class ManagedWatchIngress:
    MAX_OWNED = 1000
    MAX_RESOURCE_NOTICES = 1000

    def __init__(self, service, authority, *, capture_guard, post_event,
                 resource_guard=None):
        if resource_guard is not None and type(resource_guard) is not WatchResourceGuard:
            raise ValueError("invalid_watch_resource_guard")
        self._service = service
        self._authority = authority
        self._capture_guard = capture_guard
        self._post_event = post_event
        self._resource_guard = resource_guard
        self._resource_notices = {}
        self._open = True
        self._owned = {}
        self._issued = {}
        self._lock = Lock()

    def _normal_count_locked(self):
        return sum(not owner.resource_notice for owner in self._owned.values())

    def _mark_resource_notice_locked(self, key, owner):
        notice_key = (owner.watch_id, owner.incarnation)
        if (notice_key in self._resource_notices
                or len(self._resource_notices) >= self.MAX_RESOURCE_NOTICES):
            owner.retired = True
            owner.cancel.set()
            return False
        owner.resource_notice = True
        self._resource_notices[notice_key] = key
        return True

    def _prune_locked(self, key, owner):
        if not (owner.retired and not owner.capturing and not owner.posting
                and not owner.resource_call and owner.execution_token is None):
            return
        if owner.pending_token is not None:
            # Canonical primitive release has no clock/contributor callbacks.
            if not self._resource_guard.release_pending(owner.pending_token):
                return
            owner.pending_token = None
        self._owned.pop(key, None)
        notice_key = (owner.watch_id, owner.incarnation)
        if self._resource_notices.get(notice_key) is key:
            self._resource_notices.pop(notice_key, None)
        if owner.event is not None:
            self._issued.pop(id(owner.event), None)

    def _find_locked(self, event):
        pair = self._issued.get(id(event))
        if pair is None or pair[1].event is not event or pair[1].retired:
            return None
        return pair

    def capture(self, config, incarnation, source_path, event_id):
        if not valid_admission_fields(config, incarnation, source_path, event_id):
            return None
        key, cancel = object(), Event()
        owner = _Owned(cancel, config.id, incarnation)
        notice_reason = ""
        with self._lock:
            if not self._open:
                return None
            full = self._normal_count_locked() >= self.MAX_OWNED
            if full and self._resource_guard is None:
                return None
            self._owned[key] = owner
            if full:
                if not self._mark_resource_notice_locked(key, owner):
                    owner.capturing = False
                    self._prune_locked(key, owner)
                    return None
                notice_reason = "queue_full"
        event = None
        try:
            if self._resource_guard is not None and not notice_reason:
                # The prospective owner stays capturing across guard callbacks.
                decision, receipt = self._resource_guard.reserve_pending(config.id, 0)
                with self._lock:
                    owner.pending_token = receipt
                    if not self._open or owner.retired:
                        owner.retired = True
                        cancel.set()
                        return None
                    if not decision.allowed:
                        if not self._mark_resource_notice_locked(key, owner):
                            return None
                        allowed_reasons = {
                            R_GLOBAL_PENDING, R_WATCH_PENDING, R_GLOBAL_SIZE,
                            R_WATCH_SIZE, R_RESOURCE_UNAVAILABLE,
                        }
                        notice_reason = (decision.reason if decision.reason in allowed_reasons
                                         else R_RESOURCE_UNAVAILABLE)
            with self._capture_guard():
                snapshot = self._authority.snapshot()
                if notice_reason:
                    event = WatchAdmissionFailure(snapshot, config.id, config,
                        incarnation, event_id, notice_reason)
                else:
                    try:
                        work = self._service.capture_work(source_path, event_id,
                            task_attempt_id=uuid4().hex, task_cancel_event=cancel,
                            template_id=config.template_id, output_language="",
                            naming_mode="template", defer_execution_deadline=True)
                    except (LocalProcessingUnavailable, CloudDispatchBlocked,
                            ProcessingSuperseded, BatchAnalysisError,
                            SmartNamingError, ValueError, TypeError) as error:
                        reason = "invalid_settings"
                        if isinstance(error, LocalProcessingUnavailable):
                            reason = "local_unavailable"
                        elif isinstance(error, CloudDispatchBlocked):
                            reason = "cloud_unavailable"
                        elif isinstance(error, ProcessingSuperseded):
                            reason = "superseded"
                        event = WatchAdmissionFailure(snapshot, config.id,
                            config, incarnation, event_id, reason)
                    else:
                        event = WatchAdmission(work, config.id, config,
                            incarnation, event_id, cancel)
            with self._lock:
                if not self._open or owner.retired:
                    owner.retired = True
                    cancel.set()
                    return None
                owner.event = event
                self._issued[id(event)] = (key, owner)
                return event
        finally:
            with self._lock:
                owner.capturing = False
                if event is None:
                    owner.retired = True
                    cancel.set()
                self._prune_locked(key, owner)

    def _current_locked(self, owner):
        if not self._open or owner.retired or owner.cancel.is_set():
            return False
        event = owner.event
        if type(event) is StableWatchEvent:
            event = event.admission
        if type(event) is WatchAdmission:
            return self._authority.is_current(event.work.context)
        if type(event) is WatchAdmissionFailure:
            current = self._authority.snapshot()
            return (event.snapshot.session_id, event.snapshot.generation, event.snapshot.mode) == (
                current.session_id, current.generation, current.mode)
        return False

    def is_current(self, event):
        with self._lock:
            pair = self._find_locked(event)
            return pair is not None and self._current_locked(pair[1])

    def post_stable(self, admission, fingerprint):
        if (type(admission) is not WatchAdmission or type(fingerprint) is not SourceFingerprint
                or type(fingerprint.size_bytes) is not int or fingerprint.size_bytes <= 0
                or type(fingerprint.mtime_ns) is not int or fingerprint.mtime_ns < 0):
            return False
        extension = os.path.splitext(admission.work.source_path)[1]
        if len(extension) > 256:
            return False
        delivery = StableWatchEvent(admission, fingerprint, extension,
            admission.watch_config.target_dir or os.path.dirname(admission.work.source_path), object())
        return self._post(admission, delivery)

    def post_failure(self, failure):
        """Publish the exact snapshot-scoped failure; never recapture or promote it."""
        if type(failure) is not WatchAdmissionFailure:
            return False
        return self._post(failure, failure)

    def _post(self, admission, delivery):
        with self._lock:
            pair = self._find_locked(admission)
            if pair is None:
                return False
            key, owner = pair
            if owner.delivered or not self._current_locked(owner):
                return False
            self._issued.pop(id(admission), None)
            owner.event = delivery
            owner.delivered = owner.posting = True
            self._issued[id(delivery)] = pair
        try:
            self._post_event(delivery)
            return True
        except Exception:
            self.retire(delivery)
            return False
        finally:
            with self._lock:
                owner.posting = False
                self._prune_locked(key, owner)

    def retire(self, event):
        with self._lock:
            pair = self._find_locked(event)
            if pair is None:
                return False
            key, owner = pair
            owner.retired = True
            owner.cancel.set()
            self._prune_locked(key, owner)
            return True

    def try_acquire_execution(self, event):
        """Observe resources outside our lock; seal a receipt on the exact owner."""
        if type(event) is not StableWatchEvent:
            return ResourceDecision(False, R_INVALID_OWNER)
        with self._lock:
            pair = self._find_locked(event)
            if pair is None or not self._current_locked(pair[1]):
                return ResourceDecision(False, R_INVALID_OWNER)
            guard = self._resource_guard
            if guard is None:
                return ResourceDecision(False, R_RESOURCE_UNAVAILABLE)
            key, owner = pair
            if (owner.resource_call or owner.execution_token is not None
                    or owner.pending_token is None):
                return ResourceDecision(False, R_INVALID_OWNER)
            owner.resource_call = True
            pending = owner.pending_token
        decision, receipt = ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None
        try:
            decision, receipt = guard.try_acquire_owned_analysis(
                pending, event.fingerprint.size_bytes)
            if decision.allowed and receipt is None:
                decision = ResourceDecision(False, R_RESOURCE_UNAVAILABLE)
        finally:
            with self._lock:
                # Capture the receipt even when a clock/contributor withdrew us.
                if receipt is not None:
                    owner.execution_token = receipt
                owner.resource_call = False
                if not self._current_locked(owner):
                    owner.retired = True
                    owner.cancel.set()
                    if (owner.execution_token is not None
                            and guard.release_owned_analysis(owner.execution_token)):
                        owner.execution_token = None
                    decision = ResourceDecision(False, R_INVALID_OWNER)
                self._prune_locked(key, owner)
        return decision

    def release_execution(self, event):
        """Cleanup accepts only the original issued identity, including retired work."""
        with self._lock:
            pair = self._issued.get(id(event))
            if pair is None or pair[1].event is not event:
                return False
            key, owner = pair
            receipt = owner.execution_token
            if receipt is None or not self._resource_guard.release_owned_analysis(receipt):
                return False
            owner.execution_token = None
            self._prune_locked(key, owner)
            return True

    def has_execution(self, event):
        """Ownership observation is not an execution permission."""
        with self._lock:
            pair = self._issued.get(id(event))
            return (pair is not None and pair[1].event is event
                    and pair[1].execution_token is not None)

    def begin_close(self):
        with self._lock:
            self._open = False
            for key, owner in list(self._owned.items()):
                owner.cancel.set()
                if not owner.delivered:
                    owner.retired = True
                    self._prune_locked(key, owner)

    def cancel_incarnation(self, watch_id, incarnation):
        """Cancel only this installation; queued delivery owners await consumption."""
        with self._lock:
            for key, owner in list(self._owned.items()):
                if owner.watch_id == watch_id and owner.incarnation == incarnation:
                    owner.cancel.set()
                    if not owner.delivered:
                        owner.retired = True
                        self._prune_locked(key, owner)

    @property
    def owned_count(self):
        with self._lock:
            for key, owner in tuple(self._owned.items()):
                self._prune_locked(key, owner)
            return len(self._owned)

    @property
    def workers_idle(self):
        return self.owned_count == 0
