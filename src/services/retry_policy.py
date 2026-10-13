"""Bounded retry primitives with deterministic tests and no provider switching."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import Enum
from threading import Event
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional


class ErrorCategory(str, Enum):
    AUTH = "auth"
    PERMISSION = "permission"
    MODEL_NOT_FOUND = "model_not_found"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    MALFORMED_RESPONSE = "malformed_response"
    CANCELLED = "cancelled"
    BUDGET_BLOCKED = "budget_blocked"
    INVALID_REQUEST = "invalid_request"


NON_RETRYABLE = frozenset(
    {
        ErrorCategory.AUTH,
        ErrorCategory.PERMISSION,
        ErrorCategory.MODEL_NOT_FOUND,
        ErrorCategory.INVALID_REQUEST,
        ErrorCategory.BUDGET_BLOCKED,
        ErrorCategory.CANCELLED,
    }
)
RETRYABLE = frozenset(
    {
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TIMEOUT,
        ErrorCategory.NETWORK,
        ErrorCategory.SERVER,
        ErrorCategory.MALFORMED_RESPONSE,
    }
)


@dataclass(frozen=True, slots=True)
class ClassifiedProviderError:
    category: ErrorCategory
    retry_after: str | float | int | None = None
    status_code: int | None = None
    message: str = ""
    usage: Mapping[str, int | float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))


@dataclass(frozen=True, slots=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float
    reason: str
    used_retry_after: bool = False


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_number: int
    success: bool
    category: ErrorCategory | None
    delay_before_next: float
    error_type: str = ""
    error_message: str = ""
    usage: Mapping[str, int | float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))


@dataclass(frozen=True, slots=True)
class RetryExecutionResult:
    success: bool
    value: Any
    attempts: tuple[AttemptRecord, ...]
    final_error: Exception | None
    final_category: ErrorCategory | None
    cancelled: bool = False

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)


class RetryPolicy:
    """Pure retry decision logic.

    ``max_retries`` counts additional attempts after the initial call.  The
    policy decides only delay and termination; it never selects another model
    or provider.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter_ratio: float = 0.0,
        malformed_response_max_retries: int | None = None,
        clock: Callable[[], float] = time.time,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        malformed_limit = (
            min(1, max_retries)
            if malformed_response_max_retries is None
            else malformed_response_max_retries
        )
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if base_delay < 0 or max_delay < 0 or backoff_factor < 1:
            raise ValueError("Retry delays and backoff configuration are invalid")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")
        if malformed_limit < 0 or malformed_limit > max_retries:
            raise ValueError(
                "malformed_response_max_retries must be within max_retries"
            )
        self.max_retries = max_retries
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.backoff_factor = float(backoff_factor)
        self.jitter_ratio = float(jitter_ratio)
        self.malformed_response_max_retries = malformed_limit
        self._clock = clock
        self._random_source = random_source

    def decide(
        self, failed_attempt_number: int, error: ClassifiedProviderError
    ) -> RetryDecision:
        if failed_attempt_number < 1:
            raise ValueError("failed_attempt_number is one-based")
        if error.category not in RETRYABLE:
            return RetryDecision(
                False, 0.0, f"non-retryable:{error.category.value}"
            )

        retries_already_used = failed_attempt_number - 1
        retry_limit = self.max_retries
        if error.category is ErrorCategory.MALFORMED_RESPONSE:
            retry_limit = self.malformed_response_max_retries
        if retries_already_used >= retry_limit:
            return RetryDecision(False, 0.0, "retry-limit-reached")

        retry_after = self._parse_retry_after(error.retry_after)
        if retry_after is not None:
            return RetryDecision(
                True,
                min(retry_after, self.max_delay),
                "retry-after",
                used_retry_after=True,
            )

        exponential = self.base_delay * (
            self.backoff_factor ** retries_already_used
        )
        jitter_multiplier = 1.0 + self.jitter_ratio * (
            2.0 * self._random_source() - 1.0
        )
        delay = max(0.0, min(exponential * jitter_multiplier, self.max_delay))
        return RetryDecision(True, delay, "exponential-backoff")

    def _parse_retry_after(self, value: str | float | int | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if value >= 0 else None
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        try:
            seconds = float(candidate)
            return seconds if seconds >= 0 else None
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(candidate)
            if retry_at.tzinfo is None:
                return None
            remaining = retry_at.timestamp() - self._clock()
            return max(0.0, remaining)
        except (TypeError, ValueError, OverflowError):
            return None


class RetryExecutor:
    """Execute one immutable operation repeatedly under a ``RetryPolicy``.

    Without a cancellation Event, preserve the injected sleeper contract.
    Event-aware retries use Event.wait, or an injected ``waiter(event, delay)``
    with the same timeout/boolean semantics for deterministic execution.
    """

    def __init__(
        self,
        policy: RetryPolicy,
        sleeper: Callable[[float], None] = time.sleep,
        *,
        waiter: Callable[[Event, float], bool] | None = None,
    ) -> None:
        self._policy = policy
        self._sleeper = sleeper
        self._waiter = waiter

    def _wait_before_retry(
        self, delay: float, event: Event | None, is_cancelled: Callable[[], bool]
    ) -> None:
        if event is None:
            self._sleeper(delay)
            return
        # The generation Event wakes immediately. Bounded slices also observe
        # task/caller cancellation without holding any authority lock. An
        # injected waiter follows Event.wait's timeout/boolean contract.
        remaining = delay
        while remaining > 0 and not is_cancelled():
            interval = min(remaining, 0.1)
            signalled = (
                self._waiter(event, interval)
                if self._waiter is not None else event.wait(interval)
            )
            if signalled:
                return
            remaining -= interval

    def execute(
        self,
        operation: Callable[[], Any],
        error_categorizer: Callable[[Exception], ClassifiedProviderError],
        cancellation_token: Optional[Callable[[], bool]] = None,
        usage_extractor: Optional[
            Callable[[Any], Mapping[str, int | float]]
        ] = None,
        *,
        cancellation_event: Event | None = None,
    ) -> RetryExecutionResult:
        records: list[AttemptRecord] = []

        def is_cancelled() -> bool:
            return bool(
                (cancellation_token is not None and cancellation_token())
                or (cancellation_event is not None and cancellation_event.is_set())
            )

        if is_cancelled():
            return RetryExecutionResult(
                success=False,
                value=None,
                attempts=(),
                final_error=None,
                final_category=ErrorCategory.CANCELLED,
                cancelled=True,
            )

        while True:
            if is_cancelled():
                return RetryExecutionResult(
                    success=False,
                    value=None,
                    attempts=tuple(records),
                    final_error=None,
                    final_category=ErrorCategory.CANCELLED,
                    cancelled=True,
                )
            attempt_number = len(records) + 1
            try:
                value = operation()
            except Exception as error:
                classified = error_categorizer(error)
                if not isinstance(classified, ClassifiedProviderError):
                    raise TypeError(
                        "error_categorizer must return ClassifiedProviderError"
                    )
                decision = self._policy.decide(attempt_number, classified)

                if is_cancelled():
                    records.append(
                        AttemptRecord(
                            attempt_number,
                            False,
                            classified.category,
                            0.0,
                            type(error).__name__,
                            str(error),
                            classified.usage,
                        )
                    )
                    return RetryExecutionResult(
                        success=False,
                        value=None,
                        attempts=tuple(records),
                        final_error=error,
                        final_category=ErrorCategory.CANCELLED,
                        cancelled=True,
                    )

                if not decision.should_retry:
                    records.append(
                        AttemptRecord(
                            attempt_number,
                            False,
                            classified.category,
                            0.0,
                            type(error).__name__,
                            str(error),
                            classified.usage,
                        )
                    )
                    return RetryExecutionResult(
                        success=False,
                        value=None,
                        attempts=tuple(records),
                        final_error=error,
                        final_category=classified.category,
                        cancelled=classified.category is ErrorCategory.CANCELLED,
                    )

                records.append(
                    AttemptRecord(
                        attempt_number,
                        False,
                        classified.category,
                        decision.delay_seconds,
                        type(error).__name__,
                        str(error),
                        classified.usage,
                    )
                )
                self._wait_before_retry(
                    decision.delay_seconds, cancellation_event, is_cancelled
                )
                continue

            if usage_extractor is not None:
                success_usage = usage_extractor(value)
            else:
                success_usage = getattr(value, "usage", {})
            if not isinstance(success_usage, Mapping):
                raise TypeError("usage_extractor must return a mapping")
            records.append(
                AttemptRecord(
                    attempt_number, True, None, 0.0, usage=success_usage
                )
            )
            if is_cancelled():
                # Preserve factual successful-attempt usage, but a completed
                # response does not authorize publication after cancellation.
                return RetryExecutionResult(
                    success=False,
                    value=None,
                    attempts=tuple(records),
                    final_error=None,
                    final_category=ErrorCategory.CANCELLED,
                    cancelled=True,
                )
            return RetryExecutionResult(
                success=True,
                value=value,
                attempts=tuple(records),
                final_error=None,
                final_category=None,
            )


def classify_http_status(status_code: int) -> ErrorCategory:
    """Classify HTTP status without treating unknown statuses as retryable."""
    if status_code == 401:
        return ErrorCategory.AUTH
    if status_code == 403:
        return ErrorCategory.PERMISSION
    if status_code == 404:
        return ErrorCategory.MODEL_NOT_FOUND
    if status_code in (408, 504):
        return ErrorCategory.TIMEOUT
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if 500 <= status_code <= 599:
        return ErrorCategory.SERVER
    return ErrorCategory.INVALID_REQUEST
