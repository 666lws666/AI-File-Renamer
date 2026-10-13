"""M1/M6 QML test fixtures — pre-creation injection, stable lifecycle, warning capture."""
import os, sys
from pathlib import Path
from threading import get_ident
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Property, QObject, QUrl, QCoreApplication, QEvent
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

QML_DIR = Path(__file__).parent.parent.parent / "src" / "ui_qml"
SRC_DIR = QML_DIR.parent
ICONS_DIR = QML_DIR / "icons"


class DesignTokensProxy(QObject):
    """Python mirror of DesignTokens.qml — registered as a context property
    so cards loaded BY PATH (which do not import ui_qml 1.0) resolve
    ``DesignTokens.*`` with zero QML warnings."""

    baseWindowWidth = Property(int, lambda self: 1000, constant=True)
    baseWindowHeight = Property(int, lambda self: 700, constant=True)
    minimumWindowWidth = Property(int, lambda self: 900, constant=True)
    minimumWindowHeight = Property(int, lambda self: 640, constant=True)
    titleBarHeight = Property(int, lambda self: 32, constant=True)
    navBarWidth = Property(int, lambda self: 80, constant=True)
    taskCardHeight = Property(int, lambda self: 70, constant=True)
    spacingXs = Property(int, lambda self: 4, constant=True)
    spacingSm = Property(int, lambda self: 8, constant=True)
    spacingMd = Property(int, lambda self: 12, constant=True)
    spacingLg = Property(int, lambda self: 16, constant=True)
    spacingXl = Property(int, lambda self: 24, constant=True)
    radiusSm = Property(int, lambda self: 4, constant=True)
    radiusMd = Property(int, lambda self: 8, constant=True)
    radiusLg = Property(int, lambda self: 12, constant=True)
    bgPrimary = Property(str, lambda self: "#ffffff", constant=True)
    bgSecondary = Property(str, lambda self: "#f8fafc", constant=True)
    bgNavSelected = Property(str, lambda self: "#e8ecf0", constant=True)
    borderLight = Property(str, lambda self: "#e2e8f0", constant=True)
    textPrimary = Property(str, lambda self: "#1e293b", constant=True)
    textSecondary = Property(str, lambda self: "#64748b", constant=True)
    btnPrimary = Property(str, lambda self: "#0f172a", constant=True)
    btnPrimaryText = Property(str, lambda self: "#ffffff", constant=True)
    accentSuccess = Property(str, lambda self: "#16a34a", constant=True)
    accentError = Property(str, lambda self: "#dc2626", constant=True)
    accentWarning = Property(str, lambda self: "#ea580c", constant=True)
    accentInfo = Property(str, lambda self: "#2563eb", constant=True)
    fontFamily = Property(str, lambda self: "Microsoft YaHei UI", constant=True)
    fontSizeSm = Property(int, lambda self: 11, constant=True)
    fontSizeMd = Property(int, lambda self: 13, constant=True)
    fontSizeLg = Property(int, lambda self: 15, constant=True)
    fontSizeXl = Property(int, lambda self: 18, constant=True)
    minClickSize = Property(int, lambda self: 24, constant=True)


@pytest.fixture(scope="session", autouse=True)
def _qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield

class QmlTestHandle:
    """Creates QML root with pre-injected i18n and controller, captures warnings.

    When a controller is passed, the component is hosted in a QQuickView
    (real window) so MouseArea clicks can be delivered via QTest.mouseClick,
    and the controller is injected as the root's ``ctrl`` property.  Without
    a controller the component is created engine-only.
    """
    def __init__(self, qml_path, width=1000, height=700, controller=None, locale="zh-CN"):
        self.warnings = []
        # The engine's connection must not retain the handle itself.
        self._warning_callback = lambda msgs, warnings=self.warnings: warnings.extend(
            m.toString() for m in msgs
        )
        # A saved Qt thread wrapper can be invalidated while its Python thread
        # continues executing; it is not a stable authorization token.
        self._creator_thread_ident = get_ident()
        self._cleaned = False
        self._host_view = None
        self.component = None
        # Inject before component creation
        from src.utils.i18n.service import I18n
        self.i18n = I18n()
        if locale != self.i18n.locale: self.i18n.set_locale(locale)
        # Keep a strong Python reference — GC of the wrapper breaks QML
        # property dispatch for the injected object.
        self._design_tokens = DesignTokensProxy()
        from src.controllers.mock_batch_controller import MockBatchController
        self._injected_ctrl = controller
        self.controller = controller if controller is not None else MockBatchController()

        from PySide6.QtQuick import QQuickView, QQuickWindow
        # A Window-rooted component (e.g. main.qml / ApplicationWindow) must
        # NOT be hosted inside a QQuickView — it creates a broken window-in-
        # window and the root object comes back null.
        is_window_root = "ApplicationWindow" in Path(qml_path).read_text(
            encoding="utf-8"
        )[:2000]
        if self._injected_ctrl is not None and not is_window_root:
            # Host the card in a real window (QQuickView).  Its rootObject()
            # is QQuickItem-typed, so window()/mapToScene() work and
            # QTest.mouseClick can reach MouseAreas.
            self._host_view = QQuickView()
            self._host_view.setResizeMode(QQuickView.SizeRootObjectToView)
            self.engine = self._host_view.engine()
            self.engine.addImportPath(str(SRC_DIR))
            self.engine.warnings.connect(self._warning_callback)
            self.engine.rootContext().setContextProperty("i18n", self.i18n)
            self.engine.rootContext().setContextProperty("DesignTokens", self._design_tokens)
            self.engine.rootContext().setContextProperty("batchController", self.controller)
            self._host_view.setInitialProperties({"ctrl": self._injected_ctrl})
            self._host_view.setSource(QUrl.fromLocalFile(str(qml_path)))
            self._host_view.resize(width, height)
            self._host_view.show()
            self.root = self._host_view.rootObject()
            if self.root is None:
                raise RuntimeError(f"Null root from {qml_path.name}")
            QApplication.processEvents()
            return

        self.engine = QQmlEngine()
        self.engine.addImportPath(str(SRC_DIR))
        self.engine.warnings.connect(self._warning_callback)
        self.engine.rootContext().setContextProperty("i18n", self.i18n)
        self.engine.rootContext().setContextProperty("DesignTokens", self._design_tokens)
        self.engine.rootContext().setContextProperty("batchController", self.controller)
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(qml_path)))
        if self.component.isError():
            errs = "\n".join(e.toString() for e in self.component.errors())
            raise RuntimeError(f"QML errors in {qml_path.name}:\n{errs}")
        self.root = self.component.create()
        if self.root is None: raise RuntimeError(f"Null root from {qml_path.name}")
        self.root.setProperty("width", width); self.root.setProperty("height", height)
        QApplication.processEvents()

    @property
    def warning_count(self): return len(self.warnings)
    def assert_zero_warnings(self):
        if self.warnings:
            pytest.fail(f"{len(self.warnings)} QML warning(s):\n" + "\n".join(self.warnings[:20]))

    def cleanup(self):
        """Destroy native UI before releasing any of its context holders."""
        if get_ident() != self._creator_thread_ident:
            raise RuntimeError("QML fixture cleanup must run on its owner thread")
        if self._cleaned:
            return
        if self.engine is not None and isValid(self.engine):
            # Query current native affinity from the live engine, not a saved
            # QThread wrapper or the Python currentThread() adapter's identity.
            owner = self.engine.thread()
            if owner is None or not isValid(owner) or not owner.isCurrentThread():
                raise RuntimeError("QML fixture cleanup must run on its owner thread")

        def dispose(obj):
            if obj is not None and isValid(obj):
                obj.deleteLater()
                # processEvents alone does not drain DeferredDelete in pytest.
                QCoreApplication.sendPostedEvents(obj, QEvent.DeferredDelete)
                if isValid(obj):
                    raise RuntimeError("QML fixture native object was not destroyed")

        from PySide6.QtQuick import QQuickWindow
        if self._host_view is not None and isValid(self._host_view):
            self._host_view.close()
        elif self.root is not None and isValid(self.root) and isinstance(self.root, QQuickWindow):
            self.root.close()
        # Keep the warning connection and i18n/design/controller alive throughout
        # actual root destruction, including Component.onDestruction handlers.
        dispose(self.root)
        if self._host_view is not None:
            # QQuickView owns its engine: only destroy the owning view.
            dispose(self._host_view)
        else:
            dispose(self.component)
            dispose(self.engine)
        QApplication.processEvents()
        self.component = None
        self.engine = None
        self.root = None
        self._host_view = None
        self._warning_callback = None
        self.i18n = None
        self._design_tokens = None
        self.controller = None
        self._injected_ctrl = None
        self._cleaned = True

def make_handle(path, w=1000, h=700, ctrl=None, loc="zh-CN"):
    return QmlTestHandle(path, w, h, controller=ctrl, locale=loc)
