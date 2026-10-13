# Managed Watch manual file actions implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One fresh sole source writer and one fresh scoped reviewer; root owns Git/public plan and frozen native Gates.

**Goal:** Deliver real Review First per-item and batch Apply plus Undo through the existing shared off-Qt file engine, with durable intent and honest interrupted-state handling.

**Architecture:** A dedicated Qt ManagedWatchFileOperations owns immutable approvals and durable state transitions. It borrows the one application ManagedFileOperationLane; only the existing worker backend moves user files. ReviewQueue schema3 stores explicit metadata and atomic multi-row compare-and-replace; ManagedWatchResults retains count publication and notices.

**Tech Stack:** Windows native Python3.14.5/Qt6.12.0 isolated candidate, PySide6 QObject/direct same-thread public lane notifications, existing atomic JSON stores, real synthetic temp files/history, pytest.

## Global Constraints

- Active worktree D:\\文件AI-AGENT\\.worktrees\\ai-smart-naming, branch codex/local-privacy-mode, source baseline256166139479acb26cf71ad08539f50518134370.
- No real cloud API/Key/Credential Manager/private media; no firewall/ACL/global capture changes.
- No main checkout writes/merge, no formal Golden updates, no push/release/EXE rebuild.
- One source writer; root does not modify product source/tests or run broad tests while writer is active.
- Only FileOperationBackend/RenameExecutor/UndoManager executes user-file I/O, through the same borrowed serial lane; no legacy Watch handler execution or second lane.
- Metadata is not Auto Apply authority; startup never automatically executes or replays intent.
- Exact owner-thread/receipt/publication identities and actual tails, not copied tokens or fake idle flags.
- All errors stored for display are fixed bounded codes, no raw exception strings/prompts/secrets.
- Failed writes leave old authoritative memory/disk; an already moved file with failed completion save remains visibly ambiguous.
- Preserve existing source and test assertions. The only old-test fact changes allowed are ReviewQueue schema3 expectations/future=4 while AutoApplyJournal remains2/future=3.
- Diagnostics/private reports under ignored local-privacy QA or .superpowers/sdd; no tests using real user-data paths.
- Existing native QML GC crash remains open; passing this task does not establish final-runtime stability.

## Task 1: Managed manual actions and durable outcomes (one coherent deliverable)

**Writer file ownership (exact nine paths; amended for demonstrated nested-target failure):**
- Modify src/core/watch_review_queue.py
- Modify src/controllers/managed_watch_results.py
- Modify src/controllers/managed_file_operation_lane.py
- Modify src/services/file_operation_backend.py (only explicit immutable apply roots validation/passing to existing Preflight)
- Create src/controllers/managed_watch_file_operations.py
- Modify tests/unit/test_managed_watch_persistence.py (only version expectations/future-version fixtures, not journal semantics)
- Create tests/unit/test_watch_file_operation_persistence.py
- Create tests/integration/test_managed_watch_file_operations.py
- Modify tests/unit/test_file_operation_backend.py (add exact root-graph validation/containment tests; retain existing tests)
- Private report .superpowers/sdd/managed-watch-file-operations-report.md
- Root owns this public plan/design, private brief/review package/Git; writer must not commit or change other paths.

**Read-first interfaces:**
- ReviewItem frozen fields and ReviewQueue atomic writes in src/core/watch_review_queue.py.
- ManagedWatchResults._write/_publish_counts/_notify owner-only metadata boundary.
- FileOperationRequest(operation_id, kind, batch_id="", plans=(), task_ids=(), allowed_roots=()) and FileOperationOutcome in src/services/file_operation_backend.py. New allowed_roots is exact tuple of at most2000 unique bounded nonempty strings, apply only; Undo rejects nonempty roots. Backend must use supplied roots as-is instead of widening to plan parents; empty legacy roots preserve prior behavior.
- RenamePlan(task_id, source_path, source_fingerprint, target_name, target_parent, extension, batch_id="") in src/core/rename_plan.py; source_fingerprint is SourceFingerprint(size_bytes, mtime_ns).
- ManagedFileOperationLane.reserve(request)/cancel(reservation)/commit(reservation); direct itemCompleted/completed genuine owner dispatch, capacity held through actual terminal callback exit.
- Existing BatchFileOperations behavior is reference only; do not copy synchronous reconcile into the new Watch owner.
- Shared validate_filename(name,original_extension="") rejects path components/extension replacements.
- Design docs/superpowers/specs/2026-10-11-managed-watch-file-operations-design.md contains the full state/error/reentrancy contract.

