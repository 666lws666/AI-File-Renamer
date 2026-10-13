# Qt-owned processing coordinator and metadata-only startup

This is C1A, a bounded prerequisite for the approved Batch/Watch local-mode
composition. The earlier authority, fixed-purpose probe and managed analysis
contracts remain unchanged. Do not present this foundation as a finished UI.

## Scope and constraints

One implementation writer. Root owns Git and regression checkpoints. Allowed files:

- `src/controllers/processing_coordinator.py` (new)
- `src/core/processing_intent_store.py` (writer completion hook/bounded close only)
- `src/core/processing_authority.py` (strict pending CLOUD-choice admission only)
- `src/config.py` (explicit-path, metadata-only loader only)
- `tests/unit/test_processing_intent_store.py`
- `tests/unit/test_config_schema.py`
- `tests/unit/test_processing_coordinator.py` (new Qt event-loop tests)
- `tests/unit/test_config_metadata.py` (new)
- `tests/unit/test_processing_authority.py` (repeat-choice regression only)

No bootstrap, Batch, Watch, Settings, Provider, model/resource, QML, dependency or
packaging changes in this task. No actual API, keys, Credential Manager, private
media, system settings, Golden update, push or release. Use temporary stores and
fake credential functions. Preserve the default existing Python APIs.

Review correction: an explicit new CLOUD choice while already CLOUD also suspends
new cloud admission until its exact latest durable acknowledgement. Revoke the
old generation when that repeat choice is issued; gate new business and fixed
probe capture/currentness/commit while CLOUD persistence is pending or failed.
Successful latest completion makes new work possible, never revives old contexts.
Already-committed attempt receipts remain owned and finishable. Preserve LOCAL
immediate closure, revision bounds, exact intent identity, and public signatures.
This minimal authority correction resolves the C1A review finding; no adapter or
transport-purpose implementation rewrite is authorized.

## Writer completion boundary

Extend `ProcessingIntentWriter(store, authority, *, completion_callback=None)`.
The callback receives `(intent, persisted)` and replaces the authority completion
call on BOTH submission rejection and worker completion. With no callback, keep
the existing pure-Python direct completion behavior. Invoke the callback outside
writer/authority locks. Do not add a transport, Qt import or arbitrary background
exception text to the intent store.

Writer `close()` continues to mean that its thread/writes/callback postings have
drained, not that queued Qt delivery has occurred. Do not secretly redefine it.
Retain single worker ordering, latest failed-intent retry and finite close behavior.
Permit an optional keyword `timeout=0.25`, bounded to 0..0.25 seconds, so a
coordinator can use the smaller remaining absolute-deadline budget; the default
behavior is unchanged. Reject invalid/nonfinite timeout values before waiting.

## ProcessingCoordinator

New QObject, created and operated on its owning Qt thread. Constructor accepts an
explicit `ProcessingIntentStore` and loads it read-only; create one authority from
the returned mode/revision/startup_error. The default writer is the above writer
with a private posting callback. Allow explicit store/writer injection for bounded
tests; there is no global singleton or implicit user-directory access here.

Expose `.authority`, immutable `.snapshot`, `.is_open`, and `.pending_ack_count` for
composition/tests. Expose read-only Qt properties `processingMode`,
`localReadiness`, `persistenceStatus`, `errorCode`, `committedAttemptCount`,
`admissionOpen`, with a shared `stateChanged` notification. Values are canonical
enum values/fixed error codes, not translated prose. No model path or key in the
public record.

Public owner-thread operations:

- `selectLocal()` closes the cloud authority immediately, publishes the changed
  snapshot, and submits the exact issued choice. It never waits for a save or a
  model. A persistence error/overflow cannot restore CLOUD.
- `selectCloud()` requests a new explicit cloud choice and submits it. CLOUD does
  not become usable until the exact latest choice is durably acknowledged.
- `retryChoice()` retries only the still-current failed exact intent, never creates
  an implicit CLOUD intent. Return a boolean admission/queue result.
