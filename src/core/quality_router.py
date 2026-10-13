"""Quality mode routing within a single active Provider.

QualityRouter produces immutable pure-data configurations.  It never makes
network calls, never selects another provider, and never fabricates models
that the user has not configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from src.core.provider_profile import ProviderProfile


class QualityMode(str, Enum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


@dataclass(frozen=True, slots=True)
class QualityConfig:
    """Immutable quality-mode configuration for one provider invocation.

    All fields are pure data — no network calls, no secrets.
    """

    mode: QualityMode
    model: str
    provider_profile_id: str
    provider_id: str = ""
    max_tokens: int = 4096
    max_visual_count: int = 4
    timeout_seconds: int = 30
    max_retries: int = 3
    allows_higher_quality_retry: bool = False
    temperature: float = 0.0
    note: str = ""


# ── Per-mode limits ──────────────────────────────────────────────────────────
# These are pure preset multipliers, not price estimates.

_MODE_MULTIPLIERS = {
    QualityMode.ECONOMY: {
        "token_factor": 0.5,
        "visual_factor": 0.5,
        "timeout_factor": 0.8,
        "retry_factor": 0.5,
        "temperature": 0.0,
    },
    QualityMode.BALANCED: {
        "token_factor": 1.0,
        "visual_factor": 1.0,
        "timeout_factor": 1.0,
        "retry_factor": 1.0,
        "temperature": 0.0,
    },
    QualityMode.QUALITY: {
        "token_factor": 2.0,
        "visual_factor": 2.0,
        "timeout_factor": 1.5,
        "retry_factor": 2.0,
        "temperature": 0.3,
    },
}

_BASE_MAX_TOKENS = 4096
_BASE_MAX_VISUAL = 4
_BASE_TIMEOUT = 30
_BASE_MAX_RETRIES = 3


class QualityRouter:
    """Route a quality-mode string into a deterministic ``QualityConfig``.

    The router is bound to exactly one ``ProviderProfile`` and never selects
    another provider or fabricates models.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        available_models: Sequence[str] | None = None,
    ) -> None:
        self._profile = profile
        self._available_models: tuple[str, ...] = (
            tuple(available_models) if available_models else (profile.model,)
        )

    def route(self, mode: str) -> QualityConfig:
        """Return an immutable per-mode config for the bound profile."""
        try:
            quality_mode = QualityMode(mode)
        except ValueError:
            quality_mode = QualityMode.BALANCED

        multipliers = _MODE_MULTIPLIERS[quality_mode]

        selected_model = self._select_model(quality_mode)

        max_visual = max(
            0,
            int(_BASE_MAX_VISUAL * multipliers["visual_factor"]),
        )
        timeout = max(
            1,
            int(self._profile.timeout_seconds * multipliers["timeout_factor"]),
        )
        max_retries = max(
            0,
            int(_BASE_MAX_RETRIES * multipliers["retry_factor"]),
        )

        allows_upgrade = (
            quality_mode is QualityMode.QUALITY
            and len(self._available_models) > 1
        )

        note = self._build_note(quality_mode)

        return QualityConfig(
            mode=quality_mode,
            model=selected_model,
            provider_profile_id=self._profile.id,
            provider_id=self._profile.provider_id,
            max_tokens=int(_BASE_MAX_TOKENS * multipliers["token_factor"]),
            max_visual_count=max_visual,
            timeout_seconds=timeout,
            max_retries=max_retries,
            allows_higher_quality_retry=allows_upgrade,
            temperature=float(multipliers["temperature"]),
            note=note,
        )

    def _select_model(self, mode: QualityMode) -> str:
        """Select model deterministically from available_models.

        - ECONOMY and BALANCED → default (first) model.
        - QUALITY → last (highest-tier) model if multiple are available;
          otherwise the default.
        """
        if not self._available_models:
            return self._profile.model

        if mode is QualityMode.QUALITY and len(self._available_models) > 1:
            return self._available_models[-1]

        return self._available_models[0]

    def _build_note(self, mode: QualityMode) -> str:
        if len(self._available_models) <= 1:
            return (
                f"Single-model provider ({self._profile.provider_id}); "
                f"{mode.value} mode adjusts limits only."
            )
        return (
            f"Multi-model provider ({self._profile.provider_id}) "
            f"with {len(self._available_models)} models; "
            f"{mode.value} mode selected '{self._select_model(mode)}'."
        )


def route_quality_mode(
    profile: ProviderProfile,
    mode: str,
    *,
    available_models: Sequence[str] | None = None,
) -> QualityConfig:
    """Convenience function: route once and return the config."""
    return QualityRouter(profile, available_models=available_models).route(mode)
