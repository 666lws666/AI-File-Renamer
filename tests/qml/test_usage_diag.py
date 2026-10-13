"""Usage and Diagnostics Cards — real runtime interaction tests (M6 gate).

- UsageCard shows an explicit unavailable state (no real usage service in
  the M6 slice); it never manufactures fake data or price data.
- DiagnosticsCard export button calls ctrl.requestDiagnosticsExport() and
  reflects the diagnosticsExportRequested signal.
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


def _make_ctrl(tmp_path):
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    live = AppConfig()
    return SettingsController(
        live_config=live,
        config_file_path=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
    )


def _handle(name, ctrl=None):
    from tests.qml.conftest import make_handle
    return make_handle(SRC / name, ctrl=ctrl)


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


# ============================================================================
# Usage card
# ============================================================================

def test_usage_card_shows_unavailable_state(tmp_path):
    """No real usage service exists — explicit unavailable state, no fake data."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        text_item = _find(h, "usageUnavailableText")
        assert text_item is not None
        assert text_item.property("text") != ""
        assert "不可用" in text_item.property("text") or "unavailable" in text_item.property("text").lower()
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_card_no_fake_table(tmp_path):
    """The card must not render a usage table with manufactured records."""
    text = (SRC / "UsageCard.qml").read_text(encoding="utf-8")
    assert "ListView" not in text
    assert "usageData.length > 0" not in text


def test_usage_card_no_price_words(tmp_path):
    text = (SRC / "UsageCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "price", "cost", "currency", "budget", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in UsageCard.qml"


def test_usage_no_price_in_locale(tmp_path):
    import json
    zh = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "zh_CN.json", encoding="utf-8"))
    en = json.load(open(Path(__file__).parent.parent.parent / "src" / "utils" / "i18n" / "locales" / "en_US.json", encoding="utf-8"))
    for key in ("prefs.usage.title", "prefs.usage.unavailable", "prefs.usage.empty"):
        for word in ["价格", "费用", "预算", "CNY", "USD", "currency", "pricing"]:
            assert word not in zh[key], f"Forbidden '{word}' in zh {key}"
        for word in ["price", "cost", "currency", "budget", "pricing"]:
            assert word not in en[key].lower(), f"Forbidden '{word}' in en {key}"


# ============================================================================
# M6 correction: usage column alignment (header and rows share geometry)
# ============================================================================

_RECORD = {"provider": "Qwen", "requests": 12, "tokensIn": 3456, "tokensOut": 789}
_FIELDS = ("provider", "requests", "tokensIn", "tokensOut")


def _usage_handle(tmp_path, w, h):
    from tests.qml.conftest import make_handle
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    handle = make_handle(SRC / "UsageCard.qml", w=w, h=h, ctrl=ctrl)
    handle.root.setProperty("usageAvailable", True)
    handle.root.setProperty("usageData", [_RECORD])
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    return handle


def _assert_columns_aligned(handle, tag):
    for field in _FIELDS:
        hx = _qml_call(handle, f"headerColumnX('{field}')")
        rx = _qml_call(handle, f"rowColumnX(0, '{field}')")
        assert hx is not None and rx is not None, f"{tag}: missing geometry for {field}"
        assert abs(hx - rx) <= 1.0, (
            f"{tag}: column '{field}' header x={hx:.1f} vs row x={rx:.1f}"
        )


def test_usage_header_row_alignment_1000x700(tmp_path):
    """Header and data row must share one column geometry (native evidence:
    header was left-contiguous while values spread apart)."""
    h = _usage_handle(tmp_path, 1000, 700)
    try:
        assert _qml_call(h, "usageRowCount()") == 1
        _assert_columns_aligned(h, "1000x700")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_header_row_alignment_900x640(tmp_path):
    h = _usage_handle(tmp_path, 900, 640)
    try:
        assert _qml_call(h, "usageRowCount()") == 1
        _assert_columns_aligned(h, "900x640")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_multi_record_rows_all_aligned(tmp_path):
    from PySide6.QtWidgets import QApplication
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageData", [_RECORD, {"provider": "deepseek", "requests": 3, "tokensIn": 45, "tokensOut": 6}])
        QApplication.processEvents()
        assert _qml_call(h, "usageRowCount()") == 2
        for i in (0, 1):
            for field in _FIELDS:
                hx = _qml_call(h, f"headerColumnX('{field}')")
                rx = _qml_call(h, f"rowColumnX({i}, '{field}')")
                assert abs(hx - rx) <= 1.0, (
                    f"row {i} column '{field}': header {hx:.1f} vs row {rx:.1f}"
                )
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_values_fully_visible_in_cells(tmp_path):
    """No clipping: each cell's rendered content must fit inside its column,
    and the last column must not overflow the table area."""
    for w, h in ((1000, 700), (900, 640)):
        handle = _usage_handle(tmp_path, w, h)
        try:
            for field in _FIELDS:
                cw = _qml_call(handle, f"rowColumnContentWidth(0, '{field}')")
                ccol = _qml_call(handle, f"rowColumnWidth(0, '{field}')")
                assert cw is not None and ccol is not None, f"{w}x{h}: missing {field}"
                assert cw <= ccol + 0.5, (
                    f"{w}x{h}: '{field}' content {cw:.1f}px exceeds cell {ccol:.1f}px"
                )
            right = _qml_call(handle, "headerColumnRight('tokensOut')")
            table = _qml_call(handle, "tableWidth()")
            assert right <= table + 0.5, (
                f"{w}x{h}: table right edge {right:.1f} overflows width {table:.1f}"
            )
            handle.assert_zero_warnings()
        finally:
            handle.cleanup()


