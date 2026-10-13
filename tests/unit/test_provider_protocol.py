"""M3 Task 2: Safe Provider Protocol tests."""
import json, pytest
from src.core.provider_protocol import (
    ProviderCapabilities,
    PreparedVisualPayload,
    ProviderRequest,
    ProviderResponse,
    prepare_visual_payload,
)
from src.core.provider_profile import ProviderProfile

def test_capabilities_all_fields():
    pc = ProviderCapabilities(text=True, vision=True, json_mode=True)
    assert pc.text and pc.vision and pc.json_mode
    assert not pc.json_schema

def test_capabilities_immutable():
    pc = ProviderCapabilities(text=True)
    with pytest.raises(Exception): pc.text = False

def test_visual_payload_direct_constructor_is_closed():
    with pytest.raises(TypeError):
        PreparedVisualPayload(
            "resized_image", "image/png", b"fake", "sha", 100, 100, 4
        )


def test_visual_payload_valid_through_preprocessing_boundary():
    vp = prepare_visual_payload(
        kind="resized_image",
        mime_type="image/png",
        data=b"fake",
        width=100,
        height=100,
        source_index=0,
        preprocessing_version="resize-v1",
        provenance="local:image-resizer",
    )
    assert vp.kind == "resized_image"
    assert vp.byte_size == 4
    assert len(vp.content_digest) == 64


def test_visual_payload_invalid_kind():
    with pytest.raises(ValueError):
        prepare_visual_payload(
            kind="raw_video", mime_type="image/png", data=b"x",
            width=1, height=1, source_index=0,
            preprocessing_version="v1", provenance="local:test",
        )


def test_visual_payload_invalid_mime():
    with pytest.raises(ValueError):
        prepare_visual_payload(
            kind="resized_image", mime_type="video/mp4", data=b"x",
            width=1, height=1, source_index=0,
            preprocessing_version="v1", provenance="local:test",
        )


def test_visual_payload_pdf_rejected():
    with pytest.raises(ValueError):
        prepare_visual_payload(
            kind="rendered_scan_page", mime_type="application/pdf", data=b"x",
            width=1, height=1, source_index=0,
            preprocessing_version="v1", provenance="local:test",
        )

def test_request_no_source_path():
    with pytest.raises(ValueError):
        ProviderRequest("r1","t1", metadata={"source_path":"/tmp/a.pdf"})

def test_request_no_file_handle():
    with pytest.raises(TypeError):
        ProviderRequest("r1","t1", visual_payloads=(b"raw_bytes",))

def test_request_visual_only_prepared():
    vp = prepare_visual_payload(
        kind="resized_image", mime_type="image/png", data=b"x",
        width=10, height=10, source_index=0,
        preprocessing_version="v1", provenance="local:test",
    )
    r = ProviderRequest("r1", "t1", visual_payloads=(vp,))
    assert len(r.visual_payloads) == 1

def test_request_nested_metadata_path_rejected():
    with pytest.raises(ValueError):
        ProviderRequest("r1","t1", metadata={"nested":{"path":"/tmp/file.pdf"}})

def test_profile_serialization_no_key():
    p = ProviderProfile(id="test", display_name="Test", base_url="https://api.example.com")
    d = p.to_safe_dict()
    assert "api_key" not in d
    assert "token" not in d
    assert "authorization" not in d

def test_profile_serialization_json():
    p = ProviderProfile(id="test", display_name="Test", base_url="https://api.example.com")
    j = json.dumps(p.to_safe_dict())
    assert "api_key" not in j

def test_response_no_request_body():
    r = ProviderResponse(fields={"title":"x"}, usage={"tokens":10})
    d = r.to_safe_dict()
    assert "request_body" not in d
    assert "api_key" not in d

def test_request_rejects_path_object():
    from pathlib import Path
    with pytest.raises((TypeError, ValueError)):
        ProviderRequest("r1", "t1", metadata={"file": Path("C:/private/a.txt")})


def test_request_rejects_path_key_even_when_value_is_not_path_like():
    with pytest.raises(ValueError):
        ProviderRequest("r1", "t1", metadata={"source_path": "redacted"})


def test_request_rejects_windows_path_without_known_extension():
    with pytest.raises(ValueError):
        ProviderRequest("r1", "t1", metadata={"note": r"C:\\private\\payload"})


