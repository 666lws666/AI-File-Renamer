"""Observable first-run guidance and capped, scrollable watch form."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from tests.qml.conftest import make_handle
from tests.qml.test_watch import QML, _controller, _find, _mouse_click


def test_watch_browse_and_mode_consequence_are_explicit(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.beginCreate()
    h = make_handle(QML / 'WatchPage.qml', 952, 668, ctrl)
    try:
        assert _find(h, 'watchSourceBrowseButton').property('text') == '选择文件夹'
        assert _find(h, 'watchTargetBrowseButton').property('text') == '选择文件夹'
        hint = _find(h, 'watchModeHint')
        assert hint is not None and '确认' in hint.property('text')
        _mouse_click(h, _find(h, 'watchAutoApplySwitch'))
        assert ctrl.draftMode == 'auto_apply'
        assert '自动重命名并移动' in hint.property('text')
        assert '无需逐个确认' in hint.property('text')
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_watch_height_follows_content_and_caps_at_small_window(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.beginCreate()
    h = make_handle(QML / 'WatchPage.qml', 852, 608, ctrl)
    try:
        form = _find(h, 'watchForm')
        assert form.implicitHeight() > 300
        assert form.height() <= form.implicitHeight() + 1
        assert form.height() <= form.parentItem().height() + 1
        scroll = _find(h, 'watchFormScroll')
        scroll.setProperty('contentY', max(0, scroll.property('contentHeight') - scroll.height()))
        QTest.qWait(50)
        button = _find(h, 'watchFormCancelButton')
        assert button.mapToScene(QPointF(0, button.height())).y() <= h.root.height()
        _mouse_click(h, button)
        assert not ctrl.formOpen
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_batch_guidance_and_real_add_actions(tmp_path):
    from src.controllers.mock_batch_controller import MockBatchController
    ctrl = MockBatchController()
    h = make_handle(QML / 'DropZone.qml', 800, 480, ctrl)
    try:
        steps = _find(h, 'batchFirstRunSteps')
        assert steps is not None
        assert steps.property('text') == '1 添加文件  →  2 查看建议  →  3 应用更改'
        formats = _find(h, 'formatsText').property('text')
        assert all(ext in formats for ext in ('PDF', 'JPG', 'MP4'))
        actions = []
        h.root.addFilesClicked.connect(lambda: actions.append('files'))
        h.root.addFolderClicked.connect(lambda: actions.append('folder'))
        _mouse_click(h, _find(h, 'dropZoneAddFilesButton'))
        _mouse_click(h, _find(h, 'dropZoneAddFolderButton'))
        assert actions == ['files', 'folder']
        h.assert_zero_warnings()
    finally:
        h.cleanup()
