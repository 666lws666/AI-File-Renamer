"""Language UI is not delivered until new catalogs and dialog are in the EXE bundle."""
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_packaged_language_resources_match_source():
    packaged = ROOT/'dist/Xuxia/_internal'
    for relative in (
        'src/ui_qml/NamingLanguageDialog.qml',
        'src/ui_qml/BatchPage.qml',
        'src/ui_qml/GeneralSettingsCard.qml',
        'src/utils/i18n/locales/zh_CN.json',
        'src/utils/i18n/locales/en_US.json',
        'src/utils/i18n/locales/zh_HK.json',
    ):
        assert (packaged/relative).is_file(), relative
        assert (packaged/relative).read_bytes() == (ROOT/relative).read_bytes(), relative
