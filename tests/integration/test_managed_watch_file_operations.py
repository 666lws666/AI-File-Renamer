"""Actual Qt/serial-engine Watch manual approvals, persistence and lifecycle."""
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import importlib.util
import json
import os
import sys
import threading
import time

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from src.controllers.managed_file_operation_lane import (
    ManagedFileOperationLane, FileOperationProgress, FileOperationCompletion,
)
from src.controllers.managed_watch_results import ManagedWatchResults
from src.core.rename_history import RenameHistory
from src.core.rename_plan import SourceFingerprint
from src.core.watch_resource_guard import WatchResourceGuard
from src.core.watch_review_queue import ReviewItem, ReviewItemState, ReviewQueue
from src.services.file_operation_backend import FileOperationBackend, FileOperationRequest


def api():
    name = "src.controllers.managed_watch_file_operations"
    assert importlib.util.find_spec(name) is not None, "managed Watch manual Apply/Undo owner is missing"
    return importlib.import_module(name)


def pump(app, predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        threading.Event().wait(.001)
    assert predicate(), "actual Qt/worker drain deadline exceeded"


class Harness:
    def __init__(self, path, app, *, capacity=1000, blocked=False):
        self.path, self.app = path, app
        self.queue = ReviewQueue(path / "review.json")
        self.guard = WatchResourceGuard(cooldown_seconds=0)
        self.notifications = []
        self.results = ManagedWatchResults(queue=self.queue, resource_guard=self.guard,
            on_changed=lambda: self.notifications.append(threading.get_ident()))
        self.backend = FileOperationBackend(path / "history.json")
        self.entered, self.release = threading.Event(), threading.Event()
        if not blocked: self.release.set()
        self.calls, self.progress, self.completions = [], [], []
        execute = self.backend.execute_item
        def record(request, index):
            self.calls.append((request, index, threading.get_ident()))
            self.entered.set()
            if not self.release.wait(5): raise RuntimeError("synthetic backend release deadline")
            return execute(request, index)
        self.backend.execute_item = record
        self.lane = ManagedFileOperationLane(self.backend, capacity=capacity)
        self.parent = QObject()
        self.actions = api().ManagedWatchFileOperations(results=self.results, lane=self.lane,
                                                       parent=self.parent)
        self.lane.itemCompleted.connect(self.progress.append)
        self.lane.completed.connect(self.completions.append)
        self.keep = []

    def add(self, name="one", suggestion=None, **kw):
        source = self.path / (name + ".txt")
        source.write_bytes(("synthetic:" + name).encode())
        stat = source.stat()
        return self.queue.add(ReviewItem(name, "watch", str(source), stat.st_size,
            stat.st_mtime_ns, ".txt", name, ReviewItemState.AWAITING_APPROVAL,
            suggested_name=suggestion or ("new-" + name + ".txt"), **kw))

    def drain(self):
        pump(self.app, lambda: self.lane.workers_idle and self.actions.workers_idle)


@pytest.fixture(scope="session")
def watch_app():
    # QApplication is a QCoreApplication too. Keep the real GUI-capable singleton
    # alive for the entire mixed covering session; never replace a live core app.
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication), "the session must create QApplication before QCoreApplication"
    return app


@pytest.fixture
def make(tmp_path, watch_app):
    app = watch_app
    made = []
    def factory(**kw):
        # Check absent API in the test, not collection or fixture setup.
        api()
        path = tmp_path / str(len(made))
        path.mkdir()
        h = Harness(path, app, **kw)
        made.append(h)
        return h
    yield factory
    for h in made:
        h.release.set()
        for event in h.keep:
            if isinstance(event, threading.Event): event.set()
        h.actions.begin_close()
        h.lane.begin_close()
    for h in made:
        pump(app, lambda: h.lane.closed and h.actions.workers_idle)
        assert not h.lane._futures and h.lane.owned_item_count == 0


def test_actual_batch_partial_apply_undo_and_owner_worker_threads(make):
    h = make()
    first, second = h.add(), h.add("two")
    original = (h.path / "one.txt").read_bytes()
    (h.path / "two.txt").write_bytes(b"changed fingerprint")
    callbacks = []
    h.lane.completed.connect(lambda _: callbacks.append(threading.get_ident()))
    assert h.actions.apply((first.id, second.id)) is True
    assert all(h.results.item(i.id).state is ReviewItemState.APPLYING for i in (first, second))
    assert h.guard.pending_count("watch") == 2
    h.drain()
    applied, failed = h.results.item(first.id), h.results.item(second.id)
    assert applied.state is ReviewItemState.APPLIED and failed.state is ReviewItemState.FAILED
    assert applied.file_operation is None and not applied.recovery_required
    assert failed.error_category == "file_operation_failed" and failed.file_operation is None
    assert (h.path / "new-one.txt").read_bytes() == original
    assert (h.path / "two.txt").read_bytes() == b"changed fingerprint"
    history = RenameHistory(h.path / "history.json").get_all()
    assert len(history) == 1 and history[0].task_id == first.id and history[0].batch_id == applied.batch_id
    assert h.guard.pending_count("watch") == 0
    assert h.actions.undo(first.id) is True
    undo_intent = h.results.item(first.id).file_operation
    assert undo_intent.kind == "undo" and undo_intent.batch_id == applied.batch_id
    h.drain()
    undone = h.results.item(first.id)
    assert undone.state is ReviewItemState.UNDONE and undone.applied_path == ""
    assert undone.file_operation is None and not undone.recovery_required
    stat = (h.path / "one.txt").stat()
    assert undone.fingerprint() == (stat.st_size, stat.st_mtime_ns)
    assert (h.path / "one.txt").read_bytes() == original
    assert RenameHistory(h.path / "history.json").get_all()[0].undone
    assert ReviewQueue(h.queue._file_path).get(first.id) == undone
    assert callbacks and set(callbacks + h.notifications) == {threading.get_ident()}
    workers = {ident for _, _, ident in h.calls}
    assert len(workers) == 1 and threading.get_ident() not in workers
    assert h.actions.apply((first.id,)) is True
    h.drain()
    assert h.results.item(first.id).state is ReviewItemState.APPLIED


