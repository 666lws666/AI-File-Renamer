"""Qt owner-thread acknowledgements with real Python writer workers."""
from dataclasses import FrozenInstanceError
import importlib.util
from threading import Event, Thread, get_ident
import time

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from src.core.processing_authority import (
    ChoiceIntent, CloudDispatchBlocked, LocalReadiness, ProcessingMode, ProcessingStateError,
)
from src.core.processing_intent_store import ProcessingIntentStore, ProcessingIntentWriter

FP = "a" * 64


def coordinator_api():
    assert importlib.util.find_spec("src.controllers.processing_coordinator") is not None
    from src.controllers.processing_coordinator import ProcessingCoordinator
    return ProcessingCoordinator


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    yield application


@pytest.fixture
def make_coordinator(tmp_path, app):
    owned = []
    def make(store=None, **kwargs):
        c = coordinator_api()(store or ProcessingIntentStore(tmp_path / "intent.json"), **kwargs)
        owned.append(c)
        return c
    yield make
    for c in owned:
        c.begin_close()
        assert c.drain_choice_writer(deadline=time.monotonic() + 2)


class ControlledStore:
    def __init__(self, real, *, fail_first=False, blocked=False):
        self.real = real
        self.fail_first = fail_first
        self.started = Event()
        self.release = Event()
        self.choices = []
        self.worker_ids = []
        if not blocked:
            self.release.set()

    def load(self):
        return self.real.load()

    def save(self, intent):
        self.worker_ids.append(get_ident())
        self.choices.append(intent)
        self.started.set()
        assert self.release.wait(5)
        if self.fail_first and len(self.choices) == 1:
            raise OSError("private detail")
        self.real.save(intent)


def deliver(app, c):
    deadline = time.monotonic() + 2
    while c.pending_ack_count and time.monotonic() < deadline:
        app.processEvents()
    assert c.pending_ack_count == 0


def test_startup_is_readonly_and_properties_are_canonical(make_coordinator, tmp_path):
    path = tmp_path / "absent" / "intent.json"
    c = make_coordinator(ProcessingIntentStore(path))
    assert not path.parent.exists()
    assert c.processingMode == "cloud"
    assert c.localReadiness == "not_ready"
    assert c.persistenceStatus == "saved"
    assert c.errorCode == ""
    assert c.committedAttemptCount == 0
    assert c.admissionOpen and c.is_open
    with pytest.raises(FrozenInstanceError):
        c.snapshot.revision = 4
    for name in ("processingMode", "localReadiness", "persistenceStatus", "errorCode",
                 "committedAttemptCount", "admissionOpen"):
        prop = c.metaObject().property(c.metaObject().indexOfProperty(name))
        assert prop.hasNotifySignal() and not prop.isWritable()


def test_local_immediately_stales_business_and_authentic_probe_and_save_failure_stays_local(
        make_coordinator, tmp_path, app):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"), fail_first=True)
    c = make_coordinator(store)
    c.bind_cloud_engine(FP)
    business = c.authority.capture_work(engine_fingerprint=FP, task_attempt_id="business")
    probe = c.authority.capture_cloud_probe(candidate_fingerprint=FP,
                                           candidate_model="model", request_id="probe")
    c.selectLocal()
    assert c.processingMode == "local"
    assert not c.authority.is_current(business)
    assert not c.authority.is_current_cloud_probe(probe)
    assert store.started.wait(2)
    assert c._writer.close()  # write/post drained, not queued Qt delivery
    assert c.persistenceStatus == "pending"
    deliver(app, c)
    assert c.persistenceStatus == "error" and c.processingMode == "local"
    assert c.errorCode == "PROCESSING_PERSISTENCE_ERROR"


def test_cloud_only_opens_after_owner_thread_delivery(make_coordinator, tmp_path, app, monkeypatch):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"))
    c = make_coordinator(store)
    c.selectLocal()
    deliver(app, c)
    completions = []
    actual = c.authority.complete_choice
    def observed(intent, *, persisted):
        completions.append((get_ident(), QThread.currentThread() == c.thread()))
        return actual(intent, persisted=persisted)
    monkeypatch.setattr(c.authority, "complete_choice", observed)
    c.selectCloud()
    assert c._writer.close()
    assert c.pending_ack_count == 1
    assert c.processingMode == "local" and completions == []
    deliver(app, c)
    assert c.processingMode == "cloud"
    assert completions == [(get_ident(), True)]
    assert all(worker != get_ident() for worker in store.worker_ids)


