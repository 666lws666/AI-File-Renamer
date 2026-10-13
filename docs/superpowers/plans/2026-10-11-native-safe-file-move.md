# Native safe file movement implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One fresh sole source writer, then a fresh scoped reviewer; root owns public documents, Git and frozen broad Gates. No concurrent source writers.

**Goal:** Build and prove an independently usable Windows non-overwriting file-move primitive that binds source/destination operations to held native objects.

**Architecture:** A worker-only pure-value API wraps one native SAME-VOLUME transaction. Rename uses an exclusive source and pinned destination-parent handle. The Product Owner explicitly approved refusing all cross-volume automatic moves with originals retained; there is no copy-only substitution or unsafe fallback. Uncertain completion remains owned recovery. No current engine integration in this milestone.

**Tech Stack:** Windows Python3.14.5, ctypes/wintypes Kernel32 and user-mode ntdll, existing SourceFingerprint, native synthetic C/D-volume fixtures, pytest under the existing isolated Qt6.12.0 guarded candidate (this module itself does not import Qt).

## Global constraints

- Active `.worktrees/ai-smart-naming`, `codex/local-privacy-mode`; current completed source6a8cf710353cad3d4c34f80fe701a17642032cee; design9828666b5dd094a19a17845f65022ad43d4df0d5.
- Read `docs/superpowers/specs/2026-10-11-native-safe-file-move-design.md` fully; exact result, input, no-reparse, same-volume/refusal, recovery and cleanup semantics there are mandatory.
- Only create `src/core/safe_file_move.py` and `tests/unit/test_safe_file_move.py`. Do not edit existing source/tests, engine/backend/controllers/models/persistence/resources/UI/i18n/providers/docs/Golden, main checkout or runtime environment.
- No cloud/model/API/key/Credential Manager, network probes, ACL/firewall/security changes, main merge, push/release or history rewrite. Ordinary scoped executor escalation is only to launch the approved isolated test runtime after default setup-refresh failure.
- Private report `.superpowers/sdd/native-safe-file-move-report.md`; raw native outputs may be saved with apply_patch only under ignored `tests/screenshots/qa-current/local-privacy/` with `native-safe-file-move` prefix. Existing QA diagnostics remain unchanged.
- Root runs no broad tests while the writer is active. Writer only targeted/covering commands below, then freezes both hashes. No Git writes. Root retains native exit, forbidden-access and actual cleanup evidence.
- Existing legacy engine diagnostics remain two failures until separate integration; no application-level fix, production Watch, Undo-history identity, inherited GC or final-project completion claim from this primitive.

## Task 1: Native safe-move contract (one coherent deliverable)

**Files:** create the two exact files above; private report only otherwise.

**Read first:** existing `src/core/rename_plan.py` (SourceFingerprint), `src/core/rename_executor.py`, `src/core/preflight_service.py`; fully read `src/core/processing_intent_store.py` as a reference, never import/edit its private replacement-enabled helper. Official native contracts in the design are implementation input, not a passing test. Existing private `test_native_move_boundary_diagnostic.py` and RED JSON establish the actual old-engine failures.

**Public interfaces produced:**
```python
from dataclasses import dataclass
from src.core.rename_plan import SourceFingerprint

@dataclass(frozen=True)
class SafeFileMoveResult:
    success: bool
    new_path: str = ""
    error_code: str = ""
    recovery_required: bool = False
    source_fingerprint: SourceFingerprint | None = None
    owned_residue_paths: tuple[str, ...] = ()

# Worker-only signature; implement every design step, not a stub:
# safe_move(source: str, destination: str, *,
#           expected_fingerprint: SourceFingerprint,
#           allowed_roots: tuple[str, ...],
#           create_parents: bool = True) -> SafeFileMoveResult
```

