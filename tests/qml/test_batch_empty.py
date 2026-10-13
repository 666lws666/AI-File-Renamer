"""Gate B: Batch empty state tests."""
from .conftest import make_handle, QML_DIR
from .fixtures import make_empty_controller

def test_empty_state_renders():
    ctrl = make_empty_controller()
    h = make_handle(QML_DIR / "main.qml", ctrl=ctrl)
    try:
        assert h.root is not None
        h.assert_zero_warnings()
        # DropZone should render when count is 0
    finally: h.cleanup()

def test_empty_state_toolbar():
    ctrl = make_empty_controller()
    h = make_handle(QML_DIR / "main.qml", ctrl=ctrl)
    try:
        assert ctrl.totalCount == 0
        assert ctrl.visibleCount == 0
    finally: h.cleanup()
