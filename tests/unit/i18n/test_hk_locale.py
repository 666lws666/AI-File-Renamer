import json
import re
from pathlib import Path
import pytest
from src.utils.i18n import I18n


@pytest.mark.parametrize('alias', ['zh-HK', 'zh_HK'])
def test_hk_alias_and_catalog(alias):
    service = I18n()
    service.set_locale(alias)
    assert service.locale == 'zh-HK'
    assert 'zh-HK' in service.available_locales
    assert service.tr('nav.preferences') == '設定'
    assert service.tr('watch.form.browse') == '選擇資料夾'


def test_hk_keys_and_placeholders_match_complete_source():
    directory = Path(__file__).parents[3] / 'src/utils/i18n/locales'
    zh = json.loads((directory / 'zh_CN.json').read_text(encoding='utf-8'))
    hk = json.loads((directory / 'zh_HK.json').read_text(encoding='utf-8'))
    en = json.loads((directory / 'en_US.json').read_text(encoding='utf-8'))
    assert hk.keys() == zh.keys() == en.keys()
    for key, value in zh.items():
        assert isinstance(hk[key], str) and hk[key]
        assert sorted(re.findall(r'\{[^{}]+\}', hk[key])) == sorted(re.findall(r'\{[^{}]+\}', value)), key
