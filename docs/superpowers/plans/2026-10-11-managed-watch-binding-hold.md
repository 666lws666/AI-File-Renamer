# Managed Watch Binding and Paused Holding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Root owns review, final native verification and Git. This is one bounded continuation of the approved managed Watch design, not production activation.

**Goal:** Preserve authentic captured Watch work while resource-paused or still installing, start inference only when the exact live binding is ready, and discard genuinely superseded bindings without retiring a live worker prematurely.

**Architecture:** Add a pure, bounded WatchController binding-state query (STALE/HELD/READY), and an optional read-only start predicate to the reviewed Qt analysis adapter. Identity/authenticity, authority and captured settings stay in the existing ingress/service. Held work remains counted and cancellable; the adapter makes one bounded fair pass per poll so one held watch cannot starve a ready watch. No ResourceGuard acquisition or production composition is added here.

**Tech stack:** Python 3.14.5, isolated official PySide6 6.12.0, existing WatchController/ManagedWatchIngress, real queued Qt delivery and executor Future tests.

## Global constraints

- Source predecessor is e6e6c82aa70acfe4ee9c2f5587094ab7e8bc99a3; actual task baseline including this plan is 9675bd61a0cd2d7ee0646fd4a56e412233fc53d9 on codex/local-privacy-mode. Use the linked checkout, not main.
- Sole source writer owns exactly four paths below; no Git/stage/commit/reset/amend/network/security/model launch by the writer.
- Do not change authority, captured-work identity, ingress source capture, ResourceGuard, stores, Provider, Apply/Undo/file lane, runtime/bootstrap, UI/translations, Golden or any existing configuration/default.
- Root's current delivery source/tests are reviewed; retain their genuine reentrant, tail and cancellation regressions. Do not weaken exact-owner checks, thread affinity, idle predicates, GC, assertions, pixel thresholds or test collection.
- A resource status update replaces the immutable WatchConfig instance but is not a new binding. Ignore status/timestamps/object identity when comparing binding fields; preserve original admission settings/work.
- A pause/edit/remove/stop/close/observer reinstallation invalidates the old incarnation. No recapture or automatic model/cloud fallback.
- Held work owns capacity; it does not own a submitted worker or consume an inference slot.
- Existing admitted-failure events may publish a bounded failure without running inference; do not make resource holding conceal a failure or manufacture stable file metadata.
- This task proves binding/queue behavior with synthetic service outcomes, not real model semantics or a whole Watch/resource/privacy product Gate.

## Task 1: Exact binding snapshot and fair paused holding

### Files

Modify:
- src/controllers/watch_controller.py
- src/controllers/managed_watch_analysis.py
- tests/integration/test_managed_watch_analysis.py

Create:
- tests/integration/test_managed_watch_binding.py

Root alone maintains this plan and private reports.

### Step 1: Write genuine RED

Write named tests before source edits. At minimum:

1. Authentic Active installed binding -> READY; resource_pause replaces config instance -> HELD without invalidating the original admission, cancelling it, replacing its work, or changing captured settings.
2. Only guard-approved explicit resume returns that same installed incarnation to READY; rejected resource resume remains HELD.
3. Real raw event captured before the synthetic stability callback retains its original work; edit/pause/remove/stop/close/reinstall invalidate the old event. A newly authentic event from the new installation is distinct.
4. Same IDs/field copies or event/dataclass replacement are not authentic; unknown types/wrong ingress/wrong incarnation/closed controller are STALE.
5. Config binding key includes ID/source/target/template/recursive/mode, not status/created/updated timestamps. Use real lifecycle operations; do not inject forged counters as proof.
6. An authentic event captured during an actual blocked synthetic observer installation is HELD, then READY only after installation finishes. If that installation is withdrawn, it is STALE. Constructor must be autostart=False and all consumers/predicates installed before start_all.
7. Adapter can_start=False keeps exact owner/work counted, unset cancellation, no submitted Future/service call, finite poll, and pending_limit=1 blocks fresh capture.
8. Changing the read-only gate to True starts exactly that existing work once and publishes exact identity; timer/queued Qt processing, not a direct fake completion.
9. One held event followed by a ready event: ready event executes, held one remains owned; later allowed held work starts once. No unbounded rotate loop or head-of-line starvation.
10. Reentrant start predicate pumping Qt/duplicating the same authentic event cannot replace the owner or double submit. Predicate that closes adapter, pauses/removes watch, changes authority or cancels the incarnation cannot submit stale work.
11. Predicate exception and non-exact-True return hold fail-closed; later normal readiness may resume, no secret fallback or unbounded callback recursion.
12. Pause/authority switch/begin_close while held actually retires queued work and stops owned timers/pool via bounded drain. Running work retains real Future/emission/publication tail rules.
13. Admission failure while held still publishes at most one bounded error, never source I/O/inference.
14. Default omitted can_start preserves all current adapter cases. Non-callable can_start is rejected without constructing orphan timers/executors.

