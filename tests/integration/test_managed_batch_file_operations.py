"""Actual synthetic-file/Qt contracts for durable managed Batch approvals."""
import json
import inspect
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.controllers.managed_file_operation_lane import ManagedFileOperationLane, FileOperationProgress, FileOperationReservation
from src.services.file_operation_backend import FileOperationBackend, FileOperationRequest
from src.core.rename_history import RenameHistory


def test_managed_lane_is_an_optional_explicit_constructor_seam():
    assert 'file_operation_lane' in inspect.signature(BatchWorkspaceController).parameters


def pump(predicate, timeout=3):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        QApplication.processEvents()
        threading.Event().wait(.001)
    assert predicate()


@pytest.fixture
def managed(tmp_path):
    app = QApplication.instance() or QApplication([])
    backend = FileOperationBackend(tmp_path / 'history.jsonl')
    lane = ManagedFileOperationLane(backend)
    controller = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json',
        history_path=tmp_path / 'history.jsonl', analyzer=lambda *_: 'topic.txt',
        background=False, file_operation_lane=lane)
    yield controller, lane, backend
    controller.close()
    lane.begin_close()
    pump(lambda: lane.closed and controller.workers_idle)


def add(controller, root, name='source.txt'):
    source = root / name
    source.write_text('synthetic document', encoding='utf-8')
    controller.add_files([str(source)])
    return controller.task_ids[-1], source


def block(monkeypatch, backend):
    entered, release = threading.Event(), threading.Event()
    execute = backend.execute_item
    owner = threading.get_ident()
    def run(*args):
        assert threading.get_ident() != owner
        entered.set()
        assert release.wait(3)
        return execute(*args)
    monkeypatch.setattr(backend, 'execute_item', run)
    return entered, release


