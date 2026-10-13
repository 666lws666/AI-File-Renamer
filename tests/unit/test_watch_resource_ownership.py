"""Synthetic owned receipts and callback-safe resource observation witnesses."""
import math
import threading

import pytest

from src.core.watch_resource_guard import (
    R_COOLDOWN, R_FAILURE_BACKOFF, R_GLOBAL_CONCURRENT, R_GLOBAL_PENDING,
    R_GLOBAL_SIZE, R_MANUALLY_PAUSED, R_WATCH_CONCURRENT, R_WATCH_PENDING,
    R_WATCH_SIZE, WatchLimits, WatchResourceGuard,
)


UNAVAILABLE = "resource_unavailable"
INVALID_OWNER = "invalid_resource_owner"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def reserve(guard, watch="w", size=0):
    decision, token = guard.reserve_pending(watch, size)
    assert decision.allowed and token is not None
    return token


def assert_denied(result, reason):
    decision, token = result
    assert not decision.allowed and decision.reason == reason
    assert token is None


def finite_threaded_call(action, workers, errors):
    finished = threading.Event()

    def invoke():
        try:
            action()
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=invoke)
    workers.append(worker)
    worker.start()
    return finished.wait(timeout=0.5)


def join_workers(workers):
    for worker in workers:
        worker.join(timeout=3)
    assert not any(worker.is_alive() for worker in workers)


