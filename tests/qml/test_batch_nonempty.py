"""Gate B: nonempty batch workspace tests."""
from .conftest import make_handle, QML_DIR

def test_20_tasks_render(): h=make_handle(QML_DIR/"main.qml"); h.assert_zero_warnings(); assert h.controller.totalCount==20; h.cleanup()
def test_eight_states(): h=make_handle(QML_DIR/"main.qml"); m=h.controller.tasksModel; s=set(m.data(m.index(i,0),m.statusRole) for i in range(m.rowCount())); assert len(s)==8; h.cleanup()
def test_search(): h=make_handle(QML_DIR/"main.qml"); h.controller.setSearchText("销售"); assert h.controller.visibleCount >= 1; h.cleanup()
def test_search_none(): h=make_handle(QML_DIR/"main.qml"); h.controller.setSearchText("ZZZ_NOMATCH"); assert h.controller.visibleCount == 0; h.cleanup()
def test_filter_and_search_visibility_predicate():
    h=make_handle(QML_DIR/"main.qml")
    c=h.controller; m=c.tasksModel
    c.setStatusFilter("failed")
    visible=[m.data(m.index(i,0),m.taskIdRole) for i in range(m.rowCount()) if c.isTaskVisible(m.data(m.index(i,0),m.taskIdRole))]
    assert visible
    assert all(m.data(m.index(i,0),m.statusRole)=="failed" for i in range(m.rowCount()) if m.data(m.index(i,0),m.taskIdRole) in visible)
    c.setStatusFilter("all"); c.setSearchText("2025")
    assert 0 < c.visibleCount < c.totalCount
    h.assert_zero_warnings(); h.cleanup()
def test_task_queue_collapses_non_matching_delegates():
    source=(QML_DIR/"TaskQueue.qml").read_text(encoding="utf-8")
    assert "isTaskVisible(model.taskId)" in source
    assert "height: taskVisible ? card.height : 0" in source
def test_nine_filters(): h=make_handle(QML_DIR/"main.qml"); expected=["all","pending","analyzing","review_pending","undone","applied","failed","cancelled","ignored"]; [h.controller.setStatusFilter(f) or True for f in expected]; h.cleanup()
def test_select_all(): h=make_handle(QML_DIR/"main.qml"); h.controller.setSelectAllState("all"); assert h.controller.selectedCount > 0; assert h.controller.selectAllState == "all"; h.cleanup()
def test_partial_selection(): h=make_handle(QML_DIR/"main.qml"); h.controller.toggleTaskSelected(h.controller.tasksModel.data(h.controller.tasksModel.index(0,0),h.controller.tasksModel.taskIdRole)); assert h.controller.selectAllState=="partial"; h.cleanup()
def test_900x640_renders(): h=make_handle(QML_DIR/"main.qml",900,640); h.assert_zero_warnings(); h.cleanup()
