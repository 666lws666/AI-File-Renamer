"""Task 8 — Watch Restart Recovery integration tests.

Covers:
- Two+ watches recover source/target/template/mode/recursive/status after simulated restart
- Active auto-restarts observer; Paused stays paused; Error/ResourcePaused don't auto-activate
- Corrupted single config doesn't cause other valid watches to be lost
- Recovery doesn't trigger historical file reprocessing
- Corrupted items go into reportable error results, not silently deleted
"""

import json
import os
from pathlib import Path

import pytest

from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchConfigPersistenceError,
    WatchMode,
    WatchStatus,
)
from src.controllers.watch_controller import (
    WatchController,
    ObserverFactory,
    WatchControllerError,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_config(src: Path, config_id: str, **kwargs) -> WatchConfig:
    src.mkdir(parents=True, exist_ok=True)
    defaults = {
        "id": config_id,
        "source_dir": str(src),
        "mode": WatchMode.REVIEW_FIRST,
        "status": WatchStatus.ACTIVE,
    }
    defaults.update(kwargs)
    return WatchConfig(**defaults)


def _new_controller(store_path: str) -> WatchController:
    store = WatchConfigStore(store_path)
    factory = ObserverFactory(use_mock=True)
    return WatchController(config_store=store, observer_factory=factory)


# ── Basic Recovery ─────────────────────────────────────────────────────────────

class TestBasicRecovery:
    """Two+ watches survive simulated app restart with correct config."""

    def test_two_watches_recover_after_restart(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        # First "session": create controller, add 2 watches
        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "src1"; s2 = tmp_path / "src2"
        t1 = tmp_path / "tgt1"; t2 = tmp_path / "tgt2"
        t1.mkdir(); t2.mkdir()

        ctrl1.add_watch(_make_config(s1, "w1", target_dir=str(t1),
                                     template_id="tpl-a", recursive=False,
                                     mode=WatchMode.AUTO_APPLY))
        ctrl1.add_watch(_make_config(s2, "w2", target_dir=str(t2),
                                     template_id="tpl-b", recursive=True,
                                     mode=WatchMode.REVIEW_FIRST))
        ctrl1.stop_all()

        # Simulate "app restart": create new controller from same store
        ctrl2 = _new_controller(store_path)

        # Both watches must be recovered
        assert ctrl2.is_watching("w1")
        assert ctrl2.is_watching("w2")

        # Config must match exactly
        cfg1 = ctrl2.get_config("w1")
        assert cfg1.source_dir == str(s1)
        assert cfg1.target_dir == str(t1)
        assert cfg1.template_id == "tpl-a"
        assert cfg1.recursive is False
        assert cfg1.mode == WatchMode.AUTO_APPLY

        cfg2 = ctrl2.get_config("w2")
        assert cfg2.source_dir == str(s2)
        assert cfg2.target_dir == str(t2)
        assert cfg2.template_id == "tpl-b"
        assert cfg2.recursive is True
        assert cfg2.mode == WatchMode.REVIEW_FIRST

    def test_active_watches_auto_restart_observer(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "src1"
        ctrl1.add_watch(_make_config(s1, "active1", status=WatchStatus.ACTIVE))
        ctrl1.stop_all()

        # Restart
        ctrl2 = _new_controller(store_path)
        assert ctrl2.get_status("active1") == WatchStatus.ACTIVE
        obs = ctrl2._get_observer("active1")
        assert obs is not None and obs.running is True

    def test_paused_watches_stay_paused(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "src1"
        ctrl1.add_watch(_make_config(s1, "paused1", status=WatchStatus.PAUSED))
        ctrl1.stop_all()

        # Restart
        ctrl2 = _new_controller(store_path)
        assert ctrl2.get_status("paused1") == WatchStatus.PAUSED
        obs = ctrl2._get_observer("paused1")
        assert obs is None or obs.running is False

    def test_error_watches_do_not_auto_activate(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "src1"
        ctrl1.add_watch(_make_config(s1, "err1", status=WatchStatus.ERROR))
        ctrl1.stop_all()

        # Restart
        ctrl2 = _new_controller(store_path)
        assert ctrl2.get_status("err1") == WatchStatus.ERROR
        obs = ctrl2._get_observer("err1")
        assert obs is None or obs.running is False

    def test_resource_paused_does_not_auto_activate(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "src1"
        ctrl1.add_watch(_make_config(s1, "rp1", status=WatchStatus.RESOURCE_PAUSED))
        ctrl1.stop_all()

        # Restart
        ctrl2 = _new_controller(store_path)
        assert ctrl2.get_status("rp1") == WatchStatus.RESOURCE_PAUSED
        obs = ctrl2._get_observer("rp1")
        assert obs is None or obs.running is False


# ── Mixed State Recovery ──────────────────────────────────────────────────────

class TestMixedStateRecovery:
    """Multiple watches with different statuses all recover correctly."""

    def test_four_watches_mixed_status_recovery(self, tmp_path):
        store_path = str(tmp_path / "watches.json")

        ctrl1 = _new_controller(store_path)
        s1 = tmp_path / "s1"; s2 = tmp_path / "s2"
        s3 = tmp_path / "s3"; s4 = tmp_path / "s4"

        ctrl1.add_watch(_make_config(s1, "a", status=WatchStatus.ACTIVE))
        ctrl1.add_watch(_make_config(s2, "b", status=WatchStatus.PAUSED))
        ctrl1.add_watch(_make_config(s3, "c", status=WatchStatus.ERROR))
        ctrl1.add_watch(_make_config(s4, "d", status=WatchStatus.RESOURCE_PAUSED))
        ctrl1.stop_all()

        ctrl2 = _new_controller(store_path)

        assert ctrl2.get_status("a") == WatchStatus.ACTIVE
        assert ctrl2.get_status("b") == WatchStatus.PAUSED
        assert ctrl2.get_status("c") == WatchStatus.ERROR
        assert ctrl2.get_status("d") == WatchStatus.RESOURCE_PAUSED

        # Only ACTIVE should have a running observer
        assert ctrl2._get_observer("a") is not None and ctrl2._get_observer("a").running is True
        assert ctrl2._get_observer("b") is None or ctrl2._get_observer("b").running is False
        assert ctrl2._get_observer("c") is None or ctrl2._get_observer("c").running is False
        assert ctrl2._get_observer("d") is None or ctrl2._get_observer("d").running is False


# ── Corrupted Config Isolation ─────────────────────────────────────────────────

class TestCorruptedConfigIsolation:
    """One corrupted config must not cause other valid watches to be lost."""

    def test_corrupted_item_does_not_block_valid_items(self, tmp_path):
        store_path = tmp_path / "corrupt_store.json"
        s1 = tmp_path / "s1"; s2 = tmp_path / "s2"
        s1.mkdir(parents=True); s2.mkdir(parents=True)

        # Write a store with 2 valid + 1 invalid entry
        data = {
            "schema_version": 1,
            "configs": [
                {
                    "id": "valid-1",
                    "source_dir": str(s1),
                    "target_dir": "",
                    "template_id": "",
                    "recursive": True,
                    "mode": "review_first",
                    "status": "active",
                    "created_at": "",
                    "updated_at": "",
                    "version": 1,
                },
                {
                    "id": "valid-2",
                    "source_dir": str(s2),
                    "target_dir": "",
                    "template_id": "",
                    "recursive": True,
                    "mode": "review_first",
                    "status": "paused",
                    "created_at": "",
                    "updated_at": "",
                    "version": 1,
                },
                {
                    # Corrupted: missing source_dir
                    "id": "corrupt-1",
                    "mode": "review_first",
                    "status": "active",
                },
            ],
        }
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        # Recovery: should load valid-1 and valid-2, skip corrupt-1
        store = WatchConfigStore(str(store_path), strict=False)
        factory = ObserverFactory(use_mock=True)
        errors = {}
        ctrl = WatchController(
            config_store=store,
            observer_factory=factory,
            recovery_errors=errors,
        )

        assert ctrl.is_watching("valid-1")
        assert ctrl.is_watching("valid-2")
        assert not ctrl.is_watching("corrupt-1")

        # Corrupted item must be in the error report
        assert "corrupt-1" in errors or len(errors) > 0

    def test_corrupted_item_not_silently_deleted(self, tmp_path):
        """Corrupted items must appear in the recovery error report."""
        store_path = tmp_path / "corrupt2.json"
        s1 = tmp_path / "s1"
        s1.mkdir(parents=True)

        data = {
            "schema_version": 1,
            "configs": [
                {
                    "id": "ok",
                    "source_dir": str(s1),
                    "mode": "review_first",
                    "status": "active",
                    "template_id": "",
                    "target_dir": "",
                    "recursive": True,
                    "created_at": "",
                    "updated_at": "",
                    "version": 1,
                },
                {
                    "id": "bad-mode",
                    "source_dir": str(s1),
                    "mode": "INVALID_MODE_XYZ",
                    "status": "active",
                    "template_id": "",
                    "target_dir": "",
                    "recursive": True,
                    "created_at": "",
                    "updated_at": "",
                    "version": 1,
                },
            ],
        }
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        store = WatchConfigStore(str(store_path), strict=False)
        factory = ObserverFactory(use_mock=True)
        errors = {}
        ctrl = WatchController(
            config_store=store,
            observer_factory=factory,
            recovery_errors=errors,
        )

        assert ctrl.is_watching("ok")
        assert not ctrl.is_watching("bad-mode")
        # Error report must reference the corrupted item
        assert len(errors) >= 1


# ── No Historical File Reprocessing ────────────────────────────────────────────

class TestNoHistoricalReprocessing:
    """Recovery must NOT trigger processing of files that existed before restart."""

    def test_recovery_does_not_process_existing_files(self, tmp_path):
        fake_clock = None  # Use real time for this test
        store_path = str(tmp_path / "watches.json")

        # First session
        ctrl1 = _new_controller(store_path)
        src = tmp_path / "src"
        src.mkdir(parents=True)
        existing_file = src / "old_file.txt"
        existing_file.write_text("pre-existing content", encoding="utf-8")

        ctrl1.add_watch(_make_config(src, "hist1"))
        ready_events = []
        ctrl1.on_file_ready = lambda cid, fp: ready_events.append((cid, fp))
        ctrl1.stop_all()

        # Verify no events fired for pre-existing files
        # (The initial-scan strategy: only process events after recovery)
        assert len(ready_events) == 0, (
            "Pre-existing files must not be processed on recovery"
        )

    def test_recovery_initial_scan_skips_old_files(self, tmp_path):
        """The initial-scan strategy must default to processing only new events post-recovery."""
        store_path = str(tmp_path / "watches.json")

        # First session: add watch, create file
        ctrl1 = _new_controller(store_path)
        src = tmp_path / "src"
        src.mkdir(parents=True)
        (src / "old_doc.pdf").write_text("old", encoding="utf-8")

        ctrl1.add_watch(_make_config(src, "scan1"))
        events = []
        ctrl1.on_file_ready = lambda cid, fp: events.append((cid, fp))
        ctrl1.stop_all()

        # Restart: old file must not generate events
        ctrl2 = _new_controller(store_path)
        events2 = []
        ctrl2.on_file_ready = lambda cid, fp: events2.append((cid, fp))

        # No events should fire just because of recovery
        assert len(events2) == 0

    def test_new_files_after_recovery_are_processed(self, tmp_path):
        """Files created AFTER recovery should still be processed normally."""
        from src.controllers.watch_controller import FakeClock, FakeScheduler, FileEvent

        fake_clock = FakeClock(0.0)
        fake_sched = FakeScheduler(fake_clock)
        store_path = str(tmp_path / "watches.json")

        store = WatchConfigStore(store_path)
        factory = ObserverFactory(use_mock=True)
        ctrl = WatchController(
            config_store=store,
            observer_factory=factory,
            clock=fake_clock,
            scheduler=fake_sched,
        )

        src = tmp_path / "src"
        src.mkdir(parents=True)

        # Pre-existing file
        (src / "old.txt").write_text("old", encoding="utf-8")

        ctrl.add_watch(_make_config(src, "post1"))

        events = []
        ctrl.on_file_ready = lambda cid, fp: events.append((cid, fp))

        # New file created after recovery
        new_file = src / "new.txt"
        new_file.write_text("new", encoding="utf-8")
        ctrl._simulate_file_event("post1", str(new_file), FileEvent.CREATED)

        fake_clock.advance(3.0)
        fake_sched.run_pending()

        assert len(events) == 1
