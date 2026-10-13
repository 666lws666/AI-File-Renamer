"""Real runtime language preview is a draft, not a permanent side effect."""
import json
from PySide6.QtWidgets import QApplication
from tests.qml.test_language_switching import _build_runtime, _navigate_preferences, _find


def choose(rt, index):
    combo = _find(rt, 'languageCombo')
    combo.setProperty('currentIndex', index)
    combo.activated.emit(index)
    QApplication.processEvents()


def test_discard_restores_saved_language_without_writing(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        router, _ = _navigate_preferences(rt)
        choose(rt, 1)
        assert rt.i18n.locale == 'en-US'
        router.navigate('batch')
        router.onUnsavedDiscard()
        QApplication.processEvents()
        assert rt.i18n.locale == 'zh-CN'
        assert not (tmp_path / 'settings.json').exists()
        _navigate_preferences(rt)
        assert _find(rt, 'languageCombo').property('currentIndex') == 0
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_hk_save_then_cancel_restores_last_saved_language(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        assert _find(rt, 'languageCombo').property('count') == 3
        choose(rt, 2)
        assert rt.i18n.locale == 'zh-HK'
        rt.controller.saveAll()
        assert not rt.controller.dirty
        snapshot = (tmp_path / 'settings.json').read_bytes()
        assert json.loads(snapshot)['language'] == 'zh_HK'
        choose(rt, 1)
        rt.controller.cancel()
        QApplication.processEvents()
        assert rt.i18n.locale == 'zh-HK'
        assert (tmp_path / 'settings.json').read_bytes() == snapshot
        rt.controller.openSession()
        assert rt.controller.language == 'zh_HK'
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_failed_save_keeps_preview_and_draft(tmp_path, monkeypatch):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        choose(rt, 1)
        monkeypatch.setattr(rt.controller, '_validate', lambda: ['forced isolated failure'])
        rt.controller.saveAll()
        assert rt.i18n.locale == 'en-US' and rt.controller.dirty
        assert not (tmp_path / 'settings.json').exists()
        rt.controller.cancel()
        QApplication.processEvents()
        assert rt.i18n.locale == 'zh-CN'
    finally:
        rt.cleanup()
