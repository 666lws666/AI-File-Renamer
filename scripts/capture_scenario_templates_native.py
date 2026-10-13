"""Local-only native template catalog review; never updates formal goldens."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from capture_user_guide_native import _runtime, _click, _find, _delegate_with_runtime
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.controllers.mock_batch_controller import MockBatchController

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'tests/screenshots/qa-current/scenario-templates'


def capture(runtime, name):
    runtime.assert_zero_warnings()
    image = runtime.root.grabWindow()
    path = OUTPUT / (name + '.png')
    assert not image.isNull() and image.save(str(path))
    return dict(filename=path.name, width=image.width(), height=image.height(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), warnings=list(runtime.warnings))


def main():
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == 'windows', app.platformName()
    app.setFont(QFont('Microsoft YaHei UI', 9))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for width, height in ((1000, 700), (900, 640)):
        with tempfile.TemporaryDirectory(prefix='xuxia-preset-review-') as temp:
            runtime = _runtime(Path(temp), batch=MockBatchController())
            try:
                root = runtime.root
                root.resize(QSize(width, height))
                root.show()
                assert QTest.qWaitForWindowExposed(root, 5000)
                _click(root, 'nav_templates')
                listing = _find(root, 'templateList')
                assert listing.property('count') == 9
                QTest.qWait(200)
                records.append(capture(runtime, f'catalog-{width}'))
                point = listing.mapToScene(QPointF(listing.width()/2, listing.height()/2))
                for _ in range(80):
                    if listing.property('atYEnd'):
                        break
                    QTest.wheelEvent(root, point, QPoint(0, -120))
                    QTest.qWait(60)
                QTest.wheelEvent(root, point, QPoint(), phase=Qt.ScrollEnd)
                QTest.qWait(1000)
                assert listing.property('atYEnd'), (listing.property('contentY'), listing.property('contentHeight'))
                assert listing.property('contentY') > 0
                last = _delegate_with_runtime(runtime, 'templateList', 8)
                example = _find(last, 'templateExample')
                assert example.property('text').endswith('V2.docx')
                edit = _find(last, 'editTemplateButton')
                position = edit.mapToScene(QPointF(edit.width()/2, edit.height()/2))
                QTest.mouseMove(root, position.toPoint())
                QTest.qWait(100)
                assert 0 < position.y() < height
                records.append(capture(runtime, f'last-card-{width}'))
                QTest.qWait(300)
                position = edit.mapToScene(QPointF(edit.width()/2, edit.height()/2))
                QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position.toPoint())
                QTest.qWait(200)
                records.append(capture(runtime, f'editor-{width}'))
                assert _find(root, 'templateEditor').property('visible'), (position.x(), position.y())
                assert _find(root, 'templateNameField').property('text') == '版本文档'
                close = next(item for item in _find(root, 'templateEditor').findChildren(QQuickItem)
                             if item.property('text') == '×' and item.metaObject().className().startswith('Button'))
                close_point = close.mapToScene(QPointF(close.width()/2, close.height()/2)).toPoint()
                QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, close_point)
                QTest.qWait(100)
                assert not _find(root, 'templateEditor').property('visible')
            finally:
                runtime.cleanup()
                QTest.qWait(80)
    (OUTPUT / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'platform': app.platformName(), 'captures': len(records), 'warnings': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