Use fixed keys for invalid graph/path/roots, unsupported platform/metadata, changed source, busy source, occupied target, ordinary move failure and uncertain recovery. Cross-volume refusal uses exact SAFE_MOVE_CROSS_VOLUME_BLOCKED, false success/recovery_required, empty new_path/residue and the admitted captured fingerprint. No raw native error text or input values in error_code. Win32 numeric errors can stay internal. Result success/ordinary failure/recovery invariants must be asserted in tests, including frozen immutability and captured fingerprint equality.

- [x] **Step 1: Write native positive and negative tests before implementation.**

Start with real same-volume bytes/mtime and collision protection:
```python
def fingerprint(path):
    info = path.stat()
    return SourceFingerprint(info.st_size, info.st_mtime_ns)

def test_same_volume_exact_move(tmp_path):
    src, dst = tmp_path / "source.txt", tmp_path / "提案-🌱.txt"
    src.write_bytes(b"SYNTHETIC_APPROVED")
    approved = fingerprint(src)
    result = safe_move(str(src), str(dst), expected_fingerprint=approved,
                       allowed_roots=(str(tmp_path),))
    assert result.success and not result.recovery_required
    assert result.new_path == str(dst) and result.error_code == ""
    assert result.source_fingerprint == approved and result.owned_residue_paths == ()
    assert not src.exists() and dst.read_bytes() == b"SYNTHETIC_APPROVED"
    assert fingerprint(dst) == approved

def test_occupied_target_is_preserved(tmp_path):
    src, dst = tmp_path / "source.txt", tmp_path / "occupied.txt"
    src.write_bytes(b"SOURCE"); dst.write_bytes(b"OCCUPIED")
    approved = fingerprint(src)
    result = safe_move(str(src), str(dst), expected_fingerprint=approved,
                       allowed_roots=(str(tmp_path),))
    assert not result.success and not result.recovery_required
    assert result.new_path == "" and result.owned_residue_paths == ()
    assert src.read_bytes() == b"SOURCE" and dst.read_bytes() == b"OCCUPIED"
```

Add actual two-volume fixture using pytest OS-temp as source and TemporaryDirectory below active `tests/screenshots/qa-current/local-privacy/` as target. Derive the workspace from this test file, not hard-coded install/user paths. Validate resolved temporary directory containment before recursive fixture cleanup, and assert different actual volume/st_dev values. No simulated EXDEV, system configuration or critical skip. Test explicit refusal for ordinary/zero-byte/>1MiB data, preserved source bytes/fingerprint/streams/links, untouched occupied target, absent target descendants and no candidate/copy/delete action. Source changed before admission still has its existing SOURCE_CHANGED priority.

The complete native matrix must additionally cover:
1. Exact input types, bool integers, malformed/empty/duplicate/>2000 roots, invalid fingerprint, relative/device/UNC/ADS/traversal/trailing-dot/space/reserved basenames and UTF-16 length; rejected graph opens no handles or directories.
2. Sibling-prefix escape, absent selected authorizing root, absent target descendants with create_parents False, validated child creation with True, wrong fingerprint before any target-directory creation, non-file source, source/ancestor reparse denial.
3. Actual native hook tests while handles are held: replacing/writing the source and renaming the selected parent fails, then real move still preserves original bytes. Retain the independent truly empty-directory 0x80/0x81 rename comparison. In the R4 transaction, attempt renaming the guarded selected target root to an owned sibling outside approved roots immediately before publication: actual denial32, approved-path bytes present and no escaped file. Attribute-only handles were actually insufficient; request FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES (0x81) without delete sharing, not an ACL/privilege change. After real rename the source parent must retain its guard and independently deny conversion/rename; it is not empty at that boundary. Hook assertions must have outer witnesses; swallowed assertions do not pass. Destination inserted immediately before native publication is never overwritten.
4. Actual named stream source and actual hardlinked source: same-volume content/identity behavior; cross-volume returns CROSS_VOLUME_BLOCKED without dropping source/stream/link data. Include actual late-ADS creation after source admission with original times restored, witnessed outside the caught callback; original and stream must survive. No stream-enumeration/copy implementation is retained under a rename-only contract. A reparse/junction fixture may be created only within the exact synthetic roots, without privilege/ACL changes; retain failures if native construction is unavailable rather than calling a mock native test PASS.
5. Cross-volume refusal must precede target-descendant creation, candidate opening, native content reads/writes, time-setting/flush, publication or disposition. Assert no such actions and no leaked handle, including when a destination is occupied. Keep original unsafe-copy and ADS REDs as history; remove superseded copy-success/fault tests from the CURRENT acceptance set with explicit report mapping, not skips or relaxed assertions.
6. Same-volume rename-before-raise has actual surviving bytes and returns recovery. Close/free/pending uncertainty ownership and all17 owned child process-release witnesses from R1 remain mandatory after same-volume fixture adaptation. Known-existing occupied files remain intact in every branch. No rollback/disposition or child-owned-handle rescue.
7. Normal and repeated failed transactions release every native handle. Actual temporary cleanup can finish; compare process handle counts with a explained small runtime allowance if measured, never disable GC or dispose unrelated objects. Restore monkeypatches and close synthetic external handles before fixture cleanup.

