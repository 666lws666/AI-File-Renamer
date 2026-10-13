"""Actual Python timer/observer ownership; no Qt pumping or file execution."""
import time
from threading import Event, Thread

import pytest

from src.controllers.watch_controller import (DebounceScheduler, FakeClock, FakeScheduler,
    FileEvent, ObserverFactory, WatchController, WatchControllerError)
from src.core.watch_config import WatchConfig, WatchConfigStore, WatchStatus


def test_real_timer_blocked_callback_retained_after_cancel_and_finite_drain():
    scheduler = DebounceScheduler()
    entered, release = Event(), Event()
    scheduler.schedule(0, lambda: (entered.set(), release.wait(3)), task_id="same")
    assert entered.wait(2)
    scheduler.cancel_all()
    try:
        assert not scheduler.workers_idle, "running timer forgotten after cancel"
        assert not scheduler.drain(time.monotonic() + .02)
    finally:
        release.set()
    assert scheduler.drain(time.monotonic() + 2)


def test_real_timer_old_callback_cannot_pop_replacement():
    scheduler = DebounceScheduler()
    entered, release, replacement = Event(), Event(), Event()
    scheduler.schedule(0, lambda: (entered.set(), release.wait(3)), task_id="same")
    assert entered.wait(2)
    scheduler.schedule(.05, replacement.set, task_id="same")
    release.set()
    assert replacement.wait(2)
    assert scheduler.drain(time.monotonic() + 2)


class ControlledObserver:
    def __init__(self):
        self.release = Event(); self.entered = Event(); self.stop_called = Event()
        self.thread = None; self.handler = None; self.callback_blocked = False
    def schedule(self, handler, path, recursive=True): self.handler = handler
    def start(self):
        self.thread = Thread(target=lambda: (self.entered.set(), self.release.wait(5)), daemon=True)
        self.thread.start(); assert self.entered.wait(2)
    def unschedule_all(self): pass
    def stop(self):
        self.stop_called.set()
        # A callback during stop must not find a controller-held lock.
        finished = Event()
        callback = Thread(target=lambda: (self.handler.on_file_event(self.source, FileEvent.CREATED),
                                          finished.set()), daemon=True)
        callback.start()
        self.callback_blocked = not finished.wait(.1)
    def join(self, timeout=0): pytest.fail("blocking observer join forbidden")
    def is_alive(self): return self.thread is not None and self.thread.is_alive()


class ControlledFactory:
    def __init__(self, source): self.created = []; self.source = source
    def create(self):
        observer = ControlledObserver(); observer.source = self.source
        self.created.append(observer); return observer


def _wait_for_observers_idle(controller, timeout=2):
    """Wait for actual observer AND retirement-worker exit, failing at a finite deadline."""
    deadline = time.monotonic() + timeout
    while not controller.observers_idle:
        remaining = deadline - time.monotonic()
        assert remaining > 0, "observer ownership did not become idle before the deadline"
        time.sleep(min(.005, remaining))  # Predicate polling, not an assumed teardown delay.


def test_retired_observer_is_owned_and_blocks_same_id_replacement(tmp_path):
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
    store = WatchConfigStore(tmp_path / "watch.json")
    factory = ControlledFactory(str(source))
    controller = WatchController(store, factory)
    config = WatchConfig(id="same", source_dir=str(tmp_path))
    controller.add_watch(config)
    old = factory.created[0]
    try:
        started = time.monotonic()
        controller.remove_watch("same")
        assert time.monotonic() - started < .3
        assert not old.callback_blocked, "stop held a callback-needed lock"
        assert not controller.observers_idle
        controller.add_watch(config)
        assert len(factory.created) == 1
        assert not controller.drain(time.monotonic() + .02)
        old.release.set(); old.thread.join(2)
        _wait_for_observers_idle(controller)
        controller.resume_watch("same")
        assert len(factory.created) == 2
    finally:
        for observer in factory.created: observer.release.set()
        if hasattr(controller, "begin_close"):
            controller.begin_close()
        for observer in factory.created:
            if observer.thread is not None: observer.thread.join(2)
    assert controller.drain(time.monotonic() + 2)


