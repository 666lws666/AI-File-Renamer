"""Gate B: ApplyProgress behavior tests."""
from PySide6.QtCore import QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .conftest import make_handle, QML_DIR

def test_progress_off_by_default(): h=make_handle(QML_DIR/"main.qml"); assert h.controller.applyInProgress == False; assert h.controller.applyProgress == 0.0; h.cleanup()
def test_progress_50(): h=make_handle(QML_DIR/"main.qml"); h.controller.set_scenario_progress_50(); assert h.controller.applyInProgress == True; assert h.controller.applyCurrent == 5; assert h.controller.applyTotal == 10; assert h.controller.applySuccess == 4; assert h.controller.applyFailed == 1; assert 0.49 < h.controller.applyProgress < 0.51; h.cleanup()
def test_progress_stop(): h=make_handle(QML_DIR/"main.qml"); h.controller.applySelected(); assert h.controller.applyInProgress == True; h.controller.stopPending(); assert h.controller.applyInProgress == False; h.cleanup()


def test_progress_summary_and_bar_fit_inside_52px_card():
    h = make_handle(QML_DIR / "main.qml", w=900, h=640, loc="zh-CN")
    try:
        h.controller.set_scenario_progress_50()
        QTest.qWait(30)
        QApplication.processEvents()
        card = h.root.findChild(QQuickItem, "batchApplyProgress")
        summary = h.root.findChild(QQuickItem, "applyProgressSummary")
        bar = h.root.findChild(QQuickItem, "applyProgressBar")
        assert card is not None and summary is not None and bar is not None
        assert "正在应用更改" in summary.property("text")
        card_bottom = card.mapToScene(QPointF(0, card.height())).y()
        for item in (summary, bar):
            bottom = item.mapToScene(QPointF(0, item.height())).y()
            assert bottom <= card_bottom, f"{item.objectName()} clipped below progress card"
        h.assert_zero_warnings()
    finally:
        h.cleanup()