- [x] **Step 2: Run genuine RED and retain raw native evidence.**
```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_safe_file_move.py
exit $LASTEXITCODE
```
Expected missing-module/interface/contract RED on the unchanged source. Invalid test/launcher failures are separately retained and repaired before product edits, not substituted for valid RED. Do not run the entire tests/ tree.

- [x] **Step 3: Implement the held-object transaction and run GREEN.**

Concrete algorithm, with private native wrappers separated sufficiently for controlled fault testing (not public test-only callbacks):
```text
validate exact pure inputs and selected lexical roots -> fixed failure, zero I/O
open/pin source ancestors and source object, query attributes/identity/size/mtime
compare captured metadata to expected_fingerprint before making target descendants
pin existing selected target root WITHOUT creating descendants
  compare held volume identity with admitted source -> CROSS_VOLUME_BLOCKED if different
only on same volume create/pin approved missing descendants
  recheck held final target-parent volume -> CROSS_VOLUME_BLOCKED if different
non-replacing same-volume Nt class10 rename(handle, held_parent, relative_UTF16_name)
  query/retain exact captured identity/fingerprint; post-mutation uncertainty -> recovery
NO cross-volume copy, candidate, content read/write, source disposition or fallback
every handle close checked; failed cleanup/close -> fixed recovery and bounded residue paths
```
Native signatures use appropriate argtypes/restype and pointer-width handles. FILE_RENAME_INFORMATION buffer must handle non-BMP UTF-16 units, aligned header offsets and byte length; allocate at least sizeof(header)+encoded bytes, no Python-character count truncation. The actual identical-handle comparison retained Win32 relative-publication error87 and Nt class10 synchronous status0; use the documented user-mode Nt entry, not a path rename fallback. Typed IO_STATUS_BLOCK completion and returned NTSTATUS must both be checked; pending/unknown status must not report success. R1 process-heap/250ms/quarantine contract remains unchanged. Parent handles request LIST_DIRECTORY | READ_ATTRIBUTES | SYNCHRONIZE with FILE_SHARE_READ | FILE_SHARE_WRITE and no DELETE sharing, no source sharing, OPEN_REPARSE_POINT verification on held objects and replacement false for rename. R4's actual share-read-only compatibility run denied normal rename with error32 and remains retained. Sharing does not prevent attribute-only reparse conversion; R4 below supersedes absolute-path traversal and share-mask-only protection. No content-copy or exact-source-deletion path remains. Never reuse config replacement=True.

Run the same focused command, fix only demonstrated errors, retain every native run. Then cover the unchanged higher-level interfaces and persistence reference:
```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_safe_file_move.py tests/unit/test_rename_executor.py tests/unit/test_undo_manager.py tests/unit/test_preflight_service.py tests/unit/test_processing_intent_store.py tests/unit/test_file_operation_backend.py
exit $LASTEXITCODE
```
Root must verify these covering paths exist before dispatch; none may be silently omitted. Writer reports real counts, exits, forbidden attempts and actual atexit, native cases versus mocked faults, two frozen hashes and concerns. No broad/screenshots/acceptance/model Gates by writer.

