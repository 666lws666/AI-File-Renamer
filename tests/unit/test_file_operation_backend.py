"""Synthetic-file contracts for the worker-only disk adapter."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from src.core.rename_history import RenameHistory
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.services.file_operation_backend import FileOperationBackend, FileOperationRequest


def plan_for(root, task="one", name="original.txt", target="renamed.txt"):
    source = root / name
    source.write_text("synthetic content", encoding="utf-8")
    stat = source.stat()
    return RenamePlan(task, str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                      target, str(root), ".txt")


def test_lazy_real_apply_and_undo(tmp_path):
    history = tmp_path / "not-created" / "history.jsonl"
    backend = FileOperationBackend(history)
    assert not history.parent.exists()
    plan = plan_for(tmp_path)
    request = FileOperationRequest("apply", "apply", "batch", (plan,))
    assert request.item_count == 1
    result = backend.execute_item(request, 0)
    assert (result.task_id, result.batch_id, result.success) == ("one", "batch", True)
    assert result.new_path == str(tmp_path / "renamed.txt")
    assert not Path(plan.source_path).exists()
    with pytest.raises(FrozenInstanceError):
        result.success = False
    undo = backend.execute_item(FileOperationRequest("undo", "undo", task_ids=("one",)), 0)
    assert undo.success and undo.new_path == plan.source_path
    assert Path(plan.source_path).read_text(encoding="utf-8") == "synthetic content"
    assert RenameHistory(history).get_all()[0].undone
    missing = backend.execute_item(FileOperationRequest("missing", "undo", task_ids=("absent",)), 0)
    assert not missing.success and missing.task_id == "absent" and missing.new_path == ""


def test_non_authorizing_observation_failure_preserves_real_success_and_history(tmp_path):
    history = tmp_path / "history.jsonl"
    backend = FileOperationBackend(history)
    phases = []
    def unavailable(phase, *args):
        phases.append(phase)
        raise RuntimeError("synthetic observation unavailable")
    backend.set_move_observer(unavailable)
    plan = plan_for(tmp_path)
    result = backend.execute_item(FileOperationRequest("a", "apply", "batch", (plan,)), 0)
    assert result.success and result.source_identity is not None
    assert RenameHistory(history).get_all()[0].task_id == "one"
    undo = backend.execute_item(FileOperationRequest("u", "undo", task_ids=("one",)), 0)
    assert undo.success and RenameHistory(history).get_all()[0].undone
    assert phases == ["before", "after", "before", "after"]
    assert Path(plan.source_path).read_text(encoding="utf-8") == "synthetic content"


def test_undo_captures_actual_changed_content_fingerprint(tmp_path):
    backend = FileOperationBackend(tmp_path / 'history.jsonl')
    plan = plan_for(tmp_path)
    result = backend.execute_item(FileOperationRequest('a', 'apply', 'b', (plan,)), 0)
    Path(result.new_path).write_text('different synthetic content length', encoding='utf-8')
    undo = backend.execute_item(FileOperationRequest('u', 'undo', task_ids=('one',)), 0)
    actual = Path(plan.source_path).stat()
    assert undo.success and undo.source_fingerprint == SourceFingerprint(actual.st_size, actual.st_mtime_ns)


def test_undo_held_capture_avoids_post_path_stat(tmp_path, monkeypatch):
    import src.services.file_operation_backend as module
    backend = FileOperationBackend(tmp_path / 'history.jsonl')
    plan = plan_for(tmp_path)
    assert backend.execute_item(FileOperationRequest('a', 'apply', 'b', (plan,)), 0).success
    undo = backend._undo.undo_task
    def restored(task):
        result = undo(task)
        monkeypatch.setattr(module.os, 'stat', lambda *_a, **_k: (_ for _ in ()).throw(OSError('private')))
        return result
    monkeypatch.setattr(backend._undo, 'undo_task', restored)
    result = backend.execute_item(FileOperationRequest('u', 'undo', task_ids=('one',)), 0)
    monkeypatch.undo()
    assert result.success and result.new_path == plan.source_path and not result.recovery_required
    assert result.source_fingerprint == SourceFingerprint(Path(plan.source_path).stat().st_size, Path(plan.source_path).stat().st_mtime_ns)
    assert result.source_identity is not None and result.error is None


def test_partial_apply_and_partial_undo_preserve_exact_outcomes(tmp_path):
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    good = plan_for(tmp_path)
    bad = plan_for(tmp_path, "two", "second.txt", "other.txt")
    Path(bad.source_path).unlink()
    request = FileOperationRequest("apply", "apply", "batch", (good, bad))
    results = tuple(backend.execute_item(request, i) for i in range(2))
    assert [r.success for r in results] == [True, False]
    Path(good.source_path).write_text("occupied", encoding="utf-8")
    undo = FileOperationRequest("undo", "undo", task_ids=("one", "two"))
    results = tuple(backend.execute_item(undo, i) for i in range(2))
    assert [r.task_id for r in results] == ["one", "two"]
    assert not any(r.success for r in results)
    assert (tmp_path / "renamed.txt").exists()
    assert not RenameHistory(tmp_path / "history.jsonl").get_all()[0].undone


def test_f0_undo_marker_failure_preserves_physical_success(tmp_path, monkeypatch):
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    plan = plan_for(tmp_path)
    assert backend.execute_item(FileOperationRequest("a", "apply", "batch", (plan,)), 0).success
    def fail(*args):
        raise OSError("synthetic save failure")
    monkeypatch.setattr(RenameHistory, "mark_records_undone", fail)
    result = backend.execute_item(FileOperationRequest("u", "undo", task_ids=("one",)), 0)
    assert result.success and result.recovery_required and result.new_path == plan.source_path
    assert result.error == 'fileops.error.historySaveRecovery'
    assert Path(plan.source_path).exists() and not (tmp_path / "renamed.txt").exists()


def test_partial_undo_keeps_success_and_failure_in_requested_order(tmp_path):
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    one = plan_for(tmp_path)
    two = plan_for(tmp_path, "two", "second.txt", "other.txt")
    apply = FileOperationRequest("a", "apply", "batch", (one, two))
    assert all(backend.execute_item(apply, i).success for i in range(2))
    Path(two.source_path).write_text("occupied", encoding="utf-8")
    undo = FileOperationRequest("u", "undo", task_ids=("two", "one"))
    results = tuple(backend.execute_item(undo, i) for i in range(2))
    assert [(r.task_id, r.success) for r in results] == [("two", False), ("one", True)]
    assert Path(one.source_path).read_text(encoding="utf-8") == "synthetic content"
    records = RenameHistory(tmp_path / "history.jsonl").get_all()
    assert [(r.task_id, r.undone) for r in records] == [("one", True), ("two", False)]


def test_apply_history_failure_rollback_and_uncertain_recovery(tmp_path, monkeypatch):
    import src.core.rename_executor as engine
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    one = plan_for(tmp_path)
    def history_fail(*args):
        raise OSError("synthetic history failure")
    monkeypatch.setattr(RenameHistory, "record", history_fail)
    result = backend.execute_item(FileOperationRequest("a", "apply", "b", (one,)), 0)
    assert not result.success and result.new_path == "" and not result.recovery_required
    assert Path(one.source_path).exists()
    two = plan_for(tmp_path, "two", "second.txt", "other.txt")
    move = engine._safe_move
    def fail_only_rollback(source, target, **approval):
        if source == str(tmp_path / "other.txt"):
            raise OSError("synthetic rollback failure")
        return move(source, target, **approval)
    monkeypatch.setattr(engine, "_safe_move", fail_only_rollback)
    result = backend.execute_item(FileOperationRequest("b", "apply", "batch", (two,)), 0)
    assert not result.success and result.recovery_required and result.new_path == ''
    assert set(result.owned_residue_paths) == {two.source_path, str(tmp_path/'other.txt')}
    assert not Path(two.source_path).exists() and (tmp_path/'other.txt').exists()


@pytest.mark.parametrize("changes", [
    {"kind": "other"}, {"operation_id": ""}, {"operation_id": "x" * 257},
    {"batch_id": ""}, {"plans": []}, {"plans": ()}, {"task_ids": ("one",)},
    {"plans": (object(),)}, {"plans": tuple([None] * 1001)},
])
def test_request_rejects_invalid_values(tmp_path, changes):
    plan = plan_for(tmp_path)
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        FileOperationRequest(**({"operation_id": "a", "kind": "apply", "batch_id": "b", "plans": (plan,)} | changes))


@pytest.mark.parametrize("changes", [
    {"task_id": ""}, {"source_path": "x" * 4097}, {"target_name": "x" * 257},
    {"target_parent": object()}, {"source_fingerprint": object()},
    {"source_fingerprint": SourceFingerprint(True, 1)}, {"extension": lambda: None},
    {"batch_id": object()},
])
def test_request_revalidates_pure_frozen_plans(tmp_path, changes):
    plan = replace(plan_for(tmp_path), **changes)
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        FileOperationRequest("a", "apply", "b", (plan,))


@pytest.mark.parametrize("tasks", [(), ["one"], ("one", "one"), (object(),), ("",), ("x" * 257,)])
def test_undo_validation(tasks):
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        FileOperationRequest("a", "undo", task_ids=tasks)


def root_request(plan, roots, **changes):
    assert "allowed_roots" in FileOperationRequest.__dataclass_fields__, "explicit immutable apply roots missing"
    values = dict(operation_id="root-apply", kind="apply", batch_id="roots-batch",
                  plans=(plan,), allowed_roots=roots)
    values.update(changes)
    return FileOperationRequest(**values)


@pytest.mark.parametrize("roots", [["root"], "root", ("root", "root"), ("",), (" ",),
    (True,), (object(),), ("bad\x00root",), ("x" * 4097,), tuple(str(i) for i in range(2001))])
def test_apply_root_graph_rejects_invalid_exact_values(tmp_path, roots):
    plan = plan_for(tmp_path)
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        root_request(plan, roots)
    assert Path(plan.source_path).read_text(encoding="utf-8") == "synthetic content"
    assert not (tmp_path / "renamed.txt").exists()


def test_explicit_roots_exact_tuple_frozen_bound_and_revalidation(tmp_path):
    from src.services.file_operation_backend import validate_request
    plan = plan_for(tmp_path)
    roots = tuple("approved-" + str(i) for i in range(2000))
    request = root_request(plan, roots)
    assert request.allowed_roots is roots
    with pytest.raises(FrozenInstanceError): request.allowed_roots = ()
    object.__setattr__(request, "allowed_roots", ["root"])
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"): validate_request(request)


def test_undo_rejects_apply_roots_even_valid_strings(tmp_path):
    plan = plan_for(tmp_path)
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        root_request(plan, (str(tmp_path),), kind="undo", batch_id="", plans=(), task_ids=("one",))


def test_explicit_roots_passed_unchanged_and_allow_missing_nested_target(tmp_path, monkeypatch):
    import src.services.file_operation_backend as module
    source_root, target_root = tmp_path / "source", tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    plan = replace(plan_for(source_root), target_parent=str(target_root / "Project"))
    roots = (str(source_root), str(target_root))
    request = root_request(plan, roots)
    observed = []
    original = module.PreflightService
    def preflight(*args, **kwargs):
        if "allowed_roots" in kwargs: observed.append(kwargs["allowed_roots"])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "PreflightService", preflight)
    result = FileOperationBackend(tmp_path / "history.json").execute_item(request, 0)
    assert observed == [roots] and observed[0] is request.allowed_roots
    assert result.success and result.new_path == str(target_root / "Project" / "renamed.txt")
    assert Path(result.new_path).read_text(encoding="utf-8") == "synthetic content"
    assert not Path(plan.source_path).exists()


@pytest.mark.parametrize("authorized_source", [False, True])
def test_supplied_unrelated_roots_never_widen_to_plan_parents(tmp_path, authorized_source):
    source_root, approved_root, outside = tmp_path / "source", tmp_path / "approved", tmp_path / "outside"
    for root in (source_root, approved_root, outside): root.mkdir()
    plan = replace(plan_for(source_root), target_parent=str(outside))
    roots = (str(source_root), str(approved_root)) if authorized_source else (str(approved_root),)
    result = FileOperationBackend(tmp_path / "history.json").execute_item(root_request(plan, roots), 0)
    assert not result.success and result.new_path == ""
    assert Path(plan.source_path).read_text(encoding="utf-8") == "synthetic content"
    assert not (outside / "renamed.txt").exists()
    assert not (tmp_path / "history.json").exists()


@pytest.mark.parametrize('changes', [
    {'task_id': []}, {'task_id': ''}, {'batch_id': {}}, {'success': 1},
    {'recovery_required': 1}, {'error': {}}, {'new_path': ['bad']},
    {'new_path': {'bad': 'path'}}, {'new_path': None}, {'new_path': 'bad\x00path'},
    {'new_path': 'x' * 4097}, {'new_path': ''},
])
def test_complete_outcome_basic_fields_refuse_before_capture_or_hashing(tmp_path, changes):
    from src.services.file_operation_backend import validate_outcome_evidence
    backend = FileOperationBackend(tmp_path / 'history.jsonl')
    plan = plan_for(tmp_path)
    capture = backend.execute_item(FileOperationRequest('a', 'apply', 'b', (plan,)), 0)
    assert capture.success and capture.source_identity is not None
    malformed = replace(capture, **changes)
    with pytest.raises(ValueError, match='^invalid_file_operation_outcome$'):
        validate_outcome_evidence(malformed)
    assert Path(capture.new_path).read_text() == 'synthetic content'


@pytest.mark.parametrize('field', ['task_id', 'batch_id', 'success', 'error', 'new_path',
    'recovery_required', 'source_fingerprint', 'source_identity', 'owned_residue_paths'])
def test_deleted_outcome_field_is_not_defaulted_to_a_valid_graph(tmp_path, field):
    from src.services.file_operation_backend import validate_outcome_evidence
    backend = FileOperationBackend(tmp_path / 'history.jsonl')
    plan = plan_for(tmp_path)
    capture = backend.execute_item(FileOperationRequest('a', 'apply', 'b', (plan,)), 0)
    object.__delattr__(capture, field)
    with pytest.raises(ValueError, match='^invalid_file_operation_outcome$'):
        validate_outcome_evidence(capture)