def test_concurrent_admission_exactly_one_receipt_and_retirement():
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def admit():
        try:
            barrier.wait(timeout=3)
            results.append(guard.reserve_pending("w", 0))
        except BaseException as error:
            errors.append(error)

    workers = [threading.Thread(target=admit) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
    assert not any(worker.is_alive() for worker in workers)
    assert not errors
    assert len(results) == 2
    assert sum(decision.allowed for decision, _ in results) == 1
    assert guard.pending_count("w") == guard.global_pending_count() == 1
    token = next(token for decision, token in results if decision.allowed)
    other = WatchResourceGuard()
    foreign = reserve(other)
    assert not guard.release_pending(foreign)
    assert not guard.release_pending(object())
    assert guard.global_pending_count() == 1
    assert guard.release_pending(token)
    assert not guard.release_pending(token)
    assert guard.pending_count("w") == guard.global_pending_count() == 0
    assert other.release_pending(foreign)


def test_owner_executes_at_capacity_fresh_and_legacy_do_not():
    clock = Clock()
    guard = WatchResourceGuard(clock=clock, global_limits=WatchLimits(max_pending=1), cooldown_seconds=2)
    token = reserve(guard)
    assert guard.can_acquire_owned_analysis(token, 0).allowed
    decision, execution = guard.try_acquire_owned_analysis(token, 0)
    assert decision.allowed and execution is not None
    assert guard.active_analyses("w") == 1
    assert guard.release_owned_analysis(execution)
    assert_denied(guard.reserve_pending("w", 0), R_GLOBAL_PENDING)
    assert not guard.recover_owned(token)
    clock.now = 2
    assert guard.recover_owned(token)
    assert guard.can_analyze("w", 0).reason == R_GLOBAL_PENDING
    clock.now = 4
    assert guard.release_pending(token)


def test_external_growth_and_lowered_limit_deny_existing_owner_until_restored():
    clock = Clock()
    external = [0]
    guard = WatchResourceGuard(clock=clock, per_watch_limits={"w": WatchLimits(max_pending=2)}, cooldown_seconds=1)
    guard.set_pending_counter(lambda _: external[0])
    first, second = reserve(guard), reserve(guard)
    guard.set_watch_limits("w", WatchLimits(max_pending=1))
    assert_denied(guard.try_acquire_owned_analysis(first, 0), R_WATCH_PENDING)
    assert guard.release_pending(second)
    assert not guard.recover_owned(first)
    clock.now = 1
    assert guard.recover_owned(first)
    external[0] = 1
    assert_denied(guard.try_acquire_owned_analysis(first, 0), R_WATCH_PENDING)
    external[0] = 0
    clock.now = 2
    decision, execution = guard.try_acquire_owned_analysis(first, 0)
    assert decision.allowed
    assert guard.release_owned_analysis(execution)
    assert guard.release_pending(first)


def test_receipts_separate_pending_execution_and_legacy_releases():
    guard = WatchResourceGuard(cooldown_seconds=0)
    token = reserve(guard)
    assert guard.try_acquire_analysis("w", 0).allowed
    decision, execution = guard.try_acquire_owned_analysis(token, 0)
    assert decision.allowed
    assert guard.active_analyses("w") == 2
    assert_denied(guard.try_acquire_owned_analysis(token, 0), INVALID_OWNER)
    assert guard.can_acquire_owned_analysis(token, 0).reason == INVALID_OWNER
    assert not guard.recover_owned(token)
    assert not guard.release_pending(token)
    guard.release_analysis("w")
    guard.release_analysis("w")
    assert guard.active_analyses("w") == 1
    other = WatchResourceGuard()
    foreign_pending = reserve(other)
    _, foreign_execution = other.try_acquire_owned_analysis(foreign_pending, 0)
    for fake in (foreign_execution, foreign_pending, token, object(), True, {"owner": token}):
        assert not guard.release_owned_analysis(fake)
    assert guard.active_analyses("w") == 1
    assert guard.release_owned_analysis(execution)
    assert not guard.release_owned_analysis(execution)
    assert guard.active_analyses("w") == 0
    assert guard.global_pending_count() == 1
    assert guard.release_pending(token)
    assert_denied(guard.try_acquire_owned_analysis(token, 0), INVALID_OWNER)
    assert not guard.recover_owned(token)
    assert other.release_owned_analysis(foreign_execution)
    assert other.release_pending(foreign_pending)


@pytest.mark.parametrize("order", [("one", "two"), ("two", "one")])
def test_legacy_registered_and_owned_counts_aggregate_once(order):
    guard = WatchResourceGuard(pending_counter=lambda wid: 1 if wid == "a" else 0)
    sources = {"one": ({"a": 2}, 2), "two": ({"b": 3}, 3)}
    for name in order:
        per, total = sources[name]
        guard.register_pending_source(name, per_watch_counter=lambda wid, per=per: per.get(wid, 0), global_counter=lambda total=total: total)
    guard.set_global_pending_counter(lambda: 1)
    a, b = reserve(guard, "a"), reserve(guard, "b")
    assert guard.pending_count("a") == 4
    assert guard.pending_count("b") == 4
    assert guard.global_pending_count() == 8
    guard.register_pending_source("one", per_watch_counter=lambda _: 0, global_counter=lambda: 0)
    assert guard.global_pending_count() == 6
    guard.unregister_pending_source("two")
    assert guard.pending_count("b") == 1
    assert guard.global_pending_count() == 3
    assert guard.release_pending(a) and guard.release_pending(b)


def test_legacy_fallback_global_counts_all_seen_and_owned_watches():
    external = {"a": 1, "b": 2}
    guard = WatchResourceGuard(pending_counter=lambda wid: external.get(wid, 0))
    a, b = reserve(guard, "a"), reserve(guard, "b")
    assert guard.global_pending_count() == 5
    assert guard.pending_count("a") == 2
    assert guard.pending_count("b") == 3
    assert guard.release_pending(a) and guard.release_pending(b)


@pytest.mark.parametrize("pause_kind,reason", [("manual", R_MANUALLY_PAUSED), ("backoff", R_FAILURE_BACKOFF), ("cooldown", R_COOLDOWN), ("concurrent", R_GLOBAL_CONCURRENT)])
def test_reservation_is_held_during_pause_not_execution_permission(pause_kind, reason):
    clock = Clock()
    guard = WatchResourceGuard(clock=clock, global_limits=WatchLimits(max_pending=2, max_concurrent_analysis=1), max_consecutive_failures=1, failure_backoff_base=2, cooldown_seconds=2)
    if pause_kind == "manual":
        guard.pause("w")
    elif pause_kind == "backoff":
        assert guard.note_failure("w")
    else:
        assert guard.try_acquire_analysis("other", 0).allowed
        if pause_kind == "cooldown":
            assert guard.can_analyze("w", 0).reason == R_GLOBAL_CONCURRENT
            guard.release_analysis("other")
    token = reserve(guard)
    assert guard.active_analyses("w") == 0
    assert_denied(guard.try_acquire_owned_analysis(token, 0), reason)
    assert not guard.recover_owned(token)
    if pause_kind == "manual":
        guard.resume("w")
    elif pause_kind == "concurrent":
        guard.release_analysis("other")
    clock.now = 3
    assert guard.recover_owned(token)
    assert guard.release_pending(token)


@pytest.mark.parametrize("global_limits,watch_limits,expected", [(WatchLimits(max_file_size_mb=1), WatchLimits(max_file_size_mb=1), R_GLOBAL_SIZE), (WatchLimits(), WatchLimits(max_file_size_mb=1), R_WATCH_SIZE)])
def test_size_limits_apply_to_admission_and_owned_execution(global_limits, watch_limits, expected):
    guard = WatchResourceGuard(global_limits=global_limits, per_watch_limits={"w": watch_limits})
    size = 1024 * 1024
    assert_denied(guard.reserve_pending("w", size + 1), expected)
    token = reserve(guard, size=size)
    assert_denied(guard.try_acquire_owned_analysis(token, size + 1), expected)
    assert guard.active_analyses("w") == 0
    assert guard.can_acquire_owned_analysis(token, size).allowed
    assert guard.release_pending(token)


def test_global_pending_precedes_watch_and_global_execution_precedes_watch():
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1), per_watch_limits={"w": WatchLimits(max_pending=1)}, cooldown_seconds=0)
    token = reserve(guard)
    assert_denied(guard.reserve_pending("w", 0), R_GLOBAL_PENDING)
    assert guard.release_pending(token)
    guard = WatchResourceGuard(global_limits=WatchLimits(max_concurrent_analysis=1), per_watch_limits={"w": WatchLimits(max_concurrent_analysis=1)}, cooldown_seconds=0)
    token = reserve(guard)
    assert guard.try_acquire_analysis("w", 0).allowed
    assert_denied(guard.try_acquire_owned_analysis(token, 0), R_GLOBAL_CONCURRENT)
    guard.release_analysis("w")
    assert guard.release_pending(token)


