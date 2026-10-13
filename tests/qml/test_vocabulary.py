"""M4 controlled-vocabulary tab component and interaction tests."""

from pathlib import Path

from PySide6.QtCore import QMetaObject
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression
from PySide6.QtWidgets import QApplication

from src.controllers.template_page_controller import TemplatePageController
from src.core.template_store import TemplateStore
from src.core.vocabulary import VocabularyCategory, VocabularyStore
from src.core.vocabulary_ai import VocabularyAIManager, VocabularyCandidate
from tests.qml.conftest import make_handle


QML = Path(__file__).parents[2] / "src" / "ui_qml"


def _controller(tmp_path):
    vocabulary = VocabularyStore()
    manager = VocabularyAIManager(vocabulary)
    return TemplatePageController(
        template_store=TemplateStore(tmp_path / "templates.json"),
        vocabulary_store=vocabulary,
        vocabulary_manager=manager,
    )


def _find(handle, name):
    return handle.root.findChild(QQuickItem, name)


def _click(item):
    QMetaObject.invokeMethod(item, "click")
    QApplication.processEvents()


def test_vocabulary_is_second_tab_not_navigation_page(tmp_path):
    controller = _controller(tmp_path)
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        _click(_find(handle, "vocabularyTabButton"))
        assert controller.activeTab == "vocabulary"
        assert _find(handle, "vocabularyTab").property("visible") is True
        for category in ("subject", "organization", "project", "status", "type"):
            assert controller.setVocabularyCategory(category) is None
            assert controller.vocabularyEntries
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_search_source_filter_and_user_entry_form(tmp_path):
    controller = _controller(tmp_path)
    controller.setActiveTab("vocabulary")
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        assert _find(handle, "vocabularySearch") is not None
        assert _find(handle, "vocabularySourceFilter") is not None
        _click(_find(handle, "newVocabularyEntryButton"))
        assert _find(handle, "vocabularyEntryForm").property("visible") is True
        _find(handle, "vocabularyNameField").setProperty("text", "Operations")
        _find(handle, "vocabularyConceptField").setProperty("text", "subject.operations")
        _click(_find(handle, "saveVocabularyEntryButton"))
        assert any(row["conceptId"] == "subject.operations" for row in controller.vocabularyEntries)
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_candidate_panel_reviews_pending_ai_entry(tmp_path):
    controller = _controller(tmp_path)
    controller.vocabularyManager.add_suggestion(
        VocabularyCandidate(
            category=VocabularyCategory.SUBJECT,
            concept_id="subject.archive",
            display_name="Archive",
            locale="en",
            confidence=0.93,
            source_model="fixture-model",
        )
    )
    controller.setActiveTab("vocabulary")
    controller.refresh()
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        panel = _find(handle, "vocabularyCandidatePanel")
        assert panel is not None
        assert panel.property("candidateCount") == 1
        candidate_list = _find(handle, "vocabularyCandidateList")
        assert candidate_list is not None
        row, _undefined = QQmlExpression(
            handle.engine.rootContext(), candidate_list, "itemAtIndex(0)"
        ).evaluate()
        assert row is not None
        for name in ("candidateAcceptButton", "candidateUseOnceButton", "candidateIgnoreButton"):
            button = row.findChild(QQuickItem, name)
            assert button is not None
            assert button.x() >= 0
            assert button.x() + button.width() <= row.width() + 1
        assert controller.acceptCandidate(controller.candidateEntries[0]["id"]) is True
        assert controller.candidateCount == 0
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
