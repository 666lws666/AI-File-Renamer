# Owned fixed-probe staging: implementation handoff

Date: 2026-09-29. Status: implementation and isolated unit verification complete;
**native staging and contained execution have NOT been run by this task**.

## Scope and files

Added only:

- `scripts/local_probe_stage.py`
- `tests/unit/test_local_probe_stage.py`
- This report.

No existing profile, security, process, hello, model, naming or product file was
modified. No profile was created or removed; no actual ACL was changed; no actual
stager, executable or model was run. No commit/push/integration was performed.
Read-only official API/source lookup was explicitly permitted by the root agent.
No runtime network/cloud call, download or dependency installation was added.

## Trusted interface and ownership

`stage_probe(parent, package_sid, compiled_bytes, expected_sha256)` returns a
thread-confined `OwnedProbe`. Caller bytes must be exact `bytes`, nonempty and at
most 4 MiB, with a matching canonical lowercase SHA-256. The SID must be an exact
canonical package SID with seven uint32 package subauthorities. Input validation
precedes native binding initialization or other native calls.

Only a bounded absolute DOS-drive local path is accepted. UNC/device namespaces,
relative paths, traversal, alternate streams, ambiguous trailing dots/spaces,
reserved DOS names and control characters are rejected. Parent length is capped
at 180 characters, leaving the fixed random child names below legacy MAX_PATH.
The adapter permits fixed local NTFS only; ReFS/removable/remote types fail closed.

The owner pins each existing ancestor, including volume root, using nofollow
directory opens without delete sharing. It validates directory/disk type, absence
of reparse attributes, volume/file ID, one link and canonical final path. No
ancestor ACL is modified. These checks can fail due to host access restrictions;
there is no repair/fallback path.

The owner creates one random `stage_<32 lowercase hex>` directory and one
exclusive `hello.exe`. Both receive a protected, present, non-NULL DACL at
creation: exactly current-user full control, SYSTEM full control, and the exact
package SID read/execute (`0x1200A9`). ACE inheritance flags are zero. Readback
requires the exact owner, protection/presence flags and three basic allow ACEs;
extra, inherited, missing, broader or unsupported ACE forms fail closed.

`StageError.owner` retains partial live ownership and any acquired handles. Its
message is a fixed stage code, not a native exception message. Uncertain paths
remain labeled uncertain and receive no automatic deletion authority. The caller
must retain this owner: there is no context manager, destructor cleanup, restart
adoption, directory scanning or journal implementation.

## Explicit acquisition/transition boundary

`CreateDirectory` does not return a handle or atomic object identity. Root
explicitly approved the following initial acquisition under the narrow threat
model: this live exclusive create succeeds, then an immediate nofollow pinned
open verifies exact type/owner/protected DACL and records identity. At this point
no child is running. Failure, collision, reparse detection, unexpected security
or failed ancestor validation leaves the directory uncertain and never deletes
it automatically. This is **not** an atomic proof against a malicious same-user
administrator replacing an identically secured object in that initial gap.

The EXE uses `CREATE_NEW` with a real returned handle, not a link or copy-by-name.
Its same-object bytes are written, flushed, size/link count/hash/security checked,
then the writer is closed while its parent remains pinned. A compatible
`GENERIC_READ` pin is reopened with `FILE_SHARE_READ` only and all identity,
hash and ACL checks repeated. No write-access EXE handle remains for future
image launch. Any failed transition is uncertain, not adopted.

`recheck()` repeats ancestor identity/type checks and owned directory security
plus EXE identity/size/link/hash/security checks. Frozen evidence contains only
bounded owned paths, object IDs, digest, size, link count and security facts.
It does not certify successful child access or successful containment.

## Cleanup semantics

Only `cleanup(child_cleanup_confirmed=True)` permits deletion. False, integer
1, strings and other non-bools retain the owner and report pending. No child
process is managed here; the future orchestrator owns the truth of this signal.

Cleanup closes/reacquires a DELETE-capable handle under retained parent pins,
verifies the exact prior identity, type, link count, path and ACL, and uses
handle-based disposition. It never unlinks a name, recurses, deletes an ancestor,
or follows unexpected descendants. File failure stops parent deletion. A
nonempty directory fails native disposition and remains pending.

Close/disposition failures retain explicit state and can be retried. A successful
disposition followed by failed close retries the retained handle rather than
reopening a delete-pending path. Success also requires read-only absence
confirmation: only FILE_NOT_FOUND/PATH_NOT_FOUND counts. Deferred deletion from
an outstanding external read handle is pending; access denied is not absence.
All owned and ancestor handles must have closed before success is reported.

