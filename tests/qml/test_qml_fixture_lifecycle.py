"""Native teardown regressions: queued deletion is not actual destruction."""

import weakref
from threading import get_ident

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from src.controllers.mock_batch_controller import MockBatchController
from .conftest import QML_DIR, QmlTestHandle


@pytest.fixture
def lifecycle_handle(request):
    controller = MockBatchController() if request.param == "hosted" else None
    handle = QmlTestHandle(QML_DIR / "TaskCard.qml", controller=controller)
    objects = (handle.root, handle._host_view, handle.component, handle.engine)
    try:
        yield handle, objects, controller
    finally:
        # Run only AFTER the behavior assertions, including on the old fixture.
        # Keep the original wrappers so a broken cleanup cannot abandon natives.
        root, view, component, engine = objects
        if isValid(root):
            root.deleteLater()
            QCoreApplication.sendPostedEvents(root, QEvent.DeferredDelete)
        if component is not None and isValid(component):
            component.deleteLater()
            QCoreApplication.sendPostedEvents(component, QEvent.DeferredDelete)
        owner = view if view is not None else engine
        if isValid(owner):
            if view is not None:
                view.close()
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(owner, QEvent.DeferredDelete)
        QApplication.processEvents()


@pytest.mark.parametrize("lifecycle_handle", ["hosted", "standalone"], indirect=True)
def test_cleanup_really_destroys_native_objects_and_is_idempotent(lifecycle_handle):
    handle, objects, controller = lifecycle_handle
    handle.assert_zero_warnings()
    context_refs = [weakref.ref(handle.i18n), weakref.ref(handle._design_tokens),
                    weakref.ref(handle.controller)]
    contexts_at_destruction = []
    objects[0].destroyed.connect(lambda: contexts_at_destruction.append(
        all(ref() is not None and isValid(ref()) for ref in context_refs)
    ))

    handle.cleanup()
    assert not any(obj is not None and isValid(obj) for obj in objects), (
        "cleanup returned with live native root/view/component/engine"
    )
    assert contexts_at_destruction == [True], "context holders died before the QML root"
    handle.cleanup()
    handle.assert_zero_warnings()
    if controller is not None:
        assert isValid(controller), "cleanup deleted the caller-owned controller"
        model = controller.tasksModel
        task_id = model.data(model.index(0, 0), model.taskIdRole)
        assert controller.selectedCount == 0
        controller.toggleTaskSelected(task_id)
        assert controller.selectedCount == 1


@pytest.mark.parametrize("lifecycle_handle", ["hosted", "standalone"], indirect=True)
def test_cleanup_does_not_generate_null_context_warnings(lifecycle_handle):
    handle, _, controller = lifecycle_handle
    handle.assert_zero_warnings()
    handle.cleanup()
    handle.assert_zero_warnings()
    # Keep a borrowed controller alive through the assertion, like real callers.
    if controller is not None:
        assert isValid(controller)


@pytest.mark.parametrize("lifecycle_handle", ["hosted", "standalone"], indirect=True)
def test_cleanup_uses_native_owner_not_current_thread_wrapper(lifecycle_handle, monkeypatch):
    handle, objects, _ = lifecycle_handle
    creator_ident = get_ident()
    assert handle.engine.thread().isCurrentThread()
    other_wrapper = QThread()
    assert isValid(other_wrapper) and not other_wrapper.isCurrentThread()
    # Only the Python adapter's return value changes; the live engine still
    # belongs to this actual executing thread. Wrapper identity is not authority.
    with monkeypatch.context() as patch:
        patch.setattr(QThread, "currentThread", lambda: other_wrapper)
        assert get_ident() == creator_ident
        assert handle.engine.thread().isCurrentThread()
        handle.cleanup()
    assert not any(obj is not None and isValid(obj) for obj in objects)
    handle.cleanup()
    handle.assert_zero_warnings()


@pytest.mark.parametrize("lifecycle_handle", ["hosted", "standalone"], indirect=True)
def test_cleanup_rejects_real_worker_before_mutating(lifecycle_handle):
    handle, objects, _ = lifecycle_handle
    creator_ident = get_ident()
    contexts = (handle.i18n, handle._design_tokens, handle.controller)
    outcomes = []

    class CleanupWorker(QThread):
        def run(self):
            outcomes.append(get_ident() != creator_ident)
            try:
                handle.cleanup()
            except RuntimeError as error:
                outcomes.append(str(error))

    worker = CleanupWorker()
    worker.start()
    worker.wait()
    assert outcomes == [True, "QML fixture cleanup must run on its owner thread"]
    assert (handle.i18n, handle._design_tokens, handle.controller) == contexts
    assert all(isValid(obj) for obj in contexts)
    assert all(obj is None or isValid(obj) for obj in objects)
    handle.assert_zero_warnings()
    handle.cleanup()
    assert not any(obj is not None and isValid(obj) for obj in objects)
    handle.cleanup()
    handle.assert_zero_warnings()


def test_cleanup_keeps_warning_collection_until_root_destruction(tmp_path):
    qml_path = tmp_path / "DestructionWarning.qml"
    qml_path.write_text(
        'import QtQuick\nItem { Component.onDestruction: { '
        'let missing = null; missing.teardown_capture_sentinel } }\n', encoding="utf-8"
    )
    handle = QmlTestHandle(qml_path)
    root, component, engine = handle.root, handle.component, handle.engine
    try:
        handle.assert_zero_warnings()
        handle.cleanup()
        assert any("teardown_capture_sentinel" in msg for msg in handle.warnings)
    finally:
        for obj in (root, component, engine):
            if isValid(obj):
                obj.deleteLater()
                QCoreApplication.sendPostedEvents(obj, QEvent.DeferredDelete)
        QApplication.processEvents()
