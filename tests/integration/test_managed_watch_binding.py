"""Exact managed bindings through real controller installs and queued Qt delivery."""
from dataclasses import replace
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from src.controllers import watch_controller as watch_api
from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.watch_config import WatchConfigStore, WatchMode, WatchStatus
from src.core.watch_work import WatchAdmissionFailure
from tests.integration.test_managed_watch_analysis import lane, outcome, pump_until


class SyntheticObserver:
    """Finite real observer thread with an optionally blocked installation."""
    def __init__(self, start_release=None):
        self.handler = None
        self.entered = threading.Event()
        self.stop_event = threading.Event()
        self.start_release = start_release
        self.thread = None

    def schedule(self, handler, path, recursive=True):
        self.handler = handler

    def start(self):
        self.entered.set()
        if self.start_release is not None:
            assert self.start_release.wait(5), "synthetic install deadline"
        self.thread = threading.Thread(target=lambda: self.stop_event.wait(5),
                                       name="synthetic-binding-observer")
        self.thread.start()

    def unschedule_all(self):
        pass

    def stop(self):
        self.stop_event.set()

    def join(self, timeout=0):
        if self.thread is not None:
            self.thread.join(timeout)

    def is_alive(self):
        return self.thread is not None and self.thread.is_alive()


@pytest.fixture
def binding_lane(lane, tmp_path):
    harnesses = []

    class Harness:
        def __init__(self, *, delivery=False, blocked=False, gate=None, binding=None, pending_limit=1000):
            self.created, self.events, self.threads, self.thread_errors = [], [], [], []
            self.release = threading.Event() if blocked else None
            self.allow_recovery, self.recoveries = False, []
            self.clock = watch_api.FakeClock()
            self.scheduler = watch_api.FakeScheduler(self.clock)
            self.delivery = None
            if delivery:
                self.delivery = lane.make(
                    binding=binding or (lambda event: self.controller.managed_binding_state(event)
                        is not watch_api.WatchBindingState.STALE),
                    can_start=gate or (lambda event: self.controller.managed_binding_state(event)
                        is watch_api.WatchBindingState.READY), pending_limit=pending_limit)
                ingress = self.delivery.ingress
            else:
                ingress = ManagedWatchIngress(lane.service, lane.authority,
                    capture_guard=lane.source.guard, post_event=self.events.append)
            self.ingress = ingress
            self.controller = watch_api.WatchController(
                WatchConfigStore(tmp_path / f"watch-{len(harnesses)}.json"), self,
                self.clock, self.scheduler, managed_ingress=ingress,
                resource_guard=self, autostart=False)
            harnesses.append(self)
            self.controller.add_watch(lane.watch)

        def create(self):
            observer = SyntheticObserver(self.release)
            self.created.append(observer)
            return observer

        def recover(self, watch_id):
            self.recoveries.append(watch_id)
            return self.allow_recovery

        def start(self):
            self.controller.start_all()

        def run_thread(self, callback, *, wait=True):
            def checked():
                try:
                    callback()
                except BaseException as error:
                    self.thread_errors.append(error)
            thread = threading.Thread(target=checked, name="synthetic-binding-callback")
            self.threads.append(thread)
            thread.start()
            if wait:
                thread.join(2)
                assert not thread.is_alive(), "synthetic callback deadline"
                assert not self.thread_errors
            return thread

        def raw(self, name="captured.txt", observer=None):
            path = tmp_path / name
            path.write_text("synthetic binding source", encoding="utf-8")
            # Only the synthetic file's timestamp is aged, not controller state.
            import os
            os.utime(path, (time.time() - 10, time.time() - 10))
            observer = observer or self.created[-1]
            self.run_thread(lambda: observer.handler.on_file_event(str(path), watch_api.FileEvent.CREATED))
            entries = list(self.controller._pending_debounce.values())
            return entries[-1].admission if entries else None

        def stable(self):
            self.clock.advance(3)
            self.run_thread(self.scheduler.run_pending)
            if self.delivery is None:
                assert self.events
                return self.events[-1]

        def state(self, event):
            return self.controller.managed_binding_state(event)

    yield Harness
    for harness in harnesses:
        if harness.release is not None:
            harness.release.set()
        for thread in harness.threads:
            thread.join(2)
            assert not thread.is_alive()
        harness.controller.begin_close()
        if harness.delivery is not None:
            harness.delivery.begin_close()
            assert harness.delivery.drain(time.monotonic() + 2)
        else:
            for event in harness.events:
                harness.ingress.retire(event)
        for observer in harness.created:
            observer.stop()
            observer.join(2)
            assert not observer.is_alive()
        assert harness.controller.drain(time.monotonic() + 2)
        assert not harness.thread_errors


