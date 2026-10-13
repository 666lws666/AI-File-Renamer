"""M2 Task 7: UndoManager tests — per-record outcomes, unified batch undo."""
import os, threading, pytest
from unittest.mock import MagicMock, patch
from src.core.undo_manager import UndoManager
from src.core.rename_executor import RenameExecutor, _safe_move
from src.core.preflight_service import PreflightService
from src.core.rename_plan import RenamePlan, SourceFingerprint, BatchResult


_UNDO_HISTORY_WARNING = 'fileops.error.historySaveRecovery'


def _make_executor(tmp_path):
    return RenameExecutor(PreflightService(allowed_roots=[str(tmp_path)]))


def test_undo_single_batch(tmp_path):
    hp = tmp_path / "history.jsonl"
    src = tmp_path / "a.pdf"; src.write_text("hello")
    plan = RenamePlan("t1", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), "new.pdf", str(tmp_path), ".pdf")
    executor = _make_executor(tmp_path)
    executor._history = UndoManager(str(hp))._history
    r = executor.execute([plan], "b1")
    assert r[0].success
    um = UndoManager(str(hp), executor=executor)
    um._history = executor._history
    ur = um.undo_last_batch()
    assert ur[0].success
    assert ur[0].error is None
    assert ur[0].recovery_required is False
    assert ur[0].new_path == str(src)
    assert um._history.get_all()[0].undone is True
    assert os.path.exists(src)


def test_undo_lifo(tmp_path):
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history
    for i in range(3):
        src = tmp_path / f"f{i}.txt"; src.write_text(f"file{i}")
        ex.execute([RenamePlan(f"t{i}", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), f"new{i}.txt", str(tmp_path), ".txt")], f"b{i}")
    r = um.undo_last_batch()
    assert r[0].success
    assert os.path.exists(tmp_path / "f2.txt")


def test_partial_undo_reverse_order(tmp_path):
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history
    s1 = tmp_path / "a.pdf"; s1.write_text("a")
    s2 = tmp_path / "b.pdf"; s2.write_text("b")
    ex.execute([
        RenamePlan("t1", str(s1), SourceFingerprint(1, s1.stat().st_mtime_ns), "a2.pdf", str(tmp_path), ".pdf"),
        RenamePlan("t2", str(s2), SourceFingerprint(1, s2.stat().st_mtime_ns), "b2.pdf", str(tmp_path), ".pdf"),
    ], "bx")
    os.remove(tmp_path / "b2.pdf")
    results = um.undo_last_batch()
    # Reverse order: B (deleted, fails) first, then A (exists, succeeds)
    assert not results[0].success
    assert results[1].success


# ── NEW P0 regression tests ────────────────────────────────

def test_reverse_order_partial_success_preserves_correct_undone_flags(tmp_path):
    """Records [A,B] → undo B then A. B succeeds, A fails via injected executor.
    Only B's record should be marked undone. A must remain undone=False."""
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history

    # Create two renames: A → a_new, B → b_new
    sA = tmp_path / "a.pdf"; sA.write_text("A")
    sB = tmp_path / "b.pdf"; sB.write_text("B")
    ex.execute([
        RenamePlan("tA", str(sA), SourceFingerprint(1, sA.stat().st_mtime_ns), "a_new.pdf", str(tmp_path), ".pdf"),
        RenamePlan("tB", str(sB), SourceFingerprint(1, sB.stat().st_mtime_ns), "b_new.pdf", str(tmp_path), ".pdf"),
    ], "bx")

    # Inject a spy executor that fails the first undo_move call (which will be B, in reverse)
    call_order = []
    original_undo = ex.undo_move

    def spy_undo(src, dst, **approval):
        call_order.append((src, dst))
        if len(call_order) == 1:
            # First call = B (reverse order): succeed
            return original_undo(src, dst, **approval)
        else:
            # Second call = A: return failure without raising
            return BatchResult("fail", "", False, error="injected failure")

    ex.undo_move = spy_undo
    results = um.undo_last_batch()

    # Call order: B first (reverse), then A
    assert len(call_order) == 2
    assert "b_new.pdf" in call_order[0][0]  # B was first
    assert "a_new.pdf" in call_order[1][0]  # A was second
    assert results[0].success   # B succeeded
    assert not results[1].success  # A failed (injected)

    # Verify history: only B's record should be undone
    records = um._history.get_all()
    record_map = {}
    for r in records:
        if hasattr(r, 'old_path'):
            record_map[str(r.old_path)] = r
    # Restore executor for cleanup
    ex.undo_move = original_undo
    # Check undone flags
    a_rec = [r for r in records if "a.pdf" in str(r.old_path)][0]
    b_rec = [r for r in records if "b.pdf" in str(r.old_path)][0]
    assert b_rec.undone, "B succeeded → should be marked undone"
    assert not a_rec.undone, "A failed → must NOT be marked undone"


