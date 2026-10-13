"""Shared test fixtures for Phase 1A tests."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_config_dir(monkeypatch, tmp_path):
    """Redirect CONFIG_DIR and CONFIG_FILE to a temporary directory."""
    config_dir = tmp_path / "config"
    config_file = config_dir / "settings.json"

    monkeypatch.setattr("src.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("src.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.config.TEMPLATES_DIR", config_dir / "templates")

    return config_dir, config_file


@pytest.fixture
def mock_keyring():
    """Mock keyring with an in-memory dict — no real Windows Credential Manager."""
    store = {}

    def _get(service, account):
        return store.get(f"{service}/{account}")

    def _set(service, account, password):
        store[f"{service}/{account}"] = password

    def _delete(service, account):
        store.pop(f"{service}/{account}", None)

    with patch("keyring.get_password", side_effect=_get), \
         patch("keyring.set_password", side_effect=_set), \
         patch("keyring.delete_password", side_effect=_delete):
        yield store


@pytest.fixture
def mock_keyring_failing():
    """Mock keyring where set_password always fails — simulates broken Credential Manager."""
    store = {}

    def _get(service, account):
        return store.get(f"{service}/{account}")

    def _set(service, account, password):
        # Simulate failure: raise an exception
        raise OSError("Simulated Windows Credential Manager failure")

    def _delete(service, account):
        store.pop(f"{service}/{account}", None)

    with patch("keyring.get_password", side_effect=_get), \
         patch("keyring.set_password", side_effect=_set), \
         patch("keyring.delete_password", side_effect=_delete):
        yield store


@pytest.fixture
def mock_keyring_delete_failing():
    """Mock keyring where delete_password always fails but set works."""
    store = {}

    def _get(service, account):
        return store.get(f"{service}/{account}")

    def _set(service, account, password):
        store[f"{service}/{account}"] = password

    def _delete(service, account):
        raise OSError("Simulated Windows Credential Manager delete failure")

    with patch("keyring.get_password", side_effect=_get), \
         patch("keyring.set_password", side_effect=_set), \
         patch("keyring.delete_password", side_effect=_delete):
        yield store
