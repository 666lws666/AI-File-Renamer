"""Review First watch pipeline integration (Task 3).

Proves the full chain: stable file → analysis → awaiting approval → approve
through the SHARED Batch engine (RenameExecutor + RenameHistory + UndoManager),
plus dedupe, fingerprint re-check, ignore/retry, restart recovery, corrupted
queue fail-closed, and watch-deletion safety.  All analysis is fake; no real
AI or network is ever touched.
"""
import os
from pathlib import Path

import pytest

from src.controllers.review_first_handler import (
    ERR_FINGERPRINT_CHANGED,
    ERR_NOT_FOUND,
    ERR_PREFLIGHT,
    ReviewFirstHandler,
)
from src.controllers.watch_controller import (
    FakeClock,
    FakeScheduler,
    FileEvent,
    ObserverFactory,
    WatchController,
)
from src.core.filename_validator import validate_filename
from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_history import RenameHistory
from src.core.undo_manager import UndoManager
from src.core.watch_analysis import AnalysisResult
from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchMode,
    WatchStatus,
)
from src.core.watch_review_queue import (
    ReviewItem,
    ReviewItemState,
    ReviewQueue,
    ReviewQueueError,
)


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeAnalysis:
    """Deterministic analysis double — returns a fixed suggestion."""

    def __init__(self, suggested_name=None, error_category="", raise_error=None):
        self.suggested_name = suggested_name
        self.error_category = error_category
        self.raise_error = raise_error
        self.calls: list[str] = []

    def analyze(self, source_path, template_id="", quality_mode="balanced"):
        self.calls.append(source_path)
        if self.raise_error is not None:
            raise self.raise_error
        if self.error_category:
            return AnalysisResult(
                suggested_name="x.txt", confidence=0.0,
                error_category=self.error_category)
        name = self.suggested_name or "2026-Q1_Report.txt"
        return AnalysisResult(suggested_name=name, confidence=0.95)


def _fingerprint(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path):
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir(parents=True)
    tgt.mkdir()
    config = WatchConfig(
        id="w1",
        source_dir=str(src),
        target_dir=str(tgt),
        template_id="tpl-finance",
        mode=WatchMode.REVIEW_FIRST,
        status=WatchStatus.ACTIVE,
    )
    store = WatchConfigStore(tmp_path / "watches.json")
    # NOTE: the config is NOT pre-added — WatchController.add_watch persists it.

    queue = ReviewQueue(tmp_path / "review_queue.json")
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)
    undo = UndoManager(str(tmp_path / "history.jsonl"), executor=executor)
    clock = FakeClock(100.0)
    return {
        "tmp_path": tmp_path,
        "src": src,
        "tgt": tgt,
        "config": config,
        "store": store,
        "queue": queue,
        "history": history,
        "preflight": preflight,
        "executor": executor,
        "undo": undo,
        "clock": clock,
    }


def _handler(env, analysis=None, queue=None):
    return ReviewFirstHandler(
        queue=queue or env["queue"],
        analysis_service=analysis or FakeAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda watch_id: env["config"] if watch_id == "w1" else None,
    )


def _make_file(env, name="doc.txt", content="hello world"):
    path = env["src"] / name
    path.write_text(content, encoding="utf-8")
    return path


def _controller(env, handler):
    factory = ObserverFactory(use_mock=True)
    return WatchController(
        config_store=env["store"],
        observer_factory=factory,
        clock=env["clock"],
        scheduler=FakeScheduler(env["clock"]),
        review_first_handler=handler,
    )


# ============================================================================
# Detect → analyze → awaiting approval
# ============================================================================

def test_file_ready_enters_awaiting_approval(env):
    handler = _handler(env)
    path = _make_file(env, "quarterly.txt")
    handler.handle_file_ready("w1", str(path))

    items = handler.items("w1")
    assert len(items) == 1
    item = items[0]
    assert item.state == ReviewItemState.AWAITING_APPROVAL
    assert item.suggested_name == "2026-Q1_Report.txt"
    assert item.target_parent == str(env["tgt"])
    assert item.fingerprint() == _fingerprint(str(path))
    # no disk mutation before approval
    assert (env["src"] / "quarterly.txt").exists()
    assert list(env["tgt"].iterdir()) == []
    assert env["history"].get_all() == []


def test_debounce_resets_on_continued_modification(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])
    path = _make_file(env, "active.txt")

    ctrl._simulate_file_event("w1", str(path), FileEvent.CREATED)
    env["clock"].advance(1.0)  # modification within the 2s window
    ctrl._simulate_file_event("w1", str(path), FileEvent.MODIFIED)
    env["clock"].advance(1.0)
    ctrl._scheduler.run_pending()
    # only 2s after the LAST event → NOT yet ready
    assert handler.items("w1") == []
    env["clock"].advance(1.5)
    ctrl._scheduler.run_pending()
    # full 2s since the last modification → exactly ONE pipeline entry
    assert len(handler.items("w1")) == 1


