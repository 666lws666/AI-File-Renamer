"""Cross-pipeline safety regressions (post-audit closure).

Proves the deterministic defects found by the independent audit are closed
end-to-end:

1. ReviewQueue / AutoApplyJournal mutations are transactional — a failed
   save leaves BOTH memory and disk unchanged.
2. Auto Apply treats a same-path file with a DIFFERENT fingerprint as a new
   file (one analysis + one apply), while an identical fingerprint stays
   idempotent — the journal identity distinguishes operations; restart
   behaves the same; rename history and undo records are never clobbered.
3. note_failure / note_success run through BOTH pipelines: consecutive
   failures trip backoff (held, no analysis), a success resets the count;
   being held is never counted as a failure.

No monetary concepts, no network, no credentials, no multimodal code.
"""
import os
from pathlib import Path

import pytest

from src.controllers.auto_apply_handler import (
    AutoApplyHandler,
    AutoApplyJournal,
    AutoApplyJournalError,
)
from src.controllers.review_first_handler import ReviewFirstHandler
from src.core.preflight_service import PreflightService
from src.core.rename_executor import RenameExecutor
from src.core.rename_history import RenameHistory
from src.core.undo_manager import UndoManager
from src.core.watch_analysis import AnalysisResult
from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode, WatchStatus
from src.core.watch_review_queue import (
    ReviewItem,
    ReviewItemState,
    ReviewQueue,
    ReviewQueueError,
)
from src.core.watch_resource_guard import (
    R_FAILURE_BACKOFF,
    ResourceState,
    WatchLimits,
    WatchResourceGuard,
)


class FakeAnalysis:
    """Deterministic analysis double with call counting and failure modes."""

    def __init__(self, suggested_name=None, confidence=0.95,
                 error_category="", raise_error=None):
        self.suggested_name = suggested_name
        self.confidence = confidence
        self.error_category = error_category
        self.raise_error = raise_error
        self.calls = 0

    def analyze(self, source_path, template_id="", quality_mode="balanced"):
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        if self.error_category:
            return AnalysisResult(suggested_name="x.txt", confidence=0.0,
                                  error_category=self.error_category)
        return AnalysisResult(
            suggested_name=self.suggested_name or "2026-Q1_Auto.txt",
            confidence=self.confidence)


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
        template_id="tpl-finance", mode=WatchMode.AUTO_APPLY,
        status=WatchStatus.ACTIVE,
    )
    store = WatchConfigStore(tmp_path / "watches.json")
    history = RenameHistory(tmp_path / "history.jsonl")
    preflight = PreflightService(allowed_roots=[str(src), str(tgt)])
    executor = RenameExecutor(preflight, history)
    undo = UndoManager(str(tmp_path / "history.jsonl"), executor=executor)
    clock = FakeClock()
    return {
        "tmp_path": tmp_path,
        "src": src,
        "tgt": tgt,
        "config": config,
        "store": store,
        "history": history,
        "preflight": preflight,
        "executor": executor,
        "undo": undo,
        "clock": clock,
    }


def _auto_handler(env, analysis=None, guard=None, journal=None, preflight=None,
                  confidence_retry=None):
    return AutoApplyHandler(
        journal=journal or AutoApplyJournal(env["tmp_path"] / "journal.json"),
        analysis_service=analysis or FakeAnalysis(),
        executor=env["executor"],
        preflight=preflight or env["preflight"],
        config_provider=lambda wid: env["config"] if wid == "w1" else None,
        resource_guard=guard,
        confidence_retry=confidence_retry,
    )


def _review_handler(env, analysis=None, guard=None, queue=None):
    return ReviewFirstHandler(
        queue=queue or ReviewQueue(env["tmp_path"] / "review.json"),
        analysis_service=analysis or FakeAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda wid: env["config"] if wid == "w1" else None,
        resource_guard=guard,
    )


def _make_file(env, name, content="data"):
    path = env["src"] / name
    path.write_text(content, encoding="utf-8")
    return path


def _set_mtime(path, mtime_ns):
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _fingerprint(path):
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)


# ============================================================================
# Transactionality: ReviewQueue + AutoApplyJournal (candidate + save + swap)
# ============================================================================

def _queue_with_failing_save(tmp_path, monkeypatch):
    queue = ReviewQueue(tmp_path / "review.json")
    real_save = queue._save_locked

    def failing_save(items):
        real_save(dict(items))  # persist the pre-mutation state on disk first
        raise ReviewQueueError("injected save failure")

    monkeypatch.setattr(queue, "_save_locked", failing_save)
    return queue, real_save