def test_deferred_constructor_starts_only_active_once(tmp_path):
    store = WatchConfigStore(tmp_path / "watch.json")
    for i, status in enumerate(WatchStatus):
        root = tmp_path / str(i); root.mkdir()
        store.add(WatchConfig(id=str(i), source_dir=str(root), status=status))
    factory = ObserverFactory(use_mock=True)
    controller = WatchController(store, factory, autostart=False)
    assert not factory.created_observers
    assert [cfg.status for cfg in controller.list_configs()] == list(WatchStatus)
    controller.start_all(); controller.start_all()
    assert len(factory.created_observers) == 1
    controller.stop_all()
    assert controller.get_status("0") is WatchStatus.ACTIVE
    controller.start_all()
    assert len(factory.created_observers) == 2
    controller.begin_close(); controller.start_all()
    assert controller.drain(time.monotonic() + 1) and len(factory.created_observers) == 2


def test_dispatched_old_debounce_cannot_remove_new_entry(tmp_path):
    source = tmp_path / "synthetic.txt"; source.write_text("synthetic")
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"),
        ObserverFactory(use_mock=True), clock, scheduler)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path)))
    seen = []; controller.on_file_ready = lambda *args: seen.append(args)
    controller._simulate_file_event("watch", str(source), FileEvent.CREATED)
    old = scheduler._pending[0][1]
    controller._simulate_file_event("watch", str(source), FileEvent.MODIFIED)
    old()
    assert not seen and scheduler.pending_count == 1
    clock.advance(2); scheduler.run_pending()
    assert len(seen) == 1
    controller.begin_close()


def test_real_timer_callback_tail_keeps_actual_thread_owned(monkeypatch):
    import threading
    actual_timer = threading.Timer
    tail, release = Event(), Event()
    class TailTimer(actual_timer):
        def run(self):
            super().run()
            tail.set(); assert release.wait(3)
    monkeypatch.setattr(threading, "Timer", TailTimer)
    scheduler = DebounceScheduler()
    scheduler.schedule(0, lambda: None)
    assert tail.wait(2)
    try:
        assert not scheduler.workers_idle and not scheduler.drain(time.monotonic() + .02)
    finally:
        release.set()
    assert scheduler.drain(time.monotonic() + 2)


def test_cancelled_started_timer_cannot_claim_replacement(monkeypatch):
    import threading
    actual_timer = threading.Timer
    entered, release = Event(), Event()
    created = []
    class DispatchedTimer(actual_timer):
        def run(self):
            entered.set(); assert release.wait(3)
            # Model a callback already dispatched when cancellation arrived.
            self.function(*self.args, **self.kwargs)
    monkeypatch.setattr(threading, "Timer", DispatchedTimer)
    scheduler = DebounceScheduler()
    scheduler.schedule(0, lambda: created.append("old"), task_id="same")
    assert entered.wait(2)
    scheduler.schedule(0, lambda: created.append("new"), task_id="same")
    release.set()
    assert scheduler.drain(time.monotonic() + 2)
    assert created == ["new"]


def test_failed_start_racing_pause_never_overwrites_pause_or_schedules_retry(tmp_path):
    entered, release = Event(), Event()
    class FailingStartObserver(ControlledObserver):
        def start(self):
            entered.set(); assert release.wait(3)
            raise RuntimeError("synthetic start failure")
    class Factory:
        def __init__(self): self.created = []
        def create(self):
            observer = FailingStartObserver(); observer.source = str(tmp_path / "synthetic.txt")
            self.created.append(observer); return observer
    clock = FakeClock(); scheduler = FakeScheduler(clock); factory = Factory()
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    thread = Thread(target=lambda: controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path))))
    thread.start(); assert entered.wait(2)
    try:
        controller.pause_watch("watch")
    finally:
        release.set(); thread.join(2)
    assert not thread.is_alive()
    assert controller.get_status("watch") is WatchStatus.PAUSED
    assert scheduler.pending_count == 0
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


def test_reentrant_resume_does_not_publish_active_before_actual_start(tmp_path):
    entered, release = Event(), Event()
    class BlockingStartObserver(ControlledObserver):
        def start(self):
            entered.set(); assert release.wait(3); super().start()
    class Factory:
        def __init__(self): self.created = []
        def create(self):
            observer = BlockingStartObserver(); observer.source = str(tmp_path / "synthetic.txt")
            self.created.append(observer); return observer
    factory = Factory()
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path), status=WatchStatus.PAUSED))
    thread = Thread(target=lambda: controller.resume_watch("watch"))
    thread.start(); assert entered.wait(2)
    try:
        controller.resume_watch("watch")
        assert controller.get_status("watch") is WatchStatus.PAUSED
    finally:
        release.set(); thread.join(2)
        controller.begin_close()
        for observer in factory.created:
            observer.release.set()
            if observer.thread is not None: observer.thread.join(2)
    assert not thread.is_alive() and len(factory.created) == 1
    assert controller.drain(time.monotonic() + 1)


