"""Pending ingress ownership with real guard/catalog and finite joined threads.

Execution-receipt tests below prove primitive retention, not a Future tail.
"""
from dataclasses import replace
from threading import Barrier, Event, Thread, local

import pytest

from src.controllers.managed_watch_ingress import ManagedWatchIngress
from src.core.rename_plan import SourceFingerprint
from src.core.watch_resource_guard import WatchLimits, WatchResourceGuard
from src.core.watch_work import WatchAdmission, WatchAdmissionFailure
from tests.unit.test_managed_watch_admission import lane, capture


def make_owned(lane, guard, post=lambda event: None):
    service, authority, source, _ = lane
    return ManagedWatchIngress(service, authority, capture_guard=source.guard,
                               post_event=post, resource_guard=guard)


def start_call(call, results, errors):
    def run():
        try:
            results.append(call())
        except BaseException as error:
            errors.append(error)
    worker = Thread(target=run)
    worker.start()
    return worker


def finish_threads(workers, errors, release=None):
    if release is not None:
        release.set()
    for worker in workers:
        worker.join(5)
    assert not any(worker.is_alive() for worker in workers)
    assert not errors, repr(errors)


def test_reservation_precedes_actual_catalog_capture(lane, monkeypatch):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    ingress = make_owned(lane, guard)
    original = lane[0].capture_work
    calls = []
    def checked(*args, **kwargs):
        assert guard.pending_count("watch") == 1
        assert guard.active_analyses("watch") == 0
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(lane[0], "capture_work", checked)
    try:
        first = capture(ingress, lane)
        denied = capture(ingress, lane, "overflow")
        assert type(denied) is WatchAdmissionFailure
        assert denied.reason == "global_pending_limit"
        assert not hasattr(denied, "work")
        assert not hasattr(denied, "source_path") and not hasattr(denied, "fingerprint")
        assert calls == [1] and guard.pending_count("watch") == 1
        assert capture(ingress, lane, "coalesced") is None
        assert ingress.retire(first)
        replacement = capture(ingress, lane, "replacement")
        assert type(replacement) is WatchAdmission and calls == [1, 1]
        assert ingress.is_current(denied)  # notice does not block permitted input
    finally:
        ingress.begin_close()
        assert ingress.workers_idle and guard.global_pending_count() == 0


@pytest.mark.parametrize("invalid", [True, False, object()])
def test_constructor_rejects_nonexact_guard(lane, invalid):
    with pytest.raises(ValueError, match="^invalid_watch_resource_guard$"):
        make_owned(lane, invalid)


def test_constructor_rejects_guard_subclass(lane):
    class Derived(WatchResourceGuard):
        pass
    with pytest.raises(ValueError, match="^invalid_watch_resource_guard$"):
        make_owned(lane, Derived())


def test_explicit_none_preserves_unprotected_ingress(lane):
    ingress = make_owned(lane, None)
    event = capture(ingress, lane)
    assert type(event) is WatchAdmission
    assert ingress.retire(event) and ingress.workers_idle


def test_clock_callback_queries_ingress_from_actual_thread(lane):
    workers, errors = [], []
    armed = [False]
    def clock():
        if armed[0]:
            done = Event()
            def query():
                try:
                    assert ingress.owned_count == 1
                finally:
                    done.set()
            workers.append(start_call(query, [], errors))
            assert done.wait(1), "ingress lock held during guard callback"
        return 0
    guard = WatchResourceGuard(clock=clock)
    ingress = make_owned(lane, guard)
    armed[0] = True
    try:
        assert type(capture(ingress, lane)) is WatchAdmission
    finally:
        armed[0] = False
        ingress.begin_close()
        finish_threads(workers, errors)
        assert ingress.workers_idle and guard.global_pending_count() == 0


