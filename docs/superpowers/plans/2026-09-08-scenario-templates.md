# Scenario Templates Implementation Plan

> Execute inline in the current task using executing-plans and test-driven-development; user approved the nine-template design and direct implementation.

**Goal:** Keep General Naming and add eight editable beginner presets with Chinese purposes and rendered examples.
**Architecture:** A domain catalog defines stable preset IDs and sample values. TemplateStore installs unseen IDs and an installation ledger in a single atomic write; it reads legacy JSON arrays and the new versioned envelope. The existing controller and renderer supply localized card metadata and real formula-derived examples.
**Tech Stack:** Python, PySide6/QML, pytest, Windows native capture, PyInstaller.

## Global Constraints

- Add Simple Title, Receipts, Contracts, Project Documents, Study Materials, Papers, Photos/Videos, Versioned Documents. Keep current default choice and existing template identities/content/order.
- Chinese output, flat organization, original extension preserved. Required fields remain required; never invent missing data.
- Users may edit/delete presets. Installation IDs are remembered even after deletion. No duplicate additions after restart, no replacement of user edits or colliding IDs.
- Source/metadata installation is one atomic transaction; failure preserves both previous file and memory. Future/invalid schema fails closed before writes.
- Card purpose and naming example visible without hover; formula secondary; examples use the current template through TemplateRenderer, including after edit.
- No real API/Key/Credential Manager; no push or Golden changes. Native screenshots only under tests/screenshots/qa-current/scenario-templates/.

## Tasks

- [x] Catalog/persistence: create src/core/template_presets.py and tests/unit/test_template_presets.py. Add TemplateStore.install_presets(templates) with stable-ID ledger. RED tests: fresh/legacy install, repeated startup byte stability, edits preserved, deletions not resurrected, failed os.replace zero state change, invalid/future envelope rejected. Render each scenario fixture and reject a missing required field.
- [x] Presentation: update template_page_controller.py, TemplatesPage.qml, zh_CN/en_US locale files. Existing controller seeds eight presets after the original default, localizes unchanged built-ins, returns description/example from current template and sample values. Add tests for nine entries, localized labels, current-rule examples, batch option propagation, delete/last-template protection, scroll and edit at 1000x700/900x640. Adjust only obsolete one-template count assertions.
- [x] Documentation/native: update the offline HTML manual, add isolated scripts/capture_scenario_templates_native.py. Verify real navigation, wheel scroll, editing an example preset, template choices, readable Chinese and zero QML warnings; record screenshots and manifest without changing Golden.
- [x] Delivery: run targeted tests and independent review, complete non-screenshot pytest, screenshot pytest with UPDATE_GOLDENS off, acceptance, local commit, rebuild Windows EXE, packaging/isolated smoke and final hash/report. Keep shortcut intact.

## Verification completed

All four tasks above are complete. Native Windows: 6 captures, real navigation/wheel/edit/close at 1000x700 and 900x640, zero QML warnings. Independent read-only review found no blocking issue; additional collision/edited-example/batch-selection tests were added and passed. A collision relabelling edge case was fixed by matching the entire preset before translating its name.

- Full non-screenshot suite after rebuild: 1689 passed, 1 existing skipped, 3 existing deprecation warnings.
- Screenshot suite, update disabled: 54 passed, 1 expected update-mode skipped, 86 deprecation warnings. No Golden modified.
- Acceptance: 186/186; packaging suite including isolated EXE nine-template installation: 20 passed.
- Windows build succeeded. Existing shortcut continues to target dist/Xuxia/Xuxia.exe.
- Native evidence and artifact hash are under ignored tests/screenshots/qa-current/scenario-templates/. No real API or credentials used; no push.

## Formula catalog

| Preset | Pattern | Date format |
|---|---|---|
| Simple title | {dcTitle} | YYYY-MM-DD |
| Receipts | {dcDate}_{dcType}_{dcTitle} | YYYY-MM-DD |
| Contracts | {extOrganization}_{dcDate}_{dcTitle} | YYYY-MM-DD |
| Projects | {extProject}_{dcDate}_{dcTitle} | YYYY-MM-DD |
| Study | {dcSubject}_{dcTitle} | YYYY-MM-DD |
| Papers | {dcCreator}_{dcDate}_{dcTitle} | YYYY-MM |
| Photos/videos | {dcSubject}_{dcDate}_{dcTitle} | YYYY-MM-DD |
| Versions | {extProject}_{dcTitle}_{extVersion} | YYYY-MM-DD |