def test_auto_apply_denied_after_durable_intent_rolls_back_without_worker(make, monkeypatch):
    h = make()
    row = h.add()
    allowed, calls = [True], []
    original = h.results._replace_for_file_operation
    def reentrant(changes, **options):
        saved = original(changes, **options)
        if saved[0].state is ReviewItemState.APPLYING:
            allowed[0] = False
        return saved
    monkeypatch.setattr(h.results, "_replace_for_file_operation", reentrant)
    def authorized():
        calls.append(allowed[0]); return allowed[0]
    assert h.actions.auto_apply(row.id, is_authorized=authorized) is False
    assert calls == [True, False]
    assert h.results.item(row.id).state is ReviewItemState.AWAITING_APPROVAL
    assert h.results.item(row.id).file_operation is None
    assert h.lane.owned_item_count == 0 and h.calls == []


def test_auto_apply_accepts_only_exact_true_and_its_own_row_transition(make):
    h = make()
    row = h.add()
    assert h.actions.auto_apply(row.id, is_authorized=lambda: 1) is False
    assert h.actions.auto_apply(row.id, is_authorized=lambda: h.actions._auto_row_current(row))
    h.drain()
    assert h.results.item(row.id).state is ReviewItemState.APPLIED


def test_collision_success_preserves_existing_bytes_and_supports_undo(make):
    h = make()
    item = h.add()
    occupied = h.path / "new-one.txt"
    occupied.write_bytes(b"do not overwrite")
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLIED and not saved.recovery_required
    assert saved.applied_path == str(h.path / "new-one_1.txt")
    assert occupied.read_bytes() == b"do not overwrite"
    assert h.actions.undo(item.id)
    h.drain()
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"
    assert occupied.read_bytes() == b"do not overwrite"


@pytest.mark.parametrize("ids", [(), ("one", "one"), ("one", "missing"), ["one"],
    (True,), ("",), tuple(str(i) for i in range(1001))])
def test_all_or_none_invalid_ids_no_store_or_worker(make, ids):
    h = make()
    item = h.add()
    before = h.queue._file_path.read_bytes()
    assert h.actions.apply(ids) is False
    assert h.results.item(item.id) is item and h.queue._file_path.read_bytes() == before
    assert not h.calls and h.lane.owned_item_count == 0


@pytest.mark.parametrize("suggestion", ["../escape.txt", "/absolute.txt", "dir//new.txt",
    "dir/../new.txt", "dir\\new.txt", "C:/new.txt", "new.exe", "CON/new.txt", "new\x00.txt"])
def test_invalid_names_and_extension_escape_rejected_without_io(make, suggestion):
    h = make()
    item = h.add(suggestion=suggestion)
    assert not h.actions.apply((item.id,))
    assert h.results.item(item.id) is item and not h.calls


def test_template_subdirectories_trusted_parent_and_no_qt_source_io(make, monkeypatch):
    h = make()
    item = h.add(suggestion="year/month/new.txt", target_parent=str(h.path))
    owner = threading.get_ident()
    source = item.source_path
    seen = []
    stat = os.stat
    def guarded(value, *args, **kwargs):
        if str(value) == source:
            seen.append(threading.get_ident())
            if threading.get_ident() == owner: raise AssertionError("Qt source stat")
        return stat(value, *args, **kwargs)
    monkeypatch.setattr(os, "stat", guarded)
    assert h.actions.apply((item.id,))
    h.drain()
    assert seen and owner not in seen
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLIED
    assert saved.applied_path == str(h.path / "year" / "month" / "new.txt")
    assert (h.path / "year" / "month" / "new.txt").read_bytes() == b"synthetic:one"


def test_nested_template_under_existing_target_root_outside_source(make):
    h = make()
    target_root = h.path.parent / "approved-target"
    target_root.mkdir()
    item = h.add(suggestion="Project/new.txt", target_parent=str(target_root))
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLIED
    assert saved.applied_path == str(target_root / "Project" / "new.txt")
    assert (target_root / "Project" / "new.txt").read_bytes() == b"synthetic:one"
    assert not (h.path / "one.txt").exists()
    assert h.actions.undo(item.id)
    h.drain()
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"


def test_actual_shared_lane_capacity_reserve_failure_no_intent(make):
    h = make(capacity=1)
    item = h.add()
    foreign = h.lane.reserve(FileOperationRequest("batch-client", "undo", task_ids=("foreign",)))
    before = h.queue._file_path.read_bytes()
    assert not h.actions.apply((item.id,))
    assert h.results.item(item.id) is item and h.queue._file_path.read_bytes() == before
    assert not h.calls and h.lane.owned_item_count == 1
    assert h.lane.cancel(foreign)
    assert h.actions.apply((item.id,))
    h.drain()


