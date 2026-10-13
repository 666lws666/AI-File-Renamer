# Managed Local Resource Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide inert, pinned product resource configuration and safe explicit preparation/inspection, ready for the separate Qt operation owner.

**Architecture:** Reuse ResourceCatalog, ResourceManager, ResourceStore and LocalInferenceJournal. Add one pure production configuration loader and narrow backend methods, not a second downloader or inference engine. This task follows the production Watch source freeze/checkpoint; only one source writer is active.

**Tech Stack:** Python 3.14, native Windows owned handles/leases, existing SHA-256 catalog and resource transport; fake bounded fixtures for source tests, root-owned native full-size evidence afterward.

## Global Constraints

- Fixed Qwen source/quantization revisions and llama.cpp b10885 resources from the linked design; no new model/runtime/download endpoint.
- Product catalog purpose `managed-local-resources-v1`; expected canonical identity `1b3ca415eff1c7c2c91b0f6e743550ac6c2e75a7e4a750bb319c7d330ba6b859`.
- Constructors/loaders do not create user directories, download, launch a model or read credentials.
- Resource availability is not inference readiness; no local-to-cloud fallback.
- No document contents, names, paths, prompts, keys or provider objects in resource requests.
- No real network, credentials, private inputs, system-policy changes, Golden, main checkout or Git writes by implementer.
- Cross-volume automatic file moves remain disabled; the completed safe_file_move/rename/history engine is out of scope.
- Preserve original failed evidence. No unknown-root adoption, recursive deletion, journal reset or PID-as-ownership inference.
- Read `docs/superpowers/specs/2026-10-12-managed-local-resource-product-design.md` completely before implementation.

## Task 1: product catalog, safe explicit resource preparation and read-only recovery status

**Files:**

- Create: `resources/local-models/qwen35-4b-managed-v1.json`
- Create: `src/services/local_ai/production_resources.py`
- Create: `tests/unit/test_production_local_resources.py`
- Modify bounded: `src/services/local_ai/resource_manager.py`, `resource_store.py`, `inference_journal.py`
- Modify tests: `tests/unit/test_local_resource_manager.py`, `test_local_resource_store.py`, `test_local_inference_journal.py`
- Root only: exact runtime ZIP copy into `resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip`; source/hash attestation and private reports. Reuse existing license files unchanged.

**Consumed interfaces:**

```python
load_resource_catalog(path: Path) -> ResourceCatalog
ResourceStore(root: Path, catalog_id: str).lease(*, create=False)
ResourceManager(root: Path, catalog: ResourceCatalog)
LocalInferenceJournal(root: Path)
```

**Produced interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ProductionLocalResources:
    catalog: ResourceCatalog
    bundled_runtime: Path
    resource_root: Path
    runtime_root: Path
    state_root: Path

def load_production_resources(*, bundle_root: Path | None = None,
                              user_data_root: Path | None = None
                              ) -> ProductionLocalResources: ...

# Explicit worker-only parent initialization; never called by the loader.
@contextmanager
def prepare_production_parents(config: ProductionLocalResources, *,
                               trusted_anchor: Path, for_readiness: bool = False,
                               cancelled=lambda: False): ...

# Synchronous worker-only ResourceManager methods; no launch or mode mutation.
def import_bundled_runtime(self, source: Path, *, cancelled=lambda: False,
                           progress=None) -> ResourceSnapshot: ...
def repair_resource(self, resource_id: str) -> ResourceSnapshot: ...

class InferenceRecoveryState(str, Enum):
    MISSING = "missing"
    CLEAN = "clean"
    RECOVERY_REQUIRED = "recovery_required"
    BUSY = "busy"

