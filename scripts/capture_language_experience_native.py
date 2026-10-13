"""Native Windows language evidence, isolated inputs, no API/import/Golden writes."""
from __future__ import annotations
import os
os.environ['QT_QPA_PLATFORM'] = 'windows'
import hashlib
import json
import tempfile
from pathlib import Path
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from capture_user_guide_native import FakeCredentialStore, _find, _click, _delegate_with_runtime
from capture_beginner_ui_polish_native import click_item
from src.qml_bootstrap import build_qml_runtime
from src.models.app_config import AppConfig

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'tests/screenshots/qa-current/language-experience'


def main():
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows'
    app.setFont(QFont('Microsoft YaHei UI', 9))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for locale in ('zh-HK', 'zh-CN', 'en-US'):
        for width, height in ((1000, 700), (900, 640)):
            with tempfile.TemporaryDirectory(prefix='xuxia-language-native-') as temp:
                directory = Path(temp)
                source = directory/'synthetic.txt'
                source.write_text('Local synthetic content. Never imported.', encoding='utf-8')
                rt = build_qml_runtime(live_config=AppConfig(language=locale),
                    config_file=directory/'settings.json', credential_store=FakeCredentialStore(),
                    connection_test_service=lambda *_: None, usage_recorder=None)
                try:
                    root = rt.root
                    root.resize(QSize(width, height)); root.show()
                    assert QTest.qWaitForWindowExposed(root, 5000)
                    def capture(name):
                        QTest.qWait(160)
                        rt.assert_zero_warnings()
                        picture = root.grabWindow()
                        path = OUTPUT/f'{name}-{locale}-{width}.png'
                        assert not picture.isNull() and picture.save(str(path))
                        records.append(dict(filename=path.name, locale=locale, width=picture.width(),
                            height=picture.height(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            warnings=list(rt.warnings)))
                    page = _find(root, 'pageRouter').property('currentItem')
                    page.requestImport('files', [source.as_uri()])
                    assert rt.batch_controller.totalCount == 0
                    capture('naming-prompt')
                    _click(root, 'namingLanguageChoice')
                    capture('naming-options')
                    QTest.keyClick(root, Qt.Key_Home)
                    QTest.keyClick(root, Qt.Key_Down)
                    QTest.keyClick(root, Qt.Key_Down)
                    QTest.keyClick(root, Qt.Key_Return)
                    choice = _find(root, 'namingLanguageChoice')
                    assert choice.property('currentValue') == 'zh-HK', (
                        locale, width, root.isActive(), choice.property('currentIndex'),
                        choice.property('currentText'), choice.property('activeFocus'))
                    _click(root, 'namingLanguageCancel')
                    assert rt.batch_controller.totalCount == 0 and rt.batch_controller.namingLanguage == ''
                    _click(root, 'nav_preferences')
                    capture('settings')
                    _click(root, 'languageCombo')
                    capture('interface-options')
                    QTest.keyClick(root, Qt.Key_Escape)
                    _click(root, 'nav_templates')
                    capture('templates')
                    second = _delegate_with_runtime(rt, 'templateList', 1)
                    click_item(root, _find(second, 'editTemplateButton'))
                    capture('template-editor')
                    _click(root, 'templateOutputLanguage')
                    capture('template-output-options')
                    QTest.keyClick(root, Qt.Key_End)
                    QTest.keyClick(root, Qt.Key_Return)
                    assert rt.template_controller.draftOptions['outputLanguage'] == 'zh-HK'
                    capture('template-output-hk')
                    rt.template_controller.cancelDraft()
                    assert source.read_text(encoding='utf-8') == 'Local synthetic content. Never imported.'
                    assert not (directory/'settings.json').exists()
                    rt.assert_zero_warnings()
                finally:
                    rt.cleanup(); QTest.qWait(80)
    (OUTPUT/'native-manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'captures':len(records), 'platform':'windows','warnings':0,'imports':0}))


if __name__ == '__main__':
    main()
