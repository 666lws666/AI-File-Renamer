"""M2 Task 2: NamingFields + RenamePlan — pure data, no I/O."""
import pytest
from src.core.naming_fields import NamingFields
from src.core.rename_plan import RenamePlan, SourceFingerprint, PreflightResult, BatchResult

def test_naming_fields_from_json():
    import json
    data = json.loads('{"dcDate":"2025-01-15","dcTitle":"Test Report","dcType":"report"}')
    nf = NamingFields(**data)
    assert nf.dcDate == "2025-01-15"
    assert nf.dcTitle == "Test Report"
    assert nf.dcType == "report"
    assert nf.dcCreator is None

def test_naming_fields_optional_defaults():
    nf = NamingFields()
    assert nf.dcDate is None
    assert nf.dcTitle is None

def test_naming_fields_immutable():
    nf = NamingFields(dcTitle="x")
    with pytest.raises(Exception):
        nf.dcTitle = "y"

def test_rename_plan_is_immutable():
    rp = RenamePlan("t1", "/src/a.pdf", SourceFingerprint(100, 200), "new.pdf", "/dst", ".pdf")
    with pytest.raises(Exception):
        rp.task_id = "t2"

def test_rename_plan_no_execute_method():
    rp = RenamePlan("t1", "/src/a.pdf", SourceFingerprint(100, 200), "new.pdf", "/dst", ".pdf")
    assert not hasattr(rp, "execute")
    assert not hasattr(rp, "apply")
    assert not hasattr(rp, "undo")

def test_rename_plan_no_import_of_os_rename():
    import inspect, re
    src = inspect.getsource(RenamePlan)
    assert "os.rename" not in src
    assert "shutil.move" not in src
    assert "open(" not in src

def test_rename_plan_construction_has_no_io():
    # Prove construction doesn't hit the filesystem
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        nonexistent = os.path.join(td, "does_not_exist.pdf")
        rp = RenamePlan("t1", nonexistent, SourceFingerprint(0, 0), "n.pdf", td, ".pdf")
        assert rp.target_path.startswith(td)

def test_batch_result_records_per_task():
    r1 = BatchResult("t1", "b1", True, new_path="/dst/a.pdf")
    r2 = BatchResult("t2", "b1", False, error="Permission denied")
    assert r1.success and not r2.success
    assert r1.task_id == "t1" and r2.task_id == "t2"

def test_preflight_result_pure_data():
    pr = PreflightResult(can_execute=False, errors=["invalid name"], warnings=["long path"])
    assert not pr.can_execute
    assert pr.errors == ["invalid name"]


def test_evidence_transport_fields_append_compatible_defaults():
    result = BatchResult('task', 'batch', False)
    assert getattr(result, 'move_evidence', 'missing') is None
    assert getattr(result, 'source_fingerprint', 'missing') is None
    assert getattr(result, 'owned_residue_paths', None) == ()
    assert getattr(PreflightResult(True), 'allowed_roots', None) == ()
