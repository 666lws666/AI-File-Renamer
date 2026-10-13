"""Verified native worker boundary for Apply, identity-backed Undo and compensation."""
import os

from src.core.filename_validator import validate_filename
from src.core.rename_plan import (
    RenamePlan, BatchResult, FileMoveEvidence, NativeFileIdentity,
    validate_move_evidence, validate_native_identity, validate_source_fingerprint,
    validate_owned_residue_paths,
)
from src.core.preflight_service import PreflightService
from src.core.safe_file_move import safe_move, SafeFileMoveResult


_NATIVE_ERRORS = {
    'SAFE_MOVE_CROSS_VOLUME_BLOCKED': 'fileops.error.crossVolumeBlocked',
    'SAFE_MOVE_SOURCE_CHANGED': 'fileops.error.sourceChanged',
    'SAFE_MOVE_SOURCE_BUSY': 'fileops.error.sourceBusy',
    'SAFE_MOVE_TARGET_OCCUPIED': 'fileops.error.targetOccupied',
    'SAFE_MOVE_INVALID_INPUT': 'fileops.error.unsafePath',
    'SAFE_MOVE_INVALID_ROOT': 'fileops.error.unsafePath',
    'SAFE_MOVE_UNSUPPORTED_METADATA': 'fileops.error.unsafePath',
    'SAFE_MOVE_UNSUPPORTED_PLATFORM': 'fileops.error.unsafePath',
    'SAFE_MOVE_MOVE_FAILED': 'fileops.error.unsafePath',
}


def _safe_move(src: str, dst: str, *, expected_fingerprint=None,
               expected_identity=None, allowed_roots=(), create_parents=True) -> SafeFileMoveResult:
    """Two paths without explicit proof/roots are a no-I/O, fail-closed refusal."""
    return safe_move(src, dst, expected_fingerprint=expected_fingerprint,
                     expected_identity=expected_identity, allowed_roots=allowed_roots,
                     create_parents=create_parents)


def _counter_name(name, extension, counter):
    if extension:
        stem, suffix = name[:-len(extension)], name[-len(extension):]
    else:
        stem, suffix = os.path.splitext(name)
    return f'{stem}_{counter}{suffix}'


def _paths(*collections):
    paths = tuple(dict.fromkeys(path for collection in collections for path in collection))
    validate_owned_residue_paths(paths)
    return paths


def _capture_valid(result):
    try:
        validate_native_identity(result.source_identity)
        validate_source_fingerprint(result.source_fingerprint)
    except (AttributeError, ValueError):
        return False
    return True


def _call_native(src, dst, **approval):
    try:
        result = _safe_move(src, dst, **approval)
    except OSError:
        # A seam can raise after a real move. No path probe proves no mutation.
        return SafeFileMoveResult(False, error_code='SAFE_MOVE_RECOVERY_REQUIRED',
                                  recovery_required=True, owned_residue_paths=_paths((src, dst)))
    try:
        if (type(result) is not SafeFileMoveResult or type(result.success) is not bool
                or type(result.recovery_required) is not bool
                or type(result.new_path) is not str or len(result.new_path) > 4096 or '\x00' in result.new_path
                or type(result.error_code) is not str):
            raise ValueError()
        validate_owned_residue_paths(result.owned_residue_paths)
        if len(result.owned_residue_paths) > 4: raise ValueError()
        if result.source_identity is not None: validate_native_identity(result.source_identity)
        if result.source_fingerprint is not None: validate_source_fingerprint(result.source_fingerprint)
        if ((result.success and (result.recovery_required or result.new_path != dst or not _capture_valid(result)))
                or (result.error_code == 'SAFE_MOVE_TARGET_OCCUPIED' and not _capture_valid(result))):
            raise ValueError()
    except (AttributeError, ValueError):
        return SafeFileMoveResult(False, error_code='SAFE_MOVE_RECOVERY_REQUIRED',
                                  recovery_required=True, owned_residue_paths=_paths((src, dst)))
    return result


def _native_failure(task_id, batch_id, native):
    return BatchResult(task_id, batch_id, False,
        error=('fileops.error.nativeRecovery' if native.recovery_required else
               _NATIVE_ERRORS.get(native.error_code, 'fileops.error.unsafePath')),
        recovery_required=native.recovery_required,
        source_fingerprint=native.source_fingerprint,
        owned_residue_paths=native.owned_residue_paths)


