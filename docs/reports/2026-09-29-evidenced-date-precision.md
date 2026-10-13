# Evidenced date precision guard — 2026-09-29

## Result and scope

The shared smart-v1 `SmartNamingPolicy.render()` guard now rejects a year-only date supported only by an explicit month/day atom, and a month-only date supported only by an explicit full-day atom. It returns the existing `smart.error.ungrounded` identifier; it does not rewrite a model response or infer a more precise date. The observed zh-HK quotation `第一頁文件顯示'維護時間：2026年8月'` with value `2026` is covered through both text and visual evidence paths.

Only these files were changed by this task:

- `src/core/smart_naming.py`
- `tests/unit/test_smart_naming.py`
- `docs/reports/2026-09-29-evidenced-date-precision.md` (this report)

The root-owned, untracked probe and plan files were left alone. No model, native diagnostic, API, credential, Git mutation, configuration, template, saved name, or wire-shape change was made.

## Implementation and self-review

The previous `(?<!\d)`/`(?!\d)` match let the year or month pattern stop immediately before a date continuation. The guard now excludes a supported numeric or Chinese month continuation from a year match, and a supported numeric or Chinese day continuation from a month match. It still searches for a separate exact-precision date atom anywhere in the quoted evidence. The existing per-endpoint loop, calendar validation, same-precision range ordering, literal text occurrence, visual availability, and render ordering are unchanged. NFKC normalization remains in place before matching.

New public-render tests cover the observed quotation, numeric separators, Chinese spacing, fullwidth digits, both range-endpoint levels, and separate exact-precision dates beside more precise dates. Existing positive year/month/day and same-precision range tests remain unchanged. Review of the diff found no unrelated edits. `git diff --check` exited 0; Git printed only the working-copy LF-to-CRLF warnings for the two edited tracked files.

## Verification (from `D:\文件AI-AGENT\.worktrees\ai-smart-naming`)

All Python commands used `D:\文件AI-AGENT\.venv\Scripts\python.exe` and required shell escalation because the normal sandbox shell helper fails in this environment. Escalation was limited to executing local tests or read-only Git checks.

1. RED, after adding tests and before production change:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_smart_naming.py -k "year_only_rejected_from_observed_month or date_value_cannot_use_more_precise_atom_prefix or exact_date_atom_remains_usable_beside_more_precise_dates"`
   — exit 1: 10 failed because no `ungrounded` exception was raised, 6 passed, 94 deselected.
2. GREEN, same focused command after the guard change — exit 0: 16 passed, 94 deselected.
3. Required initial regression run:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_smart_naming.py tests/unit/test_local_inference_probe.py tests/integration/test_smart_analysis.py -k "not native_cli_reads_ascii_relative_files_from_unicode_cwd_without_loading_model"`
   — exit 0: 373 passed, 1 deselected, 3 Pydantic class-config deprecation warnings.
4. Expanded final regression run:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_smart_naming.py tests/unit/test_smart_workspace.py tests/unit/test_local_inference_probe.py tests/unit/test_local_model_probe.py tests/integration/test_smart_analysis.py -k "not native_cli_reads_ascii_relative_files_from_unicode_cwd_without_loading_model"`
   — exit 0: 397 passed, 1 deselected, the same 3 Pydantic deprecation warnings.
5. `git diff --check` — exit 0, with the LF-to-CRLF warnings noted above. `git diff -- src/core/smart_naming.py tests/unit/test_smart_naming.py` was reviewed read-only.

The deselected test deliberately launches a native executable (without model loading), outside this task's no-native-execution boundary. The results therefore do not claim that particular native smoke test passed. These tests verify consistency between a date value and its literal evidence string; they cannot verify whether a model's visual quotation is true or its proposed title is semantically accurate. The known bad result is rejected, not repaired.

## Root review and complete relevant regression

Independent scoped review found the fix compliant and no blocking code-quality
issue. Root then ran the same five modules from step 4 **without the `-k`
exclusion**, including the native CLI argument smoke test: **398 passed,
3 warnings in 4.72s**, exit 0. The three warnings are existing Pydantic class-based
configuration deprecations, not suppressed failures. No model or cloud request ran.
Production smart analysis still passes returned fields through `policy.render()`;
this patch does not bypass that guard or mutate stored tasks. Actual model quality
limitations in the separate three-language evidence report remain unchanged.
