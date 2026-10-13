"""Bounded lane ownership, real disk outcomes and native Qt lifecycle."""
from dataclasses import replace
import threading
import time
import sys

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from src.core.rename_history import RenameHistory
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.services.file_operation_backend import FileOperationBackend, FileOperationOutcome, FileOperationRequest
from src.controllers.managed_file_operation_lane import (
    FileOperationCompletion, FileOperationProgress, FileOperationReservation, ManagedFileOperationLane,
)


def pump(app, predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        threading.Event().wait(0.001)
    assert predicate(), "finite Qt drain deadline exceeded"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def lanes(app):
    made = []
    def make(backend, **kwargs):
        lane = ManagedFileOperationLane(backend, **kwargs)
        made.append((lane, backend))
        return lane
    yield make
    for lane, backend in made:
        if hasattr(backend, "release"):
            backend.release.set()
        lane.begin_close()
    for lane, _ in made:
        pump(app, lambda: lane.closed)


class Backend:
    def __init__(self, block=False, fail=False):
        self.entered = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.calls = []
        self.fail = fail
    def execute_item(self, request, index):
        self.calls.append((request.operation_id, index, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(5), "test backend was not released"
        if self.fail and index == 0:
            raise RuntimeError("PRIVATE-SYNTHETIC-PATH-SECRET")
        return FileOperationOutcome(request.task_ids[index], "", True)


def request(name="one", tasks=("one",)):
    return FileOperationRequest(name, "undo", task_ids=tasks)


def test_real_serial_apply_undo_and_queued_owner_delivery(tmp_path, app, lanes):
    source = tmp_path / "original.txt"
    source.write_text("synthetic content", encoding="utf-8")
    stat = source.stat()
    plan = RenamePlan("task-one", str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                      "renamed.txt", str(tmp_path), ".txt")
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    worker_ids = []
    execute = backend.execute_item
    def recording(req, index):
        worker_ids.append(threading.get_ident())
        return execute(req, index)
    backend.execute_item = recording
    lane = lanes(backend, capacity=1)
    progress, complete, slots = [], [], []
    lane.itemCompleted.connect(lambda value: (progress.append(value), slots.append(threading.get_ident())))
    lane.completed.connect(lambda value: (complete.append(value), slots.append(threading.get_ident())))
    reservation = lane.reserve(FileOperationRequest("apply-one", "apply", "batch-one", (plan,)))
    assert reservation is not None and source.exists()
    assert not (tmp_path / "renamed.txt").exists()
    assert lane.reserve(request("other")) is None
    assert lane.commit(reservation) and not lane.commit(reservation)
    pump(app, lambda: len(complete) == 1 and lane.workers_idle)
    assert complete[0].reservation is reservation and progress[0].reservation is reservation
    assert complete[0].results[0].success and not source.exists()
    assert RenameHistory(tmp_path / "history.jsonl").get_all()[0].batch_id == "batch-one"
    undo = lane.reserve(request("undo", ("task-one",)))
    assert lane.commit(undo)
    pump(app, lambda: len(complete) == 2 and lane.workers_idle)
    assert source.read_text(encoding="utf-8") == "synthetic content"
    assert RenameHistory(tmp_path / "history.jsonl").get_all()[0].undone
    assert set(slots) == {threading.get_ident()}
    assert worker_ids and len(set(worker_ids)) == 1 and worker_ids[0] != threading.get_ident()


def test_shared_receipt_before_worker_collision_and_undo_pre_qt(tmp_path, app, lanes):
    from src.core.watch_self_events import WatchSelfEvents
    source = tmp_path / "original.txt"; source.write_bytes(b"synthetic receipt content")
    occupied = tmp_path / "renamed.txt"; occupied.write_bytes(b"retain collision")
    value = source.stat()
    plan = RenamePlan("row", str(source), SourceFingerprint(value.st_size, value.st_mtime_ns),
        "renamed.txt", str(tmp_path), ".txt")
    backend = FileOperationBackend(tmp_path / "history.jsonl")
    receipts = WatchSelfEvents()
    lane = lanes(backend)
    lane.attach_receipts(receipts)
    emitted = threading.Event()
    lane._completionReady.connect(lambda _: emitted.set(), Qt.ConnectionType.DirectConnection)
    reservation = lane.reserve(FileOperationRequest("op", "apply", "batch", (plan,)))
    assert receipts.decision(str(tmp_path / "renamed_1.txt")) == "hold"
    assert lane.commit(reservation)
    assert emitted.wait(3)
    # No Qt pumping yet. Native successful identity/content settlement is owned
    # before the public file-operation result is delivered.
    found = []
    thread = threading.Thread(target=lambda: found.append(receipts.decision(str(tmp_path / "renamed_1.txt"))))
    thread.start(); thread.join(3)
    assert not thread.is_alive() and found == ["suppress"]
    pump(app, lambda: lane.workers_idle)
    undo = lane.reserve(request("undo", ("row",)))
    assert lane.commit(undo)
    pump(app, lambda: lane.workers_idle)
    found.clear()
    thread = threading.Thread(target=lambda: found.append(receipts.decision(str(source))))
    thread.start(); thread.join(3)
    assert not thread.is_alive() and found == ["suppress"]
    assert occupied.read_bytes() == b"retain collision"
    receipts.begin_close(); assert receipts.workers_idle


def test_receipt_is_retired_when_real_submission_refuses(app, lanes, monkeypatch):
    from src.core.watch_self_events import WatchSelfEvents
    receipts = WatchSelfEvents()
    lane = lanes(Backend())
    lane.attach_receipts(receipts)
    reserved = lane.reserve(request("submit-refusal"))
    def refuse(*args, **kwargs): raise RuntimeError("synthetic executor refusal")
    monkeypatch.setattr(lane._executor, "submit", refuse)
    assert lane.commit(reserved) is False
    receipts.begin_close()
    assert receipts.workers_idle
    assert lane.closed


def test_exact_reservations_capacity_and_fifo(app, lanes):
    backend = Backend(block=True)
    lane = lanes(backend, capacity=4)
    foreign = lanes(Backend()).reserve(request("foreign"))
    one = lane.reserve(request("one", ("a", "b")))
    two = lane.reserve(request("two"))
    cancel = lane.reserve(request("cancel"))
    assert lane.owned_item_count == 4 and lane.reserve(request("overflow")) is None
    assert lane.reserve(request("one")) is None
    for forged in (FileOperationReservation(one.request), replace(one), foreign):
        assert not lane.commit(forged) and not lane.cancel(forged)
    assert lane.cancel(cancel) and not lane.cancel(cancel)
    assert not lane.commit(cancel)
    assert lane.commit(one) and lane.commit(two)
    assert not lane.cancel(one) and lane.pending_job_count == 2
    assert backend.entered.wait(2)
    complete, progress = [], []
    lane.completed.connect(complete.append)
    lane.itemCompleted.connect(progress.append)
    backend.release.set()
    pump(app, lambda: lane.workers_idle)
    assert [(a, b) for a, b, _ in backend.calls] == [("one", 0), ("one", 1), ("two", 0)]
    assert [p.index for p in progress] == [0, 1, 0]
    assert [c.reservation for c in complete] == [one, two]
    assert lane.owned_item_count == lane.pending_job_count == 0


def test_blocked_worker_qt_responsive_and_close_drains_without_cancellation(app, lanes):
    backend = Backend(block=True)
    lane = lanes(backend, capacity=3)
    active = lane.reserve(request("active"))
    waiting = lane.reserve(request("waiting"))
    reserved = lane.reserve(request("reserved"))
    assert lane.commit(active) and lane.commit(waiting)
    assert backend.entered.wait(2)
    tick = []
    QTimer.singleShot(0, lambda: tick.append(True))
    pump(app, lambda: bool(tick))
    lane.begin_close()
    lane.begin_close()
    assert lane.owned_item_count == 2 and not lane.commit(reserved)
    assert lane.reserve(request("late")) is None and not lane.closed and not lane.workers_idle
    backend.release.set()
    deadline = time.monotonic() + 2
    while len(backend.calls) < 2 and time.monotonic() < deadline:
        threading.Event().wait(0.001)
    assert len(backend.calls) == 2
    assert not lane.workers_idle and not lane.closed and lane.owned_item_count == 2
    pump(app, lambda: lane.closed)
    assert lane.workers_idle and lane.owned_item_count == 0


def test_redacted_item_exception_continues(app, lanes):
    lane = lanes(Backend(fail=True))
    completed = []
    lane.completed.connect(completed.append)
    assert lane.commit(lane.reserve(request("a", ("a", "b"))))
    pump(app, lambda: lane.workers_idle)
    first, second = completed[0].results
    assert not first.success and first.recovery_required and first.new_path == ""
    assert first.task_id == "a" and first.error == "fileops.error.unknownOutcome"
    assert second.success


def test_wrong_thread_admission_is_rejected(app, lanes):
    lane = lanes(Backend())
    reservation = lane.reserve(request())
    errors = []
    def wrong():
        for call in (lambda: lane.reserve(request("other")), lambda: lane.commit(reservation),
                     lambda: lane.cancel(reservation), lane.begin_close):
            try:
                call()
            except RuntimeError as error:
                errors.append(str(error))
    thread = threading.Thread(target=wrong)
    thread.start()
    thread.join(2)
    assert not thread.is_alive() and errors == ["fileops.error.wrongThread"] * 4
    assert lane.owned_item_count == 1


def test_submit_failure_seals_and_retires_without_io(app, lanes, monkeypatch):
    backend = Backend()
    lane = lanes(backend)
    one, two = lane.reserve(request()), lane.reserve(request("two"))
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic rejected pool")
    monkeypatch.setattr(lane._executor, "submit", fail)
    complete = []
    lane.completed.connect(complete.append)
    assert not lane.commit(one) and not lane.commit(two)
    assert lane.reserve(request("late")) is None
    assert lane.owned_item_count == lane.pending_job_count == 0
    assert lane.closed and lane.workers_idle and not backend.calls and not complete


def test_terminal_reentrancy_retains_capacity_and_new_ownership(app, lanes):
    lane = lanes(Backend(), capacity=2)
    one = lane.reserve(request("same"))
    completed, new = [], []
    def terminal(value):
        completed.append(value)
        if value.reservation is one:
            assert lane.pending_job_count == 0 and lane.owned_item_count == 1
            assert not lane.workers_idle
            next_reservation = lane.reserve(request("same"))
            assert next_reservation is not None
            assert lane.commit(next_reservation)
            assert lane.owned_item_count == 2
            new.append(next_reservation)
    lane.completed.connect(terminal)
    assert lane.commit(one)
    pump(app, lambda: len(completed) == 2 and lane.workers_idle)
    assert completed[1].reservation is new[0] and lane.owned_item_count == 0


def test_fabricated_and_duplicate_payloads_cannot_publish_or_retire(app, lanes):
    backend = Backend(block=True)
    lane = lanes(backend, capacity=1)
    reservation = lane.reserve(request())
    progress, completed = [], []
    lane.itemCompleted.connect(progress.append)
    lane.completed.connect(completed.append)
    assert lane.commit(reservation) and backend.entered.wait(2)
    forged_result = FileOperationOutcome("one", "", True)
    lane._progressReady.emit(FileOperationProgress(reservation, 0, forged_result))
    lane._completionReady.emit(FileOperationCompletion(reservation, (forged_result,)))
    app.processEvents()
    assert not progress and not completed and lane.owned_item_count == 1
    backend.release.set()
    pump(app, lambda: lane.workers_idle)
    lane._progressReady.emit(progress[0])
    lane._completionReady.emit(completed[0])
    app.processEvents()
    assert len(progress) == len(completed) == 1 and lane.owned_item_count == 0


def test_nested_event_pump_holds_capacity_until_progress_callback_exits(app, lanes):
    lane = lanes(Backend(), capacity=1)
    completed, observed = [], []
    lane.completed.connect(completed.append)
    def progress(value):
        pump(app, lambda: bool(completed))
        observed.append(lane.owned_item_count)
        observed.append(lane.reserve(request("new")))
    lane.itemCompleted.connect(progress)
    assert lane.commit(lane.reserve(request()))
    pump(app, lambda: lane.workers_idle)
    assert observed == [1, None]


def test_actual_future_done_required_after_loop_and_deliveries_exit(app, lanes, monkeypatch):
    backend = Backend()
    lane = lanes(backend)
    tail_entered, tail_release = threading.Event(), threading.Event()
    submit = lane._executor.submit
    def delayed_submit(fn):
        def delayed():
            fn()
            tail_entered.set()
            assert tail_release.wait(5)
        return submit(delayed)
    monkeypatch.setattr(lane._executor, "submit", delayed_submit)
    try:
        assert lane.commit(lane.reserve(request()))
        assert tail_entered.wait(2)
        pump(app, lambda: lane.owned_item_count == 0)
        lane.begin_close()
        assert not lane.workers_idle and not lane.closed
        assert lane._futures and not lane._futures[0].done()
        tail_release.set()
        pump(app, lambda: lane.closed)
        assert not lane._futures
    finally:
        tail_release.set()


def test_native_callback_exception_does_not_leak_delivery(app, lanes, monkeypatch):
    lane = lanes(Backend())
    caught = []
    monkeypatch.setattr(sys, "excepthook", lambda kind, value, tb: caught.append(kind))
    def fail(value):
        raise RuntimeError("synthetic callback failure")
    lane.completed.connect(fail)
    assert lane.commit(lane.reserve(request()))
    lane.begin_close()
    pump(app, lambda: lane.closed)
    assert caught == [RuntimeError] and lane.owned_item_count == 0


def test_validation_and_reserved_cancellation_never_touch_backend(app, lanes):
    backend = Backend()
    lane = lanes(backend)
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        lane.reserve(object())
    corrupted = request()
    object.__setattr__(corrupted, "task_ids", ["one"])
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        lane.reserve(corrupted)
    reserved = lane.reserve(request("reserved"))
    lane.begin_close()
    assert not lane.commit(reserved) and lane.closed and not backend.calls


def test_capacity_is_held_in_terminal_callback_even_when_worker_finished(app, lanes):
    lane = lanes(Backend(), capacity=1)
    observed = []
    def completed(value):
        observed.extend([lane.owned_item_count, lane.pending_job_count,
                         lane.reserve(request("next")), lane.workers_idle])
        lane.begin_close()
        observed.append(lane.closed)
    lane.completed.connect(completed)
    assert lane.commit(lane.reserve(request()))
    pump(app, lambda: lane.closed)
    assert observed == [1, 0, None, False, False]


def test_terminal_emission_exit_is_owned_after_queued_callback_exit(app, lanes):
    lane = lanes(Backend(), capacity=1)
    entered, release = threading.Event(), threading.Event()
    completed = []
    lane.completed.connect(completed.append)
    def block_emission(value):
        entered.set()
        assert release.wait(5)
    lane._completionReady.connect(block_emission, Qt.ConnectionType.DirectConnection)
    try:
        assert lane.commit(lane.reserve(request()))
        assert entered.wait(2)
        pump(app, lambda: bool(completed))
        assert lane.pending_job_count == 0 and lane.owned_item_count == 1
        assert lane.reserve(request("next")) is None
        lane.begin_close()
        assert not lane.workers_idle and not lane.closed
        release.set()
        pump(app, lambda: lane.closed)
    finally:
        release.set()


def test_real_multiclient_partial_apply_and_ordered_partial_undo(tmp_path, app, lanes):
    def plan(task, name, target):
        source = tmp_path / name
        source.write_text(task, encoding="utf-8")
        stat = source.stat()
        return RenamePlan(task, str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                          target, str(tmp_path), ".txt")
    one = plan("one", "one.txt", "new-one.txt")
    bad = plan("bad", "bad.txt", "new-bad.txt")
    two = plan("two", "two.txt", "new-two.txt")
    (tmp_path / "bad.txt").unlink()
    lane = lanes(FileOperationBackend(tmp_path / "history.jsonl"), capacity=4)
    completed, progress = [], []
    lane.completed.connect(completed.append)
    lane.itemCompleted.connect(progress.append)
    client_a = lane.reserve(FileOperationRequest("client-a", "apply", "batch-a", (one, bad)))
    client_b = lane.reserve(FileOperationRequest("client-b", "apply", "batch-b", (two,)))
    assert lane.commit(client_a) and lane.commit(client_b)
    pump(app, lambda: len(completed) == 2 and lane.workers_idle)
    assert [c.reservation for c in completed] == [client_a, client_b]
    assert [p.result.task_id for p in progress] == ["one", "bad", "two"]
    assert [r.success for r in completed[0].results] == [True, False]
    assert completed[1].results[0].new_path == str(tmp_path / "new-two.txt")
    (tmp_path / "one.txt").write_text("occupied", encoding="utf-8")
    undo = lane.reserve(request("undo", ("two", "one", "missing")))
    assert lane.commit(undo)
    pump(app, lambda: len(completed) == 3 and lane.workers_idle)
    assert [(r.task_id, r.success) for r in completed[-1].results] == [
        ("two", True), ("one", False), ("missing", False)]
    assert (tmp_path / "two.txt").read_text(encoding="utf-8") == "two"
    records = RenameHistory(tmp_path / "history.jsonl").get_all()
    assert [(r.batch_id, r.undone) for r in records] == [("batch-a", False), ("batch-b", True)]


def test_lane_f0_marker_failure_retains_actual_source_path(tmp_path, app, lanes, monkeypatch):
    source = tmp_path / "original.txt"
    source.write_text("synthetic", encoding="utf-8")
    stat = source.stat()
    plan = RenamePlan("one", str(source), SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                      "renamed.txt", str(tmp_path), ".txt")
    lane = lanes(FileOperationBackend(tmp_path / "history.jsonl"))
    completed = []
    lane.completed.connect(completed.append)
    assert lane.commit(lane.reserve(FileOperationRequest("a", "apply", "b", (plan,))))
    pump(app, lambda: len(completed) == 1 and lane.workers_idle)
    def fail(*args):
        raise OSError("synthetic marker failure")
    monkeypatch.setattr(RenameHistory, "mark_records_undone", fail)
    assert lane.commit(lane.reserve(request("u")))
    lane.begin_close()
    pump(app, lambda: lane.closed)
    result = completed[-1].results[0]
    assert result.success and result.recovery_required and result.new_path == str(source)
    assert source.read_text(encoding="utf-8") == "synthetic"
    assert not (tmp_path / "renamed.txt").exists()


def test_one_thousand_item_capacity_and_duplicate_plan_tasks(app, lanes):
    lane = lanes(Backend(), capacity=1000)
    reservation = lane.reserve(request("full", tuple(str(i) for i in range(1000))))
    assert lane.owned_item_count == 1000 and lane.reserve(request("overflow")) is None
    assert lane.cancel(reservation) and lane.owned_item_count == 0
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        request("too-many", tuple(str(i) for i in range(1001)))
    plan = RenamePlan("one", "synthetic-source.txt", SourceFingerprint(1, 1),
                      "synthetic-target.txt", "synthetic-parent", ".txt")
    with pytest.raises(ValueError, match="^fileops.error.invalidRequest$"):
        FileOperationRequest("duplicates", "apply", "b", (plan, plan))


@pytest.mark.parametrize("capacity", [0, 1001, True, 1.5, "1"])
def test_capacity_exact_int(capacity, app):
    with pytest.raises(ValueError, match="^fileops.error.invalidCapacity$"):
        ManagedFileOperationLane(Backend(), capacity=capacity)