def test_fake_cloned_replayed_public_payloads_cannot_mutate_and_witness_tail(make):
    h = make(blocked=True)
    item = h.add()
    observations, originals = [], []
    def observe(payload):
        observations.append((h.lane.is_publishing(payload), h.lane.is_publishing(replace(payload)),
                             h.actions.workers_idle, h.lane.workers_idle))
        originals.append(payload)
    h.lane.itemCompleted.connect(observe)
    h.lane.completed.connect(observe)
    assert h.actions.apply((item.id,)) and h.entered.wait(2)
    reserved = next(iter(h.lane._jobs.values())).reservation
    from src.services.file_operation_backend import FileOperationOutcome
    outcome = FileOperationOutcome(item.id, reserved.request.batch_id, True,
                                   new_path=str(h.path / "new-one.txt"))
    fake = FileOperationProgress(reserved, 0, outcome)
    before = h.queue._file_path.read_bytes()
    h.lane.itemCompleted.emit(fake)
    h.lane.completed.emit(FileOperationCompletion(reserved, (outcome,)))
    assert h.queue._file_path.read_bytes() == before and h.results.item(item.id).file_operation is not None
    assert observations[:2] == [(False, False, False, False)] * 2
    h.release.set()
    h.drain()
    assert observations[2:] == [(True, False, False, False)] * 2
    assert not h.lane.is_publishing(fake)
    saved = h.results.item(item.id)
    for payload in originals[2:]:
        assert not h.lane.is_publishing(payload)
        (h.lane.itemCompleted if type(payload) is FileOperationProgress else h.lane.completed).emit(payload)
    assert h.results.item(item.id) is saved and saved.state is ReviewItemState.APPLIED


@pytest.mark.parametrize("event", ["close", "ignore", "mutate"])
def test_clock_reentry_before_commit_cannot_move_or_overwrite_foreign_row(make, event):
    h = make()
    item = h.add()
    changed = []
    def clock():
        h.queue._clock = lambda: datetime.now(timezone.utc)
        if event == "close": h.actions.begin_close()
        elif event == "ignore": changed.append(h.results.ignore(item.id))
        else: changed.append(h.queue.update(replace(item, suggested_name="foreign.txt")))
        return datetime.now(timezone.utc)
    h.queue._clock = clock
    assert not h.actions.apply((item.id,))
    assert not h.calls and h.lane.owned_item_count == 0
    now = h.results.item(item.id)
    if changed: assert now is changed[0]
    else: assert now.state is ReviewItemState.AWAITING_APPROVAL and now.file_operation is None
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"


@pytest.mark.parametrize("stage", ["admission", "rollback", "completion"])
def test_save_fault_has_honest_authoritative_state_and_disables_actions(make, monkeypatch, stage):
    h = make(blocked=stage == "completion")
    item = h.add()
    before = h.queue._file_path.read_bytes()
    original = h.queue._save_locked
    writes = []
    def save(rows):
        writes.append(1)
        if (stage == "admission" or (stage == "rollback" and len(writes) == 2)
                or (stage == "completion" and len(writes) >= 2)):
            raise OSError("PRIVATE_STORE_SENTINEL")
        return original(rows)
    monkeypatch.setattr(h.queue, "_save_locked", save)
    if stage == "rollback": monkeypatch.setattr(h.lane, "commit", lambda _: False)
    admitted = h.actions.apply((item.id,))
    if stage == "completion":
        assert admitted and h.entered.wait(2)
        h.release.set()
        h.drain()
        assert (h.path / "new-one.txt").read_bytes() == b"synthetic:one"
        assert not (h.path / "one.txt").exists()
    else:
        assert not admitted and not h.calls and h.lane.owned_item_count == 0
    now = h.results.item(item.id)
    if stage == "admission":
        assert now is item and h.queue._file_path.read_bytes() == before
    else:
        assert now.state is ReviewItemState.APPLYING and now.file_operation is not None
        assert ReviewQueue(h.queue._file_path).get(item.id) == now
    assert not h.actions.available and h.actions.error == "queue_unavailable"
    assert not h.actions.apply((item.id,))
    assert "PRIVATE_STORE_SENTINEL" not in h.queue._file_path.read_text()


def test_lane_commit_rejection_rolls_back_exact_candidate_and_remains_idle(make, monkeypatch):
    h = make()
    item = h.add()
    monkeypatch.setattr(h.lane, "commit", lambda _: False)
    assert not h.actions.apply((item.id,))
    saved = h.results.item(item.id)
    assert saved.state is item.state and saved.file_operation is None
    assert h.lane.owned_item_count == 0 and not h.calls and h.actions.workers_idle


def test_reentrant_terminal_observer_can_undo_after_owner_retired(make):
    h = make(capacity=2)
    item = h.add()
    witness = []
    def changed():
        current = h.results.item(item.id)
        witness.append((current.state, h.guard.pending_count("watch"), h.actions.workers_idle))
        if current.state is ReviewItemState.APPLIED:
            witness.append(h.actions.undo(item.id))
    h.results._changed = changed
    assert h.actions.apply((item.id,))
    h.drain()
    assert True in witness
    assert h.results.item(item.id).state is ReviewItemState.UNDONE
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"
    assert all(not value[2] for value in witness if type(value) is tuple)


