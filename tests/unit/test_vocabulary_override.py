"""Tests for user vocabulary override, tombstone, and restore."""

import json
import tempfile
from pathlib import Path
import pytest
from src.core.vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
    VocabularyIntegrityError,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store_with_presets():
    """A store pre-populated with system preset entries."""
    store = VocabularyStore()
    entries = [
        VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.invoice",
                        display_name="Invoice", locale="en", source=VocabularySource.SYSTEM),
        VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.receipt",
                        display_name="Receipt", locale="en", source=VocabularySource.SYSTEM),
        VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.report",
                        display_name="Report", locale="en", source=VocabularySource.SYSTEM),
        VocabularyEntry(category=VocabularyCategory.SUBJECT, concept_id="subject.finance",
                        display_name="Finance", locale="en", source=VocabularySource.SYSTEM),
        VocabularyEntry(category=VocabularyCategory.SUBJECT, concept_id="subject.health",
                        display_name="Health", locale="en", source=VocabularySource.SYSTEM),
    ]
    for e in entries:
        store.add_entry(e)
    return store


# ── Edit preset → user override ──────────────────────────────────────────────

class TestEditPresetEntry:
    def test_edit_preset_creates_override(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry = entries[0]
        original_version = store.vocabulary_version

        store.override_entry(entry.id, "Custom Invoice Name")
        # Entry should now show overridden display name
        updated = store.get_entries(VocabularyCategory.TYPE, "en")
        updated_entry = next(e for e in updated if e.id == entry.id)
        assert updated_entry.display_name == "Custom Invoice Name"

    def test_override_changes_vocabulary_version(self, store_with_presets):
        store = store_with_presets
        v1 = store.vocabulary_version
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        store.override_entry(entries[0].id, "Changed")
        v2 = store.vocabulary_version
        assert v2 > v1

    def test_override_does_not_change_original_entry(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry = entries[0]
        original_name = entry.display_name
        store.override_entry(entry.id, "Changed")
        # The original entry object should still have the original name
        assert entry.display_name == original_name

    def test_override_visible_in_list_all(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry = entries[0]
        store.override_entry(entry.id, "Overridden")
        all_entries = store.list_all()
        updated = next(e for e in all_entries if e.id == entry.id)
        assert updated.display_name == "Overridden"

    def test_override_nonexistent_entry_raises(self, store_with_presets):
        with pytest.raises(KeyError):
            store_with_presets.override_entry("nonexistent", "Name")

    def test_override_user_entry_raises(self):
        """Cannot override a user-created entry — only system presets."""
        store = VocabularyStore()
        user_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE, concept_id="type.custom",
            display_name="Custom", locale="en", source=VocabularySource.USER,
        )
        store.add_entry(user_entry)
        with pytest.raises(VocabularyIntegrityError, match="system"):
            store.override_entry(user_entry.id, "Changed")


# ── Delete preset → tombstone ────────────────────────────────────────────────

class TestDeletePresetTombstone:
    def test_delete_preset_creates_tombstone(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        count_before = len(entries)
        store.tombstone_entry(entries[0].id)
        count_after = len(store.get_entries(VocabularyCategory.TYPE, "en"))
        assert count_after == count_before - 1

    def test_tombstone_hides_entry_from_queries(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry_id = entries[0].id
        store.tombstone_entry(entry_id)
        remaining = store.get_entries(VocabularyCategory.TYPE, "en")
        assert entry_id not in {e.id for e in remaining}

    def test_tombstone_does_not_physically_delete(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry_id = entries[0].id
        store.tombstone_entry(entry_id)
        # Entry should still be recoverable via restore
        store.restore_entry(entry_id)
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        assert entry_id in {e.id for e in restored}

    def test_tombstone_changes_vocabulary_version(self, store_with_presets):
        store = store_with_presets
        v1 = store.vocabulary_version
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        store.tombstone_entry(entries[0].id)
        assert store.vocabulary_version > v1

    def test_tombstone_nonexistent_raises(self, store_with_presets):
        with pytest.raises(KeyError):
            store_with_presets.tombstone_entry("nonexistent")

    def test_tombstone_user_entry_raises(self):
        """Cannot tombstone a user-created entry via this path."""
        store = VocabularyStore()
        user_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE, concept_id="type.custom",
            display_name="Custom", locale="en", source=VocabularySource.USER,
        )
        store.add_entry(user_entry)
        with pytest.raises(VocabularyIntegrityError, match="system"):
            store.tombstone_entry(user_entry.id)

    def test_user_entry_deleted_normally(self):
        """User entries can be removed with remove_entry directly."""
        store = VocabularyStore()
        user_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE, concept_id="type.custom",
            display_name="Custom", locale="en", source=VocabularySource.USER,
        )
        store.add_entry(user_entry)
        store.remove_entry(user_entry.id)
        assert len(store.list_all()) == 0


# ── Restore single entry ─────────────────────────────────────────────────────

class TestRestoreSingleEntry:
    def test_restore_override(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry = entries[0]
        store.override_entry(entry.id, "Overridden")
        store.restore_entry(entry.id)
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        r = next(e for e in restored if e.id == entry.id)
        assert r.display_name == entry.display_name  # back to original

    def test_restore_tombstone(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        entry = entries[0]
        store.tombstone_entry(entry.id)
        store.restore_entry(entry.id)
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        assert entry.id in {e.id for e in restored}

    def test_restore_changes_version(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        store.tombstone_entry(entries[0].id)
        v1 = store.vocabulary_version
        store.restore_entry(entries[0].id)
        assert store.vocabulary_version > v1

    def test_restore_nonexistent_raises(self, store_with_presets):
        with pytest.raises(KeyError):
            store_with_presets.restore_entry("nonexistent")


# ── Restore entire category ──────────────────────────────────────────────────

class TestRestoreEntireCategory:
    def test_restore_category_clears_all_overrides(self, store_with_presets):
        store = store_with_presets
        type_entries = store.get_entries(VocabularyCategory.TYPE, "en")
        store.override_entry(type_entries[0].id, "A")
        store.override_entry(type_entries[1].id, "B")
        store.tombstone_entry(type_entries[2].id)
        store.restore_category(VocabularyCategory.TYPE)
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        assert len(restored) == 3
        # All display names should be original
        for e in restored:
            assert e.source == VocabularySource.SYSTEM

    def test_restore_category_does_not_affect_other_categories(self, store_with_presets):
        store = store_with_presets
        type_entries = store.get_entries(VocabularyCategory.TYPE, "en")
        subject_entries = store.get_entries(VocabularyCategory.SUBJECT, "en")
        store.tombstone_entry(type_entries[0].id)
        store.tombstone_entry(subject_entries[0].id)
        # Restore only TYPE
        store.restore_category(VocabularyCategory.TYPE)
        # TYPE should be restored
        assert len(store.get_entries(VocabularyCategory.TYPE, "en")) == 3
        # SUBJECT should still be missing one
        assert len(store.get_entries(VocabularyCategory.SUBJECT, "en")) == 1

    def test_restore_category_changes_version(self, store_with_presets):
        store = store_with_presets
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        store.tombstone_entry(entries[0].id)
        v1 = store.vocabulary_version
        store.restore_category(VocabularyCategory.TYPE)
        assert store.vocabulary_version > v1


# ── Persistence across restart ───────────────────────────────────────────────

class TestOverridePersistence:
    def test_override_persists_across_store_reload(self, tmp_path):
        save_path = tmp_path / "vocab_state.json"
        # Create store, add presets, override one, tombstone another
        store1 = VocabularyStore()
        e = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.invoice",
                           display_name="Invoice", locale="en", source=VocabularySource.SYSTEM)
        store1.add_entry(e)
        store1.override_entry(e.id, "Persisted Name")
        # Tombstone a different entry
        e2 = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.receipt",
                            display_name="Receipt", locale="en", source=VocabularySource.SYSTEM)
        store1.add_entry(e2)
        store1.tombstone_entry(e2.id)
        store1.save_state(save_path)

        # Reload
        store2 = VocabularyStore()
        store2.load_state(save_path)
        store2.add_entry(e)
        store2.add_entry(e2)

        # Verify override persisted
        all_e = store2.list_all()
        invoice = next(x for x in all_e if x.id == e.id)
        assert invoice.display_name == "Persisted Name"

        # Verify tombstone persisted
        type_entries = store2.get_entries(VocabularyCategory.TYPE, "en")
        assert e2.id not in {x.id for x in type_entries}

    def test_restore_persists_across_reload(self, tmp_path):
        save_path = tmp_path / "vocab_state.json"
        store1 = VocabularyStore()
        e = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.invoice",
                           display_name="Invoice", locale="en", source=VocabularySource.SYSTEM)
        store1.add_entry(e)
        store1.override_entry(e.id, "Overridden")
        store1.save_state(save_path)

        store2 = VocabularyStore()
        store2.load_state(save_path)
        store2.add_entry(e)
        store2.restore_entry(e.id)
        store2.save_state(save_path)

        store3 = VocabularyStore()
        store3.load_state(save_path)
        store3.add_entry(e)
        restored = store3.list_all()
        r = next(x for x in restored if x.id == e.id)
        assert r.display_name == "Invoice"


    def test_user_and_accepted_ai_entries_persist_across_restart(self, tmp_path):
        save_path = tmp_path / "vocab_state.json"
        store1 = VocabularyStore()
        user = VocabularyEntry(
            category=VocabularyCategory.PROJECT,
            concept_id="project.launch",
            display_name="Launch",
            locale="en",
            source=VocabularySource.USER,
        )
        accepted = VocabularyEntry(
            category=VocabularyCategory.SUBJECT,
            concept_id="subject.archive",
            display_name="Archive",
            locale="en",
            source=VocabularySource.AI_SUGGESTION,
            confidence=0.91,
            created_by_model="fixture-model",
        )
        store1.add_entry(user)
        store1.add_entry(accepted)
        store1.save_state(save_path)

        store2 = VocabularyStore()
        store2.load_state(save_path)
        restored = {entry.id: entry for entry in store2.list_all()}

        assert restored[user.id] == user
        assert restored[accepted.id] == accepted

    def test_corrupt_entry_load_keeps_existing_memory_unchanged(self, tmp_path):
        save_path = tmp_path / "vocab_state.json"
        save_path.write_text(
            json.dumps({
                "vocabulary_version": 99,
                "entries": [{"category": "illegal"}],
                "overrides": {"bad": "value"},
                "tombstones": ["bad"],
            }),
            encoding="utf-8",
        )
        store = VocabularyStore()
        existing = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.keep",
            display_name="Keep",
            locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(existing)
        before = store.snapshot()

        with pytest.raises((ValueError, VocabularyIntegrityError, KeyError, TypeError)):
            store.load_state(save_path)

        assert store.snapshot() == before


# ── Version tracking ─────────────────────────────────────────────────────────

class TestVocabularyVersion:
    def test_initial_version_is_zero(self):
        store = VocabularyStore()
        assert store.vocabulary_version == 0

    def test_version_changes_on_add_entry(self):
        store = VocabularyStore()
        v1 = store.vocabulary_version
        e = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.test",
                           display_name="Test", locale="en", source=VocabularySource.USER)
        store.add_entry(e)
        assert store.vocabulary_version > v1

    def test_version_changes_on_remove_entry(self):
        store = VocabularyStore()
        e = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.test",
                           display_name="Test", locale="en", source=VocabularySource.USER)
        store.add_entry(e)
        v1 = store.vocabulary_version
        store.remove_entry(e.id)
        assert store.vocabulary_version > v1
