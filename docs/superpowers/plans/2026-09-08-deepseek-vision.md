# DeepSeek visual model update

Approved design: add exact-model support for `deepseek-v4-flash-vision-exp` (experimental), without changing the default `deepseek-v4-flash` or saved user profiles. Official evidence checked 2026-09-08: https://api-docs.deepseek.com/guides/vision/ and https://api-docs.deepseek.com/news/news260821/ . Chat Completions uses user content image_url/data URLs and json_object output. Ordinary Flash/Pro remain text-only. Unknown DeepSeek models receive conservative capabilities.

## Constraints

- No real API, credentials, external image fetching, full PDF/video upload, monetary features, push, or Golden updates.
- Preserve keys/configuration and require connection re-verification when a model changes.
- Reuse the existing preprocessed-image adapter path; no second provider or new protocol.

## Implementation sequence

1. Add failing preset/adapter tests in tests/providers/contracts/test_deepseek_contract.py and tests/unit/test_deepseek_vision.py; verify exact model capability and negative cases.
2. Add model capability resolver in src/core/provider_presets.py; use it for profile construction and src/controllers/settings_controller.py view models. Keep other providers unchanged.
3. Add failing runtime tests in tests/qml/test_deepseek_vision.py; expose verified DeepSeek choices in ProviderForm.qml, refresh capabilities on edits, clearly label experimental vision vs text-only. Preserve free model entry and staged-save semantics.
4. Update zh_CN/en_US locale resources and Chinese HTML manual. Verify native Windows layout/clicks using fake credentials and synthetic state; screenshots only under qa-current.
5. Run full non-screenshot pytest, screenshot pytest with UPDATE_GOLDENS off, acceptance, rebuild Windows package, packaging smoke, and fresh EXE inventory. Review actual diff and evidence; commit locally only after passing.

## Progress

- Baseline: 62552646c7523f48fdc34909130d9a4f770ef42c; only untracked user shortcut.
- Implementation: exact-model resolver, official evidence supplement, editable model picker, dynamic capabilities, safe image-model guard and manual complete.
- Native validation: four Windows captures (1000x700 / 900x640, text / vision), actual mouse and keyboard selection, readable Chinese, zero QML warnings. Resize defect found and fixed with regression.
- Review integration fix: test/save share effective credential resolution (typed > staged including deletion > stored); retained-key upgrade works and model/key changes invalidate verification. Explicit Clear keeps a deletion tombstone.
- Targeted settings/QML tests: 145 passed; preset/DeepSeek contracts: 48 passed. Full first pass: 1672 passed, 1 skipped, four failures (two offline manual links fixed, two expected pre-commit working-tree/HEAD guards). Final unfiltered post-commit validation and package smoke recorded in qa-current/deepseek-vision/REVIEW.md.
