# File movement identity evidence implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One fresh sole source writer, then a fresh scoped task reviewer. Root owns public documents, Git and independent Gates; no simultaneous source writers.

**Goal:** Prove and persist held native identity needed by safe historical Undo and collision retries, without activating the old executor.

**Architecture:** Frozen pure identity/evidence graphs live beside SourceFingerprint. The already verified Windows primitive admits fingerprint and/or identity, always captures the opened object's metadata, and exposes it in its frozen result. RenameRecord explicitly encodes version1 evidence; absent legacy evidence stays absent.

**Tech Stack:** Windows Python3.14.5, existing Pydantic2/ctypes native boundary, existing isolated Qt6.12.0 guarded test runtime. No new dependency.

**Approved creation-metadata revision:** Product Owner approved the bounded
pre-admission/post-publication distinction after actual2failed/268passed runs.
Creation metadata remains a strict historical admission check, but the same held
file's creation time can change through native NTFS name tunneling during rename.
No OS settings or original metadata are changed to hide this behavior.

## Global constraints

- Active `.worktrees/ai-smart-naming`, `codex/local-privacy-mode`, source baseline `5a5c8e87379229d121604a069a290efc2c161830`. Read the evidence foundation and limits sections of `docs/superpowers/specs/2026-10-11-safe-engine-integration-design.md` fully.
- Cross-volume movement remains explicitly refused. Existing R4 held-relative traversal, NTFS restriction, guards, process-heap/quarantine and checked cleanup remain unchanged.
- Only source/test files listed below; no executor/preflight/Undo/backend/controllers/history/resources/UI/i18n/Provider/Golden/main/venv change. Root-owned documents/private ledger are not writer-owned.
- No network/cloud/model/API/key/Credential Manager/private files, system-security/ACL/firewall/privilege change, main merge, push/release or history rewrite.
- Ordinary scoped executor escalation only launches the existing approved isolated runtime after default setup-refresh failure. No new environment/runtime install.
- Writer runs focused/cover commands only, preserves RED outputs and freezes hashes; no broad/screenshots/acceptance/model tests or Git writes. Root does not run source/broad tests while writing.
- All30 R1/R4 controlled child ownership witnesses remain; no skips, rescue/reset, GC suppression, tolerance changes or forced process exit.
- Private report `.superpowers/sdd/file-move-evidence-report.md`; raw outputs only ignored `tests/screenshots/qa-current/local-privacy/` with `file-move-evidence` prefix. Existing failures remain untouched.

## Task 1: Pure evidence graph, held-native admission and explicit serialization

**Files:**
- Modify `src/core/rename_plan.py` — pure frozen values/validators/codecs only.
- Modify `src/core/safe_file_move.py` — optional expected identity/fingerprint and captured result only.
- Modify `src/models/rename_record.py` — optional explicit move_evidence serialization/validation.
- Modify `tests/unit/test_safe_file_move.py` — new real native identity cases, existing assertions unchanged.
- Create `tests/unit/test_file_move_evidence.py` — graph/serialization/no-I/O tests.

**Read first:** all five existing named source/test files, existing R4 public native design/plan, and the integration spec foundation. No engine activation is allowed in this task.

**Consumes:** existing SourceFingerprint, `_Info(attributes,volume,index,links,creation,access,write,fingerprint)`, held transaction/query and RenameRecord JSONL.

**Produces:** exact frozen NativeFileIdentity/FileMoveEvidence, graph validators and codecs below; optional `SafeFileMoveResult.source_identity`, and
`safe_move(source, destination, *, expected_fingerprint=None, expected_identity=None, allowed_roots, create_parents=True)`.

- [x] **Step 1: Genuine tests-first failures for missing evidence/admission.**

Start with these actual contract cases; new classes/functions must be obtained through module assertions so feature absence is unambiguous:

