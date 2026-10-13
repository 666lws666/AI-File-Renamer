# Managed Local Resource Operation Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute only the named task after the D1 backend checkpoint is accepted; source implementation is serial.

**Goal:** Expose explicit, truthful local preparation operations through one Qt-owned controller without blocking the UI, silently enabling cloud, or abandoning active work during close.

**Architecture:** One bounded runner borrows the D1 ResourceManager and the existing LocalInferenceService. One Qt controller borrows the exact ProcessingCoordinator used by Batch and Watch. Resource progress is not inference readiness. This task does not create another analyzer, inference service, transport or mode authority.

**Tech Stack:** Python 3.14, PySide6/Qt6.12, one worker, immutable operation records, bounded Qt delivery.

## Global Constraints

- Read the complete managed-local-resource product design and the actual accepted D1 public interfaces before implementation. Do not implement against anticipated stubs.
- Fixed product catalog purpose `managed-local-resources-v1`, canonical identity `1b3ca415eff1c7c2c91b0f6e743550ac6c2e75a7e4a750bb319c7d330ba6b859`, runtime b10885. No manifest/resource discovery in QA, CWD or arbitrary user executable selectors.
- At most one running operation, one latest pending replacement and one queued progress notification. Retain actual Future/callback/delivery tails, not only logical IDs.
- Constructors are inert. No download, directory creation, model launch or credentials in construction or properties. All resource I/O, hashing, runtime extraction, journal observation and local self-check execute off the Qt thread.
- Selecting LOCAL immediately fences new cloud submissions through the existing coordinator. Cancellation, pause, preparation failure and recovery-required state keep LOCAL selected. Only an explicit user CLOUD choice can authorize cloud; already-committed requests cannot be recalled.
- Only a current genuine `LocalInferenceService.check_ready()` result with phase READY and a valid engine identity may publish LocalReadiness.READY. ResourceState.AVAILABLE alone is not readiness.
- No real cloud/API/Key/Credential Manager, private inputs, system policy, main checkout, Golden or Git writes by implementer. Keep all raw evidence in `tests/screenshots/qa-current/local-privacy/`.
- No file-operation algorithm, history, Watch policy, naming protocol or provider rewrite. Cross-volume automatic moves remain disabled.

## Task 1: resource runner and Qt action controller

**Files:**

- Create: `src/services/local_ai/resource_operation_runner.py`
- Create: `src/controllers/local_resources_controller.py`
- Create: `tests/unit/test_local_resource_operation_runner.py`
- Create: `tests/integration/test_local_resources_controller.py`
- Bounded test support only where an actual shared fake is needed. D1 source changes require a specific reproduced missing contract, not an incidental redesign.
- No QML/bootstrap wiring in this task; the following composition task binds this accepted controller.

**Consumed interfaces:**

```python
ProcessingCoordinator.authority
ProcessingCoordinator.snapshot
ProcessingCoordinator.selectLocal()
ProcessingCoordinator.selectCloud()
ProcessingCoordinator.publish_local_state(expected_generation, readiness,
                                         engine_fingerprint=None)
ResourceManager.inspect(cancelled=...)
ResourceManager.import_bundled_runtime(source, cancelled=..., progress=...)
ResourceManager.download(consent=True, cancelled=..., paused=..., progress=...)
ResourceManager.import_offline(source, cancelled=..., paused=..., progress=...)
ResourceManager.repair_resource(resource_id)
prepare_production_parents(config, trusted_anchor=..., for_readiness=...,
                           cancelled=...)
LocalInferenceJournal.inspect_recovery_state()
LocalInferenceService.snapshot()
LocalInferenceService.check_ready(cancelled=..., deadline=..., is_current=...)
LocalInferenceService.retry_cleanup(deadline=...)
```

Catch the accepted D1 `StoreOwnershipUncertain` at the actual worker boundary, retain its opaque `retained_owner`, and project only `NATIVE_OWNERSHIP_UNCERTAIN`. Future completion does not retire that native owner: close must remain False while it is not genuinely idle. Retention also applies when parent context entry failed before yielding. Do not touch/reset ambiguous request storage or expose handles/source paths to QML. This is distinct from current inference-service cleanup and previous-process journal recovery.

Use the final D1 trusted directory-initialization capability around operations that need missing parents; neither a loader nor a property may initialize directories. The runner receives its absolute existing trusted anchor from composition, not a QML path. Hold the parent context through actual service self-check completion and then release only its own handles/guards. The runner must not pre-create a runtime/state marker owned by another backend.

**Produced interface:**

```python
class LocalResourcesController(QObject):
    stateChanged = Signal()
    # Read-only QML properties, notify=stateChanged:
    # phase, resourceState, errorCode, operationId, busy, canPause,
    # verifiedBytes, acquiredBytes, remainingTransferBytes, totalBytes,
    # currentResourceId, resourceRoot, modelName, runtimeVersion,
    # recoveryState, canPrepare, canDownload, canImport, canRetryCleanup
    def inspect(self) -> bool: ...
    def downloadAndEnable(self, consent: bool) -> bool: ...
    def importAndEnable(self, source_directory: str) -> bool: ...
    def prepareExisting(self) -> bool: ...
    def pause(self) -> bool: ...
    def cancel(self) -> bool: ...
    def repairResource(self, resource_id: str) -> bool: ...
    def retryCleanup(self) -> bool: ...
    def begin_close(self) -> None: ...
    def drain_owned_operations(self, *, deadline: float) -> bool: ...
    def close(self, *, deadline: float) -> bool: ...
```

The declaration comments/ellipses describe a public contract, not accepted implementation placeholders. Prefer fixed error codes and projections; no raw exception/path/content leakage. `resourceRoot` is the explicitly documented model-storage location, not a document path. Offline folder selection contains only public resource files and is validated by the existing bounded importer. Returned booleans mean admission accepted/refused, not eventual success.

