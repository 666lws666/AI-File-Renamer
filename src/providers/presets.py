"""Adapter construction for the five approved presets plus Custom Provider."""
from __future__ import annotations

from dataclasses import fields

from src.core.provider_presets import (
    FIRST_PHASE_PROVIDER_IDS,
    ProviderPresetError,
    create_profile_from_preset,
)
from src.core.provider_profile import ProviderProfile
from src.providers.factory import is_legacy_provider
from src.providers.openai_compatible import (
    JsonTransport,
    OpenAICompatibleAdapter,
    ProviderAdapterConfigurationError,
)
from src.services.retry_policy import RetryExecutor


ADAPTER_PROVIDER_IDS = frozenset((*FIRST_PHASE_PROVIDER_IDS, "custom"))


def _validate_official_profile(profile: ProviderProfile, provider_id: str) -> None:
    if profile.provider_id != provider_id:
        raise ProviderAdapterConfigurationError(
            "Official Provider profile ID must be canonical"
        )
    try:
        expected = create_profile_from_preset(
            provider_id,
            profile_id=profile.id,
            model=profile.model,
            region=profile.region,
            workspace_id=profile.workspace_id,
        )
    except ProviderPresetError as error:
        raise ProviderAdapterConfigurationError(
            "Official Provider profile does not match its preset"
        ) from error

    immutable_wire_fields = (
        "protocol_kind",
        "auth_scheme",
        "base_url_mode",
        "base_url",
        "region",
        "workspace_id",
    )
    if any(
        getattr(profile, name) != getattr(expected, name)
        for name in immutable_wire_fields
    ):
        raise ProviderAdapterConfigurationError(
            "Official Provider endpoint or authentication differs from its preset"
        )

    capability_names = tuple(
        item.name for item in fields(expected.capabilities)
    )
    if any(
        getattr(profile.capabilities, name)
        and not getattr(expected.capabilities, name)
        for name in capability_names
    ):
        raise ProviderAdapterConfigurationError(
            "Official Provider profile declares unverified capabilities"
        )


def create_adapter(
    *,
    profile: ProviderProfile,
    credential: str,
    transport: JsonTransport | None = None,
    retry_executor: RetryExecutor | None = None,
) -> OpenAICompatibleAdapter:
    """Build the only approved Task-7 adapter path.

    The function selects by immutable profile metadata.  It never falls back to
    another provider and it deliberately excludes the two legacy branded
    providers from the public adapter path.
    """
    provider_id = profile.provider_id.strip().casefold()
    if is_legacy_provider(provider_id):
        raise ProviderAdapterConfigurationError(
            "Legacy Provider is not available through the public preset path"
        )
    if provider_id not in ADAPTER_PROVIDER_IDS:
        raise ProviderAdapterConfigurationError(
            f"No approved adapter path for Provider: {provider_id or '<empty>'}"
        )
    if profile.protocol_kind != "openai_compatible":
        raise ProviderAdapterConfigurationError(
            "Approved presets require the OpenAI-compatible wire protocol"
        )
    if provider_id != "custom":
        _validate_official_profile(profile, provider_id)
    return OpenAICompatibleAdapter(
        profile=profile,
        credential=credential,
        transport=transport,
        retry_executor=retry_executor,
    )