```python
def test_evidence_round_trip_and_legacy_default(tmp_path):
    import src.core.rename_plan as values
    from src.models.rename_record import RenameRecord
    assert hasattr(values, 'NativeFileIdentity'), 'native identity contract missing'
    assert hasattr(values, 'FileMoveEvidence'), 'move evidence contract missing'
    identity = values.NativeFileIdentity(7, 2**63 + 11, 133000000000000000)
    evidence = values.FileMoveEvidence(1, identity, values.SourceFingerprint(13, 99), (str(tmp_path),))
    rec = RenameRecord(task_id='synthetic', batch_id='b', old_path=tmp_path/'old.txt',
                       new_path=tmp_path/'new.txt', move_evidence=evidence)
    loaded = RenameRecord.from_json_line(rec.to_json_line())
    assert loaded.move_evidence == evidence
    legacy = RenameRecord(old_path=tmp_path/'legacy.txt', new_path=tmp_path/'legacy-new.txt')
    assert RenameRecord.from_json_line(legacy.to_json_line()).move_evidence is None

def test_native_identity_only_preserves_edits(tmp_path):
    import src.core.safe_file_move as move
    from src.core.rename_plan import SourceFingerprint
    src, target, restored = tmp_path/'one.txt', tmp_path/'two.txt', tmp_path/'three.txt'
    src.write_bytes(b'FIRST_SYNTHETIC')
    st = src.stat()
    first = move.safe_move(str(src), str(target), expected_fingerprint=SourceFingerprint(st.st_size,st.st_mtime_ns),
                           allowed_roots=(str(tmp_path),))
    assert first.success
    assert getattr(first,'source_identity',None) is not None, 'held identity not returned'
    target.write_bytes(b'LEGITIMATE_SAME_FILE_EDIT')
    expected = SourceFingerprint(target.stat().st_size,target.stat().st_mtime_ns)
    second = move.safe_move(str(target),str(restored),expected_identity=first.source_identity,
                            allowed_roots=(str(tmp_path),))
    assert second.success
    assert (second.source_identity.volume_serial,second.source_identity.file_index) == (
        first.source_identity.volume_serial,first.source_identity.file_index)
    assert second.source_fingerprint == expected
    assert restored.read_bytes() == b'LEGITIMATE_SAME_FILE_EDIT'
    assert not src.exists() and not target.exists()
```

Also tests for frozen fields/nested roots; bool/out-of-range/native subclass graph;
invalid fingerprint graph inside evidence; empty/list/duplicate/>2000/>4096/NUL
roots; JSON exact keys, integer versions, future/partial/coerced data; tampered
frozen objects revalidated before serialization/native I/O; large64-bit identity
JSON round trip. Construction/encode/decode cannot invoke open/stat/native/network.

Required fields removed using object.__delattr__ and exact uninitialized objects
created with object.__new__ are malformed graphs too. Each identity/fingerprint/
evidence field must reject with stable ValueError at pure serialization and fixed
INVALID_INPUT at native admission, zero native actions. The other valid proof
cannot override a malformed supplied proof. SourceFingerprint construction stays
unchanged; its strict trust-boundary validator is shared by evidence and native
admission. This corrects an incomplete literal example, not the strict contract.

Native cases use exact owned fixtures: initial native capture equals actual held
`_Info`; mismatch refuses before guard/target-descendant creation; source replaced
with same size+mtime after moving retained original cannot pass expected identity;
identity captured on a real occupied-target result; fingerprint-only original
calls still succeed; neither proof/invalid supplied proof gives INVALID_INPUT and
zero native actions; both supplied proofs are independently enforced. Saved
creation-tick mismatch BEFORE publication still refuses, before guards/descendants.
After publication, held volume/fileID/fingerprint mismatch remains recovery;
creation-only change captures the actual updated held identity and may succeed.
Outer hook witnesses must prove execution; no merely mocked historical
replacement proof. Original1485-line R4 tests remain unchanged. The earlier new
creation-invariance diagnostic/controlled expectation is superseded only by the
approved revision; retain its complete RED/raw evidence and physical witnesses.

Additional tests-first revised cases:
1. Parameterized postpublication volume,fileID,size,mtime corruption of returned
   held `_Info` AFTER a witnessed real rename: each must return recovery and
   retain source/destination candidates and actual original bytes.
2. Controlled creation-only returned `_Info` change AFTER a real rename: result
   identity must equal that post-query graph, not the old graph. Clearly label
   this as controlled response classification, not a real external metadata edit.
3. The existing25 real deleted-destination renames keep exact bytes and held
   volume/fileID/fingerprint; all must succeed and each returned identity equal
   the observed actual POST-rename `_Info`, regardless of whether this particular
   run changes creation ticks. Never assert that time changes must occur on every
   host/run; retain how many actual changes were observed, without test skipping.
4. Use each such returned identity for a second real identity-only move back to
   its original name. Observe both held admission and postpublication data; second
   result must capture its own actual POST value, with same object/bytes. The
   original-name tunnel may change creation again; it is not a failed Undo.
5. Wrong historical creation ticks on a real source must refuse before guard/
   rename/descendant actions, with actual source capture and original preserved.

Concrete negative-test injection, one field per parameter:
```python
changes={'volume':lambda i:{'volume':i.volume^1},
         'index':lambda i:{'index':i.index^1},
         'size':lambda i:{'fingerprint':SourceFingerprint(i.fingerprint.size_bytes+1,i.fingerprint.mtime_ns)},
         'mtime':lambda i:{'fingerprint':SourceFingerprint(i.fingerprint.size_bytes,i.fingerprint.mtime_ns+100)}}
# The existing actual publication hook sets published=[True]. The info hook
# delegates to the real query and uses dataclasses.replace ONLY for the held
# non-directory source AFTER that publication. Assert both hook witnesses,
# recovery, exact preserved destination bytes and source/destination residues.
```
Run the exact focused suite with these revised new tests BEFORE revising the
production check; preserve the new RED output as a separate prefixed artifact.

