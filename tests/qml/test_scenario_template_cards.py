"""Preset purposes/examples must be visible without a hover."""
import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from tests.qml.test_templates import _controller, QML
from tests.qml.conftest import make_handle


@pytest.mark.parametrize('width,height', [(1000, 668), (900, 608)])
def test_cards_explain_scenarios_and_list_scrolls(tmp_path, width, height):
    controller = _controller(tmp_path)
    handle = make_handle(QML / 'TemplatesPage.qml', width, height, controller)
    try:
        listing = handle.root.findChild(QQuickItem, 'templateList')
        row, _ = QQmlExpression(handle.engine.rootContext(), listing, 'itemAtIndex(0)').evaluate()
        purpose = row.findChild(QQuickItem, 'templateDescription')
        example = row.findChild(QQuickItem, 'templateExample')
        assert purpose is not None and purpose.property('visible')
        assert example is not None and example.property('visible')
        assert example.property('text').endswith('.pdf')
        assert purpose.property('contentWidth') <= purpose.width() + 1
        assert example.property('contentWidth') <= example.width() + 1
        assert listing.property('contentHeight') > listing.height()
        assert listing.findChild(QQuickItem, 'templateListScrollBar') is not None
        QQmlExpression(handle.engine.rootContext(), listing, 'positionViewAtEnd()').evaluate()
        QTest.qWait(100)
        last, _ = QQmlExpression(handle.engine.rootContext(), listing, 'itemAtIndex(8)').evaluate()
        assert last is not None
        assert last.findChild(QQuickItem, 'templateExample').property('text').endswith('V2.docx')
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
