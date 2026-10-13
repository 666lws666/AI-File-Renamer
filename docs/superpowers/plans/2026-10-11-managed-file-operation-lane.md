# Managed File-operation Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development to implement task-by-task with TDD and
> independent scoped review. Root owns Git and integration.

**Goal:** Introduce one bounded, serial, off-Qt owner for user-approved Apply and
Undo, then connect production Batch and Watch without losing physical outcomes.

**Architecture:** This plan's first deliverable is an independently tested lane,
not a new rename engine. Immutable requests and exact one-use reservations
separate capacity/admission from execution. Existing Preflight, RenameExecutor,
RenameHistory and UndoManager remain the disk/history implementation.

**Tech Stack:** Python, frozen dataclasses, ThreadPoolExecutor(max_workers=1),
PySide6 QObject/signals with explicit queued delivery, isolated synthetic files.

## Global Constraints

- One application-owned serial off-Qt lane is shared by production Batch, Watch
  and Undo. Reuse Preflight/RenameExecutor/RenameHistory/UndoManager; do not add a
  new file engine, generic task framework or alternate history.
- Admission and durable owner metadata happen on Qt before any execution. Frozen
  user-approved plans are distinct from pending AI contexts. Later processing-mode
  changes revoke pending analysis, not an already accepted disk operation.
- Reserve capacity before persistence; a failed candidate write performs no file
  I/O. Only the exact issued reservation may be committed, once. Pool rejection
  has truthful failure/ownership retirement, never a phantom active operation.
- A bounded queue covers reservations, committed waiting/active work and outstanding
  completion delivery. Existing Batch's 1000-item pending limit is the upper bound
  for this first composition; no unbounded private staging list bypasses it.
- Runner result snapshots preserve task/batch identity, partial success,
  recovery_required and actual new_path. They cannot borrow live QObject/config
  state. New unexpected-error mapping is fixed/redacted, never exception text.
- Runtime close stops new reservations, cancels uncommitted ones, and drains all
  already committed file work/posted completions while Qt targets remain alive.
  A finite poll timeout retains ownership and returns false. Do not kill/cancel
  an in-progress file move or hide its eventual history outcome.
- Synthetic fixtures only; no real API/Key/Credential Manager/private files,
  system security changes, formal Golden update, push, merge or release.
- This task does not modify the main checkout, processing authority, UI, Watch,
  resource/model code, config/credentials, history format or disk engine. Root will
  specify the exact Batch/runtime integration task after this API's reviewed freeze.

## Task 1: standalone shared lane and immutable operation outcomes

**Files:**
- Create `src/services/file_operation_backend.py`: pure request/result values and
  worker-owned adapter to the existing disk/history classes.
- Create `src/controllers/managed_file_operation_lane.py`: bounded QObject lane,
  exact reservations, worker loop and queued ownership/delivery drain.
- Create `tests/unit/test_file_operation_backend.py`.
- Create `tests/integration/test_managed_file_operation_lane.py`.

No other source/test modification. The prerequisite F0 Undo persistence correction
is consumed as-is; root supplies its checkpoint to the implementer. Root writes
this plan, private task report and review packet separately.

### Frozen public interfaces

Implement the following interfaces (private helpers may be added within these files).

