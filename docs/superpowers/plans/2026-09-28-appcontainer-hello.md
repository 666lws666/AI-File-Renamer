# Bounded native AppContainer startup diagnostic

This implements only the first actual-startup slice of the existing L1 plan,
not file/network-denial or model containment. Real local text/image inference
is operational; semantic refinements continue independently. Root may prepare
this independent startup prerequisite without treating incomplete naming or
network gates as passed. No product integration follows from hello success.

## Task: prepare identity, owned staging, native hello

Use existing codex/local-privacy-mode worktree. Own:
`scripts/local_probe_profile.py`, `tests/unit/test_local_probe_profile.py`,
new `scripts/local_appcontainer_probe.py`,
new `tests/unit/test_local_appcontainer_probe.py`,
new `scripts/native/AppContainerHello.cs`, and report
`docs/reports/2026-09-28-appcontainer-hello.md`.
Do not modify local_probe_security/process or naming runner/test, product, QML,
resources, Golden, settings or credentials. Root owns real execution and commits.

1. TDD profile `prepare() -> PreparedProfileIdentity(name,sid)` as an immutable
   result; new->prepared->active->closed. Only derive/string conversion/free in
   prepare, no Create/Delete; idempotent only in prepared state; active/closed
   reject. Entry from new remains compatible via prepare, entry from prepared
   uses that identity. Preserve collision nonownership and all allocator/error
   semantics. Failed release can be retried by explicit close; no forgotten
   allocation or inferred ownership. Existing profile tests must retain meaning.
2. New diagnostic CLI with no user-controlled arbitrary executable/SID/path:
   unique ignored QA run under tests/screenshots/qa-current/local-privacy/.
   Fixed trusted C# source emits only exact ASCII JSON protocol hello version1.
   Build x64 console EXE with installed
   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe (no install),
   using existing bounded supervisor; record source/compiler/EXE hashes. Build
   errors are failure, no alternate executable or uncontained negative fallback.
3. Persist bounded durable journal before profile creation: random ASCII
   xuxia_probe_<32lowerhex>, derived intended SID, run ID and exact owned paths.
   Journal state distinguishes intent/created/collision/cleanup_pending/completed.
   Flush and same-directory atomic replace. Intent/SID alone never authorizes
   restart deletion; no automatic restart cleanup or prefix search. Same live
   successful creator may close after journal write failure. Do not infer Create
   success from profile name existing.
4. Stage a real copy of built EXE in newly created task-owned directory, rejecting
   reparse ancestors/files, existing target and hard-link reuse; retain exact
   canonical paths, file identities/hashes. Apply a non-NULL protected DACL only
   to new directory/file: current user/SYSTEM management, exact package SID
   read/traverse/execute, no package write/delete/WRITE_DAC/WRITE_OWNER. No
   inherited All Application Packages grant. Handle-based ACL set/readback
   preferred, or protected creation security descriptors; verify readback and
   file identity before launch. No ancestor/original/model/Python ACL changes.
   Journal/output evidence does not grant package write. No broad permissions
   fallback if traversal prevents startup.
5. Ordinary positive control runs identical staged EXE and requires exact bounded
   hello JSON, exit0 and cleanup_complete. Then create owned profile and record
   creation. Run same EXE using existing AppContainerSecurity/profile SID and
   run_bounded with 15s bound, sanitized env, bounded stdout/stderr, parent token
   evidence. Require exact SID, IsAppContainer and zero capabilities from parent,
   exact hello JSON, exit0 and cleanup. Child self-report is not identity proof.
   No socket operations/network calls in this slice.
6. Never wrap launch unconditionally in `with profile`: incomplete process
   cleanup must retain profile/staging, record cleanup_pending and fail, not
   delete under uncertain process state. After confirmed child/Job cleanup,
   close security context, remove only verified explicitly owned staging/build
   objects and delete owned profile. Retain journal/raw evidence. Do not recurse
   broad roots or follow replaced links. Any cleanup failure is nonzero with
   exact pending ownership; no crash journal interpreted as authority to delete.
   Profile Delete S_OK does not prove universal storage absence: report this
   limitation explicitly; storage/path cleanup verification is a later gate.
7. TDD fake-boundary tests for prepare states/allocator failures, collision,
   journal failure, compiler/positive/contained failure, wrong token/hello,
   incomplete cleanup preserves owned objects, cleanup failure, path/ACL/hash
   rejection. Fake native APIs in unit tests; no real profiles/ACL edits/network
   by implementer. Pure protocol tests must exercise parser, not only source grep.
   Run profile/security/process/new diagnostic tests, report original RED/GREEN,
   freeze. Root reviews before invoking actual native CLI.

No package download, system security/firewall/loopback exemption changes, real
API/Key/Credential Manager, model execution, broad cleanup, push or release.
Root will record actual startup/cleanup evidence separately. NetworkIsolation
read-only inspection and real file/network permission tests remain separate.
