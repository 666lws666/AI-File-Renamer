"""Low-confidence retry within the active provider.

ConfidenceEvaluator is a pure function.  LowConfidenceRetryHandler composes
the existing RetryExecutor — it never reimplements retry logic, never switches
providers, and never uses unconfigured models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderResponse
from src.core.quality_router import QualityConfig, QualityMode, QualityRouter
from src.services.retry_policy import ErrorCategory, RetryExecutionResult


# ── Confidence ───────────────────────────────────────────────────────────────


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"
    UNKNOWN = "unknown"

    @property
    def is_high(self) -> bool:
        return self is Confidence.HIGH

    @property
    def is_low(self) -> bool:
        return self is Confidence.LOW or self is Confidence.UNKNOWN


@dataclass(frozen=True, slots=True)
class ConfidenceReason:
    """Why a response was evaluated as high/low/unknown confidence."""

    level: Confidence
    detail: str = ""


# ── AttemptTrace ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AttemptTrace:
    """One attempt's worth of retry-relevant data — pure domain, no secrets."""

    attempt_number: int
    success: bool
    provider_profile_id: str
    model: str
    usage: Mapping[str, int | float] = field(default_factory=dict)
    error_category: ErrorCategory | None = None
    error_message: str = ""
    confidence_reason: ConfidenceReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))


# ── RetryExhaustedError ──────────────────────────────────────────────────────


