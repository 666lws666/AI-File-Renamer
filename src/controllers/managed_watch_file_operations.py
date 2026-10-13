"""Explicit managed Watch approvals; only the borrowed serial lane moves files.

Durable intents are crash evidence, not startup authority. Public lane envelopes
are accepted only during the lane's exact synchronous owner-thread publication.
"""
from dataclasses import dataclass, field, replace
import os
import threading
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Slot

from src.controllers.managed_file_operation_lane import (
    FileOperationCompletion, FileOperationProgress, ManagedFileOperationLane,
)
from src.controllers.managed_watch_results import ManagedWatchResults
from src.core.filename_validator import validate_filename
from src.core.rename_plan import RenamePlan, SourceFingerprint, RECOVERY_REASONS, validate_owned_residue_paths
from src.core.watch_review_queue import (
    ReviewItemState, WatchFileOperationIntent,
    _encode_intent,
)
from src.services.file_operation_backend import (FileOperationOutcome, FileOperationRequest, _string,
                                                validate_outcome_evidence)


@dataclass(eq=False)
class _Owner:
    reservation: object
    originals: tuple
    saved: tuple
    received: set = field(default_factory=set)


class ManagedWatchFileOperations(QObject):
    def __init__(self, *, results, lane, parent=None):
        if type(results) is not ManagedWatchResults or type(lane) is not ManagedFileOperationLane:
            raise ValueError("invalid_watch_file_operations")
        results._require_owner()
        lane._require_owner()
        super().__init__(parent)
        if self.thread() != lane.thread() or self.thread() != results.thread():
            raise RuntimeError("watch_owner_thread_required")
        self._ident = threading.get_ident()
        self._results, self._lane = results, lane
        self._owners, self._rows = {}, {}
        self._recovery_outcomes = {}
        self._closing = False
        self._available, self._error = True, ""
        self._action_depth, self._publication_depth = 0, 0
        self._started = False
        # The lane has already queued onto this owner. A second queued connection
        # would escape the actual publication/lifetime and is not authorized.
        lane.itemCompleted.connect(self._progress, Qt.ConnectionType.DirectConnection)
        lane.completed.connect(self._completion, Qt.ConnectionType.DirectConnection)

    def _require_owner(self):
        if threading.get_ident() != self._ident or not self.thread().isCurrentThread():
            raise RuntimeError("watch_owner_thread_required")

    def _can_admit(self):
        return (not self._closing and not self._results._closed
                and not self._action_depth and self.available)

    def _disable(self):
        self._available, self._error = False, "queue_unavailable"

    def _notify(self):
        # An observer exception is not a failed durable save. Keep a fixed code
        # and continue draining committed work without leaking the exception.
        self._results._depth += 1
        try:
            self._results._notify()
        except Exception:
            if self._available and self._results.available:
                self._error = "notification_failed"
        finally:
            self._results._depth -= 1

    @staticmethod
    def _fingerprint_valid(value):
        return (type(value) is SourceFingerprint
                and type(value.size_bytes) is int and value.size_bytes >= 0
                and type(value.mtime_ns) is int and value.mtime_ns >= 0)

    @staticmethod
    def _plan(item, batch):
        suggestion = item.suggested_name
        if not _string(suggestion, 4096):
            raise ValueError()
        components = suggestion.split("/")
        if (any(component in {"", ".", ".."} or "\x00" in component
                or not validate_filename(component).is_valid for component in components[:-1])
                or not validate_filename(components[-1], item.extension).is_valid
                or "\x00" in components[-1]):
            raise ValueError()
        parent = item.target_parent or os.path.dirname(item.source_path)
        parent = os.path.join(parent, *components[:-1])
        return RenamePlan(item.id, item.source_path,
            SourceFingerprint(item.size_bytes, item.mtime_ns), components[-1], parent,
            item.extension, batch)

    def apply(self, item_ids: tuple[str, ...]) -> bool:
        return self._apply(item_ids)

    def auto_apply(self, item_id: str, *, is_authorized) -> bool:
        """Ephemeral newly-published consent; never retained for replay."""
        self._require_owner()
        if not callable(is_authorized):
            return False
        try:
            if is_authorized() is not True:
                return False
        except Exception:
            return False
        return self._apply((item_id,), is_authorized=is_authorized)

    def _auto_row_current(self, original) -> bool:
        self._require_owner()
        current = self._results.item(original.id)
        if current is original:
            return original.state is ReviewItemState.AWAITING_APPROVAL
        owner = self._rows.get(original.id)
        return (owner is not None and any(before is original and after is current
            for before, after in zip(owner.originals, owner.saved)))

    def _apply(self, item_ids: tuple[str, ...], *, is_authorized=None) -> bool:
        self._require_owner()
        if (not self._can_admit() or type(item_ids) is not tuple
                or not 1 <= len(item_ids) <= 1000
                or any(not _string(value, 256) for value in item_ids)
                or len(set(item_ids)) != len(item_ids)):
            return False
        self._action_depth += 1
        try:
            rows = tuple(self._results.item(value) for value in item_ids)
            if any(row is None or row.state not in {
                    ReviewItemState.AWAITING_APPROVAL, ReviewItemState.UNDONE}
                    or row.file_operation is not None or row.recovery_required
                    or row.id in self._rows for row in rows):
                return False
            batch = "watch-batch-" + uuid4().hex
            try:
                plans = tuple(self._plan(row, batch) for row in rows)
                # Capture trusted ORIGINAL roots before template subdirectories;
                # the worker applies containment with these immutable approvals.
                roots = tuple(dict.fromkeys(root for row in rows for root in (
                    os.path.dirname(row.source_path),
                    row.target_parent or os.path.dirname(row.source_path))))
                request = FileOperationRequest(uuid4().hex, "apply", batch, plans, allowed_roots=roots)
                intents = tuple(WatchFileOperationIntent(1, request.operation_id, "apply", batch,
                    plan.source_path, plan.target_path) for plan in plans)
            except (ValueError, TypeError, AttributeError):
                return False
            return self._admit(request, rows, intents, is_authorized=is_authorized)
        finally:
            self._action_depth -= 1

    def undo(self, item_id: str) -> bool:
        self._require_owner()
        if not self._can_admit() or not _string(item_id, 256):
            return False
        self._action_depth += 1
        try:
            row = self._results.item(item_id)
            if (row is None or row.state is not ReviewItemState.APPLIED
                    or row.file_operation is not None or row.recovery_required
                    or row.id in self._rows or not _string(row.applied_path, 4096)
                    or not _string(row.batch_id, 256)):
                return False
            try:
                request = FileOperationRequest(uuid4().hex, "undo", task_ids=(row.id,))
                marker = WatchFileOperationIntent(1, request.operation_id, "undo", row.batch_id,
                                                  row.applied_path, row.source_path)
            except (ValueError, TypeError):
                return False
            return self._admit(request, (row,), (marker,))
        finally:
            self._action_depth -= 1

    def _admit(self, request, rows, intents, *, is_authorized=None):
        reservation = self._lane.reserve(request)
        if reservation is None:
            self._error = "queue_full"
            return False
        self._started = True
        owner = None
        try:
            changes = tuple((row, replace(row, state=ReviewItemState.APPLYING,
                file_operation=marker, error_category="", batch_id=marker.batch_id))
                for row, marker in zip(rows, intents))
            saved = self._results._replace_for_file_operation(changes)
            owner = _Owner(reservation, rows, saved)
            # Fallible timestamps/snapshot registration can reenter close or
            # mutate rows. No notification or file execution preceded this check.
            if (self._closing or self._results._closed or not self.available
                    or any(self._results.item(row.id) is not row for row in saved)
                    or any(row.id in self._rows for row in saved)):
                self._rollback(owner)
                return False
            self._owners[reservation] = owner
            for row in saved:
                self._rows[row.id] = owner
            # Durable timestamps/counter registration can reenter settings,
            # edit/remove or close. Compare only this exact own transition;
            # immediately recheck ephemeral permission before lane.commit.
            if is_authorized is not None and is_authorized() is not True:
                self._retire(owner)
                self._rollback(owner)
                return False
            if not self._lane.commit(reservation):
                self._retire(owner)
                self._rollback(owner)
                return False
        except Exception:
            if owner is not None:
                if self._lane.cancel(reservation):
                    self._retire(owner)
                    self._rollback(owner)
                elif self._owners.get(reservation) is owner:
                    # If commitment happened before a failing callback, retain
                    # its owner and drain real outcomes; never undo moved files.
                    self._disable()
            if not self._results.available:
                self._disable()
            return False
        finally:
            # Exact uncommitted reservations can be cancelled. The lane refuses
            # cancellation of committed work, including a UI close reentry.
            if owner is None or self._owners.get(reservation) is not owner:
                self._lane.cancel(reservation)
        self._notify()
        return True

    def _rollback(self, owner):
        self._lane.cancel(owner.reservation)
        changes = tuple((saved, original) for saved, original in zip(owner.saved, owner.originals)
                        if self._results.item(saved.id) is saved)
        if not changes:
            return
        try:
            self._results._replace_for_file_operation(changes)
        except Exception:
            self._disable()  # Intent remains durable evidence, never replay it.

    def _retire(self, owner):
        if self._owners.get(owner.reservation) is owner:
            del self._owners[owner.reservation]
        for row in owner.saved:
            if self._rows.get(row.id) is owner:
                del self._rows[row.id]

    @staticmethod
    def _same_path(left, right):
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))

    @classmethod
    def _destination_valid(cls, row, outcome):
        expected = row.file_operation.target_path
        actual = outcome.new_path
        if cls._same_path(actual, expected):
            return True
        if row.file_operation.kind != "apply":
            return False
        if not cls._same_path(os.path.dirname(actual), os.path.dirname(expected)):
            return False
        # Exact shared-engine auto-counter form; no arbitrary sibling stem,
        # leading-zero/nonpositive suffix or replacement protected extension.
        name = os.path.normcase(os.path.basename(expected))
        actual_name = os.path.normcase(os.path.basename(actual))
        extension = os.path.normcase(row.extension)
        if extension and not actual_name.endswith(extension):
            return False
        if extension:
            stem, counter_extension = name[:-len(extension)], name[-len(extension):]
            actual_stem, actual_extension = actual_name[:-len(extension)], actual_name[-len(extension):]
        else:
            stem, counter_extension = os.path.splitext(name)
            actual_stem, actual_extension = os.path.splitext(actual_name)
        if actual_extension != counter_extension:
            return False
        prefix = stem + "_"
        suffix = actual_stem[len(prefix):] if actual_stem.startswith(prefix) else ""
        return (bool(suffix) and suffix.isascii() and suffix.isdecimal()
                and suffix[0] != "0" and int(suffix) < 1000)

    def _valid_result(self, row, result):
        marker = row.file_operation
        try: validate_outcome_evidence(result)
        except (ValueError, AttributeError): return False
        return (type(result) is FileOperationOutcome
                and type(result.task_id) is str and result.task_id == row.id
                and type(result.batch_id) is str and result.batch_id == marker.batch_id
                and type(result.success) is bool and type(result.recovery_required) is bool
                and (result.error is None or _string(result.error, 4096, empty=True))
                and _string(result.new_path, 4096, empty=True)
                and (not result.success or bool(result.new_path))
                and (not result.new_path or self._destination_valid(row, result)))

    def _receive(self, owner, index, result):
        if index in owner.received:
            return
        owner.received.add(index)  # Consume BEFORE validation, store and observers.
        approved = owner.saved[index]
        current = self._results.item(approved.id)
        if (self._rows.get(approved.id) is not owner or current is not approved):
            # A foreign replacement must never be overwritten as this result.
            self._disable()
            return
        valid = self._valid_result(approved, result)
        recovery = (not valid or result.recovery_required
                    or result.error == "fileops.error.unknownOutcome"
                    or (approved.file_operation.kind == "undo" and result.success
                        and not self._fingerprint_valid(result.source_fingerprint)))
        if recovery:
            marker = current.file_operation
            if valid:
                reason = result.error if result.error in RECOVERY_REASONS else 'fileops.error.nativeRecovery'
                paths = tuple(dict.fromkeys((*result.owned_residue_paths,
                    *((result.new_path,) if result.success and result.new_path else ()))))
                validate_owned_residue_paths(paths)
                marker = replace(marker, version=2,
                    known_result_path=result.new_path if result.success else '',
                    owned_residue_paths=paths, recovery_reason=reason)
                _encode_intent(marker)
            candidate = replace(current, recovery_required=True,
                file_operation=marker,
                error_category="file_operation_recovery" if valid else "invalid_outcome")
            if valid and result.success and approved.file_operation.kind == 'undo':
                # A confirmed physical Undo keeps its current held capture even
                # when metadata marking failed. The hold/state still stays inert.
                candidate = replace(candidate, size_bytes=result.source_fingerprint.size_bytes,
                                    mtime_ns=result.source_fingerprint.mtime_ns)
        elif result.success:
            if approved.file_operation.kind == "apply":
                candidate = replace(current, state=ReviewItemState.APPLIED,
                    applied_path=result.new_path, file_operation=None, recovery_required=False,
                    error_category="")
            else:
                candidate = replace(current, state=ReviewItemState.UNDONE, applied_path="",
                    size_bytes=result.source_fingerprint.size_bytes,
                    mtime_ns=result.source_fingerprint.mtime_ns,
                    file_operation=None, recovery_required=False, error_category="")
        else:
            candidate = replace(current, state=(ReviewItemState.FAILED
                if approved.file_operation.kind == "apply" else ReviewItemState.APPLIED),
                file_operation=None, recovery_required=False, error_category="file_operation_failed")
        try:
            self._results._replace_for_file_operation(((current, candidate),))
        except Exception:
            if valid: self._recovery_outcomes[current.id] = result
            self._disable()

    @Slot(object)
    def _progress(self, payload):
        self._require_owner()
        if type(payload) is not FileOperationProgress or not self._lane.is_publishing(payload):
            return
        owner = self._owners.get(payload.reservation)
        if owner is None or type(payload.index) is not int or not 0 <= payload.index < len(owner.saved):
            return
        if payload.index in owner.received:
            return
        self._publication_depth += 1
        try:
            self._receive(owner, payload.index, payload.result)
            self._notify()
        finally:
            self._publication_depth -= 1

    @Slot(object)
    def _completion(self, payload):
        self._require_owner()
        if type(payload) is not FileOperationCompletion or not self._lane.is_publishing(payload):
            return
        owner = self._owners.get(payload.reservation)
        if owner is None:
            return
        self._publication_depth += 1
        try:
            results = (payload.results if type(payload.results) is tuple
                       and len(payload.results) == len(owner.saved) else ())
            for index in range(len(owner.saved)):
                self._receive(owner, index, results[index] if index < len(results) else None)
            self._retire(owner)  # Retire before a terminal observer can approve Undo.
            self._notify()
        finally:
            self._publication_depth -= 1

    def restore_interrupted(self) -> int:
        self._require_owner()
        if not self._can_admit() or self._started or self._owners:
            raise ValueError("invalid_watch_file_operations")
        self._action_depth += 1
        try:
            rows = tuple(row for row in self._results.items()
                         if row.state is ReviewItemState.APPLYING or row.file_operation is not None)
            if rows:
                try:
                    self._results._replace_for_file_operation(tuple((row,
                        replace(row, recovery_required=True, error_category="interrupted")) for row in rows))
                except Exception:
                    self._disable()
                    return 0
                self._notify()
            return len(rows)
        finally:
            self._action_depth -= 1

    def begin_close(self) -> None:
        self._require_owner()
        self._closing = True  # This owner does not own/shut down the shared lane.

    @property
    def workers_idle(self):
        self._require_owner()
        return (not self._owners and not self._action_depth and not self._publication_depth
                and self._lane.workers_idle)

    @property
    def available(self):
        self._require_owner()
        return self._available and self._results.available

    @property
    def error(self):
        self._require_owner()
        return self._error if self._results.available else "queue_unavailable"