def inspect_recovery_state(self) -> InferenceRecoveryState: ...
```

One narrow native-uncertainty lifetime seam is required when parent preparation fails before the context yields: `StoreOwnershipUncertain(StoreOwnershipError)` has fixed code `NATIVE_OWNERSHIP_UNCERTAIN` and read-only opaque `retained_owner: PreparedParentDirectories`. That independent owner exposes read-only `retained` and `idle` according to actual native lifetime. Uncertain/unclosed is not idle. The next operation owner catches and retains it, presents only the fixed error, and refuses false drain completion. Do not serialize handles/paths/request memory, infer ownership from PID, reset quarantine or retry an ambiguous free. This does not add capability parameters throughout the inference graph.

The declaration ellipses above describe signatures, not permitted implementation stubs. The runtime ZIP path is descriptive until an explicit preparation operation verifies it. Loader errors use fixed ResourceError codes without raw paths. Default application bundle/resource root is `_MEIPASS` when frozen, otherwise the program's project resource root, never CWD. This is distinct from writable user data. Default user root is absolute `LOCALAPPDATA/Xuxia/local-ai`; injected roots are test/composition seams, not QML arbitrary executable selectors. Resource/runtime siblings use the pinned catalog ID; state remains the service's state root.

- [ ] **Step 1: write real negative tests first.** Use tiny three-artifact fixture catalog/store for manager tests; product metadata tests use the exact immutable application catalog without downloading bytes. Representative loader contract:

```python
def test_loader_is_inert_and_pinned(tmp_path, monkeypatch):
    import src.services.local_ai.production_resources as product
    def forbidden(*args, **kwargs):
        raise AssertionError("constructor side effect")
    monkeypatch.setattr(ResourceManager, "download", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    cfg = product.load_production_resources(user_data_root=tmp_path / "absent")
    assert cfg.catalog.identity == product.PRODUCT_CATALOG_ID
    assert cfg.catalog.purpose == "managed-local-resources-v1"
    assert cfg.resource_root.name == cfg.catalog.identity
    assert cfg.runtime_root.name == cfg.catalog.identity
    assert not cfg.state_root.exists()
```

Create genuine fixtures and assertions for: substituted feasibility/catalog; CWD independence; missing/relative user root; no directory creation; wrong runtime source hash/size/basename/link; runtime-only PARTIAL then three finals AVAILABLE; existing verified finals skipped; pause/cancel retaining part; repeated seed with identical final no replacement; concurrent lease BUSY; partial size exact/oversize rejected; unknown ID repair zero mutation; exact corrupted owned final quarantine with unrelated file/source unchanged; injected copy/hash/fsync/publish failure no AVAILABLE. Test missing parents, existing parent junction, post-check parent substitution and actual handle unwind rather than lexical string assertions.

Journal inspection tests record every file's bytes/mtime before and after. Missing root remains absent; valid clean returns CLEAN unchanged; dirty/malformed/unknown-child/unowned marker returns RECOVERY_REQUIRED unchanged; held real marker lease returns BUSY; inspection opens no writable record, creates no marker, launches no process and calls no cleanup. Existing journal write/complete behavior remains unchanged.

- [ ] **Step 2: run the scoped guarded RED and retain the actual summary.**

```powershell
& 'tests/screenshots/qa-current/local-privacy/qt612-candidate/venv/Scripts/python.exe' `
  'tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py' `
  tests/unit/test_production_local_resources.py tests/unit/test_local_resource_manager.py `
  tests/unit/test_local_resource_store.py tests/unit/test_local_inference_journal.py -rs
```

Verify failures establish missing/new behavior, not leaked fixtures/invalid imports. Finally drain/close every fixture. Any inability to execute is an environment failure, not a fabricated test result.

- [ ] **Step 3: implement the pure product loader/catalog.** Copy exact catalog values from the design, retain provenance URLs, set only the new purpose, and hard-pin canonical identity after load. Use this structure:

```python
catalog = load_resource_catalog(application_root / "resources/local-models/qwen35-4b-managed-v1.json")
if catalog.identity != PRODUCT_CATALOG_ID or catalog.runtime_release != "b10885":
    raise ResourceError("INVALID_PRODUCT_CATALOG", code="INVALID_PRODUCT_CATALOG")
base = validated_absolute_user_data_root
return ProductionLocalResources(catalog,
    application_root / "resources/local-models/runtime/llama-b10885-bin-win-cpu-x64.zip",
    base / "resources" / catalog.identity,
    base / "runtime" / catalog.identity,
    base / "state")
```

Validate root type/absolute drive/local path and frozen/program lookup explicitly. Do not read arbitrary user manifests, resolve user reparse roots away, or check model readiness in the loader.

- [ ] **Step 4: extend the single manager/store lifecycle.** Refactor only the existing offline fixed-resource transfer body into one internal exact-item helper reused by offline import and bundled runtime seed. Retain pinned source/destination handles, prefix equality, capacity checks, SHA, fsync and non-replacing publish. Seed accepts only the catalog runtime basename and returns PARTIAL until all resources are verified. No HTTP when a trusted bundled ZIP is missing/corrupt. Partial sizes are separately bounded observed bytes, not verified finals. Preserve ResourceSnapshot existing positional compatibility by adding fields with defaults or a separate immutable observation type; never reinterpret `received_bytes` silently.

Create missing hierarchy only during explicit operation, with a finite bound of 8 distinct missing parent components below a captured trusted existing anchor. `prepare_production_parents` is the one production-facing context: resource actions prepare only `resource_root.parent`; readiness actions prepare the deduplicated resource/runtime/state parent set. It holds the independent directory capability across the actual worker operation, including `check_ready()` return/exception. The trusted anchor comes from product composition (default captured absolute LOCALAPPDATA, tests an explicit existing fixture anchor), never QML or an upward search for any existing directory. The context does not create role leaves or resource/runtime/journal markers. Existing single-leaf consumers retain their public signatures and alone initialize their own leaf and marker; no new capability is propagated through every inference/attestation API.

Use directory LIST+ATTRS pins, relative no-reparse native create returning the actual created handle, and an independent resource request owner; do not instantiate the frozen engine's _Transaction or touch its _OWNER. Attribute-only directory pins are insufficient. Existing owned marker/nonempty protection and first empty-component protection are separate claims. Do not assume READ-only sharing excludes reparse attribute mutation; that protection is unproven and must be established by actual owned native tests before any path-based transfer/publication is credited safe. If it fails, retain a minimal exact-owned nonempty initialization guard or equivalent relative capability until the permanent child/marker protects the namespace, with strict cleanup/uncertainty ownership, rather than another check-then-path check. Initialization guards are not ownership markers and may not become unknown children in a role leaf. No driver/system policy, cross-volume movement or frozen mutation-engine rewrite is needed. Foreign markers/unknown children/import sources never acquire marker-adoption authority. Newly created empty directories may remain on failure; no recursive rollback cleanup. Preserve service-retained journal handles after the parent context exits. Exact repair acquires a new lease with writable pin rights for the chosen fixed item before non-overwriting quarantine; it cannot use a readonly pin and claim mutation succeeded. Keep failed files and fixed error codes.

Parent-capability coverage: entirely absent descendants; resource-only does not create runtime/state; readiness creates only parents and no role leaf/marker/record; legacy single-leaf behavior preserved; missing parents still fail in an unwrapped legacy runtime call; wrapped tiny archive/journal operations create only their own exact markers; 8 distinct missing parents accepted and 9 rejected before mutation; missing/relative/UNC/outside anchor causes zero creation; cancellation/native-create/guard-unwind failures preserve outside bytes and uncertainty ownership. Actual `check_ready` fake must witness the capability held until return, not merely assert a source-string context exists.

- [ ] **Step 5: add read-only recovery observation.** Add a readonly owned-store observation context with readable marker pin excluding concurrent writers. Reuse the exact marker/record validators and size bound; do not catch corruption as MISSING. Distinguish ordinary missing from foreign ownership, lock contention and dirty state. Perform no stream truncate/write/fsync, marker adoption, profile/PID lookup or cleanup.

- [ ] **Step 6: run focused GREEN, cover unchanged consumers and self-review.**

```powershell
& 'tests/screenshots/qa-current/local-privacy/qt612-candidate/venv/Scripts/python.exe' `
  'tests/screenshots/qa-current/local-privacy/qt612-candidate/run_guarded_pytest.py' `
  tests/unit/test_production_local_resources.py tests/unit/test_local_resource_manager.py `
  tests/unit/test_local_resource_store.py tests/unit/test_local_inference_journal.py `
  tests/unit/test_local_resource_catalog.py tests/unit/test_local_resource_transport.py `
  tests/unit/test_local_inference_resources.py tests/unit/test_local_inference_service.py -rs
```

Check actual test paths before starting; report any path substitution explicitly. Every attempted raw result stays in the designated QA evidence folder. Check no network/credential calls, actual worker tails, no live normal-exit threads and no Golden/source scope escape. Freeze source and report exact paths/hashes/tests; no commit by implementer.

- [ ] **Step 7: root review and exact checkpoint.** Generate the full scoped diff from the recorded pre-task baseline, independent spec/quality review, repair only definite important findings, root covering verification, then exact staging/diff-check/commit. Root copies the verified ZIP only after validating source size/hash and verifies copied bytes. D2/Qt preparation cannot start until this backend checkpoint is coherent. Full native product preparation/packaging are later gates and must not be inferred from this task's fixtures.