def test_start_all_snapshot_cannot_start_watch_paused_before_install(tmp_path):
    factory = ObserverFactory(use_mock=True)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, autostart=False)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path)))
    original = controller._start_observer
    def race(config_id, state, **kwargs):
        controller.pause_watch(config_id)
        return original(config_id, state, **kwargs)
    controller._start_observer = race
    controller.start_all()
    assert not factory.created_observers and controller.get_status("watch") is WatchStatus.PAUSED
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


def test_failed_start_retains_and_stops_an_actual_created_live_observer(tmp_path):
    class FailedLiveObserver(ControlledObserver):
        def start(self):
            super().start()
            raise RuntimeError("synthetic failure after actual thread start")
    class Factory(ControlledFactory):
        def create(self):
            observer = FailedLiveObserver(); observer.source = self.source
            self.created.append(observer); return observer
    factory = Factory(str(tmp_path / "synthetic.txt"))
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path)))
    observer = factory.created[0]
    try:
        assert observer.stop_called.is_set() and observer.is_alive()
        assert controller.get_status("watch") is WatchStatus.ERROR
        assert not controller.observers_idle
        with pytest.raises(WatchControllerError, match="^observer_retiring$"):
            controller.resume_watch("watch")
        controller.begin_close()
        assert not controller.drain(time.monotonic() + .02)
    finally:
        observer.release.set(); observer.thread.join(2)
        controller.begin_close()
    assert controller.drain(time.monotonic() + 1)


def test_removed_recreated_watch_cannot_duplicate_observer_while_old_start_runs(tmp_path):
    entered, start_release = Event(), Event()
    class StartingObserver(ControlledObserver):
        def start(self):
            entered.set(); assert start_release.wait(3); super().start()
    class Factory(ControlledFactory):
        def create(self):
            observer = StartingObserver(); observer.source = self.source
            self.created.append(observer); return observer
    factory = Factory(str(tmp_path / "synthetic.txt"))
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    config = WatchConfig(id="same", source_dir=str(tmp_path))
    thread = Thread(target=lambda: controller.add_watch(config))
    thread.start(); assert entered.wait(2)
    try:
        controller.remove_watch("same"); controller.add_watch(config)
        assert len(factory.created) == 1 and not controller.observers_idle
        start_release.set(); thread.join(2)
        old = factory.created[0]
        assert not thread.is_alive() and old.stop_called.is_set() and old.is_alive()
        assert controller._get_observer("same") is None
        with pytest.raises(WatchControllerError, match="^observer_retiring$"):
            controller.resume_watch("same")
        old.release.set(); old.thread.join(2)
        _wait_for_observers_idle(controller)
        controller.resume_watch("same")
        assert len(factory.created) == 2
    finally:
        start_release.set(); thread.join(2)
        controller.begin_close()
        for observer in factory.created:
            observer.release.set()
            if observer.thread is not None: observer.thread.join(2)
    assert controller.drain(time.monotonic() + 1)


def test_start_all_releases_initial_defer_for_later_active_add_only(tmp_path):
    factory = ObserverFactory(use_mock=True)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, autostart=False)
    first = tmp_path / "first"; first.mkdir()
    controller.add_watch(WatchConfig(id="first", source_dir=str(first)))
    assert not factory.created_observers
    controller.start_all(); controller.start_all()
    second = tmp_path / "second"; second.mkdir()
    controller.add_watch(WatchConfig(id="second", source_dir=str(second)))
    assert len(factory.created_observers) == 2
    for status in (WatchStatus.PAUSED, WatchStatus.ERROR, WatchStatus.RESOURCE_PAUSED):
        root = tmp_path / status.value; root.mkdir()
        controller.add_watch(WatchConfig(id=status.value, source_dir=str(root), status=status))
    controller.start_all()
    assert len(factory.created_observers) == 2
    controller.begin_close(); controller.start_all()
    with pytest.raises(WatchControllerError, match="^closed$"):
        controller.add_watch(WatchConfig(id="after-close", source_dir=str(tmp_path)))
    assert len(factory.created_observers) == 2 and controller.drain(time.monotonic() + 1)