def test_review_queue_add_save_failure_leaves_no_item(tmp_path, monkeypatch):
    queue_path = tmp_path / "review.json"
    queue = ReviewQueue(queue_path)
    monkeypatch.setattr(
        queue, "_save_locked",
        lambda items: (_ for _ in ()).throw(ReviewQueueError("injected")))
    item = ReviewItem(
        id="new-1", watch_id="w1", source_path="/tmp/a.txt",
        size_bytes=1, mtime_ns=1, extension=".txt", display_name="a",
        state=ReviewItemState.PENDING,
    )
    with pytest.raises(ReviewQueueError):
        queue.add(item)
    assert queue.get("new-1") is None, "failed add must not appear in memory"
    assert queue.count() == 0
    assert not queue_path.exists(), "failed add must not create a file on disk"


def test_review_queue_update_save_failure_keeps_old(tmp_path, monkeypatch):
    queue_path = tmp_path / "review.json"
    queue = ReviewQueue(queue_path)
    item = ReviewItem(
        id="u-1", watch_id="w1", source_path="/tmp/a.txt",
        size_bytes=1, mtime_ns=1, extension=".txt", display_name="a",
        state=ReviewItemState.PENDING,
    )
    queue.add(item)
    before = queue_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        queue, "_save_locked",
        lambda items: (_ for _ in ()).throw(ReviewQueueError("injected")))
    with pytest.raises(ReviewQueueError):
        queue.update(item.with_state(ReviewItemState.AWAITING_APPROVAL))
    kept = queue.get("u-1")
    assert kept is not None and kept.state == ReviewItemState.PENDING, (
        "failed update must keep the old item in memory"
    )
    assert queue_path.read_text(encoding="utf-8") == before, (
        "failed update must keep the old file content"
    )


def test_review_queue_remove_save_failure_keeps_original(tmp_path, monkeypatch):
    queue_path = tmp_path / "review.json"
    queue = ReviewQueue(queue_path)
    item = ReviewItem(
        id="r-1", watch_id="w1", source_path="/tmp/a.txt",
        size_bytes=1, mtime_ns=1, extension=".txt", display_name="a",
        state=ReviewItemState.PENDING,
    )
    queue.add(item)
    before = queue_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        queue, "_save_locked",
        lambda items: (_ for _ in ()).throw(ReviewQueueError("injected")))
    with pytest.raises(ReviewQueueError):
        queue.remove("r-1")
    assert queue.get("r-1") is not None, "failed remove must keep the item"
    assert queue.count() == 1
    assert queue_path.read_text(encoding="utf-8") == before


def test_auto_apply_journal_put_save_failure_keeps_memory_and_disk(tmp_path, monkeypatch):
    from src.controllers.auto_apply_handler import _JournalEntry
    journal_path = tmp_path / "journal.json"
    journal = AutoApplyJournal(journal_path)
    entry = _JournalEntry(
        key=AutoApplyJournal._key("w1", "/tmp/a.txt"),
        fingerprint=(1, 1), state="applied",
    )
    monkeypatch.setattr(
        journal, "_save_locked",
        lambda entries: (_ for _ in ()).throw(AutoApplyJournalError("injected")))
    with pytest.raises(AutoApplyJournalError):
        journal.put(entry)
    assert journal.get("w1", "/tmp/a.txt") is None, (
        "failed put must not appear in memory"
    )
    assert not journal_path.exists(), (
        "failed put must not create a journal file on disk"
    )


# ============================================================================
# Auto Apply: same path, new fingerprint = new file; same fingerprint idempotent
# ============================================================================

def test_auto_apply_same_fingerprint_redelivery_no_second_rename(env):
    analysis = FakeAnalysis()
    handler = _auto_handler(env, analysis=analysis)
    path = _make_file(env, "same.txt", content="v1")
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "same.txt").exists()
    assert len(env["history"].get_all()) == 1
    applied_fp = handler.journal_entry("w1", str(path)).fingerprint

    # the file reappears at the source with the IDENTICAL fingerprint
    (env["tgt"] / "2026-Q1_Auto.txt").rename(str(path))
    _set_mtime(path, applied_fp[1])  # restore the exact applied mtime

    handler.handle_file_ready("w1", str(path))
    entry = handler.journal_entry("w1", str(path))
    assert entry is not None and entry.state == "applied"
    assert analysis.calls == 1, "identical fingerprint must not re-analyze"
    assert len(env["history"].get_all()) == 1, "identical fingerprint must not re-rename"


