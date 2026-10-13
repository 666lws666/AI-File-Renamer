"""Isolated Windows review of approved beginner controls; no golden writes."""
from __future__ import annotations
import hashlib
import json
import tempfile
import argparse
from pathlib import Path
from capture_user_guide_native import FakeCredentialStore, _find, _click, _delegate_with_runtime
from src.qml_bootstrap import build_qml_runtime
from src.models.app_config import AppConfig
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'tests/screenshots/qa-current/beginner-ui-polish'
SUFFIX = ""


def click_item(window, item):
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    assert item.isVisible() and 0 < point.y() < window.height()
    QTest.mouseMove(window, point)
    QTest.qWait(80)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(120)


def capture(runtime, name):
    QTest.qWait(160)
    runtime.assert_zero_warnings()
    picture = runtime.root.grabWindow()
    path = OUTPUT / (name + SUFFIX + '.png')
    assert not picture.isNull() and picture.save(str(path))
    return dict(filename=path.name, width=picture.width(), height=picture.height(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), warnings=list(runtime.warnings))


def main():
    global SUFFIX
    parser = argparse.ArgumentParser()
    parser.add_argument('--locale', choices=('zh-CN', 'en-US'), default='zh-CN')
    args = parser.parse_args()
    SUFFIX = '-en' if args.locale == 'en-US' else ''
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows'
    app.setFont(QFont('Microsoft YaHei UI', 9))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for width, height in ((1000, 700), (900, 640)):
        with tempfile.TemporaryDirectory(prefix='xuxia-beginner-ui-') as temp:
            rt = build_qml_runtime(
                live_config=AppConfig(language=args.locale),
                config_file=Path(temp) / "settings.json",
                credential_store=FakeCredentialStore(),
                connection_test_service=lambda *_: None,
                usage_recorder=None,
            )
            try:
                root = rt.root
                root.resize(QSize(width, height))
                root.show()
                assert QTest.qWaitForWindowExposed(root, 5000)
                assert _find(root, 'batchTemplateSelector').property('currentText') == rt.template_controller.templates[0]['name']
                records.append(capture(rt, f'batch-{width}'))
                _click(root, 'batchTemplateSelector')
                records.append(capture(rt, f'batch-template-popup-{width}'))
                QTest.keyClick(root, Qt.Key_Escape)
                _click(root, 'nav_templates')
                listing = _find(root, 'templateList')
                assert listing.property('count') == 9
                records.append(capture(rt, f'templates-{width}'))
                second = _delegate_with_runtime(rt, 'templateList', 1)
                click_item(root, _find(second, 'editTemplateButton'))
                assert _find(root, 'templateEditor').property('visible')
                records.append(capture(rt, f'editor-{width}'))
                rt.template_controller.cancelDraft()
                _click(root, 'vocabularyTabButton')
                records.append(capture(rt, f'vocabulary-{width}'))
                _click(root, 'nav_preferences')
                selector = _find(root, 'defaultTemplateField')
                assert selector.property('count') == 10
                records.append(capture(rt, f'settings-{width}'))
                click_item(root, selector)
                records.append(capture(rt, f'default-template-popup-{width}'))
                QTest.keyClick(root, Qt.Key_Home)
                QTest.keyClick(root, Qt.Key_Down)
                QTest.keyClick(root, Qt.Key_Return)
                assert rt.controller.defaultTemplateId != ''
                rt.controller.cancel()
                _click(root, 'nav_watch')
                _click(root, 'addWatchButton')
                form = _find(root, 'watchForm')
                assert form.isVisible()
                records.append(capture(rt, f'watch-review-{width}'))
                _click(root, 'watchAutoApplySwitch')
                expected_mode = 'Automatically rename and move' if SUFFIX else '自动重命名并移动'
                assert expected_mode in _find(root, 'watchModeHint').property('text')
                records.append(capture(rt, f'watch-auto-{width}'))
                scroll = _find(root, 'watchFormScroll')
                point = scroll.mapToScene(QPointF(scroll.width()/2, scroll.height()/2))
                for _ in range(12):
                    if scroll.property('atYEnd'): break
                    QTest.wheelEvent(root, point, QPoint(0, -120))
                    QTest.qWait(60)
                QTest.wheelEvent(root, point, QPoint(), phase=Qt.ScrollEnd)
                QTest.qWait(700)
                assert scroll.property('atYEnd')
                records.append(capture(rt, f'watch-scrolled-{width}'))
                _click(root, 'watchFormCancelButton')
                assert not form.isVisible()
                rt.assert_zero_warnings()
            finally:
                rt.cleanup()
                QTest.qWait(80)
    (OUTPUT / ('manifest' + SUFFIX + '.json')).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(platform=app.platformName(), captures=len(records), warnings=0)))


if __name__ == '__main__':
    main()
