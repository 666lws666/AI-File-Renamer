# Smart naming UI worker report

## Outcome

Implemented the Task 3 QML surface, faithful mock API, three locale bundles, and dynamic QML tests for template and AI smart naming. Work stayed in the isolated `ai-smart-naming` worktree. No files were staged or committed, and no Golden/screenshot assets were written.

## Changed files

- `src/ui_qml/BatchToolbar.qml`
  - Added the explicit localized naming-method selector: template vs smart.
  - Kept the saved template selector intact in template mode.
  - Hides and disables only the template selector in smart mode and shows concise, localized content/style/review guidance in its place.
  - Uses a localized "Naming rules" caption in smart mode.
  - Preserves the two-row toolbar and constrains text buttons so all critical actions remain visible at the supported 900x640 minimum, including en-US.
  - Keeps the en-US smart helper at 192 logical px / 11 px font. The final text is exactly two rendered lines with no truncation.
- `src/ui_qml/BatchPage.qml`
  - Passes the controller's current `namingMode` into the import language prompt.
- `src/ui_qml/NamingLanguageDialog.qml`
  - Template mode retains "follow template" plus real language choices.
  - Smart mode contains only real languages and initializes an empty draft to `zh`.
  - Shows mode-appropriate localized context while keeping the primary action "Generate naming suggestions".
  - Synchronizes the ComboBox after mode/model/draft changes.
- `src/ui_qml/TaskCard.qml` (scope extension approved by root)
  - Localizes `smart.error.*` keys instead of displaying raw keys.
- `src/controllers/mock_batch_controller.py`
  - Added faithful `namingMode` / `setNamingMode` and `namingLanguage` / `setNamingLanguage` Qt properties, signals, and slots.
  - Default mode remains `template`; changing mode does not mutate the selected template.
- `src/utils/i18n/locales/{zh_CN,zh_HK,en_US}.json`
  - Added mode labels, smart helper/context copy, and every required `smart.error.*` key including `strategyUnavailable`.
- `tests/qml/test_smart_naming_ui.py`
  - Added signal-driven QML behavior tests for mode selection, template preservation, smart default language, confirmed language, production task snapshots, 900px en-US geometry/text fit, locale completeness, and TaskCard smart-error translation.

## TDD evidence

### Initial RED

```text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/qml/test_smart_naming_ui.py -q
FFFF
4 failed in 0.77s
```

Expected causes: missing mode selector, smart prompt still offered follow-template, missing mode-specific summary objects, and missing locale keys.

### Initial GREEN

```text
....                                                                     [100%]
4 passed in 0.41s
```

### Layout RED/GREEN

The new 900px en-US geometry test first found the target button at x=902, then exposed the existing second-row implicit width expanding both rows to x=1086. Explicit compact button widths and a compact target-summary preferred width restored the two-row constraint. A full run then found the en-US Clear label needed 4 more px and the default template label needed 4 more px; both were corrected without hiding or abbreviating labels.

```text
tests/qml/test_home_usability_b.py::test_toolbar_two_rows_keep_readable_critical_labels
tests/qml/test_smart_naming_ui.py
12 passed, 3 warnings in 2.31s
```

The final en-US helper has dynamic assertions for exact text, `truncated == false`, at most two lines, and `contentHeight <= height`; it does not rely on elision.

### TaskCard smart error RED

```text
test_task_card_translates_smart_policy_errors_in_every_supported_locale
FAILED: expected localized message, got 'smart.error.tooLong'
1 failed in 0.64s
```

### TaskCard and readability GREEN

```text
..................                                                       [100%]
18 passed, 3 warnings in 2.86s
```

### Final full QML verification

```text
D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/qml -q
303 passed, 3 warnings in 30.38s
```

The three suite warnings are existing Pydantic v2 deprecation warnings from `file_item.py`, `rename_record.py`, and `app_config.py`. Every new dynamic QML handle asserted zero QML warnings.

## Screenshot impact

The toolbar now contains a real mode selector, so existing M1 Golden images are intentionally stale. Root's comparison reported 40 pixel-difference cases corresponding to 38 PNG baselines, while 9 non-pixel guards passed and there were no setup/assert/QML-warning errors. This worker did not perform native capture and did not write or relax any Golden assets/tests. Root retains exclusive capture ownership and will handle any separately approved baseline update.

## Requirement checks

- Session default remains template mode through both production and mock controllers.
- Smart mode does not select, rename, or mutate the saved template.
- Smart mode requires no template choice.
- Empty smart language resolves visibly to Simplified Chinese before confirmation.
- Template mode still offers follow-template.
- Confirmed language flows through `BatchPage` into a production smart task snapshot.
- The action remains generation, never Apply.
- Smart helpers explicitly communicate content-specific naming, consistent style, and human review.
- Smart policy errors are localized in zh-CN, zh-HK, and en-US and never surface as raw keys in TaskCard.
- Supported 900x640 layout and full critical labels are covered dynamically in en-US as well as the existing locale matrix.
