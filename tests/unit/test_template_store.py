"""Tests for TemplateStore — CRUD, persistence, atomic writes, fail-closed validation."""

import json
import tempfile
from pathlib import Path
import pytest
from src.core.template_model import (
    Template, TemplateField, DateFormat, Separator, OrgMode, OutputLanguage,
)
from src.core.template_store import (
    TemplateStore,
    TemplateNotFoundError,
    TemplateIntegrityError,
    TemplateReferenceError,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store_path(tmp_path):
    return tmp_path / "templates.json"


@pytest.fixture
def store(temp_store_path):
    return TemplateStore(temp_store_path)


@pytest.fixture
def sample_template():
    return Template(
        name="Test Template",
        pattern="{dcDate}_{dcTitle}",
        date_format=DateFormat.YYYY_MM_DD,
        separator=Separator.UNDERSCORE,
        org_mode=OrgMode.FLAT,
        output_language=OutputLanguage.ZH,
        fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ],
    )


# ── Create ───────────────────────────────────────────────────────────────────

class TestCreateTemplate:
    def test_create_template_persists(self, store, sample_template):
        store.create(sample_template)
        loaded = store.get(sample_template.id)
        assert loaded.id == sample_template.id
        assert loaded.name == sample_template.name

    def test_create_multiple_templates(self, store):
        t1 = Template(name="T1", pattern="{dcDate}_{dcTitle}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ])
        t2 = Template(name="T2", pattern="{dcDate}_{dcTitle}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ])
        store.create(t1)
        store.create(t2)
        assert len(store.list_all()) == 2

    def test_create_duplicate_id_fails(self, store, sample_template):
        store.create(sample_template)
        with pytest.raises(TemplateIntegrityError, match="Duplicate"):
            store.create(sample_template)  # same ID


# ── Read ─────────────────────────────────────────────────────────────────────

class TestReadTemplate:
    def test_get_existing_template(self, store, sample_template):
        store.create(sample_template)
        t = store.get(sample_template.id)
        assert t.name == sample_template.name

    def test_get_nonexistent_template_raises(self, store):
        with pytest.raises(TemplateNotFoundError):
            store.get("nonexistent-id")

    def test_list_all_returns_all(self, store):
        t1 = Template(name="T1", pattern="{dcDate}_{dcTitle}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ])
        t2 = Template(name="T2", pattern="{dcDate}_{dcTitle}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ])
        store.create(t1)
        store.create(t2)
        all_t = store.list_all()
        assert len(all_t) == 2
        ids = {t.id for t in all_t}
        assert t1.id in ids
        assert t2.id in ids

    def test_list_all_empty(self, store):
        assert store.list_all() == []


# ── Update ───────────────────────────────────────────────────────────────────

class TestUpdateTemplate:
    def test_update_increments_version(self, store, sample_template):
        store.create(sample_template)
        original = store.get(sample_template.id)
        assert original.version == 1
        updated = store.update(sample_template.id, name="Updated Name")
        assert updated.version == 2
        assert updated.name == "Updated Name"
        # Original reference should still have version 1
        assert original.version == 1

    def test_update_nonexistent_raises(self, store):
        with pytest.raises(TemplateNotFoundError):
            store.update("nonexistent", name="X")

    def test_update_preserves_other_fields(self, store, sample_template):
        store.create(sample_template)
        updated = store.update(sample_template.id, name="New Name")
        assert updated.pattern == sample_template.pattern
        assert updated.date_format == sample_template.date_format

    def test_update_persists(self, store, sample_template):
        store.create(sample_template)
        store.update(sample_template.id, name="Persisted Name")
        # Reload from disk
        store2 = TemplateStore(store._file_path)
        loaded = store2.get(sample_template.id)
        assert loaded.name == "Persisted Name"
        assert loaded.version == 2


# ── Delete ───────────────────────────────────────────────────────────────────

class TestDeleteTemplate:
    def test_delete_unreferenced_template(self, store, sample_template):
        store.create(sample_template)
        store.delete(sample_template.id, is_referenced=False)
        with pytest.raises(TemplateNotFoundError):
            store.get(sample_template.id)

    def test_delete_referenced_without_replacement_fails(self, store, sample_template):
        store.create(sample_template)
        with pytest.raises(TemplateReferenceError, match="replacement"):
            store.delete(sample_template.id, is_referenced=True)

    def test_delete_referenced_with_valid_replacement(self, store, sample_template):
        store.create(sample_template)
        t2 = Template(name="Replacement", pattern="{dcDate}_{dcTitle}", fields=[
            TemplateField(dc_name="dcDate", display_name="Date", order=1),
            TemplateField(dc_name="dcTitle", display_name="Title", order=2),
        ])
        store.create(t2)
        store.delete(sample_template.id, is_referenced=True, replacement_template_id=t2.id)
        with pytest.raises(TemplateNotFoundError):
            store.get(sample_template.id)
        # Replacement should still exist
        assert store.get(t2.id).name == "Replacement"

    def test_delete_referenced_with_nonexistent_replacement_fails(self, store, sample_template):
        store.create(sample_template)
        with pytest.raises(TemplateNotFoundError, match="Replacement"):
            store.delete(sample_template.id, is_referenced=True, replacement_template_id="no-such-id")

    def test_delete_referenced_with_self_replacement_fails(self, store, sample_template):
        store.create(sample_template)
        with pytest.raises(TemplateReferenceError, match="same"):
            store.delete(sample_template.id, is_referenced=True, replacement_template_id=sample_template.id)

    def test_delete_nonexistent_raises(self, store):
        with pytest.raises(TemplateNotFoundError):
            store.delete("nonexistent", is_referenced=False)

    def test_delete_persists(self, store, sample_template):
        store.create(sample_template)
        store.delete(sample_template.id, is_referenced=False)
        store2 = TemplateStore(store._file_path)
        with pytest.raises(TemplateNotFoundError):
            store2.get(sample_template.id)


# ── Startup loading ──────────────────────────────────────────────────────────

class TestStartupLoading:
    def test_load_templates_on_startup(self, temp_store_path, sample_template):
        store1 = TemplateStore(temp_store_path)
        store1.create(sample_template)
        # Simulate restart
        store2 = TemplateStore(temp_store_path)
        loaded = store2.list_all()
        assert len(loaded) == 1
        assert loaded[0].id == sample_template.id

    def test_load_empty_file(self, temp_store_path):
        temp_store_path.write_text("[]", encoding="utf-8")
        store = TemplateStore(temp_store_path)
        assert store.list_all() == []

    def test_load_missing_file_creates_empty(self, temp_store_path):
        store = TemplateStore(temp_store_path)
        assert store.list_all() == []
        assert temp_store_path.exists()


# ── Atomic writes & corruption ───────────────────────────────────────────────

class TestAtomicWrites:
    def test_corrupted_json_fails_closed(self, temp_store_path):
        temp_store_path.write_text("this is not valid json", encoding="utf-8")
        with pytest.raises(TemplateIntegrityError, match="Corrupted"):
            TemplateStore(temp_store_path)

    def test_unknown_schema_fails_closed(self, temp_store_path):
        temp_store_path.write_text(
            json.dumps([{"__unknown_key__": "bad data", "id": "x"}]),
            encoding="utf-8",
        )
        with pytest.raises(TemplateIntegrityError):
            TemplateStore(temp_store_path)

    def test_duplicate_id_in_file_fails_closed(self, temp_store_path):
        # Manually write two templates with same ID
        data = [
            {
                "id": "same-id",
                "name": "T1",
                "pattern": "{dcDate}_{dcTitle}",
                "date_format": "YYYY-MM-DD",
                "separator": "_",
                "org_mode": "flat",
                "output_language": "zh",
                "fields": [
                    {"id": "f1", "dc_name": "dcDate", "display_name": "Date", "order": 1, "enabled": True},
                    {"id": "f2", "dc_name": "dcTitle", "display_name": "Title", "order": 2, "enabled": True},
                ],
                "version": 1,
            },
            {
                "id": "same-id",
                "name": "T2",
                "pattern": "{dcDate}_{dcTitle}",
                "date_format": "YYYY-MM-DD",
                "separator": "_",
                "org_mode": "flat",
                "output_language": "zh",
                "fields": [
                    {"id": "f3", "dc_name": "dcDate", "display_name": "Date", "order": 1, "enabled": True},
                    {"id": "f4", "dc_name": "dcTitle", "display_name": "Title", "order": 2, "enabled": True},
                ],
                "version": 1,
            },
        ]
        temp_store_path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TemplateIntegrityError, match="Duplicate"):
            TemplateStore(temp_store_path)

    def test_write_is_atomic(self, temp_store_path, sample_template):
        store = TemplateStore(temp_store_path)
        store.create(sample_template)
        # Verify no .tmp files left behind
        tmp_files = list(temp_store_path.parent.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_create_write_failure_keeps_memory_and_disk_unchanged(
        self, temp_store_path, sample_template, monkeypatch
    ):
        store = TemplateStore(temp_store_path)
        disk_before = temp_store_path.read_bytes()
        monkeypatch.setattr(
            "src.core.template_store.os.replace",
            lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError, match="disk full"):
            store.create(sample_template)

        assert store.list_all() == []
        assert temp_store_path.read_bytes() == disk_before

    def test_update_write_failure_keeps_memory_and_disk_unchanged(
        self, temp_store_path, sample_template, monkeypatch
    ):
        store = TemplateStore(temp_store_path)
        store.create(sample_template)
        disk_before = temp_store_path.read_bytes()
        memory_before = store.get(sample_template.id)
        monkeypatch.setattr(
            "src.core.template_store.os.replace",
            lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError, match="disk full"):
            store.update(sample_template.id, name="must not leak")

        assert store.get(sample_template.id) == memory_before
        assert temp_store_path.read_bytes() == disk_before

    def test_delete_write_failure_keeps_memory_and_disk_unchanged(
        self, temp_store_path, sample_template, monkeypatch
    ):
        store = TemplateStore(temp_store_path)
        store.create(sample_template)
        disk_before = temp_store_path.read_bytes()
        monkeypatch.setattr(
            "src.core.template_store.os.replace",
            lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError, match="disk full"):
            store.delete(sample_template.id)

        assert store.get(sample_template.id) == sample_template
        assert temp_store_path.read_bytes() == disk_before

    def test_illegal_object_rejected(self, temp_store_path):
        data = [{"id": "x", "name": "NoFields", "pattern": "{dcDate}_{dcTitle}"}]
        temp_store_path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TemplateIntegrityError):
            TemplateStore(temp_store_path)


# ── No provider/file/path/credential leakage ─────────────────────────────────

class TestNoSensitiveDataLeakage:
    def test_store_does_not_accept_file_content(self, store, sample_template):
        """The store's serialization must not include unknown fields."""
        store.create(sample_template)
        data = json.loads(store._file_path.read_text(encoding="utf-8"))
        for entry in data:
            assert "api_key" not in entry
            assert "file_content" not in entry
            assert "provider" not in entry
            assert "credential" not in entry
            assert "file_path" not in entry
