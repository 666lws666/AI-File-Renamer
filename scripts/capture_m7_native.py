"""Capture M7 native-Windows QA evidence without network or real credentials.

Outputs are intentionally confined to tests/screenshots/qa-current/m7, which
is ignored by Git.  This script never updates formal goldens.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QML_DIR = ROOT / "src" / "ui_qml"
OUTPUT = ROOT / "tests" / "screenshots" / "qa-current" / "m7"


class FakeCredentialStore:
    def get(self, _service, _account): return None
    def set(self, _service, _account, _value): return True
    def delete(self, _service, _account): return True


def _status_controller(levels):
    from src.controllers.status_controller import ComponentStatus, StatusController

    names = {
        "local": "status.component.local",
        "text": "status.component.text",
        "vision": "status.component.vision",
    }
    def detail(key):
        level = levels[key]
        if level.value == "checking":
            return "status.detail.checking"
        if level.value == "unavailable":
            if key == "local": return "status.detail.localUnavailable"
            if key == "text": return "status.detail.textUnsupported"
            return "status.detail.visionUnsupported"
        return "status.detail.localReady" if key == "local" else "status.detail.available"

    ctrl = StatusController({
        key: (lambda key=key: ComponentStatus(
            key, names[key], levels[key], detail(key),
        )) for key in ("local", "text", "vision")
    })
    ctrl.check_all(force=True)
    return ctrl


def _find(root, name):
    obj = root.findChild(QQuickItem, name)
    if obj is None:
        raise RuntimeError(f"missing object: {name}")
    return obj


def _capture_status(app, output, case_id, levels, size):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    with tempfile.TemporaryDirectory(prefix="xuxia-m7-") as temp:
        ctrl = _status_controller(levels)
        runtime = build_qml_runtime(
            live_config=AppConfig(),
            config_file=Path(temp) / "settings.json",
            credential_store=FakeCredentialStore(),
            usage_recorder=None,
            template_controller=None,
            watch_controller=None,
            status_controller=ctrl,
            diagnostics_service=None,
        )
        try:
            runtime.root.resize(QSize(*size))
            app.processEvents()
            nav = _find(runtime.root, "nav_status")
            point = nav.mapToScene(nav.boundingRect().center()).toPoint()
            QTest.mouseClick(runtime.root, Qt.LeftButton, pos=point)
            app.processEvents()
            if not _find(runtime.root, "systemStatusModal").property("visible"):
                raise AssertionError("real status navigation click did not open modal")
            runtime.assert_zero_warnings()
            image = runtime.root.grabWindow()
            path = output / f"{case_id}-{size[0]}x{size[1]}.png"
            if image.isNull() or not image.save(str(path)):
                raise RuntimeError(f"capture failed: {path}")
            return {"case": case_id, "size": list(size), "path": path.name,
                    "warnings": [], "overall": ctrl.overall}
        finally:
            runtime.cleanup()


def _capture_wrapper(app, output, case_id, body, size=(1000, 700)):
    from PySide6.QtQuick import QQuickView
    from src.utils.i18n.service import I18n

    qml = f'''import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ui_qml 1.0
Rectangle {{
    width: {size[0]}; height: {size[1]}; color: DesignTokens.bgSecondary
    {body}
}}
'''
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    engine = view.engine()
    engine.addImportPath(str(ROOT / "src"))
    warnings = []
    engine.warnings.connect(lambda msgs: warnings.extend(m.toString() for m in msgs))
    i18n = I18n()
    i18n.set_locale("zh-CN")
    engine.rootContext().setContextProperty("i18n", i18n)
    with tempfile.TemporaryDirectory(prefix="xuxia-m7-qml-") as temp:
        qml_path = Path(temp) / "evidence.qml"
        qml_path.write_text(qml, encoding="utf-8")
        view.setSource(QUrl.fromLocalFile(str(qml_path)))
        view.resize(*size)
        view.show()
        app.processEvents()
        root = view.rootObject()
        if root is None:
            raise RuntimeError("null M7 evidence root: status=" + str(view.status()))
        if warnings:
            raise AssertionError("QML warnings:\n" + "\n".join(warnings))
        image = view.grabWindow()
        path = output / f"{case_id}-{size[0]}x{size[1]}.png"
        if image.isNull() or not image.save(str(path)):
            raise RuntimeError(f"capture failed: {path}")
    view.close(); view.deleteLater(); app.processEvents()
    return {"case": case_id, "size": list(size), "path": path.name,
            "warnings": []}


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    from src.controllers.status_controller import StatusLevel as S

    cases = [
        ("status-ready", {"local": S.READY, "text": S.READY, "vision": S.READY}, (1000, 700)),
        ("status-checking", {"local": S.CHECKING, "text": S.CHECKING, "vision": S.CHECKING}, (1000, 700)),
        ("status-attention-text-only", {"local": S.READY, "text": S.READY, "vision": S.UNAVAILABLE}, (1000, 700)),
        ("status-unavailable", {"local": S.UNAVAILABLE, "text": S.UNAVAILABLE, "vision": S.UNAVAILABLE}, (1000, 700)),
        ("status-attention-text-only", {"local": S.READY, "text": S.READY, "vision": S.UNAVAILABLE}, (900, 640)),
    ]
    manifest = [_capture_status(app, OUTPUT, *case) for case in cases]
    manifest.append(_capture_wrapper(app, OUTPUT, "errors-file-batch-toast", '''
        ColumnLayout {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
            anchors.margins: 80; spacing: 18
            Text { text: "错误与恢复"; font.family: DesignTokens.fontFamily; font.pixelSize: 22; font.bold: true; color: DesignTokens.textPrimary }
            FileCardError { Layout.fillWidth: true; message: "文件正被其他程序占用"; retryable: true }
            BatchError { Layout.fillWidth: true; successCount: 7; failureCount: 2; retryable: true }
            AppToast { Layout.alignment: Qt.AlignRight; visible: true; message: "网络暂不可用，已停止自动重试"; severity: "warning" }
        }
    '''))
    manifest.append(_capture_wrapper(app, OUTPUT, "blocking-error", '''
        Text { anchors.centerIn: parent; text: "主工作区"; font.family: DesignTokens.fontFamily; font.pixelSize: 22; color: DesignTokens.textSecondary }
        BlockingModal {
            anchors.fill: parent; visible: true
            title: "无法继续"
            message: "Undo 历史损坏，已阻止新的应用和撤销操作。原历史已隔离，未被静默删除。"
            actionText: "查看恢复选项"
        }
    '''))
    manifest.append(_capture_wrapper(app, OUTPUT, "diagnostics-preview", '''
        DiagnosticsDialog { anchors.fill: parent; visible: true }
    '''))
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
