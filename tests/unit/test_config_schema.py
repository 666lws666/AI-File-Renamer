"""M0 Task 6: Config schema versioning and migration tests.

ALL tests use monkeypatch + tmp_path + mock keyring.
Never touches real settings.json or Windows Credential Manager.
"""

import hashlib
import json
from unittest.mock import patch

import pytest

from src.config import (
    ConfigSaveError,
    CredentialSaveError,
    load_config,
    save_config,
    save_config_metadata,
)
from src.models.app_config import AppConfig


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect config to temp dir."""
    cd = tmp_path / "config"
    cf = cd / "settings.json"
    monkeypatch.setattr("src.config.CONFIG_DIR", cd)
    monkeypatch.setattr("src.config.CONFIG_FILE", cf)
    monkeypatch.setattr("src.config.TEMPLATES_DIR", cd / "templates")
    return cd, cf


@pytest.fixture
def mock_kr():
    store = {}
    def _g(s, a): return store.get(f"{s}/{a}")
    def _s(s, a, p): store[f"{s}/{a}"] = p
    def _d(s, a): store.pop(f"{s}/{a}", None)
    with patch("keyring.get_password", side_effect=_g), \
         patch("keyring.set_password", side_effect=_s), \
         patch("keyring.delete_password", side_effect=_d):
        yield store


# ── Schema version written on save ────────────────────

def test_new_config_has_schema_version(isolated, mock_kr):
    """Newly saved config writes schema_version."""
    _, cf = isolated
    config = AppConfig(provider="deepseek", api_key="", model="deepseek-v4-flash")
    save_config(config)
    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "schema_version" in data, "New config missing schema_version"
    assert data["schema_version"] == 2


# ── Old config without version is migrated ────────────

def test_old_config_migrates_to_version_1(isolated, mock_kr):
    """Config without schema_version loads and is migrated."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    old = {"provider": "deepseek", "model": "deepseek-v4-flash"}
    cf.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")

    config = load_config()
    assert config.provider == "deepseek"
    assert config.model == "deepseek-v4-flash"

    # After load, the file should have been migrated
    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("schema_version") == 2, "Old config not migrated to version 2"


# ── Migration preserves existing fields ───────────────