def test_auto_apply_different_fingerprint_same_path_new_operation(env):
    analysis = FakeAnalysis()
    handler = _auto_handler(env, analysis=analysis)
    path = _make_file(env, "newver.txt", content="v1")
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "newver.txt").exists()
    assert len(env["history"].get_all()) == 1

    # a NEW file arrives at the same path (different size → fingerprint)
    (env["tgt"] / "2026-Q1_Auto.txt").rename(str(path))
    path.write_text("v2 content that is longer", encoding="utf-8")

    handler.handle_file_ready("w1", str(path))
    entry = handler.journal_entry("w1", str(path))
    assert entry is not None and entry.state == "applied"
    assert analysis.calls == 2, "a new fingerprint is a new file → one re-analysis"
    assert len(env["history"].get_all()) == 2, "the new operation gets its own record"
    # the old operation's history record is untouched
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()


def test_auto_apply_new_operation_still_undoable(env):
    handler = _auto_handler(env)
    path = _make_file(env, "undo2.txt", content="v1")
    handler.handle_file_ready("w1", str(path))
    (env["tgt"] / "2026-Q1_Auto.txt").rename(str(path))
    path.write_text("v2 content longer", encoding="utf-8")
    handler.handle_file_ready("w1", str(path))
    assert len(env["history"].get_all()) == 2

    # the NEW operation is undoable through the shared UndoManager
    results = env["undo"].undo_last_batch()
    assert any(r.success for r in results)
    assert (env["src"] / "undo2.txt").exists()
    # the OLD operation's history record is intact — never clobbered
    records = env["history"].get_all()
    assert len(records) == 2
    assert str(records[0].old_path) == str(path)
    assert str(records[0].new_path) == str(env["tgt"] / "2026-Q1_Auto.txt")


def test_auto_apply_different_fingerprint_restart_consistent(env):
    analysis = FakeAnalysis()
    handler1 = _auto_handler(env, analysis=analysis)
    path = _make_file(env, "restart.txt", content="v1")
    handler1.handle_file_ready("w1", str(path))
    (env["tgt"] / "2026-Q1_Auto.txt").rename(str(path))
    path.write_text("v2 content longer", encoding="utf-8")

    # "restart": fresh handler + journal loaded from the same file
    handler2 = _auto_handler(env, analysis=analysis)
    handler2.handle_file_ready("w1", str(path))
    assert analysis.calls == 2
    assert len(env["history"].get_all()) == 2

    # re-delivery of the SAME fingerprint after restart stays idempotent
    handler2.handle_file_ready("w1", str(path))
    assert analysis.calls == 2, "same fingerprint must not re-analyze after restart"
    assert len(env["history"].get_all()) == 2


# ============================================================================
# note_failure / note_success through BOTH pipelines
# ============================================================================

def test_review_first_consecutive_failures_trip_backoff_and_success_resets(env):
    guard = WatchResourceGuard(
        failure_backoff_base=10.0,
        max_consecutive_failures=3,
        cooldown_seconds=0,
        clock=env["clock"],
    )
    failing = FakeAnalysis(raise_error=RuntimeError("transient"))
    handler = _review_handler(env, analysis=failing, guard=guard)
    paused: list[str] = []
    handler._on_resource_pause = lambda wid: paused.append(wid)

    for i in range(3):
        path = _make_file(env, f"fail{i}.txt")
        handler.handle_file_ready("w1", str(path))
    assert guard.consecutive_failures("w1") == 3

    # during backoff a new item is blocked → held AND surfaced as a pause
    path4 = _make_file(env, "held.txt")
    handler.handle_file_ready("w1", str(path4))
    assert paused, "backoff must surface as a resource pause"
    held = [i for i in handler.items("w1") if i.source_path == str(path4)][0]
    assert held.state == ReviewItemState.PENDING, "backoff blocks analysis → held"
    assert failing.calls == 3, "no analysis while in backoff"

    # backoff expires → a success resets the failure count
    env["clock"].advance(10.0)
    handler._analysis = FakeAnalysis()
    path5 = _make_file(env, "ok.txt")
    handler.handle_file_ready("w1", str(path5))
    assert guard.consecutive_failures("w1") == 0, "success must reset the count"
    ok = [i for i in handler.items("w1") if i.source_path == str(path5)][0]
    assert ok.state == ReviewItemState.AWAITING_APPROVAL
    assert guard.resource_state("w1") == ResourceState.OK


