"""SettingsController — QObject-based transactional preferences controller.

Exposes QML-safe Properties, Signals, and Slots.  Provider API keys are
NEVER returned as property values — only ``configured`` booleans and a
three-state ``credentialState`` (configured / unconfigured / unavailable).

M6 functional gate guarantees:
- ``draftChanged`` fires on EVERY real draft-field change, even when
  ``dirty`` is already true (``dirtyChanged`` covers only the transition).
- ``stageProviderKey`` is fail-closed: only the five known preset IDs and
  IDs already present in the draft are accepted — unknown IDs never create
  orphan credentials.
- ``setActiveProvider`` enforces enabled + verified + configured +
  credential-service-available; whole-row clicks cannot bypass it.
- A successful ``testConnection`` persists ``needs_connection_verification
  = false`` into the draft so the provider can be activated and the state
  survives a restart.
- ``_safe_profile_from_dict`` validates through the unified
  ``ProviderProfile`` rules (canonical id, HTTPS/loopback base URL, no URL
  credentials or secret query params) and REJECTS credential-bearing input
  fields instead of silently ignoring them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, Callable

from PySide6.QtCore import (
    Property,
    QObject,
    Signal,
    Slot,
)

from src.controllers.settings_transaction import (
    CredentialOperation,
    CredentialStore,
    SettingsSaveResult,
    SettingsSaveTransaction,
)
from src.core.connection_test import ConnectionOutcome, ConnectionResult
from src.core.provider_manager import PROVIDER_CREDENTIAL_SERVICE
from src.core.provider_presets import (
    FIRST_PHASE_PROVIDER_IDS,
    DEEPSEEK_MODELS,
    capabilities_for_model,
    ProviderPresetError,
    create_custom_provider_profile,
    create_profile_from_preset,
    get_provider_preset,
    list_provider_presets,
)
from src.core.provider_profile import ProviderProfile
from src.core.processing_authority import ProcessingAuthority
from src.core.processing_identity import cloud_engine_fingerprint
from src.providers.openai_compatible import ProcessingDispatch
from src.controllers.managed_connection_runner import ManagedConnectionRunner, ProbeRequest, ProbeCompletion
from src.core.provider_protocol import ProviderCapabilities
from src.models.app_config import AppConfig


# ---------------------------------------------------------------------------
# Provider UI view model (safe for QML — NO keys, NO prices, NO source URLs)
# ---------------------------------------------------------------------------

# Canonical provider profile id — same rule the preset builder enforces.
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")

# Credential-bearing input field markers — any normalized field name
# containing one of these is a hard rejection, never a silent ignore.
_CREDENTIAL_FIELD_MARKERS = ("apikey", "token", "secret", "password", "authorization")

_PRESET_IDS = frozenset(FIRST_PHASE_PROVIDER_IDS)


def _normalize_key(key: str) -> str:
    return key.casefold().replace("_", "").replace("-", "")


def _is_credential_field(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(marker in normalized for marker in _CREDENTIAL_FIELD_MARKERS)


def _build_provider_view_models(
    live: AppConfig,
    credential_store: CredentialStore,
    staged_keys: dict[str, str],
    credential_read_allowed: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Produce a list of safe dicts for QML rendering.

    Returns combined preset + saved profiles.  Each entry has ONLY
    display-safe fields.
    """
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    saved_map: dict[str, dict[str, Any]] = {}
    for p in live.provider_profiles:
        pid = p.get("id", "")
        if pid:
            saved_map[pid] = p

    # Presets first
    for preset in list_provider_presets():
        pid = preset.id
        seen_ids.add(pid)
        active = live.active_provider_id == pid
        saved = saved_map.get(pid, {})
        enabled = saved.get("enabled", True)
        needs_verification = saved.get("needs_connection_verification", True)
        state = _credential_state(credential_store, pid, credential_read_allowed)
        configured = state == "configured"
        staged = pid in staged_keys and bool(staged_keys[pid])
        region = saved.get("region", "")
        selected_model = saved.get("model", preset.default_model)
        model_caps = capabilities_for_model(preset, selected_model)

        result.append({
            "id": pid,
            "displayName": preset.display_name,
            "baseUrl": saved.get("base_url", preset.base_url if preset.base_url_mode != "REGIONAL" else ""),
            "model": saved.get("model", preset.default_model),
            "recommended": preset.recommended,
            "isPreset": True,
            "enabled": enabled,
            "active": active,
            "credentialState": state,
            "configured": configured,
            "credentialUnavailable": state == "unavailable",
            "staged": staged,
            "needsConnectionVerification": needs_verification,
            "canActivate": (
                enabled and not active and not needs_verification
                and state != "unavailable" and (configured or staged)
            ),
            "textSupported": model_caps.text,
            "visionSupported": model_caps.vision,
            "structuredJsonStatus": _json_status(preset.id, model_caps),
            "videoKeyframesSupported": model_caps.vision,
            "modelOptions": list(DEEPSEEK_MODELS) if preset.id == "deepseek" else [],
            "requiresUserModel": preset.requires_user_model,
            "region": region,
            "regions": _preset_region_options(preset),
        })

    # Saved profiles not in presets (custom)
    for p in live.provider_profiles:
        pid = p.get("id", "")
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        caps = p.get("capabilities", {})
        if isinstance(caps, dict):
            vision = caps.get("vision", False)
        else:
            vision = False
        state = _credential_state(credential_store, pid, credential_read_allowed)
        configured = state == "configured"
        staged = pid in staged_keys and bool(staged_keys[pid])

        result.append({
            "id": pid,
            "displayName": p.get("display_name", pid),
            "baseUrl": p.get("base_url", ""),
            "model": p.get("model", ""),
            "recommended": False,
            "isPreset": False,
            "enabled": p.get("enabled", True),
            "active": live.active_provider_id == pid,
            "credentialState": state,
            "configured": configured,
            "credentialUnavailable": state == "unavailable",
            "staged": staged,
            "needsConnectionVerification": p.get("needs_connection_verification", True),
            "canActivate": (
                p.get("enabled", True) and live.active_provider_id != pid
                and not p.get("needs_connection_verification", True)
                and state != "unavailable" and (configured or staged)
            ),
            "textSupported": caps.get("text", True) if isinstance(caps, dict) else True,
            "visionSupported": vision,
            "structuredJsonStatus": "unverified" if isinstance(caps, dict) and caps.get("json_mode") else "unsupported",
            "videoKeyframesSupported": vision,
        })

    return result


def _preset_region_options(preset: Any) -> list[dict[str, Any]]:
    """Region options for REGIONAL presets (Qwen), each with whether the
    region endpoint requires a workspace id."""
    if preset.base_url_mode != "REGIONAL":
        return []
    return [
        {"name": name, "needsWorkspaceId": "{WorkspaceId}" in template}
        for name, template in preset.regional_endpoints.items()
    ]


def _json_status(provider_id: str, caps: Any) -> str:
    if not caps.json_mode:
        return "unsupported"
    if provider_id == "mimo":
        return "unverified"
    return "verified"


def _credential_state(store: CredentialStore, profile_id: str,
                      read_allowed: Callable[[], bool] | None = None) -> str:
    """Three-state credential read: configured / unconfigured / unavailable.

    ``unavailable`` means the store raised while reading — it MUST NOT be
    forged as ``unconfigured`` (that could destroy a real secret during
    compensation).
    """
    try:
        if read_allowed is not None and not read_allowed():
            return "unavailable"
        exists = store.get(PROVIDER_CREDENTIAL_SERVICE, f"provider:{profile_id}") is not None
    except Exception:
        return "unavailable"
    return "configured" if exists else "unconfigured"