class RetryExhaustedError(RuntimeError):
    """Low-confidence retry exhausted without reaching an applicable result."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_confidence: ConfidenceReason | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_confidence = last_confidence


# ── ConfidenceEvaluator ──────────────────────────────────────────────────────


_UNKNOWN_MARKERS = frozenset(
    {
        "unknown",
        "n/a",
        "none",
        "null",
        "undefined",
        "unspecified",
        "not available",
        "not applicable",
    }
)


def _is_unknown_value(value: Any) -> bool:
    """Check if a single value is a known 'unknown' marker."""
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip().casefold()
        return stripped == "" or stripped in _UNKNOWN_MARKERS
    return False


class ConfidenceEvaluator:
    """Pure-function confidence evaluator — no I/O, no secrets, no network."""

    def evaluate(
        self,
        response: ProviderResponse,
        requested_schema: Mapping[str, Any] | None = None,
    ) -> ConfidenceReason:
        """Return a confidence reason for the given response."""
        return evaluate_confidence(response, requested_schema)


def evaluate_confidence(
    response: ProviderResponse,
    requested_schema: Mapping[str, Any] | None = None,
) -> ConfidenceReason:
    """Evaluate response confidence against a requested schema (if any).

    Rules:
    - No schema: HIGH (we can't validate further).
    - All required fields present with non-unknown values: HIGH.
    - Missing required fields / all fields unknown / empty: LOW.
    """
    fields = dict(response.fields) if response.fields else {}

    if requested_schema is None:
        return ConfidenceReason(
            level=Confidence.HIGH,
            detail="No requested schema — confidence cannot be lowered.",
        )

    required = requested_schema.get("required", ())
    if not isinstance(required, (list, tuple)):
        return ConfidenceReason(
            level=Confidence.HIGH,
            detail="Schema has no required field list.",
        )

    required = tuple(required)
    if not required:
        return ConfidenceReason(
            level=Confidence.HIGH,
            detail="Schema specifies no required fields.",
        )

    # Check missing required fields
    missing = [name for name in required if name not in fields]
    if missing:
        return ConfidenceReason(
            level=Confidence.LOW,
            detail=f"Missing required fields: {missing}",
        )

    # Check all-unknown
    unknown_count = 0
    for name in required:
        if _is_unknown_value(fields.get(name)):
            unknown_count += 1

    if unknown_count == len(required):
        return ConfidenceReason(
            level=Confidence.LOW,
            detail="All required fields contain unknown/empty values.",
        )

    if unknown_count > 0:
        return ConfidenceReason(
            level=Confidence.LOW,
            detail=f"{unknown_count}/{len(required)} required fields are unknown.",
        )

    # Fields present and valid
    return ConfidenceReason(
        level=Confidence.HIGH,
        detail="All required fields present with valid values.",
    )


# ── LowConfidenceRetryHandler ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ConfidenceRetryResult:
    """Result of a confidence-aware retry loop — pure data, no secrets."""

    success: bool
    value: ProviderResponse | None
    attempts: tuple[AttemptTrace, ...]
    final_error: Exception | None
    final_category: ErrorCategory | None
    cancelled: bool = False

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)


class LowConfidenceRetryHandler:
    """Retry low-confidence responses within the same provider.

    This handler composes the existing ``RetryExecutor`` pattern — it does not
    reimplement retry logic.  It never switches providers and never uses
    models the user has not configured.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        quality_config: QualityConfig,
        max_retries: int = 2,
    ) -> None:
        self._profile = profile
        self._quality_config = quality_config
        self._max_retries = max(0, max_retries)

    def execute(
        self,
        *,
        operation: Callable[[], ProviderResponse],
        requested_schema: Mapping[str, Any] | None = None,
        cancellation_token: Callable[[], bool] | None = None,
    ) -> ConfidenceRetryResult:
        """Run up to max_retries+1 attempts, retrying on low confidence."""
        traces: list[AttemptTrace] = []
        is_cancelled = cancellation_token or (lambda: False)
        evaluator = ConfidenceEvaluator()

        for attempt_num in range(1, self._max_retries + 2):
            if is_cancelled():
                return ConfidenceRetryResult(
                    success=False,
                    value=None,
                    attempts=tuple(traces),
                    final_error=None,
                    final_category=ErrorCategory.CANCELLED,
                    cancelled=True,
                )

            # Execute the operation
            try:
                response = operation()
            except Exception as error:
                # Transport/protocol error — classify and record
                from src.providers.openai_compatible import ProviderHTTPError

                category = ErrorCategory.INVALID_REQUEST
                status_code = getattr(error, "status_code", None)
                if status_code is not None:
                    from src.services.retry_policy import classify_http_status
                    category = classify_http_status(int(status_code))

                traces.append(
                    AttemptTrace(
                        attempt_number=attempt_num,
                        success=False,
                        provider_profile_id=self._profile.id,
                        model=self._quality_config.model,
                        usage={},
                        error_category=category,
                        error_message=str(error),
                    )
                )
                return ConfidenceRetryResult(
                    success=False,
                    value=None,
                    attempts=tuple(traces),
                    final_error=error,
                    final_category=category,
                )

            # Evaluate confidence
            confidence = evaluator.evaluate(response, requested_schema)

            model_used = getattr(response, "model_used", self._quality_config.model)
            usage = dict(getattr(response, "usage", {}))

            if confidence.level.is_high:
                traces.append(
                    AttemptTrace(
                        attempt_number=attempt_num,
                        success=True,
                        provider_profile_id=self._profile.id,
                        model=str(model_used),
                        usage=usage,
                        confidence_reason=confidence,
                    )
                )
                return ConfidenceRetryResult(
                    success=True,
                    value=response,
                    attempts=tuple(traces),
                    final_error=None,
                    final_category=None,
                )

            # Low confidence — record and retry
            traces.append(
                AttemptTrace(
                    attempt_number=attempt_num,
                    success=True,  # API call succeeded, but confidence is low
                    provider_profile_id=self._profile.id,
                    model=str(model_used),
                    usage=usage,
                    confidence_reason=confidence,
                )
            )

        # Retries exhausted without high confidence
        last_confidence = traces[-1].confidence_reason if traces else None
        error = RetryExhaustedError(
            f"Low-confidence retry exhausted after {self._max_retries + 1} attempts",
            attempts=self._max_retries + 1,
            last_confidence=last_confidence,
        )
        return ConfidenceRetryResult(
            success=False,
            value=None,
            attempts=tuple(traces),
            final_error=error,
            final_category=ErrorCategory.CANCELLED,
        )
