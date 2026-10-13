# Managed Batch submission and Qt publication

This is C1B after the coordinator prerequisite. It integrates reviewed
BatchAnalysisService.capture_work/run_prepared into the existing Batch controller;
production bootstrap and managed Watch are later tasks. Preserve accepted rows,
templates, workspace/history and existing explicit legacy analyzer fixtures.

## Scope

- `src/core/analysis_catalog.py` (new small immutable catalog/source)
- `src/controllers/batch_workspace_controller.py`
- `src/core/batch_analysis.py` / `src/core/processing_analysis.py`, limited to the
  admission guard, shared deferred LOCAL lane and execution budget described below
- `tests/unit/test_analysis_catalog.py` (new)
- `tests/integration/test_managed_batch_publication.py` (new)
- Existing managed processing-analysis/local-routing tests for those two contracts
- `tests/unit/test_batch_workspace_controller.py` only if existing assertions need
  legitimate extension for the explicit legacy/managed split
- Three existing i18n locale JSON files, limited to fixed Batch processing errors

One writer; root owns Git/review. No bootstrap, settings, Watch, authority,
preparation/inference/Provider, resource, QML layout, dependency or Golden changes.
No real API/key/Credential Manager/private content, model run, system change,
push or release. Use synthetic files and fake analyzer dependencies. Do not change
filename/extension checks, Apply/Undo semantics or saved naming defaults.

## Immutable input catalog

`AnalysisCatalog` is a frozen, tuple-backed record of AnalysisSettings, optional
immutable active ProviderProfile, default template ID and actual snapshotted
Template objects. No AppConfig reference, QObject, callback, credential value or
untrusted extras are retained. Use the reviewed whitelist/snapshot helpers. Reject
invalid/duplicate templates; an unknown template has a fixed safe error. Disabled
or unverified profiles cannot be exposed as usable active cloud profiles.

Provide an explicit builder taking config plus actual template objects on Qt.
`AnalysisCatalogSource` holds one catalog reference, with bounded get/install
operations; both are pure and do not look up disk/config/credentials/templates.
Expose a bounded reentrant admission/publication guard on the source. Managed
BatchAnalysisService.capture_work holds the injected guard over its entire pure
catalog reads and authority capture; existing callers use a no-op default guard.
The guard never surrounds file/credential/model/transport I/O, Qt event processing
or public signals. Lock order is source guard before authority. Later composition
uses this SAME guard across invalidation, catalog installation and engine binding,
then releases it before public notifications. A lock on each separate get alone
is insufficient: a non-Qt Watch callback could otherwise capture old inputs in a
new generation. This task supplies that contract, not bootstrap integration.

## Finite local execution budget for large queues

Keep the current admission-based local deadline as the default for existing
callers. Add an explicit capture option `defer_execution_deadline=False`; managed
Batch selects True. Capture all authority, template, language, policy, quality and
settings inputs at queue admission exactly as before; defer ONLY the start of the
existing 600-second local execution budget to the first actual exclusive run. That one
absolute deadline covers preparation, inference and cleanup. Record this behavior
in the private authentic work seal; the public work cannot be copied/forged to
renew permission or time. Reject repeated/concurrent execution of deferred work
before I/O, including after a failed or cancelled first run. An explicit new user
Retry creates a new admission; workers must not silently recapture. Cloud behavior
and default existing deadline behavior are unchanged. Generation and task Events
still cancel queued work immediately. Bound queued Batch work using the existing
configured task limit or an explicit finite documented cap; excess import is
reported honestly, never silently lost or allowed to grow an unbounded queue.

For explicit deferred LOCAL work ONLY, one BatchAnalysisService-owned exclusive
lane is shared by all callers (including later Batch and Watch pools). Claim the
authentic seal once BEFORE waiting, but start its deadline only AFTER acquiring
the lane. Hold it through preparation, inference and cleanup, release in finally.
There may be at most 8 waiting deferred LOCAL runners in addition to the active
runner; this is separate from the controller's 1000-item pending/running cap.
Poll at most every 50 ms with authority and admitted Event checks. Stale/cancelled,
duplicate or overflowing work invokes no preparation/model/credential I/O. Overflow
has a fixed safe queue-full category mapped to batch.error.queueFull. Default
admission-based callers and CLOUD retain existing concurrency and deadline behavior.

## Explicit managed analyzer route

Add `set_managed_analyzer(service, authority)`. Keep set_analyzer/string-callable
route only as explicitly selected legacy injection. Managed calls use the named
capture/run APIs and never inspect signatures, discard a guard, recapture a
context in a worker, or fall back to the legacy callable after a failure.

