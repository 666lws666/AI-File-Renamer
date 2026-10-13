"""M8 production Batch composition and real QML action wiring."""

from PySide6.QtCore import QObject, QPointF, Qt, Slot
import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.core.batch_analysis import BatchAnalysisService
from src.controllers.auto_apply_handler import AutoApplyHandler
from src.controllers.review_first_handler import ReviewFirstHandler
from src.core.watch_resource_guard import WatchResourceGuard
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime

from .conftest import QML_DIR, make_handle
from .fixtures import make_empty_controller


class _Credentials:
    def get(self, *_args): return None
    def set(self, *_args): return True
    def delete(self, *_args): return True


class _ActionSpy(QObject):
    def __init__(self):
        super().__init__()
        self.calls = []

    @Slot(str)
    def applyTask(self, task_id): self.calls.append(("apply", task_id))

    @Slot(str)
    def retryTask(self, task_id): self.calls.append(("retry", task_id))

    @Slot(str)
    def ignoreTask(self, task_id): self.calls.append(("ignore", task_id))

    @Slot(str)
    def cancelTask(self, task_id): self.calls.append(("cancel", task_id))

    @Slot(str)
    def undoTask(self, task_id): self.calls.append(("undo", task_id))

    @Slot(str)
    def beginInlineEdit(self, task_id): self.calls.append(("edit", task_id))


def _click(handle, name):
    item = handle.root.findChild(QQuickItem, name)
    assert item is not None and item.isVisible()
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(handle.root.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)
    QApplication.processEvents()


def test_bootstrap_uses_persistent_production_batch_controller(tmp_path):
    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=_Credentials(),
        usage_recorder=None,
        template_controller=None,
        watch_controller=None,
        status_controller=None,
        diagnostics_service=None,
    )
    try:
        assert isinstance(runtime.batch_controller, BatchWorkspaceController)
        assert runtime.batch_controller._workspace_path == tmp_path / "batch_workspace.json"
        assert runtime.batch_controller._history_path == tmp_path / "rename_history.jsonl"
        assert runtime.batch_controller._analyzer is None
        assert runtime.batch_controller._managed_analyzer is runtime.analysis_service
        assert isinstance(runtime.analysis_service, BatchAnalysisService)
        assert runtime.batch_controller._processing_authority is runtime.processing_coordinator.authority
        assert runtime.analysis_service._capture_guard == runtime.catalog_source.guard
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_batch_template_label_tracks_runtime_locale_without_mutating_store(tmp_path):
    runtime = build_qml_runtime(
        live_config=AppConfig(language="zh_CN"),
        config_file=tmp_path / "settings.json",
        credential_store=_Credentials(),
        usage_recorder=None,
        watch_controller=None,
        status_controller=None,
        diagnostics_service=None,
    )
    try:
        combo = runtime.root.findChild(QQuickItem, "batchTemplateSelector")
        assert combo is not None
        add_files = runtime.root.findChild(QQuickItem, "batchAddFilesButton")
        status = runtime.root.findChild(QQuickItem, "batchStatusFilter")
        assert add_files is not None and status is not None
        assert combo.property("currentText") == "通用命名（默认）"
        assert add_files.property("text") == "添加文件"
        assert status.property("currentText") == "全部状态"
        assert runtime.template_controller.get_template_for_analysis().name == "General Naming (Default)"

        runtime.i18n.set_locale("en-US")
        QTest.qWait(30)
        QApplication.processEvents()
        assert combo.property("currentText") == "General Naming (Default)"
        assert add_files.property("text") == "Add Files"
        assert status.property("currentText") == "All Statuses"
        toolbar = runtime.root.findChild(QQuickItem, "batchToolbar")
        assert toolbar is not None and toolbar.property("compactActions") is False

        runtime.i18n.set_locale("zh-CN")
        QTest.qWait(30)
        QApplication.processEvents()
        assert combo.property("currentText") == "通用命名（默认）"
        assert add_files.property("text") == "添加文件"
        assert status.property("currentText") == "全部状态"
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_bootstrap_c1d_watch_is_unavailable_without_executing_saved_journals(tmp_path, monkeypatch):
    # C1D interim guard, not product completion: C2 supplies managed Watch.
    from src.controllers.watch_controller import WatchController
    monkeypatch.setattr(WatchController, "__init__", lambda *_args, **_kw:
        pytest.fail("legacy Watch constructed"))
    saved = tmp_path / "watch_folders.json"
    journal = tmp_path / "watch_auto_apply.json"
    saved.write_bytes(b'synthetic saved active watch')
    journal.write_bytes(b'synthetic interrupted journal')
    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=_Credentials(),
        usage_recorder=None,
        template_controller=None,
        status_controller=None,
        diagnostics_service=None,
        watch_controller=None,
    )
    try:
        assert runtime.watch_controller is None
        assert saved.read_bytes() == b'synthetic saved active watch'
        assert journal.read_bytes() == b'synthetic interrupted journal'
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_task_card_buttons_invoke_the_visible_action(tmp_path):
    spy = _ActionSpy()
    handle = make_handle(QML_DIR / "TaskCard.qml", w=1000, h=120, ctrl=spy)
    try:
        handle.root.setProperty("taskId", "task-1")
        handle.root.setProperty("suggestedName", "建议.pdf")
        handle.root.setProperty("extension", ".pdf")
        handle.root.setProperty("selected", True)
        action_properties = {
            "taskApplyButton": "canApply", "taskRetryButton": "canRetry",
            "taskCancelButton": "canCancel", "taskUndoButton": "canUndo",
            "taskIgnoreButton": "canIgnore",
        }
        for prop in action_properties.values():
            handle.root.setProperty(prop, False)
        QTest.qWait(30)
        QApplication.processEvents()
        _click(handle, "inlineEditButton")
        handle.root.setProperty("suggestedName", "")
        for object_name, prop in action_properties.items():
            for candidate in action_properties.values():
                handle.root.setProperty(candidate, candidate == prop)
            QTest.qWait(30)
            QApplication.processEvents()
            _click(handle, object_name)
        assert spy.calls == [
            ("edit", "task-1"), ("apply", "task-1"), ("retry", "task-1"),
            ("cancel", "task-1"), ("undo", "task-1"), ("ignore", "task-1"),
        ]
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_batch_toolbar_uses_complete_chinese_action_labels():
    handle = make_handle(
        QML_DIR / "main.qml", w=1000, h=700,
        ctrl=make_empty_controller(), loc="zh-CN",
    )
    try:
        expected = {
            "batchAddFilesButton": "添加文件",
            "batchAddFolderButton": "添加文件夹",
            "batchTargetDirectoryButton": "目标目录",
            "batchApplySelectedButton": "应用所选",
            "batchStopButton": "停止任务",
            "batchClearButton": "清空工作区",
        }
        for object_name, label in expected.items():
            item = handle.root.findChild(QQuickItem, object_name)
            assert item is not None
            assert item.property("text") == label
        status = handle.root.findChild(QQuickItem, "batchStatusFilter")
        assert status is not None
        assert status.property("currentText") == "全部状态"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_batch_toolbar_text_buttons_have_no_immediate_hover_tooltips():
    source = (QML_DIR / "BatchToolbar.qml").read_text(encoding="utf-8")
    assert "ToolTip.visible: hovered" not in source