```python
@dataclass(frozen=True)
class FileOperationRequest:
    operation_id: str
    kind: str                       # exactly 'apply' or 'undo'
    batch_id: str = ''              # nonempty for apply; unused for undo
    plans: tuple[RenamePlan, ...] = ()
    task_ids: tuple[str, ...] = ()   # undo only, unique, caller order

    @property
    def item_count(self) -> int: ...

@dataclass(frozen=True)
class FileOperationOutcome:
    task_id: str
    batch_id: str
    success: bool
    error: str | None = None
    new_path: str = ''
    recovery_required: bool = False

class FileOperationBackend:
    def __init__(self, history_path: str | Path): ...
    def execute_item(self, request: FileOperationRequest,
                     index: int) -> FileOperationOutcome: ...

@dataclass(frozen=True, eq=False)
class FileOperationReservation:
    request: FileOperationRequest

@dataclass(frozen=True)
class FileOperationProgress:
    reservation: FileOperationReservation
    index: int
    result: FileOperationOutcome

@dataclass(frozen=True)
class FileOperationCompletion:
    reservation: FileOperationReservation
    results: tuple[FileOperationOutcome, ...]

class ManagedFileOperationLane(QObject):
    itemCompleted = Signal(object)  # FileOperationProgress, Qt owner delivery
    completed = Signal(object)      # FileOperationCompletion, Qt owner delivery

    def __init__(self, backend: FileOperationBackend, parent=None,
                 *, capacity: int = 1000): ...
    def reserve(self, request: FileOperationRequest) -> FileOperationReservation | None: ...
    def cancel(self, reservation: FileOperationReservation) -> bool: ...
    def commit(self, reservation: FileOperationReservation) -> bool: ...
    def begin_close(self) -> None: ...

    @property
    def owned_item_count(self) -> int: ...
    @property
    def pending_job_count(self) -> int: ...
    @property
    def workers_idle(self) -> bool: ...
    @property
    def closed(self) -> bool: ...
```

The ellipses above describe interface signatures, not permission to ship
placeholder bodies. All methods must be fully implemented and behavior-tested.

### Required behavior and implementation steps

- [ ] Write RED tests first for real serial Apply/Undo, exact reservations and
  Qt queued delivery. The following is the minimum real-file test shape; construct
  a QApplication fixture, preserve the lane until actual drain, and use an event
  pump with an explicit finite deadline rather than timing-only sleeps:

```python
source = tmp_path / 'original.txt'
source.write_text('synthetic content', encoding='utf-8')
stat = source.stat()
plan = RenamePlan('task-one', str(source),
                  SourceFingerprint(stat.st_size, stat.st_mtime_ns),
                  'renamed.txt', str(tmp_path), '.txt')
backend = FileOperationBackend(tmp_path / 'history.jsonl')
lane = ManagedFileOperationLane(backend, capacity=1)
request = FileOperationRequest('apply-one', 'apply', 'batch-one', (plan,))
reservation = lane.reserve(request)
assert reservation is not None
assert source.exists() and not (tmp_path / 'renamed.txt').exists()
assert lane.reserve(FileOperationRequest('other', 'undo', task_ids=('x',))) is None
assert lane.commit(reservation) is True
assert lane.commit(reservation) is False
# Pump to completed; assert one actual move and durable history/task/batch result.
# Reserve and commit undo('task-one'); verify the source bytes return and history
# becomes undone. Compare worker and signal-slot thread IDs to the Qt owner.
```

- [ ] Run the new targeted tests and record the expected missing-contract/behavior
  failure before production implementation. Use the project Windows interpreter,
  isolated temp user dirs, forbidden real socket/keyring callbacks and UPDATE off.

- [ ] Implement request validation before admission: exact kind, nonempty bounded
  operation/task/batch strings, exact tuples of RenamePlan or str, one nonempty
  item collection only, unique task IDs, 1..1000 items. Invalid types/requests raise
  fixed ValueError, not partial admission; reject duplicate live operation_id.
  Frozen plans contain only pure strings and SourceFingerprint; revalidate those
  value types and reasonable bounded strings (4096 chars for paths, 256 chars for
  IDs/target names), not live objects/callables. No user-file I/O during validation.

- [ ] Backend constructor only stores an explicit history path. Lazy construction
  of the one RenameHistory/UndoManager happens in its worker execution, never in
  reserve/commit on Qt. For Apply, derive allowed roots from the accepted plan's
  source parent and target parent, construct Preflight/RenameExecutor using that
  same shared history, and execute exactly one plan with request.batch_id. For
  Undo, use that shared history and the existing RenameExecutor.undo_move boundary;
  no direct os.rename/shutil.move here. No history scan or disk access on Qt.
  A missing undo record yields a fixed failure with the requested task ID, not
  an invented success. Snapshot exact BatchResult fields into immutable outcomes;
  preserve genuine success/recovery/path/task/batch results, including F0 warning.

