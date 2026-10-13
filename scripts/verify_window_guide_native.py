"""Ignored native Windows visual/interaction evidence for window + guide Gate."""
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
from PySide6.QtGui import QColor, QFont
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "tests" / "screenshots" / "qa-current" / "window-guide"


class FakeCredentialStore:
    def get(self, *_args): return None
    def set(self, *_args): return True
    def delete(self, *_args): return True


def _find(root, name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, name)
    if item is None:
        raise AssertionError(f"missing object: {name}")
    return item


def _click(root, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(100)
    QApplication.processEvents()


def _save(root, name: str) -> dict:
    image = root.grabWindow()
    path = OUTPUT / name
    if image.isNull() or not image.save(str(path)):
        raise RuntimeError(f"capture failed: {path}")
    data = path.read_bytes()
    return {"filename": name, "width": image.width(), "height": image.height(),
            "sha256": hashlib.sha256(data).hexdigest()}


def _edge_pixels_are(image, color: QColor) -> bool:
    width, height = image.width(), image.height()
    samples = (
        (0, 0), (width // 2, 0), (width - 1, 0),
        (0, height // 2), (width - 1, height // 2),
        (0, height - 1), (width // 2, height - 1), (width - 1, height - 1),
    )
    return all(image.pixelColor(x, y).name().casefold() == color.name().casefold()
               for x, y in samples)


def main() -> int:
    from src.controllers.mock_batch_controller import MockBatchController
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    app = QApplication.instance() or QApplication(sys.argv)
    if QApplication.platformName().lower() != "windows":
        raise RuntimeError("native Windows QPA required")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="xuxia-window-gate-") as temp:
        runtime = build_qml_runtime(
            live_config=AppConfig(language="zh_CN"),
            config_file=Path(temp) / "settings.json",
            credential_store=FakeCredentialStore(),
            batch_controller=MockBatchController(),
            connection_test_service=lambda *_: None,
            usage_recorder=None,
        )
        try:
            root = runtime.root
            boundary = _find(root, "windowBoundary")
            border_color = QColor(boundary.property("boundaryColor"))
            if border_color.name().casefold() != "#94a3b8":
                raise AssertionError(f"wrong boundary color: {border_color.name()}")
            if boundary.property("boundaryWidth") != 1 or boundary.isEnabled():
                raise AssertionError("boundary must be 1px and non-interactive")

            records = []
            for size, name in (((1000, 700), "normal-1000x700.png"),
                               ((900, 640), "normal-900x640.png")):
                root.showNormal(); root.resize(QSize(*size)); root.show()
                if not QTest.qWaitForWindowExposed(root, 5000):
                    raise RuntimeError("window was not exposed")
                QTest.qWait(120); QApplication.processEvents()
                if not boundary.isVisible():
                    raise AssertionError(f"boundary hidden at normal {size}")
                image = root.grabWindow()
                if not _edge_pixels_are(image, border_color):
                    raise AssertionError(f"continuous #94A3B8 edge check failed at {size}")
                records.append(_save(root, name))

            # Five navigation entries use real mouse clicks and must route visibly.
            router = _find(root, "pageRouter")
            navigation = []
            for page in ("watch", "templates", "preferences", "batch"):
                _click(root, _find(root, f"nav_{page}"))
                actual = router.property("currentPage")
                if actual != page:
                    raise AssertionError(f"nav_{page} routed to {actual!r}")
                navigation.append({"target": page, "actual": actual})
            _click(root, _find(root, "nav_status"))
            if not _find(root, "systemStatusModal").isVisible():
                raise AssertionError("status navigation did not open modal")
            navigation.append({"target": "status", "actual": "modal-visible"})

            # Real click on maximize hit rectangle by fixed title-bar geometry.
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier,
                             QPointF(root.width() - 54, 16).toPoint())
            QTest.qWait(250); QApplication.processEvents()
            if root.visibility() != root.Visibility.Maximized or boundary.isVisible():
                raise AssertionError("maximize click did not hide boundary")
            records.append(_save(root, "maximized.png"))
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier,
                             QPointF(root.width() - 54, 16).toPoint())
            QTest.qWait(250); QApplication.processEvents()
            if root.visibility() == root.Visibility.Maximized or not boundary.isVisible():
                raise AssertionError("restore click did not restore boundary")
            records.append(_save(root, "restored.png"))

            # Minimize uses the real hit target; restore through OS API so the gate can continue.
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier,
                             QPointF(root.width() - 90, 16).toPoint())
            QTest.qWait(200); QApplication.processEvents()
            if root.visibility() != root.Visibility.Minimized:
                raise AssertionError("minimize hit target did not minimize")
            root.showNormal(); QTest.qWait(150); QApplication.processEvents()

            # Drag handler: a short real press/move/release must not be intercepted by boundary.
            start = QPointF(260, 16).toPoint(); end = QPointF(290, 32).toPoint()
            QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
            QTest.mouseMove(root, end, delay=80)
            QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, end)
            QTest.qWait(100); QApplication.processEvents()
            runtime.assert_zero_warnings()
            payload = {
                "platform": QApplication.platformName().lower(),
                "border": {"width": 1, "color": border_color.name(),
                           "non_interactive": not boundary.isEnabled()},
                "navigation": navigation,
                "real_mouse": ["five navigation entries", "maximize", "restore", "minimize", "title drag"],
                "qml_warnings": list(runtime.warnings),
                "captures": records,
            }
            (OUTPUT / "native-window-manifest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        finally:
            runtime.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