class RenameExecutor:
    def __init__(self, preflight: PreflightService, history=None, *, move_observer=None):
        if preflight is None:
            raise ValueError('PreflightService is required — cannot be None')
        self._preflight, self._history = preflight, history
        self._move_observer = move_observer

    def _observe(self, phase, source, target, result=None):
        if self._move_observer is not None:
            try:
                self._move_observer(phase, source, target, result)
            except Exception:
                # Observation is not disk authority and cannot rewrite actual
                # physical success/failure or discard durable engine history.
                pass

    @property
    def history(self):
        return self._history

    def execute(self, plans: list[RenamePlan], batch_id: str = '') -> list[BatchResult]:
        results = []
        for plan in plans:
            result = self._execute_one(plan, batch_id)
            if result.success and self._history is not None:
                from src.models.rename_record import RenameRecord
                # Generate exact ID before append; append-then-raise is possible.
                record = RenameRecord(task_id=plan.task_id, batch_id=batch_id,
                    old_path=plan.source_path, new_path=result.new_path,
                    file_size=result.source_fingerprint.size_bytes, move_evidence=result.move_evidence)
                try:
                    self._history.record(record)
                except Exception:
                    result = self._compensate(plan, batch_id, result, record)
            results.append(result)
        return results

    def _compensate(self, plan, batch_id, forward, record):
        proof = forward.move_evidence
        self._observe("before", forward.new_path, plan.source_path)
        reverse = _call_native(forward.new_path, plan.source_path,
            expected_identity=proof.identity, expected_fingerprint=proof.fingerprint,
            allowed_roots=proof.allowed_roots, create_parents=False)
        self._observe("after", forward.new_path, plan.source_path, reverse)
        if reverse.success:
            try:
                self._history.finalize_rolled_back_record(record)
            except Exception:
                pass
            else:
                return BatchResult(plan.task_id, batch_id, False, error='fileops.error.historyRollback',
                                   source_fingerprint=reverse.source_fingerprint)
        return BatchResult(plan.task_id, batch_id, False, error='fileops.error.nativeRecovery',
            recovery_required=True, source_fingerprint=reverse.source_fingerprint or forward.source_fingerprint,
            owned_residue_paths=_paths((plan.source_path, forward.new_path),
                                      forward.owned_residue_paths, reverse.owned_residue_paths))

    def _execute_one(self, plan: RenamePlan, batch_id: str) -> BatchResult:
        pf = self._preflight.check(plan)
        if not pf.can_execute:
            error = ('fileops.error.sourceChanged' if pf.errors == ['Source file has changed since scan']
                     else 'fileops.error.unsafePath')
            return BatchResult(plan.task_id, batch_id, False, error=error)
        try:
            # Complete pure approval validation, not manufactured native proof.
            FileMoveEvidence(1, NativeFileIdentity(0, 0, 0), plan.source_fingerprint, pf.allowed_roots)
        except (AttributeError, ValueError):
            return BatchResult(plan.task_id, batch_id, False, error='fileops.error.unsafePath')
        identity = None
        for attempt in range(1000):
            name = plan.target_name if attempt == 0 else _counter_name(plan.target_name, plan.extension, attempt)
            if not validate_filename(name, plan.extension).is_valid:
                return BatchResult(plan.task_id, batch_id, False, error='fileops.error.unsafePath')
            target = os.path.join(plan.target_parent, name)
            self._observe("before", plan.source_path, target)
            native = _call_native(plan.source_path, target, expected_fingerprint=plan.source_fingerprint,
                                  expected_identity=identity, allowed_roots=pf.allowed_roots)
            self._observe("after", plan.source_path, target, native)
            if native.success:
                proof = FileMoveEvidence(1, native.source_identity, native.source_fingerprint, pf.allowed_roots)
                return BatchResult(plan.task_id, batch_id, True, new_path=native.new_path,
                                   move_evidence=proof, source_fingerprint=native.source_fingerprint)
            if native.error_code == 'SAFE_MOVE_TARGET_OCCUPIED' and not native.recovery_required:
                if identity is None: identity = native.source_identity
                continue
            return _native_failure(plan.task_id, batch_id, native)
        return BatchResult(plan.task_id, batch_id, False, error='fileops.error.targetOccupied')

    def undo_move(self, src: str, dst: str, *, evidence: FileMoveEvidence) -> BatchResult:
        try:
            validate_move_evidence(evidence)
        except ValueError:
            return BatchResult('undo', '', False, error='fileops.error.undoEvidenceMissing')
        self._observe("before", src, dst)
        native = _call_native(src, dst, expected_identity=evidence.identity,
                              allowed_roots=evidence.allowed_roots, create_parents=False)
        self._observe("after", src, dst, native)
        if not native.success:
            return _native_failure('undo', '', native)
        proof = FileMoveEvidence(1, native.source_identity, native.source_fingerprint, evidence.allowed_roots)
        return BatchResult('undo', '', True, new_path=native.new_path,
                           move_evidence=proof, source_fingerprint=native.source_fingerprint)
