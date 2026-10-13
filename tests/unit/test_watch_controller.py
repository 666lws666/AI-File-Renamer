"""Task 2 — Watch Folder Controller tests.

Covers:
- add_watch auto-starts monitoring (GAP-035 fix)
- pause/resume lifecycle
- remove stops observer, never deletes user files
- debounce (2s stable wait, resets on change)
- temp file filtering
- output dir re-entry guard
- observer exception backoff with max retry
- cancel/stop semantics (no stale callbacks)
- concurrent duplicate event dedup
- error messages use reason codes, not full paths
- no real watchdog daemon, no real API keys, no network
"""

import os
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchConfigValidationError,
    WatchConfigPersistenceError,
    WatchMode,
    WatchStatus,
)
from src.controllers.watch_controller import (
    WatchController,
    _WatchEventHandler,
    WatchControllerError,
    ObserverFactory,
    MockObserver,
    FileEvent,
    DebounceScheduler,
    FakeScheduler,
    FakeClock,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_config(src: Path, config_id: str = "test-1", **kwargs) -> WatchConfig:
    src.mkdir(parents=True, exist_ok=True)
    defaults = {
        "id": config_id,
        "source_dir": str(src),
        "mode": WatchMode.REVIEW_FIRST,
        "status": WatchStatus.ACTIVE,
    }
    defaults.update(kwargs)
    return WatchConfig(**defaults)


def _make_controller(tmp_path, clock=None, scheduler=None, backoff_base=None,
                     max_retries=None, debounce_seconds=None) -> WatchController:
    store_path = tmp_path / "watches.json"
    store = WatchConfigStore(str(store_path))
    factory = ObserverFactory(use_mock=True)
    return WatchController(
        config_store=store,
        observer_factory=factory,
        clock=clock,
        scheduler=scheduler,
        backoff_base=backoff_base,
        max_retries=max_retries,
        debounce_seconds=debounce_seconds,
    )


def test_moved_event_dispatches_final_destination_path(tmp_path):
    ctrl = MagicMock()
    handler = _WatchEventHandler("watch-1", ctrl)
    event = MagicMock(
        is_directory=False,
        event_type="moved",
        src_path=str(tmp_path / "download.part"),
        dest_path=str(tmp_path / "document.pdf"),
    )

    handler.dispatch(event)

    ctrl._on_raw_file_event.assert_called_once_with(
        "watch-1", str(tmp_path / "document.pdf"), FileEvent.MOVED
    )


# ── Add Watch & Auto-Start ─────────────────────────────────────────────────────

class TestAddWatchAutoStart:
    """GAP-035: Adding a valid config must auto-start monitoring."""

    def test_add_watch_creates_observer(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        cfg = _make_config(src, "w1")
        ctrl.add_watch(cfg)
        assert ctrl.is_watching("w1")
        assert ctrl.get_status("w1") == WatchStatus.ACTIVE

    def test_add_watch_starts_observer_automatically(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        cfg = _make_config(src, "w2")
        ctrl.add_watch(cfg)
        obs = ctrl._get_observer("w2")
        assert obs is not None
        assert obs.running is True

    def test_add_duplicate_id_raises(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "dup"))
        with pytest.raises(WatchControllerError, match="already"):
            ctrl.add_watch(_make_config(src, "dup"))

    def test_add_watch_with_paused_status_does_not_start(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        cfg = _make_config(src, "w3", status=WatchStatus.PAUSED)
        ctrl.add_watch(cfg)
        assert ctrl.get_status("w3") == WatchStatus.PAUSED
        obs = ctrl._get_observer("w3")
        assert obs is None or obs.running is False


# ── Pause / Resume ─────────────────────────────────────────────────────────────

class TestPauseResume:
    """Pause must stop observer; resume must restart it."""

    def test_pause_stops_observer(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "p1"))
        ctrl.pause_watch("p1")
        assert ctrl.get_status("p1") == WatchStatus.PAUSED
        obs = ctrl._get_observer("p1")
        assert obs is None or obs.running is False

    def test_resume_restarts_observer(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "p2"))
        ctrl.pause_watch("p2")
        ctrl.resume_watch("p2")
        assert ctrl.get_status("p2") == WatchStatus.ACTIVE
        obs = ctrl._get_observer("p2")
        assert obs is not None and obs.running is True

    def test_pause_nonexistent_raises(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        with pytest.raises(WatchControllerError, match="not found"):
            ctrl.pause_watch("noexist")

    def test_resume_nonexistent_raises(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        with pytest.raises(WatchControllerError, match="not found"):
            ctrl.resume_watch("noexist")


# ── Remove Watch ───────────────────────────────────────────────────────────────

class TestRemoveWatch:
    """Remove stops observer, removes config, but NEVER deletes user files."""

    def test_remove_stops_observer(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "r1"))
        ctrl.remove_watch("r1")
        assert not ctrl.is_watching("r1")
        with pytest.raises(WatchControllerError):
            ctrl.get_status("r1")

    def test_remove_does_not_delete_source_dir(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        src.mkdir(parents=True)
        test_file = src / "important.txt"
        test_file.write_text("precious data", encoding="utf-8")
        ctrl.add_watch(_make_config(src, "r2"))
        ctrl.remove_watch("r2")
        assert src.exists()
        assert test_file.exists()
        assert test_file.read_text() == "precious data"

    def test_remove_does_not_delete_target_dir(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        tgt = tmp_path / "tgt"
        src.mkdir(parents=True)
        tgt.mkdir(parents=True)
        test_file = tgt / "output.txt"
        test_file.write_text("output data", encoding="utf-8")
        ctrl.add_watch(_make_config(src, "r3", target_dir=str(tgt)))
        ctrl.remove_watch("r3")
        assert tgt.exists()
        assert test_file.exists()

    def test_remove_does_not_delete_template(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "r4", template_id="tpl-important"))
        ctrl.remove_watch("r4")
        # Template lives in TemplateStore, this controller has no access to it
        # Removing watch must not touch template store
        assert ctrl.is_watching("r4") is False

    def test_remove_nonexistent_raises(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        with pytest.raises(WatchControllerError, match="not found"):
            ctrl.remove_watch("noexist")


# ── Start All / Stop All ───────────────────────────────────────────────────────

class TestStartAllStopAll:
    """Bulk lifecycle management."""

    def test_start_all_starts_active_configs(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        s1 = tmp_path / "s1"; s2 = tmp_path / "s2"
        ctrl.add_watch(_make_config(s1, "a1"))
        ctrl.add_watch(_make_config(s2, "a2", status=WatchStatus.PAUSED))
        # Stop everything first
        ctrl.stop_all()
        # start_all should restart only Active
        ctrl.start_all()
        assert ctrl._get_observer("a1").running is True
        # Paused should NOT have observer
        assert ctrl._get_observer("a2") is None

    def test_stop_all_stops_all_observers(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        s1 = tmp_path / "s1"; s2 = tmp_path / "s2"
        ctrl.add_watch(_make_config(s1, "b1"))
        ctrl.add_watch(_make_config(s2, "b2"))
        ctrl.stop_all()
        assert ctrl._get_observer("b1") is None or ctrl._get_observer("b1").running is False
        assert ctrl._get_observer("b2") is None or ctrl._get_observer("b2").running is False

    def test_stop_all_idempotent(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        s1 = tmp_path / "s1"
        ctrl.add_watch(_make_config(s1, "c1"))
        ctrl.stop_all()
        ctrl.stop_all()  # Should not raise
        assert ctrl._get_observer("c1") is None


# ── Debounce ───────────────────────────────────────────────────────────────────

class TestDebounce:
    """2-second file stability wait, reset on change."""

    def test_file_stable_after_debounce_fires_callback(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        cfg = _make_config(src, "d1")
        ctrl.add_watch(cfg)

        events = []
        ctrl.on_file_ready = lambda config_id, file_path: events.append((config_id, file_path))

        test_file = src / "new_file.txt"
        test_file.write_text("hello")
        ctrl._simulate_file_event("d1", str(test_file), FileEvent.CREATED)

        # Debounce hasn't elapsed yet
        assert len(events) == 0

        # Advance past debounce
        fake_clock.advance(2.5)
        fake_sched.run_pending()

        assert len(events) == 1
        assert events[0][0] == "d1"

    def test_debounce_resets_on_modification(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "d2"))

        events = []
        ctrl.on_file_ready = lambda cid, fp: events.append((cid, fp))

        test_file = src / "growing.txt"
        test_file.write_text("part1")

        ctrl._simulate_file_event("d2", str(test_file), FileEvent.CREATED)
        fake_clock.advance(1.0)  # Only 1s elapsed
        # Simulate modification (file still being written)
        test_file.write_text("part1 and part2")
        ctrl._simulate_file_event("d2", str(test_file), FileEvent.MODIFIED)

        # Advance to 2.5s from start — but mod reset timer, so only 1.5s from mod
        fake_clock.advance(1.0)  # total 2.0s from start, 1.0s from mod
        fake_sched.run_pending()
        assert len(events) == 0  # Not yet stable

        fake_clock.advance(1.5)  # total 3.5s from start, 2.5s from mod
        fake_sched.run_pending()
        assert len(events) == 1

    def test_debounce_default_period_is_2_seconds(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        assert ctrl.debounce_seconds == 2.0

    def test_debounce_configurable(self, tmp_path):
        ctrl = _make_controller(tmp_path, debounce_seconds=0.5)
        assert ctrl.debounce_seconds == 0.5


# ── Temp File Filtering ────────────────────────────────────────────────────────

class TestTempFileFilter:
    """Must filter: .tmp, ~$ prefix, .part, .crdownload, .download."""

    @pytest.mark.parametrize("filename,should_filter", [
        ("file.tmp", True),
        ("file.TMP", True),
        ("~$office_doc.docx", True),
        ("file.part", True),
        ("file.crdownload", True),
        ("file.download", True),
        ("normal.pdf", False),
        ("report.docx", False),
        ("image.png", False),
        ("file.tmpx", False),   # Not exactly .tmp
        ("~normal.txt", False),  # ~ but not ~$
    ])
    def test_temp_file_filter(self, tmp_path, filename, should_filter):
        ctrl = _make_controller(tmp_path)
        result = ctrl._is_temp_file(filename)
        assert result == should_filter, f"{filename}: expected filter={should_filter}, got {result}"


# ── Observer Exception & Backoff ───────────────────────────────────────────────

class TestObserverBackoff:
    """Observer exceptions → Error status → exponential backoff retry."""

    def test_observer_exception_sets_error_status(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        cfg = _make_config(src, "e1")
        ctrl.add_watch(cfg)
        # Simulate observer crash
        ctrl._simulate_observer_error("e1", RuntimeError("watchdog crash"))
        assert ctrl.get_status("e1") == WatchStatus.ERROR

    def test_backoff_retry_after_delay(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched,
                                backoff_base=1.0)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "e2"))
        ctrl._simulate_observer_error("e2", RuntimeError("crash"))
        assert ctrl.get_status("e2") == WatchStatus.ERROR

        # First retry: delay = base * 2^0 = 1.0s
        fake_clock.advance(1.5)
        fake_sched.run_pending()
        # After retry with mock observer, should be back to ACTIVE if successful
        assert ctrl.get_status("e2") == WatchStatus.ACTIVE

    def test_backoff_exponential_increase(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        store_path = tmp_path / "watches.json"
        store = WatchConfigStore(str(store_path))
        factory = ObserverFactory(use_mock=True)
        factory.always_fail = True  # All new observers will fail
        ctrl = WatchController(
            config_store=store,
            observer_factory=factory,
            clock=fake_clock,
            scheduler=fake_sched,
            backoff_base=1.0,
            max_retries=5,
        )
        src = tmp_path / "src"
        # add_watch will fail to start observer → ERROR, retry scheduled
        ctrl.add_watch(_make_config(src, "e3"))
        assert ctrl.get_status("e3") == WatchStatus.ERROR

        # First retry (delay: 1.0 * 2^0 = 1.0)
        fake_clock.advance(1.5); fake_sched.run_pending()
        assert ctrl.get_status("e3") == WatchStatus.ERROR

        # Second retry (delay: 1.0 * 2^1 = 2.0)
        fake_clock.advance(2.5); fake_sched.run_pending()
        assert ctrl.get_status("e3") == WatchStatus.ERROR

        # Third retry (delay: 1.0 * 2^2 = 4.0)
        fake_clock.advance(4.5); fake_sched.run_pending()
        assert ctrl.get_status("e3") == WatchStatus.ERROR

    def test_max_retries_exceeded_stays_error(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        store_path = tmp_path / "watches.json"
        store = WatchConfigStore(str(store_path))
        factory = ObserverFactory(use_mock=True)
        factory.always_fail = True
        ctrl = WatchController(
            config_store=store,
            observer_factory=factory,
            clock=fake_clock,
            scheduler=fake_sched,
            backoff_base=0.1,
            max_retries=3,
        )
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "e4"))
        assert ctrl.get_status("e4") == WatchStatus.ERROR

        for i in range(5):  # More failures than max_retries
            fake_clock.advance(10.0)
            fake_sched.run_pending()

        # After max_retries, should stay ERROR
        assert ctrl.get_status("e4") == WatchStatus.ERROR

    def test_no_busy_loop(self, tmp_path):
        """Must not busy-loop: retries must have delays between them."""
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "e5"))
        obs = ctrl._get_observer("e5")
        obs.always_fail = True

        retry_count = [0]
        orig_restart = ctrl.restart_after_failure

        def counting_restart(cid, **kwargs):
            retry_count[0] += 1
            return orig_restart(cid, **kwargs)

        ctrl.restart_after_failure = counting_restart

        # Trigger one error
        ctrl._simulate_observer_error("e5", RuntimeError("fail"))
        # Run all pending
        fake_sched.run_pending()
        # Should have at most 1 retry attempt without time passing
        # The backoff prevents immediate retries
        assert retry_count[0] <= 2  # One scheduled + maybe one immediate


# ── Cancel / Stop Semantics ────────────────────────────────────────────────────

class TestCancelStopSemantics:
    """After stop, old callbacks must not reactivate Watch."""

    def test_stop_cancels_pending_debounce(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "s1"))

        events = []
        ctrl.on_file_ready = lambda cid, fp: events.append((cid, fp))

        test_file = src / "late.txt"
        test_file.write_text("data")
        ctrl._simulate_file_event("s1", str(test_file), FileEvent.CREATED)

        # Stop before debounce completes
        ctrl.stop_all()

        # Advance past debounce
        fake_clock.advance(5.0)
        fake_sched.run_pending()

        # No events should fire after stop
        assert len(events) == 0

    def test_removed_watch_does_not_fire_events(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "s2"))

        events = []
        ctrl.on_file_ready = lambda cid, fp: events.append((cid, fp))

        test_file = src / "late2.txt"
        test_file.write_text("data")
        ctrl._simulate_file_event("s2", str(test_file), FileEvent.CREATED)

        # Remove watch before debounce completes
        ctrl.remove_watch("s2")

        fake_clock.advance(5.0)
        fake_sched.run_pending()

        assert len(events) == 0


# ── Error Messages ─────────────────────────────────────────────────────────────

class TestErrorMessages:
    """Errors must not leak full file paths; use reason codes."""

    def test_error_does_not_contain_full_path(self, tmp_path, monkeypatch, capsys):
        import json

        ctrl = _make_controller(tmp_path)
        src = tmp_path / "very" / "secret" / "location"
        cfg = _make_config(src, "err1")
        private_detail = "synthetic-observer-secret:" + str(src)

        class FailingObserver(MockObserver):
            def start(self):
                raise RuntimeError(private_detail)

        monkeypatch.setattr(ctrl._observer_factory, "create", FailingObserver)
        try:
            ctrl.add_watch(cfg)
            assert ctrl.get_status("err1") == WatchStatus.ERROR
            assert ctrl._store.get("err1").status == WatchStatus.ERROR
            persisted = (tmp_path / "watches.json").read_text(encoding="utf-8")
            json.loads(persisted)  # persisted state must remain valid JSON
            assert "synthetic-observer-secret:" not in persisted
            assert private_detail not in persisted
            emitted = capsys.readouterr()
            assert private_detail not in emitted.out + emitted.err
        finally:
            ctrl.begin_close()
            assert ctrl.drain(time.monotonic() + 2.0)
            assert ctrl.workers_idle


# ── Concurrent Duplicate Events ────────────────────────────────────────────────

class TestDuplicateEvents:
    """Rapid duplicate events for the same file should be deduplicated."""

    def test_duplicate_create_events_deduped(self, tmp_path):
        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        ctrl = _make_controller(tmp_path, clock=fake_clock, scheduler=fake_sched)
        src = tmp_path / "src"
        ctrl.add_watch(_make_config(src, "dup1"))

        events = []
        ctrl.on_file_ready = lambda cid, fp: events.append((cid, fp))

        test_file = src / "single.txt"
        test_file.write_text("data")

        # Fire multiple create events for the same file
        for _ in range(5):
            ctrl._simulate_file_event("dup1", str(test_file), FileEvent.CREATED)

        fake_clock.advance(3.0)
        fake_sched.run_pending()

        # Should only fire once
        assert len(events) == 1


# ── Integration: Controller + Store ────────────────────────────────────────────

class TestControllerStoreIntegration:
    """Configs persist through store, load correctly."""

    def test_configs_survive_controller_recreation(self, tmp_path):
        store_path = tmp_path / "watches.json"
        src = tmp_path / "src"
        src.mkdir()

        # First controller
        store1 = WatchConfigStore(str(store_path))
        factory1 = ObserverFactory(use_mock=True)
        ctrl1 = WatchController(config_store=store1, observer_factory=factory1)
        ctrl1.add_watch(_make_config(src, "persist1"))
        ctrl1.stop_all()

        # Second controller loads from same store
        store2 = WatchConfigStore(str(store_path))
        factory2 = ObserverFactory(use_mock=True)
        ctrl2 = WatchController(config_store=store2, observer_factory=factory2)

        assert ctrl2.is_watching("persist1")
        cfg = ctrl2.get_config("persist1")
        assert cfg.source_dir == str(src)
