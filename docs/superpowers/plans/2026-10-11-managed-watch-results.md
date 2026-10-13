# Managed Watch Durable Results Implementation Plan

> For agentic workers: REQUIRED subagent-driven-development. One source writer, root alone Git/independent review/broad Gates.

**Goal:** Persist genuinely delivered managed Watch suggestions/failures with bounded notices and resource-accounted durable backlog.
**Architecture:** Existing schema2 ReviewQueue + small Qt-owner ManagedWatchResults. Extend delivery with exact in-callback one-shot result claim; never invoke legacy analysis.
**Tech Stack:** Python3.14.5 / isolated Qt6.12.0, real Qt/Futures/WatchResourceGuard, local synthetic OS-temp stores.

## Global Constraints

- Source3496d256c3d9d8fe0a9116fb701e6a89d8d87b54, codex/local-privacy-mode at D:/文件AI-AGENT/.worktrees/ai-smart-naming; not main.
- Read docs/superpowers/specs/2026-10-11-managed-watch-results-design.md completely; it defines durable states, authority and accounting.
- ONLY modify src/controllers/managed_watch_analysis.py; ONLY create src/controllers/managed_watch_results.py and tests/integration/test_managed_watch_results.py.
- All existing tests/guard/ReviewQueue/metadata codec/legacy handlers/WatchController/file lane/runtime/service/Provider/config/models/UI/resources/manual/package read-only.
- No second analysis/recapture/source stat/read/write/history/Undo/model/transport. Synthetic queue persistence is allowed. No real network/API/Key/CM/security/Git/Golden/main operations.
- Preserve existing resource/Future/emission/ack/reentrant consumer tails and no-guard exact-count behavior.
- Claims exact, one-shot, owner-thread and confined to actual current public callback; no public receipt tokens or replay permits.
- Persist before publication; failed writes cannot publish success. Fixed errors/notices, no exception/path/content leakage in reason text.
- One immutable contributor snapshot on same exact guard; refresh after successful store write and before actual pending retirement. Temporary conservative overlap is allowed; no undercount/subtraction/legacy source reuse.
- This component does not implement Apply/AutoApply/production activation, observer recovery, runtime or whole-project/native/model Gate. Prior Qt GC crash OPEN.

## Task1 — durable result publication (three files)

### Step1: Genuine RED tests

- [x] Create only tests/integration/test_managed_watch_results.py. Reuse the complete actual lane/pump_until/outcome fixture from tests.integration.test_managed_watch_analysis. Real ReviewQueue and WatchResourceGuard, no fake done objects. Complete initial witness:

~~~python
from pathlib import Path
import pytest
from PySide6.QtCore import QCoreApplication
from src.core.watch_review_queue import ReviewQueue, ReviewItemState
from src.core.watch_resource_guard import WatchResourceGuard, WatchLimits
from tests.integration.test_managed_watch_analysis import lane, pump_until

def test_genuine_result_is_durable_and_pending_survives_ack(lane, tmp_path):
    from src.controllers.managed_watch_results import ManagedWatchResults
    guard = WatchResourceGuard(global_limits=WatchLimits(max_pending=1),
        cooldown_seconds=0)
    queue = ReviewQueue(tmp_path / "review.json")
    results = ManagedWatchResults(queue=queue, resource_guard=guard)
    delivery = lane.make(resource_guard=guard,
        on_resource_blocked=lambda event, reason: None,
        callback=results.consume_result)
    results.attach_delivery(delivery)
    lane.post(delivery)
    assert queue.count() == 0
    pump_until(lambda: delivery.workers_idle)
    item, = results.items()
    assert item.state is ReviewItemState.AWAITING_APPROVAL
    assert item.confidence is None and item.managed_metadata is not None
    reloaded, = ReviewQueue(tmp_path / "review.json").items()
    assert reloaded == item
    assert guard.pending_count("watch") == 1
    denied, receipt = guard.reserve_pending("watch", 0)
    assert not denied.allowed and receipt is None
    assert results.ignore(item.id).state is ReviewItemState.IGNORED
    assert guard.pending_count("watch") == 0
    allowed, receipt = guard.reserve_pending("watch", 0)
    assert allowed.allowed and guard.release_pending(receipt)
    results.begin_close()
