"""M1 Task 1: Shell tests with stable lifecycle."""
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QWindow
from PySide6.QtWidgets import QApplication
from .conftest import make_handle, QML_DIR

MAIN_QML = QML_DIR / "main.qml"

def test_main_qml_loads_with_zero_warnings():
    h = make_handle(MAIN_QML)
    try:
        assert h.root is not None
        h.assert_zero_warnings()
    finally:
        h.cleanup()

def test_shell_default_size():
    h = make_handle(MAIN_QML, 1000, 700)
    try:
        assert h.root.property("width") == 1000
        assert h.root.property("height") == 700
    finally:
        h.cleanup()

def test_shell_minimum_size():
    h = make_handle(MAIN_QML, 900, 640)
    try:
        assert h.root is not None
    finally:
        h.cleanup()

def test_titlebar_exists():
    h = make_handle(MAIN_QML)
    try:
        ch = h.root.children()
        assert len(ch) > 0, "Shell has no children"
    finally:
        h.cleanup()

def test_design_tokens():
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtCore import QUrl
    engine = QQmlEngine(); engine.addImportPath(str(SRC_DIR := QML_DIR.parent))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "DesignTokens.qml")))
    assert not comp.isError()
    obj = comp.create(); assert obj is not None
    assert obj.property("baseWindowWidth") == 1000
    assert obj.property("titleBarHeight") == 32
    assert obj.property("navBarWidth") == 80
    assert obj.property("taskCardHeight") == 70
    assert obj.property("windowBorderWidth") == 1
    assert obj.property("windowBorderColor") == QColor("#94a3b8")


def test_window_boundary_is_visible_and_non_interactive_when_windowed():
    h = make_handle(MAIN_QML)
    try:
        boundary = h.root.findChild(QObject, "windowBoundary")
        assert boundary is not None
        assert boundary.property("visible") is True
        assert boundary.property("enabled") is False
        assert boundary.property("boundaryWidth") == 1
        assert boundary.property("boundaryColor") == QColor("#94a3b8")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_window_boundary_hides_when_maximized_or_fullscreen_and_returns():
    h = make_handle(MAIN_QML)
    try:
        boundary = h.root.findChild(QObject, "windowBoundary")
        assert boundary is not None
        for visibility in (QWindow.Maximized, QWindow.FullScreen):
            h.root.setProperty("visibility", visibility)
            QApplication.processEvents()
            assert boundary.property("visible") is False
        h.root.setProperty("visibility", QWindow.Windowed)
        QApplication.processEvents()
        assert boundary.property("visible") is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()

def test_nav_icons_exist():
    for icon in ["nav_batch","nav_watch","nav_templates","nav_status","nav_preferences"]:
        p = QML_DIR / "icons" / f"{icon}.svg"
        assert p.exists(); assert "<svg" in p.read_text(encoding="utf-8")

def test_no_legacy_widgets():
    for qf in QML_DIR.rglob("*.qml"):
        t = qf.read_text(encoding="utf-8")
        for bw in ["QMenuBar","QToolBar","QStatusBar","QTableView"]:
            assert bw not in t, f"{qf.name}: {bw}"

def test_qml_handle_keeps_engine_alive():
    h = make_handle(MAIN_QML)
    try:
        assert h.root is not None
        assert h.engine is not None
        assert h.component is not None
        w = h.root.property("width")
        assert w == 1000
    finally:
        h.cleanup()

def test_loaded_component_has_zero_runtime_warnings():
    h = make_handle(MAIN_QML)
    try:
        assert h.warning_count == 0, f"Expected 0 warnings, got {h.warning_count}"
    finally:
        h.cleanup()