Constructor restore with no analyzer leaves pending rows honestly pending. Managed
installation occurs before restored work starts; capture on the controller's
owning Qt thread, before pool submit. Capture exact task attempt ID, Event,
persisted template/language/naming mode/policy and source path. Store the exact
issued AnalysisWork object and context alongside that attempt, not just strings.
Run only `service.run_prepared(work)` in the worker. Service-owned cancellation
context is enough; an optional external token must be the same attempt Event.

Use a private frozen completion envelope through a private Signal(object),
explicit QueuedConnection. It carries exact stored work, task/attempt IDs,
authentic context, outcome or fixed safe failure category. No raw exception text,
source contents, key or private model output may enter user errors/diagnostics.
There is no fallback from a local failure to cloud.

Do not drop factual coverage warnings on successful publication. Validate exact
reviewed coverage types and allowlisted warning codes, never arbitrary strings or
source metadata. Persist those safe facts on the task; present partial-read and
video-keyframe limitations using fixed three-language message IDs in the existing
errorMessage presentation. A valid partial suggestion remains reviewable with an
honest warning, not a claim of complete understanding. Malformed outcome metadata
is invalidOutcome. No raw model/evidence/source text is copied into warnings.

Final Qt acceptance requires controller open, exact stored work identity,
matching attempt/context, authority currentness, current analyzing row and the
outcome's context identical to the work's context. Validate suggested filename
using the existing extension/path/conflict protection. Superseded matching work
becomes cancelled with a truthful fixed processing-change error; superseded
replacement attempts and previously accepted/applied/undone history are untouched.
Stale errors and stale successes use identical fencing. Remove matching terminal
ownership BEFORE reentrant _update_task/public signals; never pop a newly started
retry. Queued completion after cancel/clear/close cannot repopulate rows.

All managed submission/acceptance/state-map changes run on the owning Qt thread.
Off-thread calls reject before mutation. Worker only emits its frozen envelope;
ThreadPool callbacks do not mutate QML models or authority choices.

Track outstanding submitted Futures until their runners actually complete.
`close()` stops admission, cancels attempt Events and pool queued work without
blocking on slow providers; expose a truthful read-only `workers_idle`/pending
count for later QmlRuntime cleanup. shutdown(wait=False) is not proof of exit.
Keep completion bridge/controller references until runtime confirms idle. Permit
bounded subsequent cleanup rather than killing a process or silently deleting
callbacks. Legacy injected mode still passes its current behavior tests.

## Required tests

- Actual Qt event-loop delivery: capture on owner thread before worker, execution
  off Qt, final update on Qt; mutate provider/config/template source after capture
  and prove old captured immutable values remain intact.
- Fake stalled analysis: LOCAL choice invalidates queued/in-flight cloud/local
  work; both success and error are discarded; no implicit re-admission/cloud send.
- Fixed context/outcome mismatch, foreign/copy work, changed generation/session and
  repeated delivery cannot publish. Never weaken the authority seals for fixtures.
- Reentrant task change handler starts retry: old completion cannot pop the new
  attempt/Event/work. Cancel, clear and close reject late completion.
- Accepted suggestion and applied/Undo rows survive later mode/input changes.
- Local unready/admission failure shows truthful fixed error, invokes no local
  preparation/model/credential/adapter. Error strings contain no synthetic secret,
  path or arbitrary exception text. Three translations have identical new keys.
- Future idle is false while a blocked runner remains, true only after it exits;
  queued cancellation/close races do not undercount or retain false active rows.
- Catalog config/templates defensive immutable copies; no key/extra object retained;
  concurrent source reads see one complete catalog, never a partially changed one.
- Interleaved publisher/capture sees wholly old or wholly new inputs+generation;
  no old-catalog/new-generation capture. Pure catalog getters re-enter the guard;
  public notification callbacks/signals and I/O are outside the guard.
- Fake clock queues work for >600 seconds: explicitly deferred work receives one
  finite execution budget at first run, default admission deadlines do not change,
  duplicate/concurrent execution cannot renew the budget or invoke twice, and a
  queued generation change prevents all I/O. Bound pending work and report overflow.
- Deferred LOCAL runners from separate pools share the same lane. A synthetic wait
  exceeding 600 seconds does not consume execution time; no duplicate execution,
  cancel/generation-change/overflow I/O, and finally release permits the next run.
- Successful partial and sampled-video outcomes retain safe coverage/warnings and
  fixed visible messages across workspace reload. Unknown/raw warning metadata is
  rejected without content leakage; accepted suggestion remains explicitly reviewable.

Use TDD. Run focused new tests plus existing Batch analysis/workspace/runtime tests;
root performs complete regression after scoped review/checkpoint. Do not use mocked
model responses to claim real content naming quality or UI/whole-product Gate.
