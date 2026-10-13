"""Native, offline beginner-flow verification; only synthetic files are renamed."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import capture_batch_toolbar_native as capture
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.controllers.batch_workspace_controller import BatchWorkspaceController
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime


def find(root, name):
    # ListView delegates belong to the visual tree, not necessarily QObject's
    # ownership tree. Search the tree that is actually painted and clicked.
    pending = [root.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name and item.isVisible():
            return item
        pending.extend(item.childItems())
    raise AssertionError(f"missing visible item: {name}")


def main():
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "windows", app.platformName()
    app.setFont(QFont("Microsoft YaHei UI", 10))
    capture.OUTPUT = ROOT / "tests/screenshots/qa-current/beginner-review"
    capture.OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="xuxia-beginner-") as temp:
        directory = Path(temp)
        ctrl = BatchWorkspaceController(
            workspace_path=directory / "workspace.json",
            history_path=directory / "history.jsonl",
            analyzer=lambda path, task_id: "learning-notes.txt",
            background=False,
        )
        runtime = build_qml_runtime(
            live_config=AppConfig(language="zh_CN"), config_file=directory / "settings.json",
            credential_store=capture.FakeCredentialStore(), batch_controller=ctrl,
            connection_test_service=lambda *_args: None, usage_recorder=None,
            watch_controller=None, status_controller=None, diagnostics_service=None,
        )
        try:
            root = runtime.root
            root.resize(QSize(1000, 700))
            root.show()
            QTest.qWait(350)
            for width, height in [(1000, 700), (900, 640)]:
                root.resize(QSize(width, height))
                QTest.qWait(100)
                capture._assert_geometry(runtime)
                records.append(capture._capture(runtime, f"empty-zh-{width}.png"))
            root.resize(QSize(1000, 700))
            source = directory / "新手练习.txt"
            source.write_text("仅用于本地测试。", encoding="utf-8")
            unsupported = directory / "archive.zip"
            unsupported.write_bytes(b"synthetic")
            ctrl.add_files([str(source), str(source), str(unsupported), str(directory / "missing.txt")])
            QTest.qWait(200)
            notice = capture._find(root, "batchImportFeedback")
            assert notice.isVisible() and "已加入 1" in notice.property("text")
            assert "无法读取 1" in notice.property("text")
            records.append(capture._capture(runtime, "import-feedback-zh.png"))
            capture._click(root, capture._find(root, "batchDismissImportFeedback"))
            assert not notice.isVisible()
            task_id = ctrl.task_ids[0]
            ctrl.toggleTaskSelected(task_id)
            QTest.qWait(100)
            capture._click(root, find(root, "inlineEditButton"))
            field = find(root, "inlineNameField")
            editor = find(root, "taskInlineEdit")
            records.append(capture._capture(runtime, "edit-open-zh.png"))
            assert field.hasActiveFocus(), (root.isActive(), field.hasFocus(), root.activeFocusItem())
            QTest.keyClick(root, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(root, Qt.Key_Backspace)
            QTest.keyClick(root, Qt.Key_Return)
            QTest.qWait(100)
            assert editor.property("localValidationError") == "batch.validate.empty"
            records.append(capture._capture(runtime, "inline-error-zh.png"))
            QTest.keyClick(root, Qt.Key_Escape)
            QTest.qWait(80)
            capture._click(root, find(root, "inlineEditButton"))
            field = find(root, "inlineNameField")
            editor = find(root, "taskInlineEdit")
            assert editor.property("localValidationError") == ""
            assert field.hasActiveFocus()
            QTest.keyClick(root, Qt.Key_A, Qt.ControlModifier)
            for character in "study-notes":
                QTest.keyClick(root, ord(character.upper()) if character.isalpha() else Qt.Key_Minus)
            QTest.keyClick(root, Qt.Key_Return)
            QTest.qWait(150)
            assert ctrl.task_snapshot(task_id)["suggestedName"].lower() == "study-notes.txt"
            assert source.exists(), "Editing a suggestion must not rename the source"
            capture._click(root, find(root, "taskApplyButton"))
            assert not source.exists()
            assert ctrl.task_snapshot(task_id)["status"] == "applied"
            capture._click(root, find(root, "taskUndoButton"))
            assert source.exists()
            assert source.read_text(encoding="utf-8") == "仅用于本地测试。"
            assert ctrl.task_snapshot(task_id)["status"] == "undone"
            records.append(capture._capture(runtime, "undo-restored-zh.png"))
            status = capture._find(root, "batchStatusFilter")
            capture._click(root, status)
            QTest.keyClick(root, Qt.Key_Home)
            QTest.keyClick(root, Qt.Key_Down)
            QTest.keyClick(root, Qt.Key_Return)
            QTest.qWait(100)
            assert ctrl.statusFilter == "pending", ctrl.statusFilter
            runtime.i18n.set_locale("en-US")
            QTest.qWait(150)
            assert ctrl.statusFilter == "pending"
            assert status.property("currentIndex") == 1
            records.append(capture._capture(runtime, "filter-preserved-en.png"))
            runtime.i18n.set_locale("zh-CN")
            ctrl.setStatusFilter("all")
            ctrl.clearWorkspace()
            def no_provider(*_args):
                raise RuntimeError("No active AI provider is configured")
            ctrl.set_analyzer(no_provider)
            ctrl.add_files([str(source)])
            QTest.qWait(100)
            capture._click(root, capture._find(root, "batchDismissImportFeedback"))
            message = find(root, "taskErrorMessage")
            assert "尚未配置 AI" in message.property("text")
            records.append(capture._capture(runtime, "setup-guidance-zh.png"))
            runtime.assert_zero_warnings()
            report = {"platform": app.platformName(), "qml_warnings": runtime.warnings,
                      "real_interactions": ["dismiss import feedback", "edit", "invalid input",
                          "cancel", "reopen and type", "apply", "undo", "select filter"],
                      "source_content_restored": True, "cases": records}
            (capture.OUTPUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))
        finally:
            runtime.cleanup()


if __name__ == "__main__":
    main()
