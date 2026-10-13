"""Durable metadata from real queued managed completions, no inference or apply."""
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QCoreApplication

from src.core.batch_analysis import BatchAnalysisError
from src.core.processing_authority import LocalProcessingUnavailable, CloudDispatchBlocked
from src.core.watch_config import WatchMode
from src.core.watch_review_queue import ReviewQueue, ReviewQueueError, ReviewItem, ReviewItemState
from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from tests.integration.test_managed_watch_analysis import lane, pump_until, outcome, fingerprint


def api():
    return importlib.import_module("src.controllers.managed_watch_results")


def setup(lane, tmp_path, *, guard=None, changed=None, published=None):
    guard = guard or WatchResourceGuard(cooldown_seconds=0)
    queue = ReviewQueue(tmp_path / "review.json")
    options = {} if published is None else {"on_published": published}
    results = api().ManagedWatchResults(queue=queue, resource_guard=guard, on_changed=changed, **options)
    delivery = lane.make(resource_guard=guard, on_resource_blocked=lambda e, r: None,
                         callback=results.consume_result)
    results.attach_delivery(delivery)
    return queue, guard, results, delivery


def test_newly_published_hook_only_exact_durable_success_before_public_refresh(lane, tmp_path):
    publications, order = [], []
    def published(result, row):
        assert delivery.is_publishing_result(result)
        assert results.item(row.id) is row
        assert ReviewQueue(queue._file_path).get(row.id) == row
        publications.append((result, row))
        order.append("private")
    queue, guard, results, delivery = setup(lane, tmp_path, published=published,
        changed=lambda: order.append("public"))
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert len(publications) == 1 and order == ["private", "public"]
    lane.post(delivery, event_id="deduplicated")
    pump_until(lambda: delivery.workers_idle)
    results._notify()
    assert len(publications) == 1


def saved(queue, state, name="restored.txt"):
    return queue.add(ReviewItem("", "watch", str(queue._file_path.parent / name),
        16, 1, ".txt", "restored", state, confidence=None))


def post_selected_config(lane, delivery, tmp_path):
    """The reused Lane.post intentionally closes over its initial frozen watch."""
    path = tmp_path / "synthetic.txt"
    path.write_text("synthetic fixture", encoding="utf-8")
    admission = delivery.ingress.capture(lane.watch, "incarnation", str(path), "selected")
    assert admission.watch_config is lane.watch
    assert delivery.ingress.post_stable(admission, fingerprint(path))
    return admission, path


def test_genuine_result_is_durable_and_pending_survives_ack(lane, tmp_path):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    queue, guard, results, delivery = setup(lane, tmp_path, guard=guard)
    lane.post(delivery)
    assert queue.count() == 0
    pump_until(lambda: delivery.workers_idle)
    item, = results.items()
    assert item.state is ReviewItemState.AWAITING_APPROVAL
    assert item.confidence is None and item.managed_metadata is not None
    reloaded, = ReviewQueue(tmp_path / "review.json").items()
    assert reloaded == item
    assert guard.pending_count("watch") == 1
    denied, receipt = guard.reserve_pending("watch", 0)
    assert not denied.allowed and receipt is None
    assert results.ignore(item.id).state is ReviewItemState.IGNORED
    assert guard.pending_count("watch") == 0
    allowed, receipt = guard.reserve_pending("watch", 0)
    assert allowed.allowed and guard.release_pending(receipt)
    results.begin_close()


def test_claim_only_exact_actual_callback_one_shot(lane):
    observations = []
    def consume(result):
        observations.append(result)
        assert delivery.is_publishing_result(result)
        assert not delivery.claim_result(replace(result))
        assert delivery.claim_result(result)
        assert not delivery.claim_result(result)
        delivery._completed.emit(next(iter(delivery._owners.values())).issued)
        QCoreApplication.processEvents()
        assert not delivery.workers_idle
    delivery = lane.make(callback=consume)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert len(observations) == 1
    assert not delivery.is_publishing_result(observations[0])
    assert not delivery.claim_result(observations[0])