def test_resource_status_replacement_holds_original_capture_and_guarded_resume(binding_lane, lane):
    harness = binding_lane(); harness.start()
    admission = harness.raw()
    captured_work, captured_config = admission.work, admission.watch_config
    captured_settings = captured_work.settings
    installed = harness.created[0]
    catalog = lane.source.get()
    lane.source.install(replace(catalog, settings=replace(catalog.settings, max_content_chars=42)))
    assert lane.source.get().settings is not captured_settings
    harness.controller.resource_pause("watch")
    current = harness.controller.get_config("watch")
    assert current is not captured_config and current.status is WatchStatus.RESOURCE_PAUSED
    event = harness.stable()
    assert event.admission is admission
    assert harness.state(event) is watch_api.WatchBindingState.HELD
    assert admission.work is captured_work and admission.work.settings is captured_settings
    assert not admission.cancel_event.is_set() and harness.ingress.is_current(event)
    harness.controller.resume_watch("watch")
    assert harness.state(event) is watch_api.WatchBindingState.HELD
    harness.allow_recovery = True
    harness.controller.resume_watch("watch")
    assert harness.state(event) is watch_api.WatchBindingState.READY
    assert harness.recoveries == ["watch", "watch"] and harness.created == [installed]
    assert admission.work is captured_work and not admission.cancel_event.is_set()


@pytest.mark.parametrize("action", ["pause", "remove", "stop", "close", "reinstall", "edit"])
@pytest.mark.parametrize("stable_first", [False, True])
def test_real_lifecycle_invalidates_original_raw_capture(binding_lane, action, stable_first):
    harness = binding_lane(); harness.start()
    admission = harness.raw()
    event = harness.stable() if stable_first else None
    old_observer = harness.created[0]
    if event is not None:
        assert harness.state(event) is watch_api.WatchBindingState.READY
    if action in ("pause", "reinstall", "edit"):
        harness.controller.pause_watch("watch")
        if action == "edit":
            harness.controller.update_watch(replace(harness.controller.get_config("watch"), recursive=False))
    elif action == "remove": harness.controller.remove_watch("watch")
    elif action == "stop": harness.controller.stop_all()
    else: harness.controller.begin_close()
    assert admission.cancel_event.is_set()
    if event is not None:
        assert harness.state(event) is watch_api.WatchBindingState.STALE
        harness.ingress.retire(event)
    else:
        harness.clock.advance(3); harness.run_thread(harness.scheduler.run_pending)
        assert not harness.events
    if action in ("reinstall", "edit"):
        pump_until(lambda: harness.controller.observers_idle)
        harness.controller.resume_watch("watch")
        old_count = harness.ingress.owned_count
        assert harness.raw("old-handler.txt", observer=old_observer) is None
        assert harness.ingress.owned_count == old_count
        new_admission = harness.raw("new-handler.txt")
        new_event = harness.stable()
        assert new_admission is not admission and new_admission.incarnation != admission.incarnation
        assert harness.state(new_event) is watch_api.WatchBindingState.READY


def test_binding_query_authenticity_wrong_ingress_incarnation_and_unknown_types(binding_lane, lane):
    harness = binding_lane(); harness.start()
    admission = harness.raw(); event = harness.stable()
    assert harness.state(event) is watch_api.WatchBindingState.READY
    for forged in (None, object(), admission, replace(event),
                   replace(event, admission=replace(admission))):
        assert harness.state(forged) is watch_api.WatchBindingState.STALE
    foreign = binding_lane(); foreign.start()
    foreign.raw("foreign.txt"); other = foreign.stable()
    assert harness.state(other) is watch_api.WatchBindingState.STALE
    wrong = harness.ingress.capture(lane.watch, "not-installed", admission.work.source_path, "wrong")
    assert harness.ingress.post_stable(wrong, event.fingerprint)
    assert harness.state(harness.events[-1]) is watch_api.WatchBindingState.STALE


