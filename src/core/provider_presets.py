"""Evidence-backed Provider presets for the first public product slice.

Presets contain non-secret metadata only.  They are configuration shortcuts,
not proof that a user's account/model is available; every generated profile
therefore starts in ``needs_connection_verification`` state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .provider_profile import ProviderProfile
from .provider_protocol import ProviderCapabilities


VERIFICATION_DATE = "2026-07-29"
FIRST_PHASE_PROVIDER_IDS = ("deepseek", "qwen", "mimo", "zhipu", "kimi")
DEEPSEEK_FLASH_MODEL = "deepseek-flash"
DEEPSEEK_VISION_MODEL = "deepseek-v4-flash-vision-exp"  # compatibility alias
DEEPSEEK_VISION_MODELS = (DEEPSEEK_FLASH_MODEL, "deepseek-v4-flash", DEEPSEEK_VISION_MODEL)
# Order matches the explicit labels in ProviderForm. Pro is text-only in the
# 2026-09-10 snapshot; do not grant future capabilities based on the local clock.
DEEPSEEK_MODELS = (DEEPSEEK_FLASH_MODEL, "deepseek-v4-pro", DEEPSEEK_VISION_MODEL, "deepseek-v4-flash")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_PROFILE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")


class ProviderPresetError(ValueError):
    """Preset selection or user-supplied preset configuration is invalid."""


def capabilities_for_model(preset: "ProviderPreset", model: str) -> ProviderCapabilities:
    """Resolve verified capabilities without changing saved profiles or defaults."""
    if preset.id == "deepseek":
        if model not in DEEPSEEK_MODELS:
            return ProviderCapabilities(text=True)
        visual = model in DEEPSEEK_VISION_MODELS
        return ProviderCapabilities(
            text=True, vision=visual, multi_image=visual, json_mode=True,
            streaming=True, tool_calling=True,
        )
    if preset.capability_verified_models and model not in preset.capability_verified_models:
        return ProviderCapabilities(text=True)
    return preset.capabilities


def _freeze_mapping(values: Mapping) -> Mapping:
    frozen = {}
    for key, value in values.items():
        frozen[key] = (
            MappingProxyType(dict(value)) if isinstance(value, Mapping) else value
        )
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    id: str
    display_name: str
    base_url_mode: str
    base_url: str
    default_model: str
    capabilities: ProviderCapabilities
    auth_scheme: str = "bearer"
    protocol_kind: str = "openai_compatible"
    recommended: bool = False
    selectable: bool = True
    requires_user_model: bool = False
    regional_endpoints: Mapping[str, str] = field(default_factory=dict)
    verification_status: str = "PARTIAL"
    verification_date: str = VERIFICATION_DATE
    source_urls: tuple[str, ...] = ()
    pricing_status: str = "UNKNOWN"
    pricing_currency: str = ""
    pricing_unit: str = ""
    verified_prices: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    capability_verified_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "regional_endpoints", _freeze_mapping(self.regional_endpoints)
        )
        object.__setattr__(
            self, "verified_prices", _freeze_mapping(self.verified_prices)
        )
        object.__setattr__(self, "source_urls", tuple(self.source_urls))
        object.__setattr__(
            self, "capability_verified_models", tuple(self.capability_verified_models)
        )


_PRESETS = (
    ProviderPreset(
        id="deepseek",
        display_name="DeepSeek",
        base_url_mode="FIXED",
        base_url="https://api.deepseek.com",
        default_model=DEEPSEEK_FLASH_MODEL,
        capabilities=ProviderCapabilities(
            text=True,
            vision=True,
            multi_image=True,
            json_mode=True,
            streaming=True,
            tool_calling=True,
        ),
        verification_status="VERIFIED",
        verification_date="2026-09-10",
        source_urls=(
            "https://api-docs.deepseek.com",
            "https://api-docs.deepseek.com/quick_start/pricing/",
            "https://api-docs.deepseek.com/guides/vision/",
            "https://api-docs.deepseek.com/updates/",
        ),
        # Monetary features are not part of the product. Do not retain stale
        # historical numbers as currently verified prices.
    ),
    ProviderPreset(
        id="qwen",
        display_name="Qwen / 通义千问",
        base_url_mode="REGIONAL",
        base_url="",
        default_model="qwen3.6-flash",
        capabilities=ProviderCapabilities(
            text=True,
            vision=True,
            multi_image=True,
            json_mode=True,
            streaming=True,
            tool_calling=True,
        ),
        recommended=True,
        regional_endpoints={
            "beijing": (
                "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "singapore": (
                "https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "tokyo": (
                "https://{WorkspaceId}.ap-northeast-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "frankfurt": (
                "https://{WorkspaceId}.eu-central-1.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
            "virginia": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
        },
        source_urls=(
            "https://help.aliyun.com/zh/model-studio/qwen-api-via-dashscope",
            "https://help.aliyun.com/zh/model-studio/models",
            "https://help.aliyun.com/zh/model-studio/qwen-structured-output",
        ),
    ),
    ProviderPreset(
        id="mimo",
        display_name="MiMo",
        base_url_mode="FIXED",
        base_url="https://api.xiaomimimo.com/v1",
        default_model="mimo-v2.5",
        capabilities=ProviderCapabilities(
            text=True,
            vision=True,
            json_mode=True,
            streaming=True,
            tool_calling=True,
        ),
        auth_scheme="api_key_header",
        capability_verified_models=("mimo-v2.5", "mimo-v2.5-pro"),
        source_urls=(
            "https://platform.xiaomimimo.com/",
            (
                "https://mimo.mi.com/docs/en-US/quick-start/usage-guide/"
                "text-generation/structured-output"
            ),
        ),
    ),
    ProviderPreset(
        id="zhipu",
        display_name="智谱 AI / GLM",
        base_url_mode="FIXED",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="",
        requires_user_model=True,
        capabilities=ProviderCapabilities(
            text=True,
            vision=True,
            multi_image=True,
            json_mode=True,
            streaming=True,
            tool_calling=True,
        ),
        source_urls=(
            "https://docs.bigmodel.cn/cn/guide/develop/http/introduction",
            "https://docs.bigmodel.cn/api-reference/",
        ),
    ),
    ProviderPreset(
        id="kimi",
        display_name="Kimi / Moonshot AI",
        base_url_mode="FIXED",
        base_url="https://api.moonshot.ai/v1",
        default_model="",
        requires_user_model=True,
        capabilities=ProviderCapabilities(
            text=True,
            vision=True,
            multi_image=True,
            json_mode=True,
            json_schema=True,
            streaming=True,
            tool_calling=True,
        ),
        source_urls=(
            "https://platform.kimi.ai/docs",
            "https://platform.kimi.ai/docs/api/chat",
        ),
    ),
)
_PRESET_BY_ID = MappingProxyType({preset.id: preset for preset in _PRESETS})


def list_provider_presets() -> tuple[ProviderPreset, ...]:
    """Return the five immutable presets in stable UI order."""
    return _PRESETS


def get_provider_preset(provider_id: str) -> ProviderPreset:
    try:
        return _PRESET_BY_ID[provider_id.strip().casefold()]
    except (AttributeError, KeyError):
        raise ProviderPresetError(f"Unknown Provider preset: {provider_id}") from None


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderPresetError(f"{label} is required")
    return value.strip()


def _optional(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ProviderPresetError(f"{label} must be text")
    return value.strip()


def _safe_profile_id(value: str) -> str:
    profile_id = _required(value, "profile id")
    if _PROFILE_ID.fullmatch(profile_id) is None:
        raise ProviderPresetError("profile id is not canonical")
    return profile_id


def create_profile_from_preset(
    provider_id: str,
    *,
    profile_id: str,
    display_name: str = "",
    model: str = "",
    base_url: str = "",
    region: str = "",
    workspace_id: str = "",
) -> ProviderProfile:
    """Create unverified profile metadata from one evidence-backed preset."""
    preset = get_provider_preset(provider_id)
    safe_profile_id = _safe_profile_id(profile_id)
    selected_model = _optional(model, "model") or preset.default_model
    if not selected_model:
        raise ProviderPresetError(
            f"model is required for {preset.display_name}; no verified default exists"
        )

    selected_base_url = _optional(base_url, "base URL")
    selected_region = _optional(region, "region").casefold()
    selected_workspace = _optional(workspace_id, "workspace id")
    if selected_base_url:
        raise ProviderPresetError(
            "Official preset endpoint cannot be overridden; use Custom Provider"
        )
    if preset.base_url_mode == "REGIONAL":
        if not selected_region:
            raise ProviderPresetError("region is required for this Provider")
        try:
            endpoint_template = preset.regional_endpoints[selected_region]
        except KeyError:
            raise ProviderPresetError(
                f"Unsupported region for {preset.display_name}: {selected_region}"
            ) from None
        if "{WorkspaceId}" in endpoint_template:
            if not selected_workspace:
                raise ProviderPresetError(
                    "workspace id is required for the selected region"
                )
            if _WORKSPACE_ID.fullmatch(selected_workspace) is None:
                raise ProviderPresetError("workspace id is not safe")
            selected_base_url = endpoint_template.replace(
                "{WorkspaceId}", selected_workspace
            )
        else:
            if selected_workspace:
                raise ProviderPresetError(
                    "workspace id is not applicable to the selected region"
                )
            selected_base_url = endpoint_template
    else:
        if selected_region:
            raise ProviderPresetError("region is not applicable to this preset")
        if selected_workspace:
            raise ProviderPresetError(
                "workspace id is not applicable to this preset"
            )
        selected_base_url = preset.base_url

    selected_capabilities = capabilities_for_model(preset, selected_model)
    safe_display_name = _optional(display_name, "display name") or preset.display_name

    try:
        return ProviderProfile(
            id=safe_profile_id,
            display_name=safe_display_name,
            provider_id=preset.id,
            protocol_kind=preset.protocol_kind,
            auth_scheme=preset.auth_scheme,
            base_url_mode=preset.base_url_mode,
            base_url=selected_base_url,
            region=selected_region,
            workspace_id=selected_workspace,
            model=selected_model,
            capabilities=selected_capabilities,
            enabled=preset.selectable,
            needs_connection_verification=True,
        )
    except (TypeError, ValueError) as error:
        raise ProviderPresetError(str(error)) from error


def create_custom_provider_profile(
    *,
    profile_id: str,
    display_name: str,
    base_url: str,
    model: str,
    capabilities: ProviderCapabilities | None = None,
    auth_scheme: str = "bearer",
) -> ProviderProfile:
    """Create a user-configured OpenAI-compatible profile without assumptions."""
    safe_profile_id = _safe_profile_id(profile_id)
    safe_display_name = _required(display_name, "display name")
    safe_base_url = _required(base_url, "base URL")
    safe_model = _required(model, "model")
    if capabilities is not None and not isinstance(
        capabilities, ProviderCapabilities
    ):
        raise ProviderPresetError(
            "capabilities must be ProviderCapabilities"
        )
    declared_capabilities = capabilities or ProviderCapabilities(text=True)
    try:
        return ProviderProfile(
            id=safe_profile_id,
            display_name=safe_display_name,
            provider_id="custom",
            protocol_kind="openai_compatible",
            auth_scheme=auth_scheme,
            base_url_mode="USER_CONFIGURED",
            base_url=safe_base_url,
            model=safe_model,
            capabilities=declared_capabilities,
            needs_connection_verification=True,
        )
    except (TypeError, ValueError) as error:
        raise ProviderPresetError(str(error)) from error
