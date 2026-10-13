"""M2 P0: Preflight path boundary tests."""
import os, pytest, tempfile
from pathlib import Path
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.core.preflight_service import PreflightService

def _plan(src, target_parent, target_name, ext=".pdf"):
    import os
    st = os.stat(src)
    return RenamePlan("t1", src, SourceFingerprint(st.st_size, st.st_mtime_ns), target_name, target_parent, ext)

def test_target_inside_allowed_root_passes(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    src = root / "src.pdf"; src.write_text("hello")
    ps = PreflightService(allowed_roots=[str(root)])
    plan = _plan(str(src), str(root), "new.pdf")
    r = ps.check(plan)
    assert r.can_execute

def test_sibling_prefix_escape_rejected(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    escape = tmp_path / "root-escape"; escape.mkdir()
    src = root / "src.pdf"; src.write_text("hello")
    ps = PreflightService(allowed_roots=[str(root)])
    plan = _plan(str(src), str(escape), "new.pdf")
    r = ps.check(plan)
    assert not r.can_execute

def test_dotdot_escape_rejected(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    src = root / "src.pdf"; src.write_text("hello")
    ps = PreflightService(allowed_roots=[str(root)])
    plan = _plan(str(src), str(root / "sub"), "../new.pdf")
    r = ps.check(plan)
    assert not r.can_execute

def test_missing_allowed_roots_fail_closed(tmp_path):
    src = tmp_path / "src.pdf"; src.write_text("hello")
    ps = PreflightService(allowed_roots=[])
    plan = _plan(str(src), str(tmp_path), "new.pdf")
    r = ps.check(plan)
    assert not r.can_execute

def test_preflight_performs_no_mutation(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    src = root / "src.pdf"; src.write_text("hello")
    before = set(str(p) for p in tmp_path.rglob("*"))
    ps = PreflightService(allowed_roots=[str(root)])
    plan = _plan(str(src), str(root / "sub"), "new.pdf")
    ps.check(plan)
    after = set(str(p) for p in tmp_path.rglob("*"))
    assert before == after

def test_source_outside_allowed_root_rejected(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    src = outside / "src.pdf"; src.write_text("hello")
    ps = PreflightService(allowed_roots=[str(root)])
    plan = _plan(str(src), str(root), "new.pdf")
    r = ps.check(plan)
    assert not r.can_execute


def test_preflight_root_collection_is_frozen_and_lexically_deduplicated(tmp_path):
    src = tmp_path / 'source.pdf'; src.write_bytes(b'APPROVED')
    caller = [str(tmp_path), str(tmp_path).replace('\\', '/').upper()]
    service = PreflightService(caller)
    caller.clear()
    result = service.check(_plan(str(src), str(tmp_path), 'new.pdf'))
    assert result.can_execute
    assert getattr(result, 'allowed_roots', None) == (str(tmp_path),)


def test_watch_configs_snapshot_is_evaluated_once(tmp_path):
    from src.core.preflight_service import WatchPreflightService
    from types import SimpleNamespace
    src = tmp_path / 'source.pdf'; src.write_bytes(b'APPROVED')
    calls = []
    def configs():
        calls.append(True)
        return [SimpleNamespace(source_dir=str(tmp_path), target_dir=str(tmp_path))]
    result = WatchPreflightService(configs).check(_plan(str(src), str(tmp_path), 'new.pdf'))
    assert calls == [True] and result.can_execute
    assert getattr(result, 'allowed_roots', None) == (str(tmp_path),)