@pytest.mark.parametrize("field", ["id", "source_dir", "target_dir", "template_id", "recursive", "mode"])
def test_binding_key_tracks_each_policy_field_but_ignores_nonbinding_metadata(binding_lane, lane, tmp_path, field):
    harness = binding_lane(); harness.start()
    admission = harness.raw(); event = harness.stable()
    assert harness.state(event) is watch_api.WatchBindingState.READY
    key = harness.controller._managed_binding_key
    original = lane.watch
    alternate = tmp_path / "alternate"; alternate.mkdir()
    changes = dict(id="new-id", source_dir=str(alternate), target_dir=str(tmp_path.parent / "target"),
                   template_id="other", recursive=False, mode=WatchMode.AUTO_APPLY)
    changed = replace(original, **{field: changes[field]})
    assert key(changed) != key(original)
    assert key(replace(original, created_at="synthetic-created", updated_at="synthetic-updated",
                       status=WatchStatus.RESOURCE_PAUSED, version=2)) == key(original)
    # The query must also compare policy, not only authentic watch/incarnation IDs.
    copied = harness.ingress.capture(changed, admission.incarnation,
        str(Path(changed.source_dir) / "copied.txt"), "changed-policy")
    if type(copied) is WatchAdmissionFailure:
        assert harness.ingress.post_failure(copied)
    else:
        assert harness.ingress.post_stable(copied, event.fingerprint)
    assert harness.state(harness.events[-1]) is watch_api.WatchBindingState.STALE
    harness.controller.pause_watch("watch")
    if field == "id":
        harness.controller.remove_watch("watch")
        harness.controller.add_watch(replace(changed, status=WatchStatus.PAUSED))
    else:
        harness.controller.update_watch(replace(changed, status=WatchStatus.PAUSED))
    assert harness.state(event) is watch_api.WatchBindingState.STALE


@pytest.mark.parametrize("withdraw", [False, True])
def test_actual_blocked_observer_installation_holds_until_finished_or_withdrawn(binding_lane, withdraw):
    harness = binding_lane(blocked=True)
    thread = harness.run_thread(harness.start, wait=False)
    pump_until(lambda: bool(harness.created) and harness.created[0].entered.is_set())
    admission = harness.raw(); event = harness.stable()
    assert harness.state(event) is watch_api.WatchBindingState.HELD
    assert not admission.cancel_event.is_set()
    if withdraw:
        harness.controller.pause_watch("watch")
        assert harness.state(event) is watch_api.WatchBindingState.STALE
    harness.release.set(); thread.join(2)
    assert not thread.is_alive()
    assert harness.state(event) is (watch_api.WatchBindingState.STALE if withdraw
                                   else watch_api.WatchBindingState.READY)


def test_resource_held_actual_delivery_preserves_capture_then_resumes_via_qt(binding_lane, lane, monkeypatch):
    def run(work, **kwargs):
        lane.calls.append(work)
        return outcome(work)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    harness = binding_lane(delivery=True); harness.start()
    admission = harness.raw()
    harness.controller.resource_pause("watch")
    harness.stable()
    pump_until(lambda: bool(harness.delivery._queued))
    exact = harness.delivery._queued[0]
    assert exact.event.admission is admission and exact.future is None
    assert not lane.calls and not admission.cancel_event.is_set()
    harness.allow_recovery = True
    harness.controller.resume_watch("watch")
    pump_until(lambda: harness.delivery.workers_idle)
    assert lane.calls == [admission.work]
    assert len(lane.seen) == 1 and lane.seen[0].event is exact.event


