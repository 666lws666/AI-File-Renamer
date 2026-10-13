# Managed Watch Event Admission and Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for this bounded task with TDD, a fresh scoped spec/quality reviewer and root-owned verification/Git.

**Goal:** Capture authentic processing work when a Watch event arrives, before debounce, and retain truthful ownership of observer/timer callbacks through shutdown.

**Architecture:** Extend the existing plain-Python WatchController with an explicit managed ingress seam; do not construct a second processing authority or Watch store. Frozen Watch records carry the exact issued AnalysisWork or a fixed admission failure. This task only establishes event admission and owned lifecycle; persistent Qt acceptance, analysis execution and production activation are separate dependent tasks.

**Tech Stack:** Existing WatchConfig/WatchController/watchdog, threading primitives, the reviewed ProcessingAuthority/AnalysisCatalogSource/BatchAnalysisService, synthetic files and controlled observer/timer tests.

## Global Constraints

- The sole source worktree is the existing isolated codex/local-privacy-mode checkout. Root owns Git; no main-checkout edits, merge, push or release.
- Production Watch and Batch use the same ProcessingAuthority, AnalysisCatalogSource, managed BatchAnalysisService and application file-operation lane. No replacement authority, Provider, file engine or history format.
- Capture exact authentic AnalysisWork before debounce, resource wait or worker submission. Automatic timer reset/recovery must never recapture processing mode, template, language, profile, credentials or authority.
- Catalog source.guard() encloses capture and the complete invalidate/install/bind publication transaction; lock order is catalog source then authority. No disk, network, credential I/O, public signals, event pumping or worker waits under that guard.
- Preserve existing templates, Watch IDs/statuses/modes/version, timestamps, paths and histories. Default explicit legacy construction remains compatible; the managed route cannot fall back to legacy analyze/handle_file_ready.
- RESOURCE_PAUSED collects but does not start analysis or implicitly activate; PAUSED does not collect or self-activate. This task does not change approved Auto Apply policy.
- Old observer incarnations and old timer identities cannot admit or fire after pause, edit, remove/recreate-same-ID, restart or close.
- At most 1000 live managed event admissions per controller, including debounce and queued ingress delivery. Refuse overflow as an explicit non-admission (None), never successful capture; do not build an unbounded staging or error-post queue.
- Keep cancellation, authentic private identity and actual thread/callback liveness distinct. Retired observers/timers remain strongly owned until actual exit; no blocking joins under callback-needed locks or on Qt.
- Synthetic local files only; no cloud API/key/Credential Manager/private inputs, firewall/ACL changes, formal Golden update, dependency installation or disabled guard/GC/backend change.
- This task does not activate production Watch, perform analysis/file execution, change persisted Watch schema, mutate Review/Auto queues, UI/locales, model readiness/resources or manuals.

## Task 1: authentic managed ingress and truthful observer/timer retirement

**Files:**

- Create `src/core/watch_work.py`: frozen admission/failure/stable-event values and bounded pure field validation.
- Create `src/controllers/managed_watch_ingress.py`: plain-Python capture/currentness/dispatch ownership, no QObject or thread pool.
- Modify `src/controllers/watch_controller.py`: explicit ingress/autostart injection, incarnation/tokenized debounce, owned observer/timer retirement and finite lifecycle drain.
- Create `tests/unit/test_managed_watch_admission.py`: real authority/catalog/capture identity, stale/error/overflow negative tests.
- Create `tests/integration/test_managed_watch_lifecycle.py`: real Python threads, synthetic files, controlled observers/timers and actual ownership/drain tests.

No other source/test changes. Existing catalog/coordinator and managed analysis contracts already provide the publication guard; consume them rather than inventing another lock. Existing legacy Watch tests are regression evidence, not permission to weaken new assertions.

### Interfaces and immutable event values

