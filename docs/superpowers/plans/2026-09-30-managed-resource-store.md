# Managed resource store implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this task with independent review.

**Goal:** A usable offline-testable local model resource service with explicit network consent, verified offline import, cancellation/resume and restart recovery.

**Architecture:** `ResourceManager` operates inside one catalog-specific owned directory. A cross-process directory lease serializes mutations; immutable snapshots describe resource preparation only. The shared transport supplies bounded resume/hash/public-URL behavior; the manager supplies ownership, consent and multi-resource completion. No resource status can assert that a model process or privacy mode is ready.

**Tech Stack:** Python standard library; native Windows handle/locking support as needed. No new dependencies, no Qt or model execution.

## Global constraints

- Local failure never falls back to cloud.
- Downloads carry only pinned public resource URLs, never file content, source paths or user filenames.
- The app requires the user's explicit Download and enable action.
- No real network/API/Key/Credential Manager/private file/native model launch/system-security changes/QML/Golden/main-checkout edits/merge/push in this task.
- Resource preparation is not mode activation. A cancelled/failed preparation cannot reopen cloud dispatch.
- No recursive deletion or overwrite of existing unowned paths. No ACL changes.
- Only pinned application catalog metadata controls downloads/import filenames; an offline directory cannot supply alternate hashes, URLs, model or executable configuration.
- Input file content is not accepted anywhere in this manager API. Download callbacks receive resource IDs and byte counts only.

## Task 1: Owned serialized store and preparation service

**Files:**
- Create `src/services/local_ai/resource_store.py`: filesystem ownership, cross-process lease and safe exact-path operations.
- Create `src/services/local_ai/resource_manager.py`: statuses, consent, download/import/inspection and progress orchestration.
- Create `tests/unit/test_local_resource_store.py` and `tests/unit/test_local_resource_manager.py`.
- Modify shared `resource_transport.py` only if required to support the owned-store contract; retain existing transport signatures/tests.
- Do not modify catalogs/manifests, existing model probes, configuration, providers, UI or ordinary file operations.

### Interfaces and state

```python
class ResourceState(str, Enum):
    MISSING = "missing"
    PARTIAL = "partial"
    VERIFYING = "verifying"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    AVAILABLE = "available"
    ERROR = "error"

@dataclass(frozen=True)
class ResourceSnapshot:
    state: ResourceState
    catalog_id: str
    verified_ids: tuple[str, ...]
    current_id: str | None
    received_bytes: int
    total_bytes: int
    error_code: str | None
```

`ResourceManager(root: Path, catalog: ResourceCatalog, *, opener=urlopen,
free_bytes=shutil.disk_usage)` has a pure constructor and these synchronous worker
APIs (UI thread scheduling is outside this task):

- `snapshot() -> ResourceSnapshot`: immutable thread-safe last observation.
- `inspect(*, cancelled=lambda: False) -> ResourceSnapshot`: offline full hash
  verification, no network/download/process/config/credentials; missing root
  returns MISSING without creating it.
- `download(*, consent: bool=False, cancelled=lambda: False,
  paused=lambda: False, progress=None) -> ResourceSnapshot`: false/non-bool
  consent rejects before any filesystem write or opener invocation. True is an
  explicit operation authorization, not a persisted blanket permission.
- `import_offline(source: Path, *, cancelled=lambda: False,
  paused=lambda: False, progress=None) -> ResourceSnapshot`: read only the three
  expected catalog basenames from an explicitly supplied local directory; no
  network even on failure. Do not read an external manifest or run any file.
- `restart_partial(resource_id: str) -> None`: deliberate local-only recovery
  action; move only the exact owned `.part` file into a unique `.rejected-<uuid>`
  sibling with a no-overwrite operation. Preserve bytes; next explicit download
  or import can restart. Reject unknown IDs and unsafe/link files. No blanket
  directory cleanup and no automatic retry loop.

All operations propagate a fixed `ResourceError`/specific subclass for misuse or
store-busy/ownership errors; expected pause/cancel/verification/transport failures
produce an accurate non-AVAILABLE snapshot with a fixed safe code. No caught
exception text, absolute path, signed URL or response body enters snapshots or
logs. Cancellation checked during hashing/copy/download and between resources.
Pause wins only if the supplied pause predicate is true; otherwise cancellation
is CANCELLED. Progress is monotonic *within one attempt*, may reset on a deliberate
fresh attempt, and counts actual received/verified bytes, not invented completion.

### Store rules