def test_notification_exception_not_a_store_failure_and_close_keeps_lane_open(make):
    h = make(blocked=True)
    item = h.add()
    seen = []
    def changed():
        seen.append(h.results.item(item.id).state)
        raise RuntimeError("PRIVATE_OBSERVER_SENTINEL")
    h.results._changed = changed
    assert h.actions.apply((item.id,))
    h.actions.begin_close()
    h.results.begin_close()
    assert not h.actions.apply((item.id,))
    h.release.set()
    h.drain()
    assert h.results.item(item.id).state is ReviewItemState.APPLIED
    assert h.results.available and h.actions.available
    assert seen and "PRIVATE_OBSERVER_SENTINEL" not in h.queue._file_path.read_text()
    foreign = h.lane.reserve(FileOperationRequest("other-client", "undo", task_ids=("foreign",)))
    assert foreign is not None and h.lane.cancel(foreign)


def test_undo_normal_failure_stays_applied_and_explicit_retry(make):
    h = make()
    item = h.add()
    assert h.actions.apply((item.id,))
    h.drain()
    original = h.path / "one.txt"
    original.write_bytes(b"occupied original")
    assert h.actions.undo(item.id)
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLIED and saved.file_operation is None
    assert not saved.recovery_required and saved.error_category == "file_operation_failed"
    assert original.read_bytes() == b"occupied original"
    original.unlink()
    assert h.actions.undo(item.id)
    h.drain()
    assert h.results.item(item.id).state is ReviewItemState.UNDONE


@pytest.mark.parametrize("bad", ["task", "batch", "path", "extension", "parent", "zero_suffix",
    "noncanonical_suffix", "fingerprint", "recovery", "unknown", "shape"])
def test_genuine_worker_malformed_or_recovery_outcomes_never_invent_success(make, bad):
    h = make()
    item = h.add()
    if bad == "fingerprint":
        assert h.actions.apply((item.id,))
        h.drain()
    real = h.backend.execute_item
    def altered(request, index):
        result = real(request, index)
        if bad == "task": return replace(result, task_id="other-row")
        if bad == "batch": return replace(result, batch_id="other-batch")
        if bad == "path": return replace(result, new_path=str(h.path / "arbitrary.txt"))
        if bad == "extension": return replace(result, new_path=str(h.path / "new-one.exe"))
        if bad == "parent": return replace(result, new_path=str(h.path.parent / "new-one.txt"))
        if bad == "zero_suffix": return replace(result, new_path=str(h.path / "new-one_0.txt"))
        if bad == "noncanonical_suffix": return replace(result, new_path=str(h.path / "new-one_01.txt"))
        if bad == "fingerprint": return replace(result, source_fingerprint=None)
        if bad == "recovery": return replace(result, recovery_required=True, error="PRIVATE_HISTORY_SENTINEL")
        if bad == "unknown": return replace(result, success=False, recovery_required=True,
                                                error="fileops.error.unknownOutcome", new_path="")
        return object()
    h.backend.execute_item = altered
    assert (h.actions.undo(item.id) if bad == "fingerprint" else h.actions.apply((item.id,)))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.file_operation is not None and saved.recovery_required
    assert saved.state is ReviewItemState.APPLYING
    assert saved.error_category in {"invalid_outcome", "file_operation_recovery"}
    assert "PRIVATE_HISTORY_SENTINEL" not in h.queue._file_path.read_text()
    assert not h.actions.apply((item.id,)) and not h.actions.undo(item.id)


def test_missing_undo_history_batch_is_not_fabricated(make):
    h = make()
    item = h.add()
    saved = h.queue.update(replace(item, state=ReviewItemState.APPLIED,
                                 applied_path=str(h.path / "new-one.txt"), batch_id="saved-batch"))
    assert h.actions.undo(item.id)
    h.drain()
    now = h.results.item(item.id)
    assert now.file_operation.batch_id == saved.batch_id and now.recovery_required
    assert now.error_category == "invalid_outcome"


def test_interrupted_restore_inert_zero_backend_and_legacy_undo_not_reconstructed(make):
    h = make()
    module = importlib.import_module("src.core.watch_review_queue")
    marker = module.WatchFileOperationIntent(1, "interrupted", "apply", "batch", "absent.txt", "target.txt")
    item = h.add()
    interrupted = h.queue.update(replace(item, state=ReviewItemState.APPLYING, file_operation=marker))
    legacy = h.add("legacy")
    legacy = h.queue.update(replace(legacy, state=ReviewItemState.APPLIED, batch_id="legacy-batch"))
    assert not h.calls
    assert h.actions.restore_interrupted() == 1
    saved = h.results.item(interrupted.id)
    assert saved.recovery_required and saved.file_operation == marker and saved.error_category == "interrupted"
    assert not h.actions.undo(legacy.id) and not h.actions.apply((saved.id,))
    assert not h.calls and h.lane.owned_item_count == 0
    assert ReviewQueue(h.queue._file_path).get(saved.id) == saved


def test_owner_affinity_properties_and_publication_query(make):
    h = make()
    h.add()
    errors = []
    calls = [lambda: h.actions.apply(("one",)), lambda: h.actions.undo("one"),
             h.actions.restore_interrupted, h.actions.begin_close,
             lambda: h.actions.available, lambda: h.actions.error,
             lambda: h.actions.workers_idle, lambda: h.lane.is_publishing(object())]
    def wrong():
        for call in calls:
            try: call()
            except RuntimeError: errors.append(True)
    thread = threading.Thread(target=wrong)
    thread.start()
    thread.join(2)
    assert not thread.is_alive() and errors == [True] * len(calls)
    assert not h.calls


