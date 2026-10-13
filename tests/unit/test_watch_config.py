"""Task 1 — Watch Config Domain Model tests.

Tests cover:
- Creation & validation
- Path overlap detection (real path semantics)
- JSON serialization without sensitive fields
- Persistence store with schema versioning
- Fail-closed on invalid data
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.core.watch_config import (
    WatchConfig,
    WatchConfigStore,
    WatchConfigValidationError,
    WatchConfigPersistenceError,
    WatchMode,
    WatchStatus,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


# ── Creation & Validation ──────────────────────────────────────────────────────

class TestWatchConfigCreation:
    """Basic creation and field validation."""

    def test_creation_valid_minimal(self, tmp_path):
        src = tmp_path / "watch_src"
        src.mkdir()
        cfg = WatchConfig(
            id="cfg-1",
            source_dir=str(src),
        )
        assert cfg.id == "cfg-1"
        assert cfg.source_dir == str(src)
        assert cfg.mode == WatchMode.REVIEW_FIRST
        assert cfg.status == WatchStatus.ACTIVE
        assert cfg.recursive is True
        assert cfg.version == 1

    def test_creation_valid_full(self, tmp_path):
        src = tmp_path / "src"
        tgt = tmp_path / "tgt"
        src.mkdir(); tgt.mkdir()
        cfg = WatchConfig(
            id="full-1",
            source_dir=str(src),
            target_dir=str(tgt),
            template_id="tpl-1",
            recursive=False,
            mode=WatchMode.AUTO_APPLY,
            status=WatchStatus.PAUSED,
            created_at="2026-07-30T10:00:00",
            updated_at="2026-07-30T11:00:00",
            version=3,
        )
        assert cfg.target_dir == str(tgt)
        assert cfg.template_id == "tpl-1"
        assert cfg.recursive is False
        assert cfg.mode == WatchMode.AUTO_APPLY
        assert cfg.status == WatchStatus.PAUSED

    def test_source_dir_required_empty(self):
        with pytest.raises(WatchConfigValidationError, match="source_dir"):
            WatchConfig(id="x", source_dir="")

    def test_source_dir_required_whitespace(self):
        with pytest.raises(WatchConfigValidationError, match="source_dir"):
            WatchConfig(id="x", source_dir="   ")

    def test_empty_id_rejected(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises(WatchConfigValidationError, match="id"):
            WatchConfig(id="", source_dir=str(src))

    def test_whitespace_id_rejected(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises(WatchConfigValidationError, match="id"):
            WatchConfig(id="   ", source_dir=str(src))

    def test_id_stripped_validation(self, tmp_path):
        """Whitespace-only id must be rejected."""
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises(WatchConfigValidationError):
            WatchConfig(id="\t\n ", source_dir=str(src))


class TestWatchConfigModeEnum:
    """mode enum validation."""

    def test_mode_review_first(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="m1", source_dir=str(src), mode=WatchMode.REVIEW_FIRST)
        assert cfg.mode == WatchMode.REVIEW_FIRST

    def test_mode_auto_apply(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="m2", source_dir=str(src), mode=WatchMode.AUTO_APPLY)
        assert cfg.mode == WatchMode.AUTO_APPLY

    def test_mode_invalid_string_rejected(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises((WatchConfigValidationError, ValueError, TypeError)):
            WatchConfig(id="m3", source_dir=str(src), mode="invalid_mode")

    def test_mode_none_rejected(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises((WatchConfigValidationError, ValueError, TypeError)):
            WatchConfig(id="m4", source_dir=str(src), mode=None)


class TestWatchConfigStatusEnum:
    """status enum validation — must not use BudgetPaused."""

    def test_status_active(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="s1", source_dir=str(src), status=WatchStatus.ACTIVE)
        assert cfg.status == WatchStatus.ACTIVE

    def test_status_paused(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="s2", source_dir=str(src), status=WatchStatus.PAUSED)
        assert cfg.status == WatchStatus.PAUSED

    def test_status_error(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="s3", source_dir=str(src), status=WatchStatus.ERROR)
        assert cfg.status == WatchStatus.ERROR

    def test_status_resource_paused(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="s4", source_dir=str(src), status=WatchStatus.RESOURCE_PAUSED)
        assert cfg.status == WatchStatus.RESOURCE_PAUSED

    def test_status_budget_paused_not_in_enum(self):
        """ResourcePaused is used, NOT BudgetPaused."""
        valid_values = {s.value for s in WatchStatus}
        assert "budget_paused" not in valid_values
        assert "resource_paused" in valid_values

    def test_status_invalid_string_rejected(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        with pytest.raises((WatchConfigValidationError, ValueError, TypeError)):
            WatchConfig(id="s5", source_dir=str(src), status="invalid_status")


# ── Path Overlap Detection ─────────────────────────────────────────────────────

class TestPathOverlapDetection:
    """Prevent source/target re-entry loops using real path semantics."""

    def test_source_equals_target_rejected(self, tmp_path):
        d = tmp_path / "same"
        d.mkdir()
        with pytest.raises(WatchConfigValidationError, match="same"):
            WatchConfig(id="p1", source_dir=str(d), target_dir=str(d))

    def test_target_inside_source_rejected(self, tmp_path):
        src = tmp_path / "watch"
        tgt = src / "output"
        src.mkdir(parents=True)
        tgt.mkdir()
        with pytest.raises(WatchConfigValidationError, match="inside"):
            WatchConfig(id="p2", source_dir=str(src), target_dir=str(tgt))

    def test_source_inside_target_rejected(self, tmp_path):
        tgt = tmp_path / "output"
        src = tgt / "watch"
        tgt.mkdir(parents=True)
        src.mkdir()
        with pytest.raises(WatchConfigValidationError, match="inside"):
            WatchConfig(id="p3", source_dir=str(src), target_dir=str(tgt))

    def test_no_overlap_allowed(self, tmp_path):
        src = tmp_path / "src"
        tgt = tmp_path / "tgt"
        src.mkdir(); tgt.mkdir()
        cfg = WatchConfig(id="p4", source_dir=str(src), target_dir=str(tgt))
        assert cfg.source_dir == str(src)
        assert cfg.target_dir == str(tgt)

    def test_no_target_no_overlap_check(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        cfg = WatchConfig(id="p5", source_dir=str(src), target_dir="")
        assert cfg.target_dir == ""

    def test_overlap_uses_realpath_not_string_prefix(self, tmp_path):
        """String-prefix checking must not be used; real path semantics required."""
        # Create: base/a-extra  and  base/a
        # String prefix "base/a" would match "base/a-extra" but real path won't
        base = tmp_path / "base"
        src = base / "a-extra"
        tgt = base / "a"
        src.mkdir(parents=True)
        tgt.mkdir()
        # These are sibling dirs, should NOT be detected as overlapping
        cfg = WatchConfig(id="p6", source_dir=str(src), target_dir=str(tgt))
        assert cfg.source_dir == str(src)

    def test_overlap_with_symlinks(self, tmp_path):
        """Symlink-based aliasing must be caught via realpath resolution."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "link"
        # Create a symlink on platforms that support it
        try:
            os.symlink(str(real_dir), str(link_dir), target_is_directory=True)
        except OSError:
            pytest.skip("Symlink creation not supported on this platform")
        # source=link, target=real → same real path → must reject
        with pytest.raises(WatchConfigValidationError):
            WatchConfig(id="p7", source_dir=str(link_dir), target_dir=str(real_dir))


