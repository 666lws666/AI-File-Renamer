# Local Inference Resource Lease Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Supply the coordinator with verified public model/runtime files while
retaining exclusive managed-store leases and read pins until its context exits.

**Architecture:** A context manager prepares the already pinned runtime archive,
then leases resource and expanded-runtime stores in that fixed order. It hashes
the pinned files again before producing immutable staging inputs. No caller-
supplied runtime inventory or arbitrary executable is accepted.

**Tech Stack:** Python standard library, ResourceCatalog, ResourceStore,
prepare_runtime_inventory, StageMember, pytest; Windows native file handles.

## Global Constraints

- No download, model/process launch, cloud API/key/Credential Manager, private
  input, ACL/security change, QML/Golden, main checkout, merge or push.
- Reuse canonical catalog/inventory/store/staging code; do not copy file pinning,
  ZIP extraction, ACL, native process, or transport implementations.
- Cancellation and the one absolute monotonic deadline cover preparation,
  lease acquisition, hashing and the final pre-yield check. Do not reset budgets.
- Errors are fixed codes, not exception text or local paths. Input resource paths
  and staging records are repr-hidden. Import has no I/O or native-discovery side effects.

## Task 1: Leased and pinned attestation

Files: create `src/services/local_ai/inference_resources.py` and
`tests/unit/test_local_inference_resources.py`. Existing modules are read-only.

### Stable interface

```python
@dataclass(frozen=True, slots=True)
class AttestedResources:
    catalog_id: str
    runtime_release: str
    identity: str
    model_name: str
    projector_name: str | None
    members: tuple[StageMember, ...]  # repr=False

@contextmanager
def attest_resources(resource_root: Path, runtime_root: Path,
                     catalog: ResourceCatalog, *, include_vision: bool,
                     cancelled=lambda: False, deadline: float):
    yield AttestedResources(...)  # pins/leases remain held across this yield
```

The callable returns no content bytes. Its internal inventory comes only from
`prepare_runtime_inventory(resource_root, runtime_root, catalog, cancelled=...,
timeout_seconds=remaining)`. Validate finite future deadline (bool/huge integer
are invalid) before side effects. Cancellation exceptions become fixed cancellation
failure; no caller exception text escapes. Validate include_vision is an actual
bool and catalog is genuine, internally consistent application metadata. Rebuild
the catalog manifest from its public fields, pass it through
`catalog_from_manifest`, and require the resulting identity equals catalog.identity;
do not trust manually constructed inconsistent dataclasses.

After preparation, hold ResourceStore(resource_root, catalog.identity).lease(),
then ResourceStore(runtime_root, catalog.identity + ':runtime:' + release).lease().
Neither lease creates or adopts a missing store. Require internal inventory
catalog/release/root to match. Read-pin every selected file before hashing:
all inventory members, model-q4, and vision-f16 only when include_vision=True.
Use the store's pinned stream and <=1MiB reads with checks before/after each read.
Check exact size, EOF, and SHA256. No path-based reads or stat-only acceptance.
The pin denies modification/deletion through staging. Recheck store.assert_safe()
and cancellation/deadline immediately before yielding.

Produce StageMember tuples in inventory's deterministic casefold/name order,
then model, then optional projector. Preserve exact executable bool for runtime
members; weights never executable. Reject duplicate case-insensitive names,
0-byte/nonregular members, invalid public hashes, >68 runtime members, >70 total
public members, or >5GiB total public bytes. Request-private bytes are accounted
by the staging/coordinator separately. Keep the existing 80-member native limit.

The public identity is SHA256 of canonical compact sorted-key JSON containing
schema=1, catalog_id, runtime_release, and the ordered selected members' name,
size, sha256 and executable flag; explicitly include vision=true/false. Paths,
mtime, process IDs, private input and exceptions are excluded. Recipe/protocol/
locale/request context are added by the later coordinator/cache layer, not here.

No result, busy/error path or context exception releases only one lease: use
ExitStack/context managers, unwind all acquired handles on any BaseException.
StoreBusy remains distinguishable from missing/corrupt/timeout/cancelled errors.

- [ ] Write RED tests using synthetic tiny catalog ZIP/model/projector managed
  stores, not downloaded model weights. Exercise returned content-free records,
  exact deterministic identity, text/vision membership and context lifetime.

```python
with attest_resources(resource, runtime, catalog, include_vision=True,
                      deadline=time.monotonic() + 10) as result:
    assert result.model_name == catalog_model.filename
    with pytest.raises(StoreBusy):
        with ResourceStore(resource, catalog.identity).lease():
            pass
    assert not can_open_selected_file_for_write(result.members[0].source)
# Both store leases are usable after the context exits.
```

- [ ] Cover wrong catalog identity, swapped/corrupt model/runtime after inventory
  but before pinning, wrong inventory root/release, missing store, a busy second
  lease, cancellation during hashing, deadline exhausted during inventory/hash,
  bool/overflow input, consumer exception and BaseException cleanup. Assert no
  arbitrary resource or path is accepted and no network/process API is called.
- [ ] Implement the minimal manager; run focused tests plus runtime inventory and
  managed resource/store tests with project Python. No real model/native launch.
- [ ] Diff check; commit only these two files; full RED/GREEN commands/output in
  `.superpowers/sdd/local-inference-resource-lease-report.md`.
