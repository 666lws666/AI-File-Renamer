"""Preferences page assembly + unsaved-changes navigation guard (M6 gate F).

Runtime tests drive the REAL navigation: main.qml -> Shell -> PageRouter ->
Preferences, then verify all four paths:
  save-and-leave, discard-and-leave, keep-editing, dirty=false direct.
"""
import os, sys
from pathlib import Path

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


def _build_runtime(tmp_path, service=None):
    from src.qml_bootstrap import build_qml_runtime
    from src.models.app_config import AppConfig
    return build_qml_runtime(
        live_config=AppConfig(),
        config_file=tmp_path / "settings.json",
        credential_store=FakeCredentialStore(),
        main_qml=SRC / "main.qml",
        # not testing the default recorder — keep the user dir untouched
        usage_recorder=None,
    )


def _find(handle, object_name):
    from PySide6.QtQuick import QQuickItem
    return handle.root.findChild(QQuickItem, object_name)


def _navigate_to_preferences(rt):
    from PySide6.QtWidgets import QApplication
    router = _find(rt, "pageRouter")
    router.navigate("preferences")
    QApplication.processEvents()
    item = router.property("currentItem")
    assert item is not None and item.property("objectName") == "preferencesPage"
    return router, item


def _make_dirty(page):
    from PySide6.QtCore import QObject
    field = page.findChild(QObject, "defaultTemplateField")
    assert field.property("count") > 1
    field.setProperty("currentIndex", 1)
    field.activated.emit(1)
    assert page.property("ctrl").property("dirty") is True


# ============================================================================
# Assembly (static)
# ============================================================================

def test_preferences_page_qml_exists():
    assert (SRC / "PreferencesPage.qml").exists()


def test_page_router_references_preferences():
    text = (SRC / "PageRouter.qml").read_text(encoding="utf-8")
    assert "preferencesComponent" in text
    assert "PreferencesPage" in text


def test_all_cards_referenced_in_page():
    text = (SRC / "PreferencesPage.qml").read_text(encoding="utf-8")
    cards = [
        "GeneralSettingsCard", "ProviderSettingsCard",
        "QualityCard", "ResourceLimitsCard", "PrivacyCard",
        "CacheCard", "UsageCard", "DiagnosticsCard",
    ]
    for card in cards:
        assert card in text, f"PreferencesPage missing {card}"


def test_save_cancel_buttons_present():
    text = (SRC / "PreferencesPage.qml").read_text(encoding="utf-8")
    assert "saveBtn" in text
    assert "cancelBtn" in text


def test_no_deferred_preferences():
    text = (SRC / "PageRouter.qml").read_text(encoding="utf-8")
    assert 'case "preferences": comp = deferredComponent' not in text
    assert 'preferencesComponent' in text


def test_unsaved_dialog_object_names():
    text = (SRC / "PageRouter.qml").read_text(encoding="utf-8")
    for name in ("unsavedDialog", "unsavedSaveBtn", "unsavedDiscardBtn", "unsavedKeepBtn"):
        assert name in text, f"missing {name}"


# ============================================================================
# F: runtime navigation guard — four paths
# ============================================================================

def test_dirty_blocks_navigation_and_opens_dialog(tmp_path):
    """F.1: dirty Preferences must not be replaced immediately."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is False

        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        # still on preferences, dialog open, pending destination kept
        assert router.property("currentItem").property("objectName") == "preferencesPage"
        assert dialog.property("visible") is True
        assert router.property("pendingPage") == "batch"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_dirty_preferences_intercepts_window_close(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        dialog = _find(rt, "unsavedDialog")
        assert router.requestClose() is False
        assert dialog.property("visible") is True
        assert router.property("pendingPage") == "__close__"
        assert rt.controller.property("dirty") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_dirty_false_navigates_directly(tmp_path):
    """F.6: dirty=false navigates without the dialog."""
    rt = _build_runtime(tmp_path)
    try:
        router, _page = _navigate_to_preferences(rt)
        dialog = _find(rt, "unsavedDialog")
        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        assert router.property("currentPage") == "batch"
        assert dialog.property("visible") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_unsaved_save_and_leave(tmp_path):
    """F.3: Save-and-Leave saves then navigates only after saveSucceeded."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True

        _find(rt, "unsavedSaveBtn").click()
        QApplication.processEvents()

        # saved + navigated
        assert rt.controller is not None and not rt.controller.property("dirty")
        assert router.property("currentPage") == "batch"
        assert dialog.property("visible") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_unsaved_save_failed_stays_on_preferences(tmp_path):
    """F.3: saveFailed -> stay on Preferences and show the error."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        # Force a save failure: stage an invalid situation -> validation error
        ctrl = rt.controller
        assert ctrl is not None
        ctrl.stageProviderKey("qwen", "staged-key")
        # make save fail via credential store failure
        ctrl._credentials._global_set_fail = True  # type: ignore[attr-defined]

        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True

        _find(rt, "unsavedSaveBtn").click()
        QApplication.processEvents()

        # stayed on preferences; error text visible; pending cleared
        assert router.property("currentPage") == "preferences"
        assert router.property("pendingPage") == ""
        assert dialog.property("visible") is False
        err = _find(rt, "saveErrorText")
        assert err.property("visible") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_unsaved_discard_and_leave(tmp_path):
    """F.4: Discard cancels the draft then navigates."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True

        _find(rt, "unsavedDiscardBtn").click()
        QApplication.processEvents()

        assert router.property("currentPage") == "batch"
        assert dialog.property("visible") is False
        ctrl = rt.controller
        assert ctrl is not None
        assert ctrl.property("sessionOpen") is False
        assert ctrl.property("dirty") is False
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_unsaved_keep_editing_stays_and_keeps_draft(tmp_path):
    """F.5: Continue Editing closes the dialog, stays, draft untouched."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        template_before = page.property("ctrl").property("defaultTemplateId")
        router.navigate("batch")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True

        _find(rt, "unsavedKeepBtn").click()
        QApplication.processEvents()

        assert router.property("currentPage") == "preferences"
        assert dialog.property("visible") is False
        ctrl = rt.controller
        assert ctrl is not None
        assert ctrl.property("dirty") is True
        assert ctrl.property("defaultTemplateId") == template_before
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_cancel_button_dirty_reuses_discard_semantics(tmp_path):
    """F.7: Cancel must not silently discard a dirty draft."""
    rt = _build_runtime(tmp_path)
    try:
        router, page = _navigate_to_preferences(rt)
        _make_dirty(page)
        from PySide6.QtWidgets import QApplication
        cancel_btn = _find(rt, "cancelBtn")
        cancel_btn.click()
        QApplication.processEvents()
        dialog = _find(rt, "unsavedDialog")
        assert dialog.property("visible") is True
        assert router.property("pendingPage") == "batch"
        # draft still intact
        ctrl = rt.controller
        assert ctrl is not None and ctrl.property("dirty") is True
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()


def test_cancel_button_clean_leaves(tmp_path):
    rt = _build_runtime(tmp_path)
    try:
        router, _page = _navigate_to_preferences(rt)
        from PySide6.QtWidgets import QApplication
        _find(rt, "cancelBtn").click()
        QApplication.processEvents()
        assert router.property("currentPage") == "batch"
        rt.assert_zero_warnings()
    finally:
        rt.cleanup()