def test_failed_add_after_defer_release_retains_existing_live_state(tmp_path, monkeypatch):
    from src.core.watch_config import WatchConfigPersistenceError
    factory = ObserverFactory(use_mock=True)
    store = WatchConfigStore(tmp_path / "watch.json")
    controller = WatchController(store, factory, autostart=False)
    first = tmp_path / "first"; first.mkdir()
    config = WatchConfig(id="first", source_dir=str(first))
    controller.add_watch(config); controller.start_all()
    observer = controller._get_observer("first")
    second = tmp_path / "second"; second.mkdir()
    def fail(*args): raise WatchConfigPersistenceError("synthetic")
    with monkeypatch.context() as patch:
        patch.setattr(store, "add", fail)
        with pytest.raises(WatchControllerError):
            controller.add_watch(WatchConfig(id="second", source_dir=str(second)))
    assert controller.get_config("first") is config and controller._get_observer("first") is observer
    assert not controller.is_watching("second") and len(factory.created_observers) == 1
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


@pytest.mark.parametrize("operation", ["pause", "remove", "stop_all", "begin_close"])
def test_real_watchdog_emitter_teardown_never_blocks_lifecycle_caller(tmp_path, operation):
    from watchdog.observers.api import BaseObserver, EventEmitter
    import threading
    entered, release, called = Event(), Event(), Event()
    teardown_threads = []
    class HeldEmitter(EventEmitter):
        def queue_events(self, timeout):
            entered.set(); assert release.wait(5)
        def join(self, *args, **kwargs):
            teardown_threads.append(threading.current_thread())
            return super().join(*args, **kwargs)
    class Factory:
        def __init__(self): self.created = []
        def create(self):
            observer = BaseObserver(HeldEmitter, timeout=.01)
            self.created.append(observer); return observer
    factory = Factory(); clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    config = WatchConfig(id="watch", source_dir=str(tmp_path))
    controller.add_watch(config)
    observer = factory.created[0]; emitters = tuple(observer.emitters)
    assert entered.wait(2)
    def lifecycle():
        if operation == "pause": controller.pause_watch("watch")
        elif operation == "remove": controller.remove_watch("watch")
        else: getattr(controller, operation)()
        called.set()
    caller = Thread(target=lifecycle, name="synthetic-lifecycle-caller")
    caller.start()
    try:
        assert called.wait(.2), "real watchdog unschedule/stop joined a held emitter on lifecycle caller"
        caller.join(1)
        assert not controller.observers_idle
        assert not controller.drain(time.monotonic() + .02)
        owner = controller._observer_owners[id(observer)]
        assert owner.teardown_thread is not None and owner.teardown_thread.is_alive()
        assert owner.emitters == emitters
        if operation == "pause":
            with pytest.raises(WatchControllerError, match="^observer_retiring$"):
                controller.resume_watch("watch")
        elif operation == "remove":
            controller.add_watch(config)
        elif operation == "stop_all":
            with pytest.raises(WatchControllerError, match="^observer_retiring$"):
                controller.start_all()
        else: controller.start_all()
        assert len(factory.created) == 1
    finally:
        release.set(); caller.join(2)
        controller.begin_close()
        observer.join(2)  # synthetic fixture cleanup, never the product lifecycle caller
        for emitter in emitters: emitter.join(2)
        assert controller.drain(time.monotonic() + 2)
    assert not caller.is_alive() and not observer.is_alive()
    assert teardown_threads and all(thread is not caller for thread in teardown_threads)


@pytest.mark.parametrize("operation", ["resume", "retry"])
def test_stop_between_install_and_publish_preserves_original_saved_choice(tmp_path, operation):
    status = WatchStatus.PAUSED if operation == "resume" else WatchStatus.ERROR
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"),
        ObserverFactory(use_mock=True), clock, scheduler)
    config = WatchConfig(id="watch", source_dir=str(tmp_path), status=status)
    controller.add_watch(config)
    original = controller._start_observer
    def cancelled(*args, **kwargs):
        result = original(*args, **kwargs)
        controller.stop_all()
        return result
    controller._start_observer = cancelled
    if operation == "resume": controller.resume_watch("watch")
    else: controller.restart_after_failure("watch")
    assert controller.get_config("watch") is config
    assert controller._store.get("watch").status is status
    assert controller._get_observer("watch") is None and controller._stopped
    assert scheduler.pending_count == 0
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


