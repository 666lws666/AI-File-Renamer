"""Provider connection test and honest capability detection.

The connection probe uses a minimal, hard-coded, non-secret test message.
It never sends visual data, user content, paths, or private metadata.

Capability detection is honest: capabilities not confirmed by preset data,
explicit response evidence, or user configuration remain false/unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from src.core.provider_presets import ProviderPreset, capabilities_for_model
from src.core.provider_protocol import ProviderCapabilities, ProviderRequest
from src.providers.openai_compatible import (
    OpenAICompatibleAdapter,
    ProviderAdapterConfigurationError,
)
from src.services.retry_policy import (
    ClassifiedProviderError,
    ErrorCategory,
    RetryExecutionResult,
)


# ── Pure-data value objects ─────────────────────────────────────────────────


class ProbeStatus(str, Enum):
    SUCCESS = "success"
    AUTH_ERROR = "auth_error"
    PERMISSION_ERROR = "permission_error"
    MODEL_ERROR = "model_error"
    NETWORK_ERROR = "network_error"
    RESPONSE_ERROR = "response_error"
    RATE_LIMITED = "rate_limited"
    RETRY_EXHAUSTED = "retry_exhausted"
    UNKNOWN_ERROR = "unknown_error"


class ConnectionOutcome(str, Enum):
    SUCCESS = "success"
    AUTH_ERROR = "auth_error"
    PERMISSION_ERROR = "permission_error"
    MODEL_ERROR = "model_error"
    NETWORK_ERROR = "network_error"
    RESPONSE_ERROR = "response_error"
    RATE_LIMITED = "rate_limited"
    RETRY_EXHAUSTED = "retry_exhausted"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    """Pure-data description of a probe call; never executed directly."""

    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    json_body: Mapping[str, Any] = field(default_factory=dict)
    timeout: int = 30

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "json_body", MappingProxyType(dict(self.json_body)))


@dataclass(frozen=True, slots=True)
class ProbeResponse:
    """Result of a connection probe — pure data, no secrets."""

    status: ProbeStatus
    status_code: int | None = None
    latency_ms: float = 0.0
    response_body: Mapping[str, Any] = field(default_factory=dict)
    model_from_response: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "response_body", MappingProxyType(dict(self.response_body))
        )


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    """Result of running a connection test against one profile."""

    outcome: ConnectionOutcome
    latency_ms: float = 0.0
    status_code: int | None = None
    error_category: ErrorCategory | None = None
    error_message: str = ""
    model_detected: str = ""
    detected_capabilities: ProviderCapabilities | None = None
    probe_response: ProbeResponse | None = None

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(outcome={self.outcome.value!r}, "
            f"model={self.model_detected!r}, "
            f"latency_ms={self.latency_ms:.1f})"
        )


@dataclass(frozen=True, slots=True)
class CapabilityDetection:
    """Honest capability record — unverified capabilities remain false."""

    text: bool = False
    vision: bool = False
    multi_image: bool = False
    json_mode: bool = False
    json_schema: bool = False
    streaming: bool = False
    tool_calling: bool = False
    verified_by: str = ""
    detection_note: str = ""

    def to_provider_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text=self.text,
            vision=self.vision,
            multi_image=self.multi_image,
            json_mode=self.json_mode,
            json_schema=self.json_schema,
            streaming=self.streaming,
            tool_calling=self.tool_calling,
        )


# ── Error classification helpers ────────────────────────────────────────────


def _map_error_category_to_outcome(category: ErrorCategory) -> ConnectionOutcome:
    mapping = {
        ErrorCategory.AUTH: ConnectionOutcome.AUTH_ERROR,
        ErrorCategory.PERMISSION: ConnectionOutcome.PERMISSION_ERROR,
        ErrorCategory.MODEL_NOT_FOUND: ConnectionOutcome.MODEL_ERROR,
        ErrorCategory.TIMEOUT: ConnectionOutcome.NETWORK_ERROR,
        ErrorCategory.NETWORK: ConnectionOutcome.NETWORK_ERROR,
        ErrorCategory.RATE_LIMIT: ConnectionOutcome.RATE_LIMITED,
        ErrorCategory.SERVER: ConnectionOutcome.RETRY_EXHAUSTED,
        ErrorCategory.MALFORMED_RESPONSE: ConnectionOutcome.RESPONSE_ERROR,
        ErrorCategory.INVALID_REQUEST: ConnectionOutcome.UNKNOWN_ERROR,
        ErrorCategory.BUDGET_BLOCKED: ConnectionOutcome.UNKNOWN_ERROR,
        ErrorCategory.CANCELLED: ConnectionOutcome.UNKNOWN_ERROR,
    }
    return mapping.get(category, ConnectionOutcome.UNKNOWN_ERROR)


def _map_category_to_probe_status(category: ErrorCategory) -> ProbeStatus:
    mapping = {
        ErrorCategory.AUTH: ProbeStatus.AUTH_ERROR,
        ErrorCategory.PERMISSION: ProbeStatus.PERMISSION_ERROR,
        ErrorCategory.MODEL_NOT_FOUND: ProbeStatus.MODEL_ERROR,
        ErrorCategory.TIMEOUT: ProbeStatus.NETWORK_ERROR,
        ErrorCategory.NETWORK: ProbeStatus.NETWORK_ERROR,
        ErrorCategory.RATE_LIMIT: ProbeStatus.RATE_LIMITED,
        ErrorCategory.SERVER: ProbeStatus.RETRY_EXHAUSTED,
        ErrorCategory.MALFORMED_RESPONSE: ProbeStatus.RESPONSE_ERROR,
        ErrorCategory.INVALID_REQUEST: ProbeStatus.UNKNOWN_ERROR,
        ErrorCategory.BUDGET_BLOCKED: ProbeStatus.UNKNOWN_ERROR,
        ErrorCategory.CANCELLED: ProbeStatus.UNKNOWN_ERROR,
    }
    return mapping.get(category, ProbeStatus.UNKNOWN_ERROR)


# ── ConnectionTest ──────────────────────────────────────────────────────────


class ConnectionTest:
    """Run a minimal probe call against one adapter and classify the outcome.

    The probe uses a tiny, fixed message (``"ping"``).  It never sends visual
    data, user documents, paths, or private metadata.

    The probe goes through ``OpenAICompatibleAdapter.invoke_probe`` — the
    ONLY path allowed to bypass ``needs_connection_verification`` — so an
    unverified provider can complete its first connection test while normal
    business invokes remain blocked by the verification gate.
    """

    def __init__(self, adapter: OpenAICompatibleAdapter) -> None:
        self._adapter = adapter

    def execute(self) -> ConnectionResult:
        """Send a minimal text probe and return a classified result."""
        try:
            result: RetryExecutionResult = self._adapter.invoke_probe(
                cancellation_token=None,
            )
        except ProviderAdapterConfigurationError as error:
            return ConnectionResult(
                outcome=ConnectionOutcome.UNKNOWN_ERROR,
                error_message=str(error),
                error_category=ErrorCategory.INVALID_REQUEST,
            )

        if result.success and result.value is not None:
            outcome = result.value
            # probe outcome: plain text content is accepted (never a naming
            # field); model / latency / usage are still recorded.
            return ConnectionResult(
                outcome=ConnectionOutcome.SUCCESS,
                latency_ms=float(outcome.latency_ms),
                status_code=200,
                model_detected=str(outcome.model),
                probe_response=ProbeResponse(
                    status=ProbeStatus.SUCCESS,
                    status_code=200,
                    latency_ms=float(outcome.latency_ms),
                    response_body=dict(outcome.body),
                    model_from_response=str(outcome.model),
                ),
            )

        # Failure path
        final_category = result.final_category or ErrorCategory.INVALID_REQUEST
        outcome = _map_error_category_to_outcome(final_category)
        error_msg = str(result.final_error) if result.final_error else ""

        # Extract status_code from the final error if it carries one
        status_code = None
        final_error = result.final_error
        if final_error is not None:
            status_code = getattr(final_error, "status_code", None)

        return ConnectionResult(
            outcome=outcome,
            error_category=final_category,
            error_message=error_msg,
            status_code=status_code,
        )


def run_connection_test(adapter: OpenAICompatibleAdapter) -> ConnectionResult:
    """Convenience function: probe one adapter and return the outcome."""
    return ConnectionTest(adapter).execute()


# ── Capability Detection ────────────────────────────────────────────────────


def detect_capabilities_from_response(
    *,
    preset: ProviderPreset | None,
    response_body: Mapping[str, Any],
    model_from_response: str,
    declared_capabilities: ProviderCapabilities | None = None,
) -> CapabilityDetection:
    """Determine capabilities from preset data and explicit response evidence.

    Rules (in order):
    1. If ``declared_capabilities`` is provided (custom provider), use it directly.
    2. If ``preset`` is available, use its capabilities as the ceiling.
    3. If the detected model is in ``capability_verified_models``, retain full
       preset capabilities; otherwise fall back to text-only.
    4. Never auto-detect capabilities from a text-only probe success.
    5. Unverified capabilities remain ``False``.
    """
    # Custom provider: user-declared capabilities are authoritative
    if preset is None:
        if declared_capabilities is not None:
            return CapabilityDetection(
                text=declared_capabilities.text,
                vision=declared_capabilities.vision,
                multi_image=declared_capabilities.multi_image,
                json_mode=declared_capabilities.json_mode,
                json_schema=declared_capabilities.json_schema,
                streaming=declared_capabilities.streaming,
                tool_calling=declared_capabilities.tool_calling,
                verified_by="user_declared",
                detection_note="Capabilities come from the user-configured profile.",
            )
        # No preset and no declared caps → conservatively text-only
        return CapabilityDetection(
            text=True,
            verified_by="fallback",
            detection_note="No preset or declared capabilities available; text-only assumed.",
        )

    preset_caps = capabilities_for_model(preset, model_from_response)
    verified_models = set(preset.capability_verified_models)

    # If preset has verified models and the detected model is not among them,
    # fall back to text-only
    if verified_models and model_from_response not in verified_models:
        return CapabilityDetection(
            text=True,
            verified_by="preset_text_fallback",
            detection_note=(
                f"Model '{model_from_response}' is not in the preset's "
                f"capability-verified list {sorted(verified_models)}; "
                f"capabilities reduced to text-only."
            ),
        )

    # Resolve the exact model; a brand-wide Flash ceiling must not grant vision
    # to Pro or an unverified name after a text-only connection probe.
    return CapabilityDetection(
        text=preset_caps.text,
        vision=preset_caps.vision,
        multi_image=preset_caps.multi_image,
        json_mode=preset_caps.json_mode,
        json_schema=preset_caps.json_schema,
        streaming=preset_caps.streaming,
        tool_calling=preset_caps.tool_calling,
        verified_by="preset",
        detection_note=(
            "Capabilities reflect the preset definition "
            f"(verification: {preset.verification_status})."
        ),
    )


# ── ConnectionTransportProbe ────────────────────────────────────────────────


class ConnectionTransportProbe:
    """Low-level transport probe that bypasses the adapter verification gate.

    This is the ONLY path allowed to bypass ``needs_connection_verification``.
    It runs through ``OpenAICompatibleAdapter.invoke_probe`` — the same
    shared transport operation, response parsing, retry policy, and error
    classification as a normal invoke — so classification and sanitisation
    are identical, never a second HTTP client or a drifting protocol copy.
    """

    def __init__(self, adapter: OpenAICompatibleAdapter) -> None:
        self._adapter = adapter

    def probe(self) -> ProbeResponse:
        """Execute one minimal probe call with a fixed "ping" payload."""
        profile = self._adapter.profile
        result = self._adapter.invoke_probe(cancellation_token=None)

        if result.success and result.value is not None:
            outcome = result.value
            return ProbeResponse(
                status=ProbeStatus.SUCCESS,
                status_code=200,
                latency_ms=float(outcome.latency_ms),
                response_body=dict(outcome.body),
                model_from_response=str(outcome.model),
            )

        final_category = result.final_category or ErrorCategory.INVALID_REQUEST
        status = _map_category_to_probe_status(final_category)
        error_msg = str(result.final_error) if result.final_error else ""
        status_code = None
        final_error = result.final_error
        if final_error is not None:
            status_code = getattr(final_error, "status_code", None)
        return ProbeResponse(
            status=status,
            status_code=status_code,
            latency_ms=0.0,
            error_message=error_msg,
        )
