"""Tests for AI vocabulary suggestion — candidate flow, accept, modify, map, use once, ignore."""

import pytest
from src.core.vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)
from src.core.vocabulary_ai import (
    VocabularyCandidate,
    VocabularyAIManager,
    SuggestionStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    return VocabularyStore()


@pytest.fixture
def manager(store):
    return VocabularyAIManager(store)


def make_candidate(**kwargs):
    defaults = dict(
        category=VocabularyCategory.TYPE,
        concept_id="type.ai_invoice",
        display_name="AI Invoice",
        locale="en",
        confidence=0.85,
        source_model="test-model-v1",
        task_id="task-001",
    )
    defaults.update(kwargs)
    return VocabularyCandidate(**defaults)


# ── AI suggestion → candidate only (not formal) ──────────────────────────────

class TestAISuggestionCandidateOnly:
    def test_ai_suggestion_goes_to_candidate_not_formal(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        # Candidate should be in candidate list
        candidates = manager.list_candidates()
        assert len(candidates) == 1
        # Formal vocabulary should NOT contain it
        formal = store.get_entries(VocabularyCategory.TYPE, "en")
        assert len(formal) == 0
        # Even with include_ai_suggestions=True, candidates are NOT in the store
        formal_all = store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)
        assert len(formal_all) == 0

    def test_multiple_suggestions_all_candidates(self, manager, store):
        manager.add_suggestion(make_candidate(concept_id="type.ai_1", display_name="AI 1"))
        manager.add_suggestion(make_candidate(concept_id="type.ai_2", display_name="AI 2"))
        assert len(manager.list_candidates()) == 2
        assert len(store.list_all()) == 0


# ── Accept suggestion ────────────────────────────────────────────────────────

class TestAcceptSuggestion:
    def test_accept_suggestion_adds_to_formal(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        manager.accept(c.id)
        formal = store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)
        assert len(formal) == 1
        assert formal[0].concept_id == "type.ai_invoice"
        assert formal[0].display_name == "AI Invoice"
        assert formal[0].source == VocabularySource.AI_SUGGESTION

    def test_accept_changes_vocabulary_version(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        manager.accept(c.id)
        assert store.vocabulary_version > v_before

    def test_accept_removes_from_candidates(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.accept(c.id)
        assert len(manager.list_candidates()) == 0

    def test_accept_nonexistent_raises(self, manager):
        with pytest.raises(KeyError):
            manager.accept("nonexistent")

    def test_accept_already_processed_raises(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.accept(c.id)
        with pytest.raises(ValueError, match="already"):
            manager.accept(c.id)


# ── Modify then accept ───────────────────────────────────────────────────────

class TestModifyThenAccept:
    def test_modify_then_accept_changes_display_name(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.modify_and_accept(c.id, "Modified Invoice Name")
        formal = store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)
        assert formal[0].display_name == "Modified Invoice Name"
        assert formal[0].concept_id == "type.ai_invoice"

    def test_modify_then_accept_changes_version(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        manager.modify_and_accept(c.id, "Changed")
        assert store.vocabulary_version > v_before

    def test_modify_then_accept_removes_from_candidates(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.modify_and_accept(c.id, "Changed")
        assert len(manager.list_candidates()) == 0

    def test_modify_empty_name_raises(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        with pytest.raises(ValueError, match="display_name"):
            manager.modify_and_accept(c.id, "")


# ── Map to existing ──────────────────────────────────────────────────────────

class TestMapToExisting:
    def test_map_to_existing_records_mapping(self, manager, store):
        existing = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(existing)
        c = make_candidate(concept_id="type.ai_invoice")
        manager.add_suggestion(c)
        manager.map_to_existing(c.id, existing.id)
        # Candidate should be removed
        assert len(manager.list_candidates()) == 0
        # Existing entry should be unchanged
        assert store.get_entries(VocabularyCategory.TYPE, "en")[0].display_name == "Invoice"

    def test_map_to_nonexistent_entry_raises(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        with pytest.raises(KeyError):
            manager.map_to_existing(c.id, "nonexistent")

    def test_map_does_not_change_version(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        existing = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice", locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(existing)
        v_after_add = store.vocabulary_version
        manager.map_to_existing(c.id, existing.id)
        # Version should not change from mapping alone (beyond the add_entry above)
        assert store.vocabulary_version == v_after_add


# ── Use once ─────────────────────────────────────────────────────────────────

class TestUseOnce:
    def test_use_once_returns_entry_without_adding_to_store(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        entry = manager.use_once(c.id)
        assert entry is not None
        assert entry.display_name == "AI Invoice"
        # Store must be unchanged
        assert len(store.list_all()) == 0
        assert store.vocabulary_version == v_before

    def test_use_once_keeps_candidate(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.use_once(c.id)
        # use_once should keep candidate available for future decisions
        assert len(manager.list_candidates()) == 1

    def test_use_once_does_not_change_version(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        manager.use_once(c.id)
        assert store.vocabulary_version == v_before

    def test_use_once_nonexistent_raises(self, manager):
        with pytest.raises(KeyError):
            manager.use_once("nonexistent")


# ── Ignore suggestion ────────────────────────────────────────────────────────

class TestIgnoreSuggestion:
    def test_ignore_removes_candidate(self, manager):
        c = make_candidate()
        manager.add_suggestion(c)
        manager.ignore(c.id)
        assert len(manager.list_candidates()) == 0

    def test_ignore_does_not_affect_store(self, manager, store):
        c = make_candidate()
        manager.add_suggestion(c)
        v_before = store.vocabulary_version
        manager.ignore(c.id)
        assert len(store.list_all()) == 0
        assert store.vocabulary_version == v_before

    def test_ignore_nonexistent_raises(self, manager):
        with pytest.raises(KeyError):
            manager.ignore("nonexistent")


# ── Candidate model ──────────────────────────────────────────────────────────

class TestVocabularyCandidate:
    def test_candidate_has_source_model(self):
        c = make_candidate()
        assert c.source_model == "test-model-v1"

    def test_candidate_has_confidence(self):
        c = make_candidate()
        assert c.confidence == 0.85

    def test_candidate_has_task_id(self):
        c = make_candidate()
        assert c.task_id == "task-001"

    def test_candidate_has_created_at(self):
        c = make_candidate()
        assert c.created_at is not None

    def test_candidate_has_auto_id(self):
        c = make_candidate()
        assert len(c.id) > 0

    def test_candidate_concept_id_required(self):
        with pytest.raises(ValueError):
            make_candidate(concept_id="")

    def test_candidate_display_name_required(self):
        with pytest.raises(ValueError):
            make_candidate(display_name="")

    def test_candidate_immutable(self):
        c = make_candidate()
        with pytest.raises(Exception):
            c.display_name = "changed"


# ── List candidates ──────────────────────────────────────────────────────────

class TestListCandidates:
    def test_list_all_candidates(self, manager):
        manager.add_suggestion(make_candidate(concept_id="type.a", display_name="A"))
        manager.add_suggestion(make_candidate(concept_id="type.b", display_name="B"))
        assert len(manager.list_candidates()) == 2

    def test_list_candidates_by_category(self, manager):
        manager.add_suggestion(make_candidate(category=VocabularyCategory.TYPE, concept_id="type.a", display_name="A"))
        manager.add_suggestion(make_candidate(category=VocabularyCategory.SUBJECT, concept_id="subject.b", display_name="B"))
        type_candidates = manager.list_candidates(category=VocabularyCategory.TYPE)
        assert len(type_candidates) == 1

    def test_list_candidates_by_locale(self, manager):
        manager.add_suggestion(make_candidate(locale="en", concept_id="type.a", display_name="A"))
        manager.add_suggestion(make_candidate(locale="zh", concept_id="type.b", display_name="B"))
        en_candidates = manager.list_candidates(locale="en")
        assert len(en_candidates) == 1

    def test_list_candidates_empty(self, manager):
        assert manager.list_candidates() == []

    def test_list_candidates_only_shows_pending(self, manager):
        c1 = make_candidate(concept_id="type.1")
        c2 = make_candidate(concept_id="type.2")
        manager.add_suggestion(c1)
        manager.add_suggestion(c2)
        manager.accept(c1.id)
        # Only c2 should remain
        assert len(manager.list_candidates()) == 1
