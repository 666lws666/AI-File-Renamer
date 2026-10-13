# Managed Watch Execution Resource Integration Plan

> REQUIRED: subagent-driven-development, one source writer; root alone Git/review/broad native Gates.

**Goal:** Extend the already-reviewed ingress/delivery to own genuine execution resources through actual worker/Qt/publication tails.
**Architecture:** Same ingress owner and same shared guard, optional old standalone path, exact stable fingerprint sizes, finite fair delivery queue.
**Tech Stack:** Python3.14.5 + isolated Qt6.12.0 guarded native tests.

## Global Constraints

- Source dependency54d42123f3ac4c8a5724d134bdbf68850b321062. Branch codex/local-privacy-mode in D:/文件AI-AGENT/.worktrees/ai-smart-naming, not main; plan commit supplied at dispatch.
- Read docs/superpowers/specs/2026-10-11-managed-watch-execution-resource-design.md in full.
- ONLY modify src/controllers/managed_watch_ingress.py and src/controllers/managed_watch_analysis.py; ONLY create tests/unit/test_managed_watch_execution_resource.py and tests/integration/test_managed_watch_resource_delivery.py.
- Existing tests/guard/WatchController/service/Provider/settings/runtime/QML/resources/UI/model/manual/package/file lanes are read-only. No source I/O beyond existing worker fingerprint, no inference/key/network/CM/security/Git/Golden/main operation.
- resource_guard=None preserves old delivery behavior/constructor and old exact-count readiness tests; it is not resource-protected production permission. Supplied guard must be exact WatchResourceGuard. Guarded delivery requires callable on_resource_blocked; validate before pool/timer.
- Admission uses genuine pending receipt; execution uses authentic StableWatchEvent fingerprint size, never admission0 or caller-supplied size/token.
- Guard observation outside ingress lock; canonical primitive release only under lock. Actual acquisition/capture/post/public-consumer tails prevent false idle. False release retains exact owner.
- No receipt exposed to public caller. Legacy watch-id release cannot release owned execution. No ingress contributor double-registration.
- Transient hold reasons: global_pending_limit,watch_pending_limit,global_concurrency_limit,watch_concurrency_limit,manually_paused,failure_backoff,cooldown,resource_unavailable. Terminal size reasons: global_size_limit,watch_size_limit. Invalid/lost owner -> fixed analysis_failed/superseded with no body, not infinite retry.
- No automatic observer resume or failure-count accounting, production activation or whole-project/native-stability claim. Prior Qt GC crash remains open.

## Task1 — owned execution integration (four files, one reviewed task)

### Step1 — write genuine RED tests first

- [x] New unit tests reuse tests.unit.test_managed_watch_admission lane/capture; new integration tests reuse tests.integration.test_managed_watch_analysis lane/pump_until/outcome/fingerprint. Existing files remain untouched. Complete integration witness:

~~~python
from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from tests.integration.test_managed_watch_analysis import lane, pump_until, outcome

def test_real_worker_receipt_survives_close_until_actual_tail(lane):
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1,
        max_concurrent_analysis=1), cooldown_seconds=0)
    entered, release = lane.block()
    blocked = []
    owner = lane.make(resource_guard=guard,
        on_resource_blocked=lambda event, reason: blocked.append((event, reason)))
    admission, _ = lane.post(owner)
    pump_until(entered.is_set)
    try:
        assert guard.pending_count("watch") == 1
        assert guard.active_analyses("watch") == 1
        owner.begin_close()
        assert not owner.workers_idle
        assert not owner.drain(__import__("time").monotonic() + .03)
        assert guard.active_analyses("watch") == 1
        assert guard.pending_count("watch") == 1
    finally:
        release.set()
    assert owner.drain(__import__("time").monotonic() + 2)
    assert guard.active_analyses("watch") == guard.pending_count("watch") == 0
    assert not lane.seen
~~~

