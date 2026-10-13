"""M1 Task 2: Navigation tests."""
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .conftest import make_handle, QML_DIR


@pytest.fixture
def global_qt_problems():
    """StackView property errors use global Qt messages, not engine.warnings."""
    messages = []
    def capture(kind, context, message):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append((kind.name, context.file, context.line, message))
    previous = qInstallMessageHandler(capture)
    try:
        yield messages
    finally:
        qInstallMessageHandler(previous)


def _click_named(handle, name):
    button = handle.root.findChild(QObject, name)
    assert button is not None and button.property("visible") and button.property("enabled")
    point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
    QTest.mouseClick(handle.root, Qt.LeftButton, Qt.NoModifier, point)
    QApplication.processEvents()

def test_main_loads_and_shows_batch():
    h = make_handle(QML_DIR / "main.qml")
    try: assert h.root is not None
    finally: h.cleanup()

def test_five_nav_entries():
    h = make_handle(QML_DIR / "main.qml")
    try:
        # NavBar has 5 NavBtn with objectNames
        import re
        found = set()
        def find(obj):
            n = obj.objectName()
            if n.startswith("nav_"): found.add(n)
            for c in obj.children(): find(c)
        find(h.root)
        assert len(found) == 5, f"Expected 5 nav entries, got {len(found)}: {found}"
        h.assert_zero_warnings()
    finally: h.cleanup()


def test_initial_batch_has_no_global_qt_property_error(global_qt_problems):
    h = make_handle(QML_DIR / "main.qml")
    try:
        router = h.root.findChild(QObject, "pageRouter")
        assert router.property("currentPage") == "batch"
        assert router.property("currentItem") is not None
        assert router.property("currentItem").metaObject().indexOfProperty("pageId") == -1
        h.assert_zero_warnings()
    finally:
        h.cleanup()
    assert not global_qt_problems, global_qt_problems


def test_real_five_nav_and_preferences_batch_roundtrip_has_no_global_qt_errors(global_qt_problems):
    h = make_handle(QML_DIR / "main.qml")
    try:
        router = h.root.findChild(QObject, "pageRouter")
        for page in ("batch", "watch", "templates"):
            _click_named(h, "nav_" + page)
            assert router.property("currentPage") == page
        _click_named(h, "nav_status")
        assert h.root.findChild(QObject, "systemStatusModal").property("visible")
        _click_named(h, "statusCloseButton")
        assert not h.root.findChild(QObject, "systemStatusModal").property("visible")
        _click_named(h, "nav_preferences")
        assert router.property("currentPage") == "preferences"
        item = router.property("currentItem")
        assert item.objectName() == "preferencesPage"
        assert item.metaObject().indexOfProperty("pageId") == -1
        _click_named(h, "nav_batch")
        assert router.property("currentPage") == "batch"
        h.assert_zero_warnings()
    finally:
        h.cleanup()
    assert not global_qt_problems, global_qt_problems


def test_declaring_routes_keep_page_ids_and_controller_references(global_qt_problems):
    h = make_handle(QML_DIR / "main.qml")
    try:
        router = h.root.findChild(QObject, "pageRouter")
        for page in ("watch", "templates", "status", "unknown-route"):
            router.navigate(page)
            QApplication.processEvents()
            item = router.property("currentItem")
            assert router.property("currentPage") == page
            assert item.property("pageId") == page
            if page in ("watch", "templates"):
                name = "watchController" if page == "watch" else "templateController"
                assert item.property("ctrl") is router.property(name)
        router.navigate("preferences")
        QApplication.processEvents()
        item = router.property("currentItem")
        assert item.property("router") is router
        for name in ("processingCoordinator", "resourcesController", "templateController"):
            assert item.property(name) is router.property(name)
        assert item.property("ctrl") is router.property("settingsController")
        h.assert_zero_warnings()
    finally:
        h.cleanup()
    assert not global_qt_problems, global_qt_problems