@pytest.mark.parametrize("action", ["pause", "remove"])
def test_actual_lifecycle_from_start_predicate_prevents_worker_submission(binding_lane, lane, action):
    checked = []
    def gate(event):
        checked.append(event)
        if action == "pause": harness.controller.pause_watch("watch")
        else: harness.controller.remove_watch("watch")
        QCoreApplication.processEvents()
        return True
    harness = binding_lane(delivery=True, gate=gate); harness.start()
    admission = harness.raw(); harness.stable()
    pump_until(lambda: bool(checked))
    assert harness.delivery.drain(time.monotonic() + 1)
    assert not harness.delivery._pool._threads and not lane.seen
    assert admission.cancel_event.is_set()


def test_pausing_actual_resource_held_delivery_retires_without_inference(binding_lane, lane):
    harness = binding_lane(delivery=True); harness.start()
    admission = harness.raw(); harness.controller.resource_pause("watch"); harness.stable()
    pump_until(lambda: bool(harness.delivery._queued))
    harness.controller.pause_watch("watch")
    pump_until(lambda: harness.delivery.workers_idle)
    assert admission.cancel_event.is_set() and not lane.seen and not harness.delivery._pool._threads


def test_resource_held_admission_failure_publishes_once_without_source_io(binding_lane, lane, monkeypatch):
    harness = binding_lane(delivery=True); harness.start()
    harness.controller.resource_pause("watch")
    lane.authority.select_local()
    def forbidden(*args, **kwargs):
        pytest.fail("held admitted failure read source or ran inference")
    monkeypatch.setattr(lane.service, "run_prepared", forbidden)
    monkeypatch.setattr(harness.delivery.__class__, "_fingerprint", forbidden)
    harness.raw("failure.txt")
    pump_until(lambda: harness.delivery.workers_idle)
    assert len(lane.seen) == 1 and lane.seen[0].failure == "local_unavailable"
    assert not harness.delivery._pool._threads


def test_binding_query_is_pure_no_observer_filesystem_store_or_guard_calls(binding_lane, monkeypatch):
    harness = binding_lane(); harness.start()
    admission = harness.raw(); event = harness.stable()
    before = (harness.ingress.owned_count, admission.work, harness.controller.get_config("watch"))
    def forbidden(*args, **kwargs):
        pytest.fail("binding query crossed its read-only boundary")
    with monkeypatch.context() as patch:
        patch.setattr(harness.created[0], "is_alive", forbidden)
        patch.setattr(harness, "recover", forbidden)
        patch.setattr(harness.controller._store, "update", forbidden)
        patch.setattr(harness.ingress, "capture", forbidden)
        patch.setattr(watch_api.os, "stat", forbidden)
        for _ in range(3):
            assert harness.state(event) is watch_api.WatchBindingState.READY
    assert (harness.ingress.owned_count, admission.work, harness.controller.get_config("watch")) == before
    assert not admission.cancel_event.is_set()


def test_admitted_failure_binding_authenticity_and_closed_controller(binding_lane, lane):
    harness = binding_lane(); harness.start()
    lane.authority.select_local()
    harness.raw("failure.txt")
    failure = harness.events[-1]
    assert type(failure) is WatchAdmissionFailure
    assert harness.state(failure) is watch_api.WatchBindingState.READY
    assert harness.state(replace(failure)) is watch_api.WatchBindingState.STALE
    harness.controller.resource_pause("watch")
    assert harness.state(failure) is watch_api.WatchBindingState.HELD
    harness.controller.begin_close()
    assert harness.state(failure) is watch_api.WatchBindingState.STALE


def test_two_installed_watches_ready_watch_is_not_starved_by_resource_held_watch(binding_lane, lane, monkeypatch):
    def run(work, **kwargs):
        lane.calls.append(work)
        return outcome(work)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    harness = binding_lane(delivery=True)
    harness.controller.add_watch(replace(lane.watch, id="ready-watch"))
    harness.start()
    held = harness.raw("held-watch.txt", observer=harness.created[0])
    harness.controller.resource_pause("watch")
    harness.stable()
    pump_until(lambda: bool(harness.delivery._queued))
    exact = harness.delivery._queued[0]
    ready = harness.raw("ready-watch.txt", observer=harness.created[1])
    harness.stable()
    pump_until(lambda: len(lane.seen) == 1)
    assert lane.calls == [ready.work] and lane.seen[0].event.admission.watch_id == "ready-watch"
    assert harness.delivery.owned_count == 1 and harness.delivery._queued == [exact]
    assert exact.event.admission is held and exact.future is None and not held.cancel_event.is_set()
    harness.allow_recovery = True
    harness.controller.resume_watch("watch")
    pump_until(lambda: harness.delivery.workers_idle)
    assert lane.calls == [ready.work, held.work]
    assert len(lane.seen) == 2 and lane.seen[1].event is exact.event


