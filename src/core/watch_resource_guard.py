"""Local queue, concurrency, file-size and failure protection for Watch.

Owned receipts admit bounded input independently of execution permission.
External contributors are sampled outside the lock; only the owned ledgers
and primitive policy state are committed under it. Global limits apply first.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

R_GLOBAL_PENDING = "global_pending_limit"
R_GLOBAL_CONCURRENT = "global_concurrency_limit"
R_GLOBAL_SIZE = "global_size_limit"
R_WATCH_PENDING = "watch_pending_limit"
R_WATCH_CONCURRENT = "watch_concurrency_limit"
R_WATCH_SIZE = "watch_size_limit"
R_FAILURE_BACKOFF = "failure_backoff"
R_COOLDOWN = "cooldown"
R_MANUALLY_PAUSED = "manually_paused"
R_RESOURCE_UNAVAILABLE = "resource_unavailable"
R_INVALID_OWNER = "invalid_resource_owner"

_MB = 1024 * 1024
_UNAVAILABLE = object()
_OBSERVATION_ATTEMPTS = 3


def _valid_id(value: object) -> bool:
    return type(value) is str and len(value) > 0


def _valid_size(value: object) -> bool:
    return type(value) is int and value >= 0


def _finite_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _require_id(value: object) -> None:
    if not _valid_id(value):
        raise ValueError(R_RESOURCE_UNAVAILABLE)


def _require_callback(value: object) -> None:
    if not callable(value):
        raise ValueError(R_RESOURCE_UNAVAILABLE)


class ResourceState(str, Enum):
    OK = "ok"
    PAUSED = "paused"


@dataclass(frozen=True)
class WatchLimits:
    """Optional positive integer limits on local resources."""

    max_pending: int | None = None
    max_concurrent_analysis: int | None = None
    max_file_size_mb: int | None = None

    def __post_init__(self) -> None:
        for value in (self.max_pending, self.max_concurrent_analysis, self.max_file_size_mb):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(R_RESOURCE_UNAVAILABLE)


def _require_limits(value: object) -> None:
    if type(value) is not WatchLimits:
        raise ValueError(R_RESOURCE_UNAVAILABLE)
    value.__post_init__()


@dataclass(frozen=True)
class ResourceDecision:
    allowed: bool
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed


class WatchResourceGuard:
    """Thread-safe local resource gate with legacy and owned slot accounting.

    Counter samples do not freeze arbitrary producer queues. The receipts
    account for this guard's own concurrent reservations exactly.
    """

    def __init__(
        self,
        *,
        global_limits: WatchLimits | None = None,
        per_watch_limits: dict[str, WatchLimits] | None = None,
        pending_counter: Callable[[str], int] | None = None,
        failure_backoff_base: float = 60.0,
        max_consecutive_failures: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if global_limits is not None:
            _require_limits(global_limits)
        if per_watch_limits is not None:
            if type(per_watch_limits) is not dict:
                raise ValueError(R_RESOURCE_UNAVAILABLE)
            for watch_id, limits in per_watch_limits.items():
                _require_id(watch_id)
                _require_limits(limits)
        if not _finite_number(failure_backoff_base) or not _finite_number(cooldown_seconds):
            raise ValueError(R_RESOURCE_UNAVAILABLE)
        if type(max_consecutive_failures) is not int or max_consecutive_failures <= 0:
            raise ValueError(R_RESOURCE_UNAVAILABLE)
        if pending_counter is not None:
            _require_callback(pending_counter)
        if clock is not None:
            _require_callback(clock)

        self._global = global_limits if global_limits is not None else WatchLimits()
        self._per_watch = dict(per_watch_limits) if per_watch_limits is not None else {}
        self._pending_counter = pending_counter if pending_counter is not None else lambda _: 0
        self._global_pending_counter: Callable[[], int] | None = None
        self._pending_sources: dict[str, tuple[Callable[[str], int], Callable[[], int]]] = {}
        self._backoff_base = max(1.0, failure_backoff_base)
        self._max_failures = max_consecutive_failures
        self._cooldown = max(0.0, cooldown_seconds)
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._revision = 0
        self._active_analyses: dict[str, int] = {}
        self._pending_owners: dict[object, str] = {}
        self._pending_sizes: dict[object, int] = {}
        self._execution_owners: dict[object, object] = {}
        self._pending_executions: dict[object, object] = {}
        self._seen_watches: set[str] = set()
        self._consecutive_failures: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._global_cooldown_until = 0.0
        self._manually_paused: set[str] = set()

    # Registry and limits contain only validated primitive keys and values.

    def set_watch_limits(self, watch_id: str, limits: WatchLimits) -> None:
        _require_id(watch_id)
        _require_limits(limits)
        with self._lock:
            self._per_watch[watch_id] = limits
            self._revision += 1

    def set_pending_counter(self, counter: Callable[[str], int]) -> None:
        _require_callback(counter)
        with self._lock:
            previous = self._pending_counter
            self._pending_counter = counter
            self._revision += 1
        del previous  # Caller-defined finalizers must also run outside the lock.

    def set_global_pending_counter(self, counter: Callable[[], int]) -> None:
        _require_callback(counter)
        with self._lock:
            previous = self._global_pending_counter
            self._global_pending_counter = counter
            self._revision += 1
        del previous

    def register_pending_source(
        self,
        source_id: str,
        *,
        per_watch_counter: Callable[[str], int],
        global_counter: Callable[[], int],
    ) -> None:
        """Add or replace one source; distinct registered sources are summed."""
        _require_id(source_id)
        _require_callback(per_watch_counter)
        _require_callback(global_counter)
        with self._lock:
            previous = self._pending_sources.get(source_id)
            self._pending_sources[source_id] = (per_watch_counter, global_counter)
            self._revision += 1
        del previous

    def unregister_pending_source(self, source_id: str) -> None:
        _require_id(source_id)
        with self._lock:
            previous = self._pending_sources.pop(source_id, None)
            self._revision += 1
        del previous

    def _observed(self, watch_id, commit, *, counts="all", read_clock=True):
        """Sample untrusted callbacks outside the lock, then commit primitives.

        Registry/limit changes and newly seen watches invalidate observations.
        Owned ledger changes need no retry: they are read at the actual commit.
        ``commit`` is an internal closure, never a caller-supplied callback.
        """
        for _ in range(_OBSERVATION_ATTEMPTS):
            with self._lock:
                if counts == "all" and watch_id not in self._seen_watches:
                    self._seen_watches.add(watch_id)
                    self._revision += 1
                revision = self._revision
                legacy = self._pending_counter
                explicit_global = self._global_pending_counter
                sources = tuple(self._pending_sources.values())
                seen = tuple(self._seen_watches)
                clock = self._clock
            try:
                now = clock() if read_clock else 0
                if not _finite_number(now):
                    return _UNAVAILABLE
                pending = total = 0
                legacy_samples = {}

                def count(callback, *args):
                    value = callback(*args)
                    if not _valid_size(value):
                        raise ValueError(R_RESOURCE_UNAVAILABLE)
                    return value

                if counts in ("all", "watch"):
                    legacy_samples[watch_id] = count(legacy, watch_id)
                    pending = legacy_samples[watch_id] + sum(count(per, watch_id) for per, _ in sources)
                if counts in ("all", "global"):
                    if sources or explicit_global is not None:
                        total = sum(count(glob) for _, glob in sources)
                        if explicit_global is not None:
                            total += count(explicit_global)
                    else:
                        for seen_id in seen:
                            if seen_id not in legacy_samples:
                                legacy_samples[seen_id] = count(legacy, seen_id)
                        total = sum(legacy_samples.values())
            except BaseException:
                return _UNAVAILABLE
            with self._lock:
                if revision == self._revision:
                    return commit(pending, total, now)
            del legacy, explicit_global, sources, clock
        return _UNAVAILABLE

    def _owned_pending_locked(self, watch_id: str) -> int:
        return sum(owner == watch_id for owner in self._pending_owners.values())

    def _active_locked(self, watch_id: str) -> int:
        return self._active_analyses.get(watch_id, 0) + sum(
            self._pending_owners[pending] == watch_id
            for pending in self._execution_owners.values()
        )

    def pending_count(self, watch_id: str) -> int:
        _require_id(watch_id)
        result = self._observed(watch_id, lambda pending, total, now: pending + self._owned_pending_locked(watch_id), counts="watch", read_clock=False)
        if result is _UNAVAILABLE:
            raise ValueError(R_RESOURCE_UNAVAILABLE)
        return result

    def global_pending_count(self) -> int:
        result = self._observed(None, lambda pending, total, now: total + len(self._pending_owners), counts="global", read_clock=False)
        if result is _UNAVAILABLE:
            raise ValueError(R_RESOURCE_UNAVAILABLE)
        return result

    # Owned admission and execution: exact object identity, never supplied data.

    def reserve_pending(self, watch_id: str, size_bytes: int):
        if not _valid_id(watch_id) or not _valid_size(size_bytes):
            return ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None

        def commit(pending, total, now):
            decision = self._decide_locked(watch_id, size_bytes, pending, total, now, admission=True)
            if not decision.allowed:
                return decision, None
            token = object()
            self._pending_owners[token] = watch_id
            self._pending_sizes[token] = size_bytes
            return decision, token

        result = self._observed(watch_id, commit)
        return (ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None) if result is _UNAVAILABLE else result

    def release_pending(self, pending_token) -> bool:
        if type(pending_token) is not object:
            return False
        with self._lock:
            if pending_token not in self._pending_owners or pending_token in self._pending_executions:
                return False
            del self._pending_owners[pending_token]
            del self._pending_sizes[pending_token]
            return True

    def _owned_decision(self, pending_token, size_bytes, *, acquire=False, recovery=False):
        if type(pending_token) is not object:
            return ResourceDecision(False, R_INVALID_OWNER), None
        with self._lock:
            watch_id = self._pending_owners.get(pending_token)
            if watch_id is None or pending_token in self._pending_executions:
                return ResourceDecision(False, R_INVALID_OWNER), None
            if recovery:
                size_bytes = self._pending_sizes[pending_token]
        if not _valid_size(size_bytes):
            return ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None

        def commit(pending, total, now):
            if pending_token not in self._pending_owners or pending_token in self._pending_executions:
                return ResourceDecision(False, R_INVALID_OWNER), None
            decision = self._decide_locked(watch_id, size_bytes, pending, total, now, owned=True)
            if not decision.allowed:
                return decision, None
            if acquire:
                execution = object()
                self._execution_owners[execution] = pending_token
                self._pending_executions[pending_token] = execution
                return decision, execution
            if recovery:
                self._clear_recovered_locked(watch_id)
            return decision, None

        result = self._observed(watch_id, commit)
        return (ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None) if result is _UNAVAILABLE else result

    def try_acquire_owned_analysis(self, pending_token, size_bytes: int):
        return self._owned_decision(pending_token, size_bytes, acquire=True)

    def can_acquire_owned_analysis(self, pending_token, size_bytes: int) -> ResourceDecision:
        return self._owned_decision(pending_token, size_bytes)[0]

    def release_owned_analysis(self, execution_token) -> bool:
        if type(execution_token) is not object:
            return False
        with self._lock:
            pending = self._execution_owners.pop(execution_token, None)
            if pending is None:
                return False
            del self._pending_executions[pending]
            return True

    def recover_owned(self, pending_token) -> bool:
        return self._owned_decision(pending_token, 0, recovery=True)[0].allowed

    # Legacy calls remain separate from the owned execution ledger.

    def _legacy_decision(self, watch_id, size_bytes, *, acquire=False, recovery=False):
        if not _valid_id(watch_id) or not _valid_size(size_bytes):
            return ResourceDecision(False, R_RESOURCE_UNAVAILABLE)

        def commit(pending, total, now):
            decision = self._decide_locked(watch_id, size_bytes, pending, total, now)
            if decision.allowed:
                if acquire:
                    self._active_analyses[watch_id] = self._active_analyses.get(watch_id, 0) + 1
                if recovery:
                    self._clear_recovered_locked(watch_id)
            return decision

        result = self._observed(watch_id, commit)
        return ResourceDecision(False, R_RESOURCE_UNAVAILABLE) if result is _UNAVAILABLE else result

    def try_acquire_analysis(self, watch_id: str, size_bytes: int) -> ResourceDecision:
        """Atomically check current policy and take one legacy slot."""
        return self._legacy_decision(watch_id, size_bytes, acquire=True)

    def can_analyze(self, watch_id: str, size_bytes: int) -> ResourceDecision:
        return self._legacy_decision(watch_id, size_bytes)

    def release_analysis(self, watch_id: str) -> None:
        _require_id(watch_id)
        with self._lock:
            current = self._active_analyses.get(watch_id, 0)
            if current > 1:
                self._active_analyses[watch_id] = current - 1
            else:
                self._active_analyses.pop(watch_id, None)

    def active_analyses(self, watch_id: str) -> int:
        _require_id(watch_id)
        with self._lock:
            return self._active_locked(watch_id)

    def note_failure(self, watch_id: str) -> bool:
        """Sample the clock safely; validate a deadline before publishing state."""
        if not _valid_id(watch_id):
            return False

        def commit(pending, total, now):
            count = self._consecutive_failures.get(watch_id, 0) + 1
            if count >= self._max_failures:
                try:
                    delay = self._backoff_base * (2 ** (count - self._max_failures))
                    deadline = now + delay
                except (OverflowError, ValueError):
                    raise ValueError(R_RESOURCE_UNAVAILABLE) from None
                if not _finite_number(delay) or not _finite_number(deadline):
                    raise ValueError(R_RESOURCE_UNAVAILABLE)
                deadline = max(self._backoff_until.get(watch_id, 0.0), deadline)
                self._backoff_until[watch_id] = deadline
            self._consecutive_failures[watch_id] = count
            return count >= self._max_failures

        result = self._observed(watch_id, commit, counts="none")
        return False if result is _UNAVAILABLE else result

    def note_success(self, watch_id: str) -> None:
        _require_id(watch_id)
        with self._lock:
            self._consecutive_failures.pop(watch_id, None)

    def consecutive_failures(self, watch_id: str) -> int:
        _require_id(watch_id)
        with self._lock:
            return self._consecutive_failures.get(watch_id, 0)

    def pause(self, watch_id: str) -> None:
        _require_id(watch_id)
        with self._lock:
            self._manually_paused.add(watch_id)

    def _clear_recovered_locked(self, watch_id: str) -> None:
        self._backoff_until.pop(watch_id, None)
        self._cooldown_until.pop(watch_id, None)
        self._consecutive_failures.pop(watch_id, None)

    def resume(self, watch_id: str) -> None:
        _require_id(watch_id)
        with self._lock:
            self._manually_paused.discard(watch_id)
            self._clear_recovered_locked(watch_id)

    def resource_state(self, watch_id: str) -> ResourceState:
        return ResourceState.OK if self.can_analyze(watch_id, 0).allowed else ResourceState.PAUSED

    def _trip_locked(self, watch_id, now, reason, *, global_trip=False):
        try:
            deadline = now + self._cooldown
        except OverflowError:
            return ResourceDecision(False, R_RESOURCE_UNAVAILABLE)
        if not _finite_number(deadline):
            return ResourceDecision(False, R_RESOURCE_UNAVAILABLE)
        if global_trip:
            self._global_cooldown_until = deadline
        else:
            self._cooldown_until[watch_id] = deadline
        return ResourceDecision(False, reason)

    def _decide_locked(self, watch_id, size_bytes, pending, total, now, *, admission=False, owned=False):
        """Evaluate sampled external counts plus current owned primitive state."""
        if not admission:
            if watch_id in self._manually_paused:
                return ResourceDecision(False, R_MANUALLY_PAUSED)
            if now < self._global_cooldown_until:
                return ResourceDecision(False, R_COOLDOWN)
            if now < self._backoff_until.get(watch_id, 0.0):
                return ResourceDecision(False, R_FAILURE_BACKOFF)
            if now < self._cooldown_until.get(watch_id, 0.0):
                return ResourceDecision(False, R_COOLDOWN)

        pending += self._owned_pending_locked(watch_id)
        total += len(self._pending_owners)
        active = self._active_locked(watch_id)
        active_global = sum(self._active_analyses.values()) + len(self._execution_owners)

        def pending_full(value, limit):
            return limit is not None and (value > limit if owned else value >= limit)

        if pending_full(total, self._global.max_pending):
            return self._trip_locked(watch_id, now, R_GLOBAL_PENDING, global_trip=True)
        if not admission and self._global.max_concurrent_analysis is not None and active_global >= self._global.max_concurrent_analysis:
            return self._trip_locked(watch_id, now, R_GLOBAL_CONCURRENT, global_trip=True)
        if self._global.max_file_size_mb is not None and size_bytes > self._global.max_file_size_mb * _MB:
            return ResourceDecision(False, R_GLOBAL_SIZE)

        limits = self._per_watch.get(watch_id, WatchLimits())
        if pending_full(pending, limits.max_pending):
            return self._trip_locked(watch_id, now, R_WATCH_PENDING)
        if not admission and limits.max_concurrent_analysis is not None and active >= limits.max_concurrent_analysis:
            return self._trip_locked(watch_id, now, R_WATCH_CONCURRENT)
        if limits.max_file_size_mb is not None and size_bytes > limits.max_file_size_mb * _MB:
            return ResourceDecision(False, R_WATCH_SIZE)
        return ResourceDecision(True)

    def recover(self, watch_id: str) -> bool:
        """Check current protection before retiring expired per-watch state."""
        return self._legacy_decision(watch_id, 0, recovery=True).allowed
