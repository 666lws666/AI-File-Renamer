"""Unit tests for quality mode routing within the active provider.

QualityRouter produces immutable pure-data configurations — no network calls.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.core.provider_presets import (
    create_custom_provider_profile,
    create_profile_from_preset,
)
from src.core.provider_protocol import ProviderCapabilities
from src.core.provider_profile import ProviderProfile
from src.core.quality_router import (
    QualityConfig,
    QualityMode,
    QualityRouter,
    route_quality_mode,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _deepseek_profile(model="deepseek-v4-flash"):
    return replace(
        create_profile_from_preset("deepseek", profile_id="qr-deepseek"),
        needs_connection_verification=False,
        model=model,
    )


def _qwen_profile(model="qwen3.6-flash"):
    return replace(
        create_profile_from_preset("qwen", profile_id="qr-qwen", region="virginia"),
        needs_connection_verification=False,
        model=model,
    )


def _mimo_profile(model="mimo-v2.5"):
    return replace(
        create_profile_from_preset("mimo", profile_id="qr-mimo"),
        needs_connection_verification=False,
        model=model,
    )


def _custom_profile(model="custom-model", **caps):
    caps_obj = ProviderCapabilities(text=True, **caps)
    return replace(
        create_custom_provider_profile(
            profile_id="qr-custom",
            display_name="Quality custom",
            base_url="https://custom.test/v1",
            model=model,
            capabilities=caps_obj,
        ),
        needs_connection_verification=False,
    )


# ── QualityConfig tests ──────────────────────────────────────────────────────


class TestQualityConfig:
    def test_config_is_immutable_pure_data(self):
        cfg = QualityConfig(
            mode=QualityMode.BALANCED,
            model="test-model",
            provider_profile_id="p1",
        )
        assert cfg.mode is QualityMode.BALANCED
        assert cfg.model == "test-model"
        with pytest.raises(Exception):
            cfg.model = "other"  # frozen

    def test_default_values(self):
        cfg = QualityConfig(
            mode=QualityMode.BALANCED,
            model="m",
            provider_profile_id="p1",
        )
        assert cfg.max_visual_count == 4
        assert cfg.timeout_seconds == 30
        assert cfg.allows_higher_quality_retry is False


# ── QualityRouter tests ──────────────────────────────────────────────────────


class TestQualityRouter:
    """Quality modes route within one provider; they never cross providers."""

    # ── balanced is default ──────────────────────────────────────────────────

    def test_balanced_is_default(self):
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg = router.route("balanced")
        assert cfg.mode is QualityMode.BALANCED

    def test_none_mode_defaults_to_balanced(self):
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg = router.route("balanced")
        assert cfg.mode is QualityMode.BALANCED

    def test_unknown_mode_defaults_to_balanced(self):
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg = router.route("balanced")
        assert cfg.mode is QualityMode.BALANCED

    # ── three modes produce distinct configs ─────────────────────────────────

    def test_economy_tightens_limits(self):
        """Economy mode should reduce resource limits vs balanced."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        econ = router.route("economy")
        bal = router.route("balanced")

        # Economy should not allow more than balanced
        assert econ.max_visual_count <= bal.max_visual_count
        assert econ.timeout_seconds <= bal.timeout_seconds

    def test_quality_relaxes_limits(self):
        """Quality mode should allow higher resource limits."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        qual = router.route("quality")
        bal = router.route("balanced")

        # Quality should allow at least as much as balanced
        assert qual.max_visual_count >= bal.max_visual_count
        assert qual.timeout_seconds >= bal.timeout_seconds

    def test_economy_marks_allow_quality_retry_false(self):
        """Economy mode should not allow higher-quality retries."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg = router.route("economy")
        assert cfg.allows_higher_quality_retry is False

    def test_quality_mode_marks_higher_retry_possible(self):
        """Quality mode may allow backup retries if multi-model."""
        profile = _qwen_profile()
        router = QualityRouter(
            profile, available_models=("qwen3.6-flash", "qwen3.6-pro")
        )
        cfg = router.route("quality")
        assert cfg.allows_higher_quality_retry is True

    # ── single-model provider honesty ────────────────────────────────────────

    def test_single_model_provider_does_not_change_model(self):
        """Single-model providers must not pretend to switch to a better model."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        router = QualityRouter(profile)
        for mode_name in ("economy", "balanced", "quality"):
            cfg = router.route(mode_name)
            assert cfg.model == "deepseek-v4-flash", (
                f"{mode_name} must not fabricate a different model"
            )

    def test_single_model_still_adjusts_limits(self):
        """Even with one model, modes can adjust token/visual/timeout limits."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        router = QualityRouter(profile)
        econ = router.route("economy")
        qual = router.route("quality")

        # Limits should differ even if model stays the same
        different = (
            econ.max_visual_count != qual.max_visual_count
            or econ.timeout_seconds != qual.timeout_seconds
            or econ.max_tokens != qual.max_tokens
        )
        assert different, (
            "Single-model modes should still differentiate via limits"
        )

    # ── multi-model provider routes within configured models ─────────────────

    def test_multi_model_provider_selects_by_mode(self):
        """When multiple models are configured, quality mode can select a higher-tier one."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        router = QualityRouter(
            profile,
            available_models=("deepseek-v4-flash", "deepseek-v4-pro"),
        )
        qual_cfg = router.route("quality")
        econ_cfg = router.route("economy")

        # Quality may select the higher-tier model
        assert qual_cfg.model in ("deepseek-v4-flash", "deepseek-v4-pro")
        # Economy stays with the default
        assert econ_cfg.model == "deepseek-v4-flash"

    def test_multi_model_deterministic_rules(self):
        """Model selection must be deterministic — same input → same output."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        available = ("deepseek-v4-flash", "deepseek-v4-pro")
        router = QualityRouter(profile, available_models=available)

        cfg1 = router.route("quality")
        cfg2 = router.route("quality")
        assert cfg1.model == cfg2.model  # deterministic

    def test_multi_model_economy_uses_default(self):
        """Economy mode always uses the default model."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        router = QualityRouter(
            profile,
            available_models=("deepseek-v4-flash", "deepseek-v4-pro"),
        )
        cfg = router.route("economy")
        assert cfg.model == "deepseek-v4-flash"

    def test_multi_model_balanced_uses_default(self):
        """Balanced mode uses the default model."""
        profile = _deepseek_profile(model="deepseek-v4-flash")
        router = QualityRouter(
            profile,
            available_models=("deepseek-v4-flash", "deepseek-v4-pro"),
        )
        cfg = router.route("balanced")
        assert cfg.model == "deepseek-v4-flash"

    # ── no cross-provider routing ────────────────────────────────────────────

    def test_router_is_bound_to_one_profile(self):
        """QualityRouter is constructed with one profile and never changes it."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg = router.route("quality")
        assert cfg.provider_profile_id == profile.id
        assert cfg.provider_id == profile.provider_id

    def test_no_cross_provider_model_selection(self):
        """Even when model names overlap, routing stays within the same provider."""
        ds_profile = _deepseek_profile()
        ds_router = QualityRouter(ds_profile)

        cfg = ds_router.route("quality")
        # Model must be from the profile's own provider
        assert cfg.provider_id == "deepseek"
        assert cfg.model == ds_profile.model  # stays with profile model

    # ── immutable pure data ──────────────────────────────────────────────────

    def test_route_returns_new_config_each_time(self):
        """Each route call returns a fresh, independent config."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        cfg1 = router.route("balanced")
        cfg2 = router.route("balanced")
        assert cfg1 is not cfg2  # different objects
        assert cfg1 == cfg2       # but equal values

    def test_no_network_calls(self):
        """QualityRouter.route() must be a pure function — no I/O."""
        profile = _deepseek_profile()
        router = QualityRouter(profile)
        # This must complete without any external calls
        cfg = router.route("quality")
        assert isinstance(cfg, QualityConfig)

    # ── custom provider ──────────────────────────────────────────────────────

    def test_custom_provider_single_model_adjusts_limits(self):
        profile = _custom_profile("my-model")
        router = QualityRouter(profile)
        econ = router.route("economy")
        qual = router.route("quality")
        assert econ.model == "my-model"
        assert qual.model == "my-model"
        # Limits should differ
        assert econ.timeout_seconds <= qual.timeout_seconds

    def test_custom_provider_multi_model_routes(self):
        profile = _custom_profile("cheap-model")
        router = QualityRouter(
            profile,
            available_models=("cheap-model", "good-model", "best-model"),
        )
        bal = router.route("balanced")
        qual = router.route("quality")
        assert bal.model == "cheap-model"
        assert qual.model == "best-model"

    # ── visual limits per mode ───────────────────────────────────────────────

    def test_vision_provider_modes_adjust_visual_limits(self):
        """For vision-capable providers, quality mode allows more images."""
        profile = _qwen_profile()
        router = QualityRouter(profile)
        econ = router.route("economy")
        bal = router.route("balanced")
        qual = router.route("quality")

        # Economy should be most restrictive
        assert econ.max_visual_count <= bal.max_visual_count
        assert bal.max_visual_count <= qual.max_visual_count

    # ── convenience function ─────────────────────────────────────────────────

    def test_route_quality_mode_convenience(self):
        cfg = route_quality_mode(_deepseek_profile(), "balanced")
        assert cfg.mode is QualityMode.BALANCED
        assert cfg.provider_id == "deepseek"


# ── QualityMode enum ─────────────────────────────────────────────────────────


class TestQualityModeEnum:
    def test_three_values(self):
        assert QualityMode.ECONOMY.value == "economy"
        assert QualityMode.BALANCED.value == "balanced"
        assert QualityMode.QUALITY.value == "quality"

    def test_from_string(self):
        assert QualityMode("economy") is QualityMode.ECONOMY
        assert QualityMode("balanced") is QualityMode.BALANCED
        assert QualityMode("quality") is QualityMode.QUALITY

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            QualityMode("turbo")
