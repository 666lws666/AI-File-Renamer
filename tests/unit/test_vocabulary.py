"""Tests for Controlled Vocabulary domain model — 5 categories, stable concept IDs, locale display."""

import pytest
from src.core.vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
    VocabularyIntegrityError,
)


# ── Five categories ──────────────────────────────────────────────────────────

class TestVocabularyCategories:
    def test_five_categories_exist(self):
        categories = list(VocabularyCategory)
        assert len(categories) == 5
        names = {c.value for c in categories}
        assert names == {"subject", "organization", "project", "status", "type"}

    def test_category_enum_values(self):
        assert VocabularyCategory.SUBJECT.value == "subject"
        assert VocabularyCategory.ORGANIZATION.value == "organization"
        assert VocabularyCategory.PROJECT.value == "project"
        assert VocabularyCategory.STATUS.value == "status"
        assert VocabularyCategory.TYPE.value == "type"


# ── Concept ID ───────────────────────────────────────────────────────────────

class TestConceptId:
    def test_entry_has_stable_concept_id(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        assert entry.concept_id == "type.invoice"

    def test_concept_id_stable_across_locales(self):
        """Same concept_id should have different display names per locale."""
        en_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        zh_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="发票",
            locale="zh",
            source=VocabularySource.SYSTEM,
        )
        assert en_entry.concept_id == zh_entry.concept_id
        assert en_entry.display_name != zh_entry.display_name

    def test_concept_id_required(self):
        with pytest.raises(ValueError, match="concept_id"):
            VocabularyEntry(
                category=VocabularyCategory.TYPE,
                concept_id="",
                display_name="Invoice",
                locale="en",
                source=VocabularySource.SYSTEM,
            )


# ── Display name by locale ───────────────────────────────────────────────────

class TestDisplayNameByLocale:
    def test_display_name_varies_by_locale(self):
        entries = [
            VocabularyEntry(
                category=VocabularyCategory.SUBJECT,
                concept_id="subject.finance",
                display_name="Finance",
                locale="en",
                source=VocabularySource.SYSTEM,
            ),
            VocabularyEntry(
                category=VocabularyCategory.SUBJECT,
                concept_id="subject.finance",
                display_name="财务",
                locale="zh",
                source=VocabularySource.SYSTEM,
            ),
        ]
        store = VocabularyStore()
        for e in entries:
            store.add_entry(e)
        results_en = store.get_entries(VocabularyCategory.SUBJECT, "en")
        results_zh = store.get_entries(VocabularyCategory.SUBJECT, "zh")
        assert len(results_en) == 1
        assert len(results_zh) == 1
        assert results_en[0].display_name == "Finance"
        assert results_zh[0].display_name == "财务"


# ── Source tracking ──────────────────────────────────────────────────────────