@pytest.mark.parametrize("mode", list(WatchMode))
def test_exact_metadata_no_source_access_apply_or_active_duplicate(lane, tmp_path, monkeypatch, mode):
    lane.watch = lane.watch.with_mode(mode)
    seen, notes = [], []
    queue, guard, results, delivery = setup(lane, tmp_path, changed=lambda: seen.append(results.items()))
    original = guard.note_success
    monkeypatch.setattr(guard, "note_success", lambda watch: (notes.append(watch), original(watch))[1])
    admission, path = post_selected_config(lane, delivery, tmp_path)
    before = path.read_bytes()
    source_stats = []
    real_stat = os.stat
    def counted_stat(value, *args, **kwargs):
        if str(value) == str(path):
            source_stats.append(threading.get_ident())
            assert threading.get_ident() != threading.main_thread().ident
        return real_stat(value, *args, **kwargs)
    monkeypatch.setattr(os, "stat", counted_stat)
    # Delivery alone performs its two off-owner fingerprint checks. Publication
    # must not recapture, stat, read content, invoke legacy or execute a rename.
    capture = lane.service.capture_work
    def forbidden(*a, **k):
        pytest.fail("forbidden duplicate source/legacy/file operation")
    monkeypatch.setattr(lane.service, "capture_work", forbidden)
    pump_until(lambda: delivery.workers_idle)
    assert len(source_stats) == 2  # only the actual worker's before/after checks
    first, = queue.items()
    assert first.target_parent == str(path.parent)
    assert first.managed_metadata == seen[0][0].managed_metadata
    assert first.size_bytes == len(before) and path.read_bytes() == before
    record = json.loads(queue._file_path.read_text(encoding="utf-8"))["items"][0]
    assert record["confidence"] is None
    assert not {"fields", "text", "prompts", "content", "key", "outcome"}.intersection(record)
    assert "synthetic fixture" not in json.dumps(record)
    source_stats.clear()
    monkeypatch.setattr(os, "stat", real_stat)
    monkeypatch.setattr(lane.service, "capture_work", capture)
    lane.post(delivery, event_id="second")
    pump_until(lambda: delivery.workers_idle)
    assert queue.items() == [first] and notes == ["watch", "watch"]
    from src.controllers.managed_watch_analysis import ManagedWatchAnalysisResult
    forged = ManagedWatchAnalysisResult(object(), failure="analysis_failed")
    results.consume_result(forged)
    assert queue.items() == [first] and results.notice("watch") == ""


def test_replace_failure_preserves_memory_disk_and_closes_actual_delivery(lane, tmp_path, monkeypatch, capsys):
    queue, guard, results, delivery = setup(lane, tmp_path, changed=lambda: pytest.fail("false changed"))
    old = saved(queue, ReviewItemState.IGNORED)
    before = queue._file_path.read_bytes()
    original = os.replace
    def fail(source, target):
        if str(target) == str(queue._file_path):
            raise OSError("PRIVATE_REPLACE_SECRET")
        return original(source, target)
    monkeypatch.setattr(os, "replace", fail)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert queue.items() == [old] and queue._file_path.read_bytes() == before
    assert not results.available and results.error == "queue_unavailable"
    assert delivery.publication_failed
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        guard.pending_count("watch")
    assert "PRIVATE_REPLACE_SECRET" not in str(capsys.readouterr())


def test_counts_precede_changed_and_ignore_cannot_release_live_receipt(lane, tmp_path):
    observations = []
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    def changed():
        assert not results.workers_idle and not delivery.workers_idle
        if not observations:
            observations.append(guard.pending_count("watch"))
            assert observations == [2]
            decision, receipt = guard.reserve_pending("watch", 0)
            assert not decision.allowed and receipt is None
            item, = results.items()
            results.ignore(item.id)
            assert guard.pending_count("watch") == 1
    queue, guard, results, delivery = setup(lane, tmp_path, guard=guard, changed=changed)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert queue.items()[0].state is ReviewItemState.IGNORED
    assert observations == [2] and guard.pending_count("watch") == 0


def test_old_snapshot_observation_retries_after_durable_publication(lane, tmp_path, monkeypatch):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    queue, guard, results, delivery = setup(lane, tmp_path, guard=guard)
    entered, release = threading.Event(), threading.Event()
    observed, errors = [], []
    source_id, (per, total) = next(iter(guard._pending_sources.items()))
    def held(watch):
        if threading.current_thread() is thread:
            entered.set()
            assert release.wait(3)
        return per(watch)
    guard.register_pending_source(source_id, per_watch_counter=held, global_counter=total)
    def observe():
        try:
            observed.append(guard.reserve_pending("watch", 0))
        except ValueError as error:
            errors.append(str(error))
    thread = threading.Thread(target=observe)
    thread.start()
    try:
        assert entered.wait(2)
        lane.post(delivery)
        pump_until(lambda: delivery.workers_idle)
        assert queue.count() == 1
        release.set()
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()
    assert errors == [] and len(observed) == 1
    decision, receipt = observed[0]
    assert not decision.allowed and receipt is None
    assert decision.reason in {"global_pending_limit", "resource_unavailable"}


