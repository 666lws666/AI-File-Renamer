"""WatchResourceGuard pipeline integration (Task 5).

Proves the guard's behavior inside BOTH pipelines:
- Auto Apply over limit → no analysis/apply, watch RESOURCE_PAUSED, files
  held (never lost, never falsely marked successful);
- Review First at limit → new items stay pending/held; an existing
  awaiting-approval item can still be manually approved (preflight again);
- recovery re-processes held items deterministically with fingerprint
  re-checks and no duplicates.

No monetary concepts anywhere — ResourcePaused is a local-resource state.
"""
import os
from pathlib import Path

import pytest

from src.controllers.auto_apply_handler import AutoApplyHandler, AutoApplyJournal
from src.controllers.review_first_handler import ReviewFirstHandler
from src.controllers.watch_controller import WatchController, ObserverFactory
from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_history import RenameHistory
from src.core.watch_analysis import AnalysisResult
from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchMode,
    WatchStatus,
)
from src.core.watch_review_queue import ReviewItemState, ReviewQueue
from src.core.watch_resource_guard import (
    ResourceState,
    WatchLimits,
    WatchResourceGuard,
)


class FakeAnalysis:
    def __init__(self):
        self.calls = 0

    def analyze(self, source_path, template_id="", quality_mode="balanced"):
        self.calls += 1
        return AnalysisResult(suggested_name="2026-Q1_Auto.txt", confidence=0.95)


class FakeClock:
    def __init__(self):
        self._now = 0.0

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(parents=True)
    tgt.mkdir()
    config = WatchConfig(
        id="w1", source_dir=str(src), target_dir=str(tgt),
        mode=WatchMode.AUTO_APPLY, status=WatchStatus.ACTIVE,
    )
    store = WatchConfigStore(tmp_path / "watches.json")
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)
    clock = FakeClock()
    paused: list[str] = []
    return {
        "tmp_path": tmp_path,
        "src": src,
        "tgt": tgt,
        "config": config,
        "store": store,
        "history": history,
        "preflight": preflight,
        "executor": executor,
        "clock": clock,
        "paused": paused,
    }


def _make_auto(env, guard):
    handler = AutoApplyHandler(
        journal=AutoApplyJournal(env["tmp_path"] / "journal.json"),
        analysis_service=FakeAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda wid: env["config"] if wid == "w1" else None,
        resource_guard=guard,
        on_resource_pause=lambda wid: env["paused"].append(wid),
    )
    return handler


def _make_review(env, guard):
    handler = ReviewFirstHandler(
        queue=ReviewQueue(env["tmp_path"] / "review.json"),
        analysis_service=FakeAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda wid: env["config"] if wid == "w1" else None,
        resource_guard=guard,
        on_resource_pause=lambda wid: env["paused"].append(wid),
    )
    return handler


def _make_file(env, name, content="data"):
    path = env["src"] / name
    path.write_text(content, encoding="utf-8")
    return path


def _controller(env, handler):
    return WatchController(
        config_store=env["store"],
        observer_factory=ObserverFactory(use_mock=True),
        auto_apply_handler=handler,
        resource_guard=handler._resource_guard,
    )


# ============================================================================
# Auto Apply: over limit → hold, never fake success
# ============================================================================

def test_auto_apply_over_limit_holds_and_pauses(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1, max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_auto(env, guard)
    ctrl = _controller(env, handler)
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(env["config"])

    path1 = _make_file(env, "a.txt")
    handler.handle_file_ready("w1", str(path1))
    assert handler.journal_entry("w1", str(path1)).state == "applied"

    # an oversized file trips the size limit → held, watch paused
    path2 = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path2))
    entry = handler.journal_entry("w1", str(path2))
    assert entry is not None and entry.state == "held"
    assert ctrl.get_status("w1") == WatchStatus.RESOURCE_PAUSED
    # no analysis for the held file, no fake success, file not lost
    assert (env["src"] / "big.txt").exists()
    assert len(env["history"].get_all()) == 1

    # while the watch is resource-paused, further files are held too
    path3 = _make_file(env, "c.txt")
    handler.handle_file_ready("w1", str(path3))
    entry3 = handler.journal_entry("w1", str(path3))
    assert entry3 is not None and entry3.state == "held"
    assert (env["src"] / "c.txt").exists()


