# AppContainer hello diagnostic — PARTIAL, frozen before native staging

Task brief: `docs/superpowers/plans/2026-09-28-appcontainer-hello.md`.
Implementation report written 2026-09-29. No commit made by implementer.

## Current outcome

Only brief item 1, the profile prepare lifecycle, is implemented and tested.
The native hello diagnostic is **not implemented or ready for execution**.
Root explicitly requested a freeze at this safe point while a separate bounded
naming correction is completed. This is not an AppContainer startup pass,
network-denial pass, privacy pass, or product-integration gate.

Modified owned files:

- `scripts/local_probe_profile.py`
- `tests/unit/test_local_probe_profile.py`
- This report.

Not created: `scripts/local_appcontainer_probe.py`,
`tests/unit/test_local_appcontainer_probe.py`,
`scripts/native/AppContainerHello.cs`.
No security/process helper, naming source/test/report, product, QML, resource,
Golden, settings, credential, or model file was edited by this implementer.

## Implemented lifecycle

`PreparedProfileIdentity(name, sid)` is a frozen dataclass. The new `prepare()`
derives and converts the intended SID and releases temporary allocations before
returning. It does not create or delete a profile. It returns the same immutable
identity on repeated calls only while prepared; active/closed states reject it.

Lifecycle: `new -> prepared -> active -> closed`. Entry from `new` calls
`prepare()` for compatibility. Entry from `prepared` uses the previously derived
identity and does not derive again. Failed preparation closes the lifecycle;
failed frees remain recorded and can be retried with explicit `close()`.
Closing an unentered prepared context never creates or deletes a profile.

Existing creation ownership remains based only on a witnessed Create S_OK.
Collision never becomes ownership; failed delete/free remains retryable. Existing
tests were preserved rather than weakened. A prepared identity or future journal
intent is not deletion authority.

## Original RED / GREEN evidence

Interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`.
Working directory: `D:\文件AI-AGENT\.worktrees\ai-smart-naming`.

1. Added tests before implementation, then ran:
   `python -m pytest tests/unit/test_local_probe_profile.py -q`.
   Result: **4 failed, 66 passed in 0.25s**, exit 1.
   All four failures were the expected assertion
   `prepare lifecycle is not implemented`, not import/syntax failures.
2. Implemented immutable identity and prepare lifecycle; same command:
   **70 passed in 0.15s**, exit 0.
3. Fresh freeze regression command:
   `python -m pytest tests/unit/test_local_probe_profile.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_process.py -q`.
   Result: **201 passed in 2.73s**, exit 0.

The profile suite forbids real native DLL loading. Its new four cases cover
immutable/idempotent preparation, prepared entry without re-derivation,
active/closed rejection, prepared close without creation/deletion, and SID/string
free failures retaining allocations until explicit close.

Precision about combined verification: the existing process suite is not wholly
fake-native. It includes ordinary Windows child/job/pipe lifecycle tests and some
SID conversion calls. Running that existing suite did not run a new diagnostic,
create/delete a real AppContainer profile, modify ACLs, run a contained hello,
load a model, or perform a network test. No new native mutation path was executed.

## Remaining work and review boundary

Root independently reran the same three suites: `201 passed in 2.77s`.
Scoped Part1 review: spec compliant, no Critical/Important issue; minor coverage
note is direct prepare-specific derive/conversion exception tests (existing
entry-from-new tests already exercise this shared path). No claim about the
unimplemented native filesystem/hello boundary follows from this checkpoint.

Brief items 2–7 remain pending apart from the profile-specific tests above:

- Fixed trusted C# ASCII JSON hello and bounded x64 compiler invocation, source /
  compiler / output identity evidence; no alternate executable fallback.
- Bounded atomic durable ownership journal with intent / created / collision /
  cleanup_pending / completed states. Never infer restart deletion authority.
- Owned staging with reparse-ancestor rejection, no target reuse/hard links,
  exact canonical identities and hashes, protected non-NULL DACL containing only
  current-user/SYSTEM management and exact-package read/traverse/execute.
- Meaningful fake-native tests of ACL/file-handle boundaries, including readback
  and identity checks through launch and deletion; orchestration-only success
  fakes would be insufficient evidence for this boundary.
- Ordinary positive control and contained launch using existing bounded process
  supervisor; parent token evidence, exact protocol, exit 0, complete cleanup.
- Incomplete-process-cleanup retention, explicit verified-object cleanup,
  collision/journal/compiler/hello/token/path/ACL/hash/cleanup-failure coverage.

The native filesystem layer requires additional reviewed Win32 bindings for
protected object creation, handle identity, ACL readback, handle lifetime/share
modes, and deletion. Existing profile/security/process helpers do not provide
that layer. The implementer escalated this scope before writing staging code;
root then instructed this freeze. No placeholder implementation or fake claim of
native success has been added.

Even future DeleteAppContainerProfile S_OK would not prove universal removal of
profile storage artifacts. Storage/path cleanup verification and actual file /
network-denial tests are later gates. Root owns review, future native execution,
and any commits. Continue only on an explicit follow-up; preserve this partial
change and the unrelated worktree changes.