~~~

Required bounded additional witnesses:
1. Observe genuine on_result before/after queued ack; not a direct fabricated result. Copy/replay/out-of-callback claims false, genuine one claim true, no second persistence or note. Direct forged ManagedWatchAnalysisResult creates no row/notice/count.
2. Real outcome metadata survives JSON roundtrip; no fields/text/prompts/content/key/outcome object in record. Scope Review First/Auto Apply with no file execution. Existing active source remains unchanged/no duplicate. Stable failure no name/metadata/confidence; raw admission failure no source row, fixed bounded notice.
3. Real source bytes unchanged, forbidden legacy analyze/executor/preflight/source methods not called. Queue persistence is metadata only.
4. Inject os.replace failure on exact synthetic review file: memory/file unchanged, results unavailable/queue_unavailable, no successful changed publication, guard contributor becomes unavailable, delivery fail-safe closes after its actual callback. Callback exception string is not persisted/public reason.
5. Real guard snapshots: successful row counts before pending retirement; inside changed callback count includes saved row + live receipt conservatively; nested admission cannot bypass cap. Ignore/cancel releases only durable backlog and not live receipt. Restored Awaiting/Applying counts before attach/admission.
6. A real finite guard observation thread blocks reading old snapshot; metadata write registers new immutable callback/revision; after release it observes new count or fixed unavailable, never grants using stale old count. Join every thread in finally.
7. restore_interrupted before attachment: Pending/Analyzing cancelled/interrupted, Awaiting/Applying/Applied preserved, zero file execution. Calling after attachment rejected, no replay. Corrupt new ReviewQueue still raises fail-closed.
8. Analysis_failed/timeout/invalid_outcome/local_unavailable/cloud_unavailable count once; duplicate claim count unchanged; resource/source/admission notice no invented inference failure; success one reset. Real guard, instrument wrappers rather than fake guard class.
9. changed callback reenters ignore/close/consume; exact once, no stale autosuccess, actual delivery non-idle through callback. Store owner affinity required; wrong-thread consume/action rejected without mutation.
10. Guard/queue/callback/attach validation occurs before contributor/delivery mutation. Attach one time to same guard and this direct bound consume callback; mismatch rejects fixed invalid_managed_watch_results.

### Step2: Native RED

- [x] Run only the new test file before source edit:
~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/integration/test_managed_watch_results.py; exit $LASTEXITCODE
~~~
Retain native exit/full output/forbidden/thread facts. Missing module is feature-absence RED, not an observed store-loss failure. Fix faulty fixtures without editing existing tests; preserve diagnostic failures.

### Step3: Published-result identity on delivery

- [x] Add _Owner.published_result=None and result_claimed=False. Keep all actual lifetime predicates unchanged. Immediately around the real _consume(result) call in _deliver, seal this exact result to its current _Owner only while in_callback; clear in finally. No publication identity for a fabricated delivery or after consumer return. Result/owner authenticity checks are primitive, not another external binding callback.

Complete method contracts (use the existing _current call in _deliver, do not add readiness/binding calls):

~~~python
    def is_publishing_result(self, result):
        self._require_owner()
        if type(result) is not ManagedWatchAnalysisResult or self._closed:
            return False
        owner = self._owners.get(id(result.event))
        return (owner is not None and owner.event is result.event
                and owner.in_callback and owner.published_result is result
                and self.ingress.is_current(owner.event))

    def claim_result(self, result):
        if not self.is_publishing_result(result):
            return False
        owner = self._owners[id(result.event)]
        if owner.result_claimed:
            return False
        owner.result_claimed = True
        return True
~~~
Initialize/reset result_claimed at publication installation, not on claim replay. Nested Qt duplicate completions cannot install a second publication because existing in_callback/issued identity guards still govern. Do not change _prune/acquire/close/Future/bridge protocol.

### Step4: ManagedWatchResults complete boundary

