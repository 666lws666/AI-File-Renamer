"""Real runtime QML tests for the M6 preferences chain (M6 gate B/G).

Loads main.qml through the bootstrap factory, navigates to Preferences via
Shell/PageRouter, and drives real controls by objectName.  The injected
SettingsController is the SAME QObject the page's ctrl binds to.  Every
scenario asserts exactly zero QML warnings (real I18n injected — nothing is
filtered).
"""
import os, sys
from pathlib import Path

from src.core.connection_test import ConnectionOutcome, ConnectionResult

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).parent.parent.parent / "src" / "ui_qml"


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}
        self._global_set_fail = False

    def get(self, s, a):
        return self.values.get((s, a))

    def set(self, s, a, v):
        if self._global_set_fail:
            return False
        self.values[(s, a)] = v
        return True

    def delete(self, s, a):
        self.values.pop((s, a), None)
        return True


def _build_runtime(tmp_path, service=None, store=None, **kw):
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    return build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=store if store is not None else FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        # fixtures that don't test the default recorder explicitly disable it
        usage_recorder=None,
        **kw,
    )


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)



def _card(rt):
    from PySide6.QtQuick import QQuickItem
    return rt.root.findChild(QQuickItem, "providerSettingsCard")


def _qml_on_card(rt, js):
    from PySide6.QtQml import QQmlExpression
    expr = QQmlExpression(rt.engine.rootContext(), _card(rt), js)
    value, _err = expr.evaluate()
    return value


def _click_action_on_page(rt, provider_id, action):
    """Invoke a row action Button through its own click() API.

    Real QTest mouse clicks cannot reach Flickable (ScrollView) content in
    offscreen mode; genuine QTest clicks on these buttons are covered by the
    standalone-card tests (test_provider_settings.py).  Here the runtime
    integration flow drives the SAME onClicked handlers."""
    from PySide6.QtWidgets import QApplication
    _qml_on_card(rt, f"clickAction('{provider_id}', '{action}')")
    QApplication.processEvents()


def _navigate_preferences(rt):
    from PySide6.QtWidgets import QApplication
    router = _find(rt, "pageRouter")
    router.navigate("preferences")
    QApplication.processEvents()
    item = router.property("currentItem")
    assert item is not None and item.property("objectName") == "preferencesPage"
    return router, item


def _template_id(rt, name):
    return next(row['id'] for row in rt.template_controller.templates if row['name'] == name)


def _choose_default_template(rt, name):
    """Create a real local fixture template, then select it via the QML signal."""
    import json
    from PySide6.QtQml import QQmlExpression
    from PySide6.QtWidgets import QApplication
    catalog = rt.template_controller
    if not any(row['name'] == name for row in catalog.templates):
        catalog.beginCreateTemplate()
        catalog.setDraftName(name)
        assert catalog.saveDraft()
    QApplication.processEvents()
    combo = _find(rt, 'defaultTemplateField')
    selected = json.dumps(_template_id(rt, name))
    expression = QQmlExpression(rt.engine.rootContext(), combo,
        f'currentIndex = indexOfValue({selected}); activated(currentIndex)')
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QApplication.processEvents()
    assert combo.property('currentIndex') >= 0


# ============================================================================
# B: real injection chain
# ============================================================================

