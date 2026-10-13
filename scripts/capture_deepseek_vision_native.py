"""Offline native model-selection evidence; no real credentials or network."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from scripts import capture_batch_toolbar_native as capture
from scripts.capture_user_guide_native import _click, _find, _scroll_into_view, _runtime
from src.controllers.mock_batch_controller import MockBatchController


def main():
    app = QApplication.instance() or QApplication([])
    assert app.platformName() == "windows"
    app.setFont(QFont("Microsoft YaHei UI", 10))
    capture.OUTPUT = ROOT / "tests/screenshots/qa-current/deepseek-v41"
    capture.OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = []
    with tempfile.TemporaryDirectory(prefix="xuxia-deepseek-visual-") as temp:
        runtime = _runtime(Path(temp), batch=MockBatchController())
        try:
            root = runtime.root
            root.resize(QSize(1000, 700))
            root.show()
            QTest.qWait(200)
            _click(root, "nav_preferences")
            _scroll_into_view(root, "preferencesScroll", "providerSettingsCard")
            card = _find(root, "providerSettingsCard")
            pos, error = QQmlExpression(runtime.engine.rootContext(), card,
                "actionButtonPos('deepseek', 'edit')").evaluate()
            assert not error
            xy = pos.toVariant()
            point = root.mapFromGlobal(QPoint(round(xy[0]), round(xy[1])))
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
            QTest.qWait(100)
            form = _find(root, "providerForm")
            assert form.isVisible()
            for locale, width, height in (
                (language, w, h) for language in ("zh-CN", "en-US", "zh-HK")
                for w, h in ((1000, 700), (900, 640))
            ):
                runtime.i18n.set_locale(locale)
                root.resize(QSize(width, height))
                QTest.qWait(100)
                _scroll_into_view(root, "preferencesScroll", "pfDeepSeekModels")
                _click(root, "pfDeepSeekModels")
                cases.append(capture._capture(runtime, f"options-{locale}-{width}.png"))
                QTest.keyClick(root, Qt.Key_Home)
                QTest.keyClick(root, Qt.Key_Return)
                QTest.qWait(150)
                assert form.property("model") == "deepseek-flash"
                assert form.property("capVision") is True
                assert "V4.1" in _find(root, "pfDeepSeekModelHint").property("text")
                hint = _find(root, "pfDeepSeekModelHint")
                from PySide6.QtCore import QPointF
                right = hint.mapToScene(QPointF(hint.width(), 0)).x()
                assert right <= width, (right, width, hint.width(), form.width(), card.width(),
                    _find(root, "preferencesScroll").width(), card.parentItem().width(),
                    _find(root, "preferencesPage").width())
                cases.append(capture._capture(runtime, f"flash-{locale}-{width}.png"))
                _click(root, "pfDeepSeekModels")
                QTest.keyClick(root, Qt.Key_Home)
                QTest.keyClick(root, Qt.Key_Down)
                QTest.keyClick(root, Qt.Key_Return)
                QTest.qWait(100)
                assert form.property("model") == "deepseek-v4-pro"
                assert form.property("capVision") is False
                cases.append(capture._capture(runtime, f"pro-{locale}-{width}.png"))
                for index, alias in ((2, "deepseek-v4-flash-vision-exp"), (3, "deepseek-v4-flash")):
                    _click(root, "pfDeepSeekModels")
                    QTest.keyClick(root, Qt.Key_Home)
                    for _ in range(index):
                        QTest.keyClick(root, Qt.Key_Down)
                    QTest.keyClick(root, Qt.Key_Return)
                    QTest.qWait(100)
                    assert form.property("model") == alias
                    assert form.property("capVision") is True
                    cases.append(capture._capture(runtime, f"alias{index}-{locale}-{width}.png"))
            assert not (Path(temp) / "settings.json").exists()
            runtime.assert_zero_warnings()
            report = {"platform": app.platformName(), "qml_warnings": runtime.warnings,
                      "real_click_selection": True, "saved_user_config": False, "cases": cases}
            (capture.OUTPUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))
        finally:
            runtime.cleanup()


if __name__ == "__main__":
    main()
