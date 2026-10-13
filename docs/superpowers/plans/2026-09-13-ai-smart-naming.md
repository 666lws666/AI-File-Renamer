# AI Smart Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans. Follow TDD and review each bounded deliverable.

**Goal:** Add evidence-conscious AI smart naming alongside unchanged template naming, and update the offline three-language manual.

**Architecture:** A pure SmartNamingPolicy defines one versioned expression contract. The existing BatchAnalysisService branches to that contract after the same local extraction and bounded media preprocessing. BatchWorkspaceController snapshots mode, language and policy version into each imported task; Watch explicitly remains template-based. AI returns evidence-tagged semantic parts, never paths. A local renderer orders/validates parts and attaches the original extension.

**Tech Stack:** Python 3.14, PySide6/QML, existing JSON-schema Provider protocol, static offline HTML/CSS/JS.

## Global Constraints
- User approved implementation on 2026-09-13; continue without repeating the product approval gate.
- Work only in the isolated ai-smart-naming worktree. Base 4feb712. Main checkout/public snapshot remain unchanged.
- No real API, credentials, network model calls, push, or unrequested defaults/watch migration. After native review the user explicitly approved only the 38 affected M1 Golden files (40 cases); M0, assertions, dimensions and tolerances remain unchanged.
- Existing templates and saved defaults stay intact; new Batch session starts in template mode.
- Language is the user's filename language, independent of UI/manual locale.
- Smart mode is not a renamed title template. One policy version, separator, ordering and date grammar applies across a batch.
- Unsupported/unreadable/insufficient/generic/unsafe/overlong responses fail visibly; never silently fall back or truncate.
- Provider mocks prove software contracts, not real model comprehension/semantic quality.
- Existing Apply/Undo/extension/conflict/preflight logic is reused unchanged.
- Any stale Golden comparison must be reported honestly; request permission only after real native inspection, do not auto-update.

## Task 1: Smart policy and analysis strategy
Read the complete requirements in `2026-09-13-smart-task-1.md`.
Owned files: src/core/smart_naming.py, src/core/batch_analysis.py, tests/unit/test_smart_naming.py, tests/integration/test_smart_analysis.py.
- [x] RED: mixed source fixtures, generic/insufficient/invented-evidence/overlong/path/locale failures.
- [x] GREEN: implement policy/schema/render and production service branch, preserve default template and Watch behavior.
- [x] Review: no path I/O in policy; no hidden semantic PASS claim.

## Task 2: Batch snapshot integration (root)
Owned files: src/controllers/batch_workspace_controller.py, tests/unit/test_smart_workspace.py.
Interfaces: namingMode Property + namingModeChanged Signal + setNamingMode(str); values template/smart. Per-task namingMode and namingPolicyVersion default template/smart-v1. Smart selections persist on tasks, not AppConfig/default templates; session choice starts template.
- [x] RED: mode default, no saved default mutation, import/retry/restart snapshot consistency, legacy workspace template fallback, conflict Apply+Undo.
- [x] GREEN: send named naming_mode/naming_policy_version to compatible analyzers; fail smart mode if an injected analyzer cannot accept it.
- [x] Test two same-name smart suggestions through real RenameExecutor; no overwrite, Undo both.

## Task 3: QML and locales
Read `2026-09-13-smart-task-3.md`.
Owned: BatchToolbar.qml, BatchPage.qml, NamingLanguageDialog.qml, mock_batch_controller.py, three locale JSONs, new QML smart tests.
- [x] RED: explicit mode switching, template irrelevant in smart mode, language carryover and no hidden API invocation.
- [x] GREEN: accessible two modes, localized helpers/errors; preserve minimum-size usability.
- [x] Root native review, no Golden writes.

## Task 4: Offline multilingual manual
Read `2026-09-13-smart-task-4.md`.
Owned: root Chinese HTML, guide assets text/HTML/JS/CSS, build/spec/manual tests as needed; no PNG capture by worker.
- [x] RED: complete three languages, linked chapters, offline paths, mode/language/safety explanations.
- [x] GREEN: one existing entry, complete zh-HK/en-US static subpages; keyboard language links and print current language.
- [x] Capture actual three-language updated UI; no synthetic screenshot or private source material.
- [x] Build package and validate companion manual/resources.

## Task 5: Integration Gate (root)
- [x] Focused tests then complete non-screenshot suite and existing screenshot suite (updates disabled).
- [x] Native Windows captures at 1000x700 and 900x640 for three locales: mode chooser, smart mode, filename language, mixed review, error/long name; all mocked/local.
- [x] Inspect screenshots for CJK, overlap/scroll, real click behavior and zero QML warnings.
- [x] Review policy/pipeline and UI/manual independently; fix deterministic defects.
- [x] Build EXE only after source gates; package/acceptance verification with ephemeral settings/credentials.
- [x] Report actual test output, deviations, remaining Golden/real-model quality gate; no merge or push implied.

## Checkpoint status (2026-09-13)

Tasks 1–4 and native/independent review are complete. RED/GREEN and final implementation evidence are in the three worker reports and the final integration report. The checklist above now records completed software gates; the final integration report preserves both the initial failure and the complete post-checkpoint rerun. Real model semantic quality remains a separate unverified gate.

- Policy/controller focused regression: 101 passed; final QML suite: 303 passed; manual contract: 15 passed.
- Native Windows: 36 three-language manual images plus 12 minimum-window review/error images; all captured with synthetic data, CJK checks and zero QML warnings.
- The approved 38 M1 images were regenerated once; update-disabled comparison: 49 passed. M0 independently: 5 passed, 1 expected update-mode skip.
- Current-source acceptance: 186/186. Fixed the legacy acceptance harness's hardcoded main checkout; a RED/GREEN regression now enforces script-relative source selection.
- Windows package rebuilt with final manual assets; packaging/isolated EXE smoke: 23 passed.
- First complete non-screenshot run: 1871 passed, 1 skipped, 1 failed. The sole failure requires Golden files to be committed; the approved files were still pending. Do not alter/skip that test. Commit the reviewed baseline, then rerun the entire suite before claiming PASS.
- Actual cloud-model understanding/translation quality remains unverified. Synthetic adapter tests demonstrate contracts and file safety only. The next separately approved local-privacy stage must run a real local model before semantic acceptance.