def test_watch_concurrency_counts_managed_and_legacy():
    guard = WatchResourceGuard(per_watch_limits={"w": WatchLimits(max_concurrent_analysis=1)}, cooldown_seconds=0)
    token = reserve(guard)
    _, execution = guard.try_acquire_owned_analysis(token, 0)
    assert guard.try_acquire_analysis("w", 0).reason == R_WATCH_CONCURRENT
    guard.release_analysis("w")
    assert guard.active_analyses("w") == 1
    assert guard.release_owned_analysis(execution)
    assert guard.release_pending(token)


def test_concurrent_owned_execution_same_receipt_only_one():
    guard = WatchResourceGuard()
    token = reserve(guard)
    barrier = threading.Barrier(2)
    results, errors = [], []

    def execute():
        try:
            barrier.wait(timeout=3)
            results.append(guard.try_acquire_owned_analysis(token, 0))
        except BaseException as error:
            errors.append(error)

    workers = [threading.Thread(target=execute) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
    assert not any(worker.is_alive() for worker in workers)
    assert not errors and len(results) == 2
    assert sum(decision.allowed for decision, _ in results) == 1
    execution = next(receipt for decision, receipt in results if decision.allowed)
    assert guard.active_analyses("w") == 1
    assert guard.release_owned_analysis(execution)
    assert guard.release_pending(token)


class Hostile:
    def __hash__(self):
        raise AssertionError("must not hash caller-defined object")

    def __eq__(self, other):
        raise AssertionError("must not compare caller-defined object")

    def __bool__(self):
        raise AssertionError("must not coerce caller-defined object")


@pytest.mark.parametrize("fake", [True, None, "w", {}, Hostile(), object()])
def test_fake_owners_never_hashed_or_accepted(fake):
    guard = WatchResourceGuard()
    token = reserve(guard)
    assert_denied(guard.try_acquire_owned_analysis(fake, 0), INVALID_OWNER)
    assert guard.can_acquire_owned_analysis(fake, 0).reason == INVALID_OWNER
    assert not guard.release_pending(fake)
    assert not guard.release_owned_analysis(fake)
    assert not guard.recover_owned(fake)
    assert guard.global_pending_count() == 1
    assert guard.release_pending(token)


@pytest.mark.parametrize("bad", [True, 0, -1, 1.0, math.inf, math.nan, Hostile()])
@pytest.mark.parametrize("field", ["max_pending", "max_concurrent_analysis", "max_file_size_mb"])
def test_limits_require_exact_positive_optional_ints(field, bad):
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        WatchLimits(**{field: bad})


@pytest.mark.parametrize("kwargs", [{"failure_backoff_base": True}, {"failure_backoff_base": math.inf}, {"failure_backoff_base": math.nan}, {"cooldown_seconds": True}, {"cooldown_seconds": math.inf}, {"cooldown_seconds": math.nan}, {"max_consecutive_failures": True}, {"max_consecutive_failures": 0}, {"max_consecutive_failures": 1.0}, {"clock": False}, {"pending_counter": False}, {"global_limits": Hostile()}, {"per_watch_limits": {True: WatchLimits()}}, {"per_watch_limits": {"w": Hostile()}}])
def test_invalid_constructor_values_fail_fixed(kwargs):
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        WatchResourceGuard(**kwargs)


def test_constructor_copies_watch_limits_and_preserves_valid_duration_clamps():
    limits = {"w": WatchLimits(max_pending=1)}
    guard = WatchResourceGuard(per_watch_limits=limits, failure_backoff_base=-1, cooldown_seconds=-1, max_consecutive_failures=1, clock=lambda: 0)
    limits.clear()
    token = reserve(guard)
    assert_denied(guard.reserve_pending("w", 0), R_WATCH_PENDING)
    assert guard.note_failure("w")
    assert guard.can_acquire_owned_analysis(token, 0).reason == R_FAILURE_BACKOFF
    assert guard.release_pending(token)


@pytest.mark.parametrize("watch,size", [(True, 0), ("", 0), (Hostile(), 0), ("w", True), ("w", -1), ("w", 0.0), ("w", Hostile())])
def test_invalid_decision_arguments_fail_closed_without_receipts(watch, size):
    guard = WatchResourceGuard()
    assert_denied(guard.reserve_pending(watch, size), UNAVAILABLE)
    assert guard.can_analyze(watch, size).reason == UNAVAILABLE
    assert guard.try_acquire_analysis(watch, size).reason == UNAVAILABLE
    assert guard.global_pending_count() == guard.active_analyses("w") == 0


@pytest.mark.parametrize("size", [True, -1, 0.0, math.nan, Hostile()])
def test_invalid_owned_size_does_not_acquire(size):
    guard = WatchResourceGuard()
    token = reserve(guard)
    assert_denied(guard.try_acquire_owned_analysis(token, size), UNAVAILABLE)
    assert guard.can_acquire_owned_analysis(token, size).reason == UNAVAILABLE
    assert guard.active_analyses("w") == 0
    assert guard.release_pending(token)


@pytest.mark.parametrize("method", ["pending_count", "active_analyses", "consecutive_failures", "pause", "resume", "note_success", "release_analysis"])
def test_invalid_watch_on_queries_and_setters_raises_fixed(method):
    guard = WatchResourceGuard()
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        getattr(guard, method)(Hostile())


def test_invalid_registry_and_limit_setters_do_not_replace_good_state():
    guard = WatchResourceGuard(pending_counter=lambda _: 1)
    setters = [lambda: guard.set_pending_counter(False), lambda: guard.set_global_pending_counter(False), lambda: guard.set_watch_limits(True, WatchLimits()), lambda: guard.set_watch_limits("w", Hostile()), lambda: guard.register_pending_source(Hostile(), per_watch_counter=lambda _: 0, global_counter=lambda: 0), lambda: guard.register_pending_source("x", per_watch_counter=False, global_counter=lambda: 0), lambda: guard.unregister_pending_source(Hostile())]
    for setter in setters:
        with pytest.raises(ValueError, match="^resource_unavailable$"):
            setter()
    assert guard.pending_count("w") == 1


@pytest.mark.parametrize("bad", [True, -1, 0.0, math.nan, math.inf, Hostile()])
@pytest.mark.parametrize("source", ["legacy", "registered_watch", "registered_global", "explicit_global"])
def test_malformed_counters_fail_closed_fixed_with_zero_owned_changes(bad, source):
    guard = WatchResourceGuard()
    token = reserve(guard)
    if source == "legacy":
        guard.set_pending_counter(lambda _: bad)
    elif source.startswith("registered"):
        guard.register_pending_source("s", per_watch_counter=lambda _: bad if source == "registered_watch" else 0, global_counter=lambda: bad if source == "registered_global" else 0)
    else:
        guard.set_global_pending_counter(lambda: bad)
    assert_denied(guard.reserve_pending("w", 0), UNAVAILABLE)
    assert_denied(guard.try_acquire_owned_analysis(token, 0), UNAVAILABLE)
    assert guard.can_analyze("w", 0).reason == UNAVAILABLE
    assert not guard.recover_owned(token) and not guard.recover("w")
    assert guard.active_analyses("w") == 0
    query = guard.global_pending_count if source in ("registered_global", "explicit_global") else lambda: guard.pending_count("w")
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        query()
    assert guard.release_pending(token)


@pytest.mark.parametrize("bad", [True, math.nan, math.inf, -math.inf, "zero", Hostile()])
def test_invalid_clock_denies_and_failure_does_not_publish_state(bad):
    current = [0]
    guard = WatchResourceGuard(clock=lambda: current[0], max_consecutive_failures=1)
    token = reserve(guard)
    current[0] = bad
    assert_denied(guard.reserve_pending("w", 0), UNAVAILABLE)
    assert_denied(guard.try_acquire_owned_analysis(token, 0), UNAVAILABLE)
    assert guard.can_analyze("w", 0).reason == UNAVAILABLE
    assert not guard.recover_owned(token)
    assert not guard.note_failure("w")
    assert guard.consecutive_failures("w") == 0
    assert guard.release_pending(token)


@pytest.mark.parametrize("error_type", [RuntimeError, BaseException, SystemExit])
def test_throwing_callbacks_never_expose_raw_exception_text(error_type):
    def throwing(*args):
        raise error_type("PRIVATE RAW CALLBACK DATA")

    guard = WatchResourceGuard(pending_counter=throwing)
    assert_denied(guard.reserve_pending("w", 0), UNAVAILABLE)
    assert guard.can_analyze("w", 0).reason == UNAVAILABLE
    with pytest.raises(ValueError, match="^resource_unavailable$") as caught:
        guard.pending_count("w")
    assert caught.value.__context__ is None
    guard = WatchResourceGuard(clock=throwing, max_consecutive_failures=1)
    assert not guard.note_failure("w")
    assert guard.consecutive_failures("w") == 0


def test_backoff_overflow_has_no_partial_count_or_deadline_write():
    clock = Clock()
    guard = WatchResourceGuard(clock=clock, failure_backoff_base=1e308, max_consecutive_failures=1)
    assert guard.note_failure("w")
    assert guard.consecutive_failures("w") == 1
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        guard.note_failure("w")
    assert guard.consecutive_failures("w") == 1
    clock.now = 1e308
    assert guard.can_analyze("w", 0).allowed
    guard.resume("w")
    clock.now = 1e308
    with pytest.raises(ValueError, match="^resource_unavailable$"):
        guard.note_failure("w")
    assert guard.consecutive_failures("w") == 0
    assert guard.can_analyze("w", 0).allowed


def run_callback_query_witness(kind, operation):
    """The finite callback always releases outer code before cleanup joins."""
    workers, observed, query_errors = [], [], []
    armed = [False]
    guard = None

    def callback(*args):
        if not armed[0]:
            return 0
        finished = threading.Event()

        def query():
            try:
                assert guard.active_analyses("w") == 0
            except BaseException as error:
                query_errors.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=query)
        workers.append(worker)
        worker.start()
        completed = finished.wait(timeout=0.5)
        observed.append(completed)
        if not completed:
            raise AssertionError("guard lock held during external callback")
        return 0

    guard = WatchResourceGuard(clock=callback if kind == "clock" else lambda: 0, pending_counter=callback if kind == "counter" else None, max_consecutive_failures=1, cooldown_seconds=0)
    token = reserve(guard) if operation.startswith("owned") else None
    if kind == "counter" and operation == "global_count":
        guard.set_global_pending_counter(callback)
    calls = {
        "pending_count": lambda: guard.pending_count("w"),
        "global_count": guard.global_pending_count,
        "can": lambda: guard.can_analyze("w", 0),
        "acquire": lambda: guard.try_acquire_analysis("w", 0),
        "reserve": lambda: guard.reserve_pending("w", 0),
        "owned_can": lambda: guard.can_acquire_owned_analysis(token, 0),
        "owned_acquire": lambda: guard.try_acquire_owned_analysis(token, 0),
        "recover": lambda: guard.recover("w"),
        "owned_recover": lambda: guard.recover_owned(token),
        "failure": lambda: guard.note_failure("w"),
    }
    armed[0] = True
    try:
        result = calls[operation]()
        assert observed and all(observed)
        assert not query_errors
        if operation in ("pending_count", "global_count"):
            assert result == 0
        elif operation in ("recover", "owned_recover", "failure"):
            assert result is True
        elif operation in ("reserve", "owned_acquire"):
            assert result[0].allowed
        else:
            assert result.allowed
    finally:
        armed[0] = False
        for worker in workers:
            worker.join(timeout=3)
        assert not any(worker.is_alive() for worker in workers), "cleanup must join every actual query thread"