`drain_owned_operations` is the narrow composition seam for staged shutdown: permanently seal admissions and prove only this controller/runner's real worker, Future, callback, Qt acknowledgment, emission and ambiguous native ownership has drained. It does not call, reset, adopt or certify shutdown of the borrowed inference service. Preserve the stricter existing `close` predicate requiring the borrowed service's safe phase as well. D3 may shut down that same service only after this owned-operation proof, then require full close before destroying Qt. This avoids a circular wait when a genuinely drained resource operation leaves the borrowed service CLEANUP_PENDING. Unknown native/resource tails still make both drains False.

- [ ] **Step 1: create genuine RED tests and retain the failed output.** Inject fake manager/journal/service and a deterministic runner at one explicit composition seam. Check Qt ownership and actual callbacks rather than source-string checks. Cover missing public APIs, inert construction, no worker start from properties, exact catalog/coordinator/service object identity, wrong catalog refusal, and blocking fake work demonstrably off the Qt thread.

- [ ] **Step 2: implement immutable request/result/progress records.** Capture an operation UUID, session ID, generation, catalog identity, operation kind, cancellation/pause events and only fixed resource inputs. No provider/profile/key/prompt/document objects. Mutable events are privately owned control channels, not serialized content. Progress carries bounded bytes/state/current fixed resource ID; coalesce to one latest slot and one notification. Never relabel transfer callback high-water marks as durable retained bytes.

- [ ] **Step 3: implement one worker and replacement admission.** On supersession cancel running work and replace only the latest pending request; drain any displaced pending owner and its eventual acknowledgement. A pending request is rechecked before execution against its captured identity/generation and current LOCAL choice; never silently recapture a stale request. Inspection is read-only and may be requested while CLOUD is selected. Download/import/prepare/repair/cleanup require explicit current LOCAL action; no resource action may select CLOUD. Pause and cancel are distinct requests. They do not invent an idle worker while native or callback tails exist.

- [ ] **Step 4: compose worker preparation without inventing success.** For `downloadAndEnable`, validate exact consent before any mutation/network; seed the bundled runtime, download only missing catalog items, inspect verified resources, inspect recovery, then run genuine self-check. Offline import uses the existing exact three-resource importer, never an arbitrary executable. `prepareExisting` must not download, silently repair or alter dirty journal state. Clean verified resources can be checked after a saved LOCAL startup through this same explicit composition operation; startup cannot infer READY from a journal record or previous session. AVAILABLE publishes 'verified, not enabled' until self-check succeeds. Preserve RECOVERY_REQUIRED/CLEANUP_PENDING; a cleanup retry only addresses the retained current owner, not previous-process PID/profile adoption. Self-check has a finite monotonic deadline within the existing service's 900-second ceiling and cleanup reserve; do not pass infinity or reuse an expired transfer deadline. Public model downloads retain their existing socket timeout/cooperative cancellation behavior; neither slow progress nor a UI wait timeout grants permission to abandon the actual worker or silently restart a model service.

- [ ] **Step 5: authenticate publication at the Qt boundary.** Publish PREPARING before capturing the generation returned by that state change. The authority may advance when clearing an old READY fingerprint; do not reuse the earlier generation. Recheck session/generation/catalog/request identity and open state at worker start, immediately before self-check and before final Qt publication. Exact success requires phase READY, no error and a valid engine identity from the borrowed service. A stale successful service result cannot enable the new choice. Remove terminal logical ownership before public reentrant stateChanged handlers, but retain real emission/Future/Qt acknowledgement tail ownership. Coordinator callbacks may select modes, queue work or close; prove those races rather than forbidding callbacks by convention.

- [ ] **Step 6: test negative privacy and lifecycle boundaries.** Require all of these concrete cases: false/non-bool consent zero backend calls; invalid resource ID zero repair; LOCAL selection blocks an existing cloud candidate before preparation; failure/cancel/pause stays LOCAL; CLOUD selection fences an in-flight and a pending ready result; same generation with foreign request/session/catalog cannot publish; reentrant PREPARING changes choice; reentrant terminal handler queues a new operation without old cleanup touching it; one running/one pending/one notification under a progress flood; callable cancellation exception fails closed; delayed worker/completion callback/Qt acknowledgement each makes finite close False and later drain True; begin_close forbids new admissions; recursive close does not deadlock; no locks held around public signals, event processing or user callbacks. Store/source fake state before and after cancelled and failed actions must agree with the D1 truthful snapshot.

- [ ] **Step 7: run GREEN and the exact unchanged consumer coverage.**

```powershell
& 'tests/screenshots/qa-current/local-privacy/qt612-candidate/venv/Scripts/python.exe' `
  'tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py' `
  tests/unit/test_local_resource_operation_runner.py `
  tests/integration/test_local_resources_controller.py `
  tests/unit/test_production_local_resources.py `
  tests/unit/test_local_resource_manager.py `
  tests/unit/test_local_inference_service.py `
  tests/unit/test_processing_authority.py `
  tests/unit/test_processing_coordinator.py -rs
```

Confirm the existing test paths before the run; report any exact path correction. Preserve every attempted result. The guard must report no network/credential attempts and no normal-exit live worker threads. No model inference is required for this task's fake lifecycle tests, and those tests cannot be described as model-quality/privacy-network proof.

- [ ] **Step 8: freeze and independent review.** Supply exact changes/hashes, RED/GREEN evidence, concerns and consumed/produced interfaces. Root builds a scoped full-diff package from the recorded task baseline, obtains independent spec+quality review and runs focused verification. Only after acceptance/checkpoint may the next task compose this controller into production QmlRuntime. No final feature completion declaration from this task alone.