The caller supplies the exact catalog-specific cache root; production user-data
location selection will be connected separately. Do not access the actual user's
cache in tests. The reserved ownership marker is `.xuxia-local-resources.json`,
with exactly schema integer1, catalog identity and a random store ID. Create it
atomically/no-overwrite only in an empty root. Existing nonempty unmarked root,
invalid/foreign marker, link/reparse ancestors, non-directory root or unsafe
recognized file fail closed without changing existing bytes.

Every mutation holds one cross-process nonblocking lease for this root and a
same-instance thread lock. The OS must release the lease on process exit; never
trust an old PID or kill another process. A second manager/process must get BUSY,
not share/append the same `.part`. On Windows pin the traversed directory chain
against rename/deletion while operating and reject reparse points using native
handle evidence. Preserve caller-owned ancestors and never change their ACLs.
Use exact no-follow regular-file checks; reject hardlinked partial/final files.
If an unsafe substitution is observed before a write/publish, fail closed.

Use an owned subdirectory for the shared transport if needed. Verified final
files are never replaced. A corrupt existing final reports ERROR and remains
untouched; this task does not offer destructive repair of installed resources.
Partial files survive pause/cancel/transport errors. `restart_partial` preserves
the invalid bytes for diagnosis and is explicit, not automatic deletion.

AVAILABLE requires independent hashes of **all** three final resources in the
same catalog. No mutable ready flag or progress counter is authoritative. Reopen
with a fresh manager and rehash before reporting AVAILABLE. A crash leaving only
some correct finals or `.part` files yields PARTIAL, not success. No catalog can
reuse another catalog's directory merely because filenames match.

Offline import uses bounded streaming into the same staged/publish protocol.
Source files remain byte-for-byte untouched on success/failure/cancellation;
source links/reparse entries are rejected. A copied stream with wrong byte count
or hash cannot publish. Disk accounting includes remaining bytes and the shared
64MiB reserve before and during writes; do not allocate a full model in memory.

### Tests and implementation sequence

- [ ] Write and run RED tests for the new modules/APIs. At minimum:

```python
def test_no_consent_has_zero_side_effects(tmp_path, tiny_catalog, spy_opener):
    root = tmp_path / "new-cache"
    manager = ResourceManager(root, tiny_catalog, opener=spy_opener)
    with pytest.raises(ResourceError):
        manager.download()
    assert not root.exists()
    assert spy_opener.calls == []

def test_partial_restart_never_advertises_available(prepared_partial_store,
                                                   tiny_catalog):
    fresh = ResourceManager(prepared_partial_store, tiny_catalog,
                            opener=network_forbidden)
    state = fresh.inspect()
    assert state.state is ResourceState.PARTIAL
    assert len(state.verified_ids) < 3
```

- [ ] Implement lease/ownership and fixed error codes; cover real Windows
  two-process exclusion/release, same-instance competing calls, bad marker,
  unrelated nonempty root, junction/symlink/hardlink rejection and parent rename
  resistance. Tests manipulate only temporary owned fixtures. No security policy
  changes or admin privilege needed.
- [ ] Implement manager inspection and snapshots; inject a tiny valid catalog and
  fake HTTP responses. Test all three verified => AVAILABLE; missing/partial/
  corrupt => accurate state; new manager after completion rehashes; later
  corruption is rejected. Snapshot/constructor perform no hidden I/O/network.
- [ ] Implement download and progress using one transport implementation; tests
  for missing consent, exact URLs/headers only, cancellation/pause after first
  chunk, preserved partial, correct Range resume, invalid Range, hash/size failure,
  disk shortage before and during transfer, opener exception sanitization, retry
  after failure, exclusive final publication, and no false AVAILABLE on a failure
  in the last resource.
- [ ] Implement offline import and explicit partial restart; tests assert no
  opener invocation, source hashes unchanged, bounded reads, expected filenames
  only, unknown external manifest ignored, unsupported source/link rejected,
  cancellation/recovery, invalid part moved to a unique preserved sibling and
  unknown IDs leave the entire store unchanged.
- [ ] Run exact covering command with project Python:
  `python -m pytest tests/unit/test_local_resource_store.py
  tests/unit/test_local_resource_manager.py tests/unit/test_local_resource_catalog.py
  tests/unit/test_local_resource_transport.py tests/unit/test_local_probe_resources.py -q`.
- [ ] Run `git diff --check`, self-review the failure states and ownership paths,
  commit only allowed source/tests, report RED/GREEN output and known limitations.

No model availability or privacy-enabled UI is introduced by this task. Runtime
archive verification/extraction, production process adaptation and the shared
cloud-dispatch authority remain separate reviewed deliverables.