**Produced public interfaces:**
```python
@dataclass(frozen=True)
class WatchFileOperationIntent:
    version: int
    operation_id: str
    kind: str
    batch_id: str
    source_path: str
    target_path: str

# ReviewItem gains neutral defaults:
# file_operation: WatchFileOperationIntent | None = None
# applied_path: str = ""
# recovery_required: bool = False
# ReviewItemState.UNDONE == "undone"

# ReviewQueue exact expected-object compare-and-replace:
def replace_many(self, changes: tuple[tuple[ReviewItem, ReviewItem], ...]) -> tuple[ReviewItem, ...]:
    ...

# ManagedWatchResults internal atomic transition/count publication:
# Keep callers on owner Qt thread; notify only at the intended final boundary.
def _replace_for_file_operation(self, changes, *, notify=False):
    ...

# Lane exact owner-only actual publication witness:
def is_publishing(self, payload) -> bool:
    ...

class ManagedWatchFileOperations(QObject):
    def __init__(self, *, results, lane, parent=None): ...
    def apply(self, item_ids: tuple[str, ...]) -> bool: ...
    def undo(self, item_id: str) -> bool: ...
    def restore_interrupted(self) -> int: ...
    def begin_close(self) -> None: ...
    # owner-only workers_idle/available/error properties
```
The ellipses above are interface signatures, not permission to ship placeholder bodies. Implement all behavior described by the design.

- [x] **Step 1: Add failing dynamic contract tests before product edits.**
Use tmp_path ReviewQueue and actual ManagedFileOperationLane(FileOperationBackend(tmp_path/"history.json")); create synthetic .txt files, persist AwaitingApproval with real stat fingerprint. Pump QCoreApplication until actual lane and client workers_idle, then assert saved row, history and bytes, not just callback counts. Representative required assertions:
```python
assert actions.apply((first.id, second.id)) is True
# With second's source fingerprint changed, first succeeds and second fails.
assert results.item(first.id).state is ReviewItemState.APPLIED
assert results.item(second.id).state is ReviewItemState.FAILED
# A separate collision test expects successful stem_N.ext, preserving occupied bytes.
assert actions.undo(first.id) is True
# After actual drain:
assert results.item(first.id).state is ReviewItemState.UNDONE
assert original.read_bytes() == original_bytes
assert results.item(first.id).file_operation is None
```
Add independently asserted tests for all design negatives including old schemas, atomic multi-row faults at mkdir/temp/write/fsync/replace, clock-driven replacement conflict, fake public signals, actual shared capacity, notification reentry, interrupted restart zero backend work and real callback/worker threads. Test fixture always drains/retains Qt objects/Futures; no swallowed asserts inside caught callbacks without outer failure/finished witness.

Demonstrated native RED1failed76passed: a valid Project/new.txt under an existing target root outside the source directory was refused because the backend treated the absent Project path as the whole allowed root. Required regression: successful creation/move under the approved existing target root, while supplying an unrelated explicit root refuses the plan with zero user-file mutation. Exact roots and malformed-root cases are dynamically tested. Do not change RenamePlan, RenameExecutor or PreflightService.

- [x] **Step 2: Run and retain genuine RED in the isolated guarded runtime.**
```powershell
& '.\\tests\\screenshots\\qa-current\\local-privacy\\qt612-candidate\\venv\\Scripts\\python.exe' -B '.\\tests\\screenshots\\qa-current\\local-privacy\\qt612-candidate\\run_guarded_pytest.py' tests/unit/test_watch_file_operation_persistence.py tests/integration/test_managed_watch_file_operations.py
exit $LASTEXITCODE
```
Expected absence/contract failure on baseline, not a launcher failure. Save exact command, native exit/output and fixture cleanup; fix invalid test fixtures before editing source and retain all failures.

