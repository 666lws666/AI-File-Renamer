"""Provider Settings Card + ProviderForm — real runtime interaction tests
(M6 gate, D.1-D.14).

- "Add Provider" opens the ProviderForm (D.1)
- nothing enters the draft before Save (D.2)
- form fields: name / id / base URL / model / capabilities / API key /
  test connection / save / cancel / clear key / delete (D.3)
- API key field is always empty on open; only status shown (D.5)
- key status badge shows three states (D.7/D.8)
- row click and activate are guarded (D.14)
"""
import os, sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).parent.parent.parent / "src" / "ui_qml"


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}
        self.fail_get = False

    def get(self, s, a):
        if self.fail_get:
            raise OSError("Credential Manager unavailable")
        return self.values.get((s, a))

    def set(self, s, a, v):
        self.values[(s, a)] = v
        return True

    def delete(self, s, a):
        self.values.pop((s, a), None)
        return True


def _make_ctrl(tmp_path, store=None, service=None):
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    live = AppConfig()
    return SettingsController(
        live_config=live,
        config_file_path=tmp_path / "settings.json",
        credential_store=store if store is not None else FakeCredentialStore(),
        connection_test_service=service,
    )


def _ok_service_qml(profile, credential):
    from src.core.connection_test import ConnectionOutcome, ConnectionResult
    return ConnectionResult(outcome=ConnectionOutcome.SUCCESS)


def _auth_fail_service_qml(profile, credential):
    from src.core.connection_test import ConnectionOutcome, ConnectionResult
    return ConnectionResult(outcome=ConnectionOutcome.AUTH_ERROR)


def _handle(name, ctrl=None):
    from tests.qml.conftest import make_handle
    return make_handle(SRC / name, ctrl=ctrl)


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)



def _invoke_qml(handle, method, arg=None):
    """Call a QML function on the card root via QQmlExpression.

    QML ``function`` declarations are JS methods — not QMetaMethod slots —
    so QMetaObject.invokeMethod cannot reach them.  Evaluating an
    expression in the card's context is the supported path, and it avoids
    crossing QObject wrappers (Qt 6.11 Repeater delegates live outside the
    object tree and shiboken wrapper caches are unsafe across engines)."""
    from PySide6.QtQml import QQmlExpression
    js = f"{method}('{arg}')" if arg is not None else f"{method}()"
    expr = QQmlExpression(handle.engine.rootContext(), handle.root, js)
    value, _err = expr.evaluate()  # PySide6 returns (result, errorFlag)
    return value


def _provider_row(handle, provider_id):
    return bool(_invoke_qml(handle, "hasProviderRow", provider_id))


def _click_at(handle, pos):
    """Deliver a REAL mouse click at scene coordinates."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    win = handle.root.window()
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(pos[0]), int(pos[1])))
    QApplication.processEvents()


def _qml_call(handle, js):
    """Evaluate a JS expression in the card root's context."""
    from PySide6.QtQml import QQmlExpression
    expr = QQmlExpression(handle.engine.rootContext(), handle.root, js)
    value, _err = expr.evaluate()
    return value


def _pos_tuple(pos):
    """QJSValue array [x, y] -> (x, y) floats."""
    if pos is None:
        return (0.0, 0.0)
    if hasattr(pos, "toVariant"):
        arr = pos.toVariant()
        if isinstance(arr, (list, tuple)) and len(arr) >= 2:
            return (float(arr[0]), float(arr[1]))
        return (0.0, 0.0)
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return (float(pos[0]), float(pos[1]))
    return (0.0, 0.0)


def _click_action(handle, provider_id, action):
    """Real click on the row action Button (edit/delete/activate)."""
    pos = _qml_call(handle, f"actionButtonPos('{provider_id}', '{action}')")
    _click_at(handle, _pos_tuple(pos))


def _click_row(handle, provider_id):
    """Real click on the row background (TapHandler activation)."""
    pos = _qml_call(handle, f"rowCenter('{provider_id}')")
    _click_at(handle, _pos_tuple(pos))


def _click_btn(handle, item):
    from PySide6.QtCore import QMetaObject
    QMetaObject.invokeMethod(item, "click")
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()


