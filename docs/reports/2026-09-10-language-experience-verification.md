# Language experience verification — 2026-09-10

## Delivered behavior

- Interface choices: Simplified Chinese, English, Traditional Chinese (Hong Kong). All 390 catalog keys and formatting placeholders match across locales.
- Interface changes preview immediately. Cancel/discard restores the most recently saved language; failed Save preserves the draft and preview.
- Before a Batch file, folder or drop import enters analysis, a dialog identifies the current template and asks for filename language. Default: Follow template, with the effective language spelled out.
- Explicit filename choices: Simplified Chinese, Traditional Chinese (Hong Kong), English, Japanese, Spanish. The session choice does not rewrite templates, existing tasks or original files. Cancel performs no import or API call.
- Provider request locale follows the captured filename language, not interface language. Watch continues to follow its template's output setting.
- New tasks retain import-time choices. Older workspace tasks acquire persistent choices before their first resumed analysis. Retry/reload preserves those choices.
- Template saves refresh the Batch catalog. HK interface labels do not translate sample filenames or user-authored names.

## Review and negative tests

Independent review identified stale template-language metadata and unpersisted legacy-task choices; both were reproduced, fixed and re-reviewed. HK sample-filename overrides were removed, and the generic Chinese output label was clarified as Simplified Chinese. The four regression cases failed before the fixes and passed afterward; expanded targeted regression: 87 passed.

The implementation follows the approved language-experience design and plan. Test-first implementation, independent code review and verification-before-completion were used. No existing Golden was updated and no assertion or pixel tolerance was weakened.

## Final Windows verification

Runtime: project `.venv`, Python 3.14.5, Windows 11, native Qt Windows platform for visual evidence.

| Command / check | Actual result |
| --- | --- |
| `python -m pytest tests/ --ignore=tests/screenshots -q` | 1730 passed, 1 skipped, 3 warnings; 38.84 s |
| `python -m pytest tests/screenshots -q` with UPDATE_GOLDENS absent | 54 passed, 1 skipped, 86 warnings; 34.40 s |
| `python acceptance_test.py` | 186/186 passed, 0 failed |
| `python -m pytest tests/packaging -q` | 23 passed, 3 warnings; 5.68 s |
| `scripts/build_windows.ps1 -SkipClean -PythonPath .venv/Scripts/python.exe` | Exit 0; new Windows onedir build |
| `scripts/capture_language_experience_native.py` | 48 native captures, 0 QML warnings, 0 imports |
| `git diff --check` | Exit 0 |

The two pytest skips are the existing Windows symlink condition and the explicit Golden-update-only test. Warnings are existing Pydantic/Pillow deprecations, not suppressed failures. The packaging checks include the real isolated EXE smoke (ephemeral credentials, media dependencies, diagnostics, entry point), bundled resource/source byte equality and absence of user state/developer paths.

## Native visual evidence

Evidence stays in ignored `tests/screenshots/qa-current/language-experience/`; `native-manifest.json` records dimensions, locale, SHA-256 and warnings. Each of zh-CN/en-US/zh-HK is exercised at 1000×700 and 900×640. Actual mouse/keyboard actions cover naming-language selection and cancellation, Preferences language options, template navigation and template output-language selection. Temporary inputs/configuration and fake credentials are used.

Direct image review confirmed readable CJK, unclipped language options and controls in the reviewed smallest-window states. The HK template output option visibly changes the editor while its draft remains unsaved. No real user file is imported by this capture script.

One intermediate native run failed its keyboard-selection assertion. Diagnostic fields (locale, size, active window, index, text, focus) were added without weakening the assertion; two subsequent consecutive complete 48-capture runs passed. Keep this as an automation reliability observation, not a proven application defect or a concealed successful run.

## Artifact

- Application: `dist/Xuxia/Xuxia.exe`
- SHA-256: `A4557C864B6ABDBBDDC2DBDC8C9589BC572126F68AE649ADD5DC634DB8E1C7F4`
- EXE bytes: 10,951,103
- Complete onedir package: 3,081 files; 567,782,715 bytes
- Offline manual: `序匣用户手册.html`, also packaged beside the EXE with its assets.
- The existing untracked `序匣.lnk` is preserved and excluded from commits.

No push, public release, real API, real Key or real Credential Manager access. This verifies local behavior and the locale sent to a fake Provider; actual model output still requires user review before Apply, especially proper names and identifiers.
