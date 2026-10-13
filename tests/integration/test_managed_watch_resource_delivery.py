"""Real Qt, Futures and bounded threads, synthetic work, no model/network."""
from dataclasses import replace
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from tests.integration.test_managed_watch_analysis import lane, pump_until, outcome, fingerprint, api


def guarded(lane, guard=None, blocked=None, **kwargs):
    guard = guard or WatchResourceGuard(cooldown_seconds=0)
    return lane.make(resource_guard=guard,
        on_resource_blocked=blocked or (lambda event, reason: None), **kwargs)


def test_real_worker_receipt_survives_close_until_actual_tail(lane):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1,
        max_concurrent_analysis=1), cooldown_seconds=0)
    entered, release = lane.block()
    owner = guarded(lane, guard)
    lane.post(owner)
    pump_until(entered.is_set)
    try:
        assert guard.pending_count("watch") == guard.active_analyses("watch") == 1
        owner.begin_close()
        assert not owner.workers_idle
        assert not owner.drain(time.monotonic() + .03)
        assert guard.active_analyses("watch") == guard.pending_count("watch") == 1
    finally:
        release.set()
    assert owner.drain(time.monotonic() + 2)
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0
    assert not lane.seen


def test_shared_limit_one_blocks_other_delivery_until_public_tail(lane):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_concurrent_analysis=1), cooldown_seconds=0)
    entered, release = lane.block()
    notices, observed = [], []
    def consume(result):
        second.poll()
        observed.append((guard.active_analyses("watch"), len(lane.calls)))
        QCoreApplication.processEvents()
        second.poll()
        assert len(lane.calls) == 1
        lane.seen.append(result)
    first = guarded(lane, guard, callback=consume)
    second = guarded(lane, guard, blocked=lambda e, r: notices.append((e, r)))
    one, _ = lane.post(first, event_id="one")
    pump_until(entered.is_set)
    two, _ = lane.post(second, event_id="two")
    pump_until(lambda: bool(notices))
    assert notices[0][1] == "global_concurrency_limit" and lane.calls == [one.work]
    second.poll(); second.poll()
    assert len(notices) == 1 and guard.pending_count("watch") == 2
    release.set()
    pump_until(lambda: first.workers_idle and second.workers_idle)
    assert observed == [(1, 1)] and lane.calls == [one.work, two.work]
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0


def test_paused_watch_does_not_starve_ready_watch_in_bounded_queue(lane, monkeypatch):
    guard = WatchResourceGuard(cooldown_seconds=0)
    guard.pause("watch")
    notices = []
    owner = guarded(lane, guard, blocked=lambda e, r: notices.append((e, r)), max_workers=1)
    held, _ = lane.post(owner, event_id="held")
    path = Path(lane.watch.source_dir) / "ready.txt"
    path.write_text("synthetic fixture")
    ready = owner.ingress.capture(replace(lane.watch, id="ready-watch"), "incarnation", str(path), "ready")
    assert owner.ingress.post_stable(ready, fingerprint(path))
    monkeypatch.setattr(lane.service, "run_prepared", lambda work: (lane.calls.append(work), outcome(work))[1])
    pump_until(lambda: len(lane.seen) == 1)
    exact = owner._owners[id(notices[0][0])]
    assert lane.calls == [ready.work] and owner._queued == [exact] and exact.event.admission is held
    guard.resume("watch")
    pump_until(lambda: owner.workers_idle)
    assert lane.calls == [ready.work, held.work]


@pytest.mark.parametrize("reason", ["manually_paused", "failure_backoff", "cooldown", "resource_unavailable"])
def test_transient_hold_recovers_same_work_without_recapture(lane, monkeypatch, reason):
    now, unavailable = [10], [False]
    def clock(): return float("nan") if unavailable[0] else now[0]
    guard = WatchResourceGuard(clock=clock, cooldown_seconds=5, max_consecutive_failures=1,
        failure_backoff_base=5, global_limits=WatchLimits(max_concurrent_analysis=1))
    owner_notices = []
    owner = guarded(lane, guard, blocked=lambda e, r: owner_notices.append((e, r)))
    admission, _ = lane.post(owner)
    if reason == "manually_paused": guard.pause("watch")
    elif reason == "failure_backoff": assert guard.note_failure("watch")
    elif reason == "cooldown":
        assert guard.try_acquire_analysis("watch", 0).allowed
        assert not guard.try_acquire_analysis("watch", 0).allowed
        guard.release_analysis("watch")
    else: unavailable[0] = True
    monkeypatch.setattr(lane.service, "capture_work", lambda *a, **k: pytest.fail("resource recapture"))
    monkeypatch.setattr(lane.service, "run_prepared", lambda work: (lane.calls.append(work), outcome(work))[1])
    pump_until(lambda: bool(owner_notices))
    exact = owner._owners[id(owner_notices[0][0])]
    assert owner_notices[0][1] == reason and not lane.calls and not owner._pool._threads
    owner.poll(); owner.poll()
    assert len(owner_notices) == 1 and owner._queued == [exact]
    guard.resume("watch"); now[0] = 20; unavailable[0] = False
    pump_until(lambda: owner.workers_idle)
    assert lane.calls == [admission.work] and lane.seen[0].event is exact.event