def test_actual_future_tail_required_for_client_idle(make, monkeypatch):
    h = make()
    item = h.add()
    entered, release = threading.Event(), threading.Event()
    h.keep.extend((entered, release))
    submit = h.lane._executor.submit
    def delayed(fn):
        def run():
            fn()
            entered.set()
            release.wait(5)
        return submit(run)
    monkeypatch.setattr(h.lane._executor, "submit", delayed)
    assert h.actions.apply((item.id,)) and entered.wait(2)
    pump(h.app, lambda: h.lane.owned_item_count == 0)
    assert h.results.item(item.id).state is ReviewItemState.APPLIED
    assert not h.lane.workers_idle and not h.actions.workers_idle
    release.set()
    h.drain()


def test_managed_request_captures_original_roots_before_template_components(make):
    h = make()
    target_root = h.path.parent / "target-root"
    target_root.mkdir()
    first = h.add(suggestion="Project/one.txt", target_parent=str(target_root))
    second = h.add("two", suggestion="Project/two.txt", target_parent=str(target_root))
    assert h.actions.apply((first.id, second.id))
    h.drain()
    request = h.calls[0][0]
    assert getattr(request, "allowed_roots", None) == (str(h.path), str(target_root))
    assert len(h.calls) == 2 and all(call[0] is request for call in h.calls)
    assert h.results.item(first.id).state is ReviewItemState.APPLIED
    assert h.results.item(second.id).state is ReviewItemState.APPLIED


def test_raising_uncommitted_commit_rolls_back_without_leaking_owner(make, monkeypatch):
    h = make()
    item = h.add()
    commit = h.lane.commit
    def fail(_): raise RuntimeError("PRIVATE_COMMIT_SENTINEL")
    monkeypatch.setattr(h.lane, "commit", fail)
    try:
        assert not h.actions.apply((item.id,))
        saved = h.results.item(item.id)
        assert saved.state is ReviewItemState.AWAITING_APPROVAL and saved.file_operation is None
        assert not h.calls and h.lane.owned_item_count == 0 and h.actions.workers_idle
    finally:
        # Genuine approved synthetic work drains a leaked owner on failing RED;
        # no fake idle flag, manually cleared owner or abandoned Future.
        monkeypatch.setattr(h.lane, "commit", commit)
        for job in tuple(h.lane._jobs.values()):
            if not job.committed: assert commit(job.reservation)
        h.drain()


@pytest.mark.parametrize("shape", ["valid", "missing", "extra", "list"])
def test_actual_terminal_missing_progress_and_malformed_shape(make, monkeypatch, shape):
    h = make()
    item = h.add()
    post = h.lane._post
    def altered(payload, job, signal):
        if type(payload) is FileOperationProgress: return
        if shape == "missing": payload = replace(payload, results=())
        elif shape == "extra": payload = replace(payload, results=payload.results + payload.results)
        elif shape == "list": payload = replace(payload, results=list(payload.results))
        return post(payload, job, signal)
    monkeypatch.setattr(h.lane, "_post", altered)
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert not h.progress and len(h.completions) == 1
    assert (h.path / "new-one.txt").read_bytes() == b"synthetic:one"
    if shape == "valid":
        assert saved.state is ReviewItemState.APPLIED and saved.file_operation is None
    else:
        assert saved.state is ReviewItemState.APPLYING and saved.file_operation is not None
        assert saved.recovery_required and saved.error_category == "invalid_outcome"


@pytest.mark.parametrize("event", ["close_actions", "close_results", "foreign_row"])
def test_snapshot_registration_reentry_after_save_rechecks_and_rolls_back_only_own(make, monkeypatch, event):
    h = make()
    first, second = h.add(), h.add("two")
    register = h.guard.register_pending_source
    armed, foreign = [True], []
    def reentrant(*args, **kwargs):
        result = register(*args, **kwargs)
        if armed[0]:
            armed[0] = False
            if event == "close_actions": h.actions.begin_close()
            elif event == "close_results": h.results.begin_close()
            else:
                current = h.results.item(first.id)
                foreign.append(h.queue.update(replace(current, state=ReviewItemState.AWAITING_APPROVAL,
                    file_operation=None, suggested_name="foreign.txt")))
        return result
    monkeypatch.setattr(h.guard, "register_pending_source", reentrant)
    assert not h.actions.apply((first.id, second.id))
    assert not h.calls and h.lane.owned_item_count == 0
    assert h.results.item(second.id).state is ReviewItemState.AWAITING_APPROVAL
    assert h.results.item(second.id).file_operation is None
    if foreign: assert h.results.item(first.id) is foreign[0]
    else: assert h.results.item(first.id).file_operation is None
    assert h.guard.pending_count("watch") == 2


def test_notification_admission_reentry_has_no_early_second_approval(make):
    h = make()
    first, second = h.add(), h.add("two")
    observed = []
    def changed():
        if not observed:
            observed.append(h.actions.apply((second.id,)))
    h.results._changed = changed
    assert h.actions.apply((first.id,))
    h.drain()
    assert observed == [False]
    assert h.results.item(second.id) is second and len(h.calls) == 1


@pytest.mark.parametrize("state", [state for state in ReviewItemState
                                  if state.value not in {"awaiting_approval", "undone"}])
def test_apply_rejects_nonqualifying_state_without_durable_changes(make, state):
    h = make()
    item = h.add()
    saved = h.queue.update(replace(item, state=state))
    assert not h.actions.apply((item.id,))
    assert h.results.item(item.id) is saved and not h.calls


