"""General Settings Card — real runtime interaction tests (M6 gate).

The card's displayed values must come from the controller, and user edits
via the real controls must mutate the controller draft.  QML warnings must
be zero in every scenario (real I18n injected).
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


def _build_handle(ctrl):
    from tests.qml.conftest import make_handle
    return make_handle(SRC / "GeneralSettingsCard.qml", ctrl=ctrl)


def _make_ctrl(tmp_path):
    from src.controllers.settings_controller import SettingsController
    from src.models.app_config import AppConfig
    live = AppConfig()
    return SettingsController(
        live_config=live,
        config_file_path=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
    )


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


def test_general_card_displays_ctrl_values(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.language = "en_US"
    ctrl.defaultTemplateId = "finance-2026"
    ctrl.maxFileSizeMb = 88
    ctrl.maxContentChars = 7777

    h = _build_handle(ctrl)
    try:
        assert _find(h, "languageCombo").property("currentIndex") == 1
        assert _find(h, "defaultTemplateField").property("currentIndex") == -1
        assert _find(h, "defaultTemplateError").property("visible") is True
        assert ctrl.defaultTemplateId == "finance-2026"
        assert _find(h, "maxFileSizeSpin").property("value") == 88
        assert _find(h, "maxContentCharsSpin").property("value") == 7777
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_language_combo_writes_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    assert ctrl.language == "zh_CN"

    h = _build_handle(ctrl)
    try:
        combo = _find(h, "languageCombo")
        combo.setProperty("currentIndex", 1)  # en_US
        combo.activated.emit(1)
        assert ctrl.language == "en_US", "combo must write to controller draft"
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_template_selection_writes_ctrl_draft(tmp_path):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    ctrl.defaultTemplateId = "missing-template"
    h = _build_handle(ctrl)
    try:
        field = _find(h, "defaultTemplateField")
        point = field.mapToScene(QPointF(field.width()/2, field.height()/2)).toPoint()
        QTest.mouseClick(h._host_view, Qt.LeftButton, Qt.NoModifier, point)
        QTest.keyClick(h._host_view, Qt.Key_Home)
        QTest.keyClick(h._host_view, Qt.Key_Return)
        assert ctrl.defaultTemplateId == ""
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_spinboxes_write_ctrl_draft(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        _find(h, "maxFileSizeSpin").setProperty("value", 120)
        _find(h, "maxContentCharsSpin").setProperty("value", 6000)
        assert ctrl.maxFileSizeMb == 120
        assert ctrl.maxContentChars == 6000
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_ctrl_change_updates_card_display(tmp_path):
    """Display follows the controller even when changed from outside QML."""
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        ctrl.maxFileSizeMb = 150  # external change -> draftChanged
        assert _find(h, "maxFileSizeSpin").property("value") == 150
        ctrl.language = "en_US"
        assert _find(h, "languageCombo").property("currentIndex") == 1
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_card_parses_without_controller(tmp_path):
    """Card loads cleanly even with ctrl=null (no warnings)."""
    from tests.qml.conftest import make_handle
    h = make_handle(SRC / "GeneralSettingsCard.qml")
    try:
        assert h.root is not None
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_object_names_present(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        for name in ("languageCombo", "defaultTemplateField", "maxFileSizeSpin", "maxContentCharsSpin", "maxFileSizeError"):
            assert _find(h, name) is not None, f"missing objectName {name}"
    finally:
        h.cleanup()


# ============================================================================
# M6 correction: visible validation for out-of-range max file size
# ============================================================================

def _max_file_size_error(h):
    return _find(h, "maxFileSizeError")


def test_max_file_size_zero_shows_error_and_no_write(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        field = _find(h, "maxFileSizeSpin")
        field.setProperty("text", "0")
        assert _max_file_size_error(h).property("visible") is True, (
            "0 must show the inline range error"
        )
        assert field.property("text") == "0", "raw editing text must be preserved"
        assert ctrl.maxFileSizeMb == 50, "0 must never reach the draft"
        assert not ctrl.dirty, "an invalid value must not dirty the draft"
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_max_file_size_1000_shows_error_and_no_write(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        field = _find(h, "maxFileSizeSpin")
        field.setProperty("text", "1000")
        assert _max_file_size_error(h).property("visible") is True
        assert field.property("text") == "1000", "raw editing text must be preserved"
        assert ctrl.maxFileSizeMb == 50, "1000 must never reach the draft"
        assert not ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_max_file_size_boundaries_1_and_500_valid(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        field = _find(h, "maxFileSizeSpin")
        field.setProperty("text", "1")
        assert _max_file_size_error(h).property("visible") is False
        assert ctrl.maxFileSizeMb == 1
        field.setProperty("text", "500")
        assert _max_file_size_error(h).property("visible") is False
        assert ctrl.maxFileSizeMb == 500
        assert ctrl.dirty
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_max_file_size_correction_clears_error(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        field = _find(h, "maxFileSizeSpin")
        field.setProperty("text", "1000")
        assert _max_file_size_error(h).property("visible") is True
        field.setProperty("text", "200")
        assert _max_file_size_error(h).property("visible") is False, (
            "correcting to a legal value must clear the error"
        )
        assert ctrl.maxFileSizeMb == 200
        h.assert_zero_warnings()
    finally:
        h.cleanup()


def test_max_file_size_error_text_shows_range(tmp_path):
    ctrl = _make_ctrl(tmp_path)
    ctrl.openSession()
    h = _build_handle(ctrl)
    try:
        _find(h, "maxFileSizeSpin").setProperty("text", "0")
        err = _max_file_size_error(h).property("text")
        assert "1" in err and "500" in err, f"error must state the 1-500 range, got {err!r}"
        h.assert_zero_warnings()
    finally:
        h.cleanup()