def test_stale_old_failure_does_not_override_latest_choice(make_coordinator, tmp_path, app):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"),
                            fail_first=True, blocked=True)
    c = make_coordinator(store)
    c.selectCloud()
    assert store.started.wait(2)
    c.selectLocal()
    store.release.set()
    assert c._writer.close()
    deliver(app, c)
    assert c.processingMode == "local" and c.persistenceStatus == "saved"
    assert store.real.load().mode is ProcessingMode.LOCAL


def test_latest_failed_retry_reuses_exact_intent(make_coordinator, tmp_path, app):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"), fail_first=True)
    c = make_coordinator(store)
    assert not c.retryChoice()
    c.selectLocal()
    deliver(app, c)
    original = store.choices[0]
    assert c.persistenceStatus == "error"
    revision = c.snapshot.revision
    assert c.retryChoice()
    deliver(app, c)
    assert store.choices == [original, original]
    assert store.choices[1] is original
    assert c.snapshot.revision == revision
    assert c.persistenceStatus == "saved" and c.processingMode == "local"
    assert not c.retryChoice()


def test_offthread_operations_reject_before_any_side_effect(make_coordinator):
    c = make_coordinator()
    before = c.snapshot
    errors = []
    operations = [c.selectLocal, c.selectCloud, c.retryChoice,
        lambda: c.bind_cloud_engine(FP), c.invalidate_work,
        lambda: c.publish_local_state(before.generation, LocalReadiness.PREPARING),
        c.begin_close, lambda: c.drain_choice_writer(deadline=time.monotonic() + 1)]
    def run():
        for operation in operations:
            try:
                operation()
            except RuntimeError as error:
                errors.append(str(error))
    worker = Thread(target=run)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert len(errors) == len(operations)
    assert c.snapshot == before and c.is_open and c.pending_ack_count == 0


def test_close_before_cloud_ack_never_reopens_and_repeated_bounded_drain_completes(
        make_coordinator, tmp_path):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"), blocked=True)
    store.real.save(ChoiceIntent("startup", 1, ProcessingMode.LOCAL))
    c = make_coordinator(store)
    c.selectCloud()
    assert store.started.wait(2)
    generation = c.snapshot.generation
    c.begin_close()
    assert not c.admissionOpen and c.snapshot.generation == generation + 1
    c.begin_close()
    assert c.snapshot.generation == generation + 1
    start = time.monotonic()
    assert not c.drain_choice_writer(deadline=start + 0.02)
    assert time.monotonic() - start < 0.2
    store.release.set()
    assert c.drain_choice_writer(deadline=time.monotonic() + 2)
    assert c.pending_ack_count == 0 and c.processingMode == "local"
    assert store.real.load().mode is ProcessingMode.CLOUD
    for operation in (c.selectLocal, c.selectCloud, c.retryChoice,
                      lambda: c.bind_cloud_engine(FP), c.invalidate_work,
                      lambda: c.publish_local_state(c.snapshot.generation, LocalReadiness.PREPARING)):
        with pytest.raises(RuntimeError):
            operation()


def test_reentrant_close_drain_and_rejected_submit_keep_ack_ownership(make_coordinator, app):
    c = make_coordinator()
    results = []
    def close_during_publish():
        c.begin_close()
        results.append(c.drain_choice_writer(deadline=time.monotonic() + 0.01))
    c.stateChanged.connect(close_during_publish)
    c.selectLocal()
    assert c.processingMode == "local" and not c.is_open
    assert c.pending_ack_count == 1
    assert False in results
    assert c.drain_choice_writer(deadline=time.monotonic() + 2)
    app.processEvents()
    assert c.pending_ack_count == 0


