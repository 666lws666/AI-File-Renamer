"""Approved B layout: observable labels, geometry and real input, no network."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFontMetricsF, QFontDatabase
from PySide6.QtQml import QQmlExpression, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from .conftest import make_handle, QML_DIR
from .fixtures import make_empty_controller


def find(root, name):
    item = root.findChild(QQuickItem, name)
    assert item is not None, name
    return item


def click(item):
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    QTest.mouseClick(item.window(), Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(30)


@pytest.mark.parametrize("locale", ["zh-CN", "zh-HK", "en-US"])
def test_nav_labels_are_visible_and_keyboard_activates_once(locale):
    h = make_handle(QML_DIR / "NavBar.qml", w=80, h=608, loc=locale)
    window = QQuickWindow()
    window.resize(80, 608)
    h.root.setParentItem(window.contentItem())
    window.show()
    QTest.qWait(50)
    events = []
    h.root.pageSelected.connect(events.append)
    try:
        for page in ("batch", "watch", "templates", "status", "preferences"):
            button = find(h.root, "nav_" + page)
            assert button.property("text"), "Navigation must have persistent text"
            label = find(button, "navLabel_" + page)
            assert label.isVisible() and label.property("text") == button.property("text")
            assert label.property("contentWidth") <= label.width() + 1
            click(button)
            assert events.pop() == page and not events
            button.forceActiveFocus(Qt.TabFocusReason)
            assert button.hasActiveFocus()
            for key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
                QTest.keyClick(window, key)
                assert events == [page]
                events.clear()
            h.root.setProperty("currentPage", page)
            assert button.property("checked") is True
        first = find(h.root, "nav_batch")
        first.forceActiveFocus(Qt.TabFocusReason)
        QTest.keyClick(window, Qt.Key_Tab)
        assert find(h.root, "nav_watch").hasActiveFocus()
        h.assert_zero_warnings()
    finally:
        window.close()
        h.cleanup()


@pytest.mark.parametrize("locale", ["zh-CN", "zh-HK", "en-US"])
@pytest.mark.parametrize("width", [820, 920])
def test_toolbar_two_rows_keep_readable_critical_labels(locale, width):
    ctrl = make_empty_controller()
    h = make_handle(QML_DIR / "BatchToolbar.qml", w=width, h=144, ctrl=ctrl, loc=locale)
    try:
        template = find(h.root, "batchTemplateSelector")
        assert h.root.property("implicitHeight") == 144
        search = find(h.root, "batchSearchField")
        assert search.mapToScene(QPointF()).y() >= template.mapToScene(QPointF(0, template.height())).y()
        for name in ("batchTemplateLabel", "batchSearchLabel", "batchStatusLabel", "batchTargetLabel"):
            assert find(h.root, name).property("text")
        for name in ("batchApplySelectedButton", "batchStopButton", "batchClearButton",
                     "batchAddFilesButton", "batchAddFolderButton", "batchTargetDirectoryButton"):
            button = find(h.root, name)
            assert button.isVisible() and button.property("text")
            assert button.property("font").pixelSize() >= 12
            needed = QFontMetricsF(button.property("font")).horizontalAdvance(button.property("text"))
            assert needed + button.property("leftPadding") + button.property("rightPadding") <= button.width() + 1
            pos = button.mapToScene(QPointF())
            assert pos.x() >= 0 and pos.x() + button.width() <= width + 1
            assert pos.y() + button.height() <= h.root.height() - 12 + 1
            assert pos.y() >= 0 and pos.y() + button.height() <= h.root.height() + 1
        actions = []
        h.root.addFilesRequested.connect(lambda: actions.append("files"))
        h.root.addFolderRequested.connect(lambda: actions.append("folder"))
        h.root.targetDirectoryRequested.connect(lambda: actions.append("target"))
        for name in ("batchAddFilesButton", "batchAddFolderButton", "batchTargetDirectoryButton"):
            click(find(h.root, name))
        assert actions == ["files", "folder", "target"]
        assert not find(h.root, "batchApplySelectedButton").property("enabled")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_target_path_disclosure_is_keyboard_operable_and_read_only():
    ctrl = make_empty_controller()
    h = make_handle(QML_DIR / "BatchToolbar.qml", w=820, h=144, ctrl=ctrl)
    try:
        target = find(h.root, "batchTargetSummary")
        assert "原目录" in target.property("text")
        assert not target.property("enabled")
        path = "D:/报告/<b>原样文本</b>/" + "很长的目录/" * 20
        ctrl.setTargetDirectory(path)
        QTest.qWait(30)
        assert path in target.property("text")
        combo = find(h.root, "batchTemplateSelector")
        content = combo.property("contentItem")
        available = content.width() - content.property("leftPadding") - content.property("rightPadding")
        assert QFontMetricsF(combo.property("font")).horizontalAdvance(combo.property("currentText")) <= available
        target.forceActiveFocus(Qt.TabFocusReason)
        QTest.keyClick(target.window(), Qt.Key_Space)
        QTest.qWait(30)
        assert h.root.property("targetDetailsVisible") is True
        text = find(h.root, "batchTargetFullPath")
        assert text.property("text") == path
        assert text.property("readOnly") is True
        expression = QQmlExpression(QQmlEngine.contextForObject(text), text,
                                   "textFormat === TextEdit.PlainText")
        assert expression.evaluate()[0] is True
        QTest.keyClick(target.window(), Qt.Key_Escape)
        QTest.qWait(30)
        assert h.root.property("targetDetailsVisible") is False
        assert ctrl.targetDirectory == path
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_toolbar_counts_distinguish_selected_visible_and_total():
    from src.controllers.mock_batch_controller import MockBatchController
    ctrl = MockBatchController()
    h = make_handle(QML_DIR / "BatchToolbar.qml", w=920, h=124, ctrl=ctrl)
    try:
        ctrl.setSelectAllState("all")
        ctrl.setStatusFilter("pending")
        QTest.qWait(30)
        selected = find(h.root, "batchSelectedCount").property("text")
        shown = find(h.root, "batchVisibleCount").property("text")
        assert selected == f"已选 {ctrl.selectedCount}"
        assert shown == f"显示 {ctrl.visibleCount}/{ctrl.totalCount}"
        assert ctrl.visibleCount < ctrl.totalCount
        h.assert_zero_warnings()
    finally:
        h.cleanup()
@pytest.fixture(autouse=True)
def native_font(_qt_app):
    """Use actual Windows glyph metrics when offscreen has no font database."""
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    assert font_id >= 0, "Native Windows font required for these geometry tests"
    yield
    QFontDatabase.removeApplicationFont(font_id)


def test_english_provider_name_survives_narrower_navigation(tmp_path):
    from .test_provider_settings import _make_ctrl
    ctrl = _make_ctrl(tmp_path)
    h = make_handle(QML_DIR / "ProviderSettingsCard.qml", w=772, h=800, ctrl=ctrl, loc="en-US")
    try:
        repeater = find(h.root, "providerListRepeater")
        row, undefined = QQmlExpression(h.engine.rootContext(), repeater, "itemAt(1)").evaluate()
        assert not undefined and row is not None
        def descendants(item):
            for child in item.childItems():
                yield child
                yield from descendants(child)
        name = ctrl.providerProfiles[1]["displayName"]
        labels = [item for item in descendants(row) if item.property("text") == name]
        assert len(labels) == 1
        needed = QFontMetricsF(labels[0].property("font")).horizontalAdvance(name)
        assert labels[0].width() >= needed > 0
        h.assert_zero_warnings()
    finally:
        h.cleanup()
