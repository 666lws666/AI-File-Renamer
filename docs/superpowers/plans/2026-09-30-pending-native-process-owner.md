# Pending Native Process Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Preserve exact child/Job ownership when bounded cleanup cannot confirm
termination or close a handle, so product code can safely retry cleanup.

**Architecture:** Extend the one canonical native runner with a retained owner;
normal successful return and existing positional ProcessResult construction stay
compatible. No second process launcher, PID-based reopening or reaper service.

**Tech Stack:** Existing typed Win32 bindings, pytest native fault injection and
harmless temporary child processes. No real model or external network activity.

## Global Constraints

- Keep creation-time nonbreakaway kill-on-close Job, suspended launch, exact token
  verification before resume, zero-capability policy, pipe bounds and validation.
- Cleanup confirmation requires BOTH owned Job ActiveProcesses zero and owned root
  signalled. Closing a Job is a kill backstop, not proof that the tree has exited.
- Retain exact handles on uncertain cleanup; never reopen by PID/name, blindly
  delete stages/profiles, change security policy, or report pending as complete.
- Do not log arguments/environment/stdout/stderr/private paths. No cloud/API/key/
  credentials/private sample, model launch, administrator actions, QML/Golden,
  main-checkout changes, merge or push.

## Task 1: Retryable process ownership

**Files:** Modify `src/services/local_ai/native/process.py` and
`tests/unit/test_local_probe_process.py`; create
`tests/unit/test_pending_local_process.py`. Existing diagnostic imports alias the
canonical product module. No diagnostic orchestrator or security module rewrite.

**Interfaces:** Keep ProcessResult's existing positional fields unchanged; append
the new fields with safe defaults. stdout/stderr repr may be hidden without
changing their values or accessibility.

```python
@dataclass(frozen=True)
class ProcessCleanupResult:
    tree_exited: bool
    handles_closed: bool
    # fixed error stage/code fields only; no handles, paths or stream content

class PendingProcessOwner:
    def retry_reap(self, *, deadline: float) -> ProcessCleanupResult: ...

# Append to ProcessResult:
# pending_owner: PendingProcessOwner | None = field(default=None, repr=False)
# stop_reason: str | None = None
```

An incomplete exceptional unwind must also hand the owner to the caller. Expose
a fixed-message `ProcessOwnershipInterrupted(BaseException)` with repr-hidden
`pending_owner` and a safe original category (e.g. `keyboard_interrupt`), not the
raw exception text. Preserve the original interruption's normal behavior when
cleanup actually completes. No arbitrary exception setattr/deepcopy trick.

- [ ] RED tests demonstrate current cleanup-incomplete result has no retry owner,
  failed CloseHandle is incorrectly ignored, and pending BaseException loses
  ownership. Use existing fake/native seams and bounded synthetic processes.
- [ ] Factor handle acquisition/close accounting into one owner, without changing
  creation and token logic. Each successful acquisition is adopted immediately,
  including partial CreateProcess failure. A handle is removed only after a
  confirmed successful close; failed close retains its identity for retry.
- [ ] On normal complete cleanup, return no pending owner, cleanup_complete=True.
  On failed termination/query/wait, retain root/Job and necessary handles; status
  remains cleanup_incomplete, pending_owner is live and stop_reason retains the
  pre-cleanup cancelled/timeout/output_limit/launch_error/completed outcome.
  Do not discard any handle merely to make the count look clean.
- [ ] A retry invokes the existing exact Job/root termination and confirmation
  using retained handles, independent of the original cancellation event. It has
  a fresh finite monotonic absolute deadline, no background thread and no I/O
  other than owned native cleanup. Reject invalid/nonfinite/bool deadlines using
  fixed errors; an expired budget must not start an unbounded polling loop.
- [ ] Close remaining handles only once tree exit is confirmed. Retry partial
  CloseHandle failure later without re-closing known successfully closed handles.
  Preserve a confirmed tree_exited fact even if handles_closed remains false.
  Repeated retry after fully complete is idempotent. Concurrency must not race
  two retry callers into double-close; serialize owner cleanup only, not any
  unrelated authority/UI lock.
- [ ] Delete initialized attribute-list metadata exactly once after launch use
  finishes. It must not keep referencing already-freed storage; this metadata
  cleanup is distinct from owned process/Job handle cleanup. Partial failures
  before child creation still retain/retry any handles that failed close.
- [ ] Any BaseException during launch or cleanup must not discard unresolved
  ownership; propagate the fixed owner-carrying interrupt when needed. Do not let
  errors while draining finite stdout after confirmed exit reopen a false tree-
  alive state. Raw streams never appear in the interrupt or repr.

Tests include:

```python
assert result.status == "cleanup_incomplete"
assert result.stop_reason == "cancelled"
owner = result.pending_owner
assert owner is not None
# Fault removed, same retained native handles used, never OpenProcess(PID).
cleanup = owner.retry_reap(deadline=clock() + 1.0)
assert cleanup.tree_exited and cleanup.handles_closed
assert owner.retry_reap(deadline=clock() + 1.0) == cleanup
```

Also cover failed Job termination/query/root wait then success; one failed handle
close then success; partial creation and pre-child acquisition; original cancel
still set during successful retry; preserved timeout/output-limit reasons;
BaseException handoff and normal fully-clean interruption; no duplicate closes;
safe repr/errors; no success with pending owner. Update the existing deliberately
unconfirmed-cleanup test to actually finish its new owner in teardown so the test
suite does not leave owned processes/handles behind. Keep all old launch/security
and parent-exit-kills-child assertions.

- [ ] Run new tests plus existing process/security/hello/appcontainer/access/
  contained-inference tests. Report exact RED/GREEN/commands to
  `.superpowers/sdd/pending-native-process-owner-report.md`; `git diff --check`,
  then scoped new commit, no amend. Independent review precedes any product
  coordinator or real-model execution using this owner.