- [ ] Implement exact identity-based reservation registry and a locked deque of
  committed jobs. reserve/commit/cancel/begin_close require the owning Qt thread;
  counters may be read under the lock from diagnostic/runtime polling. A copied,
  forged, foreign-lane, canceled or already committed reservation is never valid.
  reserve does no scheduling. cancel works only on issued uncommitted reservations.
  Weight is request.item_count; capacity must be exact int 1..1000. Count weight
  from reserve until final Qt delivery exits, including waiting/active/completed
  work; no early capacity release just because disk work or a Future finished.

- [ ] commit marks the exact reservation once and submits at most one worker loop
  to one ThreadPoolExecutor. The loop executes committed jobs FIFO, their items
  in request order, all Apply/Undo serially. Backend execution never runs under
  the lane lock or on Qt. Catch unexpected per-item backend exceptions into a fixed
  `fileops.error.unknownOutcome` failure with `recovery_required=True`, preserving
  later items; do not expose exception text or invent an actual path. This is an
  unconfirmed outcome, not proof that no move happened; consumers must not blindly
  retry it. Expected actual disk outcomes are returned by the existing backend,
  not guessed from exceptions. Worker snapshots no QObject/controller/config state.

- [ ] Queued progress and completion connections must be explicit. Each item
  produces one immutable progress record, and each job one terminal tuple. Track
  both emission exit and queued delivery exit; keep a bounded set of outstanding
  deliveries (at most capacity items plus committed job terminals). Foreign/forged
  or duplicate signal payloads cannot publish/retire a job. Retire matching private
  operation ownership before public terminal notifications, but retain its capacity
  and delivery lifetime through the public callback's exit; a reentrant new job
  cannot be erased by an old terminal callback. No raw error/path logging added.

- [ ] If the initial pool submission fails, remove only unexecuted ownership,
  return False without backend I/O, seal new admission and shut down the unused
  executor. Retire other uncommitted reservations truthfully; no phantom running
  worker, hanging close or success signal. A completion callback exception cannot
  leak delivery ownership; use finally for that narrow delivery cleanup.

- [ ] begin_close is idempotent and quick: refuse new reserve/commit, discard only
  uncommitted reservations, let all committed queued/active disk work and queued
  outcomes finish. Never cancel/kill an accepted move. workers_idle becomes True
  only after worker loop/emit exit and every queued/public delivery has returned;
  keep submitted worker-loop Futures until they are actually done as well as the
  emission/delivery facts. An internal running=False flag just before a function
  returns is not by itself proof of actual loop exit. Prune only completed Futures.
  without Qt event pumping it must stay False. Use nonblocking pool shutdown.

- [ ] Run GREEN focused suites. Cover real serial multi-client operations and
  duplicate reservation/capacity/per-item progress; partial Apply and partial Undo
  with actual files; F0 history-save recovery; missing record; worker exception
  redaction; deterministic blocked-backend Qt responsiveness; wrong-thread admission;
  submit failure; reentrant completed submission; fabricated/duplicated payload;
  begin_close with reserved/waiting/active/delivery work and no event pump. Preserve
  sources and all existing assertions/Golden. Tests must cleanly drain their own
  lane/pool/Qt fixtures even on failure, not disable GC or bypass cleanup.

- [ ] Write full self-review and RED/GREEN commands/raw summaries to
  `.superpowers/sdd/managed-file-operation-lane-report.md`. Root performs focused
  regression and independent scoped spec/quality review, then makes the source
  checkpoint. No writer Git mutations or claim of Batch/Watch integration yet.

## Integration gate after Task 1

The next bounded task will consume these frozen types in Batch/runtime, install
one shared lane before restored execution, durably store row operation ownership
before commit, reconcile interrupted metadata without automatic replay, display
actual recovery outcomes and hold the lane during finite runtime close. Root will
write its full concrete controller/runtime ownership and tests before dispatch.
This standalone lane is not user-visible completion or permission to activate
Watch, alter resource readiness, update screenshots or create another file engine.
