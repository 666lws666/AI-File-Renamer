"""M1 i18n fallback tests — QML-safe API."""
import pytest
def test_missing_falls_to_en(): from src.utils.i18n.service import I18n; i=I18n(); assert len(i.tr("nonexistent.zzz"))>0
def test_planned_falls_to_en(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("ja-JP"); assert i.locale=="en-US"
def test_unknown_falls_to_en(): from src.utils.i18n.service import I18n; i=I18n(); i.setLocale("xx-XX"); assert i.locale=="en-US"
def test_pseudo_expansion(): from src.utils.i18n.service import I18n; i=I18n(); r=i._translate("test.key","en-XA"); assert len(r)>=len(i._translate("test.key","en-US"))
