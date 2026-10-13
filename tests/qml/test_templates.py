"""M4 Templates page component and interaction tests."""

from pathlib import Path

from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from src.controllers.template_page_controller import TemplatePageController
from src.core.template_store import TemplateStore
from src.core.vocabulary import VocabularyStore
from src.core.vocabulary_ai import VocabularyAIManager
from tests.qml.conftest import make_handle


QML = Path(__file__).parents[2] / "src" / "ui_qml"


def _controller(tmp_path):
    vocabulary = VocabularyStore()
    return TemplatePageController(
        template_store=TemplateStore(tmp_path / "templates.json"),
        vocabulary_store=vocabulary,
        vocabulary_manager=VocabularyAIManager(vocabulary),
    )


def _find(handle, name):
    return handle.root.findChild(QQuickItem, name)


def _click(item):
    QMetaObject.invokeMethod(item, "click")
    QApplication.processEvents()


def _mouse_click(handle, item):
    scene = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(handle._host_view, Qt.LeftButton, Qt.NoModifier, scene)
    QTest.qWait(50)


def test_templates_page_renders_at_reference_and_minimum_sizes(tmp_path):
    for width, height in ((1000, 668), (900, 608)):
        handle = make_handle(QML / "TemplatesPage.qml", width, height, _controller(tmp_path))
        try:
            assert _find(handle, "templatesPageTitle") is not None
            assert _find(handle, "templatesTabButton") is not None
            assert _find(handle, "vocabularyTabButton") is not None
            assert _find(handle, "templateList") is not None
            assert handle.root.property("contentFits") is True
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()


def test_real_mouse_click_opens_editor_and_minimum_size_is_scrollable(tmp_path):
    controller = _controller(tmp_path)
    handle = make_handle(QML / "TemplatesPage.qml", 900, 608, controller)
    try:
        _mouse_click(handle, _find(handle, "addTemplateButton"))
        assert controller.editorOpen is True
        scroll = _find(handle, "templateEditorScroll")
        assert scroll is not None
        assert scroll.property("contentHeight") > scroll.property("height")
        bar = _find(handle, "templateEditorScrollBar")
        assert bar is not None
        target = bar.mapToScene(QPointF(bar.width() / 2, bar.height() - 4)).toPoint()
        QTest.mouseClick(handle._host_view, Qt.LeftButton, Qt.NoModifier, target)
        QTest.qWait(100)
        assert scroll.property("contentY") > 0
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_create_and_edit_template_flow_uses_live_preview(tmp_path):
    controller = _controller(tmp_path)
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        _click(_find(handle, "addTemplateButton"))
        assert controller.editorOpen is True
        assert _find(handle, "templateEditor").property("visible") is True
        assert _find(handle, "fieldSorter") is not None
        assert _find(handle, "templatePreviewText") is not None
        assert controller.previewText.endswith(".pdf")

        _find(handle, "templateNameField").setProperty("text", "Client archive")
        controller.setDraftName("Client archive")
        _click(_find(handle, "templateSaveButton"))
        assert controller.templateCount == 10
        assert any(row["name"] == "Client archive" for row in controller.templates)
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_template_list_exposes_working_delete_action_after_second_template(tmp_path):
    controller = _controller(tmp_path)
    controller.beginCreateTemplate()
    controller.setDraftName("Temporary")
    assert controller.saveDraft() is True
    handle = make_handle(QML / "TemplatesPage.qml", ctrl=controller)
    try:
        for _ in range(5):
            QApplication.processEvents()
        list_view = _find(handle, "templateList")
        assert list_view.property("count") == 10
        row, _undefined = QQmlExpression(
            handle.engine.rootContext(), list_view, "itemAtIndex(0)"
        ).evaluate()
        assert row is not None
        delete_button = row.findChild(QQuickItem, "deleteTemplateButton")
        assert delete_button is not None
        assert delete_button.property("visible") is True
        _click(delete_button)
        assert controller.templateCount == 9
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_field_sorter_changes_pattern_order_and_can_disable_field(tmp_path):
    controller = _controller(tmp_path)
    controller.beginCreateTemplate()
    controller.setDraftName("Ordered")
    controller.setDraftFieldEnabled("dcSubject", True)
    before = controller.previewText
    controller.moveDraftField("dcSubject", -1)
    controller.setDraftFieldEnabled("dcTitle", False)

    assert controller.saveDraft() is True
    row = next(item for item in controller.templates if item["name"] == "Ordered")
    assert row["pattern"] == "{dcDate}_{dcSubject}"
    assert controller.previewText != before


def test_main_router_opens_real_templates_page_with_precreation_controller(tmp_path):
    from PySide6.QtCore import QObject
    from PySide6.QtQml import QQmlExpression

    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    class Credentials:
        def get(self, *_args): return None
        def set(self, *_args): return True
        def delete(self, *_args): return True

    controller = _controller(tmp_path)
    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=Credentials(),
        connection_test_service=lambda *_args: None,
        usage_recorder=None,
        template_controller=controller,
    )
    try:
        router = runtime.root.findChild(QObject, "pageRouter")
        expression = QQmlExpression(runtime.engine.rootContext(), router, "navigate('templates')")
        expression.evaluate()
        QApplication.processEvents()

        assert router.property("currentPage") == "templates"
        assert router.property("currentItem").objectName() == "templatesPage"
        assert all(row["locale"] == "zh" for row in controller.vocabularyEntries)
        runtime.i18n.set_locale("en-US")
        QApplication.processEvents()
        assert all(row["locale"] == "en" for row in controller.vocabularyEntries)
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()
