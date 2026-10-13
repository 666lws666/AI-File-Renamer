"""M2 Task 6: RenameExecutor tests — Preflight-enforced, cross-volume."""
import errno, os, pytest
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.core.rename_executor import RenameExecutor, _safe_move
from src.core.preflight_service import PreflightService

def _make_executor(tmp_path):
    return RenameExecutor(PreflightService(allowed_roots=[str(tmp_path)]))

def test_execute_success(tmp_path):
    src = tmp_path / "src.pdf"; src.write_text("hello")
    plan = RenamePlan("t1", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), "new.pdf", str(tmp_path), ".pdf")
    results = _make_executor(tmp_path).execute([plan], "b1")
    assert results[0].success
    assert os.path.exists(tmp_path / "new.pdf")

def test_execute_source_missing(tmp_path):
    plan = RenamePlan("t1", str(tmp_path/"gone.pdf"), SourceFingerprint(0,0), "n.pdf", str(tmp_path), ".pdf")
    r = _make_executor(tmp_path).execute([plan], "b1")
    assert not r[0].success

def test_execute_rejects_escape(tmp_path):
    allowed = tmp_path / "root"; allowed.mkdir()
    src = allowed / "src.pdf"; src.write_text("hello")
    escape = tmp_path / "escape"; escape.mkdir()
    plan = RenamePlan("t1", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), "n.pdf", str(escape), ".pdf")
    ex = RenameExecutor(PreflightService(allowed_roots=[str(allowed)]))
    r = ex.execute([plan], "b1")
    assert not r[0].success

def test_execute_conflict_auto_counter(tmp_path):
    (tmp_path / "n.pdf").write_text("existing")
    src = tmp_path / "src.pdf"; src.write_text("new")
    plan = RenamePlan("t1", str(src), SourceFingerprint(3, src.stat().st_mtime_ns), "n.pdf", str(tmp_path), ".pdf")
    r = _make_executor(tmp_path).execute([plan], "b1")
    assert r[0].success
    assert os.path.exists(tmp_path / "n_1.pdf")

def test_partial_success(tmp_path):
    s1 = tmp_path / "a.pdf"; s1.write_text("a")
    p1 = RenamePlan("t1", str(s1), SourceFingerprint(1, s1.stat().st_mtime_ns), "a_new.pdf", str(tmp_path), ".pdf")
    p2 = RenamePlan("t2", str(tmp_path/"gone.pdf"), SourceFingerprint(0,0), "b_new.pdf", str(tmp_path), ".pdf")
    results = _make_executor(tmp_path).execute([p1, p2], "b1")
    assert results[0].success
    assert not results[1].success

def test_executor_requires_preflight():
    with pytest.raises(ValueError, match="PreflightService"):
        RenameExecutor(None)

def test_cross_volume_move_same_volume(tmp_path):
    src = tmp_path / "a.txt"; src.write_text("x")
    dst = tmp_path / "b.txt"
    st = src.stat()
    result = _safe_move(str(src), str(dst), expected_fingerprint=SourceFingerprint(st.st_size, st.st_mtime_ns),
                        allowed_roots=(str(tmp_path),))
    assert result.success
    assert os.path.exists(dst)
    assert not os.path.exists(src)

