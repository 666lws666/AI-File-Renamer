"""Vocabulary CacheContextContributor — stable semantic version tests (Task 2).

Every successful semantic change must change the vocabulary version; pure
reads, no-op saves, failed operations, and unaccepted suggestions must not.
The version is a digest of normalized semantic content — stable across
restarts, never a process-local counter.
"""
import pytest

from src.core.cache_manager import CacheContext
from src.core.vocabulary import (
    VocabularyCacheContextContributor,
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)
from src.core.vocabulary_undo import VocabularyUndoManager, VocabActionType


def make_store():
    store = VocabularyStore()
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.STATUS,
        concept_id="done",
        display_name="Done",
        locale="en-US",
        source=VocabularySource.SYSTEM,
    ))
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.TYPE,
        concept_id="report",
        display_name="Report",
        locale="en-US",
        source=VocabularySource.SYSTEM,
    ))
    return store


def contributor(store):
    return VocabularyCacheContextContributor(store)


# ============================================================================
# Stability across reload / rebuild
# ============================================================================

def test_digest_stable_across_reload():
    store1 = make_store()
    version1 = contributor(store1).vocabulary_version

    # "restart": a fresh store with the same semantic content (new entry ids
    # and timestamps must not matter)
    store2 = make_store()
    version2 = contributor(store2).vocabulary_version

    assert version1 == version2
    assert len(version1) == 64  # sha256 hex


def test_digest_stable_across_state_roundtrip(tmp_path):
    """Reload (same entry objects re-added + persisted overrides/tombstones)
    must reproduce the identical semantic digest."""
    store1 = make_store()
    store1.override_entry(next(e.id for e in store1.list_all() if e.concept_id == "done"), "Finished")
    state_file = tmp_path / "vocab_state.json"
    store1.save_state(state_file)
    version1 = contributor(store1).vocabulary_version

    # reload: load the persisted state, then re-add the same entry objects
    store2 = VocabularyStore()
    store2.load_state(state_file)
    for e in store1.list_all():
        store2.add_entry(e)
    assert contributor(store2).vocabulary_version == version1


def test_digest_not_raw_content_and_hex_only():
    store = make_store()
    digest = contributor(store).vocabulary_version
    assert digest.isalnum() and digest.islower()
    assert "Done" not in digest and "report" not in digest


# ============================================================================
# Successful semantic changes change the version
# ============================================================================

def test_add_entry_changes_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.PROJECT,
        concept_id="q1",
        display_name="Q1",
        locale="en-US",
        source=VocabularySource.USER,
    ))
    assert contributor(store).vocabulary_version != base


def test_edit_via_override_changes_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    done_id = next(e.id for e in store.list_all() if e.concept_id == "done")
    store.override_entry(done_id, "Finished")
    assert contributor(store).vocabulary_version != base


def test_delete_tombstone_changes_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    done_id = next(e.id for e in store.list_all() if e.concept_id == "done")
    store.tombstone_entry(done_id)
    assert contributor(store).vocabulary_version != base


def test_restore_returns_to_previous_version():
    store = make_store()
    original = contributor(store).vocabulary_version
    done_id = next(e.id for e in store.list_all() if e.concept_id == "done")
    store.tombstone_entry(done_id)
    assert contributor(store).vocabulary_version != original
    store.restore_entry(done_id)
    assert contributor(store).vocabulary_version == original


def test_user_override_and_restore_roundtrip():
    store = make_store()
    original = contributor(store).vocabulary_version
    done_id = next(e.id for e in store.list_all() if e.concept_id == "done")
    store.override_entry(done_id, "Finished")
    changed = contributor(store).vocabulary_version
    assert changed != original
    store.restore_entry(done_id)
    assert contributor(store).vocabulary_version == original


def test_accept_ai_suggestion_changes_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.SUBJECT,
        concept_id="invoice",
        display_name="Invoice",
        locale="en-US",
        source=VocabularySource.AI_SUGGESTION,
        confidence=0.95,
    ))
    assert contributor(store).vocabulary_version != base


def test_auto_create_changes_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.ORGANIZATION,
        concept_id="acme",
        display_name="ACME",
        locale="en-US",
        source=VocabularySource.AI_AUTO,
    ))
    assert contributor(store).vocabulary_version != base


