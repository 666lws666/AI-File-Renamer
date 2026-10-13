"""Test that legacy api_key in settings.json is migrated to credential manager.

Covers: AM-01.1, AM-01.2
"""

import json

from src.config import load_config


def test_migration_removes_key_from_json(temp_config_dir, mock_keyring):
    """When settings.json contains api_key, load_config() moves it to
    keyring and atomically rewrites the JSON file without the key."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    # Write old-style settings.json WITH api_key
    old_data = {
        "provider": "deepseek",
        "api_key": "sk-test-legacy-key-12345",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(old_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Load config — triggers migration
    config = load_config()

    # Assert: api_key is loaded into runtime config
    assert config.api_key == "sk-test-legacy-key-12345"

    # Assert: JSON file no longer contains api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "api_key" not in saved_data, "api_key should be removed from settings.json"

    # Assert: key is in the mock keyring
    assert "AIRenamer/api_key" in mock_keyring
    assert mock_keyring["AIRenamer/api_key"] == "sk-test-legacy-key-12345"


def test_migration_empty_key_is_removed(temp_config_dir, mock_keyring):
    """Empty api_key in settings.json is just removed, not migrated."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    old_data = {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(old_data, indent=2, ensure_ascii=False), encoding="utf-8")

    config = load_config()

    # Assert: keyring is NOT populated for empty key
    assert "AIRenamer/api_key" not in mock_keyring

    # Assert: JSON has no api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "api_key" not in saved_data

    # Runtime config should have empty api_key
    assert config.api_key == ""


# ---------------------------------------------------------------------------
# Migration failure: key preserved in JSON (no data loss)
# ---------------------------------------------------------------------------

def test_migration_failure_preserves_key_in_json(temp_config_dir, mock_keyring_failing):
    """When credential-manager write fails during migration, the original
    api_key is preserved in settings.json — never silently lost."""
    config_dir, config_file = temp_config_dir
    config_dir.mkdir(parents=True, exist_ok=True)

    legacy_key = "sk-legacy-key-migration-fail-test"

    old_data = {
        "provider": "deepseek",
        "api_key": legacy_key,
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
    }
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(old_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # When credential manager fails, load_config logs a warning but
    # does NOT delete the key from JSON (data preservation)
    config = load_config()

    # JSON file MUST still contain the original api_key
    with open(config_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data.get("api_key") == legacy_key, (
        "api_key was lost from JSON during failed migration — DATA LOSS BUG"
    )

    # Runtime config should have loaded the key from JSON (AppConfig consumes it)
    # Note: AppConfig(api_key=...) sets api_key even though it's excluded from dump
    assert config.api_key == legacy_key
