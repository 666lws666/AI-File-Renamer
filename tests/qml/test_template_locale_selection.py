"""Locale model resets must not replace a template's persisted option."""
from PySide6.QtWidgets import QApplication
from tests.qml.test_beginner_ui_polish import QML, template_controller, find
from tests.qml.conftest import make_handle


def test_nonfirst_template_options_survive_locale_model_reset(tmp_path):
    ctrl = template_controller(tmp_path / 'templates.json')
    ctrl.beginEditTemplate(ctrl.templates[0]['id'])
    expected = {'dateFormat': 'YYYY-MM', 'separator': '-', 'outputLanguage': 'ja', 'orgMode': 'project_tree'}
    objects = {'dateFormat': 'templateDateFormat', 'separator': 'templateSeparator',
               'outputLanguage': 'templateOutputLanguage', 'orgMode': 'templateOrgMode'}
    for option, value in expected.items():
        ctrl.setDraftOption(option, value)
    h = make_handle(QML / 'TemplateEditor.qml', ctrl=ctrl)
    try:
        for locale in ('zh-CN', 'en-US', 'zh-CN'):
            h.i18n.set_locale(locale)
            QApplication.processEvents()
            for option, value in expected.items():
                assert find(h, objects[option]).property('currentValue') == value, (locale, option)
                assert ctrl.draftOptions[option] == value
        h.assert_zero_warnings()
    finally:
        h.cleanup()