@pytest.mark.parametrize("change", ["readiness", "binding", "authority", "cancel", "close"])
def test_guard_reentry_refresh_blocks_withdrawn_body(lane, change):
    armed, ready, bound, observations = [False], [True], [True], []
    def clock():
        if armed[0]:
            armed[0] = False
            if change == "readiness": ready[0] = False
            elif change == "binding": bound[0] = False
            elif change == "authority": lane.authority.invalidate_work()
            elif change == "cancel": owner.ingress.cancel_incarnation("watch", "incarnation")
            else: owner.begin_close()
            observations.append((owner.workers_idle, owner.owned_count))
        return 10
    guard = WatchResourceGuard(clock=clock, cooldown_seconds=0)
    owner = guarded(lane, guard, can_start=lambda e: ready[0], binding=lambda e: bound[0])
    admission, _ = lane.post(owner)
    armed[0] = True
    QCoreApplication.processEvents()
    assert observations == [(False, 1)] and not owner._pool._threads and not lane.seen
    assert guard.active_analyses("watch") == 0
    if change == "readiness":
        assert owner.owned_count == 1 and not admission.cancel_event.is_set()
        ready[0] = True
    assert owner.drain(time.monotonic() + 2)
    assert len(lane.seen) == (change == "readiness")


@pytest.mark.parametrize("action", ["close", "raise", "cancel"])
def test_blocked_observer_reentry_keeps_actual_tail_then_retires(lane, action):
    guard = WatchResourceGuard(cooldown_seconds=0)
    guard.pause("watch")
    observations = []
    def blocked(event, reason):
        owner._incoming.emit(event)
        QCoreApplication.processEvents(); owner.poll()
        if action == "cancel": owner.ingress.cancel_incarnation("watch", "incarnation")
        elif action == "close": owner.begin_close()
        observations.append((owner.workers_idle, owner.owned_count, guard.pending_count("watch")))
        if action == "raise": raise RuntimeError("PRIVATE_BLOCKED_OBSERVER")
    owner = guarded(lane, guard, blocked=blocked)
    lane.post(owner)
    assert owner.drain(time.monotonic() + 2)
    assert observations == [(False, 1, 1)]
    assert owner.publication_failed is (action == "raise")
    assert not lane.seen and not owner._pool._threads and guard.pending_count("watch") == 0


@pytest.mark.parametrize("scope", ["global", "watch"])
def test_authentic_stable_oversize_queues_failure_without_body(lane, monkeypatch, scope):
    limits = WatchLimits(max_file_size_mb=1)
    guard = WatchResourceGuard(global_limits=limits if scope == "global" else None,
        per_watch_limits={"watch": limits} if scope == "watch" else None)
    owner = guarded(lane, guard)
    admission, path = lane.capture(owner)
    # Genuine observed size without allocating a giant in-memory payload.
    with path.open("r+b") as stream:
        stream.truncate(1024 * 1024 + 1)
    assert owner.ingress.post_stable(admission, fingerprint(path))
    monkeypatch.setattr(lane.service, "run_prepared", lambda *a, **k: pytest.fail("oversize body"))
    QCoreApplication.processEvents()
    assert not lane.seen and not owner.workers_idle and guard.pending_count("watch") == 1
    assert not owner._pool._threads
    pump_until(lambda: owner.workers_idle)
    assert lane.seen[0].failure == scope + "_size_limit"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None


def test_raw_pending_notice_preserves_reason_without_capture_gate_or_io(lane, monkeypatch):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    owner = guarded(lane, guard, can_start=lambda e: False)
    lane.capture(owner)
    def forbidden(*a, **k): pytest.fail("resource notice used body/capture/gate/source")
    monkeypatch.setattr(lane.service, "capture_work", forbidden)
    monkeypatch.setattr(lane.service, "run_prepared", forbidden)
    monkeypatch.setattr(owner, "_can_start", forbidden)
    monkeypatch.setattr(owner.__class__, "_fingerprint", forbidden)
    failure = owner.ingress.capture(lane.watch, "incarnation", str(Path(lane.watch.source_dir) / "missing.txt"), "overflow")
    assert owner.ingress.post_failure(failure)
    pump_until(lambda: bool(lane.seen))
    assert lane.seen[0].event is failure and lane.seen[0].failure == "global_pending_limit"
    assert lane.seen[0].outcome is lane.seen[0].metadata is None and not owner._pool._threads
    owner.begin_close(); assert owner.drain(time.monotonic() + 2)


