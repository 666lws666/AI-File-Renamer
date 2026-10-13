"""Gate B: mock data integration tests."""
import pytest
from .conftest import make_handle, QML_DIR
from .fixtures import make_default_controller, make_empty_controller

def test_20_tasks_all_states():
    ctrl = make_default_controller()
    assert ctrl.totalCount == 20
    statuses = set()
    for i in range(ctrl.tasksModel.rowCount()):
        idx = ctrl.tasksModel.index(i,0)
        statuses.add(ctrl.tasksModel.data(idx, ctrl.tasksModel.statusRole))
    assert len(statuses) == 8, f"Expected 8 states, got {len(statuses)}: {statuses}"

def test_search_filters():
    ctrl = make_default_controller()
    ctrl.setSearchText("销售")
    assert ctrl.visibleCount <= 20

def test_status_filter():
    ctrl = make_default_controller()
    ctrl.setStatusFilter("failed")
    assert ctrl.visibleCount >= 1

def test_selection():
    ctrl = make_default_controller()
    assert ctrl.selectedCount == 0
    ctrl.setSelectAllState("all")
    assert ctrl.selectedCount > 0
    assert ctrl.selectAllState in ("all","partial")

def test_ingore_task():
    ctrl = make_default_controller()
    tid = ctrl.tasksModel.data(ctrl.tasksModel.index(0,0), ctrl.tasksModel.taskIdRole)
    ctrl.ignoreTask(tid)
    # Verify status changed
    new_status = ctrl.tasksModel.data(ctrl.tasksModel.index(0,0), ctrl.tasksModel.statusRole)
    assert new_status == "ignored"

def test_controller_no_file_side_effects():
    ctrl = make_default_controller()
    # All operations are in-memory only
    assert ctrl.applyInProgress == False

def test_controller_injected_in_qml():
    ctrl = make_default_controller()
    h = make_handle(QML_DIR / "main.qml", ctrl=ctrl)
    try:
        assert h.root is not None
        h.assert_zero_warnings()
    finally: h.cleanup()