- [x] Create ManagedWatchResults(QObject) and fixed ManagedWatchResultsError(RuntimeError). Interface:
  - __init__(*,queue:ReviewQueue,resource_guard:WatchResourceGuard,on_changed=None,parent=None)
  - on_changed is an optional synchronous trusted-owner callback; None means no observer. Validate callable before contributor registration. Notify by direct Python invocation, not Signal.emit: Qt signal receiver exceptions do not propagate to the emitter and cannot prove delivery fail-safe closure.
  - attach_delivery(delivery)->None; single assignment before events, same thread/guard and direct bound consume_result; otherwise fixed invalid_managed_watch_results.
  - consume_result(result)->None; owner-thread, open/available, genuinely claim through attached delivery before any disk/state/accounting.
  - items(watch_id=None)->list[ReviewItem], item(item_id)->ReviewItem|None, notice(watch_id)->str
  - ignore(item_id)->ReviewItem|None, cancel_watch(watch_id)->None, restore_interrupted()->int (before attach only), begin_close()->None
  - available,error,workers_idle read-only properties. workers_idle includes actual consumer/changed publication depth, not saved backlog. Closing does not unregister durable counts.

Validate exact ReviewQueue/WatchResourceGuard and optional callable on_changed before mutation. Generate private unique source id; bounds MAX_NOTICES=1000, fixed perwatch latest notice, no result/event/content in notices. Validate watch/item ids exact nonempty str, reject bool/object without arbitrary conversion.

Immutable count publication helper, complete starting implementation:
~~~python
    def _publish_counts(self):
        from types import MappingProxyType
        counts = {}
        for item in self._queue.items(states=ACTIVE_STATES):
            counts[item.watch_id] = counts.get(item.watch_id, 0) + 1
        snapshot = MappingProxyType(counts)
        total = sum(counts.values())
        self._guard.register_pending_source(self._source_id,
            per_watch_counter=lambda watch_id, saved=snapshot: saved.get(watch_id, 0),
            global_counter=lambda saved=total: saved)

    def _fail_store(self):
        self._available = False
        self._error = "queue_unavailable"
        def unavailable(*args):
            raise ValueError("resource_unavailable")
        self._guard.register_pending_source(self._source_id,
            per_watch_counter=unavailable, global_counter=unavailable)
        raise ManagedWatchResultsError("queue_unavailable") from None
~~~
No callback queries the mutable queue, no subtract/clear ledger. Constructor publishes restored ACTIVE_STATES before attachment. All writes belong to this Qt owner; no legacy handler shares the queue in managed runtime. Refused writes keep older conservative snapshot or unavailable, never zero.

consume algorithm, fully defined order:
1. _require_owner; return if closed/unavailable or no delivery or claim false. Increment publication depth in try/finally. Claim is before fallible queue/guard/user callbacks.
2. Exact raw WatchAdmissionFailure: update bounded fixed notice from validated result.failure, invoke on_changed, no fabricated ReviewItem/source I/O/note. Accepted notice codes are invalid_settings/local_unavailable/cloud_unavailable/superseded/global_pending_limit/watch_pending_limit/global_size_limit/watch_size_limit/resource_unavailable/queue_full/analysis_failed.
3. Exact stable event: use only work.source_path, genuine event fingerprint/protected_extension/target_parent/watch_id. Existing active_for_path stays unmodified; no duplicate row. Otherwise add ReviewItem(id="",display_name=os.path.splitext(os.path.basename(source_path))[0],confidence=None):
   - Success: AWAITING_APPROVAL, suggested_name=result.outcome.suggested_name, exact managed_metadata=result.metadata, content_kind=metadata.content_kind,error_category="".
   - Failure: FAILED,suggested_name="",managed_metadata=None,content_kind="",error_category=fixed result.failure.
   Do not synthesize confidence, evidence or file operation. The live delivery already validated outcome/metadata/name/extension; retain exact managed facts, optionally strict codec validation but no relaxed replacements.