- [x] **Step 4: Frozen primitive review and bounded root verification (production failures remain explicit below).**
Fresh scoped reviewer reads full design/brief/report, full new module/tests and old-engine contrast only as named context. Separate Spec/Quality verdicts; deterministic P0/P1 corrections use same sole writer and targeted RED first. Root then runs focused/cover, full non-screenshot, unchanged screenshots with UPDATE unset, guarded acceptance sequentially. Retain actual native exit0/forbidden0/cleanup and old baseline RED. Golden/main/frozen-hash/diff-check verification mandatory. Inherited GC concerns do not disappear from a green run.

### R1 correction inside Task 1: native uncertainty ownership

Independent frozen review found two completion/ownership defects and root's real
ADS diagnostic found a separate cross-volume data-loss defect. This R1 corrects
only the first two; it cannot complete Step4/5 until the ADS policy/architecture
also passes. Root's added specification section is binding and leaves the public
result unchanged. Source writer still owns only the two new module/test paths.

- [x] Add genuine RED tests for pending WAIT_FAILED/TIMEOUT, signaled-but-sentinel
  or pending IOSB, unknown informational return, success/IOSB mismatch, and
  exception after native submission. Assert recovery, retained exact operation
  buffers/handles, zero conflicting cleanup and subsequent valid-call refusal.
  Run uncertain cases in owned subprocesses so no reset/rescue path is invented.
- [x] Implement serialized transaction admission and one bounded process-lifetime
  quarantine. Use one `HeapAlloc(GetProcessHeap(), 8, byte_count)` allocation for
  typed IOSB plus aligned UTF-16 bytes. Register ownership before calling Nt;
  inspect one bounded 250ms wait and IOSB. Explicit free only on proven terminal
  nonpending completion. Unknown/pending/ambiguous free transfers ownership; no
  finalizer, atexit free, GC suppression, cancellation-as-completion or forced exit.

```text
pure graph validation and supported platform checks
lock -> existing quarantine ? fixed recovery rejection before native file I/O
owned transaction -> native allocation registered before Nt submission
negative nonpending Nt return -> proven rejected/terminal native operation
exact return0 + IOSB0 -> completion -> single checked native free
pending -> finite wait + IOSB inspection -> recovery, never success
unknown/mismatched/exception -> quarantine transaction/resources, no disposal
normal checked closes -> closed records; first ambiguous close -> retain record,
  stop remaining cleanup, quarantine, never retry/probe possibly reused value
unlock -> pure result; no public quarantine reset; only OS process exit resolves
```

- [x] Replace the test-only withheld-handle rescue with real child-process
  before-effect and after-effect close faults and heap-free ambiguity cases.
  Parent checks the actual child-held lock, signals normal exit, waits for process
  termination and then checks surviving bytes, reopenability and exact fixture
  cleanup. Simulated pending responses are labelled controlled faults; native
  process/lock/release witnesses are actual. Verify no retry or new I/O after
  quarantine and no new request receives unrelated old residue paths.
- [x] Run the exact focused and six-file covering commands above, retaining
  native exit, forbidden counters and atexit. Freeze new hashes and give separate
  I1/I2 outcomes while I3 remains FAIL. No full/Git/product completion claim.

R1 scoped evidence: writer focused172passed, six-file317passed/1existing skip/
3inherited warnings. Root independently reran the exact six-file cover:
317passed/1existing skip/3inherited warnings in10.33s, native exit0, forbidden0,
MainThread-only normal atexit. All17 owned fault children had real live sharing
denial32, normal exit0 and post-exit reopen/bytes/cleanup witnesses. Independent
R1 Spec compliant / Quality approved. These checked R1 items do not resolve the
actual late-ADS data-loss finding. The Product Owner has now explicitly approved
R2 refusal below; Steps4/5 remain pending until R2 is implemented and verified.

