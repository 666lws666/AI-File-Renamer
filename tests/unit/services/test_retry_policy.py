"""M3 Task 3: bounded, deterministic retry policy and executor tests."""
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest

from src.services.retry_policy import (
    ClassifiedProviderError,
    ErrorCategory,
    RetryExecutor,
    RetryPolicy,
    classify_http_status,
)


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.AUTH,
        ErrorCategory.PERMISSION,
        ErrorCategory.MODEL_NOT_FOUND,
        ErrorCategory.INVALID_REQUEST,
        ErrorCategory.BUDGET_BLOCKED,
        ErrorCategory.CANCELLED,
    ],
)
def test_non_retryable_categories(category):
    decision = RetryPolicy().decide(1, ClassifiedProviderError(category))
    assert decision.should_retry is False
    assert decision.delay_seconds == 0


@pytest.mark.parametrize(
    "category",
    [
        ErrorCategory.RATE_LIMIT,
        ErrorCategory.TIMEOUT,
        ErrorCategory.NETWORK,
        ErrorCategory.SERVER,
        ErrorCategory.MALFORMED_RESPONSE,
    ],
)
def test_retryable_categories(category):
    decision = RetryPolicy().decide(1, ClassifiedProviderError(category))
    assert decision.should_retry is True


def test_max_retries_means_extra_attempts_after_initial():
    policy = RetryPolicy(max_retries=2)
    assert policy.decide(1, ClassifiedProviderError(ErrorCategory.SERVER)).should_retry
    assert policy.decide(2, ClassifiedProviderError(ErrorCategory.SERVER)).should_retry
    assert not policy.decide(3, ClassifiedProviderError(ErrorCategory.SERVER)).should_retry


def test_malformed_response_has_smaller_retry_limit():
    policy = RetryPolicy(max_retries=4, malformed_response_max_retries=1)
    error = ClassifiedProviderError(ErrorCategory.MALFORMED_RESPONSE)
    assert policy.decide(1, error).should_retry
    assert not policy.decide(2, error).should_retry


def test_retry_after_numeric_is_bounded():
    policy = RetryPolicy(max_delay=10)
    decision = policy.decide(
        1, ClassifiedProviderError(ErrorCategory.RATE_LIMIT, retry_after="999")
    )
    assert decision.delay_seconds == 10
    assert decision.used_retry_after is True


def test_retry_after_http_date_uses_injected_clock():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    retry_at = datetime(2026, 7, 29, 12, 0, 7, tzinfo=timezone.utc)
    policy = RetryPolicy(clock=lambda: now.timestamp(), max_delay=30)
    decision = policy.decide(
        1,
        ClassifiedProviderError(
            ErrorCategory.RATE_LIMIT,
            retry_after=format_datetime(retry_at, usegmt=True),
        ),
    )
    assert decision.delay_seconds == 7
    assert decision.used_retry_after is True


def test_malformed_retry_after_falls_back_to_exponential_delay():
    policy = RetryPolicy(base_delay=2, random_source=lambda: 0.5)
    decision = policy.decide(
        2,
        ClassifiedProviderError(ErrorCategory.RATE_LIMIT, retry_after="not-a-delay"),
    )
    assert decision.delay_seconds == 4
    assert decision.used_retry_after is False


def test_jitter_is_deterministic_when_random_is_injected():
    policy = RetryPolicy(base_delay=10, jitter_ratio=0.2, random_source=lambda: 1.0)
    decision = policy.decide(1, ClassifiedProviderError(ErrorCategory.NETWORK))
    assert decision.delay_seconds == 12


def test_http_status_classification_is_fail_closed():
    assert classify_http_status(400) is ErrorCategory.INVALID_REQUEST
    assert classify_http_status(401) is ErrorCategory.AUTH
    assert classify_http_status(403) is ErrorCategory.PERMISSION
    assert classify_http_status(404) is ErrorCategory.MODEL_NOT_FOUND
    assert classify_http_status(429) is ErrorCategory.RATE_LIMIT
    assert classify_http_status(500) is ErrorCategory.SERVER
    assert classify_http_status(599) is ErrorCategory.SERVER
    assert classify_http_status(302) is ErrorCategory.INVALID_REQUEST


def test_success_on_first_attempt_has_one_record_and_no_sleep():
    sleeps = []
    executor = RetryExecutor(RetryPolicy(), sleeper=sleeps.append)
    result = executor.execute(
        lambda: "ok", lambda exc: ClassifiedProviderError(ErrorCategory.SERVER)
    )
    assert result.success is True
    assert result.value == "ok"
    assert result.total_attempts == 1
    assert len(result.attempts) == 1
    assert result.attempts[0].success is True
    assert sleeps == []


def test_retry_executor_records_each_attempt_and_preserves_final_exception():
    calls = []
    sleeps = []
    terminal_error = RuntimeError("terminal")

    def operation():
        calls.append("same-provider/same-model")
        if len(calls) == 1:
            raise TimeoutError("first")
        raise terminal_error

    executor = RetryExecutor(
        RetryPolicy(max_retries=1, base_delay=0.25, random_source=lambda: 0.5),
        sleeper=sleeps.append,
    )
    result = executor.execute(
        operation,
        lambda exc: ClassifiedProviderError(ErrorCategory.TIMEOUT),
    )
    assert result.success is False
    assert result.total_attempts == 2
    assert result.final_error is terminal_error
    assert result.final_category is ErrorCategory.TIMEOUT
    assert [record.attempt_number for record in result.attempts] == [1, 2]
    assert [record.success for record in result.attempts] == [False, False]
    assert result.attempts[0].delay_before_next == 0.25
    assert result.attempts[1].delay_before_next == 0
    assert sleeps == [0.25]
    assert calls == ["same-provider/same-model", "same-provider/same-model"]