def test_duplicate_events_dedupe_single_item(env):
    handler = _handler(env)
    path = _make_file(env, "dup.txt")
    handler.handle_file_ready("w1", str(path))
    handler.handle_file_ready("w1", str(path))
    handler.handle_file_ready("w1", str(path))
    assert len(handler.items("w1")) == 1


# ============================================================================
# Approve reuses the Batch apply chain; shared undo
# ============================================================================

def test_approve_reuses_batch_apply_engine(env):
    handler = _handler(env)
    path = _make_file(env, "approve.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]

    assert handler._executor is env["executor"], (
        "the handler must run through the SAME RenameExecutor the Batch uses"
    )
    result = handler.approve(item.id)
    assert result is not None and result.state == ReviewItemState.APPLIED

    assert not (env["src"] / "approve.txt").exists()
    assert (env["tgt"] / "2026-Q1_Report.txt").exists()
    # shared history contains the watch rename
    records = env["history"].get_all()
    assert len(records) == 1
    assert records[0].task_id == item.id
    assert records[0].batch_id == item.batch_id or records[0].batch_id.startswith("watch-review-")


def test_approved_watch_rename_undoable_by_main_undo_manager(env):
    handler = _handler(env)
    path = _make_file(env, "undoable.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    handler.approve(item.id)
    assert not (env["src"] / "undoable.txt").exists()

    # the MAIN Batch UndoManager undoes the watch-created record
    results = env["undo"].undo_last_batch()
    assert any(r.success for r in results)
    assert (env["src"] / "undoable.txt").exists()
    assert not (env["tgt"] / "2026-Q1_Report.txt").exists()


def test_approve_after_fingerprint_change_is_stale(env):
    handler = _handler(env)
    path = _make_file(env, "changing.txt", content="v1")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]

    # file changes during review → old suggestion invalid
    path.write_text("v2 content that changes the mtime", encoding="utf-8")
    result = handler.approve(item.id)
    assert result is not None and result.state == ReviewItemState.FAILED
    assert result.error_category == ERR_FINGERPRINT_CHANGED
    assert (env["src"] / "changing.txt").exists(), "no rename may happen"
    assert env["history"].get_all() == []


def test_approve_missing_source_fails_closed(env):
    handler = _handler(env)
    path = _make_file(env, "gone.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    path.unlink()
    result = handler.approve(item.id)
    assert result is not None and result.state == ReviewItemState.FAILED
    assert result.error_category == ERR_NOT_FOUND


# ============================================================================
# Ignore / retry
# ============================================================================

def test_ignore_zero_io(env):
    handler = _handler(env)
    path = _make_file(env, "skip.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]

    result = handler.ignore(item.id)
    assert result is not None and result.state == ReviewItemState.IGNORED
    assert (env["src"] / "skip.txt").exists()
    assert list(env["tgt"].iterdir()) == []
    assert env["history"].get_all() == [], "ignore must never write history"


def test_retry_only_failed_items(env):
    failing = FakeAnalysis(raise_error=RuntimeError("transient"))
    handler = _handler(env, analysis=failing)
    path = _make_file(env, "retry.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    assert item.state == ReviewItemState.FAILED

    # retry with a working analysis → same item re-analyzed, no duplicate
    handler._analysis = FakeAnalysis()
    result = handler.retry(item.id)
    assert result is not None and result.state == ReviewItemState.AWAITING_APPROVAL
    assert len(handler.items("w1")) == 1

    # an awaiting item is not retryable (no-op)
    again = handler.retry(result.id)
    assert again is not None and again.state == ReviewItemState.AWAITING_APPROVAL


def test_analysis_capability_error_fail_closed(env):
    handler = _handler(env, analysis=FakeAnalysis(error_category="capability_unsupported"))
    path = _make_file(env, "cap.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    assert item.state == ReviewItemState.FAILED
    assert item.error_category == "capability_unsupported"
    assert (env["src"] / "cap.txt").exists()
    assert list(env["tgt"].iterdir()) == []


# ============================================================================
# Persistence: restart recovery + corrupted queue fail-closed
# ============================================================================

def test_restart_recovery_preserves_awaiting_and_cancels_interrupted(env):
    handler1 = _handler(env)
    path = _make_file(env, "survive.txt")
    handler1.handle_file_ready("w1", str(path))
    awaiting = handler1.items("w1")[0]
    assert awaiting.state == ReviewItemState.AWAITING_APPROVAL

    # simulate a crash mid-analysis: an item stuck in ANALYZING
    env["queue"].add(ReviewItem(
        id="interrupted-1", watch_id="w1", source_path=str(env["src"] / "x.txt"),
        size_bytes=1, mtime_ns=1, extension=".txt", display_name="x",
        state=ReviewItemState.ANALYZING,
    ))

    # "restart": a fresh handler on the same persisted queue
    handler2 = _handler(env)
    handler2.restore_after_restart()

    items = {i.id: i for i in handler2.items("w1")}
    assert items[awaiting.id].state == ReviewItemState.AWAITING_APPROVAL, (
        "an unfinished review must survive a restart"
    )
    assert items["interrupted-1"].state == ReviewItemState.CANCELLED, (
        "interrupted analysis must never auto-apply"
    )

    # the surviving item is still approvable after restart
    result = handler2.approve(awaiting.id)
    assert result is not None and result.state == ReviewItemState.APPLIED


def test_restart_reconciles_apply_when_final_queue_write_failed(env, monkeypatch):
    handler = _handler(env)
    path = _make_file(env, "queue-failure.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    real_update = env["queue"].update

    def fail_applied(candidate):
        if candidate.state == ReviewItemState.APPLIED:
            raise ReviewQueueError("queue unavailable")
        return real_update(candidate)

    monkeypatch.setattr(env["queue"], "update", fail_applied)
    result = handler.approve(item.id)
    assert result is not None and result.state == ReviewItemState.APPLIED
    assert (env["tgt"] / "2026-Q1_Report.txt").exists()

    restarted_queue = ReviewQueue(env["tmp_path"] / "review_queue.json")
    restarted = _handler(env, queue=restarted_queue)
    assert restarted.restore_after_restart() == 1
    restored = restarted_queue.get(item.id)
    assert restored is not None and restored.state == ReviewItemState.APPLIED


def test_corrupted_queue_fail_closed(env):
    queue_path = env["tmp_path"] / "corrupt_queue.json"
    queue_path.write_text("{not-valid-json", encoding="utf-8")
    with pytest.raises(ReviewQueueError):
        ReviewQueue(queue_path)

    handler = _handler(env, queue=ReviewQueue(env["tmp_path"] / "fresh_queue.json"))
    handler._queue._file_path = queue_path  # simulate corrupted storage
    handler._queue_available = False
    handler._queue_error = "unknown"

    path = _make_file(env, "corrupt.txt")
    handler.handle_file_ready("w1", str(path))  # must not create/apply anything
    assert handler.items("w1") == []
    assert list(env["tgt"].iterdir()) == []
    assert env["history"].get_all() == []


def test_partial_apply_single_failure(env):
    handler = _handler(env)
    path1 = _make_file(env, "ok.txt")
    path2 = _make_file(env, "doomed.txt")
    handler.handle_file_ready("w1", str(path1))
    handler.handle_file_ready("w1", str(path2))
    item1 = handler.items("w1")[0]
    item2 = handler.items("w1")[1]
    path2.unlink()  # source gone before approve

    r1 = handler.approve(item1.id)
    r2 = handler.approve(item2.id)
    assert r1.state == ReviewItemState.APPLIED
    assert r2.state == ReviewItemState.FAILED
    assert (env["tgt"] / "2026-Q1_Report.txt").exists()
    assert len(env["history"].get_all()) == 1


# ============================================================================
# Controller integration: dispatch, stop semantics, deletion safety
# ============================================================================

def test_review_mode_dispatches_to_handler(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])
    path = _make_file(env, "dispatch.txt")

    ctrl._simulate_file_event("w1", str(path), FileEvent.CREATED)
    env["clock"].advance(3.0)
    ctrl._scheduler.run_pending()
    assert len(handler.items("w1")) == 1, (
        "REVIEW_FIRST events must reach the review handler after debounce"
    )


def test_observer_stop_no_stale_callback(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])
    path = _make_file(env, "stale.txt")

    ctrl._simulate_file_event("w1", str(path), FileEvent.CREATED)
    ctrl.stop_all()  # observer stopped before debounce expires
    env["clock"].advance(5.0)
    ctrl._scheduler.run_pending()
    assert handler.items("w1") == [], "no stale callback after stop"


def test_delete_config_does_not_delete_files_or_undo(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])

    path = _make_file(env, "keep.txt")
    handler.handle_file_ready("w1", str(path))
    item = handler.items("w1")[0]
    handler.approve(item.id)

    # second pending item
    path2 = _make_file(env, "pending.txt")
    handler.handle_file_ready("w1", str(path2))

    ctrl.remove_watch("w1")

    # files intact — both the applied (renamed) and the pending one
    assert (env["tgt"] / "2026-Q1_Report.txt").exists()
    assert (env["src"] / "pending.txt").exists()
    # history NOT undone by config deletion
    assert len(env["history"].get_all()) == 1
    # unapplied item follows the edit-impact policy (cancelled)
    pending = [i for i in handler.items("w1") if i.source_path.endswith("pending.txt")]
    assert pending and pending[0].state == ReviewItemState.CANCELLED