### R2 correction inside Task1: approved explicit cross-volume refusal

The Product Owner selected: "先明确阻止跨盘自动移动，保留原文件；安全方案验证后再恢复".
This supersedes the original cross-volume copy acceptance requirement, not the
retained original failing evidence. Same source/test ownership and no Git writes
by the sole implementer. No engine/controller/UI/main changes in this milestone.

- [x] Add tests-first fixed-key refusal, same-volume R1 fixture adaptation and
  actual post-admission ADS preservation; run the exact focused command as RED.

```python
def test_cross_volume_blocked_before_target_descendant_creation(tmp_path, second_volume, monkeypatch):
    src = tmp_path / "source.txt"
    src.write_bytes(b"SYNTHETIC_APPROVED")
    dst = second_volume / "absent" / "target.txt"
    approved = fingerprint(src)
    actions = []
    def forbidden_action(*args, **kwargs):
        actions.append(True)
        raise AssertionError("Cross-volume mutation is forbidden")
    monkeypatch.setattr(move, "_mkdir", forbidden_action)
    monkeypatch.setattr(move, "_rename", forbidden_action)
    result = invoke(src, dst, roots=(str(tmp_path), str(second_volume)), approved=approved)
    ordinary(result, "SAFE_MOVE_CROSS_VOLUME_BLOCKED")
    assert result.source_fingerprint == approved
    assert actions == [] and src.read_bytes() == b"SYNTHETIC_APPROVED"
    assert fingerprint(src) == approved and not dst.parent.exists()
```

Also assert no target-file open/content-copy/disposition action by instrumenting
the actual native boundaries used; do not merely check source strings or mock
the volume identity. Actual second-volume cases cover zero/ordinary/>1MiB data,
occupied target, ADS/hardlink source, missing descendants and repeat cleanup.
The preserved-time late-ADS test must create a real stream after source admission
at the target-root inspection boundary, before refusal; use the retained private
native diagnostic as a read-only reference, restore original times and assert
source/default bytes/ADS/fingerprint/target preservation outside caught hooks.

- [x] Implement the minimal exact held-root guard and remove rejected copying.

```python
# Inside _move_validated, after admitted source fingerprint matches, BEFORE
# creating missing descendants; exact helpers are already defined in this module.
target_authorizer = transaction.chain(target_root, target_root, create=False)
if _info(target_authorizer).volume != original.volume:
    raise _CrossVolumeBlocked()
target_parent = transaction.chain(ntpath.dirname(destination), target_root,
                                  create=create_parents)
if _info(target_parent).volume != original.volume:
    raise _CrossVolumeBlocked()
# _CrossVolumeBlocked is a private Exception, caught by _move_validated and
# mapped by _ordinary_key to exact SAFE_MOVE_CROSS_VOLUME_BLOCKED. Then only
# the existing same-volume _rename/held-info verification path can execute.
```

Remove the cross-volume else branch and unused copy/streams/disposition/time/
flush helpers and imports/constants. Do not retain an unsafe bypass, silently
copy, fall back to os.rename/shutil, expose a force option, or return success.
Keep R1 ownership/state/result semantics. Adapt all17 real R1 fault subprocesses
to same-volume source and a separate already-existing destination parent: after
actual rename, witness the locked destination and source absence; on definite
collision/pending-no-effect, witness the locked source and occupied/absent target.
An after-effect first target-parent close must still leave the file handle owned.
No rescue of child handles, skip or waiver of dynamic native lock/exit assertions.
Remove obsolete cross-volume success/copy-fault tests from current acceptance
with an explicit report mapping; retain their original evidence, not false PASS.