def test_usage_is_recorded_for_each_failed_and_successful_attempt():
    call_count = 0

    def operation():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("retry")
        return {"value": "ok", "usage": {"input_tokens": 3, "output_tokens": 2}}

    executor = RetryExecutor(
        RetryPolicy(max_retries=1, base_delay=0), sleeper=lambda delay: None
    )
    result = executor.execute(
        operation,
        lambda exc: ClassifiedProviderError(
            ErrorCategory.TIMEOUT, usage={"input_tokens": 1}
        ),
        usage_extractor=lambda value: value["usage"],
    )

    assert result.success is True
    assert result.attempts[0].usage == {"input_tokens": 1}
    assert result.attempts[1].usage == {"input_tokens": 3, "output_tokens": 2}


def test_cancellation_before_initial_attempt_calls_nothing():
    calls = []
    executor = RetryExecutor(RetryPolicy(), sleeper=lambda delay: calls.append(delay))
    result = executor.execute(
        lambda: calls.append("operation"),
        lambda exc: ClassifiedProviderError(ErrorCategory.SERVER),
        cancellation_token=lambda: True,
    )
    assert result.cancelled is True
    assert result.total_attempts == 0
    assert result.final_category is ErrorCategory.CANCELLED
    assert calls == []


def test_cancellation_after_failure_stops_before_sleep_and_retry():
    call_count = 0
    sleeps = []

    def operation():
        nonlocal call_count
        call_count += 1
        raise OSError("network")

    executor = RetryExecutor(RetryPolicy(max_retries=5), sleeper=sleeps.append)
    result = executor.execute(
        operation,
        lambda exc: ClassifiedProviderError(ErrorCategory.NETWORK),
        cancellation_token=lambda: call_count >= 1,
    )
    assert result.cancelled is True
    assert result.total_attempts == 1
    assert result.final_category is ErrorCategory.CANCELLED
    assert isinstance(result.final_error, OSError)
    assert sleeps == []


def test_cancellation_during_backoff_stops_before_next_operation():
    calls = []
    cancelled = False

    def operation():
        calls.append("operation")
        raise OSError("network")

    def sleeper(_delay):
        nonlocal cancelled
        cancelled = True

    executor = RetryExecutor(RetryPolicy(max_retries=2, base_delay=0.1), sleeper=sleeper)
    result = executor.execute(
        operation,
        lambda exc: ClassifiedProviderError(ErrorCategory.NETWORK),
        cancellation_token=lambda: cancelled,
    )
    assert result.cancelled is True
    assert calls == ["operation"]
    assert result.total_attempts == 1


def test_invalid_policy_configuration_is_rejected():
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=-1)
    with pytest.raises(ValueError):
        RetryPolicy(jitter_ratio=1.5)
    with pytest.raises(ValueError):
        RetryPolicy(malformed_response_max_retries=4, max_retries=2)


def test_generation_event_wakes_real_backoff_without_second_operation():
    from inspect import signature
    from threading import Event, Thread

    assert "cancellation_event" in signature(RetryExecutor.execute).parameters
    cancelled, entered_wait = Event(), Event()
    calls, results = [], []
    real_wait = cancelled.wait

    def observed_wait(delay):
        entered_wait.set()
        return real_wait(delay)

    cancelled.wait = observed_wait

    def operation():
        calls.append(1)
        raise TimeoutError("synthetic")

    executor = RetryExecutor(RetryPolicy(base_delay=60))
    worker = Thread(target=lambda: results.append(executor.execute(
        operation, lambda exc: ClassifiedProviderError(ErrorCategory.TIMEOUT),
        cancellation_event=cancelled)), daemon=True)
    worker.start()
    try:
        assert entered_wait.wait(5)
        cancelled.set()
        worker.join(5)
        assert not worker.is_alive()
    finally:
        cancelled.set()
        worker.join(5)
    assert calls == [1]
    assert results[0].cancelled


def test_event_backoff_polls_separate_callback_in_bounded_slices():
    from threading import Event

    event = Event()
    calls, waits = [], []
    cancelled = False

    def operation():
        calls.append(1)
        raise TimeoutError("synthetic")

    def waiter(received_event, delay):
        nonlocal cancelled
        assert received_event is event
        waits.append(delay)
        cancelled = True
        return False

    executor = RetryExecutor(RetryPolicy(base_delay=60), waiter=waiter)
    result = executor.execute(
        operation, lambda exc: ClassifiedProviderError(ErrorCategory.TIMEOUT),
        cancellation_token=lambda: cancelled, cancellation_event=event)
    assert result.cancelled
    assert calls == [1]
    assert len(waits) == 1
    assert 0 < waits[0] <= 0.1
    assert not event.is_set()