def test_auto_apply_capability_preflight_executor_failures_count(env):
    guard = WatchResourceGuard(
        failure_backoff_base=10.0,
        max_consecutive_failures=3,
        cooldown_seconds=0,
        clock=env["clock"],
    )
    handler = _auto_handler(env, guard=guard)

    # 1) capability failure → count 1
    handler._analysis = FakeAnalysis(error_category="capability_unsupported")
    p1 = _make_file(env, "cap.txt")
    handler.handle_file_ready("w1", str(p1))
    assert guard.consecutive_failures("w1") == 1

    # 2) preflight failure → count 2
    class _BlockingPreflight:
        def check(self, plan):
            return type("PF", (), {"can_execute": False})()

    handler._preflight = _BlockingPreflight()
    handler._analysis = FakeAnalysis()
    p2 = _make_file(env, "preflight.txt")
    handler.handle_file_ready("w1", str(p2))
    assert guard.consecutive_failures("w1") == 2

    # 3) executor failure → count 3 → backoff trips
    class _FailingExecutor:
        def execute(self, plans, batch_id=""):
            raise RuntimeError("executor exploded")

    handler._preflight = env["preflight"]
    handler._executor = _FailingExecutor()
    p3 = _make_file(env, "exec.txt")
    handler.handle_file_ready("w1", str(p3))
    assert guard.consecutive_failures("w1") == 3
    assert guard.try_acquire_analysis("w1", 0).reason == R_FAILURE_BACKOFF

    # 4) a success (applied) resets the count
    env["clock"].advance(10.0)
    handler._executor = env["executor"]
    p4 = _make_file(env, "win.txt")
    handler.handle_file_ready("w1", str(p4))
    assert guard.consecutive_failures("w1") == 0
    assert handler.journal_entry("w1", str(p4)).state == "applied"


def test_held_does_not_count_as_failure(env):
    guard = WatchResourceGuard(
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1)},
        cooldown_seconds=0,
        clock=env["clock"],
    )
    handler = _auto_handler(env, guard=guard)
    path = _make_file(env, "big.txt", content="x" * (2 * 1024 * 1024))
    handler.handle_file_ready("w1", str(path))
    assert handler.journal_entry("w1", str(path)).state == "held"
    assert guard.consecutive_failures("w1") == 0, "held is not a failure"


# ============================================================================
# Auto Apply: one failed operation counts EXACTLY once
# ============================================================================

def test_auto_apply_initial_analysis_exception_counts_once(env):
    guard = WatchResourceGuard(
        failure_backoff_base=10.0,
        max_consecutive_failures=3,
        cooldown_seconds=0,
        clock=env["clock"],
    )
    handler = _auto_handler(
        env, analysis=FakeAnalysis(raise_error=RuntimeError("transient")),
        guard=guard)
    path = _make_file(env, "once.txt")
    handler.handle_file_ready("w1", str(path))
    assert guard.consecutive_failures("w1") == 1, (
        "one initial analyze exception must count exactly once"
    )


def test_auto_apply_confidence_retry_exception_counts_once(env):
    guard = WatchResourceGuard(
        failure_backoff_base=10.0,
        max_consecutive_failures=3,
        cooldown_seconds=0,
        clock=env["clock"],
    )
    analysis = FakeAnalysis(confidence=0.2)  # low confidence → retry path

    def failing_retry(operation):
        raise RuntimeError("injected retry failure")

    handler = _auto_handler(
        env, analysis=analysis, confidence_retry=failing_retry, guard=guard)
    path = _make_file(env, "retryonce.txt")
    handler.handle_file_ready("w1", str(path))
    assert guard.consecutive_failures("w1") == 1, (
        "an exception inside the injected retry must count exactly once"
    )


def test_auto_apply_two_failed_operations_trip_backoff_at_two(env):
    """With max_consecutive_failures=2, TWO separate file operations must
    fail before backoff trips — a single exception must never trip it."""
    guard = WatchResourceGuard(
        failure_backoff_base=10.0,
        max_consecutive_failures=2,
        cooldown_seconds=0,
        clock=env["clock"],
    )
    handler = _auto_handler(
        env, analysis=FakeAnalysis(raise_error=RuntimeError("transient")),
        guard=guard)
    p1 = _make_file(env, "fail1.txt")
    handler.handle_file_ready("w1", str(p1))
    assert guard.consecutive_failures("w1") == 1
    assert not guard.try_acquire_analysis("w1", 0).blocked, (
        "one failed operation must NOT trip the backoff"
    )
    p2 = _make_file(env, "fail2.txt")
    handler.handle_file_ready("w1", str(p2))
    assert guard.consecutive_failures("w1") == 2
    decision = guard.try_acquire_analysis("w1", 0)
    assert decision.blocked and decision.reason == R_FAILURE_BACKOFF