The adapted same-volume fixtures exposed a separate confirmed P1, not merely a
bad test: an attribute-only empty target-parent handle allowed its directory to
move outside the selected roots; the actual held-parent rename then moved the
source there while reporting the absent original approved path as success.
Retain R2-run-2 (10failed/173passed, native1/forbidden0) and its single-variable
native directory comparison (0x80 rename succeeds; 0x81 denies with error32).
Root authorized only the minimal 0x81 directory-open correction in the same two
files, alongside the cross-volume refusal. No added privileges/security changes.
Genuine escape regression, positive rename and all17 process-release witnesses
must pass before freezing; do not reinterpret this failure as a fixture waiver.

### R3 correction inside Task1: confirmed post-check junction conversion

After R2 froze, root's exact owned native diagnostic returned1failed/1passed and
then1failed/3passed (both native1/forbidden0/MainThread-only). An ordinary junction
control succeeded; converting the already checked empty target root before
descendant mkdir caused success at a linked approved spelling, source absence
and exact bytes outside selected roots. Native single-variable0x81 share3 versus
share1 comparison: writable conversion handle accepted versus denied32. Retain
both root raw outputs; R2 counts are historical, not proof this risk is closed.

- [x] Sole two-file writer adds a genuine formal native RED at the same boundary,
  with ordinary junction control, exact outside-root bytes/path witnesses and
  checked external-handle/link cleanup; do not import ignored QA helpers.
- [x] Share-mask-only correction is SUPERSEDED by R4 below. Formal native RED
  additionally established FILE_WRITE_ATTRIBUTES permits junction conversion;
  the GENERIC_WRITE sharing comparison does not prove containment. Preserve
  source and raw failures; do not relabel them as PASS or retry the same rejected
  comparison experiment. No source sharing change was applied in that run.
- [x] Focused and exact six-file cover pass with all17 child ownership witnesses;
  full self-review/frozen hashes, scoped independent review/root Gates below.

### R4 correction inside Task1: relative traversal and nonempty directory guards

User explicitly authorized continuing the confirmed directory-link repair with
cross-volume movement disabled, original files/failure evidence retained, and
verification before production integration. This is a technical correction to
the selected held-object architecture, not a new feature or silent same-parent
restriction. Read-only architecture review recommended relative traversal plus
ordinary owned guards. R2 source remains unchanged before this correction;
R3 tests expose actual failures. One invalid control expectation was corrected
to the observed legitimate attribute-writer behavior, not a weakened security
assertion. Original RED output remains retained.

**Sole writer:** only `src/core/safe_file_move.py` and
`tests/unit/test_safe_file_move.py`; root owns this public plan/spec and private
ledger. No writer Git operations. Fresh task brief:
`.superpowers/sdd/native-safe-file-move-R4-brief.md`.

**Private interfaces:** `_Transaction.open_child(parent, name, *, directory=False,
create=False, guard=False)` obtains a single-component handle; `_Transaction.guard
(parent, path, *, retain=False)` owns a create-only zero-content guard;
`_Transaction.release_guard(path)` performs its single checked close only after
a held child makes that intermediate parent nonempty; `_filesystem(handle)`
returns the bounded held-volume filesystem name; `_nt_create(request, access,
share, disposition, options)` is the injectable native submission boundary.
These are private implementation boundaries, never test-only public API.

- [x] Tests first: retain R3 controls/escape RED; add guard-acquisition-window,
  source admission, source-parent-after-rename, guard removal, collision and
  cleanup tests with outer physical witnesses. Explicit native action records
  prove there are no full-path descendant/source opens or path-based mkdirs.
  Native reparse helpers are fixture-only, exact owned directories and sibling
  targets; no security configuration or broader experiment.

