# Language Experience Implementation Plan

> **For agentic workers:** Use executing-plans for coupled integration and a bounded subagent for the independent translation catalog, with review before completion.

**Goal:** Reliable cancelable language preview, HK localization, and explicit filename-language confirmation.

**Architecture:** I18n remains the rendering service; SettingsController emits saved-locale restoration only on cancel. A separate Batch dialog gates import, records immutable per-task language/template choices, and BatchAnalysisService passes the effective output locale to the Provider. UI language never chooses naming language.

**Tech Stack:** Python 3.14, PySide6/Qt Quick, UTF-8 JSON catalogs, pytest and PyInstaller on Windows.

## Global Constraints

- No real API/Key/Credential Manager, user file operations, push/release or Golden updates.
- Preserve the untracked user shortcut. Work in current feature/xuxia-m0-foundation checkout as authorized.
- zh-HK/zh_HK aliases; immutable captured output choices; cancel writes nothing.
- Existing template/user vocabulary/file strings must not be mechanically translated.

## Task 1: Hong Kong catalog

Files: create src/utils/i18n/locales/zh_HK.json. Independent translation worker owns only that file.

- [x] Read zh_CN.json fully; translate each value with the exact same keys/placeholders into HK Traditional Chinese. Preserve tokens, format codes, API identifiers and brand.
- [x] Verify JSON and key/placeholder equality with `python -c` or an isolated helper; manually review HK vocabulary. Root adds new task-specific keys after handoff.

## Task 2: Locale transaction and presentation

Files: src/utils/i18n/locale_metadata.py, src/controllers/settings_controller.py, src/qml_bootstrap.py, src/ui_qml/GeneralSettingsCard.qml, src/controllers/template_page_controller.py, locale catalogs; tests/unit/i18n/test_hk_locale.py and tests/qml/test_language_rollback.py.

- [x] RED: assert `I18n().tr('nav.preferences','zh-HK') == '設定'`; assert catalog key/placeholder parity; switch zh→HK then cancel returns zh and creates no JSON; Save HK, preview English, cancel returns HK. Assert user-named template is unchanged.
- [x] Add supported locale and aliases; third ComboBox choice. SettingsController gains `localeRestoreRequested = Signal(str)` emitted by cancel with live language; bootstrap connects to I18n.set_locale before QML creation. Add HK built-in labels without changing stored objects.
- [x] GREEN: run focused i18n/settings/QML tests and inspect translation resources. Commit only reviewed task files.

## Task 3: Filename language contract and prompt

Files: src/core/template_model.py, src/core/batch_analysis.py, src/controllers/batch_workspace_controller.py, src/ui_qml/BatchPage.qml, DropZone.qml, TemplateEditor.qml; create NamingLanguageDialog.qml; locale catalogs; tests/unit/test_naming_language.py and tests/qml/test_naming_language_dialog.py.

- [x] RED: fake adapter receives `request.locale == 'zh-HK'` with English UI; template English default sends en-US with Chinese UI; separate tasks preserve import-time selection; dialog cancel makes zero addPaths/importDropped/addFolder calls.
- [x] Add OutputLanguage.ZH_HK = 'zh-HK'. Add validated mapping function for effective naming locale. BatchAnalysisService accepts explicit `output_language` and uses template fallback when empty. Batch controller stores templateId/outputLanguage on tasks and passes them when analyzer signature supports the keywords, including cancellation_token. Preserve older two-arg analyzers.
- [x] Add a modal dialog (title, read-only template, language ComboBox, explanatory text, Cancel/Generate buttons). BatchPage requestImport(kind, paths) stages local URLs only; confirm sets session language and calls existing import API; cancel clears staged URLs. DropZone delegates to injected requestImport callback in BatchPage, retaining standalone controller path. No network on opening/cancel.
- [x] Add HK output option to TemplateEditor. No changes to old closed-page geometry or Golden files.
- [x] GREEN: fake Provider pipeline tests, native QML keyboard/click/cancel tests, targeted unit/QML suites. Commit scoped implementation.

## Task 4: Delivery

- [x] Native zh-HK screenshots (Batch confirmation, settings dropdown, template editor) at 1000x700/900x640, inspect glyphs/overlap and runtime warnings. Record evidence in tests/screenshots/qa-current/language-experience/.
- [x] Run `pytest tests --ignore=tests/screenshots -q`, `pytest tests/screenshots -q` with UPDATE_GOLDENS unset, acceptance_test.py and diff-check. Review changes for state/cancellation/config races.
- [x] Update 序匣用户手册.html; rebuild via scripts/build_windows.ps1 with project venv; run packaging tests/isolated EXE smoke and hash executable. No publish.
- [x] Record actual results and remaining limitations. Commit reviewed files without shortcut or evidence artifacts.
