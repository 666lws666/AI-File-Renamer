"""Tests for auto-create vocabulary — opt-in, confidence threshold, dedup, rate limit, audit."""

import time
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
    AutoCreateConfig,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    return VocabularyStore()


@pytest.fixture
def manager(store):
    mgr = VocabularyAIManager(store)
    mgr.set_auto_create_config(AutoCreateConfig(
        enabled=True,
        confidence_threshold=0.9,
        rate_limit_window_seconds=60,
        max_per_window=5,
    ))
    return mgr


def make_high_conf_candidate(**kwargs):
    defaults = dict(
        category=VocabularyCategory.TYPE,
        concept_id="type.auto_test",
        display_name="Auto Test",
        locale="en",
        confidence=0.95,
        source_model="test-model",
        task_id="task-001",
    )
    defaults.update(kwargs)
    return VocabularyCandidate(**defaults)


# ── Auto-create disabled by default ──────────────────────────────────────────

class TestAutoCreateDisabledByDefault:
    def test_auto_create_disabled_by_default(self, store):
        mgr = VocabularyAIManager(store)
        assert mgr.auto_create_config.enabled is False

    def test_disabled_auto_create_rejects(self, store):
        mgr = VocabularyAIManager(store)
        # Default: disabled
        c = make_high_conf_candidate()
        result = mgr.try_auto_create(c)
        assert result is False
        assert len(store.list_all()) == 0

    def test_disabled_returns_false_not_exception(self, store):
        """When disabled, return False rather than raising — fail-closed."""
        mgr = VocabularyAIManager(store)
        c = make_high_conf_candidate()
        result = mgr.try_auto_create(c)
        assert result is False  # Not raised, just not created


# ── Opt-in auto-create ───────────────────────────────────────────────────────

class TestOptInAutoCreate:
    def test_opt_in_high_confidence_creates(self, manager, store):
        c = make_high_conf_candidate(confidence=0.95)
        result = manager.try_auto_create(c)
        assert result is True
        entries = store.get_entries(VocabularyCategory.TYPE, "en", include_ai_suggestions=True)
        assert len(entries) == 1
        assert entries[0].source == VocabularySource.AI_AUTO

    def test_auto_create_changes_version(self, manager, store):
        c = make_high_conf_candidate()
        v_before = store.vocabulary_version
        manager.try_auto_create(c)
        assert store.vocabulary_version > v_before


# ── Confidence threshold ─────────────────────────────────────────────────────

class TestConfidenceThreshold:
    def test_low_confidence_rejected(self, manager, store):
        c = make_high_conf_candidate(confidence=0.85)  # below 0.9 threshold
        result = manager.try_auto_create(c)
        assert result is False
        assert len(store.list_all()) == 0

    def test_exact_threshold_accepted(self, manager, store):
        c = make_high_conf_candidate(confidence=0.9)  # exactly at threshold
        result = manager.try_auto_create(c)
        assert result is True

    def test_just_below_threshold_rejected(self, manager, store):
        c = make_high_conf_candidate(confidence=0.89)
        result = manager.try_auto_create(c)
        assert result is False

    def test_confidence_zero_rejected(self, manager, store):
        c = make_high_conf_candidate(confidence=0.0)
        result = manager.try_auto_create(c)
        assert result is False

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValueError):
            make_high_conf_candidate(confidence=1.5)


# ── Dedup ────────────────────────────────────────────────────────────────────

class TestAutoCreateDedup:
    def test_duplicate_concept_id_locale_not_created(self, manager, store):
        c = make_high_conf_candidate(concept_id="type.invoice")
        manager.try_auto_create(c)  # first succeeds
        c2 = make_high_conf_candidate(concept_id="type.invoice")  # same concept_id+locale
        result = manager.try_auto_create(c2)
        assert result is False
        assert len(store.list_all()) == 1

    def test_dedup_against_existing_store_entries(self, manager, store):
        # Pre-existing entry in store
        existing = VocabularyEntry(
            category=VocabularyCategory.TYPE,
            concept_id="type.invoice",
            display_name="Invoice", locale="en",
            source=VocabularySource.SYSTEM,
        )
        store.add_entry(existing)
        # Try auto-create with same concept_id+locale
        c = make_high_conf_candidate(concept_id="type.invoice")
        result = manager.try_auto_create(c)
        assert result is False

    def test_dedup_against_previous_auto_creates(self, manager, store):
        c = make_high_conf_candidate(concept_id="type.unique")
        manager.try_auto_create(c)
        # Try again with same candidate data but new candidate object
        c2 = make_high_conf_candidate(concept_id="type.unique")
        result = manager.try_auto_create(c2)
        assert result is False
        assert len(store.list_all()) == 1


