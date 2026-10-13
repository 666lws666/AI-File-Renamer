"""Immutable approvals and worker-owned adapter to the existing file engine.

Construction/validation perform no disk access. A backend belongs to one serial
worker lane; it must not be shared between independently running lanes.
"""
from dataclasses import dataclass
from pathlib import Path
import os

from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_plan import (RenamePlan, SourceFingerprint, NativeFileIdentity,
    validate_native_identity, validate_source_fingerprint, validate_owned_residue_paths)
from src.core.undo_manager import UndoManager


def _string(value, maximum, *, empty=False):
    return (type(value) is str and len(value) <= maximum and "\x00" not in value
            and (empty or bool(value.strip())))


@dataclass(frozen=True)
class FileOperationRequest:
    operation_id: str
    kind: str
    batch_id: str = ""
    plans: tuple[RenamePlan, ...] = ()
    task_ids: tuple[str, ...] = ()
    allowed_roots: tuple[str, ...] = ()

    def __post_init__(self):
        validate_request(self)

    @property
    def item_count(self) -> int:
        return len(self.plans) if self.kind == "apply" else len(self.task_ids)


def validate_request(request):
    """Recheck the complete pure value graph at the admission boundary."""
    invalid = "fileops.error.invalidRequest"
    if (type(request) is not FileOperationRequest
            or not _string(request.operation_id, 256)
            or type(request.kind) is not str or request.kind not in ("apply", "undo")
            or type(request.plans) is not tuple or type(request.task_ids) is not tuple
            or type(request.allowed_roots) is not tuple or len(request.allowed_roots) > 2000
            or any(not _string(root, 4096) for root in request.allowed_roots)
            or len(set(request.allowed_roots)) != len(request.allowed_roots)):
        raise ValueError(invalid)
    if request.kind == "undo":
        if (type(request.batch_id) is not str or request.batch_id != "" or request.plans
                or request.allowed_roots
                or not 1 <= len(request.task_ids) <= 1000
                or any(not _string(task, 256) for task in request.task_ids)
                or len(set(request.task_ids)) != len(request.task_ids)):
            raise ValueError(invalid)
        return
    if (not _string(request.batch_id, 256) or request.task_ids
            or not 1 <= len(request.plans) <= 1000):
        raise ValueError(invalid)
    ids = set()
    for plan in request.plans:
        if type(plan) is not RenamePlan:
            raise ValueError(invalid)
        fingerprint = plan.source_fingerprint
        if (not _string(plan.task_id, 256) or plan.task_id in ids
                or not _string(plan.source_path, 4096)
                or not _string(plan.target_parent, 4096)
                or not _string(plan.target_name, 256)
                or not _string(plan.extension, 256, empty=True)
                or not _string(plan.batch_id, 256, empty=True)
                or type(fingerprint) is not SourceFingerprint
                or type(fingerprint.size_bytes) is not int or fingerprint.size_bytes < 0
                or type(fingerprint.mtime_ns) is not int or fingerprint.mtime_ns < 0):
            raise ValueError(invalid)
        ids.add(plan.task_id)


@dataclass(frozen=True)
class FileOperationOutcome:
    task_id: str
    batch_id: str
    success: bool
    error: str | None = None
    new_path: str = ""
    recovery_required: bool = False
    source_fingerprint: SourceFingerprint | None = None
    source_identity: NativeFileIdentity | None = None
    owned_residue_paths: tuple[str, ...] = ()


def validate_outcome_evidence(outcome):
    """Validate the complete value graph before capture branches or path hashing."""
    fields = ('task_id', 'batch_id', 'success', 'error', 'new_path',
              'recovery_required', 'source_fingerprint', 'source_identity', 'owned_residue_paths')
    if (type(outcome) is not FileOperationOutcome
            or any(name not in vars(outcome) for name in fields)
            or not _string(outcome.task_id, 256)
            or not _string(outcome.batch_id, 256, empty=True)
            or type(outcome.success) is not bool
            or type(outcome.recovery_required) is not bool
            or (outcome.error is not None and not _string(outcome.error, 4096, empty=True))
            or not _string(outcome.new_path, 4096, empty=True)
            or (outcome.success and not outcome.new_path)):
        raise ValueError('invalid_file_operation_outcome')
    validate_owned_residue_paths(outcome.owned_residue_paths)
    if outcome.source_fingerprint is not None:
        validate_source_fingerprint(outcome.source_fingerprint)
    if outcome.source_identity is not None:
        validate_native_identity(outcome.source_identity)
    if outcome.success:
        validate_source_fingerprint(outcome.source_fingerprint)
        validate_native_identity(outcome.source_identity)
    # The known confirmed result is part of the same bounded recovery graph.
    paths = tuple(dict.fromkeys((*outcome.owned_residue_paths,
                    *((outcome.new_path,) if outcome.success and outcome.new_path else ()))))
    validate_owned_residue_paths(paths)


class FileOperationBackend:
    def __init__(self, history_path: str | Path):
        if not isinstance(history_path, (str, Path)) or not str(history_path):
            raise ValueError("fileops.error.invalidHistoryPath")
        self._history_path = history_path
        self._undo = None
        self._history = None
        self._move_observer = None

    def set_move_observer(self, callback):
        """Worker-only, non-authorizing candidate/result observation."""
        if callback is not None and not callable(callback):
            raise ValueError("invalid_move_observer")
        self._move_observer = callback
        if self._undo is not None:
            self._undo._executor._move_observer = callback

    def _initialize(self):
        if self._undo is None:
            # UndoManager has no shared-history injection API. Construct it once,
            # then use its one history for both existing execution boundaries.
            self._undo = UndoManager(self._history_path)
            self._history = self._undo._history
            self._undo._executor = RenameExecutor(PreflightService(), self._history,
                move_observer=self._move_observer)

    def execute_item(self, request: FileOperationRequest, index: int) -> FileOperationOutcome:
        self._initialize()
        if request.kind == "apply":
            plan = request.plans[index]
            # Supplied roots are explicit approval, never widen them to a plan's
            # derived parent. Empty legacy requests retain the existing policy.
            roots = request.allowed_roots or [os.path.dirname(plan.source_path), plan.target_parent]
            executor = RenameExecutor(PreflightService(allowed_roots=roots), self._history,
                move_observer=self._move_observer)
            result = executor.execute([plan], request.batch_id)[0]
        else:
            task_id = request.task_ids[index]
            result = self._undo.undo_task(task_id)
            if result is None:
                return FileOperationOutcome(task_id, "", False,
                                            error="fileops.error.undoRecordMissing")
        fingerprint = result.source_fingerprint
        recovery, error = result.recovery_required, result.error
        identity = None
        if result.move_evidence is not None:
            from src.core.rename_plan import validate_move_evidence
            try:
                validate_move_evidence(result.move_evidence)
                identity = result.move_evidence.identity
                validate_source_fingerprint(fingerprint)
                if fingerprint != result.move_evidence.fingerprint: raise ValueError()
            except ValueError:
                fingerprint, identity = None, None
        if result.success and (identity is None or fingerprint is None):
            recovery, error = True, 'fileops.error.nativeRecovery'
        return FileOperationOutcome(result.task_id, result.batch_id, result.success,
                                    error, result.new_path, recovery, fingerprint, identity,
                                    result.owned_residue_paths)
