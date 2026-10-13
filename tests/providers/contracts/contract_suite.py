"""Reusable behavioural contract for every first-phase Provider path."""
from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from src.core.provider_presets import (
    create_custom_provider_profile,
    create_profile_from_preset,
)
from src.core.provider_protocol import (
    ProviderCapabilities,
    ProviderRequest,
    prepare_visual_payload,
)
from src.providers.openai_compatible import (
    OpenAICompatibleAdapter,
    ProviderAdapterConfigurationError,
    TransportResponse,
)
from src.providers.presets import create_adapter
from src.services.retry_policy import ErrorCategory, RetryExecutor, RetryPolicy


class RecordingTransport:
    """Deterministic transport double; it never touches the network."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
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
        if not self.responses:
            raise AssertionError("Unexpected transport call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def success_response(
    *,
    title: str = "Quarterly report",
    model: str = "server-model",
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={},
        json_body={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"dcTitle": title, "dcType": "report"},
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": model,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
        latency_ms=12.5,
    )


def error_response(status_code: int, *, retry_after: str | None = None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return TransportResponse(
        status_code=status_code,
        headers=headers,
        json_body={"error": {"message": "remote failure"}},
        latency_ms=2.0,
    )


def verified_profile(provider_id: str):
    kwargs: dict[str, str] = {"profile_id": f"{provider_id}-profile"}
    if provider_id == "qwen":
        kwargs.update(region="virginia")
    if provider_id in {"zhipu", "kimi"}:
        kwargs.update(model=f"{provider_id}-user-model")
    return replace(
        create_profile_from_preset(provider_id, **kwargs),
        needs_connection_verification=False,
    )


def verified_custom_profile():
    return replace(
        create_custom_provider_profile(
            profile_id="custom-profile",
            display_name="Private compatible endpoint",
            base_url="https://provider.example.test/v1",
            model="custom-model",
            capabilities=ProviderCapabilities(
                text=True,
                vision=True,
                multi_image=True,
                json_mode=True,
            ),
        ),
        needs_connection_verification=False,
    )


def request(*, with_visual: bool = False) -> ProviderRequest:
    visuals = ()
    if with_visual:
        image_bytes = BytesIO()
        Image.new("RGB", (100, 80), (20, 40, 60)).save(
            image_bytes, format="PNG"
        )
        visuals = (
            prepare_visual_payload(
                kind="resized_image",
                mime_type="image/png",
                data=image_bytes.getvalue(),
                width=100,
                height=80,
                source_index=0,
                preprocessing_version="test-v1",
                provenance="image_preprocessor",
            ),
        )
    return ProviderRequest(
        request_id="request-1",
        task_id="task-1",
        extracted_text="Quarterly revenue increased.",
        metadata={"extension": "pdf", "page_count": 3},
        visual_payloads=visuals,
        requested_schema={
            "type": "object",
            "properties": {
                "dcTitle": {"type": "string"},
                "dcType": {"type": "string"},
            },
            "required": ["dcTitle", "dcType"],
            "additionalProperties": False,
        },
        locale="zh-CN",
        correlation_id="corr-1",
    )


class ProviderContract:
    """Subclasses provide one profile and expected auth contract."""

    provider_id = ""
    auth_header = "Authorization"
    auth_value = "Bearer contract-secret"
    supports_visual = False
    expected_url = ""
    expected_response_format = "json_object"

    def make_profile(self):
        return verified_profile(self.provider_id)

    def make_adapter(self, responses):
        transport = RecordingTransport(responses)
        retry = RetryExecutor(
            RetryPolicy(max_retries=2, base_delay=0, max_delay=0),
            sleeper=lambda _delay: None,
        )
        adapter = create_adapter(
            profile=self.make_profile(),
            credential="contract-secret",
            transport=transport,
            retry_executor=retry,
        )
        return adapter, transport

    def test_request_response_usage_contract(self):
        adapter, transport = self.make_adapter([success_response()])

        result = adapter.invoke(request(with_visual=self.supports_visual))

        assert result.success is True
        assert result.total_attempts == 1
        response = result.value
        assert response.fields == {
            "dcTitle": "Quarterly report",
            "dcType": "report",
        }
        assert response.usage["prompt_tokens"] == 11
        assert response.usage["completion_tokens"] == 7
        assert response.usage["total_tokens"] == 18
        assert response.provider_profile_id == self.make_profile().id
        assert response.correlation_id == "corr-1"

        assert len(transport.calls) == 1
        sent = transport.calls[0]
        assert sent["url"] == self.expected_url
        assert sent["headers"][self.auth_header] == self.auth_value
        forbidden_header = (
            "api-key" if self.auth_header == "Authorization" else "Authorization"
        )
        assert forbidden_header not in sent["headers"]
        assert "contract-secret" not in json.dumps(sent["json_body"])
        assert sent["json_body"]["model"] == self.make_profile().model
        assert sent["json_body"]["stream"] is False
        assert sent["json_body"]["messages"][0]["role"] == "system"
        assert "JSON" in sent["json_body"]["messages"][0]["content"]
        assert (
            sent["json_body"]["response_format"]["type"]
            == self.expected_response_format
        )
        serialized = json.dumps(sent["json_body"])
        assert "Quarterly revenue increased." in serialized
        assert "page_count" in serialized
        assert "source_path" not in serialized
        if self.supports_visual:
            assert "data:image/png;base64," in serialized

    def test_auth_error_is_classified_and_not_retried(self):
        adapter, transport = self.make_adapter([error_response(401)])

        result = adapter.invoke(request())

        assert result.success is False
        assert result.final_category is ErrorCategory.AUTH
        assert result.total_attempts == 1
        assert len(transport.calls) == 1
        assert "contract-secret" not in str(result.final_error)

    def test_rate_limit_retries_same_profile_only(self):
        adapter, transport = self.make_adapter(
            [error_response(429, retry_after="0"), success_response()]
        )

        result = adapter.invoke(request())

        assert result.success is True
        assert result.total_attempts == 2
        assert result.attempts[0].category is ErrorCategory.RATE_LIMIT
        assert {call["url"] for call in transport.calls} == {
            adapter.chat_completions_url
        }

    def test_malformed_response_is_bounded_and_classified(self):
        malformed = TransportResponse(
            status_code=200,
            headers={},
            json_body={"choices": []},
            latency_ms=1.0,
        )
        adapter, transport = self.make_adapter([malformed, malformed])

        result = adapter.invoke(request())

        assert result.success is False
        assert result.final_category is ErrorCategory.MALFORMED_RESPONSE
        assert result.total_attempts == 2
        assert len(transport.calls) == 2

    def test_unverified_profile_fails_before_transport(self):
        transport = RecordingTransport([success_response()])
        profile = replace(
            self.make_profile(),
            needs_connection_verification=True,
        )
        adapter = OpenAICompatibleAdapter(
            profile=profile,
            credential="contract-secret",
            transport=transport,
        )

        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(request())

        assert transport.calls == []
