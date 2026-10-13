"""Qt-owner durable approvals; user-file I/O belongs solely to the shared lane."""
import copy
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Slot

from src.core.rename_history import RenameHistory
from src.core.rename_plan import (RenamePlan, SourceFingerprint, validate_owned_residue_paths,
                                  RECOVERY_REASONS)
from src.controllers.managed_file_operation_lane import (
    ManagedFileOperationLane, FileOperationProgress, FileOperationCompletion,
    FileOperationReservation,
)
from src.services.file_operation_backend import (FileOperationRequest, FileOperationOutcome, _string,
                                                validate_outcome_evidence)


@dataclass
class _Owner:
    reservation: object
    epoch: int
    ids: tuple[str, ...]
    received: set[int] = field(default_factory=set)


class BatchFileOperations(QObject):
    def __init__(self, controller, lane: ManagedFileOperationLane):
        super().__init__(controller)
        if self.thread() != lane.thread() or not self.thread().isCurrentThread():
            raise RuntimeError('fileops.error.wrongThread')
        self._controller, self._lane = controller, lane
        self._owners = {}
        self._rows = {}
        self._recovery_outcomes = {}
        self._epoch = 0
        self._closing = False
        self._publication_depth = 0
        # Public lane dispatch is already owner-queued. A second queue would
        # escape the lane's delivery lifetime and permit premature destruction.
        lane.itemCompleted.connect(self._progress, Qt.DirectConnection)
        lane.completed.connect(self._completion, Qt.DirectConnection)

    def owns(self, task_id: str) -> bool:
        return task_id in self._rows

    def advance_epoch(self) -> None:
        self._require_owner()
        self._epoch += 1
        self._rows.clear()

    def begin_close(self) -> None:
        self._require_owner()
        self._closing = True  # Borrowed lane may serve other application clients.

    @property
    def workers_idle(self) -> bool:
        return not self._owners and not self._publication_depth

    def _require_owner(self):
        if not self.thread().isCurrentThread():
            raise RuntimeError('fileops.error.wrongThread')

    def _error(self, ids, message, recovery=False):
        self._publication_depth += 1
        try:
            candidate = copy.deepcopy(self._controller._tasks)
            for row in candidate:
                if row['taskId'] in ids:
                    row['errorMessage'] = message
                    if recovery: row['fileOperationRecoveryRequired'] = True
            self._controller._publish_tasks(candidate)
            return False
        finally:
            self._publication_depth -= 1

    def apply(self, task_ids: tuple[str, ...]) -> bool:
        self._require_owner()
        if self._closing or self._controller.closed: return False
        c = self._controller
        ids = tuple(dict.fromkeys(task_ids))
        if len(ids) > 1000: return self._error(ids, 'fileops.error.queueFull')
        rows = [c._find_task(tid) for tid in ids]
        rows = [row for row in rows if row is not None and not c._file_operation_locked(row['taskId'])
                and not row.get('isEditing') and row['status'] in {'review_pending', 'undone'}
                and not c._validate_suggested_name(row, row['suggestedName'])]
        if not rows: return False
        batch = 'batch-' + uuid.uuid4().hex
        try:
            plans = tuple(RenamePlan(row['taskId'], row['originalName'],
                SourceFingerprint(row['sizeBytes'], row['modifiedNs']), row['suggestedName'],
                c._target_directory or str(Path(row['originalName']).parent), row['extension']) for row in rows)
            roots = tuple(dict.fromkeys(root for plan in plans for root in (
                str(Path(plan.source_path).parent), plan.target_parent)))
            request = FileOperationRequest(uuid.uuid4().hex, 'apply', batch, plans, allowed_roots=roots)
        except (ValueError, TypeError):
            return self._error(tuple(row['taskId'] for row in rows), 'fileops.error.queueUnavailable')
        markers = {plan.task_id: dict(version=1, operationId=request.operation_id, kind='apply',
            batchId=batch, sourcePath=plan.source_path, targetPath=plan.target_path) for plan in plans}
        return self._admit(request, markers)

    def undo(self, task_id: str) -> bool:
        self._require_owner()
        c = self._controller
        row = c._find_task(task_id)
        if (self._closing or c.closed or row is None or c._file_operation_locked(task_id)
                or row.get('isEditing') or row['status'] != 'applied' or not row.get('appliedPath')):
            return False
        try:
            request = FileOperationRequest(uuid.uuid4().hex, 'undo', task_ids=(task_id,))
        except (ValueError, TypeError):
            return self._error((task_id,), 'fileops.error.queueUnavailable')
        marker = dict(version=1, operationId=request.operation_id, kind='undo', batchId='',
                      sourcePath=row['appliedPath'], targetPath=row['originalName'])
        return self._admit(request, {task_id: marker})

    def _admit(self, request, markers):
        self._publication_depth += 1
        try:
            ids = tuple(markers)
            reservation = self._lane.reserve(request)
            if reservation is None:
                return self._error(ids, 'fileops.error.queueFull' if not self._lane.closed
                                   else 'fileops.error.queueUnavailable')
            c = self._controller
            candidate = copy.deepcopy(c._tasks)
            for row in candidate:
                if row['taskId'] in markers:
                    row['fileOperation'] = markers[row['taskId']]
                    row['errorMessage'] = ''
            try:
                c._save_workspace(candidate)
            except Exception:
                self._lane.cancel(reservation)
                return self._error(ids, 'fileops.error.admissionSaveFailed')
            owner = _Owner(reservation, self._epoch, ids)
            self._owners[reservation] = owner
            for tid in ids: self._rows[tid] = owner
            if not self._lane.commit(reservation):
                self._retire(owner)
                self._lane.cancel(reservation)
                for row in candidate:
                    if row['taskId'] in markers: row.pop('fileOperation', None)
                try:
                    c._save_workspace(candidate)
                except Exception:
                    for row in candidate:
                        if row['taskId'] in markers:
                            row['fileOperation'] = markers[row['taskId']]
                            row['fileOperationRecoveryRequired'] = True
                for row in candidate:
                    if row['taskId'] in markers: row['errorMessage'] = 'fileops.error.queueUnavailable'
                c._publish_tasks(candidate)
                return False
            if request.kind == 'apply':
                if not c._apply_active:
                    c._apply_current = c._apply_total = c._apply_success = c._apply_failed = 0
                c._apply_active = True
                c._apply_total += len(ids)
            c._publish_tasks(candidate, selection=True)
            if request.kind == 'apply': c.progressChanged.emit()
            return True
        finally:
            self._publication_depth -= 1

    def _retire(self, owner):
        self._owners.pop(owner.reservation, None)
        for tid in owner.ids:
            if self._rows.get(tid) is owner: self._rows.pop(tid)

    def _valid_result(self, owner, index, result):
        request = owner.reservation.request
        try: validate_outcome_evidence(result)
        except (ValueError, AttributeError): return False
        return (type(index) is int and 0 <= index < len(owner.ids)
            and type(result) is FileOperationOutcome and type(result.task_id) is str
            and result.task_id == owner.ids[index]
            and _string(result.batch_id, 256, empty=True)
            and (request.kind == 'undo' or result.batch_id == request.batch_id)
            and type(result.success) is bool and type(result.recovery_required) is bool
            and (result.error is None or _string(result.error, 4096, empty=True))
            and _string(result.new_path, 4096, empty=True)
            and (not result.success or bool(result.new_path)))

    @staticmethod
    def _fingerprint_valid(value):
        return (type(value) is SourceFingerprint and type(value.size_bytes) is int
            and value.size_bytes >= 0 and type(value.mtime_ns) is int and value.mtime_ns >= 0)

    def _receive(self, owner, index, result):
        if index in owner.received: return
        owner.received.add(index)  # Before any persistence/model/reentrant signal.
        c = self._controller
        request = owner.reservation.request
        if request.kind == 'apply':
            c._apply_current += 1
            if result.success: c._apply_success += 1
            else: c._apply_failed += 1
        if owner.epoch == self._epoch and self._rows.get(result.task_id) is owner:
            candidate = copy.deepcopy(c._tasks)
            row = next((row for row in candidate if row['taskId'] == result.task_id), None)
            if row is not None:
                recovery = result.recovery_required or result.error == 'fileops.error.unknownOutcome'
                error = result.error or ''
                if recovery and not error.startswith('fileops.error.'):
                    error = 'fileops.error.historySaveRecovery'
                elif not error.startswith('fileops.error.'):
                    error = c._safe_error(error)
                if result.success:
                    if request.kind == 'apply':
                        row.update(status='applied', appliedPath=result.new_path)
                    else:
                        row.update(status='undone', originalName=result.new_path, appliedPath='')
                        if self._fingerprint_valid(result.source_fingerprint):
                            row.update(sizeBytes=result.source_fingerprint.size_bytes,
                                       modifiedNs=result.source_fingerprint.mtime_ns)
                        else:
                            recovery = True
                            error = error or 'fileops.error.fingerprintRecovery'
                else:
                    row['status'] = 'failed'
                row.update(selected=False, errorMessage=error, fileOperationRecoveryRequired=recovery)
                if recovery:
                    reason = error if error in RECOVERY_REASONS else 'fileops.error.nativeRecovery'
                    row['fileOperation'] = self._recovery_marker(row['fileOperation'], result, reason)
                else: row.pop('fileOperation', None)
                try:
                    c._save_workspace(candidate)
                except Exception:
                    row.update(fileOperationRecoveryRequired=True,
                               errorMessage='fileops.error.workspaceSaveRecovery')
                    current = c._find_task(result.task_id)
                    if current and 'fileOperation' in current:
                        # Disk keeps its original durable intent. Memory retains
                        # exact returned evidence and the confirmed result path.
                        self._recovery_outcomes[result.task_id] = result
                        row['fileOperation'] = self._recovery_marker(current['fileOperation'], result,
                            'fileops.error.workspaceSaveRecovery')
                c._publish_tasks(candidate, selection=True)
        if request.kind == 'apply': c.progressChanged.emit()

    @Slot(object)
    def _progress(self, payload):
        self._require_owner()
        if (type(payload) is not FileOperationProgress or type(payload.reservation) is not FileOperationReservation
                or not self._lane.is_publishing(payload)): return
        owner = self._owners.get(payload.reservation)
        if owner is None or type(payload.index) is not int or not 0 <= payload.index < len(owner.ids): return
        self._publication_depth += 1
        try: self._receive(owner, payload.index, self._normalized_result(owner, payload.index, payload.result))
        finally: self._publication_depth -= 1

    def _normalized_result(self, owner, index, result):
        if self._valid_result(owner, index, result): return result
        # A genuine lane result with a malformed graph is unknown, not authority
        # to update paths. Consume it once and drain, retaining the durable intent.
        request = owner.reservation.request
        batch = request.batch_id if request.kind == 'apply' else ''
        return FileOperationOutcome(owner.ids[index], batch, False,
                                    error='fileops.error.unknownOutcome', recovery_required=True)

    @Slot(object)
    def _completion(self, payload):
        self._require_owner()
        if (type(payload) is not FileOperationCompletion or type(payload.reservation) is not FileOperationReservation
                or not self._lane.is_publishing(payload)): return
        owner = self._owners.get(payload.reservation)
        if owner is None: return
        self._publication_depth += 1
        try:
            results = payload.results if type(payload.results) is tuple and len(payload.results) == len(owner.ids) else ()
            for index in range(len(owner.ids)):
                result = results[index] if index < len(results) else None
                self._receive(owner, index, self._normalized_result(owner, index, result))
            self._retire(owner)
            c = self._controller
            c._apply_active = any(value.reservation.request.kind == 'apply' for value in self._owners.values())
            # Ownership is gone before observers may immediately enqueue Undo.
            c._publish_tasks(copy.deepcopy(c._tasks))
            if owner.reservation.request.kind == 'apply': c.progressChanged.emit()
        finally:
            self._publication_depth -= 1

    @staticmethod
    def _marker_valid(marker):
        if type(marker) is not dict or type(marker.get('version')) is not int: return False
        keys = {'version', 'operationId', 'kind', 'batchId', 'sourcePath', 'targetPath'}
        if marker['version'] == 2:
            keys |= {'knownResultPath', 'recoveryPaths', 'recoveryReason'}
            if marker.keys() != keys or type(marker['recoveryPaths']) is not list: return False
            try: validate_owned_residue_paths(tuple(marker['recoveryPaths']))
            except ValueError: return False
            if (not _string(marker['knownResultPath'], 4096, empty=True)
                    or type(marker['recoveryReason']) is not str
                    or marker['recoveryReason'] not in RECOVERY_REASONS): return False
            paths = tuple(dict.fromkeys((*marker['recoveryPaths'],
                *((marker['knownResultPath'],) if marker['knownResultPath'] else ()))))
            try: validate_owned_residue_paths(paths)
            except ValueError: return False
        return (marker.keys() == keys and marker['version'] in (1, 2)
            and _string(marker['operationId'], 256)
            and type(marker['kind']) is str and marker['kind'] in {'apply', 'undo'}
            and _string(marker['batchId'], 256, empty=marker['kind'] == 'undo')
            and _string(marker['sourcePath'], 4096) and _string(marker['targetPath'], 4096))

    @staticmethod
    def _recovery_marker(marker, result, reason):
        recovery = copy.deepcopy(marker)
        paths = tuple(dict.fromkeys((*result.owned_residue_paths,
                                    *((result.new_path,) if result.success and result.new_path else ()))))
        validate_owned_residue_paths(paths)
        recovery.update(version=2, knownResultPath=result.new_path if result.success else '',
                        recoveryPaths=list(paths), recoveryReason=reason)
        return recovery

    @staticmethod
    def _same_path(left, right):
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))

    def reconcile(self, tasks):
        """Metadata is evidence to inspect, never authority to execute a request."""
        c = self._controller
        history, history_loaded = None, False
        changed = False
        for row in tasks:
            marker = row.get('fileOperation')
            row['fileOperationPending'] = False
            # Every unresolved durable intent is unknown, including original V1
            # when a newer result save failed. Only durable completion removes it;
            # history/path metadata cannot clear this conservative reload hold.
            if (row.get('fileOperationRecoveryRequired')
                    or marker is not None):
                row.update(fileOperationRecoveryRequired=True,
                           errorMessage=(marker['recoveryReason'] if self._marker_valid(marker)
                                         and marker['version'] == 2 else
                                         'fileops.error.interrupted' if marker is not None else
                                         'fileops.error.nativeRecovery'))
                c._refresh_task(row)
                changed = True
                continue
            if not history_loaded:
                history = RenameHistory(str(c._history_path)) if c._history_path and c._history_path.exists() else None
                history_loaded = True
            record = history.get_latest_for_task(row['taskId'], active_only=False) if history else None
            if marker is None and row['status'] != 'applied' and (record is None or record.undone): continue
            if marker is not None or row['status'] == 'applied' or record is not None:
                changed = True
                row['fileOperationRecoveryRequired'] = False
                kind = marker.get('kind') if type(marker) is dict else 'apply'
                original = row['originalName']
                applied = str(record.new_path) if record else row.get('appliedPath', '')
                valid = (marker is None or self._marker_valid(marker))
                if valid and marker is not None:
                    old, new = ((marker['sourcePath'], marker['targetPath']) if kind == 'apply'
                                else (marker['targetPath'], marker['sourcePath']))
                    valid = self._same_path(old, original)
                    if kind == 'undo':
                        valid = (valid and record is not None and
                                 (not row.get('appliedPath') or self._same_path(new, row['appliedPath'])))
                    if record:
                        valid = (valid and self._same_path(old, str(record.old_path))
                                 and self._same_path(new, str(record.new_path))
                                 and (kind == 'undo' or marker['batchId'] == record.batch_id))
                    elif kind == 'apply': applied = new
                if record:
                    valid = valid and record.task_id == row['taskId'] and self._same_path(str(record.old_path), original)
                old_exists = os.path.exists(original)
                new_exists = bool(applied) and os.path.exists(applied)
                if valid and kind == 'apply' and record and not record.undone and os.path.isfile(applied) and not old_exists:
                    try:
                        stat = os.stat(applied)
                        valid = stat.st_size == row['sizeBytes'] and stat.st_mtime_ns == row['modifiedNs']
                    except OSError: valid = False
                    if valid: row.update(status='applied', appliedPath=applied, selected=False, errorMessage='')
                elif valid and kind == 'undo' and record and os.path.isfile(original) and not new_exists:
                    try:
                        stat = os.stat(original)
                        row.update(status='undone', appliedPath='', sizeBytes=stat.st_size,
                                   modifiedNs=stat.st_mtime_ns, selected=False,
                                   errorMessage='' if record.undone else 'fileops.error.historySaveRecovery',
                                   fileOperationRecoveryRequired=not record.undone)
                    except OSError: valid = False
                elif valid and kind == 'apply' and marker is not None and os.path.isfile(original) and not new_exists:
                    try:
                        stat = os.stat(original)
                        valid = stat.st_size == row['sizeBytes'] and stat.st_mtime_ns == row['modifiedNs']
                    except OSError: valid = False
                    if valid: row.update(status='undone' if row['status'] == 'undone' else 'review_pending',
                                         errorMessage='fileops.error.interrupted', appliedPath='')
                else:
                    valid = False
                if not valid:
                    row.update(fileOperationRecoveryRequired=True, errorMessage='fileops.error.interrupted')
                if not row['fileOperationRecoveryRequired'] or not self._marker_valid(marker):
                    row.pop('fileOperation', None)
                c._refresh_task(row)
        return changed
