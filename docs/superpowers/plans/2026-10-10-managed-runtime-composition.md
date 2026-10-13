# One managed runtime composition

C1D composes reviewed coordinator, immutable catalog, managed Batch and Settings
probe contracts. It is followed immediately by managed Watch (C2) and resources/
product UI (D); the interim unavailable Watch is a development safety state, not
a release or finished feature. Existing saved Watch files/history are preserved.

## Scope

- `src/qml_bootstrap.py`
- `src/main_qml.py` only bounded runtime lifecycle/isolated smoke composition
- `src/controllers/processing_coordinator.py` catalog publication ordering only
- `src/core/processing_authority.py` and its focused unit tests, limited to explicit
  pure cloud-engine unbind and one-way admission-close primitives (do not relax
  fingerprint validation or committed receipt finishing)
- `tests/integration/test_managed_processing_runtime.py` (new)
- Existing focused bootstrap/runtime/production-service tests as necessary
- `packaging/xuxia.spec` and focused packaging assertions, limited to including
  the existing pinned engineering catalog used by inert C1D construction; no
  model/projector weights, runtime ZIP, license migration or product resource flow
- `src/ui_qml/WatchForm.qml`, `WatchPage.qml`, `WatchResultsPanel.qml`, limited to
  explicit boolean coercion at the seven existing null-controller bindings found
  by the guarded navigation regression (visible/checked/enabled); preserve all
  non-null semantics, layout, text and actions. The interim unavailable default
  must navigate without QML type warnings, not hide the defect by injecting Watch.

No Watch handlers/config persistence, file executor/Undo, Provider/media/model
implementation, resource downloads, QML layout, manual or Golden changes. The
seven null-safe boolean corrections above do not enable or complete Watch. One
writer; root owns Git/review. No real API/keys/Credential Manager/private fixtures,
system settings, push or release. Runtime tests inject fake dependencies, stores
and synthetic files; no implicit OS user-directory writes from test defaults.

## Bootstrap order and ownership

Determine the explicit configuration path and load processing-intent.json from
its parent FIRST. Construct one ProcessingCoordinator/authority before config
loading or any credential read. Production startup always uses metadata-only
loading (`load_credentials=False`), including CLOUD; exact per-profile cloud
credentials are resolved only later under admitted captured work. Preserve the
legacy migration API and input JSON bytes. Honor config_file rather than global
CONFIG_FILE. This is root's approved construction policy, not a model/default change.
Explicit supplied live config remains caller-owned; don't use it to select mode.

Compose one managed LocalInferenceService and BoundedLocalPreparationService
using explicit factory/root/catalog injections. Constructors are inert; no automatic
model download, import, self-check, key read or network call. Production roots are
OS user data, not program/working/QA/developer paths. Bundled catalog lookup is
program-relative, explicit, pinned and key-free; no localhost proxy/provider masquerade.
Resource/UI activation remains D. Missing/unverified resources stay NOT_READY.
Keep local/cloud processing choice separate from template/smart naming choice.

The current bundled `qwen35-4b-feasibility.json` is engineering metadata, not a
product-ready catalog. Before D1 adds the separately reviewed product catalog,
it may supply only the inert C1D service configuration with fixed OS-data roots:
do not import/adopt its QA stores, launch a self-check, expose activation/download,
or promote readiness. D1/D3 replace this interim construction with the product
catalog and owned resource flow before any product-local completion claim.
Explicit test catalog/service factories remain synthetic dependency seams.
The default loader must check the existing bundled engineering catalog's expected
canonical identity, not accept an arbitrary valid manifest. Include that exact
JSON as program-relative package data so an isolated frozen startup follows the
same inert composition without a repository/CWD dependency. Missing/tampered
metadata must never be substituted by a QA/developer path or arbitrary URL.
D5 will replace the engineering data entry with the reviewed product catalog.
The current exact interim identity is
`a313ef6e1bc1df079bab962cd8e605cc1c6aa135a91f5d4894150f4dc23da5e6`,
purpose `engineering-feasibility-only-not-product-ready`, total resource bytes
`3431786583`. Root recomputed these from the bundled metadata; this is not a new
artifact download/hash, hardware measurement or product resource verification.

Existing explicitly supplied two-argument `connection_test_service(profile, key)`
fixtures remain intentional legacy injection. The omitted production default uses
the fixed managed three-argument service/runner contract from C1C, with no runtime
signature probing or fallback. Test-only legacy injection is not evidence that
the production connection path is guarded.

Build actual templates on Qt, freeze one AnalysisCatalog and source, bind active
cloud fingerprint (only enabled verified profiles), and construct one managed
BatchAnalysisService whose callbacks read only that source. Credential callback
looks up only the exact captured cloud profile. Pass explicit managed adapter
factory with ProcessingDispatch/retry executor. No live AppConfig/QObject lookup
from analysis workers. Inject managed analyzer BEFORE restored rows can execute.

