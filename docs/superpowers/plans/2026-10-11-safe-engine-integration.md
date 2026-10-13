# Verified safe movement production integration plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One fresh sole source writer for the coherent task, then a fresh task reviewer; root owns public docs/Git and frozen independent Gates. No halfway engine activation checkpoint.

**Goal:** Route actual approved Apply/Undo and history compensation through the verified non-overwriting Windows boundary, preserving historical identity and durable recovery evidence.

**Architecture:** Successful preflight exports one frozen lexical authorization snapshot. Native moves return captured identity/fingerprint; atomic collision retry stays bound to the first object. Versioned history and both managed durable consumers preserve actual outcomes and sticky uncertainty instead of reapproving a path.

**Tech Stack:** Existing Windows Python3.14.5/ctypes/Pydantic/Qt6.12.0 isolated guarded runtime, JSONL/history and metadata-only workspace/Watch queue. No new library.

**Creation metadata:** Consume the approved foundation revision: strict saved
identity before mutation; volume/fileID/fingerprint verification across the held
rename; capture actual POST-rename creation metadata for the next Undo proof.
Definite occupied-target attempts return PRE-rename capture. Creation-time
tunneling must not cause stale evidence or bypass historical pre-admission.
No timestamp/OS setting change is permitted. The coherent engine task adds a
real forward-to-recently-deleted-name then identity-only historical Undo case;
each move's captured POST identity must travel in its outcome/history evidence.

## Global constraints

- Task requires the completed, reviewed and root-checkpointed `2026-10-11-file-move-evidence.md` foundation before source writes. Root must supply the actual baseline hash in the extracted brief; do not invent or use a historical one.
- Read the complete `docs/superpowers/specs/2026-10-11-safe-engine-integration-design.md`; cross-volume movement remains refused with originals retained; no copy/delete/os.rename/shutil/platform fallback, unproven rollback, new legacy entry or production Watch activation.
- Only listed source/tests. Root docs/ledger/Git/private QA preservation are not writer-owned. Do not modify main checkout, formal Golden, config/Provider/model/resource/AI behavior, runtime dependencies, security settings, firewall/ACL/privileges or user shortcut.
- No cloud/network/model/API/key/Credential Manager/private files, push/release/main merge/history rewrite. All native inputs are owned synthetic Windows fixtures.
- One writer; root source/broad tests stop until freeze. Writer runs focused/cover only with the exact existing guarded runtime. Normal GC, native exit, actual forbidden-access/atexit/child cleanup are mandatory.
- Preserve all old failed evidence/private diagnostic files unchanged. Changed helper signatures cannot prove an old race passed; new formal tests must execute the physical attack at the actual boundary and assert an outer witness.
- Private report `.superpowers/sdd/safe-engine-integration-report.md`; returned raw outputs only ignored qa-current/local-privacy with `safe-engine-integration` prefix; never overwrite old failure artifacts.

## Task 1: Complete engine, historical Undo and recovery transport

**Owned source files (14):**
- `src/core/rename_plan.py`: PreflightResult snapshot and BatchResult evidence fields.
- `src/core/preflight_service.py`: frozen roots, same successful snapshot export.
- `src/core/rename_executor.py`: exclusive native forward/collision/Undo/compensation, fixed errors.
- `src/core/undo_manager.py`: evidence argument and complete outcome propagation.
- `src/core/rename_history.py`: fsync/strict targeted rollback disposition, no logging-after-commit ambiguity.
- `src/services/file_operation_backend.py`: immutable outcome fields, no post-Undo path stat.
- `src/controllers/batch_file_operations.py`: explicit approved roots, versioned residue marker and sticky reconcile.
- `src/controllers/managed_watch_file_operations.py`: matching counters, bounded outcome evidence/durable holds.
- `src/core/watch_review_queue.py`: nested intent version2 codec, version1 compatibility.
- `src/utils/i18n/locales/zh_CN.json`, `zh_HK.json`, `en_US.json`: fixed safe reason translations only.
- `src/core/safe_file_move.py`: only its module docstring changes from standalone/not-integrated to the actual worker boundary; native implementation frozen by foundation.
- `src/controllers/batch_workspace_controller.py`: only if actual load/save projection otherwise drops the new nested marker; inspect first, preserve opaque fields if already supported. No AI/resource/UI behavior change.