- [x] **Step 2: Run exact focused RED and retain actual output.**

```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_file_move_evidence.py tests/unit/test_safe_file_move.py
exit $LASTEXITCODE
```

Feature-absence/admission assertions must fail on unchanged source. A fixture or
launcher error is not a RED substitute; repair only that harness and rerun first.

- [x] **Step 3: Minimal pure values and explicit codecs.**

Insert the following contracts in rename_plan.py (no I/O or pydantic imports here):

```python
@dataclass(frozen=True)
class NativeFileIdentity:
    volume_serial: int
    file_index: int
    creation_ticks: int
    def __post_init__(self):
        validate_native_identity(self)

def validate_native_identity(value):
    if type(value) is not NativeFileIdentity:
        raise ValueError('invalid_native_file_identity')
    volume,index,creation=(getattr(value,field,None) for field in
                           ('volume_serial','file_index','creation_ticks'))
    if (type(volume) is not int or not 0 <= volume < 2**32
            or type(index) is not int or not 0 <= index < 2**64
            or type(creation) is not int or not 0 <= creation < 2**64):
        raise ValueError('invalid_native_file_identity')

def validate_source_fingerprint(value):
    if type(value) is not SourceFingerprint:
        raise ValueError('invalid_source_fingerprint')
    size,mtime=(getattr(value,field,None) for field in ('size_bytes','mtime_ns'))
    if type(size) is not int or size < 0 or type(mtime) is not int or mtime < 0:
        raise ValueError('invalid_source_fingerprint')

@dataclass(frozen=True)
class FileMoveEvidence:
    version: int
    identity: NativeFileIdentity
    fingerprint: SourceFingerprint
    allowed_roots: tuple[str, ...]
    def __post_init__(self):
        validate_move_evidence(self)

def validate_move_evidence(value):
    if type(value) is not FileMoveEvidence:
        raise ValueError('invalid_file_move_evidence')
    version=getattr(value,'version',None)
    if type(version) is not int or version != 1:
        raise ValueError('invalid_file_move_evidence')
    validate_native_identity(getattr(value,'identity',None))
    try:
        validate_source_fingerprint(getattr(value,'fingerprint',None))
    except ValueError:
        raise ValueError('invalid_file_move_evidence') from None
    roots=getattr(value,'allowed_roots',None)
    if (type(roots) is not tuple or not 1 <= len(roots) <= 2000
            or any(type(root) is not str or not root.strip() or len(root)>4096 or '\x00' in root for root in roots)
            or len({root.replace('/', '\\').casefold() for root in roots}) != len(roots)):
        raise ValueError('invalid_file_move_evidence')

def encode_move_evidence(value):
    validate_move_evidence(value)
    return {'version':value.version,
            'identity':{'volume_serial':value.identity.volume_serial,'file_index':value.identity.file_index,
                        'creation_ticks':value.identity.creation_ticks},
            'fingerprint':{'size_bytes':value.fingerprint.size_bytes,'mtime_ns':value.fingerprint.mtime_ns},
            'allowed_roots':list(value.allowed_roots)}

def decode_move_evidence(data):
    if (type(data) is not dict or data.keys() != {'version','identity','fingerprint','allowed_roots'}
            or type(data['identity']) is not dict
            or data['identity'].keys() != {'volume_serial','file_index','creation_ticks'}
            or type(data['fingerprint']) is not dict
            or data['fingerprint'].keys() != {'size_bytes','mtime_ns'}
            or type(data['allowed_roots']) is not list):
        raise ValueError('invalid_file_move_evidence')
    return FileMoveEvidence(data['version'],NativeFileIdentity(**data['identity']),
                            SourceFingerprint(**data['fingerprint']),tuple(data['allowed_roots']))
```

The validators are shared by constructors, codecs and actual boundaries, not
duplicated permissive parse paths. Existing SourceFingerprint constructors and
existing RenamePlan/BatchResult defaults remain unchanged in this task.

RenameRecord appends `move_evidence: FileMoveEvidence | None = None` and uses a
Pydantic before-field validator requiring None or an exact graph:

```python
@field_validator('move_evidence',mode='before')
@classmethod
def _validate_move_evidence(cls,value):
    if value is not None: validate_move_evidence(value)
    return value
```