def _credential_exists(store: CredentialStore, profile_id: str,
                       read_allowed: Callable[[], bool] | None = None) -> bool:
    return _credential_state(store, profile_id, read_allowed) == "configured"


def _strict_bool(value: Any, name: str, default: bool) -> bool:
    """Coerce a profile boolean field strictly — a string like ``"false"``
    must not silently become True."""
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"Provider profile field {name} must be boolean")
    return value


def _cap_bool(caps: dict[str, Any], name: str, default: bool) -> bool:
    """Read one capability, accepting snake_case / camelCase keys strictly."""
    for key in (name, name.replace("_", "")):
        if key in caps:
            value = caps[key]
            if not isinstance(value, bool):
                raise ValueError(f"Capability {name} must be boolean")
            return value
    return default


def _parse_capabilities(caps_raw: Any) -> ProviderCapabilities:
    """Strictly parse a user-declared capabilities mapping (Custom only)."""
    if not isinstance(caps_raw, dict):
        raise ValueError("Provider capabilities must be a mapping")
    return ProviderCapabilities(
        text=_cap_bool(caps_raw, "text", True),
        vision=_cap_bool(caps_raw, "vision", False),
        multi_image=_cap_bool(caps_raw, "multi_image", False),
        json_mode=_cap_bool(caps_raw, "json_mode", False),
        json_schema=_cap_bool(caps_raw, "json_schema", False),
        streaming=_cap_bool(caps_raw, "streaming", False),
        tool_calling=_cap_bool(caps_raw, "tool_calling", False),
    )


def _build_profile_from_data(data: dict[str, Any]) -> ProviderProfile:
    """Build a ProviderProfile through the UNIFIED M3 constructors.

    - presets -> ``create_profile_from_preset`` (official endpoints, region,
      workspace id, requires_user_model rules)
    - custom  -> ``create_custom_provider_profile`` (HTTPS/loopback base URL,
      user-declared capabilities)

    Only the M3 constructors decide profile shape; SettingsController never
    hand-rolls ProviderProfile fields.  Credential-bearing input fields are
    a hard rejection (fail-closed).
    """
    # 1. Credential-bearing fields are a hard rejection, not a silent strip.
    for key in data:
        if _is_credential_field(str(key)):
            raise ValueError(f"Credential field is forbidden in provider profile: {key}")

    # 2. Canonical provider id.
    pid = str(data.get("id", "")).strip()
    if not pid:
        raise ValueError("Provider profile id is required")
    if _PROFILE_ID_RE.fullmatch(pid) is None:
        raise ValueError("Provider profile id is not canonical")

    # 3. Display name.
    display_name = str(data.get("display_name", data.get("displayName", pid))).strip()

    # 4. Protocol — only the OpenAI-compatible wire protocol is supported.
    protocol_kind = str(
        data.get("protocol_kind", data.get("protocolKind", "openai_compatible"))
    ).strip()
    if protocol_kind != "openai_compatible":
        raise ValueError(f"Unsupported protocol_kind: {protocol_kind}")

    model = str(data.get("model", "")).strip()

    # 5. Preset branch — create_profile_from_preset enforces official
    #    endpoint rules (base URL override rejected, region + workspace for
    #    REGIONAL providers, requires_user_model).
    if pid in _PRESET_IDS:
        try:
            profile = create_profile_from_preset(
                pid,
                profile_id=pid,
                display_name=display_name,
                model=model,
                base_url=str(data.get("base_url", data.get("baseUrl", ""))).strip(),
                region=str(data.get("region", "")).strip().casefold(),
                workspace_id=str(
                    data.get("workspace_id", data.get("workspaceId", ""))
                ).strip(),
            )
        except ProviderPresetError as error:
            raise ValueError(str(error)) from error
        return profile

    # 6. Custom branch — HTTPS/loopback enforced by ProviderProfile, base
    #    URL and model required, capabilities user-declared.
    base_url = str(data.get("base_url", data.get("baseUrl", ""))).strip()
    capabilities = _parse_capabilities(data.get("capabilities", {}))
    try:
        return create_custom_provider_profile(
            profile_id=pid,
            display_name=display_name,
            base_url=base_url,
            model=model,
            capabilities=capabilities,
        )
    except ProviderPresetError as error:
        raise ValueError(str(error)) from error


