"""Test TaskCard component behavior."""
import pytest
from .conftest import make_handle, QML_DIR

def test_eight_states_render():
    """All 8 states from MockTaskListModel appear in the ListView."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        h.assert_zero_warnings()
        m = h.controller.tasksModel
        statuses = set()
        for i in range(m.rowCount()):
            statuses.add(m.data(m.index(i,0), m.statusRole))
        assert len(statuses) == 8, f"Expected 8 states, got {len(statuses)}: {statuses}"
    finally: h.cleanup()

def test_selection_toggle():
    """Checkbox toggles selected state."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        assert ctrl.selectedCount == 0
        ctrl.toggleTaskSelected(ctrl.tasksModel.data(ctrl.tasksModel.index(0,0), ctrl.tasksModel.taskIdRole))
        assert ctrl.selectedCount == 1
    finally: h.cleanup()

def test_ignore_action():
    """Ignore changes task status."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        tid = ctrl.tasksModel.data(ctrl.tasksModel.index(0,0), ctrl.tasksModel.taskIdRole)
        ctrl.ignoreTask(tid)
        new_status = ctrl.tasksModel.data(ctrl.tasksModel.index(0,0), ctrl.tasksModel.statusRole)
        assert new_status == "ignored"
    finally: h.cleanup()

def test_undo_action():
    """Undo changes applied→undone."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        ctrl = h.controller
        # Find an applied task
        for i in range(ctrl.tasksModel.rowCount()):
            s = ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.statusRole)
            if s == "applied":
                tid = ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.taskIdRole)
                ctrl.undoTask(tid)
                ns = ctrl.tasksModel.data(ctrl.tasksModel.index(i,0), ctrl.tasksModel.statusRole)
                assert ns == "undone", f"Undo failed: {s}→{ns}"
                return
        pytest.skip("No applied task in fixture")
    finally: h.cleanup()

def test_actions_per_status():
    """Each status has correct canApply/canRetry/canIgnore/canUndo flags."""
    h = make_handle(QML_DIR / "main.qml")
    try:
        m = h.controller.tasksModel
        for i in range(m.rowCount()):
            s = m.data(m.index(i,0), m.statusRole)
            canApply = m.data(m.index(i,0), m.canApplyRole)
            canRetry = m.data(m.index(i,0), m.canRetryRole)
            if s == "review_pending": assert canApply and canRetry, f"review_pending: apply={canApply} retry={canRetry}"
            if s == "applied": assert m.data(m.index(i,0), m.canUndoRole), f"applied should be undoable"
            if s == "failed": assert canRetry, f"failed should be retryable"
    finally: h.cleanup()
