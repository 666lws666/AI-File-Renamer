# Task 4 — three-language offline manual report

Date: 2026-09-13

## Scope delivered

- Kept the single root entry 序匣用户手册.html as Simplified Chinese.
- Added complete static Traditional Chinese (Hong Kong) and English manuals at
  user-guide-assets/manual-zh-HK.html and
  user-guide-assets/manual-en-US.html.
- Each locale contains all 17 chapters, localised navigation, body text, image
  alt text, captions, print control, and explicit text language links.
- Documented Template mode versus AI Smart mode, the template-mode default,
  per-import mode/language snapshots, the five filename languages, unchanged
  templates and Watch configurations, visible smart failures, the 180 UTF-16
  stem rejection rule, and the limit of mocked-model evidence.
- Removed dated or unverified model availability claims. Provider guidance now
  directs users to current capability labels, account permissions, and the
  connection test.
- Preserved Apply/Undo, Watch, extension, version, path, conflict, privacy,
  multimodal, cache, and resource-safety explanations.
- Added visible keyboard focus and made language controls screen-only when
  printing, so each static page prints only its current language.
- Wired the agreed 12-scene locale paths under
  user-guide-assets/{zh-CN,zh-HK,en-US}/.
- Packaging code already recursively includes user-guide-assets; no spec or
  build-script production edit was required. The packaging test now expects the
  two static locale pages and compares every recursive source asset.

## TDD evidence

RED command:

    D:/文件AI-AGENT/.venv/Scripts/python.exe -m pytest tests/docs/test_user_guide.py -q

RED result:

- Exit 1.
- 6 failed, 8 passed.
- Expected failures covered the old date, absent locale pages, missing smart
  semantics, dated model aliases, and absent focus/language-switch styling.

GREEN command:

    D:/文件AI-AGENT/.venv/Scripts/python.exe -m pytest tests/docs/test_user_guide.py -q

GREEN result after implementation:

- Exit 0.
- 14 passed.

Source packaging command:

    D:/文件AI-AGENT/.venv/Scripts/python.exe -m pytest tests/packaging/test_packaged_app.py -q -k "packaging_spec_includes_offline_user_manual_and_asset_tree or build_script_targets_candidate_spec_not_official_entry"

Result:

- Exit 0.
- 2 passed, 17 deselected.

## External completion dependencies

- The root task owns the native capture script, PNG files, and manifest. It
  confirmed and produced the 36-case locale/scene contract. Final recapture
  after the English narrow-width hint adjustment and manifest hash refresh are
  root-owned.
- test_packaged_offline_manual_matches_every_source_asset currently fails
  because dist/Xuxia/序匣用户手册.html does not exist in the pre-build tree.
  This is the expected fail-closed state until the root task rebuilds the
  release artifact; it is not evidence of a source packaging-rule failure.

No real Provider, API credential, online translation service, or native GUI was
used by this worker.

## Final deterministic-copy correction

The final review corrected three claims in every locale:

- Settings exposes cache status and clearing, but the current AI Smart Batch
  analysis pipeline does not read or write a naming-suggestion cache. The
  manual no longer implies that smart suggestions are cached.
- A first smart-analysis failure has no suggestion to edit. Users should
  correct the input or Provider and regenerate.
- Retry always retains the mode and filename language captured at import.
  Changing the toolbar mode does not mutate an existing failed task; to use a
  different mode, remove that task from the workspace and import it again.

The English quick-start mode labels were also aligned to the current UI:
Name with template and AI smart naming. No UI, application code, capture, or
PNG was changed by this correction.

Correction RED:

    D:/文件AI-AGENT/.venv/Scripts/python.exe -m pytest tests/docs/test_user_guide.py::test_smart_retry_reimport_and_cache_boundaries_are_exact_in_every_locale -q

- Exit 1: the old manuals did not contain the required exact boundaries.

Correction GREEN:

    D:/文件AI-AGENT/.venv/Scripts/python.exe -m pytest tests/docs/test_user_guide.py -q

- Exit 0: 15 passed in 0.28 seconds.
