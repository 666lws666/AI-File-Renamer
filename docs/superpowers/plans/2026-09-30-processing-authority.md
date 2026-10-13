# Processing Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.
> Each task is independently reviewed before the next source-writing task.

**Goal:** One process-owned authority fences queued work and cloud attempts across
Batch and Watch while keeping local readiness separate from the selected mode.

**Architecture:** Short in-memory state transitions, immutable work contexts and
one-use attempt receipts. A separate ordered persistence service owns the sole
`processing-intent.json` fact; provider/network/UI integration follows these tasks.

**Tech Stack:** Python standard library, dataclasses, threading Events/Lock,
temporary synthetic JSON files and deterministic pytest synchronization.

## Global Constraints

- Naming mode and processing mode are independent. Do not change saved templates,
  Watch rules, cloud configuration, or the default of genuine legacy installs.
- Selecting LOCAL closes new cloud commitments synchronously, before persistence
  or resource preparation. Preparation failure, cancellation or settings Cancel
  never selects CLOUD. No automatic local-to-cloud fallback.
- A cloud attempt committed before a mode transition may still transmit or finish;
  its result cannot publish in the new generation. A queued task is not committed.
- Never hold the authority lock during I/O, callbacks, Qt signals, waits or model
  operations. Internal Event.set is allowed; external cancellation callbacks are
  not called under the lock. No global network or system-security modifications.
- No real API, credentials, private files, model execution, QML/Golden changes,
  main-checkout writes, merge or push. Only fixed safe errors; no content/path/key
  in identities, receipt repr or diagnostics.
- No second AppConfig mode field or journal. The versioned intent record is the
  only durable processing choice. A completely failed/unfinished write cannot be
  recovered after a crash; tests and documentation must not claim otherwise.

## Task 1: Pure in-memory authority and generation fencing

**Files:** Create `src/core/processing_authority.py` and
`tests/unit/test_processing_authority.py`. No existing caller changes.

**Interfaces:** Public names below are stable for later integration. Exact
implementation helpers remain private, with no dependency on config/providers/Qt.

```python
class ProcessingMode(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"

class LocalReadiness(str, Enum):
    NOT_READY = "not_ready"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"

# Frozen public values: ProcessingSnapshot, WorkContext, ChoiceIntent,
# TransitionReceipt. Errors: ProcessingSuperseded, CloudDispatchBlocked,
# LocalProcessingUnavailable, ProcessingStateError (fixed codes only).
# Internal authority UUID/session ID, generation and revision must not be secrets.

class ProcessingAuthority:
    def __init__(self, *, initial_mode: ProcessingMode,
                 initial_revision: int = 0, startup_error: bool = False): ...
    def snapshot(self) -> ProcessingSnapshot: ...
    def select_local(self) -> TransitionReceipt: ...
    def request_cloud_choice(self) -> ChoiceIntent: ...
    def complete_choice(self, intent: ChoiceIntent, *, persisted: bool) -> bool: ...
    def bind_cloud_engine(self, fingerprint: str) -> ProcessingSnapshot: ...
    def set_local_state(self, expected_generation: int, state: LocalReadiness,
                        *, engine_fingerprint: str | None = None) -> bool: ...
    def capture_work(self, *, engine_fingerprint: str, task_attempt_id: str,
                     task_cancel_event: threading.Event | None = None) -> WorkContext: ...
    def is_current(self, context: WorkContext) -> bool: ...
    def assert_current(self, context: WorkContext) -> None: ...
    def commit_cloud_attempt(self, context: WorkContext, attempt_id: str): ...
    def finish_attempt(self, receipt) -> None: ...
```

State contract:

- Constructor performs no I/O and starts with a fresh session ID. Initial LOCAL
  is NOT_READY, never READY from saved state. `startup_error=True` stays cloud-
  closed even if an invalid caller supplied initial CLOUD; expose a fixed error.
- Fingerprints are exactly 64 lowercase SHA256 hex characters, supplied by later
  request identity construction, never a raw model/path/credential string. The
  authority does not hash file contents. Bind CLOUD identity explicitly; changing
  it invalidates prior work by increasing generation. LOCAL READY requires a
  verified fingerprint supplied only by the future managed runtime coordinator.
  Binding cloud identity while LOCAL cannot change mode or open the cloud gate.
- WorkContext is frozen, bound to this exact authority instance/session, current
  generation/mode/engine, task attempt ID and internal generation cancellation
  Event; optional caller task Event is referenced but never cleared. Capturing
  LOCAL work before READY or with a mismatched identity fails closed. A worker
  cannot refresh an old context into a new one implicitly.
- Each explicit intent increases revision; LOCAL synchronously closes cloud,
  invalidates prior generation and prior outstanding CLOUD intents, then returns
  its ChoiceIntent in the receipt for later persistence. Repeated LOCAL selection
  may produce a new revision/generation; it cannot clear existing failures into
  READY or reopen anything. Snapshot exposes selected mode, generation, revision,
  readiness, persistence status and outstanding committed count.
