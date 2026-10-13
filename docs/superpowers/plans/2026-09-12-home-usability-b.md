# 首页易用性 B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use executing-plans inline, honoring the user's existing current-checkout execution preference. Independent read-only review before completion.

**Goal:** Deliver the approved labeled navigation and two-row Batch toolbar.
**Architecture:** QML-only presentation changes retain all controller method names and domain semantics. Short localized labels replace icon-only discoverability.
**Tech Stack:** Python 3.14, PySide6/Qt Quick Controls Basic, pytest, native Windows QPA.

## Global Constraints
- Reference approved design: docs/superpowers/specs/2026-09-12-home-usability-b-design.md.
- Current branch feature/xuxia-m0-foundation; preserve untracked shortcut.
- No API, real credentials, Golden update without separate approval, push or release.
- Keep minimum 900×640; navigation 80 logical px; current 5 destinations.
- Do not refactor backend/controller/state logic. Only narrow cross-page layout corrections are permitted when native evidence shows the wider rail causes a regression.

## Task 1: Navigation
Execution note: Tasks 1–2 share one reviewed source checkpoint (`b1c9dee`), including the separately approved38-image M1 baseline update. Cross-page regression correction moved the long provider video description below the name; no provider logic changed. Final evidence and commands are in `docs/reports/2026-09-12-home-usability-b-verification.md`.
Files: src/ui_qml/NavBar.qml; src/ui_qml/DesignTokens.qml; three locales; tests/qml/test_navigation.py; tests/qml/test_shell.py; tests/qml/conftest.py.
Consumes pageSelected(string), currentPage/status properties; emits existing pageSelected without new route.
- [x] Add RED tests: actual labels visible in all locales; actual click/Space/Return dispatch each page; active/focus state; no duplicate activation.
```python
button.forceActiveFocus()
QTest.keyClick(window, Qt.Key_Space)
assert events == [page_id]
assert button.property("text")
```
- [x] Run navigation tests, confirm missing-label/keyboard behavior failure.
- [x] Replace Rectangle/TapHandler navigation primitive with Basic Button, fixed width parent.width-8 and implicitHeight 56; contentItem column: existing SVG 20px + localized 12px Text; background selected/hover/pressed and 2px focus border. Bind checked to currentPage, onClicked forwards pageSelected(pageId). No checkable toggling independent of router.
```qml
Button {
    activeFocusOnTab: true
    onClicked: root.pageSelected(pageId)
    Keys.onReturnPressed: root.pageSelected(pageId)
    Keys.onEnterPressed: root.pageSelected(pageId)
}
```
- [x] Change real navBarWidth and test mirror from48 to80. Add nav.short.* catalogs zh-CN/en-US/zh-HK. Verify route/state without modifying Shell routing.
- [x] Run navigation/shell/status tests and commit scoped Task1 after review of diff.

## Task 2: Toolbar
Files: src/ui_qml/BatchToolbar.qml; three locales; tests/qml/test_home_usability_b.py (new); tests/qml/test_batch_runtime_wiring.py; test_batch_beginner_regressions.py.
Consumes existing ctrl properties: templateOptions, selectedTemplateId, visibleCount, totalCount, selectedCount, selectAllState, searchText, statusFilter, targetDirectory. Uses existing setSelectedTemplate, setSelectAllState, setSearchText, setStatusFilter, applySelected, stopPending, clearWorkspace. Retain import/target signals.
- [x] RED: assert two distinct action-row geometries, nonempty apply/stop/clear labels at820/920px, model/filter values survive translations, click signals, truthful count and target summary, keyboard full-path disclosure.
```python
assert apply_button.property("text")
assert search.mapToScene(QPointF()).y() > template.mapToScene(QPointF()).y()
assert clear.mapToScene(QPointF(clear.width(),0)).x() <= window.width()
```
- [x] Run new tests; confirm expected failures before implementation.
- [x] Implement ColumnLayout with configuration RowLayout and workspace RowLayout. Widths use implicit text metrics/minimums and remaining space; no compact IconOnly path. Give stable objectNames, 32px high AppButtons/fields, 12px fonts. Separate template label and selected/visible/total wording. Keep current selection sync functions.
- [x] Target summary presents localized same-folder or moved-to path. Only nonempty target enables disclosure; readonly wrap-anywhere text in closable Dialog, textFormat PlainText, escaped paths never interpreted as rich text. Dialog is view-only; closing or Escape makes no mutation.
- [x] Convert obsolete single-row/icon tests to two-row/labeled semantics; preserve real click/search/filter/control signal coverage.
- [x] Run all QML/i18n tests, inspect cross-page width regression caused by80px navigation; fix only layout regressions within approved presentation scope.

## Task 3: Native and release Gate
Files: scripts/capture_home_usability_b_native.py (new); docs/reports/2026-09-12-home-usability-b-verification.md (new); plan checkboxes.
- [x] Build native harness from existing isolated runtime helper: FakeCredentialStore, fake connection service, usage=None, temporary config. Real mouse/keyboard events; save only qa-current/home-usability-b.
- [x] Capture three locales at1000×700/900×640, real select/filter/search, empty+mixed, long-path disclosure, five nav destinations. Record warnings, dimensions, hashes, assertions; inspect images, not just manifest.
- [x] Run full non-screenshot tests. Existing HEAD-integrity tests require a scoped implementation checkpoint; do not remove those assertions.
- [x] Run screenshots with update mode off. Produce exact mismatch list; request narrowly scoped Golden approval only after native evidence passes. Without approval report visual Gate pending rather than pass.
- [x] After authorized visual Gate, build scripts/build_windows.ps1 with project venv; run packaging tests/isolated EXE smoke, acceptance, complete tests, diff check. Record real results, EXE SHA/size; commit only scoped changes.
