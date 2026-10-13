"""Tests for independent Vocabulary Undo — LIFO, per-record outcomes, isolated from file undo."""

import pytest
from src.core.vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)
from src.core.vocabulary_undo import (
    VocabularyUndoManager,
    VocabActionType,
    VocabUndoResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    return VocabularyStore()


@pytest.fixture
def undo(store):
    return VocabularyUndoManager(store)


# ── Undo add entry ───────────────────────────────────────────────────────────

class TestUndoAddEntry:
    def test_undo_add_removes_entry(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.test",
            display_name="Test", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        results = undo.undo_last()
        assert len(results) == 1
        assert results[0].success is True
        assert len(store.list_all()) == 0

    def test_undo_add_restores_version(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.v_test",
            display_name="Test", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        v_after = store.vocabulary_version
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        undo.undo_last()
        # Version should have changed from undo
        assert store.vocabulary_version != v_after

    def test_undo_add_already_removed_entry(self, store, undo):
        """If entry was already removed, undo should report failure not crash."""
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.removed",
            display_name="Gone", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        # Remove it manually (simulating external removal)
        store.remove_entry(entry.id)
        results = undo.undo_last()
        # Undo should fail gracefully
        assert results[0].success is False


# ── Undo edit entry ──────────────────────────────────────────────────────────

class TestUndoEditEntry:
    def test_undo_edit_restores_previous_state(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.edited",
            display_name="Original", locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(entry)
        # Edit by overriding
        store.override_entry(entry.id, "Changed")
        undo.record_action(VocabActionType.EDIT, entry_id=entry.id,
                          previous_display_name="Original")
        results = undo.undo_last()
        assert results[0].success is True
        # Entry should be restored to original
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        r = next(e for e in restored if e.id == entry.id)
        assert r.display_name == "Original"

    def test_undo_edit_works_on_user_entry(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.user_edit",
            display_name="Original", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        # For user entries, "edit" means remove + re-add
        store.remove_entry(entry.id)
        new_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.user_edit",
            display_name="Changed", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(new_entry)
        undo.record_action(VocabActionType.EDIT, entry_id=new_entry.id,
                          previous_entry=entry)
        results = undo.undo_last()
        assert results[0].success is True


# ── Undo delete (tombstone) ──────────────────────────────────────────────────

class TestUndoDeleteTombstone:
    def test_undo_tombstone_restores_entry(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.to_restore",
            display_name="Deleted Me", locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(entry)
        store.tombstone_entry(entry.id)
        undo.record_action(VocabActionType.DELETE_TOMBSTONE, entry_id=entry.id)
        results = undo.undo_last()
        assert results[0].success is True
        restored = store.get_entries(VocabularyCategory.TYPE, "en")
        assert entry.id in {e.id for e in restored}


# ── Undo restore ─────────────────────────────────────────────────────────────

class TestUndoRestore:
    def test_undo_restore_reapplies_previous_state(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.was_overridden",
            display_name="Original", locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(entry)
        store.override_entry(entry.id, "Overridden")
        store.restore_entry(entry.id)
        undo.record_action(VocabActionType.RESTORE, entry_id=entry.id,
                          previous_override="Overridden")
        results = undo.undo_last()
        assert results[0].success is True
        # Should re-apply override
        entries = store.get_entries(VocabularyCategory.TYPE, "en")
        r = next(e for e in entries if e.id == entry.id)
        assert r.display_name == "Overridden"


# ── Undo accept suggestion ───────────────────────────────────────────────────

class TestUndoAcceptSuggestion:
    def test_undo_accept_removes_accepted_entry(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.accepted",
            display_name="Accepted Entry", locale="en",
            source=VocabularySource.AI_SUGGESTION,
            confidence=0.9, created_by_model="test",
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.ACCEPT_SUGGESTION, entry_id=entry.id,
                          previous_entry=entry)
        results = undo.undo_last()
        assert results[0].success is True
        assert len(store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)) == 0


# ── Undo auto-create ─────────────────────────────────────────────────────────

class TestUndoAutoCreate:
    def test_undo_auto_create_removes_entry(self, store, undo):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.auto_made",
            display_name="Auto Entry", locale="en",
            source=VocabularySource.AI_AUTO,
            confidence=0.95, created_by_model="test",
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.AUTO_CREATE, entry_id=entry.id,
                          previous_entry=entry)
        results = undo.undo_last()
        assert results[0].success is True
        assert len(store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)) == 0


# ── LIFO ordering ────────────────────────────────────────────────────────────

class TestLIFOOrdering:
    def test_lifo_order_respected(self, store, undo):
        e1 = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.1",
                            display_name="First", locale="en", source=VocabularySource.USER)
        e2 = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.2",
                            display_name="Second", locale="en", source=VocabularySource.USER)
        store.add_entry(e1)
        undo.record_action(VocabActionType.ADD, entry_id=e1.id, previous_entry=e1)
        store.add_entry(e2)
        undo.record_action(VocabActionType.ADD, entry_id=e2.id, previous_entry=e2)

        # Undo last → should remove e2 (most recent)
        results = undo.undo_last()
        assert results[0].entry_id == e2.id
        # e2 gone, e1 still there
        remaining = store.list_all()
        assert e2.id not in {e.id for e in remaining}
        assert e1.id in {e.id for e in remaining}

        # Undo last again → should remove e1
        results2 = undo.undo_last()
        assert results2[0].entry_id == e1.id
        assert len(store.list_all()) == 0


# ── Partial failure ──────────────────────────────────────────────────────────

class TestPartialFailure:
    def test_partial_failure_does_not_mark_all_undone(self, store, undo):
        e1 = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.p1",
                            display_name="P1", locale="en", source=VocabularySource.USER)
        e2 = VocabularyEntry(category=VocabularyCategory.TYPE, concept_id="type.p2",
                            display_name="P2", locale="en", source=VocabularySource.USER)
        store.add_entry(e1)
        undo.record_action(VocabActionType.ADD, entry_id=e1.id, previous_entry=e1)
        store.add_entry(e2)
        undo.record_action(VocabActionType.ADD, entry_id=e2.id, previous_entry=e2)

        # Manually remove e2 to cause partial failure
        store.remove_entry(e2.id)

        results = undo.undo_last()  # tries to undo e2
        assert results[0].success is False
        # undo_last consumes the failed action — next undo_last should get e1
        results2 = undo.undo_last()
        assert results2[0].success is True
        assert results2[0].entry_id == e1.id


# ── Independent from file undo ───────────────────────────────────────────────

class TestIndependentFromFileUndo:
    def test_vocab_undo_independent_of_file_undo(self, store, undo):
        """Vocabulary undo must not touch file RenameHistory or UndoManager."""
        # This is a design verification: the undo manager only interacts with
        # VocabularyStore, never with RenameHistory or file UndoManager
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.vocab_only",
            display_name="Vocab Only", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        # Undo should work purely through VocabularyStore
        results = undo.undo_last()
        assert results[0].success is True
        # Store is the only thing affected
        assert len(store.list_all()) == 0

    def test_vocab_undo_uses_store_properly(self, store, undo):
        """Undo must go through VocabularyStore, not bypass it."""
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.through_store",
            display_name="Store Path", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        v_before = store.vocabulary_version
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        undo.undo_last()
        # Version should have changed twice: add + undo
        # Actually: add bumps version, undo (remove) also bumps version
        # So version should be greater than before (it was bumped twice more)
        assert store.vocabulary_version > v_before


# ── Empty stack / edge cases ─────────────────────────────────────────────────

class TestUndoEdgeCases:
    def test_undo_empty_stack_returns_empty(self, undo):
        results = undo.undo_last()
        assert results == []

    def test_get_undoable_count(self, store, undo):
        assert undo.get_undoable_count() == 0
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.count_test",
            display_name="Count", locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(entry)
        undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                          previous_entry=entry)
        assert undo.get_undoable_count() == 1

    def test_undo_all(self, store, undo):
        for i in range(3):
            entry = VocabularyEntry(
                category=VocabularyCategory.TYPE,
                concept_id=f"type.all_{i}",
                display_name=f"Entry {i}", locale="en",
                source=VocabularySource.USER,
            )
            store.add_entry(entry)
            undo.record_action(VocabActionType.ADD, entry_id=entry.id,
                              previous_entry=entry)
        results = undo.undo_all()
        assert len(results) == 3
        assert all(r.success for r in results)
        assert len(store.list_all()) == 0


# ── VocabUndoResult model ────────────────────────────────────────────────────

class TestVocabUndoResult:
    def test_success_result(self):
        r = VocabUndoResult(action_type=VocabActionType.ADD,
                           entry_id="abc", success=True)
        assert r.success is True
        assert r.entry_id == "abc"

    def test_failure_result_with_reason(self):
        r = VocabUndoResult(action_type=VocabActionType.EDIT,
                           entry_id="xyz", success=False,
                           error="Entry no longer exists")
        assert r.success is False
        assert "Entry" in r.error