Consume existing `BatchAnalysisService.capture_work(source_path, task_id, *, task_attempt_id, task_cancel_event, template_id='', output_language='', naming_mode='template', naming_policy_version=SMART_POLICY_VERSION, quality_mode=None, defer_execution_deadline=False)`, `AnalysisCatalogSource.guard()`, `ProcessingAuthority.snapshot/is_current`, immutable WatchConfig and SourceFingerprint.

Add frozen values with exact primitive ownership fields:

- `WatchAdmission`: exact `work: AnalysisWork`, `watch_id`, exact immutable `watch_config: WatchConfig`, `incarnation: str`, `event_id: str`, `cancel_event: threading.Event`.
- `WatchAdmissionFailure`: exact captured `ProcessingSnapshot`, watch ID/config/incarnation/event ID, and a fixed `reason: str`; no invented WorkContext or model output.
- `StableWatchEvent`: exact admission, `fingerprint: SourceFingerprint`, protected extension, accepted target directory, and a private delivery identity. The private delivery identity is never serialized.

Admission identity and configuration are not copied into reconstructed AnalysisWork. `watch_config` must already be a validated existing frozen WatchConfig; do not construct/normalize paths with WatchConfig during pure capture.

Plain ingress interface:

```python
class ManagedWatchIngress:
    # service/authority are shared existing instances; capture_guard is source.guard.
    # post_event is a thread-safe private queued-post callback supplied by the next task.
    def __init__(self, service, authority, *, capture_guard, post_event):
        self._service = service
        self._authority = authority
        self._capture_guard = capture_guard
        self._post_event = post_event
        self._open = True
        self._owned = {}  # exact issued event objects; protected by a short lock
```

Produce complete bodies for these public methods:

- `capture(config: WatchConfig, incarnation: str, source_path: str, event_id: str) -> WatchAdmission | WatchAdmissionFailure | None`: reserves bounded ownership before pure capture; None means closed/overflow/invalid admission, never a successful work.
- `post_stable(admission: WatchAdmission, fingerprint: SourceFingerprint) -> bool`: validates exact privately owned identity, source suffix/accepted target from captured inputs, transfers one owned delivery to post_event without releasing ownership before the callback is consumed.
- `is_current(event: WatchAdmission | WatchAdmissionFailure | StableWatchEvent) -> bool`: authentic private identity and captured authority/session/generation/cancellation, no store/QObject I/O.
- `retire(event) -> bool`: retires only that exact issued event/delivery, idempotent; it may not remove a newer event with the same string IDs/path.
- `begin_close() -> None`: stop new admissions, cancel untransferred admissions; preserve queued-delivery ownership until consumption.
- `owned_count` and `workers_idle` properties: include all live reservations, in-flight pure capture/post callbacks and queued delivery ownership, not just dict length.

`capture` takes the authority snapshot and calls service.capture_work inside one reentrant catalog guard. Set `defer_execution_deadline=True`; the existing sealed service starts the finite local budget once at first actual run. For this task's existing WatchConfig there are no new naming/language fields, so capture template naming with config.template_id and empty output_language (template language). Later schema task adds explicit choices without a late UI-language read.

Catch only to produce allowlisted safe admission reasons: local_unavailable, cloud_unavailable, superseded, invalid_settings, queue_full, closed. A failure preserves the prior captured snapshot, not a newer snapshot obtained after a race. Never retain exception text, file content, credential, prompt or a guessed probability.

### Event and debounce ordering