`close_only()` explicitly releases pins without issuing new dispositions and
reports remaining/uncertain paths; it permanently relinquishes automatic cleanup
authority. If a disposition was already issued by an earlier confirmed cleanup,
closing its handle can finish that pending deletion; the report only marks it
removed after absence confirmation. No operation cancels an issued disposition.

File/directory handles are detached raw integers, not retained PyHANDLE objects.
This avoids PyHANDLE destructor closes while a child might be alive and preserves
the handle value after close failure. Dropping the live owner leaks pins until
process exit intentionally; orchestrator retention is required. Other code must
not close these private handles or concurrently mutate this owner.

## Source-backed contracts versus OS evidence

Installed pywin32 metadata reports version **312**. Required exported wrappers
were checked by attribute inspection only. The sole real pywin32 test constructs
and reads an in-memory security descriptor; it changes no filesystem object.

- [pywin32 b312 win32file source](https://raw.githubusercontent.com/mhammond/pywin32/b312/win32/src/win32file.i): verified creation/open wrappers, handle-info tuple indexes, synchronous read/write return contracts, final-path wrapper, and Boolean `FileDispositionInfo` input. There is no handwritten ctypes structure ABI here.
- [pywin32 b312 handle source](https://raw.githubusercontent.com/mhammond/pywin32/b312/win32/src/PyHANDLE.cpp): verified Detach and raw-integer close support. PyHANDLE automatic closure and zeroing after failed Close motivated explicit raw ownership, covered by regression tests.
- [pywin32 b312 API source](https://raw.githubusercontent.com/mhammond/pywin32/b312/win32/src/win32apimodule.cpp): volume serial is exposed via signed C long; adapter normalizes it to uint32 to match handle information.
- [Microsoft CreateDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw): creation descriptor and no-handle-return limitation.
- [Microsoft file security/access](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights) and [handle-based disposition](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle): the planned access/cleanup contracts, not evidence that this implementation works natively on this host.

The helper does not construct an AppContainer access-check token, so a package
SID alone does not prove the eventual child's effective traverse access through
existing host ancestors. An ancestry-related future launch failure must remain
a reported failure; there is no ancestor ACL repair. Staging alone proves neither
network denial nor file denial. Arbitrary same-user/admin security changes,
process death and journal/restart recovery are outside this implementation.

## Verification record

Interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`.
Working directory: `D:\文件AI-AGENT\.worktrees\ai-smart-naming`.

1. Initial RED: 53 failures, all because the helper was not implemented.
2. Initial GREEN: 53 passed.
3. Deferred-deletion regression RED: 1 failed, 59 passed; GREEN: 60 passed.
4. PyHANDLE/signed-serial regressions RED: 2 failed, 60 passed; GREEN: 62 passed.
5. Required combined regression command:

   ```text
   D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_stage.py tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py -q --tb=short
   ```

   Result: **285 passed in 3.38s**, exit 0.

Coverage includes input-before-native calls, security descriptor roundtrip and
strict ACL readback, creation/share/nofollow flags, ancestor reparse/filesystem
rejection, collisions, partial writes, flush/read/hash/link failures, writer-pin
transition uncertainty, prelaunch tampering, strict child-cleanup confirmation,
delete/close retry including post-disposition close failure, delayed removal,
replacement objects, unexpected descendants, close-only reporting and lazy import.

Native smoke, full security review, actual ancestor compatibility, real image
launch sharing, real handle disposition/absence behavior, commits and any later
profile execution remain root-owned follow-up work. No native success is claimed.

## Review correction wave: acquisition retry and entropy lifetime

Two Important review findings were reproduced and fixed within the same three
owned files; no native effects or commits were performed.

1. Cleanup's DELETE reopen previously treated a native acquisition failure as
   permanent uncertainty. It now preserves the previously established identity
   when no handle was acquired and allows a later reacquisition attempt. Every
   acquired handle still undergoes full path/type/link/identity/security checks
   before disposition. An acquired but unverifiable or different object remains
   uncertain and is never adopted or deleted. New tests cover transient reopen
   failure followed by successful cleanup for both the EXE and directory; existing
   replacement-object negative tests remain passing.
2. Random stage-name generation previously happened after ancestor pins, outside
   the owner-preserving error boundary. It now runs after input validation but
   before native initialization or resource acquisition. A failed random source
   raises fixed `StageError("stage_entropy")` with no owner, native calls or
   handles to lose. The injected-failure regression checks those exact facts.

Verification with the same project interpreter and working directory:

- RED staging suite: **3 failed, 62 passed in 0.41s**. Two failures demonstrate
  premature uncertainty for no-handle reopen failures; the third demonstrates
  raw entropy exception propagation after resources had already been acquired.
- First-fix targeted GREEN: **5 passed, 60 deselected in 0.05s**, covering transient
  reopen and replacement-object rejection.
- Complete staging GREEN: **65 passed in 0.21s**.
- Required combined command, unchanged from above: **288 passed in 3.50s**, exit
  0. This includes staging, hello, process, security and profile suites.

Files are frozen again for root review. The earlier source/API and native-evidence
limitations remain unchanged.

## Root native-smoke finding: unchecked attributes wrapper

The root agent subsequently reported real native staging, ACL readback and
**ordinary (not contained) image launch** succeeded. Cleanup nevertheless returned
`removal_unconfirmed`, including a retry after 3 seconds. Root's read-only check
on the exact now-absent EXE found:

```text
win32file.GetFileAttributes(path) == -1
win32api.GetLastError() == 2
no exception raised
```

This disproved the adapter's assumption that `win32file.GetFileAttributes`
always raises on failure. Its previous implementation returned False for the
unchecked sentinel and could not acknowledge the already-removed EXE.

The correction uses `win32api.GetFileAttributes`, whose [b312 implementation](https://raw.githubusercontent.com/mhammond/pywin32/b312/win32/src/win32apimodule.cpp)
explicitly checks `INVALID_FILE_ATTRIBUTES` and converts it into an API exception.
Only exception codes 2/3 establish absence. Access denied, sharing violations,
other error codes and malformed return values propagate failure; a sentinel or
stale last-error value alone never establishes removal. This is preferable to
adding a separate unchecked-call/GetLastError timing dependency.

Root preserved these failed smoke runs:

- `native-stage-smoke-66845304e5594868a1d1b96522eaa74d`
- `native-stage-smoke-fb25706a6353404d8ac5f6a532aeb04e`

Root reports each EXE is now absent, with its empty protected stage directory
retained after `close_only()`. This correction does **not** adopt or delete those
old directories. They no longer have automatic cleanup authority in this helper.
These native observations are root-reported evidence; this task did not run a
native stager, change an ACL, launch an image or clean up an old path.

Added fake-boundary regressions reproduce the unchecked `-1` behavior alongside
the checked-wrapper error contract; they exercise error codes 2, 3, 5, 32 and 0,
invalid returned sentinels/types, and existing attributes with stale last-error 2.

- RED: **13 failed, 65 passed in 0.45s**.
- Staging GREEN: **78 passed in 0.18s**.
- Required combined five-suite command: **301 passed in 3.50s**, exit 0.

Only the same three owned files changed. They are frozen for root's next review
and fresh native smoke. No commit or new native-effect verification was performed
by this task; successful native cleanup with this correction is still unverified.

## Root verification of corrected native staging

The scoped independent re-review approved the checked-wrapper correction. Root
then reran the five suites using the project Python: **301 passed in 3.33s**,
exit 0. A fresh Windows native smoke also exited 0:

- Run: `native-stage-smoke-0e215119c6c045a8be3e62fbf2c13bf2` under the ignored
  local-privacy QA directory; `result.json` retains raw evidence.
- Staging module SHA-256:
  `6dc810da93c99f8fabae906840552fa30ce28e0be860d1873dc5042173aa263d`.
- Fixed hello EXE: 3,584 bytes; SHA-256
  `9acdd9275f9bb7601424ead85ada6ec6762ad5a8cd07dd02a67b17c22a11f2df`.
- Protected owner/SYSTEM/full and exact-package/read-execute DACL, file identity,
  single link and hash readback passed; the staged ordinary child completed with
  exit 0, exact hello protocol and confirmed child cleanup.
- The first explicit staging cleanup returned complete, handles closed, and no
  remaining/uncertain paths or failures. No polling retry was needed.
- A separate PowerShell `Test-Path -LiteralPath` check confirmed both this run's
  exact `stage_fcd4e2ef61728c6d87961aa1a7c0a811` directory and its `hello.exe`
  were absent. `git diff --check` exited 0.

This establishes ordinary native staging, launch compatibility and exact-owned
cleanup only. Profile identity was derived but **no profile was created**; no
AppContainer child or network-isolation test ran. Previous failed evidence and
its two empty stage directories remain untouched. Contained startup, file/network
denial and durable orchestration are still separate uncompleted gates.