def test_batch_comboboxes_open_only_after_real_click():
    for object_name in ("batchTemplateSelector", "batchStatusFilter"):
        handle = make_handle(
            QML_DIR / "main.qml", w=1000, h=700,
            ctrl=make_empty_controller(), loc="zh-CN",
        )
        try:
            combo = handle.root.findChild(QQuickItem, object_name)
            assert combo is not None
            point = combo.mapToScene(
                QPointF(combo.width() / 2, combo.height() / 2)
            ).toPoint()
            QTest.mouseMove(combo.window(), point)
            QTest.qWait(650)
            QApplication.processEvents()
            assert combo.property("popupVisible") is False

            QTest.mouseClick(
                combo.window(), Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier, point,
            )
            QTest.qWait(50)
            QApplication.processEvents()
            assert combo.property("popupVisible") is True
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()


def test_batch_toolbar_responsive_mode_preserves_clear_labels():
    for width, height, compact in ((1000, 700, False), (900, 640, False)):
        handle = make_handle(
            QML_DIR / "main.qml", w=width, h=height,
            ctrl=make_empty_controller(), loc="zh-CN",
        )
        try:
            toolbar = handle.root.findChild(QQuickItem, "batchToolbar")
            assert toolbar is not None
            assert toolbar.property("compactActions") is compact
            for name, label in (
                ("batchAddFilesButton", "添加文件"),
                ("batchAddFolderButton", "添加文件夹"),
                ("batchTargetDirectoryButton", "目标目录"),
            ):
                item = handle.root.findChild(QQuickItem, name)
                assert item.property("text") == label
            for name, label in (
                ("batchApplySelectedButton", "应用所选"),
                ("batchStopButton", "停止任务"),
                ("batchClearButton", "清空工作区"),
            ):
                item = handle.root.findChild(QQuickItem, name)
                assert item.property("text") == label
                assert item.property("accessibleName") == label
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()


def test_action_label_is_persistent_without_hover_disclosure():
    handle = make_handle(
        QML_DIR / "main.qml", w=900, h=640,
        ctrl=make_empty_controller(), loc="zh-CN",
    )
    try:
        button = handle.root.findChild(QQuickItem, "batchClearButton")
        assert button is not None
        point = button.mapToScene(
            QPointF(button.width() / 2, button.height() / 2)
        ).toPoint()
        QTest.mouseMove(button.window(), point)
        QTest.qWait(650)
        QApplication.processEvents()
        assert button.property("text") == "清空工作区"
        assert button.property("tooltipVisible") is None
        assert button.property("accessibleName") == "清空工作区"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_batch_toolbar_keeps_every_critical_action_inside_supported_widths():
    """The two-row toolbar must not clip Clear/Stop/Apply at 1000 or 900."""
    for width, height in ((1000, 700), (900, 640)):
        handle = make_handle(QML_DIR / "main.qml", w=width, h=height,
                             ctrl=make_empty_controller())
        try:
            for name in (
                "batchAddFilesButton", "batchAddFolderButton",
                "batchTargetDirectoryButton", "batchApplySelectedButton",
                "batchStopButton", "batchClearButton",
            ):
                item = handle.root.findChild(QQuickItem, name)
                assert item is not None and item.isVisible()
                left = item.mapToScene(QPointF(0, 0)).x()
                right = item.mapToScene(QPointF(item.width(), 0)).x()
                assert left >= 80, f"{width}px: {name} starts under the nav rail"
                assert right <= width, f"{width}px: {name} is clipped at x={right}"
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()