def test_restore_is_metadata_only_and_cannot_run_after_manual_actions(make, monkeypatch):
    h = make()
    item = h.add()
    applied = h.queue.update(replace(item, state=ReviewItemState.APPLYING))
    def forbidden(*args, **kwargs): pytest.fail("restore attempted file/history work")
    with monkeypatch.context() as guard:
        guard.setattr(h.backend, "execute_item", forbidden)
        guard.setattr(h.backend, "_initialize", forbidden)
        assert h.actions.restore_interrupted() == 1
    assert h.results.item(applied.id).recovery_required and not h.calls
    clean = h.add("clean")
    assert h.actions.apply((clean.id,))
    h.drain()
    with pytest.raises(ValueError, match="^invalid_watch_file_operations$"):
        h.actions.restore_interrupted()


def test_actual_commit_then_raise_retains_owner_intent_and_late_outcome(make, monkeypatch):
    h = make(blocked=True)
    item = h.add()
    commit = h.lane.commit
    witnessed = []
    def ambiguous(reservation):
        witnessed.append(commit(reservation))
        raise RuntimeError("PRIVATE_AFTER_COMMIT_SENTINEL")
    monkeypatch.setattr(h.lane, "commit", ambiguous)
    assert not h.actions.apply((item.id,))
    assert witnessed == [True] and h.entered.wait(2)
    before = h.results.item(item.id)
    assert before.state is ReviewItemState.APPLYING and before.file_operation is not None
    assert h.lane.owned_item_count == 1 and not h.actions.workers_idle
    assert not h.actions.available and h.actions.error == "queue_unavailable"
    h.actions.begin_close()
    h.release.set()
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLIED and saved.file_operation is None
    assert ReviewQueue(h.queue._file_path).get(saved.id) == saved
    assert (h.path / "new-one.txt").read_bytes() == b"synthetic:one"
    assert "PRIVATE_AFTER_COMMIT_SENTINEL" not in h.queue._file_path.read_text()


def test_native_submit_rejection_is_definitely_unexecuted_and_rolls_back(make, monkeypatch):
    h = make()
    item = h.add()
    def fail(*args, **kwargs): raise RuntimeError("PRIVATE_SUBMIT_SENTINEL")
    monkeypatch.setattr(h.lane._executor, "submit", fail)
    assert not h.actions.apply((item.id,))
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.AWAITING_APPROVAL and saved.file_operation is None
    assert h.actions.workers_idle and h.lane.closed and not h.calls
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"
    assert not (h.path / "new-one.txt").exists()


def test_real_undo_history_save_recovery_keeps_durable_intent_and_actual_bytes(make, monkeypatch):
    h = make()
    item = h.add()
    assert h.actions.apply((item.id,))
    h.drain()
    def fail(*args, **kwargs): raise OSError("PRIVATE_HISTORY_WRITE_SENTINEL")
    monkeypatch.setattr(RenameHistory, "mark_records_undone", fail)
    assert h.actions.undo(item.id)
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLYING and saved.file_operation.kind == "undo"
    assert saved.recovery_required and saved.error_category == "file_operation_recovery"
    assert (h.path / "one.txt").read_bytes() == b"synthetic:one"
    assert not (h.path / "new-one.txt").exists()
    assert not RenameHistory(h.path / "history.json").get_all()[0].undone
    assert not h.actions.undo(item.id)
    assert "PRIVATE_HISTORY_WRITE_SENTINEL" not in h.queue._file_path.read_text()


def test_duplicate_actual_progress_reentry_consumes_index_before_notifications(make):
    h = make()
    item = h.add()
    witness = []
    armed = [True]
    def changed():
        if h.progress and armed[0]:
            armed[0] = False
            payload = h.progress[0]
            count = len(h.notifications)
            current = h.results.item(item.id)
            h.actions._progress(payload)
            h.lane.itemCompleted.emit(replace(payload))
            witness.append((h.results.item(item.id) is current, len(h.notifications) == count))
        h.notifications.append(threading.get_ident())
    # Harness progress observer is after the actions owner; retain the genuine
    # payload in a direct callback before the client callback for this test.
    h.lane.itemCompleted.disconnect(h.actions._progress)
    h.lane.itemCompleted.connect(h.actions._progress, Qt.ConnectionType.DirectConnection)
    h.results._changed = changed
    assert h.actions.apply((item.id,))
    h.drain()
    assert witness == [(True, True)]
    assert h.results.item(item.id).state is ReviewItemState.APPLIED
    assert len(RenameHistory(h.path / "history.json").get_all()) == 1


@pytest.mark.parametrize("bad", ["success_bool", "recovery_bool", "error_type", "null_path",
    "fingerprint_bool", "unknown_without_recovery"])
def test_exact_outcome_primitive_graph_and_unknown_code_fail_closed(make, bad):
    h = make()
    item = h.add()
    if bad == "fingerprint_bool":
        assert h.actions.apply((item.id,))
        h.drain()
    real = h.backend.execute_item
    def altered(request, index):
        outcome = real(request, index)
        changes = {
            "success_bool": {"success": 1}, "recovery_bool": {"recovery_required": 1},
            "error_type": {"error": object()}, "null_path": {"new_path": "bad\x00path"},
            "fingerprint_bool": {"source_fingerprint": SourceFingerprint(True, 1)},
            "unknown_without_recovery": {"success": False, "new_path": "",
                                         "error": "fileops.error.unknownOutcome"},
        }[bad]
        return replace(outcome, **changes)
    h.backend.execute_item = altered
    assert (h.actions.undo(item.id) if bad == "fingerprint_bool" else h.actions.apply((item.id,)))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLYING and saved.file_operation is not None
    assert saved.recovery_required and saved.error_category in {"invalid_outcome", "file_operation_recovery"}


