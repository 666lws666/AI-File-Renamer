"""Unit tests for provider connection test and capability detection.

Every test uses an in-memory transport double — no real network calls.
"""
from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from src.core.connection_test import (
    CapabilityDetection,
    ConnectionOutcome,
    ConnectionResult,
    ConnectionTest,
    ConnectionTransportProbe,
    ProbeRequest,
    ProbeResponse,
    ProbeStatus,
    detect_capabilities_from_response,
    run_connection_test,
)
from src.core.provider_presets import (
    create_custom_provider_profile,
    create_profile_from_preset,
    get_provider_preset,
)
from src.core.provider_protocol import (
    ProviderCapabilities,
    prepare_visual_payload,
)
from src.providers.openai_compatible import (
    OpenAICompatibleAdapter,
    ProviderAdapterConfigurationError,
    TransportResponse,
)
from src.services.retry_policy import ErrorCategory, RetryExecutor, RetryPolicy


# ── helpers ──────────────────────────────────────────────────────────────────


def _verified_profile(provider_id: str):
    kwargs: dict[str, str] = {"profile_id": f"ct-{provider_id}"}
    if provider_id == "qwen":
        kwargs["region"] = "virginia"
    if provider_id in {"zhipu", "kimi"}:
        kwargs["model"] = f"{provider_id}-test-model"
    return replace(
        create_profile_from_preset(provider_id, **kwargs),
        needs_connection_verification=False,
    )


def _verified_custom():
    return replace(
        create_custom_provider_profile(
            profile_id="ct-custom",
            display_name="Connection test custom",
            base_url="https://custom.test/v1",
            model="test-model",
            capabilities=ProviderCapabilities(text=True, json_mode=True),
        ),
        needs_connection_verification=False,
    )