**Owned tests:**
- Modify `tests/unit/test_rename_executor.py`, `test_undo_manager.py`, `test_preflight_service.py`, `test_rename_plan.py`, `test_file_operation_backend.py`, `test_watch_file_operation_persistence.py`.
- Modify `tests/integration/test_managed_batch_file_operations.py`, `test_managed_watch_file_operations.py`.
- Create `tests/unit/test_safe_engine_native_boundaries.py` for genuine same/cross-volume/race/history cases.
- Foundation native/graph tests remain unchanged; include them in cover. Never modify their ownership/physical proof to accommodate integration.

**Read first:** complete owned sources/tests, source foundation values and primitive, the design and existing exact production bootstrap composition. Legacy RenameEngine/organization/history.undo_batch remain outside source ownership and cannot be called as fallback. Model evidence code is already provided by the foundation, not rewritten.

### Exact produced/consumed interfaces

```python
# Appended values; old positional fields/defaults remain compatible.
PreflightResult.allowed_roots: tuple[str,...] = ()
BatchResult.move_evidence: FileMoveEvidence | None = None
BatchResult.source_fingerprint: SourceFingerprint | None = None
BatchResult.owned_residue_paths: tuple[str,...] = ()
FileOperationOutcome.source_identity: NativeFileIdentity | None = None
FileOperationOutcome.owned_residue_paths: tuple[str,...] = ()

# Mandatory authority for actual Undo. No inferred roots or fresh-stat proof.
RenameExecutor.undo_move(src, dst, *, evidence: FileMoveEvidence) -> BatchResult

# Strict metadata-only disposition after confirmed physical compensation.
RenameHistory.finalize_rolled_back_record(record: RenameRecord) -> None
```

Preserve old FileOperationOutcome.source_fingerprint; use held captured fingerprint
from BatchResult. All residue tuples are exact/unique and <=8 strings each<=4096;
one native result remains<=4. No unbounded merge, silent truncation or raw error.
No result is authority to replay/clean up files.

- [x] **Step 1: Real native and pure contract regressions BEFORE source.**

Add these actual native cases; old helper signature may be called with two args
on RED, but the wrapper must accept **kwargs on GREEN and outer assertions prove
the attempt happened, not just that a TypeError stopped execution:

```python
def test_replacement_after_preflight_is_not_moved(tmp_path,monkeypatch):
    import src.core.rename_executor as module
    from src.core.preflight_service import PreflightService
    from src.core.rename_plan import RenamePlan,SourceFingerprint
    src,dst,retained=tmp_path/'old.txt',tmp_path/'new.txt',tmp_path/'retained.txt'
    src.write_bytes(b'APPROVED')
    st=src.stat()
    plan=RenamePlan('task',str(src),SourceFingerprint(st.st_size,st.st_mtime_ns),dst.name,str(tmp_path),'.txt')
    real=module._safe_move
    attempted=[]
    def attack(source,target,**approval):
        os.rename(source,retained)
        Path(source).write_bytes(b'UNAPPROVED_REPLACEMENT')
        attempted.append(True)
        return real(source,target,**approval)
    monkeypatch.setattr(module,'_safe_move',attack)
    result=module.RenameExecutor(PreflightService([str(tmp_path)])).execute([plan],'batch')[0]
    assert attempted==[True]
    assert not result.success and not result.recovery_required
    assert retained.read_bytes()==b'APPROVED'
    assert src.read_bytes()==b'UNAPPROVED_REPLACEMENT' and not dst.exists()
```

The old two-argument helper can be preserved as a **fail-closed no-proof refusal**,
but actual executor calls pass explicit proof/roots. It may never derive authority
from two arbitrary paths or use a platform fallback. Private old diagnostics stay
unchanged and are not substituted for the above new actually-executed attack.

Additional mandatory native matrix (not mocked volumes/IO):
1. Real C/D refusal for plain/occupied/absent-descendant/named-stream sources,
   original bytes/stream/fingerprint untouched, zero target-descendant/move/copy action.
2. Target junction installed at the real move seam: ordinary owned control,
   outer construction witness, refusal, original preserved and outside empty;
   native held-directory conversion behavior still covered by frozen R4 tests.
3. Real target insertion immediately before `_rename`: occupied bytes survive,
   next candidate succeeds, identity carried forward; replaced original between
   occupied attempts with same size/mtime is refused and retained original survives.
4. `.tar.gz` preserved as a whole; empty-extension `report.v2` retains existing
   `report_1.v2` behavior. Length overflow/exhaustion fails without truncation,
   no destructive overwrite and no retry after uncertain result.
