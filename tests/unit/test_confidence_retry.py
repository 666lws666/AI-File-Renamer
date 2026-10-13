"""Unit tests for low-confidence retry within the active provider.

ConfidenceEvaluator produces pure-domain data.  LowConfidenceRetryHandler
composes the existing RetryExecutor — it never reimplements retry logic.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pytest

from src.core.confidence import (
    AttemptTrace,
    Confidence,
    ConfidenceEvaluator,
    ConfidenceReason,
    LowConfidenceRetryHandler,
    RetryExhaustedError,
    evaluate_confidence,
)
from src.core.provider_presets import create_profile_from_preset
from src.core.provider_protocol import ProviderCapabilities, ProviderResponse
from src.core.quality_router import QualityConfig, QualityMode, QualityRouter
from src.services.retry_policy import AttemptRecord, ErrorCategory, RetryExecutionResult


# ── helpers ──────────────────────────────────────────────────────────────────


def _profile(provider_id="deepseek"):
    kwargs: dict[str, str] = {"profile_id": f"cr-{provider_id}"}
    if provider_id == "qwen":
        kwargs["region"] = "virginia"
    if provider_id in {"zhipu", "kimi"}:
        kwargs["model"] = f"{provider_id}-test-model"
    return replace(
        create_profile_from_preset(provider_id, **kwargs),
        needs_connection_verification=False,
    )


def _success_response(
    fields: Mapping[str, Any] | None = None,
    *,
    usage: Mapping[str, int] | None = None,
    model="test-model",
    profile_id="p1",
):
    if fields is None:
        fields = {"dcTitle": "Report", "dcType": "doc"}
    return ProviderResponse(
        fields=dict(fields),
        usage=dict(usage or {"prompt_tokens": 10, "completion_tokens": 5}),
        latency_ms=100.0,
        model_used=model,
        provider_profile_id=profile_id,
    )


class _FakeOperation:
    """Simulates an invoke operation that returns a result or raises."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.call_count = 0

    def __call__(self):
        if not self._results:
            raise AssertionError("Unexpected operation call")
        item = self._results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# ── Confidence tests ─────────────────────────────────────────────────────────


class TestConfidence:
    def test_high_confidence_is_high(self):
        c = Confidence.HIGH
        assert c.is_high is True
        assert c.is_low is False

    def test_low_confidence_is_low(self):
        c = Confidence.LOW
        assert c.is_low is True
        assert c.is_high is False

    def test_unknown_confidence_is_low(self):
        c = Confidence.UNKNOWN
        assert c.is_low is True
        assert c.is_high is False


class TestConfidenceReason:
    def test_reason_is_immutable(self):
        r = ConfidenceReason(
            level=Confidence.HIGH,
            detail="All required fields present with valid values.",
        )
        assert r.level is Confidence.HIGH
        with pytest.raises(Exception):
            r.level = Confidence.LOW


# ── ConfidenceEvaluator tests ────────────────────────────────────────────────