- [x] **Step 3: Implement the minimal complete contract, then targeted GREEN.**
Pure admission algorithm:
```python
# 1 exact owner/available/open checks + input/value validation + action-depth guard
# 2 gather immutable qualifying ReviewItems and pure plans/expected targets
# 3 lane.reserve -> exact opaque reservation or False (no saved intent)
# 4 results.replace_many(expected -> Applying + intent) -> saved identities/counts
# 5 recheck no close/row mutation, install exact owner, lane.commit
# 6 on precommit failure cancel/rollback only exact own saved candidates
# 7 notify only after commit; committed work cannot be cancelled by UI close
```
Codec and transitions must be real implementations, not these comments. Keep outcomes linked by ID/index/kind/batch/expected path. Apply may accept the shared engine's canonical positive integer auto-counter suffix in the same normalized approved parent with the same protected extension; arbitrary sibling names/parents remain invalid. Undo requires the exact approved original path. A preoccupied target must not be expected to fail: test preserved bytes and valid counted success separately. Consume index before any fallible publication. For valid terminal completion, process missing results then retire exact owner before reentrant observer actions. For malformed/unknown/missing fingerprint/recovery outcomes, keep intent/recovery and fixed error, do not synthesize success.
A pure-code policy for Undo state:
```python
next_state = (ReviewItemState.UNDONE if outcome.success
              else ReviewItemState.APPLIED)
# Only a valid expected-path success with genuine SourceFingerprint can clear intent.
```
After close, no new approvals; actual committed progress is still durably published. Borrowed lane remains open for Batch. Actual publication predicate must be false after notification tail and for copied/replayed/forged envelopes. No manual result signal can mutate rows.
Run focused GREEN and the exact covering set below after self-review. Report all raw summaries/native exit codes/cleanup/forbidden counts, frozen hashes and remaining limits.

- [x] **Step 4: Freeze, scoped independent review and root native Gates.**
Writer reports frozen source/test9hashes and does not alter them while reviewer/root run. Reviewer reads private brief/report/full context delta and all new files, gives independent Spec and Quality decisions, no broader unrelated audit. Root resolves concrete Critical/Important, records Minor backlog. Root then runs:
```powershell
# Cover:
# tests/unit/test_watch_file_operation_persistence.py
# tests/unit/test_managed_watch_persistence.py
# tests/integration/test_managed_watch_file_operations.py
# tests/integration/test_managed_watch_results.py
# tests/integration/test_managed_file_operation_lane.py
# tests/integration/test_managed_batch_file_operations.py
# tests/integration/test_managed_file_operation_runtime.py
# tests/unit/test_file_operation_backend.py
# tests/integration/test_review_first.py
# Full: tests/ --ignore=tests/screenshots
# Screens: tests/screenshots (UPDATE_GOLDENS removed)
# Acceptance: -B qa-current/local-privacy/qt612-candidate/run_guarded_acceptance.py
```
Root corrects any nonexistent covering path before writer dispatch, not by silently omitting tests. Root checks all original native outputs, forbidden=0 and MainThread-only exit, frozen hashes, diffcheck/status, main baseline and unchanged formal Goldens. No final project PASS from this slice.

- [x] **Step 5: Exact root checkpoint and resume remaining integration.**
Root records exact Gate evidence in QA/ledger, marks only this deliverable complete, stages only nine permitted source/test files plus root public plan, standalone cached diffcheck then commits:
```powershell
git commit -m "feat: apply and undo managed watch reviews"
```
No wildcard staging, model runs, main merge, push or history rewriting. Remaining off-Qt recovery/self-event/AutoApply/production runtime/resource consent/UI/native media/manual/package Gates remain honestly open.