def test_inline_validation_is_localized_and_does_not_overlap_input():
    handle = make_handle(QML_DIR / "TaskCard.qml", w=900, h=140,
                         ctrl=_ActionSpy(), loc="zh-CN")
    try:
        handle.root.setProperty("taskId", "task-1")
        handle.root.setProperty("extension", ".pdf")
        handle.root.setProperty("suggestedName", "建议.pdf")
        handle.root.setProperty("isEditing", True)
        handle.root.setProperty("validationError", "batch.validate.illegalChars")
        QTest.qWait(30)
        QApplication.processEvents()
        field = handle.root.findChild(QQuickItem, "inlineNameField")
        error = handle.root.findChild(QQuickItem, "inlineValidationError")
        assert field is not None and error is not None and error.isVisible()
        field_bottom = field.mapToScene(QPointF(0, field.height())).y()
        error_top = error.mapToScene(QPointF(0, 0)).y()
        assert error_top >= field_bottom, (
            f"validation text overlaps input: {error_top=} < {field_bottom=}"
        )
        assert error.property("text") == "文件名包含非法字符"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_task_error_message_uses_locale_key_when_available():
    assert BatchWorkspaceController._safe_error("HTTP 429 rate limit") == "batch.error.rateLimit"
    handle = make_handle(QML_DIR / "TaskCard.qml", w=900, h=90,
                         ctrl=_ActionSpy(), loc="zh-CN")
    try:
        handle.root.setProperty("originalName", "报告.pdf")
        handle.root.setProperty("errorMessage", "batch.error.rateLimit")
        QTest.qWait(30)
        QApplication.processEvents()
        error = handle.root.findChild(QQuickItem, "taskErrorMessage")
        assert error is not None and error.isVisible()
        assert error.property("text") == "请求过于频繁，请稍后重试"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_page_router_uses_immediate_explicit_stack_operations():
    source = (QML_DIR / "PageRouter.qml").read_text(encoding="utf-8")
    assert "StackView.Immediate" in source
    assert "replace(null" not in source
    assert "root.currentItem" in source


def test_shell_navigation_replaces_current_page_and_settles(tmp_path):
    import time

    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=_Credentials(),
        connection_test_service=lambda *_: None,
        usage_recorder=None,
        watch_controller=None,
    )
    try:
        runtime.root.resize(1000, 700)
        runtime.root.show()
        QApplication.processEvents()
        nav = runtime.root.findChild(QQuickItem, "nav_watch")
        router = runtime.root.findChild(QQuickItem, "pageRouter")
        assert nav is not None and router is not None
        point = nav.mapToScene(QPointF(nav.width() / 2, nav.height() / 2)).toPoint()
        QTest.mouseClick(
            nav.window(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        deadline = time.monotonic() + 2.0
        while bool(router.property("busy")) and time.monotonic() < deadline:
            QTest.qWait(20)
            QApplication.processEvents()
        assert router.property("busy") is False
        assert router.property("currentPage") == "watch"
        current = router.property("currentItem")
        assert current is not None and current.objectName() == "watchPage"
        assert runtime.root.findChild(QQuickItem, "watchEmptyState").isVisible()
        assert runtime.watch_controller is None
        assert runtime.root.findChild(QQuickItem, "watchList").isVisible() is False
        assert runtime.root.findChild(QQuickItem, "watchFormSaveButton").isEnabled() is False
        assert runtime.root.findChild(QQuickItem, "watchAutoApplySwitch").property("checked") is False
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_template_selection_is_persisted_and_forwarded_to_analyzer(tmp_path):
    class Analyzer:
        def __init__(self): self.template_ids = []
        def set_template_id(self, value): self.template_ids.append(value)

    analyzer = Analyzer()
    ctrl = BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json", background=False
    )
    ctrl.configure_templates([
        {"id": "general", "name": "General"},
        {"id": "legal", "name": "Legal"},
    ], "general")
    ctrl.set_analyzer(analyzer)
    ctrl.setSelectedTemplate("legal")

    assert ctrl.selectedTemplateId == "legal"
    assert analyzer.template_ids[-1] == "legal"
    restarted = BatchWorkspaceController(
        workspace_path=tmp_path / "workspace.json", background=False
    )
    restarted.configure_templates(ctrl.templateOptions, "general")
    assert restarted.selectedTemplateId == "legal"