```python
def test_before_guard_conversion_preserves_source_without_escaped_creation(tmp_path, monkeypatch):
    source_root, target_root = tmp_path / "source-root", tmp_path / "target-root"
    outside = tmp_path / "outside-approved-roots"
    for directory in (source_root, target_root, outside):
        directory.mkdir()
    src, dst = source_root / "source.txt", target_root / "child" / "target.txt"
    approved_bytes = b"OWNED_APPROVED_ONLY"
    src.write_bytes(approved_bytes)
    approved = fingerprint(src)
    attempts = []
    original_guard = move._Transaction.guard
    def attempt_before_guard(transaction, parent, path, **kwargs):
        if str(path).casefold() == str(target_root).casefold() and not attempts:
            attempts.append(_r3_owned_junction(target_root, outside, 0x100))
        return original_guard(transaction, parent, path, **kwargs)
    monkeypatch.setattr(move._Transaction, "guard", attempt_before_guard)
    result = invoke(src, dst, roots=(str(source_root), str(target_root)), approved=approved)
    try:
        assert attempts[0]["set"] is True
        assert not result.success and not result.recovery_required
        assert src.read_bytes() == approved_bytes and fingerprint(src) == approved
        assert list(outside.iterdir()) == []  # No guard, descendant or source escapes.
        assert not dst.exists()
    finally:
        if target_root.is_junction():
            os.rmdir(target_root)  # Only this exact owned link, never its target.
```

The source-after-publication regression must attempt ordinary owned junction
establishment against its newly otherwise-empty parent while the guard is held,
then prove denial, exact destination content and no surviving guard after normal
cleanup. Expected mutation denial may be directory-not-empty rather than a
sharing violation. Assertion changes must reflect the new independent defensive
mechanism and actual operation, not omit the attempted race or its physical proof.

- [x] Use the exact focused command as RED before product changes. In a bounded
  child prove the new relative/guard semantics on ordinary owned fixtures before
  relying on them to move a source. If the guard-acquisition window redirects an
  owned object, STOP with original retained and evidence; no path recheck waiver.

- [x] Implement only the revised native directory algorithm:

```text
pure validate -> absolute open of drive anchor only
each existing ancestor: held-parent + single basename NtCreateFile OPEN
  OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE, FILE_OPEN_REPARSE_POINT,
  synchronous nonalert + SYNCHRONIZE; verify held directory/non-reparse
source basename: held-relative OPEN, exclusive read/DELETE -> expected fingerprint
directory sharing: READ | WRITE, never DELETE; relative/guard tests prove containment
existing selected target root: relative OPEN chain -> actual volume comparison
different volume -> CROSS_VOLUME_BLOCKED, no guards/descendants/mutation
same volume -> held volume filesystem must equal NTFS before guard creation
source-parent guard: relative CREATE, exclusive, zero content, DELETE_ON_CLOSE
missing target child: protect approved parent with guard, recheck parent,
  single-component directory CREATE (collision -> refuse), obtain handle together
  verify child; release intermediate guard only once exact child is pinned
final-target-parent guard: retained through non-replacing rename and verification
source-parent and final-target-parent still protected -> existing Nt rename
verify exact file identity/fingerprint -> checked closes (guards disappear)
ambiguity -> quarantine requests/handles/guards, source/destination + guard evidence
```

Allocation for relative open contains all pointed-to native input/output storage
in one bounded process-heap object (<=2048bytes for <=255 UTF-16 units). Register
before submission; on proven success register the returned handle before freeing
the request. Exact status0/IOSB0 and expected OPENED1/CREATED2 information plus
valid handle are mandatory. Negative nonpending results without output handle
are terminal; pending/informational/mismatch/after-submission exception or free
ambiguity preserves heap/output slot/any handle for real process termination.
Do not call a native helper again or free an uncertain request. Relative CREATE
is never OPEN_IF/SUPERSEDE/OVERWRITE. Guard DELETE_ON_CLOSE applies only to the
new empty owned file, never source/user files. No access escalation, ACL, oplock,
security changes, background helper or fallback.

Guard files use `.xuxia-move-` + random fixed-length token + `.tmp`. A name
collision must refuse and leave the pre-existing object untouched, without a
retry loop. At most source-parent and current target-parent guards stay live;
normal exits close every owned guard. Recovery evidence has at most four unique
paths (source, destination and at most two guards); temporary intermediate
guard close uncertainty stops further operations rather than adding more guards.
Post-close records are never reprobed/reclosed, and the R1 quarantine is never
reset. Existing source/target file size/mtime/bytes/streams/hardlinks stay bound
to the original rename object. Directory metadata changes from guard creation
and removal are documented, not silently described as no filesystem writes.