def _profile_fingerprint(data: dict[str, Any], key: str, *, profile: ProviderProfile | None = None) -> str:
    """Deterministic fingerprint of the candidate metadata + key.

    Stored as a digest only — the raw key is never retained in the
    verification record.  Any field or key change yields a different
    fingerprint, invalidating a previously successful connection test.
    """
    # Canonical full adapter metadata, not a partial/UI capability subset.
    # Aliases and preset-derived defaults must fingerprint the actual profile.
    normalized = profile if profile is not None else _build_profile_from_data(data)
    metadata = replace(normalized, enabled=True, needs_connection_verification=True,
        credential_account_id="").to_safe_dict()
    key_digest = hashlib.sha256((key or "").encode("utf-8")).hexdigest()
    material = json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "|" + key_digest
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_profile_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a provider profile dict through the unified
    M3 constructors (``_build_profile_from_data``), then attach only the
    M6-only fields: enabled / needs_connection_verification /
    credential_account_id.

    REJECTS any input carrying credential-bearing fields — fail-closed.
    """
    profile = _build_profile_from_data(data)
    enabled = _strict_bool(data.get("enabled"), "enabled", True)
    needs_verification = _strict_bool(
        data.get(
            "needs_connection_verification",
            data.get("needsConnectionVerification", True),
        ),
        "needs_connection_verification",
        True,
    )
    profile = replace(
        profile,
        enabled=enabled,
        needs_connection_verification=needs_verification,
        credential_account_id=f"provider:{profile.id}",
    )
    return profile.to_safe_dict()


# ---------------------------------------------------------------------------
# SettingsController (QObject)
# ---------------------------------------------------------------------------


class SettingsController(QObject):
    """QObject controller for the Preferences page.

    All QML-visible state is exposed via Qt Properties with notify
    signals.  Edits go through Slots that mutate the draft only.
    """

    # --- Signals ---
    dirtyChanged = Signal()
    draftChanged = Signal()
    savingChanged = Signal()
    saveErrorChanged = Signal()
    sessionOpenChanged = Signal()
    providerProfilesChanged = Signal()
    activeProviderChanged = Signal()
    connectionTestStateChanged = Signal()
    saveSucceeded = Signal()
    saveFailed = Signal(str)
    cacheClearFinished = Signal(bool)
    diagnosticsExportRequested = Signal()
    diagnosticsExportFinished = Signal(bool, str)
    diagnosticsAvailabilityChanged = Signal()
    usageChanged = Signal()
    localeRestoreRequested = Signal(str)

    def __init__(
        self,
        live_config: AppConfig,
        config_file_path: Path,
        credential_store: CredentialStore,
        *,
        cache_service: Any = None,
        connection_test_service: Any = None,
        usage_service: Any = None,
        diagnostics_service: Any = None,
        event_publisher: Callable[[str, Any], None] | None = None,
        config_applier: Callable[[AppConfig], None] | None = None,
        credential_read_allowed: Callable[[], bool] | None = None,
        runtime_input_preparer: Callable[[AppConfig], Any] | None = None,
        runtime_inputs_committed: Callable[[AppConfig, Any], None] | None = None,
        runtime_admission_failed: Callable[[str], None] | None = None,
        managed_connection_runner: ManagedConnectionRunner | None = None,
        processing_authority: ProcessingAuthority | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._live_config = live_config
        self._config_file_path = config_file_path
        self._credentials = credential_store
        self._cache_service = cache_service
        self._connection_test_service = connection_test_service
        self._usage_service = usage_service  # injectable UsageRecorder (read-only binding)
        self._diagnostics_service = diagnostics_service
        self._event_publisher = event_publisher
        self._config_applier = config_applier  # dependency-injection only; NOT a QML property
        self._credential_read_allowed = credential_read_allowed or (lambda: True)
        self._runtime_input_preparer = runtime_input_preparer
        self._runtime_inputs_committed = runtime_inputs_committed
        self._runtime_admission_failed = runtime_admission_failed
        self._managed_publication = runtime_inputs_committed is not None
        self._probe_runner = managed_connection_runner
        self._processing_authority = processing_authority
        self._session_epoch = 0
        self._candidate_epoch = 0
        self._probe_sequence = 0
        self._owned_probe: ProbeRequest | None = None
        self._probe_candidate: dict[str, Any] | None = None
        self._closing = False
        if self._probe_runner is not None:
            if type(processing_authority) is not ProcessingAuthority:
                raise TypeError("Managed probes require processing authority")
            self._probe_runner.completed.connect(self._accept_probe_completion)

        # Draft state
        self._draft: AppConfig | None = None
        self._draft_profiles: list[dict[str, Any]] = []
        self._staged_keys: dict[str, str] = {}
        self._session_open = False
        self._dirty = False
        self._saving = False
        self._save_error = ""
        self._last_result: SettingsSaveResult | None = None

        # Connection test
        self._connection_test_state = "idle"
        self._connection_test_provider_id = ""
        # profile_id -> fingerprint digest of the last SUCCESSFUL test
        self._verified_fingerprints: dict[str, str] = {}

    # ==================================================================
    # Properties
    # ==================================================================

    # --- sessionOpen ---
    def _get_session_open(self) -> bool:
        return self._session_open

    sessionOpen = Property(bool, _get_session_open, notify=sessionOpenChanged)

    # --- dirty ---
    def _get_dirty(self) -> bool:
        return self._dirty

    dirty = Property(bool, _get_dirty, notify=dirtyChanged)

    # --- saving ---
    def _get_saving(self) -> bool:
        return self._saving

    saving = Property(bool, _get_saving, notify=savingChanged)

    # --- saveError ---
    def _get_save_error(self) -> str:
        return self._save_error

    saveError = Property(str, _get_save_error, notify=saveErrorChanged)

    @Property(bool, notify=diagnosticsAvailabilityChanged)
    def diagnosticsAvailable(self) -> bool:
        return self._diagnostics_service is not None

    def set_diagnostics_service(self, service: Any) -> None:
        if self._diagnostics_service is service:
            return
        self._diagnostics_service = service
        self.diagnosticsAvailabilityChanged.emit()

    # --- language ---
    _LANG_MAP = {"zh": "zh_CN", "en": "en_US", "zh_CN": "zh_CN", "en_US": "en_US",
                 "zh-HK": "zh_HK", "zh_HK": "zh_HK",
                 "zh-CN": "zh_CN", "en-US": "en_US"}

    def _get_language(self) -> str:
        return self._draft.language if self._draft else "zh_CN"

    def _set_language(self, value: str) -> None:
        if not self._draft:
            return
        v = self._LANG_MAP.get(value, "zh_CN")
        if self._draft.language != v:
            self._draft.language = v
            self._mark_dirty()

    language = Property(str, _get_language, _set_language, notify=draftChanged)

    # --- theme ---
    def _get_theme(self) -> str:
        return self._draft.theme if self._draft else "light"

    def _set_theme(self, value: str) -> None:
        if not self._draft:
            return
        if value != "light":
            return
        if self._draft.theme != value:
            self._draft.theme = value
            self._mark_dirty()

    theme = Property(str, _get_theme, _set_theme, notify=draftChanged)

    # --- defaultTemplateId ---
    def _get_default_template_id(self) -> str:
        return self._draft.default_template_id if self._draft else ""

    def _set_default_template_id(self, value: str) -> None:
        if not self._draft:
            return
        if self._draft.default_template_id != value:
            self._draft.default_template_id = value
            self._mark_dirty()

    defaultTemplateId = Property(str, _get_default_template_id, _set_default_template_id, notify=draftChanged)

    # --- maxFileSizeMb ---
    def _get_max_file_size_mb(self) -> int:
        return self._draft.max_file_size_mb if self._draft else 50

    def _set_max_file_size_mb(self, value: int) -> None:
        if not self._draft:
            return
        v = max(1, min(500, int(value)))
        if self._draft.max_file_size_mb != v:
            self._draft.max_file_size_mb = v
            self._mark_dirty()

    maxFileSizeMb = Property(int, _get_max_file_size_mb, _set_max_file_size_mb, notify=draftChanged)

    # --- maxContentChars ---
    def _get_max_content_chars(self) -> int:
        return self._draft.max_content_chars if self._draft else 4000

    def _set_max_content_chars(self, value: int) -> None:
        if not self._draft:
            return
        v = max(500, min(16000, int(value)))
        if self._draft.max_content_chars != v:
            self._draft.max_content_chars = v
            self._mark_dirty()

    maxContentChars = Property(int, _get_max_content_chars, _set_max_content_chars, notify=draftChanged)

    # --- qualityMode ---
    def _get_quality_mode(self) -> str:
        return self._draft.quality_mode if self._draft else "balanced"

    def _set_quality_mode(self, value: str) -> None:
        if not self._draft:
            return
        if value in ("economy", "balanced", "high") and self._draft.quality_mode != value:
            self._draft.quality_mode = value
            self._mark_dirty()

    qualityMode = Property(str, _get_quality_mode, _set_quality_mode, notify=draftChanged)

    # --- maxConcurrentRequests ---
    def _get_max_concurrent_requests(self) -> int:
        return self._draft.max_concurrent_requests if self._draft else 4

    def _set_max_concurrent_requests(self, value: int) -> None:
        if not self._draft:
            return
        v = max(1, min(20, int(value)))
        if self._draft.max_concurrent_requests != v:
            self._draft.max_concurrent_requests = v
            self._mark_dirty()

    maxConcurrentRequests = Property(int, _get_max_concurrent_requests, _set_max_concurrent_requests, notify=draftChanged)

    # --- requestTimeoutSeconds ---
    def _get_request_timeout_seconds(self) -> int:
        return self._draft.request_timeout_seconds if self._draft else 30

    def _set_request_timeout_seconds(self, value: int) -> None:
        if not self._draft:
            return
        v = max(5, min(300, int(value)))
        if self._draft.request_timeout_seconds != v:
            self._draft.request_timeout_seconds = v
            self._mark_dirty()

    requestTimeoutSeconds = Property(int, _get_request_timeout_seconds, _set_request_timeout_seconds, notify=draftChanged)

    # --- maxRetries ---
    def _get_max_retries(self) -> int:
        return self._draft.max_retries if self._draft else 3

    def _set_max_retries(self, value: int) -> None:
        if not self._draft:
            return
        v = max(0, min(10, int(value)))
        if self._draft.max_retries != v:
            self._draft.max_retries = v
            self._mark_dirty()

    maxRetries = Property(int, _get_max_retries, _set_max_retries, notify=draftChanged)

    # --- maxPdfPages ---
    def _get_max_pdf_pages(self) -> int:
        return self._draft.max_pdf_pages if self._draft else 50

    def _set_max_pdf_pages(self, value: int) -> None:
        if not self._draft:
            return
        v = max(1, min(200, int(value)))
        if self._draft.max_pdf_pages != v:
            self._draft.max_pdf_pages = v
            self._mark_dirty()

    maxPdfPages = Property(int, _get_max_pdf_pages, _set_max_pdf_pages, notify=draftChanged)

    # --- maxVideoKeyframes ---
    def _get_max_video_keyframes(self) -> int:
        return self._draft.max_video_keyframes if self._draft else 8

    def _set_max_video_keyframes(self, value: int) -> None:
        if not self._draft:
            return
        v = max(1, min(32, int(value)))
        if self._draft.max_video_keyframes != v:
            self._draft.max_video_keyframes = v
            self._mark_dirty()

    maxVideoKeyframes = Property(int, _get_max_video_keyframes, _set_max_video_keyframes, notify=draftChanged)

    # --- allowTextCloud ---
    def _get_allow_text_cloud(self) -> bool:
        return self._draft.allow_text_cloud if self._draft else True

    def _set_allow_text_cloud(self, value: bool) -> None:
        if not self._draft:
            return
        if self._draft.allow_text_cloud != value:
            self._draft.allow_text_cloud = value
            self._mark_dirty()

    allowTextCloud = Property(bool, _get_allow_text_cloud, _set_allow_text_cloud, notify=draftChanged)

    # --- allowVisionCloud ---
    def _get_allow_vision_cloud(self) -> bool:
        return self._draft.allow_vision_cloud if self._draft else True

    def _set_allow_vision_cloud(self, value: bool) -> None:
        if not self._draft:
            return
        if self._draft.allow_vision_cloud != value:
            self._draft.allow_vision_cloud = value
            self._mark_dirty()

    allowVisionCloud = Property(bool, _get_allow_vision_cloud, _set_allow_vision_cloud, notify=draftChanged)

    # --- allowVideoKeyframesCloud ---
    def _get_allow_video_keyframes_cloud(self) -> bool:
        return self._draft.allow_video_keyframes_cloud if self._draft else True

    def _set_allow_video_keyframes_cloud(self, value: bool) -> None:
        if not self._draft:
            return
        if self._draft.allow_video_keyframes_cloud != value:
            self._draft.allow_video_keyframes_cloud = value
            self._mark_dirty()

    allowVideoKeyframesCloud = Property(bool, _get_allow_video_keyframes_cloud, _set_allow_video_keyframes_cloud, notify=draftChanged)

    # --- cacheEnabled ---
    def _get_cache_enabled(self) -> bool:
        return self._draft.cache_enabled if self._draft else True

    def _set_cache_enabled(self, value: bool) -> None:
        if not self._draft:
            return
        if self._draft.cache_enabled != value:
            self._draft.cache_enabled = value
            self._mark_dirty()

    cacheEnabled = Property(bool, _get_cache_enabled, _set_cache_enabled, notify=draftChanged)

    # --- cacheMaxMb ---
    def _get_cache_max_mb(self) -> int:
        return self._draft.cache_max_mb if self._draft else 500

    def _set_cache_max_mb(self, value: int) -> None:
        if not self._draft:
            return
        v = max(10, min(10000, int(value)))
        if self._draft.cache_max_mb != v:
            self._draft.cache_max_mb = v
            self._mark_dirty()

    cacheMaxMb = Property(int, _get_cache_max_mb, _set_cache_max_mb, notify=draftChanged)

    # --- cacheTtlDays ---
    def _get_cache_ttl_days(self) -> int:
        return self._draft.cache_ttl_days if self._draft else 7

    def _set_cache_ttl_days(self, value: int) -> None:
        if not self._draft:
            return
        v = max(1, min(90, int(value)))
        if self._draft.cache_ttl_days != v:
            self._draft.cache_ttl_days = v
            self._mark_dirty()

    cacheTtlDays = Property(int, _get_cache_ttl_days, _set_cache_ttl_days, notify=draftChanged)

    # --- providerProfiles (QVariantList-safe) ---
    def _get_provider_profiles(self) -> list[dict[str, Any]]:
        if not self._draft:
            return _build_provider_view_models(self._live_config, self._credentials, self._staged_keys, self._passive_reads_allowed)
        # Use draft state for active and saved profiles; live for credential existence
        draft_copy = self._draft.model_copy(deep=True)
        draft_copy.provider_profiles = copy.deepcopy(self._draft_profiles)
        return _build_provider_view_models(draft_copy, self._credentials, self._staged_keys, self._passive_reads_allowed)

    providerProfiles = Property("QVariantList", _get_provider_profiles, notify=providerProfilesChanged)

    # --- activeProviderId ---
    def _get_active_provider_id(self) -> str:
        return self._draft.active_provider_id if self._draft else ""

    def _set_active_provider_id(self, value: str) -> None:
        if not self._draft:
            return
        if self._draft.active_provider_id != value:
            self._draft.active_provider_id = value
            self._mark_dirty()

    activeProviderId = Property(str, _get_active_provider_id, _set_active_provider_id, notify=activeProviderChanged)

    # --- connectionTestState ---
    def _get_connection_test_state(self) -> str:
        return self._connection_test_state

    connectionTestState = Property(str, _get_connection_test_state, notify=connectionTestStateChanged)

    # --- connectionTestProviderId — the provider the state belongs to ---
    def _get_connection_test_provider_id(self) -> str:
        return self._connection_test_provider_id

    connectionTestProviderId = Property(str, _get_connection_test_provider_id, notify=connectionTestStateChanged)

    @Slot(str, result=str)
    def connectionTestStateFor(self, profile_id: str) -> str:
        """The test state scoped to ONE provider — a success for qwen must
        never surface in the kimi form."""
        if profile_id == self._connection_test_provider_id:
            return self._connection_test_state
        return "idle"

    # --- usageAvailable / usageData (non-monetary usage, read-only) ---
    # No service injected, or storage corrupted → unavailable.  Corrupt
    # storage is NEVER reported as an empty store.

    def _get_usage_available(self) -> bool:
        if self._usage_service is None:
            return False
        return self._usage_service.is_available()

    def _get_usage_data(self) -> list[dict[str, Any]]:
        if self._usage_service is None:
            return []
        try:
            aggregates = self._usage_service.daily_summary(group_by=("provider",))
        except Exception:
            return []
        return [
            {
                "provider": agg.provider_id,
                "requests": agg.request_count,
                # Unknown token usage renders a dash in the card — never 0.
                "tokensIn": agg.input_tokens.value if agg.input_tokens.known else "—",
                "tokensOut": agg.output_tokens.value if agg.output_tokens.known else "—",
            }
            for agg in aggregates
        ]

    usageAvailable = Property(bool, _get_usage_available, notify=usageChanged)
    usageData = Property("QVariantList", _get_usage_data, notify=usageChanged)

    # ==================================================================
    # Slots
    # ==================================================================

    @Slot()
    def openSession(self) -> None:
        if self._closing:
            return
        if self._session_open:
            return
        self._session_epoch += 1
        self._supersede_probe()
        self._draft = self._live_config.model_copy(deep=True)
        self._draft.language = self._LANG_MAP.get(self._draft.language, "zh_CN")
        self._draft_profiles = copy.deepcopy(self._draft.provider_profiles)
        self._staged_keys.clear()
        self._dirty = False
        self._saving = False
        self._save_error = ""
        self._session_open = True
        self._connection_test_state = "idle"
        self._connection_test_provider_id = ""
        self._verified_fingerprints.clear()
        self._notify_probe_superseded()
        self.sessionOpenChanged.emit()
        self.draftChanged.emit()
        self.dirtyChanged.emit()
        self.providerProfilesChanged.emit()
        self.activeProviderChanged.emit()
        self.usageChanged.emit()

    @Slot()
    def cancel(self) -> None:
        self._session_epoch += 1
        self._supersede_probe()
        saved_language = self._live_config.language
        self._draft = None
        self._draft_profiles = []
        self._staged_keys.clear()
        self._session_open = False
        self._dirty = False
        self._saving = False
        self._save_error = ""
        self._last_result = None
        self._connection_test_state = "idle"
        self._connection_test_provider_id = ""
        self._verified_fingerprints.clear()
        self._notify_probe_superseded()
        self.sessionOpenChanged.emit()
        self.draftChanged.emit()
        self.dirtyChanged.emit()
        self.saveErrorChanged.emit()
        self.providerProfilesChanged.emit()
        self.usageChanged.emit()

        # Locale preview belongs to the discarded settings session, not to
        # the persisted configuration. Never write config while restoring it.
        self.localeRestoreRequested.emit(saved_language)

    @Slot()
    def saveAll(self) -> None:
        if not self._session_open or self._draft is None:
            return
        if self._saving:
            return  # re-entrancy guard
        session_epoch = self._session_epoch
        originating_draft = self._draft
        def owns_session() -> bool:
            return self._settings_session_current(session_epoch, originating_draft)
        self._supersede_probe()
        self._saving = True
        self._notify_probe_superseded()
        if not owns_session():
            return
        self.savingChanged.emit()
        if not owns_session():
            return

        # --- Validate ---
        errors = self._validate()
        if not owns_session():
            return
        if errors:
            self._finish_save_failure(SettingsSaveResult(success=False, errors=errors), mark_dirty=False)
            return

        # --- Build candidate ---
        candidate = self._draft.model_copy(deep=True)
        candidate.provider_profiles = copy.deepcopy(self._draft_profiles)
        cred_ops = self._build_credential_operations()
        prepared = None
        if self._runtime_input_preparer is not None:
            try:
                prepared = self._runtime_input_preparer(candidate.model_copy(deep=True))
            except Exception:
                if owns_session():
                    self._finish_save_failure(SettingsSaveResult(False, ["runtime-input-preparation-failed"]))
                return
            if not owns_session():
                return

        # --- Snapshot live config BEFORE any mutation ---
        live_snapshot = self._live_config.model_copy(deep=True)

        # --- Execute transaction ---
        if self._config_applier is not None:
            config_setter = self._config_applier
        else:

            def _config_setter(cfg: AppConfig) -> None:
                for fn in type(self._live_config).model_fields:
                    setattr(self._live_config, fn, getattr(cfg, fn))

            config_setter = _config_setter

        buffered_events: list[tuple[str, Any]] = []
        publisher = self._event_publisher
        if self._managed_publication:
            publisher = lambda name, payload: buffered_events.append((name, payload))
        txn = SettingsSaveTransaction(
            current_config=live_snapshot,  # deep-copied BEFORE transaction
            config_file_path=self._config_file_path,
            credential_store=self._credentials,
            config_setter=config_setter,
            event_publisher=publisher,
        )
        if not owns_session():
            return
        result = txn.commit(candidate, credential_operations=cred_ops)
        if result.success and self._runtime_inputs_committed is not None:
            try:
                self._runtime_inputs_committed(candidate, prepared)
            except Exception:
                self._close_runtime_admission("runtime-input-publication-failed")
                if owns_session():
                    self._finish_save_failure(SettingsSaveResult(False, ["runtime-input-publication-failed"]))
                return  # Durable save is NOT claimed to have rolled back.
        elif not result.success and result.rollback_errors and self._managed_publication:
            self._close_runtime_admission("settings-rollback-indeterminate")

        # Runtime hooks reflect the durable outcome even if an observer replaced
        # Settings. The old Save must never apply its UI/result to that session.
        if not owns_session():
            return

        if self._managed_publication and self._event_publisher is not None:
            for name, payload in buffered_events:
                try:
                    self._event_publisher(name, payload)
                except Exception:
                    pass  # external observer is not part of durable commit
                if not owns_session():
                    return

        if result.success:
            self._staged_keys.clear()
            self._draft = self._live_config.model_copy(deep=True)
            self._draft_profiles = copy.deepcopy(self._draft.provider_profiles)
            self._dirty = False
            self._save_error = ""
            self._saving = False
            self._last_result = result
            published_draft = self._draft
            for signal in (self.savingChanged, self.draftChanged, self.dirtyChanged,
                           self.saveErrorChanged, self.providerProfilesChanged, self.saveSucceeded):
                if not self._settings_session_current(session_epoch, published_draft):
                    return
                signal.emit()
        else:
            self._finish_save_failure(result)

    @Slot(str, str)
    def stageProviderKey(self, profile_id: str, key: str) -> None:
        if not self._session_open:
            return
        profile_id = str(profile_id).strip()
        if not profile_id:
            return
        # Fail-closed: only the five known preset IDs and IDs already
        # present in the draft are accepted.
        if not self._known_profile_id(profile_id):
            return
        session_epoch, originating_draft = self._session_epoch, self._draft
        self._supersede_probe()
        key = (key or "").strip()
        if key:
            self._staged_keys[profile_id] = key
        else:
            if profile_id in self._staged_keys:
                del self._staged_keys[profile_id]
            else:
                exists = _credential_exists(self._credentials, profile_id, self._passive_reads_allowed)
                if not self._settings_session_current(session_epoch, originating_draft):
                    return
                if exists:
                    self._staged_keys[profile_id] = ""  # sentinel: delete
        if not self._finish_provider_mutation(session_epoch, originating_draft):
            return
        self.providerProfilesChanged.emit()

    @Slot(str)
    def clearProviderKey(self, profile_id: str) -> None:
        if not self._session_open or not self._known_profile_id(profile_id):
            return
        session_epoch, originating_draft = self._session_epoch, self._draft
        self._supersede_probe()
        # Explicit Clear means delete, including when a replacement is staged.
        # Keep the tombstone so reopening/testing cannot revive the stored key.
        self._staged_keys[profile_id] = ""
        if not self._finish_provider_mutation(session_epoch, originating_draft):
            return
        self.providerProfilesChanged.emit()

    @Slot(str)
    def setActiveProvider(self, profile_id: str) -> None:
        """Activate a provider, enforcing enabled + verified + configured +
        credential-service-available.  A whole-row click cannot bypass this."""
        if not self._draft:
            return
        if not self._passive_reads_allowed():
            return
        pid = str(profile_id).strip()
        if not self._known_profile_id(pid):
            return  # unknown id — fail-closed
        profile = self._find_draft_profile(pid)
        if profile is None:
            return  # not verified (no saved profile for it yet)
        if not profile.get("enabled", True):
            return
        if profile.get("needs_connection_verification", True):
            return
        state = _credential_state(self._credentials, pid, self._passive_reads_allowed)
        if state == "unavailable":
            return
        configured = state == "configured" or bool(self._staged_keys.get(pid))
        if not configured:
            return
        if self._draft.active_provider_id != pid:
            self._draft.active_provider_id = pid
            self._mark_dirty()
            self.activeProviderChanged.emit()
        self.providerProfilesChanged.emit()

    @Slot(str, str, result="QVariantMap")
    def presetModelCapabilities(self, provider_id: str, model: str) -> dict[str, Any]:
        """Safe model-derived presentation; no profile, key or disk mutation."""
        caps = capabilities_for_model(get_provider_preset(provider_id), model.strip())
        return {"text": caps.text, "vision": caps.vision, "json_mode": caps.json_mode}

    @Slot("QVariantMap", str)
    def addOrUpdateProvider(self, data: dict[str, Any], key: str = "") -> None:
        """Save a candidate through the unified M3 constructors.

        The provider is saved as verified ONLY when the fingerprint of this
        exact candidate + key matches a previous SUCCESSFUL connection test.
        Any field or key change invalidates the fingerprint, so the saved
        profile stays ``needs_connection_verification=true``.
        """
        if not self._draft:
            return
        session_epoch, originating_draft = self._session_epoch, self._draft
        try:
            profile = _build_profile_from_data(dict(data))
        except (ValueError, ProviderPresetError):
            return  # fail-closed: invalid input never mutates the draft
        pid = profile.id

        # Duplicate / case-conflict protection against presets and draft.
        for preset_id in _PRESET_IDS:
            if preset_id != pid and preset_id.casefold() == pid.casefold():
                return
        profiles = copy.deepcopy(self._draft_profiles)
        for p in profiles:
            existing_id = str(p.get("id", ""))
            if existing_id != pid and existing_id.casefold() == pid.casefold():
                return

        # Verification is an internal security state.  QML/caller input is
        # untrusted and may never mark a candidate verified.  Only a successful
        # connection test for this exact profile + key fingerprint can do so.
        effective_key = self._candidate_credential(pid, key)
        if not self._settings_session_current(session_epoch, originating_draft):
            return
        fp = _profile_fingerprint(dict(data), effective_key, profile=profile)
        needs_verification = not effective_key or self._verified_fingerprints.get(pid) != fp
        self._supersede_probe()

        enabled = _strict_bool(data.get("enabled"), "enabled", True)
        safe = replace(
            profile,
            enabled=enabled,
            needs_connection_verification=needs_verification,
            credential_account_id=f"provider:{pid}",
        ).to_safe_dict()

        replaced = False
        for i, p in enumerate(profiles):
            if p.get("id") == pid:
                profiles[i] = safe
                replaced = True
                break
        if not replaced:
            profiles.append(safe)
        self._draft_profiles = profiles
        self._draft.provider_profiles = copy.deepcopy(profiles)
        if not self._finish_provider_mutation(session_epoch, originating_draft):
            return
        self.providerProfilesChanged.emit()

    @Slot(str)
    def removeProvider(self, profile_id: str) -> None:
        if not self._draft:
            return
        session_epoch, originating_draft = self._session_epoch, self._draft
        pid = str(profile_id).strip()
        if pid.casefold() in _PRESET_IDS:
            return  # presets cannot be deleted — only custom providers
        profiles = [p for p in self._draft_profiles if p.get("id") != pid]
        if len(profiles) == len(self._draft_profiles):
            return  # not found
        self._supersede_probe()
        # Ensure credential deletion
        if pid not in self._staged_keys:
            self._staged_keys[pid] = ""
        active_changed = self._draft.active_provider_id == pid
        if active_changed:
            self._draft.active_provider_id = ""
        self._draft_profiles = profiles
        self._draft.provider_profiles = copy.deepcopy(profiles)
        if not self._finish_provider_mutation(session_epoch, originating_draft):
            return
        if active_changed:
            self.activeProviderChanged.emit()
            if not self._settings_session_current(session_epoch, originating_draft):
                return
        self.providerProfilesChanged.emit()

    @Slot(str, str)
    def testConnection(self, profile_id: str, staged_key: str) -> None:
        """Test a KNOWN provider (preset or already in the draft).

        Unknown ids fail closed WITHOUT calling the connection service.
        An empty key input falls back to the CredentialStore internally —
        the key is never returned to QML, and an unavailable store fails
        closed.
        """
        if not self._session_open:
            return
        if self._probe_runner is not None:
            self._start_managed_probe(str(profile_id).strip(), None, staged_key)
            return
        if not self._passive_reads_allowed():
            self._connection_test_provider_id = str(profile_id).strip()
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return
        pid = str(profile_id).strip()
        self._connection_test_provider_id = pid
        self._connection_test_state = "testing"
        self.connectionTestStateChanged.emit()

        if not self._known_profile_id(pid):
            # Unknown id — fail closed, never call the service.
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return

        try:
            profile = self._build_profile_for_test(pid)
        except (ValueError, ProviderPresetError):
            self._connection_test_state = "failure"
            self._drop_failed_staged_key(pid)
            self.connectionTestStateChanged.emit()
            return

        key = (staged_key or "").strip()
        if not key:
            state = _credential_state(self._credentials, pid, self._passive_reads_allowed)
            if state == "unavailable":
                self._connection_test_state = "failure"
                self.connectionTestStateChanged.emit()
                return
            if state == "configured":
                try:
                    if not self._passive_reads_allowed():
                        self._connection_test_state = "failure"
                        self.connectionTestStateChanged.emit()
                        return
                    key = (
                        self._credentials.get(
                            PROVIDER_CREDENTIAL_SERVICE, f"provider:{pid}"
                        )
                        or ""
                    ).strip()
                except Exception:
                    key = ""

        if not key:
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return

        result = self._run_connection_service(profile, key)
        if result.outcome == ConnectionOutcome.SUCCESS:
            self._connection_test_state = "success"
            self._verified_fingerprints[pid] = _profile_fingerprint(
                profile.to_safe_dict(), key, profile=profile
            )
            self._record_verification_success(pid, profile)
        else:
            self._connection_test_state = "failure"
            self._verified_fingerprints.pop(pid, None)
            self._drop_failed_staged_key(pid)
        self.connectionTestStateChanged.emit()

    @Slot("QVariantMap", str)
    def testConnectionCandidate(self, data: dict[str, Any], key: str) -> None:
        """Test a full candidate (new Custom OR preset with region/workspace)
        WITHOUT touching the draft.

        The candidate is built and validated through the unified M3
        constructors; only a fully buildable profile reaches the connection
        service.  A successful result is bound to the candidate's
        fingerprint — any later field or key change invalidates it.
        """
        if not self._session_open:
            return
        if self._probe_runner is not None:
            self._start_managed_probe(str(data.get("id", "")).strip(), dict(data), key)
            return
        if not self._passive_reads_allowed():
            self._connection_test_provider_id = str(data.get("id", "")).strip()
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return
        candidate = dict(data)
        pid = str(candidate.get("id", "")).strip()
        self._connection_test_provider_id = pid
        self._connection_test_state = "testing"
        self.connectionTestStateChanged.emit()

        try:
            profile = _build_profile_from_data(candidate)
        except (ValueError, ProviderPresetError):
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return

        key = self._candidate_credential(profile.id, key)

        if not key:
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return

        result = self._run_connection_service(profile, key)
        if result.outcome == ConnectionOutcome.SUCCESS:
            self._connection_test_state = "success"
            self._verified_fingerprints[profile.id] = _profile_fingerprint(
                candidate, key, profile=profile
            )
        else:
            self._connection_test_state = "failure"
            self._verified_fingerprints.pop(profile.id, None)
            self._drop_failed_staged_key(profile.id)
        self.connectionTestStateChanged.emit()

    @Slot()
    def clearCache(self) -> None:
        if self._cache_service is None:
            self.cacheClearFinished.emit(False)
            return
        try:
            self._cache_service.clear()
            self.cacheClearFinished.emit(True)
        except Exception:
            self.cacheClearFinished.emit(False)

    @Slot()
    def requestDiagnosticsExport(self) -> None:
        self.diagnosticsExportRequested.emit()

    @Slot(str)
    def exportDiagnostics(self, destination: str) -> None:
        if self._diagnostics_service is None:
            self.diagnosticsExportFinished.emit(False, "diagnostics-unavailable")
            return
        if not destination:
            self.diagnosticsExportFinished.emit(False, "diagnostics-destination-required")
            return
        try:
            exported = self._diagnostics_service(destination)
        except Exception as error:
            from src.core.error_handler import sanitize_detail
            self.diagnosticsExportFinished.emit(False, sanitize_detail(error))
            return
        self.diagnosticsExportFinished.emit(True, str(exported))

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _known_profile_id(self, profile_id: str) -> bool:
        if profile_id in _PRESET_IDS:
            return True
        if self._draft is not None:
            return any(p.get("id") == profile_id for p in self._draft_profiles)
        return False

    def _candidate_credential(self, profile_id: str, key: str) -> str:
        """Resolve the same effective key for testing and staging verification."""
        typed = (key or "").strip()
        if typed or not self._known_profile_id(profile_id):
            return typed
        if profile_id in self._staged_keys:
            return self._staged_keys[profile_id]
        if not self._passive_reads_allowed():
            return ""
        try:
            return (self._credentials.get(
                PROVIDER_CREDENTIAL_SERVICE, f"provider:{profile_id}",
            ) or "").strip()
        except Exception:
            return ""

    def _find_draft_profile(self, profile_id: str) -> dict[str, Any] | None:
        for p in self._draft_profiles if self._draft else []:
            if p.get("id") == profile_id:
                return p
        return None

    def _build_profile_for_test(self, profile_id: str) -> ProviderProfile:
        """Rebuild a KNOWN provider's profile for a connection test.

        Prefers the draft's saved profile (round-tripped through
        ProviderProfile); an unsaved preset is built via the unified
        ``create_profile_from_preset`` (fails for REGIONAL providers without
        a region — nothing to test against).
        """
        for p in self._draft_profiles:
            if p.get("id") == profile_id:
                return ProviderProfile.from_safe_dict(p)
        preset = get_provider_preset(profile_id)
        return create_profile_from_preset(
            profile_id,
            profile_id=profile_id,
            model=preset.default_model or "",
        )

    def _run_connection_service(
        self, profile: ProviderProfile, key: str
    ) -> ConnectionResult:
        """Run the injected connection service against a full profile.

        The service contract is ``(ProviderProfile, credential) ->
        ConnectionResult``.  Exceptions are converted to a failure result —
        they never propagate into QML.
        """
        if self._connection_test_service is None:
            return ConnectionResult(outcome=ConnectionOutcome.UNKNOWN_ERROR)
        try:
            result = self._connection_test_service(profile, key)
        except Exception:
            return ConnectionResult(outcome=ConnectionOutcome.UNKNOWN_ERROR)
        if not isinstance(result, ConnectionResult):
            return ConnectionResult(outcome=ConnectionOutcome.UNKNOWN_ERROR)
        return result

    def _record_verification_success(
        self, profile_id: str, profile: ProviderProfile, *, notify: bool = True
    ) -> None:
        """Persist a successful connection test into the draft so the
        provider can be activated and the state survives a restart.

        The draft entry is the unified-built profile with only
        enabled / needs_connection_verification / credential_account_id
        attached (M6-only fields).
        """
        if self._draft is None:
            return
        pid = profile.id
        safe = replace(
            profile,
            enabled=True,
            needs_connection_verification=False,
            credential_account_id=f"provider:{pid}",
        ).to_safe_dict()
        profiles = [
            safe if p.get("id") == pid else p for p in self._draft_profiles
        ]
        if not any(p.get("id") == pid for p in profiles):
            profiles.append(safe)
        self._draft_profiles = profiles
        self._draft.provider_profiles = copy.deepcopy(profiles)
        if notify:
            self._mark_dirty()
            self.providerProfilesChanged.emit()

    def _drop_failed_staged_key(self, profile_id: str) -> None:
        """A key that failed its connection test must never be persisted.

        Only the in-memory staged copy is dropped — credentials already
        stored in the Credential Manager are never touched here.
        """
        if profile_id in self._staged_keys:
            del self._staged_keys[profile_id]
            self.providerProfilesChanged.emit()

    def _settings_session_current(self, session_epoch: int, draft: AppConfig | None) -> bool:
        return (self._session_open and not self._closing and draft is not None
                and self._session_epoch == session_epoch and self._draft is draft)

    def _mark_dirty(self) -> bool:
        session_epoch, originating_draft = self._session_epoch, self._draft
        if not self._settings_session_current(session_epoch, originating_draft):
            return False
        changed = not self._dirty
        self._dirty = True  # Finish private mutation before draftChanged reentry.
        self.draftChanged.emit()
        if not self._settings_session_current(session_epoch, originating_draft):
            return False
        if changed:
            self.dirtyChanged.emit()
        return self._settings_session_current(session_epoch, originating_draft)

    def _finish_provider_mutation(self, session_epoch: int, draft: AppConfig | None) -> bool:
        if not self._settings_session_current(session_epoch, draft) or not self._mark_dirty():
            return False
        self._notify_probe_superseded()
        return self._settings_session_current(session_epoch, draft)

    def _validate(self) -> list[str]:
        errors: list[str] = []
        if self._draft is None:
            return ["会话未打开"]
        aid = self._draft.active_provider_id
        if aid:
            found = None
            for p in self._draft_profiles:
                if p.get("id") == aid:
                    found = p
                    break
            if found is None:
                errors.append("当前激活的服务商不存在")
            elif not found.get("enabled", True):
                errors.append("当前激活的服务商已被禁用")
            elif found.get("needs_connection_verification", True):
                errors.append("当前激活的服务商未通过连接验证")
            elif self._passive_reads_allowed():
                state = _credential_state(self._credentials, aid, self._passive_reads_allowed)
                if not self._passive_reads_allowed():
                    return errors  # LOCAL/closing metadata save does not require a key.
                if state == "unavailable":
                    errors.append("凭据服务不可用，无法保存该服务商配置")
                else:
                    has_saved = state == "configured"
                    has_staged = aid in self._staged_keys and bool(self._staged_keys[aid])
                    if not has_saved and not has_staged:
                        errors.append("当前激活的服务商未配置 API Key")
        return errors

    def _build_credential_operations(self) -> list[CredentialOperation]:
        ops: list[CredentialOperation] = []
        assert self._draft is not None

        new_key = (self._draft.api_key or "").strip()
        old_key = (self._live_config.api_key or "").strip()
        if new_key != old_key:
            if new_key:
                ops.append(CredentialOperation("AIRenamer", "api_key", "set", new_key))
            else:
                ops.append(CredentialOperation("AIRenamer", "api_key", "delete"))

        for profile_id, staged_value in sorted(self._staged_keys.items()):
            account = f"provider:{profile_id}"
            if staged_value:
                ops.append(CredentialOperation(PROVIDER_CREDENTIAL_SERVICE, account, "set", staged_value))
            else:
                ops.append(CredentialOperation(PROVIDER_CREDENTIAL_SERVICE, account, "delete"))

        return ops

    # ==================================================================
    # Public Python API (for non-QML test access)
    # ==================================================================

    @property
    def draft_config(self) -> AppConfig | None:
        return self._draft

    @property
    def last_result(self) -> SettingsSaveResult | None:
        return self._last_result

    @property
    def staged_key_count(self) -> int:
        return len(self._staged_keys)

    # Managed owner-thread lifecycle and publication contracts.
    def _passive_reads_allowed(self) -> bool:
        if self._closing:
            return False
        try:
            permitted = self._credential_read_allowed() is True
            return permitted and not self._closing
        except Exception:
            return False

    def _supersede_probe(self) -> None:
        request = self._owned_probe
        self._owned_probe = None
        self._probe_candidate = None
        self._candidate_epoch += 1
        if request is not None and self._probe_runner is not None:
            self._probe_runner.cancel(request)
        if self._probe_runner is not None:
            self._connection_test_state = "idle"
            self._connection_test_provider_id = ""

    @Slot()
    def invalidateConnectionCandidate(self) -> None:
        self._supersede_probe()
        self.connectionTestStateChanged.emit()

    def _notify_probe_superseded(self) -> None:
        # Callers finish their private mutation before notifying. Never reset
        # state here: a reentrant observer may already own a newer request.
        if self._probe_runner is not None:
            self.connectionTestStateChanged.emit()

    def begin_close(self) -> None:
        self._closing = True
        self._session_epoch += 1
        self._supersede_probe()
        if self._probe_runner is not None:
            self._probe_runner.begin_close()
        self._notify_probe_superseded()

    @property
    def workers_idle(self) -> bool:
        return self._probe_runner is None or self._probe_runner.workers_idle

    def _start_managed_probe(self, pid: str, candidate: dict[str, Any] | None, typed_key: str) -> None:
        self._supersede_probe()
        self._probe_sequence += 1
        request_id = str(self._probe_sequence)
        session_epoch = self._session_epoch
        candidate_epoch = self._candidate_epoch
        event = Event()
        def owns_reservation() -> bool:
            return self._probe_reservation_current(request_id, session_epoch, candidate_epoch)
        try:
            if self._closing or not self._passive_reads_allowed():
                raise ValueError("probe-blocked")
            if not owns_reservation():
                event.set()
                return
            if candidate is None:
                if not self._known_profile_id(pid):
                    raise ValueError("unknown-profile")
                profile = self._build_profile_for_test(pid)
                data = profile.to_safe_dict()
                purpose = "known"
            else:
                profile = _build_profile_from_data(candidate)
                data = copy.deepcopy(candidate)
                purpose = "candidate"
            # Authentic purpose permission is captured on Qt BEFORE any key read.
            context = self._processing_authority.capture_cloud_probe(
                candidate_fingerprint=cloud_engine_fingerprint(profile),
                candidate_model=profile.model, request_id=request_id,
                task_cancel_event=event)
            source = "typed" if (typed_key or "").strip() else ("staged" if pid in self._staged_keys else "stored")
            key = self._candidate_credential(pid, typed_key)
            if not owns_reservation():
                event.set()
                return
            if not key or not self._processing_authority.is_current_cloud_probe(context):
                event.set()
                raise ValueError("probe-blocked")
            request = ProbeRequest(request_id, session_epoch,
                candidate_epoch, purpose, profile, key, source,
                _profile_fingerprint(data, key, profile=profile), ProcessingDispatch(self._processing_authority, context))
            self._owned_probe = request
            self._probe_candidate = data
            if not self._probe_runner.submit(request):
                self._owned_probe = None
                self._probe_candidate = None
                raise ValueError("probe-closing")
        except Exception:
            event.set()
            if not owns_reservation():
                return
            self._owned_probe = None
            self._probe_candidate = None
            self._connection_test_provider_id = pid
            self._connection_test_state = "failure"
            self.connectionTestStateChanged.emit()
            return
        self._connection_test_provider_id = pid
        self._connection_test_state = "testing"
        self.connectionTestStateChanged.emit()

    def _probe_reservation_current(self, request_id: str, session_epoch: int, candidate_epoch: int) -> bool:
        return (not self._closing and self._session_open
                and str(self._probe_sequence) == request_id
                and self._session_epoch == session_epoch
                and self._candidate_epoch == candidate_epoch
                and self._owned_probe is None)

    @Slot(object)
    def _accept_probe_completion(self, completion: ProbeCompletion) -> None:
        request = completion.request
        if request is not self._owned_probe:
            return
        data = self._probe_candidate
        # Terminal ownership is removed BEFORE any reentrant public notification.
        self._owned_probe = None
        self._probe_candidate = None
        def owns_terminal() -> bool:
            return self._probe_reservation_current(request.request_id,
                request.session_epoch, request.candidate_epoch)
        if not owns_terminal():
            return
        if data is None or not request.processing_dispatch.is_current():
            self._discard_probe_display(request)
            return
        permitted = self._passive_reads_allowed()
        if not owns_terminal():
            return
        if not permitted or not request.processing_dispatch.is_current():
            self._discard_probe_display(request)
            return
        if request.purpose == "known":
            try:
                if self._build_profile_for_test(request.profile.id) != request.profile:
                    self._discard_probe_display(request)
                    return
            except Exception:
                self._discard_probe_display(request)
                return
        key = request.key
        if request.credential_source != "typed":
            key = self._candidate_credential(request.profile.id, "")
        # Getter/policy reentry must not let the obsolete terminal clear loading
        # or ownership of a new request, even if the getter subsequently raises.
        if not owns_terminal():
            return
        if (not request.processing_dispatch.is_current()
                or _profile_fingerprint(data, key, profile=request.profile) != request.fingerprint):
            self._discard_probe_display(request)
            return
        pid = request.profile.id
        self._connection_test_provider_id = pid
        was_dirty = self._dirty
        if completion.result.outcome is ConnectionOutcome.SUCCESS:
            self._connection_test_state = "success"
            self._verified_fingerprints[pid] = request.fingerprint
            if request.purpose == "known":
                self._record_verification_success(pid, request.profile, notify=False)
                self._dirty = True
                self.draftChanged.emit()
                if not was_dirty:
                    self.dirtyChanged.emit()
                self.providerProfilesChanged.emit()
        else:
            self._connection_test_state = "failure"
            self._verified_fingerprints.pop(pid, None)
            self._drop_failed_staged_key(pid)
        self.connectionTestStateChanged.emit()

    def _discard_probe_display(self, request: ProbeRequest) -> None:
        if self._probe_reservation_current(request.request_id,
                request.session_epoch, request.candidate_epoch):
            self._connection_test_state = "idle"
            self._connection_test_provider_id = ""
            self.connectionTestStateChanged.emit()

    def _close_runtime_admission(self, reason: str) -> None:
        if self._runtime_admission_failed is not None:
            self._runtime_admission_failed(reason)

    def _finish_save_failure(self, result: SettingsSaveResult, *, mark_dirty: bool = True) -> None:
        session_epoch, originating_draft = self._session_epoch, self._draft
        if not self._settings_session_current(session_epoch, originating_draft):
            return
        if mark_dirty:
            self._dirty = True
        self._saving = False
        self._save_error = "; ".join(result.errors)
        self._last_result = result
        for signal in (self.savingChanged, self.draftChanged, self.dirtyChanged, self.saveErrorChanged):
            if not self._settings_session_current(session_epoch, originating_draft):
                return
            signal.emit()
        if self._settings_session_current(session_epoch, originating_draft):
            self.saveFailed.emit(self._save_error)
