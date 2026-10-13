"""M0 Task 3: locale metadata tests — RED phase."""
import os
import pytest


def test_seven_target_locales():
    """Three supported interface locales and four reserved targets."""
    from src.utils.i18n.locale_metadata import LOCALE_META
    assert len(LOCALE_META) == 7
    assert LOCALE_META["zh-HK"] == "supported"
    assert LOCALE_META["zh-CN"] == "supported"
    assert LOCALE_META["en-US"] == "supported"
    assert LOCALE_META["ja-JP"] == "planned"
    assert LOCALE_META["ko-KR"] == "planned"
    assert LOCALE_META["vi-VN"] == "planned"
    assert LOCALE_META["th-TH"] == "planned"


def test_en_us_is_fallback():
    """en-US is the designated fallback locale."""
    from src.utils.i18n.locale_metadata import FALLBACK_LOCALE
    assert FALLBACK_LOCALE == "en-US"


def test_no_empty_locale_files_for_planned():
    """Planned locales must not have empty resource files on disk."""
    locales_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "src", "utils", "i18n", "locales"
    )
    for planned in ["ja-JP", "ko-KR", "vi-VN", "th-TH"]:
        path = os.path.join(locales_dir, f"{planned.replace('-', '_')}.json")
        assert not os.path.exists(path), (
            f"Planned locale {planned} has an empty resource file at {path}. "
            f"Planned locales should only exist in metadata, not as empty JSON files."
        )