def test_vocabulary_undo_restores_previous_version():
    store = make_store()
    undo = VocabularyUndoManager(store)
    original = contributor(store).vocabulary_version

    entry = store.add_entry(VocabularyEntry(
        category=VocabularyCategory.PROJECT,
        concept_id="alpha",
        display_name="Alpha",
        locale="en-US",
        source=VocabularySource.USER,
    ))
    undo.record_action(VocabActionType.ADD, entry.id, previous_entry=entry)
    after_add = contributor(store).vocabulary_version
    assert after_add != original

    undo.undo_last()
    assert contributor(store).vocabulary_version == original, (
        "undo must restore the pre-add semantic version"
    )

    # redo (re-add the same semantic content) → same version as the first add
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.PROJECT,
        concept_id="alpha",
        display_name="Alpha",
        locale="en-US",
        source=VocabularySource.USER,
    ))
    assert contributor(store).vocabulary_version == after_add


# ============================================================================
# No-change operations keep the version
# ============================================================================

def test_reads_do_not_change_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    store.get_entries(VocabularyCategory.STATUS, "en-US")
    store.list_all()
    assert contributor(store).vocabulary_version == base


def test_save_same_content_no_change(tmp_path):
    store = make_store()
    state_file = tmp_path / "vocab_state.json"
    store.save_state(state_file)
    base = contributor(store).vocabulary_version
    store.save_state(state_file)  # saving identical state again
    assert contributor(store).vocabulary_version == base


def test_failed_operations_do_not_change_version():
    store = make_store()
    base = contributor(store).vocabulary_version
    with pytest.raises(Exception):
        store.add_entry(store.list_all()[0])  # duplicate concept_id+locale
    with pytest.raises(KeyError):
        store.remove_entry("missing-id")
    with pytest.raises(Exception):
        store.override_entry("missing-id", "X")
    assert contributor(store).vocabulary_version == base


def test_unaccepted_ai_suggestion_does_not_change_version():
    from src.core.vocabulary_ai import VocabularyAIManager, VocabularyCandidate

    store = make_store()
    base = contributor(store).vocabulary_version
    manager = VocabularyAIManager(store)
    manager.add_suggestion(VocabularyCandidate(
        category=VocabularyCategory.SUBJECT,
        concept_id="draft",
        display_name="Draft",
        locale="en-US",
        confidence=0.9,
    ))
    # candidate area only — the store is untouched
    assert contributor(store).vocabulary_version == base

    # accepting it moves it into the store → version changes
    candidates = manager.list_candidates()
    assert len(candidates) == 1
    accepted = manager.accept(candidates[0].id)
    assert accepted is not None
    assert contributor(store).vocabulary_version != base


def test_reorder_and_equivalent_format_no_change():
    store = make_store()
    version = contributor(store).vocabulary_version

    # rebuild the same semantic content in a different insertion order
    store2 = VocabularyStore()
    entries = sorted(store.list_all(), key=lambda e: e.concept_id, reverse=True)
    for e in entries:
        store2.add_entry(e)
    assert contributor(store2).vocabulary_version == version


# ============================================================================
# CacheContext application
# ============================================================================

def test_apply_to_sets_only_vocabulary_dimensions():
    store = make_store()
    c = contributor(store)
    ctx = CacheContext(
        content_hash="abc123",
        provider_profile_id="qwen",
        provider_id="qwen",
        model="qwen3.6-flash",
        quality_mode="balanced",
        template_id="tpl-1",
    )
    applied = c.apply_to(ctx)
    assert applied.vocabulary_id == "controlled-vocabulary"
    assert applied.vocabulary_version == store.semantic_digest()
    # every other dimension is preserved untouched
    assert applied.content_hash == "abc123"
    assert applied.provider_profile_id == "qwen"
    assert applied.provider_id == "qwen"
    assert applied.model == "qwen3.6-flash"
    assert applied.quality_mode == "balanced"
    assert applied.template_id == "tpl-1"


def test_custom_vocabulary_id():
    store = make_store()
    c = VocabularyCacheContextContributor(store, vocabulary_id="finance-vocab")
    ctx = c.apply_to(CacheContext())
    assert ctx.vocabulary_id == "finance-vocab"
    assert ctx.vocabulary_version == store.semantic_digest()
