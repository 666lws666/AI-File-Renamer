"""Quality, Resource, Privacy, Cache Cards — real runtime interaction tests
(M6 gate).

Display values come from ctrl; user edits on real controls mutate the
controller draft; no shadow properties mask controller state; Cache TTL is
expressed in DAYS; the clear button calls ctrl.clearCache() and reflects
cacheClearFinished(bool).  Every scenario: zero QML warnings.
"""
import os, sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).parent.parent.parent / "src" / "ui_qml"


class FakeCredentialStore:
    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get(self, s, a):
        return self.values.get((s, a))

    def set(self, s, a, v):
        self.values[(s, a)] = v
        return True

    def delete(self, s, a):
        self.values.pop((s, a), None)
        return True


class FakeCacheService:
    def __init__(self, fail=False):
        self.fail = fail
        self.cleared = False

    def clear(self):
        if self.fail:
            raise RuntimeError("cache service failure")
        self.cleared = True


def _make_ctrl(tmp_path, cache_service=None):
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    live = AppConfig()
    return SettingsController(
        live_config=live,
        config_file_path=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        cache_service=cache_service,
    )


def _handle(name, ctrl=None):
    from tests.qml.conftest import make_handle
    return make_handle(SRC / name, ctrl=ctrl)


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


# ============================================================================
# Quality card
# ============================================================================

