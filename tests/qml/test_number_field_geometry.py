"""Numeric-control geometry regression tests (M6 correction).

Native Windows showed ``4000`` and ``500 MB`` clipped to ``00`` at 1000×700
in both locales.  These tests verify, at BOTH 1000×700 and 900×640, that the
numeric area of every General / Cache / ResourceLimit numeric control is wide
enough to fully display the longest in-range digit string.

Geometry/control-level only — no screenshots, no goldens.
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).parent.parent.parent / "src" / "ui_qml"

# (control objectName, longest in-range digits, is_spinbox)
_CONTROLS_GENERAL = [
    ("maxFileSizeSpin", "500", False),      # validated field component
    ("maxContentCharsSpin", "16000", True),  # General spinbox
]
_CONTROLS_CACHE = [
    ("cacheMaxMbSpin", "10000", True),
    ("cacheTtlDaysSpin", "90", True),
]
_CONTROLS_RESOURCE = [
    ("maxConcurrentSpin", "20", True),
    ("timeoutSpin", "300", True),
    ("maxRetriesSpin", "10", True),
    ("maxPdfPagesSpin", "200", True),
    ("maxVideoKeyframesSpin", "32", True),
]


def _metrics(width_px):
    from PySide6.QtGui import QFont, QFontMetricsF
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(13)  # DesignTokens.fontSizeMd
    return QFontMetricsF(font).horizontalAdvance(width_px)


def _make_card(name):
    from tests.qml.conftest import make_handle
    return make_handle(SRC / name)


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


def _assert_fits(handle, object_name, longest, is_spinbox, tag):
    item = _find(handle, object_name)
    assert item is not None, f"{tag}: missing {object_name}"
    w = float(item.property("width"))
    adv = _metrics(longest)
    # a TextField needs ~16px padding; a SpinBox needs the value area PLUS
    # its up/down indicator strip (Basic style) and padding.
    reserve = 60 if is_spinbox else 20
    assert w >= adv + reserve, (
        f"{tag}: {object_name} width {w:.1f}px < {longest} ({adv:.1f}px) + {reserve}px"
    )


def test_general_numbers_fully_visible_1000x700():
    h = _make_card("GeneralSettingsCard.qml")
    try:
        assert h.root.property("width") == 1000 and h.root.property("height") == 700
        for name, digits, spin in _CONTROLS_GENERAL:
            _assert_fits(h, name, digits, spin, "1000x700")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_general_numbers_fully_visible_900x640():
    from tests.qml.conftest import make_handle
    h = make_handle(SRC / "GeneralSettingsCard.qml", w=900, h=640)
    try:
        for name, digits, spin in _CONTROLS_GENERAL:
            _assert_fits(h, name, digits, spin, "900x640")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_numbers_fully_visible_1000x700():
    h = _make_card("CacheCard.qml")
    try:
        for name, digits, spin in _CONTROLS_CACHE:
            _assert_fits(h, name, digits, spin, "1000x700")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_cache_numbers_fully_visible_900x640():
    from tests.qml.conftest import make_handle
    h = make_handle(SRC / "CacheCard.qml", w=900, h=640)
    try:
        for name, digits, spin in _CONTROLS_CACHE:
            _assert_fits(h, name, digits, spin, "900x640")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_resource_numbers_fully_visible_1000x700():
    h = _make_card("ResourceLimitsCard.qml")
    try:
        for name, digits, spin in _CONTROLS_RESOURCE:
            _assert_fits(h, name, digits, spin, "1000x700")
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_resource_numbers_fully_visible_900x640():
    from tests.qml.conftest import make_handle
    h = make_handle(SRC / "ResourceLimitsCard.qml", w=900, h=640)
    try:
        for name, digits, spin in _CONTROLS_RESOURCE:
            _assert_fits(h, name, digits, spin, "900x640")
        h.assert_zero_warnings()
    finally:
        h.cleanup()
