"""Auto Apply watch pipeline integration (Task 4).

Proves the fully automatic chain shares the Batch engine (same
RenameExecutor / RenameHistory / UndoManager), filters nothing by itself
(the controller debounces/filters), is idempotent across restarts via its
journal, fails closed on capability errors and history/disk inconsistency,
and stops cleanly on cancellation.  All analysis is fake; no real AI.
"""
import os
from pathlib import Path

import pytest

from src.controllers.auto_apply_handler import (
    ERR_APPLY,
    ERR_CAPABILITY,
    ERR_INCONSISTENT,
    ERR_PREFLIGHT,
    AutoApplyHandler,
    AutoApplyJournal,
    AutoApplyJournalError,
)
from src.controllers.watch_controller import (
    FakeClock,
    FakeScheduler,
    FileEvent,
    ObserverFactory,
    WatchController,
)
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


class FakeAnalysis:
    def __init__(self, suggested_name=None, confidence=0.95,
                 error_category="", raise_error=None):
        self.suggested_name = suggested_name
        self.confidence = confidence
        self.error_category = error_category
        self.raise_error = raise_error
        self.calls: list[tuple[str, str, str]] = []

    def analyze(self, source_path, template_id="", quality_mode="balanced"):
        self.calls.append((source_path, template_id, quality_mode))
        if self.raise_error is not None:
            raise self.raise_error
        if self.error_category:
            return AnalysisResult(suggested_name="x.txt", confidence=0.0,
                                  error_category=self.error_category)
        return AnalysisResult(
            suggested_name=self.suggested_name or "2026-Q1_Auto.txt",
            confidence=self.confidence)


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
        mode=WatchMode.AUTO_APPLY,
        status=WatchStatus.ACTIVE,
    )
    store = WatchConfigStore(tmp_path / "watches.json")
    journal = AutoApplyJournal(tmp_path / "auto_apply_journal.json")
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
        "journal": journal,
        "history": history,
        "preflight": preflight,
        "executor": executor,
        "undo": undo,
        "clock": clock,
    }


def _handler(env, analysis=None, confidence_retry=None, journal=None):
    return AutoApplyHandler(
        journal=journal or env["journal"],
        analysis_service=analysis or FakeAnalysis(),
        executor=env["executor"],
        preflight=env["preflight"],
        config_provider=lambda watch_id: env["config"] if watch_id == "w1" else None,
        confidence_retry=confidence_retry,
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
        auto_apply_handler=handler,
    )


# ============================================================================
# Detect → analyze → apply (shared engine)
# ============================================================================

def test_stable_file_auto_applied_via_shared_engine(env):
    handler = _handler(env)
    path = _make_file(env, "auto.txt")
    handler.handle_file_ready("w1", str(path))

    assert not (env["src"] / "auto.txt").exists()
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()
    records = env["history"].get_all()
    assert len(records) == 1
    assert records[0].batch_id == "watch-auto-w1"
    assert handler._executor is env["executor"], (
        "Auto Apply must run through the SAME RenameExecutor as Batch"
    )


def test_auto_applied_undoable_by_main_undo_manager(env):
    handler = _handler(env)
    path = _make_file(env, "undo.txt")
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "undo.txt").exists()

    results = env["undo"].undo_last_batch()
    assert any(r.success for r in results)
    assert (env["src"] / "undo.txt").exists()
    assert not (env["tgt"] / "2026-Q1_Auto.txt").exists()


def test_auto_apply_controller_dispatch_after_debounce(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])
    path = _make_file(env, "dispatch.txt")

    ctrl._simulate_file_event("w1", str(path), FileEvent.CREATED)
    env["clock"].advance(3.0)
    ctrl._scheduler.run_pending()

    assert not (env["src"] / "dispatch.txt").exists()
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()


def test_temp_and_lock_files_never_reach_pipeline(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])
    for name in ("draft.tmp", "~$report.docx", "half.part"):
        p = env["src"] / name
        p.write_text("x", encoding="utf-8")
        ctrl._simulate_file_event("w1", str(p), FileEvent.CREATED)
    env["clock"].advance(3.0)
    ctrl._scheduler.run_pending()
    assert env["history"].get_all() == []
    assert list(env["tgt"].iterdir()) == []


# ============================================================================
# Low confidence reuses injected retry machinery
# ============================================================================

