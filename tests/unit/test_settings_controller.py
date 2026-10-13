"""SettingsController — QObject transactional draft tests (M6 functional gate).

Covers:
- session open/cancel/save semantics
- C: draftChanged notification on EVERY real draft-field change (even when
  dirty is already true); dirtyChanged only for the dirty transition
- D: stageProviderKey fail-closed (preset ids + existing draft custom ids only)
- D: credential three-state (configured / unconfigured / unavailable)
- D: setActiveProvider guards (enabled / verified / configured / unavailable)
- D: testConnection success persists verification state into draft
- D: _safe_profile_from_dict unified ProviderProfile validation
- E: config applier partial-mutation restore (call order + field-by-field)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.controllers.settings_controller import (
    SettingsController,
    _credential_state,
    _safe_profile_from_dict,
)
from src.models.app_config import AppConfig


class FakeCredentialStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self._global_set_fail = False
        self._global_get_fail = False
        self._set_fail_count = 0
        self._set_fail_at: int | None = None

    def get(self, service: str, account: str) -> str | None:
        if self._global_get_fail:
            raise OSError("Simulated Credential Manager unavailable")
        return self.values.get((service, account))

    def set(self, service: str, account: str, secret: str) -> bool:
        self._set_fail_count += 1
        if self._set_fail_at == self._set_fail_count:
            return False
        if self._global_set_fail:
            return False
        self.values[(service, account)] = secret
        return True

    def delete(self, service: str, account: str) -> bool:
        self.values.pop((service, account), None)
        return True


def make_config(**kw: object) -> AppConfig:
    d: dict[str, object] = {
        "provider": "deepseek", "api_key": "", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro", "language": "zh_CN", "theme": "light",
        "max_file_size_mb": 50, "max_content_chars": 4000,
    }
    d.update(kw)
    return AppConfig(**d)  # type: ignore[arg-type]


@pytest.fixture
def store() -> FakeCredentialStore:
    return FakeCredentialStore()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


@pytest.fixture
def live() -> AppConfig:
    return make_config()


@pytest.fixture
def ctrl(live: AppConfig, config_file: Path, store: FakeCredentialStore) -> SettingsController:
    return SettingsController(live_config=live, config_file_path=config_file, credential_store=store)


# === Session ===

def test_open_session_deep_copies(ctrl: SettingsController, live: AppConfig) -> None:
    ctrl.openSession()
    assert ctrl.sessionOpen
    ctrl.language = "en_US"
    assert live.language == "zh_CN"
    assert ctrl.language == "en_US"


def test_cancel_discards_draft(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.stageProviderKey("qwen", "secret")
    ctrl.cancel()
    assert not ctrl.sessionOpen
    assert not ctrl.dirty


def test_cancel_no_file_writes(ctrl: SettingsController, config_file: Path) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.cancel()
    assert not config_file.exists()


# === C: notification mechanism ===

def test_first_field_change_sets_dirty(ctrl: SettingsController) -> None:
    ctrl.openSession()
    assert not ctrl.dirty
    ctrl.language = "en_US"
    assert ctrl.dirty


def test_second_field_change_still_notifies_after_dirty(ctrl: SettingsController) -> None:
    """dirty=true must NOT suppress notifications for later field changes."""
    ctrl.openSession()
    events: list[str] = []
    ctrl.draftChanged.connect(lambda: events.append("draft"))
    ctrl.language = "en_US"
    assert ctrl.dirty
    ctrl.maxFileSizeMb = 77  # dirty already true
    assert events == ["draft", "draft"], (
        "draftChanged must fire for EVERY real draft-field change, "
        f"got {len(events)} notification(s)"
    )


def test_dirty_changed_only_on_transition(ctrl: SettingsController) -> None:
    ctrl.openSession()
    transitions: list[bool] = []
    ctrl.dirtyChanged.connect(lambda: transitions.append(ctrl.dirty))
    ctrl.language = "en_US"     # False -> True
    ctrl.theme = "light"        # no change -> nothing
    ctrl.maxFileSizeMb = 60     # already dirty -> no dirtyChanged
    assert transitions == [True], f"dirtyChanged must fire only on transition: {transitions}"


def test_no_notify_when_value_unchanged(ctrl: SettingsController) -> None:
    ctrl.openSession()
    fired: list[str] = []
    ctrl.draftChanged.connect(lambda: fired.append("x"))
    ctrl.language = "zh_CN"  # same value
    ctrl.maxFileSizeMb = 50  # same value
    assert fired == []


# === Save success ===

def test_save_success(ctrl: SettingsController, live: AppConfig) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.maxFileSizeMb = 88
    ctrl.saveAll()
    assert live.language == "en_US"
    assert live.max_file_size_mb == 88
    assert not ctrl.dirty


def test_save_clears_staged_keys(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "secret-key")
    ctrl.saveAll()
    assert ctrl.staged_key_count == 0


def test_save_failure_preserves_draft(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    store._global_set_fail = True
    ctrl.stageProviderKey("qwen", "new-key")
    ctrl.saveAll()
    assert ctrl.dirty
    assert ctrl.language == "en_US"  # draft preserved


def test_save_failure_does_not_update_live(ctrl: SettingsController, live: AppConfig, store: FakeCredentialStore) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    store._global_set_fail = True
    ctrl.stageProviderKey("qwen", "new-key")
    ctrl.saveAll()
    assert live.language == "zh_CN"


def test_save_failure_never_emits_save_succeeded(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    ctrl.openSession()
    ok: list[bool] = []
    ctrl.saveSucceeded.connect(lambda: ok.append(True))
    store._global_set_fail = True
    ctrl.stageProviderKey("qwen", "k")
    ctrl.saveAll()
    assert ok == [], "saveSucceeded must NOT be emitted on failure"


# === E: live partial mutation recovery (rewritten) ===

def _apply_fields(target: AppConfig, source: AppConfig) -> None:
    for fn in type(source).model_fields:
        setattr(target, fn, getattr(source, fn))


def test_setter_partial_mutation_then_failure_restores(
    store: FakeCredentialStore, config_file: Path
) -> None:
    """A config applier that mutates live_config then raises must trigger a
    real restoration pass via config_setter(old_snapshot).

    Proven by recording the setter call ORDER and comparing live_config to the
    old snapshot field-by-field after the failed save.
    """
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"provider": "openai", "schema_version": 2, "language": "zh_CN"}),
        encoding="utf-8",
    )
    live = make_config(provider="openai", language="zh_CN", model="gpt-4o", max_file_size_mb=30)
    store.values[("AIRenamer", "api_key")] = "sk-old"

    old_snapshot = live.model_copy(deep=True)

    setter_calls: list[str] = []

    def _partially_mutating_applier(cfg: AppConfig) -> None:
        # First call = candidate application. Mutate live for real, then raise.
        if not setter_calls:
            setter_calls.append("candidate")
            _apply_fields(live, cfg)
            raise RuntimeError("config setter failed after partial mutation")
        # Second call = old-snapshot restoration.
        setter_calls.append("restore")
        _apply_fields(live, cfg)

    ctrl = SettingsController(
        live_config=live,
        config_file_path=config_file,
        credential_store=store,
        config_applier=_partially_mutating_applier,
    )
    succeeded: list[bool] = []
    ctrl.saveSucceeded.connect(lambda: succeeded.append(True))

    ctrl.openSession()
    ctrl.language = "en_US"
    assert ctrl._draft is not None
    ctrl._draft.api_key = "sk-new-key"
    ctrl._mark_dirty()

    ctrl.saveAll()

    result = ctrl.last_result
    assert result is not None
    assert not result.success, "partial-mutation failure must fail the save"
    assert succeeded == [], "saveSucceeded must not be emitted"

    # 1. Call order proves candidate-apply AND old-snapshot restore both ran.
    assert setter_calls == ["candidate", "restore"], (
        f"Expected candidate apply then restore, got {setter_calls}"
    )

    # 2. live_config equals the old snapshot field-by-field.
    for fn in type(old_snapshot).model_fields:
        assert getattr(live, fn) == getattr(old_snapshot, fn), (
            f"live_config field {fn} not restored: "
            f"{getattr(live, fn)!r} != {getattr(old_snapshot, fn)!r}"
        )

    # 3. JSON restored to pre-transaction content.
    restored = json.loads(config_file.read_text(encoding="utf-8"))
    assert restored.get("provider") == "openai"

    # 4. Credentials restored.
    assert store.values.get(("AIRenamer", "api_key")) == "sk-old"

    # 5. Page stays dirty.
    assert ctrl.dirty


def test_default_config_applier_still_safe(ctrl: SettingsController, live: AppConfig) -> None:
    """Without an injected applier, the production default must copy candidate
    fields onto live_config and save successfully."""
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.maxFileSizeMb = 77
    ctrl.saveAll()
    assert live.language == "en_US"
    assert live.max_file_size_mb == 77
    assert not ctrl.dirty


def test_config_applier_not_exposed_to_qml(ctrl: SettingsController) -> None:
    """The injectable applier must not become a QML-visible property."""
    from PySide6.QtCore import QMetaObject
    meta = ctrl.metaObject()
    names = []
    for i in range(meta.propertyCount()):
        names.append(meta.property(i).name())
    assert "config_applier" not in names
    assert "configApplier" not in names


# === Re-entrancy ===

def test_double_save_rejected(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.saveAll()
    r2 = ctrl.saveAll()
    assert not ctrl.dirty


# === Multi-key compensation ===

def test_multi_key_mid_failure_compensates(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    store.values[("Xuxia.Provider", "provider:qwen")] = "old-qwen"
    store.values[("Xuxia.Provider", "provider:kimi")] = "old-kimi"
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "new-qwen")
    ctrl.stageProviderKey("kimi", "new-kimi")
    store._set_fail_at = 2  # fail 2nd credential
    ctrl.saveAll()
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) == "old-qwen"
    assert store.values.get(("Xuxia.Provider", "provider:kimi")) == "old-kimi"


# === Provider profiles ===

def test_provider_profiles_from_presets(ctrl: SettingsController) -> None:
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    assert isinstance(profiles, list)
    assert len(profiles) >= 5
    ids = [p["id"] for p in profiles]
    assert "deepseek" in ids
    assert "qwen" in ids
    assert "mimo" in ids
    assert "zhipu" in ids
    assert "kimi" in ids


def test_qwen_recommended(ctrl: SettingsController) -> None:
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    qwen = next(p for p in profiles if p["id"] == "qwen")
    assert qwen["recommended"]


def test_deepseek_flash_preset_has_verified_vision(ctrl: SettingsController) -> None:
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    ds = next(p for p in profiles if p["id"] == "deepseek")
    assert ds["visionSupported"] is True


def test_mimo_json_unverified(ctrl: SettingsController) -> None:
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    mimo = next(p for p in profiles if p["id"] == "mimo")
    assert mimo["structuredJsonStatus"] == "unverified"


def test_preset_profiles_exist_without_saved_profile(ctrl: SettingsController) -> None:
    """Presets are legal profiles even when not written to provider_profiles."""
    ctrl.openSession()
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.provider_profiles == []
    ids = [p["id"] for p in ctrl.providerProfiles]
    for pid in ("deepseek", "qwen", "mimo", "zhipu", "kimi"):
        assert pid in ids


# === Key security ===

def test_no_raw_key_in_provider_profiles(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    store.values[("Xuxia.Provider", "provider:secret-prov")] = "super-secret-real-key"
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    for p in profiles:
        for v in p.values():
            if isinstance(v, str):
                assert "super-secret-real-key" not in v


# === D: credential three-state ===

def test_credential_state_configured(store: FakeCredentialStore, config_file: Path, live: AppConfig) -> None:
    store.values[("Xuxia.Provider", "provider:qwen")] = "dashscope-key"
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    assert _credential_state(store, "qwen") == "configured"
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["credentialState"] == "configured"
    assert qwen["configured"] is True
    assert qwen["credentialUnavailable"] is False


def test_credential_state_unconfigured(store: FakeCredentialStore, config_file: Path, live: AppConfig) -> None:
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    assert _credential_state(store, "qwen") == "unconfigured"
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["credentialState"] == "unconfigured"
    assert qwen["configured"] is False


def test_credential_state_unavailable(store: FakeCredentialStore, config_file: Path, live: AppConfig) -> None:
    """Store read failure must surface as unavailable, NOT forged unconfigured."""
    store._global_get_fail = True
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    assert _credential_state(store, "qwen") == "unavailable"
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["credentialState"] == "unavailable"
    assert qwen["configured"] is False, "unavailable must not masquerade as unconfigured"
    assert qwen["credentialUnavailable"] is True


# === D: stageProviderKey fail-closed ===

def test_stage_key_preset_accepted(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "dashscope-test-key")
    assert ctrl.staged_key_count == 1
    assert ctrl.dirty


def test_stage_key_custom_after_add_accepted(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "my-custom", "display_name": "My Custom", "base_url": "https://example.com/v1",
        "model": "custom-model-1", "capabilities": {"text": True},
    })
    ctrl.stageProviderKey("my-custom", "custom-secret")
    assert ctrl.staged_key_count == 1


def test_stage_key_unknown_fail_closed(ctrl: SettingsController) -> None:
    """Unknown IDs must not create orphan staged keys or credentials."""
    ctrl.openSession()
    ctrl.stageProviderKey("nonexistent-provider", "secret-orphan")
    assert ctrl.staged_key_count == 0
    assert not ctrl.dirty
    assert ctrl._credentials.values == {}
    ctrl.saveAll()
    assert ctrl._credentials.values == {}


def test_stage_key_empty_unknown_fail_closed(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.stageProviderKey("", "k")
    ctrl.stageProviderKey("  ", "k")
    assert ctrl.staged_key_count == 0
    assert not ctrl.dirty


def test_stage_key_clear_existing_schedules_delete(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-key"
    ctrl.openSession()
    ctrl.clearProviderKey("qwen")
    assert ctrl.staged_key_count == 1  # "" sentinel schedules delete
    ctrl.saveAll()
    assert ("Xuxia.Provider", "provider:qwen") not in store.values


def test_stage_key_clear_unknown_no_op(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.clearProviderKey("unknown-thing")
    assert ctrl.staged_key_count == 0
    assert not ctrl.dirty


# === D: setActiveProvider guards ===

_QWEN_CANDIDATE = {
    "id": "qwen", "display_name": "Qwen / 通义千问",
    "model": "qwen3.6-flash", "region": "virginia",
}


def _verify_qwen(ctrl: SettingsController) -> None:
    """Drive qwen through verification success with a staged key."""
    ctrl._connection_test_service = _ok_service
    ctrl.testConnectionCandidate(dict(_QWEN_CANDIDATE), "dashscope-key")
    ctrl.addOrUpdateProvider(dict(_QWEN_CANDIDATE), "dashscope-key")
    ctrl.stageProviderKey("qwen", "dashscope-key")


def test_activate_unverified_blocked(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.setActiveProvider("qwen")  # preset starts needs_connection_verification=True
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""
    assert ctrl.draft_config.active_provider_id == ""


def test_caller_cannot_forge_verified_provider_state(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "qwen", "display_name": "Qwen", "model": "qwen3.6-flash",
        "region": "virginia", "needs_connection_verification": False,
    }, "unverified-key")
    ctrl.stageProviderKey("qwen", "unverified-key")
    ctrl.setActiveProvider("qwen")
    profile = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "qwen")
    assert profile["needs_connection_verification"] is True
    assert ctrl.draft_config.active_provider_id == ""


def test_activate_unconfigured_blocked(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl._connection_test_service = _ok_service
    ctrl.testConnection("qwen", "k")  # verified but no key staged/saved
    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""


def test_activate_credential_unavailable_blocked(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    store._global_get_fail = True
    ctrl.openSession()
    ctrl._connection_test_service = _ok_service
    ctrl.stageProviderKey("qwen", "k")
    ctrl.testConnection("qwen", "k")
    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""


def test_activate_disabled_blocked(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "deepseek", "display_name": "DS", "enabled": False,
        "needs_connection_verification": False, "model": "deepseek-v4-pro",
    })
    ctrl.setActiveProvider("deepseek")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""
    errs = ctrl._validate()
    assert errs == []


def test_activate_unknown_blocked(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.setActiveProvider("no-such-provider")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""


def test_activate_after_verified_and_staged_ok(ctrl: SettingsController) -> None:
    ctrl.openSession()
    _verify_qwen(ctrl)
    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == "qwen"
    assert ctrl.activeProviderId == "qwen"


# === D: connection test state machine ===

def test_connection_success_saves_verification_state(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl._connection_test_service = _ok_service
    changed: list[bool] = []
    ctrl.providerProfilesChanged.connect(lambda: changed.append(True))
    ctrl.testConnectionCandidate(dict(_QWEN_CANDIDATE), "key-x")
    assert ctrl.connectionTestState == "success"
    # Candidate testing does NOT touch the draft; saving the identical
    # candidate persists the verified state.
    ctrl.addOrUpdateProvider(dict(_QWEN_CANDIDATE), "key-x")
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["needsConnectionVerification"] is False
    assert ctrl.dirty, "successful verification must dirty the draft"
    assert changed, "providerProfilesChanged must be emitted on verification success"
    # Draft profile persisted so activation works and survives reload
    assert ctrl.draft_config is not None
    assert any(p["id"] == "qwen" for p in ctrl.draft_config.provider_profiles)


def test_connection_failure_keeps_verification(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl._connection_test_service = _auth_fail_service
    ctrl.testConnection("qwen", "bad-key")
    assert ctrl.connectionTestState == "failure"
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["needsConnectionVerification"] is True
    assert not ctrl.dirty, "failed connection must not dirty the draft"
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""
    assert ctrl.draft_config.provider_profiles == []


def test_connection_failure_drops_staged_wrong_key(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    """A key that fails its connection test must never be persisted."""
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "wrong-key")
    assert ctrl.staged_key_count == 1
    ctrl._connection_test_service = _auth_fail_service
    ctrl.testConnectionCandidate(dict(_QWEN_CANDIDATE), "wrong-key")
    assert ctrl.connectionTestState == "failure"
    assert ctrl.staged_key_count == 0, "failed key must be dropped from staging"
    ctrl.saveAll()
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) is None


def test_connection_failure_keeps_existing_safe_state(
    ctrl: SettingsController, store: FakeCredentialStore
) -> None:
    """D.13: a failed test must not clear an already-configured credential."""
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-good-key"
    ctrl.openSession()
    ctrl._connection_test_service = _auth_fail_service
    ctrl.testConnection("qwen", "new-bad-key")
    assert ctrl.connectionTestState == "failure"
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) == "existing-good-key"


def test_connection_service_exception_failure(ctrl: SettingsController) -> None:
    ctrl.openSession()
    def _boom(profile, key):
        raise RuntimeError("network down")
    ctrl._connection_test_service = _boom
    ctrl.testConnection("qwen", "k")
    assert ctrl.connectionTestState == "failure"
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["needsConnectionVerification"] is True


def test_connection_without_service_failure(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.testConnection("qwen", "k")  # no service injected
    assert ctrl.connectionTestState == "failure"


def test_connection_success_custom_provider(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "custom-a", "display_name": "Custom A", "base_url": "https://a.example.com/v1",
        "model": "m-a", "capabilities": {"text": True},
    })
    ctrl._connection_test_service = _ok_service
    ctrl.testConnection("custom-a", "k")
    assert ctrl.connectionTestState == "success"
    prof = next(p for p in ctrl.providerProfiles if p["id"] == "custom-a")
    assert prof["needsConnectionVerification"] is False


def test_connection_unknown_id_fails_closed(ctrl: SettingsController) -> None:
    """GATE-6: an id with no preset and no draft profile must fail WITHOUT
    calling the service, mutating the draft, or staging a key."""
    ctrl.openSession()
    calls: list[object] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(p) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.testConnection("totally-unknown", "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == []
    assert not ctrl.dirty
    assert ctrl.staged_key_count == 0


# === Active provider validation ===

def test_validate_blocks_unverified_active(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "k")
    # Force active id directly (setActiveProvider refuses unverified)
    assert ctrl.draft_config is not None
    ctrl.draft_config.active_provider_id = "qwen"
    ctrl._mark_dirty()
    errs = ctrl._validate()
    # qwen was never verified, so no profile exists in the draft yet
    assert any("不存在" in e or "验证" in e for e in errs)


def test_validate_blocks_unconfigured_active(ctrl: SettingsController) -> None:
    ctrl.openSession()
    _verify_qwen(ctrl)
    assert ctrl.draft_config is not None
    ctrl.draft_config.active_provider_id = "qwen"
    ctrl._mark_dirty()
    # Remove staged key + credential so it is unconfigured
    ctrl._staged_keys.clear()
    ctrl.saveAll()  # persists verification only; staged key gone after save
    ctrl._staged_keys = {}
    assert ctrl.draft_config.active_provider_id == "qwen"
    errs = ctrl._validate()
    assert any("API Key" in e or "Key" in e for e in errs)


def test_validate_blocks_unavailable_credential_active(ctrl: SettingsController, store: FakeCredentialStore) -> None:
    ctrl.openSession()
    _verify_qwen(ctrl)
    assert ctrl.draft_config is not None
    ctrl.draft_config.active_provider_id = "qwen"
    ctrl._mark_dirty()
    store._global_get_fail = True
    errs = ctrl._validate()
    assert any("凭据服务不可用" in e for e in errs)


# === Add / remove provider ===

def test_add_custom_provider(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "custom1", "display_name": "My Custom", "base_url": "https://example.com/v1",
        "model": "m1", "capabilities": {"text": True},
    })
    profiles = ctrl.providerProfiles
    assert any(p["id"] == "custom1" for p in profiles)


def test_add_custom_provider_drafts_and_saves(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "custom1", "display_name": "My Custom", "base_url": "https://example.com/v1",
        "model": "m1", "capabilities": {"text": True, "vision": True},
    })
    ctrl.saveAll()
    saved = json.loads(ctrl._config_file_path.read_text(encoding="utf-8"))
    profiles = saved["provider_profiles"]
    assert any(p["id"] == "custom1" for p in profiles)
    assert "api_key" not in saved


def test_remove_provider(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "to-remove", "display_name": "Remove Me", "base_url": "https://r.example.com",
        "model": "m", "capabilities": {"text": True},
    })
    ctrl.removeProvider("to-remove")
    profiles = ctrl.providerProfiles
    assert not any(p["id"] == "to-remove" for p in profiles)


def test_remove_preset_refused(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.removeProvider("qwen")
    ids = [p["id"] for p in ctrl.providerProfiles]
    assert "qwen" in ids
    assert not ctrl.dirty


def test_update_existing_profile_replaces(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "custom1", "display_name": "V1", "base_url": "https://example.com/v1",
        "model": "m1", "capabilities": {"text": True},
    })
    ctrl.addOrUpdateProvider({
        "id": "custom1", "display_name": "V2", "base_url": "https://example.com/v2",
        "model": "m2", "capabilities": {"text": True, "vision": True},
    })
    profiles = ctrl.providerProfiles
    matches = [p for p in profiles if p["id"] == "custom1"]
    assert len(matches) == 1
    assert matches[0]["displayName"] == "V2"
    assert matches[0]["visionSupported"] is True


def test_add_provider_case_conflict_with_preset_rejected(ctrl: SettingsController) -> None:
    """Case-conflicting IDs (e.g. 'Qwen' vs preset 'qwen') must be rejected."""
    ctrl.openSession()
    before = [p["id"] for p in ctrl.providerProfiles]
    ctrl.addOrUpdateProvider({
        "id": "Qwen", "display_name": "Fake Qwen", "base_url": "https://evil.example.com",
        "model": "m", "capabilities": {"text": True},
    })
    after = [p["id"] for p in ctrl.providerProfiles]
    assert after == before, f"Draft must be unchanged, got {after}"
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.provider_profiles == []


def test_add_provider_case_conflict_with_custom_rejected(ctrl: SettingsController) -> None:
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "my-custom", "display_name": "C", "base_url": "https://c.example.com",
        "model": "m", "capabilities": {"text": True},
    })
    before = [p["id"] for p in ctrl.providerProfiles]
    ctrl.addOrUpdateProvider({
        "id": "My-Custom", "display_name": "C2", "base_url": "https://c2.example.com",
        "model": "m2", "capabilities": {"text": True},
    })
    after = [p["id"] for p in ctrl.providerProfiles]
    assert after == before


# === D: _safe_profile_from_dict unified validation ===

def _base_profile_dict() -> dict[str, object]:
    return {
        "id": "custom-safe", "display_name": "Safe Custom",
        "base_url": "https://api.example.com/v1", "model": "m1",
        "protocol_kind": "openai_compatible", "base_url_mode": "USER_CONFIGURED",
        "capabilities": {"text": True, "vision": False, "json_mode": False},
    }


def test_safe_profile_valid_dict_ok() -> None:
    out = _safe_profile_from_dict(_base_profile_dict())
    assert out["id"] == "custom-safe"
    assert out["display_name"] == "Safe Custom"
    assert out["model"] == "m1"
    assert out["capabilities"]["text"] is True
    # Re-round-trips through ProviderProfile validation
    from src.core.provider_profile import ProviderProfile
    restored = ProviderProfile.from_safe_dict(out)
    assert restored.id == "custom-safe"
    assert restored.base_url == "https://api.example.com/v1"


def test_safe_profile_rejects_credential_fields() -> None:
    for key in (
        "api_key", "token", "secret", "password", "authorization",
        "API_Key", "AccessToken", "api_token_value", "x-authorization-x",
    ):
        data = _base_profile_dict()
        data[key] = "sk-leak-me"
        with pytest.raises(ValueError, match="forbidden|Credential"):
            _safe_profile_from_dict(data)


def test_safe_profile_rejects_missing_id() -> None:
    data = _base_profile_dict()
    data.pop("id")
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


@pytest.mark.parametrize("bad_id", [
    "", " ", "a/b", "a\\b", "a:b", "-start", "end-", "has space", "x" * 70, "a#b",
])
def test_safe_profile_rejects_non_canonical_id(bad_id: str) -> None:
    data = _base_profile_dict()
    data["id"] = bad_id
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


@pytest.mark.parametrize("good_id", ["custom-1", "a", "provider.example_1", "A1b", "qwen-custom"])
def test_safe_profile_accepts_canonical_id(good_id: str) -> None:
    data = _base_profile_dict()
    data["id"] = good_id
    out = _safe_profile_from_dict(data)
    assert out["id"] == good_id


def test_safe_profile_rejects_http_remote_url() -> None:
    data = _base_profile_dict()
    data["base_url"] = "http://api.example.com/v1"
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_accepts_loopback_http() -> None:
    data = _base_profile_dict()
    data["base_url"] = "http://localhost:11434/v1"
    out = _safe_profile_from_dict(data)
    assert out["base_url"] == "http://localhost:11434/v1"


def test_safe_profile_rejects_url_credentials() -> None:
    data = _base_profile_dict()
    data["base_url"] = "https://user:pass@api.example.com/v1"
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


@pytest.mark.parametrize("evil_url", [
    "https://api.example.com/v1?api_key=abc",
    "https://api.example.com/v1?token=abc",
    "https://api.example.com/v1?signature=abc",
    "https://api.example.com/v1?apikey=abc&model=x",
    "https://api.example.com/v1?x=1#secret=abc",
])
def test_safe_profile_rejects_url_with_secret_params(evil_url: str) -> None:
    data = _base_profile_dict()
    data["base_url"] = evil_url
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_requires_display_name() -> None:
    data = _base_profile_dict()
    data["display_name"] = "  "
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_requires_model() -> None:
    data = _base_profile_dict()
    data["model"] = ""
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_rejects_unknown_protocol() -> None:
    data = _base_profile_dict()
    data["protocol_kind"] = "anthropic"
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_rejects_bad_capabilities() -> None:
    data = _base_profile_dict()
    data["capabilities"] = {"text": "yes", "vision": True}
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


def test_safe_profile_rejects_malformed_base_url() -> None:
    data = _base_profile_dict()
    data["base_url"] = "not-a-url"
    with pytest.raises(ValueError):
        _safe_profile_from_dict(data)


# === No second persist_metadata ===

def test_no_second_persist_on_save(ctrl: SettingsController, config_file: Path) -> None:
    """saveAll writes exactly once through SettingsSaveTransaction."""
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.saveAll()
    assert config_file.exists()
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["language"] == "en_US"



# ============================================================================
# M6 Provider Integration Gate — unified profile building + connection service
# ============================================================================

from src.core.connection_test import ConnectionOutcome, ConnectionResult


def _ok_service(profile, credential):
    return ConnectionResult(outcome=ConnectionOutcome.SUCCESS)


def _auth_fail_service(profile, credential):
    return ConnectionResult(outcome=ConnectionOutcome.AUTH_ERROR)


_CUSTOM_CANDIDATE = {
    "id": "brand-new", "display_name": "Brand New",
    "base_url": "https://bn.example.com/v1", "model": "m1",
    "capabilities": {"text": True},
}


def test_custom_single_session_verified_and_activatable(
    ctrl: SettingsController, store: FakeCredentialStore
) -> None:
    """GATE-1: new Custom in one form session — profile+key -> test success ->
    save -> must persist verified and be activatable."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()

    ctrl.testConnectionCandidate(dict(_CUSTOM_CANDIDATE), "sk-bn-2026")
    assert ctrl.connectionTestState == "success"
    # testing must NOT mutate the draft
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.provider_profiles == []

    ctrl.addOrUpdateProvider(dict(_CUSTOM_CANDIDATE), "sk-bn-2026")
    assert ctrl.draft_config.provider_profiles, "save must add the custom provider"
    prof = next(
        p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new"
    )
    assert prof["needs_connection_verification"] is False, (
        "verified in the same session must persist needs_connection_verification=false"
    )

    ctrl.stageProviderKey("brand-new", "sk-bn-2026")
    ctrl.setActiveProvider("brand-new")
    assert ctrl.draft_config.active_provider_id == "brand-new"

    ctrl.saveAll()
    assert ctrl.last_result is not None and ctrl.last_result.success