@pytest.mark.parametrize("operation", ["pending_count", "global_count", "can", "acquire", "reserve", "owned_can", "owned_acquire", "recover", "owned_recover"])
def test_counter_callback_runs_outside_lock_actual_query_thread(operation):
    run_callback_query_witness("counter", operation)


@pytest.mark.parametrize("operation", ["can", "acquire", "reserve", "owned_can", "owned_acquire", "recover", "owned_recover", "failure"])
def test_clock_callback_runs_outside_lock_actual_query_thread(operation):
    run_callback_query_witness("clock", operation)


@pytest.mark.parametrize("query", ["decision", "count", "recovery", "failure"])
def test_revision_changing_callback_retries_three_then_fails_closed(query):
    calls = []
    workers, errors = [], []
    armed = [False]
    guard = None

    def clock():
        if armed[0]:
            calls.append("clock")
            assert finite_threaded_call(lambda: guard.register_pending_source("changing", per_watch_counter=lambda _: 0, global_counter=lambda: 0), workers, errors)
        return 0

    def counter(_):
        if armed[0] and query == "count":
            calls.append("counter")
            assert finite_threaded_call(lambda: guard.set_pending_counter(counter), workers, errors)
        return 0

    guard = WatchResourceGuard(clock=clock, pending_counter=counter, max_consecutive_failures=1)
    token = reserve(guard)
    armed[0] = True
    try:
        if query == "decision":
            assert_denied(guard.try_acquire_owned_analysis(token, 0), UNAVAILABLE)
        elif query == "count":
            with pytest.raises(ValueError, match="^resource_unavailable$"):
                guard.pending_count("w")
        elif query == "failure":
            assert not guard.note_failure("w")
        else:
            assert not guard.recover_owned(token)
        assert len(calls) == 3
        assert not errors
    finally:
        armed[0] = False
        join_workers(workers)
    assert guard.active_analyses("w") == guard.consecutive_failures("w") == 0
    assert guard.global_pending_count() == 1
    assert guard.release_pending(token)


