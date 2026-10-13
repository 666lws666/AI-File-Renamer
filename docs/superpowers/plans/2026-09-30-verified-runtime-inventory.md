# Verified runtime inventory

> Execute as one implementation task followed by independent task review.

**Goal:** Turn the already hash-verified, pinned Windows runtime archive into a
bounded, restartable runtime inventory for the managed local runner. Do not make
the product invoke the diagnostic QA directory or an arbitrary PATH executable.

## Global constraints

- Local failure never falls back to cloud.
- No network, API, Key, Credential Manager, private input, process launch, ACL or
  firewall changes, QML, Golden, main checkout edits, merge or push in this task.
- Existing owned resource files are not overwritten or deleted. A corrupt final
  extraction is preserved and rejected; a partial extraction may resume only
  after its bytes are compared with the trusted archive member.
- Never execute an archive member. The inventory is not model readiness or an
  enabled privacy mode.
- Only the application's pinned catalog determines the archive filename/hash.
  No offline package can supply a different catalog, URL or executable command.
- Reuse the existing ResourceStore native lease, pinning, no-overwrite publication
  and safe fixed errors. No second filesystem ownership implementation.

## Task 1: Runtime inventory service

Create only:

- `src/services/local_ai/runtime_inventory.py`
- `tests/unit/test_local_runtime_inventory.py`

Use existing ResourceCatalog/ResourceStore interfaces. If their public interfaces
are genuinely insufficient, report the precise need before modifying them.

### Interface

```python
@dataclass(frozen=True)
class RuntimeMember:
    name: str
    path: Path
    size: int
    sha256: str
    executable: bool

@dataclass(frozen=True)
class RuntimeInventory:
    catalog_id: str
    runtime_release: str
    root: Path
    members: tuple[RuntimeMember, ...]

def prepare_runtime_inventory(resource_root: Path, runtime_root: Path,
                              catalog: ResourceCatalog, *,
                              cancelled=lambda: False,
                              timeout_seconds=120.0,
                              free_bytes=shutil.disk_usage) -> RuntimeInventory:
    ...
```

This is a synchronous worker API; a UI controller must schedule it off the UI
thread later. Constructor/import performs no I/O. Invalid inputs and expected
resource/extraction failures raise fixed ResourceError or a specific subclass,
without interpolating paths, ZIP names, exception strings or archive comments.

### Trust and lifecycle

1. Validate positive finite timeout (including rejecting bool), establish a
   monotonic deadline covering verification, extraction and re-verification.
   Cancellation/deadline must be checked between bounded chunks and members.
2. `resource_root` and `runtime_root` must be distinct, non-overlapping paths;
   runtime parent must already exist. Do not create arbitrary parent chains.
3. Hold the resource store's read lease and pin the catalog runtime archive.
   Verify byte size and SHA-256 from its pinned stream immediately before parsing.
   Hold that lease and file handle until archive parsing/copy is done. No separate
   unchecked path open is allowed between verification and ZIP use.
4. Accept a flat archive with 1–68 regular members, bounded total expanded bytes
   <=64 MiB, each <=64 MiB, safe ASCII basenames, case-insensitive unique names,
   no directories, separators, device names, ADS, absolute paths, trailing dots
   or spaces, encrypted members, Unix links/special nodes, or unsupported ZIP
   compression. The68 limit reserves12 members in the existing80-member owned
   staging bound for two weights, two request files and at most eight visuals.
   Accept ZIP_STORED/ZIP_DEFLATED only. Require both fixed entries
   `llama-completion.exe` and `llama-mtmd-cli.exe`. Preserve every legitimate
   runtime member, including `LICENSE-LLVM-OpenMP`; don't drop license files.
5. Only after full central-directory validation acquire/create the separate
   catalog-owned runtime store. An unrelated nonempty root is never adopted.
   Pin directories and target files for the complete extraction using ResourceStore.
6. Compute each member's expected hash from archive bytes with bounded reads, then
   stream into its exact `<name>.part`. On resume, compare the existing prefix
   against archive bytes before append. Preserve mismatched parts; require a
   separate explicit repair action rather than truncating them. Check free space
   for remaining expanded bytes plus64MiB before and during writes.
7. Publish only after CRC/read success, exact size and independent staged hash;
   use the store's no-overwrite publication. Existing final members are rehashed
   and must match; invalid ones remain untouched and fail closed. Unexpected
   unrelated files are never removed.
8. Return only after all declared members are independently verified while pinned.
   `members` is a deterministic sorted tuple. Executable is true only for `.exe`
   or `.dll` suffix (case-insensitive), an ACL staging hint rather than permission
   to choose or execute it. The future runner must still independently pin/hash
   these paths against this inventory immediately before owned staging.
9. On cancel/timeout/disk/read failure retain valid finals and safe partials;
   release all leases/handles. A fresh call can resume, but no success flag can
   substitute for re-verification. No recursive cleanup, arbitrary deletion,
   model launch, subprocess or network operation is added.

### RED/GREEN tests

Use tiny local ZIP fixtures and valid tiny catalogs; test actual ResourceStore
under native Windows, with no external downloads.

- Valid flat archive => all exact hashes/sizes; preserves notice files; fresh call
  rehashes; immutable result; constructor/import no work.
- Wrong archive hash/size => no runtime root or output; arbitrary external metadata
  ignored; already-open archive stream is the stream used for ZIP reading.
- Each unsafe member class, duplicate/case collision, missing required executable,
  over-count/expanded-size, encrypted and unsupported compression => fail closed
  before runtime writes. ZIP corruption/CRC failure cannot publish a member.
- Cancel/deadline before acquisition/during verification/during extraction, partial
  retained and exact resume; changed prefix preserves original bytes and fails.
- Disk shortage preflight and mid-copy, member failure after another publication,
  reopened partial store; corrupt final preserved; unrelated root rejected.
- Two resource/runtime roots overlapping rejected before writes; source archive
  unchanged on every path; busy root; returned identities are traceable to pinned
  archive, not an unverified extracted file.
- Chunk requests <=1MiB; no model-size allocation or invocation. No broad skips.

Run focused inventory tests plus resource store/manager/catalog/transport/probe
resource suites. Report initial RED and final exact raw summary, diff-check,
source/test file list, known limits. Commit only the two allowed files in a new
commit; no amend, no other source changes. Independent reviewer then checks this
task; root separately exercises the actual pinned archive (no model launch).
