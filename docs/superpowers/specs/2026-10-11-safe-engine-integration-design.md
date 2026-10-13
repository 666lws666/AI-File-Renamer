# Verified native file movement — production integration design

## Authority and baseline

The Product Owner authorized continuing the confirmed directory-link escape
repair, keeping cross-volume moves disabled, preserving originals and failed
evidence, and integrating only after verification. This design implements that
approved safety behavior; it adds no naming/AI/UI feature and does not restore
cross-volume copying. Earlier autonomous execution authority applies to the
technical steps, not new product scope, publication or security permissions.

Active linked checkout: `.worktrees/ai-smart-naming`, `codex/local-privacy-mode`.
Verified standalone primitive checkpoint: `5a5c8e87379229d121604a069a290efc2c161830`.
Main checkout remains untouched. Existing failed native/old-engine evidence and
formal Golden files must remain unchanged.

## Selected approach and alternatives

Selected: carry immutable caller-authorized roots into the reviewed held-object
Windows transaction, persist the captured file identity, and consume truthful
results throughout Apply, Undo and history compensation. Native target collisions
are retried without replacement, bounded and bound to the first source identity.

A path-helper-only substitution is rejected: it would bless fresh historical
replacement files, discard uncertain counter/guard paths, and allow restart
reconciliation to clear a real recovery hold. Disabling every file action is a
safe fallback if integration cannot be verified, but is not the normal selected
delivery. Cross-volume movement itself remains explicitly disabled.

## Milestone boundaries

1. Evidence foundation: independently prove a frozen native identity and
   versioned history evidence contract, extending the already verified primitive.
   No executor/controller activation occurs in this milestone.
2. Coherent production integration: one source writer updates executor,
   preflight, Undo, worker outcomes and both managed durable consumers together.
   Root performs actual Windows file/race and full regression Gates before a
   checkpoint. There is no halfway application-level safety PASS.

The second milestone cannot silently omit recovery transport to reduce file
count. Production Watch activation, Auto Apply/self-events, local model/resource
preparation, privacy/model quality, manuals and final packaging remain separate
unfinished work. No final-project completion claim follows from this design.

## Evidence foundation contract

`src/core/rename_plan.py` owns frozen pure-value `NativeFileIdentity` and
`FileMoveEvidence` beside the existing `SourceFingerprint`. Construction and
validation perform no filesystem, native, network or credential operations.

```python
@dataclass(frozen=True)
class NativeFileIdentity:
    volume_serial: int
    file_index: int
    creation_ticks: int

@dataclass(frozen=True)
class FileMoveEvidence:
    version: int
    identity: NativeFileIdentity
    fingerprint: SourceFingerprint
    allowed_roots: tuple[str, ...]
```

Version is exact integer1. Volume serial is an exact integer0..2**32-1;
file index and creation ticks are exact integers0..2**64-1. Bool/coercion is
rejected. Fingerprint retains exact nonnegative integer fields. Roots are an
exact nonempty tuple of at most2000 unique nonempty NUL-free strings, each
at most4096characters. The native primitive still supplies strict lexical drive,
component, reparse, selected-root and guard validation before any mutation.
An explicit validation function rechecks the entire graph at serialization and
native admission; frozen dataclasses alone are not a hostile-input validator.
Deleted required fields and exact uninitialized objects are also rejected as
malformed graphs. Shared pure validators return stable ValueError; native
admission returns fixed INVALID_INPUT without native actions. No missing field
is defaulted or coerced into approval, even when another supplied proof is valid.

`SafeFileMoveResult` appends optional `source_identity`. `safe_move` accepts
`expected_fingerprint: SourceFingerprint | None = None` and optional keyword
`expected_identity: NativeFileIdentity | None = None`; at least one valid proof
must be supplied. Apply always supplies its original approved fingerprint;
identity-only admission is for historical Undo of the same legitimately edited
file. Any invalid supplied proof returns fixed INVALID_INPUT before native I/O.
After exclusive source opening, its held information supplies the identity;
an expected-identity mismatch (including saved creation ticks) returns
SOURCE_CHANGED before target guards or descendants. Across one uninterrupted
held-object rename, successful publication verifies the same volume/file index
and captured size/mtime fingerprint. Creation metadata is NOT required to remain
equal across that rename: the Product Owner explicitly approved this revision
after a real NTFS deleted-name tunneling reproduction. Capture the actual
post-rename creation ticks from that same held source, and return the updated
identity as the historical evidence for the next operation. A definite collision
returns its captured PRE-rename identity; a postpublication/cleanup uncertainty
returns only its last verified capture as diagnostic evidence, never authority
for automatic replay. Results never substitute a caller-supplied value as capture.
Existing public arguments/defaults/R4 ownership and all30 fault witnesses remain.

