"""Canonical key-free identity may be imported without analysis services."""
import importlib
import subprocess
import sys
from dataclasses import fields, replace

import pytest

from src.core.provider_profile import ProviderProfile
from src.core.provider_protocol import ProviderCapabilities


def fingerprint():
    assert importlib.util.find_spec("src.core.processing_identity") is not None, "pure identity module is missing"
    return importlib.import_module("src.core.processing_identity").cloud_engine_fingerprint


def test_canonical_identity_is_reexported_unchanged():
    helper = fingerprint()
    from src.core.processing_analysis import cloud_engine_fingerprint
    assert helper is cloud_engine_fingerprint
    assert helper(ProviderProfile()) == "0abff527b0a98bbad0ce6a85ca18b90201fe1ed6fc17a66cca38844e972347a8"


def test_every_profile_and_capability_field_participates():
    helper = fingerprint()
    profile = ProviderProfile()
    baseline = helper(profile)
    for item in fields(ProviderProfile):
        if item.name == "capabilities":
            for cap in fields(ProviderCapabilities):
                changed = replace(profile.capabilities, **{cap.name: not getattr(profile.capabilities, cap.name)})
                assert helper(replace(profile, capabilities=changed)) != baseline
            continue
        value = getattr(profile, item.name)
        changes = {"auth_scheme": "api_key_header", "base_url_mode": "USER_CONFIGURED",
                   "base_url": "https://identity.example.test/v1"}
        changed = changes.get(item.name, not value if type(value) is bool else
                              value + 1 if type(value) is int else value + "changed")
        assert helper(replace(profile, **{item.name: changed})) != baseline
    assert "credential" not in str(inspect_signature(helper))


def inspect_signature(helper):
    from inspect import signature
    return signature(helper)


@pytest.mark.parametrize("invalid", [None, object(), "profile"])
def test_invalid_profile_types_are_rejected(invalid):
    with pytest.raises(ValueError, match="Invalid provider profile"):
        fingerprint()(invalid)


def test_pure_import_has_no_analysis_model_or_media_dependencies():
    result = subprocess.run([sys.executable, "-c",
        "import sys; import src.core.processing_identity; "
        "assert 'src.core.processing_analysis' not in sys.modules; "
        "assert not any(n.startswith(('src.services.', 'PIL', 'PySide6')) for n in sys.modules)"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
