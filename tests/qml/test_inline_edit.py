"""InlineEdit + TaskCard integration tests."""
import pytest
from .conftest import make_handle, QML_DIR
from .fixtures import make_default_controller

def _tid(ctrl, i=0):
    return ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.taskIdRole)
def _val(ctrl, i=0):
    return ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.validationErrorRole)
def _name(ctrl, i=0):
    return ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.suggestedNameRole)
def _ext(ctrl, i=0):
    return ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.extensionRole)
def _isedit(ctrl, i=0):
    return ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.isEditingRole)

def test_inline_edit_not_visible_by_default():
    h = make_handle(QML_DIR / "main.qml")
    try:
        h.assert_zero_warnings()
        ctrl = h.controller
        assert not _isedit(ctrl), "No task should be editing by default"
    finally: h.cleanup()

def test_begin_inline_edit_sets_is_editing():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        ctrl.beginInlineEdit(_tid(ctrl))
        assert _isedit(ctrl), "Task should be in editing state"
    finally: h.cleanup()

def test_confirm_saves_new_name():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        tid = _tid(ctrl); ext = _ext(ctrl)
        ctrl.beginInlineEdit(tid)
        ctrl.confirmInlineEdit(tid, "new_name")
        new = _name(ctrl)
        assert "new_name" in new
        assert new.endswith(ext), f"Extension should be preserved: {new}"
        assert not _isedit(ctrl), "Editing should be complete after confirm"
    finally: h.cleanup()

def test_cancel_restores_original():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller; old = _name(ctrl)
        ctrl.beginInlineEdit(_tid(ctrl))
        ctrl.cancelInlineEdit(_tid(ctrl))
        assert _name(ctrl) == old
        assert not _isedit(ctrl)
    finally: h.cleanup()

def test_validation_empty_name():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        ctrl.beginInlineEdit(_tid(ctrl))
        ctrl.confirmInlineEdit(_tid(ctrl), "")
        assert _val(ctrl) != ""
        assert _isedit(ctrl), "Should stay in edit mode on validation failure"
    finally: h.cleanup()

def test_validation_illegal_chars():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        ctrl.beginInlineEdit(_tid(ctrl))
        ctrl.confirmInlineEdit(_tid(ctrl), "a<b>c")
        assert _val(ctrl) != ""
        assert _isedit(ctrl)
    finally: h.cleanup()

def test_validation_reserved_names():
    for r in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
        h = make_handle(QML_DIR / "main.qml")
        try:
            ctrl = h.controller
            ctrl.beginInlineEdit(_tid(ctrl))
            ctrl.confirmInlineEdit(_tid(ctrl), r)
            assert _val(ctrl) != "", f"Reserved {r} should fail validation"
            assert _isedit(ctrl)
        finally: h.cleanup()

def test_edit_button_triggers_begin_edit():
    """Clicking edit button calls beginInlineEdit and enters editing state."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        tid = _tid(ctrl)
        assert not _isedit(ctrl), "Should not be editing initially"
        ctrl.beginInlineEdit(tid)
        assert _isedit(ctrl), "Should enter editing state after beginInlineEdit"
    finally: h.cleanup()

def test_edit_exits_after_confirm():
    """After confirm, task exits editing state."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller; tid = _tid(ctrl)
        ctrl.beginInlineEdit(tid)
        ctrl.confirmInlineEdit(tid, "valid_name")
        assert not _isedit(ctrl), "Should exit editing after confirm"
    finally: h.cleanup()

def test_edit_exits_after_cancel():
    """After cancel, task exits editing state."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller; tid = _tid(ctrl)
        ctrl.beginInlineEdit(tid)
        ctrl.cancelInlineEdit(tid)
        assert not _isedit(ctrl), "Should exit editing after cancel"
    finally: h.cleanup()

def test_extension_preserved():
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller; e = _ext(ctrl)
        ctrl.beginInlineEdit(_tid(ctrl))
        ctrl.confirmInlineEdit(_tid(ctrl), "newname")
        assert _name(ctrl).endswith(e)
    finally: h.cleanup()