- `bind_cloud_engine(fingerprint)` and `invalidate_work()` delegate to authority
  on Qt and publish state. Closed coordinator rejects further mutations/admission.
- `publish_local_state(expected_generation, state, *, engine_fingerprint=None)`
  delegates only on Qt and returns whether the expected generation was accepted.
  It does not run the model, interpret resource AVAILABLE as READY, or fabricate
  an engine identity.
- `begin_close()` is idempotent: close admission and revoke generation before
  waiting. Public choice/binding/readiness mutation cannot reopen admission.
- `drain_choice_writer(*, deadline)` uses one absolute monotonic deadline, writer's
  finite close polls and queued acknowledgements while Qt owners remain alive.
  It returns false if either writer work or posted Qt acknowledgements remain.
  Repeated calls may complete later. Never process Qt events under a lock, use
  BlockingQueuedConnection, or delete the QObject while callbacks may still post.

An owner-thread guard rejects these mutations from a worker before side effects;
authority transport attempt commitment remains independently thread-safe.

Before submit, count one expected acknowledgement, including rejected submits.
Worker callback only posts a private Signal connected with explicit QueuedConnection;
it does NOT mutate authority or public state. Qt delivery decrements exactly once,
authenticates the exact intent against the latest choice, applies completion only
while open and emits the actual snapshot. Stale failure cannot replace a new
choice. During close, consume the acknowledgement but never call a completion
path that reopens CLOUD; the actual file write remains the durable startup fact.
Keep strong references until drain completes. Guard reentrant close/drain.

## Metadata-only configuration loading

Extend `load_config(config_file=None, *, load_credentials=True)`. Existing no-arg
callers retain legacy migration/key-loading behavior. Honor the explicit path for
all reads and legacy migration writes; do not accidentally use global CONFIG_FILE.
For an explicit legacy path, create only its required parent rather than unrelated
global directories.

For `load_credentials=False`, branch BEFORE directory creation, schema migration,
atomic write or any keyring function. Read an existing JSON only; check supported
schema before any migration. Strip `api_key` from the in-memory candidate and
return an AppConfig with empty key. Leave source bytes/schema/key untouched, never
log its value. A missing directory returns defaults without creating it. Existing
future schema rejection remains typed. Malformed data may follow existing default
config recovery but must not mutate files or expose content in a diagnostic.

## Required negative tests

- Writer with callback: both queued success/failure and rejected submit notify
  externally; authority remains unchanged until external completion; no callback
  runs under the condition lock. Default direct completion still works.
- Qt delayed acknowledgements: selectLocal immediately stales business/probe
  contexts; failed save/cancel-equivalent leaves LOCAL; cloud only opens after Qt
  delivery; stale old failure cannot override a later choice; latest failed retry
  succeeds without silently generating a different choice.
- No authority mutation from worker callback, and off-thread public mutation
  rejected before changes. Test actual Python worker + Qt event delivery.
- Close before pending CLOUD acknowledgement cannot reopen runtime; first bounded
  drain is false for blocked writer, then later succeeds; acknowledgement ownership
  survives reentrant stateChanged and rejected submissions without underflow.
- Resource/readiness updates reject stale generation, real READY requires actual
  identity, stable repeated READY does not churn existing contexts.
- Metadata loading: saved legacy key/schema leaves bytes identical, zero credential
  get/set/delete and atomic writes; missing directory not created; explicit path
  honored; future schema rejected with zero writes/credential calls; current and
  malformed paths never return the legacy key. Legacy loader tests still pass.

Use TDD. Run the focused new tests plus existing authority/intent/schema/security
configuration tests on the project Windows interpreter. Report raw summaries and
RED/GREEN evidence. Root then reviews and checkpoints before runtime integration.
Event-loop fixtures must reuse/create QApplication (not a QCoreApplication-only
singleton that would break later QML/Widgets tests in the full suite). Do not
change global QPA/scaling during product execution or weaken warnings assertions.
