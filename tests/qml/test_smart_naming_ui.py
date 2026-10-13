import json
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from src.controllers.mock_batch_controller import MockBatchController
from src.controllers.batch_workspace_controller import BatchWorkspaceController
from tests.qml.conftest import make_handle
from tests.qml.test_beginner_ui_polish import QML, evaluate, find


LOCALES = Path(__file__).parents[2] / "src" / "utils" / "i18n" / "locales"


def settle():
    QTest.qWait(30)
    QApplication.processEvents()


def test_mode_choice_selects_smart_without_changing_the_saved_template():
    ctrl = MockBatchController()
    ctrl._template_options.append({"id": "legal", "name": "Legal documents"})
    ctrl.setSelectedTemplate("legal")
    handle = make_handle(QML / "BatchToolbar.qml", w=1000, h=144, ctrl=ctrl)
    try:
        mode = find(handle, "batchNamingModeSelector")
        template = find(handle, "batchTemplateSelector")
        guidance = find(handle, "batchSmartNamingGuidance")
        assert mode is not None and mode.property("currentValue") == "template"
        assert mode.property("currentText") == "按模板命名"
        assert template is not None and template.isVisible() and template.isEnabled()

        evaluate(handle, mode, 'currentIndex = indexOfValue("smart"); activated(currentIndex)')
        settle()

        assert ctrl.namingMode == "smart"
        assert ctrl.selectedTemplateId == "legal"
        assert not template.isVisible() and not template.isEnabled()
        assert guidance is not None and guidance.isVisible()
        assert "一致" in guidance.property("text")
        assert "检查" in guidance.property("text")

        evaluate(handle, mode, 'currentIndex = indexOfValue("template"); activated(currentIndex)')
        settle()
        assert ctrl.namingMode == "template"
        assert ctrl.selectedTemplateId == "legal"
        assert template.isVisible() and template.isEnabled()
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_smart_language_prompt_defaults_to_chinese_and_confirms_a_real_language():
    handle = make_handle(QML / "NamingLanguageDialog.qml", w=700, h=500)
    try:
        dialog = handle.root
        dialog.setProperty("namingMode", "smart")
        dialog.setProperty("draftLanguage", "")
        dialog.setProperty("visible", True)
        settle()

        combo = find(handle, "namingLanguageChoice")
        template_summary = find(handle, "namingTemplateSummary")
        smart_summary = find(handle, "namingSmartSummary")
        assert combo is not None and combo.property("count") == 5
        assert combo.property("currentValue") == "zh"
        assert all("沿用模板" not in evaluate(handle, combo, f"textAt({i})") for i in range(5))
        assert template_summary is not None
        assert smart_summary is not None and "一致" in smart_summary.property("text")

        evaluate(handle, combo, 'currentIndex = indexOfValue("zh-HK"); activated(currentIndex)')
        confirmed = QSignalSpy(dialog.confirmed)
        confirm = find(handle, "namingLanguageConfirm")
        assert confirm.property("text") == "生成命名建议"
        evaluate(handle, confirm, "clicked()")

        assert confirmed.count() == 1
        assert list(confirmed.at(0)) == ["zh-HK"]
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_template_language_prompt_still_offers_follow_template():
    handle = make_handle(QML / "NamingLanguageDialog.qml", w=700, h=500)
    try:
        dialog = handle.root
        dialog.setProperty("namingMode", "template")
        dialog.setProperty("templateName", "General Naming")
        dialog.setProperty("templateLanguage", "en")
        dialog.setProperty("draftLanguage", "")
        dialog.setProperty("visible", True)
        settle()

        combo = find(handle, "namingLanguageChoice")
        assert combo.property("count") == 6
        assert combo.property("currentValue") == ""
        assert "沿用模板" in combo.property("currentText")
        assert "英文" in combo.property("currentText")
        assert "General Naming" in find(handle, "namingTemplateSummary").property("text")
        assert find(handle, "namingSmartSummary") is not None
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_smart_naming_copy_and_policy_errors_exist_in_all_three_locales():
    required = {
        "batch.toolbar.namingMode",
        "batch.toolbar.namingRule",
        "batch.namingMode.template",
        "batch.namingMode.smart",
        "batch.toolbar.smartHint",
        "naming.prompt.smart",
        "smart.error.insufficientContent",
        "smart.error.invalidResponse",
        "smart.error.genericName",
        "smart.error.ungrounded",
        "smart.error.tooLong",
        "smart.error.languageMismatch",
        "smart.error.unsafeName",
        "smart.error.unsupportedPolicy",
        "smart.error.strategyUnavailable",
    }
    expected_modes = {
        "zh_CN.json": ("按模板命名", "AI 智能命名"),
        "zh_HK.json": ("按範本命名", "AI 智能命名"),
        "en_US.json": ("Name with template", "AI smart naming"),
    }
    for filename, labels in expected_modes.items():
        data = json.loads((LOCALES / filename).read_text(encoding="utf-8"))
        assert required <= data.keys()
        assert (data["batch.namingMode.template"], data["batch.namingMode.smart"]) == labels
        assert all(data[key].strip() and data[key] != key for key in required)


