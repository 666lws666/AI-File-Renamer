"""M3 Task 5: evidence-backed first-phase Provider presets."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path

import pytest

from src.core.provider_presets import (
    FIRST_PHASE_PROVIDER_IDS,
    ProviderPresetError,
    create_custom_provider_profile,
    create_profile_from_preset,
    get_provider_preset,
    list_provider_presets,
)
from src.core.provider_protocol import ProviderCapabilities


def test_five_presets_loadable_in_stable_order():
    presets = list_provider_presets()
    assert tuple(preset.id for preset in presets) == (
        "deepseek",
        "qwen",
        "mimo",
        "zhipu",
        "kimi",
    )
    assert FIRST_PHASE_PROVIDER_IDS == tuple(preset.id for preset in presets)
    assert len(presets) == 5


def test_qwen_marked_recommended_not_forced():
    presets = list_provider_presets()
    recommended = [preset.id for preset in presets if preset.recommended]
    assert recommended == ["qwen"]
    assert all(preset.selectable for preset in presets)
    assert create_profile_from_preset(
        "deepseek", profile_id="my-deepseek"
    ).id == "my-deepseek"


def test_no_openai_or_anthropic_brand_preset():
    identifiers = {preset.id.casefold() for preset in list_provider_presets()}
    names = " ".join(preset.display_name for preset in list_provider_presets()).casefold()
    assert "openai" not in identifiers
    assert "anthropic" not in identifiers
    assert "claude" not in identifiers
    assert "openai" not in names
    assert "anthropic" not in names
    assert "claude" not in names


def test_preset_defaults_match_verified_evidence_without_invented_models():
    deepseek = get_provider_preset("deepseek")
    assert deepseek.base_url == "https://api.deepseek.com"
    assert deepseek.default_model == "deepseek-flash"
    assert deepseek.capabilities.vision is True
    assert deepseek.capabilities.multi_image is True

    qwen = get_provider_preset("qwen")
    assert qwen.base_url_mode == "REGIONAL"
    assert qwen.default_model == "qwen3.6-flash"
    assert qwen.capabilities.vision is True
    assert qwen.capabilities.json_mode is True
    assert qwen.capabilities.json_schema is False
    assert set(qwen.regional_endpoints) == {
        "beijing",
        "singapore",
        "tokyo",
        "frankfurt",
        "virginia",
    }

    mimo = get_provider_preset("mimo")
    assert mimo.base_url == "https://api.xiaomimimo.com/v1"
    assert mimo.default_model == "mimo-v2.5"
    assert mimo.auth_scheme == "api_key_header"
    mimo_profile = create_profile_from_preset("mimo", profile_id="mimo-main")
    assert mimo_profile.provider_id == "mimo"
    assert mimo_profile.auth_scheme == "api_key_header"

    zhipu = get_provider_preset("zhipu")
    kimi = get_provider_preset("kimi")
    assert zhipu.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert kimi.base_url == "https://api.moonshot.ai/v1"
    assert zhipu.default_model == ""
    assert kimi.default_model == ""
    assert zhipu.requires_user_model is True
    assert kimi.requires_user_model is True


def test_preset_metadata_matches_committed_m3a_verification_evidence():
    evidence_path = (
        Path(__file__).parents[2]
        / "docs"
        / "implementation"
        / "reports"
        / "M3_PROVIDER_CAPABILITY_VERIFICATION.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_by_id = {
        item["provider_id"]: item for item in evidence["providers"]
    }

    assert set(evidence_by_id) == set(FIRST_PHASE_PROVIDER_IDS)
    for preset in list_provider_presets():
        source = evidence_by_id[preset.id]
        assert preset.base_url_mode == source["base_url_mode"]
        assert (preset.base_url or None) == source["base_url"]
        assert preset.verification_status == source["conclusion"]
        assert preset.verification_date == source["pricing"]["verification_date"]
        assert preset.source_urls == tuple(source["official_sources"])
        assert preset.pricing_status == source["pricing"]["status"]
        assert asdict(preset.capabilities) == source["capabilities"]
        if preset.id == "qwen":
            assert dict(preset.regional_endpoints) == source["regional_endpoints"]
        if preset.pricing_status == "VERIFIED":
            assert preset.pricing_currency == source["pricing"]["currency"]
            assert preset.pricing_unit == source["pricing"]["unit"]
            assert {
                model: dict(prices)
                for model, prices in preset.verified_prices.items()
            } == source["pricing"]["models"]


def test_unknown_prices_are_not_fabricated():
    for provider_id in FIRST_PHASE_PROVIDER_IDS:
        preset = get_provider_preset(provider_id)
        assert preset.pricing_status == "UNKNOWN"
        assert preset.verified_prices == {}


def test_preset_records_are_immutable():
    preset = get_provider_preset("qwen")
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        preset.default_model = "changed"
    with pytest.raises(TypeError):
        preset.regional_endpoints["singapore"] = "https://attacker.invalid"


def test_regional_preset_requires_and_resolves_supported_region():
    with pytest.raises(ProviderPresetError, match="region"):
        create_profile_from_preset("qwen", profile_id="qwen-main")
    with pytest.raises(ProviderPresetError, match="workspace"):
        create_profile_from_preset(
            "qwen", profile_id="qwen-main", region="singapore"
        )

    profile = create_profile_from_preset(
        "qwen",
        profile_id="qwen-main",
        region="singapore",
        workspace_id="workspace-123",
    )
    assert profile.base_url == (
        "https://workspace-123.ap-southeast-1.maas.aliyuncs.com/"
        "compatible-mode/v1"
    )
    assert profile.region == "singapore"
    assert profile.workspace_id == "workspace-123"
    assert profile.needs_connection_verification is True


@pytest.mark.parametrize("provider_id", ["deepseek", "qwen", "mimo", "zhipu", "kimi"])
def test_official_preset_cannot_override_verified_endpoint(provider_id):
    kwargs = {}
    if provider_id == "qwen":
        kwargs = {"region": "singapore", "workspace_id": "workspace-123"}
    if get_provider_preset(provider_id).requires_user_model:
        kwargs["model"] = "user-confirmed-model"
    with pytest.raises(ProviderPresetError, match="Custom"):
        create_profile_from_preset(
            provider_id,
            profile_id=f"{provider_id}-main",
            base_url="https://attacker.invalid/v1",
            **kwargs,
        )


def test_fixed_preset_with_unverified_model_requires_user_model():
    with pytest.raises(ProviderPresetError, match="model"):
        create_profile_from_preset("kimi", profile_id="kimi-main")
    profile = create_profile_from_preset(
        "kimi", profile_id="kimi-main", model="user-confirmed-model"
    )
    assert profile.model == "user-confirmed-model"


def test_unverified_mimo_model_does_not_inherit_model_specific_capabilities():
    profile = create_profile_from_preset(
        "mimo", profile_id="mimo-custom-model", model="unverified-model"
    )
    assert profile.capabilities == ProviderCapabilities(text=True)
    assert profile.needs_connection_verification is True


def test_custom_provider_requires_user_configuration_and_starts_unverified():
    profile = create_custom_provider_profile(
        profile_id="custom-main",
        display_name="My Company Gateway",
        base_url="https://ai.example.invalid/v1",
        model="company-model",
    )
    assert profile.base_url_mode == "USER_CONFIGURED"
    assert profile.protocol_kind == "openai_compatible"
    assert profile.capabilities == ProviderCapabilities(text=True)
    assert profile.needs_connection_verification is True
    assert profile.credential_account_id == ""


@pytest.mark.parametrize(
    ("profile_id", "display_name", "base_url", "model", "message"),
    [
        ("", "Custom", "https://example.invalid/v1", "model", "profile"),
        ("custom", "", "https://example.invalid/v1", "model", "name"),
        ("custom", "Custom", "", "model", "base"),
        ("custom", "Custom", "https://example.invalid/v1", "", "model"),
    ],
)
def test_custom_provider_rejects_incomplete_configuration(
    profile_id, display_name, base_url, model, message
):
    with pytest.raises(ProviderPresetError, match=message):
        create_custom_provider_profile(
            profile_id=profile_id,
            display_name=display_name,
            base_url=base_url,
            model=model,
        )


@pytest.mark.parametrize(
    "base_url",
    ["file:///tmp/provider", "provider.example.invalid/v1", "https:///missing-host"],
)
def test_custom_provider_rejects_unsafe_base_url(base_url):
    with pytest.raises(ProviderPresetError, match=r"HTTP\(S\)"):
        create_custom_provider_profile(
            profile_id="custom",
            display_name="Custom",
            base_url=base_url,
            model="model",
        )


def test_custom_provider_rejects_remote_plaintext_http_but_allows_loopback():
    with pytest.raises(ProviderPresetError, match="HTTPS"):
        create_custom_provider_profile(
            profile_id="remote",
            display_name="Remote",
            base_url="http://evil.example/v1",
            model="model",
        )
    loopback = create_custom_provider_profile(
        profile_id="local",
        display_name="Local",
        base_url="http://127.0.0.1:8000/v1",
        model="model",
    )
    assert loopback.base_url == "http://127.0.0.1:8000/v1"


def test_custom_capabilities_must_be_typed_and_cannot_smuggle_secrets():
    capabilities = {"text": True, "api_key": "secret"}
    with pytest.raises((ProviderPresetError, TypeError), match="capabilities"):
        create_custom_provider_profile(
            profile_id="custom",
            display_name="Custom",
            base_url="https://example.invalid/v1",
            model="model",
            capabilities=capabilities,
        )


@pytest.mark.parametrize("profile_id", ["a/b", "a:b", "bad\nid"])
def test_profile_id_must_be_canonical(profile_id):
    with pytest.raises(ProviderPresetError, match="profile id"):
        create_custom_provider_profile(
            profile_id=profile_id,
            display_name="Custom",
            base_url="https://example.invalid/v1",
            model="model",
        )


def test_non_applicable_region_or_workspace_is_rejected():
    with pytest.raises(ProviderPresetError, match="region"):
        create_profile_from_preset(
            "deepseek", profile_id="deepseek", region="singapore"
        )
    with pytest.raises(ProviderPresetError, match="workspace"):
        create_profile_from_preset(
            "qwen",
            profile_id="qwen-us",
            region="virginia",
            workspace_id="not-used",
        )


def test_unknown_preset_rejected():
    with pytest.raises(ProviderPresetError, match="Unknown"):
        get_provider_preset("openai")
