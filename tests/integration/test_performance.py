"""M8 bounded performance and lifetime regression tests."""

import gc
import os
import time
import tracemalloc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from src.controllers.batch_workspace_controller import BatchWorkspaceController


# Integration tests do not inherit tests/qml/conftest.py's autouse fixture.
# Hold the application for the whole module so a standalone virtualization
# test cannot construct a QQuickView before a QApplication exists.
_QT_APP = QApplication.instance() or QApplication([])


def _make_files(tmp_path, count):
    paths = []
    for index in range(count):
        path = tmp_path / f"document-{index:04d}.txt"
        path.write_text(f"payload-{index}", encoding="utf-8")
        paths.append(str(path))
    return paths


def test_scan_1000_files_under_5s(tmp_path):
    paths = _make_files(tmp_path, 1000)
    controller = BatchWorkspaceController(background=False)

    started = time.perf_counter()
    controller.add_files(paths)
    elapsed = time.perf_counter() - started

    assert controller.totalCount == 1000
    assert elapsed < 5.0, f"1000-file import took {elapsed:.3f}s"


def test_batch_card_virtualization_1000_items(tmp_path):
    from PySide6.QtQml import QQmlExpression
    from tests.qml.conftest import QML_DIR, make_handle

    controller = BatchWorkspaceController(background=False)
    controller.add_files(_make_files(tmp_path, 1000))
    handle = make_handle(QML_DIR / "BatchPage.qml", ctrl=controller)
    try:
        queue = handle.root.findChild(QObject, "batchTaskQueue")
        assert queue is not None
        first, first_error = QQmlExpression(
            handle.engine.rootContext(), queue, "itemAtIndex(0)"
        ).evaluate()
        last, last_error = QQmlExpression(
            handle.engine.rootContext(), queue, "itemAtIndex(999)"
        ).evaluate()
        assert first_error is False and first is not None
        assert last_error is False and last is None, "ListView eagerly instantiated all 1000 cards"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_memory_no_leak_100_batches(tmp_path):
    paths = _make_files(tmp_path, 10)
    controller = BatchWorkspaceController(background=False)
    tracemalloc.start()
    try:
        gc.collect()
        baseline = tracemalloc.get_traced_memory()[0]
        for _ in range(100):
            controller.add_files(paths)
            controller.clear_workspace()
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - baseline
    finally:
        tracemalloc.stop()
        controller.close()
    assert retained < 2 * 1024 * 1024, f"retained Python memory: {retained} bytes"