def test_apply_undo_are_durable_off_qt_and_fresh_fingerprint(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    c.applyTask(tid)
    assert entered.wait(1)
    row = c.task_snapshot(tid)
    assert row['fileOperationPending'] is True and row['status'] == 'review_pending'
    marker = json.loads((tmp_path / 'workspace.json').read_text(encoding='utf-8'))['tasks'][0]['fileOperation']
    assert marker['kind'] == 'apply' and marker['sourcePath'] == str(source)
    fired = []
    QTimer.singleShot(0, lambda: fired.append(True))
    pump(lambda: bool(fired))
    c.beginInlineEdit(tid); c.confirmInlineEdit(tid, 'wrong'); c.cancelInlineEdit(tid)
    c.retryTask(tid); c.ignoreTask(tid); c.applyTask(tid); c.undoTask(tid)
    assert c.task_snapshot(tid)['suggestedName'] == 'topic.txt'
    assert lane.owned_item_count == 1
    c.toggleTaskSelected(tid); c.setSearchText('topic')
    other_target = tmp_path / 'later-target'; other_target.mkdir()
    c.setTargetDirectory(str(other_target))
    release.set()
    pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert row['status'] == 'applied' and not row['fileOperationPending']
    target = Path(row['appliedPath'])
    assert target == tmp_path / 'topic.txt'  # Accepted parent is immutable.
    target.write_text('changed synthetic content', encoding='utf-8')
    c.undoTask(tid)
    pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert row['status'] == 'undone' and row['appliedPath'] == ''
    assert row['sizeBytes'] == source.stat().st_size
    assert row['modifiedNs'] == source.stat().st_mtime_ns
    c.applyTask(tid)
    pump(lambda: lane.workers_idle and c.workers_idle)
    assert c.task_snapshot(tid)['status'] == 'applied'


def test_admission_save_failure_cancels_reservation_without_io(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    monkeypatch.setattr(c, '_save_workspace', lambda *_: (_ for _ in ()).throw(OSError('private')))
    monkeypatch.setattr(backend, 'execute_item', lambda *_: pytest.fail('user-file IO'))
    c.applyTask(tid)
    row = c.task_snapshot(tid)
    assert row['status'] == 'review_pending' and row['suggestedName'] == 'topic.txt'
    assert row['errorMessage'] == 'fileops.error.admissionSaveFailed'
    assert lane.owned_item_count == 0 and source.read_text() == 'synthetic document'


def test_clear_does_not_cancel_or_resurrect_and_close_retains_work(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    c.applyTask(tid); assert entered.wait(1)
    c.clearWorkspace(); c.close()
    assert c.task_ids == () and not c.workers_idle
    assert json.loads((tmp_path / 'workspace.json').read_text(encoding='utf-8'))['tasks'] == []
    release.set()
    pump(lambda: lane.workers_idle and c.workers_idle)
    assert c.task_ids == () and not source.exists() and (tmp_path / 'topic.txt').exists()


def test_partial_conflict_progress_and_foreign_duplicate_payload(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    one, _ = add(c, tmp_path)
    two, second = add(c, tmp_path, 'second.txt')
    second.write_text('changed source fingerprint', encoding='utf-8')
    c.select_all_visible()
    seen = []
    lane.itemCompleted.connect(seen.append, Qt.DirectConnection)
    c.applySelected()
    pump(lambda: lane.workers_idle and c.workers_idle)
    assert c.applyTotal == c.applyCurrent == 2 and c.applySuccess == c.applyFailed == 1
    assert c.task_snapshot(one)['status'] == 'applied'
    assert c.task_snapshot(two)['status'] == 'failed' and second.exists()
    before = c.task_snapshot(one)
    lane.itemCompleted.emit(seen[0])
    lane.itemCompleted.emit(replace(seen[0], reservation=FileOperationReservation(seen[0].reservation.request)))
    assert c.task_snapshot(one) == before and c.applyCurrent == 2


def test_post_move_save_failure_keeps_physical_facts_and_recovery(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    c.applyTask(tid); assert entered.wait(1)
    monkeypatch.setattr(c, '_save_workspace', lambda *_: (_ for _ in ()).throw(OSError('private')))
    release.set(); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert row['status'] == 'applied' and Path(row['appliedPath']).exists() and not source.exists()
    assert row['fileOperationRecoveryRequired'] and row['errorMessage'] == 'fileops.error.workspaceSaveRecovery'
    assert not row['canUndo']


def test_commit_rejection_retirement_save_failure_is_inert_recovery(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    save = c._save_workspace
    calls = []
    def saving(candidate=None):
        calls.append(True)
        if len(calls) == 2: raise OSError('private')
        save(candidate)
    monkeypatch.setattr(c, '_save_workspace', saving)
    monkeypatch.setattr(lane, 'commit', lambda reservation: False)
    c.applyTask(tid)
    assert lane.owned_item_count == 0 and source.exists()
    row = c.task_snapshot(tid)
    assert row['fileOperationRecoveryRequired'] and not row['fileOperationPending']
    assert row['errorMessage'] == 'fileops.error.queueUnavailable'


@pytest.mark.parametrize('kind,moved,ambiguous', [('apply',False,False), ('apply',True,False), ('apply',True,True), ('undo',True,False), ('undo',False,False), ('undo',True,True)])
def test_restart_unresolved_v1_markers_remain_unknown_never_replayed(managed, tmp_path, kind, moved, ambiguous):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    record = RenameHistory(tmp_path / 'history.jsonl').get_latest_for_task(tid)
    row = c.task_snapshot(tid)
    target = Path(row['appliedPath'])
    if kind == 'apply' and not moved: target.replace(source)
    if kind == 'undo' and moved: target.replace(source)  # F0: history still active
    if ambiguous:
        (source if target.exists() else target).write_text('occupied')
    row['fileOperation'] = dict(version=1, operationId='inert', kind=kind, batchId=record.batch_id if kind == 'apply' else '',
        sourcePath=str(source if kind == 'apply' else target), targetPath=str(target if kind == 'apply' else source))
    row['status'] = 'review_pending' if kind == 'apply' else 'applied'
    c._save_workspace([row])
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        fresh = restored.task_snapshot(tid)
        assert not fresh['fileOperationPending'] and lane.owned_item_count == 0
        assert fresh['fileOperationRecoveryRequired'] and fresh['fileOperation'] == row['fileOperation']
        assert fresh['status'] == row['status'] and fresh['errorMessage'] == 'fileops.error.interrupted'
        assert not fresh['canApply'] and not fresh['canUndo'] and not fresh['canRetry']
    finally: restored.close()


def test_valid_reconciliation_write_failure_never_quarantines(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid); row['status'] = 'review_pending'
    c._save_workspace([row])
    monkeypatch.setattr(BatchWorkspaceController, '_save_workspace', lambda *_: (_ for _ in ()).throw(OSError('private')))
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    assert restored.task_ids == (tid,) and restored.task_snapshot(tid)['status'] == 'applied'
    assert (tmp_path / 'workspace.json').exists() and not list(tmp_path.glob('*.corrupted'))
    restored.close()


@pytest.mark.parametrize('unknown', [False, True])
def test_undo_recovery_retains_inert_marker_for_factual_restart(managed, tmp_path, monkeypatch, unknown):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    if unknown:
        execute = backend.execute_item
        def lost_result(*values):
            execute(*values)
            raise RuntimeError('private exception')
        monkeypatch.setattr(backend, 'execute_item', lost_result)
    else:
        monkeypatch.setattr(RenameHistory, 'mark_records_undone', lambda *_: (_ for _ in ()).throw(OSError('private')))
    c.undoTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert source.exists() and row['fileOperationRecoveryRequired']
    assert row['errorMessage'] == ('fileops.error.unknownOutcome' if unknown else 'fileops.error.historySaveRecovery')
    assert 'fileOperation' in json.loads((tmp_path / 'workspace.json').read_text(encoding='utf-8'))['tasks'][0]
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        assert restored.task_snapshot(tid)['status'] == ('failed' if unknown else 'undone')
        assert restored.task_snapshot(tid)['fileOperationRecoveryRequired']
        if not unknown: assert restored.task_snapshot(tid)['sizeBytes'] == source.stat().st_size
    finally: restored.close()
    again = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        assert again.task_snapshot(tid)['status'] == ('failed' if unknown else 'undone')
        if not unknown:
            assert again.task_snapshot(tid)['errorMessage'] == 'fileops.error.historySaveRecovery'
    finally: again.close()


def test_nested_publication_retains_owner_and_reentrant_undo_is_exact(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    nested = []
    issued = []
    def observe():
        row = c.task_snapshot(tid)
        if row['status'] == 'applied' and not row['fileOperationPending'] and not issued:
            issued.append(True)
            assert not c.workers_idle
            c.undoTask(tid)
            QApplication.processEvents()
            nested.append(c.task_snapshot(tid)['fileOperationPending'])
    c.tasksChanged.connect(observe, Qt.DirectConnection)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    assert nested == [True] and c.task_snapshot(tid)['status'] == 'undone'
    assert source.exists() and c.applyCurrent == c.applySuccess == 1


def test_oversized_selection_is_refused_in_full_without_io(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    base = c.task_snapshot(tid)
    rows = []
    for index in range(1001):
        row = dict(base, taskId='synthetic-' + str(index), selected=True)
        rows.append(row)
    c._commit_tasks(rows)
    monkeypatch.setattr(backend, 'execute_item', lambda *_: pytest.fail('unapproved IO'))
    c.applySelected()
    assert lane.owned_item_count == 0 and source.exists()
    assert all(row['errorMessage'] == 'fileops.error.queueFull' for row in c._tasks)


def test_restart_original_directory_is_ambiguous_not_completed(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    source.mkdir()
    row = c.task_snapshot(tid)
    row['status'] = 'review_pending'
    record = RenameHistory(tmp_path / 'history.jsonl').get_latest_for_task(tid)
    row['fileOperation'] = dict(version=1, operationId='inert', kind='apply', batchId=record.batch_id,
        sourcePath=str(source), targetPath=row['appliedPath'])
    c._save_workspace([row])
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        assert restored.task_snapshot(tid)['status'] != 'applied'
        assert restored.task_snapshot(tid)['fileOperationRecoveryRequired']
    finally: restored.close()


def test_foreign_malformed_payload_does_not_release_valid_pending_owner(managed, tmp_path, monkeypatch):
    from src.services.file_operation_backend import FileOperationOutcome
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    c.applyTask(tid); assert entered.wait(1)
    try:
        owner = c._file_operations._rows[tid]
        row = c.task_snapshot(tid)
        assert c._file_operations._progress(FileOperationProgress([], 0, FileOperationOutcome(tid, '', True))) is None
        payload = FileOperationProgress(owner.reservation, 0, FileOperationOutcome('foreign', owner.reservation.request.batch_id, True, new_path=str(source)))
        c._file_operations._progress(payload)
        assert c.task_snapshot(tid) == row and lane.owned_item_count == 1
    finally: release.set()


def test_recovery_blocked_pending_restoration_never_starts_analysis(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    row = c.task_snapshot(tid)
    row.update(status='pending', fileOperation=dict(version=True, operationId='bad', kind='apply',
        batchId='b', sourcePath=str(source), targetPath=str(tmp_path / 'topic.txt')))
    c._save_workspace([row])
    calls = []
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl', analyzer=lambda *_: calls.append(True) or 'topic.txt', background=False, file_operation_lane=lane)
    try:
        assert calls == [] and restored.task_snapshot(tid)['fileOperationRecoveryRequired']
    finally: restored.close()


def test_real_submit_rejection_clears_marker_without_backend_io(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    monkeypatch.setattr(lane._executor, 'submit', lambda *_: (_ for _ in ()).throw(RuntimeError('private submit')))
    monkeypatch.setattr(backend, 'execute_item', lambda *_: pytest.fail('not submitted'))
    c.applyTask(tid)
    row = c.task_snapshot(tid)
    assert row['status'] == 'review_pending' and row['errorMessage'] == 'fileops.error.queueUnavailable'
    assert not row['fileOperationPending'] and lane.owned_item_count == 0 and source.exists()
    assert 'fileOperation' not in json.loads((tmp_path / 'workspace.json').read_text(encoding='utf-8'))['tasks'][0]


def test_old_epoch_terminal_cannot_retire_reused_row_owner(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, first = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    c.applyTask(tid); assert entered.wait(1)
    c.clearWorkspace()
    source = tmp_path / 'new-source.txt'; source.write_text('new epoch synthetic')
    stat = source.stat()
    row = c._new_task(tid, str(source), '.txt', stat.st_size, stat.st_mtime_ns)
    row.update(status='review_pending', suggestedName='new-topic.txt')
    c._commit_tasks([row])
    c.applyTask(tid)
    current_owner = c._file_operations._rows[tid]
    seen = []
    def terminal(payload):
        if payload.reservation is not current_owner.reservation:
            seen.append(c._file_operations._rows.get(tid) is current_owner)
    lane.completed.connect(terminal, Qt.DirectConnection)
    release.set(); pump(lambda: lane.workers_idle and c.workers_idle)
    assert seen == [True] and c.task_snapshot(tid)['appliedPath'] == str(tmp_path / 'new-topic.txt')
    assert c.applyTotal == c.applyCurrent == c.applySuccess == 2


def test_invalid_persisted_fingerprint_refuses_with_fixed_error(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c._find_task(tid)['sizeBytes'] = -1
    c.applyTask(tid)
    assert c.task_snapshot(tid)['errorMessage'] == 'fileops.error.queueUnavailable'
    assert lane.owned_item_count == 0 and source.exists()


def test_refusal_publication_depth_blocks_reentrant_disposal(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    ids = tuple('synthetic-' + str(index) for index in range(1001))
    seen = []
    c.tasksChanged.connect(lambda: seen.append(c.workers_idle), Qt.DirectConnection)
    assert c._file_operations.apply(ids) is False
    assert seen == [False] and c.workers_idle


@pytest.mark.parametrize('case', ['apply-neither', 'undo-neither', 'apply-missing-history',
    'undo-missing-history', 'apply-wrong-batch', 'apply-wrong-source', 'apply-changed-fingerprint',
    'undo-invalid-marker', 'undo-normal-history'])
def test_restart_additional_identity_path_and_history_matrix(managed, tmp_path, case):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    target = Path(row['appliedPath'])
    record = RenameHistory(tmp_path / 'history.jsonl').get_latest_for_task(tid)
    kind = 'undo' if case.startswith('undo') else 'apply'
    marker = dict(version=1, operationId='inert', kind=kind,
        batchId=record.batch_id if kind == 'apply' else '',
        sourcePath=str(target if kind == 'undo' else source),
        targetPath=str(source if kind == 'undo' else target))
    if case.endswith('neither'): target.replace(tmp_path / 'safe-backup.txt')
    if case == 'undo-missing-history': target.replace(source)
    if case == 'apply-wrong-batch': marker['batchId'] = 'foreign'
    if case == 'apply-wrong-source': marker['sourcePath'] = str(tmp_path / 'foreign.txt')
    if case == 'apply-changed-fingerprint': target.write_text('changed synthetic target content')
    if case == 'undo-invalid-marker': marker['version'] = True
    if case == 'undo-normal-history':
        c.undoTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
        assert RenameHistory(tmp_path / 'history.jsonl').get_latest_for_task(tid, active_only=False).undone
    row['fileOperation'] = marker
    row['status'] = 'applied' if kind == 'undo' else 'review_pending'
    c._save_workspace([row])
    history_path = tmp_path / ('missing.jsonl' if case.endswith('missing-history') else 'history.jsonl')
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=history_path,
        background=False, file_operation_lane=lane)
    try:
        fresh = restored.task_snapshot(tid)
        assert not fresh['fileOperationPending'] and lane.owned_item_count == 0
        # Even matching history cannot durably publish a lost operation outcome.
        assert fresh['fileOperationRecoveryRequired'] and fresh['errorMessage'] == 'fileops.error.interrupted'
        assert fresh['fileOperation'] == marker and fresh['status'] == row['status']
        assert not fresh['canApply'] and not fresh['canUndo'] and not fresh['canRetry']
    finally: restored.close()


def test_valid_workspace_history_read_failure_is_fixed_recovery_not_corruption(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    monkeypatch.setattr(RenameHistory, 'get_latest_for_task', lambda *_a, **_k: (_ for _ in ()).throw(OSError('private history path')))
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json', history_path=tmp_path / 'history.jsonl',
        background=False, file_operation_lane=lane)
    try:
        row = restored.task_snapshot(tid)
        assert row['status'] == 'applied' and row['fileOperationRecoveryRequired']
        assert row['errorMessage'] == 'fileops.error.interrupted'
        assert (tmp_path / 'workspace.json').exists() and not list(tmp_path.glob('*.corrupted'))
    finally: restored.close()


def test_numbered_native_uncertainty_persists_sticky_restart_hold(managed, tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    occupied = tmp_path/'topic.txt'; occupied.write_bytes(b'OCCUPIED')
    real, witnesses = native._rename, []
    def uncertain(*args):
        answer = real(*args)
        witnesses.append(args[2])
        raise OSError('PRIVATE_AFTER_PUBLICATION')
    monkeypatch.setattr(native, '_rename', uncertain)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert witnesses == ['topic_1.txt']
    assert row['status'] != 'applied' and row['fileOperationRecoveryRequired']
    marker = row['fileOperation']
    assert marker['version'] == 2 and marker['recoveryReason'] == 'fileops.error.nativeRecovery'
    assert set(marker['recoveryPaths']) == {str(source), str(tmp_path/'topic_1.txt')}
    assert (tmp_path/'topic_1.txt').read_text() == 'synthetic document' and occupied.read_bytes() == b'OCCUPIED'
    before = len(witnesses)
    restored = BatchWorkspaceController(workspace_path=tmp_path/'workspace.json', history_path=tmp_path/'history.jsonl',
        background=False, file_operation_lane=lane)
    try:
        fresh = restored.task_snapshot(tid)
        assert fresh['fileOperation'] == marker and fresh['fileOperationRecoveryRequired']
        assert not fresh['canUndo'] and not fresh['canApply'] and not fresh['canRetry']
        restored.applyTask(tid); restored.undoTask(tid); restored.retryTask(tid)
        assert len(witnesses) == before
    finally: restored.close()


@pytest.mark.parametrize('bad', ['list_residues', 'duplicate_residues', 'too_many', 'merged_overflow', 'deleted_identity', 'missing_capture'])
def test_genuine_batch_malformed_graph_drains_to_locked_recovery(managed, tmp_path, monkeypatch, bad):
    from src.services.file_operation_backend import FileOperationOutcome
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    real = backend.execute_item
    def altered(*args):
        result = real(*args)
        if bad == 'missing_capture': return replace(result, source_fingerprint=None, source_identity=None)
        if bad == 'deleted_identity':
            object.__delattr__(result.source_identity, 'file_index')
            return result
        paths = {'list_residues': [], 'duplicate_residues': ('same', 'same'),
                 'too_many': tuple(str(tmp_path/f'p{i}') for i in range(9)),
                 'merged_overflow': tuple(str(tmp_path/f'p{i}') for i in range(8))}[bad]
        return replace(result, recovery_required=True, error='fileops.error.nativeRecovery', owned_residue_paths=paths)
    monkeypatch.setattr(backend, 'execute_item', altered)
    c.applyTask(tid)
    # Physical worker finish is distinct from rejected result-owner retirement.
    pump(lambda: lane.workers_idle)
    row = c.task_snapshot(tid)
    assert c.workers_idle, 'invalid real result must drain, not leak the row owner'
    assert row['fileOperationRecoveryRequired'] and not row['canUndo'] and not row['canApply']
    assert row['status'] != 'applied'
    assert (tmp_path/'topic.txt').read_text() == 'synthetic document' and not source.exists()


def test_completed_undo_workspace_save_failure_retains_edited_capture(managed, tmp_path, monkeypatch):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    target = Path(c.task_snapshot(tid)['appliedPath']); target.write_bytes(b'LEGITIMATE_EDIT')
    entered, release = block(monkeypatch, backend)
    c.undoTask(tid); assert entered.wait(1)
    durable = (tmp_path/'workspace.json').read_bytes()
    monkeypatch.setattr(c, '_save_workspace', lambda *_: (_ for _ in ()).throw(OSError('PRIVATE')))
    release.set(); pump(lambda: lane.workers_idle and c.workers_idle)
    row = c.task_snapshot(tid)
    assert row['status'] == 'undone' and row['fileOperationRecoveryRequired']
    assert row['fileOperation']['knownResultPath'] == str(source)
    assert (row['sizeBytes'], row['modifiedNs']) == (source.stat().st_size, source.stat().st_mtime_ns)
    assert source.read_bytes() == b'LEGITIMATE_EDIT' and not target.exists()
    assert (tmp_path/'workspace.json').read_bytes() == durable
    assert c._file_operations._recovery_outcomes[tid].source_fingerprint.size_bytes == len(b'LEGITIMATE_EDIT')


def test_batch_reloaded_recovery_graph_bounds_known_result_with_residues(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    marker = dict(version=2, operationId='inert', kind='apply', batchId='batch',
        sourcePath=str(source), targetPath=str(tmp_path / 'topic.txt'),
        knownResultPath=str(tmp_path / 'topic_1.txt'),
        recoveryPaths=[str(tmp_path / f'residue-{i}') for i in range(8)],
        recoveryReason='fileops.error.nativeRecovery')
    assert not c._file_operations._marker_valid(marker)
    row = c.task_snapshot(tid)
    row['fileOperation'] = marker
    c._save_workspace([row])
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json',
        history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        loaded = restored.task_snapshot(tid)
        assert loaded['fileOperation'] == marker and loaded['fileOperationRecoveryRequired']
        assert not loaded['canUndo'] and not loaded['canApply'] and not loaded['canRetry']
        assert source.read_text() == 'synthetic document' and lane.owned_item_count == 0
    finally: restored.close()


@pytest.mark.parametrize('path', [['bad'], {'bad': 'path'}])
def test_actual_batch_unhashable_path_is_one_locked_outcome_and_drains(managed, tmp_path, monkeypatch, path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    real, calls, saves, payloads = backend.execute_item, [], [], []
    save = c._save_workspace
    def altered(*args):
        result = real(*args)
        assert result.success and result.source_identity is not None and result.source_fingerprint is not None
        calls.append(result)
        return replace(result, new_path=path)
    def saving(rows=None):
        if rows and rows[0].get('errorMessage') == 'fileops.error.unknownOutcome': saves.append(True)
        return save(rows)
    monkeypatch.setattr(backend, 'execute_item', altered)
    monkeypatch.setattr(c, '_save_workspace', saving)
    def duplicate(payload):
        payloads.append(payload)
        c._file_operations._progress(payload)  # Exact live publication, not a forged authority.
    lane.itemCompleted.connect(duplicate, Qt.DirectConnection)
    c.applyTask(tid)
    pump(lambda: lane.workers_idle)
    assert c.workers_idle and lane.owned_item_count == 0
    assert not c._file_operations._owners and not c._file_operations._rows
    assert len(calls) == len(payloads) == len(saves) == 1
    assert c.applyCurrent == c.applyFailed == 1 and c.applySuccess == 0
    row = c.task_snapshot(tid)
    assert row['errorMessage'] == 'fileops.error.unknownOutcome' and row['fileOperationRecoveryRequired']
    assert not row['canApply'] and not row['canUndo'] and not row['canRetry']
    lane.itemCompleted.emit(payloads[0])
    assert c.task_snapshot(tid) == row and c.applyCurrent == 1
    assert not source.exists() and (tmp_path / 'topic.txt').read_text() == 'synthetic document'
    assert len(RenameHistory(tmp_path / 'history.jsonl').get_all()) == 1


def test_native_uncertainty_original_retained_save_failure_v1_reload_stays_held(managed, tmp_path, monkeypatch):
    from src.core import safe_file_move as native
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    entered, release = block(monkeypatch, backend)
    native_calls = []
    def uncertain_before_effect(*args):
        native_calls.append(args[2])
        raise OSError('CONTROLLED_UNCERTAIN_PUBLICATION')
    monkeypatch.setattr(native, '_rename', uncertain_before_effect)
    c.applyTask(tid); assert entered.wait(1)
    durable = (tmp_path / 'workspace.json').read_bytes()
    original = json.loads(durable)['tasks'][0]['fileOperation']
    assert set(original) == {'version', 'operationId', 'kind', 'batchId', 'sourcePath', 'targetPath'}
    assert original['version'] == 1
    monkeypatch.setattr(c, '_save_workspace', lambda *_: (_ for _ in ()).throw(OSError('CONTROLLED_SAVE_FAILURE')))
    release.set(); pump(lambda: lane.workers_idle and c.workers_idle)
    held = c._file_operations._recovery_outcomes[tid]
    assert native_calls == ['topic.txt'] and not held.success and held.recovery_required
    assert held.error == 'fileops.error.nativeRecovery' and held.source_fingerprint is not None
    assert set(held.owned_residue_paths) == {str(source), str(tmp_path / 'topic.txt')}
    assert (tmp_path / 'workspace.json').read_bytes() == durable
    assert source.read_text() == 'synthetic document' and not (tmp_path / 'topic.txt').exists()
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (held.source_fingerprint.size_bytes, held.source_fingerprint.mtime_ns)
    before = len(native_calls)
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json',
        history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        row = restored.task_snapshot(tid)
        assert row['fileOperation'] == original and row['fileOperationRecoveryRequired']
        assert not row['canApply'] and not row['canUndo'] and not row['canRetry']
        restored.applyTask(tid); restored.undoTask(tid); restored.retryTask(tid)
        assert len(native_calls) == before and lane.owned_item_count == 0
        assert source.read_text() == 'synthetic document' and not (tmp_path / 'topic.txt').exists()
    finally: restored.close()


def test_v1_before_start_interruption_is_held_without_file_or_history_probes(managed, tmp_path, monkeypatch):
    import src.controllers.batch_file_operations as module
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    row = c.task_snapshot(tid)
    marker = dict(version=1, operationId='before-start', kind='apply', batchId='batch',
        sourcePath=str(source), targetPath=str(tmp_path / 'topic.txt'))
    row['fileOperation'] = marker
    c._save_workspace([row])
    probes = []
    def probe(*args, **kwargs):
        probes.append(args)
        raise AssertionError('unresolved intent must not be cleared by path/history metadata')
    with monkeypatch.context() as guard:
        guard.setattr(module.os.path, 'exists', probe)
        guard.setattr(module.os.path, 'isfile', probe)
        guard.setattr(module.os, 'stat', probe)
        guard.setattr(RenameHistory, 'get_latest_for_task', probe)
        assert c._file_operations.reconcile([row])
    assert not probes and row['fileOperation'] == marker and row['fileOperationRecoveryRequired']
    assert source.read_text() == 'synthetic document' and lane.owned_item_count == 0


def test_confirmed_durable_completion_removes_v1_intent_and_reload_allows_undo(managed, tmp_path):
    c, lane, backend = managed
    tid, source = add(c, tmp_path)
    c.applyTask(tid); pump(lambda: lane.workers_idle and c.workers_idle)
    durable = json.loads((tmp_path / 'workspace.json').read_text(encoding='utf-8'))['tasks'][0]
    assert 'fileOperation' not in durable and not durable['fileOperationRecoveryRequired']
    restored = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json',
        history_path=tmp_path / 'history.jsonl', background=False, file_operation_lane=lane)
    try:
        row = restored.task_snapshot(tid)
        assert row['status'] == 'applied' and row['canUndo'] and not row['fileOperationRecoveryRequired']
        assert not source.exists() and Path(row['appliedPath']).read_text() == 'synthetic document'
    finally: restored.close()