4. Queue add/update success -> _publish_counts BEFORE changed. Any queue/snapshot exception -> _fail_store; fixed only. Clear previous notice for this watch only after durable success.
5. If delivery no longer is_publishing_result after a fallible persistence callback, cancel an uncommitted newly-created row with superseded and refresh counts; never mark APPLYING/APPLIED. If this write fails, unavailable. Preserve pre-existing rows.
6. Genuine claimed success note_success once, accounted fixed failure set={analysis_failed,timeout,invalid_outcome,local_unavailable,cloud_unavailable} note_failure once. Resource/source/queue/admission denial no invented inference failure. Do not account when completion lost currentness before publication, do not infer success from mere empty failure. After note clock callbacks, recheck currentness before changed; on withdrawal, cancel newly-created uncommitted row as above. No automatic resume.
7. Invoke the synchronous on_changed callback only after counts/write; exception propagates through delivery fail-safe closure, never stringify it. Always decrement actual depth. A reentrant consume cannot claim twice. An exception from notification after a durable write is not mislabeled as a failed queue write; keep the saved row/counts authoritative.
All fixed result constructors/enum imports come from existing modules, no new protocol/schema.

Metadata action algorithms:
- ignore: only Pending/Analyzing/Awaiting/Failed/Cancelled -> IGNORED via queue.update, publish counts, invoke on_changed; Applied/Applying unchanged. Missing returnsNone.
- cancel_watch: only Pending/Analyzing/Awaiting/Failed -> CANCELLED; each successful update refreshes snapshot before publication; preserve Applying/Applied/Ignored/Cancelled. invoke on_changed once after full action; on failure unavailable.
- restore_interrupted: before attachment only; Pending/Analyzing -> CANCELLED/error_category=interrupted, refresh each write, preserve every other state (including Applying), invoke on_changed once, returns recovered count. No analysis, stat/history or automatic apply.
- begin_close: mark closed, no contributor unregister; preserve backlog/resource protection until runtime guard lifetime ends.
- All metadata actions same affinity/open/available/depth discipline. Fixed queue errors only. No FileOperationLane or old handler construction in this task.

### Step5: GREEN, exact cover, freeze

- [x] New tests then cover once, unchanged other tests:
~~~powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/integration/test_managed_watch_results.py tests/integration/test_managed_watch_resource_delivery.py tests/integration/test_managed_watch_analysis.py tests/integration/test_managed_watch_binding.py tests/integration/test_managed_watch_lifecycle.py tests/unit/test_managed_watch_execution_resource.py tests/unit/test_managed_watch_resource_admission.py tests/unit/test_watch_resource_ownership.py tests/integration/test_review_first.py tests/unit/test_managed_watch_metadata.py; exit $LASTEXITCODE
~~~
Actualnative0/forbidden0/MainThread-only; do not call legacy handler or synthetic API success model-quality proof. Self-review and freeze exact three files. Report .superpowers/sdd/managed-watch-results-report.md full original RED/GREEN/native exits/commands/hashes/limitations. No Git/broad/full/screens. Root fresh scoped review, frozen sequential root full/screens/acceptance then exact local checkpoint.

## Scoped verification completed

Exact three source/test files frozen and independently reviewed: Spec/Quality Approved, no Critical/Important. Root native cover418passed; sequential full4930passed/3existing skips/4warnings; unchanged formal screenshots66passed/1designed skip/86warnings with UPDATE absent; guarded acceptance186/186. Every actual nativeexit0/forbidden0/MainThread-only. Frozen SHA256 independently unchanged after all gates. Original RED/diagnostic evidence retained privately and ignored QA. Minor test-quality callback sentinel enhancement and existing deprecation warnings are backlog, not present product defects. Prior Qt GC crash remains OPEN; this is not production Watch, model quality or final native product approval. No current-source EXE rebuild/main/Golden/push.

## Remaining integration

Managed file approval/AutoApply on the same existing serial file lane, no legacy execution bypass; startup authoritative history/file reconciliation and self-event suppression. Then production runtime injection/resource consent, three-language UI/manual/native clicks, current-source real contained Qwen/no-cloud-fallback and Windows build/artifact/final runtime Gate. This task alone does not deliver Auto Apply or complete the project.