def test_auto_apply_recovers_after_resume_no_duplicates(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1, max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_auto(env, guard)
    ctrl = _controller(env, handler)
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(env["config"])

    path1 = _make_file(env, "a.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path2))
    assert handler.journal_entry("w1", str(path2)).state == "held"

    # resource recovery (limits raised) + manual resume
    guard.set_watch_limits("w1", WatchLimits(max_file_size_mb=100, max_pending=10))
    ctrl.resume_watch("w1")
    assert ctrl.get_status("w1") == WatchStatus.ACTIVE

    assert handler.journal_entry("w1", str(path2)).state == "applied"
    assert len(env["history"].get_all()) == 2
    # resume must not re-apply the already applied tasks
    ctrl.resume_watch("w1")
    assert len(env["history"].get_all()) == 2


# ============================================================================
# Review First: held items + manual approve still allowed
# ============================================================================

def test_review_first_holds_new_items_but_allows_existing_approval(env):
    review_config = env["config"].with_mode(WatchMode.REVIEW_FIRST)
    env["config"] = review_config
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_review(env, guard)
    ctrl = WatchController(
        config_store=env["store"],
        observer_factory=ObserverFactory(use_mock=True),
        review_first_handler=handler,
        resource_guard=guard,
    )
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(review_config)

    path1 = _make_file(env, "one.txt")
    handler.handle_file_ready("w1", str(path1))
    item1 = handler.items("w1")[0]
    assert item1.state == ReviewItemState.AWAITING_APPROVAL

    # second file at the limit → stays PENDING (held), watch paused
    path2 = _make_file(env, "two.txt")
    handler.handle_file_ready("w1", str(path2))
    item2 = handler.items("w1")[1]
    assert item2.state == ReviewItemState.PENDING
    assert ctrl.get_status("w1") == WatchStatus.RESOURCE_PAUSED

    # an existing awaiting-approval item is still manually approvable —
    # and it re-passes preflight before any disk mutation
    result = handler.approve(item1.id)
    assert result is not None and result.state == ReviewItemState.APPLIED
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()

    # held item still not lost
    assert (env["src"] / "two.txt").exists()


def test_review_first_resume_processes_held_in_fifo_order(env):
    review_config = env["config"].with_mode(WatchMode.REVIEW_FIRST)
    env["config"] = review_config
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_review(env, guard)
    ctrl = WatchController(
        config_store=env["store"],
        observer_factory=ObserverFactory(use_mock=True),
        review_first_handler=handler,
        resource_guard=guard,
    )
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(review_config)

    path1 = _make_file(env, "first.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "second.txt")
    handler.handle_file_ready("w1", str(path2))
    held = handler.items("w1")[1]
    assert held.state == ReviewItemState.PENDING

    # resource recovery (approval capacity freed) + manual resume
    guard.set_watch_limits("w1", WatchLimits(max_pending=10))
    ctrl.resume_watch("w1")

    items = handler.items("w1")
    by_path = {i.source_path: i for i in items}
    assert by_path[str(path2)].state == ReviewItemState.AWAITING_APPROVAL
    # exactly the same two items — no duplicates were created
    assert len(items) == 2


def test_resource_paused_is_not_budget_paused(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1, max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_auto(env, guard)
    ctrl = _controller(env, handler)
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(env["config"])
    path1 = _make_file(env, "a.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path2))

    status = ctrl.get_status("w1")
    assert status is WatchStatus.RESOURCE_PAUSED
    assert status.value == "resource_paused"
    assert not hasattr(WatchStatus, "BUDGET_PAUSED"), "no monetary status exists"
    assert guard.resource_state("w1") == ResourceState.PAUSED


# ============================================================================
# Controller: RESOURCE_PAUSED recovery requires guard confirmation
# ============================================================================

def _controller_with_guard(env, handler, guard):
    return WatchController(
        config_store=env["store"],
        observer_factory=ObserverFactory(use_mock=True),
        auto_apply_handler=handler,
        resource_guard=guard,
    )


def test_controller_resume_requires_guard_recovery(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1, max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_auto(env, guard)
    ctrl = _controller_with_guard(env, handler, guard)
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    resumed: list[str] = []
    ctrl._notify_resumed = lambda cid: resumed.append(cid)
    ctrl.add_watch(env["config"])

    path1 = _make_file(env, "a.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path2))
    assert ctrl.get_status("w1") == WatchStatus.RESOURCE_PAUSED

    # resume while resources are still exhausted → the controller must NOT
    # activate the watch; guard.recover() says no
    ctrl.resume_watch("w1")
    assert ctrl.get_status("w1") == WatchStatus.RESOURCE_PAUSED, (
        "the controller must not persist RESOURCE_PAUSED as ACTIVE without "
        "guard confirmation"
    )
    assert resumed == [], "no replay may be triggered on a failed recovery"
    assert handler.journal_entry("w1", str(path2)).state == "held"

    # the observer keeps collecting while still resource-paused: a new file
    # is held, never lost
    path3 = _make_file(env, "c.txt")
    handler.handle_file_ready("w1", str(path3))
    assert handler.journal_entry("w1", str(path3)).state == "held"
    assert (env["src"] / "c.txt").exists()


def test_controller_resume_after_recover_activates_and_replays(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1, max_pending=1)},
        cooldown_seconds=0,
    )
    handler = _make_auto(env, guard)
    ctrl = _controller_with_guard(env, handler, guard)
    handler._on_resource_pause = lambda wid: ctrl.resource_pause(wid)
    ctrl.add_watch(env["config"])

    path1 = _make_file(env, "a.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path2))
    assert ctrl.get_status("w1") == WatchStatus.RESOURCE_PAUSED

    # resources freed → guard.recover() succeeds → activation + replay
    guard.set_watch_limits("w1", WatchLimits(max_file_size_mb=100, max_pending=10))
    assert guard.recover("w1") is True
    ctrl.resume_watch("w1")
    assert ctrl.get_status("w1") == WatchStatus.ACTIVE
    assert handler.journal_entry("w1", str(path2)).state == "applied"
    assert len(env["history"].get_all()) == 2

    # replay is idempotent: a second resume must not duplicate
    ctrl.resume_watch("w1")
    assert len(env["history"].get_all()) == 2


def test_controller_resume_plain_paused_unaffected(env):
    """Ordinary user PAUSED recovery must not involve the guard at all."""
    guard = WatchResourceGuard(cooldown_seconds=0)
    handler = _make_auto(env, guard)
    ctrl = _controller_with_guard(env, handler, guard)
    ctrl.add_watch(env["config"])

    ctrl.pause_watch("w1")
    assert ctrl.get_status("w1") == WatchStatus.PAUSED
    ctrl.resume_watch("w1")
    assert ctrl.get_status("w1") == WatchStatus.ACTIVE


def test_auto_apply_slot_active_during_analysis(env):
    """While the Auto Apply analysis callback runs, the guard must show the
    watch's slot as acquired (active_analyses == 1)."""
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_concurrent_analysis=1)},
        cooldown_seconds=0,
    )
    observed: list[int] = []

    class _ProbingAnalysis(FakeAnalysis):
        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            observed.append(guard.active_analyses("w1"))
            return super().analyze(source_path, template_id, quality_mode)

    handler = AutoApplyHandler(
        journal=AutoApplyJournal(env["tmp_path"] / "journal.json"),
        analysis_service=_ProbingAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda wid: env["config"] if wid == "w1" else None,
        resource_guard=guard,
    )
    path = _make_file(env, "slot.txt")
    handler.handle_file_ready("w1", str(path))
    assert observed == [1], f"slot must be held during analysis, saw {observed}"
    assert handler.journal_entry("w1", str(path)).state == "applied"
    assert guard.active_analyses("w1") == 0, "slot must be released afterwards"
