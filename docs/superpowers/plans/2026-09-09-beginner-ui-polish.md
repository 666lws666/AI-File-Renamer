# Beginner UI Polish Implementation Plan

> Execute inline using executing-plans and test-driven-development, as selected by the Product Owner. Use independent read-only review before completion.

**Goal:** Complete five approved usability improvements and the organization-mode display correction without changing file safety or AI behavior.
**Architecture:** Reusable local QML controls; explicit label/value mappings at the view boundary; catalog injected from PageRouter into Preferences and GeneralSettingsCard. Existing Python controllers retain ownership of drafts and persistence.
**Tech Stack:** Python 3.14, PySide6/Qt Quick Basic, pytest, native Windows capture, PyInstaller.

## Global constraints

Follow docs/superpowers/specs/2026-09-09-beginner-ui-polish-design.md. No real API/Key/Credential Manager, no push, no user data edits. Work in the authorized current feature checkout. Do not change formal Golden without a controlled baseline decision. Capture to tests/screenshots/qa-current/beginner-ui-polish/ only.

## Task 1 — truthful, localized selections

Files: src/ui_qml/{GeneralSettingsCard,PreferencesPage,PageRouter,TemplateEditor,FieldSorter,VocabList}.qml; src/utils/i18n/locales/{zh_CN,en_US}.json; tests/qml/test_beginner_ui_polish.py and obsolete default-template assertions in test_general_settings.py.

