"""Read-only startup uses isolated files and never invokes credentials."""
import json

import pytest

from src import config


@pytest.fixture
def no_side_effects(monkeypatch, tmp_path):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("metadata startup side effect")
    for name in ("get_credential", "get_credential_strict", "set_credential",
                 "delete_credential", "_ensure_dirs", "_atomic_write_json"):
        monkeypatch.setattr(config, name, forbidden)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "wrong" / "settings.json")
    return calls


@pytest.mark.parametrize("version", [0, 1, 2])
def test_metadata_leaves_legacy_key_schema_and_bytes_untouched(tmp_path, no_side_effects, version):
    path = tmp_path / "settings.json"
    original = json.dumps({"schema_version": version, "api_key": "fake-private-key",
                           "model": "selected-model"}, indent=4).encode()
    path.write_bytes(original)
    loaded = config.load_config(path, load_credentials=False)
    assert loaded.api_key == ""
    assert loaded.schema_version == version
    assert loaded.model == "selected-model"
    assert path.read_bytes() == original
    assert no_side_effects == []


def test_metadata_missing_directory_is_not_created(tmp_path, no_side_effects):
    path = tmp_path / "missing" / "settings.json"
    assert config.load_config(path, load_credentials=False).api_key == ""
    assert not path.parent.exists()
    assert no_side_effects == []


def test_metadata_future_schema_typed_rejection_has_no_side_effects(tmp_path, no_side_effects):
    path = tmp_path / "future.json"
    original = b'{"schema_version":99,"api_key":"fake-private-key"}'
    path.write_bytes(original)
    with pytest.raises(config.UnsupportedConfigVersionError):
        config.load_config(path, load_credentials=False)
    assert path.read_bytes() == original
    assert no_side_effects == []


@pytest.mark.parametrize("payload", [b'{"api_key":"fake-private-key",',
    b'{"schema_version":2,"api_key":"fake-private-key","max_file_size_mb":"invalid"}',
    b'[]'])
def test_metadata_malformed_recovery_never_logs_or_returns_key(
        tmp_path, no_side_effects, payload):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    logs = []
    sink = config.logger.add(lambda message: logs.append(str(message)))
    try:
        assert config.load_config(path, load_credentials=False).api_key == ""
    finally:
        config.logger.remove(sink)
    assert path.read_bytes() == payload
    assert "fake-private-key" not in "".join(logs)
    assert no_side_effects == []


def test_metadata_no_argument_path_uses_global_without_creating_dirs(tmp_path, no_side_effects, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version":2,"model":"global-model","api_key":"fake-key"}')
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    assert config.load_config(load_credentials=False).model == "global-model"
    assert no_side_effects == []
