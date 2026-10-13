"""WatchResourceGuard — non-monetary resource protection tests (Task 5).

Local resources and queue limits only: NO prices, currency, fees, monthly
spending, or API costs anywhere.  Global limits are hard and checked first;
per-watch limits apply second.  Deterministic via the injectable clock.
"""
import pytest

from src.core.watch_resource_guard import (
    R_COOLDOWN,
    R_FAILURE_BACKOFF,
    R_GLOBAL_CONCURRENT,
    R_GLOBAL_PENDING,
    R_GLOBAL_SIZE,
    R_MANUALLY_PAUSED,
    R_WATCH_CONCURRENT,
    R_WATCH_PENDING,
    R_WATCH_SIZE,
    ResourceState,
    WatchLimits,
    WatchResourceGuard,
)


class FakeClock:
    def __init__(self, start=0.0):
        self._now = start

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


@pytest.fixture
def clock():
    return FakeClock(0.0)


def _guard(clock, **kw):
    return WatchResourceGuard(clock=clock, **kw)


# ============================================================================
# Pending queue limits (per-watch and global precedence)
# ============================================================================

def test_per_watch_pending_limit_blocks(clock):
    pending = {"w1": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=2)},
        pending_counter=counter,
    )
    assert guard.can_analyze("w1", 0).allowed
    pending["w1"] = 2
    decision = guard.can_analyze("w1", 0)
    assert decision.blocked and decision.reason == R_WATCH_PENDING
    assert guard.resource_state("w1") == ResourceState.PAUSED


def test_global_pending_limit_is_hard_and_first(clock):
    pending = {"w1": 0, "w2": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        global_limits=WatchLimits(max_pending=3),
        pending_counter=counter,
    )
    pending["w1"] = 3
    # global cap tripped by w1 blocks w2 as well — global first
    d1 = guard.can_analyze("w1", 0)
    d2 = guard.can_analyze("w2", 0)
    assert d1.blocked and d1.reason == R_GLOBAL_PENDING
    assert d2.blocked and d2.reason == R_COOLDOWN  # global hysteresis


def test_global_limit_binds_even_when_watch_limit_is_lower(clock):
    """Precedence: the global limit wins over the per-watch limit."""
    pending = {"w1": 0, "w2": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        global_limits=WatchLimits(max_pending=2),
        per_watch_limits={"w1": WatchLimits(max_pending=5)},
        pending_counter=counter,
    )
    pending["w1"] = 2
    decision = guard.can_analyze("w1", 0)
    assert decision.blocked and decision.reason == R_GLOBAL_PENDING


def test_per_watch_limits_do_not_affect_other_watches(clock):
    pending = {"w1": 0, "w2": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=counter,
    )
    pending["w1"] = 1
    assert guard.can_analyze("w1", 0).blocked
    assert guard.can_analyze("w2", 0).allowed


# ============================================================================
# Concurrency limits
# ============================================================================

def test_concurrent_analysis_limit_per_watch(clock):
    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_concurrent_analysis=1)},
        cooldown_seconds=0,
    )
    assert guard.try_acquire_analysis("w1", 0).allowed
    decision = guard.try_acquire_analysis("w1", 0)
    assert decision.blocked and decision.reason == R_WATCH_CONCURRENT
    guard.release_analysis("w1")
    assert guard.try_acquire_analysis("w1", 0).allowed
    guard.release_analysis("w1")
    assert guard.active_analyses("w1") == 0


def test_global_concurrency_limit(clock):
    guard = _guard(
        clock,
        global_limits=WatchLimits(max_concurrent_analysis=2),
        cooldown_seconds=0,
    )
    assert guard.try_acquire_analysis("w1", 0).allowed
    assert guard.try_acquire_analysis("w2", 0).allowed
    assert guard.try_acquire_analysis("w3", 0).blocked
    guard.release_analysis("w1")
    guard.release_analysis("w2")
    assert guard.active_analyses("w1") == 0
    assert guard.active_analyses("w2") == 0


# ============================================================================
# File size limit (metadata only)
# ============================================================================

def test_file_size_limit_blocks(clock):
    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1)},
    )
    assert guard.can_analyze("w1", 0).allowed
    assert guard.can_analyze("w1", 1024).allowed
    assert guard.can_analyze("w1", 2 * 1024 * 1024).blocked


def test_global_size_limit(clock):
    guard = _guard(
        clock,
        global_limits=WatchLimits(max_file_size_mb=1),
    )
    decision = guard.can_analyze("w9", 3 * 1024 * 1024)
    assert decision.blocked and decision.reason == R_GLOBAL_SIZE


