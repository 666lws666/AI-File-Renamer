"""User-facing labels must map to real stored values without implicit writes."""
from pathlib import Path
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.qml.conftest import make_handle
from tests.qml.test_general_settings import _make_ctrl
from tests.unit.test_template_presets import controller as template_controller
from src.core.template_model import OrgMode
from src.core.template_store import TemplateStore

QML = Path(__file__).parents[2] / 'src/ui_qml'


def find(handle, name):
    pending = [handle.root]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    return None


def evaluate(handle, obj, expression):
    result = QQmlExpression(handle.engine.rootContext(), obj, expression)
    value, _ = result.evaluate()
    assert not result.hasError(), result.error().toString()
    QApplication.processEvents()
    return value


def test_default_template_is_named_select_and_cancel_restores(tmp_path):
    templates = template_controller(tmp_path / 'templates.json')
    settings = _make_ctrl(tmp_path)
    settings.openSession()
    handle = make_handle(QML / 'GeneralSettingsCard.qml', ctrl=settings)
    try:
        assert handle.root.setProperty('templateController', templates)
        combo = find(handle, 'defaultTemplateField')
        assert combo.property('editable') is False
        assert combo.property('count') == 10
        assert combo.property('currentIndex') == 0
        assert settings.defaultTemplateId == '' and not settings.dirty
        evaluate(handle, combo, 'currentIndex = 2; activated(2)')
        assert settings.defaultTemplateId == templates.templates[1]['id']
        assert combo.property('currentText') == '简洁标题'
        settings.cancel()
        QApplication.processEvents()
        assert settings.defaultTemplateId == ''
        assert combo.property('currentIndex') == 0
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_missing_default_is_visible_blocking_and_not_silently_replaced(tmp_path):
    templates = template_controller(tmp_path / 'templates.json')
    settings = _make_ctrl(tmp_path)
    settings.openSession()
    settings.defaultTemplateId = 'missing-template'
    handle = make_handle(QML / 'GeneralSettingsCard.qml', ctrl=settings)
    try:
        assert handle.root.setProperty('templateController', templates)
        combo = find(handle, 'defaultTemplateField')
        assert combo.property('currentIndex') == -1
        assert settings.defaultTemplateId == 'missing-template'
        assert handle.root.property('inputError') is True
        assert find(handle, 'defaultTemplateError').property('visible') is True
        evaluate(handle, combo, 'currentIndex = 0; activated(0)')
        assert not handle.root.property('inputError')
        assert settings.defaultTemplateId == ''
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_preferences_receives_catalog_from_router(tmp_path):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime
    from tests.qml.test_general_settings import FakeCredentialStore
    runtime = build_qml_runtime(live_config=AppConfig(), config_file=tmp_path / 'settings.json',
        credential_store=FakeCredentialStore(), connection_test_service=lambda *_: None,
        usage_recorder=None, batch_controller=None, watch_controller=None, status_controller=None)
    try:
        router = runtime.root.findChild(QQuickItem, 'pageRouter')
        expression = QQmlExpression(runtime.engine.rootContext(), router, "navigate('preferences')")
        expression.evaluate()
        QApplication.processEvents()
        combo = runtime.root.findChild(QQuickItem, 'defaultTemplateField')
        assert combo.property('count') == 10
        assert runtime.controller.dirty is False
        runtime.controller.defaultTemplateId = 'deleted-template'
        QApplication.processEvents()
        assert not runtime.root.findChild(QQuickItem, 'saveBtn').property('enabled')
        page = router.property('currentItem')
        QQmlExpression(runtime.engine.rootContext(), page, 'doSave()').evaluate()
        QApplication.processEvents()
        assert not (tmp_path / 'settings.json').exists()
        assert runtime.controller.dirty is True
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


@pytest.mark.parametrize('mode', [OrgMode.SUBJECT_TREE, OrgMode.TYPE_TREE, OrgMode.PROJECT_TREE])
def test_organization_selection_reflects_stored_mode_and_switches(tmp_path, mode):
    path = tmp_path / 'templates.json'
    templates = template_controller(path)
    first = templates.templates[0]['id']
    TemplateStore(path).update(first, org_mode=mode)
    templates = template_controller(path)
    templates.beginEditTemplate(first)
    handle = make_handle(QML / 'TemplateEditor.qml', ctrl=templates)
    try:
        combo = find(handle, 'templateOrgMode')
        assert combo.property('currentValue') == mode.value
        assert templates.draftOptions['orgMode'] == mode.value
        templates.beginEditTemplate(templates.templates[1]['id'])
        QApplication.processEvents()
        assert combo.property('currentValue') == 'flat'
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_editor_translates_language_fields_and_date_labels(tmp_path):
    templates = template_controller(tmp_path / 'templates.json')
    templates.beginEditTemplate(templates.templates[0]['id'])
    handle = make_handle(QML / 'TemplateEditor.qml', ctrl=templates)
    try:
        assert find(handle, 'templateOutputLanguage').property('currentText') == '简体中文'
        assert '2026-09-09' in find(handle, 'templateDateFormat').property('currentText')
        assert '下划线' in find(handle, 'templateSeparator').property('currentText')
        title = find(handle, 'fieldLabel_dcTitle')
        assert title is not None and title.property('text').startswith('标题')
        assert templates.draftOptions['outputLanguage'] == 'zh'
        handle.i18n.set_locale('en-US')
        QApplication.processEvents()
        assert find(handle, 'templateOutputLanguage').property('currentText') == 'Simplified Chinese'
        assert title.property('text').startswith('Title')
        assert templates.draftOptions['outputLanguage'] == 'zh'
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_vocabulary_source_is_localized(tmp_path):
    templates = template_controller(tmp_path / 'templates.json')
    handle = make_handle(QML / 'VocabList.qml', ctrl=templates)
    try:
        row = evaluate(handle, handle.root, 'itemAtIndex(0)')
        badge = row.findChild(QQuickItem, 'vocabularySourceLabel')
        assert badge is not None and badge.property('text') == '内置'
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