def test_undo_move_returns_false_without_exception(tmp_path):
    """When undo_move returns BatchResult(success=False) without raising,
    UndoManager must preserve the failure and not mark the record undone."""
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history

    s = tmp_path / "f.pdf"; s.write_text("x")
    ex.execute([RenamePlan("t1", str(s), SourceFingerprint(1, s.stat().st_mtime_ns), "f_new.pdf", str(tmp_path), ".pdf")], "bx")

    # Inject undo_move that returns failure without raising
    ex.undo_move = lambda src, dst, **approval: BatchResult("x", "", False, error="injected")
    results = um.undo_last_batch()
    assert not results[0].success
    assert "injected" in (results[0].error or "")

    # Record must NOT be marked undone
    records = um._history.get_all()
    assert not records[0].undone, "Failed undo must not mark record as undone"


def test_undo_results_retain_reversed_record_identity(tmp_path):
    """Three records A,B,C → undo C,B,A. Results must carry correct task_id, batch_id."""
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history

    sA = tmp_path / "a.pdf"; sA.write_text("A")
    sB = tmp_path / "b.pdf"; sB.write_text("B")
    sC = tmp_path / "c.pdf"; sC.write_text("C")
    ex.execute([
        RenamePlan("task-a", str(sA), SourceFingerprint(1, sA.stat().st_mtime_ns), "a_new.pdf", str(tmp_path), ".pdf"),
        RenamePlan("task-b", str(sB), SourceFingerprint(1, sB.stat().st_mtime_ns), "b_new.pdf", str(tmp_path), ".pdf"),
        RenamePlan("task-c", str(sC), SourceFingerprint(1, sC.stat().st_mtime_ns), "c_new.pdf", str(tmp_path), ".pdf"),
    ], "BATCH-X")

    results = um.undo_last_batch()
    assert len(results) == 3
    # Reverse order: C, B, A
    assert results[0].task_id == "task-c"
    assert results[1].task_id == "task-b"
    assert results[2].task_id == "task-a"
    for r in results:
        assert r.batch_id == "BATCH-X", f"Expected BATCH-X, got {r.batch_id}"
        assert r.success
        assert "new.pdf" not in (r.new_path or "")

def test_multi_batch_lifo(tmp_path):
    """Three batches, undo works backward across them."""
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history
    for i in range(3):
        src = tmp_path / f"f{i}.txt"; src.write_text(f"file{i}")
        ex.execute([RenamePlan(f"t{i}", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), f"new{i}.txt", str(tmp_path), ".txt")], f"b{i}")
    # Undo b2 first
    r1 = um.undo_last_batch()
    assert r1[0].success and os.path.exists(tmp_path / "f2.txt")
    # Undo b1 next
    r2 = um.undo_last_batch()
    assert r2[0].success and os.path.exists(tmp_path / "f1.txt")


def test_undo_task_targets_latest_active_record_only(tmp_path):
    """A row-level undo must not undo another task from the same batch."""
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history

    source_a = tmp_path / "a.pdf"; source_a.write_text("A")
    source_b = tmp_path / "b.pdf"; source_b.write_text("B")
    ex.execute([
        RenamePlan("task-a", str(source_a), SourceFingerprint(1, source_a.stat().st_mtime_ns), "a-new.pdf", str(tmp_path), ".pdf"),
        RenamePlan("task-b", str(source_b), SourceFingerprint(1, source_b.stat().st_mtime_ns), "b-new.pdf", str(tmp_path), ".pdf"),
    ], "batch-shared")

    result = um.undo_task("task-a")

    assert result.success
    assert result.task_id == "task-a"
    assert result.batch_id == "batch-shared"
    assert source_a.exists()
    assert not (tmp_path / "a-new.pdf").exists()
    assert (tmp_path / "b-new.pdf").exists()
    records = {record.task_id: record for record in um._history.get_all()}
    assert records["task-a"].undone is True
    assert records["task-b"].undone is False