def test_low_confidence_retried_through_injected_machinery(env):
    analysis = FakeAnalysis(confidence=0.2)  # low confidence
    retry_calls = []

    def injected_retry(operation):
        retry_calls.append(operation)
        # deterministic: the injected machinery "re-runs" until high confidence
        analysis.confidence = 0.9
        return operation()

    handler = _handler(env, analysis=analysis, confidence_retry=injected_retry)
    path = _make_file(env, "lowconf.txt")
    handler.handle_file_ready("w1", str(path))

    assert len(retry_calls) == 1, "retry must go through the injected machinery"
    assert len(analysis.calls) == 2, "the same analysis service is re-invoked"
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()
    # no provider switch: only the one analysis service was ever used
    assert all(c[0] == str(path) for c in analysis.calls)


def test_high_confidence_no_retry(env):
    analysis = FakeAnalysis(confidence=0.95)
    retry_calls = []
    handler = _handler(env, analysis=analysis,
                       confidence_retry=lambda op: retry_calls.append(op) or op())
    path = _make_file(env, "highconf.txt")
    handler.handle_file_ready("w1", str(path))
    assert retry_calls == []
    assert len(analysis.calls) == 1


# ============================================================================
# Capability errors fail closed; failures are retryable, not lost
# ============================================================================

def test_capability_error_fail_closed(env):
    handler = _handler(env, analysis=FakeAnalysis(error_category="capability_unsupported"))
    path = _make_file(env, "cap.txt")
    handler.handle_file_ready("w1", str(path))

    assert (env["src"] / "cap.txt").exists()
    assert list(env["tgt"].iterdir()) == []
    entry = handler.journal_entry("w1", str(path))
    assert entry is not None and entry.state == "failed"
    assert entry.error_category == ERR_CAPABILITY


def test_analysis_failure_retryable_via_new_event(env):
    failing = FakeAnalysis(raise_error=RuntimeError("transient"))
    handler = _handler(env, analysis=failing)
    path = _make_file(env, "retry.txt")
    handler.handle_file_ready("w1", str(path))
    entry = handler.journal_entry("w1", str(path))
    assert entry.state == "failed"
    assert (env["src"] / "retry.txt").exists(), "failed files must not vanish"

    # a new event (or manual retry) with a working analysis applies it
    handler._analysis = FakeAnalysis()
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "retry.txt").exists()
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()


def test_partial_batch_success(env):
    class _SequenceAnalysis:
        """First call valid, second call yields an invalid suggestion."""

        def __init__(self):
            self._results = [
                AnalysisResult(suggested_name="2026-Q1_Auto.txt", confidence=0.95),
                AnalysisResult(suggested_name="wrong-extension-name", confidence=0.95),
            ]

        def analyze(self, source_path, template_id="", quality_mode="balanced"):
            return self._results.pop(0)

    handler = _handler(env, analysis=_SequenceAnalysis())
    path1 = _make_file(env, "ok1.txt")
    handler.handle_file_ready("w1", str(path1))
    path2 = _make_file(env, "doomed.txt")
    handler.handle_file_ready("w1", str(path2))

    e1 = handler.journal_entry("w1", str(path1))
    e2 = handler.journal_entry("w1", str(path2))
    assert e1 is not None and e1.state == "applied"
    assert e2 is not None and e2.state == "failed"
    assert (env["src"] / "doomed.txt").exists(), "the failed file stays put"
    assert len(env["history"].get_all()) == 1


# ============================================================================
# Restart idempotency
# ============================================================================

def test_restart_does_not_reapply_applied_task(env):
    handler1 = _handler(env)
    path = _make_file(env, "done.txt")
    handler1.handle_file_ready("w1", str(path))
    assert not (env["src"] / "done.txt").exists()

    # "restart" — same journal, fresh handler, same event re-delivered
    handler2 = _handler(env)
    handler2.handle_file_ready("w1", str(path))
    assert len(env["history"].get_all()) == 1, "applied task must not re-apply"
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()