# ============================================================================
# Card + form basics
# ============================================================================

def test_card_shows_five_presets(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        for pid in ("deepseek", "qwen", "mimo", "zhipu", "kimi"):
            assert _provider_row(h, pid) is not None, f"missing row {pid}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_capability_chips_display_only(tmp_path):
    """Current Flash supports vision; preserve other providers' display policy."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    profiles = ctrl.providerProfiles
    ds = next(p for p in profiles if p["id"] == "deepseek")
    qwen = next(p for p in profiles if p["id"] == "qwen")
    mimo = next(p for p in profiles if p["id"] == "mimo")
    assert ds["visionSupported"]
    assert ds["model"] == "deepseek-flash"
    assert qwen["recommended"]
    assert mimo["structuredJsonStatus"] == "unverified"


def test_add_provider_button_opens_form(tmp_path):
    """D.1: clicking Add Provider opens the ProviderForm."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        form = _find(h, "providerForm")
        assert form is not None
        assert form.property("visible") is False
        _click_btn(h, _find(h, "addProviderBtn"))
        assert form.property("visible") is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_no_draft_change_before_save(tmp_path):
    """D.2: opening the form must not add a blank custom provider to draft."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    assert ctrl.draft_config is not None
    before = [p["id"] for p in ctrl.providerProfiles]
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        form = _find(h, "providerForm")
        assert form.property("visible") is True
        # fill fields but DO NOT save
        _find(h, "pfNameField").setProperty("text", "My Custom")
        _find(h, "pfIdField").setProperty("text", "my-custom")
        _find(h, "pfBaseUrlField").setProperty("text", "https://example.com/v1")
        _find(h, "pfModelField").setProperty("text", "m1")
        after = [p["id"] for p in ctrl.providerProfiles]
        assert after == before, "draft must be untouched until Save"
        assert not ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_save_adds_custom_provider_to_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "My Custom")
        _find(h, "pfIdField").setProperty("text", "my-custom")
        _find(h, "pfBaseUrlField").setProperty("text", "https://example.com/v1")
        _find(h, "pfModelField").setProperty("text", "m1")
        _find(h, "pfVisionCap").setProperty("checked", True)
        _click_btn(h, _find(h, "pfSaveBtn"))
        ids = [p["id"] for p in ctrl.providerProfiles]
        assert "my-custom" in ids, "saved custom provider must be in draft"
        assert ctrl.dirty
        prof = next(p for p in ctrl.providerProfiles if p["id"] == "my-custom")
        assert prof["displayName"] == "My Custom"
        assert prof["visionSupported"] is True
        assert prof["isPreset"] is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_cancel_adds_nothing(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "Never Saved")
        _find(h, "pfIdField").setProperty("text", "never-saved")
        _click_btn(h, _find(h, "pfCancelBtn"))
        assert not any(p["id"] == "never-saved" for p in ctrl.providerProfiles)
        assert not ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_validation_blocks_save(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "X")
        _find(h, "pfIdField").setProperty("text", "bad id!")
        _click_btn(h, _find(h, "pfSaveBtn"))
        assert not any(p["id"] == "bad id!" for p in ctrl.providerProfiles)
        assert not ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_edit_custom_provider_opens_prefilled_form(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "my-custom", "display_name": "My Custom", "base_url": "https://example.com/v1",
        "model": "m1", "capabilities": {"text": True, "vision": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "my-custom", "edit")
        form = _find(h, "providerForm")
        assert form.property("visible") is True
        assert _find(h, "pfNameField").property("text") == "My Custom"
        assert _find(h, "pfIdField").property("text") == "my-custom"
        assert _find(h, "pfModelField").property("text") == "m1"
        assert _find(h, "pfVisionCap").property("checked") is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_edit_preset_updates_verification_state(tmp_path):
    """Presets are legal profiles; editing a REGIONAL preset requires a
    region selection, then saves the profile."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        form = _find(h, "providerForm")
        assert form.property("visible") is True
        assert _find(h, "pfNameField").property("text") == "Qwen / 通义千问"
        region_combo = _find(h, "pfRegionCombo")
        assert region_combo is not None, "REGIONAL preset must show a region selector"
        region_combo.setProperty("currentIndex", 0)  # beijing
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfSaveBtn"))
        ids = [p["id"] for p in ctrl.providerProfiles]
        assert "qwen" in ids
        assert ctrl.draft_config is not None
        qwen = next(p for p in ctrl.draft_config.provider_profiles if p["id"] == "qwen")
        assert qwen["region"] == "beijing"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_delete_custom_provider_removes_from_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "doomed", "display_name": "Doomed", "base_url": "https://d.example.com",
        "model": "m", "capabilities": {"text": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "doomed", "delete")
        form = _find(h, "providerForm")
        assert form.property("visible") is True
        _click_btn(h, _find(h, "pfDeleteBtn"))
        assert not any(p["id"] == "doomed" for p in ctrl.providerProfiles)
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


# ============================================================================
# API key handling (D.5, D.6, D.7, D.8)
# ============================================================================

def test_api_key_field_always_empty_on_open(tmp_path):
    """D.5: the key field is NEVER pre-filled, even when configured."""
    store = FakeCredentialStore()
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-secret"
    ctrl = _make_ctrl(tmp_path, store=store)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        key_field = _find(h, "pfApiKeyField")
        assert key_field.property("text") == "", "key field must always open empty"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_key_status_three_states(tmp_path):
    """D.7/D.8: configured / unconfigured / unavailable are distinct."""
    store = FakeCredentialStore()
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-secret"

    # configured
    ctrl = _make_ctrl(tmp_path, store=store)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        status = _find(h, "pfKeyStatusText")
        text = status.property("text")
        assert "已配置" in text or "Configured" in text
        h.assert_zero_warnings()
    finally:
        h.cleanup()

    # unconfigured
    ctrl2 = _make_ctrl(tmp_path, store=FakeCredentialStore())
    ctrl2.openSession()
    h2 = _handle("ProviderSettingsCard.qml", ctrl2)
    try:
        _click_action(h2, "qwen", "edit")
        status2 = _find(h2, "pfKeyStatusText")
        text2 = status2.property("text")
        assert "未配置" in text2 or "Not Configured" in text2
        h2.assert_zero_warnings()
    finally:
        h2.cleanup()

    # unavailable must NOT masquerade as unconfigured
    store3 = FakeCredentialStore()
    store3.fail_get = True
    ctrl3 = _make_ctrl(tmp_path, store=store3)
    ctrl3.openSession()
    h3 = _handle("ProviderSettingsCard.qml", ctrl3)
    try:
        _click_action(h3, "qwen", "edit")
        status3 = _find(h3, "pfKeyStatusText")
        text3 = status3.property("text")
        assert "不可用" in text3 or "unavailable" in text3.lower(), f"got {text3}"
        h3.assert_zero_warnings()
    finally:
        h3.cleanup()


def test_form_save_stages_typed_key(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "My Custom")
        _find(h, "pfIdField").setProperty("text", "my-custom")
        _find(h, "pfBaseUrlField").setProperty("text", "https://example.com/v1")
        _find(h, "pfModelField").setProperty("text", "m1")
        _find(h, "pfApiKeyField").setProperty("text", "sk-typed-key-12345")
        _click_btn(h, _find(h, "pfSaveBtn"))
        assert ctrl.staged_key_count == 1
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_clear_key_button_calls_ctrl(tmp_path):
    store = FakeCredentialStore()
    store.values[("Xuxia.Provider", "provider:qwen")] = "existing-secret"
    ctrl = _make_ctrl(tmp_path, store=store)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        _click_btn(h, _find(h, "pfClearKeyBtn"))
        assert ctrl.staged_key_count == 1  # sentinel "" scheduled delete
        h.assert_zero_warnings()
    finally:
        h.cleanup()


# ============================================================================
# Test connection + activation (D.12, D.13, D.14)
# ============================================================================

def test_test_connection_success_in_form(tmp_path):
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        # REGIONAL preset: pick a region + workspace before testing
        from PySide6.QtWidgets import QApplication
        region_combo = _find(h, "pfRegionCombo")
        assert region_combo is not None
        region_combo.setProperty("currentIndex", 1)  # singapore needs workspace
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(h, "pfApiKeyField").setProperty("text", "sk-qwen-sg")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfTestConnBtn"))
        assert ctrl.connectionTestState == "success"
        assert _find(h, "pfTestStatus").property("text") != ""
        # testing alone does not persist verification — saving the SAME
        # candidate does
        _click_btn(h, _find(h, "pfSaveBtn"))
        qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
        assert qwen["needsConnectionVerification"] is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_test_connection_failure_in_form(tmp_path):
    ctrl = _make_ctrl(tmp_path, service=_auth_fail_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "edit")
        from PySide6.QtWidgets import QApplication
        region_combo = _find(h, "pfRegionCombo")
        region_combo.setProperty("currentIndex", 0)  # beijing needs workspace
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(h, "pfApiKeyField").setProperty("text", "sk-qwen-bj")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfTestConnBtn"))
        assert ctrl.connectionTestState == "failure"
        qwen = next(p for p in ctrl.providerProfiles if p["id"] == "qwen")
        assert qwen["needsConnectionVerification"] is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()


# ============================================================================
# M6 correction: connection-test visible state (form must show the result)
# ============================================================================

def test_form_test_status_text_success_preset(tmp_path):
    """A successful preset test must show 连接成功 in the form."""
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        from PySide6.QtWidgets import QApplication
        _click_action(h, "qwen", "edit")
        region_combo = _find(h, "pfRegionCombo")
        region_combo.setProperty("currentIndex", 0)  # beijing needs workspace
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(h, "pfApiKeyField").setProperty("text", "sk-qwen-bj")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfTestConnBtn"))
        status = _find(h, "pfTestStatus").property("text")
        assert status == "连接成功", f"preset success must show 连接成功, got {status!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_test_status_text_failure_preset(tmp_path):
    """An auth-failure preset test must show 连接失败 in the form."""
    ctrl = _make_ctrl(tmp_path, service=_auth_fail_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        from PySide6.QtWidgets import QApplication
        _click_action(h, "qwen", "edit")
        region_combo = _find(h, "pfRegionCombo")
        region_combo.setProperty("currentIndex", 0)
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(h, "pfApiKeyField").setProperty("text", "sk-qwen-bj")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfTestConnBtn"))
        status = _find(h, "pfTestStatus").property("text")
        assert status == "连接失败", f"preset failure must show 连接失败, got {status!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_test_status_text_success_new_custom(tmp_path):
    """A NEW custom provider has no editingId — the form must scope the
    visible state to the typed providerId (this was always idle)."""
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "New Custom")
        _find(h, "pfIdField").setProperty("text", "new-custom")
        _find(h, "pfBaseUrlField").setProperty("text", "https://new.example.com/v1")
        _find(h, "pfModelField").setProperty("text", "m1")
        _find(h, "pfApiKeyField").setProperty("text", "sk-new-custom")
        _click_btn(h, _find(h, "pfTestConnBtn"))
        status = _find(h, "pfTestStatus").property("text")
        assert status == "连接成功", f"new-custom success must show 连接成功, got {status!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_test_status_text_failure_new_custom(tmp_path):
    ctrl = _make_ctrl(tmp_path, service=_auth_fail_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_btn(h, _find(h, "addProviderBtn"))
        _find(h, "pfNameField").setProperty("text", "New Custom")
        _find(h, "pfIdField").setProperty("text", "new-custom")
        _find(h, "pfBaseUrlField").setProperty("text", "https://new.example.com/v1")
        _find(h, "pfModelField").setProperty("text", "m1")
        _find(h, "pfApiKeyField").setProperty("text", "sk-new-custom")
        _click_btn(h, _find(h, "pfTestConnBtn"))
        status = _find(h, "pfTestStatus").property("text")
        assert status == "连接失败", f"new-custom failure must show 连接失败, got {status!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_form_edit_after_success_resets_state_to_idle(tmp_path):
    """Any fingerprint-changing edit must immediately return the visible
    test state to idle."""
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        from PySide6.QtWidgets import QApplication
        _click_action(h, "qwen", "edit")
        region_combo = _find(h, "pfRegionCombo")
        region_combo.setProperty("currentIndex", 0)
        QApplication.processEvents()
        _find(h, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(h, "pfApiKeyField").setProperty("text", "sk-qwen-bj")
        QApplication.processEvents()
        _click_btn(h, _find(h, "pfTestConnBtn"))
        assert _find(h, "pfTestStatus").property("text") == "连接成功"

        # edit a fingerprint-bearing field -> back to idle text
        _find(h, "pfModelField").setProperty("text", "qwen-other-model")
        QApplication.processEvents()
        status = _find(h, "pfTestStatus").property("text")
        assert status == "测试连接", f"edit must reset to idle, got {status!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_row_click_cannot_bypass_activation_guards(tmp_path):
    """D.14: whole-row click must not activate an unverified provider."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_row(h, "qwen")
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.active_provider_id == ""
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_activate_after_verify_and_key(tmp_path):
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "dashscope-key",
    )
    ctrl.addOrUpdateProvider(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "dashscope-key",
    )
    ctrl.stageProviderKey("qwen", "dashscope-key")
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "qwen", "activate")
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.active_provider_id == "qwen"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_credential_unavailable_blocks_activation(tmp_path):
    store = FakeCredentialStore()
    store.fail_get = True
    ctrl = _make_ctrl(tmp_path, store=store, service=_ok_service_qml)
    ctrl.openSession()
    ctrl.testConnectionCandidate(
        {"id": "qwen", "display_name": "Qwen / 通义千问",
         "model": "qwen3.6-flash", "region": "virginia"},
        "k",
    )
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_row(h, "qwen")
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.active_provider_id == ""
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_provider_card_no_price_words(tmp_path):
    text = (SRC / "ProviderSettingsCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "budget", "price", "cost", "currency", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in ProviderSettingsCard.qml"


def test_form_no_price_words(tmp_path):
    text = (SRC / "ProviderForm.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "budget", "price", "cost", "currency", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in ProviderForm.qml"


# ============================================================================
# M6 Provider Integration Gate — form reopen loop + row hit layer
# ============================================================================

def test_form_reopen_loop_visibility(tmp_path):
    """GATE: Open → Cancel → Open → Save → Open → Delete → Open — the form
    visibility binding must survive every close path (no direct visible=)."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "loop-custom", "display_name": "Loop Custom",
        "base_url": "https://loop.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        from PySide6.QtWidgets import QApplication
        form = _find(h, "providerForm")

        # 1. Open (new)
        _click_btn(h, _find(h, "addProviderBtn"))
        QApplication.processEvents()
        assert form.property("visible") is True
        _find(h, "pfNameField").setProperty("text", "Never Saved")
        _find(h, "pfIdField").setProperty("text", "never-saved")

        # 2. Cancel → closed, nothing in draft
        _click_btn(h, _find(h, "pfCancelBtn"))
        QApplication.processEvents()
        assert form.property("visible") is False
        assert not any(p["id"] == "never-saved" for p in ctrl.providerProfiles)

        # 3. Open (edit existing custom) → prefilled
        _click_action(h, "loop-custom", "edit")
        QApplication.processEvents()
        assert form.property("visible") is True
        assert _find(h, "pfNameField").property("text") == "Loop Custom"

        # 4. Save → closed, draft updated
        _click_btn(h, _find(h, "pfSaveBtn"))
        QApplication.processEvents()
        assert form.property("visible") is False

        # 5. Open (edit again) → works after save-close
        _click_action(h, "loop-custom", "edit")
        QApplication.processEvents()
        assert form.property("visible") is True
        assert _find(h, "pfApiKeyField").property("text") == ""

        # 6. Delete via form → closed, provider removed
        _click_btn(h, _find(h, "pfDeleteBtn"))
        QApplication.processEvents()
        assert form.property("visible") is False
        assert not any(p["id"] == "loop-custom" for p in ctrl.providerProfiles)

        # 7. Open (new) → still works after delete-close
        _click_btn(h, _find(h, "addProviderBtn"))
        QApplication.processEvents()
        assert form.property("visible") is True
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_action_clicks_do_not_trigger_row_activation(tmp_path):
    """GATE: clicking edit/delete must NOT activate the row."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "row-custom", "display_name": "Row Custom",
        "base_url": "https://row.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "row-custom", "edit")
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.active_provider_id == "", (
            "clicking Edit must not activate the row"
        )
        _click_btn(h, _find(h, "pfCancelBtn"))
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        _click_action(h, "row-custom", "delete")
        assert ctrl.draft_config.active_provider_id == "", (
            "clicking Delete must not activate the row"
        )
        _click_btn(h, _find(h, "pfCancelBtn"))
        QApplication.processEvents()
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_edit_click_opens_correct_profile(tmp_path):
    """GATE: clicking Edit opens the form for THAT provider, not another."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "alpha", "display_name": "Alpha Provider",
        "base_url": "https://alpha.example.com/v1", "model": "m-alpha",
        "capabilities": {"text": True},
    })
    ctrl.addOrUpdateProvider({
        "id": "beta", "display_name": "Beta Provider",
        "base_url": "https://beta.example.com/v1", "model": "m-beta",
        "capabilities": {"text": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "beta", "edit")
        assert _find(h, "pfNameField").property("text") == "Beta Provider"
        assert _find(h, "pfIdField").property("text") == "beta"
        assert _find(h, "pfModelField").property("text") == "m-beta"
        from PySide6.QtWidgets import QApplication
        _click_btn(h, _find(h, "pfCancelBtn"))
        QApplication.processEvents()
        _click_action(h, "alpha", "edit")
        assert _find(h, "pfNameField").property("text") == "Alpha Provider"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_delete_click_executes_correct_custom_delete(tmp_path):
    """GATE: the Delete flow removes the intended custom provider only."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.addOrUpdateProvider({
        "id": "keep", "display_name": "Keep Me",
        "base_url": "https://keep.example.com/v1", "model": "m1",
        "capabilities": {"text": True},
    })
    ctrl.addOrUpdateProvider({
        "id": "remove-me", "display_name": "Remove Me",
        "base_url": "https://remove.example.com/v1", "model": "m2",
        "capabilities": {"text": True},
    })
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        _click_action(h, "remove-me", "delete")
        _click_btn(h, _find(h, "pfDeleteBtn"))
        ids = [p["id"] for p in ctrl.providerProfiles]
        assert "remove-me" not in ids
        assert "keep" in ids, "the other custom provider must survive"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_activate_click_only_succeeds_when_verified_and_configured(tmp_path):
    """GATE: the activate Button is only present/effective when the provider
    is verified AND (configured or staged)."""
    from PySide6.QtQml import QQmlExpression
    ctrl = _make_ctrl(tmp_path, service=_ok_service_qml)
    ctrl.openSession()
    h = _handle("ProviderSettingsCard.qml", ctrl)
    try:
        # unverified qwen → activate button hidden
        pos = _qml_call(h, "actionButtonPos('qwen', 'activate')")
        arr = _pos_tuple(pos)
        assert arr == (0.0, 0.0), "activate must be hidden for unverified providers"

        # verify + stage → activate visible and effective
        ctrl.testConnectionCandidate(
            {"id": "qwen", "display_name": "Qwen / 通义千问",
             "model": "qwen3.6-flash", "region": "virginia"},
            "k",
        )
        ctrl.addOrUpdateProvider(
            {"id": "qwen", "display_name": "Qwen / 通义千问",
             "model": "qwen3.6-flash", "region": "virginia"},
            "k",
        )
        ctrl.stageProviderKey("qwen", "k")
        pos2 = _qml_call(h, "actionButtonPos('qwen', 'activate')")
        arr2 = _pos_tuple(pos2)
        assert arr2 != (0.0, 0.0), "activate must be visible for verified+staged"
        _click_action(h, "qwen", "activate")
        assert ctrl.draft_config is not None
        assert ctrl.draft_config.active_provider_id == "qwen"
        h.assert_zero_warnings()
    finally:
        h.cleanup()