def test_construction_exact_borrowed_objects_no_backend_or_durable_mutation(make):
    h = make()
    item = h.add()
    before = h.queue._file_path.read_bytes()
    for results, lane in ((object(), h.lane), (h.results, object())):
        with pytest.raises(ValueError, match="^invalid_watch_file_operations$"):
            api().ManagedWatchFileOperations(results=results, lane=lane)
    fresh = api().ManagedWatchFileOperations(results=h.results, lane=h.lane, parent=h.parent)
    h.keep.append(fresh)
    assert fresh.workers_idle and fresh.available and fresh.error == ""
    assert not h.calls and h.results.item(item.id) is item
    assert h.queue._file_path.read_bytes() == before
    fresh.begin_close()


def test_new_fixture_retains_gui_capable_singleton_for_later_qml_covering(make):
    h = make()
    assert isinstance(h.app, QApplication), "a live QCoreApplication cannot be upgraded for later QML runtime"
    assert QApplication.instance() is h.app


def extensionless_review(h):
    source = h.path / "original"
    source.write_bytes(b"synthetic extensionless content")
    stat = source.stat()
    item = h.queue.add(ReviewItem("extensionless", "watch", str(source), stat.st_size,
        stat.st_mtime_ns, "", "original", ReviewItemState.AWAITING_APPROVAL,
        suggested_name="report.v2"))
    return source, item


def test_extensionless_dotted_collision_apply_and_undo(make):
    h = make()
    source, item = extensionless_review(h)
    original_bytes = source.read_bytes()
    occupied, counted = h.path / "report.v2", h.path / "report_1.v2"
    occupied.write_bytes(b"occupied approved target")
    assert h.actions.apply((item.id,))
    h.drain()
    applied = h.results.item(item.id)
    assert counted.read_bytes() == original_bytes and not source.exists()
    assert occupied.read_bytes() == b"occupied approved target"
    history = RenameHistory(h.path / "history.json").get_all()
    assert len(history) == 1 and history[0].task_id == item.id
    assert history[0].new_path == counted and history[0].old_path == source
    assert history[0].batch_id == applied.batch_id and not history[0].undone
    undo_admitted = h.actions.undo(item.id)
    assert (applied.state, applied.error_category, applied.recovery_required, undo_admitted) == (
        ReviewItemState.APPLIED, "", False, True), (
        f"state={applied.state.value}; error={applied.error_category}; "
        f"recovery={applied.recovery_required}; undo_admitted={undo_admitted}")
    assert applied.applied_path == str(counted) and applied.file_operation is None
    h.drain()
    undone = h.results.item(item.id)
    assert undone.state is ReviewItemState.UNDONE and undone.applied_path == ""
    assert undone.file_operation is None and not undone.recovery_required and undone.error_category == ""
    stat = source.stat()
    assert undone.fingerprint() == (stat.st_size, stat.st_mtime_ns)
    assert source.read_bytes() == original_bytes and not counted.exists()
    assert occupied.read_bytes() == b"occupied approved target"
    history = RenameHistory(h.path / "history.json").get_all()
    assert len(history) == 1 and history[0].task_id == item.id and history[0].undone
    assert ReviewQueue(h.queue._file_path).get(item.id) == undone


@pytest.mark.parametrize("reported", ["report.v2_1", "report_0.v2", "report_01.v2",
    "report_1.v3", "arbitrary_1.v2", "report_١.v2"])
def test_extensionless_dotted_counter_rejects_nonengine_sibling_forms(make, reported):
    h = make()
    source, item = extensionless_review(h)
    occupied = h.path / "report.v2"
    occupied.write_bytes(b"occupied approved target")
    real = h.backend.execute_item
    def altered(request, index):
        result = real(request, index)
        return replace(result, new_path=str(h.path / reported))
    h.backend.execute_item = altered
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLYING and saved.recovery_required
    assert saved.file_operation is not None and saved.error_category == "invalid_outcome"
    assert not h.actions.undo(item.id)
    assert (h.path / "report_1.v2").read_bytes() == b"synthetic extensionless content"
    assert not source.exists() and occupied.read_bytes() == b"occupied approved target"


def test_compound_protected_extension_remains_independent_of_engine_counter(make):
    h = make()
    source = h.path / "original.tar.gz"
    source.write_bytes(b"synthetic protected compound content")
    stat = source.stat()
    item = h.queue.add(ReviewItem("compound", "watch", str(source), stat.st_size,
        stat.st_mtime_ns, ".tar.gz", "original", ReviewItemState.AWAITING_APPROVAL,
        suggested_name="archive.tar.gz"))
    occupied = h.path / "archive.tar.gz"
    occupied.write_bytes(b"occupied compound target")
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert (h.path / "archive_1.tar.gz").read_bytes() == b"synthetic protected compound content"
    assert occupied.read_bytes() == b"occupied compound target" and not source.exists()
    assert saved.state is ReviewItemState.APPLIED and not saved.recovery_required
    assert saved.file_operation is None and saved.applied_path == str(h.path/'archive_1.tar.gz')
    assert h.actions.undo(item.id)
    h.drain()
    assert h.results.item(item.id).state is ReviewItemState.UNDONE
    assert source.read_bytes() == b'synthetic protected compound content'