- [ ] Write the failing admission tests first, using real catalog/service/authority contracts with fake bounded preparation/inference and no external calls.
- [ ] Assert service capture runs on the event-admitting thread before a scheduler callback is allowed to fire; its exact returned object survives stabilization.
- [ ] Replace the current unsynchronized tuple debounce registry with identity-bearing entries under the controller registry lock. Each scheduled callback carries its exact entry token and observer incarnation.
- [ ] Snapshot existing watch/config/incarnation under the short controller lock, release it, capture under catalog guard, then recheck the same watch/config/incarnation under controller lock before insertion. Pause/remove/edit racing capture retires/cancels that work rather than inserting it into a new watch.
- [ ] Only new external CREATED/MODIFIED/MOVED events can replace an admission and capture fresh work. Internal timer reschedule/recovery retains the exact admission and Event. DELETED cancels matching unaccepted work and does not invoke analysis.
- [ ] Directory/temp/path-scope filtering is explicit. Raw watchdog directory events are rejected before admission; do not stat/read source before capture. Lexical source scope uses the configured normalized absolute root and path-component containment, never string-prefix containment or resolve/stat in capture.
- [ ] At debounce time, atomically claim only the matching token, then stat outside registry/catalog locks. Require existing regular nonempty file and create a factual SourceFingerprint. A changing file may reset stability wait with the same admission, not new processing inputs.
- [ ] Managed stable work posts only through ingress; it never calls legacy handlers, on_file_ready, inference, ReviewQueue/history or public UI callbacks on the observer/timer thread.
- [ ] A failed admission is posted as its exact snapshot-scoped failure through the same private callback and remains owned until consumed. It cannot be promoted to success or newly captured after LOCAL/unavailable failure.

The controller constructor gains keyword-only `managed_ingress=None, autostart=True` after the existing compatible inputs. Omitted ingress retains identified legacy synchronous dispatch. `autostart=False` loads configuration without starting observers/retries; later runtime wiring explicitly invokes start_all after all callbacks/owners exist. Existing constructors/handler helper tests retain positional compatibility.

### Actual timer ownership

Production DebounceScheduler gains a short lock, token-bearing timer registry and an owned set that includes cancelled, running and callback-tail timers until actual `is_alive()` is false. Install the entry before Timer.start. `_on_fire` claims only the exact timer token, increments callback ownership before releasing its lock, executes callback outside the lock, and decrements in finally; cancellation of a replacement cannot be undone by the old callback's pop.

- [ ] `cancel` removes only the matching scheduled entry, calls cancel without waiting and retains the timer for truthful liveness.
- [ ] `cancel_all` seals outstanding scheduled callbacks without forgetting their actual threads.
- [ ] `workers_idle` prunes only actual exited threads and requires no active callback body/tail.
- [ ] `drain(deadline: float) -> bool` is finite and does not pump Qt, block a running callback or join under any controller/scheduler lock. The caller may poll and process events outside locks.
- [ ] FakeScheduler remains deterministic/compatible and may report actual synchronous callback ownership for equivalent tests. Do not make static dict assertions substitute for a blocked real Timer regression.

### Observer incarnation, transactional lifecycle and retirement

Each live observer receives a unique incarnation token at installation; _WatchEventHandler carries it. Optional legacy helper construction without a token remains compatible. Production callback dispatch includes the actual token and rejects stale token before capture. Store a retired observer record keyed by exact object and original watch ID/incarnation until its real is_alive is false; removed watches do not erase retired ownership.

- [ ] Keep persist-first pause/remove/update behavior: failed save leaves durable/live state and the existing observer intact.
- [ ] After successful pause/remove/edit, invalidate the old incarnation and retire/cancel matching unaccepted admissions/timers before any notification. Stop/unschedule outside callback-needed locks; do not perform a one-second join on Qt or drop a still-live observer after timeout.
- [ ] No same-watch replacement observer may start while an old active/starting/retired observer is actually alive. Report fixed observer_retiring rather than silently creating two observers. Failed/reentrant start must retain and stop its actual created observer even if the watch was removed meanwhile.
- [ ] start_all is idempotent; stop_all is reusable, does not change stored ACTIVE choices, and keeps retirement ownership. begin_close is one-way, cancels debounce/retries and rejects future starts/admissions without deleting user files/config/history.
- [ ] RESOURCE_PAUSED keeps its current observer collecting; only existing resource_guard.recover authorizes return to ACTIVE. PAUSED/ERROR/future status do not self-start on constructor with autostart=False.
- [ ] Existing bounded exponential restart remains token/incarnation fenced; an old dispatched retry cannot revive a removed/recreated watch or resume one now PAUSED/RESOURCE_PAUSED.
- [ ] Add `observers_idle`, `workers_idle`, `begin_close()` and finite `drain(deadline)` to WatchController. Idle requires retired/starting observers, timer bodies/tails and ingress deliveries actually drained; False retains all strong owners. Controller does not own or close the shared analysis service/authority/file lane.