- A CLOUD choice initially leaves the current gate as-is. It opens only after
  `complete_choice` confirms persistence of that same latest intent; a failed or
  stale completion cannot open. Even a successful LOCAL completion never alters
  readiness. A new mode/engine generation sets the old generation Event once and
  replaces it. Explicit CLOUD selection can recover from startup error only after
  successful persistence.
- Capture and every commit check both generation and task cancellation. Foreign
  or forged contexts and receipts fail closed. Track attempted IDs per live work
  context so a finished attempt ID cannot be reused; bound this to 32 attempts
  per context (well above existing product retry counts), never an unbounded
  session-wide history. Context lifetime owns this ledger, not a global strong
  reference that retains all finished tasks.
- `commit_cloud_attempt` is synchronous in-memory commitment only. It returns a
  private typed receipt once; `finish_attempt` validates owner and consumes it,
  keeping outstanding counts correct even after generation changes. Duplicate
  finish fails safely without underflow. Receipt cannot itself be presented as
  authorization for another call. Last-opener placement is a separate transport
  task, not claimed implemented here.

- [ ] Write RED tests for missing module/API and the transitions below.
- [ ] Implement the smallest single-lock state machine; ordinary immutable data
  validation occurs before lock acquisition. No filesystem or executor imports.
- [ ] Use deterministic Event/barrier tests, not scheduling sleeps:

```python
ctx = authority.capture_work(engine_fingerprint=engine, task_attempt_id="task-1")
receipt = authority.commit_cloud_attempt(ctx, "attempt-1")
transition = authority.select_local()
assert transition.committed_attempts == 1
assert not authority.is_current(ctx)
with pytest.raises(CloudDispatchBlocked):
    authority.commit_cloud_attempt(ctx, "attempt-2")
authority.finish_attempt(receipt)
assert authority.snapshot().committed_attempts == 0
```

Also test opposite ordering LOCAL-before-commit, foreign authority/context,
duplicate attempt and finish, task cancellation, CLOUD->LOCAL->CLOUD, stale cloud
save success after newer LOCAL, failed saves, stale READY, changed engine, nonready
local capture, mode-independent local failure/cancel, invalid fingerprints/types,
32-attempt bound and contexts not retained after caller release. A blocked worker
outside the authority must not block selecting LOCAL from another thread.

- [ ] Run `python -m pytest tests/unit/test_processing_authority.py -q`, report raw
  RED/GREEN and `git diff --check`; commit only these two files, no amend. Report
  `.superpowers/sdd/processing-authority-report.md`. This is not yet a cloud gate.

## Task 2: Ordered sole-authority processing intent persistence

**Files:** Create `src/core/processing_intent_store.py` and
`tests/unit/test_processing_intent_store.py`. Narrow authority corrections only
with a concrete Task 1 contract issue, not unrelated restructuring.

**Interfaces:** `ProcessingIntentStore(path: Path)` has `load()` and
`save(intent: ChoiceIntent)`. `ProcessingIntentWriter(store, authority)` owns one
worker thread and `submit(intent)`, `close()`; close must be bounded and must not
silently drop pending choice notifications. Construction of the writer does not
choose a mode. Load returns a frozen startup record, not a mutable AppConfig.

Record format is exact (no content/provider/model/path):

```json
{"schema_version":1,"revision":7,"mode":"local"}
```

- [ ] RED tests cover `FileNotFoundError` as the only legacy-cloud default,
  corrupt/unreadable/oversized/duplicate-key/nonfinite/future-schema/type-invalid
  record as cloud-closed error; saved LOCAL loads NOT_READY; saved explicit CLOUD
  restores CLOUD. Bound JSON to 4096 bytes and revision to positive signed64-bit;
  reject bool as integer. No auto-rewrite during load.
- [ ] Implement prevalidated candidate + unique same-directory temporary file,
  flush/fsync and atomic replace; clean only the exact temp this operation owns.
  Failed mkdir/write/flush/replace preserves the prior file. Reject symlink,
  reparse or nonregular target/parent substitutions instead of following them.
  No recursive deletion/ACL relaxation; existing settings helpers may be reused
  only if they satisfy the contract without loading real global configuration.
- [ ] The single writer processes monotonically newer revisions and serializes
  saves. An out-of-order lower revision is rejected/skipped without file changes;
  one authority completion follows each submitted choice. No callback under the
  writer queue/store/authority lock. A newer LOCAL invalidates a delayed CLOUD
  callback regardless of its I/O result. Repeated close is safe; failed saves use
  fixed errors and retain the closed runtime state, never roll back to cloud.
- [ ] Deterministic fake-store barriers cover delayed CLOUD then LOCAL, failed
  cloud/local writes, pending close, and ordered durable last revision. Real
  temporary-file tests inject each write failure, preserve old bytes, and reopen
  valid records. Do not create a fake test promising recovery when every write
  failed before a crash.
- [ ] Run both new test files and related config future-schema tests. Report exact
  commands/results to `.superpowers/sdd/processing-intent-store-report.md`, then
  commit scoped files. No Qt or transport wiring yet; integration must consume
  this single persisted fact and must not let general settings reset delete it.
