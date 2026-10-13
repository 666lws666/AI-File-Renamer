"""M7 diagnostics preview/export-confirmation UI contracts."""

from pathlib import Path

from PySide6.QtCore import QObject

from tests.qml.conftest import make_handle

QML_DIR = Path(__file__).parents[2] / "src" / "ui_qml"


def _find(root: QObject, name: str) -> QObject:
    obj = root.findChild(QObject, name)
    assert obj is not None, name
    return obj


def test_diagnostics_dialog_discloses_included_and_excluded_data():
    h = make_handle(QML_DIR / "DiagnosticsDialog.qml")
    try:
        h.root.setProperty("visible", True)
        assert _find(h.root, "diagnosticsIncluded").property("text")
        assert _find(h.root, "diagnosticsExcluded").property("text")
        assert _find(h.root, "diagnosticsExportButton").property("enabled") is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_bootstrap_preserves_caller_diagnostics_service(tmp_path):
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    from src.qml_bootstrap import build_qml_runtime

    class FakeCredentialStore:
        def get(self, _service, _account): return None
        def set(self, _service, _account, _value): return True
        def delete(self, _service, _account): return True

    calls = []
    store = FakeCredentialStore()
    ctrl = SettingsController(
        AppConfig(), tmp_path / "settings.json", store,
        diagnostics_service=lambda path: calls.append(path) or path,
    )
    runtime = build_qml_runtime(
        live_config=AppConfig(), config_file=tmp_path / "settings.json",
        credential_store=store, controller=ctrl, usage_recorder=None,
        template_controller=None, watch_controller=None, status_controller=None,
    )
    try:
        destination = str(tmp_path / "caller.zip")
        ctrl.exportDiagnostics(destination)
        assert calls == [destination]
        runtime.assert_zero_warnings()
    finally:
        runtime.cleanup()
