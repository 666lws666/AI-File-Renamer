"""Exact-model capabilities; never infer image support from a provider name."""
import pytest

from src.core.provider_presets import create_profile_from_preset, get_provider_preset

VISION = "deepseek-v4-flash-vision-exp"


@pytest.mark.parametrize("model,vision,json_mode", [
    (VISION, True, True),
    ("deepseek-flash", True, True),
    ("deepseek-v4-flash", True, True),
    ("deepseek-v4-pro", False, True),
    ("deepseek-v4-flash-vision-exp-other", False, False),
])
def test_exact_model_capabilities(model, vision, json_mode):
    profile = create_profile_from_preset("deepseek", profile_id="deepseek", model=model)
    assert profile.capabilities.text
    assert profile.capabilities.vision is vision
    assert profile.capabilities.multi_image is vision
    assert profile.capabilities.json_mode is json_mode
    assert not profile.capabilities.json_schema
    assert profile.needs_connection_verification


def test_default_uses_current_multimodal_flash_without_rewriting_explicit_config():
    from src.models.app_config import AppConfig
    assert get_provider_preset("deepseek").default_model == "deepseek-flash"
    assert create_profile_from_preset("deepseek", profile_id="deepseek").capabilities.vision
    assert AppConfig().model == "deepseek-flash"
    assert AppConfig(model="deepseek-v4-pro").model == "deepseek-v4-pro"
