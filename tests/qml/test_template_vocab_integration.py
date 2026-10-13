"""M4 Templates/Vocabulary shared-page integration tests."""

from pathlib import Path

from src.controllers.template_page_controller import TemplatePageController
from src.core.template_store import TemplateStore
from src.core.vocabulary import VocabularyStore
from tests.qml.conftest import make_handle


QML = Path(__file__).parents[2] / "src" / "ui_qml"


def test_templates_page_exposes_vocabulary_guidance_without_new_nav_entry(tmp_path):
    controller = TemplatePageController(
        template_store=TemplateStore(tmp_path / "templates.json"),
        vocabulary_store=VocabularyStore(),
    )
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        assert handle.root.property("pageId") == "templates"
        assert handle.root.property("hasVocabularyMainNavigation") is False
        assert handle.root.property("controlledFieldCount") == 5
        assert handle.root.property("vocabularyAvailable") is True
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
