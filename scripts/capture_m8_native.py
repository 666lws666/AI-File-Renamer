"""Capture M8 native Windows Batch evidence without network or credentials.

All output is confined to ``tests/screenshots/qa-current/m8``. The script uses
only a deterministic mock model and exercises the real QML hit targets with
QTest mouse and keyboard input.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

for key in list(os.environ):
    if key.startswith("QT_QPA_PLATFORM"):
        del os.environ[key]

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtQml import QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QML_DIR = ROOT / "src" / "ui_qml"
OUTPUT = ROOT / "tests" / "screenshots" / "qa-current" / "m8"


def _find(root, name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, name)
    if item is None:
        available = sorted({child.objectName() for child in root.findChildren(QQuickItem)
                            if child.objectName()})
        raise AssertionError(f"missing QML object {name!r}; available={available}")
    return item


def _delegate_at(view: QQuickView, queue: QQuickItem, index: int) -> QQuickItem:
    item, is_undefined = QQmlExpression(
        view.engine().rootContext(), queue, f"itemAtIndex({index})"
    ).evaluate()
    if is_undefined or item is None:
        raise AssertionError(f"ListView delegate {index} is not materialized")
    return item


def _click(view: QQuickView, item: QQuickItem) -> None:
    if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
        raise AssertionError(f"unclickable item {item.objectName()!r}")
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(60)
    QApplication.processEvents()


def _save(view: QQuickView, filename: str) -> dict:
    image = view.grabWindow()
    if image.isNull():
        raise RuntimeError(f"null native capture for {filename}")
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


def _load(view: QQuickView, controller) -> object:
    view.setSource(QUrl())
    view.rootContext().setContextProperty("batchController", controller)
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "ScreenshotShell.qml")))
    if view.status() != QQuickView.Status.Ready or view.rootObject() is None:
        raise RuntimeError("M8 native QML did not load: " + repr(view.errors()))
    QTest.qWait(100)
    QApplication.processEvents()
    return view.rootObject()


def main() -> int:
    from scripts.capture_m1_native import _cjk_probe
    from src.controllers.mock_batch_controller import MockBatchController
    from src.utils.i18n.service import I18n

    app = QApplication.instance() or QApplication(sys.argv)
    if QApplication.platformName().lower() != "windows":
        raise RuntimeError(f"native Windows QPA required, got {QApplication.platformName()!r}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    OUTPUT.mkdir(parents=True, exist_ok=True)

    i18n = I18n()
    i18n.set_locale("zh-CN")
    warnings: list[str] = []
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.engine().addImportPath(str(ROOT / "src"))
    view.engine().warnings.connect(
        lambda messages: warnings.extend(message.toString() for message in messages)
    )
    view.rootContext().setContextProperty("i18n", i18n)
    view.resize(900, 640)
    view.show()
    if not QTest.qWaitForWindowExposed(view, 5000):
        raise RuntimeError("M8 native window was not exposed")

    results = []
    controller = MockBatchController()
    controller.set_empty()
    root = _load(view, controller)
    results.append({"case": "empty-minimum", **_save(view, "empty_zh_900x640.png")})

    controller = MockBatchController()
    root = _load(view, controller)
    queue = _find(root, "batchTaskQueue")
    # Index 2 is the first review-pending row and therefore exposes both
    # selection and inline-edit actions after the real checkbox click.
    first_card = _delegate_at(view, queue, 2)
    checkbox = _find(first_card, "taskCheckBox")
    _click(view, checkbox)
    if controller.selectedCount != 1:
        raise AssertionError("native checkbox click did not select exactly one task")
    results.append({"case": "mixed-selected-click", **_save(view, "mixed_selected_zh_900x640.png")})

    edit_button = _find(first_card, "inlineEditButton")
    _click(view, edit_button)
    first_card = _delegate_at(view, queue, 2)
    field = _find(first_card, "inlineNameField")
    model = controller.tasksModel
    editing = model.data(model.index(2, 0), model.isEditingRole)
    if not editing or not field.isVisible():
        raise AssertionError(
            f"native edit click did not expose input: editing={editing!r}, "
            f"fieldVisible={field.isVisible()}, geometry={field.width()}x{field.height()}"
        )
    _click(view, field)
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for key in (Qt.Key.Key_A, Qt.Key.Key_Less, Qt.Key.Key_B,
                Qt.Key.Key_Greater, Qt.Key.Key_C):
        QTest.keyClick(view, key)
    QTest.keyClick(view, Qt.Key.Key_Return)
    QTest.qWait(80)
    app.processEvents()
    first_card = _delegate_at(view, queue, 2)
    error = _find(first_card, "inlineValidationError")
    if not error.isVisible() or error.property("text") != "文件名包含非法字符":
        raise AssertionError(f"native inline validation not visible/localized: {error.property('text')!r}")
    results.append({"case": "inline-error-click", **_save(view, "inline_error_click_zh_900x640.png")})

    controller.cancelInlineEdit("m1-002")
    queue = _find(root, "batchTaskQueue")
    queue.setProperty("contentY", max(0.0, float(queue.property("contentHeight")) - queue.height()))
    QTest.qWait(80)
    app.processEvents()
    if float(queue.property("contentY")) <= 0:
        raise AssertionError("task queue did not scroll")
    results.append({"case": "scrolled-bottom", **_save(view, "scrolled_bottom_zh_900x640.png")})

    font = QFontInfo(app.font())
    cjk = _cjk_probe(app)
    if warnings:
        raise AssertionError("QML warnings:\n" + "\n".join(warnings))
    if not cjk["passed"]:
        raise AssertionError("CJK glyph probe failed")
    if len({row["sha256"] for row in results}) != len(results):
        raise AssertionError("distinct M8 native states produced duplicate pixels")
    manifest = {
        "platform": QApplication.platformName().lower(),
        "font_requested": "Microsoft YaHei UI",
        "font_actual": font.family(),
        "qml_warnings": warnings,
        "cjk": cjk,
        "real_mouse_clicks": ["taskCheckBox", "inlineEditButton", "inlineNameField"],
        "cases": results,
    }
    (OUTPUT / "m8-native-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    view.close()
    view.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
