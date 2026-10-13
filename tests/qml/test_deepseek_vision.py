"""DeepSeek model choice, draft isolation and visible capability feedback."""
import json

from tests.qml.test_provider_settings import _make_ctrl, _handle, _find, _qml_call

VISION = "deepseek-flash"


def test_model_edit_refreshes_capabilities_without_saving(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    original = list(ctrl.providerProfiles)
    profile = next(p for p in original if p["id"] == "deepseek")
    h = _handle("ProviderForm.qml", ctrl)
    try:
        _qml_call(h, "openExisting(" + json.dumps(profile) + ")")
        field = _find(h, "pfModelField")
        field.setProperty("text", VISION)
        assert h.root.property("capVision") is True
        assert h.root.property("capJson") is True
        assert _find(h, "pfDeepSeekModelHint").property("visible")
        assert "V4.1" in _find(h, "pfDeepSeekModelHint").property("text")
        field.setProperty("text", "deepseek-v4-flash")
        assert h.root.property("capVision") is True
        field.setProperty("text", "deepseek-v4-pro")
        assert h.root.property("capVision") is False
        field.setProperty("text", "unknown-model")
        assert h.root.property("capVision") is False
        assert h.root.property("capJson") is False
        assert ctrl.providerProfiles == original
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_saved_visual_model_view_and_reverification(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({"id": "deepseek", "display_name": "DeepSeek", "model": VISION}, "")
    ds = next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")
    assert ds["visionSupported"] and ds["videoKeyframesSupported"]
    assert ds["structuredJsonStatus"] == "verified"
    assert ds["needsConnectionVerification"]
    assert not (tmp_path / "settings.json").exists()


def test_open_form_shrinks_with_provider_card(tmp_path):
    from PySide6.QtTest import QTest
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _qml_call(h, "clickAction('deepseek', 'edit')")
        QTest.qWait(50)
        h.root.setWidth(804)
        QTest.qWait(50)
        form = _find(h, "providerForm")
        assert form.x() + form.width() <= h.root.width()
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_upgrade_using_retained_key_can_be_verified_without_retyping(tmp_path):
    from tests.qml.test_provider_settings import FakeCredentialStore, _ok_service_qml
    from src.core.provider_manager import PROVIDER_CREDENTIAL_SERVICE
    store = FakeCredentialStore()
    account = (PROVIDER_CREDENTIAL_SERVICE, "provider:deepseek")
    store.values[account] = "synthetic-key"
    ctrl = _make_ctrl(tmp_path, store=store, service=_ok_service_qml)
    ctrl.openSession()
    candidate = {"id": "deepseek", "display_name": "DeepSeek", "model": VISION}
    ctrl.testConnectionCandidate(candidate, "")
    assert ctrl.connectionTestState == "success"
    ctrl.addOrUpdateProvider(candidate, "")
    ds = next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")
    assert ds["needsConnectionVerification"] is False
    assert store.values[account] == "synthetic-key"
    ctrl.addOrUpdateProvider(dict(candidate, model="deepseek-v4-pro"), "")
    assert next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")["needsConnectionVerification"]
    store.values[account] = "changed-key"
    ctrl.addOrUpdateProvider(candidate, "")
    assert next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")["needsConnectionVerification"]


def test_reopened_form_tests_staged_key_and_never_falls_back_after_clear(tmp_path):
    from tests.qml.test_provider_settings import FakeCredentialStore, _ok_service_qml
    from src.core.provider_manager import PROVIDER_CREDENTIAL_SERVICE
    store = FakeCredentialStore()
    account = (PROVIDER_CREDENTIAL_SERVICE, "provider:deepseek")
    store.values[account] = "stored-old-key"
    seen = []
    def service(profile, key):
        seen.append(key)
        return _ok_service_qml(profile, key)
    ctrl = _make_ctrl(tmp_path, store=store, service=service)
    ctrl.openSession()
    candidate = {"id": "deepseek", "display_name": "DeepSeek", "model": VISION}
    ctrl.stageProviderKey("deepseek", "staged-new-key")
    ctrl.testConnectionCandidate(candidate, "")
    assert seen == ["staged-new-key"]
    ctrl.addOrUpdateProvider(candidate, "")
    assert not next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")["needsConnectionVerification"]
    ctrl.stageProviderKey("deepseek", "different-staged-key")
    ctrl.addOrUpdateProvider(candidate, "")
    assert next(p for p in ctrl.providerProfiles if p["id"] == "deepseek")["needsConnectionVerification"]
    ctrl.clearProviderKey("deepseek")
    ctrl.clearProviderKey("deepseek")
    ctrl.testConnectionCandidate(candidate, "")
    assert ctrl.connectionTestState == "failure"
    assert seen == ["staged-new-key"]
    assert store.values[account] == "stored-old-key"
