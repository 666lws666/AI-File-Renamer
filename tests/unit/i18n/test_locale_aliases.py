"""I18n locale-alias tests — underscore/hyphen equivalence at the boundary.

AppConfig persists ``zh_CN`` / ``en_US`` while I18n resources are keyed by
canonical ``zh-CN`` / ``en-US``.  The I18n boundary must accept both spellings
for ANY entry point (set_locale, setLocale, explicit tr locale) and keep one
canonical (hyphenated) locale internally.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module", autouse=True)
def _qt():
    app = QApplication.instance() or QApplication(sys_argv())
    yield


def sys_argv():
    import sys
    return sys.argv


def test_set_locale_underscore_alias_canonicalizes():
    from src.utils.i18n.service import I18n
    i = I18n()
    i.set_locale("zh_CN")
    assert i.locale == "zh-CN", "zh_CN must canonicalize to zh-CN"
    i.set_locale("en_US")
    assert i.locale == "en-US", "en_US must canonicalize to en-US"


def test_set_locale_slot_accepts_underscore():
    from src.utils.i18n.service import I18n
    i = I18n()
    i.setLocale("zh_CN")
    assert i.locale == "zh-CN"
    assert i.tr("test.key") == "测试文案"


def test_explicit_tr_locale_accepts_underscore():
    from src.utils.i18n.service import I18n
    i = I18n()
    assert i.tr("test.key", "zh_CN") == "测试文案"
    assert i.tr("test.key", "en_US") == "Test Content"
    # explicit alias must not change the active locale
    assert i.locale == "en-US"


def test_underscore_does_not_leak_into_available_locales():
    from src.utils.i18n.service import I18n
    i = I18n()
    locs = i.available_locales
    assert "zh_CN" not in locs and "en_US" not in locs
    assert "zh-CN" in locs and "en-US" in locs


def test_unknown_underscore_falls_back():
    from src.utils.i18n.service import I18n
    i = I18n()
    i.set_locale("ja_JP")  # planned locale, no resource
    assert i.locale == "en-US"