class _FakeTransport:
    """Deterministic transport double for connection tests."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def send(self, *, url, headers, json_body, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "json_body": json_body,
                "timeout": timeout,
            }
        )
        if not self._responses:
            raise AssertionError("Unexpected transport call in connection test")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _probe_transport(profile, credential="test-key"):
    """Create an adapter with a fake transport suitable for probe calls."""
    transport = _FakeTransport([])
    adapter = OpenAICompatibleAdapter(
        profile=profile,
        credential=credential,
        transport=transport,
        retry_executor=RetryExecutor(
            RetryPolicy(max_retries=0),
            sleeper=lambda d: None,
        ),
    )
    return adapter, transport


def _minimal_probe_response(model="detected-model", *, usage=True, content='{"status":"ok"}'):
    return TransportResponse(
        status_code=200,
        headers={},
        json_body={
            "choices": [
                {
                    "message": {
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": model,
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
            } if usage else {},
        },
        latency_ms=8.0,
    )


# ── ConnectionTest tests ────────────────────────────────────────────────────


class TestConnectionTest:
    """Connection tests probe a profile with a minimal, hard-coded prompt."""

    def test_connection_success_returns_ok(self):
        """200 + legitimate structured response → success outcome with latency."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        result = run_connection_test(adapter)

        assert isinstance(result, ConnectionResult)
        assert result.outcome is ConnectionOutcome.SUCCESS
        assert result.latency_ms > 0
        assert result.error_category is None
        assert len(transport.calls) == 1

        # Probe must be minimal
        body = transport.calls[0]["json_body"]
        serialized = json.dumps(body)
        assert "connection" in serialized.lower() or "test" in serialized.lower() or "ping" in serialized.lower()
        # No user content, files, paths, or real credentials leak into the probe
        model_bytes = body.get("messages")
        assert model_bytes is not None
        # Ensure the probe message is tiny
        total_text = json.dumps(body["messages"])
        assert len(total_text) < 2000, "Probe payload is too large"

    def test_connection_401_yields_auth_error(self):
        """401 response → auth_error outcome."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=401,
                headers={},
                json_body={"error": {"message": "Unauthorized"}},
                latency_ms=3.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.AUTH_ERROR
        assert result.error_category is ErrorCategory.AUTH
        assert result.status_code == 401
        # No secret in result
        dumped = repr(result)
        assert "test-key" not in dumped

    def test_connection_403_yields_permission_error(self):
        """403 response → permission_error outcome."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=403,
                headers={},
                json_body={"error": {}},
                latency_ms=2.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.PERMISSION_ERROR
        assert result.error_category is ErrorCategory.PERMISSION

    def test_connection_404_yields_model_error(self):
        """404 / model-unavailable → model_error outcome."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=404,
                headers={},
                json_body={},
                latency_ms=2.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.MODEL_ERROR
        assert result.error_category is ErrorCategory.MODEL_NOT_FOUND

    def test_connection_timeout_yields_network_error(self):
        """Timeout → timeout/network_error outcome."""
        from src.providers.openai_compatible import ProviderTransportTimeout

        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(ProviderTransportTimeout("timed out"))

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.NETWORK_ERROR
        assert result.error_category in (ErrorCategory.TIMEOUT, ErrorCategory.NETWORK)

    def test_connection_dns_failure_yields_network_error(self):
        """DNS/connection error → network_error outcome."""
        from src.providers.openai_compatible import ProviderNetworkError

        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(ProviderNetworkError("connection refused"))

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.NETWORK_ERROR
        assert result.error_category is ErrorCategory.NETWORK

    def test_malformed_response_yields_response_error(self):
        """Malformed / non-JSON response → response_error outcome."""
        from src.providers.openai_compatible import ProviderResponseError

        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            ProviderResponseError("non-JSON body")
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RESPONSE_ERROR
        assert result.error_category is ErrorCategory.MALFORMED_RESPONSE

    def test_429_rate_limited_deterministic(self):
        """A single 429 with max_retries=0 → RATE_LIMITED / RATE_LIMIT,
        exactly one transport call (no retry loop)."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=429,
                headers={"Retry-After": "0"},
                json_body={"error": {}},
                latency_ms=1.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RATE_LIMITED
        assert result.error_category is ErrorCategory.RATE_LIMIT
        assert len(transport.calls) == 1

    def test_success_does_not_set_vision_capability(self):
        """A text-only success must not be misreported as vision-verified."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS
        # A text probe cannot prove vision
        if result.detected_capabilities is not None:
            assert result.detected_capabilities.vision is False, (
                "Text-only connection must not claim vision is verified"
            )

    def test_unverified_profile_cannot_perform_normal_invoke(self):
        """Profiles with needs_connection_verification=True are rejected by invoke."""
        profile = replace(
            _verified_profile("deepseek"),
            needs_connection_verification=True,
        )
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        # The run_connection_test function MUST use a probe interface, not normal invoke
        result = run_connection_test(adapter)

        # The probe works — it bypasses the verification gate for test purposes
        assert result.outcome is ConnectionOutcome.SUCCESS, (
            f"unverified profile probe must succeed, got {result.outcome.value}"
        )
        assert len(transport.calls) == 1, "probe must send exactly one request"
        # But the adapter's normal invoke should still reject the unverified profile
        from src.core.provider_protocol import ProviderRequest
        with pytest.raises(ProviderAdapterConfigurationError, match="verification"):
            adapter.invoke(
                ProviderRequest(request_id="r", task_id="t", extracted_text="hello")
            )

    def test_probe_does_not_send_visual_payload(self):
        """Connection probe must not send any image/visual data."""
        profile = _verified_profile("qwen")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        run_connection_test(adapter)

        body = transport.calls[0]["json_body"]
        messages = body.get("messages", [])
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    assert part.get("type") != "image_url", (
                        "Probe must not contain visual data"
                    )
            else:
                assert "base64" not in str(content), (
                    "Probe must not contain base64-encoded data"
                )

    def test_probe_does_not_send_user_text(self):
        """Connection probe must not include user document text."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        run_connection_test(adapter)

        body = transport.calls[0]["json_body"]
        serialized = json.dumps(body)
        # The probe must be a fixed, non-user-content message
        assert "Quarterly revenue" not in serialized
        assert "user document" not in serialized.lower()

    def test_probe_does_not_send_paths_or_private_metadata(self):
        """Connection probe must not leak paths, filenames or private metadata."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        run_connection_test(adapter)

        body = transport.calls[0]["json_body"]
        serialized = json.dumps(body)
        # No paths
        assert "D:\\" not in serialized
        assert "/home/" not in serialized
        assert "file://" not in serialized

    def test_probe_failure_does_not_mark_profile_verified(self):
        """A failed probe must not alter the persistent profile verification state."""
        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=401,
                headers={},
                json_body={},
                latency_ms=1.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is not ConnectionOutcome.SUCCESS
        # The original profile is untouched (it's immutable anyway)
        assert profile.needs_connection_verification is False  # unchanged

    def test_custom_provider_connection_test(self):
        """Connection test works for custom provider profiles too."""
        profile = _verified_custom()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response(model="my-custom-model"))

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS
        assert len(transport.calls) == 1

    def test_5xx_retry_exhausted_deterministic(self):
        """2 retries on 3x 502 with max_retries=2 → RETRY_EXHAUSTED / SERVER,
        exactly three transport calls."""
        from src.services.retry_policy import RetryExecutor, RetryPolicy

        profile = _verified_profile("deepseek")
        transport = _FakeTransport([
            TransportResponse(status_code=502, headers={}, json_body={}, latency_ms=1.0),
            TransportResponse(status_code=502, headers={}, json_body={}, latency_ms=1.0),
            TransportResponse(status_code=502, headers={}, json_body={}, latency_ms=1.0),
        ])
        adapter = OpenAICompatibleAdapter(
            profile=profile,
            credential="test-key",
            transport=transport,
            retry_executor=RetryExecutor(
                RetryPolicy(max_retries=2),
                sleeper=lambda d: None,
            ),
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RETRY_EXHAUSTED
        assert result.error_category is ErrorCategory.SERVER
        assert len(transport.calls) == 3


# ── CapabilityDetection tests ───────────────────────────────────────────────


class TestCapabilityDetection:
    """Capability detection is honest — it never infers unverified capabilities."""

    def test_text_only_model_reports_text_true_vision_false(self):
        """Pro stays text-only even though the current Flash preset has vision."""
        preset = get_provider_preset("deepseek")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={"model": "deepseek-v4-pro"},
            model_from_response="deepseek-v4-pro",
        )

        assert detection.text is True
        assert detection.vision is False
        assert detection.multi_image is False

    def test_vision_preset_reports_preset_capabilities(self):
        """Qwen preset declares vision=True; detection records it as preset-verified."""
        preset = get_provider_preset("qwen")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={},
            model_from_response="qwen3.6-flash",
        )

        assert detection.text is True
        assert detection.vision is True
        # Preset-level capability is the floor; we don't upgrade without evidence
        assert detection.multi_image is preset.capabilities.multi_image

    @pytest.mark.parametrize("model", ["deepseek-v4-pro", "deepseek-flash-unverified"])
    def test_text_success_does_not_auto_detect_vision(self, model):
        """A successful text probe must not set vision=True."""
        preset = get_provider_preset("deepseek")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={"choices": [{"message": {"content": "ok"}}]},
            model_from_response=model,
        )

        assert detection.vision is False, (
            "Text-only success must not auto-detect vision support"
        )

    @pytest.mark.parametrize("model", [
        "deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
    ])
    def test_verified_flash_names_retain_catalog_vision(self, model):
        detection = detect_capabilities_from_response(
            preset=get_provider_preset("deepseek"), response_body={},
            model_from_response=model,
        )
        assert detection.vision is True
        assert detection.multi_image is True
        assert detection.json_mode is True
        assert detection.json_schema is False

    def test_unknown_model_in_preset_falls_back_to_text_only(self):
        """If the detected model is not in verified capability models, default text-only."""
        preset = get_provider_preset("mimo")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={},
            model_from_response="some-unknown-model-v99",
        )

        # MiMo's capability_verified_models are mimo-v2.5 and mimo-v2.5-pro
        # An unknown model must fallback to text-only
        assert detection.text is True
        assert detection.vision is False, (
            "Unverified model must not claim unverified capabilities"
        )

    def test_verified_model_retains_preset_capabilities(self):
        """A model in capability_verified_models keeps the preset's capabilities."""
        preset = get_provider_preset("mimo")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={},
            model_from_response="mimo-v2.5",
        )

        assert detection.text is True
        assert detection.vision is True
        assert detection.json_mode is True

    def test_unverified_capability_remains_false(self):
        """Capabilities not in the preset remain false even after connection success."""
        preset = get_provider_preset("mimo")
        detection = detect_capabilities_from_response(
            preset=preset,
            response_body={},
            model_from_response="mimo-v2.5",
        )

        # MiMo preset does NOT declare json_schema
        assert detection.json_schema is False, (
            "Unverified capability must remain false"
        )

    def test_custom_provider_capabilities_from_profile(self):
        """Custom provider capabilities come from the user's declared capabilities."""
        # For custom providers, we pass the profile capabilities directly
        caps = ProviderCapabilities(text=True, vision=True, json_mode=True)
        detection = detect_capabilities_from_response(
            preset=None,
            response_body={},
            model_from_response="custom-model",
            declared_capabilities=caps,
        )

        assert detection.text is True
        assert detection.vision is True
        assert detection.json_mode is True
        assert detection.json_schema is False
        assert detection.streaming is False

    def test_null_preset_without_declared_caps_is_text_only(self):
        """Without preset or declared caps, only text is assumed."""
        detection = detect_capabilities_from_response(
            preset=None,
            response_body={},
            model_from_response="unknown-model",
            declared_capabilities=None,
        )

        assert detection.text is True
        assert detection.vision is False
        assert detection.json_mode is False