def test_unproven_two_path_helper_refuses_without_platform_fallback(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"; src.write_text("x")
    dst = tmp_path / "b.txt"
    calls = []

    def cross_volume(_src, _dst):
        calls.append((_src, _dst))
        raise AssertionError('Unproven platform action')

    def fallback(_src, _dst):
        calls.append((_src, _dst))
        raise AssertionError('Unproven copy fallback')

    monkeypatch.setattr("src.core.rename_executor.os.rename", cross_volume)
    monkeypatch.setattr('shutil.move', fallback)
    result = _safe_move(str(src), str(dst))
    assert not result.success and not result.recovery_required and result.error_code == 'SAFE_MOVE_INVALID_INPUT'
    assert calls == [] and src.read_text() == 'x' and not dst.exists()


def test_execute_does_not_mutate_on_preflight_failure(tmp_path):
    allowed = tmp_path / "root"; allowed.mkdir()
    src = allowed / "src.pdf"; src.write_text("hello")
    # Target outside allowed root
    escape = tmp_path / "escape"; escape.mkdir()
    plan = RenamePlan("t1", str(src), SourceFingerprint(5, src.stat().st_mtime_ns), "n.pdf", str(escape), ".pdf")
    ex = RenameExecutor(PreflightService(allowed_roots=[str(allowed)]))
    r = ex.execute([plan], "b1")
    assert not r[0].success
    assert os.path.exists(src)


def test_history_failure_and_rollback_failure_reports_moved_file(tmp_path, monkeypatch):
    """A double persistence/rollback failure must never pretend the file stayed put."""
    src = tmp_path / "source.txt"
    src.write_text("payload", encoding="utf-8")
    target = tmp_path / "renamed.txt"

    class BrokenHistory:
        def record(self, _record):
            raise OSError("history unavailable")

    real_move = _safe_move
    moves = 0

    def fail_only_rollback(source, destination, **approval):
        nonlocal moves
        moves += 1
        if moves == 1:
            return real_move(source, destination, **approval)
        raise OSError("rollback unavailable")

    monkeypatch.setattr("src.core.rename_executor._safe_move", fail_only_rollback)
    plan = RenamePlan("t1", str(src), SourceFingerprint(7, src.stat().st_mtime_ns),
                      target.name, str(tmp_path), ".txt")
    result = RenameExecutor(PreflightService([str(tmp_path)]), BrokenHistory()).execute([plan], "b1")[0]

    assert result.success is False
    assert result.recovery_required is True
    assert result.new_path == ''
    assert set(result.owned_residue_paths) == {str(src), str(target)}
    assert target.exists() and not src.exists()
    assert result.error == 'fileops.error.nativeRecovery'


def test_sole_changed_fingerprint_preflight_has_fixed_reason_zero_native_calls(tmp_path, monkeypatch):
    import src.core.rename_executor as module
    source, target = tmp_path / 'original.txt', tmp_path / 'renamed.txt'
    source.write_bytes(b'APPROVED')
    stat = source.stat()
    plan = RenamePlan('task', str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                      target.name, str(tmp_path), '.txt')
    source.write_bytes(b'CHANGED_SINCE_SCAN')
    preflight = PreflightService([str(tmp_path)])
    assert preflight.check(plan).errors == ['Source file has changed since scan']
    calls = []
    def forbidden(*args, **approval):
        calls.append((args, approval))
        raise AssertionError('Refused preflight must not call native movement')
    monkeypatch.setattr(module, '_safe_move', forbidden)
    result = RenameExecutor(preflight).execute([plan], 'batch')[0]
    assert not result.success and not result.recovery_required and result.new_path == ''
    assert result.error == 'fileops.error.sourceChanged'
    assert calls == [] and source.read_bytes() == b'CHANGED_SINCE_SCAN' and not target.exists()


@pytest.mark.parametrize('errors', [[], ['Source file does not exist'],
    ['Source file has changed since scan', 'Target path escapes allowed root directories'],
    ['Source file has changed since scan', 'Source file has changed since scan'],
    ('Source file has changed since scan',)])
def test_other_preflight_error_graphs_keep_fixed_unsafe_path(tmp_path, monkeypatch, errors):
    import src.core.rename_executor as module
    from src.core.rename_plan import PreflightResult
    source = tmp_path / 'original.txt'; source.write_bytes(b'APPROVED')
    target = tmp_path / 'renamed.txt'
    stat = source.stat()
    plan = RenamePlan('task', str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                      target.name, str(tmp_path), '.txt')
    class Refusal:
        def check(self, _): return PreflightResult(False, errors=errors)
    calls = []
    monkeypatch.setattr(module, '_safe_move', lambda *args, **kw: calls.append((args, kw)))
    result = RenameExecutor(Refusal()).execute([plan], 'batch')[0]
    assert result.error == 'fileops.error.unsafePath' and not result.success and not result.recovery_required
    assert calls == [] and source.read_bytes() == b'APPROVED' and not target.exists()
