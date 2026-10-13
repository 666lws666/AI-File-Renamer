import json

from src.core.recovery import RecoveryManager, RecoveryState


def test_corrupt_config_is_quarantined_and_last_snapshot_loaded(tmp_path):
    current = tmp_path / "settings.json"
    snapshot = tmp_path / "settings.last-valid.json"
    current.write_text("{broken", encoding="utf-8")
    snapshot.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
    credentials = object()
    manager = RecoveryManager(credential_store=credentials)

    result = manager.recover_json(current, snapshot_path=snapshot, safe_default={"safe": True}, kind="config")

    assert result.state is RecoveryState.RESTORED
    assert result.data == {"language": "zh_CN"}
    assert result.quarantined_path.exists()
    assert result.quarantined_path.suffix == ".corrupted"
    assert manager.credential_store is credentials


def test_no_valid_snapshot_uses_safe_defaults(tmp_path):
    current = tmp_path / "workspace.json"
    current.write_text("bad", encoding="utf-8")
    result = RecoveryManager().recover_json(current, safe_default={"tasks": []}, kind="workspace")
    assert result.state is RecoveryState.DEFAULTED
    assert result.data == {"tasks": []}


def test_corrupt_cache_is_removed_and_rebuilt_on_next_write(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("bad", encoding="utf-8")
    manager = RecoveryManager()
    result = manager.recover_cache(cache)
    assert result.state is RecoveryState.CLEARED
    assert not cache.exists()
    manager.write_json_atomic(cache, {"entries": {}})
    assert json.loads(cache.read_text(encoding="utf-8")) == {"entries": {}}


def test_corrupt_undo_is_quarantined_and_blocks_apply_without_silent_drop(tmp_path):
    undo = tmp_path / "undo.json"
    undo.write_text("not-json-history", encoding="utf-8")
    manager = RecoveryManager()
    result = manager.recover_undo(undo)
    assert result.state is RecoveryState.BLOCKED
    assert manager.apply_allowed is False
    assert result.quarantined_path.read_text(encoding="utf-8") == "not-json-history"
    assert result.user_message_id == "recovery.undo.blocked"