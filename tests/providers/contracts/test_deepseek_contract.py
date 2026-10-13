import pytest
import base64
from dataclasses import replace
from io import BytesIO
from PIL import Image
from src.core.provider_presets import create_profile_from_preset
from src.core.provider_protocol import prepare_visual_payload
from src.providers.presets import create_adapter

from src.providers.openai_compatible import ProviderAdapterConfigurationError

from .contract_suite import ProviderContract, request, success_response


class TestDeepSeekContract(ProviderContract):
    provider_id = "deepseek"
    supports_visual = True
    expected_url = "https://api.deepseek.com/chat/completions"

    def test_pro_override_rejects_visual_payload_before_transport(self):
        adapter, transport = self.make_adapter([success_response()])

        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(replace(request(with_visual=True), model="deepseek-v4-pro"))

        assert transport.calls == []


class TestDeepSeekVisionContract(ProviderContract):
    provider_id = "deepseek"
    supports_visual = True
    expected_url = "https://api.deepseek.com/chat/completions"

    def make_profile(self):
        return replace(create_profile_from_preset(
            "deepseek", profile_id="deepseek-vision",
            model="deepseek-flash",
        ), needs_connection_verification=False)

    @pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"])
    def test_prepared_image_roundtrip_wire_format(self, model):
        adapter, transport = self.make_adapter([success_response()])
        assert adapter.invoke(replace(request(with_visual=True), model=model)).success
        body = transport.calls[0]["json_body"]
        assert body["model"] == model
        assert body["response_format"] == {"type": "json_object"}
        user = body["messages"][1]
        assert user["role"] == "user"
        url = user["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            assert image.size == (100, 80)

    def test_text_model_override_cannot_receive_images(self):
        adapter, transport = self.make_adapter([success_response()])
        with pytest.raises(ProviderAdapterConfigurationError):
            adapter.invoke(replace(request(with_visual=True), model="deepseek-v4-pro"))
        assert not transport.calls

    @pytest.mark.parametrize("model", ["deepseek-v4-pro", "unknown-vision-model"])
    def test_unverified_model_cannot_inherit_vision_capability(self, model):
        profile = replace(self.make_profile(), model=model)
        with pytest.raises((ProviderAdapterConfigurationError, ValueError)):
            create_adapter(profile=profile, credential="synthetic-key")

    def test_official_capabilities_cannot_be_redirected_to_a_gateway(self):
        profile = replace(self.make_profile(), base_url="https://gateway.example.invalid/v1")
        with pytest.raises(ProviderAdapterConfigurationError, match="endpoint"):
            create_adapter(profile=profile, credential="synthetic-key")

    @pytest.mark.parametrize("kind,count", [("rendered_scan_page", 2), ("video_keyframe", 8)])
    def test_scan_pages_and_video_frames_use_only_prepared_images(self, kind, count):
        original = request(with_visual=True)
        payload = original.visual_payloads[0]
        visuals = tuple(prepare_visual_payload(
            kind=kind, mime_type="image/png", data=payload.data,
            width=100, height=80, source_index=i,
            preprocessing_version="test-v1", provenance="local-preprocessing",
        ) for i in range(count))
        adapter, transport = self.make_adapter([success_response()])
        assert adapter.invoke(replace(original, visual_payloads=visuals)).success
        content = transport.calls[0]["json_body"]["messages"][1]["content"]
        assert len(content) == count + 1
        assert all(block["image_url"]["url"].startswith("data:image/png;base64,") for block in content[1:])

    def test_oversized_image_side_rejected_before_transport(self):
        stream = BytesIO()
        Image.new("RGB", (8193, 1)).save(stream, format="PNG")
        payload = prepare_visual_payload(kind="resized_image", mime_type="image/png",
            data=stream.getvalue(), width=8193, height=1, source_index=0,
            preprocessing_version="test-v1", provenance="image_preprocessor")
        adapter, transport = self.make_adapter([success_response()])
        with pytest.raises(ProviderAdapterConfigurationError, match="dimensions"):
            adapter.invoke(replace(request(), visual_payloads=(payload,)))
        assert not transport.calls
