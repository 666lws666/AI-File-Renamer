"""Language bootstrap + instant switching — real QML runtime (M6 correction).

- bootstrap must initialize I18n from the live/draft config BEFORE QML
  creation: zh_CN starts in Chinese, en_US starts in English;
- switching the General card language combo must re-translate the CURRENT
  page immediately, in BOTH directions;
- the chosen language persists after Save and survives a page reopen.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).parent.parent.parent / "src" / "ui_qml"


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get(self, s, a):
        return self.values.get((s, a))

    def set(self, s, a, v):
        self.values[(s, a)] = v
        return True

    def delete(self, s, a):
        self.values.pop((s, a), None)
        return True


def _build_runtime(tmp_path, language="zh_CN"):
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    return build_qml_runtime(
        live_config=AppConfig(language=language),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        # not testing the default recorder — keep the user dir untouched
        usage_recorder=None,
    )


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


def _navigate_preferences(rt):
    from PySide6.QtWidgets import QApplication
    router = _find(rt, "pageRouter")
    router.navigate("preferences")
    QApplication.processEvents()
    item = router.property("currentItem")
    assert item is not None and item.property("objectName") == "preferencesPage"
    return router, item


def _page_title(rt):
    return _find(rt, "preferencesTitle").property("text")


def test_zh_cn_startup_displays_chinese(tmp_path):
    """zh_CN live config -> I18n initialized to zh-CN BEFORE QML creation."""
    rt = _build_runtime(tmp_path, language="zh_CN")
    try:
        assert rt.i18n.locale == "zh-CN", (
            "bootstrap must init I18n from live config, got " + rt.i18n.locale
        )
        _navigate_preferences(rt)
        assert _page_title(rt) == "设置", f"zh title should be 设置, got {_page_title(rt)!r}"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_en_us_startup_displays_english(tmp_path):
    rt = _build_runtime(tmp_path, language="en_US")
    try:
        assert rt.i18n.locale == "en-US"
        _navigate_preferences(rt)
        assert _page_title(rt) == "Preferences", (
            f"en title should be Preferences, got {_page_title(rt)!r}"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_instant_switch_zh_to_en_and_back(tmp_path):
    """Both directions must re-translate the current page immediately."""
    rt = _build_runtime(tmp_path, language="zh_CN")
    try:
        _navigate_preferences(rt)
        assert _page_title(rt) == "设置"
        combo = _find(rt, "languageCombo")

        combo.setProperty("currentIndex", 1)  # en_US
        combo.activated.emit(1)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert rt.controller.property("language") == "en_US"
        assert _page_title(rt) == "Preferences", (
            f"page must switch to English instantly, got {_page_title(rt)!r}"
        )

        combo.setProperty("currentIndex", 0)  # back to zh_CN
        combo.activated.emit(0)
        QApplication.processEvents()
        assert rt.controller.property("language") == "zh_CN"
        assert _page_title(rt) == "设置", (
            f"page must switch back to Chinese instantly, got {_page_title(rt)!r}"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_language_persists_after_save_and_reopen(tmp_path):
    """Save keeps the language in the config file; a page reopen keeps it."""
    import json
    rt = _build_runtime(tmp_path, language="zh_CN")
    try:
        from PySide6.QtWidgets import QApplication
        router, _page = _navigate_preferences(rt)
        combo = _find(rt, "languageCombo")
        combo.setProperty("currentIndex", 1)
        combo.activated.emit(1)
        QApplication.processEvents()

        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert rt.controller.property("dirty") is False
        saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert saved["language"] == "en_US", f"language must persist, got {saved.get('language')}"

        # reopen the page -> still English
        router.navigate("batch")
        QApplication.processEvents()
        router.navigate("preferences")
        QApplication.processEvents()
        assert _page_title(rt) == "Preferences"
        assert _find(rt, "languageCombo").property("currentIndex") == 1
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()
