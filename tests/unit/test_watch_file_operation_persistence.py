"""Explicit durable intents and atomic identity-based review transitions."""
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json

import pytest

from src.core.watch_review_queue import ReviewItem, ReviewItemState, ReviewQueue, ReviewQueueError
from tests.unit.test_managed_watch_persistence import inject_store_write_fault


def intent(**changes):
    cls = getattr(importlib.import_module("src.core.watch_review_queue"), "WatchFileOperationIntent", None)
    assert cls is not None, "schema3 requires an explicit frozen file-operation intent"
    values = dict(version=1, operation_id="operation", kind="apply", batch_id="batch",
                  source_path="C:/synthetic/source.txt", target_path="C:/synthetic/target.txt")
    values.update(changes)
    return cls(**values)


def row(name="one", **changes):
    values = dict(id=name, watch_id="watch", source_path=f"C:/synthetic/{name}.txt",
                  size_bytes=4, mtime_ns=12, extension=".txt", display_name=name,
                  state=ReviewItemState.AWAITING_APPROVAL)
    values.update(changes)
    return ReviewItem(**values)


def cas(queue, changes):
    call = getattr(queue, "replace_many", None)
    assert callable(call), "review transitions require atomic exact-object compare-and-replace"
    return call(changes)


def test_schema3_roundtrip_frozen_intent_and_undone(tmp_path):
    marker = intent()
    assert marker.__dataclass_params__.frozen
    queue = ReviewQueue(tmp_path / "queue.json")
    saved = queue.add(row(state=ReviewItemState.APPLYING, file_operation=marker,
                          applied_path="", recovery_required=True))
    payload = json.loads(queue._file_path.read_bytes())
    assert payload["schema_version"] == 3
    assert payload["items"][0]["file_operation"] == {key:value for key,value in marker.__dict__.items()
        if key not in {'known_result_path', 'owned_residue_paths', 'recovery_reason'}}
    assert ReviewQueue(queue._file_path).get(saved.id) == saved
    undone = getattr(ReviewItemState, "UNDONE", None)
    assert undone is not None and undone.value == "undone"
    current, = cas(queue, ((saved, replace(saved, state=undone, file_operation=None,
                                         recovery_required=False)),))
    assert current is queue.get(saved.id)
    assert ReviewQueue(queue._file_path).get(saved.id) == current


@pytest.mark.parametrize("schema", [1, 2])
def test_old_schema_read_only_neutral_defaults_then_migrate(tmp_path, schema):
    path = tmp_path / "queue.json"
    values = row().__dict__.copy()
    values["state"] = "applied"
    values.pop("managed_metadata")
    for name in ("file_operation", "applied_path", "recovery_required"):
        values.pop(name, None)
    original = json.dumps(dict(schema_version=schema, items=[values])).encode()
    path.write_bytes(original)
    queue = ReviewQueue(path)
    old = queue.get("one")
    assert getattr(old, "file_operation", "missing") is None
    assert old.applied_path == "" and old.recovery_required is False
    assert path.read_bytes() == original
    saved, = cas(queue, ((old, replace(old, error_category="interrupted")),))
    assert saved is queue.get("one") and json.loads(path.read_bytes())["schema_version"] == 3


@pytest.mark.parametrize("fault", ["mkdir", "temp", "write", "fsync", "replace"])
def test_multirow_fault_preserves_all_identities_and_bytes(tmp_path, monkeypatch, fault):
    queue = ReviewQueue(tmp_path / "queue.json")
    first, second = queue.add(row()), queue.add(row("two"))
    before = queue._file_path.read_bytes()
    inject_store_write_fault(monkeypatch, ReviewQueue, fault)
    with pytest.raises(ReviewQueueError, match="^review queue write failed$"):
        cas(queue, ((first, replace(first, state=ReviewItemState.APPLYING)),
                    (second, replace(second, state=ReviewItemState.APPLYING))))
    assert queue.get(first.id) is first and queue.get(second.id) is second
    assert queue._file_path.read_bytes() == before
    assert not list(tmp_path.glob("review_queue_*.tmp"))


@pytest.mark.parametrize("bad", ["clone", "duplicate", "invalid_later", "changed_id", "list"])
def test_complete_cas_validation_no_partial_changes(tmp_path, bad):
    queue = ReviewQueue(tmp_path / "queue.json")
    first, second = queue.add(row()), queue.add(row("two"))
    changes = ((first, replace(first, state=ReviewItemState.APPLYING)),
               (second, replace(second, state=ReviewItemState.APPLYING)))
    if bad == "clone": changes = ((replace(first), changes[0][1]),)
    elif bad == "duplicate": changes = (changes[0], changes[0])
    elif bad == "invalid_later": changes = (changes[0], (second, replace(second, size_bytes=True)))
    elif bad == "changed_id": changes = ((first, replace(first, id="other")),)
    else: changes = list(changes)
    before = queue._file_path.read_bytes()
    with pytest.raises(ReviewQueueError): cas(queue, changes)
    assert queue._file_path.read_bytes() == before
    assert queue.get(first.id) is first and queue.get(second.id) is second