- [x] RED: instantiate real settings/controller in an isolated runtime; unknown default ID stays unchanged with currentIndex=-1; selecting a named catalog row writes its ID; cancel restores old value. Open a non-flat template and assert currentValue equals the stored enum; switch templates without writing the mode. Inspect translated labels.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/qml/test_beginner_ui_polish.py -q` and confirm missing UI/value assertions fail.
- [x] Add `property var templateController: null` to PreferencesPage and GeneralSettingsCard, wire PageRouter props and card. Derive choices as `[{id:'',name:translatedAutoLabel}].concat(templateController ? templateController.templates : [])`. Bind currentValue by the stable ID role; `onActivated` writes only a valid selected ID. `inputError = numericError || unknownTemplate`. Guard both page save button and doSave().
- [x] TemplateEditor models use `{label,value}` and `textRole/valueRole`; bind `currentIndex` by the current draft option. `onActivated` writes currentValue. FieldSorter uses translation key `templates.field.` plus dcName; VocabList maps source values to existing source translation keys.
- [x] Run new tests plus test_general_settings.py, test_templates.py, test_template_vocab_integration.py and test_preferences_runtime.py. Commit only Task 1 files after green.

## Task 2 — shared readable controls

Files: create src/ui_qml/AppButton.qml, AppComboBox.qml and icons/chevron_down.svg; register qmldir. Apply these types to BatchToolbar, TemplatesPage/TemplateEditor/FieldSorter, WatchPage/WatchForm, GeneralSettingsCard, VocabTab/VocabList and Preferences actions; additional settings cards only for their existing Button/ComboBox instances, with no business edits. Tests: tests/qml/test_beginner_controls.py.

- [x] RED: controls instantiate with zero warnings; ComboBox popup opens by real mouse click, keyboard selects an item and emits activated; Button click/Space emits clicked while disabled does not. Assert single indicator and visible focus/border geometry at narrow widths.
- [x] Implement AppButton as Basic.Button, `property bool primary: false`, implicit height 32, text-dependent width, 8px horizontal padding, 6px rounded border, focus outline, dark checked/primary colors. Preserve text/icon/padding/implicit dimensions overrides used by call sites.
- [x] Implement AppComboBox as Basic.ComboBox with 32px minimum height, native value/index API, text content elision, a local SVG chevron and bordered white background. Style popup delegates while preserving keyboard selection and scroll clipping. Do not shadow Qt's global Button/ComboBox names.
- [x] Replace only declared control type names, preserve objectNames/signals/models. Primary = save/add/apply; cancel/edit/browse remain secondary. Run component and full QML tests, then native capture. Commit Task 2 independently.

## Task 3 — Watch and Batch guidance

Files: WatchForm.qml, WatchPage.qml, DropZone.qml, locales; tests/qml/test_beginner_guidance.py and existing affected geometry tests.

- [x] RED: Watch browse buttons display text; mode hint changes with draftMode; form height=min(content,available), scroll remains usable at 900×640. DropZone displays three steps and supported PDF/JPG/MP4 examples, both actions remain visible/clickable.
- [x] WatchForm implicitHeight follows form content; WatchPage sets capped height rather than bottom anchor. Replace ellipsis with localized browse text and adequate width. Mode hint derives from `draftMode === 'auto_apply'` with explicit consequences; use wrapped text and content-sized option cards.
- [x] DropZone centered ColumnLayout bounded to available width; local SVG folder/upload icon; format examples and three-step explanatory text, both AppButton actions reuse existing signals. No unsupported format promises or network checks.
- [x] Run targeted/full QML tests, inspect real native screenshots and clicks. Commit Task 3 after green.

## Task 4 — integration verification and delivery

Files: scripts/capture_beginner_ui_polish_native.py; tests/screenshots/qa-current/beginner-ui-polish/ (ignored evidence); offline Chinese HTML manual; this plan.

- [x] Create isolated native capture runner using existing FakeCredentialStore/runtime helpers; click settings/templates/watch, select known template, switch non-flat editor, toggle Auto Apply, scroll small form, inspect Batch empty state. Save before/after screenshots plus manifest and warnings.
- [x] Independent code review; fix only deterministic scope-related failures, preserve test rigor. Run `.venv/Scripts/python.exe -m pytest tests --ignore=tests/screenshots -q`, then screenshots with UPDATE_GOLDENS unset, then acceptance_test.py. If legitimate visual changes fail Golden comparison, retain current/golden diff evidence and request a controlled baseline decision; never skip a failing case.
- [x] Rebuild with `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -SkipClean -PythonPath .venv/Scripts/python.exe`; rerun packaging suite/isolated smoke and full regression as needed. Record actual SHA-256/size/file inventory, verify shortcut target and git diff/status. Commit scoped changes only, no push.

## Execution checkpoint — 2026-09-09

- Task 1 committed as c13965d. Selections bind stable currentValue rather than currentIndex; this also survives locale model resets without relying on an unrelated controller notification.
- Tasks 2 and 3 share WatchForm/WatchPage and were verified together as one coherent candidate checkpoint. Shared controls preserve real click/keyboard behavior; new guidance does not change file/AI behavior.
- Native review: 20 Chinese plus 20 English Windows captures at 1000×700 and 900×640, all warning-free. Review found and corrected narrow-toolbar text elision, English switch-label overlap, and en-US/zh-CN aliases missing from SettingsController's draft normalization map. No real settings were changed.
- QML suite: 278 passed, 3 existing deprecation warnings. The short feedback timer test now waits for the exposed first layout frame before starting its timed interaction; the original 120ms timer and 5-second failure bound remain.
- Independent read-only review found no confirmed blocking production regression. Its non-first locale selection concern has a red/green regression and stable-value fix; English evidence was added.
- Acceptance: 186/186. First full non-screenshot run: 1701 passed, 1 skipped, 2 failures limited to existing uncommitted-vs-HEAD scope checks; rerun after candidate commit is required.
- Screenshot suite with UPDATE disabled: 40 comparison failures, 14 passed, 1 expected update-mode skip. All 40 state/warning assertions passed. Differences are retained under qa-current/beginner-ui-polish/comparison; all 38 formal M1 files remain byte-identical. Baseline refresh needs a controlled Product Owner decision; no release-ready claim is made.
- At this checkpoint the controlled baseline decision, full regression and package validation were pending. They are closed by the final verification below. English narrow Provider badges remain a separate small-screen readability backlog item, not changed by this task.

## Final verification — 2026-09-09

- Product Owner explicitly approved updating only the affected 38 M1 images (40 semantic cases). Controlled update: 49 passed. Then UPDATE disabled, complete screenshots: **54 passed, 1 existing update-mode skip**, 86 existing Pillow deprecation warnings. No M0/test assertion/tolerance change.
- Native evidence: 40 Chinese/English Windows screenshots, mouse selection/navigation/toggle/scroll/cancel actions and warning count 0; stored only in qa-current/beginner-ui-polish.
- Final complete non-screenshot suite: **1711 passed, 1 existing platform skip**, 3 Pydantic deprecation warnings (39.35s).
- Packaging suite: **22 passed**, including actual isolated EXE smoke. The first rebuild revealed an omitted chevron SVG; a two-test red/green regression and packaging spec fix resolved it. Final smoke: status ok, QML warnings 0, ephemeral credentials, image/PDF/video/diagnostics ok.
- Final acceptance: **186/186 passed**. No real API/Key/Credential Manager access; no push or release.
- Production code checkpoint 9cd22e3; approved M1 baseline c7b9690; packaging correction f07d601.
- EXE: dist/Xuxia/Xuxia.exe; **10,947,734 bytes**, SHA-256 **A5DA8458278BAA253D73283D7B84A99B62CAB890F277B582EC3A6441353B543D**. Complete onedir package: **3,079 files**, **567,748,553 bytes**. Existing local shortcut points to this EXE and was not modified or staged.
- Backlog (non-blocking): long English Provider capability badges crowd the provider-name column at 900px; pre-existing Pydantic/Pillow deprecations and unused optional packaging-hook warnings. No additional product feature was introduced.
