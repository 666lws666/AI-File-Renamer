"""Shared runtime lane lifetime, including construction failures."""
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from src.controllers.managed_file_operation_lane import ManagedFileOperationLane
from src.services.file_operation_backend import FileOperationBackend
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime


class Credentials:
    def get(self, *_): return None
    def set(self, *_): return True
    def delete(self, *_): return True


class Inference:
    def __init__(self, _): pass
    def shutdown(self, **_): return SimpleNamespace(phase='CLOSED')


class Preparation:
    def close(self, _): return True


def args(tmp_path):
    return dict(live_config=AppConfig(), config_file=tmp_path / 'settings.json',
        credential_store=Credentials(), usage_recorder=None, template_controller=None,
        watch_controller=None, status_controller=None, diagnostics_service=None,
        local_inference_factory=Inference, local_preparation_factory=Preparation,
        resource_controller=None)


def test_production_installs_one_lane_before_batch_restore_and_close(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime = build_qml_runtime(**args(tmp_path))
    release = threading.Event()
    try:
        assert getattr(runtime, 'file_operation_lane', None) is not None
        assert runtime.owns_file_operation_lane
        lane = runtime.file_operation_lane
        c = runtime.batch_controller
        c.set_analyzer(lambda *_: 'topic.txt')
        source = tmp_path / 'source.txt'; source.write_text('synthetic')
        c.add_files([str(source)])
        end = time.monotonic() + 2
        while c.task_snapshot(c.task_ids[0])['status'] != 'review_pending' and time.monotonic() < end:
            QApplication.processEvents()
        entered = threading.Event()
        execute = lane._backend.execute_item
        def blocked(*values):
            entered.set(); assert release.wait(3); return execute(*values)
        monkeypatch.setattr(lane._backend, 'execute_item', blocked)
        c.applyTask(c.task_ids[0]); assert entered.wait(1)
        root = runtime.root
        assert runtime.cleanup(deadline=time.monotonic() + .01) is False
        assert runtime.root is root and runtime.file_operation_lane is lane and runtime.batch_controller is c
        release.set()
        assert runtime.cleanup(deadline=time.monotonic() + 2) is True
        assert not source.exists() and (tmp_path / 'topic.txt').exists()
        runtime.assert_zero_warnings()
    finally:
        release.set(); assert runtime.cleanup(deadline=time.monotonic() + 2)


def test_partial_construction_failure_closes_created_lane(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    lanes = []
    def factory(history_path):
        lane = ManagedFileOperationLane(FileOperationBackend(history_path))
        lanes.append(lane); return lane
    def fail(*_a, **_k): raise ValueError('synthetic construction failure')
    monkeypatch.setattr('src.controllers.batch_workspace_controller.BatchWorkspaceController', fail)
    with pytest.raises(ValueError, match='synthetic construction failure'):
        build_qml_runtime(**args(tmp_path), file_operation_lane_factory=factory)
    assert len(lanes) == 1 and lanes[0].closed


def test_borrowed_batch_never_creates_hidden_lane(tmp_path):
    app = QApplication.instance() or QApplication([])
    runtime = build_qml_runtime(**args(tmp_path), batch_controller=None,
        file_operation_lane_factory=lambda _: pytest.fail('hidden lane'))
    try:
        assert runtime.file_operation_lane is None and not runtime.owns_file_operation_lane
    finally: assert runtime.cleanup()


def test_nested_terminal_publication_prevents_runtime_disposal_until_exit(tmp_path):
    app = QApplication.instance() or QApplication([])
    runtime = build_qml_runtime(**args(tmp_path))
    c = runtime.batch_controller
    try:
        c.set_analyzer(lambda *_: 'topic.txt')
        source = tmp_path / 'source.txt'; source.write_text('synthetic')
        c.add_files([str(source)])
        end = time.monotonic() + 2
        while c.task_snapshot(c.task_ids[0])['status'] != 'review_pending' and time.monotonic() < end:
            QApplication.processEvents()
        tid = c.task_ids[0]
        results = []
        def nested():
            row = c.task_snapshot(tid)
            if row['status'] == 'applied' and not row['fileOperationPending'] and not results:
                results.append(runtime.cleanup(deadline=time.monotonic() + .001))
                assert runtime.root is not None and runtime.batch_controller is c
        from PySide6.QtCore import Qt
        c.tasksChanged.connect(nested, Qt.DirectConnection)
        c.applyTask(tid)
        end = time.monotonic() + 2
        while not results and time.monotonic() < end: QApplication.processEvents()
        assert results == [False]
        assert runtime.cleanup(deadline=time.monotonic() + 2)
        assert (tmp_path / 'topic.txt').read_text() == 'synthetic'
        runtime.assert_zero_warnings()
    finally: assert runtime.cleanup(deadline=time.monotonic() + 2)
