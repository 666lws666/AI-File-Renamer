# Managed Batch File-operation Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this bounded task with TDD, a fresh scoped spec/quality reviewer and root-owned verification/Git.

**Goal:** Move production Batch Apply/Undo off the Qt thread while preserving durable admission, partial physical outcomes, restart recovery and truthful finite close.

**Architecture:** Consume the reviewed standalone ManagedFileOperationLane, not a new disk engine. A small owner-side BatchFileOperations helper owns exact reservations and workspace epochs; BatchWorkspaceController remains the row/model/persistence surface. Runtime creates one shared application lane before Batch restoration and retains both until accepted moves and direct Qt publication have actually drained.

**Tech Stack:** Python frozen values, existing Preflight/RenameExecutor/RenameHistory/UndoManager, native PySide6 QObject/signals, the existing serial lane, isolated synthetic Windows tests.

## Global Constraints

- The sole source worktree is the existing isolated codex/local-privacy-mode checkout. Root owns Git; no main-checkout edits, merge, push or release.
- One application-owned serial off-Qt lane is shared by production Batch, later Watch and Undo. Do not add another file engine, history format or generic queue.
- Preserve existing templates, naming/output-language choices, extensions, source fingerprints, per-file outcomes and Apply/Undo semantics.
- A frozen user-approved disk request is separate from pending AI authority. A later mode/settings change or close cannot cancel a committed move or discard its physical result.
- Reserve capacity before durable workspace admission. Failed admission persistence performs zero user-file I/O. Stored operation IDs are never issued reservations or restart authorization.
- At most one operation per row, and at most 1000 admitted items across the shared lane. Do not add an unbounded private staging queue.
- Qt acceptance, ownership, model publication and lifecycle transitions remain on actual native Qt affinity. Disk execution and fresh post-Undo stat are on the lane worker.
- Public lane consumers connect with explicit DirectConnection on the same Qt owner; separately queued consumer work is not implicitly drained by the lane.
- Keep all eight existing domain statuses. Pending/recovery are additional explicit row roles; do not invent Applied or Undone before real physical success.
- Clear Workspace does not undo files/history. Late outcomes must never recreate cleared rows.
- Close is finite and retryable; keep Qt targets/owners alive until actual Future completion, signal emission exit and public delivery/publication exit. No forced move cancellation or worker wait on Qt.
- Expected legacy failures retain established redaction. New unexpected/queue/save/interruption failures use fixed message IDs, never exception text or a fabricated path.
- Synthetic local files only; no cloud API/key/Credential Manager/private inputs, firewall/ACL changes, formal Golden update or disabled guard/GC/backend change.
- This task excludes Watch activation, model resources/readiness, Settings/Provider changes, HTML/manual packaging and real model inference. Explicitly injected legacy Batch behavior remains a compatibility seam.

## Task 1: durable Batch ownership, composition, row locks and close

**Files:**
- Create `src/controllers/batch_file_operations.py`: small owner-side reservation/persistence/publication helper; no disk executor of its own.
- Modify `src/controllers/batch_workspace_controller.py`: optional lane injection, row roles, guarded Apply/Undo routes, epoch Clear, truthful physical result publication, interrupted metadata reconciliation.
- Modify `src/qml_bootstrap.py`: one production lane created before Batch restore, owned during partial construction and finite cleanup.
- Modify `src/services/file_operation_backend.py`: append optional immutable SourceFingerprint outcome field; capture actual successful Undo target stat on the worker.
- Modify `src/ui_qml/TaskQueue.qml` and `src/ui_qml/TaskCard.qml`: minimal pending/recovery lock/busy bindings, fixed message translation.
- Modify `src/utils/i18n/locales/zh_CN.json`, `zh_HK.json`, `en_US.json`: fixed operation/recovery strings.
- Create `tests/integration/test_managed_batch_file_operations.py`.
- Create `tests/integration/test_managed_file_operation_runtime.py`.
- Modify `tests/unit/test_file_operation_backend.py`: actual changed-content Undo fingerprint and stat-failure recovery.
- Create `tests/qml/test_file_operation_row_locks.py`: real QML pending/recovery interaction and teardown.

No other source/test changes. In particular do not edit the reviewed lane, disk/history engine, processing authority, Watch, Provider/config/credentials or existing screenshot registry/Golden/tolerances.

### Frozen consumption and additive interfaces

Consume `FileOperationRequest(operation_id, kind, batch_id='', plans=(), task_ids=())`, exact `FileOperationReservation`, `FileOperationProgress`, `FileOperationCompletion`, `lane.reserve/cancel/commit/begin_close`, and truthful `owned_item_count/workers_idle/closed`.

