"""Historical Provider IDs used by the current preset gate."""

LEGACY_PROVIDER_IDS = frozenset({"openai", "claude"})


def is_legacy_provider(provider_name: str) -> bool:
    return isinstance(provider_name, str) and provider_name.strip().casefold() in LEGACY_PROVIDER_IDS