5. Real partial Apply/reverse partial Undo, returned task/batch IDs and only exact
   successful history IDs marked; same original file edited content may Undo;
   same-size/mtime replacement historical file cannot. Legacy record without
   evidence remains untouched/unmarked and explicitly refused.
6. History raise before append, append-then-raise, rollback refused by occupied
   old path/replaced target, and rename-then-error uncertainty. Check physical
   bytes/locations, exact retained record disposition, false/recovery vs known
   physical Undo success, no stale successful path and no accidental deletion.
7. Metadata-codec roundtrip/tamper/unsupported version; native numbered-target
   recovery paths persist and stay held after Batch/Watch reload; existence/mtime
   equality cannot clear native uncertainty. Save failure retains original intent
   plus in-memory evidence, blocks retry/Undo/replay, no duplicate publication.

No skip or AST-only assertion replaces these dynamic checks. Existing fault spies
that accept two args must be intentionally upgraded to evidence **kwargs while
retaining their exact physical/partial-result assertions. Old tests demanding
shutil fallback or unconditional degraded success are superseded unsafe policy
expectations; document mapping and preserve their original evidence.

- [x] **Step 2: Retain genuine focused RED.**

```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_safe_engine_native_boundaries.py tests/unit/test_rename_executor.py tests/unit/test_undo_manager.py tests/unit/test_preflight_service.py tests/unit/test_file_operation_backend.py tests/unit/test_watch_file_operation_persistence.py tests/integration/test_managed_batch_file_operations.py tests/integration/test_managed_watch_file_operations.py
exit $LASTEXITCODE
```
If any named covering path is missing, stop and report; never omit it silently.
Launcher/fixture errors are separate from behavioral RED and repaired before source.

- [x] **Step 3: Frozen preflight snapshots and forward native execution.**

Preflight copies caller values and deduplicates lexical comparison without
realpath-resolving the approved roots. Check uses the immutable snapshot once.
Executable PreflightResult carries the exact tuple; existing realpath fields
remain diagnostic only. Watch configs are evaluated once per check.
Executor refuses empty/malformed approval even if can_execute=True and calls the
native boundary with ORIGINAL lexical paths and this snapshot.

Concrete counter decomposition (complete name remains protected):
```python
def _counter_name(name,extension,counter):
    if extension:
        stem,suffix=name[:-len(extension)],name[-len(extension):]
    else:
        stem,suffix=os.path.splitext(name)  # preserved existing dotted-empty compatibility
    return f'{stem}_{counter}{suffix}'
```
Run validate_filename for each generated name; no guessed protected suffix,
truncation or names from raw model paths. At most1000 candidates total.

Concrete execution algorithm:
```python
identity=None
for attempt in range(1000):
    name=plan.target_name if attempt==0 else _counter_name(plan.target_name,plan.extension,attempt)
    # Validate name; failure is fixed invalid-name/exhaustion, never truncate.
    target=os.path.join(plan.target_parent,name)
    native=_safe_move(plan.source_path,target,expected_fingerprint=plan.source_fingerprint,
                      expected_identity=identity,allowed_roots=pf.allowed_roots)
    if native.success:
        # source_identity is the verified POST-rename held capture, not old proof.
        evidence=FileMoveEvidence(1,native.source_identity,native.source_fingerprint,pf.allowed_roots)
        return BatchResult(plan.task_id,batch_id,True,new_path=native.new_path,
                           move_evidence=evidence,source_fingerprint=native.source_fingerprint)
    if native.error_code=='SAFE_MOVE_TARGET_OCCUPIED' and not native.recovery_required:
        if identity is None: identity=native.source_identity
        # Invalid/missing capture is recovery, never newly sampled approval.
        continue
    # Complete exact fixed-code map; no fallback/retry/rollback on uncertainty.
    return _native_failure(plan.task_id,batch_id,native)
# Exact exhaustion key fileops.error.targetOccupied with source retained.
```
The `_safe_move` wrapper returns SafeFileMoveResult; it never mutates without
explicit proof/roots. `_native_failure` has this complete fixed-code behavior:
```python
_NATIVE_ERRORS={
    'SAFE_MOVE_CROSS_VOLUME_BLOCKED':'fileops.error.crossVolumeBlocked',
    'SAFE_MOVE_SOURCE_CHANGED':'fileops.error.sourceChanged',
    'SAFE_MOVE_SOURCE_BUSY':'fileops.error.sourceBusy',
    'SAFE_MOVE_TARGET_OCCUPIED':'fileops.error.targetOccupied',
    'SAFE_MOVE_INVALID_INPUT':'fileops.error.unsafePath',
    'SAFE_MOVE_INVALID_ROOT':'fileops.error.unsafePath',
    'SAFE_MOVE_UNSUPPORTED_METADATA':'fileops.error.unsafePath',
    'SAFE_MOVE_UNSUPPORTED_PLATFORM':'fileops.error.unsafePath',
    'SAFE_MOVE_MOVE_FAILED':'fileops.error.unsafePath',
}
def _native_failure(task_id,batch_id,native):
    return BatchResult(task_id,batch_id,False,
        error=('fileops.error.nativeRecovery' if native.recovery_required else
               _NATIVE_ERRORS.get(native.error_code,'fileops.error.unsafePath')),
        recovery_required=native.recovery_required,
        source_fingerprint=native.source_fingerprint,
        owned_residue_paths=native.owned_residue_paths)
```
No raw native exception strings, shutil, final stat/mkdir/exists loop or os.rename
in executor. Validate native capture types before constructing success/collision
evidence; invalid capture is false/recovery, not fresh-stat reapproval.
Guard/source identity behavior is supplied by frozen native implementation.

