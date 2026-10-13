# Managed Watch owned resource receipts — implementation plan
Approved autonomous product scope. Actual clean dependency baseline: 0580f686629b0c76718d3f7b89b4907e378b03aa, branch codex/local-privacy-mode. This plan is not product PASS. One implementer, root alone Git.

## Why this task is necessary
Managed Watch ingress/delivery already preserves sealed events, binding/incarnation and actual callback tails. The current resource guard has legacy counters and string-based releases only. Equal-to-capacity recovery treats an existing item like a fresh item; external callbacks run under a nonreentrant lock. A trusted readiness bool cannot be an owned execution receipt. Actual production Watch activation remains intentionally absent.

## Options chosen
Reuse existing WatchResourceGuard with additive exact receipts; no second policy guard or caller bypass bool. Split pure guard from ingress/delivery wiring: this task changes only guard + new targeted unit tests. This limits review while preserving legacy APIs. Source/task integration must separately connect genuine ingress ownership before production activation.

## Proposed exact task scope
- Modify src/core/watch_resource_guard.py.
- Add tests/unit/test_watch_resource_ownership.py.
- Existing tests/unit/test_watch_resource_guard.py and tests/integration/test_watch_resource_guard_pipeline.py are covering regression, not editable.
- Root alone plan/private ledger/Git. No config, schema, settings defaults, legacy handler, ingress/delivery, cloud/local lanes, file operations, QML/model/API/Golden/main changes.

## Public receipt contract
reserve_pending(watch_id,size_bytes) -> (ResourceDecision,pending_token|None).
release_pending(pending_token) -> bool.
try_acquire_owned_analysis(pending_token,size_bytes) -> (ResourceDecision,execution_token|None).
can_acquire_owned_analysis(pending_token,size_bytes) -> ResourceDecision.
release_owned_analysis(execution_token) -> bool.
recover_owned(pending_token) -> bool.

Only exact object tokens created by this guard; no public token class constructor, bool ownership, dictionary snapshot, task id or subtract-one API. Per guard pending-token->watch-id ledger; execution-token->pending-token ledger. Exact type checks before dict access avoid arbitrary __hash__/__eq__. Foreign/retired/duplicate tokens denied fixed invalid-resource-owner reason. One pending token at most one active execution; release_pending refuses a live execution, preserving receipt until actual consumer finalization. Legacy release_analysis(watch_id) affects only legacy counters, never managed executions. active_analyses returns the sum. Managed pending totals add to registered/legacy external counts without double registration of the same ledger.

## Admission vs execution
Reservation is ownership of an admitted input, NOT permission to read/analyze/send/resume. It checks exact valid id/size, global+per-watch pending capacity strictly BEFORE increment and file-size hard limits. It does not consume an analysis slot. To preserve bounded held inputs during resource pause, backoff/manual/cooldown/concurrency do NOT block receipt admission; only queue/size safety does. Existing observer/incarnation/mode policy outside this guard still determines whether an event may enter. This task cannot initiate any event/observer work.
Fresh reservation at total >= cap is denied. Limit trip retains existing fixed reason + cooldown semantics.
Execution for a genuine pending owner can proceed at total==cap, but total>cap denies (e.g. limits lowered or external pending changed). All manual/backoff/cooldown/size/concurrent constraints still apply, global limits before per-watch. Existing legacy try_acquire/can_analyze retains >= semantics; it cannot impersonate managed work.
Recovery uses genuine live non-executing receipt, normal current constraints, and == rule; no minting owner or clearing live backoff/manual/cooldown to force success. No observer resume/activation or auto pipeline is done by guard.

## Callback-safe observation and commit
Clock and pending contributors execute OUTSIDE lock for every API, including legacy decisions/count queries/note_failure/recovery. Lock protects only exact primitive ledgers, limits, revisions and backoff/cooldown state.
Finite snapshot protocol: copy contributor references/seen-watches/registry revision under lock; evaluate exact nonnegative int counts and finite int/float clock outside; reacquire lock, verify observation revision, commit/check actual owned ledgers and current limits. Bounded retry (at most3), then fixed resource-unavailable decision. Registration/unregistration/setters/new seen watch invalidate snapshot. Constructor copies per-watch limits to avoid alias mutation.
No callback-defined code or truthiness/hashing/custom numeric comparison under lock. Exact counter bool/negative/NaN/non-int invalid; clock bool/NaN/inf/non-number invalid. Throwing callback and unstable revision fail closed; raw exception text never exposed. Count query raises fixed ValueError rather than false zero; boolean APIs returnFalse; decision APIs deny.
External counters are a consistent sampled input, not arbitrary-source linearizability proof; only managed admission/execution owns exact concurrent reservations. Tests must not claim all producer queues are frozen under guard lock.
Validate WatchLimits optional exact positive ints, watch id exact nonempty str, size exact nonnegative int. Accept previous valid None/positive inputs; no runtime defaults/schema changes. Backoff constructor values finite and max failures exactpositive; invalid raises fixed ValueError. Avoid falsey clock fallback.
note_failure now reads safe clock outside lock then updates once; preserve existing valid backoff policy and base-duration behavior. If arithmetic cannot produce a finite deadline, fail closed with a fixed ValueError before publishing partial count/deadline state; do not introduce a new configured cap or silently shorten protection. General future facade still owns once-per-operation count; no handler change here.

