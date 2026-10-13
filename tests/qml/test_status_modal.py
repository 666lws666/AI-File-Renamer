"""M7 System Status modal contracts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.controllers.status_controller import ComponentStatus, StatusController, StatusLevel
from tests.qml.conftest import make_handle


QML_DIR = Path(__file__).parents[2] / "src" / "ui_qml"


def _find(root: QObject, name: str) -> QObject:
    obj = root.findChild(QObject, name)
    assert obj is not None, f"missing QML object {name}"
    return obj


def _controller(text=StatusLevel.READY, vision=StatusLevel.UNAVAILABLE):
    controller = StatusController({
        "local": lambda: ComponentStatus("local", "status.component.local", StatusLevel.READY),
        "text": lambda: ComponentStatus("text", "status.component.text", text),
        "vision": lambda: ComponentStatus("vision", "status.component.vision", vision),
    })
    controller.check_all(force=True)
    return controller


def test_status_modal_renders_split_capabilities_without_warnings():
    ctrl = _controller()
    h = make_handle(QML_DIR / "StatusModal.qml", ctrl=ctrl)
    try:
        assert h.root.property("visible") is True
        assert h.root.property("overall") == "attention"
        assert h.root.property("componentCount") == 3
        assert _find(h.root, "statusCard").property("width") <= 560
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_shell_status_nav_opens_and_close_button_closes_modal(tmp_path):
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    class FakeCredentialStore:
        def get(self, _service, _account): return None
        def set(self, _service, _account, _value): return True
        def delete(self, _service, _account): return True

    ctrl = _controller()
    runtime = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        usage_recorder=None,
        template_controller=None,
        watch_controller=None,
        status_controller=ctrl,
    )
    try:
        root = runtime.root
        modal = _find(root, "systemStatusModal")
        status_nav = _find(root, "nav_status")
        assert modal.property("visible") is False
        center = status_nav.mapToScene(status_nav.boundingRect().center()).toPoint()
        QTest.mouseClick(root, Qt.LeftButton, pos=center)
        QApplication.processEvents()
        assert modal.property("visible") is True
        assert _find(root, "pageRouter").property("currentPage") == "batch"

        close_btn = _find(root, "statusCloseButton")
        center = close_btn.mapToScene(close_btn.boundingRect().center()).toPoint()
        QTest.mouseClick(root, Qt.LeftButton, pos=center)
        QApplication.processEvents()
        assert modal.property("visible") is False
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()


def test_status_card_fits_reference_and_minimum_sizes():
    for width, height in ((1000, 700), (900, 640)):
        ctrl = _controller(StatusLevel.CHECKING, StatusLevel.ATTENTION)
        h = make_handle(QML_DIR / "StatusModal.qml", width, height, ctrl=ctrl)
        try:
            card = _find(h.root, "statusCard")
            assert card.property("x") >= 0
            assert card.property("y") >= 0
            assert card.property("x") + card.property("width") <= width
            assert card.property("y") + card.property("height") <= height
            h.assert_zero_warnings()
        finally:
            h.cleanup()