def test_custom_candidate_change_invalidates_verification(
    ctrl: SettingsController,
) -> None:
    """GATE-5: changing any field after a successful test must invalidate the
    fingerprint — saving then keeps the provider unverified."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(dict(_CUSTOM_CANDIDATE), "sk-bn-2026")
    assert ctrl.connectionTestState == "success"

    changed = dict(_CUSTOM_CANDIDATE)
    changed["model"] = "m2"  # any field changed
    ctrl.addOrUpdateProvider(changed, "sk-bn-2026")
    prof = next(
        p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new"
    )
    assert prof["needs_connection_verification"] is True, (
        "fingerprint must invalidate when a field changed after the test"
    )


def test_custom_key_change_invalidates_verification(ctrl: SettingsController) -> None:
    """GATE-5: changing the key after a successful test must invalidate."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(dict(_CUSTOM_CANDIDATE), "sk-bn-2026")
    assert ctrl.connectionTestState == "success"

    ctrl.addOrUpdateProvider(dict(_CUSTOM_CANDIDATE), "sk-DIFFERENT-2026")
    prof = next(
        p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new"
    )
    assert prof["needs_connection_verification"] is True


def test_test_failure_adds_nothing_to_draft(ctrl: SettingsController) -> None:
    """GATE-5: a failed test must not add the provider or persist the key."""
    ctrl._connection_test_service = _auth_fail_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(dict(_CUSTOM_CANDIDATE), "sk-bn-2026")
    assert ctrl.connectionTestState == "failure"
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.provider_profiles == []
    ctrl.saveAll()
    assert ctrl._credentials.values == {}


