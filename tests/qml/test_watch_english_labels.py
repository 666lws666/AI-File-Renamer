from tests.qml.test_watch import QML, _controller, _find
from tests.qml.conftest import make_handle
from PySide6.QtTest import QTest


def test_long_recursive_label_wraps_before_switch(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.beginCreate()
    h = make_handle(QML / 'WatchPage.qml', 852, 608, ctrl, 'en-US')
    try:
        QTest.qWait(50)  # finish the first Qt Quick layout/text polish pass
        label = _find(h, 'watchRecursiveLabel')
        assert label is not None
        assert label.property('paintedWidth') <= label.width() + 1
        assert label.property('lineCount') >= 2
        h.assert_zero_warnings()
    finally:
        h.cleanup()