Settings receives current policy and the managed fixed-probe runner. Successful
input commit on Qt invalidates generation, installs prevalidated catalog, binds
cloud engine and ONLY THEN emits coordinator/settings public signals. Prevent
reentrant signal callbacks from admitting an old catalog in a new generation.
Hold the AnalysisCatalogSource admission/publication guard over that entire pure
invalidate/install/bind operation, using source-before-authority lock order. The
managed analyzer holds the same guard for capture from both Qt and non-Qt threads.
Release it before all public signals, file/credential/transport/model operations
and Qt event processing. Merely locking individual catalog get/install calls or
assuming all admission runs on Qt does not prevent the non-Qt Watch race.
When there is no active profile, invalidate prior work and avoid exposing a usable
previous engine/catalog. Key-only successful changes also invalidate queued work.
The existing bind API requires an actual SHA-256 identity; do not invent a dummy
identity to mean unavailable. If needed add a named authority unbind operation
that clears the cloud fingerprint and invalidates prior cloud work under its
short lock, preserving choice/readiness/receipt ownership. Publish its Qt state
only after the catalog transaction is complete. Capture/commit with the old engine
must then fail; unrelated already-committed receipt finishing remains valid.
Failed settings transaction preserves current catalog/context; general Save/Cancel
cannot roll back the separate immediate processing choice.

Default C1 production Watch is None/unavailable: do NOT construct legacy backend,
observers or handlers, restore work journals into execution, or rewrite stored
statuses. Explicit injected test Watch remains caller-owned. C2 replaces this
temporary safety boundary with actual guarded Watch before product delivery.

Inject/hold coordinator before QML root creation as processingController. This
task does not add visual controls; D will expose the user flow. Status must not
claim model readiness merely because extraction dependencies or files exist.
Keep all prior i18n/controller strong references through their full Qt lifetime.

## Lifecycle

Extend QmlRuntime to own coordinator/catalog/local services/probe runner and actual
worker references. `cleanup(deadline=None) -> bool` uses one finite absolute
monotonic deadline. Begin by closing admissions and revoking work; cancel Batch/
probes/any explicitly runtime-owned observer. Drain writer + queued acknowledgements
while Qt owners live; require actual Batch/probe idle, preparation close, local
shutdown phase CLOSED before destroying root/component/engine or dropping owners.
BUSY/CLEANUP_PENDING/RECOVERY_REQUIRED means incomplete, not successful cleanup.
On timeout keep owners and return false; repeated cleanup may finish later. Never
process Qt events under locks or recursively drain from a stateChanged callback.
Already-committed HTTP may finish; no fabricated cancellation/unsend claim or PID
killing. Caller-injected resources have explicit ownership; don't close/delete
someone else's service without the agreed injection contract.

The existing coordinator's `_open=False` and generation invalidation alone do
not close pure authority admission: an exposed managed service could capture new
work in the new generation. Add a narrow one-way authority admission-close operation
and use it before coordinator close/failure notifications. It rejects new work,
new fixed probes, uncommitted HTTP attempts and old result acceptance under the
authority's short lock, without I/O, Qt callbacks, invented mode selection or
readiness promotion. Existing already-committed receipts still finish truthfully.
Closing is not reversible by a queued choice acknowledgement. Normal catalog
changes use invalidation/unbind, not this permanent lifetime close. Include direct
post-close capture/probe/HTTP and committed-receipt completion negative tests.

Wire actual application closing to begin this boundary BEFORE Qt tree deletion.
If work is not drained, retain the runtime/event loop and poll bounded cleanup;
do not let app.exec exit destroy callback targets and report success. Diagnostics
are fixed/redacted. Smoke uses explicitly isolated metadata/intent/fake credentials,
not real user settings, and exercises the same managed composition.

## Required tests

- Saved LOCAL/invalid intent with fake legacy-key JSON: zero credential reads,
  migrations, adapter/probe/cloud calls; source config bytes unchanged. Views and
  metadata save remain usable. Missing config path honored without user-directory
  contamination. Explicit future schema aborts with zero side effects.
- Default managed Batch routes LOCAL through fake bounded preparation/inference,
  no cloud fallback. CLOUD uses captured verified profile and guarded dispatch.
  Saved unready LOCAL rows never create cloud requests. Explicit legacy fixtures
  are still intentional; don't use them to prove production guarded composition.
- Config/template/key changes invalidate before reentrant signals can start work;
  new work sees one complete catalog, old work cannot publish/Auto Apply.
- A non-Qt capture interleaved with publication sees an entirely old or entirely
  new catalog/generation/binding, never mixed old inputs with new authority.
- Default C1 with saved active watches starts zero observers/legacy analysis/journal
  reprocessing and leaves persisted Watch bytes/history unchanged.
- Blocked probe/Batch/local/writer cleanup: first deadline returns false, Qt owners
  remain; after release/cancellation, later cleanup returns true and warnings=0.
  Close before queued cloud choice acknowledgement never reopens submission.
- Qt deletion ordering and real main entry/isolated smoke observe finite owner
  cleanup; no `shutdown(wait=False)` interpreted as proven worker exit.

Use TDD, run focused runtime/Batch/Settings/lifecycle tests. Root reviews/checkpoints
and runs current full non-screenshot/screenshots(no update)/acceptance before C2.
No model quality, native visual or whole-product completion claim at this stage.