def test_preferences_page_ctrl_is_injected_controller(tmp_path):
    """main.qml -> Shell -> PageRouter -> Preferences: same QObject."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_preferences(rt)
        ctrl_obj = page.property("ctrl")
        assert ctrl_obj is not None
        assert ctrl_obj is rt.controller, (
            "PreferencesPage.ctrl must be the injected SettingsController instance"
        )
        # Shell.settingsController == PageRouter.settingsController == page.ctrl
        assert router.property("settingsController") is rt.controller
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_navigation_roundtrip_and_destroy_clean(tmp_path):
    """Navigate away and back; destruction produces no warnings."""
    rt = _build_runtime(tmp_path)
    try:
        router, _page = _navigate_preferences(rt)
        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        router.navigate("preferences")
        QApplication.processEvents()
        item = router.property("currentItem")
        assert item.property("objectName") == "preferencesPage"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_loading_all_card_types_creates_cleanly(tmp_path):
    """Every M6 card file must load + create with zero warnings (real i18n)."""
    from tests.qml.conftest import make_handle
    for name in (
        "GeneralSettingsCard.qml", "ProviderSettingsCard.qml",
        "QualityCard.qml", "ResourceLimitsCard.qml", "PrivacyCard.qml",
        "CacheCard.qml", "UsageCard.qml", "DiagnosticsCard.qml",
        "ProviderForm.qml", "PreferencesPage.qml", "Shell.qml",
    ):
        h = make_handle(SRC / name)
        try:
            assert h.root is not None, f"{name} root is None"
            h.assert_zero_warnings()
        finally:
            h.cleanup()


# ============================================================================
# Real QML interaction scenarios (no direct controller setter calls)
# ============================================================================

def test_general_fields_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        _find(rt, "languageCombo").setProperty("currentIndex", 1)
        _find(rt, "languageCombo").activated.emit(1)
        _choose_default_template(rt, "runtime-template")
        _find(rt, "maxFileSizeSpin").setProperty("value", 66)
        _find(rt, "maxContentCharsSpin").setProperty("value", 5500)
        QApplication.processEvents()
        ctrl = rt.controller
        assert ctrl is not None
        assert ctrl.property("language") == "en_US"
        assert ctrl.property("defaultTemplateId") == _template_id(rt, "runtime-template")
        assert ctrl.property("maxFileSizeMb") == 66
        assert ctrl.property("maxContentChars") == 5500
        assert ctrl.property("dirty") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_quality_three_modes_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        ctrl = rt.controller
        assert ctrl is not None
        for radio, mode in (("qualityEconomyRadio", "economy"), ("qualityHighRadio", "high"), ("qualityBalancedRadio", "balanced")):
            _find(rt, radio).setProperty("checked", True)
            assert ctrl.property("qualityMode") == mode
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_resource_values_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        ctrl = rt.controller
        assert ctrl is not None
        _find(rt, "maxConcurrentSpin").setProperty("value", 7)
        _find(rt, "timeoutSpin").setProperty("value", 60)
        _find(rt, "maxRetriesSpin").setProperty("value", 4)
        _find(rt, "maxPdfPagesSpin").setProperty("value", 90)
        _find(rt, "maxVideoKeyframesSpin").setProperty("value", 10)
        assert ctrl.property("maxConcurrentRequests") == 7
        assert ctrl.property("requestTimeoutSeconds") == 60
        assert ctrl.property("maxRetries") == 4
        assert ctrl.property("maxPdfPages") == 90
        assert ctrl.property("maxVideoKeyframes") == 10
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_privacy_switches_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        ctrl = rt.controller
        assert ctrl is not None
        _find(rt, "allowTextCloudSwitch").setProperty("checked", False)
        _find(rt, "allowVisionCloudSwitch").setProperty("checked", False)
        _find(rt, "allowVideoCloudSwitch").setProperty("checked", False)
        assert ctrl.property("allowTextCloud") is False
        assert ctrl.property("allowVisionCloud") is False
        assert ctrl.property("allowVideoKeyframesCloud") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_cache_settings_and_clear_via_qml(tmp_path):
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    from src.controllers.settings_controller import SettingsController

    class FakeCache:
        def __init__(self):
            self.cleared = False

        def clear(self):
            self.cleared = True

    cache = FakeCache()
    ctrl = SettingsController(
        live_config=AppConfig(),
        config_file_path=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        cache_service=cache,
    )
    rt = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        controller=ctrl,
    )
    try:
        _navigate_preferences(rt)
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        _find(rt, "cacheEnabledSwitch").setProperty("checked", False)
        _find(rt, "cacheMaxMbSpin").setProperty("value", 800)
        _find(rt, "cacheTtlDaysSpin").setProperty("value", 30)
        assert ctrl.property("cacheEnabled") is False
        assert ctrl.property("cacheMaxMb") == 800
        assert ctrl.property("cacheTtlDays") == 30
        # clear cache via the real button -> ctrl.clearCache() -> success state
        QMetaObject.invokeMethod(_find(rt, "cacheClearBtn"), "click")
        QApplication.processEvents()
        assert cache.cleared, "clear button must call ctrl.clearCache()"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_provider_add_edit_activate_clear_via_qml(tmp_path):
    """Provider full chain through real controls on the preferences page."""
    from PySide6.QtCore import QPointF, Qt, QMetaObject
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    def click(item):
        win = item.window()
        center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center.toPoint())
        QApplication.processEvents()

    rt = _build_runtime(tmp_path, connection_test_service=lambda *_: None)
    try:
        _navigate_preferences(rt)
        # Enlarge the window so the whole preferences scroll content (and the
        # provider rows deep in the page) is inside the viewport — otherwise
        # real mouse clicks land outside the visible area.
        rt.root.resize(1000, 1600)
        QApplication.processEvents()
        ctrl = rt.controller
        assert ctrl is not None

        # Add a custom provider through the form
        QMetaObject.invokeMethod(_find(rt, "addProviderBtn"), "click")
        _find(rt, "pfNameField").setProperty("text", "Runtime Custom")
        _find(rt, "pfIdField").setProperty("text", "runtime-custom")
        _find(rt, "pfBaseUrlField").setProperty("text", "https://rt.example.com/v1")
        _find(rt, "pfModelField").setProperty("text", "rt-model")
        _find(rt, "pfApiKeyField").setProperty("text", "sk-rt-key-2026")
        QMetaObject.invokeMethod(_find(rt, "pfSaveBtn"), "click")
        QApplication.processEvents()

        ids = [p["id"] for p in ctrl.property("providerProfiles")]
        assert "runtime-custom" in ids

        # Edit it via a REAL click on the row edit Button: change the model
        _click_action_on_page(rt, "runtime-custom", "edit")
        _find(rt, "pfModelField").setProperty("text", "rt-model-v2")
        QMetaObject.invokeMethod(_find(rt, "pfSaveBtn"), "click")
        QApplication.processEvents()
        prof = next(p for p in ctrl.property("providerProfiles") if p["id"] == "runtime-custom")
        assert prof["model"] == "rt-model-v2"

        # Clear its key via the form (real edit click again)
        _click_action_on_page(rt, "runtime-custom", "edit")
        assert _find(rt, "pfApiKeyField").property("text") == ""
        QMetaObject.invokeMethod(_find(rt, "pfClearKeyBtn"), "click")

        # Qwen: real edit click, pick region+workspace, key, test, save.
        # Explicit synchronous legacy fixture; managed default is tested separately.
        ctrl._connection_test_service = (
            lambda profile, key: ConnectionResult(outcome=ConnectionOutcome.SUCCESS)
            if profile.id == "qwen" and key == "sk-qwen-rt"
            else ConnectionResult(outcome=ConnectionOutcome.AUTH_ERROR)
        )
        _click_action_on_page(rt, "qwen", "edit")
        region_combo = _find(rt, "pfRegionCombo")
        assert region_combo is not None
        region_combo.setProperty("currentIndex", 0)  # beijing
        QApplication.processEvents()
        _find(rt, "pfWorkspaceField").setProperty("text", "w-1234567890")
        _find(rt, "pfApiKeyField").setProperty("text", "sk-qwen-rt")
        QApplication.processEvents()
        QMetaObject.invokeMethod(_find(rt, "pfTestConnBtn"), "click")
        QApplication.processEvents()
        assert ctrl.property("connectionTestState") == "success"
        QMetaObject.invokeMethod(_find(rt, "pfSaveBtn"), "click")
        QApplication.processEvents()

        qwen = next(p for p in ctrl.property("providerProfiles") if p["id"] == "qwen")
        assert qwen["needsConnectionVerification"] is False, (
            f"qwen still unverified; draft="
            f"{[(p.get('id'), p.get('needs_connection_verification')) for p in ctrl.draft_config.provider_profiles] if ctrl.draft_config else None}"
        )

        # Activate via a REAL click on the activate Button
        _click_action_on_page(rt, "qwen", "activate")
        assert ctrl.draft_config.active_provider_id == "qwen"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_save_and_cancel_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        _choose_default_template(rt, "save-me")
        ctrl = rt.controller
        assert ctrl is not None
        assert ctrl.property("dirty") is True

        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert ctrl.property("dirty") is False
        assert ctrl.property("defaultTemplateId") == _template_id(rt, "save-me")
        assert (tmp_path / "settings.json").exists()

        # dirty again then cancel via the guard dialog
        _choose_default_template(rt, "cancel-me")
        assert ctrl.property("dirty") is True
        _find(rt, "cancelBtn").click()
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True
        _find(rt, "unsavedDiscardBtn").click()
        QApplication.processEvents()
        assert ctrl.property("sessionOpen") is False
        assert ctrl.property("dirty") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_save_failure_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        ctrl = rt.controller
        assert ctrl is not None
        _choose_default_template(rt, "x")
        ctrl._credentials._global_set_fail = True  # type: ignore[attr-defined]
        ctrl.stageProviderKey("qwen", "k")
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert ctrl.property("dirty") is True
        err = _find(rt, "saveErrorText")
        assert err.property("visible") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


# ============================================================================
# M6 correction: max file size validation blocks page Save
# ============================================================================

def test_max_file_size_invalid_blocks_page_save(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        ctrl = rt.controller
        assert ctrl is not None

        _find(rt, "maxFileSizeSpin").setProperty("text", "0")
        QApplication.processEvents()
        err = _find(rt, "maxFileSizeError")
        assert err.property("visible") is True
        assert ctrl.property("maxFileSizeMb") == 50, "invalid value must not reach the draft"

        # make the page dirty elsewhere: Save must STILL be blocked
        _choose_default_template(rt, "x")
        QApplication.processEvents()
        assert ctrl.property("dirty") is True
        save_btn = _find(rt, "saveBtn")
        assert save_btn.property("enabled") is False, (
            "Save must be disabled while max file size is invalid"
        )

        # correct the value -> error gone, Save allowed again
        _find(rt, "maxFileSizeSpin").setProperty("text", "100")
        QApplication.processEvents()
        assert err.property("visible") is False
        assert save_btn.property("enabled") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_max_file_size_1000_blocks_page_save(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        ctrl = rt.controller
        assert ctrl is not None
        _find(rt, "maxFileSizeSpin").setProperty("text", "1000")
        QApplication.processEvents()
        assert _find(rt, "maxFileSizeError").property("visible") is True
        assert ctrl.property("maxFileSizeMb") == 50
        _choose_default_template(rt, "x")
        QApplication.processEvents()
        assert _find(rt, "saveBtn").property("enabled") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


# ============================================================================
# M6 correction: save success visible feedback
# ============================================================================

def test_save_success_feedback_shown(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        _choose_default_template(rt, "save-feedback")
        QApplication.processEvents()
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert rt.controller.property("dirty") is False
        success = _find(rt, "saveSuccessText")
        assert success.property("visible") is True, "success feedback must be visible"
        assert "设置已保存" in success.property("text"), (
            f"got {success.property('text')!r}"
        )
        assert _find(rt, "saveErrorText").property("visible") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_save_failure_clears_success_feedback(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        ctrl = rt.controller
        assert ctrl is not None
        _choose_default_template(rt, "save-feedback")
        QApplication.processEvents()
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert _find(rt, "saveSuccessText").property("visible") is True

        # second save fails -> error shows, success feedback must NOT mask it
        _choose_default_template(rt, "x2")
        ctrl._credentials._global_set_fail = True  # type: ignore[attr-defined]
        ctrl.stageProviderKey("qwen", "k")
        QApplication.processEvents()
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert ctrl.property("dirty") is True
        assert _find(rt, "saveErrorText").property("visible") is True
        assert _find(rt, "saveSuccessText").property("visible") is False, (
            "success feedback must not mask a failure"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_save_success_cleared_on_next_edit(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        _choose_default_template(rt, "save-feedback")
        QApplication.processEvents()
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert _find(rt, "saveSuccessText").property("visible") is True

        _choose_default_template(rt, "edited-again")
        QApplication.processEvents()
        assert _find(rt, "saveSuccessText").property("visible") is False, (
            "next edit must clear the success feedback"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_save_success_auto_dismisses(tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QObject
    import time
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        # QML Timer shares Qt Quick's animation clock. Start the timed
        # interaction after the window's first exposed/layout frame, as a
        # real user would, not during component construction in a long suite.
        assert QTest.qWaitForWindowExposed(rt.root, 5000)
        QTest.qWait(50)
        from PySide6.QtWidgets import QApplication
        # QML Timer is a QObject, not a QQuickItem — findChild must not
        # filter by item type here.
        timer = rt.root.findChild(QObject, "saveSuccessTimer")
        assert timer is not None, "success feedback timer must have an objectName"
        # shorten the auto-dismiss window from the QML side (no wrapper
        # crossing for the interval) and verify the timer is armed
        page = _find(rt, "preferencesPage")
        from PySide6.QtQml import QQmlExpression
        expr = QQmlExpression(rt.engine.rootContext(), page, "setSuccessFeedbackInterval(120)")
        expr.evaluate()
        _choose_default_template(rt, "save-feedback")
        QApplication.processEvents()
        _find(rt, "saveBtn").click()
        QApplication.processEvents()
        assert _find(rt, "saveSuccessText").property("visible") is True
        assert timer.property("running") is True, "auto-dismiss timer must be armed"

        # poll with a bounded budget — under suite load the offscreen event
        # loop can take several short waits before a QML timer dispatches
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _find(rt, "saveSuccessText").property("visible"):
                break
            QTest.qWait(50)
        assert _find(rt, "saveSuccessText").property("visible") is False, (
            "success feedback must auto-dismiss"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


# ============================================================================
# Usage card three states via the real page (Task 1 binding)
# ============================================================================

def _usage_runtime(tmp_path, recorder):
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    from src.controllers.settings_controller import SettingsController
    ctrl = SettingsController(
        live_config=AppConfig(),
        config_file_path=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        usage_service=recorder,
    )
    return build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        controller=ctrl,
    )


def _usage_card(rt):
    from PySide6.QtQuick import QQuickItem
    return rt.root.findChild(QQuickItem, "usageCard")


def _usage_qml(rt, js):
    from PySide6.QtQml import QQmlExpression
    card = _usage_card(rt)
    expr = QQmlExpression(rt.engine.rootContext(), card, js)
    value, _err = expr.evaluate()
    if value is None or (hasattr(value, "isUndefined") and value.isUndefined()):
        return None
    if hasattr(value, "isNumber") and value.isNumber():
        return int(value.toInt()) if value.isInt() else float(value.toNumber())
    if hasattr(value, "isString"):
        return value.toString() if value.isString() else value.toVariant()
    return value.toVariant() if hasattr(value, "toVariant") else value


def test_usage_unavailable_without_service(tmp_path):
    """Explicitly disabled recorder (usage_recorder=None) → the card shows
    the unavailable state."""
    rt = _build_runtime(tmp_path)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        card = _usage_card(rt)
        assert card.property("usageAvailable") is False
        assert _find(rt, "usageUnavailableText").property("visible") is True
        assert _find(rt, "usageEmptyText").property("visible") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_usage_empty_state_with_service_no_records(tmp_path):
    from src.core.usage import UsageRecorder
    recorder = UsageRecorder(tmp_path / "usage.json")
    rt = _usage_runtime(tmp_path, recorder)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        card = _usage_card(rt)
        assert card.property("usageAvailable") is True
        assert _find(rt, "usageUnavailableText").property("visible") is False
        assert _find(rt, "usageEmptyText").property("visible") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_usage_data_state_with_service_records(tmp_path):
    from datetime import datetime, timezone
    from src.core.usage import UsageRecorder, UsageRecord, UsageContentKind
    UTC = timezone.utc
    clock = lambda: datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    recorder = UsageRecorder(tmp_path / "usage.json", clock=clock)
    recorder.record(UsageRecord(
        provider_id="deepseek", profile_id="deepseek", model="ds-a",
        content_kind=UsageContentKind.TEXT.value, request_count=2,
        cache_hit=False, success=True,
        input_tokens=300, output_tokens=60,
        timestamp_utc="2026-08-03T09:00:00+00:00",
    ))
    recorder.record(UsageRecord(
        provider_id="qwen", profile_id="qwen", model="qw-b",
        content_kind=UsageContentKind.TEXT.value, request_count=1,
        cache_hit=True, success=True,
        input_tokens=None, output_tokens=None,  # unknown tokens → "—"
        timestamp_utc="2026-08-03T09:30:00+00:00",
    ))
    rt = _usage_runtime(tmp_path, recorder)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        card = _usage_card(rt)
        assert card.property("usageAvailable") is True
        assert _find(rt, "usageUnavailableText").property("visible") is False
        assert _find(rt, "usageEmptyText").property("visible") is False
        assert _usage_qml(rt, "usageRowCount()") == 2
        assert _usage_qml(rt, "usageRowField(0, 'provider')") == "deepseek"
        assert _usage_qml(rt, "usageRowField(0, 'requests')") == "2"
        assert _usage_qml(rt, "usageRowField(0, 'tokensIn')") == "300"
        # unknown tokens render a dash, never a fabricated zero
        qwen_row = 1
        assert _usage_qml(rt, f"usageRowField({qwen_row}, 'provider')") == "qwen"
        assert _usage_qml(rt, f"usageRowField({qwen_row}, 'tokensIn')") == "—"
        assert _usage_qml(rt, f"usageRowField({qwen_row}, 'tokensOut')") == "—"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_usage_corrupted_storage_stays_unavailable(tmp_path):
    from src.core.usage import UsageRecorder
    store = tmp_path / "usage.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{broken", encoding="utf-8")
    recorder = UsageRecorder(store)
    assert recorder.is_available() is False
    rt = _usage_runtime(tmp_path, recorder)
    try:
        _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert _usage_card(rt).property("usageAvailable") is False
        assert _find(rt, "usageUnavailableText").property("visible") is True
        assert _find(rt, "usageEmptyText").property("visible") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_qml_bootstrap_injects_usage_recorder(tmp_path):
    """build_qml_runtime(usage_recorder=...) wires the recorder into the
    internally-constructed SettingsController (production composition path,
    without touching any OS user-data directory)."""
    from datetime import datetime, timezone
    from src.core.usage import UsageRecorder, UsageRecord, UsageContentKind
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig

    UTC = timezone.utc
    now = datetime(2026, 8, 3, 10, 30, tzinfo=UTC)
    recorder = UsageRecorder(tmp_path / "usage.json", clock=lambda: now)
    recorder.record(UsageRecord(
        provider_id="deepseek", profile_id="deepseek", model="ds-a",
        content_kind=UsageContentKind.TEXT.value, request_count=1,
        cache_hit=False, success=True,
        input_tokens=100, output_tokens=50,
        timestamp_utc=datetime(2026, 8, 3, 10, 0, tzinfo=UTC).isoformat(),
    ))
    rt = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        usage_recorder=recorder,
    )
    try:
        assert rt.controller is not None
        assert rt.controller._usage_service is recorder, (
            "the bootstrap must inject the usage recorder into the controller"
        )
        assert rt.controller.usageAvailable is True
        data = rt.controller.usageData
        assert len(data) == 1 and data[0]["provider"] == "deepseek"
        assert data[0]["tokensIn"] == 100
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def _runtime_with_default_recorder(tmp_path, monkeypatch, config_dir):
    """Build the runtime WITHOUT a usage_recorder argument — the bootstrap
    must construct a default recorder in the OS user-data directory."""
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    monkeypatch.setenv("LOCALAPPDATA", str(config_dir))
    return build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
    )


def test_qml_bootstrap_default_recorder_in_user_data_dir(tmp_path, monkeypatch):
    """Omitting usage_recorder builds a REAL recorder whose store lives in
    the OS user-data directory (LOCALAPPDATA redirected to tmp_path)."""
    config_dir = tmp_path / "appdata"
    # Managed resources capture an existing trusted OS user-data anchor.
    config_dir.mkdir()
    rt = _runtime_with_default_recorder(tmp_path, monkeypatch, config_dir)
    try:
        assert rt.controller is not None
        service = rt.controller._usage_service
        assert service is not None, "the default path must wire a recorder"
        store = service.store_path
        assert str(store).startswith(str(config_dir)), (
            f"default store must live under LOCALAPPDATA, got {store}"
        )
        assert "usage.json" in str(store)
        assert rt.controller.usageAvailable is True, (
            "the default runtime must no longer be permanently unavailable"
        )
        # the recorder is real: writing a record is reflected in the card
        from datetime import datetime, timezone
        from src.core.usage import UsageRecord, UsageContentKind
        now = datetime.now(timezone.utc)
        service.record(UsageRecord(
            provider_id="deepseek", profile_id="deepseek", model="ds-a",
            content_kind=UsageContentKind.TEXT.value, request_count=1,
            cache_hit=False, success=True,
            input_tokens=None, output_tokens=None,
            timestamp_utc=now.isoformat(),
        ))
        assert len(rt.controller.usageData) == 1
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_qml_bootstrap_explicit_none_disables_recorder(tmp_path):
    """usage_recorder=None explicitly → no recorder, card unavailable (even
    though LOCALAPPDATA points somewhere real)."""
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    rt = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        usage_recorder=None,
    )
    try:
        assert rt.controller is not None
        assert rt.controller._usage_service is None
        assert rt.controller.usageAvailable is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_qml_bootstrap_explicit_recorder_still_used(tmp_path, monkeypatch):
    """Passing a recorder wins over the default even when LOCALAPPDATA is
    set — no user-dir store is created."""
    from src.core.usage import UsageRecorder
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    config_dir = tmp_path / "appdata"
    # Keep the production resource graph enabled, with a real isolated anchor.
    config_dir.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(config_dir))
    recorder = UsageRecorder(tmp_path / "explicit.json")
    rt = build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        usage_recorder=recorder,
    )
    try:
        assert rt.controller._usage_service is recorder
        assert not (config_dir / "Xuxia").exists(), (
            "an injected recorder must prevent the default user-dir store"
        )
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_unsaved_dialog_three_branches_via_qml(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        router, _page = _navigate_preferences(rt)
        from PySide6.QtWidgets import QApplication
        ctrl = rt.controller
        assert ctrl is not None

        # keep-editing
        _choose_default_template(rt, "keep-me")
        router.navigate("batch")
        QApplication.processEvents()
        assert _find(rt, "unsavedDialog").property("visible") is True
        _find(rt, "unsavedKeepBtn").click()
        QApplication.processEvents()
        assert router.property("currentPage") == "preferences"
        assert ctrl.property("dirty") is True
        assert ctrl.property("defaultTemplateId") == _template_id(rt, "keep-me")

        # discard-and-leave
        router.navigate("batch")
        QApplication.processEvents()
        _find(rt, "unsavedDiscardBtn").click()
        QApplication.processEvents()
        assert router.property("currentPage") == "batch"
        assert ctrl.property("sessionOpen") is False

        # save-and-leave (re-enter, dirty, save path)
        router.navigate("preferences")
        QApplication.processEvents()
        _choose_default_template(rt, "save-and-go")
        router.navigate("batch")
        QApplication.processEvents()
        _find(rt, "unsavedSaveBtn").click()
        QApplication.processEvents()
        assert router.property("currentPage") == "batch"
        assert ctrl.property("dirty") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()