def test_interrupted_task_resumes_after_recheck(env):
    # simulate a crash mid-apply: journal says interrupted, the file sits at
    # source with the SAME fingerprint, and NO history record was written
    from src.controllers.auto_apply_handler import _JournalEntry
    path = _make_file(env, "interrupted.txt")
    fp = _fingerprint(str(path))
    env["journal"].put(_JournalEntry(
        key=AutoApplyJournal._key("w1", str(path)),
        fingerprint=fp,
        state="interrupted",
        suggested_name="2026-Q1_Auto.txt",
        target_parent=str(env["tgt"]),
        extension=".txt",
        batch_id="watch-auto-w1",
    ))

    handler = _handler(env)
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "interrupted.txt").exists()
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()
    assert len(env["history"].get_all()) == 1

    # and the resumed task is recorded as applied — no duplicate on re-delivery
    handler.handle_file_ready("w1", str(path))
    assert len(env["history"].get_all()) == 1


def test_restore_reconciles_move_when_final_journal_write_failed(env, monkeypatch):
    path = _make_file(env, "journal-failure.txt")
    real_put = env["journal"].put

    def fail_applied(entry):
        if entry.state == "applied":
            raise AutoApplyJournalError("journal unavailable")
        return real_put(entry)

    monkeypatch.setattr(env["journal"], "put", fail_applied)
    handler = _handler(env)
    handler.handle_file_ready("w1", str(path))
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()
    assert env["journal"].get("w1", str(path)).state == "interrupted"

    restarted_journal = AutoApplyJournal(env["tmp_path"] / "auto_apply_journal.json")
    restarted = _handler(env, journal=restarted_journal)
    assert restarted.restore_after_restart() == 1
    assert restarted_journal.get("w1", str(path)).state == "applied"


def test_same_fingerprint_after_undo_stays_idempotent(env):
    """Journal says applied, the file is back at source with the SAME
    fingerprint (e.g. the user undid it) → the applied operation stays
    idempotent: no re-apply, no journal rewrite, no duplicate history."""
    handler = _handler(env)
    path = _make_file(env, "inconsistent.txt")
    handler.handle_file_ready("w1", str(path))
    assert not (env["src"] / "inconsistent.txt").exists()

    # the user undoes → file is back at source with the identical content
    (env["tgt"] / "2026-Q1_Auto.txt").rename(str(path))

    handler.handle_file_ready("w1", str(path))
    entry = handler.journal_entry("w1", str(path))
    assert entry is not None and entry.state == "applied", (
        "the applied marker must survive re-delivery with the same fingerprint"
    )
    assert (env["src"] / "inconsistent.txt").exists(), (
        "fail-closed: no rename may happen on identical content"
    )
    assert len(env["history"].get_all()) == 1, (
        "no second rename may be recorded for the same fingerprint"
    )


def test_corrupted_journal_fail_closed(env):
    path = env["tmp_path"] / "corrupt_journal.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(AutoApplyJournalError):
        AutoApplyJournal(path)

    good_journal = AutoApplyJournal(env["tmp_path"] / "good_journal.json")
    handler = _handler(env, journal=good_journal)
    handler._journal_available = False  # simulated corruption at runtime
    handler._journal_error = "unknown"

    f = _make_file(env, "blocked.txt")
    handler.handle_file_ready("w1", str(f))
    assert (env["src"] / "blocked.txt").exists()
    assert list(env["tgt"].iterdir()) == []
    assert env["history"].get_all() == []


# ============================================================================
# Cancellation
# ============================================================================

def test_stop_blocks_further_processing(env):
    handler = _handler(env)
    ctrl = _controller(env, handler)
    ctrl.add_watch(env["config"])

    handler.stop()
    path = _make_file(env, "cancelled.txt")
    ctrl._simulate_file_event("w1", str(path), FileEvent.CREATED)
    env["clock"].advance(3.0)
    ctrl._scheduler.run_pending()

    assert (env["src"] / "cancelled.txt").exists()
    assert list(env["tgt"].iterdir()) == []
    assert env["history"].get_all() == []


def test_self_produced_events_do_not_reenter(env):
    """The applied rename's own events never re-enter the pipeline: the
    target sits outside the watched source (config guard), and re-delivered
    source events find the source gone."""
    handler = _handler(env)
    path = _make_file(env, "no_loop.txt")
    handler.handle_file_ready("w1", str(path))
    assert (env["tgt"] / "2026-Q1_Auto.txt").exists()

    # re-deliver the original event — the source no longer exists
    handler.handle_file_ready("w1", str(path))
    assert len(env["history"].get_all()) == 1


def _fingerprint(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns)
