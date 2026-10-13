# Frozen Local Workflow and Daily Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete actual isolated Windows EXE workflow evidence, locally fast-forward the approved candidate into the daily branch, and safely update the existing launcher.

**Architecture:** Reuse the exact production graph and the existing fixed-purpose `run_local_smoke` isolation, guards, report publication and strict cleanup. A separate explicit diagnostic choice generates only fixed public synthetic samples; it never accepts document paths or changes normal startup. Root owns actual model/visual evidence, Git, integration and the shortcut; one implementer at a time owns the diagnostic source/test paths.

**Tech Stack:** Windows x64, isolated Python 3.14.5/PySide6 6.12.0 candidate runtime, existing PyMuPDF/Pillow/PyAV, pinned managed Qwen3.5-4B and llama.cpp b10885, existing native same-volume file lane and watchdog.

## Global Constraints

- Do not call real cloud APIs, use real keys/Credential Manager or private samples.
- Do not change firewall/system policy, update formal Golden, push or publish.
- All screenshots and raw diagnostic artifacts go only to `tests/screenshots/qa-current/local-privacy/` in the active worktree.
- Keep cross-volume moves disabled; preserve original files, failed evidence and unknown stage/journal ownership.
- No normal-startup behavior change, new product feature, provider, model pin or UI redesign.
- Root alone performs Git commits, model inference, native image judgment, local merge and launcher writes. No concurrent writer edits the same files.
- Require explicit smoke/resources/data/report arguments for diagnostics; accept only a fixed workflow choice, never arbitrary file content/path inputs.
- A passing mock/fake logic test is not actual model or frozen workflow acceptance.
- Existing main HEAD must remain `4feb71200c08b18f0fe550295b624f9915577ae1` and tracked clean until the authorized local integration. Stop on divergence; fast-forward only, no pull or merge commit.
- Preserve all historical worktrees and resources. Updating the existing shortcut requires a backup and readback; do not delete it or overwrite an unrelated link target silently.

## Task 1 Fixed synthetic frozen workflow diagnostic

**Files:**

- Modify: `src/main_qml.py` (parser and explicit diagnostic dispatch only).
- Create: `src/services/local_ai/packaged_workflow_smoke.py` (bounded workflow orchestration).
- Create: `src/services/local_ai/synthetic_smoke_media.py` (fixed local PDF/video generation).
- Create: `tests/unit/test_packaged_workflow_smoke.py`.
- Modify only if necessary: `tests/unit/test_packaged_local_smoke.py` for CLI regression, retaining existing assertions.
- Root brief/report: `.superpowers/sdd/frozen-workflow-task-20261013-{brief,report}.md`.

**Interfaces:**

- Consume `run_local_smoke(resources_dir, data_dir, report_path, runtime_builder, exercise, timeout, cleanup_timeout)` without altering its isolation/guard/cleanup contract.
- Consume the actual `build_qml_runtime`, local resources/coordinator, Batch `applyTask/undoTask`, Watch `approveResult/undoResult`, stores and observed filesystem state.
- Produce `run_local_workflow_smoke(*, resources_dir, data_dir, report_path, workflow)` with finite budgets and workflows exactly `file-workflows`, `scan-pdf`, `video`.
- Add CLI `--local-smoke-workflow` with these exact choices. It requires the existing explicit `--smoke-test --local-smoke-resources --data-dir --report` combination; otherwise reject before any application/data/model action. Absence preserves the old local-text smoke.

- [x] RED: write/run parser guard tests and focused tests proving the orchestration uses actual returned states, restored hashes, zero cloud/credential activity, strict failure handling and the exact PDF/frame payload facts. Use injection for logic only; record failures before implementation.
- [x] Implement inert fixed media generation: two image-only PDF pages with readable synthetic coffee-machine maintenance/month/version facts; short three-stage pruning/rooting/transplant video with visible distinct stages. No filename/path/content options; no external file references, full PDF/video model input or download.
- [x] `file-workflows`: prepare the actual local service using existing smoke exercise; apply/undo its Batch suggestion and verify the original SHA. Configure two fixed new empty folders and a title-only HK template before runtime creation; after LOCAL READY, create one synthetic file in each folder. Observe real watchdog results, approve Review First, verify Auto Apply, undo both and verify SHA; bounded six-second duplicate observation and unchanged stored config bytes.
- [x] `scan-pdf` and `video`: each command uses a new EXE/service/data root. Generate its fixed sample, submit through actual Batch local routing, wait for a terminal state; reject NOT_READY/FAILED or invalid names. Record safe filename, coverage, prepared text/visual type/count/index/dimensions/bytes, response success/error and forbidden counters. Actual infer delegates remain unchanged; no strict JSON/evidence relaxations or replacement inference outputs.
- [x] Record minimal fixed-case request facts; assert no full PDF/video bytes or source path entered the local request. Semantic/visual acceptance is not set automatically by this diagnostic.
- [x] GREEN: run the entire new test file plus `test_packaged_local_smoke.py` and `tests/packaging/test_packaged_app.py` under the existing guarded candidate. Report raw summaries and any existing dependency warnings, not invented clean-output claims.
- [x] Root reviews exact diff and obtains independent task review before scoped commit. Rebuild when product source changed.