def test_connection_unknown_id_no_service_call(ctrl: SettingsController) -> None:
    """GATE-6: testConnection on an unknown id must fail WITHOUT calling the
    connection service."""
    calls: list[tuple[object, str]] = []

    def _svc(profile, credential):
        calls.append((profile, credential))
        return ConnectionResult(outcome=ConnectionOutcome.SUCCESS)

    ctrl._connection_test_service = _svc
    ctrl.openSession()
    ctrl.testConnection("totally-unknown", "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == [], "connection service must not be called for unknown ids"
    assert not ctrl.dirty
    assert ctrl.staged_key_count == 0


def test_qwen_preset_profile_built_with_preset_rules(ctrl: SettingsController) -> None:
    """GATE-4: a saved Qwen profile must carry provider_id=qwen, REGIONAL
    base_url_mode, a legal region, and the resolved official HTTPS endpoint —
    never provider_id='custom'."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "beijing",
        "workspace_id": "w-1234567890",
    }
    ctrl.testConnectionCandidate(dict(candidate), "sk-qwen-1")
    assert ctrl.connectionTestState == "success", "valid qwen region must test ok"
    ctrl.addOrUpdateProvider(dict(candidate), "sk-qwen-1")
    qwen = next(
        p for p in ctrl.draft_config.provider_profiles if p["id"] == "qwen"
    )
    assert qwen["provider_id"] == "qwen", "preset must keep provider_id=qwen"
    assert qwen["base_url_mode"] == "REGIONAL"
    assert qwen["region"] == "beijing"
    assert qwen["base_url"] == (
        "https://w-1234567890.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    ), "base_url not resolved from preset endpoint template"
    assert qwen["credential_account_id"] == "provider:qwen"
    assert qwen["needs_connection_verification"] is False


def test_qwen_virginia_no_workspace_ok(ctrl: SettingsController) -> None:
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "virginia",
    }
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "success"
    ctrl.addOrUpdateProvider(dict(candidate), "k")
    qwen = next(
        p for p in ctrl.draft_config.provider_profiles if p["id"] == "qwen"
    )
    assert qwen["base_url"] == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"


def test_qwen_requires_region(ctrl: SettingsController) -> None:
    """REGIONAL presets need a region — no region must fail closed."""
    calls: list[object] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(p) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.openSession()
    candidate = {"id": "qwen", "display_name": "Qwen / 通义千问", "model": "qwen3.6-flash"}
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == [], "service must not be called for an unbuildable profile"


def test_qwen_requires_workspace_for_region(ctrl: SettingsController) -> None:
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "beijing",
    }
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "failure"


def test_qwen_rejects_unknown_region(ctrl: SettingsController) -> None:
    calls: list[object] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(p) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "mars",
    }
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == []


def test_fixed_endpoint_preset_base_url_override_rejected(ctrl: SettingsController) -> None:
    """GATE: fixed-endpoint presets must not allow Base URL override."""
    calls: list[object] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(p) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.openSession()
    candidate = {
        "id": "deepseek", "display_name": "DeepSeek",
        "model": "deepseek-v4-flash", "base_url": "https://evil.example.com/v1",
    }
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == []


def test_requires_user_model_preset_requires_model(ctrl: SettingsController) -> None:
    calls: list[object] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(p) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.openSession()
    candidate = {"id": "zhipu", "display_name": "Zhipu"}
    ctrl.testConnectionCandidate(dict(candidate), "k")
    assert ctrl.connectionTestState == "failure"
    assert calls == []


def test_connection_service_receives_complete_profile(ctrl: SettingsController) -> None:
    """GATE: the connection service must receive a fully built ProviderProfile."""
    received: list[tuple[object, str]] = []

    def _svc(profile, credential):
        received.append((profile, credential))
        return ConnectionResult(outcome=ConnectionOutcome.SUCCESS)

    ctrl._connection_test_service = _svc
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {
            "id": "my-custom", "display_name": "My Custom",
            "base_url": "https://custom.example.com/v1", "model": "m1",
            "capabilities": {"text": True, "vision": True},
        },
        "sk-xyz-2026",
    )
    assert received, "service must be called with the built profile"
    profile, credential = received[0]
    from src.core.provider_profile import ProviderProfile
    assert isinstance(profile, ProviderProfile)
    assert profile.id == "my-custom"
    assert profile.provider_id == "custom"
    assert profile.base_url == "https://custom.example.com/v1"
    assert profile.model == "m1"
    assert profile.capabilities.text is True
    assert profile.capabilities.vision is True
    assert credential == "sk-xyz-2026"


def test_connection_uses_stored_credential_when_key_empty(
    ctrl: SettingsController, store: FakeCredentialStore
) -> None:
    """GATE: for a saved provider with an empty key input, the controller may
    read the key internally from the CredentialStore — never returns it to QML."""
    store.values[("Xuxia.Provider", "provider:qwen")] = "stored-secret"
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    ctrl.addOrUpdateProvider(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    received: list[str] = []
    ctrl._connection_test_service = (
        lambda p, k: received.append(k) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    ctrl.testConnection("qwen", "")
    assert received == ["stored-secret"], "controller must read the stored key internally"


def test_connection_store_unavailable_fail_closed(
    ctrl: SettingsController, store: FakeCredentialStore
) -> None:
    store.values[("Xuxia.Provider", "provider:qwen")] = "stored-secret"
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    ctrl.addOrUpdateProvider(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    calls: list[str] = []
    ctrl._connection_test_service = (
        lambda p, k: calls.append(k) or ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
    )
    store._global_get_fail = True
    ctrl.testConnection("qwen", "")
    assert ctrl.connectionTestState == "failure"
    assert calls == []


def test_connection_result_associated_with_provider(ctrl: SettingsController) -> None:
    """GATE: connection state must be scoped to the provider under test."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    assert ctrl.connectionTestState == "success"
    assert ctrl.connectionTestProviderId == "qwen"
    assert ctrl.connectionTestStateFor("kimi") == "idle"
    assert ctrl.connectionTestStateFor("qwen") == "success"


def test_qwen_saved_profile_loads_in_provider_manager(
    ctrl: SettingsController, store: FakeCredentialStore, config_file: Path
) -> None:
    """GATE-4: the M6-saved AppConfig must load in ProviderManager with a
    valid Qwen profile (region, resolved endpoint, canonical account)."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "beijing",
        "workspace_id": "w-1234567890",
    }
    ctrl.testConnectionCandidate(dict(candidate), "sk-qwen-wf")
    ctrl.addOrUpdateProvider(dict(candidate), "sk-qwen-wf")
    ctrl.stageProviderKey("qwen", "sk-qwen-wf")
    ctrl.setActiveProvider("qwen")
    ctrl.saveAll()

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    qwen = next(p for p in saved["provider_profiles"] if p["id"] == "qwen")
    assert qwen["provider_id"] == "qwen"
    assert qwen["base_url_mode"] == "REGIONAL"
    assert qwen["region"] == "beijing"
    assert qwen["base_url"].startswith("https://")
    assert qwen["credential_account_id"] == "provider:qwen"
    assert "api_key" not in saved

    from src.core.provider_manager import ProviderManager
    pm = ProviderManager(
        config=ctrl._live_config,
        persist_config=lambda cfg: None,
        credential_store=store,
    )
    profiles = pm.list_profiles()
    assert any(p.id == "qwen" for p in profiles)
    active = pm.get_active()
    assert active is not None and active.id == "qwen"
    assert active.base_url_mode == "REGIONAL"
    assert active.region == "beijing"
    assert active.credential_account_id == "provider:qwen"
    assert pm.get_credential_status("qwen") is True


def test_custom_saved_profile_loads_in_provider_manager(
    ctrl: SettingsController, store: FakeCredentialStore, config_file: Path
) -> None:
    """GATE-5: a saved Custom profile must load in ProviderManager with a
    canonical credential account."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "my-custom", "display_name": "My Custom",
        "base_url": "https://custom.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    }
    ctrl.testConnectionCandidate(dict(candidate), "sk-custom-wf")
    ctrl.addOrUpdateProvider(dict(candidate), "sk-custom-wf")
    ctrl.stageProviderKey("my-custom", "sk-custom-wf")
    ctrl.setActiveProvider("my-custom")
    ctrl.saveAll()

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    prof = next(p for p in saved["provider_profiles"] if p["id"] == "my-custom")
    assert prof["credential_account_id"] == "provider:my-custom", (
        "credential account must be canonical"
    )
    assert prof["provider_id"] == "custom"

    from src.core.provider_manager import ProviderManager
    pm = ProviderManager(
        config=ctrl._live_config,
        persist_config=lambda cfg: None,
        credential_store=store,
    )
    assert any(p.id == "my-custom" for p in pm.list_profiles())
    active = pm.get_active()
    assert active is not None and active.id == "my-custom"
    assert active.credential_account_id == "provider:my-custom"
    assert pm.get_credential_status("my-custom") is True


def test_provider_manager_rejects_unverified_active_after_m6_save(
    ctrl: SettingsController, store: FakeCredentialStore, config_file: Path
) -> None:
    """GATE: fingerprint-invalidated saves must NOT produce an activatable
    state — activation must stay blocked for the unverified profile."""
    ctrl._connection_test_service = _ok_service
    ctrl.openSession()
    candidate = {
        "id": "my-custom", "display_name": "My Custom",
        "base_url": "https://custom.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    }
    ctrl.testConnectionCandidate(dict(candidate), "sk-ok")
    # key changed before save -> verification invalidated
    ctrl.addOrUpdateProvider(dict(candidate), "sk-CHANGED")
    prof = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "my-custom")
    assert prof["needs_connection_verification"] is True
    # cannot be activated until verified again
    ctrl.stageProviderKey("my-custom", "sk-CHANGED")
    ctrl.setActiveProvider("my-custom")
    assert ctrl.draft_config.active_provider_id == ""


def test_custom_single_session_real_service_fake_transport(
    ctrl: SettingsController, store: FakeCredentialStore, config_file: Path
) -> None:
    """GATE-P0: full custom single-session flow using the PRODUCTION-shaped
    connection service (real ConnectionTest over the adapter) with a fake
    transport — no SUCCESS lambda, no real network."""
    from dataclasses import replace
    from src.qml_bootstrap import build_production_connection_service
    from src.services.retry_policy import RetryExecutor, RetryPolicy
    from tests.unit.test_connection_test import _FakeTransport, _minimal_probe_response

    from tests.qml.test_qml_bootstrap import _guarded_transport
    transport = _guarded_transport([_minimal_probe_response(model="brand-new-model")])
    guarded_service = build_production_connection_service(
        transport=transport,
        retry_executor=RetryExecutor(RetryPolicy(max_retries=0), sleeper=lambda d: None),
    )
    # Deliberate standalone legacy controller seam, not default runtime evidence.
    from src.core.processing_authority import ProcessingAuthority, ProcessingMode
    from src.core.processing_identity import cloud_engine_fingerprint
    from src.providers.openai_compatible import ProcessingDispatch
    authority = ProcessingAuthority(initial_mode=ProcessingMode.CLOUD)
    def legacy_service(profile, key):
        context = authority.capture_cloud_probe(candidate_fingerprint=cloud_engine_fingerprint(profile),
            candidate_model=profile.model, request_id="synthetic-standalone-probe")
        return guarded_service(profile, key, processing_dispatch=ProcessingDispatch(authority, context))
    ctrl._connection_test_service = legacy_service
    ctrl.openSession()

    candidate = {
        "id": "brand-new", "display_name": "Brand New",
        "base_url": "https://bn.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    }
    key = "sk-real-service-2026"
    ctrl.testConnectionCandidate(dict(candidate), key)
    assert ctrl.connectionTestState == "success", (
        "production-shaped service must succeed on the unverified custom candidate"
    )
    assert len(transport.calls) == 1

    ctrl.addOrUpdateProvider(dict(candidate), key)
    prof = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new")
    assert prof["needs_connection_verification"] is False, (
        "fingerprint-matched save must persist verified state"
    )

    ctrl.stageProviderKey("brand-new", key)
    ctrl.setActiveProvider("brand-new")
    assert ctrl.draft_config.active_provider_id == "brand-new"

    ctrl.saveAll()
    assert ctrl.last_result is not None and ctrl.last_result.success
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert "api_key" not in saved
    assert "sk-real-service-2026" not in config_file.read_text(encoding="utf-8")
    assert store.values.get(("Xuxia.Provider", "provider:brand-new")) == key

    # any field or key change after the successful test re-invalidates
    transport._responses.append(_minimal_probe_response(model="brand-new-model"))
    ctrl.testConnectionCandidate(dict(candidate), key)
    assert ctrl.connectionTestState == "success"
    changed = dict(candidate)
    changed["model"] = "m2"
    ctrl.addOrUpdateProvider(changed, key)
    prof2 = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new")
    assert prof2["needs_connection_verification"] is True, (
        "field change must invalidate the fingerprint and re-require verification"
    )
    ctrl.addOrUpdateProvider(dict(candidate), "sk-DIFFERENT")
    prof3 = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "brand-new")
    assert prof3["needs_connection_verification"] is True, (
        "key change must invalidate the fingerprint"
    )