- [x] **Step 4: Strict history disposition and truthful compensation.**

Construct record ID/evidence BEFORE `history.record`. Keep exact record task/batch/
source/actual final destination and file_size=captured.size_bytes. record serializes
first, appends under lock, flushes/fsyncs and closes; safely swallowed logging
failure occurs only AFTER proven persistence, never as an ambiguous append error.

Concrete compensation state machine:
```text
native forward PASS -> record(candidate_id,captured evidence)
  record PASS -> actual success
  record exception -> ONE safe reverse using exact identity+captured fp+same roots
    reverse PASS -> finalize_rolled_back_record(candidate record)
      strict disposition PASS -> false, empty new_path, historyRollback key, no recovery
      disposition FAIL -> false+recovery; exact old/actual target retained as evidence
    reverse definite FAIL or uncertain -> false+recovery; no stale forward success
      merge actual old/forward target + native residues, <=8unique; never truncate
```
Strict finalize holds history lock, reads/parses EVERY nonblank line without
dropping any corrupt line, validates matching exact record ID/paths/batch/proof,
marks only that record undone if present, serializes complete candidate and uses
flush/fsync/atomic replace. If exact ID is absent after strict read, no invalidation
write is needed. An unreadable/corrupt/different same-ID row, write/replace failure
or ambiguous commit returns/raises fixed failure; bytes/evidence are preserved.
Do not reuse `_get_all_unlocked`'s permissive skip behavior for this repair.
Use the same strict read for mark_records_undone rewrite so unrelated corrupted
raw evidence cannot disappear. Normal getter compatibility can remain read-only.

- [x] **Step 5: Identity-backed Undo and immutable worker outcomes.**

UndoManager passes `evidence=rec.move_evidence`, validated; absent evidence is
fileops.error.undoEvidenceMissing, zero file mutation. It preserves task/batch,
success/error/new_path/recovery/fingerprint/residue rather than rebuilding only
three fields. Successful IDs only enter marking; existing OSError marker failure
continues physical success+recovery. Programming errors still surface.

Concrete native Undo:
```python
validate_move_evidence(evidence)
native=_safe_move(src,dst,expected_identity=evidence.identity,
                  allowed_roots=evidence.allowed_roots,create_parents=False)
# No apply-time fingerprint equality, fresh path stat, counter or replacement.
# Return exact captured fingerprint/evidence/residue or fixed native failure.
```
For a confirmed historical identity, optional fingerprint is omitted so same-file
edits work. Undo's successful evidence uses its own actual POST-rename identity
(creation time may tunnel again), not the original Apply identity. Backend removes
post-Undo os.stat; confirmed native captured fingerprint
travels directly through immutable FileOperationOutcome. Invalid/missing proof
on claimed success is recovery, not freshly read evidence.

- [x] **Step 6: Persist bounded evidence and never clear native recovery by existence.**

Batch and Watch normal admission retain their original version1 marker; evidence
recovery emits nested version2 with these exact additional fields:
```text
Batch marker keys: original6 + knownResultPath:str + recoveryPaths:list[str] + recoveryReason:str
Watch intent dataclass: existing6 + known_result_path:str='' + owned_residue_paths:tuple[str,...]=() + recovery_reason:str=''
```
Batch `version`=2 when new fields exist; Watch nested version=2; oldversion1 must
encode/decode/load unchanged. Batch knownResultPath means last confirmed result,
NOT a promise about current location after uncertain compensation. Watch same.
Nested Watch JSON uses list for owned_residue_paths; strict graph decoder restores
tuple. Same queue schema3 is sufficient because nested intent is already versioned;
older readers reject intent2 fail-closed. Reject partial/unknown/coerced/malformed
recovery graph; length<=8 unique bounded strings, fixed nonsecret reason.

