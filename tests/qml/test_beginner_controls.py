"""Shared controls retain real input behavior while exposing readable geometry."""
from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtQuick import QQuickWindow, QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlExpression
from tests.qml.conftest import make_handle

QML = Path(__file__).parents[2] / 'src/ui_qml'


def create(name):
    path = QML / name
    assert path.is_file(), f'Shared control {name} has not been implemented'
    handle = make_handle(path, 220, 32)
    window = QQuickWindow()
    window.resize(400, 300)
    handle.root.setParentItem(window.contentItem())
    handle.root.setX(10)
    handle.root.setY(10)
    window.show()
    QTest.qWait(50)
    return handle, window


def value(handle, expression):
    expr = QQmlExpression(handle.engine.rootContext(), handle.root, expression)
    result, _ = expr.evaluate()
    assert not expr.hasError(), expr.error().toString()
    return result


def test_button_mouse_keyboard_and_disabled_behavior():
    handle, window = create('AppButton.qml')
    try:
        button = handle.root
        button.setProperty('text', '保存设置')
        events = []
        button.clicked.connect(lambda: events.append('clicked'))
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
        assert len(events) == 1
        button.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Space)
        assert len(events) == 2
        button.setProperty('enabled', False)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
        QTest.keyClick(window, Qt.Key_Space)
        assert len(events) == 2
        assert value(handle, 'background.radius') == 6
        assert value(handle, 'background.border.width') >= 1
        handle.assert_zero_warnings()
    finally:
        window.close()
        handle.cleanup()


def test_select_popup_keyboard_and_label_value_mapping():
    handle, window = create('AppComboBox.qml')
    try:
        control = handle.root
        control.setProperty('textRole', 'label')
        control.setProperty('valueRole', 'value')
        control.setProperty('model', [{'label': '中文', 'value': 'zh'}, {'label': '英文', 'value': 'en'}])
        QTest.qWait(30)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(100, 25))
        QTest.qWait(30)
        assert value(handle, 'popup.visible')
        QTest.keyClick(window, Qt.Key_Home)
        QTest.keyClick(window, Qt.Key_Down)
        QTest.keyClick(window, Qt.Key_Return)
        assert control.property('currentValue') == 'en'
        assert control.property('currentText') == '英文'
        assert not value(handle, 'popup.visible')
        indicator = control.findChild(QQuickItem, 'selectChevron')
        assert indicator is not None and indicator.width() == 16
        assert value(handle, 'background.border.width') >= 1
        handle.assert_zero_warnings()
    finally:
        window.close()
        handle.cleanup()


def test_select_long_label_stays_inside_narrow_control():
    handle, window = create('AppComboBox.qml')
    try:
        handle.root.setWidth(140)
        handle.root.setProperty('model', ['这是一个长度超过控件宽度的命名模板名称'])
        QTest.qWait(30)
        assert value(handle, 'contentItem.width') <= 140 - 28
        assert value(handle, 'contentItem.elide') == Qt.TextElideMode.ElideRight.value
        handle.assert_zero_warnings()
    finally:
        window.close()
        handle.cleanup()