### Concrete minimum behavior tests

```python
# The setup uses a real authority/catalog/managed service and a controlled scheduler.
# No model or transport is executed by this task.
controller._simulate_file_event(watch_id, str(source), FileEvent.CREATED)
admission = captured_events[0]
assert admission.work.context.mode is ProcessingMode.CLOUD
coordinator.selectLocal()
scheduler.run_pending()
assert accepted_events == []
assert not legacy_analyze_calls
assert not cloud_transport_calls
```

The test fixture supplies captured_events by observing the actual service capture return, and accepted_events by the private post callback performing real ingress.is_current checks and ingress.retire in finally. It must not manufacture a matching context or treat a fake service as proof of authority currentness.

- [ ] Admission capture is source/credential-I/O-free; spies on source stat/read, config/credential getters fail if called before timer stabilization. Catalog publication racing capture proves one whole generation/catalog and no deadlock.
- [ ] CLOUD admission then LOCAL before debounce; unavailable LOCAL then cloud after capture; failure publication after generation changes: none can become current or fall back to legacy/cloud.
- [ ] Old timer already executing while a new entry replaces it; old callback cannot remove/fire the new entry. Automatic stability reset retains work object/Event; external new event changes them.
- [ ] Pause/remove/recreate same ID and observer restart preserve exact fencing; raw late old-observer event has zero capture/queue/file effect.
- [ ] Boundary 1000 owned captures succeeds, 1001 refuses without capture or source I/O; retire once allows exactly one replacement; closed/pending-post owner count remains truthful.
- [ ] Controlled observer thread remains alive after a nonblocking stop; join is patched to reject blocking calls while pause/remove/start_all/drain returns promptly, with no duplicate observer. Release the thread and require true drain. A callback enters the controller during stop without lock-order deadlock; is_alive remains an accurate nonblocking liveness query.
- [ ] Real Timer blocked inside callback and at callback tail: first finite drain False, actual ownership retained, release then true. Cancelled-but-started timer cannot claim replacement.
- [ ] Pool/model/Review/Auto methods are patched to fail if this task invokes them. No queue/journal or user-file mutation during admission/lifecycle tests.
- [ ] Deferred constructor loads saved ACTIVE/PAUSED/ERROR/RESOURCE_PAUSED unchanged, creates zero observers until explicit start_all, then only ACTIVE starts once; no initial scan or filename processing.
- [ ] Failed persist on pause/remove/update retains status/config/observer and admission; successful lifecycle transition cancels only matching unaccepted ownership.

### Verification and checkpoint

- [ ] Record RED/GREEN commands, actual native exit, forbidden count and scope in `.superpowers/sdd/managed-watch-admission-report.md`. Root supplies the existing strongly guarded Windows harness; ordinary GC/offscreen and UPDATE absence remain.
- [ ] Run new `tests/unit/test_managed_watch_admission.py`, `tests/integration/test_managed_watch_lifecycle.py`, plus unchanged `tests/unit/test_watch_controller.py`, `tests/unit/test_watch_integrity.py`, `tests/integration/test_watch_recovery.py`, `tests/unit/test_analysis_catalog.py`, `tests/integration/test_managed_processing_runtime.py` and `tests/integration/test_managed_file_operation_runtime.py`.
- [ ] Root freezes the exact five paths, obtains fresh scoped spec/quality review, addresses Critical/Important issues, independently verifies covered tests and creates one local checkpoint.
- [ ] Production Watch remains unavailable until the separate persistent Qt acceptance and runtime composition tasks pass. Do not count this admission/lifecycle deliverable as Watch end-to-end/model-quality acceptance or project completion.