Every constructed delivery/controller must be finally closed/drained and actual threads joined at finite deadlines; no assert True/static pseudo Gates. Use real Qt queued signals/Futures and synthetic files. Reuse existing bounded helpers where useful, but do not copy old fake logic or create a separate analyzer.

### Step 2: Run RED natively

Cwd is the isolated checkout. Use the guarded candidate interpreter:

```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/integration/test_managed_watch_binding.py tests/integration/test_managed_watch_analysis.py
```

Record actual failure summary, native exit, forbidden accesses and real exit threads. The runner isolates user-data, blocks network/native CM, keeps normal GC, disables Golden updates and catches process-exit failures. Missing APIs/constructor behavior should genuinely fail before the implementation.

### Step 3: Implement the bounded queries

Add StableWatchEvent to the existing watch_work import. Add this pure enum near the existing event enums:

```python
class WatchBindingState(Enum):
    STALE = "stale"
    HELD = "held"
    READY = "ready"
```

Add a binding-key helper and public query to WatchController. The following complete starting implementation is intentionally narrow; strengthen it only when genuine negatives reveal a defect:

```python
    @staticmethod
    def _managed_binding_key(config):
        return (config.id, config.source_dir, config.target_dir,
                config.template_id, config.recursive, config.mode)

    def managed_binding_state(self, event) -> WatchBindingState:
        """Pure current installation/policy query; no filesystem or inference."""
        ingress = self._managed_ingress
        if ingress is None or type(event) not in (StableWatchEvent, WatchAdmissionFailure):
            return WatchBindingState.STALE
        # Do not hold the Watch lock while entering ingress/authority callbacks.
        try:
            if not ingress.is_current(event):
                return WatchBindingState.STALE
        except Exception:
            return WatchBindingState.STALE
        admitted = event.admission if type(event) is StableWatchEvent else event
        with self._lock:
            state = self._watches.get(admitted.watch_id)
            if (self._closed or self._stopped or state is None
                    or state.incarnation != admitted.incarnation
                    or state.config.status not in
                        (WatchStatus.ACTIVE, WatchStatus.RESOURCE_PAUSED)
                    or self._managed_binding_key(state.config)
                        != self._managed_binding_key(admitted.watch_config)):
                return WatchBindingState.STALE
            if state.starting:
                return (WatchBindingState.HELD
                        if self._start_reservations.get(admitted.incarnation) == admitted.watch_id
                        else WatchBindingState.STALE)
            installed = state.installation
            if (installed is None or state.observer is not installed.observer
                    or installed.incarnation != admitted.incarnation
                    or self._observer_owners.get(id(installed.observer)) is not installed
                    or installed.teardown_required or installed.teardown_starting
                    or installed.teardown_complete):
                return WatchBindingState.STALE
            if state.config.status is WatchStatus.RESOURCE_PAUSED:
                return WatchBindingState.HELD
            return WatchBindingState.READY
```

The method never returns paths/config/resource authority, invokes arbitrary observer methods, persists state or calls ResourceGuard. Callback currentness is rechecked again by the existing adapter/authority. Do not use immutable config-object identity as the policy/binding test.

### Step 4: Implement optional queue start predicate

ManagedWatchAnalysisDelivery gets optional keyword-only can_start=None. Validate it before constructing the pool/timer; if not None and not callable, raise TypeError with a fixed reason. Retain the value in self._can_start. This is a trusted read-only permission predicate, NOT a ResourceGuard slot acquisition/reservation or capacity counter.

Replace only the scheduling loop in poll with a bounded fair pass. Preserve outer _pumping/prune/close logic and the existing exact owner completion protocol. The full starting scheduling block is:

```python
            running = sum(owner.future is not None or owner.issued is not None
                          for owner in self._owners.values())
            attempts = len(self._queued)
            while self._queued and running < self._max_workers and attempts:
                attempts -= 1
                owner = self._queued.pop(0)
                current = self._current(owner.event)
                # Fallible/reentrant callbacks can close this adapter or retire
                # an unstarted owner. Never submit an orphan continuation.
                if self._closed or self._owners.get(id(owner.event)) is not owner:
                    continue
                if not current:
                    self.ingress.retire(owner.event)
                    self._owners.pop(id(owner.event), None)
                    continue
                if self._can_start is not None:
                    try:
                        allowed = self._can_start(owner.event) is True
                    except Exception:
                        allowed = False
                    if self._closed or self._owners.get(id(owner.event)) is not owner:
                        continue
                    current = self._current(owner.event)
                    if self._closed or self._owners.get(id(owner.event)) is not owner:
                        continue
                    if not current:
                        self.ingress.retire(owner.event)
                        self._owners.pop(id(owner.event), None)
                        continue
                    if not allowed:
                        self._queued.append(owner)
                        continue
                try:
                    owner.future = self._pool.submit(self._run, self._service, owner)
                except Exception:
                    completion = _Completion(owner, failure="analysis_failed")
                    with owner.lock:
                        owner.issued = completion
                    owner.bridge_done.set()
                    self._completed.emit(completion)
                else:
                    owner.future.add_done_callback(
                        lambda done, owned=owner: self._emit(owned, done))
                running += 1
```

