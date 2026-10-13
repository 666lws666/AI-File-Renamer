"""Opening settings must not rewrite locale aliases or dirty the draft."""
from pathlib import Path
import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication
from src.qml_bootstrap import build_qml_runtime
from src.models.app_config import AppConfig
from tests.qml.test_preferences_page import FakeCredentialStore


@pytest.mark.parametrize('language,index', [('en-US', 1), ('en_US', 1), ('zh-CN', 0), ('zh_CN', 0)])
def test_language_alias_is_read_without_initialization_write(tmp_path, language, index):
    live = AppConfig(language=language)
    rt = build_qml_runtime(live_config=live,
        config_file=tmp_path / 'settings.json', credential_store=FakeCredentialStore(),
        connection_test_service=lambda *_: None, usage_recorder=None,
        batch_controller=None, watch_controller=None, status_controller=None)
    try:
        rt.root.findChild(QQuickItem, 'pageRouter').navigate('preferences')
        QApplication.processEvents()
        combo = rt.root.findChild(QQuickItem, 'languageCombo')
        assert combo.property('currentIndex') == index
        assert rt.controller.language == language.replace('-', '_')
        assert live.language == language
        assert rt.i18n.locale == language.replace('_', '-')
        assert not rt.controller.dirty
        assert not (tmp_path / 'settings.json').exists()
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()