Append an optional compatible final field to the outcome:

```python
@dataclass(frozen=True)
class FileOperationOutcome:
    task_id: str
    batch_id: str
    success: bool
    error: str | None = None
    new_path: str = ''
    recovery_required: bool = False
    source_fingerprint: SourceFingerprint | None = None
```

Existing six-positional callers continue to work. Only successful Undo snapshots a fresh `os.stat(result.new_path)` into SourceFingerprint on the worker. Preserve genuine success/new_path and existing F0 warning; a failed stat adds recovery_required and fixed `fileops.error.fingerprintRecovery` if no existing warning. Never turn a completed move into false failure or run a replacement move.

Add `file_operation_lane: ManagedFileOperationLane | None = None` as a keyword-only Batch constructor input. Omitted/None retains the explicit legacy synchronous behavior; production bootstrap always supplies its one managed lane. Install the helper before workspace restoration and before any restored analysis starts.

Helper interface (complete implemented bodies, no placeholders):

```python
class BatchFileOperations(QObject):
    def __init__(self, controller: BatchWorkspaceController,
                 lane: ManagedFileOperationLane): ...
    def apply(self, task_ids: tuple[str, ...]) -> bool: ...
    def undo(self, task_id: str) -> bool: ...
    def owns(self, task_id: str) -> bool: ...
    def advance_epoch(self) -> None: ...
    def begin_close(self) -> None: ...
    @property
    def workers_idle(self) -> bool: ...
```

The helper borrows the same-thread controller/lane, owns no pool, and uses an exact-reservation registry plus current-epoch row ownership. Pending registry and result snapshots remain bounded by shared admitted capacity. Explicit DirectConnection consumes the lane's already queued owner-side public signals. Each callback holds helper publication depth in try/finally, so reentrant runtime cleanup cannot dispose owners during publication.

Add `fileOperationPending` and `fileOperationRecoveryRequired` bool model roles. They are derived from private current row ownership and factual recovery state, not permission from JSON. Existing mock models need no new role: TaskQueue uses `model.fileOperationPending === true` and `model.fileOperationRecoveryRequired === true` to avoid undefined assignment warnings.

Runtime adds `file_operation_lane` and `owns_file_operation_lane` strong fields and `file_operation_lane_factory` build injection. The production factory signature is `factory(history_path: Path) -> ManagedFileOperationLane`; default builds one FileOperationBackend + lane. A borrowed/explicit Batch controller does not secretly create another lane. This shared lane is retained for later Watch composition.

### Durable admission and row transaction

- [ ] Write failing actual-file/Qt tests before changing production code. Use the guarded Windows command in the private dispatch, fresh OS-temp dirs, zero network/credential access and ordinary Qt destruction.
- [ ] Capture eligible task IDs on Qt, refusing absent, editing, already-owned or recovery-blocked rows. Apply accepts only review_pending/undone with a valid exact suggested name; Undo only applied. For a selection larger than 1000, refuse the operation with queueFull and zero I/O rather than silently applying only a prefix.
- [ ] Freeze plans from the row's source path, persisted SourceFingerprint, suggested name, accepted target directory or source parent and protected extension. Do not stat/preflight/history-scan on Qt admission; the worker rechecks the accepted file. One Apply request carries one batch ID; Undo carries the exact task ID.
- [ ] Reserve first. Build a deep-copied candidate with this optional per-row `fileOperation` marker, then atomically save it before installing the exact private owner and committing:

```python
marker = {
    'version': 1,
    'operationId': request.operation_id,
    'kind': request.kind,
    'batchId': request.batch_id,
    'sourcePath': task['originalName'],
    'targetPath': accepted_target_path,
}
```

For Undo sourcePath is the actually applied path, targetPath the accepted original path. Exact primitive keys/types and bounded lengths are validated when restoring a marker. Marker paths must match the row and matching actual history; marker data can never create a RenamePlan or execute work on restart.

- [ ] Admission save failure cancels only the uncommitted reservation. Preserve suggestion/status/file bytes and show `fileops.error.admissionSaveFailed`; publish only an explicit in-memory error, no fake saved success.
- [ ] Install private exact ownership before commit; commit rejection retires only that owner, attempts to clear its persisted marker, and displays `fileops.error.queueUnavailable`. If marker retirement save fails, retain interrupted-recovery metadata rather than execution authorization.
- [ ] Publish model/public notifications only after save + exact owner + commit transition. Reentrant callbacks must not enqueue the same row twice, mutate a frozen accepted target or erase a newly created operation.
- [ ] While owned/recovery-blocked, begin/confirm/cancel inline-edit, retry, ignore, Apply and Undo do nothing; model action flags and QML controls match Python guards. Selection/search/filter remain usable. Clear does not cancel the physical operation.

