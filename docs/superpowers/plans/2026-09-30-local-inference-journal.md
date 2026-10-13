# Local Inference Recovery Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Refuse a second or restarted local inference while a previous owned run
has no durable clean completion, without adopting processes or deleting by path.

**Architecture:** One content-free, bounded record in a dedicated ResourceStore
root, leased for the service lifetime. The pinned record is written and fsynced
before native side effects, and marked clean only after exact-owner cleanup.
Interrupted or malformed writes fail closed; no fallback to an older clean copy.

**Tech Stack:** Python standard library, existing Windows ResourceStore pins and
exclusive lease, strict JSON validation, pytest fault injection.

## Global Constraints

- No process/profile creation, PID reopening, recursive cleanup, downloads,
  API/key/Credential Manager, private files, security setting changes, QML/Golden,
  main checkout, merge or push. The journal never executes cleanup itself.
- No raw text, user paths, prompts, schema, stdout/stderr, file-content hashes,
  filenames or model results in the record, error text, logs or repr.
- Reuse ResourceStore; do not copy Win32 pinning or release a pin then mutate by
  pathname. Existing resource-store implementation stays read-only in this task.
- A crash-interrupted write may require explicit recovery. Do not promise atomic
  rollback, silently reset invalid records, or infer ownership from durable JSON.

## Task 1: Bounded content-free active-run journal

Files: create `src/services/local_ai/inference_journal.py` and
`tests/unit/test_local_inference_journal.py`.

### Stable API

```python
class InferenceRecoveryRequired(RuntimeError): ...  # fixed reason code only
class InferenceJournalError(RuntimeError): ...     # fixed reason code only

@dataclass(frozen=True, slots=True)
class InferenceRunRecord:
    revision: int
    run_id: str | None
    phase: str  # clean or active
    catalog_id: str | None
    profile_name: str | None
    package_sid: str | None
    stage_name: str | None
    stage_identity: tuple[int, int] | None

class LocalInferenceJournal:
    def __init__(self, root: Path): ...
    @contextmanager
    def lease(self, *, create: bool = True):
        yield self
    @property
    def record(self) -> InferenceRunRecord: ...
    def begin(self, *, catalog_id: str, profile_name: str,
              package_sid: str) -> InferenceRunRecord: ...
    def attach_stage(self, run_id: str, *, name: str,
                     identity: tuple[int, int]) -> InferenceRunRecord: ...
    def complete(self, run_id: str) -> InferenceRunRecord: ...
```

Use the fixed managed-store namespace `xuxia-local-inference-journal-v1` and
basename `inference-run.json`. The caller supplies one dedicated state root, not
a resource-cache root. The native private `stage_<32 lowercase hex>` directories
will be children of this state root; journal code does not create these children.

Hold ResourceStore.lease() and one writable pinned journal handle for the entire
lease context. Constructor/import does no I/O. Multiple instances/processes using
the same root must get StoreBusy, not simultaneously believe they are clean.
Release all acquired journal/store handles when the lease context exits; this
does not mark an active run clean. Coordinator keeps that context alive while any
native ownership is unresolved, and never treats Python context exit as cleanup.

On lease entry, allow only the store marker and journal file in the root.
Unexpected children (including old stage directories) cause RECOVERY_REQUIRED;
do not inspect their contents, adopt them, remove or rename them. A missing
journal may be created only when the marker is the sole existing child. Existing
empty/truncated/bad journal is not a missing journal. New state starts revision=0,
phase=clean and all optional ownership fields null.

The serialized object has exactly `schema_version` (integer1, not bool) plus the
eight fields in InferenceRunRecord. Max4096 UTF8 bytes, strict duplicate-key and
nonfinite rejection, strict types/bounds, no unknown fields. Revision is an actual
int in [0,2**63-1]. Active run_id/profile suffix must be the same32 lowercase hex;
catalog_id is64 lowercase hex; profile_name is `xuxia_local_` plus run_id;
package_sid must match an AppContainer `S-1-15-2-` followed by seven valid uint32
decimal subauthorities (no leading zeros except zero). Stage name is null or
`stage_` plus32 lowercase hex; identity null iff name null, else two actual ints
(volume0..2**32-1, file ID1..2**64-1). Clean initial record has all optionals null;
clean completed records retain their validated public ownership metadata. Reject
all other combinations. Reopening any valid active record returns
RECOVERY_REQUIRED before native operations can occur.

begin requires an active lease and clean record, validates all inputs and root
children before writes, increments revision (refuse overflow), and derives run_id
from profile_name. attach_stage requires the exact active run_id, attaches once
(an identical repeated call is a no-op; conflicting metadata is rejected), and
increments revision. complete requires that exact active run_id and an otherwise
empty state root (only marker/journal); it increments revision and writes clean.
The later coordinator calls complete only after process/stage/profile owners have
all confirmed cleanup. No boolean supplied by a UI can bypass that ordering.
Repeated complete for the same already-clean run is an idempotent no-op; other
run IDs cannot complete it. Calls outside the lease or incompatible phase fail.

Writing uses only the existing pinned handle: seek0, write the complete bounded
UTF8 bytes with short-write detection, truncate to exact new length, flush, fsync.
Update the in-memory record only after all steps succeed. Do not first truncate
the old record. A write/flush/fsync failure latches JOURNAL_WRITE_FAILED within
this lease and refuses further begin/attach/complete; no native side effects may
start after failed begin. Retain previous in-memory record for diagnostics, but
it is not proof that disk was unchanged. The coordinator retains native owners
and reports recovery required after terminal-write failure. On restart malformed
bytes/active state/unexpected residue remain closed, not reset. An OS-confirmed
clean record written after actual cleanup is safe even if a later fsync reported
failure; no pending run is hidden by taking an older snapshot.

This deliberately replaces the earlier design sketch's generic 'atomic journal'
phrase with a specific bounded, pinned, crash-fail-closed protocol. It does not
change the separate settings/configuration atomic-save requirements.

- [ ] Write RED tests for new/clean reopen, active reopen refusal, exact revision
  progression, idempotence and lease exclusion using tiny synthetic records.

```python
with LocalInferenceJournal(root).lease() as journal:
    current = journal.begin(catalog_id=catalog_id, profile_name=profile_name,
                            package_sid=package_sid)
    assert current.phase == 'active'
with pytest.raises(InferenceRecoveryRequired):
    with LocalInferenceJournal(root).lease():
        pytest.fail('an unfinished run must never be admitted')
```

- [ ] Fault-inject write/short-write/truncate/flush/fsync separately. Check no
  candidate record is published on failure, no subsequent begin succeeds, and a
  fresh lease rejects all malformed/active disk outcomes. Exercise existing empty
  file, oversized/deep/duplicate JSON, invalid SID/UUID/bool/identity/revision,
  unexpected root file/directory, stale run ID, false stage metadata and unknown
  version. A fake process/profile API that raises if called proves none is used.
- [ ] Implement canonical pinned serialization and fixed errors. Tests also prove
  no secret marker appears in file/error/repr and no arbitrary path is accepted.
- [ ] Run new tests and managed resource/store tests in project Python; diff check;
  commit only the two files. Record full RED/GREEN/commands in
  `.superpowers/sdd/local-inference-journal-report.md`.
