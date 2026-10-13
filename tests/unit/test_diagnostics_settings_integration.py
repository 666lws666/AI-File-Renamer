from pathlib import Path

from PySide6.QtTest import QSignalSpy

from src.controllers.settings_controller import SettingsController
from src.models.app_config import AppConfig


class FakeCredentialStore:
    def get(self, _service, _account): return None
    def set(self, _service, _account, _value): return True
    def delete(self, _service, _account): return True


def test_diagnostics_service_is_visible_and_reports_success(tmp_path):
    calls = []
    ctrl = SettingsController(
        AppConfig(), tmp_path / "settings.json", FakeCredentialStore(),
        diagnostics_service=lambda path: calls.append(path) or path,
    )
    spy = QSignalSpy(ctrl.diagnosticsExportFinished)
    assert ctrl.diagnosticsAvailable is True
    ctrl.exportDiagnostics(str(tmp_path / "support.zip"))
    assert calls == [str(tmp_path / "support.zip")]
    assert spy.count() == 1
    assert list(spy.at(0)) == [True, str(tmp_path / "support.zip")]


def test_diagnostics_export_failure_is_honest(tmp_path):
    def fail(_path):
        raise OSError("disk full at C:/Users/private")

    ctrl = SettingsController(
        AppConfig(), tmp_path / "settings.json", FakeCredentialStore(),
        diagnostics_service=fail,
    )
    spy = QSignalSpy(ctrl.diagnosticsExportFinished)
    ctrl.exportDiagnostics(str(tmp_path / "support.zip"))
    assert spy.count() == 1
    success, message = list(spy.at(0))
    assert success is False
    assert "C:/Users/private" not in message


def test_diagnostics_unavailable_does_not_claim_success(tmp_path):
    ctrl = SettingsController(AppConfig(), tmp_path / "settings.json", FakeCredentialStore())
    spy = QSignalSpy(ctrl.diagnosticsExportFinished)
    assert ctrl.diagnosticsAvailable is False
    ctrl.exportDiagnostics(str(tmp_path / "support.zip"))
    assert list(spy.at(0))[0] is False