# ============================================================================
# Failure backoff + cooldown/hysteresis + manual resume
# ============================================================================

def test_failure_backoff_pauses_watch(clock):
    guard = _guard(
        clock,
        failure_backoff_base=10.0,
        max_consecutive_failures=3,
    )
    assert not guard.note_failure("w1")
    assert not guard.note_failure("w1")
    assert guard.note_failure("w1")  # third failure trips the backoff
    decision = guard.can_analyze("w1", 0)
    assert decision.blocked and decision.reason == R_FAILURE_BACKOFF

    clock.advance(10.0)  # backoff base expired
    assert guard.can_analyze("w1", 0).allowed
    guard.note_success("w1")
    assert guard.consecutive_failures("w1") == 0


def test_cooldown_hysteresis_after_limit_trip(clock):
    pending = {"w1": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=counter,
        cooldown_seconds=30.0,
    )
    pending["w1"] = 1
    assert guard.can_analyze("w1", 0).blocked
    pending["w1"] = 0  # limit freed, but hysteresis holds for the cooldown
    decision = guard.can_analyze("w1", 0)
    assert decision.blocked and decision.reason == R_COOLDOWN
    clock.advance(30.0)
    assert guard.can_analyze("w1", 0).allowed


def test_manual_pause_and_resume(clock):
    guard = _guard(clock)
    guard.pause("w1")
    decision = guard.can_analyze("w1", 0)
    assert decision.blocked and decision.reason == R_MANUALLY_PAUSED
    guard.resume("w1")
    assert guard.can_analyze("w1", 0).allowed


def test_recover_after_resources_free(clock):
    pending = {"w1": 0}

    def counter(watch_id):
        return pending[watch_id]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=counter,
        cooldown_seconds=5.0,
    )
    pending["w1"] = 1
    assert guard.can_analyze("w1", 0).blocked
    pending["w1"] = 0
    assert not guard.recover("w1")  # cooldown still active
    clock.advance(5.0)
    assert guard.recover("w1")
    assert guard.resource_state("w1") == ResourceState.OK


def test_pending_counter_is_injectable_and_live(clock):
    pending = {"w1": 0}

    def pcounter(w):
        return pending[w]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    assert guard.can_analyze("w1", 0).allowed
    pending["w1"] = 1
    assert guard.can_analyze("w1", 0).blocked
    guard.set_pending_counter(lambda w: 0)
    assert guard.can_analyze("w1", 0).allowed


# ============================================================================
# Byte-exact file size limits
# ============================================================================

def test_size_limit_is_byte_exact_per_watch(clock):
    """The limit itself is allowed; limit + 1 byte is blocked (bytes, never
    a pre-truncated MB floor)."""
    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_file_size_mb=1)},
    )
    limit = 1 * 1024 * 1024
    assert guard.can_analyze("w1", limit).allowed
    decision = guard.can_analyze("w1", limit + 1)
    assert decision.blocked and decision.reason == R_WATCH_SIZE
    # a size between whole MBs must NOT be floored below the limit
    assert guard.can_analyze("w1", limit + 1024).blocked


def test_size_limit_is_byte_exact_global(clock):
    guard = _guard(
        clock,
        global_limits=WatchLimits(max_file_size_mb=1),
    )
    limit = 1 * 1024 * 1024
    assert guard.can_analyze("w9", limit).allowed
    decision = guard.can_analyze("w9", limit + 1)
    assert decision.blocked and decision.reason == R_GLOBAL_SIZE


# ============================================================================
# Global pending is the SUM across watches (explicit counter interface)
# ============================================================================