def test_restored_backlog_interrupted_recovery_and_preserved_states(lane, tmp_path):
    queue = ReviewQueue(tmp_path / "review.json")
    original = [saved(queue, state, state.value + ".txt") for state in ReviewItemState]
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    results = api().ManagedWatchResults(queue=ReviewQueue(queue._file_path), resource_guard=guard)
    assert guard.pending_count("watch") == 4
    assert not guard.reserve_pending("watch", 0)[0].allowed
    assert results.restore_interrupted() == 2
    assert guard.pending_count("watch") == 2
    for item in original:
        now = results.item(item.id)
        if item.state in {ReviewItemState.PENDING, ReviewItemState.ANALYZING}:
            assert now.state is ReviewItemState.CANCELLED and now.error_category == "interrupted"
        else:
            assert now == item
    delivery = lane.make(callback=results.consume_result, resource_guard=guard, on_resource_blocked=lambda e, r: None)
    results.attach_delivery(delivery)
    with pytest.raises(api().ManagedWatchResultsError, match="^invalid_managed_watch_results$"):
        results.restore_interrupted()
    results.cancel_watch("watch")
    assert guard.pending_count("watch") == 1
    applying = next(item for item in original if item.state is ReviewItemState.APPLYING)
    assert results.ignore(applying.id) == applying
    results.begin_close()
    assert guard.pending_count("watch") == 1


@pytest.mark.parametrize("kind", ["analysis_failed", "timeout", "invalid_outcome", "local_unavailable", "cloud_unavailable", "queue_full", "source_changed", "success"])
def test_real_completion_failure_accounting_once(lane, tmp_path, monkeypatch, kind):
    queue, guard, results, delivery = setup(lane, tmp_path)
    notes = []
    failure, success = guard.note_failure, guard.note_success
    monkeypatch.setattr(guard, "note_failure", lambda watch: (notes.append("failure"), failure(watch))[1])
    monkeypatch.setattr(guard, "note_success", lambda watch: (notes.append("success"), success(watch))[1])
    def run(work, **kwargs):
        if kind == "success": return outcome(work)
        if kind == "invalid_outcome": return None
        if kind == "source_changed": raise ValueError("PRIVATE")
        if kind == "local_unavailable": raise LocalProcessingUnavailable()
        if kind == "cloud_unavailable": raise CloudDispatchBlocked()
        if kind == "timeout": raise BatchAnalysisError("Cloud analysis queue timed out")
        if kind == "queue_full": raise BatchAnalysisError("Cloud analysis queue is full")
        raise RuntimeError("PRIVATE")
    monkeypatch.setattr(lane.service, "run_prepared", run)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    item, = queue.items()
    if kind == "success":
        assert item.state is ReviewItemState.AWAITING_APPROVAL and notes == ["success"]
    else:
        assert item.state is ReviewItemState.FAILED and item.error_category == kind
        assert item.suggested_name == "" and item.managed_metadata is None and item.confidence is None
        assert notes == (["failure"] if kind in {"analysis_failed", "timeout", "invalid_outcome", "local_unavailable", "cloud_unavailable"} else [])


def test_raw_admission_notice_no_row_inference_count_or_source_io(lane, tmp_path, monkeypatch):
    queue, guard, results, delivery = setup(lane, tmp_path)
    lane.authority.select_local()
    def forbidden(*a, **k): pytest.fail("raw notice accessed inference/source")
    monkeypatch.setattr(lane.service, "run_prepared", forbidden)
    monkeypatch.setattr(delivery.__class__, "_fingerprint", forbidden)
    failure = delivery.ingress.capture(lane.watch, "incarnation", str(tmp_path / "missing.txt"), "raw")
    assert delivery.ingress.post_failure(failure)
    pump_until(lambda: delivery.workers_idle)
    assert queue.count() == 0 and results.notice("watch") == "local_unavailable"
    assert guard.pending_count("watch") == guard.consecutive_failures("watch") == 0