def test_migration_preserves_fields(isolated, mock_kr):
    """Migration does not drop existing config fields."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    old = {
        "provider": "openai",
        "model": "gpt-4",
        "base_url": "https://api.openai.com/v1",
        "max_file_size_mb": 100,
        "language": "en",
    }
    cf.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")

    config = load_config()
    assert config.provider == "openai"
    assert config.model == "gpt-4"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.max_file_size_mb == 100
    assert config.language == "en"

    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("schema_version") == 2
    for k in old:
        assert data.get(k) == old[k], f"Field {k} lost during migration"


# ── api_key still excluded ────────────────────────────

def test_api_key_still_excluded_after_migration(isolated, mock_kr):
    """api_key remains excluded from JSON after migration."""
    _, cf = isolated
    config = AppConfig(provider="deepseek", api_key="sk-test-migrate", model="deepseek-v4-flash")
    save_config(config)
    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "api_key" not in data, "api_key must never appear in JSON"
    assert data.get("schema_version") == 2


# ── Future version rejected ───────────────────────────

def test_future_version_rejected(isolated, mock_kr):
    """Config with version higher than current raises clear error."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    future = {"schema_version": 99, "provider": "deepseek", "model": "dummy"}
    cf.write_text(json.dumps(future, indent=2, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        load_config()
    # Must be a clear version error, not silently swallowed
    assert "schema_version" in str(exc_info.value).lower() or "version" in str(exc_info.value).lower(), (
        f"Future version should raise version error, got: {exc_info.value}"
    )


# ── Future version distinguishable from corrupt JSON ──

def test_future_version_not_confused_with_corrupt(isolated, mock_kr):
    """Future version error is distinct from corrupt JSON error."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)

    # Corrupt JSON
    cf.write_text("not valid json {{{", encoding="utf-8")
    config = load_config()
    # Corrupt JSON → graceful default, not crash
    assert config.provider == "deepseek"  # default

    # Future version — different file
    cf2 = cd / "settings_future.json"
    monkeypatch2 = pytest.MonkeyPatch()
    # We need to re-test with future version on a clean load
    # Just verify they produce different error paths
    future = {"schema_version": 99, "provider": "deepseek"}
    cf.write_text(json.dumps(future), encoding="utf-8")
    with pytest.raises(Exception):
        load_config()
    # This proves future version is NOT silently treated as corrupt/default


# ── Future schema + legacy key: zero side effects ─────

def test_future_schema_with_legacy_api_key_has_zero_side_effects(isolated, mock_kr):
    """Future version + api_key: no credential calls, no JSON rewrite, no migration."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    future = {"schema_version": 99, "provider": "deepseek", "api_key": "sk-legacy-do-not-migrate"}
    cf.write_text(json.dumps(future, indent=2, ensure_ascii=False), encoding="utf-8")
    original_hash = hashlib.sha256(cf.read_bytes()).hexdigest()

    import src.config
    atomic_calls = []
    original_atomic = src.config._atomic_write_json

    def _spy_atomic(filepath, data):
        atomic_calls.append(str(filepath))
        return original_atomic(filepath, data)

    src.config._atomic_write_json = _spy_atomic
    try:
        with pytest.raises(Exception):
            load_config()
        # JSON file must be completely unchanged
        new_hash = hashlib.sha256(cf.read_bytes()).hexdigest()
        assert new_hash == original_hash, (
            f"JSON was modified by future version load! hash before={original_hash}, after={new_hash}"
        )
        # No atomic write should have occurred
        assert len(atomic_calls) == 0, f"_atomic_write_json called {len(atomic_calls)} times"
        # Keyring mock store should be empty (no set_credential called)
        assert mock_kr == {}, f"set_credential was called: {mock_kr}"
    finally:
        src.config._atomic_write_json = original_atomic


def test_future_schema_without_key_has_zero_side_effects(isolated, mock_kr):
    """Future version without api_key also produces zero side effects."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    future = {"schema_version": 99, "provider": "deepseek"}
    cf.write_text(json.dumps(future, indent=2, ensure_ascii=False), encoding="utf-8")
    original_hash = hashlib.sha256(cf.read_bytes()).hexdigest()

    with pytest.raises(Exception):
        load_config()
    new_hash = hashlib.sha256(cf.read_bytes()).hexdigest()
    assert new_hash == original_hash, "JSON was modified by future version load"
    assert mock_kr == {}, "Credential calls were made during future version load"


def test_future_schema_error_is_not_config_save_error(isolated, mock_kr):
    """Future version must raise a distinct error type, not ConfigSaveError."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    future = {"schema_version": 99, "provider": "deepseek"}
    cf.write_text(json.dumps(future, indent=2, ensure_ascii=False), encoding="utf-8")

    # Must NOT raise ConfigSaveError (that implies a write-side error)
    with pytest.raises(Exception) as exc_info:
        load_config()
    assert not isinstance(exc_info.value, ConfigSaveError), (
        f"Future schema should not use ConfigSaveError: {type(exc_info.value)}"
    )


def test_supported_legacy_config_migrates_only_after_version_check(isolated, mock_kr):
    """A supported (version 0/1) legacy config with api_key successfully migrates."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    old = {"provider": "deepseek", "api_key": "sk-migrate-me", "model": "deepseek-v4-flash"}
    cf.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")

    config = load_config()
    assert config.api_key == "sk-migrate-me"
    assert mock_kr.get("AIRenamer/api_key") == "sk-migrate-me"
    with open(cf, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "api_key" not in data
    assert data.get("schema_version") == 2


def test_credential_migration_failure_leaves_v1_json_byte_for_byte_unchanged(
    isolated, mock_kr, monkeypatch
):
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    legacy = {
        "schema_version": 1,
        "provider": "deepseek",
        "api_key": "sk-must-remain-until-retry",
        "model": "legacy-model",
    }
    original = json.dumps(legacy, indent=2, ensure_ascii=False).encode("utf-8")
    cf.write_bytes(original)
    monkeypatch.setattr("src.config.set_credential", lambda *args, **kwargs: False)

    loaded = load_config()

    assert loaded.schema_version == 1
    assert cf.read_bytes() == original
    assert json.loads(cf.read_text(encoding="utf-8")) == legacy


def test_credential_read_failure_aborts_legacy_migration_without_mutation(
    isolated, mock_kr, monkeypatch
):
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    legacy = {
        "schema_version": 1,
        "provider": "deepseek",
        "api_key": "sk-original",
        "model": "legacy-model",
    }
    original = json.dumps(legacy, indent=2, ensure_ascii=False).encode("utf-8")
    cf.write_bytes(original)
    set_calls = []
    monkeypatch.setattr(
        "src.config.get_credential_strict",
        lambda: (_ for _ in ()).throw(OSError("credential backend unavailable")),
    )
    monkeypatch.setattr(
        "src.config.set_credential",
        lambda *args, **kwargs: set_calls.append((args, kwargs)) or True,
    )

    load_config()

    assert cf.read_bytes() == original
    assert set_calls == []


# ── Migration failure does not corrupt original ────────

def test_migration_failure_preserves_original(isolated, mock_kr):
    """If migration write fails, original config is preserved."""
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    old = {"provider": "deepseek", "model": "deepseek-v4-flash", "max_file_size_mb": 42}
    cf.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")

    # Force atomic write to fail
    import src.config
    original_atomic = src.config._atomic_write_json

    def _failing_write(filepath, data):
        raise OSError("Simulated disk failure during migration write")

    src.config._atomic_write_json = _failing_write
    try:
        # Migration write fails → load_config falls back to defaults
        # The critical property: original file must NOT be corrupted
        load_config()
        # Original file must be intact (not overwritten by migration attempt)
        with open(cf, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved == old, "Original config corrupted by failed migration"
    finally:
        src.config._atomic_write_json = original_atomic


def test_version_1_migrates_to_provider_schema_version_2(isolated, mock_kr):
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    version_1 = {
        "schema_version": 1,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "legacy-model",
    }
    cf.write_text(json.dumps(version_1), encoding="utf-8")

    config = load_config()

    assert config.provider_profiles == []
    assert config.active_provider_id == ""
    saved = json.loads(cf.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["provider_profiles"] == []
    assert saved["active_provider_id"] == ""
    assert saved["provider"] == "deepseek"
    assert saved["model"] == "legacy-model"


def test_provider_metadata_save_never_touches_legacy_credential(
    isolated, mock_kr
):
    _, cf = isolated
    mock_kr["AIRenamer/api_key"] = "legacy-secret"
    config = AppConfig(
        provider_profiles=[
            {
                "id": "qwen-main",
                "display_name": "Qwen",
                "credential_account_id": "provider:qwen-main",
            }
        ],
        active_provider_id="qwen-main",
    )

    save_config_metadata(config)

    assert mock_kr["AIRenamer/api_key"] == "legacy-secret"
    saved = json.loads(cf.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["active_provider_id"] == "qwen-main"
    assert "api_key" not in saved
    assert "legacy-secret" not in repr(saved)


def test_provider_metadata_save_is_atomic_and_fail_closed(
    isolated, mock_kr, monkeypatch
):
    cd, cf = isolated
    cd.mkdir(parents=True, exist_ok=True)
    original = {"schema_version": 2, "active_provider_id": "old"}
    cf.write_text(json.dumps(original), encoding="utf-8")

    def fail_atomic(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.config._atomic_write_json", fail_atomic)
    with pytest.raises(ConfigSaveError):
        save_config_metadata(AppConfig(active_provider_id="new"))
    assert json.loads(cf.read_text(encoding="utf-8")) == original
    assert mock_kr == {}


def test_explicit_legacy_path_migrates_only_that_path(isolated, mock_kr, tmp_path):
    cd, cf = isolated
    explicit = tmp_path / "explicit" / "settings.json"
    explicit.parent.mkdir()
    explicit.write_text('{"api_key":"fake-explicit-key","model":"explicit-model"}')
    loaded = load_config(explicit)
    assert loaded.model == "explicit-model"
    assert loaded.api_key == "fake-explicit-key"
    assert json.loads(explicit.read_text())["schema_version"] == 2
    assert "api_key" not in json.loads(explicit.read_text())
    assert not cd.exists()
    assert not cf.exists()


def test_explicit_missing_path_creates_only_its_parent(isolated, mock_kr, tmp_path):
    cd, _ = isolated
    explicit = tmp_path / "explicit" / "nested" / "settings.json"
    load_config(explicit)
    assert explicit.parent.is_dir()
    assert not cd.exists()
    assert not (explicit.parent / "templates").exists()
