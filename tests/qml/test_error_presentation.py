"""M7 four-layer error presentation contracts."""

from pathlib import Path

from PySide6.QtCore import QObject

from tests.qml.conftest import make_handle

QML_DIR = Path(__file__).parents[2] / "src" / "ui_qml"


def _find(root: QObject, name: str) -> QObject:
    obj = root.findChild(QObject, name)
    assert obj is not None, name
    return obj


def test_file_card_error_exposes_retry_action():
    h = make_handle(QML_DIR / "FileCardError.qml")
    try:
        h.root.setProperty("message", "文件被占用")
        h.root.setProperty("retryable", True)
        assert _find(h.root, "fileErrorRetry").property("visible") is True
        assert h.root.property("implicitHeight") > 0
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_batch_error_shows_partial_result_counts():
    h = make_handle(QML_DIR / "BatchError.qml")
    try:
        h.root.setProperty("successCount", 7)
        h.root.setProperty("failureCount", 2)
        assert _find(h.root, "batchErrorSummary").property("text")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_toast_and_blocking_modal_have_distinct_layers():
    toast = make_handle(QML_DIR / "AppToast.qml")
    blocking = make_handle(QML_DIR / "BlockingModal.qml")
    try:
        toast.root.setProperty("message", "网络暂不可用")
        toast.root.setProperty("visible", True)
        blocking.root.setProperty("title", "无法继续")
        blocking.root.setProperty("message", "配置损坏")
        blocking.root.setProperty("visible", True)
        assert toast.root.property("message") == "网络暂不可用"
        assert blocking.root.property("message") == "配置损坏"
        assert _find(blocking.root, "blockingCard").property("width") <= 440
        toast.assert_zero_warnings()
        blocking.assert_zero_warnings()
    finally:
        toast.cleanup()
        blocking.cleanup()