The admission boundary has this exact order:

```python
reservation = lane.reserve(request)
if reservation is None:
    return refuse_without_disk_io()
candidate = build_pending_candidate(request)
try:
    controller._save_workspace(candidate)
except Exception:
    lane.cancel(reservation)
    return publish_admission_error_preserving_suggestion()
install_exact_owner(reservation, epoch)
if not lane.commit(reservation):
    retire_only_that_owner(reservation)
    return retire_marker_and_publish_queue_error()
controller._publish_tasks(candidate, selection=True)
return True
```

These names describe the complete task implementation; no undefined placeholder helper bodies may ship.

### Result, progress and recovery publication

- [ ] Consume only expected exact reservation + item index + task ID + outcome type/primitive field types; deduplicate each index before model signals. For Apply batch IDs must match; Undo preserves its real historical batch ID. Reject foreign/copy/stale payloads without retiring a valid current operation.
- [ ] Mark an item received before any reentrant publication. Terminal ownership retirement occurs before public/reentrant completion notifications; helper publication depth stays owned until callback exit. Never drop a physical result solely because analysis authority/mode changed or the controller is closing.
- [ ] Apply success publishes Applied using actual new_path. Undo success publishes Undone using actual restored new_path and fresh worker SourceFingerprint, clears appliedPath and retains the exact recovery warning. An absent/rejected fresh fingerprint marks recovery and blocks unsafe ordinary retry.
- [ ] Preserve partial failed results and identities. Unexpected backend unknownOutcome means unconfirmed physical state, recovery_required and no fabricated path; block ordinary Apply/Undo/retry pending actual restart/history reconciliation.
- [ ] First active Apply resets aggregate progress; later admitted Apply requests add to its total. Each authentic item increments current/success/failed once. Active ends only when all owned Apply requests have terminated. Undo uses row busy/recovery state, not a fabricated Apply success. No double counting on terminal duplicate/reentrancy.
- [ ] Save result candidates before ordinary publication. If this post-move save fails, publish actual physical status/path/fingerprint in memory with `fileops.error.workspaceSaveRecovery` and recovery flag; persist pending marker remains for restart. Do not leave UI pointing to a nonexistent file or discard later items.
- [ ] Any epoch-mismatched Clear result may update history/progress facts but cannot recreate rows. Clear order: persist empty candidate, advance epoch/unlink current row owners, publish empty model, invalidate pending AI. Accepted operation owners remain alive until terminal publication.
- [ ] Fixed three-language IDs: `fileops.status.running`, `fileops.error.admissionSaveFailed`, `fileops.error.queueFull`, `fileops.error.queueUnavailable`, `fileops.error.unknownOutcome`, `fileops.error.undoRecordMissing`, `fileops.error.historySaveRecovery`, `fileops.error.workspaceSaveRecovery`, `fileops.error.fingerprintRecovery`, `fileops.error.interrupted`. History/manual-recovery legacy warning maps to historySaveRecovery, not raw English text in Chinese UI.

### Interrupted metadata and restart

- [ ] Preserve schema_version1 compatibility and all existing row/naming/template/language data. Optional markers are inert. No automatically committed move or undo is reconstructed from persisted IDs.
- [ ] Validate/parse JSON separately from reconciliation persistence. A valid workspace whose reconciliation write fails must not be quarantined as corrupted or replaced with an empty list.
- [ ] For an interrupted Apply, require matching task/batch/history old/new paths, actual target exists and original does not; only then restore Applied. If no move occurred, retain the suggestion and expose Interrupted instead of auto-applying. Both/neither path or incompatible identity/fingerprint yields recovery.
- [ ] For interrupted Undo, read the latest matching history with `active_only=False`, require matching task/history paths and actual original exists while renamed target does not; only then restore Undone with a fresh verified stat fingerprint. This applies both when normal history marks undone and when F0 could not save the undone history flag. Both/neither or incompatible/missing history stays recovery; never guess completed from the stored marker.
- [ ] Existing already-applied rows must be reconciled too, not blindly trusted if an interrupted Undo exists. Changed/missing/ambiguous paths cannot be silently relabeled successful.
- [ ] Strip private pending ownership from restoration. A marker may yield factual status/recovery warning but cannot become a live reservation or trigger automatic replay.
- [ ] Preserve exact actual history and bytes; no clearing history/quarantine to make a state green.

### Runtime close and minimal QML state

