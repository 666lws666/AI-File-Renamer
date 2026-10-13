# Local resource foundation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement and independently review this task.

**Goal:** Make the already tested bounded public-resource transport reusable by the upcoming managed-resource service without depending on diagnostic scripts.

**Architecture:** Move the existing transport unchanged into a production-owned module, retain the engineering CLI as a compatibility wrapper, and add an immutable validated resource catalog. This foundation alone never starts downloads, declares a model enabled, launches a process or changes processing mode. Transactional ownership, operation consent, resource recovery and UI are a subsequent bounded task, not supplied by this primitive transport.

**Tech Stack:** Existing Python standard library; no new dependency.

## Global constraints

- Local failure never falls back to cloud.
- Downloads carry only pinned public resource URLs, never file content, source paths or user filenames.
- The app requires the user's explicit Download and enable action.
- No real network/API/Key/Credential Manager, native model launch, system-security changes, QML, Golden changes, main-checkout edits, merge or push in this task.
- Preserve the existing feasibility manifest, its purpose label, exact URLs/revisions/hash/byte values. This task is not product-ready approval.
- The low-level transport requires a separately owned/exclusively locked destination; it is not by itself a safe arbitrary-folder download API. Do not invent ancestor-ACL changes or recursive cleanup.

## Task 1: Shared transport and immutable catalog

**Allowed files:**
- Create `src/services/local_ai/__init__.py` (package description only).
- Create `src/services/local_ai/resource_transport.py`.
- Create `src/services/local_ai/resource_catalog.py`.
- Modify `scripts/local_model_probe_resources.py` into a CLI/import compatibility wrapper.
- Create `tests/unit/test_local_resource_catalog.py` and `tests/unit/test_local_resource_transport.py`.
- Existing `tests/unit/test_local_probe_resources.py` must continue passing unchanged.

### Interfaces

Transport exports retain the existing signatures and behavior of
`ResourceError`, `ResourceCancelled`, `validate_resource`, `verify_resource`,
`fetch_resource`, `TrustedRedirectHandler`, `urlopen`, and their constants.
Existing script callers keep their imports; CLI monkeypatches of its
`fetch_resource`/`DEFAULT_DESTINATION` remain effective. There is one actual
transport implementation, no duplicated HTTP/hash/publish logic. Its imports
must not reach `scripts`, UI, config, keyring or runtime launcher.

Catalog defines:

```python
@dataclass(frozen=True, slots=True)
class ResourceSpec:
    id: str
    filename: str
    url: str
    bytes: int
    sha256: str

    def as_transport_dict(self) -> dict:
        return {"id": self.id, "filename": self.filename, "url": self.url,
                "bytes": self.bytes, "sha256": self.sha256}

@dataclass(frozen=True, slots=True)
class ResourceCatalog:
    model_id: str
    source_revision: str
    quantization_repository: str
    quantization_revision: str
    runtime_release: str
    model_license: str
    runtime_license: str
    purpose: str
    resources: tuple[ResourceSpec, ...]
    identity: str

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.resources)

def catalog_from_manifest(manifest: dict) -> ResourceCatalog: ...
def load_resource_catalog(path: Path) -> ResourceCatalog: ...
```

The signatures above define contracts, not incomplete production bodies. Implement
the parser fully: schema exactly integer1 (reject bool); model_id exactly
`Qwen/Qwen3.5-4B`, quantization_repository exactly
`unsloth/Qwen3.5-4B-GGUF`; revision fields40 lowercase hex; release `b` plus digits;
model_license Apache-2.0/runtime_license MIT; nonempty bounded purpose <=120chars.
Resources exactly the three IDs `runtime-cpu`, `model-q4`, `vision-f16`, each once;
ID/basename uniqueness case-insensitive, existing filename/URL validation,
per-resource size <=4GiB, sum <=5GiB, no bool sizes. Reject unsafe/control-character
metadata and unknown resource keys. Validate model/projector URLs against their
stated quantization revision and filename, runtime URL against release and
filename. Runtime `.zip`, model/projector `.gguf` only.

`identity` is SHA256 of deterministic UTF-8 sorted-key JSON containing these
catalog fields and resources sorted by ID (no identity field itself). It changes
on hash/revision/resource changes, not input dict/list ordering. Return fresh
transport dicts; mutating the caller manifest or exported dict must not alter
catalog. File loader accepts at most64KiB UTF-8 JSON, requires regular file, and
raises a fixed `ResourceError` without echoing paths/URLs/remote text on failure.
Catalog parsing performs no network, filesystem writes, config loading or model
startup. A supplied catalog is trusted *application metadata*, not a user offline
package's permission to invent a new model/runtime.

### Test and implementation steps

- [ ] Write red tests importing the new modules and validating a small three-file
  synthetic manifest with the same allowed URL/revision structure. Include:

```python
def test_catalog_is_detached_and_transport_dict_is_fresh(valid_manifest):
    original = valid_manifest["resources"][0]["sha256"]
    catalog = catalog_from_manifest(valid_manifest)
    valid_manifest["resources"][0]["sha256"] = "b" * 64
    first = next(x for x in catalog.resources if x.id == "runtime-cpu")
    exported = first.as_transport_dict()
    exported["sha256"] = "c" * 64
    assert first.sha256 == original
    assert first.as_transport_dict()["sha256"] == original
```

- [ ] Red tests: invalid schema/type/duplicate IDs/names, bad URLs or revision
  mismatch, invalid bounds, missing resources/unknown resource keys, parse error,
  oversized manifest and sanitized error; reorder-stable identity, hash-change
  identity; real manifest's exact total **3431786583 bytes** (sum the three pinned
  download objects and confirm before asserting).
- [ ] Run those tests, record the expected missing-module failure.
- [ ] Move the existing transport functions/constants/imports from
  `scripts/local_model_probe_resources.py` into `resource_transport.py`. Do not
  change resume/hash/no-overwrite/redirect/progress/timeout behavior. The wrapper
  inserts the project root for direct script execution, explicitly imports the
  public compatibility names, and retains ROOT/MANIFEST_PATH/DEFAULT_DESTINATION
  and `main` locally. Remove transport-only code/imports from the wrapper.
- [ ] Implement frozen catalog validation and bounded loader. Avoid global loading
  on import. Explicitly document the owned-directory precondition on transport.
- [ ] New transport tests exercise the production module directly with fake
  Response/io.BytesIO (no network), including successful publish/reuse, partial
  cancellation/resume, corrupt hash and sanitized exception. Assert old/new class
  and function identities prove there is one implementation.
- [ ] Run `python -m pytest tests/unit/test_local_probe_resources.py
  tests/unit/test_local_resource_catalog.py tests/unit/test_local_resource_transport.py -q`
  and `git diff --check`. Use project interpreter; all tests use tmp_path/fakes.
- [ ] Self-review imports and allowed file list, commit only task files, report RED,
  GREEN, actual files/hash and limitations. Do not begin manager/UI in this task.

Independent reviewer gate covers only this task and its tests. The owner continues
resource-store design after this shared layer is accepted; no complete-product
claim is permitted from these tests.