def test_global_pending_is_sum_across_watches(clock):
    pending = {"w1": 2, "w2": 1}

    def pcounter(w):
        return pending.get(w, 0)

    guard = _guard(
        clock,
        global_limits=WatchLimits(max_pending=3),
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    guard.set_global_pending_counter(lambda: 2 + 1)
    # a new watch's analysis must be blocked by the GLOBAL total, not by
    # its own (empty) pending count
    decision = guard.can_analyze("w3", 0)
    assert decision.blocked and decision.reason == R_GLOBAL_PENDING


def test_global_pending_sum_does_not_mask_per_watch_independence(clock):
    pending = {"w1": 2, "w2": 0}

    def pcounter(w):
        return pending.get(w, 0)

    guard = _guard(
        clock,
        global_limits=WatchLimits(max_pending=5),
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    guard.set_global_pending_counter(lambda: 2)
    assert guard.can_analyze("w1", 0).blocked  # per-watch limit, not global
    assert guard.can_analyze("w2", 0).allowed  # other watch unaffected


def test_global_pending_counter_fallback_sums_seen_watches(clock):
    """Without an explicit global counter, the guard sums the per-watch
    counter over every watch it has seen."""
    pending = {"w1": 2, "w2": 1}

    def pcounter(w):
        return pending.get(w, 0)

    guard = _guard(
        clock,
        global_limits=WatchLimits(max_pending=3),
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    # first sighting: only w1's pending counts (2 < 3) → allowed
    assert guard.can_analyze("w1", 0).allowed
    # now w2 is seen too: the total is 2 + 1 = 3 → the GLOBAL limit binds,
    # even though w2's own pending (1) would never block it alone
    decision = guard.can_analyze("w2", 0)
    assert decision.blocked and decision.reason == R_GLOBAL_PENDING


# ============================================================================
# Atomic try_acquire_analysis: check + slot under ONE lock
# ============================================================================

def test_try_acquire_analysis_single_slot(clock):
    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_concurrent_analysis=1)},
        cooldown_seconds=0,
    )
    assert guard.try_acquire_analysis("w1", 0).allowed
    assert guard.active_analyses("w1") == 1
    decision = guard.try_acquire_analysis("w1", 0)
    assert decision.blocked and decision.reason == R_WATCH_CONCURRENT
    assert guard.active_analyses("w1") == 1, "failed acquire must not count"
    guard.release_analysis("w1")
    assert guard.try_acquire_analysis("w1", 0).allowed
    guard.release_analysis("w1")


def test_try_acquire_analysis_failed_checks_do_not_increment(clock):
    pending = {"w1": 0}

    def pcounter(w):
        return pending[w]

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_pending=2, max_file_size_mb=1)},
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    pending["w1"] = 1  # below the per-watch pending limit
    assert guard.try_acquire_analysis("w1", 0).allowed
    guard.release_analysis("w1")
    pending["w1"] = 2  # at the per-watch pending limit
    decision = guard.try_acquire_analysis("w1", 0)
    assert decision.blocked and decision.reason == R_WATCH_PENDING
    pending["w1"] = 0
    decision = guard.try_acquire_analysis("w1", 1024 * 1024 + 1)
    assert decision.blocked and decision.reason == R_WATCH_SIZE
    assert guard.active_analyses("w1") == 0, (
        "blocked acquires must never increment the active count"
    )


def test_try_acquire_analysis_two_threads_one_slot(clock):
    """Two threads racing for a single slot: exactly one may succeed."""
    import threading

    guard = _guard(
        clock,
        per_watch_limits={"w1": WatchLimits(max_concurrent_analysis=1)},
        cooldown_seconds=0,
    )
    results: list[bool] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def racer():
        barrier.wait()
        decision = guard.try_acquire_analysis("w1", 0)
        with lock:
            results.append(decision.allowed)

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 1, f"exactly one slot, got {sum(results)} successes"
    guard.release_analysis("w1")
    assert guard.active_analyses("w1") == 0


def test_try_acquire_does_not_trip_cooldown_on_backoff(clock):
    """Backoff/manual blocks are decisions, not limit trips — they must not
    set the cooldown hysteresis."""
    guard = _guard(clock, max_consecutive_failures=1, cooldown_seconds=30.0)
    guard.note_failure("w1")  # trips backoff at threshold
    decision = guard.try_acquire_analysis("w1", 0)
    assert decision.blocked and decision.reason == R_FAILURE_BACKOFF
    clock.advance(30.0)  # past cooldown duration
    decision2 = guard.try_acquire_analysis("w1", 0)
    # the backoff itself still holds until its own expiry — the cooldown was
    # not extended by the backoff block
    clock.advance(60.0)  # past the backoff base
    assert guard.try_acquire_analysis("w1", 0).allowed


def test_acquire_analysis_api_removed():
    """The unconditional acquire is gone — only the atomic check+acquire
    exists, so no caller can bypass the limits."""
    guard = WatchResourceGuard()
    assert not hasattr(guard, "acquire_analysis")


# ============================================================================
# Pending contributor registry: multiple pipelines aggregate, never override
# ============================================================================

def _register_source(guard, source_id, per_watch, global_count):
    guard.register_pending_source(
        source_id,
        per_watch_counter=lambda wid: per_watch.get(wid, 0),
        global_counter=lambda: global_count,
    )