## Task 2 Actual frozen evidence and final source validation

**Files:** root-only QA capture/run scripts and reports under `tests/screenshots/qa-current/local-privacy/`; delivery report under `docs/reports/2026-10-13-frozen-local-handoff.md`.

- [x] Rebuild `dist/Xuxia` from the reviewed source using the existing Windows build script and candidate overlay. Run actual artifact packaging tests.
- [x] Execute each of the three fixed workflows in its own fresh isolated data root, from outside repository CWD, with native Windows QPA, forbidden guards, finite lifetime and no real keys. Preserve every failure and output directory; do not relabel reruns.
- [x] Inspect actual names against the generated content, PDF page images and ordered video frames. Verify request facts, original/hash restoration, actual observer behavior, zero QML warnings, owned process tokens, strict cleanup and correct state-directory residue checks. Real mouse/window captures supplement existing three-language UI evidence.
- [x] Run complete non-screenshot pytest, both entire tracked formal screenshot files with update modes off, acceptance and packaging tests. Record current raw counts/skips/warnings. No source change after these gates except truthful documentation.
- [x] Final independent bounded review covers the new diagnostic delta and the previously reviewed integration constraints; resolve determinate P0/P1 before merge, list ordinary P2/P3 separately.

## Task 3 Local integration and post-merge verification

**Files:** Git refs/index controlled only by root; existing build/QA scripts reused; no product implementation in this task.

- [x] Recheck main branch/HEAD, tracked clean, current candidate, ancestry and exact original shortcut. Retain the candidate worktree/branch and all unknown evidence.
- [x] In main run `git merge --ff-only codex/local-privacy-mode`; do not pull, push, amend, rebase or create a divergence-hiding merge commit.
- [x] Preserve the old runnable main artifact before an authorized rebuild; validate backup targets as narrow in-workspace paths. Do not recursively delete user or historical worktree data.
- [x] Rebuild from merged HEAD in main and run full non-screenshot regression, formal screenshot comparison with updates off, acceptance, packaging and explicit isolated EXE startup/local workflow smoke using main's artifact. Raw evidence remains in the approved local-privacy QA destination.
- [x] Recompute current main artifact SHA/size/full inventory and verify packaged three-language manuals equal current source. If a gate fails, retain branches/worktrees and fix the bounded defect; do not update the shortcut as if delivery passed.

## Task 4 Daily shortcut and truthful handoff

**Files:** `D:\文件AI-AGENT\序匣.lnk`, exact timestamped backup within the approved QA directory, final delivery report/ledger.

- [x] Read the existing shortcut target/working directory/arguments without launching it. Back up exact bytes before any write.
- [x] Set target to the verified main `dist/Xuxia/Xuxia.exe`, working directory to its complete artifact directory, no diagnostic/private arguments. Create no global registry or system settings.
- [x] Read back target/arguments/icon/working directory and verify the actual EXE bytes match the validated main inventory. Do not launch normal user mode during tests, since that would touch real configuration/credentials.
- [x] Report final main HEAD, current EXE/manual/launcher paths, actual gate results and limitations. User's own 10–20 copied-file trial remains user acceptance, not falsely counted as executed.

## Starting evidence

On 2026-10-13 root observed candidate HEAD `964c68625d2523424c4462354d942f0864ba10a5`, tracked clean with expected private `.superpowers/`; main remained `4feb71200c08b18f0fe550295b624f9915577ae1`, only the existing untracked `序匣.lnk`. A fresh guarded baseline ran **88 passed, 3 existing warnings, forbidden 0, MainThread only**. Root detected existing linked-worktree isolation and creates no new worktree.