# ── Rate limiting ────────────────────────────────────────────────────────────

class TestAutoCreateRateLimit:
    def test_rate_limit_enforced(self, manager, store):
        manager.set_auto_create_config(AutoCreateConfig(
            enabled=True, confidence_threshold=0.9,
            rate_limit_window_seconds=60, max_per_window=2,
        ))
        for i in range(3):
            c = make_high_conf_candidate(concept_id=f"type.auto_{i}")
            result = manager.try_auto_create(c)
            if i < 2:
                assert result is True
            else:
                assert result is False, f"Expected rate limit at i={i}"

    def test_rate_limit_respects_window(self, manager, store):
        manager.set_auto_create_config(AutoCreateConfig(
            enabled=True, confidence_threshold=0.9,
            rate_limit_window_seconds=0.1, max_per_window=2,
        ))
        # Create 2 (fills window)
        manager.try_auto_create(make_high_conf_candidate(concept_id="type.a1"))
        manager.try_auto_create(make_high_conf_candidate(concept_id="type.a2"))
        # 3rd should fail
        c3 = make_high_conf_candidate(concept_id="type.a3")
        assert manager.try_auto_create(c3) is False
        # After window passes, should succeed
        time.sleep(0.15)
        c4 = make_high_conf_candidate(concept_id="type.a4")
        assert manager.try_auto_create(c4) is True


# ── Audit log ────────────────────────────────────────────────────────────────

class TestAutoCreateAuditLog:
    def test_audit_log_records_creation(self, manager):
        c = make_high_conf_candidate()
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert len(log) == 1
        assert log[0].concept_id == "type.auto_test"
        assert log[0].success is True

    def test_audit_log_records_rejection(self, manager):
        c = make_high_conf_candidate(confidence=0.5)  # below threshold
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert len(log) == 1
        assert log[0].success is False
        assert "confidence" in log[0].reason.lower()

    def test_audit_log_records_source_model(self, manager):
        c = make_high_conf_candidate(source_model="gpt-4o")
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert log[0].source_model == "gpt-4o"

    def test_audit_log_records_task_id(self, manager):
        c = make_high_conf_candidate(task_id="task-xyz")
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert log[0].task_id == "task-xyz"

    def test_audit_log_records_confidence(self, manager):
        c = make_high_conf_candidate(confidence=0.92)
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert log[0].confidence == 0.92

    def test_audit_log_has_timestamp(self, manager):
        c = make_high_conf_candidate()
        manager.try_auto_create(c)
        log = manager.get_audit_log()
        assert log[0].created_at is not None

    def test_audit_log_empty_initially(self, manager):
        assert manager.get_audit_log() == []


# ── Known issues rejected ────────────────────────────────────────────────────

class TestAutoCreateFailClosed:
    def test_unknown_category_rejected(self, store):
        """Category must be a valid VocabularyCategory."""
        with pytest.raises(ValueError):
            VocabularyCandidate(
                category="not_a_category",  # type: ignore
                concept_id="bad.test",
                display_name="Test",
                locale="en",
                confidence=0.95,
            )

    def test_illegal_locale_rejected(self):
        with pytest.raises(ValueError):
            VocabularyCandidate(
                category=VocabularyCategory.TYPE,
                concept_id="type.test",
                display_name="Test",
                locale="",  # empty locale
                confidence=0.95,
            )

    def test_disabled_config_blocks_all(self, store):
        mgr = VocabularyAIManager(store)
        mgr.set_auto_create_config(AutoCreateConfig(enabled=False))
        c = make_high_conf_candidate(confidence=0.99)
        assert mgr.try_auto_create(c) is False
        assert len(store.list_all()) == 0


# ── AutoCreateConfig ─────────────────────────────────────────────────────────

class TestAutoCreateConfig:
    def test_default_config_disabled(self):
        config = AutoCreateConfig()
        assert config.enabled is False

    def test_custom_config(self):
        config = AutoCreateConfig(
            enabled=True,
            confidence_threshold=0.85,
            rate_limit_window_seconds=120,
            max_per_window=10,
        )
        assert config.enabled is True
        assert config.confidence_threshold == 0.85

    def test_set_config_updates_manager(self, store):
        mgr = VocabularyAIManager(store)
        mgr.set_auto_create_config(AutoCreateConfig(
            enabled=True, confidence_threshold=0.8,
        ))
        assert mgr.auto_create_config.confidence_threshold == 0.8

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError):
            AutoCreateConfig(confidence_threshold=1.5)

    def test_invalid_max_per_window_rejected(self):
        with pytest.raises(ValueError):
            AutoCreateConfig(max_per_window=0)