# ── Immutability ───────────────────────────────────────────────────────────────

class TestWatchConfigImmutability:
    """WatchConfig is frozen/immutable."""

    def test_cannot_set_attribute(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="i1", source_dir=str(src))
        with pytest.raises(Exception):  # FrozenInstanceError or similar
            cfg.source_dir = "/other"

    def test_with_status_returns_new_instance(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="i2", source_dir=str(src), status=WatchStatus.ACTIVE)
        new_cfg = cfg.with_status(WatchStatus.PAUSED)
        assert cfg.status == WatchStatus.ACTIVE  # original unchanged
        assert new_cfg.status == WatchStatus.PAUSED
        assert new_cfg.id == cfg.id
        assert new_cfg is not cfg

    def test_with_mode_returns_new_instance(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="i3", source_dir=str(src), mode=WatchMode.REVIEW_FIRST)
        new_cfg = cfg.with_mode(WatchMode.AUTO_APPLY)
        assert cfg.mode == WatchMode.REVIEW_FIRST
        assert new_cfg.mode == WatchMode.AUTO_APPLY
        assert new_cfg is not cfg


# ── Serialization ──────────────────────────────────────────────────────────────

class TestWatchConfigSerialization:
    """JSON serialization must never include API Key, Provider creds, file content, or observer."""

    def test_to_dict_no_sensitive_fields(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="ser1", source_dir=str(src))
        d = cfg.to_dict()
        # Must have expected keys
        assert "id" in d
        assert "source_dir" in d
        assert "mode" in d
        assert "status" in d
        assert "version" in d
        # Must NOT have sensitive fields
        forbidden = {"api_key", "key", "provider_credentials", "file_content",
                     "observer", "credential", "password", "secret", "token",
                     "body", "content", "binary"}
        for key in forbidden:
            assert key not in d, f"Sensitive key '{key}' leaked into serialization"

    def test_to_dict_no_runtime_objects(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="ser2", source_dir=str(src))
        d = cfg.to_dict()
        for k, v in d.items():
            assert not callable(v), f"Callable leaked at key '{k}'"
            assert not hasattr(v, 'start'), f"Possible observer leaked at key '{k}'"
            assert type(v).__name__ not in ("Observer", "Thread", "Timer",
                                             "module", "function", "type")

    def test_roundtrip_to_dict_from_dict(self, tmp_path):
        src = tmp_path / "s"; tgt = tmp_path / "t"
        src.mkdir(); tgt.mkdir()
        cfg = WatchConfig(
            id="r1",
            source_dir=str(src),
            target_dir=str(tgt),
            template_id="tpl-x",
            recursive=False,
            mode=WatchMode.AUTO_APPLY,
            status=WatchStatus.PAUSED,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-06-01T00:00:00",
            version=5,
        )
        d = cfg.to_dict()
        cfg2 = WatchConfig.from_dict(d)
        assert cfg2.id == cfg.id
        assert cfg2.source_dir == cfg.source_dir
        assert cfg2.target_dir == cfg.target_dir
        assert cfg2.template_id == cfg.template_id
        assert cfg2.recursive == cfg.recursive
        assert cfg2.mode == cfg.mode
        assert cfg2.status == cfg.status
        assert cfg2.version == cfg.version

    def test_serialization_is_json_serializable(self, tmp_path):
        src = tmp_path / "s"; src.mkdir()
        cfg = WatchConfig(id="ser3", source_dir=str(src))
        d = cfg.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        assert len(json_str) > 0
        # Roundtrip through JSON
        d2 = json.loads(json_str)
        assert d2["id"] == "ser3"


