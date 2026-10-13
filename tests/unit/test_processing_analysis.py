"""Pure admission contract tests; no models, files or credentials."""
from dataclasses import replace
import importlib

import pytest

from src.core.processing_analysis import AnalysisSettings
from src.core.provider_profile import ProviderProfile
from src.models.app_config import AppConfig


def test_cloud_fingerprint_is_canonical_safe_and_changes_with_binding():
    contracts = importlib.import_module("src.core.processing_analysis")
    assert hasattr(contracts, "cloud_engine_fingerprint"), "canonical fingerprint missing"
    profile = ProviderProfile(id="one", model="synthetic", base_url="https://example.invalid", needs_connection_verification=False)
    fingerprint = contracts.cloud_engine_fingerprint(profile)
    assert len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint)
    assert contracts.cloud_engine_fingerprint(replace(profile)) == fingerprint
    for field, value in [("model", "another"), ("credential_account_id", "account-two"), ("base_url", "https://another.invalid")]:
        assert contracts.cloud_engine_fingerprint(replace(profile, **{field: value})) != fingerprint


@pytest.mark.parametrize("field,value", [("max_content_chars", 0), ("max_file_size_mb", -1), ("quality_mode", "secret-value"), ("allow_text_cloud", 1)])
def test_settings_reject_unsafe_types_with_fixed_safe_message(field, value):
    config = AppConfig()
    setattr(config, field, value)
    with pytest.raises(ValueError, match="^Invalid analysis settings$"):
        AnalysisSettings.capture(config)


def test_settings_never_copy_extra_values():
    class Trap:
        def __deepcopy__(self, memo):
            pytest.fail("arbitrary extra copied")
    config = AppConfig(api_key="secret-value", arbitrary=Trap())
    result = AnalysisSettings.capture(config, "economy")
    assert result.quality_mode == "economy" and "secret-value" not in repr(result)


def test_published_immutable_settings_accept_validated_quality_override():
    published = AnalysisSettings.capture(AppConfig())
    overridden = AnalysisSettings.capture(published, "high")
    assert overridden.quality_mode == "high" and published.quality_mode == "balanced"
    with pytest.raises(ValueError):
        AnalysisSettings.capture(published, "unsupported")