class TestSourceTracking:
    def test_system_source(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.report",
            display_name="Report",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        assert entry.source == VocabularySource.SYSTEM

    def test_user_source(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.custom",
            display_name="Custom Doc",
            locale="en",
            source=VocabularySource.USER,
        )
        assert entry.source == VocabularySource.USER

    def test_ai_suggestion_source(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.ai_suggested",
            display_name="AI Suggested",
            locale="en",
            source=VocabularySource.AI_SUGGESTION,
            confidence=0.75,
            created_by_model="test-model",
        )
        assert entry.source == VocabularySource.AI_SUGGESTION
        assert entry.confidence == 0.75

    def test_ai_auto_source(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.ai_auto",
            display_name="Auto Created",
            locale="en",
            source=VocabularySource.AI_AUTO,
            confidence=0.95,
        )
        assert entry.source == VocabularySource.AI_AUTO

    def test_four_source_types_exist(self):
        sources = list(VocabularySource)
        assert len(sources) == 4
        names = {s.value for s in sources}
        assert names == {"system", "user", "ai_suggestion", "ai_auto"}

    def test_illegal_source_rejected(self):
        with pytest.raises(ValueError):
            VocabularyEntry(
                category=VocabularyCategory.TYPE,
                concept_id="type.test",
                display_name="Test",
                locale="en",
                source="illegal_source",
            )


# ── VocabularyStore ──────────────────────────────────────────────────────────

class TestVocabularyStore:
    def test_add_and_get_entries(self):
        store = VocabularyStore()
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(entry)
        results = store.get_entries(VocabularyCategory.TYPE, "en")
        assert len(results) == 1
        assert results[0].concept_id == "type.invoice"

    def test_get_entries_empty_category(self):
        store = VocabularyStore()
        assert store.get_entries(VocabularyCategory.SUBJECT, "en") == []

    def test_remove_entry(self):
        store = VocabularyStore()
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(entry)
        store.remove_entry(entry.id)
        assert store.get_entries(VocabularyCategory.TYPE, "en") == []

    def test_remove_nonexistent_raises(self):
        store = VocabularyStore()
        with pytest.raises(KeyError):
            store.remove_entry("nonexistent")

    def test_duplicate_concept_id_locale_rejected(self):
        """Same concept_id + locale combination must be rejected."""
        store = VocabularyStore()
        e1 = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        e2 = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice Duplicate",
            locale="en",
            source=VocabularySource.USER,
        )
        store.add_entry(e1)
        with pytest.raises(VocabularyIntegrityError, match="Duplicate"):
            store.add_entry(e2)

    def test_same_concept_different_locale_allowed(self):
        """Same concept_id with different locale is allowed."""
        store = VocabularyStore()
        e1 = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        e2 = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="发票",
            locale="zh",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(e1)
        store.add_entry(e2)  # Should not raise
        assert len(store.get_entries(VocabularyCategory.TYPE, "en")) == 1
        assert len(store.get_entries(VocabularyCategory.TYPE, "zh")) == 1

    def test_illegal_category_rejected(self):
        with pytest.raises(ValueError):
            VocabularyEntry(
                category="not_a_category",
                concept_id="x.y",
                display_name="X",
                locale="en",
                source=VocabularySource.SYSTEM,
            )

    def test_ai_entry_not_in_formal_by_default(self):
        """AI-sourced entries should be tracked but flagged, not mixed with system/user."""
        store = VocabularyStore()
        ai_entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.ai_test",
            display_name="AI Test",
            locale="en",
            source=VocabularySource.AI_SUGGESTION,
            confidence=0.8,
        )
        store.add_entry(ai_entry)
        # Default: entries filtered by source
        formal = store.get_entries(VocabularyCategory.TYPE, "en",
                                   include_ai_suggestions=False)
        assert len(formal) == 0
        # Including AI
        all_entries = store.get_entries(VocabularyCategory.TYPE, "en",
                                        include_ai_suggestions=True)
        assert len(all_entries) == 1

    def test_list_all_categories(self):
        store = VocabularyStore()
        store.add_entry(VocabularyEntry(
            category=VocabularyCategory.TYPE, concept_id="type.invoice",
            display_name="Invoice", locale="en", source=VocabularySource.SYSTEM,
        ))
        store.add_entry(VocabularyEntry(
            category=VocabularyCategory.SUBJECT, concept_id="subject.finance",
            display_name="Finance", locale="en", source=VocabularySource.SYSTEM,
        ))
        all_entries = store.list_all()
        assert len(all_entries) == 2
        categories = {e.category for e in all_entries}
        assert VocabularyCategory.TYPE in categories
        assert VocabularyCategory.SUBJECT in categories


# ── Entry model ──────────────────────────────────────────────────────────────

class TestVocabularyEntryModel:
    def test_entry_has_auto_id(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.report",
            display_name="Report",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        assert len(entry.id) > 0

    def test_entry_has_created_at(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.report",
            display_name="Report",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        assert entry.created_at is not None

    def test_entry_locale_required(self):
        with pytest.raises(ValueError, match="locale"):
            VocabularyEntry(
                category=VocabularyCategory.TYPE,
                concept_id="type.test",
                display_name="Test",
                locale="",
                source=VocabularySource.SYSTEM,
            )

    def test_entry_immutable(self):
        entry = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.report",
            display_name="Report",
            locale="en",
            source=VocabularySource.SYSTEM,
        )
        with pytest.raises(Exception):
            entry.concept_id = "changed"