def test_limit_one_two_actual_admitting_threads(lane, monkeypatch):
    barrier, seen = Barrier(2), local()
    def clock():
        if not getattr(seen, "entered", False):
            seen.entered = True
            barrier.wait(3)
        return 0
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), clock=clock,
                               cooldown_seconds=0)
    ingress = make_owned(lane, guard)
    original, calls = lane[0].capture_work, []
    def checked(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(lane[0], "capture_work", checked)
    results, errors, workers = [], [], []
    try:
        for event_id in ("one", "two"):
            workers.append(start_call(lambda event_id=event_id: capture(ingress, lane, event_id),
                                      results, errors))
        finish_threads(workers, errors)
        assert sum(type(event) is WatchAdmission for event in results) == 1
        assert sum(type(event) is WatchAdmissionFailure for event in results) == 1
        assert calls == [1] and guard.pending_count("watch") == 1
        assert ingress.owned_count == 2
    finally:
        barrier.abort()
        finish_threads(workers, errors)
        ingress.begin_close()
        assert ingress.workers_idle and guard.global_pending_count() == 0


@pytest.mark.parametrize("transition", ["close", "cancel"])
def test_clock_tail_retains_prospective_owner_and_returned_receipt(lane, transition):
    entered, release = Event(), Event()
    def clock():
        entered.set()
        assert release.wait(3)
        return 0
    guard = WatchResourceGuard(clock=clock)
    ingress = make_owned(lane, guard)
    results, errors, workers = [], [], []
    try:
        workers.append(start_call(lambda: capture(ingress, lane), results, errors))
        assert entered.wait(3)
        if transition == "close":
            ingress.begin_close()
        else:
            ingress.cancel_incarnation("watch", "incarnation")
        assert ingress.owned_count == 1 and not ingress.workers_idle
    finally:
        finish_threads(workers, errors, release)
        ingress.begin_close()
    assert results == [None] and ingress.workers_idle
    assert guard.global_pending_count() == 0


def test_close_during_actual_catalog_capture_keeps_pending(lane, monkeypatch):
    guard = WatchResourceGuard()
    ingress = make_owned(lane, guard)
    entered, release = Event(), Event()
    original = lane[0].capture_work
    def blocked(*args, **kwargs):
        work = original(*args, **kwargs)
        entered.set()
        assert release.wait(3)
        return work
    monkeypatch.setattr(lane[0], "capture_work", blocked)
    results, errors, workers = [], [], []
    try:
        workers.append(start_call(lambda: capture(ingress, lane), results, errors))
        assert entered.wait(3)
        ingress.begin_close()
        assert guard.pending_count("watch") == 1
        assert ingress.owned_count == 1 and not ingress.workers_idle
    finally:
        finish_threads(workers, errors, release)
        ingress.begin_close()
    assert results == [None] and ingress.workers_idle
    assert guard.global_pending_count() == 0


def test_post_tail_keeps_receipt_after_actual_synchronous_consumer(lane):
    guard = WatchResourceGuard()
    entered, release = Event(), Event()
    def post(delivery):
        assert ingress.retire(delivery)
        entered.set()
        assert release.wait(3)
    ingress = make_owned(lane, guard, post)
    event = capture(ingress, lane)
    results, errors, workers = [], [], []
    try:
        workers.append(start_call(lambda: ingress.post_stable(event, SourceFingerprint(4, 2)),
                                  results, errors))
        assert entered.wait(3)
        ingress.begin_close()
        assert ingress.owned_count == 1 and guard.pending_count("watch") == 1
    finally:
        finish_threads(workers, errors, release)
        ingress.begin_close()
    assert results == [True] and ingress.workers_idle
    assert guard.global_pending_count() == 0


def test_resource_notice_post_tail_remains_owned_until_callback_returns(lane):
    guard = WatchResourceGuard(pending_counter=lambda _: 1,
                               global_limits=WatchLimits(max_pending=1))
    entered, release = Event(), Event()
    def post(failure):
        assert ingress.retire(failure)
        entered.set()
        assert release.wait(3)
    ingress = make_owned(lane, guard, post)
    failure = capture(ingress, lane)
    results, errors, workers = [], [], []
    try:
        workers.append(start_call(lambda: ingress.post_failure(failure), results, errors))
        assert entered.wait(3)
        ingress.begin_close()
        assert ingress.owned_count == 1 and not ingress.workers_idle
    finally:
        finish_threads(workers, errors, release)
        ingress.begin_close()
    assert results == [True] and ingress.workers_idle
    guard.set_pending_counter(lambda _: 0)
    assert guard.global_pending_count() == 0


def test_distinct_watch_notice_cap_is_independent_and_freed_by_retirement(lane, monkeypatch):
    guard = WatchResourceGuard(pending_counter=lambda _: 1,
                               global_limits=WatchLimits(max_pending=1))
    ingress = make_owned(lane, guard)
    monkeypatch.setattr(ingress, "MAX_RESOURCE_NOTICES", 1)
    other = replace(lane[3], id="other")
    def other_capture():
        return ingress.capture(other, "incarnation", other.source_dir + "/other.txt", "other")
    try:
        first = capture(ingress, lane)
        assert type(first) is WatchAdmissionFailure
        assert other_capture() is None and ingress.owned_count == 1
        assert ingress.retire(first)
        assert type(other_capture()) is WatchAdmissionFailure
        assert ingress.owned_count == 1
    finally:
        ingress.begin_close()
        guard.set_pending_counter(lambda _: 0)
        assert ingress.workers_idle and guard.global_pending_count() == 0


def test_internal_owned_overflow_has_separate_notice_without_reservation(lane, monkeypatch):
    assert ManagedWatchIngress.MAX_OWNED == 1000
    assert ManagedWatchIngress.MAX_RESOURCE_NOTICES == 1000
    guard = WatchResourceGuard()
    ingress = make_owned(lane, guard)
    monkeypatch.setattr(ingress, "MAX_OWNED", 1)
    try:
        event = capture(ingress, lane)
        notice = capture(ingress, lane, "overflow")
        assert type(notice) is WatchAdmissionFailure and notice.reason == "queue_full"
        assert ingress.owned_count == 2 and guard.pending_count("watch") == 1
        assert capture(ingress, lane, "duplicate") is None
        assert ingress.retire(event)
        assert type(capture(ingress, lane, "replacement")) is WatchAdmission
    finally:
        ingress.begin_close()
        assert ingress.workers_idle and guard.global_pending_count() == 0


def test_resource_notice_exact_post_authority_cancel_and_repeat_retirement(lane):
    guard = WatchResourceGuard(pending_counter=lambda _: 1,
                               per_watch_limits={"watch": WatchLimits(max_pending=1)})
    posted = []
    ingress = make_owned(lane, guard, posted.append)
    failure = capture(ingress, lane)
    assert failure.reason == "watch_pending_limit"
    assert ingress.is_current(failure) and not ingress.is_current(replace(failure))
    assert not ingress.post_failure(replace(failure)) and not ingress.retire(replace(failure))
    assert ingress.post_failure(failure) and posted == [failure] and posted[0] is failure
    assert not ingress.post_failure(failure)
    snapshot = failure.snapshot
    lane[1].invalidate_work()
    assert not ingress.is_current(failure) and failure.snapshot is snapshot
    ingress.cancel_incarnation("watch", "incarnation")
    ingress.begin_close()
    assert ingress.owned_count == 1
    assert ingress.retire(failure) and not ingress.retire(failure) and ingress.workers_idle
    guard.set_pending_counter(lambda _: 0)
    assert guard.global_pending_count() == 0


def test_unavailable_callback_fixed_denial_has_no_capture_io_or_execution(lane, monkeypatch):
    def unavailable(_):
        raise RuntimeError("secret/path/not-a-public-reason")
    guard = WatchResourceGuard(pending_counter=unavailable)
    ingress = make_owned(lane, guard)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(1)
        raise AssertionError("forbidden capture or source operation")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(lane[0], "capture_work", forbidden)
            patch.setattr("os.stat", forbidden)
            patch.setattr("builtins.open", forbidden)
            failure = capture(ingress, lane)
        assert type(failure) is WatchAdmissionFailure and failure.reason == "resource_unavailable"
        assert not calls and not hasattr(failure, "work")
        assert not hasattr(failure, "source_path") and not hasattr(failure, "fingerprint")
    finally:
        ingress.begin_close()
        guard.set_pending_counter(lambda _: 0)
        assert ingress.workers_idle and guard.global_pending_count() == 0


def test_admitted_settings_failure_retains_pending_until_retirement(lane):
    guard = WatchResourceGuard()
    ingress = make_owned(lane, guard)
    lane[1].select_local()
    failure = capture(ingress, lane)
    assert failure.reason == "local_unavailable" and guard.pending_count("watch") == 1
    assert ingress.retire(failure) and guard.global_pending_count() == 0
    assert ingress.workers_idle


def test_primitive_release_refusal_keeps_retired_owner_until_execution_receipt_released(lane):
    guard = WatchResourceGuard()
    ingress = make_owned(lane, guard)
    event = capture(ingress, lane)
    pair = ingress._issued[id(event)]
    pending = pair[1].pending_token
    decision, execution = guard.try_acquire_owned_analysis(pending, 4)
    assert decision.allowed and execution is not None
    try:
        assert ingress.retire(event) and not ingress.retire(event)
        assert not ingress.is_current(event) and event.cancel_event.is_set()
        ingress.begin_close()
        assert ingress.owned_count == 1 and not ingress.workers_idle
        assert ingress._issued[id(event)] is pair and pair[1].pending_token is pending
        assert guard.pending_count("watch") == 1 and guard.active_analyses("watch") == 1
    finally:
        assert guard.release_owned_analysis(execution)
        ingress.begin_close()
    assert ingress.workers_idle and guard.global_pending_count() == 0
    assert id(event) not in ingress._issued and pair[1].pending_token is None


def test_idle_query_retries_retired_owner_after_primitive_execution_release(lane):
    guard = WatchResourceGuard()
    ingress = make_owned(lane, guard)
    event = capture(ingress, lane)
    pending = ingress._issued[id(event)][1].pending_token
    decision, execution = guard.try_acquire_owned_analysis(pending, 4)
    assert decision.allowed
    try:
        assert ingress.retire(event) and ingress.owned_count == 1
    finally:
        assert guard.release_owned_analysis(execution)
    assert ingress.workers_idle and guard.global_pending_count() == 0
