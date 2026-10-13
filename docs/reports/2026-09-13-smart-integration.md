# AI smart naming: checkpoint and verification

## Scope and safety

Base: `4feb71200c08b18f0fe550295b624f9915577ae1`, isolated branch `codex/ai-smart-naming`. Main checkout and the public snapshot remain untouched. No cloud API, real credential, private media, push or release was used.

Implemented a versioned evidence-conscious naming policy, frozen per-task naming/language snapshots, explicit three-language mode controls, and complete offline Simplified Chinese / Traditional Chinese (Hong Kong) / English manuals. Existing defaults, nine templates and Watch settings are not migrated. Apply, Undo, extension protection and collision handling are reused.

Local rendering enforces separator, role ordering, date grammar and length. It does not prove that a model understood an image or translated a topic correctly. Missing evidence, unsafe/generic/overlong output and unsupported strategy fail visibly; no truncation or silent template fallback occurs.

## Bugs found and corrected during review

- Default image/video metadata cannot masquerade as extracted body evidence.
- Empty spreadsheet `[Sheet: ...]` structure cannot masquerade as real content; actual Workbook tests cover rejection and populated acceptance.
- Smart error identifiers are translated on task cards.
- Manual claims now distinguish current uncached smart Batch behavior and failed-first-generation editing limits.
- The legacy acceptance script used the main checkout even from a worktree. It now selects its own source directory, with a regression test. Only the rerun against this worktree counts as current-source evidence.

## Native evidence

`scripts/capture_smart_naming_native.py` records 36 real app screenshots (12 per locale) and 12 minimum-window cases. Synthetic fixture names are not semantic model outputs. Setup assertions, warning capture, native clicks, CJK and geometry are enforced. The companion manifest records this limitation.

`scripts/verify_smart_manual_native.py` uses an off-the-record native Qt browser with external requests blocked. Six locale/width cases load all 12 chapter images and 17 chapters; desktop language switching uses real mouse clicks. Screenshots are local QA output, not formal Golden files.

The old ten flat manual PNGs were replaced by the 36 current localized images. The old files remain recoverable in Git history.

## Verified results before checkpoint

| Gate | Raw result |
|---|---|
| Policy / smart analysis / task snapshots | 101 passed |
| QML suite | 303 passed |
| Manual contracts | 15 passed |
| Acceptance harness location regression | 1 passed (previously RED) |
| Current-worktree acceptance | 186/186 passed |
| M1 capture/compare, updates disabled | 49 passed |
| M0 screenshots, updates disabled | 5 passed, 1 expected update-mode skip |
| Packaging and isolated EXE smoke | 23 passed |
| Complete non-screenshot suite before commit | 1871 passed, 1 skipped, 1 failed |

The last failure is `test_screenshot_goldens_untouched`: it requires no pending Golden Git changes. The user explicitly approved the 38 changed M1 PNGs; they were not yet committed. Independent review confirmed this is a checkpoint-order constraint. The test is not removed, skipped, loosened or excluded. A complete rerun after committing is mandatory; the pre-checkpoint run is NOT reported as all-green.

M0 pixels, screenshot assertions and pixel tolerances are unchanged. Existing Pydantic/Pillow deprecation warnings are maintenance backlog, not suppressed.

## Windows artifact

- Relative distribution: `dist/Xuxia/` (ignored build output).
- EXE: `Xuxia.exe`, 10,962,726 bytes.
- SHA-256: `2A814F41559ACC36F34658E8F6C4DEEA72FA305064BBE6785DC35F71B898171B`.
- Distribution: 3,137 files, 576,124,555 bytes, including the three-language companion manual and resources.
- Build succeeded; optional Qt asset-downloader plugin warning did not prevent packaging or smoke.

## Remaining at this checkpoint

Run the complete non-screenshot and screenshot gates after committing, and record the final raw result. No merge/push is implied. The newly approved local privacy mode is a subsequent isolated milestone, not implemented by this checkpoint. Real smart-naming semantic quality remains unverified until actual permitted model inference and human content review.

## Post-checkpoint verification: PASS (software gates only)

Implementation checkpoint: `6225f85b0076e3b7b41605593eb1ae2cb76dfe4d`.

- Complete `pytest tests/ --ignore=tests/screenshots -q --tb=short`: **1872 passed, 1 skipped, 3 warnings**. The previously failing Golden Git-state guard now passes without modification or exclusion.
- M1, `UPDATE_GOLDENS` absent and `QT_SCALE_FACTOR=0.8`: **49 passed**, 82 existing Pillow deprecation warnings.
- M0, update/scale/platform overrides absent: **5 passed, 1 expected update-mode skip**, 4 existing Pillow warnings.
- Final offline browser run: **6 cases, 12 screenshots, 0 network requests, 0 console errors**.
- Packaging/EXE smoke: **23 passed**; build and artifact identity are listed above.
- Working tree and `git diff --check` clean before this documentation-only record. Main remains `4feb712`; its pre-existing untracked user shortcut is preserved.

This closes the current implementation/visual/regression/package work. It does not claim real cloud model semantic quality. Continue the separately authorized local-mode feasibility and real-inference milestone without changing this baseline or silently enabling unfinished privacy behavior.

Artifact history note: the EXE hash above identifies this smart-naming checkpoint's build. A later independently verified Batch cancellation/attempt-identity safety fix (`481e2b0`) rebuilt the same ignored distribution directory. For the current EXE hash, tests and resource/memory handoff, use [the subsequent feasibility report](2026-09-13-local-privacy-feasibility.md). The historical smart-naming commits remain unchanged and reproducible.