def test_one_revision_change_resamples_current_registry_before_commit():
    guard = None
    calls = []
    workers, errors = [], []

    def contributor(_):
        calls.append(1)
        if len(calls) == 1:
            assert finite_threaded_call(lambda: guard.register_pending_source("added", per_watch_counter=lambda _: 1, global_counter=lambda: 1), workers, errors)
        return 0

    guard = WatchResourceGuard(pending_counter=contributor, global_limits=WatchLimits(max_pending=1), cooldown_seconds=0)
    try:
        assert_denied(guard.reserve_pending("w", 0), R_GLOBAL_PENDING)
        assert len(calls) == 2
        assert not errors
        assert guard.active_analyses("w") == 0
    finally:
        join_workers(workers)


def test_falsey_callable_clock_is_used_not_replaced():
    class FalseyClock:
        def __bool__(self):
            raise AssertionError("clock truthiness must not be evaluated")

        def __call__(self):
            return 0

    guard = WatchResourceGuard(clock=FalseyClock(), max_consecutive_failures=1)
    assert guard.note_failure("w")
    assert guard.can_analyze("w", 0).reason == R_FAILURE_BACKOFF


@pytest.mark.parametrize("retirement", ["legacy", "global", "replace_source", "unregister_source"])
def test_retired_contributor_finalizer_never_runs_under_guard_lock(retirement):
    guard = WatchResourceGuard()
    workers, completed, errors = [], [], []

    class Contributor:
        def __call__(self, *args):
            return 0

        def __del__(self):
            finished = threading.Event()

            def query():
                try:
                    assert guard.active_analyses("w") == 0
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            worker = threading.Thread(target=query)
            workers.append(worker)
            worker.start()
            completed.append(finished.wait(timeout=0.5))

    if retirement == "legacy":
        guard.set_pending_counter(Contributor())
        retire = lambda: guard.set_pending_counter(lambda _: 0)
    elif retirement == "global":
        guard.set_global_pending_counter(Contributor())
        retire = lambda: guard.set_global_pending_counter(lambda: 0)
    else:
        guard.register_pending_source("s", per_watch_counter=Contributor(), global_counter=lambda: 0)
        retire = (lambda: guard.unregister_pending_source("s")) if retirement == "unregister_source" else lambda: guard.register_pending_source("s", per_watch_counter=lambda _: 0, global_counter=lambda: 0)
    try:
        retire()
        assert completed == [True], "retired caller code must query before the setter returns"
        assert not errors
    finally:
        for worker in workers:
            worker.join(timeout=3)
        assert not any(worker.is_alive() for worker in workers)


def test_observation_retry_retires_old_snapshot_outside_lock():
    guard = WatchResourceGuard()
    workers, completed, errors = [], [], []

    def threaded(action):
        finished = threading.Event()

        def run():
            try:
                action()
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=run)
        workers.append(worker)
        worker.start()
        return finished.wait(timeout=0.5)

    class Contributor:
        def __call__(self, watch_id):
            assert threaded(lambda: guard.unregister_pending_source("retiring"))
            return 0

        def __del__(self):
            completed.append(threaded(lambda: guard.active_analyses("w")))

    guard.register_pending_source("retiring", per_watch_counter=Contributor(), global_counter=lambda: 0)
    try:
        assert guard.can_analyze("w", 0).allowed
        assert completed == [True], "retry must retire its old callback snapshot outside the lock"
        assert not errors
    finally:
        for worker in workers:
            worker.join(timeout=3)
        assert not any(worker.is_alive() for worker in workers)