Use named bounded witnesses, not duplicate broad test matrices. Required additional proof:
- Real shared guard limit1 across two delivery owners, no second body until actual first tail; queue fairness held vs ready watch.
- Owned pending at cap can execute its own receipt; callback error/invalid constructor fails before pool/timer.
- Clock/contributor reentry query from actual finite thread; close/cancel during actual resource observation keeps ingress/delivery non-idle until return.
- Manual pause/backoff/cooldown/temporary unavailable holds exact original work; after explicit guard state change, starts same work without recapture. Observer does not get resumed by this task.
- Guard callback changes readiness/binding/authority/cancels/closes; final trusted refresh/sealed check blocks withdrawn body. Public blocked observer may reenter/duplicate/poll/close/raise; actual owner lives through callback.
- Actual stable oversize (not giant allocation) no run_prepared; resource notice does not stat/extract/start predicate/worker or create outcome.
- Real blocked worker, Future.done+before/after emission, queued acknowledgement, nested on_result consumer, submission exception: active execution and pending survive until exact existing tail boundary.
- Forge/copy/duplicate events cannot release/acquire other's receipt; repeated release false; cleanup of retired event releases its own stored receipt; old legacy release isolation.
- No real model/key/network. Genuine threads/Futures/Qt queue joined; no pretend done objects.

### Step2 — native RED

- [x] Before source edits run only both new files:

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_managed_watch_execution_resource.py tests/integration/test_managed_watch_resource_delivery.py; exit $LASTEXITCODE
~~~

Feature-absence RED is not called observed tail failure. Retain any failing fixture/cleanup evidence and correct it before interpreting RED. Use scoped require_escalated on default setup-refresh launch failure; no runner changes.

### Step3 — implement ingress exact execution protocol

- [x] Add ResourceDecision/R_INVALID_OWNER imports, private owner execution_token=None and resource_call=False. Locked pruning additionally requires not resource_call and execution_token is None, independently of the guard ledger. No caller token/size accepts. Complete starting methods (negative tests may require strengthening):

~~~python
    def try_acquire_execution(self, event):
        if type(event) is not StableWatchEvent:
            return ResourceDecision(False, R_INVALID_OWNER)
        with self._lock:
            pair = self._find_locked(event)
            if pair is None or not self._current_locked(pair[1]):
                return ResourceDecision(False, R_INVALID_OWNER)
            guard = self._resource_guard
            if guard is None:
                return ResourceDecision(False, R_RESOURCE_UNAVAILABLE)
            key, owner = pair
            if (owner.resource_call or owner.execution_token is not None
                    or owner.pending_token is None):
                return ResourceDecision(False, R_INVALID_OWNER)
            owner.resource_call = True
            pending = owner.pending_token
        decision, receipt = ResourceDecision(False, R_RESOURCE_UNAVAILABLE), None
        try:
            decision, receipt = guard.try_acquire_owned_analysis(
                pending, event.fingerprint.size_bytes)
        finally:
            with self._lock:
                # Preserve actual receipt before observing reentrant withdrawal.
                if receipt is not None:
                    owner.execution_token = receipt
                owner.resource_call = False
                if not self._current_locked(owner):
                    owner.retired = True
                    owner.cancel.set()
                    if (owner.execution_token is not None
                            and guard.release_owned_analysis(owner.execution_token)):
                        owner.execution_token = None
                    decision = ResourceDecision(False, R_INVALID_OWNER)
                self._prune_locked(key, owner)
        return decision

    def release_execution(self, event):
        with self._lock:
            pair = self._issued.get(id(event))
            if pair is None or pair[1].event is not event:
                return False
            key, owner = pair
            receipt = owner.execution_token
            if receipt is None or not self._resource_guard.release_owned_analysis(receipt):
                return False
            owner.execution_token = None
            self._prune_locked(key, owner)
            return True

    def has_execution(self, event):
        with self._lock:
            pair = self._issued.get(id(event))
            return (pair is not None and pair[1].event is event
                    and pair[1].execution_token is not None)
~~~

Keep pending/capture/post/notice/identity semantics unchanged. release/has_execution accept exact retired issued identity solely for cleanup; no authority freshness needed there. has_execution is ownership observation, never permission. No guard returns unavailable, not a protected permit. Guarded acquire may never return allowed without an actual stored receipt. A denied decision after reentrant withdrawal may still own an execution if primitive cleanup refused; delivery must query genuine retained ownership and retry cleanup at a finite poll boundary, not discard it or submit a body. Any stale/close reentrant path must preserve false-release owner rather than report false idle.

