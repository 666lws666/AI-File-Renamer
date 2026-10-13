"""Pure canonical non-secret Provider identity; no orchestration or media imports."""
from dataclasses import fields
from hashlib import sha256
import json

from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities


def cloud_engine_fingerprint(profile: ProviderProfile) -> str:
    """Canonical non-secret binding shared by admission and runtime composition.

    No credential reads; every immutable profile field participates, including
    credential-account identity (never its value) and verified capabilities.
    """
    if type(profile) is not ProviderProfile or type(profile.capabilities) is not ProviderCapabilities:
        raise ValueError("Invalid provider profile")
    values = {}
    for item in fields(ProviderProfile):
        value = getattr(profile, item.name)
        if item.name == "capabilities":
            value = {cap.name: getattr(value, cap.name) for cap in fields(ProviderCapabilities)}
            if any(type(v) is not bool for v in value.values()):
                raise ValueError("Invalid provider profile")
        elif item.name in {"enabled", "needs_connection_verification"}:
            if type(value) is not bool:
                raise ValueError("Invalid provider profile")
        elif item.name == "timeout_seconds":
            if type(value) is not int or value <= 0:
                raise ValueError("Invalid provider profile")
        elif type(value) is not str:
            raise ValueError("Invalid provider profile")
        values[item.name] = value
    return sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
