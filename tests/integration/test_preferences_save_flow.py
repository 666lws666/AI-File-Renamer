"""Integration: Preferences save flow through SettingsController + Transaction.

M6 functional gate:
- Qwen preset: stage key -> simulated connection success -> activate -> saveAll
  -> reload config -> active_provider_id + verification state correct; JSON has
  no key; FakeCredentialStore holds the key.
- Negative paths: connection failure, credential service unavailable, unknown
  provider id, malicious profile fields, illegal URLs.
"""
import json
from pathlib import Path

import pytest

from src.controllers.settings_controller import SettingsController
from src.core.connection_test import ConnectionOutcome, ConnectionResult
from src.models.app_config import AppConfig


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}
        self.fail_get = False

    def get(self, s, a):
        if self.fail_get:
            raise OSError("Credential Manager unavailable")
        return self.values.get((s, a))

    def set(self, s, a, v):
        self.values[(s, a)] = v
        return True

    def delete(self, s, a):
        self.values.pop((s, a), None)
        return True


def make_config(**kw):
    d = {"provider": "deepseek", "api_key": "", "base_url": "https://api.deepseek.com/v1",
         "model": "deepseek-v4-pro", "language": "zh_CN", "theme": "light",
         "max_file_size_mb": 50, "max_content_chars": 4000}
    d.update(kw)
    return AppConfig(**d)


def _make_ctrl(tmp_path: Path, store=None, live=None, service=None):
    config_file = tmp_path / "settings.json"
    ctrl = SettingsController(
        live_config=live if live is not None else make_config(),
        config_file_path=config_file,
        credential_store=store if store is not None else FakeCredentialStore(),
        connection_test_service=service,
    )
    return ctrl


def test_full_save_flow(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    live = make_config()
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.maxFileSizeMb = 88
    ctrl.stageProviderKey("qwen", "dashscope-integration-key")
    ctrl.saveAll()

    assert live.language == "en_US"
    assert live.max_file_size_mb == 88
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) == "dashscope-integration-key"
    assert config_file.exists()
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert "api_key" not in saved
    assert saved["language"] == "en_US"


def test_cancel_discards_all(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    live = make_config()
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.stageProviderKey("qwen", "secret-not-persisted")
    ctrl.cancel()
    assert not ctrl.sessionOpen
    assert ctrl.staged_key_count == 0
    assert not config_file.exists()
    assert live.language == "zh_CN"


def test_multi_key_compensation(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    store.values[("Xuxia.Provider", "provider:qwen")] = "old-qwen"
    store.values[("Xuxia.Provider", "provider:kimi")] = "old-kimi"
    live = make_config()
    ctrl = SettingsController(live_config=live, config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "new-qwen")
    ctrl.stageProviderKey("kimi", "new-kimi")

    set_count = [0]
    orig_set = store.set
    def _failing_set(svc, acct, sec):
        set_count[0] += 1
        if set_count[0] == 2:
            return False
        return orig_set(svc, acct, sec)
    import types
    store.set = types.MethodType(_failing_set, store)
    ctrl.saveAll()
    assert ctrl.last_result is not None and not ctrl.last_result.success
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) == "old-qwen"
    assert store.values.get(("Xuxia.Provider", "provider:kimi")) == "old-kimi"


# ============================================================================
# D.15 — Qwen preset full workflow: stage key -> connect -> activate -> save
# -> reload -> state correct, JSON key-free, credential store holds the key
# ============================================================================

def test_qwen_full_workflow_persists_verification(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    live = make_config()
    sentinel_key = "dashscope-qwen-workflow-key-20260802"

    ctrl = SettingsController(
        live_config=live,
        config_file_path=config_file,
        credential_store=store,
        connection_test_service=lambda profile, key: (
            ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
            if profile.id == "qwen" and key == sentinel_key
            else ConnectionResult(outcome=ConnectionOutcome.AUTH_ERROR)
        ),
    )
    ctrl.openSession()

    # 1. Qwen preset is present
    qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen["recommended"]
    assert qwen["needsConnectionVerification"] is True

    # 2. Candidate (REGIONAL preset with region + workspace) + staged key
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "beijing",
        "workspace_id": "w-1234567890",
    }
    ctrl.stageProviderKey("qwen", sentinel_key)
    assert ctrl.dirty

    # 3. Simulated connection success
    ctrl.testConnectionCandidate(dict(candidate), sentinel_key)
    assert ctrl.connectionTestState == "success"
    ctrl.addOrUpdateProvider(dict(candidate), sentinel_key)
    qwen_after = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
    assert qwen_after["needsConnectionVerification"] is False
    assert ctrl.dirty

    # 4. Activate Qwen
    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == "qwen"

    # 5. saveAll
    ctrl.saveAll()
    assert not ctrl.dirty
    assert ctrl.last_result is not None and ctrl.last_result.success
    assert live.active_provider_id == "qwen"

    # 6. JSON: active id + verification state correct; NO key anywhere
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["active_provider_id"] == "qwen"
    saved_profiles = saved["provider_profiles"]
    qwen_saved = next(p for p in saved_profiles if p["id"] == "qwen")
    assert qwen_saved["needs_connection_verification"] is False
    assert "api_key" not in saved
    assert sentinel_key not in config_file.read_text(encoding="utf-8")
    assert "sk-" not in config_file.read_text(encoding="utf-8")

    # 7. FakeCredentialStore holds the key
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) == sentinel_key

    # 8. Reload from disk: new controller sees verified, active, configured
    from src.config import load_config
    import src.config
    import src.utils.credential_manager as credential_manager

    original_config_file = src.config.CONFIG_FILE
    original_config_dir = src.config.CONFIG_DIR
    original_config_file_value = str(original_config_file)
    original_config_dir_value = str(original_config_dir)
    denied_credential_calls = []

    def deny_real_credential(*args, **kwargs):
        denied_credential_calls.append("real credential access")
        raise AssertionError("metadata reload must not access real credentials")

    with monkeypatch.context() as reload_guard:
        for module in (src.config, credential_manager):
            for name in ("get_credential", "get_credential_strict",
                         "set_credential", "delete_credential"):
                reload_guard.setattr(module, name, deny_real_credential)
        reloaded = load_config(config_file, load_credentials=False)

    assert denied_credential_calls == [], "reload attempted real credential access"
    assert reloaded.api_key == ""
    assert src.config.CONFIG_FILE is original_config_file
    assert src.config.CONFIG_DIR is original_config_dir
    assert str(src.config.CONFIG_FILE) == original_config_file_value
    assert str(src.config.CONFIG_DIR) == original_config_dir_value
    assert reloaded.active_provider_id == "qwen"
    reloaded_qwen = next(p for p in reloaded.provider_profiles if p["id"] == "qwen")
    assert reloaded_qwen["needs_connection_verification"] is False

    ctrl2 = SettingsController(
        live_config=reloaded,
        config_file_path=config_file,
        credential_store=store,
    )
    ctrl2.openSession()
    assert ctrl2.activeProviderId == "qwen"
    qwen2 = next(p for p in ctrl2.providerProfiles if p["id"] == "qwen")
    assert qwen2["configured"] is True
    assert qwen2["needsConnectionVerification"] is False
    assert qwen2["active"] is True
    # Activation works after restart (verified + configured)
    ctrl2.setActiveProvider("qwen")
    assert ctrl2.draft_config is not None
    assert ctrl2.draft_config.active_provider_id == "qwen"