def test_timer_steady_state_mutation_reaps_exited_owners_without_idle_poll():
    scheduler = DebounceScheduler()
    entered, release = Event(), Event()
    scheduler.schedule(0, lambda: (entered.set(), release.wait(5)), task_id="blocked")
    assert entered.wait(2)
    blocked = next(timer for timer in scheduler._owned if timer.is_alive())
    try:
        for i in range(30):
            done = Event(); scheduler.schedule(0, done.set, task_id=str(i))
            assert done.wait(2)
            for timer in tuple(scheduler._owned):
                if timer is not blocked: timer.join(1)  # exited synthetic fixture threads only
            # No workers_idle/drain call: ordinary traffic must reap historical exits.
            assert len(scheduler._owned) <= 2, "historical exited timers accumulated"
            assert blocked in scheduler._owned and blocked.is_alive()
        scheduler.cancel("missing")
        assert scheduler._owned == {blocked}
        scheduler.cancel_all()
        assert blocked in scheduler._owned and blocked.is_alive()
    finally:
        release.set()
    assert scheduler.drain(time.monotonic() + 2)


@pytest.mark.parametrize("operation", ["resume", "retry"])
def test_old_installation_cannot_publish_for_same_config_new_observer(tmp_path, operation):
    status = WatchStatus.PAUSED if operation == "resume" else WatchStatus.ERROR
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"),
        ObserverFactory(use_mock=True), clock, scheduler)
    config = WatchConfig(id="watch", source_dir=str(tmp_path), status=status)
    controller.add_watch(config)
    original = controller._start_observer
    replacements = []
    def replaced(*args, **kwargs):
        old = original(*args, **kwargs)
        controller.stop_all(); controller.start_all()  # opens, but preserves non-ACTIVE choice
        original("watch", controller._watches["watch"], expected_config=config)
        replacements.append(controller._get_observer("watch"))
        return old
    controller._start_observer = replaced
    if operation == "resume": controller.resume_watch("watch")
    else: controller.restart_after_failure("watch")
    assert controller.get_config("watch") is config
    assert controller._store.get("watch").status is status
    assert controller._get_observer("watch") is replacements[0] and replacements[0].is_alive()
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


@pytest.mark.parametrize("operation", ["resume", "retry"])
def test_old_persist_failure_cannot_detach_or_schedule_over_new_installation(tmp_path, monkeypatch, operation):
    from src.core.watch_config import WatchConfigPersistenceError
    status = WatchStatus.PAUSED if operation == "resume" else WatchStatus.ERROR
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"),
        ObserverFactory(use_mock=True), clock, scheduler)
    config = WatchConfig(id="watch", source_dir=str(tmp_path), status=status)
    controller.add_watch(config)
    original = controller._start_observer
    replacements = []
    def raced_failure(updated):
        controller.stop_all(); controller.start_all()
        original("watch", controller._watches["watch"], expected_config=config)
        replacements.append(controller._get_observer("watch"))
        raise WatchConfigPersistenceError("synthetic old-attempt persist failure")
    with monkeypatch.context() as patch:
        patch.setattr(controller._store, "update", raced_failure)
        if operation == "resume":
            with pytest.raises(WatchControllerError): controller.resume_watch("watch")
        else: controller.restart_after_failure("watch")
    assert controller.get_config("watch") is config
    assert controller._get_observer("watch") is replacements[0] and replacements[0].is_alive()
    assert scheduler.pending_count == 0
    controller.begin_close(); assert controller.drain(time.monotonic() + 1)


def test_actual_retirement_worker_tail_is_owned_after_observer_exit(tmp_path, monkeypatch):
    import threading
    actual_thread = threading.Thread
    tail, release = Event(), Event()
    class TailThread(actual_thread):
        def run(self):
            super().run()
            if self.name == "watch-observer-retirement":
                tail.set(); assert release.wait(5)
    monkeypatch.setattr(threading, "Thread", TailThread)
    factory = ControlledFactory(str(tmp_path / "synthetic.txt"))
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path)))
    observer = factory.created[0]
    observer.release.set(); observer.thread.join(2)
    controller.pause_watch("watch"); assert tail.wait(2)
    try:
        assert not observer.is_alive() and not controller.observers_idle
        with pytest.raises(WatchControllerError, match="^observer_retiring$"):
            controller.resume_watch("watch")
        assert not controller.drain(time.monotonic() + .02)
    finally:
        release.set(); controller.begin_close()
    assert controller.drain(time.monotonic() + 2)


