"""Native TaskCard pointer interaction for additive operation locks."""
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, Slot
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from .conftest import QML_DIR, make_handle
from shiboken6 import isValid


class Spy(QObject):
    def __init__(self): super().__init__(); self.calls = []
    @Slot(str)
    def beginInlineEdit(self, tid): self.calls.append(('edit', tid))
    @Slot(str)
    def applyTask(self, tid): self.calls.append(('apply', tid))


@pytest.mark.parametrize('role', ['fileOperationPending', 'fileOperationRecoveryRequired'])
@pytest.mark.parametrize('locale', ['zh-CN', 'zh-HK', 'en-US'])
@pytest.mark.parametrize('width', [900, 1000])
def test_native_clicks_do_not_edit_or_apply_locked_row(role, locale, width):
    spy = Spy()
    handle = make_handle(QML_DIR / 'TaskCard.qml', w=width, h=120, ctrl=spy, loc=locale)
    try:
        handle.root.setProperty('taskId', 'synthetic')
        handle.root.setProperty('suggestedName', 'topic.txt')
        handle.root.setProperty('selected', True)
        handle.root.setProperty('canApply', True)
        window = handle.root.window()
        assert QTest.qWaitForWindowExposed(window)
        QApplication.processEvents()
        assert not window.grabWindow().isNull()  # Complete a real frame/layout.

        def click_point(name):
            item = handle.root.findChild(QQuickItem, name)
            assert item is not None and item.isVisible()
            assert item.width() > 0 and item.height() > 0
            point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
            assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height()
            return point

        # The same view must prove pointer dispatch before any negative click.
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, click_point('taskApplyButton'))
        QApplication.processEvents()
        assert spy.calls == [('apply', 'synthetic')]
        spy.calls.clear()
        assert handle.root.setProperty(role, True)
        QApplication.processEvents()
        assert not window.grabWindow().isNull()
        for name in ('inlineEditButton', 'taskApplyButton'):
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, click_point(name))
        QApplication.processEvents()
        assert spy.calls == []
        handle.assert_zero_warnings()
    finally:
        native_root = handle.root
        handle.cleanup()
        assert not isValid(native_root)
        handle.assert_zero_warnings()


@pytest.mark.parametrize('locale', ['zh-CN', 'zh-HK', 'en-US'])
def test_pending_running_and_recovery_messages_are_fixed_translations(locale):
    spy = Spy()
    handle = make_handle(QML_DIR / 'TaskCard.qml', w=1000, h=120, ctrl=spy, loc=locale)
    try:
        handle.root.setProperty('suggestedName', 'topic.txt')
        handle.root.setProperty('fileOperationPending', True)
        QApplication.processEvents()
        texts = [item.property('text') for item in handle.root.findChildren(QQuickItem) if item.metaObject().indexOfProperty('text') >= 0]
        assert handle.i18n.tr('fileops.status.running', locale) in texts
        handle.root.setProperty('fileOperationPending', False)
        handle.root.setProperty('fileOperationRecoveryRequired', True)
        handle.root.setProperty('errorMessage', 'fileops.error.workspaceSaveRecovery')
        QApplication.processEvents()
        error = handle.root.findChild(QQuickItem, 'taskErrorMessage')
        assert error.property('text') == handle.i18n.tr('fileops.error.workspaceSaveRecovery', locale)
        handle.assert_zero_warnings()
    finally: handle.cleanup()
