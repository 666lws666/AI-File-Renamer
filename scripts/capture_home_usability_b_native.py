"""Native Windows evidence for B. Synthetic data, temporary stores, no golden writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from capture_user_guide_native import FakeCredentialStore, _find, _click
from src.qml_bootstrap import build_qml_runtime
from src.models.app_config import AppConfig
from src.controllers.mock_batch_controller import MockBatchController
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/screenshots/qa-current/home-usability-b"


def capture(rt, name, records):
    QTest.qWait(120)
    rt.assert_zero_warnings()
    image = rt.root.grabWindow()
    path = OUTPUT / (name + ".png")
    assert not image.isNull() and image.save(str(path))
    records.append(dict(file=path.name, width=image.width(), height=image.height(),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), warnings=list(rt.warnings)))


def geometry(root):
    for name in ("batchAddFilesButton", "batchAddFolderButton", "batchTargetDirectoryButton",
                 "batchApplySelectedButton", "batchStopButton", "batchClearButton"):
        item = _find(root, name)
        x = item.mapToScene(QPointF()).x()
        assert x >= 80 and x + item.width() <= root.width(), name
        needed = QFontMetricsF(item.property("font")).horizontalAdvance(item.property("text"))
        assert needed + item.property("leftPadding") + item.property("rightPadding") <= item.width() + 1, name
    for page in ("batch", "watch", "templates", "status", "preferences"):
        text = _find(root, "navLabel_" + page)
        assert text.property("contentWidth") <= text.width() + 1, page


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", choices=("zh-CN", "zh-HK", "en-US"), default="zh-CN")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "windows"
    app.setFont(QFont("Microsoft YaHei UI", 9))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for width, height in ((1000, 700), (900, 640)):
        prefix = f"{args.locale}-{width}"
        with tempfile.TemporaryDirectory(prefix="xuxia-home-b-") as temp:
            rt = build_qml_runtime(live_config=AppConfig(language=args.locale),
                                  config_file=Path(temp) / "settings.json",
                                  credential_store=FakeCredentialStore(),
                                  connection_test_service=lambda *_: None, usage_recorder=None)
            try:
                root = rt.root
                root.resize(QSize(width, height))
                root.show()
                assert QTest.qWaitForWindowExposed(root, 5000)
                QTest.qWait(80)
                geometry(root)
                capture(rt, prefix + "-empty", records)
                _click(root, "batchTemplateSelector")
                capture(rt, prefix + "-templates-popup", records)
                QTest.keyClick(root, Qt.Key_Escape)
                for page in ("watch", "templates", "preferences", "status"):
                    _click(root, "nav_" + page)
                    capture(rt, prefix + "-" + page, records)
                    if page == "preferences":
                        scroll = _find(root, "preferencesScroll")
                        flickable = scroll.property("contentItem")
                        assert flickable is not None
                        point = scroll.mapToScene(QPointF(scroll.width()/2, scroll.height()/2))
                        for _ in range(100):
                            if flickable.property("atYEnd"):
                                break
                            QTest.wheelEvent(root, point, QPoint(0, -120))
                            QTest.qWait(30)
                        QTest.wheelEvent(root, point, QPoint(), phase=Qt.ScrollEnd)
                        QTest.qWait(180)
                        assert flickable.property("atYEnd")
                        capture(rt, prefix + "-preferences-bottom", records)
                    if page == "status":
                        _click(root, "statusCloseButton")
                _click(root, "nav_batch")
                target_dir = Path(temp) / ("很长的中文演示目录" * 8)
                target_dir.mkdir()
                path = str(target_dir.resolve())
                rt.batch_controller.setTargetDirectory(path)
                QTest.qWait(80)
                target = _find(root, "batchTargetSummary")
                assert target.property("enabled") and path in target.property("text")
                target.forceActiveFocus(Qt.TabFocusReason)
                QTest.keyClick(root, Qt.Key_Space)
                QTest.qWait(80)
                assert _find(root, "batchToolbar").property("targetDetailsVisible")
                assert _find(root, "batchTargetFullPath").property("text") == path
                capture(rt, prefix + "-full-path", records)
                QTest.keyClick(root, Qt.Key_Escape)
                assert rt.batch_controller.targetDirectory == path
                rt.assert_zero_warnings()
            finally:
                rt.cleanup()
                QTest.qWait(60)
        # Separate synthetic queue; never send a real file to the analysis pipeline.
        with tempfile.TemporaryDirectory(prefix="xuxia-home-b-mock-") as temp:
            ctrl = MockBatchController()
            rt = build_qml_runtime(live_config=AppConfig(language=args.locale),
                                  config_file=Path(temp) / "settings.json",
                                  credential_store=FakeCredentialStore(), batch_controller=ctrl,
                                  connection_test_service=lambda *_: None, usage_recorder=None)
            try:
                root = rt.root
                root.resize(QSize(width, height)); root.show()
                assert QTest.qWaitForWindowExposed(root, 5000)
                _click(root, "batchSelectAll")
                assert ctrl.selectedCount == ctrl.totalCount == 20
                capture(rt, prefix + "-selected", records)
                _click(root, "batchSearchField")
                for digit in "2025":
                    QTest.keyClick(root, ord(digit))
                assert ctrl.searchText == "2025" and 0 < ctrl.visibleCount < ctrl.totalCount
                capture(rt, prefix + "-search", records)
                QTest.keyClick(root, Qt.Key_A, Qt.ControlModifier)
                QTest.keyClick(root, Qt.Key_Backspace)
                assert ctrl.searchText == ""
                _click(root, "batchStatusFilter")
                QTest.keyClick(root, Qt.Key_Home)
                QTest.keyClick(root, Qt.Key_Down)
                QTest.keyClick(root, Qt.Key_Return)
                assert ctrl.statusFilter == "pending"
                assert ctrl.visibleCount < ctrl.totalCount
                capture(rt, prefix + "-filtered", records)
                _click(root, "batchApplySelectedButton")
                assert ctrl.applyInProgress
                capture(rt, prefix + "-apply", records)
            finally:
                rt.cleanup()
                QTest.qWait(60)
    (OUTPUT / ("manifest-" + args.locale + ".json")).write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(platform=app.platformName(), locale=args.locale,
                         captures=len(records), warnings=0)))


if __name__ == "__main__":
    main()