def test_smart_import_confirms_language_into_the_production_task_snapshot(tmp_path):
    source = tmp_path / "evidence.txt"
    source.write_text("specific content", encoding="utf-8")
    ctrl = BatchWorkspaceController(background=False)
    ctrl.configure_templates([
        {"id": "general", "name": "General Naming", "outputLanguage": "en"},
    ])
    selected_template = ctrl.selectedTemplateId
    ctrl.setNamingMode("smart")
    handle = make_handle(QML / "BatchPage.qml", ctrl=ctrl)
    try:
        handle.root.requestImport("files", [source.as_uri()])
        settle()
        combo = find(handle, "namingLanguageChoice")
        assert combo.property("count") == 5
        assert combo.property("currentValue") == "zh"

        evaluate(handle, combo, 'currentIndex = indexOfValue("en"); activated(currentIndex)')
        evaluate(handle, find(handle, "namingLanguageConfirm"), "clicked()")
        settle()

        assert ctrl.totalCount == 1
        snapshot = ctrl.task_snapshot(ctrl.task_ids[0])
        assert snapshot["namingMode"] == "smart"
        assert snapshot["outputLanguage"] == "en"
        assert ctrl.selectedTemplateId == selected_template
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
        ctrl.close()


def test_english_smart_toolbar_stays_inside_the_900px_supported_window():
    ctrl = MockBatchController()
    ctrl.setNamingMode("smart")
    handle = make_handle(QML / "main.qml", w=900, h=640, ctrl=ctrl, loc="en-US")
    try:
        item_by_name = lambda name: handle.root.findChild(QQuickItem, name)
        assert item_by_name("batchTemplateSelector").isVisible() is False
        guidance = item_by_name("batchSmartNamingGuidance")
        assert guidance.isVisible()
        assert guidance.property("text") == "Content + style.\nReview first."
        assert guidance.property("truncated") is False
        assert guidance.property("lineCount") <= 2
        assert guidance.property("contentHeight") <= guidance.height()
        for name in (
            "batchNamingModeSelector",
            "batchAddFilesButton",
            "batchAddFolderButton",
            "batchTargetDirectoryButton",
            "batchTargetSummary",
            "batchApplySelectedButton",
            "batchStopButton",
            "batchClearButton",
        ):
            item = item_by_name(name)
            assert item is not None and item.isVisible()
            left = item.mapToScene(QPointF(0, 0)).x()
            right = item.mapToScene(QPointF(item.width(), 0)).x()
            assert left >= 80, f"{name} starts under the navigation rail: {left}"
            assert right <= 900, f"{name} is clipped at x={right}"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_task_card_translates_smart_policy_errors_in_every_supported_locale():
    expected = {
        "zh-CN": "生成的名称太长，请重新生成或改用模板命名。",
        "zh-HK": "生成的名稱太長，請重新生成或改用範本命名。",
        "en-US": "The generated name is too long. Generate it again or use template naming.",
    }
    for locale, message in expected.items():
        handle = make_handle(QML / "TaskCard.qml", w=900, h=90,
                             ctrl=MockBatchController(), loc=locale)
        try:
            handle.root.setProperty("errorMessage", "smart.error.tooLong")
            settle()
            error = find(handle, "taskErrorMessage")
            assert error.property("text") == message
            assert error.property("text") != "smart.error.tooLong"
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()