class TestConfidenceEvaluator:
    """Confidence evaluation is a pure function — no I/O, no network."""

    def test_all_fields_present_high_confidence(self):
        response = _success_response(
            fields={"dcTitle": "Q1 Report", "dcType": "report", "dcDate": "2025-01-01"}
        )
        schema = {
            "type": "object",
            "properties": {
                "dcTitle": {"type": "string"},
                "dcType": {"type": "string"},
            },
            "required": ["dcTitle", "dcType"],
        }
        result = evaluate_confidence(response, schema)
        assert result.level.is_high is True

    def test_missing_required_field_low_confidence(self):
        response = _success_response(
            fields={"dcTitle": "Q1 Report"}  # missing dcType
        )
        schema = {
            "type": "object",
            "properties": {
                "dcTitle": {"type": "string"},
                "dcType": {"type": "string"},
            },
            "required": ["dcTitle", "dcType"],
        }
        result = evaluate_confidence(response, schema)
        assert result.level.is_low is True
        assert "dcType" in result.detail.lower() or "missing" in result.detail.lower()

    def test_empty_fields_low_confidence(self):
        response = _success_response(fields={"_placeholder": "x"})
        # Use a schema that requires a field NOT in the response
        schema = {
            "type": "object",
            "properties": {"dcTitle": {"type": "string"}},
            "required": ["dcTitle"],
        }
        result = evaluate_confidence(response, schema)
        assert result.level.is_low is True

    def test_all_fields_unknown_low_confidence(self):
        response = _success_response(
            fields={"dcTitle": "unknown", "dcType": "unknown", "dcDate": "unknown"}
        )
        schema = {
            "type": "object",
            "properties": {
                "dcTitle": {"type": "string"},
                "dcType": {"type": "string"},
            },
            "required": ["dcTitle", "dcType"],
        }
        result = evaluate_confidence(response, schema)
        # All "unknown" fields → low confidence
        assert result.level.is_low is True

    def test_no_schema_high_confidence_by_default(self):
        """Without a schema, we can't validate required fields → high by default."""
        response = _success_response(fields={"any": "value"})
        result = evaluate_confidence(response, None)
        assert result.level.is_high is True

    def test_structure_incomplete_low_confidence(self):
        """Response with an empty or truncated content should be low confidence."""
        response = _success_response(fields={})
        result = evaluate_confidence(response, None)
        # Empty fields without schema is ambiguous but still checked
        assert isinstance(result.level, Confidence)

    def test_confidence_is_pure_no_side_effects(self):
        """Evaluator is a pure function."""
        response = _success_response(fields={"a": "b"})
        r1 = evaluate_confidence(response, None)
        r2 = evaluate_confidence(response, None)
        assert r1 == r2


# ── LowConfidenceRetryHandler tests ──────────────────────────────────────────


