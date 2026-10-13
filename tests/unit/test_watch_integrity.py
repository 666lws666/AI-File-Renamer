"""M5 persistence and lifecycle integrity regressions."""

import pytest

from src.controllers.watch_controller import (
    FakeClock,
    FakeScheduler,
    ObserverFactory,
    WatchController,
)
from src.core.watch_config import WatchConfig, WatchConfigStore, WatchStatus


def _config(tmp_path, config_id="watch", status=WatchStatus.ACTIVE):
    source = tmp_path / config_id
    source.mkdir(exist_ok=True)
    return WatchConfig(id=config_id, source_dir=str(source), status=status)


@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_store_write_failure_keeps_memory_and_disk_unchanged(tmp_path, monkeypatch, operation):
    path = tmp_path / "watches.json"
    store = WatchConfigStore(path)
    original = _config(tmp_path, "original", WatchStatus.PAUSED)
    store.add(original)
    before_memory = store.list_all()
    before_disk = path.read_bytes()

    def fail_save(_candidate=None):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        if operation == "add":
            store.add(_config(tmp_path, "new", WatchStatus.PAUSED))
        elif operation == "update":
            store.update(original.with_status(WatchStatus.ACTIVE))
        else:
            store.remove(original.id)

    assert store.list_all() == before_memory
    assert path.read_bytes() == before_disk


def _controller(tmp_path, factory=None, status=WatchStatus.ACTIVE):
    clock = FakeClock()
    scheduler = FakeScheduler(clock)
    store = WatchConfigStore(tmp_path / "watches.json")
    store.add(_config(tmp_path, "watch", status))
    return WatchController(
        store,
        observer_factory=factory or ObserverFactory(use_mock=True),
        clock=clock,
        scheduler=scheduler,
        backoff_base=1,
        max_retries=2,
    ), scheduler, clock


def test_start_all_is_idempotent_for_running_observer(tmp_path):
    factory = ObserverFactory(use_mock=True)
    controller, _scheduler, _clock = _controller(tmp_path, factory=factory)
    first = controller._get_observer("watch")

    controller.start_all()

    assert controller._get_observer("watch") is first
    assert len(factory.created_observers) == 1


def test_resource_paused_cannot_resume_without_guard_confirmation(tmp_path):
    controller, _scheduler, _clock = _controller(
        tmp_path, status=WatchStatus.RESOURCE_PAUSED
    )

    controller.resume_watch("watch")

    assert controller.get_status("watch") is WatchStatus.RESOURCE_PAUSED
    assert controller._get_observer("watch") is None


def test_update_watch_requires_paused_state_and_replaces_persisted_config(tmp_path):
    controller, _scheduler, _clock = _controller(tmp_path)
    original = controller.get_config("watch")
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(Exception, match="paused"):
        controller.update_watch(original)

    controller.pause_watch("watch")
    updated = WatchConfig(
        id=original.id,
        source_dir=original.source_dir,
        target_dir=str(target),
        template_id="template-2",
        recursive=False,
        mode=original.mode,
        status=WatchStatus.PAUSED,
    )
    controller.update_watch(updated)

    assert controller.get_config("watch") == updated
    assert controller._get_observer("watch") is None


@pytest.mark.parametrize("operation", ["pause", "resume", "remove"])
def test_lifecycle_write_failure_preserves_runtime_and_disk_state(tmp_path, monkeypatch, operation):
    controller, _scheduler, _clock = _controller(tmp_path)
    if operation == "resume":
        controller.pause_watch("watch")
    before_status = controller.get_status("watch")
    before_observer = controller._get_observer("watch")
    before_disk = controller._store._file_path.read_bytes()

    def fail_save(_candidate=None):
        raise OSError("disk full")

    monkeypatch.setattr(controller._store, "_save", fail_save)
    with pytest.raises(Exception, match="disk full|failed"):
        if operation == "pause":
            controller.pause_watch("watch")
        elif operation == "resume":
            controller.resume_watch("watch")
        else:
            controller.remove_watch("watch")

    assert controller.get_status("watch") is before_status
    assert controller._get_observer("watch") is before_observer
    if before_observer is not None:
        assert before_observer.running is True
    assert controller._store._file_path.read_bytes() == before_disk