@pytest.mark.parametrize("withdraw", [False, True])
def test_qt_delivery_holds_actual_starting_installation_without_submitting(binding_lane, lane, withdraw):
    harness = binding_lane(delivery=True, blocked=True)
    starter = harness.run_thread(harness.start, wait=False)
    pump_until(lambda: bool(harness.created) and harness.created[0].entered.is_set())
    admission = harness.raw(); harness.stable()
    pump_until(lambda: bool(harness.delivery._queued))
    exact = harness.delivery._queued[0]
    assert exact.event.admission is admission and exact.future is None
    assert not harness.delivery._pool._threads and not admission.cancel_event.is_set()
    if withdraw:
        harness.controller.pause_watch("watch")
    harness.release.set(); starter.join(2)
    assert not starter.is_alive()
    pump_until(lambda: harness.delivery.workers_idle)
    assert len(lane.seen) == (0 if withdraw else 1)
    if not withdraw:
        assert lane.seen[0].event is exact.event
    else:
        assert admission.cancel_event.is_set() and not harness.delivery._pool._threads


def test_post_gate_binding_resource_pause_holds_same_work_until_explicit_recovery(binding_lane, lane, monkeypatch):
    readiness, paused_owners = [], []
    def gate(event):
        state = harness.state(event)
        readiness.append(state)
        return state is watch_api.WatchBindingState.READY
    def binding(event):
        if readiness and not paused_owners:
            assert readiness[-1] is watch_api.WatchBindingState.READY
            harness.controller.resource_pause("watch")
            paused_owners.append(harness.delivery._owners[id(event)])
        return harness.state(event) is not watch_api.WatchBindingState.STALE
    def run(work, **kwargs):
        lane.calls.append(work)
        return outcome(work)
    monkeypatch.setattr(lane.service, "run_prepared", run)
    harness = binding_lane(delivery=True, gate=gate, binding=binding, pending_limit=1)
    harness.start()
    admission = harness.raw(); harness.stable()
    QCoreApplication.processEvents()
    assert len(paused_owners) == 1
    exact = paused_owners[0]
    assert exact.event.admission is admission and harness.ingress.is_current(exact.event)
    assert harness.state(exact.event) is watch_api.WatchBindingState.HELD
    assert exact.future is None and exact.issued is None
    assert harness.delivery._queued == [exact] and harness.delivery.owned_count == 1
    assert not admission.cancel_event.is_set() and not lane.calls and not lane.seen
    assert not harness.delivery._pool._threads
    assert harness.ingress.capture(lane.watch, admission.incarnation,
        admission.work.source_path, "over-capacity") is None
    harness.controller.resume_watch("watch")
    assert harness.state(exact.event) is watch_api.WatchBindingState.HELD
    harness.allow_recovery = True
    harness.controller.resume_watch("watch")
    pump_until(lambda: harness.delivery.workers_idle)
    assert lane.calls == [admission.work]
    assert len(lane.seen) == 1 and lane.seen[0].event is exact.event


@pytest.mark.parametrize("action", ["pause", "remove"])
def test_final_readiness_boundary_rechecks_actual_binding_withdrawal(binding_lane, lane, action):
    checks = []
    def gate(event):
        checks.append(event)
        if len(checks) == 2:
            if action == "pause": harness.controller.pause_watch("watch")
            else: harness.controller.remove_watch("watch")
            QCoreApplication.processEvents()
        return True
    harness = binding_lane(delivery=True, gate=gate); harness.start()
    admission = harness.raw(); harness.stable()
    QCoreApplication.processEvents()
    assert len(checks) == 2
    assert harness.delivery.drain(time.monotonic() + 1)
    assert admission.cancel_event.is_set() and not lane.seen and not harness.delivery._pool._threads