### Step4 — integrate guarded delivery

- [x] Constructor extends resource_guard=None,on_resource_blocked=None; validate exact guard and callback before pool/timer. Pass same guard into ingress. Add delivery owner execution_owned=False,admitting=False,blocked_reason="". Do not change no-guard scheduling branch or existing test expectations.

Keep existing _current/_can_start behavior. In guarded scheduling, protect an actual admitting tail around resource observation and blocked notification:
1. Existing authentication/readiness before resource acquisition.
2. try_acquire_execution(event); recheck exact delivery owner/open/ingress after external callbacks.
3. Allowed: mark genuine execution_owned. Refresh _current binding, then final trusted can_start (exactTrue). After that only sealed owner/open/ingress current facts. Held -> release only execution and requeue same owner; stale/closed -> release and retire unsubmitted after admitting tail.
4. Transient denied: retain same owner/work, notify observer only if fixed reason changed; after actual observer tail recheck sealed owner/open and hold or retire. Finite attempts pass; not busy-loop or recapture. No notification grants permission.
5. Size/lost-owner terminal failure: issue exact canonical queued completion with fixed failure, no body. No submitted Future; actual emit tail bridge_done only after emission returns, then real queued ack/public-consumer tail.
6. When admitted, preserve existing submit exception + completion protocol; an exact execution lease is held even if submit fails until queued ack.

Factor the actual owner release/retirement helpers; do not copy a second full poll scheduling loop. _prune requires existing acked/!in_callback/bridge_done/Future.done plus !admitting; release owned execution first and keep owner on false release, then ingress retirement. begin_close excludes genuinely admitting owners as well as callback/worker owners; finally retires closed/unsubmitted owned work after actual tail, not by queue position. pending/idle no premature zero.

Raw WatchAdmissionFailure resource reasons/queue_full are preserved in the fixed safe allowlist; neither start gate nor source I/O is invoked. Completion allowlist adds the two terminal size codes; no arbitrary reason or exception/path text. Result validation/source fingerprint/outcome coverage/extension/thread affinity remains unchanged. No note_failure/note_success added here.

### Step5 — GREEN, exact cover, freeze

- [x] Focused two new files then exact cover once:

~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_managed_watch_execution_resource.py tests/integration/test_managed_watch_resource_delivery.py tests/unit/test_managed_watch_resource_admission.py tests/unit/test_managed_watch_admission.py tests/unit/test_watch_resource_ownership.py tests/unit/test_watch_resource_guard.py tests/integration/test_managed_watch_analysis.py tests/integration/test_managed_watch_binding.py tests/integration/test_managed_watch_lifecycle.py; exit $LASTEXITCODE
~~~

All actual native0/forbidden0/MainThread-only. Implementer no broad/full/screens/model/UI/Git. Self-review and freeze four files; report .superpowers/sdd/managed-watch-execution-resource-report.md with full original RED/GREEN/cover outputs and hashes. Root fresh scoped review then frozen sequential full/screens/acceptance and exact local checkpoint.

## Remaining release sequence

Task1 verification: writer35focused/412cover passed, genuine feature-absence RED and cleanup-order RED preserved. Independent scoped review: Spec compliant / Quality Approved, no Critical/Important finding. Root sequential frozen cover412passed, full4900passed/3existing skips, screenshots66passed/1designed skip with UPDATE removed, isolated acceptance186/186. Each actual nativeexit0/forbidden0/MainThread-only; frozen4hashes unchanged, official screenshot tree and main unchanged. Existing warnings remain backlog. Prior QML GC native crash remains OPEN; this task does not establish production activation/native stability/current-source packaging or model quality. Root exact local checkpoint only; no main merge/push.

This task completes resource-owning delivery only. Next integrate durable managed Review/AutoApply using the same shared file-operation lane and self-event suppression, without invoking old duplicate legacy analysis/guard path. Then runtime Watch injection and local resource-consent manager; three-language UI/manual + native real-click evidence; real contained Qwen mixed corpus/no-cloud-fallback tests; current-source Windows build/isolated native artifact Gate and bounded final branch review. No whole-project completion, main merge or release from a passing component.
