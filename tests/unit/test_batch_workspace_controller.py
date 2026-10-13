"""M2 Task 4: BatchWorkspaceController tests."""
import os, tempfile, pytest
from src.controllers.batch_workspace_controller import BatchWorkspaceController

class FakeScanner:
    pass

@pytest.fixture
def ctrl():
    return BatchWorkspaceController(FakeScanner())

def test_add_files(ctrl, tmp_path):
    f1 = tmp_path / "a.pdf"; f1.write_text("hello"); f2 = tmp_path / "b.txt"; f2.write_text("world")
    ctrl.add_files([str(f1), str(f2)])
    assert ctrl.total_count == 2

def test_search(ctrl, tmp_path):
    f1 = tmp_path / "report.pdf"; f1.write_text("x")
    ctrl.add_files([str(f1)])
    ctrl.set_search("report")
    assert ctrl.visible_count == 1
    ctrl.set_search("zzz")
    assert ctrl.visible_count == 0

def test_filter(ctrl, tmp_path):
    f1 = tmp_path / "a.pdf"; f1.write_text("x")
    ctrl.add_files([str(f1)])
    ctrl.set_filter("pending")
    assert ctrl.visible_count == 1

def test_selection(ctrl, tmp_path):
    f1 = tmp_path / "a.pdf"; f1.write_text("x"); f2 = tmp_path / "b.txt"; f2.write_text("y")
    ctrl.add_files([str(f1), str(f2)])
    tid = ctrl._tasks[0]["task_id"]
    ctrl.toggle_selected(tid)
    assert ctrl.selected_count == 1
    ctrl.clear_selection()
    assert ctrl.selected_count == 0

def test_clear_workspace(ctrl, tmp_path):
    f1 = tmp_path / "a.pdf"; f1.write_text("x")
    ctrl.add_files([str(f1)])
    assert ctrl.total_count == 1
    ctrl.clear_workspace()
    assert ctrl.total_count == 0