def test_stale_readiness_real_identity_and_stable_ready_contexts(make_coordinator, app):
    c = make_coordinator()
    c.selectLocal()
    deliver(app, c)
    generation = c.snapshot.generation
    c.invalidate_work()
    assert not c.publish_local_state(generation, LocalReadiness.PREPARING)
    current = c.snapshot.generation
    with pytest.raises(ProcessingStateError):
        c.publish_local_state(current, LocalReadiness.READY)
    assert c.publish_local_state(current, LocalReadiness.PREPARING)
    assert c.localReadiness == "preparing"
    assert c.publish_local_state(current, LocalReadiness.READY, engine_fingerprint=FP)
    context = c.authority.capture_work(engine_fingerprint=FP, task_attempt_id="local")
    generation = c.snapshot.generation
    assert c.publish_local_state(generation, LocalReadiness.READY, engine_fingerprint=FP)
    assert c.snapshot.generation == generation and c.authority.is_current(context)
    assert c.publish_local_state(generation, LocalReadiness.CANCELLED)
    assert c.processingMode == "local" and not c.authority.is_current(context)


def test_local_revision_overflow_cannot_leave_cloud_open(make_coordinator, tmp_path):
    path = tmp_path / "intent.json"
    path.write_text('{"schema_version":1,"revision":9223372036854775807,"mode":"cloud"}')
    c = make_coordinator(ProcessingIntentStore(path))
    with pytest.raises(ProcessingStateError):
        c.selectLocal()
    assert c.processingMode == "local" and c.persistenceStatus == "error"
    assert c.pending_ack_count == 0


def test_explicit_writer_factory_injection(make_coordinator):
    writers = []
    def factory(store, authority, *, completion_callback):
        writer = ProcessingIntentWriter(store, authority, completion_callback=completion_callback)
        writers.append(writer)
        return writer
    c = make_coordinator(writer_factory=factory)
    assert c._writer is writers[0]


def test_repeat_cloud_business_and_probe_wait_for_actual_qt_ack_on_failure_retry_success(
        make_coordinator, tmp_path, app):
    store = ControlledStore(ProcessingIntentStore(tmp_path / "intent.json"), fail_first=True)
    posted = Event()
    def factory(store, authority, *, completion_callback):
        def complete(intent, persisted):
            completion_callback(intent, persisted)
            posted.set()
        return ProcessingIntentWriter(store, authority, completion_callback=complete)
    c = make_coordinator(store, writer_factory=factory)
    c.bind_cloud_engine(FP)
    def business():
        return c.authority.capture_work(engine_fingerprint=FP, task_attempt_id="business")
    def probe():
        return c.authority.capture_cloud_probe(candidate_fingerprint=FP,
                                              candidate_model="model", request_id="probe")
    old_business, old_probe = business(), probe()
    receipt = c.authority.commit_cloud_attempt(old_business, "committed")
    c.selectCloud()
    assert posted.wait(2)
    assert c.pending_ack_count == 1 and c.persistenceStatus == "pending"
    assert not c.authority.is_current(old_business)
    assert not c.authority.is_current_cloud_probe(old_probe)
    for take in (business, probe):
        with pytest.raises(CloudDispatchBlocked):
            take()
    deliver(app, c)
    assert c.persistenceStatus == "error"
    for take in (business, probe):
        with pytest.raises(CloudDispatchBlocked):
            take()
    original = store.choices[0]
    posted.clear()
    assert c.retryChoice()
    assert posted.wait(2)
    assert c.pending_ack_count == 1
    for take in (business, probe):
        with pytest.raises(CloudDispatchBlocked):
            take()
    deliver(app, c)
    assert c.persistenceStatus == "saved" and c.processingMode == "cloud"
    assert store.choices[1] is original
    assert c.authority.is_current(business())
    assert c.authority.is_current_cloud_probe(probe())
    assert not c.authority.is_current(old_business)
    assert not c.authority.is_current_cloud_probe(old_probe)
    c.authority.finish_attempt(receipt)


def test_oversized_drain_deadline_has_fixed_error_before_side_effects(make_coordinator):
    c = make_coordinator()
    before = c.snapshot
    with pytest.raises(ValueError, match="^PROCESSING_DRAIN_DEADLINE_ERROR$"):
        c.drain_choice_writer(deadline=10**1000)
    assert c.snapshot == before and c.is_open
    assert not c._writer._closed