`RenameRecord` appends optional `move_evidence`. Explicit JSON serialization
stores a versioned dictionary with exact keys and the identity/fingerprint/root
graph; decoding rejects unsupported versions, malformed or coerced fields.
Records without that field stay readable with `None`, are not backfilled by stat,
and cannot authorize automatic historical Undo. They are preserved, not deleted.

### Limits, not exaggerated identity claims

Identity is held NTFS volume serial/file index/creation metadata, not content
hashing or timeless authentication. Windows documents possible file-ID reuse;
creation metadata is an additional pre-admission check, not an immutable
cryptographic secret. NTFS name tunneling can change creation metadata during a
rename while the held volume/fileID and fingerprint remain unchanged; preserving
the observed POST-rename value avoids false recovery and stale Undo evidence.
No creation-time restoration, registry/tunneling changes or other metadata-setting
workaround is permitted. Failed volume/fileID/fingerprint verification still
requires honest recovery with retained evidence.
The design protects the demonstrated replacement/TOCTOU paths and never claims
that hostile tampering with history, all metadata, the OS or another application
is cryptographically prevented. Same-volume NTFS remains the verified platform;
UNC, reparse traversals, other filesystems and cross-volume movement refuse.

## Trusted root admission

`PreflightService` snapshots its supplied root collection into an immutable tuple.
`WatchPreflightService.check` snapshots configs once; its result carries those
same roots. `PreflightResult` appends `allowed_roots: tuple[str, ...] = ()`.
The executor consumes that one result, never reevaluates configs or derives wider
authority from AI-generated targets, canonicalized links or a later helper call.

Containment checks remain a read-only early rejection, not the final race barrier.
Native admission uses the original approved lexical source/target spellings;
preflight realpath must not erase a junction spelling before the native check.
Existing duplicate roots are normalized/deduplicated without granting another
directory. Missing/invalid approval fails closed. Existing explicit user source
and target-parent compatibility policy in the worker is not expanded.

## Apply and atomic collision handling

Every real executor forward move uses `safe_move`; remove os.rename/EXDEV/shutil,
path mkdir, exists-based collision publication and raw exception/path error text.
Extension validation still precedes mutation. Only a definite
SAFE_MOVE_TARGET_OCCUPIED response may retry, at most1000 candidate names.
Bind all later attempts to the first native captured identity plus the original
approved fingerprint and root snapshot. A replaced source between retries must
not be freshly approved merely because size/mtime matches.

Suffixes are inserted before the COMPLETE nonempty supplied protected extension,
e.g. report_1.tar.gz, not report.tar_1.gz. For an empty extension, preserve the
existing observable dotted-name behavior (report_1.v2); never allow extension
substitution. Newly inserted occupied targets must remain byte-identical.
No retry/compensation follows native uncertainty.

Successful native proof is saved in RenameRecord with actual final target and
captured fingerprint/identity/roots. A history write failure may attempt only a
non-countered reverse safe move using that exact proof. If compensation succeeds,
report failed Apply with source restored ONLY after history is strictly proven
absent or that exact record has been durably marked rolled back/undone. Build the
record ID before append: an exception may occur after appending. History repair
must strictly parse and preserve unrelated records, never silently drop corrupt
lines. Record serialization precedes append; flush/fsync is required; a logging
exception after commit must not turn a committed append into a reported failure.
If compensation/history disposition fails or is uncertain, do not assert that
the old forward destination still contains the original; return false/recovery
with all known/uncertain source/destination/guard evidence. No stale degraded
success merely because the first move once succeeded.

