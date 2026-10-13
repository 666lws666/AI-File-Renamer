"""Native Windows visual/interaction evidence for the Batch toolbar.

All captures are synthetic and confined to
``tests/screenshots/qa-current/batch-toolbar``.  The runtime uses a temporary
configuration, fake credential store, and fake connection service; it never
contacts a provider or the real Windows Credential Manager.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

for key in list(os.environ):
    if key.startswith("QT_QPA_PLATFORM"):
        del os.environ[key]

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "tests" / "screenshots" / "qa-current" / "batch-toolbar"


class FakeCredentialStore:
    def get(self, *_args): return None
    def set(self, *_args): return True
    def delete(self, *_args): return True


def _find(root, name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, name)
    if item is None:
        raise AssertionError(f"missing QML object: {name}")
    return item


def _center(item: QQuickItem):
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()


def _hover(root, item: QQuickItem, wait_ms: int) -> None:
    QTest.mouseMove(root, _center(item))
    QTest.qWait(wait_ms)
    QApplication.processEvents()


def _click(root, item: QQuickItem) -> None:
    QTest.mouseClick(
        root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        _center(item),
    )
    QTest.qWait(80)
    QApplication.processEvents()


def _capture(runtime, filename: str) -> dict:
    image = runtime.root.grabWindow()
    if image.isNull():
        raise RuntimeError(f"null native capture: {filename}")
    path = OUTPUT / filename
    if not image.save(str(path)):
        raise RuntimeError(f"failed to save {path}")
    data = path.read_bytes()
    return {
        "filename": filename,
        "width": image.width(),
        "height": image.height(),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _assert_labels(runtime, compact: bool, locale: str) -> list[dict]:
    root = runtime.root
    zh = locale == "zh-CN"
    expected = {
        "batchAddFilesButton": "添加文件" if zh else "Add Files",
        "batchAddFolderButton": "添加文件夹" if zh else "Add Folder",
        "batchTargetDirectoryButton": "目标目录" if zh else "Target Folder",
    }
    records = []
    for name, label in expected.items():
        actual = _find(root, name).property("text")
        if actual != label:
            raise AssertionError(f"{name}.text={actual!r}, expected {label!r}")
        records.append({"object": name, "text": actual})

    right = {
        "batchApplySelectedButton": "应用所选" if zh else "Apply Selected",
        "batchStopButton": "停止任务" if zh else "Stop Tasks",
        "batchClearButton": "清空工作区" if zh else "Clear Workspace",
    }
    for name, label in right.items():
        item = _find(root, name)
        expected_text = "" if compact else label
        if item.property("text") != expected_text:
            raise AssertionError(
                f"{name}.text={item.property('text')!r}, expected {expected_text!r}"
            )
        if item.property("accessibleName") != label:
            raise AssertionError(f"{name} has wrong accessible name")
        records.append({
            "object": name,
            "text": item.property("text"),
            "accessible_name": item.property("accessibleName"),
        })

    template = _find(root, "batchTemplateSelector").property("currentText")
    expected_template = "通用命名（默认）" if zh else "General Naming (Default)"
    if template != expected_template:
        raise AssertionError(f"template={template!r}, expected {expected_template!r}")
    status = _find(root, "batchStatusFilter").property("currentText")
    expected_status = "全部状态" if zh else "All Statuses"
    if status != expected_status:
        raise AssertionError(f"status={status!r}, expected {expected_status!r}")
    records.extend([
        {"object": "batchTemplateSelector", "current_text": template},
        {"object": "batchStatusFilter", "current_text": status},
    ])
    return records


def _assert_geometry(runtime) -> list[dict]:
    names = (
        "batchAddFilesButton", "batchAddFolderButton",
        "batchTargetDirectoryButton", "batchSearchField",
        "batchStatusFilter", "batchApplySelectedButton",
        "batchStopButton", "batchClearButton",
    )
    rows = []
    previous_right = 48.0
    for name in names:
        item = _find(runtime.root, name)
        left = item.mapToScene(QPointF(0, 0)).x()
        right = item.mapToScene(QPointF(item.width(), 0)).x()
        if left < 48 or right > runtime.root.width():
            raise AssertionError(f"{name}: out of bounds {left}..{right}")
        if left < previous_right - 0.5:
            raise AssertionError(f"{name}: overlaps prior control at x={left}")
        previous_right = right
        rows.append({"object": name, "left": left, "right": right,
                     "width": item.width()})
    return rows


def _verify_combo_clicks(runtime) -> list[dict]:
    records = []
    for name in ("batchTemplateSelector", "batchStatusFilter"):
        combo = _find(runtime.root, name)
        _hover(runtime.root, combo, 650)
        if combo.property("popupVisible") is not False:
            raise AssertionError(f"{name}: hover opened the popup")
        _click(runtime.root, combo)
        if combo.property("popupVisible") is not True:
            raise AssertionError(f"{name}: real click did not open the popup")
        records.append({"object": name, "hover_open": False, "click_open": True})
        QTest.keyClick(runtime.root, Qt.Key.Key_Escape)
        QTest.qWait(50)
        QApplication.processEvents()
    return records


def _build(temp_dir: Path):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime
    return build_qml_runtime(
        live_config=AppConfig(language="zh_CN"),
        config_file=temp_dir / "settings.json",
        credential_store=FakeCredentialStore(),
        connection_test_service=lambda *_args: None,
        usage_recorder=None,
        watch_controller=None,
        status_controller=None,
        diagnostics_service=None,
    )


def main() -> int:
    from scripts.capture_m1_native import _cjk_probe

    app = QApplication.instance() or QApplication(sys.argv)
    if QApplication.platformName().lower() != "windows":
        raise RuntimeError(
            f"native Windows QPA required, got {QApplication.platformName()!r}"
        )
    app.setFont(QFont("Microsoft YaHei UI", 10))
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="xuxia-toolbar-") as temp:
        runtime = _build(Path(temp))
        try:
            runtime.root.resize(QSize(1000, 700))
            runtime.root.show()
            if not QTest.qWaitForWindowExposed(runtime.root, 5000):
                raise RuntimeError("native Batch window was not exposed")
            QTest.qWait(150)
            app.processEvents()

            cases = []
            assertions = _assert_labels(runtime, False, "zh-CN")
            assertions.extend(_assert_geometry(runtime))
            interactions = _verify_combo_clicks(runtime)
            runtime.assert_zero_warnings()
            cases.append({
                "case": "zh-1000x700", "assertions": assertions,
                "interactions": interactions,
                **_capture(runtime, "zh-1000x700.png"),
            })

            runtime.root.resize(QSize(900, 640))
            QTest.qWait(120)
            app.processEvents()
            toolbar = _find(runtime.root, "batchToolbar")
            if toolbar.property("compactActions") is not True:
                raise AssertionError("900px did not activate compact actions")
            assertions = _assert_labels(runtime, True, "zh-CN")
            assertions.extend(_assert_geometry(runtime))
            clear_button = _find(runtime.root, "batchClearButton")
            _hover(runtime.root, clear_button, 150)
            if clear_button.property("tooltipVisible") is not False:
                raise AssertionError("compact tooltip appeared before its delay")
            _hover(runtime.root, clear_button, 550)
            if clear_button.property("tooltipVisible") is not True:
                raise AssertionError("compact tooltip did not appear after 500 ms")
            if clear_button.property("accessibleName") != "清空工作区":
                raise AssertionError("compact tooltip/accessibility label is not Chinese")
            QTest.mouseMove(runtime.root, _center(_find(runtime.root, "batchSearchField")))
            QTest.qWait(80)
            app.processEvents()
            cases.append({
                "case": "zh-900x640", "assertions": assertions,
                "tooltip": {"before_500ms": False, "after_500ms": True,
                            "text": "清空工作区"},
                **_capture(runtime, "zh-900x640.png"),
            })

            runtime.root.resize(QSize(1000, 700))
            runtime.i18n.set_locale("en-US")
            QTest.qWait(100)
            app.processEvents()
            assertions = _assert_labels(runtime, True, "en-US")
            assertions.extend(_assert_geometry(runtime))
            cases.append({"case": "en-1000x700", "assertions": assertions,
                          **_capture(runtime, "en-1000x700.png")})

            runtime.i18n.set_locale("zh-CN")
            QTest.qWait(100)
            app.processEvents()
            assertions = _assert_labels(runtime, False, "zh-CN")
            cases.append({"case": "zh-restored-1000x700", "assertions": assertions,
                          **_capture(runtime, "zh-restored-1000x700.png")})

            runtime.assert_zero_warnings()
            cjk = _cjk_probe(app)
            if not cjk["passed"]:
                raise AssertionError("CJK glyph probe failed")
            manifest = {
                "platform": QApplication.platformName().lower(),
                "font_requested": "Microsoft YaHei UI",
                "font_actual": QFontInfo(app.font()).family(),
                "qml_warnings": list(runtime.warnings),
                "cjk": cjk,
                "real_mouse": {
                    "hovered": ["template", "status", "compact clear"],
                    "clicked": ["template", "status"],
                },
                "cases": cases,
            }
            (OUTPUT / "batch-toolbar-native-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        finally:
            runtime.cleanup()
            app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