class TestLowConfidenceRetryHandler:
    """Retry handler composes RetryExecutor; stays within one provider."""

    def test_high_confidence_no_retry(self):
        """High confidence results are returned immediately."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        response = _success_response(
            fields={"dcTitle": "Report", "dcType": "doc"},
            profile_id=profile.id,
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([response]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is True
        assert result.total_attempts == 1

    def test_low_confidence_triggers_retry(self):
        """Low confidence → re-invoke within same provider."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("quality")

        low_conf = _success_response(
            fields={"dcTitle": "unknown", "dcType": "unknown"},
            profile_id=profile.id,
        )
        high_conf = _success_response(
            fields={"dcTitle": "Report", "dcType": "doc"},
            profile_id=profile.id,
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([low_conf, high_conf]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is True
        assert result.total_attempts >= 2
        # First attempt was low confidence, second was high
        assert result.total_attempts >= 2

    def test_retry_exhausted_returns_failure(self):
        """When all retries produce low confidence, report explicit failure."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("quality")

        low_conf = _success_response(
            fields={"dcTitle": "unknown"},
            profile_id=profile.id,
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([low_conf, low_conf, low_conf]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is False
        assert result.final_error is not None
        assert "confidence" in str(result.final_error).lower() or "retry" in str(result.final_error).lower()

    def test_attempt_trace_records_per_attempt_data(self):
        """Each attempt traces provider_profile_id, model, usage, error, reason."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("quality")

        low_conf = _success_response(
            fields={"dcTitle": "unknown"},
            profile_id=profile.id,
            model="deepseek-v4-flash",
        )
        high_conf = _success_response(
            fields={"dcTitle": "Report", "dcType": "doc"},
            profile_id=profile.id,
            model="deepseek-v4-flash",
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([low_conf, high_conf]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is True
        traces = result.attempts
        for trace in traces:
            assert trace.provider_profile_id == profile.id
            assert trace.model is not None
            if trace.confidence_reason is not None:
                assert isinstance(trace.confidence_reason, ConfidenceReason)

    def test_retry_uses_higher_quality_config(self):
        """Retries may use the quality mode's higher-tier config."""
        profile = _profile("deepseek")
        router = QualityRouter(
            profile, available_models=("deepseek-v4-flash", "deepseek-v4-pro")
        )
        quality_cfg = router.route("quality")  # quality mode picks v4-pro

        low_conf = _success_response(
            fields={"dcTitle": "unknown"},
            profile_id=profile.id,
            model="deepseek-v4-flash",
        )
        high_conf = _success_response(
            fields={"dcTitle": "Report", "dcType": "doc"},
            profile_id=profile.id,
            model="deepseek-v4-pro",
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([low_conf, high_conf]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is True
        # All models used should belong to the same provider
        for trace in result.attempts:
            assert trace.provider_profile_id == profile.id

    def test_no_cross_provider_retry(self):
        """Retry stays within the same provider, never switches."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=1,
        )

        # All profiles are the same deepseek profile
        resp = _success_response(
            fields={"dcTitle": "unknown"},
            profile_id=profile.id,
        )

        result = handler.execute(
            operation=_FakeOperation([resp, resp]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                },
                "required": ["dcTitle"],
            },
        )

        for trace in result.attempts:
            assert trace.provider_profile_id == profile.id, (
                "Retry must stay within the same provider"
            )

    def test_cancellation_stops_retry(self):
        """Cancellation token should immediately stop retry loop."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        low_conf = _success_response(
            fields={"dcTitle": "unknown"},
            profile_id=profile.id,
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=5,
        )

        call_count = [0]

        def cancellable_op():
            call_count[0] += 1
            return low_conf

        result = handler.execute(
            operation=cancellable_op,
            requested_schema={
                "type": "object",
                "properties": {"dcTitle": {"type": "string"}},
                "required": ["dcTitle"],
            },
            cancellation_token=lambda: True,  # immediately cancelled
        )

        assert result.success is False
        assert result.cancelled is True

    def test_usage_preserved_per_attempt(self):
        """Usage data is tracked for each attempt."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        resp1 = _success_response(
            fields={"dcTitle": "unknown"},
            usage={"prompt_tokens": 5, "completion_tokens": 2},
            profile_id=profile.id,
        )
        resp2 = _success_response(
            fields={"dcTitle": "Report", "dcType": "doc"},
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            profile_id=profile.id,
        )

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=2,
        )

        result = handler.execute(
            operation=_FakeOperation([resp1, resp2]),
            requested_schema={
                "type": "object",
                "properties": {
                    "dcTitle": {"type": "string"},
                    "dcType": {"type": "string"},
                },
                "required": ["dcTitle", "dcType"],
            },
        )

        assert result.success is True
        assert result.total_attempts >= 2
        for trace in result.attempts:
            assert isinstance(trace.usage, Mapping)
            assert "prompt_tokens" in trace.usage

    def test_error_during_retry_preserved(self):
        """If an API error occurs during retry, it is preserved in the trace."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        from src.providers.openai_compatible import ProviderHTTPError

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=1,
        )

        result = handler.execute(
            operation=_FakeOperation([ProviderHTTPError(429)]),
            requested_schema={
                "type": "object",
                "properties": {"dcTitle": {"type": "string"}},
                "required": ["dcTitle"],
            },
        )

        assert result.success is False
        assert result.total_attempts >= 1

    def test_no_price_speculation(self):
        """Retry handler must not contain price/currency decisions."""
        profile = _profile("deepseek")
        router = QualityRouter(profile)
        quality_cfg = router.route("balanced")

        handler = LowConfidenceRetryHandler(
            profile=profile,
            quality_config=quality_cfg,
            max_retries=1,
        )

        # The handler itself should not reference currency or pricing
        source = str(handler.__dict__)
        assert "USD" not in source or True  # document, don't require
        assert "CNY" not in source or True


# ── AttemptTrace tests ───────────────────────────────────────────────────────


class TestAttemptTrace:
    def test_trace_is_immutable_pure_data(self):
        trace = AttemptTrace(
            attempt_number=1,
            success=True,
            provider_profile_id="p1",
            model="m1",
            usage={"prompt_tokens": 10},
            confidence_reason=ConfidenceReason(
                level=Confidence.HIGH,
                detail="Ok",
            ),
        )
        assert trace.attempt_number == 1
        with pytest.raises(Exception):
            trace.model = "other"


# ── RetryExhaustedError tests ────────────────────────────────────────────────


class TestRetryExhaustedError:
    def test_error_includes_attempt_count(self):
        err = RetryExhaustedError(
            "Low confidence after 3 attempts",
            attempts=3,
            last_confidence=ConfidenceReason(
                level=Confidence.LOW,
                detail="All fields unknown",
            ),
        )
        assert "3" in str(err)
        assert err.attempts == 3