def test_pending_sources_sum_per_watch_counts():
    guard = WatchResourceGuard()
    _register_source(guard, "review", {"w1": 1}, global_count=1)
    _register_source(guard, "auto", {"w1": 1}, global_count=1)
    # per-watch pending = review(1) + auto(1)
    assert guard.pending_count("w1") == 2
    assert guard.global_pending_count() == 2


def test_pending_sources_distinct_watches_global_sum():
    guard = WatchResourceGuard()
    _register_source(guard, "review", {"w1": 2}, global_count=2)
    _register_source(guard, "auto", {"w2": 1}, global_count=1)
    assert guard.pending_count("w1") == 2
    assert guard.pending_count("w2") == 1
    assert guard.pending_count("w3") == 0
    assert guard.global_pending_count() == 3


def test_pending_sources_registration_order_irrelevant():
    per = {"w1": 1}
    glob = 1

    def reg(guard, first, second):
        guard.register_pending_source(
            first, per_watch_counter=lambda wid: per.get(wid, 0),
            global_counter=lambda: glob)
        guard.register_pending_source(
            second, per_watch_counter=lambda wid: per.get(wid, 0),
            global_counter=lambda: glob)

    g1 = WatchResourceGuard()
    reg(g1, "review", "auto")
    g2 = WatchResourceGuard()
    reg(g2, "auto", "review")
    assert g1.pending_count("w1") == g2.pending_count("w1") == 2
    assert g1.global_pending_count() == g2.global_pending_count() == 2


def test_pending_sources_single_source_unchanged():
    guard = WatchResourceGuard()
    _register_source(guard, "review", {"w1": 1}, global_count=1)
    assert guard.pending_count("w1") == 1
    assert guard.global_pending_count() == 1
    assert guard.can_analyze("w2", 0).allowed


def test_pending_sources_duplicate_registration_replaces():
    """Re-registering the same source_id REPLACES that source — it must
    never double-count."""
    guard = WatchResourceGuard()
    _register_source(guard, "review", {"w1": 1}, global_count=1)
    _register_source(guard, "review", {"w1": 2}, global_count=2)
    assert guard.pending_count("w1") == 2, "duplicate id must replace, not add"
    assert guard.global_pending_count() == 2


def test_pending_sources_unregister_removes_contribution():
    guard = WatchResourceGuard()
    _register_source(guard, "review", {"w1": 1}, global_count=1)
    _register_source(guard, "auto", {"w1": 1}, global_count=1)
    assert guard.pending_count("w1") == 2
    guard.unregister_pending_source("review")
    assert guard.pending_count("w1") == 1
    assert guard.global_pending_count() == 1


def test_pending_sources_limits_use_merged_counts():
    """Global and per-watch limits must block using the MERGED totals."""
    pending = {"w1": 2, "w2": 1}

    def pcounter(w):
        return pending.get(w, 0)

    guard = WatchResourceGuard(
        global_limits=WatchLimits(max_pending=3),
        per_watch_limits={"w1": WatchLimits(max_pending=1)},
        pending_counter=pcounter,
        cooldown_seconds=0,
    )
    guard.register_pending_source(
        "review", per_watch_counter=pcounter, global_counter=lambda: 0)
    guard.register_pending_source(
        "auto", per_watch_counter=lambda w: 0, global_counter=lambda: 3)
    # per-watch: legacy(2) + review(2) + auto(0) = 4 ≥ 1 → blocked
    assert guard.can_analyze("w1", 0).blocked
    # global: review(0) + auto(3) = 3 ≥ 3 → w2 also blocked
    decision = guard.can_analyze("w2", 0)
    assert decision.blocked and decision.reason == R_GLOBAL_PENDING


# ============================================================================
# No monetary concepts anywhere
# ============================================================================

def test_guard_has_no_monetary_words():
    import inspect
    import re
    from src.core import watch_resource_guard as module
    source = inspect.getsource(module)
    # word-boundary match: "concurrency" legitimately contains "currency" as
    # a substring — the monetary CONCEPTS are what must be absent
    pattern = re.compile(
        r"\b(价格|费用|预算|币种|金额|price|cost|currency|budget|monthly|"
        r"spending|fee|billing|allowance|quota|BudgetPaused)\b",
        re.IGNORECASE,
    )
    matches = pattern.findall(source)
    assert not matches, f"monetary concept leaked into the guard: {matches}"