def test_notice_is_bounded_and_success_clears_only_its_watch(lane, tmp_path):
    queue, guard, results, delivery = setup(lane, tmp_path)
    lane.authority.select_local()
    for index in range(results.MAX_NOTICES + 1):
        lane.watch = replace(lane.watch, id=f"notice-{index}")
        failure = delivery.ingress.capture(lane.watch, "incarnation", str(tmp_path / "missing.txt"), f"raw-{index}")
        assert delivery.ingress.post_failure(failure)
        pump_until(lambda: delivery.workers_idle)
    assert queue.count() == 0 and len(results._notices) == results.MAX_NOTICES
    assert results.notice("notice-0") == "" and results.notice("notice-1") == "local_unavailable"
    assert lane.authority.complete_choice(lane.authority.request_cloud_choice(), persisted=True)
    lane.watch = replace(lane.watch, id="notice-1")
    post_selected_config(lane, delivery, tmp_path)
    pump_until(lambda: delivery.workers_idle)
    assert results.notice("notice-1") == "" and results.notice("notice-2") == "local_unavailable"


def test_success_reset_and_duplicate_claim_does_not_account_twice(lane, tmp_path, monkeypatch):
    queue, guard, results, delivery = setup(lane, tmp_path)
    guard.note_failure("watch")
    calls = []
    original = guard.note_success
    monkeypatch.setattr(guard, "note_success", lambda watch: (calls.append(watch), original(watch))[1])
    def changed():
        result = next(iter(delivery._owners.values())).published_result
        assert not delivery.claim_result(result)
        results.consume_result(result)
    results._changed = changed
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert calls == ["watch"] and guard.consecutive_failures("watch") == 0 and queue.count() == 1


def test_note_clock_withdrawal_does_not_publish_changed(lane, tmp_path, monkeypatch):
    armed, changes = [False], []
    def clock():
        if armed[0]:
            armed[0] = False
            lane.authority.invalidate_work()
        return 0.0
    guard = WatchResourceGuard(clock=clock, cooldown_seconds=0)
    queue, guard, results, delivery = setup(lane, tmp_path, guard=guard, changed=lambda: changes.append(1))
    def run(work, **kwargs):
        armed[0] = True
        raise RuntimeError("PRIVATE")
    monkeypatch.setattr(lane.service, "run_prepared", run)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    item, = queue.items()
    assert item.state is ReviewItemState.CANCELLED and item.error_category == "superseded"
    assert changes == []


def test_snapshot_registration_failure_is_unavailable_not_zero(lane, tmp_path, monkeypatch):
    changes = []
    queue, guard, results, delivery = setup(lane, tmp_path, changed=lambda: changes.append(1))
    original = guard.register_pending_source
    fail = [True]
    def register(*args, **kwargs):
        if fail[0]:
            fail[0] = False
            raise RuntimeError("PRIVATE_SNAPSHOT_SECRET")
        return original(*args, **kwargs)
    monkeypatch.setattr(guard, "register_pending_source", register)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert queue.count() == 1 and changes == []
    assert not results.available and results.error == "queue_unavailable" and delivery.publication_failed
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        guard.pending_count("watch")


@pytest.mark.parametrize("action", ["ignore", "cancel", "restore"])
def test_metadata_action_replace_failure_preserves_saved_state(lane, tmp_path, monkeypatch, action):
    queue = ReviewQueue(tmp_path / "review.json")
    old = saved(queue, ReviewItemState.PENDING)
    guard = WatchResourceGuard()
    changes = []
    results = api().ManagedWatchResults(queue=queue, resource_guard=guard, on_changed=lambda: changes.append(1))
    before = queue._file_path.read_bytes()
    original = os.replace
    def fail(source, target):
        if str(target) == str(queue._file_path): raise OSError("PRIVATE_ACTION_SECRET")
        return original(source, target)
    monkeypatch.setattr(os, "replace", fail)
    call = {"ignore": lambda: results.ignore(old.id), "cancel": lambda: results.cancel_watch("watch"),
            "restore": results.restore_interrupted}[action]
    with pytest.raises(api().ManagedWatchResultsError, match="^queue_unavailable$"):
        call()
    assert queue.items() == [old] and queue._file_path.read_bytes() == before and changes == []
    assert results.workers_idle and not results.available


