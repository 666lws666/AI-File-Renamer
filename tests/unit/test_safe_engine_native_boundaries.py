"""Actual owned Windows fixtures at the production engine admission boundary."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from src.core import rename_executor as engine
from src.core import safe_file_move as native
from src.core.preflight_service import PreflightService
from src.core.rename_history import RenameHistory
from src.core.rename_plan import RenamePlan, SourceFingerprint, PreflightResult
from src.core.undo_manager import UndoManager
from src.models.rename_record import RenameRecord
from tests.unit.test_safe_file_move import second_volume, _r3_owned_junction, _publish_ready_json


def plan(source, target, extension='.txt', task='task'):
    st = source.stat()
    return RenamePlan(task, str(source), SourceFingerprint(st.st_size, st.st_mtime_ns),
                      target.name, str(target.parent), extension)


def executor(root, history=None, roots=None):
    return engine.RenameExecutor(PreflightService(roots or [str(root)]), history)


def test_deleted_destination_engine_history_and_identity_only_undo_preserve_actual_post_proof(tmp_path, monkeypatch, capsys):
    """Real deleted-name forward/reverse captures through durable history and Undo."""
    from src.core.rename_plan import FileMoveEvidence, NativeFileIdentity, encode_move_evidence

    src, dst = tmp_path / 'source-post.txt', tmp_path / 'target-post.txt'
    original = b'APPROVED_ENGINE_DELETED_NAME'
    src.write_bytes(original)
    dst.write_bytes(b'DISTINCT_OWNED_OCCUPIED_DESTINATION')
    assert src.stat().st_ino != dst.stat().st_ino
    approved = plan(src, dst, task='deleted-name-task')
    roots, batch = (str(tmp_path),), 'deleted-name-batch'
    history = RenameHistory(tmp_path / 'history.jsonl')
    unrelated = RenameRecord(task_id='unrelated', batch_id=batch,
                             old_path=tmp_path / 'other-old', new_path=tmp_path / 'other-new')
    history.record(unrelated)
    unrelated_graph = json.loads(unrelated.to_json_line())
    real_move, real_rename, real_info = engine._safe_move, native._rename, native._info
    real_open, real_record = native._Transaction.open_child, history.record
    calls, held, admissions, pending, recorded, deleted = [], [], [], [], [], []

    def open_source(transaction, parent, name, **kwargs):
        handle = real_open(transaction, parent, name, **kwargs)
        if not kwargs.get('directory') and name in (src.name, dst.name):
            pending.append(handle)
        return handle

    def query(handle):
        info = real_info(handle)
        if pending and handle == pending[0]:
            admissions.append(info)
            pending.pop(0)
        return info

    def observe_rename(handle, parent, name):
        before = real_info(handle)
        real_rename(handle, parent, name)
        held.append((before, real_info(handle)))

    def observe_move(source, target, **approval):
        calls.append((source, target, approval))
        if len(calls) == 1:
            assert (source, target) == (str(src), str(dst))
            assert dst.read_bytes() == b'DISTINCT_OWNED_OCCUPIED_DESTINATION'
            deleted.append(True)
            dst.unlink()  # Immediately before the real executor/native move.
        return real_move(source, target, **approval)

    def observe_record(record):
        recorded.append(record)
        return real_record(record)

    monkeypatch.setattr(native._Transaction, 'open_child', open_source)
    monkeypatch.setattr(native, '_info', query)
    monkeypatch.setattr(native, '_rename', observe_rename)
    monkeypatch.setattr(engine, '_safe_move', observe_move)
    monkeypatch.setattr(history, 'record', observe_record)
    forward = executor(tmp_path, history).execute([approved], batch)[0]
    assert forward.success and not forward.recovery_required and forward.owned_residue_paths == ()
    assert (forward.task_id, forward.batch_id, forward.new_path) == (approved.task_id, batch, str(dst))
    assert deleted == [True] and len(held) == len(admissions) == len(recorded) == 1
    assert not src.exists() and dst.read_bytes() == original

    def post_proof(info):
        return FileMoveEvidence(1, NativeFileIdentity(info.volume, info.index, info.creation),
                                info.fingerprint, roots)

    forward_post = post_proof(held[0][1])
    assert forward.move_evidence == forward_post and forward.source_fingerprint == held[0][1].fingerprint
    assert calls[0][2] == dict(expected_fingerprint=approved.source_fingerprint,
                              expected_identity=None, allowed_roots=roots)
    record = recorded[0]
    assert (record.task_id, record.batch_id, record.old_path, record.new_path) == (
        approved.task_id, batch, src, dst)
    assert record.id != unrelated.id and record.move_evidence == forward_post
    graphs = [json.loads(line) for line in history._file.read_text(encoding='utf-8').splitlines()]
    assert len(graphs) == 2 and graphs[0] == unrelated_graph
    assert graphs[1]['id'] == record.id and graphs[1]['move_evidence'] == encode_move_evidence(forward_post)
    assert graphs[1]['file_size'] == forward_post.fingerprint.size_bytes and not graphs[1]['undone']
    manager = UndoManager(history._file, executor(tmp_path))  # Fresh, actual JSONL reload.
    loaded = manager._history.get_latest_for_task(approved.task_id)
    assert loaded.id == record.id and loaded.move_evidence == forward_post and not loaded.undone

    fresh_stats, real_stat = [], os.stat
    def forbid_path_stat(path, *args, **kwargs):
        if not isinstance(path, int) and os.fspath(path) in (str(src), str(dst)):
            fresh_stats.append(os.fspath(path))
            raise AssertionError('Historical Undo must use stored identity, not fresh path stat')
        return real_stat(path, *args, **kwargs)
    with monkeypatch.context() as undo_scope:
        undo_scope.setattr(os, 'stat', forbid_path_stat)
        reverse = manager.undo_task(approved.task_id)
    assert fresh_stats == [] and len(calls) == len(held) == len(admissions) == 2 and pending == []
    assert calls[1] == (str(dst), str(src), dict(expected_identity=loaded.move_evidence.identity,
                                               allowed_roots=roots, create_parents=False))
    assert reverse.success and not reverse.recovery_required and reverse.owned_residue_paths == ()
    assert (reverse.task_id, reverse.batch_id, reverse.new_path) == (approved.task_id, batch, str(src))
    assert reverse.move_evidence == post_proof(held[1][1])
    assert reverse.source_fingerprint == held[1][1].fingerprint
    for admission, (before, after) in zip(admissions, held):
        assert admission == before
        assert before.volume == after.volume and before.index == after.index
        assert before.fingerprint == after.fingerprint
    assert NativeFileIdentity(admissions[1].volume, admissions[1].index,
                              admissions[1].creation) == forward_post.identity
    assert src.read_bytes() == original and not dst.exists() and not list(tmp_path.glob('.xuxia-move-*'))
    final_graphs = [json.loads(line) for line in history._file.read_text(encoding='utf-8').splitlines()]
    assert final_graphs[0] == unrelated_graph
    assert final_graphs[1] == {**graphs[1], 'undone': True}
    final_records = RenameHistory(history._file).get_all()
    assert [(item.id, item.undone) for item in final_records] == [(unrelated.id, False), (record.id, True)]
    with capsys.disabled():
        captures = [(before.volume, before.index, before.creation, after.creation,
                     after.fingerprint.size_bytes, after.fingerprint.mtime_ns) for before, after in held]
        print(f'ENGINE_DELETED_NAME_POST_PROOF forward_reverse={captures!r} task={approved.task_id} '
              f'batch={batch} record_id={record.id} moves=2 restored=True destination_absent=True '
              f'fresh_path_stats={len(fresh_stats)} roots={roots!r}')


def test_replacement_after_preflight_is_not_moved(tmp_path, monkeypatch):
    src, dst, retained = (tmp_path / name for name in ('old.txt', 'new.txt', 'retained.txt'))
    src.write_bytes(b'APPROVED')
    approved = plan(src, dst)
    real, attempted = engine._safe_move, []
    def attack(source, target, **approval):
        os.rename(source, retained)
        Path(source).write_bytes(b'UNAPPROVED_REPLACEMENT')
        attempted.append(True)
        return real(source, target, **approval)
    monkeypatch.setattr(engine, '_safe_move', attack)
    result = executor(tmp_path).execute([approved], 'batch')[0]
    assert attempted == [True]
    assert not result.success and not result.recovery_required
    assert retained.read_bytes() == b'APPROVED'
    assert src.read_bytes() == b'UNAPPROVED_REPLACEMENT' and not dst.exists()


@pytest.mark.parametrize('case', ['plain', 'occupied', 'descendant', 'stream'])
def test_real_cross_volume_engine_refusal(tmp_path, second_volume, monkeypatch, case):
    src = tmp_path / 'source.txt'
    src.write_bytes(b'ORIGINAL')
    if case == 'stream': Path(str(src) + ':evidence').write_bytes(b'NAMED_STREAM')
    dst = second_volume / ('absent/nested/target.txt' if case == 'descendant' else 'target.txt')
    if case == 'occupied': dst.write_bytes(b'OCCUPIED')
    approved = plan(src, dst)
    actions = []
    def forbidden(*args, **kwargs):
        actions.append(True)
        raise OSError('Cross volume mutation forbidden')
    monkeypatch.setattr(native, '_rename', forbidden)
    monkeypatch.setattr(native._Transaction, 'guard', forbidden)
    result = executor(tmp_path, roots=[str(tmp_path), str(second_volume)]).execute([approved], 'b')[0]
    assert not result.success and not result.recovery_required
    assert result.error == 'fileops.error.crossVolumeBlocked' and actions == []
    assert src.read_bytes() == b'ORIGINAL'
    st = src.stat()
    assert SourceFingerprint(st.st_size, st.st_mtime_ns) == approved.source_fingerprint
    if case == 'stream': assert Path(str(src) + ':evidence').read_bytes() == b'NAMED_STREAM'
    if case == 'occupied': assert dst.read_bytes() == b'OCCUPIED'
    else: assert not dst.exists()
    if case == 'descendant': assert not (second_volume / 'absent').exists()


def test_target_junction_installed_at_move_seam_is_refused(tmp_path, monkeypatch):
    source_root, target_root, outside, control = (tmp_path / name for name in ('source', 'target', 'outside', 'control'))
    for directory in (source_root, target_root, outside, control): directory.mkdir()
    src, dst = source_root / 'old.txt', target_root / 'new.txt'
    src.write_bytes(b'APPROVED')
    approved = plan(src, dst)
    construction = _r3_owned_junction(control, outside, 0x100)
    assert construction == dict(opened=True, set=True, winerror=0, closed=True)
    (control / 'witness').write_bytes(b'CONTROL')
    assert (outside / 'witness').read_bytes() == b'CONTROL'
    os.rmdir(control)
    (outside / 'witness').unlink()
    real, attempted = engine._safe_move, []
    def attack(source, target, **approval):
        attempted.append(_r3_owned_junction(target_root, outside, 0x100))
        return real(source, target, **approval)
    monkeypatch.setattr(engine, '_safe_move', attack)
    try:
        result = executor(tmp_path, roots=[str(source_root), str(target_root)]).execute([approved], 'b')[0]
        assert attempted == [construction]
        assert not result.success and not result.recovery_required
        assert result.error == 'fileops.error.unsafePath'
        assert src.read_bytes() == b'APPROVED' and list(outside.iterdir()) == []
    finally:
        if target_root.is_junction(): os.rmdir(target_root)


def test_target_inserted_at_native_publication_is_counted_without_overwrite(tmp_path, monkeypatch):
    src, dst = tmp_path / 'old.txt', tmp_path / 'new.txt'
    src.write_bytes(b'APPROVED')
    approved = plan(src, dst)
    real, attempted, captures = native._rename, [], []
    def insert(handle, parent, name):
        captures.append(native._info(handle))
        if not attempted:
            dst.write_bytes(b'INSERTED')
            attempted.append(dst.read_bytes())
        return real(handle, parent, name)
    monkeypatch.setattr(native, '_rename', insert)
    result = executor(tmp_path).execute([approved], 'b')[0]
    assert attempted == [b'INSERTED'] and len(captures) == 2
    assert result.success and result.new_path == str(tmp_path / 'new_1.txt')
    assert captures[0].index == captures[1].index
    assert result.move_evidence.identity.file_index == captures[1].index
    assert dst.read_bytes() == b'INSERTED' and Path(result.new_path).read_bytes() == b'APPROVED'


def test_replacement_between_real_collisions_cannot_be_reapproved(tmp_path, monkeypatch):
    src, dst, retained = (tmp_path / name for name in ('old.txt', 'new.txt', 'retained.txt'))
    src.write_bytes(b'ORIGINAL')
    dst.write_bytes(b'OCCUPIED')
    approved = plan(src, dst)
    real, witnesses = engine._safe_move, []
    def replace_after_collision(source, target, **approval):
        result = real(source, target, **approval)
        if not witnesses:
            os.rename(src, retained)
            src.write_bytes(b'REPLACED')
            os.utime(src, ns=(src.stat().st_atime_ns, approved.source_fingerprint.mtime_ns))
            witnesses.append(result)
        return result
    monkeypatch.setattr(engine, '_safe_move', replace_after_collision)
    result = executor(tmp_path).execute([approved], 'b')[0]
    assert len(witnesses) == 1 and witnesses[0].error_code == 'SAFE_MOVE_TARGET_OCCUPIED'
    assert not result.success and not result.recovery_required and result.error == 'fileops.error.sourceChanged'
    assert retained.read_bytes() == b'ORIGINAL' and src.read_bytes() == b'REPLACED'
    assert dst.read_bytes() == b'OCCUPIED' and not (tmp_path / 'new_1.txt').exists()


@pytest.mark.parametrize('name,extension,counted', [('archive.tar.gz', '.tar.gz', 'archive_1.tar.gz'), ('report.v2', '', 'report_1.v2')])
def test_complete_protected_suffix_counter(tmp_path, name, extension, counted):
    src, dst = tmp_path / 'old.txt', tmp_path / name
    src.write_bytes(b'ORIGINAL'); dst.write_bytes(b'OCCUPIED')
    result = executor(tmp_path).execute([plan(src, dst, extension)], 'b')[0]
    assert result.success and result.new_path == str(tmp_path / counted)
    assert (tmp_path / counted).read_bytes() == b'ORIGINAL' and dst.read_bytes() == b'OCCUPIED'


def test_counter_exhaustion_is_bounded_and_retains_all_files(tmp_path):
    src, dst = tmp_path / 'old.txt', tmp_path / 'new.txt'
    src.write_bytes(b'ORIGINAL'); dst.write_bytes(b'OCCUPIED')
    for index in range(1, 1000): (tmp_path / f'new_{index}.txt').write_bytes(b'OCCUPIED')
    result = executor(tmp_path).execute([plan(src, dst)], 'b')[0]
    assert not result.success and not result.recovery_required and result.error == 'fileops.error.targetOccupied'
    assert src.read_bytes() == b'ORIGINAL'
    assert all(path.read_bytes() == b'OCCUPIED' for path in tmp_path.glob('new*.txt'))
    assert not (tmp_path / 'new_1000.txt').exists()


def test_counter_length_overflow_does_not_truncate(tmp_path):
    src, dst = tmp_path / 'old.txt', tmp_path / ('n' * 251 + '.txt')
    src.write_bytes(b'ORIGINAL'); dst.write_bytes(b'OCCUPIED')
    # Validator protects the existing 255-character complete-name limit.
    result = executor(tmp_path).execute([plan(src, dst)], 'b')[0]
    assert not result.success and not result.recovery_required
    assert src.read_bytes() == b'ORIGINAL' and dst.read_bytes() == b'OCCUPIED'
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize('mode', ['edited', 'replaced', 'legacy'])
def test_historical_undo_uses_identity_not_size_mtime(tmp_path, mode):
    src, dst = tmp_path / 'old.txt', tmp_path / 'new.txt'
    src.write_bytes(b'ORIGINAL')
    history = RenameHistory(tmp_path / 'history.jsonl')
    manager = UndoManager(history._file, executor(tmp_path, history)); manager._history = history
    approved = plan(src, dst)
    assert manager._executor.execute([approved], 'b')[0].success
    records = history.get_all()
    if mode == 'edited': dst.write_bytes(b'SAME_FILE_EDITED_CONTENT')
    elif mode == 'replaced':
        os.rename(dst, tmp_path / 'retained.txt'); dst.write_bytes(b'REPLACED')
        os.utime(dst, ns=(dst.stat().st_atime_ns, approved.source_fingerprint.mtime_ns))
        assert dst.stat().st_ino != (tmp_path / 'retained.txt').stat().st_ino
    else:
        records[0].move_evidence = None
        history._file.write_text(records[0].to_json_line() + '\n', encoding='utf-8')
    before = history._file.read_bytes()
    result = manager.undo_task('task')
    assert (result.task_id, result.batch_id) == ('task', 'b')
    if mode == 'edited':
        assert result.success and src.read_bytes() == b'SAME_FILE_EDITED_CONTENT'
        assert result.source_fingerprint == SourceFingerprint(src.stat().st_size, src.stat().st_mtime_ns)
        assert history.get_all()[0].undone
    else:
        assert not result.success and not result.recovery_required and not src.exists()
        assert result.error == ('fileops.error.sourceChanged' if mode == 'replaced' else 'fileops.error.undoEvidenceMissing')
        assert history._file.read_bytes() == before and not history.get_all()[0].undone
        assert dst.read_bytes() == (b'REPLACED' if mode == 'replaced' else b'ORIGINAL')
        if mode == 'replaced': assert (tmp_path / 'retained.txt').read_bytes() == b'ORIGINAL'


@pytest.mark.parametrize('mode', ['before', 'after', 'occupied', 'replaced', 'disposition', 'corrupt'])
def test_history_failure_truthful_compensation_and_exact_disposition(tmp_path, monkeypatch, mode):
    src, dst = tmp_path / 'old.txt', tmp_path / 'new.txt'
    src.write_bytes(b'ORIGINAL')
    history = RenameHistory(tmp_path / 'history.jsonl')
    unrelated = RenameRecord(task_id='unrelated', batch_id='previous', old_path=tmp_path/'a', new_path=tmp_path/'b')
    history.record(unrelated)
    real, witnesses = history.record, []
    def fail(record):
        witnesses.append(record)
        if mode != 'before': real(record)
        if mode == 'occupied': src.write_bytes(b'OCCUPIED')
        if mode == 'replaced':
            os.rename(dst, tmp_path / 'retained.txt'); dst.write_bytes(b'REPLACED')
            os.utime(dst, ns=(dst.stat().st_atime_ns, record.move_evidence.fingerprint.mtime_ns))
        if mode == 'corrupt':
            with history._file.open('a', encoding='utf-8') as stream: stream.write('{CORRUPT_EVIDENCE}\n')
        raise OSError('PRIVATE_HISTORY_FAILURE')
    monkeypatch.setattr(history, 'record', fail)
    if mode == 'disposition':
        monkeypatch.setattr(history, 'finalize_rolled_back_record', lambda *_: (_ for _ in ()).throw(OSError('PRIVATE')),
                            raising=False)
    result = executor(tmp_path, history).execute([plan(src, dst)], 'batch')[0]
    assert len(witnesses) == 1 and not result.success and result.new_path == ''
    assert 'PRIVATE' not in result.error
    if mode in ('before', 'after'):
        assert not result.recovery_required and result.error == 'fileops.error.historyRollback'
        assert src.read_bytes() == b'ORIGINAL' and not dst.exists()
    else:
        assert result.recovery_required and result.error == 'fileops.error.nativeRecovery'
        assert {str(src), str(dst)}.issubset(result.owned_residue_paths)
    loaded = history.get_all()
    assert loaded[0].id == unrelated.id and not loaded[0].undone
    if mode == 'before': assert len(loaded) == 1
    else:
        assert loaded[1].id == witnesses[0].id
        assert loaded[1].undone is (mode == 'after')
    if mode == 'occupied': assert src.read_bytes() == b'OCCUPIED' and dst.read_bytes() == b'ORIGINAL'
    if mode == 'replaced':
        assert (tmp_path/'retained.txt').read_bytes() == b'ORIGINAL' and dst.read_bytes() == b'REPLACED' and not src.exists()
    if mode in ('disposition', 'corrupt'): assert src.read_bytes() == b'ORIGINAL' and not dst.exists()
    if mode == 'corrupt': assert b'{CORRUPT_EVIDENCE}' in history._file.read_bytes()


def test_native_rename_then_error_never_retries_or_compensates(tmp_path, monkeypatch):
    src, dst = tmp_path / 'old.txt', tmp_path / 'new.txt'
    src.write_bytes(b'ORIGINAL')
    real, witnesses = native._rename, []
    def uncertain(*args):
        real(*args); witnesses.append(True)
        raise OSError('PRIVATE_AFTER_RENAME')
    monkeypatch.setattr(native, '_rename', uncertain)
    history = RenameHistory(tmp_path / 'history.jsonl')
    result = executor(tmp_path, history).execute([plan(src, dst)], 'b')[0]
    assert witnesses == [True] and not result.success and result.recovery_required and result.new_path == ''
    assert result.error == 'fileops.error.nativeRecovery'
    assert set(result.owned_residue_paths) == {str(src), str(dst)}
    assert dst.read_bytes() == b'ORIGINAL' and not src.exists() and history.get_all() == []


@pytest.mark.parametrize('roots', [(), [], ('',), ('bad\x00root',), ('C:/same', 'c:/same')])
def test_executable_preflight_without_exact_authority_cannot_mutate(tmp_path, roots):
    src, dst = tmp_path/'old.txt', tmp_path/'new.txt'; src.write_bytes(b'ORIGINAL')
    class Approval:
        def check(self, _):
            assert 'allowed_roots' in PreflightResult.__dataclass_fields__, 'frozen root snapshot missing'
            return PreflightResult(True, allowed_roots=roots)
    result = engine.RenameExecutor(Approval()).execute([plan(src, dst)], 'b')[0]
    assert not result.success and not result.recovery_required
    assert src.read_bytes() == b'ORIGINAL' and not dst.exists()


def test_strict_history_marking_preserves_unrelated_corruption(tmp_path):
    history = RenameHistory(tmp_path/'history.jsonl')
    record = RenameRecord(old_path=tmp_path/'old', new_path=tmp_path/'new', batch_id='b')
    history.record(record)
    with history._file.open('a', encoding='utf-8') as stream: stream.write('{CORRUPT_EVIDENCE}\n')
    before = history._file.read_bytes()
    with pytest.raises(OSError): history.mark_records_undone('b', [record.id])
    assert history._file.read_bytes() == before


def test_logging_after_durable_append_does_not_compensate(tmp_path, monkeypatch):
    import src.core.rename_history as module
    src, dst = tmp_path/'old.txt', tmp_path/'new.txt'; src.write_bytes(b'ORIGINAL')
    history = RenameHistory(tmp_path/'history.jsonl')
    calls = []
    def broken(*args):
        calls.append(True)
        raise RuntimeError('PRIVATE_LOGGING_ERROR')
    monkeypatch.setattr(module.logger, 'debug', broken)
    result = executor(tmp_path, history).execute([plan(src, dst)], 'b')[0]
    assert result.success and not result.recovery_required and calls == [True]
    assert dst.read_bytes() == b'ORIGINAL' and not src.exists()
    assert len(history.get_all()) == 1 and not history.get_all()[0].undone


@pytest.mark.parametrize('mode', ['different_proof', 'same_id_different_path', 'unsupported_proof', 'duplicate_key', 'duplicate_id'])
def test_strict_disposition_refuses_bad_same_id_or_corrupt_graph(tmp_path, mode):
    from src.core.rename_plan import FileMoveEvidence, NativeFileIdentity
    evidence = FileMoveEvidence(1, NativeFileIdentity(1,2,3), SourceFingerprint(4,5), (str(tmp_path),))
    history = RenameHistory(tmp_path/'history.jsonl')
    record = RenameRecord(task_id='task', batch_id='b', old_path=tmp_path/'old', new_path=tmp_path/'new', move_evidence=evidence)
    graph = json.loads(record.to_json_line())
    if mode == 'different_proof': graph['move_evidence']['identity']['file_index'] = 9
    elif mode == 'same_id_different_path': graph['new_path'] = str(tmp_path/'foreign')
    elif mode == 'unsupported_proof': graph['move_evidence']['version'] = 2
    raw = json.dumps(graph) + '\n'
    if mode == 'duplicate_key': raw = raw.replace('"id":', '"id":"foreign", "id":')
    if mode == 'duplicate_id': raw += raw
    history._file.write_text(raw, encoding='utf-8'); before = history._file.read_bytes()
    with pytest.raises(OSError): history.finalize_rolled_back_record(record)
    assert history._file.read_bytes() == before


def test_strict_history_absence_requires_actual_read_not_false_negative_probe(tmp_path, monkeypatch):
    history = RenameHistory(tmp_path / 'history.jsonl')
    record = RenameRecord(old_path=tmp_path / 'old', new_path=tmp_path / 'new', batch_id='b')
    history.record(record)
    before, reads = history._file.read_bytes(), []
    real_exists, real_open = Path.exists, Path.open
    def false_negative(path, *args, **kwargs):
        return False if path == history._file else real_exists(path, *args, **kwargs)
    def unreadable(path, *args, **kwargs):
        if path == history._file:
            reads.append(True)
            raise PermissionError('PRIVATE_UNREADABLE_HISTORY')
        return real_open(path, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'exists', false_negative)
        fault.setattr(Path, 'open', unreadable)
        with pytest.raises(OSError, match='^fileops.error.historySaveRecovery$'):
            history.finalize_rolled_back_record(record)
    assert reads == [True] and history._file.read_bytes() == before


def _consumer_quarantine_child(kind, root_text, ready_text, release_text):
    """Controlled close fault, actual publication/lock/guard/persistence/OS release."""
    import atexit
    import socket
    import threading
    import time
    import keyring, keyring.core
    from keyring.backends import Windows
    from keyring.backends.fail import Keyring
    from PySide6.QtWidgets import QApplication
    forbidden = []
    def deny(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError('Forbidden external access')
    for name in ('connect', 'connect_ex', 'sendto'): setattr(socket.socket, name, deny)
    for name in ('getaddrinfo', 'create_connection'): setattr(socket, name, deny)
    keyring.set_keyring(Keyring())
    for owner in (keyring, keyring.core, Windows.WinVaultKeyring):
        for name in ('get_password', 'set_password', 'delete_password', 'get_credential', '_read_credential',
                     '_resolve_credential', '_set_password', '_delete_password'):
            if hasattr(owner, name): setattr(owner, name, deny)
    for name in ('CredRead', 'CredWrite', 'CredDelete', 'CredEnumerate'):
        if hasattr(Windows.win32cred, name): setattr(Windows.win32cred, name, deny)
    atexit.register(lambda: print('ENGINE_CHILD_FORBIDDEN=' + str(len(forbidden)) + '\nENGINE_CHILD_ATEXIT=' +
        repr([(thread.name, thread.is_alive(), thread.daemon) for thread in threading.enumerate()]), flush=True))
    app = QApplication.instance() or QApplication([])
    root = Path(root_text)
    real_rename, real_close, published, closes = native._rename, native._close, [], []
    def publication(*args):
        answer = real_rename(*args)
        published.append(args[2])
        return answer
    def uncertain_close(handle):
        if published and not closes:
            closes.append(handle)
            raise OSError('CONTROLLED_CLOSE_BEFORE_EFFECT')
        return real_close(handle)
    native._rename, native._close = publication, uncertain_close
    if kind == 'watch':
        from tests.integration.test_managed_watch_file_operations import Harness, pump
        h = Harness(root, app); item = h.add()
        target = root/'new-one.txt'; target.write_bytes(b'OCCUPIED')
        assert h.actions.apply((item.id,)); h.drain()
        row = h.results.item(item.id); marker = row.file_operation
        assert row.recovery_required and marker.version == 2
        from src.core.watch_review_queue import ReviewQueue
        assert ReviewQueue(h.queue._file_path).get(item.id) == row
        from src.controllers.managed_watch_file_operations import ManagedWatchFileOperations
        restored = ManagedWatchFileOperations(results=h.results, lane=h.lane, parent=h.parent)
        assert restored.restore_interrupted() == 1
        assert h.results.item(item.id).file_operation == marker
        assert not restored.apply((item.id,)) and not restored.undo(item.id)
        paths = marker.owned_residue_paths
        restored.begin_close(); h.actions.begin_close(); h.lane.begin_close()
        pump(app, lambda: h.lane.closed and h.actions.workers_idle and restored.workers_idle)
        counted = root/'new-one_1.txt'
    else:
        from tests.integration.test_managed_batch_file_operations import add, pump
        from src.controllers.batch_workspace_controller import BatchWorkspaceController
        from src.controllers.managed_file_operation_lane import ManagedFileOperationLane
        from src.services.file_operation_backend import FileOperationBackend
        lane = ManagedFileOperationLane(FileOperationBackend(root/'history.jsonl'))
        controller = BatchWorkspaceController(workspace_path=root/'workspace.json', history_path=root/'history.jsonl',
            analyzer=lambda *_:'topic.txt', background=False, file_operation_lane=lane)
        task, source = add(controller, root)
        (root/'topic.txt').write_bytes(b'OCCUPIED')
        controller.applyTask(task); pump(lambda: lane.workers_idle and controller.workers_idle)
        row = controller.task_snapshot(task); marker = row['fileOperation']
        assert row['fileOperationRecoveryRequired'] and marker['version'] == 2
        restored = BatchWorkspaceController(workspace_path=root/'workspace.json', history_path=root/'history.jsonl',
            background=False, file_operation_lane=lane)
        fresh = restored.task_snapshot(task)
        assert fresh['fileOperation'] == marker and fresh['fileOperationRecoveryRequired']
        restored.applyTask(task); restored.undoTask(task); restored.retryTask(task)
        paths = tuple(marker['recoveryPaths'])
        restored.close(); controller.close(); lane.begin_close()
        pump(lambda: lane.closed and controller.workers_idle)
        counted = root/'topic_1.txt'
    assert len(published) == len(closes) == 1 and native._OWNER.quarantine is not None
    assert str(counted) in paths and any(Path(path).name.startswith('.xuxia-move-') for path in paths)
    assert 2 < len(paths) <= 4
    _publish_ready_json(ready_text, dict(paths=paths, counted=str(counted)))
    deadline = time.monotonic() + 15
    while not Path(release_text).exists() and time.monotonic() < deadline: time.sleep(.02)
    assert Path(release_text).exists()


@pytest.mark.parametrize('kind', ['batch', 'watch'])
def test_native_numbered_guard_residues_persist_and_os_exit_releases(tmp_path, kind, capsys):
    import subprocess
    import sys
    import time
    root = tmp_path/kind; root.mkdir()
    ready, release = tmp_path/'ready.json', tmp_path/'release'
    code = "import runpy,sys; runpy.run_path(sys.argv[1])['_consumer_quarantine_child'](*sys.argv[2:])"
    child = subprocess.Popen([sys.executable, '-B', '-c', code, str(Path(__file__).resolve()), kind, str(root),
        str(ready), str(release)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, 'QT_QPA_PLATFORM':'offscreen'})
    witness = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline: time.sleep(.02)
        assert ready.exists(), 'child failed before residue/lock witness'
        graph = json.loads(ready.read_text(encoding='utf-8'))
        try: handle = native._open(graph['counted'])
        except OSError as error: witness = error.winerror
        else: native._close(handle)
        assert witness == 32
        assert any(Path(path).exists() for path in graph['paths'] if Path(path).name.startswith('.xuxia-move-'))
    finally:
        release.write_text('normal', encoding='ascii')
        stdout, stderr = child.communicate(timeout=30)
        with capsys.disabled():
            print(f'ENGINE_CHILD_PROOF kind={kind} native_exit={child.returncode} lock={witness} stdout={stdout!r} stderr={stderr!r}')
    assert child.returncode == 0, (stdout, stderr)
    assert 'ENGINE_CHILD_FORBIDDEN=0' in stdout and "ENGINE_CHILD_ATEXIT=[('MainThread', False, False)]" in stdout
    assert not list(root.glob('.xuxia-move-*'))
    counted = root/('topic_1.txt' if kind == 'batch' else 'new-one_1.txt')
    assert counted.read_bytes() == (b'synthetic document' if kind == 'batch' else b'synthetic:one')
    counted.unlink()
    assert not counted.exists()
