"""Test that config loads correctly when settings.json has no api_key.

Covers: AM-01.1
"""

import json

import pytest

from src.config import load_config, save_config, CredentialSaveError, ConfigSaveError
from src.models.app_config import AppConfig


def test_load_without_key(temp_config_dir, mock_keyring):
    """Config loads with defaults when settings.json has no api_key."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    config = load_config()

    assert config.provider == "openai"
    assert config.model == "gpt-4o"
    assert config.api_key == ""  # No key in JSON, no key in keyring


def test_save_never_writes_api_key(temp_config_dir, mock_keyring):
    """save_config() never writes api_key to JSON."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        provider="deepseek",
        api_key="sk-super-secret-999",
        base_url="https://api.deepseek.com/v1",
    )

    save_config(config)

    # Assert: key saved to keyring
    assert mock_keyring.get("AIRenamer/api_key") == "sk-super-secret-999"

    # Assert: JSON has no api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "api_key" not in saved_data, "api_key must never appear in settings.json"


def test_load_from_keyring_when_json_has_no_key(temp_config_dir, mock_keyring):
    """When JSON has no api_key, load from keyring into runtime config."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # settings.json WITHOUT api_key
    data = {"provider": "claude", "model": "claude-sonnet-4-20250514"}
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Pre-seed the mock keyring
    mock_keyring["AIRenamer/api_key"] = "sk-from-keyring-abc"

    config = load_config()

    # Runtime config has the key from keyring
    assert config.api_key == "sk-from-keyring-abc"
    assert config.provider == "claude"

    # JSON still has no api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "api_key" not in saved_data


def test_roundtrip_save_and_load(temp_config_dir, mock_keyring):
    """Save and then load — api_key survives via keyring, not JSON."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        provider="deepseek",
        api_key="sk-roundtrip-test",
        base_url="https://api.example.com",
        model="test-model",
    )
    save_config(config)

    # Load fresh
    config2 = load_config()
    assert config2.api_key == "sk-roundtrip-test"
    assert config2.provider == "deepseek"
    assert config2.base_url == "https://api.example.com"


# ---------------------------------------------------------------------------
# Fail-closed tests — keyring write failure must NOT write api_key to JSON
# ---------------------------------------------------------------------------

def test_save_config_raises_when_keyring_fails(temp_config_dir, mock_keyring_failing):
    """When set_credential fails, save_config() raises CredentialSaveError."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        provider="deepseek",
        api_key="sk-should-not-be-saved",
        base_url="https://api.deepseek.com/v1",
    )

    with pytest.raises(CredentialSaveError, match="无法将 API Key 保存"):
        save_config(config)


def test_save_config_does_not_write_json_when_keyring_fails(temp_config_dir, mock_keyring_failing):
    """When set_credential fails, the JSON file is NOT written (fail-closed).

    This is the critical safety property: we must never write JSON
    when the credential save failed, because we don't want the caller
    to think "settings saved" when the key was lost.
    """
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # Pre-write a known JSON so we can detect overwrite
    original_data = {"provider": "openai", "model": "gpt-4o"}
    config_file.write_text(json.dumps(original_data, indent=2, ensure_ascii=False), encoding="utf-8")

    config = AppConfig(
        provider="deepseek",
        api_key="sk-secret-key",
        base_url="https://api.deepseek.com/v1",
    )

    try:
        save_config(config)
    except CredentialSaveError:
        pass  # Expected

    # JSON file must still contain the ORIGINAL data — NOT the new config
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data.get("provider") == "openai", (
        "JSON was overwritten despite credential save failure"
    )
    assert "api_key" not in saved_data


def test_save_no_key_succeeds_even_when_keyring_fails(temp_config_dir, mock_keyring_failing):
    """When api_key is empty, save_config() succeeds even if keyring is broken.

    No credential to save → no credential failure.
    """
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        provider="deepseek",
        api_key="",  # No key
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
    )

    # Should NOT raise — no key to save, so keyring failure is irrelevant
    save_config(config)

    # JSON should be written (credential deletion is a no-op when keyring is broken
    # but _delete in mock_keyring_failing still succeeds — it just pops from dict)
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data.get("provider") == "deepseek"
    assert "api_key" not in saved_data


# ---------------------------------------------------------------------------
# Empty-key → credential deletion tests
# ---------------------------------------------------------------------------

def test_clear_key_deletes_existing_credential(temp_config_dir, mock_keyring):
    """When user clears the API key, the existing credential is deleted."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # Pre-seed the keyring with an existing credential
    mock_keyring["AIRenamer/api_key"] = "sk-old-key-to-delete"

    config = AppConfig(
        provider="deepseek",
        api_key="",  # User cleared the key
        base_url="https://api.deepseek.com/v1",
    )

    save_config(config)

    # Assert: credential was deleted from keyring
    assert "AIRenamer/api_key" not in mock_keyring, (
        "Credential should be deleted when user clears API key"
    )

    # Assert: JSON was written without api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "api_key" not in saved_data
    assert saved_data.get("provider") == "deepseek"


def test_delete_credential_failure_fail_closed(temp_config_dir, mock_keyring_delete_failing):
    """When credential deletion fails, save_config() raises CredentialSaveError."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # Pre-write known JSON
    original_data = {"provider": "openai", "model": "gpt-4o"}
    config_file.write_text(json.dumps(original_data, indent=2, ensure_ascii=False), encoding="utf-8")

    config = AppConfig(
        provider="deepseek",
        api_key="",  # Triggers deletion
        base_url="https://api.deepseek.com/v1",
    )

    with pytest.raises(CredentialSaveError, match="无法将 API Key 保存"):
        save_config(config)

    # Assert: JSON file was NOT overwritten
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data.get("provider") == "openai", (
        "JSON was overwritten despite credential deletion failure"
    )


# ---------------------------------------------------------------------------
# JSON write failure test
# ---------------------------------------------------------------------------

def test_json_atomic_write_failure_raises_config_save_error(temp_config_dir, mock_keyring, monkeypatch):
    """When _atomic_write_json fails, save_config() raises ConfigSaveError."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # Force _atomic_write_json to fail
    def _fail_write(*args, **kwargs):
        raise OSError("Simulated disk full")

    monkeypatch.setattr("src.config._atomic_write_json", _fail_write)

    config = AppConfig(
        provider="deepseek",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
    )

    with pytest.raises(ConfigSaveError, match="无法写入配置文件"):
        save_config(config)

    # Cross-storage save is compensating: a failed JSON commit restores the
    # credential snapshot instead of leaving split-brain settings.
    assert mock_keyring.get("AIRenamer/api_key") is None