# ── ProbeRequest / ProbeResponse value objects ──────────────────────────────


class TestProbeValueObjects:
    def test_probe_request_is_immutable_pure_data(self):
        req = ProbeRequest(
            url="https://api.example.com/chat/completions",
            headers={"Authorization": "Bearer ***"},
            json_body={"model": "test", "messages": []},
            timeout=10,
        )
        assert req.url.startswith("https://")
        assert req.timeout == 10
        # Fields should be read-only
        with pytest.raises(Exception):
            req.timeout = 999

    def test_probe_response_captures_all_fields(self):
        resp = ProbeResponse(
            status=ProbeStatus.SUCCESS,
            status_code=200,
            latency_ms=45.0,
            response_body={"model": "m1"},
            model_from_response="m1",
            error_message="",
        )
        assert resp.status is ProbeStatus.SUCCESS
        assert resp.model_from_response == "m1"

    def test_probe_status_enum_values(self):
        assert ProbeStatus.SUCCESS.value == "success"
        assert ProbeStatus.AUTH_ERROR.value == "auth_error"
        assert ProbeStatus.PERMISSION_ERROR.value == "permission_error"
        assert ProbeStatus.MODEL_ERROR.value == "model_error"
        assert ProbeStatus.NETWORK_ERROR.value == "network_error"
        assert ProbeStatus.RESPONSE_ERROR.value == "response_error"
        assert ProbeStatus.RATE_LIMITED.value == "rate_limited"
        assert ProbeStatus.RETRY_EXHAUSTED.value == "retry_exhausted"
        assert ProbeStatus.UNKNOWN_ERROR.value == "unknown_error"


