"""Observable Batch regressions, with local fake data and no cloud access."""

import pytest
from PySide6.QtCore import QObject, QMetaObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF
from PySide6.QtTest import QTest

from .conftest import QML_DIR, make_handle
from .fixtures import make_empty_controller
from src.controllers.batch_workspace_controller import BatchWorkspaceController


def texts(root):
    return [obj.property("text") for obj in root.findChildren(QObject)
            if obj.metaObject().indexOfProperty("text") >= 0]


@pytest.mark.parametrize("component,key", [
    ("DropZone.qml", "batch.dropzone.hint"),
    ("TaskCard.qml", "batch.state.pending"),
    ("TaskQueue.qml", "batch.noMatching"),
])
def test_batch_existing_text_updates_when_locale_changes(component, key):
    handle = make_handle(QML_DIR / component, ctrl=make_empty_controller())
    try:
        assert handle.i18n.tr(key, "zh-CN") in texts(handle.root)
        handle.i18n.set_locale("en-US")
        QTest.qWait(30)
        assert handle.i18n.tr(key, "en-US") in texts(handle.root)
        handle.i18n.set_locale("zh-CN")
        QTest.qWait(30)
        assert handle.i18n.tr(key, "zh-CN") in texts(handle.root)
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_reopening_inline_editor_resets_error_and_focuses_input():
    handle = make_handle(QML_DIR / "TaskCard.qml", h=130, ctrl=make_empty_controller())
    try:
        handle.root.setProperty("suggestedName", "报告.pdf")
        handle.root.setProperty("extension", ".pdf")
        handle.root.setProperty("isEditing", True)
        QTest.qWait(50)
        editor = handle.root.findChild(QQuickItem, "taskInlineEdit")
        field = handle.root.findChild(QQuickItem, "inlineNameField")
        field.setProperty("text", "")
        assert QMetaObject.invokeMethod(editor, "validateAndConfirm", Qt.DirectConnection)
        assert editor.property("localValidationError") == "batch.validate.empty"
        handle.root.setProperty("isEditing", False)
        handle.root.setProperty("isEditing", True)
        QTest.qWait(50)
        assert editor.property("localValidationError") == ""
        assert field.property("text") == "报告"
        assert field.hasActiveFocus()
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


@pytest.mark.parametrize("width", [900, 1000])
def test_status_filter_label_is_not_clipped(width):
    handle = make_handle(QML_DIR / "BatchToolbar.qml", w=width - 48,
                         ctrl=make_empty_controller())
    try:
        combo = handle.root.findChild(QQuickItem, "batchStatusFilter")
        content = combo.property("contentItem")
        metrics = QFontMetricsF(combo.property("font"))
        needed = metrics.horizontalAdvance(combo.property("currentText"))
        available = content.width() - content.property("leftPadding") - content.property("rightPadding")
        assert available >= needed, (available, needed)
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_skipped_import_displays_clear_feedback_in_batch_page(tmp_path):
    ctrl = BatchWorkspaceController(background=False)
    handle = make_handle(QML_DIR / "BatchPage.qml", ctrl=ctrl)
    try:
        ctrl.add_files([str(tmp_path / "missing.txt")])
        QTest.qWait(30)
        notice = handle.root.findChild(QQuickItem, "batchImportFeedback")
        assert notice is not None and notice.isVisible()
        assert "无法读取 1" in notice.property("text")
        assert ctrl.totalCount == 0
        handle.i18n.set_locale("en-US")
        QTest.qWait(30)
        assert "unreadable 1" in notice.property("text")
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_status_filter_selection_survives_language_switch():
    ctrl = make_empty_controller()
    handle = make_handle(QML_DIR / "BatchToolbar.qml", ctrl=ctrl)
    try:
        combo = handle.root.findChild(QQuickItem, "batchStatusFilter")
        ctrl.setStatusFilter("review_pending")
        assert ctrl.statusFilter == "review_pending"
        handle.i18n.set_locale("en-US")
        QTest.qWait(30)
        assert ctrl.statusFilter == "review_pending"
        assert combo.property("currentIndex") == 3
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_capability_error_is_explained_in_chinese_not_raw_key():
    handle = make_handle(QML_DIR / "TaskCard.qml", ctrl=make_empty_controller())
    try:
        key = "capability.vision_unavailable_image"
        handle.root.setProperty("errorMessage", key)
        error = handle.root.findChild(QQuickItem, "taskErrorMessage")
        assert error.property("text") == handle.i18n.tr(key, "zh-CN")
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


def test_search_field_displays_current_controller_filter_and_external_reset():
    ctrl = make_empty_controller()
    ctrl.setSearchText("2025")
    handle = make_handle(QML_DIR / "BatchToolbar.qml", ctrl=ctrl)
    try:
        field = handle.root.findChild(QQuickItem, "batchSearchField")
        assert field.property("text") == "2025"
        ctrl.setSearchText("报告")
        QTest.qWait(30)
        assert field.property("text") == "报告"
        ctrl.setSearchText("")
        QTest.qWait(30)
        assert field.property("text") == ""
        field.forceActiveFocus()
        for character in "invoice":
            QTest.keyClick(field.window(), ord(character.upper()))
        assert ctrl.searchText == "INVOICE"
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()


@pytest.mark.parametrize("width", [900, 1000])
@pytest.mark.parametrize("locale,label", [("zh-CN", "通用命名（默认）"),
                                         ("en-US", "General Naming (Default)")])
def test_default_template_label_is_fully_readable(width, locale, label):
    ctrl = BatchWorkspaceController(background=False)
    ctrl.configure_templates([{"id": "general", "name": label}], "general")
    # Load real glyphs before QML computes all controls' implicit widths.
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    assert font_id >= 0
    handle = make_handle(QML_DIR / "BatchToolbar.qml", w=width - 80, h=124, ctrl=ctrl, loc=locale)
    try:
        combo = handle.root.findChild(QQuickItem, "batchTemplateSelector")
        # Match the native Windows launcher; Qt's test-only Sans Serif
        # fallback may have no Latin glyphs on this host.
        families = QFontDatabase.applicationFontFamilies(font_id)
        native_font = QFont(families[0] if families else "Microsoft YaHei UI")
        native_font.setPixelSize(12)
        combo.setProperty("font", native_font)
        content = combo.property("contentItem")
        available = content.width() - content.property("leftPadding") - content.property("rightPadding")
        needed = QFontMetricsF(combo.property("font")).horizontalAdvance(label)
        assert combo.property("currentText") == label
        assert available >= needed, (available, needed)
        clear = handle.root.findChild(QQuickItem, "batchClearButton")
        assert clear.x() + clear.width() <= handle.root.width()
        handle.assert_zero_warnings()
    finally:
        handle.cleanup()
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)