At outcome reception validate the complete graph before persistence. Persist
numbered candidate/guard paths and any known successful new_path. For completed
Undo marker-save failure, retain actual source fingerprint/path and recovery; for
uncertain native result do not invent APPLIED/UNDONE or drop the marker.

Batch reconcile FIRST checks existing native recovery flag/evidence-bearing
version2 reason: keep sticky hold/marker/paths without exists/stat-based downgrade,
without automatic retry/Undo, and without native move calls. Watch reload and
restore_interrupted preserve the same graph. Store failure keeps original durable
intent, in-memory returned evidence, locks row and reports persistence recovery.
It does not provide crash-atomic preservation of evidence whose write failed.

An unresolved original version1 Batch intent must also remain held on reload:
the original durable intent is the fallback when a newer recovery save failed.
Do not clear it using original existence/fingerprint or nominal target absence;
only durably published completion removes it. Preserve version1's six-key shape.
Do not add startup replay or automated residue deletion.

Counter validation in managed Watch matches the engine policy, including full
supplied compound extension and old dotted-empty behavior; reject arbitrary
sibling names/leading-zero/nonpositive counters/protected extension changes.
Batch emits explicit tuple roots from selected target/source parents at the
already trusted user action; no newly derived model/organization authority.

- [x] **Step 7: Fixed three-language error text, no UI/Golden changes.**

Produced keys:
```text
fileops.error.crossVolumeBlocked: Cross-volume moves are disabled. The original file was kept.
fileops.error.sourceChanged: The source file changed or was replaced. No rename was performed.
fileops.error.sourceBusy: The source file is in use. Close other programs and retry.
fileops.error.unsafePath: The path or directory link could not be safely verified. No move was performed.
fileops.error.targetOccupied: No free target name could be safely reserved. The original file was kept.
fileops.error.undoEvidenceMissing: This older record lacks identity evidence. Automatic Undo is unavailable; the file was kept.
fileops.error.nativeRecovery: The file operation could not be confirmed. Do not retry; inspect the retained recovery paths.
fileops.error.historyRollback: History could not be saved. The original file was restored.
```
Write concise accurate Simplified Chinese/Hong Kong Traditional Chinese versions
with exactly the same meaning. Unknown unsupported/native errors use unsafePath
or nativeRecovery according to certainty; no path/Key/native exception leakage.
Do not claim a no-mutation outcome for post-publication uncertainty.

- [x] **Step 8: GREEN/cover, self-review and complete freeze.**

Focused command above must pass; then exact covering command:
```powershell
& '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\venv\Scripts\python.exe' -B '.\tests\screenshots\qa-current\local-privacy\qt612-candidate\run_guarded_pytest.py' tests/unit/test_file_move_evidence.py tests/unit/test_safe_file_move.py tests/unit/test_safe_engine_native_boundaries.py tests/unit/test_rename_plan.py tests/unit/test_preflight_service.py tests/unit/test_rename_executor.py tests/unit/test_undo_manager.py tests/unit/test_file_operation_backend.py tests/unit/test_watch_file_operation_persistence.py tests/integration/test_managed_batch_file_operations.py tests/integration/test_managed_watch_file_operations.py tests/unit/test_processing_intent_store.py
exit $LASTEXITCODE
```
Self-review every spec item and source/test file. Report explicit RED/GREEN counts,
raw commands/exits/forbidden/atexit, physically verified versus controlled faults,
old expectation mapping and all limitations. Freeze all changed hashes and stop
source writes. No broad suite/Git/product-safety PASS by writer.

- [x] **Step 9: Root fresh scoped review and actual production safety Gates.**

Independent verification correction scope (2026-10-11): retain all failed raw
results. Permit only the exact fingerprint-change preflight's fixed reason,
two M7 spies' explicit proof-keyword contract and conservative unknown-effect
expectations (raw legacy classifier controls retained), and atomic completed-file
publication of test-only R1/R4/consumer ready JSON. This test-file exception does
not alter the frozen native implementation, parent physical assertions, case
counts, wait limits, GC or permissions. Named additions are
`tests/integration/test_fault_injection_m7.py` and test-only publication helpers
in `tests/unit/test_safe_file_move.py`; the existing engine/native boundary tests
cover new negative controls. Full-pipeline and packaging tests remain unchanged.
Old EXE resource mismatch is reported, not repaired or hidden by this task.