def test_mark_undone_cannot_overwrite_concurrent_append(tmp_path):
    from src.core.rename_history import RenameHistory
    from src.models.rename_record import RenameRecord

    history = RenameHistory(tmp_path / "history.jsonl")
    first = RenameRecord(task_id="first", batch_id="batch-a", old_path=tmp_path / "a", new_path=tmp_path / "a2")
    second = RenameRecord(task_id="second", batch_id="batch-b", old_path=tmp_path / "b", new_path=tmp_path / "b2")
    history.record(first)

    read_started = threading.Event()
    allow_rewrite = threading.Event()
    original_get_all = history.get_all

    def paused_get_all():
        snapshot = original_get_all()
        read_started.set()
        assert allow_rewrite.wait(2)
        return snapshot

    history.get_all = paused_get_all
    worker = threading.Thread(target=history.mark_records_undone, args=("batch-a", [first.id]))
    worker.start()
    if read_started.wait(0.2):
        # Vulnerable implementation released the lock after taking a stale
        # snapshot, so this append lands before that snapshot is rewritten.
        history.record(second)
        allow_rewrite.set()
        worker.join(2)
    else:
        # Correct implementation never calls the public unlocked snapshot path;
        # its entire read-modify-write has already completed atomically.
        worker.join(2)
        history.record(second)
    assert not worker.is_alive()

    records = {record.task_id: record for record in original_get_all()}
    assert set(records) == {"first", "second"}
    assert records["first"].undone is True
    assert records["second"].undone is False


def test_undo_task_failure_keeps_record_active(tmp_path):
    hp = tmp_path / "history.jsonl"
    ex = _make_executor(tmp_path)
    um = UndoManager(str(hp), executor=ex)
    ex._history = um._history
    source = tmp_path / "a.pdf"; source.write_text("A")
    ex.execute([
        RenamePlan("task-a", str(source), SourceFingerprint(1, source.stat().st_mtime_ns), "a-new.pdf", str(tmp_path), ".pdf"),
    ], "batch-a")
    ex.undo_move = lambda *_, **approval: BatchResult("", "", False, error="blocked")

    result = um.undo_task("task-a")

    assert not result.success
    assert result.task_id == "task-a"
    assert result.batch_id == "batch-a"
    assert result.error == "blocked"
    assert um._history.get_all()[0].undone is False


def _apply_durable_undo_batch(tmp_path, count):
    """Set up real moves and a persisted history before injecting any failure."""
    hp = tmp_path / "history.jsonl"
    executor = _make_executor(tmp_path)
    manager = UndoManager(str(hp), executor=executor)
    executor._history = manager._history
    files = []
    plans = []
    for index in range(count):
        source = tmp_path / f"source-{index}.txt"
        target = tmp_path / f"renamed-{index}.txt"
        payload = f"original bytes {index}".encode()
        source.write_bytes(payload)
        plans.append(RenamePlan(
            f"task-{index}", str(source),
            SourceFingerprint(len(payload), source.stat().st_mtime_ns),
            target.name, str(tmp_path), ".txt",
        ))
        files.append((source, target, payload))
    applied = executor.execute(plans, "batch-persisted")
    assert len(applied) == count
    assert all(result.success and not result.recovery_required for result in applied)
    for source, target, payload in files:
        assert not source.exists()
        assert target.read_bytes() == payload
    records = manager._history.get_all()
    assert len(records) == count
    assert all(not record.undone for record in records)
    return manager, executor, hp, files, hp.read_bytes()


def _fail_undo_history_boundary(monkeypatch, boundary, message):
    import src.core.rename_history as history_module

    def fail(*args, **kwargs):
        raise OSError(message)

    monkeypatch.setattr(history_module.os, boundary, fail)


def _assert_history_snapshot(manager, hp, original_bytes):
    assert hp.read_bytes() == original_bytes
    assert all(not record.undone for record in manager._history.get_all())


