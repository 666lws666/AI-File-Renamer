"""M1 i18n service tests — QML-safe API."""
import os, sys, pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
@pytest.fixture(scope="session", autouse=True)
def _qt(): app = QApplication.instance() or QApplication(sys.argv); yield

def test_tr_zh_cn(): from src.utils.i18n.service import I18n; i=I18n(); assert i.tr("test.key") and len(i.tr("test.key"))>0
def test_tr_en_us(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("en-US"); assert i.tr("test.key") and len(i.tr("test.key"))>0
def test_importable(): from src.utils.i18n import I18n; assert I18n
def test_available_locales(): from src.utils.i18n.service import I18n; i=I18n(); locs=i.available_locales; assert "zh-CN" in locs and "en-US" in locs
def test_planned_not_available(): from src.utils.i18n.service import I18n; i=I18n(); assert "ja-JP" not in i.available_locales
def test_locale_property(): from src.utils.i18n.service import I18n; i=I18n(); assert i.locale == "en-US"
def test_set_locale_slot(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("zh-CN"); assert i.locale=="zh-CN"
def test_fallback_missing(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("ja-JP"); assert i.locale=="en-US"
def test_fallback_en(): from src.utils.i18n.service import I18n; i=I18n(); r=i.tr("nonexistent.zzz"); assert len(r)>0
def test_python_explicit_zh(): from src.utils.i18n.service import I18n; i=I18n(); assert "测试" in i.tr("test.key","zh-CN")
def test_python_explicit_en(): from src.utils.i18n.service import I18n; i=I18n(); assert "Test" in i.tr("test.key","en-US")
def test_python_locale_kwarg(): from src.utils.i18n.service import I18n; i=I18n(); assert "World" in i.tr("test.greeting",locale="en-US",name="World")
def test_python_explicit_does_not_change_active(): from src.utils.i18n.service import I18n; i=I18n(); orig=i.locale; i.tr("test.key","zh-CN"); assert i.locale==orig
def test_python_kwargs_interpolation(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("zh-CN"); assert "World" in i.tr("test.greeting",name="World")