R4 native run2 returned27failed/149passed, native1/forbidden0/MainThread-only:
READ-only directory sharing blocked ordinary publication with error32, including
the retained independent Win32/Nt compatibility witness. Restore READ|WRITE (no
DELETE) while retaining held-relative traversal and guards; this is not another
share-mask-only reparse comparison. Existing writer admission is legitimate if
guarded conversion is denied; separately require pre-guard conversion refusal.
Preserve all17 R1 child-fault assertions, including their four after-effect REDs
caused by the blocked publication. Generated guard paths are bounded<=4096 before
native submission; requests needing a guard at a bare drive anchor refuse.

Reuse one guard for the same held directory and make retain=True sticky: releasing
an intermediate target guard cannot release a retained source guard on an
overlapping path. After successful guard close, prove its exact directory entry
is absent using a relative OPEN on the still-held parent; known NOT_FOUND is the
proof, not CloseHandle success alone. Existing/delete-pending/uncertain results
stop later operations with recovery; no path unlink, closed-handle probe or
foreign-object deletion. Add actual external attribute-handle retention tests
and assert guard absence after normal return/process exit.

- [x] Add owned-subprocess relative-open uncertainty tests: pending, inconsistent
  output/IOSB/information, exception after submission, returned handle before
  free ambiguity and guard-close ambiguity. Observe real normal process exit
  and fixture cleanup; no Python-handle rescue/reset. Adapt existing R1 faults to
  inject at the rename request rather than accidentally at an earlier relative
  acquisition free. Preserve every original per-case assertion; account for new
  request allocations by operation kind instead of weakening ownership checks.
- [x] Focused and exact six-file cover pass, all17 original R1 child faults and
  added relative/guard ownership witnesses retained; freeze hashes and self-review.
  Root then fresh scoped review and all Gates below. No engine integration until
  that independent primitive Gate passes.

- [x] Run exact focused and six-file cover, retain all actual outputs/REDs and
  owned child/fixture cleanup, freeze both hashes, and stop source writes.
- [x] Independent scoped final R4 Spec/Quality review plus root fresh Gates below;
  only after approval mark this primitive complete and checkpoint exactly four
  public/source/test files. Existing unsafe production engine remains unmodified.

- [x] **Step 5: Exact standalone root checkpoint; production integration is the next separate milestone.**
Root stages only the two created source/test paths, this completed public plan and its root-owned compatibility/uncertainty/approved-refusal corrections in the public design; standalone cached diffcheck/identity check, commit `feat: add held-handle Windows file movement`. No checkpoint until explicit cross-volume refusal closes the selected-policy safety finding and native/root Gates pass. No private QA/report, other files, amend, main merge or push. Only this primitive is marked complete. Next separately designed milestone must integrate it into RenameExecutor/Undo and re-run actual old-engine failures, preserved extension/counter and caller contracts, and clear UI messages for cross-volume refusal; production Watch remains disabled until those safety prerequisites are satisfied.

Final scope calibration: independent scoped review approved the new primitive;
root323native cover and5238non-screenshot regression passed; tracked M1/M0
screenshots49+5passed/1designedskip and acceptance186/186 passed. All successful
processes native0/forbidden0/MainThread-only. The entire screenshot-directory
run also collected retained PRIVATE old-engine diagnostics and returned2failed/
66passed/1skip/86warnings. Those two unchanged production safety failures remain
FAIL, must close in the separate integration milestone and are not waived by
this standalone checkpoint. Neither overall project PASS nor production Apply/
Undo/Watch safety is claimed. The initial obsolete0.8DPI run failed40size checks;
current actual WindowsDPR1.0/logicalDPI96 passed without Golden/assertion changes.
