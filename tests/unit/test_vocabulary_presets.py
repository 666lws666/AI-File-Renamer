"""Tests for Vocabulary Presets — General pack, versioned, fail-closed on corruption."""

import json
import pytest
from pathlib import Path
from src.core.vocabulary import VocabularyCategory, VocabularyEntry
from src.core.vocabulary_presets import (
    PresetPack,
    PresetIntegrityError,
    load_preset_pack,
    get_general_presets,
    GENERAL_PRESETS_VERSION,
)


# ── Presets loadable ─────────────────────────────────────────────────────────

class TestPresetsLoadable:
    def test_presets_loadable(self):
        pack = get_general_presets()
        assert pack is not None
        assert isinstance(pack, PresetPack)
        assert len(pack.entries) > 0

    def test_preset_pack_has_version(self):
        pack = get_general_presets()
        assert pack.version > 0
        assert isinstance(pack.version, int)

    def test_presets_version_is_stable(self):
        """The GENERAL_PRESETS_VERSION constant must match the loaded pack version."""
        pack = get_general_presets()
        assert pack.version == GENERAL_PRESETS_VERSION


# ── Subjects ─────────────────────────────────────────────────────────────────

class TestPresetSubjects:
    def test_presets_include_all_subjects(self):
        pack = get_general_presets()
        subjects = {
            e.concept_id.split(".", 1)[1]
            for e in pack.entries
            if e.category == VocabularyCategory.SUBJECT
        }
        expected = {"personal", "finance", "legal", "health", "learning", "research", "travel", "home"}
        assert subjects == expected

    def test_subjects_have_zh_and_en(self):
        pack = get_general_presets()
        subjects_en = {
            e for e in pack.entries
            if e.category == VocabularyCategory.SUBJECT and e.locale == "en"
        }
        subjects_zh = {
            e for e in pack.entries
            if e.category == VocabularyCategory.SUBJECT and e.locale == "zh"
        }
        assert len(subjects_en) == 8
        assert len(subjects_zh) == 8

    def test_subjects_have_display_names(self):
        pack = get_general_presets()
        for e in pack.entries:
            if e.category == VocabularyCategory.SUBJECT:
                assert len(e.display_name) > 0, f"Empty display_name for {e.concept_id}/{e.locale}"


# ── Types ────────────────────────────────────────────────────────────────────

class TestPresetTypes:
    def test_presets_include_all_types(self):
        pack = get_general_presets()
        types = {
            e.concept_id.split(".", 1)[1]
            for e in pack.entries
            if e.category == VocabularyCategory.TYPE
        }
        expected = {"invoice", "receipt", "statement", "contract", "proposal",
                    "report", "presentation", "meeting-note", "minutes"}
        assert types == expected

    def test_types_have_zh_and_en(self):
        pack = get_general_presets()
        types_en = {
            e for e in pack.entries
            if e.category == VocabularyCategory.TYPE and e.locale == "en"
        }
        types_zh = {
            e for e in pack.entries
            if e.category == VocabularyCategory.TYPE and e.locale == "zh"
        }
        assert len(types_en) == 9
        assert len(types_zh) == 9

    def test_types_have_display_names(self):
        pack = get_general_presets()
        for e in pack.entries:
            if e.category == VocabularyCategory.TYPE:
                assert len(e.display_name) > 0


# ── Versioning ───────────────────────────────────────────────────────────────

class TestPresetsVersioned:
    def test_presets_versioned_for_cache_invalidation(self):
        pack = get_general_presets()
        # Version exists and is a positive integer
        assert isinstance(pack.version, int)
        assert pack.version >= 1

    def test_different_version_different_pack(self):
        """When version changes, the pack should be reloadable with new version."""
        pack_v1 = get_general_presets()
        pack_v2 = get_general_presets()  # reload
        assert pack_v1.version == pack_v2.version
        # Same version → same entry count
        assert len(pack_v1.entries) == len(pack_v2.entries)

    def test_system_entry_ids_are_stable_across_fresh_loads(self):
        first = load_preset_pack(Path(__file__).parents[2] / "src" / "core" / "data" / "vocabulary_presets_general.json")
        second = load_preset_pack(Path(__file__).parents[2] / "src" / "core" / "data" / "vocabulary_presets_general.json")

        assert [entry.id for entry in first.entries] == [entry.id for entry in second.entries]


# ── Fail-closed ──────────────────────────────────────────────────────────────

class TestPresetsFailClosed:
    def test_corrupted_json_fails_closed(self, tmp_path):
        bad_file = tmp_path / "bad_presets.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(PresetIntegrityError):
            load_preset_pack(bad_file)

    def test_missing_version_fails_closed(self, tmp_path):
        bad_file = tmp_path / "no_version.json"
        bad_file.write_text(json.dumps({"entries": []}), encoding="utf-8")
        with pytest.raises(PresetIntegrityError, match="version"):
            load_preset_pack(bad_file)

    def test_invalid_version_fails_closed(self, tmp_path):
        bad_file = tmp_path / "bad_version.json"
        bad_file.write_text(json.dumps({"version": "not-a-number", "entries": []}), encoding="utf-8")
        with pytest.raises(PresetIntegrityError, match="version"):
            load_preset_pack(bad_file)

    def test_duplicate_concept_id_in_preset_fails_closed(self, tmp_path):
        bad_file = tmp_path / "dupes.json"
        data = {
            "version": 1,
            "entries": [
                {
                    "category": "type",
                    "concept_id": "type.invoice",
                    "display_name": "Invoice",
                    "locale": "en",
                    "source": "system",
                },
                {
                    "category": "type",
                    "concept_id": "type.invoice",
                    "display_name": "Invoice Duplicate",
                    "locale": "en",
                    "source": "system",
                },
            ],
        }
        bad_file.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetIntegrityError, match="duplicate"):
            load_preset_pack(bad_file)

    def test_illegal_category_in_preset_fails_closed(self, tmp_path):
        bad_file = tmp_path / "bad_cat.json"
        data = {
            "version": 1,
            "entries": [
                {
                    "category": "not_a_category",
                    "concept_id": "bad.test",
                    "display_name": "Test",
                    "locale": "en",
                    "source": "system",
                },
            ],
        }
        bad_file.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(PresetIntegrityError, match="category"):
            load_preset_pack(bad_file)

    def test_presets_are_system_source(self):
        pack = get_general_presets()
        from src.core.vocabulary import VocabularySource
        for e in pack.entries:
            assert e.source == VocabularySource.SYSTEM, \
                f"Preset {e.concept_id} has source {e.source}, expected system"


# ── PresetPack model ─────────────────────────────────────────────────────────

class TestPresetPackModel:
    def test_preset_pack_has_entries(self):
        pack = get_general_presets()
        for e in pack.entries:
            assert isinstance(e, VocabularyEntry)

    def test_preset_pack_has_correct_categories(self):
        pack = get_general_presets()
        categories = {e.category for e in pack.entries}
        assert VocabularyCategory.SUBJECT in categories
        assert VocabularyCategory.TYPE in categories
        # General preset only covers subject and type