@pytest.mark.parametrize("action", ["close", "raise", "replay"])
def test_changed_reentry_is_owned_and_observer_exception_is_not_store_failure(lane, tmp_path, monkeypatch, action, capsys):
    seen, genuine = [], []
    def changed():
        seen.append(1)
        assert not results.workers_idle and not delivery.workers_idle
        owner = next(iter(delivery._owners.values()))
        genuine.append(owner.published_result)
        results.consume_result(owner.published_result)
        QCoreApplication.processEvents()
        if action == "close": results.begin_close(); delivery.begin_close()
        if action == "raise": raise RuntimeError("PRIVATE_CALLBACK_SECRET")
    queue, guard, results, delivery = setup(lane, tmp_path, changed=changed)
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    assert seen == [1] and queue.count() == 1
    assert results.available and results.error == ""
    assert delivery.publication_failed is (action == "raise")
    results.consume_result(genuine[0])
    assert seen == [1] and queue.count() == 1 and guard.pending_count("watch") == 1
    assert "PRIVATE_CALLBACK_SECRET" not in str(capsys.readouterr())


def test_persistence_reentrant_withdrawal_cancels_new_row_before_changed(lane, tmp_path):
    queue = ReviewQueue(tmp_path / "review.json", clock=lambda: clock())
    from datetime import datetime, timezone
    armed, changes = [False], []
    def clock():
        if armed[0]:
            armed[0] = False
            lane.authority.invalidate_work()
        return datetime.now(timezone.utc)
    guard = WatchResourceGuard(cooldown_seconds=0)
    results = api().ManagedWatchResults(queue=queue, resource_guard=guard, on_changed=lambda: changes.append(1))
    delivery = lane.make(callback=results.consume_result, resource_guard=guard, on_resource_blocked=lambda e, r: None)
    results.attach_delivery(delivery)
    armed[0] = True
    lane.post(delivery)
    pump_until(lambda: delivery.workers_idle)
    item, = queue.items()
    assert item.state is ReviewItemState.CANCELLED and item.error_category == "superseded"
    assert changes == [] and guard.pending_count("watch") == 0


def test_owner_validation_and_attach_no_mutation(lane, tmp_path):
    queue, guard, results, delivery = setup(lane, tmp_path)
    before = guard._revision
    for args in [dict(queue=object(), resource_guard=guard), dict(queue=queue, resource_guard=object()),
                 dict(queue=queue, resource_guard=guard, on_changed=False)]:
        with pytest.raises(api().ManagedWatchResultsError, match="^invalid_managed_watch_results$"):
            api().ManagedWatchResults(**args)
    assert guard._revision == before
    for invalid in [object(), delivery, lane.make(resource_guard=guard, on_resource_blocked=lambda e, r: None)]:
        with pytest.raises(api().ManagedWatchResultsError, match="^invalid_managed_watch_results$"):
            results.attach_delivery(invalid)
    fresh = api().ManagedWatchResults(queue=queue, resource_guard=guard)
    other = lane.make(callback=fresh.consume_result, resource_guard=WatchResourceGuard(), on_resource_blocked=lambda e, r: None)
    with pytest.raises(api().ManagedWatchResultsError, match="^invalid_managed_watch_results$"):
        fresh.attach_delivery(other)
    errors = []
    def foreign():
        for call in [lambda: results.consume_result(object()), lambda: results.ignore("missing"),
                     lambda: results.cancel_watch("watch"), results.begin_close]:
            try: call()
            except RuntimeError as error: errors.append(str(error))
    thread = threading.Thread(target=foreign)
    thread.start()
    try: thread.join(2)
    finally:
        thread.join(2)
        assert not thread.is_alive()
    assert errors == ["watch_owner_thread_required"] * 4 and queue.count() == 0
    for invalid in [True, object(), ""]:
        with pytest.raises(api().ManagedWatchResultsError): results.item(invalid)
        with pytest.raises(api().ManagedWatchResultsError): results.notice(invalid)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    with pytest.raises(ReviewQueueError): ReviewQueue(corrupt)


def test_attach_requires_actual_bound_method_not_attribute_spoof(lane, tmp_path):
    queue = ReviewQueue(tmp_path / "review.json")
    guard = WatchResourceGuard()
    results = api().ManagedWatchResults(queue=queue, resource_guard=guard)
    class Spoof:
        def __init__(self):
            self.__self__ = results
            self.__func__ = api().ManagedWatchResults.consume_result
        def __call__(self, result):
            pytest.fail("spoof callback should never receive admission")
    delivery = lane.make(callback=Spoof(), resource_guard=guard, on_resource_blocked=lambda e, r: None)
    revision = guard._revision
    with pytest.raises(api().ManagedWatchResultsError, match="^invalid_managed_watch_results$"):
        results.attach_delivery(delivery)
    assert results._delivery is None and guard._revision == revision
