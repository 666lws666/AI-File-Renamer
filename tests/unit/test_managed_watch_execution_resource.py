"""Exact ingress execution ownership; real guard and finite reentry threads."""
from dataclasses import replace
from threading import Event, Thread

import pytest

from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.rename_plan import SourceFingerprint
from src.core.watch_resource_guard import WatchLimits, WatchResourceGuard
from tests.unit.test_managed_watch_admission import lane, capture


def stable(lane, guard=None, size=4):
    posted = []
    ingress = ManagedWatchIngress(lane[0], lane[1], capture_guard=lane[2].guard,
        post_event=posted.append, resource_guard=guard)
    admission = capture(ingress, lane)
    assert ingress.post_stable(admission, SourceFingerprint(size, 2))
    return ingress, posted[0]


def test_exact_receipt_at_pending_cap_and_retired_cleanup_isolated_from_legacy(lane):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1,
        max_concurrent_analysis=1), cooldown_seconds=0)
    ingress, event = stable(lane, guard)
    assert ingress.try_acquire_execution(event).allowed
    assert ingress.has_execution(event)
    assert not ingress.try_acquire_execution(event).allowed
    assert not ingress.try_acquire_execution(replace(event)).allowed
    assert not ingress.release_execution(replace(event))
    assert not ingress.has_execution(replace(event))
    guard.release_analysis("watch")
    assert guard.active_analyses("watch") == 1
    assert ingress.retire(event) and not ingress.workers_idle
    assert guard.pending_count("watch") == 1
    assert ingress.release_execution(event)
    assert not ingress.release_execution(event)
    assert ingress.workers_idle and guard.pending_count("watch") == 0
    assert guard.active_analyses("watch") == 0
    assert not hasattr(event, "execution_token") and not hasattr(event, "pending_token")


def test_stable_size_not_zero_and_absent_guard_is_not_permission(lane):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_file_size_mb=1))
    ingress, event = stable(lane, guard, 1024 * 1024 + 1)
    decision = ingress.try_acquire_execution(event)
    assert not decision.allowed and decision.reason == "global_size_limit"
    assert not ingress.has_execution(event)
    assert ingress.retire(event) and ingress.workers_idle
    plain, event = stable(lane)
    decision = plain.try_acquire_execution(event)
    assert not decision.allowed and decision.reason == "resource_unavailable"
    plain.retire(event)


@pytest.mark.parametrize("withdraw", ["close", "cancel", "retire"])
@pytest.mark.parametrize("callback", ["clock", "contributor"])
def test_actual_resource_observation_survives_reentrant_withdrawal(lane, withdraw, callback):
    entered, release, observing = Event(), Event(), Event()
    observations, decisions, errors = [], [], []
    def observe(*args):
        if observing.is_set():
            observations.append(ingress.owned_count)
            entered.set()
            assert release.wait(2)
        return 10 if callback == "clock" else 0
    guard = WatchResourceGuard(clock=observe if callback == "clock" else lambda: 10)
    if callback == "contributor":
        guard.register_pending_source("external", per_watch_counter=observe, global_counter=lambda: 0)
    ingress, event = stable(lane, guard)
    observing.set()
    assert callable(ingress.try_acquire_execution)
    def acquire():
        try:
            decisions.append(ingress.try_acquire_execution(event))
        except BaseException as error:
            errors.append(error)
    thread = Thread(target=acquire)
    try:
        thread.start()
        assert entered.wait(2)
        if withdraw == "close": ingress.begin_close()
        elif withdraw == "cancel": ingress.cancel_incarnation("watch", "incarnation")
        else: ingress.retire(event)
        assert ingress.owned_count == 1 and not ingress.workers_idle
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and not errors
    assert observations == [1] and len(decisions) == 1
    assert not decisions[0].allowed and decisions[0].reason == "invalid_resource_owner"
    assert ingress.workers_idle and guard.active_analyses("watch") == 0
    observing.clear()
    assert guard.pending_count("watch") == 0


def test_stale_acquisition_false_release_keeps_exact_owner_until_cleanup(lane, monkeypatch):
    armed = [False]
    def clock():
        if armed[0]: ingress.retire(event)
        return 10
    guard = WatchResourceGuard(clock=clock)
    ingress, event = stable(lane, guard)
    original = guard.release_owned_analysis
    monkeypatch.setattr(guard, "release_owned_analysis", lambda receipt: False)
    armed[0] = True
    decision = ingress.try_acquire_execution(event)
    assert not decision.allowed and ingress.has_execution(event)
    assert not ingress.release_execution(event)
    assert not ingress.workers_idle and guard.active_analyses("watch") == 1
    monkeypatch.setattr(guard, "release_owned_analysis", original)
    assert ingress.release_execution(event) and ingress.workers_idle
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0