Expected composition in tests, not production activation:

```python
is_binding_current=lambda event: controller.managed_binding_state(event) is not WatchBindingState.STALE
can_start=lambda event: controller.managed_binding_state(event) is WatchBindingState.READY
```

Construct controller with autostart=False, install the shared ingress/all consumers, then start_all. No new threads or independent engine; no data-path reads on Qt. A held event remains the same owner in the bounded queue. Each poll examines at most the entry queue length, and does not endlessly spin a held first entry.

### Step 5: GREEN, review and root checkpoint

Writer runs exact covering files:

```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/integration/test_managed_watch_binding.py tests/integration/test_managed_watch_analysis.py tests/unit/test_managed_watch_admission.py tests/integration/test_managed_watch_lifecycle.py tests/unit/test_watch_controller.py tests/unit/test_watch_integrity.py tests/unit/test_watch_edit.py
```

Writer reports exact changed paths, real RED/GREEN commands and native summaries in .superpowers/sdd/managed-watch-binding-report.md, then freezes all four paths. Root creates the complete scoped diff, independent review and frozen-file native covering/full/screenshot/acceptance Gates before exact checkpoint. Shared project venv remains untouched; use candidate Qt6.12. No ordinary source edit during root's all-suite process.

## Explicit next-stage boundary

ResourceGuard's already-owned pending threshold/recovery and real slot acquisition/release are not implemented here. A predicate True is not a resource permit. Production Watch remains unavailable until those controls, durable results, accepted file operations/self-event ownership and bootstrap close graph are separately integrated and verified. This task's default predicate cannot be used as a claim of global Batch/Watch concurrency control. Resources UI/download/actual model/manual/package Gates also remain unfinished.

## Completed bounded task — root native verification

All task steps above are complete for binding/holding only. The supplied code is the historical starting sketch, not a claim that its original scheduling boundary was correct. Genuine negatives revealed two defects and the final implementation strengthens that sketch:

- Closing inside a predicate could leave a popped-but-unsubmitted owner unretired. Close now retires exact stable owners only without a Future, issued completion or active callback; submitted/issued/callback tails retain real ownership.
- READY permission observed before a later reentrant binding query could survive an actual ResourcePaused transition. A bounded final readiness observation now occurs after that query, followed only by exact-owner/closed and sealed ingress authentication/authority/cancellation checks. No alternating unbounded callbacks, resource lease or recapture was added.

Retained genuine writer RED evidence: initial clean RED 45 failed/60 passed; starting-sketch close defect 1 failed/104 passed plus one teardown error; additional close boundaries 3 failed/3 passed plus three teardown errors; R1 readiness boundary 12 failed/112 deselected. Preliminary fixture cleanup errors were corrected before source changes and remain recorded privately. No failed run is relabeled a pass. Independent task review's superseding R1 assessment approves both spec compliance and code quality; its earlier approval/failure drafts remain historical.

Root verified the final four source/test SHA256 values before native runs and made no source edits during regression. Isolated Python3.14.5/official Qt6.12.0 was used; shared project venv and main checkout remained unchanged. Exact actual results:

- Seven-file covering: **269 passed, 3 existing warnings in 4.30s**, native exit0.
- Complete non-screenshot suite: **4644 passed, 3 existing skips, 4 existing warnings in 93.91s**, native exit0.
- Complete committed-Golden comparison suite with UPDATE disabled: **66 passed, 1 designed update-mode skip, 86 existing Pillow deprecation warnings in 45.50s**, native exit0.
- Guarded acceptance_test.py: **186/186 passed**, native exit0.
- Every run reported forbidden network/real-credential accesses0 and actual atexit threads containing MainThread only. Warnings were retained rather than suppressed; these runs are not described as warning-clean.

The tests use synthetic service outcomes and real Qt/Future/observer ownership, not actual model semantics. This task did not rebuild a new release EXE, activate production Watch, change existing configuration/defaults, alter UI/Golden/assertions/tolerances, access real API/Key/Credential Manager, change firewall, merge main or push. Next stage remains explicit execution resource permits, durable result/file-operation composition and production integration, followed by resources/UI/model/manual/package gates.
