"""Store compatibility facts only: no Watch activation or analysis authority."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import pytest

from src.core.watch_review_queue import ReviewItem, ReviewItemState, ReviewQueue, ReviewQueueError
from src.controllers.auto_apply_handler import AutoApplyJournal, AutoApplyJournalError, _JournalEntry
from src.core.managed_watch_metadata import ManagedWatchMetadata, encode_managed_metadata
from src.services.local_ai.preparation_protocol import PreparationCoverage


def metadata(kind="text"):
    coverage = {
        "text": PreparationCoverage("text", sections_processed=1, sections_total=1),
        "image": PreparationCoverage("image", text_source="none"),
        "scanned_pdf": PreparationCoverage("scanned_pdf", text_source="none", pdf_total_pages=2,
            sections_total=2, rendered_page_indices=(0, 1)),
        "video": PreparationCoverage("video", text_source="none", video_duration_seconds=10.0,
            video_timestamps_seconds=tuple(float(i) for i in range(6))),
    }[kind]
    return ManagedWatchMetadata(kind, "balanced", "balanced", coverage,
        ("video_sampled",) if kind == "video" else ())


def review(**kw):
    fields = dict(id="item-id", watch_id="watch-id", source_path="C:/synthetic/source.txt",
        size_bytes=123, mtime_ns=456, extension=".txt", display_name="source.txt",
        state=ReviewItemState.AWAITING_APPROVAL, suggested_name="reviewed.txt",
        target_parent="C:/synthetic/target", confidence=None, content_kind="text",
        error_category="", batch_id="batch-id", created_at_utc="created", updated_at_utc="updated")
    fields.update(kw)
    return ReviewItem(**fields)


def journal(**kw):
    fields = dict(key="watch-id\x00C:/synthetic/source.txt", fingerprint=(123, 456),
        state="applied", suggested_name="reviewed.txt", target_parent="C:/synthetic/target",
        extension=".txt", batch_id="batch-id", error_category="")
    fields.update(kw)
    return _JournalEntry(**fields)


def legacy_payload(store_kind):
    if store_kind == "queue":
        return {"schema_version": 1, "items": [dict(id="legacy", watch_id="watch-id",
            source_path="C:/legacy.txt", size_bytes=7, mtime_ns=8, state="pending", confidence=0.73)]}
    return {"schema_version": 1, "entries": [dict(key="watch-id\x00C:/legacy.txt",
        size=7, mtime_ns=8, state="held", batch_id="legacy-batch")]}


def store_parts(kind):
    return ((ReviewQueue, ReviewQueueError, "items") if kind == "queue"
            else (AutoApplyJournal, AutoApplyJournalError, "entries"))


def inject_store_write_fault(monkeypatch, store_class, fault):
    """Fail one atomic-write stage while exercising the real store operation."""
    module = __import__(store_class.__module__, fromlist=["os"])

    def fail(*args, **kwargs):
        raise OSError("PRIVATE_INPUT must stay internal")

    if fault == "mkdir":
        monkeypatch.setattr(Path, "mkdir", fail)
    elif fault == "temp":
        monkeypatch.setattr(module.tempfile, "mkstemp", fail)
    elif fault == "write":
        original_fdopen = module.os.fdopen

        class FailedWrite:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            write = fail

        monkeypatch.setattr(module.os, "fdopen",
            lambda *args, **kwargs: FailedWrite(original_fdopen(*args, **kwargs)))
    else:
        monkeypatch.setattr(module.os, fault, fail)


@pytest.mark.parametrize("kind", ["text", "image", "scanned_pdf", "video"])
def test_actual_stores_roundtrip_all_record_facts_with_explicit_metadata(tmp_path, kind):
    meta = metadata(kind)
    qpath, jpath = tmp_path / "queue.json", tmp_path / "journal.json"
    item = review(content_kind=kind, managed_metadata=meta)
    before = replace(item)
    saved = ReviewQueue(qpath).add(item)
    entry = journal(managed_metadata=meta)
    AutoApplyJournal(jpath).put(entry)
    assert ReviewQueue(qpath).get(item.id) == saved
    assert AutoApplyJournal(jpath).get("watch-id", item.source_path) == entry
    assert item == before and saved.confidence is None
    for path, collection in ((qpath, "items"), (jpath, "entries")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == (3 if collection == "items" else 2)
        record = raw[collection][0]
        assert record["managed_metadata"] == encode_managed_metadata(meta)
        assert record["suggested_name"] == "reviewed.txt"
        encoded = json.dumps(record["managed_metadata"])
        for sentinel in ("source_path", "suggested_name", "prompt", "credential", "runtime",
                         "AnalysisWork", "WorkContext", "C:/synthetic", "PRIVATE_INPUT"):
            assert sentinel not in encoded
    assert "confidence" not in json.loads(jpath.read_text())["entries"][0]


def test_pending_none_and_legacy_numeric_are_distinct(tmp_path):
    path = tmp_path / "queue.json"
    queue = ReviewQueue(path)
    unknown = queue.add(review(state=ReviewItemState.PENDING))
    numeric = queue.add(review(id="numeric", confidence=0.0))
    loaded = ReviewQueue(path)
    assert loaded.get(unknown.id).confidence is None
    assert loaded.get(numeric.id).confidence == 0.0


@pytest.mark.parametrize("kind", ["queue", "journal"])
def test_schema1_open_is_read_only_and_successful_mutation_migrates(tmp_path, monkeypatch, kind):
    cls, _, collection = store_parts(kind)
    path = tmp_path / "store.json"
    original = json.dumps(legacy_payload(kind)).encode()
    path.write_bytes(original)
    with monkeypatch.context() as guard:
        def deny(*args, **kwargs):
            raise AssertionError("opening a store must not write")
        guard.setattr(cls, "_save_locked", deny)
        store = cls(path)
    assert path.read_bytes() == original
    if kind == "queue":
        assert store.get("legacy").confidence == 0.73
        assert store.get("legacy").extension == ""
        store.add(review(managed_metadata=metadata()))
        assert store.get("legacy").confidence == 0.73
    else:
        assert store.get("watch-id", "C:/legacy.txt").batch_id == "legacy-batch"
        store.put(journal(managed_metadata=metadata()))
    payload = json.loads(path.read_bytes())
    assert payload["schema_version"] == (3 if kind == "queue" else 2) and len(payload[collection]) == 2


@pytest.mark.parametrize("kind", ["queue", "journal"])
@pytest.mark.parametrize("fault", ["mkdir", "temp", "write", "fsync", "replace"])
@pytest.mark.parametrize("schema", [1, 2])
def test_atomic_failures_preserve_old_bytes_and_memory(tmp_path, monkeypatch, kind, fault, schema):
    cls, error, _ = store_parts(kind)
    path = tmp_path / "store.json"
    if schema == 1:
        path.write_text(json.dumps(legacy_payload(kind)), encoding="utf-8")
    store = cls(path)
    if schema == 2:
        if kind == "queue":
            store.add(review(managed_metadata=metadata()))
        else:
            store.put(journal(managed_metadata=metadata()))
    old_bytes = path.read_bytes()
    old_memory = dict(store._items if kind == "queue" else store._entries)
    inject_store_write_fault(monkeypatch, cls, fault)
    with pytest.raises(error, match="^(review queue write failed|auto apply journal write failed)$"):
        if kind == "queue":
            store.add(review(managed_metadata=metadata(), suggested_name="replacement.txt"))
        else:
            store.put(journal(managed_metadata=metadata(), suggested_name="replacement.txt"))
    assert path.read_bytes() == old_bytes
    assert (store._items if kind == "queue" else store._entries) == old_memory


@pytest.mark.parametrize("operation", ["update", "remove"])
@pytest.mark.parametrize("fault", ["mkdir", "temp", "write", "fsync", "replace"])
def test_review_update_remove_rollback(tmp_path, monkeypatch, operation, fault):
    path = tmp_path / "queue.json"
    queue = ReviewQueue(path)
    saved = queue.add(review(managed_metadata=metadata()))
    before = path.read_bytes()
    inject_store_write_fault(monkeypatch, ReviewQueue, fault)
    with pytest.raises(ReviewQueueError, match="^review queue write failed$"):
        if operation == "update": queue.update(replace(saved, suggested_name="changed.txt"))
        else: queue.remove(saved.id)
    assert queue.get(saved.id) is saved and path.read_bytes() == before


def test_review_existing_empty_id_generation_persists_nonempty_id(tmp_path):
    queue = ReviewQueue(tmp_path / "queue.json")
    item = review(id="", confidence=0.0)
    saved = queue.add(item)
    assert saved.id and item.id == ""
    assert ReviewQueue(queue._file_path).get(saved.id) == saved


@pytest.mark.parametrize("confidence", [True, float("nan"), float("inf"), -0.1, 1.1, "0.5", object()])
def test_invalid_confidence_fails_safely_before_io(tmp_path, confidence):
    queue = ReviewQueue(tmp_path / "missing" / "queue.json")
    with pytest.raises(ReviewQueueError, match="^review queue write failed$"):
        queue.add(review(confidence=confidence))
    assert queue.count() == 0 and not queue._file_path.parent.exists()


@pytest.mark.parametrize("kind", ["queue", "journal"])
@pytest.mark.parametrize("bad", ["dict", "numeric", "mismatch", "foreign", "shape"])
def test_invalid_records_rejected_without_disk_changes(tmp_path, kind, bad):
    cls, error, _ = store_parts(kind)
    path = tmp_path / "store.json"
    path.write_text(json.dumps(legacy_payload(kind)), encoding="utf-8")
    store = cls(path)
    before = path.read_bytes()
    record = review(managed_metadata=metadata()) if kind == "queue" else journal(managed_metadata=metadata())
    if bad == "dict": record = replace(record, managed_metadata=encode_managed_metadata(metadata()))
    elif bad == "numeric":
        if kind == "queue": record = replace(record, confidence=0.9)
        else: record = replace(record, managed_metadata={"confidence": 0.9})
    elif bad == "mismatch":
        if kind == "queue": record = replace(record, content_kind="image")
        else: record = replace(record, fingerprint=(True, 2))
    elif bad == "foreign": record = object()
    else: record = replace(record, suggested_name=12)
    with pytest.raises(error, match="^(review queue write failed|auto apply journal write failed)$"):
        if kind == "queue": store.add(record)
        else: store.put(record)
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["queue", "journal"])
@pytest.mark.parametrize("bad", ["bool_version", "future", "duplicate", "later_shape", "schema1_metadata",
    "metadata_secret", "metadata_path", "missing_id", "bool_fingerprint", "negative_fingerprint", "state", "optional_type"])
def test_load_complete_candidate_is_fail_closed(tmp_path, kind, bad):
    cls, error, collection = store_parts(kind)
    payload = legacy_payload(kind)
    first = payload[collection][0]
    if bad == "bool_version": payload["schema_version"] = True
    elif bad == "future": payload["schema_version"] = 4 if kind == "queue" else 3
    elif bad == "duplicate": payload[collection].append(dict(first))
    elif bad == "later_shape": payload[collection].append({"secret": "PRIVATE_INPUT"})
    elif bad == "schema1_metadata": first["managed_metadata"] = None
    elif bad.startswith("metadata_"):
        payload["schema_version"] = 2
        first["managed_metadata"] = encode_managed_metadata(metadata())
        if kind == "queue": first.update(confidence=None, content_kind="text")
        if bad == "metadata_secret": first["managed_metadata"]["secret"] = "PRIVATE_INPUT"
        else: first["managed_metadata"]["coverage"]["source_path"] = "PRIVATE_INPUT"
    elif bad == "missing_id": first["id" if kind == "queue" else "key"] = ""
    elif bad == "bool_fingerprint": first["size_bytes" if kind == "queue" else "size"] = True
    elif bad == "negative_fingerprint": first["mtime_ns"] = -1
    elif bad == "state": first["state"] = "foreign"
    else: first["batch_id"] = 123
    path = tmp_path / "store.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    store = cls.__new__(cls)
    store._file_path = path
    sentinel = {"existing": object()}
    setattr(store, "_items" if kind == "queue" else "_entries", sentinel)
    with pytest.raises(error) as caught: store._load()
    assert "PRIVATE_INPUT" not in str(caught.value)
    assert getattr(store, "_items" if kind == "queue" else "_entries") is sentinel
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["queue", "journal"])
@pytest.mark.parametrize("fault", ["mkdir", "temp", "write", "fsync", "replace"])
def test_failed_first_create_leaves_no_record_or_store(tmp_path, monkeypatch, kind, fault):
    cls, error, _ = store_parts(kind)
    path = tmp_path / "new" / "store.json"
    store = cls(path)
    inject_store_write_fault(monkeypatch, cls, fault)
    with pytest.raises(error, match="^(review queue write failed|auto apply journal write failed)$"):
        if kind == "queue": store.add(review(managed_metadata=metadata()))
        else: store.put(journal(managed_metadata=metadata()))
    assert not path.exists()
    assert (store._items if kind == "queue" else store._entries) == {}


@pytest.mark.parametrize("kind", ["queue", "journal"])
def test_serialization_failure_preserves_schema1_memory_and_disk(tmp_path, monkeypatch, kind):
    cls, error, _ = store_parts(kind)
    path = tmp_path / "store.json"
    path.write_text(json.dumps(legacy_payload(kind)), encoding="utf-8")
    store = cls(path)
    old_bytes = path.read_bytes()
    old_memory = dict(store._items if kind == "queue" else store._entries)
    module = __import__(cls.__module__, fromlist=["json"])
    def fail(*a, **kw):
        assert kw["allow_nan"] is False
        raise ValueError("PRIVATE_INPUT")
    monkeypatch.setattr(module.json, "dumps", fail)
    with pytest.raises(error, match="^(review queue write failed|auto apply journal write failed)$"):
        if kind == "queue": store.add(review(managed_metadata=metadata()))
        else: store.put(journal(managed_metadata=metadata()))
    assert path.read_bytes() == old_bytes
    assert (store._items if kind == "queue" else store._entries) == old_memory


@pytest.mark.parametrize("kind", ["queue", "journal"])
def test_exact_store_class_and_exact_metadata_required(tmp_path, kind):
    cls, error, _ = store_parts(kind)
    store = cls(tmp_path / "store.json")
    base = review(managed_metadata=metadata()) if kind == "queue" else journal(managed_metadata=metadata())
    foreign_class = type("ForeignRecord", (type(base),), {})
    foreign = foreign_class(**base.__dict__)
    invalid_meta = metadata()
    object.__setattr__(invalid_meta, "requested_quality", "PRIVATE_PROMPT")
    for record in (foreign, replace(base, managed_metadata=invalid_meta)):
        with pytest.raises(error, match="^(review queue write failed|auto apply journal write failed)$"):
            if kind == "queue": store.add(record)
            else: store.put(record)
        assert not store._file_path.exists()


@pytest.mark.parametrize("field,value", [
    ("id", True), ("id", None), ("watch_id", ""), ("source_path", ""),
    ("size_bytes", True), ("mtime_ns", -1), ("state", "pending"),
    ("extension", 3), ("display_name", None), ("target_parent", object()),
    ("content_kind", None), ("error_category", []), ("batch_id", 5),
    ("created_at_utc", False), ("updated_at_utc", 0),
])
def test_write_rejects_invalid_record_fields_before_timestamp_normalization(tmp_path, field, value):
    queue = ReviewQueue(tmp_path / "queue.json")
    with pytest.raises(ReviewQueueError, match="^review queue write failed$"):
        queue.add(review(**{field: value}))
    assert queue.count() == 0 and not queue._file_path.exists()


@pytest.mark.parametrize("kind", ["queue", "journal"])
def test_schema2_null_or_absent_metadata_and_defaults_load_without_mutating_payload(tmp_path, monkeypatch, kind):
    cls, _, collection = store_parts(kind)
    payload = legacy_payload(kind)
    payload["schema_version"] = 2
    first = payload[collection][0]
    if kind == "queue": first["confidence"] = None
    second = dict(first, managed_metadata=None)
    second["id" if kind == "queue" else "key"] = "second"
    payload[collection].append(second)
    original = copy.deepcopy(payload)
    path = tmp_path / "store.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    module = __import__(cls.__module__, fromlist=["json"])
    monkeypatch.setattr(module.json, "loads", lambda raw: payload)
    store = cls(path)
    assert payload == original
    records = store._items if kind == "queue" else store._entries
    assert len(records) == 2 and all(r.managed_metadata is None for r in records.values())
    if kind == "queue": assert all(r.confidence is None for r in records.values())