- [ ] Runtime partial construction installs the owned shared lane immediately after creation and before Batch initialization. First cleanup seals shared lane admission before Batch.close; drain writer/analysis/local services and file lane together. Require lane.closed and Batch/helper idle before deleting root/engine/context objects.
- [ ] Batch.close seals further row operation admission but retains committed private owners and publishes eventual physical outcomes despite closed. It does not shut down a lane borrowed by another client. Legacy analysis close behavior and OSError retry remain.
- [ ] Finite cleanup returns False with strong owners intact if backend, Future tail, emission/public callback, candidate publication or Qt delivery is not drained. Later cleanup succeeds only after actual completion; no wait/kill/cancel committed moves on Qt.
- [ ] TaskCard shows fixed Running while operation-owned, disables row edit/Apply/retry/ignore/Undo as required, renders the one fixed recovery message. No normal row visual redesign, duplicated error or fake model READY. All three locales work; no Golden update.

### Required concrete regression shapes

Use real synthetic files, an actual lane and finite QApplication event pumping. Controlled worker blockers may wrap the actual backend; observers of I/O must assert thread IDs. These examples are minimum tests, not static/AST substitutes:

```python
source = tmp_path / 'source.txt'
source.write_text('synthetic document', encoding='utf-8')
controller = BatchWorkspaceController(workspace_path=tmp_path / 'workspace.json',
    history_path=tmp_path / 'history.jsonl', analyzer=lambda *_a: 'topic.txt',
    background=False, file_operation_lane=lane)
controller.add_files([str(source)])
task_id, = controller.task_ids
controller.applyTask(task_id)
assert controller.task_snapshot(task_id)['fileOperationPending'] is True
assert saved_marker_exists_for(task_id)
# Block the worker before the actual engine: an owner QTimer must still fire.
# Release it, pump until the helper and lane are truly idle, inspect actual bytes.
assert controller.task_snapshot(task_id)['status'] == 'applied'
controller.undoTask(task_id)
pump_finite_until_true_idle()
assert source.read_text(encoding='utf-8') == 'synthetic document'
assert controller.task_snapshot(task_id)['status'] == 'undone'
```

- [ ] Admission-save-failure actual bytes/no backend call/no reservation weight leak, queue-submit rejection and marker-retirement-failure cases.
- [ ] Two-file Apply partial conflict, per-item progress/identity, F0 Undo-history-save failure, post-move workspace-save failure, actual changed-content Undo fresh fingerprint and subsequent Apply.
- [ ] Edit/retry/ignore/duplicate Apply blocked while pending; search/selection still work; queued targets remain frozen despite global target/settings/mode changes.
- [ ] Clear during a deterministic blocked move persists no rows, late completion never resurrects them, old terminal cannot erase a newer epoch's private owner.
- [ ] Nested public callback/reentrant operation and finite runtime close; explicit Direct consumers and ownership depth cover public callback exit. Foreign/duplicate payloads cannot mutate rows/progress.
- [ ] Restart every unambiguous/ambiguous Apply/Undo marker case, no automatic backend invocation, valid JSON reconciliation save failure remains valid/not quarantined.
- [ ] Runtime construction failure after lane creation; no lane worker/pool or Qt-owner leak. Actual close while move blocked returns False, keeps root/lane/controller valid, then completes after release.
- [ ] Real TaskCard native QML clicks on pending/recovery row do not trigger edits/Apply; defaults remain unchanged and warnings=0. Fixture teardown actually destroys its owned Qt tree before contexts.

### Verification and checkpoint

- [ ] Record assertion-level RED/GREEN, exact guarded commands/raw summaries, scope and concerns in `.superpowers/sdd/managed-batch-file-operations-report.md`. No writer Git changes.
- [ ] Run `tests/integration/test_managed_batch_file_operations.py`, `tests/integration/test_managed_file_operation_runtime.py`, `tests/qml/test_file_operation_row_locks.py`, `tests/unit/test_file_operation_backend.py`, plus existing `tests/integration/test_managed_file_operation_lane.py`, `tests/unit/test_batch_workspace_controller.py`, `tests/unit/test_batch_attempt_identity.py`, `tests/integration/test_managed_batch_publication.py`, `tests/integration/test_managed_processing_runtime.py`, and `tests/qml/test_batch_runtime_wiring.py`. Do not mutate prior tests to hide compatibility regressions.
- [ ] Root freezes the diff, obtains fresh scoped spec+quality review, resolves Critical/Important findings, then runs independent covered regression and complete non-screenshot/screenshots/acceptance with UPDATE absent.
- [ ] Root stages only the named task files and public plan and creates an independently revertible local checkpoint. Do not call the product complete: Watch/resource management/mode UI/manual/package/model acceptance remain separate gates.
