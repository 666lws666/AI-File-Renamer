"""M4 QML-facing template and controlled-vocabulary controller tests."""

from src.core.template_store import TemplateStore
from src.core.vocabulary import VocabularyCategory, VocabularyStore
from src.core.vocabulary_ai import VocabularyAIManager, VocabularyCandidate
from src.controllers.template_page_controller import TemplatePageController


def _controller(tmp_path):
    template_store = TemplateStore(tmp_path / "templates.json")
    vocabulary_store = VocabularyStore()
    manager = VocabularyAIManager(vocabulary_store)
    return TemplatePageController(
        template_store=template_store,
        vocabulary_store=vocabulary_store,
        vocabulary_manager=manager,
        vocabulary_state_path=tmp_path / "vocabulary.json",
    )


def test_controller_seeds_default_template_and_general_vocabulary(tmp_path):
    controller = _controller(tmp_path)

    assert controller.templateCount == 9
    assert controller.templates[0]["pattern"] == "{dcDate}_{dcTitle}"
    assert controller.vocabularyCount > 0
    assert {row["category"] for row in controller.allVocabularyEntries} == {
        "subject", "organization", "project", "status", "type"
    }


def test_controller_locale_switch_changes_visible_vocabulary_without_rebuild(tmp_path):
    controller = _controller(tmp_path)
    controller.setVocabularyCategory("subject")
    assert any(row["displayName"] == "Personal" for row in controller.vocabularyEntries)

    controller.setLocale("zh-CN")

    assert any(row["displayName"] == "个人" for row in controller.vocabularyEntries)
    assert all(row["locale"] == "zh" for row in controller.vocabularyEntries)


def test_builtin_default_template_name_follows_locale_without_mutating_store(tmp_path):
    controller = _controller(tmp_path)
    stored = controller.get_template_for_analysis()
    assert stored.name == "General Naming (Default)"

    controller.setLocale("zh-CN")
    assert controller.templates[0]["name"] == "通用命名（默认）"
    assert controller.get_template_for_analysis().name == "General Naming (Default)"

    controller.setLocale("en-US")
    assert controller.templates[0]["name"] == "General Naming (Default)"


def test_user_template_name_that_resembles_default_is_never_translated(tmp_path):
    controller = _controller(tmp_path)
    controller.beginCreateTemplate()
    controller.setDraftName("General Naming (Default) copy")
    assert controller.saveDraft() is True

    controller.setLocale("zh-CN")
    names = {row["name"] for row in controller.templates}
    assert "General Naming (Default) copy" in names


def test_create_template_uses_ordered_enabled_fields_and_shared_renderer(tmp_path):
    controller = _controller(tmp_path)
    controller.beginCreateTemplate()
    controller.setDraftName("Project filing")
    controller.setDraftFieldEnabled("dcSubject", True)
    controller.moveDraftField("dcSubject", -1)

    assert controller.saveDraft() is True
    created = next(row for row in controller.templates if row["name"] == "Project filing")
    assert created["pattern"] == "{dcDate}_{dcSubject}_{dcTitle}"
    assert controller.previewText.endswith(".pdf")
    assert "finance" in controller.previewText


def test_edit_template_increments_version_and_cancel_preserves_store(tmp_path):
    controller = _controller(tmp_path)
    template_id = controller.templates[0]["id"]

    controller.beginEditTemplate(template_id)
    controller.setDraftName("Changed")
    controller.cancelDraft()
    assert controller.templates[0]["name"] != "Changed"

    controller.beginEditTemplate(template_id)
    controller.setDraftName("Changed")
    assert controller.saveDraft() is True
    assert controller.templates[0]["name"] == "Changed"
    assert controller.templates[0]["version"] == 2