Explicit JSON dictionary adds only:
```python
'move_evidence': None if self.move_evidence is None else encode_move_evidence(self.move_evidence)
```
Explicit decoder constructor adds only:
```python
move_evidence=None if d.get('move_evidence') is None else decode_move_evidence(d['move_evidence'])
```
Import validators/codecs from rename_plan, never safe_file_move; retain every old
record field and legacy missing-field defaults. Pydantic cannot coerce hostile
proof dictionaries/booleans into trusted evidence before the strict validator.

- [x] **Step 4: Held-native identity admission/capture without altering R4 ownership.**

Extend SafeFileMoveResult by optional `source_identity=None`. Add identity to the
transaction capture record. The public argument defaults and pure admission are:

```python
def safe_move(source,destination,*,expected_fingerprint=None,expected_identity=None,
              allowed_roots,create_parents=True):
    # Pure boundary before platform check/owner/native calls:
    # both provided proof graphs must validate; neither provided -> INVALID_INPUT.
    # _validate's fingerprint clause permits None only when identity is supplied.
    # R4 _validate paths/roots/flags and all remaining transaction steps are unchanged.
```

Concrete proof checks at the existing exclusively-held source `_Info` boundary:
```python
captured = original.fingerprint
captured_identity = NativeFileIdentity(original.volume,original.index,original.creation)
transaction.source_fingerprint = captured
transaction.source_identity = captured_identity
if ((expected_fingerprint is not None and captured != expected_fingerprint)
        or (expected_identity is not None and captured_identity != expected_identity)):
    raise _Changed()
```
Concrete successful publication verification:
```python
check = _info(source_handle)
if ((check.volume,check.index) != (original.volume,original.index)
        or check.fingerprint != captured):
    raise _Changed()
captured_identity = NativeFileIdentity(check.volume,check.index,check.creation)
transaction.source_identity = captured_identity
```
Each existing terminal result appends `source_identity=captured_identity`, with
None until the actual capture occurs. This is the PRE-rename value on definitive
collision/refusal and the verified POST-rename value on confirmed success. On
uncertainty it is only the last verified graph and diagnostic, not replay authority.
Early INVALID_INPUT/platform/admission refusals must not manufacture one.
Keep optional fingerprint input documented
as identity-backed Undo only; later executor Apply must always pass its approved
fingerprint. No new ownership/fallback/platform/reset logic is permitted.

- [x] **Step 5: Focused GREEN, exact covering suite, self-review and freeze.**

Run the focused command above, then:
```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_file_move_evidence.py tests/unit/test_safe_file_move.py tests/unit/test_rename_plan.py tests/unit/test_rename_executor.py tests/unit/test_undo_manager.py tests/unit/test_preflight_service.py tests/unit/test_processing_intent_store.py tests/unit/test_file_operation_backend.py
exit $LASTEXITCODE
```
Keep all30 actual child lock/normal-exit/bytes/reopenability/guard-cleanup witnesses
and original failures. Self-review exact ranges, serialization identity, no
side effects, no coercion, no old defaults changed, no native weakening.
Report every result/count/native exit/forbidden/actual atexit/concern, observed
creation transitions in the physical25rename/second-move case, and freeze
the five file SHA256s. Stop source writes. No task/project completion inference.

- [x] **Step 6: Root scoped review, independent focused Gate and exact checkpoint.**

Fresh reviewer gets this one task, report and complete diff file. Root verifies
complete requirements, actual fresh covering output, unchanged old engine/Golden/
main and frozen hashes. Root stages only the five source/test files plus this
root-owned plan/design, diffchecks and commits `feat: retain native file move evidence`.
No private QA/.superpowers/staging by worker, amend/main merge/push/newEXE.

After Task1 passes, root creates the separate coherent integration task from the
approved production design. Until that task passes, old production failures remain
open and the old engine is not claimed repaired. This is not a placeholder for
this evidence task: all interfaces and acceptance above must be fully implemented.

## Actual scoped completion evidence

Independent final Windows eight-file Gate:455passed,1existing skip,3existing
Pydantic warnings in17.34s; nativeexit0, forbidden-access attempts0, normal
MainThread-only atexit. All17R1+13R4 physical child witnesses exit0/lock32; real
25forward+25reverse operations capture actual POSTidentity, observed5creation
changes per direction in this run. No mandatory transition-count assertion.
Skip is file-symlink permission1314, not a weakened movement assertion.

Fresh scoped review:Spec compliant / Quality Approved after I1 missing-field
correction. The exact five frozen hashes independently match; original76300native
test bytes are unchanged. Engine/Undo/main/Golden remain unchanged. All earlier
REDs and first I1 GREEN's ready-file JSONDecodeError are retained; its timing
explanation remains unproven and tracked as a verification-maintenance concern.
This milestone does not certify the old production engine or entire application.
