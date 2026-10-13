"""Shared native guide helpers and compatibility entry for the current guide.

No network, real credentials, user configuration, formal golden, or private input
is touched.  Every case receives a fresh native Windows runtime backed by a
temporary settings directory and deterministic local-only dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

for key in list(os.environ):
    if key.startswith("QT_QPA_PLATFORM"):
        del os.environ[key]

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtQml import QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED = {
    "navigation": "01-navigation.png",
    "provider-settings": "02-provider-settings.png",
    "batch-empty": "03-batch-empty.png",
    "batch-review": "04-batch-review.png",
    "inline-edit": "05-inline-edit.png",
    "watch-create": "06-watch-create.png",
    "watch-results": "07-watch-results.png",
    "templates": "08-templates.png",
    "vocabulary": "09-vocabulary.png",
    "system-status": "10-system-status.png",
}

PRIVATE_SENTINELS = (
    "15413", "api_key=", "bearer ", "sentinel-secret", "真实密钥",
)


class FakeCredentialStore:
    def get(self, _service, _account): return None
    def set(self, _service, _account, _value): return True
    def delete(self, _service, _account): return True


def _find(root, name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, name)
    if item is None:
        available = sorted({child.objectName() for child in root.findChildren(QQuickItem)
                            if child.objectName()})
        raise AssertionError(f"missing QML object {name!r}; available={available}")
    return item


def _click(root, name: str) -> None:
    item = _find(root, name)
    if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
        raise AssertionError(f"{name}: target is not visibly clickable")
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(root, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(80)
    QApplication.processEvents()
    router = root.findChild(QQuickItem, "pageRouter")
    if router is not None:
        QTest.qWait(80)
        QApplication.processEvents()


def _scroll_into_view(root, scroll_name: str, item_name: str) -> None:
    scroll = _find(root, scroll_name)
    item = _find(root, item_name)
    item_center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).y()
    scroll_top = scroll.mapToScene(QPointF(0, 0)).y()
    target_center = scroll_top + scroll.height() / 2
    flickable = scroll.property("contentItem")
    if flickable is None:
        raise AssertionError(f"{scroll_name}: ScrollView has no Flickable contentItem")
    current = float(flickable.property("contentY") or 0)
    flickable.setProperty("contentY", max(0.0, current + item_center - target_center))
    QTest.qWait(100)
    QApplication.processEvents()
    item_center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).y()
    if not (scroll_top <= item_center <= scroll_top + scroll.height()):
        raise AssertionError(
            f"{item_name}: scrolling did not expose click target; y={item_center}, "
            f"viewport={scroll_top}..{scroll_top + scroll.height()}"
        )


def _delegate_with_runtime(runtime, queue_name: str, index: int) -> QQuickItem:
    queue = _find(runtime.root, queue_name)
    item, undefined = QQmlExpression(
        runtime.engine.rootContext(), queue, f"itemAtIndex({index})"
    ).evaluate()
    if undefined or item is None:
        raise AssertionError(f"{queue_name}: delegate {index} is not materialized")
    return item


def _status_controller():
    from src.controllers.status_controller import ComponentStatus, StatusController, StatusLevel
    return StatusController({
        "local": lambda: ComponentStatus("local", "status.component.local", StatusLevel.READY, "status.detail.localReady"),
        "text": lambda: ComponentStatus("text", "status.component.text", StatusLevel.READY, "status.detail.available"),
        "vision": lambda: ComponentStatus("vision", "status.component.vision", StatusLevel.READY, "status.detail.available"),
    })


@dataclass
class _ReviewRow:
    id: str
    watch_id: str
    display_name: str
    suggested_name: str
    state: object
    confidence: float = 0.94
    error_category: str = ""


class _Reviews:
    def __init__(self, rows=()): self.rows = list(rows)
    def items(self, watch_id=None):
        return [row for row in self.rows if watch_id is None or row.watch_id == watch_id]
    def approve(self, _item_id): pass
    def ignore(self, _item_id): pass
    def retry(self, _item_id): pass


def _watch_page_controller(root_dir: Path, *, with_result: bool = False):
    from src.controllers.watch_controller import ObserverFactory, WatchController
    from src.controllers.watch_edit_handler import WatchEditHandler
    from src.controllers.watch_page_controller import WatchPageController
    from src.core.watch_config import WatchConfig, WatchConfigStore, WatchMode, WatchStatus
    from src.core.watch_review_queue import ReviewItemState

    root_dir.mkdir(parents=True, exist_ok=True)
    store = WatchConfigStore(root_dir / "watches.json")
    rows = []
    if with_result:
        source = root_dir / "synthetic-inbox"
        source.mkdir()
        store.add(WatchConfig(
            id="guide-watch",
            source_dir=str(source),
            template_id="general",
            mode=WatchMode.REVIEW_FIRST,
            status=WatchStatus.PAUSED,
        ))
        rows.append(_ReviewRow(
            "guide-result", "guide-watch", "季度复盘资料.pdf",
            "2026_季度复盘资料.pdf", ReviewItemState.AWAITING_APPROVAL,
        ))
    reviews = _Reviews(rows)
    backend = WatchController(
        store,
        observer_factory=ObserverFactory(use_mock=True),
        review_first_handler=reviews,
    )
    page = WatchPageController(
        watch_controller=backend,
        edit_handler=WatchEditHandler(backend),
        review_handler=reviews,
        templates_provider=lambda: [{"id": "general", "name": "通用命名（默认）"}],
        results_provider=reviews.items,
    )
    if with_result:
        page.openResults("guide-watch")
        original_watch_row = page._watch_row
        def safe_watch_row(config):
            row = original_watch_row(config)
            row["sourceName"] = "示例收件箱"
            row["sourceDir"] = "示例收件箱"
            return row
        page._watch_row = safe_watch_row
    return page


def _runtime(temp_dir: Path, *, batch=None, watch=None, status=None):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime
    return build_qml_runtime(
        live_config=AppConfig(language="zh_CN"),
        config_file=temp_dir / "settings.json",
        credential_store=FakeCredentialStore(),
        batch_controller=batch,
        watch_controller=watch,
        status_controller=status,
        connection_test_service=lambda *_: None,
        usage_recorder=None,
    )


def _capture(case_id: str, output: Path, configure) -> dict:
    from src.controllers.mock_batch_controller import MockBatchController

    with tempfile.TemporaryDirectory(prefix=f"xuxia-guide-{case_id}-") as temp:
        root_dir = Path(temp)
        batch = MockBatchController()
        watch = _watch_page_controller(root_dir / "watch", with_result=case_id == "watch-results")
        status = _status_controller()
        runtime = _runtime(root_dir, batch=batch, watch=watch, status=status)
        try:
            size, assertions = configure(runtime, batch)
            runtime.root.resize(QSize(*size))
            runtime.root.show()
            if not QTest.qWaitForWindowExposed(runtime.root, 5000):
                raise RuntimeError(f"{case_id}: native window was not exposed")
            QTest.qWait(120)
            QApplication.processEvents()
            records = []
            for target, prop, expected in assertions:
                if isinstance(target, tuple) and target[0] == "delegate":
                    _, queue_name, index, child_name = target
                    delegate = _delegate_with_runtime(runtime, queue_name, index)
                    item = _find(delegate, child_name)
                    label = f"{queue_name}[{index}].{child_name}"
                elif isinstance(target, str):
                    item = _find(runtime.root, target)
                    label = target
                else:
                    raise TypeError(f"unsupported assertion target: {target!r}")
                actual = item.property(prop)
                if actual != expected:
                    raise AssertionError(
                        f"{case_id}: {label}.{prop}={actual!r}, expected {expected!r}"
                    )
                records.append({"object": label, "property": prop,
                                "actual": actual, "expected": expected})
            runtime.assert_zero_warnings()
            image = runtime.root.grabWindow()
            filename = EXPECTED[case_id]
            path = output / filename
            if image.isNull() or not image.save(str(path)):
                raise RuntimeError(f"{case_id}: failed to save {path}")
            data = path.read_bytes()
            return {
                "case_id": case_id,
                "filename": filename,
                "width": image.width(),
                "height": image.height(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "warnings": list(runtime.warnings),
                "assertions": records,
            }
        finally:
            runtime.cleanup()
            QTest.qWait(100)
            QApplication.processEvents()


def _navigation(runtime, batch):
    batch.set_empty()
    return (900, 640), (("pageRouter", "currentPage", "batch"), ("windowBoundary", "visible", True))


def _provider(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_preferences")
    _scroll_into_view(runtime.root, "preferencesScroll", "providerSettingsCard")
    card = _find(runtime.root, "providerSettingsCard")
    result, undefined = QQmlExpression(
        runtime.engine.rootContext(), card, "clickAction('deepseek', 'edit')"
    ).evaluate()
    if undefined or result is not True:
        raise AssertionError("DeepSeek preset edit action did not open ProviderForm")
    QTest.qWait(100); QApplication.processEvents()
    return (1000, 700), (("preferencesPage", "visible", True), ("providerForm", "visible", True))


def _batch_empty(runtime, batch):
    batch.set_empty()
    return (1000, 700), (("batchDropZone", "visible", True), ("windowBoundary", "visible", True))


def _batch_review(runtime, batch):
    batch.set_scenario_n_items(5)
    return (1000, 700), (("batchTaskQueue", "visible", True), ("windowBoundary", "visible", True))


def _inline_edit(runtime, batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    card = _delegate_with_runtime(runtime, "batchTaskQueue", 2)
    button = _find(card, "inlineEditButton")
    point = button.mapToScene(button.boundingRect().center()).toPoint()
    QTest.mouseClick(runtime.root, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(100); QApplication.processEvents()
    return (1000, 700), (
        (("delegate", "batchTaskQueue", 2, "inlineNameField"), "visible", True),
        ("windowBoundary", "visible", True),
    )


def _watch_create(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_watch"); _click(runtime.root, "addWatchButton")
    return (1000, 700), (("watchPage", "visible", True), ("watchForm", "visible", True))


def _watch_results(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_watch")
    return (1000, 700), (("watchResultsPanel", "visible", True), ("watchResultsList", "count", 1))


def _templates(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_templates")
    return (1000, 700), (("templatesPage", "visible", True), ("templateList", "visible", True))


def _vocabulary(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_templates"); _click(runtime.root, "vocabularyTabButton")
    return (1000, 700), (("templatesPage", "visible", True), ("vocabularyTab", "visible", True))


def _system_status(runtime, _batch):
    runtime.root.resize(QSize(1000, 700)); runtime.root.show(); QTest.qWait(100)
    _click(runtime.root, "nav_status")
    return (1000, 700), (("systemStatusModal", "visible", True), ("windowBoundary", "visible", True))


CASES = (
    ("navigation", _navigation), ("provider-settings", _provider),
    ("batch-empty", _batch_empty), ("batch-review", _batch_review),
    ("inline-edit", _inline_edit), ("watch-create", _watch_create),
    ("watch-results", _watch_results), ("templates", _templates),
    ("vocabulary", _vocabulary), ("system-status", _system_status),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "user-guide-assets")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if output != (ROOT / "user-guide-assets").resolve():
        raise ValueError("guide evidence may only be written to user-guide-assets")

    app = QApplication.instance() or QApplication(sys.argv)
    if QApplication.platformName().lower() != "windows":
        raise RuntimeError(f"native Windows QPA required, got {QApplication.platformName()!r}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    from scripts.capture_m1_native import _cjk_probe

    results = [_capture(case_id, output, configure) for case_id, configure in CASES]
    shas = [row["sha256"] for row in results]
    if len(shas) != len(set(shas)):
        raise AssertionError("distinct user-guide states produced duplicate pixels")
    cjk = _cjk_probe(app)
    if not cjk["passed"]:
        raise AssertionError("CJK glyph probe failed")

    manifest_text = json.dumps(results, ensure_ascii=False)
    privacy_hits = [value for value in PRIVATE_SENTINELS if value.casefold() in manifest_text.casefold()]
    if privacy_hits:
        raise AssertionError(f"privacy sentinel found in screenshot manifest: {privacy_hits}")
    payload = {
        "platform": QApplication.platformName().lower(),
        "font_requested": "Microsoft YaHei UI",
        "font_actual": QFontInfo(app.font()).family(),
        "cjk": cjk,
        "privacy_scan": {"passed": True, "checked_count": len(PRIVATE_SENTINELS)},
        "cases": results,
    }
    (output / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Keep older invocations on the current three-language evidence contract.
    from capture_smart_naming_native import main as capture_current_guide
    raise SystemExit(capture_current_guide())