## Historical Undo

UndoManager preserves reverse record/batch order and task/batch identity. It passes
the record's validated evidence to the executor and never marks a failed or
uncertain result undone. A legacy/no-proof record is explicitly refused with the
files and record untouched; callers do not manufacture replacement proof.

Legitimate content edits on the SAME recorded native file remain supported:
require the stored native identity, opening and capturing the current fingerprint
inside the exclusive native transaction without a path-stat reapproval. A
different file with identical size/mtime is refused. The
returned held fingerprint is transported to the UI instead of stat'ing a newly
replaceable returned path as the proof of success. Existing truthful completed
Undo/history-marker-save-failure behavior and per-record partial results remain.

## Recovery transport and durable consumers

Append immutable bounded `owned_residue_paths` and optional held proof fields to
BatchResult/FileOperationOutcome. Residues are exact unique tuples, at most8 local
paths of at most4096characters (one native result remains at most4; two known
forward/compensation evidence sets are deduplicated, never silently truncated).
Malformed outcomes cannot gain execution authority.
They are diagnostic evidence only, never a startup replay or deletion instruction.

Batch's versioned file-operation marker persists native recovery paths/known actual
target. Reconcile treats an existing native uncertain hold as sticky; pathname
presence/size/mtime alone cannot clear it, turn it into success or enable retry.
Watch's nested intent codec gains the corresponding supported version while old
version1 remains readable; recovery preserves the actual known successful target
and all reported residue candidates. Store failures retain original durable intent
and in-memory returned evidence, disable unsafe reuse and surface failure.

There is no crash-proof promise if the post-operation evidence write itself fails:
the original durable intent keeps a conservative manual recovery hold; counter
and guard candidates may require manual inspection. A pre-publication journal for
every counter would be separate work, not fabricated by this integration.

An unresolved original version1 Batch intent is therefore a conservative hold
on reload even when no newer recovery flag could be saved. Existence, size/mtime
or a nominal target's absence cannot prove a lost outcome harmless. A confirmed
completion must be durably published before that intent can disappear; old
version1 markers remain readable with their original six-key shape.

Fixed visible error keys must distinguish cross-volume blocked/original retained,
changed source, rejected unsafe path, occupied/exhausted collision, missing legacy
Undo proof and native recovery. No raw secrets/native exception text. Three locales
are updated for these errors, without Golden changes or UI redesign.

## Legacy routes and execution ownership

Default production uses FileOperationBackend/ManagedFileOperationLane and
RenameExecutor. Current src callsite inspection finds no active references to
legacy RenameEngine or organization_engine; they must not be selected as a
fallback. Their path-based functions are not claimed repaired by this milestone.
Any future supported legacy entry must first delegate to the verified boundary;
do not reactivate it as a workaround. Main/public startup stays unchanged.

## Required verification

Tests first, retained genuine REDs, one writer, frozen hashes, fresh scoped review
and root fresh Windows verification. Required physical witnesses: Apply same
volume and occupied target, actual C/D cross-volume refusal with source and named
streams retained, source replacement after preflight, replacement between atomic
collision attempts, target-root junction conversion, exact compound extension,
partial reverse Undo and same-size/mtime historical replacement refusal, history
save/rollback ordinary and uncertain outcomes, residue and sticky restart holds.
All fault hooks have outer witnesses proving the attempted mutation happened.

Reuse the existing isolated Qt6.12.0 guarded Python runtime. Native/source tests
must keep ordinary GC, real process exit/cleanup and forbidden-access counters.
No network, true keys/Credential Manager/private media/system-security changes.
Root full non-screenshot regression, unchanged formal M1/M0 screenshots with
UPDATE unset, acceptance and the exact production safety diagnostics follow.
The old ignored diagnostic files/raw failures remain unchanged. A changed helper
signature cannot be called a passing repair of a race that no longer executes;
new actual-boundary regressions explicitly execute the equivalent physical race.

## Primary API references

- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information
- https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/fltkernel/nf-fltkernel-fltgettunneledname
- Native rename/traversal/ownership references in the approved R4 standalone spec.

No merge, push, release, Golden update or product completion is authorized here.