def test_delete_template_persists_and_last_template_is_protected(tmp_path):
    controller = _controller(tmp_path)
    for row in controller.templates[1:]:
        assert controller.deleteTemplate(row["id"]) is True
    protected_id = controller.templates[0]["id"]
    assert controller.deleteTemplate(protected_id) is False
    assert controller.templateCount == 1

    controller.beginCreateTemplate()
    controller.setDraftName("Temporary")
    assert controller.saveDraft() is True
    temporary_id = next(row["id"] for row in controller.templates if row["name"] == "Temporary")
    assert controller.deleteTemplate(temporary_id) is True

    restarted = _controller(tmp_path)
    assert restarted.templateCount == 1
    assert all(row["id"] != temporary_id for row in restarted.templates)


def test_vocabulary_filter_add_override_restore_and_candidate_review(tmp_path):
    controller = _controller(tmp_path)
    controller.setVocabularyCategory("subject")
    controller.setVocabularyQuery("finance")
    assert all("finance" in row["displayName"].lower() for row in controller.vocabularyEntries)

    controller.setVocabularyQuery("")
    assert controller.addVocabularyEntry("Operations", "subject.operations") is True
    added = next(row for row in controller.vocabularyEntries if row["conceptId"] == "subject.operations")
    assert added["source"] == "user"

    system_entry = next(row for row in controller.vocabularyEntries if row["source"] == "system")
    assert controller.overrideVocabularyEntry(system_entry["id"], "Personal files") is True
    assert any(row["displayName"] == "Personal files" for row in controller.vocabularyEntries)
    assert controller.restoreVocabularyCategory() >= 1

    candidate = VocabularyCandidate(
        category=VocabularyCategory.SUBJECT,
        concept_id="subject.archive",
        display_name="Archive",
        locale="en",
        confidence=0.91,
        source_model="fixture-model",
        task_id="task-1",
    )
    controller.vocabularyManager.add_suggestion(candidate)
    controller.refresh()
    assert controller.candidateCount == 1
    assert controller.acceptCandidate(candidate.id) is True
    assert controller.candidateCount == 0


def test_user_and_accepted_candidate_survive_controller_restart(tmp_path):
    first = _controller(tmp_path)
    first.setVocabularyCategory("subject")
    assert first.addVocabularyEntry("Operations", "subject.operations") is True
    candidate = VocabularyCandidate(
        category=VocabularyCategory.SUBJECT,
        concept_id="subject.archive",
        display_name="Archive",
        locale="en",
        confidence=0.91,
        source_model="fixture-model",
    )
    first.vocabularyManager.add_suggestion(candidate)
    assert first.acceptCandidate(candidate.id) is True

    second = _controller(tmp_path)
    concepts = {row["conceptId"] for row in second.allVocabularyEntries}
    assert "subject.operations" in concepts
    assert "subject.archive" in concepts


def test_vocabulary_save_failure_rolls_back_memory_and_candidate_status(tmp_path, monkeypatch):
    controller = _controller(tmp_path)
    before = list(controller.allVocabularyEntries)

    def fail_save(_path):
        raise OSError("disk full")

    monkeypatch.setattr(controller._vocabulary_store, "save_state", fail_save)
    assert controller.addVocabularyEntry("Unsafe", "subject.unsafe") is False
    assert controller.allVocabularyEntries == before

    candidate = VocabularyCandidate(
        category=VocabularyCategory.SUBJECT,
        concept_id="subject.retryable",
        display_name="Retryable",
        locale="en",
        confidence=0.9,
        source_model="fixture-model",
    )
    controller.vocabularyManager.add_suggestion(candidate)
    assert controller.acceptCandidate(candidate.id) is False
    assert controller.candidateCount == 1
    assert controller.allVocabularyEntries == before


def test_invalid_editor_and_vocabulary_input_fail_closed(tmp_path):
    controller = _controller(tmp_path)
    before_templates = list(controller.templates)
    controller.beginCreateTemplate()
    controller.setDraftName("   ")
    assert controller.saveDraft() is False
    assert controller.templates == before_templates
    assert controller.errorMessage

    before_vocab = list(controller.allVocabularyEntries)
    assert controller.addVocabularyEntry("", "subject.invalid") is False
    assert controller.allVocabularyEntries == before_vocab