# ── M6 P0: unverified profiles MUST be able to run the connection probe ─────


class TestUnverifiedProfileProbe:
    """The connection probe is the ONLY path allowed to run for a profile
    whose needs_connection_verification is still True."""

    def test_unverified_profile_connection_probe_succeeds(self):
        """GATE-P0: an unverified but otherwise valid profile must complete a
        REAL probe (200 Chat Completions response) with SUCCESS — and the
        normal invoke() must still refuse it."""
        profile = replace(
            _verified_profile("deepseek"),
            needs_connection_verification=True,
        )
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response())

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS, (
            f"unverified profile probe must succeed, got {result.outcome.value}"
        )
        assert result.error_category is None
        # exactly one request, fixed minimal ping payload
        assert len(transport.calls) == 1, "probe must send exactly one request"
        body = transport.calls[0]["json_body"]
        assert body["messages"] == [{"role": "user", "content": "ping"}]
        assert body.get("stream") is False
        assert body.get("max_tokens") == 1
        serialized = json.dumps(body)
        assert "D:\\" not in serialized and "/home/" not in serialized
        assert "file://" not in serialized
        # no user content / paths / credentials in the probe
        assert "secret" not in serialized.lower()
        # the normal business invoke() must STILL reject the unverified profile
        from src.core.provider_protocol import ProviderRequest
        with pytest.raises(ProviderAdapterConfigurationError, match="verification"):
            adapter.invoke(
                ProviderRequest(request_id="r", task_id="t", extracted_text="hello")
            )
        # the probe must not mutate the immutable profile
        assert profile.needs_connection_verification is True

    def test_unverified_probe_401_auth_error(self):
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(status_code=401, headers={}, json_body={"error": {"message": "Unauthorized"}}, latency_ms=3.0)
        )
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.AUTH_ERROR
        assert result.error_category is ErrorCategory.AUTH

    def test_unverified_probe_403_permission_error(self):
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(status_code=403, headers={}, json_body={"error": {}}, latency_ms=2.0)
        )
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.PERMISSION_ERROR

    def test_unverified_probe_404_model_error(self):
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(status_code=404, headers={}, json_body={}, latency_ms=2.0)
        )
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.MODEL_ERROR

    def test_unverified_probe_429_rate_limited(self):
        from src.providers.openai_compatible import ProviderHTTPError
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(status_code=429, headers={"Retry-After": "0"}, json_body={"error": {}}, latency_ms=1.0)
        )
        result = run_connection_test(adapter)
        assert result.outcome in (ConnectionOutcome.RATE_LIMITED, ConnectionOutcome.RETRY_EXHAUSTED)

    def test_unverified_probe_timeout_network_error(self):
        from src.providers.openai_compatible import ProviderTransportTimeout
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(ProviderTransportTimeout("timed out"))
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.NETWORK_ERROR

    def test_unverified_probe_5xx_retry_exhausted(self):
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.extend([
            TransportResponse(status_code=502, headers={}, json_body={}, latency_ms=1.0),
            TransportResponse(status_code=502, headers={}, json_body={}, latency_ms=1.0),
        ])
        result = run_connection_test(adapter)
        assert result.outcome in (
            ConnectionOutcome.RETRY_EXHAUSTED,
            ConnectionOutcome.NETWORK_ERROR,
            ConnectionOutcome.RESPONSE_ERROR,
        )

    def test_unverified_probe_malformed_response_error(self):
        from src.providers.openai_compatible import ProviderResponseError
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile)
        transport._responses.append(ProviderResponseError("non-JSON body"))
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.RESPONSE_ERROR
        assert result.error_category is ErrorCategory.MALFORMED_RESPONSE

    def test_probe_never_leaks_key_or_raw_exception(self):
        """The key must never appear in result repr / error text, and raw
        transport exceptions (which may carry the key) must be sanitized."""
        from src.providers.openai_compatible import ProviderNetworkError
        profile = replace(_verified_profile("deepseek"), needs_connection_verification=True)
        adapter, transport = _probe_transport(profile, credential="sk-secret-probe-key-999")
        transport._responses.append(
            ProviderNetworkError(f"connection refused while using sk-secret-probe-key-999")
        )
        result = run_connection_test(adapter)
        assert result.outcome is ConnectionOutcome.NETWORK_ERROR
        assert "sk-secret-probe-key-999" not in repr(result)
        assert "sk-secret-probe-key-999" not in result.error_message
        # the probe result keeps the profile unverified
        assert profile.needs_connection_verification is True