def test_clock_reentrant_replacement_checked_after_timestamp_preparation(tmp_path):
    queue = ReviewQueue(tmp_path / "queue.json")
    first = queue.add(row())
    replacement = []
    def clock():
        queue._clock = lambda: datetime.now(timezone.utc)
        replacement.append(queue.update(replace(first, suggested_name="changed.txt")))
        return datetime.now(timezone.utc)
    queue._clock = clock
    with pytest.raises(ReviewQueueError):
        cas(queue, ((first, replace(first, state=ReviewItemState.APPLYING)),))
    assert queue.get(first.id) is replacement[0]
    assert ReviewQueue(queue._file_path).get(first.id) == replacement[0]


@pytest.mark.parametrize("field,value", [("version", True), ("version", 2), ("operation_id", ""),
    ("operation_id", "x" * 257), ("kind", "auto"), ("batch_id", ""),
    ("source_path", "x" * 4097), ("target_path", "bad\x00path")])
def test_invalid_intent_rejected_before_disk(tmp_path, field, value):
    queue = ReviewQueue(tmp_path / "queue.json")
    marker = intent(**{field: value})
    with pytest.raises(ReviewQueueError): queue.add(row(file_operation=marker))
    assert not queue._file_path.exists() and not queue.items()


@pytest.mark.parametrize("bad", ["future", "duplicate", "intent_extra", "intent_shape", "recovery_bool",
    "applied_type", "old_intent", "missing_new_field"])
def test_malformed_complete_load_keeps_prior_memory_and_bytes(tmp_path, bad):
    path = tmp_path / "queue.json"
    queue = ReviewQueue(path)
    queue.add(row(file_operation=intent(), state=ReviewItemState.APPLYING))
    payload = json.loads(path.read_bytes())
    record = payload["items"][0]
    if bad == "future": payload["schema_version"] = 4
    elif bad == "duplicate": payload["items"].append(dict(record))
    elif bad == "intent_extra": record["file_operation"]["secret"] = "PRIVATE_SENTINEL"
    elif bad == "intent_shape": record["file_operation"] = []
    elif bad == "recovery_bool": record["recovery_required"] = 1
    elif bad == "applied_type": record["applied_path"] = False
    elif bad == "old_intent": payload["schema_version"] = 2
    else: record.pop("recovery_required")
    path.write_text(json.dumps(payload), encoding="utf-8")
    before, memory = path.read_bytes(), queue._items
    with pytest.raises(ReviewQueueError) as error: queue._load()
    assert "PRIVATE_SENTINEL" not in str(error.value)
    assert queue._items is memory and path.read_bytes() == before


def test_nested_version2_recovery_graph_roundtrip(tmp_path):
    assert 'known_result_path' in intent().__dataclass_fields__, 'version2 recovery evidence missing'
    marker = intent(version=2, known_result_path='C:/synthetic/target_1.txt',
        owned_residue_paths=('C:/synthetic/source.txt', 'C:/synthetic/target_1.txt', 'C:/synthetic/.guard'),
        recovery_reason='fileops.error.nativeRecovery')
    queue = ReviewQueue(tmp_path/'queue.json')
    saved = queue.add(row(file_operation=marker, recovery_required=True, state=ReviewItemState.APPLYING))
    graph = json.loads(queue._file_path.read_bytes())['items'][0]['file_operation']
    assert graph['version'] == 2 and type(graph['owned_residue_paths']) is list
    assert ReviewQueue(queue._file_path).get(saved.id) == saved


@pytest.mark.parametrize('field,value', [('known_result_path', None), ('owned_residue_paths', []),
    ('owned_residue_paths', ('duplicate', 'duplicate')), ('owned_residue_paths', tuple(str(i) for i in range(9))),
    ('owned_residue_paths', ('x'*4097,)), ('owned_residue_paths', ('nul\x00path',)),
    ('recovery_reason', 'PRIVATE_NATIVE_ERROR')])
def test_version2_malformed_recovery_graph_refuses_before_save(tmp_path, field, value):
    assert 'known_result_path' in intent().__dataclass_fields__, 'version2 recovery evidence missing'
    marker = intent(version=2, recovery_reason='fileops.error.nativeRecovery', **{field:value}) if field != 'recovery_reason' else intent(version=2, recovery_reason=value)
    queue = ReviewQueue(tmp_path/'queue.json')
    with pytest.raises(ReviewQueueError): queue.add(row(file_operation=marker))
    assert not queue._file_path.exists()


@pytest.mark.parametrize('tamper', ['future', 'partial', 'extra', 'coerced', 'duplicate', 'merged_overflow'])
def test_version2_tampered_reload_preserves_original_bytes(tmp_path, tamper):
    path = tmp_path / 'queue.json'
    queue = ReviewQueue(path)
    marker = intent(version=2, known_result_path='C:/synthetic/target_1.txt',
        owned_residue_paths=('C:/synthetic/target_1.txt',),
        recovery_reason='fileops.error.nativeRecovery')
    saved = queue.add(row(file_operation=marker, recovery_required=True))
    graph = json.loads(path.read_bytes())
    nested = graph['items'][0]['file_operation']
    if tamper == 'future': nested['version'] = 3
    elif tamper == 'partial': nested.pop('known_result_path')
    elif tamper == 'extra': nested['unrecognized'] = 'PRIVATE'
    elif tamper == 'coerced': nested['version'] = '2'
    elif tamper == 'duplicate': nested['owned_residue_paths'] *= 2
    else: nested['owned_residue_paths'] = [f'C:/synthetic/residue-{i}' for i in range(8)]
    path.write_text(json.dumps(graph), encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ReviewQueueError): queue._load()
    assert queue.get(saved.id) is saved and path.read_bytes() == before