def test_usage_stable_columns_requests_tokens(tmp_path):
    """Requests / tokens columns keep stable widths while provider expands."""
    h = _usage_handle(tmp_path, 1000, 700)
    try:
        for field in ("requests", "tokensIn", "tokensOut"):
            hw = _qml_call(h, f"headerColumnWidth('{field}')")
            assert hw is not None and hw >= 80, f"{field} column too narrow: {hw}"
        pw = _qml_call(h, "headerColumnWidth('provider')")
        assert pw is not None and pw >= 80, f"provider column collapsed: {pw}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


# ============================================================================
# M6 correction: usage data rendering (non-monetary records)
# ============================================================================

def test_usage_empty_state_with_service(tmp_path):
    """Service connected but no records -> explicit empty state."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageData", [])
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        empty = _find(h, "usageEmptyText")
        assert empty is not None and empty.property("visible") is True
        assert "暂无使用数据" in empty.property("text") or "No usage data" in empty.property("text")
        assert _find(h, "usageUnavailableText").property("visible") is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_one_record_renders_fields(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageData", [
            {"provider": "deepseek", "requests": 12, "tokensIn": 345, "tokensOut": 678},
        ])
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert _qml_call(h, "usageRowCount()") == 1
        assert _qml_call(h, "usageRowField(0, 'provider')") == "deepseek"
        assert _qml_call(h, "usageRowField(0, 'requests')") == "12"
        assert _qml_call(h, "usageRowField(0, 'tokensIn')") == "345"
        assert _qml_call(h, "usageRowField(0, 'tokensOut')") == "678"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_multi_record_renders_all(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageData", [
            {"provider": "deepseek", "requests": 10, "tokensIn": 100, "tokensOut": 200},
            {"provider": "qwen", "requests": 5, "tokensIn": 50, "tokensOut": 60},
        ])
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert _qml_call(h, "usageRowCount()") == 2
        assert _qml_call(h, "usageRowField(0, 'provider')") == "deepseek"
        assert _qml_call(h, "usageRowField(1, 'provider')") == "qwen"
        assert _qml_call(h, "usageRowField(1, 'requests')") == "5"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_usage_available_with_records_hides_empty_state(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _handle("UsageCard.qml", ctrl)
    try:
        h.root.setProperty("usageAvailable", True)
        h.root.setProperty("usageData", [
            {"provider": "kimi", "requests": 1, "tokensIn": 2, "tokensOut": 3},
        ])
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert _find(h, "usageEmptyText").property("visible") is False
        assert _find(h, "usageUnavailableText").property("visible") is False
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def _qml_call(handle, js):
    from PySide6.QtQml import QQmlExpression
    expr = QQmlExpression(handle.engine.rootContext(), handle.root, js)
    value, _err = expr.evaluate()
    if value is None or (hasattr(value, "isUndefined") and value.isUndefined()):
        return None
    if hasattr(value, "isNumber") and value.isNumber():
        return int(value.toInt()) if value.isInt() else float(value.toNumber())
    if hasattr(value, "isString"):
        return value.toString() if value.isString() else value.toVariant()
    return value.toVariant() if hasattr(value, "toVariant") else value


# ============================================================================
# Diagnostics card
# ============================================================================

def test_diagnostics_export_disabled_when_no_service(tmp_path):
    """GATE-9: with serviceAvailable=false the export button is DISABLED,
    clicking it neither calls the controller nor claims completion."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    emitted: list[bool] = []
    ctrl.diagnosticsExportRequested.connect(lambda: emitted.append(True))
    h = _handle("DiagnosticsCard.qml", ctrl)
    try:
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        btn = _find(h, "diagnosticsExportBtn")
        assert btn is not None
        assert btn.property("enabled") is False, (
            "export must be disabled while the diagnostic service is unavailable"
        )
        QMetaObject.invokeMethod(btn, "click")
        QApplication.processEvents()
        assert emitted == [], "no request may be emitted without a service"
        # the button text must never claim completion
        assert "done" not in str(btn.property("text")).lower()
        assert "完成" not in str(btn.property("text"))
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_diagnostics_export_requests_when_service_available(tmp_path):
    """With a connected service the button is enabled and clicking it
    requests the export — completion is reported by a FUTURE dedicated
    signal, never by the request itself."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    emitted: list[bool] = []
    ctrl.diagnosticsExportRequested.connect(lambda: emitted.append(True))
    h = _handle("DiagnosticsCard.qml", ctrl)
    try:
        from PySide6.QtCore import QMetaObject
        from PySide6.QtWidgets import QApplication
        h.root.setProperty("serviceAvailable", True)
        QApplication.processEvents()
        btn = _find(h, "diagnosticsExportBtn")
        assert btn.property("enabled") is True
        QMetaObject.invokeMethod(btn, "click")
        QApplication.processEvents()
        assert emitted == [True], "export button must call ctrl.requestDiagnosticsExport()"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_diagnostics_card_loads_without_ctrl():
    h = _handle("DiagnosticsCard.qml")
    try:
        assert h.root is not None
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_diagnostics_no_price_words(tmp_path):
    text = (SRC / "DiagnosticsCard.qml").read_text(encoding="utf-8")
    for word in ["价格", "费用", "预算", "CNY", "USD", "price", "cost", "currency", "budget", "pricing"]:
        assert word not in text, f"Forbidden '{word}' in DiagnosticsCard.qml"