# ── M6 P0: probe must accept plain-text responses (no business JSON) ────────


class TestProbePlainTextResponses:
    """The connection probe sends "ping" WITHOUT response_format=json_object,
    so real providers may legally answer with plain text.  The probe parser
    must accept plain text while the BUSINESS parser keeps the strict JSON
    contract."""

    def _unverified_deepseek(self):
        return replace(
            _verified_profile("deepseek"),
            needs_connection_verification=True,
        )

    def _probe(self, transport, profile=None):
        adapter, _ = _probe_transport(profile or self._unverified_deepseek())
        # reuse the same transport
        adapter._transport = transport
        return adapter

    def test_probe_plain_pong_succeeds(self):
        """200 + message.content="pong" → SUCCESS (no JSON required)."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response(content="pong"))

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS, (
            f"plain 'pong' must succeed, got {result.outcome.value}"
        )
        assert result.error_category is None
        assert len(transport.calls) == 1

    def test_probe_plain_chinese_text_succeeds(self):
        """200 + plain Chinese text → SUCCESS."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response(content="连接成功"))

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS

    def test_probe_json_text_still_succeeds(self):
        """200 + JSON text is still accepted by the probe parser."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            _minimal_probe_response(content='{"status":"ok"}')
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS

    def test_probe_length_finish_reason_succeeds(self):
        """max_tokens=1 truncation (finish_reason='length') still proves the
        endpoint, auth, and model are reachable → SUCCESS."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=200,
                headers={},
                json_body={
                    "choices": [
                        {
                            "message": {"content": "po"},
                            "finish_reason": "length",
                        }
                    ],
                    "model": "detected-model",
                    "usage": {"total_tokens": 1},
                },
                latency_ms=5.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.SUCCESS, (
            f"truncated probe (length) must succeed, got {result.outcome.value}"
        )

    def test_probe_missing_choices_response_error(self):
        """200 + no choices → RESPONSE_ERROR."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=200,
                headers={},
                json_body={"model": "detected-model"},
                latency_ms=1.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RESPONSE_ERROR

    def test_probe_missing_message_response_error(self):
        """200 + choice without message → RESPONSE_ERROR."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=200,
                headers={},
                json_body={
                    "choices": [{"finish_reason": "stop"}],
                    "model": "detected-model",
                },
                latency_ms=1.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RESPONSE_ERROR

    def test_probe_empty_content_response_error(self):
        """200 + empty/null content → RESPONSE_ERROR."""
        profile = self._unverified_deepseek()
        adapter, transport = _probe_transport(profile)
        transport._responses.append(
            TransportResponse(
                status_code=200,
                headers={},
                json_body={
                    "choices": [
                        {"message": {"content": ""}, "finish_reason": "stop"}
                    ],
                    "model": "detected-model",
                },
                latency_ms=1.0,
            )
        )

        result = run_connection_test(adapter)

        assert result.outcome is ConnectionOutcome.RESPONSE_ERROR

    def test_business_invoke_still_rejects_plain_text(self):
        """The BUSINESS invoke keeps the strict JSON contract: 200 + content
        "pong" must remain RESPONSE_ERROR for a normal (verified) invoke."""
        from src.core.provider_protocol import ProviderRequest

        profile = _verified_profile("deepseek")
        adapter, transport = _probe_transport(profile)
        transport._responses.append(_minimal_probe_response(content="pong"))

        result = adapter.invoke(
            ProviderRequest(request_id="r", task_id="t", extracted_text="hello")
        )

        assert result.success is False, "business invoke must reject plain text"
        assert result.final_category is ErrorCategory.MALFORMED_RESPONSE
