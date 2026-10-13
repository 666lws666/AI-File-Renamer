import base64
import json
from dataclasses import replace
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from PIL import Image

from src.core.provider_protocol import ProviderCapabilities, prepare_visual_payload
from src.providers.openai_compatible import (
    ProviderAdapterConfigurationError,
    ProviderNetworkError,
    ProviderResponseError,
    TransportResponse,
    UrllibJsonTransport,
    _NoRedirectHandler,
)
from src.providers.presets import create_adapter
from src.services.retry_policy import ErrorCategory

from .contract_suite import (
    ProviderContract,
    RecordingTransport,
    error_response,
    request,
    success_response,
    verified_custom_profile,
    verified_profile,
)


class TestCustomProviderContract(ProviderContract):
    provider_id = "custom"
    expected_url = "https://provider.example.test/v1/chat/completions"
    supports_visual = True

    def make_profile(self):
        return verified_custom_profile()

    def test_permission_error_is_not_retried(self):
        adapter, transport = self.make_adapter([error_response(403)])

        result = adapter.invoke(request())

        assert result.success is False
        assert result.final_category is ErrorCategory.PERMISSION
        assert result.total_attempts == 1
        assert len(transport.calls) == 1

    def test_server_error_and_timeout_are_bounded_retries(self):
        adapter, transport = self.make_adapter(
            [
                error_response(503),
                TimeoutError("socket timed out"),
                success_response(),
            ]
        )

        result = adapter.invoke(request())

        assert result.success is True
        assert [attempt.category for attempt in result.attempts] == [
            ErrorCategory.SERVER,
            ErrorCategory.TIMEOUT,
            None,
        ]
        assert len(transport.calls) == 3

    @pytest.mark.parametrize("legacy_id", ["openai", " CLAUDE "])
    def test_public_adapter_factory_rejects_legacy_provider(self, legacy_id):
        profile = replace(
            verified_custom_profile(),
            provider_id=legacy_id,
        )
        transport = RecordingTransport([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            create_adapter(
                profile=profile,
                credential="contract-secret",
                transport=transport,
            )

        assert transport.calls == []

    def test_profile_timeout_is_a_hard_upper_bound(self):
        profile = replace(verified_custom_profile(), timeout_seconds=5)
        transport = RecordingTransport([success_response()])
        adapter = create_adapter(
            profile=profile,
            credential="contract-secret",
            transport=transport,
        )

        result = adapter.invoke(request())

        assert result.success is True
        assert transport.calls[0]["timeout"] == 5

    def test_transport_exception_cannot_leak_credential(self):
        adapter, _transport = self.make_adapter(
            [ConnectionError("network failed with contract-secret header")]
        )

        result = adapter.invoke(request())

        assert result.success is False
        assert "contract-secret" not in str(result.final_error)
        assert all(
            "contract-secret" not in attempt.error_message
            for attempt in result.attempts
        )

    def test_adapter_error_from_transport_is_sanitized_before_retry_log(self):
        adapter, _transport = self.make_adapter(
            [
                ProviderNetworkError("contract-secret plus extracted body")
                for _ in range(3)
            ]
        )

        result = adapter.invoke(request())

        assert result.success is False
        assert result.final_category is ErrorCategory.NETWORK
        assert "contract-secret" not in str(result.final_error)
        assert all(
            "contract-secret" not in attempt.error_message
            for attempt in result.attempts
        )

    @pytest.mark.parametrize(
        "forged_profile",
        [
            replace(verified_custom_profile(), provider_id="deepseek"),
            replace(
                verified_profile("deepseek"),
                base_url="https://provider.example.test/v1",
            ),
            replace(verified_profile("deepseek"), auth_scheme="api_key_header"),
            replace(
                verified_profile("deepseek"),
                model="deepseek-v4-pro",
                capabilities=ProviderCapabilities(
                    text=True,
                    vision=True,
                    json_mode=True,
                ),
            ),
        ],
    )
    def test_official_provider_identity_cannot_use_custom_wire_settings(
        self, forged_profile
    ):
        transport = RecordingTransport([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            create_adapter(
                profile=forged_profile,
                credential="contract-secret",
                transport=transport,
            )

        assert transport.calls == []

    def test_schema_violation_retries_and_records_billed_attempt_usage(self):
        invalid = TransportResponse(
            status_code=200,
            headers={},
            json_body={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "dcTitle": "Quarterly report",
                                    "dcType": "report",
                                    "echo": "must-not-cross-boundary",
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 9},
            },
            latency_ms=1.0,
        )
        adapter, _transport = self.make_adapter([invalid, success_response()])

        result = adapter.invoke(request())

        assert result.success is True
        assert result.total_attempts == 2
        assert result.attempts[0].category is ErrorCategory.MALFORMED_RESPONSE
        assert result.attempts[0].usage == {"total_tokens": 9}
        assert "echo" not in result.value.fields

    def test_complete_video_cannot_masquerade_as_prepared_keyframe(self):
        disguised_video = prepare_visual_payload(
            kind="video_keyframe",
            mime_type="image/jpeg",
            data=b"\x00\x00\x00\x18ftypmp42complete-video-bytes",
            width=640,
            height=360,
            source_index=0,
            preprocessing_version="keyframes-v1",
            provenance="keyframe_extractor",
        )
        unsafe_request = replace(request(), visual_payloads=(disguised_video,))
        adapter, transport = self.make_adapter([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(unsafe_request)

        assert transport.calls == []

    def test_image_polyglot_with_appended_video_bytes_is_rejected(self):
        valid = request(with_visual=True).visual_payloads[0]
        polyglot = prepare_visual_payload(
            kind="video_keyframe",
            mime_type=valid.mime_type,
            data=valid.data + b"\x00\x00\x00\x18ftypmp42complete-video",
            width=valid.width,
            height=valid.height,
            source_index=0,
            preprocessing_version="keyframes-v1",
            provenance="keyframe_extractor",
        )
        unsafe_request = replace(request(), visual_payloads=(polyglot,))
        adapter, transport = self.make_adapter([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(unsafe_request)

        assert transport.calls == []

    @pytest.mark.parametrize(
        "field_schema,bad_content,good_content",
        [
            ({"enum": [1]}, '{"x": true}', '{"x": 1}'),
            (
                {"type": "number", "maximum": 10},
                '{"x": NaN}',
                '{"x": 5}',
            ),
        ],
    )
    def test_schema_uses_strict_json_values_and_rejects_nonfinite_numbers(
        self, field_schema, bad_content, good_content
    ):
        schema = {
            "type": "object",
            "properties": {"x": field_schema},
            "required": ["x"],
            "additionalProperties": False,
        }

        def response(content):
            return TransportResponse(
                status_code=200,
                headers={},
                json_body={
                    "choices": [
                        {
                            "message": {"content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"total_tokens": 3},
                },
            )

        adapter, _transport = self.make_adapter(
            [response(bad_content), response(good_content)]
        )
        schema_request = replace(request(), requested_schema=schema)

        result = adapter.invoke(schema_request)

        assert result.success is True
        assert result.total_attempts == 2
        assert result.attempts[0].category is ErrorCategory.MALFORMED_RESPONSE
        assert result.attempts[0].usage == {"total_tokens": 3}

    def test_structured_enum_uses_json_container_semantics(self):
        schema_request = replace(
            request(),
            requested_schema={
                "type": "object",
                "properties": {
                    "x": {"enum": [{"a": [1, True]}]},
                },
                "required": ["x"],
                "additionalProperties": False,
            },
        )
        valid = TransportResponse(
            status_code=200,
            headers={},
            json_body={
                "choices": [
                    {
                        "message": {"content": '{"x":{"a":[1,true]}}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
        adapter, _transport = self.make_adapter([valid])

        result = adapter.invoke(schema_request)

        assert result.success is True
        assert result.total_attempts == 1

    @pytest.mark.parametrize(
        "field_schema",
        [
            {"enum": [float("nan")]},
            {"type": "number", "maximum": float("inf")},
        ],
    )
    def test_nonfinite_schema_definition_fails_before_transport(
        self, field_schema
    ):
        schema_request = replace(
            request(),
            requested_schema={
                "type": "object",
                "properties": {"x": field_schema},
                "required": ["x"],
                "additionalProperties": False,
            },
        )
        adapter, transport = self.make_adapter([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(schema_request)

        assert transport.calls == []

    def test_jpeg_polyglot_is_reencoded_before_upload(self):
        jpeg = BytesIO()
        Image.new("RGB", (32, 24), (120, 80, 40)).save(jpeg, format="JPEG")
        original = jpeg.getvalue() + b"complete-mp4-ftyp-payload" + b"\xff\xd9"
        payload = prepare_visual_payload(
            kind="video_keyframe",
            mime_type="image/jpeg",
            data=original,
            width=32,
            height=24,
            source_index=0,
            preprocessing_version="keyframes-v1",
            provenance="keyframe_extractor",
        )
        adapter, transport = self.make_adapter([success_response()])

        result = adapter.invoke(replace(request(), visual_payloads=(payload,)))

        assert result.success is True
        data_url = transport.calls[0]["json_body"]["messages"][1]["content"][1][
            "image_url"
        ]["url"]
        uploaded = base64.b64decode(data_url.split(",", 1)[1])
        assert b"complete-mp4-ftyp-payload" not in uploaded
        assert uploaded != original
        with Image.open(BytesIO(uploaded)) as image:
            assert image.size == (32, 24)
            image.verify()


def test_non_json_http_error_preserves_status_for_retry_classification():
    headers = Message()
    headers["Content-Type"] = "text/html"
    http_error = HTTPError(
        "https://provider.example.test/v1/chat/completions",
        401,
        "Unauthorized",
        headers,
        BytesIO(b"<html>unauthorized</html>"),
    )

    def fail_request(*_args, **_kwargs):
        raise http_error

    response = UrllibJsonTransport(opener=fail_request).send(
        url="https://provider.example.test/v1/chat/completions",
        headers={"Authorization": "Bearer contract-secret"},
        json_body={"model": "test", "messages": []},
        timeout=5,
    )

    assert response.status_code == 401
    assert response.json_body == {}


def test_non_json_401_remains_auth_and_is_not_retried_through_adapter():
    calls = []

    def unauthorized(_request, **_kwargs):
        calls.append(1)
        headers = Message()
        raise HTTPError(
            "https://provider.example.test/v1/chat/completions",
            401,
            "Unauthorized",
            headers,
            BytesIO(b"<html>unauthorized</html>"),
        )

    adapter = create_adapter(
        profile=verified_custom_profile(),
        credential="contract-secret",
        transport=UrllibJsonTransport(opener=unauthorized),
    )

    result = adapter.invoke(request())

    assert result.success is False
    assert result.final_category is ErrorCategory.AUTH
    assert result.total_attempts == 1
    assert calls == [1]


def test_redirect_handler_never_creates_a_followup_request():
    original = Request(
        "https://provider.example.test/v1/chat/completions",
        headers={"Authorization": "Bearer contract-secret"},
    )
    headers = Message()
    headers["Location"] = "https://attacker.example.test/collect"

    redirected = _NoRedirectHandler().redirect_request(
        original,
        None,
        302,
        "Found",
        headers,
        "https://attacker.example.test/collect",
    )

    assert redirected is None


def test_transport_rejects_oversized_success_response_before_json_decode():
    class OversizedResponse:
        status = 200
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(size):
            return b"x" * size

    transport = UrllibJsonTransport(
        opener=lambda *_args, **_kwargs: OversizedResponse(),
        max_response_bytes=32,
    )

    with pytest.raises(ProviderResponseError, match="size limit"):
        transport.send(
            url="https://provider.example.test/v1/chat/completions",
            headers={"Authorization": "Bearer contract-secret"},
            json_body={"model": "test", "messages": []},
            timeout=5,
        )
