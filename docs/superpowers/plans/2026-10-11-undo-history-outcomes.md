# F0: preserve actual Undo outcomes when history marking fails

This prerequisite fixes an observed data/UI truth defect before the managed,
shared file-operation lane is introduced. It does not complete that lane or Watch.

## Scope and global constraints

- Sole writer may change only `src/core/undo_manager.py` and
  `tests/unit/test_undo_manager.py`. Root owns this brief, Git and review.
- Reuse `BatchResult`, `RenameExecutor` and atomic `RenameHistory` as-is. No new
  disk engine, history format, direct move I/O or automatic repair/retry of moves.
- Synthetic files under isolated pytest temporary directories only. No network,
  real API/Key/Credential Manager, private inputs, firewall/ACL changes, Golden,
  packaging/manual/UI changes, push, merge or release.
- No exception detail, source/destination path or synthetic secret may enter the
  new history-persistence warning. Existing unrelated executor errors are not
  broadened or rewritten by this task.
- The source worktree is `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch
  `codex/local-privacy-mode`. Task base is
  `3a3ceeb8047a8fd2a18fd23e43454130ed291f1a`.

## Confirmed failure and required behavior

`UndoManager._undo_records()` performs successful physical moves, then calls
`mark_records_undone()`. An `OSError` in atomic history persistence currently
escapes and discards all per-record results. The restored source exists, its
renamed destination no longer exists, but the history flag is still active.

Preserve that physical truth. If marking successfully moved records raises
`OSError`, return the already produced results:

1. Every physically successful record remains `success=True`, with its actual
   restored old path in `new_path`, correct `task_id` and current `batch_id`.
2. Mark only those successful results `recovery_required=True`; set one fixed,
   redacted warning describing completed Undo and unsaved history/manual recovery.
   Never format or include the caught exception. Do not report a failed move.
3. Preserve failed records as failures with their original error, empty new path,
   and no invented history-persistence recovery marker.
4. History bytes/flags remain as the atomic writer actually left them. Do not
   claim `undone=True`, call moves a second time, overwrite history in memory or
   swallow arbitrary programming errors. Catch only the confirmed `OSError` at
   the history marking boundary, not the whole Undo operation.
5. Existing successful history marking is unchanged: success outcomes have no
   new warning/recovery flag; LIFO across/within batches and row-level task Undo
   remain unchanged.

The later managed lane/UI task must publish these outcomes and visible warning;
this pure domain correction alone is not a finished user-facing recovery feature.

## TDD implementation and acceptance

Before production edits, add failing regression tests that exercise real
synthetic file moves and real atomic history persistence. Inject failure only at
the history write/replace boundary after the Apply setup is durable.

- Single `undo_task`: history marking `OSError` must not escape; old file and bytes
  restored, renamed file absent, returned physical success+actual restored path+
  task/batch IDs+recovery warning. Old history bytes and flags preserved.
- Mixed batch reverse order: at least one real successful move and one failed
  record (e.g. occupied old path). Results in record-reverse order with their own
  identities; only real successes recovery-marked, failed result unchanged.
- Two real successes: both outcomes retained, no second move/retry, history
  unchanged, warning contains neither injected exception text/path nor secrets.
- Healthy marking regression remains ordinary success without warning/recovery.
- A non-`OSError` programming exception from the history marker must still
  surface; do not catch `Exception` to conceal it.

Run the existing Undo tests plus focused file-executor/history dependencies and
report exact RED/GREEN commands, outputs and exits. Root runs wider regression
and commits after scoped independent review. Do not execute Git mutations.

## Handoff

Write full report (requirements implemented, RED/GREEN evidence, exact changed
files, self-review/concerns) to
`.superpowers/sdd/undo-history-outcomes-report.md`. Return only status and compact
test summary. Preserve existing private `.superpowers/` files and all unrelated
source; do not run full packaging/screenshots or claim product completion.