## Test-first witnesses / acceptance
1. Fresh pending limits1, two concurrent actual threads exactly one receipt; foreign/repeated release zeroeffect.
2. At total1 ==limit1 genuine execution succeeds; fresh second reservation denied; lower cap/external growth >cap denies genuine exec after cooldown; restore permits it.
3. global/per-watch limits+legacy counts aggregate correctly; two independent watches and sources/registration order unchanged.
4. Same pending cannot execute twice; live pending cannotrelease; releasing execution doesn'trelease pending; legacy release cannotfree managed; foreign execution cannot free any.
5. Manual/backoff/cooldown active/size still blockexecution/recovery; fresh reservation canbe held duringpause but grants no slot. ==recover worksafteractualcooldown, no bypasstoken.
6. Real thread counter/clock callback reenters active_analyses or registration without lockdeadlock; revision changes retry3thenfixeddeny. No invented clock/pass to avoid hanging.
7. Malformed/throwing counters/clock/limit/id/size failclosed with fixed messages and zeroownedchanges. Guard no I/O/content/path/key payload.
8. Existing unit/pipeline/safety/review/autoapply suites allpass under actual native guarded candidate; native exit0,forbidden0,actual atexitMainThreadonly. Correct RED oldguard missing receipt API establishes feature absence; genuine callback deadlock RED use finite actual thread and cleanup-safe orchestration; do not leave actual locked daemon in process or weaken old tests to pass.
9. Freeze scoped diff; independent spec/quality reviewer; root full tests/screens/acceptance; commitexact files only. No actual network/model/runtime or whole Watch PASS from this pureguard task.

## Follow-up NOT done here
Ingress connects pending reservation before sealed capture and retires only actual capture/post/delivery tails. Delivery acquires exact execution after arbitrary readiness callback and retains Future/bridge/ack/public tails. Durable Review/AutoApply facade, serial file lane/selfevents, controlled ResourcePaused recovery and production runtime composition. Local resources/download consent/offline/trilingual UI/manual/package/real model Gates remain unfinished.

## Ordered implementation and verification

- [x] Step1: New receipt tests first: finite exact owner/capacity/legacy separation/held admission cases; old implementation must fail honestly for missing functionality. Do not claim a missing-method RED is a successful end-to-end regression witness.
- [x] Step2: Implement additive pending/execution ledger and <= owner execution semantics, keeping legacy >= decisions. Validate/reject inputs before ledger changes. Focused GREEN.
- [x] Step3: Move contributor/clock observation outside lock using bounded revision resnapshot; commit only primitive state under lock. Reentrant callback test must be cleanup-safe: callback may start a second actual querying thread, finite-wait it, and fail if it cannot query before returning; always allow release and join after failure, no stranded deadlock/daemon.
- [x] Step4: Preserve old aggregation, limit precedence, size checks, cooldown/backoff/base duration and legacy separate release. Add malformed/reentrant/revision/concurrent negative tests and overflow zero-partial-state safety test; run existing guard/pipeline/safety/review/auto suites.
- [x] Step5: Freeze two files, independent scoped spec/quality review, root native full/screenshot/acceptance tests, exact checkpoint. No production Watch or whole-project PASS from these tests.

Runtime is the existing isolated Qt6.12 candidate: tests/screenshots/qa-current/local-privacy/qt612-candidate/venv/Scripts/python.exe -B tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py. Covering files: tests/unit/test_watch_resource_ownership.py tests/unit/test_watch_resource_guard.py tests/integration/test_watch_resource_guard_pipeline.py tests/integration/test_watch_safety_regressions.py tests/integration/test_auto_apply.py tests/integration/test_review_first.py. Root must verify actual existing file paths before dispatch; equivalent exact existing handler tests may be selected instead of nonexistent paths. Writer must preserve native original summaries/exit/forbidden/thread evidence and disclose any fixture/tool failure, freeze all source/test bytes in .superpowers/sdd/watch-resource-ownership-report.md. Root intends feat: add owned watch resource receipts.

Open final-runtime investigation inherited from predecessor: one parallel broad QML run native access violation during GC; same unchanged sequential tree full4705passed/native0. Cause remains unproven. This pure guard task neither repairs nor excuses that crash. No GC disable, skip, tolerance/Golden changes or claimed final-release stability.

## Completed pure-guard checkpoint evidence

All five steps above are complete for the exact guard/new-test scope. Exact opaque pending/execution receipts and their distinct lifetime, true owned-at-capacity policy, legacy isolation, sampled revision commit, strict primitive/fixed-error behavior and failure overflow safety are implemented. Callback/finalizer paths are outside the lock. Genuine finite-thread REDs and all tool failures were retained; no failed run was renamed passing. Initial feature-absence RED is not end-to-end evidence.

Frozen implementation independent task review: Spec compliant / Quality Approved, no Critical or Important findings. Root sequential isolated Windows Python3.14.5/Qt6.12.0 results:227 covering passed/3existing warnings/1.46s; full4845 passed/3existing skips/4existing warnings/95.80s; screenshots66 passed/1designed update-mode skip/86existing warnings/46.11s with UPDATE removed; guarded acceptance186/186. Every process actual native0, forbidden accesses0 and actual atexit MainThread only. Source/test SHA256 values were independently checked unchanged before staging. Main/shortcut and formal screenshot tree unchanged.

This is not ingress/delivery resource wiring, production Watch activation, actual-model quality/privacy acceptance or final runtime stability. The earlier unexplained Qt native GC crash remains open. No new release EXE, real API/Key/Credential Manager/private input, system-security change, Golden update, merge or push. Next integration must connect genuine pending and execution ownership through actual capture/post/Future/Qt publication tails before activation.