def test_removed_observer_exit_cannot_replace_while_actual_retirement_tail_runs(tmp_path, monkeypatch):
    import threading
    actual_thread = threading.Thread
    tail_entered, tail_release = Event(), Event()
    actual_threads, retirement_threads = [], []
    class TailThread(actual_thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            actual_threads.append(self)
        def run(self):
            super().run()
            if self.name == "watch-observer-retirement":
                retirement_threads.append(self)
                tail_entered.set(); assert tail_release.wait(5)
    monkeypatch.setattr(threading, "Thread", TailThread)
    monkeypatch.setitem(globals(), "Thread", TailThread)  # Track fixture observer/callback threads too.
    factory = ControlledFactory(str(tmp_path / "synthetic.txt"))
    clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    config = WatchConfig(id="same", source_dir=str(tmp_path))
    controller.add_watch(config)
    old = factory.created[0]
    try:
        controller.remove_watch("same")
        assert tail_entered.wait(2)
        old.release.set(); old.thread.join(2)
        assert not old.is_alive() and retirement_threads[0].is_alive()
        assert not old.callback_blocked, "stop held a callback-needed lock"
        assert not controller.observers_idle
        controller.add_watch(config)
        with pytest.raises(WatchControllerError, match="^observer_retiring$"):
            controller.resume_watch("same")
        assert len(factory.created) == 1
        assert not controller.drain(time.monotonic() + .02)
        tail_release.set()
        _wait_for_observers_idle(controller)
        assert not retirement_threads[0].is_alive()
        controller.resume_watch("same")
        assert len(factory.created) == 2
        replacement = factory.created[1]
        assert replacement is not old and replacement.is_alive()
        assert controller._get_observer("same") is replacement
    finally:
        tail_release.set()
        for observer in factory.created: observer.release.set()
        controller.begin_close()
        for observer in factory.created:
            if observer.thread is not None:
                observer.thread.join(2)
                assert not observer.thread.is_alive()
        assert controller.drain(time.monotonic() + 2)
        for thread in actual_threads:
            thread.join(2)
            assert not thread.is_alive()


@pytest.mark.parametrize("emitter_already_exited", [False, True])
def test_real_exited_dispatcher_keeps_emitter_and_uncompleted_teardown_owned(tmp_path, emitter_already_exited):
    from watchdog.observers.api import BaseObserver, EventEmitter
    emitter_entered, emitter_release, dispatcher_release = Event(), Event(), Event()
    class HeldEmitter(EventEmitter):
        def queue_events(self, timeout):
            emitter_entered.set(); assert emitter_release.wait(5)
            self.stopped_event.set()  # controlled actual emitter exit, no observer teardown
    class ExitedDispatcher(BaseObserver):
        def run(self): assert dispatcher_release.wait(5)
    class Factory:
        def __init__(self): self.created = []
        def create(self):
            observer = ExitedDispatcher(HeldEmitter, timeout=.01)
            self.created.append(observer); return observer
    factory = Factory(); clock = FakeClock(); scheduler = FakeScheduler(clock)
    controller = WatchController(WatchConfigStore(tmp_path / "watch.json"), factory, clock, scheduler)
    controller.add_watch(WatchConfig(id="watch", source_dir=str(tmp_path)))
    observer = factory.created[0]; emitters = tuple(observer.emitters)
    assert emitter_entered.wait(2)
    dispatcher_release.set(); observer.join(2)  # synthetic dispatcher actually exits without stop()
    if emitter_already_exited:
        emitter_release.set()
        for emitter in emitters: emitter.join(2)
    try:
        assert not observer.is_alive()
        assert all(emitter.is_alive() is (not emitter_already_exited) for emitter in emitters)
        assert not controller.observers_idle, "owner discarded before owned teardown completion"
        owner = controller._observer_owners[id(observer)]
        assert owner.emitters == emitters and not owner.teardown_complete
        if not emitter_already_exited:
            with pytest.raises(WatchControllerError, match="^observer_retiring$"):
                controller.start_all()
            assert len(factory.created) == 1
        controller.pause_watch("watch")
        if not emitter_already_exited:
            assert not controller.drain(time.monotonic() + .02)
    finally:
        emitter_release.set(); dispatcher_release.set(); controller.begin_close()
        for emitter in emitters: emitter.join(2)
        observer.join(2)
    assert controller.drain(time.monotonic() + 2)