def test_request_rejects_raw_bytes_anywhere_in_metadata():
    with pytest.raises(TypeError):
        ProviderRequest("r1", "t1", metadata={"nested": [{"blob": b"raw"}]})


def test_request_rejects_secret_like_metadata_keys():
    for key in ("api_key", "authorization", "auth_token", "password", "secret"):
        with pytest.raises(ValueError):
            ProviderRequest("r1", "t1", metadata={key: "redacted"})


def test_request_metadata_is_recursively_immutable():
    request = ProviderRequest(
        "r1", "t1", metadata={"camera": {"iso": 100}, "tags": ["a", "b"]}
    )
    with pytest.raises(TypeError):
        request.metadata["camera"] = {}
    with pytest.raises(TypeError):
        request.metadata["camera"]["iso"] = 200
    assert request.metadata["tags"] == ("a", "b")


def test_response_rejects_secret_or_request_echo_fields():
    for key in ("api_key", "authorization", "request_body"):
        with pytest.raises(ValueError):
            ProviderResponse(fields={key: "redacted"})


def test_profile_is_immutable_and_has_no_secret_field():
    p = ProviderProfile(id="test", display_name="Test")
    with pytest.raises((AttributeError, TypeError)):
        p.model = "changed"
    assert "api_key" not in p.__dataclass_fields__


def test_factory_records_digest_size_and_provenance():
    import hashlib

    vp = prepare_visual_payload(
        kind="video_keyframe", mime_type="image/jpeg", data=b"frame",
        width=640, height=360, source_index=4,
        preprocessing_version="keyframes-v2", provenance="local:ffmpeg",
    )
    assert vp.content_digest == hashlib.sha256(b"frame").hexdigest()
    assert vp.byte_size == len(b"frame")
    assert vp.provenance == "local:ffmpeg"


def test_request_rejects_file_handle_and_schema_secrets():
    import io

    with pytest.raises(TypeError):
        ProviderRequest("r1", "t1", metadata={"stream": io.BytesIO(b"raw")})
    with pytest.raises(ValueError):
        ProviderRequest(
            "r1", "t1", requested_schema={"authorization": {"type": "string"}}
        )


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://user:password@example.com/v1",
        "https://example.com/v1?api_key=secret",
        "https://example.com/v1#token=secret",
    ],
)
def test_profile_rejects_credentials_embedded_in_base_url(unsafe_url):
    with pytest.raises(ValueError):
        ProviderProfile(id="unsafe", display_name="Unsafe", base_url=unsafe_url)


@pytest.mark.parametrize(
    "secret_key",
    ["access_token", "auth_token", "x-api-key", "x_api_key", "client_secret"],
)
def test_profile_rejects_common_secret_aliases_in_base_url(secret_key):
    with pytest.raises(ValueError, match="secret"):
        ProviderProfile(
            id="unsafe",
            display_name="Unsafe",
            base_url=f"https://example.invalid/v1?{secret_key}=top-secret",
        )


@pytest.mark.parametrize("secret_key", ["key", "credential", "signature", "sig"])
def test_profile_rejects_generic_secret_query_keys(secret_key):
    with pytest.raises(ValueError, match="secret"):
        ProviderProfile(
            id="unsafe",
            display_name="Unsafe",
            base_url=f"https://example.invalid/v1?{secret_key}=top-secret",
        )


def test_profile_capabilities_must_be_provider_capabilities():
    with pytest.raises(TypeError, match="capabilities"):
        ProviderProfile(
            id="unsafe",
            display_name="Unsafe",
            base_url="https://example.invalid/v1",
            capabilities={"text": True, "api_key": "secret"},
        )


@pytest.mark.parametrize(
    "unsafe_url",
    ["file:///tmp/provider", "example.invalid/v1", "https:///missing-host"],
)
def test_profile_rejects_non_http_or_non_absolute_base_url(unsafe_url):
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        ProviderProfile(id="unsafe", display_name="Unsafe", base_url=unsafe_url)


@pytest.mark.parametrize("width,height,data,source_index", [
    (0, 10, b"x", 0),
    (10, 0, b"x", 0),
    (10, 10, b"", 0),
    (10, 10, b"x", -1),
])
def test_factory_rejects_invalid_preprocessing_output(
    width, height, data, source_index
):
    with pytest.raises(ValueError):
        prepare_visual_payload(
            kind="resized_image", mime_type="image/png", data=data,
            width=width, height=height, source_index=source_index,
            preprocessing_version="v1", provenance="local:test",
        )