@pytest.mark.parametrize("boundary", ["fsync", "replace"])
def test_undo_task_preserves_success_when_history_persistence_fails(
    tmp_path, monkeypatch, boundary,
):
    manager, _, hp, files, original_bytes = _apply_durable_undo_batch(tmp_path, 1)
    source, target, payload = files[0]
    _fail_undo_history_boundary(monkeypatch, boundary, "synthetic history failure")

    result = manager.undo_task("task-0")

    assert result.success is True
    assert result.task_id == "task-0"
    assert result.batch_id == "batch-persisted"
    assert result.new_path == str(source)
    assert result.recovery_required is True
    assert result.error == _UNDO_HISTORY_WARNING
    assert source.read_bytes() == payload
    assert not target.exists()
    _assert_history_snapshot(manager, hp, original_bytes)


@pytest.mark.parametrize("boundary", ["fsync", "replace"])
def test_mixed_undo_preserves_failed_record_when_history_persistence_fails(
    tmp_path, monkeypatch, boundary,
):
    manager, executor, hp, files, original_bytes = _apply_durable_undo_batch(tmp_path, 2)
    blocked_source, blocked_target, blocked_payload = files[1]
    blocked_source.write_bytes(b"occupied original path")
    _fail_undo_history_boundary(monkeypatch, boundary, "synthetic history failure")
    with patch.object(executor, "undo_move", wraps=executor.undo_move) as move:
        results = manager.undo_last_batch()

    assert [(result.task_id, result.batch_id) for result in results] == [
        ("task-1", "batch-persisted"), ("task-0", "batch-persisted"),
    ]
    failed, succeeded = results
    assert failed.success is False
    assert failed.error == 'fileops.error.targetOccupied'
    assert failed.new_path == ""
    assert failed.recovery_required is False
    source, target, payload = files[0]
    assert succeeded.success is True
    assert succeeded.new_path == str(source)
    assert succeeded.error == _UNDO_HISTORY_WARNING
    assert succeeded.recovery_required is True
    assert move.call_count == 2
    assert move.call_args_list[-1].args == (str(target), str(source))
    assert move.call_args_list[-1].kwargs['evidence'] == manager._history.get_all()[0].move_evidence
    assert source.read_bytes() == payload
    assert not target.exists()
    assert blocked_source.read_bytes() == b"occupied original path"
    assert blocked_target.read_bytes() == blocked_payload
    _assert_history_snapshot(manager, hp, original_bytes)


@pytest.mark.parametrize("boundary", ["fsync", "replace"])
def test_two_undo_successes_retained_without_retry_or_warning_disclosure(
    tmp_path, monkeypatch, boundary,
):
    manager, executor, hp, files, original_bytes = _apply_durable_undo_batch(tmp_path, 2)
    secret = "synthetic-secret-do-not-disclose"
    injected_message = f"history failed at {hp}: {secret}"
    _fail_undo_history_boundary(monkeypatch, boundary, injected_message)
    with patch.object(executor, "undo_move", wraps=executor.undo_move) as move:
        results = manager.undo_last_batch()

    expected_files = list(reversed(files))
    assert [result.task_id for result in results] == ["task-1", "task-0"]
    assert move.call_count == 2
    assert [call.args for call in move.call_args_list] == [
        (str(target), str(source)) for source, target, _ in expected_files
    ]
    for result, (source, target, payload) in zip(results, expected_files):
        assert result.success is True
        assert result.batch_id == "batch-persisted"
        assert result.new_path == str(source)
        assert result.recovery_required is True
        assert result.error == _UNDO_HISTORY_WARNING
        assert injected_message not in result.error
        assert secret not in result.error
        assert str(hp) not in result.error
        assert str(source) not in result.error
        assert str(target) not in result.error
        assert source.read_bytes() == payload
        assert not target.exists()
    _assert_history_snapshot(manager, hp, original_bytes)


def test_undo_history_programming_error_still_surfaces(tmp_path, monkeypatch):
    manager, _, hp, files, original_bytes = _apply_durable_undo_batch(tmp_path, 1)

    def programming_error(*args, **kwargs):
        raise RuntimeError("synthetic programming defect")

    monkeypatch.setattr(manager._history, "mark_records_undone", programming_error)

    with pytest.raises(RuntimeError, match="synthetic programming defect"):
        manager.undo_task("task-0")

    source, target, payload = files[0]
    assert source.read_bytes() == payload
    assert not target.exists()
    _assert_history_snapshot(manager, hp, original_bytes)