def test_quality_card_no_shadow_display_from_ctrl(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.qualityMode = "high"
    h = _handle("QualityCard.qml", ctrl)
    try:
        assert _find(h, "qualityHighRadio").property("checked") is True
        assert _find(h, "qualityEconomyRadio").property("checked") is False
        assert _find(h, "qualityBalancedRadio").property("checked") is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_quality_radio_writes_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    assert ctrl.qualityMode == "balanced"
    h = _handle("QualityCard.qml", ctrl)
    try:
        _find(h, "qualityEconomyRadio").setProperty("checked", True)
        assert ctrl.qualityMode == "economy"
        assert ctrl.dirty
        _find(h, "qualityHighRadio").setProperty("checked", True)
        assert ctrl.qualityMode == "high"
        # dirty already true — the second change must still reach the draft
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_quality_modes_all_three(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("QualityCard.qml", ctrl)
    try:
        for radio_name, mode in (
            ("qualityEconomyRadio", "economy"),
            ("qualityBalancedRadio", "balanced"),
            ("qualityHighRadio", "high"),
        ):
            _find(h, radio_name).setProperty("checked", True)
            assert ctrl.qualityMode == mode, f"{radio_name} must set {mode}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_quality_no_price_words(tmp_path):
    text = (SRC / "QualityCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "budget", "price", "cost", "currency", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in QualityCard.qml"


# ============================================================================
# Resource limits card
# ============================================================================

def test_resource_card_displays_ctrl_values(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.maxConcurrentRequests = 6
    ctrl.requestTimeoutSeconds = 90
    ctrl.maxRetries = 5
    ctrl.maxPdfPages = 77
    ctrl.maxVideoKeyframes = 12
    h = _handle("ResourceLimitsCard.qml", ctrl)
    try:
        assert _find(h, "maxConcurrentSpin").property("value") == 6
        assert _find(h, "timeoutSpin").property("value") == 90
        assert _find(h, "maxRetriesSpin").property("value") == 5
        assert _find(h, "maxPdfPagesSpin").property("value") == 77
        assert _find(h, "maxVideoKeyframesSpin").property("value") == 12
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_resource_spinboxes_write_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("ResourceLimitsCard.qml", ctrl)
    try:
        _find(h, "maxConcurrentSpin").setProperty("value", 8)
        _find(h, "timeoutSpin").setProperty("value", 45)
        _find(h, "maxRetriesSpin").setProperty("value", 2)
        _find(h, "maxPdfPagesSpin").setProperty("value", 100)
        _find(h, "maxVideoKeyframesSpin").setProperty("value", 16)
        assert ctrl.maxConcurrentRequests == 8
        assert ctrl.requestTimeoutSeconds == 45
        assert ctrl.maxRetries == 2
        assert ctrl.maxPdfPages == 100
        assert ctrl.maxVideoKeyframes == 16
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


# ============================================================================
# Privacy card
# ============================================================================

def test_privacy_switches_display_ctrl_values(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.allowTextCloud = False
    ctrl.allowVisionCloud = False
    ctrl.allowVideoKeyframesCloud = False
    h = _handle("PrivacyCard.qml", ctrl)
    try:
        assert _find(h, "allowTextCloudSwitch").property("checked") is False
        assert _find(h, "allowVisionCloudSwitch").property("checked") is False
        assert _find(h, "allowVideoCloudSwitch").property("checked") is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_privacy_switches_write_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    assert ctrl.allowTextCloud is True
    h = _handle("PrivacyCard.qml", ctrl)
    try:
        _find(h, "allowTextCloudSwitch").setProperty("checked", False)
        assert ctrl.allowTextCloud is False
        _find(h, "allowVisionCloudSwitch").setProperty("checked", True)
        assert ctrl.allowVisionCloud is True
        _find(h, "allowVideoCloudSwitch").setProperty("checked", False)
        assert ctrl.allowVideoKeyframesCloud is False
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_privacy_no_price_words(tmp_path):
    text = (SRC / "PrivacyCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "budget", "price", "cost", "currency", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in PrivacyCard.qml"


# ============================================================================
# Cache card
# ============================================================================

def test_cache_card_displays_ctrl_values(tmp_path):
    ctrl = _make_ctrl(tmp_path, cache_service=FakeCacheService())
    ctrl.openSession()
    ctrl.cacheEnabled = False
    ctrl.cacheMaxMb = 900
    ctrl.cacheTtlDays = 14
    h = _handle("CacheCard.qml", ctrl)
    try:
        assert _find(h, "cacheEnabledSwitch").property("checked") is False
        assert _find(h, "cacheMaxMbSpin").property("value") == 900
        # TTL is in DAYS and matches cacheTtlDays (never hours)
        assert _find(h, "cacheTtlDaysSpin").property("value") == 14
        assert _find(h, "cacheTtlDaysSpin").property("to") == 90
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_controls_write_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path, cache_service=FakeCacheService())
    ctrl.openSession()
    h = _handle("CacheCard.qml", ctrl)
    try:
        _find(h, "cacheEnabledSwitch").setProperty("checked", False)
        _find(h, "cacheMaxMbSpin").setProperty("value", 750)
        _find(h, "cacheTtlDaysSpin").setProperty("value", 21)
        assert ctrl.cacheEnabled is False
        assert ctrl.cacheMaxMb == 750
        assert ctrl.cacheTtlDays == 21  # days, not hours
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_clear_button_calls_ctrl_and_shows_success(tmp_path):
    service = FakeCacheService()
    ctrl = _make_ctrl(tmp_path, cache_service=service)
    ctrl.openSession()
    h = _handle("CacheCard.qml", ctrl)
    try:
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        btn = _find(h, "cacheClearBtn")
        assert btn is not None
        QMetaObject.invokeMethod(btn, "click")
        QApplication.processEvents()
        assert service.cleared, "ctrl.clearCache() must be invoked"
        assert btn.property("text") != ""
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_clear_failure_shows_error(tmp_path):
    service = FakeCacheService(fail=True)
    ctrl = _make_ctrl(tmp_path, cache_service=service)
    ctrl.openSession()
    h = _handle("CacheCard.qml", ctrl)
    try:
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        btn = _find(h, "cacheClearBtn")
        QMetaObject.invokeMethod(btn, "click")
        QApplication.processEvents()
        # cacheClearFinished(false) must switch the button to the failure text
        text = btn.property("text")
        assert text != ""
        assert "失败" in text or "Failed" in text
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_ttl_uses_days_not_hours_in_locale(tmp_path):
    """The i18n string must say days (天), never hours (小时)."""
    import json
    zh = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "zh_CN.json", encoding="utf-8"))
    en = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "en_US.json", encoding="utf-8"))
    assert "小时" not in zh["prefs.cache.ttl"]
    assert "hours" not in en["prefs.cache.ttl"].lower()
    assert "天" in zh["prefs.cache.ttl"]
    assert "days" in en["prefs.cache.ttl"].lower()


def test_cache_card_no_price_words(tmp_path):
    text = (SRC / "CacheCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "budget", "price", "cost", "currency", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in CacheCard.qml"


def test_no_budget_card():
    assert not (SRC / "BudgetCard.qml").exists()


# ============================================================================
# M6 correction: Privacy video notice layout
# ============================================================================

def test_privacy_video_notice_has_height_and_sits_inside_card():
    for loc in ("zh-CN", "en-US"):
        from tests.qml.conftest import make_handle
        h = make_handle(SRC / "PrivacyCard.qml", loc=loc)
        try:
            box = _find(h, "videoNoticeBox")
            text = _find(h, "videoNoticeText")
            assert box is not None and text is not None, f"{loc}: missing notice items"
            box_h = float(box.property("height"))
            assert box_h > 30, f"{loc}: notice container has no effective height ({box_h})"
            content_h = float(text.property("contentHeight"))
            assert content_h <= box_h, (
                f"{loc}: text ({content_h:.1f}px) overflows the container ({box_h:.1f}px)"
            )
            # fully inside the card (bottom margin is spacingXl = 24)
            y = float(box.property("y"))
            card_h = float(h.root.property("height"))
            assert y + box_h <= card_h - 20 + 1, (
                f"{loc}: notice bottom {y + box_h:.1f} exceeds card {card_h:.1f}"
            )
            h.assert_zero_warnings()
        finally:
            h.cleanup()


def test_privacy_video_notice_copy_preserved():
    import json
    zh = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "zh_CN.json", encoding="utf-8"))
    en = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "en_US.json", encoding="utf-8"))
    zh_note = zh["prefs.privacy.video.notice"]
    en_note = en["prefs.privacy.video.notice"]
    assert "完整视频" in zh_note and "不会上传" in zh_note
    assert "never uploaded" in en_note or "never uploaded" in en_note.lower()
    assert "4" in zh_note and "8" in zh_note  # 约 4-8 个关键帧
    assert "4" in en_note and "8" in en_note


# ============================================================================
# M6 correction: Cache current usage state
# ============================================================================

def test_cache_current_usage_unavailable_by_default(tmp_path):
    """No stats service injected -> explicit unavailable, never a fake 0 MB."""
    ctrl = _make_ctrl(tmp_path, cache_service=FakeCacheService())
    ctrl.openSession()
    h = _handle("CacheCard.qml", ctrl)
    try:
        row = _find(h, "cacheUsageText")
        assert row is not None, "missing cacheUsageText objectName"
        text = row.property("text")
        assert text != "", "current-usage row must render something"
        assert "0 MB" not in text, f"unavailable must not forge 0 MB, got {text!r}"
        assert ("尚未统计" in text) or ("Not yet tracked" in text), f"got {text!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_current_usage_injected_value(tmp_path):
    ctrl = _make_ctrl(tmp_path, cache_service=FakeCacheService())
    ctrl.openSession()
    h = _handle("CacheCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageMb", 42)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        text = _find(h, "cacheUsageText").property("text")
        assert "42 MB" in text, f"injected usage must render 42 MB, got {text!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()