# ============================================================================
# D.16 — negative paths
# ============================================================================

def test_connection_failure_blocks_activation_and_persists_nothing(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    live = make_config()
    ctrl = SettingsController(
        live_config=live,
        config_file_path=config_file,
        credential_store=store,
        connection_test_service=lambda pid, key: False,
    )
    ctrl.openSession()
    ctrl.stageProviderKey("qwen", "wrong-key")
    ctrl.testConnection("qwen", "wrong-key")
    assert ctrl.connectionTestState == "failure"

    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.active_provider_id == ""

    ctrl.saveAll()
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved.get("active_provider_id", "") == ""
    # failure persists nothing: no qwen profile entry was saved
    saved_qwen_ids = [p["id"] for p in saved.get("provider_profiles", [])]
    assert "qwen" not in saved_qwen_ids
    # the wrong key was never saved
    assert store.values.get(("Xuxia.Provider", "provider:qwen")) is None
    assert "wrong-key" not in config_file.read_text(encoding="utf-8")


def test_credential_service_unavailable_blocks_activation(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-key"
    live = make_config()
    ctrl = SettingsController(
        live_config=live,
        config_file_path=config_file,
        credential_store=store,
        connection_test_service=lambda profile, key: ConnectionResult(
            outcome=ConnectionOutcome.SUCCESS
        ),
    )
    ctrl.openSession()
    candidate = {
        "id": "qwen", "display_name": "Qwen / 通义千问",
        "model": "qwen3.6-flash", "region": "virginia",
    }
    ctrl.testConnectionCandidate(dict(candidate), "k")  # verified
    ctrl.addOrUpdateProvider(dict(candidate), "k")
    # provider was active before the service died
    assert ctrl.draft_config is not None
    ctrl.draft_config.active_provider_id = "qwen"
    ctrl._mark_dirty()
    store.fail_get = True  # service now unavailable
    ctrl.setActiveProvider("qwen")
    assert ctrl.draft_config.active_provider_id == "qwen"  # already active, not re-set
    errs = ctrl._validate()
    assert any("凭据服务不可用" in e for e in errs)


def test_stage_key_unknown_provider_fail_closed(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    ctrl = SettingsController(live_config=make_config(), config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    ctrl.stageProviderKey("evil-unknown", "sk-orphan-key")
    assert ctrl.staged_key_count == 0
    ctrl.saveAll()
    assert store.values == {}, "no orphan credential may be created"


def test_malicious_profile_fields_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    ctrl = SettingsController(live_config=make_config(), config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "evil", "display_name": "Evil", "base_url": "https://evil.example.com",
        "model": "m", "capabilities": {"text": True}, "api_key": "sk-stolen",
    })
    # fail-closed: nothing added to draft
    assert ctrl.draft_config is not None
    assert ctrl.draft_config.provider_profiles == []
    assert not any(p["id"] == "evil" for p in ctrl.providerProfiles)
    assert not ctrl.dirty


def test_illegal_url_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    store = FakeCredentialStore()
    ctrl = SettingsController(live_config=make_config(), config_file_path=config_file, credential_store=store)
    ctrl.openSession()
    for bad_url in ("http://remote.example.com/v1", "https://h/v1?api_key=abc", "not-a-url"):
        ctrl.addOrUpdateProvider({
            "id": "bad-url", "display_name": "Bad", "base_url": bad_url,
            "model": "m", "capabilities": {"text": True},
        })
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.provider_profiles == []


def test_case_conflict_id_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.json"
    ctrl = SettingsController(live_config=make_config(), config_file_path=config_file, credential_store=FakeCredentialStore())
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "Qwen", "display_name": "Imposter", "base_url": "https://fake.example.com",
        "model": "m", "capabilities": {"text": True},
    })
    ids = [p["id"] for p in ctrl.providerProfiles]
    assert "Qwen" not in ids
    assert "qwen" in ids
