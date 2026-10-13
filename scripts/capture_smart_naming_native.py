"""Three-language offline manual and smart-mode native evidence.

All rows are synthetic UI examples, not outputs of a real model. Uses temporary
configuration and FakeCredentialStore; no provider or user-file operation runs.
Formal screenshot goldens are neither read nor written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from capture_user_guide_native import (
    EXPECTED, PRIVATE_SENTINELS, FakeCredentialStore, _click, _find,
    _delegate_with_runtime, _watch_page_controller, _status_controller, _scroll_into_view,
    _navigation, _provider, _batch_empty, _inline_edit,
    _watch_create, _watch_results, _templates, _vocabulary, _system_status,
)
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QFont, QFontInfo, QFontMetricsF
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.controllers.mock_batch_controller import MockBatchController
from src.models.app_config import AppConfig
from src.qml_bootstrap import build_qml_runtime

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-CN", "zh-HK", "en-US")
FILENAMES = dict(EXPECTED, **{
    "naming-mode": "11-naming-mode.png",
    "filename-language": "12-filename-language.png",
})
QA_FILENAMES = {"smart-errors": "13-smart-errors.png"}
TITLES = {
    "zh-CN": ["北辰项目_数据迁移服务合同", "海岚科技_第二季度销售复盘",
              "蓝桥学校_春季研学交通安排", "滨海公园_日落步道",
              "净水器_滤芯更换操作演示"],
    "zh-HK": ["北辰項目_數據遷移服務合約", "海嵐科技_第二季銷售回顧",
              "藍橋學校_春季研學交通安排", "濱海公園_日落步道",
              "濾水器_濾芯更換操作示範"],
    "en-US": ["Northstar_Data migration service agreement", "Hailan_Q2 sales review",
              "Bluebridge School_Spring field trip transport", "Coastal Park_Sunset walkway",
              "Water purifier_Filter replacement demonstration"],
}


def _synthetic_rows(batch, locale):
    batch._template_options = [{"id": "default", "outputLanguage": "zh", "name": {
        "zh-CN": "通用命名（默认）", "zh-HK": "通用命名（預設）",
        "en-US": "General naming (default)"}[locale]}]
    batch.set_scenario_n_items(5)
    model = batch.tasksModel
    model.beginResetModel()
    extensions = (".pdf", ".docx", ".xlsx", ".jpg", ".mp4")
    for index, row in enumerate(model._tasks):
        row.update(originalName=f"Examples/input-{index + 1}{extensions[index]}",
                   suggestedName=f"2026-04_{TITLES[locale][index]}{extensions[index]}",
                   extension=extensions[index], status="review_pending",
                   errorMessage="", selected=False, isEditing=False,
                   thumbnailKind=("image" if index == 3 else "video" if index == 4 else "doc"))
    model._update_actions()
    model.endResetModel()
    batch.tasksChanged.emit()


def _choose_smart(runtime, batch):
    _click(runtime.root, "batchNamingModeSelector")
    QTest.keyClick(runtime.root, Qt.Key_Home)
    QTest.keyClick(runtime.root, Qt.Key_Down)
    QTest.keyClick(runtime.root, Qt.Key_Return)
    QTest.qWait(100)
    assert batch.namingMode == "smart", "native mode selection did not change controller"
    assert _find(runtime.root, "batchSmartNamingGuidance").isVisible()
    assert not _find(runtime.root, "batchTemplateSelector").isVisible()


def _geometry(root):
    records = []
    for name in ("batchNamingModeSelector", "batchAddFilesButton",
                 "batchAddFolderButton", "batchTargetDirectoryButton",
                 "batchApplySelectedButton", "batchStopButton", "batchClearButton"):
        item = _find(root, name)
        point = item.mapToScene(QPointF())
        assert item.isVisible() and item.width() > 0 and item.height() > 0, name
        assert point.x() >= 0 and point.x() + item.width() <= root.width() + 1, name
        assert point.y() >= 0 and point.y() + item.height() <= root.height() + 1, name
        if item.property("text") is not None:
            needed = QFontMetricsF(item.property("font")).horizontalAdvance(item.property("text"))
            assert needed + item.property("leftPadding") + item.property("rightPadding") <= item.width() + 1, name
        records.append({"object": name, "x": point.x(), "y": point.y(),
                        "width": item.width(), "height": item.height()})
    return records


def _configure(scene, runtime, batch, minimum=False):
    if scene in {"navigation", "batch-empty", "naming-mode", "filename-language"}:
        batch.set_empty()
    runtime.root.resize(QSize(900 if minimum or scene == "navigation" else 1000,
                             640 if minimum or scene == "navigation" else 700))
    runtime.root.show()
    assert QTest.qWaitForWindowExposed(runtime.root, 5000)
    QTest.qWait(120)
    if scene == "naming-mode":
        _choose_smart(runtime, batch)
        return (("batchSmartNamingGuidance", "visible", True),)
    if scene == "filename-language":
        _choose_smart(runtime, batch)
        page = _find(runtime.root, "namingLanguageDialog").parentItem()
        expression = QQmlExpression(runtime.engine.rootContext(), page,
            "requestImport('files', ['Examples/input-1.pdf'])")
        expression.evaluate()  # requestImport is void; undefined is expected.
        assert not expression.hasError(), expression.error().toString()
        QTest.qWait(100)
        assert _find(runtime.root, "namingLanguageChoice").property("count") == 5
        return (("namingLanguageDialog", "visible", True),
                ("namingSmartSummary", "visible", True))
    if scene == "batch-review":
        _choose_smart(runtime, batch)
        return (("batchTaskQueue", "visible", True),)
    if scene == "smart-errors":
        _choose_smart(runtime, batch)
        keys = ("insufficientContent", "genericName", "tooLong", "ungrounded", "languageMismatch")
        model = batch.tasksModel
        model.beginResetModel()
        for row, reason in zip(model._tasks, keys):
            row.update(status="failed", suggestedName="", errorMessage="smart.error." + reason)
        model._update_actions()
        model.endResetModel()
        batch.tasksChanged.emit()
        QTest.qWait(100)
        return tuple((("delegate", "batchTaskQueue", index, "taskErrorMessage"),
                      "text", runtime.i18n.tr("smart.error." + key))
                     for index, key in enumerate(keys))
    callbacks = {
        "navigation": _navigation, "provider-settings": _provider, "batch-empty": _batch_empty,
        "inline-edit": _inline_edit, "watch-create": _watch_create,
        "watch-results": _watch_results, "templates": _templates,
        "vocabulary": _vocabulary, "system-status": _system_status,
    }
    size, assertions = callbacks[scene](runtime, batch)
    runtime.root.resize(QSize(*size))
    if scene == "provider-settings":
        _scroll_into_view(runtime.root, "preferencesScroll", "providerForm")
    return assertions


def _capture(locale, scene, output, minimum=False):
    with tempfile.TemporaryDirectory(prefix="xuxia-smart-guide-") as temp:
        base = Path(temp)
        batch = MockBatchController()
        _synthetic_rows(batch, locale)
        watch = _watch_page_controller(base / "watch", with_result=scene == "watch-results")
        watch._templates_provider = lambda: [{"id": "general", "name": batch._template_options[0]["name"]}]
        if locale != "zh-CN" and scene == "watch-results":
            # Translate the synthetic examples as well as the chrome.
            for row in watch._review_handler.rows:
                row.display_name = "Quarterly review.pdf" if locale == "en-US" else "季度回顧資料.pdf"
                row.suggested_name = "2026_Quarterly review.pdf" if locale == "en-US" else "2026_季度回顧資料.pdf"
        runtime = build_qml_runtime(
            live_config=AppConfig(language=locale), config_file=base / "settings.json",
            credential_store=FakeCredentialStore(), batch_controller=batch,
            watch_controller=watch, status_controller=_status_controller(),
            connection_test_service=lambda *_: None, usage_recorder=None)
        try:
            assertions = _configure(scene, runtime, batch, minimum)
            QTest.qWait(180)
            records = []
            delegates = []  # Keep PySide wrappers alive while reading child items.
            for target, prop, expected in assertions:
                if isinstance(target, tuple):
                    _, queue, index, child = target
                    delegate = _delegate_with_runtime(runtime, queue, index)
                    delegates.append(delegate)
                    item = _find(delegate, child)
                    label = f"{queue}[{index}].{child}"
                else:
                    item, label = _find(runtime.root, target), target
                actual = item.property(prop)
                assert actual == expected, (scene, label, prop, actual, expected)
                records.append({"object": label, "property": prop, "actual": actual, "expected": expected})
            geometry = _geometry(runtime.root) if scene in {
                "navigation", "batch-empty", "batch-review", "naming-mode", "filename-language"} else []
            runtime.assert_zero_warnings()
            image = runtime.root.grabWindow()
            filename = (FILENAMES | QA_FILENAMES)[scene]
            destination = output / locale / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            assert not image.isNull() and image.save(str(destination))
            result = dict(case_id=f"{locale}:{scene}", locale=locale,
                          filename=f"{locale}/{filename}", width=image.width(),
                          height=image.height(), size_bytes=destination.stat().st_size,
                          sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                          warnings=list(runtime.warnings), assertions=records, geometry=geometry,
                          synthetic_examples=True, real_model_quality_verified=False)
            if scene == "filename-language":
                _click(runtime.root, "namingLanguageCancel")
                assert not _find(runtime.root, "namingLanguageDialog").isVisible()
                assert batch.totalCount == 0, "cancel must not import"
            runtime.assert_zero_warnings()
            print(f"CAPTURE {locale}:{scene} {image.width()}x{image.height()} warnings=0", flush=True)
            return result
        finally:
            runtime.cleanup()
            QTest.qWait(80)
            QApplication.processEvents()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", choices=LOCALES)
    parser.add_argument("--scene", choices=tuple(FILENAMES | QA_FILENAMES))
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    assert app.platformName().lower() == "windows", "native Windows QPA required"
    app.setFont(QFont("Microsoft YaHei UI", 10))
    output = ROOT / "user-guide-assets"
    qa_output = ROOT / "tests/screenshots/qa-current/smart-naming"
    results = [_capture(locale, scene, qa_output if scene in QA_FILENAMES else output)
               for locale in ((args.locale,) if args.locale else LOCALES)
               for scene in ((args.scene,) if args.scene else FILENAMES)]
    from scripts.capture_m1_native import _cjk_probe
    cjk = _cjk_probe(app)
    assert cjk["passed"]
    manifest = dict(platform="windows", font_requested="Microsoft YaHei UI",
                    font_actual=QFontInfo(app.font()).family(), cjk=cjk,
                    synthetic_examples=True, real_model_quality_verified=False,
                    privacy_scan={"passed": True, "checked_count": len(PRIVATE_SENTINELS)},
                    cases=results)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    assert not any(s.casefold() in text.casefold() for s in PRIVATE_SENTINELS)
    if not args.locale and not args.scene:
        (output / "manifest.json").write_text(text, encoding="utf-8")
        minimum = [_capture(locale, scene, qa_output, minimum=True)
                   for locale in LOCALES for scene in ("naming-mode", "filename-language", "batch-review", "smart-errors")]
        (qa_output / "manifest-minimum.json").write_text(
            json.dumps(minimum, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"captures": len(results), "warnings": 0, "cjk": cjk["passed"],
                      "real_model_quality_verified": False}))


if __name__ == "__main__":
    main()
