"""Capture M8 page evidence through real Windows clicks.

All output is confined to the ignored ``tests/screenshots/qa-current/m8/pages``
directory. The script uses temporary configuration, a fake credential store,
and a fake connection service; it performs no network or credential-manager I/O
and never updates formal goldens.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

for key in list(os.environ):
    if key.startswith("QT_QPA_PLATFORM"):
        del os.environ[key]

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "tests" / "screenshots" / "qa-current" / "m8" / "pages"


class FakeCredentialStore:
    def get(self, _service, _account):
        return None

    def set(self, _service, _account, _value):
        return True

    def delete(self, _service, _account):
        return True


def _find(root, name: str) -> QQuickItem:
    item = root.findChild(QQuickItem, name)
    if item is None:
        raise RuntimeError(f"missing QML object: {name}")
    return item


def _click(root, name: str) -> None:
    item = _find(root, name)
    point = item.mapToScene(item.boundingRect().center()).toPoint()
    window = item.window()
    if window is None:
        raise RuntimeError(f"{name}: item has no QQuickWindow")
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        point,
    )
    QTest.qWait(25)
    QApplication.processEvents()
    router = root.findChild(QQuickItem, "pageRouter")
    if router is not None:
        deadline = time.monotonic() + 5.0
        while bool(router.property("busy")) and time.monotonic() < deadline:
            QTest.qWait(25)
            QApplication.processEvents()
        if bool(router.property("busy")):
            raise TimeoutError(f"{name}: PageRouter transition did not finish")


def _visible(root, name: str) -> bool:
    return bool(_find(root, name).property("visible"))


def _capture(case_id: str, size: tuple[int, int], actions, assertions):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    with tempfile.TemporaryDirectory(prefix="xuxia-m8-pages-") as temp:
        root_dir = Path(temp)
        runtime = build_qml_runtime(
            live_config=AppConfig(language="zh_CN"),
            config_file=root_dir / "settings.json",
            credential_store=FakeCredentialStore(),
            batch_controller=None,
            connection_test_service=lambda *_: None,
            usage_recorder=None,
        )
        try:
            runtime.root.resize(QSize(*size))
            runtime.root.show()
            if not QTest.qWaitForWindowExposed(runtime.root, 5000):
                raise RuntimeError(f"{case_id}: native window was not exposed")
            QApplication.processEvents()
            for action in actions:
                _click(runtime.root, action)
            assertion_records = []
            for name, expected in assertions:
                actual = _visible(runtime.root, name)
                if actual is not expected:
                    raise AssertionError(
                        f"{case_id}: {name}.visible={actual!r}, expected {expected!r}"
                    )
                assertion_records.append(
                    {"object": name, "property": "visible", "actual": actual, "expected": expected}
                )
            runtime.assert_zero_warnings()
            QApplication.processEvents()
            image = runtime.root.grabWindow()
            if image.isNull():
                raise RuntimeError(f"{case_id}: grabWindow returned null")
            path = OUTPUT / f"{case_id}-{size[0]}x{size[1]}.png"
            if not image.save(str(path)):
                raise RuntimeError(f"{case_id}: failed to save {path}")
            data = path.read_bytes()
            return {
                "case": case_id,
                "size": list(size),
                "path": path.name,
                "platform": QApplication.platformName().lower(),
                "font": QApplication.font().family(),
                "warnings": list(runtime.warnings),
                "assertions": assertion_records,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        finally:
            runtime.root.close()
            QTest.qWait(100)
            QApplication.processEvents()
            runtime.cleanup()
            QTest.qWait(100)
            QApplication.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    if QApplication.platformName().lower() != "windows":
        raise RuntimeError(f"expected Windows QPA, got {QApplication.platformName()!r}")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    OUTPUT.mkdir(parents=True, exist_ok=True)

    cases = (
        ("watch-form", (1000, 700), ("nav_watch", "addWatchButton"), (("watchPage", True), ("watchForm", True))),
        ("watch-empty", (1000, 700), ("nav_watch",), (("watchPage", True), ("watchEmptyState", True))),
        ("watch-form", (900, 640), ("nav_watch", "addWatchButton"), (("watchPage", True), ("watchForm", True))),
        ("templates-list", (1000, 700), ("nav_templates",), (("templatesPage", True), ("templateList", True))),
        ("vocabulary-tab", (1000, 700), ("nav_templates", "vocabularyTabButton"), (("templatesPage", True), ("vocabularyTab", True))),
        ("preferences-top", (1000, 700), ("nav_preferences",), (("preferencesPage", True), ("preferencesScroll", True))),
        ("preferences-top", (900, 640), ("nav_preferences",), (("preferencesPage", True), ("preferencesScroll", True))),
    )
    selected = os.environ.get("M8_PAGE_CASE", "")
    if selected:
        cases = tuple(case for case in cases if f"{case[0]}-{case[1][0]}x{case[1][1]}" == selected)
        if len(cases) != 1:
            raise ValueError(f"unknown M8_PAGE_CASE: {selected}")
    manifest = [_capture(*case) for case in cases]
    shas = [item["sha256"] for item in manifest]
    if len(shas) != len(set(shas)):
        raise AssertionError("distinct M8 page cases produced duplicate images")
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