# ── Persistence Store ──────────────────────────────────────────────────────────

class TestWatchConfigStore:
    """WatchConfigStore with schema versioning, fail-closed validation."""

    def test_save_and_load_roundtrip(self, tmp_path):
        store_path = tmp_path / "watch_configs.json"
        src = tmp_path / "src1"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        cfg = WatchConfig(id="cfg-a", source_dir=str(src))
        store.add(cfg)
        assert len(store.list_all()) == 1

        # Load in a new store instance
        store2 = WatchConfigStore(str(store_path))
        loaded = store2.get("cfg-a")
        assert loaded.id == "cfg-a"
        assert loaded.source_dir == str(src)

    def test_schema_version_written(self, tmp_path):
        store_path = tmp_path / "watches.json"
        src = tmp_path / "s"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        store.add(WatchConfig(id="v1", source_dir=str(src)))
        raw = json.loads(store_path.read_text(encoding="utf-8"))
        assert "schema_version" in raw
        assert isinstance(raw["schema_version"], int)

    def test_duplicate_id_rejected(self, tmp_path):
        store_path = tmp_path / "dupes.json"
        src = tmp_path / "s"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        store.add(WatchConfig(id="dup", source_dir=str(src)))
        with pytest.raises(WatchConfigPersistenceError, match="Duplicate"):
            store.add(WatchConfig(id="dup", source_dir=str(src)))

    def test_load_invalid_schema_version_fail_closed(self, tmp_path):
        store_path = tmp_path / "bad_schema.json"
        store_path.write_text(json.dumps({
            "schema_version": 9999,
            "configs": []
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_invalid_enum_fail_closed(self, tmp_path):
        store_path = tmp_path / "bad_enum.json"
        src = str(tmp_path / "s")
        os.makedirs(src, exist_ok=True)
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": [{
                "id": "bad",
                "source_dir": src,
                "mode": "not_a_real_mode",
                "status": "active",
                "template_id": "",
                "target_dir": "",
                "recursive": True,
                "created_at": "",
                "updated_at": "",
                "version": 1,
            }]
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_empty_id_fail_closed(self, tmp_path):
        store_path = tmp_path / "bad_id.json"
        src = str(tmp_path / "s")
        os.makedirs(src, exist_ok=True)
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": [{
                "id": "",
                "source_dir": src,
                "mode": "review_first",
                "status": "active",
                "template_id": "",
                "target_dir": "",
                "recursive": True,
                "created_at": "",
                "updated_at": "",
                "version": 1,
            }]
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_invalid_status_enum_fail_closed(self, tmp_path):
        store_path = tmp_path / "bad_status.json"
        src = str(tmp_path / "s")
        os.makedirs(src, exist_ok=True)
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": [{
                "id": "bs",
                "source_dir": src,
                "mode": "review_first",
                "status": "budget_paused",
                "template_id": "",
                "target_dir": "",
                "recursive": True,
                "created_at": "",
                "updated_at": "",
                "version": 1,
            }]
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_missing_required_field_fail_closed(self, tmp_path):
        store_path = tmp_path / "missing_field.json"
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": [{
                "id": "mf",
                "mode": "review_first",
                "status": "active",
            }]
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_corrupted_json_fail_closed(self, tmp_path):
        store_path = tmp_path / "corrupt.json"
        store_path.write_text("this is not json {{{", encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_not_a_list_fail_closed(self, tmp_path):
        store_path = tmp_path / "not_list.json"
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": "not_a_list"
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_load_extra_unknown_keys_fail_closed(self, tmp_path):
        store_path = tmp_path / "extra_keys.json"
        src = str(tmp_path / "s")
        os.makedirs(src, exist_ok=True)
        store_path.write_text(json.dumps({
            "schema_version": 1,
            "configs": [{
                "id": "ek",
                "source_dir": src,
                "mode": "review_first",
                "status": "active",
                "template_id": "",
                "target_dir": "",
                "recursive": True,
                "created_at": "",
                "updated_at": "",
                "version": 1,
                "secret_key": "should-not-be-here",
                "observer_ref": {},
            }]
        }), encoding="utf-8")
        with pytest.raises(WatchConfigPersistenceError):
            WatchConfigStore(str(store_path))

    def test_remove_config(self, tmp_path):
        store_path = tmp_path / "remove.json"
        src = tmp_path / "s"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        store.add(WatchConfig(id="rem", source_dir=str(src)))
        assert store.get("rem") is not None
        store.remove("rem")
        with pytest.raises(WatchConfigPersistenceError):
            store.get("rem")

    def test_remove_nonexistent_raises(self, tmp_path):
        store_path = tmp_path / "no_remove.json"
        store = WatchConfigStore(str(store_path))
        with pytest.raises(WatchConfigPersistenceError):
            store.remove("nonexistent")

    def test_update_config(self, tmp_path):
        store_path = tmp_path / "update.json"
        src = tmp_path / "s"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        cfg = WatchConfig(id="upd", source_dir=str(src), status=WatchStatus.ACTIVE)
        store.add(cfg)
        updated = cfg.with_status(WatchStatus.PAUSED)
        store.update(updated)
        assert store.get("upd").status == WatchStatus.PAUSED

    def test_update_nonexistent_raises(self, tmp_path):
        store_path = tmp_path / "no_update.json"
        src = tmp_path / "s"; src.mkdir()
        store = WatchConfigStore(str(store_path))
        cfg = WatchConfig(id="nope", source_dir=str(src))
        with pytest.raises(WatchConfigPersistenceError):
            store.update(cfg)

    def test_list_all_empty(self, tmp_path):
        store = WatchConfigStore(str(tmp_path / "empty.json"))
        assert store.list_all() == []

    def test_empty_store_creates_file(self, tmp_path):
        store_path = tmp_path / "will_exist.json"
        WatchConfigStore(str(store_path))
        assert store_path.exists()


# ── Path Escape / Safety ───────────────────────────────────────────────────────

class TestPathEscape:
    """Path traversal and escape attempts must be rejected."""

    def test_relative_path_normalized(self, tmp_path):
        """Relative paths are resolved to absolute."""
        src = tmp_path / "s"
        src.mkdir()
        # Use a relative path; must be normalized internally
        old_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            cfg = WatchConfig(id="rel1", source_dir="s")
            # Should have been resolved to absolute
            assert os.path.isabs(cfg.source_dir)
        finally:
            os.chdir(old_cwd)

    def test_dot_dot_resolved(self, tmp_path):
        """Paths with .. must be resolved."""
        src = tmp_path / "actual"
        src.mkdir()
        trick = tmp_path / "decoy" / ".." / "actual"
        trick.parent.mkdir(parents=True, exist_ok=True)
        cfg = WatchConfig(id="dd1", source_dir=str(trick))
        # After resolution, normalized path should not contain ..
        assert ".." not in Path(cfg.source_dir).parts

    def test_target_path_escape_resolved(self, tmp_path):
        """Target path with .. that escapes must not cause false acceptance."""
        src = tmp_path / "src"
        tgt = tmp_path / "tgt"
        src.mkdir(); tgt.mkdir()
        # target with .. should be resolved before overlap check
        tricky_tgt = src / ".." / "tgt"
        # After resolution, tgt resolves correctly and is outside src
        cfg = WatchConfig(id="esc1", source_dir=str(src), target_dir=str(tricky_tgt))
        assert cfg.target_dir is not None