def test_numbered_native_recovery_evidence_survives_watch_reload(make, monkeypatch):
    from src.core import safe_file_move as native
    h = make(); item = h.add()
    occupied = h.path/'new-one.txt'; occupied.write_bytes(b'OCCUPIED')
    real, witnesses = native._rename, []
    def uncertain(*args):
        result = real(*args)
        witnesses.append(args[2])
        raise OSError('PRIVATE_AFTER_PUBLICATION')
    monkeypatch.setattr(native, '_rename', uncertain)
    assert h.actions.apply((item.id,)); h.drain()
    saved = h.results.item(item.id)
    assert witnesses == ['new-one_1.txt']
    assert saved.state is ReviewItemState.APPLYING and saved.recovery_required
    marker = saved.file_operation
    assert marker.version == 2 and marker.recovery_reason == 'fileops.error.nativeRecovery'
    assert set(marker.owned_residue_paths) == {item.source_path, str(h.path/'new-one_1.txt')}
    loaded = ReviewQueue(h.queue._file_path)
    assert loaded.get(item.id) == saved
    h.results._queue = loaded
    assert not h.actions.apply((item.id,)) and not h.actions.undo(item.id)
    assert (h.path/'new-one_1.txt').read_bytes() == b'synthetic:one' and occupied.read_bytes() == b'OCCUPIED'


def test_watch_completion_save_failure_retains_returned_evidence_in_memory(make, monkeypatch):
    h = make(blocked=True); item = h.add()
    assert h.actions.apply((item.id,)) and h.entered.wait(2)
    durable = h.queue._file_path.read_bytes()
    monkeypatch.setattr(h.queue, '_save_locked', lambda *_: (_ for _ in ()).throw(OSError('PRIVATE')))
    h.release.set(); h.drain()
    assert h.queue._file_path.read_bytes() == durable
    assert not h.actions.available and not h.actions.undo(item.id)
    held = getattr(h.actions, '_recovery_outcomes', {}).get(item.id)
    assert held is not None and held.new_path == str(h.path/'new-one.txt') and held.source_identity is not None
    assert (h.path/'new-one.txt').read_bytes() == b'synthetic:one'


def test_completed_watch_undo_history_failure_preserves_edited_capture(make, monkeypatch):
    h = make(); item = h.add()
    assert h.actions.apply((item.id,)); h.drain()
    target = h.path/'new-one.txt'; target.write_bytes(b'SAME_FILE_LEGITIMATE_EDITED_CONTENT')
    monkeypatch.setattr(RenameHistory, 'mark_records_undone', lambda *_: (_ for _ in ()).throw(OSError('PRIVATE')))
    assert h.actions.undo(item.id); h.drain()
    saved = h.results.item(item.id)
    actual = (h.path/'one.txt').stat()
    assert saved.recovery_required and saved.file_operation.version == 2
    assert saved.file_operation.known_result_path == item.source_path
    assert saved.fingerprint() == (actual.st_size, actual.st_mtime_ns)
    assert ReviewQueue(h.queue._file_path).get(item.id) == saved


@pytest.mark.parametrize('bad', ['list', 'duplicate', 'overlong', 'merged_overflow', 'missing_apply_capture'])
def test_watch_complete_recovery_graph_and_apply_capture_fail_closed(make, bad):
    h = make(); item = h.add(); real = h.backend.execute_item
    def altered(*args):
        result = real(*args)
        if bad == 'missing_apply_capture': return replace(result, source_identity=None, source_fingerprint=None)
        paths = {'list': [], 'duplicate': ('same', 'same'), 'overlong': ('x'*4097,),
                 'merged_overflow': tuple(str(h.path/f'p{i}') for i in range(8))}[bad]
        return replace(result, recovery_required=True, owned_residue_paths=paths)
    h.backend.execute_item = altered
    assert h.actions.apply((item.id,)); h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLYING and saved.recovery_required and saved.file_operation is not None
    assert not h.actions.undo(item.id)


@pytest.mark.parametrize('path', [['bad'], {'bad': 'path'}])
def test_actual_watch_unhashable_path_is_one_locked_outcome_and_drains(make, monkeypatch, path):
    h = make(); item = h.add()
    real, calls, saves = h.backend.execute_item, [], []
    saving = h.queue._save_locked
    def altered(*args):
        result = real(*args)
        assert result.success and result.source_identity is not None and result.source_fingerprint is not None
        calls.append(result)
        return replace(result, new_path=path)
    def save(rows):
        if rows[item.id].error_category == 'invalid_outcome': saves.append(True)
        return saving(rows)
    h.backend.execute_item = altered
    monkeypatch.setattr(h.queue, '_save_locked', save)
    payloads = []
    def duplicate(payload):
        payloads.append(payload)
        h.actions._progress(payload)  # Exact envelope during actual owner publication.
    h.lane.itemCompleted.connect(duplicate, Qt.DirectConnection)
    assert h.actions.apply((item.id,))
    h.drain()
    saved = h.results.item(item.id)
    assert saved.state is ReviewItemState.APPLYING and saved.recovery_required
    assert saved.file_operation is not None and saved.error_category == 'invalid_outcome'
    assert len(calls) == len(saves) == len(payloads) == 1
    assert not h.actions._owners and not h.actions._rows and h.lane.owned_item_count == 0
    assert not h.actions.apply((item.id,)) and not h.actions.undo(item.id)
    h.lane.itemCompleted.emit(payloads[0])
    assert h.results.item(item.id) is saved and len(saves) == 1
    assert (h.path / 'new-one.txt').read_bytes() == b'synthetic:one' and not (h.path / 'one.txt').exists()
    assert len(RenameHistory(h.path / 'history.json').get_all()) == 1