@pytest.mark.parametrize("tail", ["before_emit", "after_emit"])
def test_completed_future_emission_and_queued_ack_keep_execution(lane, tail):
    guard = WatchResourceGuard(cooldown_seconds=0)
    held, release = threading.Event(), threading.Event()
    lane.releases.append(release)
    class Held(api().ManagedWatchAnalysisDelivery):
        def _emit(self, owned, future):
            try:
                completion = future.result()
                with owned.lock: owned.issued = completion
                if tail == "before_emit": held.set(); assert release.wait(3)
                self._completed.emit(completion)
                if tail == "after_emit": held.set(); assert release.wait(3)
            finally: owned.bridge_done.set()
    entered, worker_release = lane.block()
    owner = guarded(lane, guard, cls=Held)
    lane.post(owner); pump_until(entered.is_set); worker_release.set()
    pump_until(held.is_set)
    exact = next(iter(owner._owners.values()))
    assert exact.future.done() and not exact.bridge_done.is_set()
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 1
    if tail == "after_emit":
        pump_until(lambda: len(lane.seen) == 1)
        owner.poll()
        assert guard.active_analyses("watch") == 1 and not owner.workers_idle
    release.set(); pump_until(lambda: owner.workers_idle)
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0


def test_submission_exception_and_nested_consumer_retain_receipt_until_ack(lane, monkeypatch):
    guard = WatchResourceGuard(cooldown_seconds=0)
    observations = []
    def consume(result):
        owner._incoming.emit(result.event); QCoreApplication.processEvents(); owner.poll()
        observations.append((guard.active_analyses("watch"), guard.pending_count("watch"), owner.workers_idle))
        lane.seen.append(result)
    owner = guarded(lane, guard, callback=consume)
    def fail(*a, **k): raise RuntimeError("PRIVATE_SUBMIT")
    monkeypatch.setattr(owner._pool, "submit", fail)
    lane.post(owner); QCoreApplication.processEvents()
    assert not lane.seen and guard.active_analyses("watch") == 1
    pump_until(lambda: owner.workers_idle)
    assert observations == [(1, 1, False)] and lane.seen[0].failure == "analysis_failed"
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0


def test_stale_false_release_retry_is_cleanup_not_submission_permission(lane, monkeypatch):
    armed = [False]
    def clock():
        if armed[0]: owner.ingress.cancel_incarnation("watch", "incarnation")
        return 10
    guard = WatchResourceGuard(clock=clock)
    owner = guarded(lane, guard)
    lane.post(owner)
    original = guard.release_owned_analysis
    monkeypatch.setattr(guard, "release_owned_analysis", lambda receipt: False)
    armed[0] = True
    QCoreApplication.processEvents()
    assert not owner.workers_idle and guard.active_analyses("watch") == 1
    assert not owner._pool._threads and not lane.seen
    monkeypatch.setattr(guard, "release_owned_analysis", original)
    owner.poll(); assert owner.drain(time.monotonic() + 2)
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0


def test_held_false_release_retries_cleanup_even_while_readiness_stays_false(lane, monkeypatch):
    armed, ready = [False], [True]
    def clock():
        if armed[0]: ready[0] = False
        return 10
    guard = WatchResourceGuard(clock=clock)
    owner = guarded(lane, guard, can_start=lambda event: ready[0])
    lane.post(owner)
    original = guard.release_owned_analysis
    monkeypatch.setattr(guard, "release_owned_analysis", lambda receipt: False)
    armed[0] = True
    QCoreApplication.processEvents()
    assert guard.active_analyses("watch") == 1 and not owner._pool._threads
    monkeypatch.setattr(guard, "release_owned_analysis", original)
    owner.poll()
    assert guard.active_analyses("watch") == 0
    assert guard.pending_count("watch") == 1 and not owner.workers_idle
    assert not lane.seen and not owner._pool._threads
    armed[0] = False; ready[0] = True
    assert owner.drain(time.monotonic() + 2)


@pytest.mark.parametrize("kwargs, error", [
    ({"resource_guard": object(), "on_resource_blocked": lambda e, r: None}, ValueError),
    ({"resource_guard": WatchResourceGuard(), "on_resource_blocked": None}, TypeError),
    ({"resource_guard": WatchResourceGuard(), "on_resource_blocked": False}, TypeError),
])
def test_invalid_guarded_constructor_precedes_pool_and_timer(lane, monkeypatch, kwargs, error):
    def forbidden(*a, **k): pytest.fail("invalid guarded constructor created resource")
    monkeypatch.setattr(api(), "ThreadPoolExecutor", forbidden)
    monkeypatch.setattr(api(), "QTimer", forbidden)
    with pytest.raises(error): lane.make(**kwargs)