def test_restore_start_failure_schedules_bounded_retry_then_recovers(tmp_path):
    factory = ObserverFactory(use_mock=True)
    factory.always_fail = True
    controller, scheduler, clock = _controller(tmp_path, factory=factory)
    assert controller.get_status("watch") is WatchStatus.ERROR
    assert scheduler.pending_count == 1

    factory.always_fail = False
    clock.advance(1)
    scheduler.run_pending()

    assert controller.get_status("watch") is WatchStatus.ACTIVE
    assert controller._get_observer("watch").running is True


def _queued_retry(controller, scheduler):
    controller._simulate_observer_error("watch", RuntimeError("observer failed"))
    assert controller.get_status("watch") is WatchStatus.ERROR
    assert scheduler.pending_count == 1
    # Retain a callback as if Timer had dispatched it before cancellation.
    return scheduler._pending[0][1]


@pytest.mark.parametrize("transition", ["pause", "resource_pause", "stop", "remove"])
def test_queued_retry_cannot_override_lifecycle_transition(tmp_path, transition):
    controller, scheduler, clock = _controller(tmp_path)
    stale_callback = _queued_retry(controller, scheduler)
    if transition == "pause":
        controller.pause_watch("watch")
    elif transition == "resource_pause":
        controller.resource_pause("watch")
    elif transition == "stop":
        controller.stop_all()
    else:
        controller.remove_watch("watch")

    assert scheduler.pending_count == 0
    stale_callback()
    clock.advance(10)
    scheduler.run_pending()
    assert controller._get_observer("watch") is None
    if transition == "remove":
        assert not controller.is_watching("watch")
    else:
        expected = {
            "pause": WatchStatus.PAUSED,
            "resource_pause": WatchStatus.RESOURCE_PAUSED,
            "stop": WatchStatus.ERROR,
        }[transition]
        assert controller.get_status("watch") is expected
        assert WatchConfigStore(tmp_path / "watches.json").get("watch").status is expected


def test_old_retry_cannot_consume_new_error_retry(tmp_path):
    controller, scheduler, clock = _controller(tmp_path)
    stale_callback = _queued_retry(controller, scheduler)
    controller.pause_watch("watch")
    controller.resume_watch("watch")
    _queued_retry(controller, scheduler)

    stale_callback()

    assert controller.get_status("watch") is WatchStatus.ERROR
    assert controller._get_observer("watch") is None
    assert scheduler.pending_count == 1
    clock.advance(1)
    scheduler.run_pending()
    assert controller.get_status("watch") is WatchStatus.ACTIVE
    assert controller._get_observer("watch").running
    assert scheduler.pending_count == 0


def test_retry_save_failure_stops_observer_and_keeps_disk_then_recovers(tmp_path, monkeypatch):
    controller, scheduler, clock = _controller(tmp_path)
    _queued_retry(controller, scheduler)
    store = controller._store
    before = store._file_path.read_bytes()
    save = store._save

    def fail_save(_candidate=None):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", fail_save)
    clock.advance(1)
    scheduler.run_pending()

    assert controller.get_status("watch") is WatchStatus.ERROR
    assert controller._get_observer("watch") is None
    assert all(not observer.running for observer in controller._observer_factory.created_observers)
    assert store._file_path.read_bytes() == before
    assert store.get("watch").status is WatchStatus.ERROR
    assert scheduler.pending_count == 1

    monkeypatch.setattr(store, "_save", save)
    clock.advance(1)
    scheduler.run_pending()
    assert controller.get_status("watch") is WatchStatus.ACTIVE
    assert WatchConfigStore(store._file_path).get("watch").status is WatchStatus.ACTIVE
    assert controller._get_observer("watch").running
    assert scheduler.pending_count == 0


def test_retry_save_failures_exhaust_without_live_observer(tmp_path, monkeypatch):
    controller, scheduler, clock = _controller(tmp_path)
    _queued_retry(controller, scheduler)
    before = controller._store._file_path.read_bytes()

    def fail_save(_candidate=None):
        raise OSError("disk full")

    monkeypatch.setattr(controller._store, "_save", fail_save)
    for _ in range(2):
        clock.advance(10)
        scheduler.run_pending()

    assert controller.get_status("watch") is WatchStatus.ERROR
    assert controller._get_observer("watch") is None
    assert scheduler.pending_count == 0
    assert controller._store._file_path.read_bytes() == before
    assert all(not observer.running for observer in controller._observer_factory.created_observers)