Reviewer reads complete task brief/report/full diff plus required named context;
distinct Spec and Quality verdict. Root verifies frozen hashes and actual Windows
same/cross/native race/partial Undo/history/recovery witnesses; complete nonshots,
formal unchanged M1/M0, acceptance, full screenshot-directory result honestly
classified. Old ignored stale-seam diagnostics may now be invalid for the changed
contract; retain their actual outputs and do not call errors or dead hooks PASS.
New active-boundary physical tests are mandatory evidence for safety closure.
Any deterministic P0/P1 gets one combined tests-first correction wave.

- [x] **Step 10: Exact reviewed local checkpoint only.**

Root alone stages named actual changed source/tests plus completed root-owned
plan/spec, cached diffcheck, correct identity and commit `fix: enforce verified native file operations`.
No private artifacts/main merge/push/Golden/newEXE. Standalone legacy APIs, full
production Watch/local privacy/resources/model/manual/package remain explicitly
unfinished; only the tested actual native engine/managed manual result boundary
is marked repaired. No hidden safety waiver or whole-product completion claim.

## Actual verification disposition — source checkpoint only (2026-10-11)

The completed checkboxes record this bounded source task and execution/classification
of its required checks. They do not declare every wider suite or old packaged
artifact passing, do not activate production Watch, and do not approve release.
R4 task review reports Spec compliant and Quality approved; I1/I2/I3 are closed.
All28 frozen source/test controls matched in root's final independent check.

| Root check on final frozen source | Actual result | Disposition |
| --- | --- | --- |
| Exact14-file Windows physical/contract cover |730 passed,1 skipped,3 warnings; exit0 | Scoped safety cover passed; Windows1314 symlink case untested |
| Complete non-screenshot tests |1 failed,5473 passed,3 skipped,4 warnings; exit1 | NOT an all-green suite; sole failure is old packaged locale/source mismatch |
| Unchanged formal M1/M0 screenshots |54 passed,1 skipped,86 warnings; exit0 | Passed with UPDATE disabled; update-mode skip and Pillow deprecations retained |
| Entire screenshot directory including historical private diagnostics |1 failed,67 passed,1 skipped,86 warnings; exit1 | Old two-argument replacement spy fails before its body; not a physical safety witness |
| Existing acceptance script |186/186,0 failed; exit0 | Existing checks passed, not real AI semantics or current-package delivery |

Initial cached diffcheck rejected one extra EOF blank line in this new plan and
the new native test. Only those blank lines were removed; no definition, assertion
or product source changed. The added real engine/history/Undo case was rerun after
formatting:1 passed,3 inherited warnings, normal exit0/forbidden0/MainThread-only.
Both the initial formatting failure and later corrected check are retained.

The final cover independently executed all32 native ownership/lock child cases:
actual lock32, native exit0 and forbidden0, with unchanged parent cleanup/reopen
assertions. Its added engine/history/deleted-name case executed two real moves,
transported exact held POST evidence through JSONL/reload, used saved identity-only
Undo with zero fresh path stats, restored the original bytes, and marked only the
selected record. In that added case creation ticks did not change; the separate
native25+25 matrix observed3 forward/3 reverse creation transitions in this root
cover. These are distinct observations, not a universal transition promise.

Every final guarded parent test command exited normally with MainThread-only
atexit and forbidden-access count0. The old failed readiness/full/raw diagnostics
remain failed and preserved; later corrected runs do not rewrite them. No formal
Golden, main checkout, shortcut, old EXE, native implementation body, system
settings, real credentials or cloud/API call was changed by this task.

The old private two-argument helper/spy is deliberately retained as historical
evidence, not updated or counted as a live replacement attack. New formal native
regressions reached the proof-bearing move seam and asserted actual physical
bytes/locations. The packaged-language comparison likewise stays unchanged and
failing: old dist resources are not silently copied from source or rebuilt here.

Only the named reviewed source/tests plus this plan/design are checkpointed.
Private report/raw artifacts remain untracked/ignored and are not committed.
Legacy helpers, production Watch activation, local model quality/privacy/resource
flows, manuals and a newly built Windows application remain separate unfinished
items. Whole-project/packaging/release approval remains absent.
