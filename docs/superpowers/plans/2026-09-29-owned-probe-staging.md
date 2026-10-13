# Owned fixed-probe staging prerequisite

This task implements the precise staging boundary of the approved native hello
plan. Profile prepare and the fixed hello protocol are committed; ordinary csc
compilation/hello/argument rejection have passed. No contained startup has run.
Use installed pywin32 lazily rather than reimplementing a large Win32 ABI layer.

## Ownership and task

Only add `scripts/local_probe_stage.py`, `tests/unit/test_local_probe_stage.py`,
and `docs/reports/2026-09-29-owned-probe-staging.md`. Do not modify existing
profile/security/process/hello/naming files. Root owns actual native effects and
Git. Write tests first with fake native boundaries; do not create real profiles,
change actual ACLs, or run the actual stager in this task.

Expose a small trusted internal helper for creating and retaining one newly
owned fixed `hello.exe` from caller-supplied trusted compiled bytes. This is not a
general CLI copy/permission utility. The future orchestrator selects the fixed
ignored QA root and prepared profile SID; no user-supplied command is added.

### Creation and evidence

- Validate absolute local paths, package SID canonical shape and uint32 bounds,
  exact bytes (nonempty, at most 4 MiB), expected SHA-256 before mutation. Accept
  only local NTFS for this diagnostic's legacy volume/file-ID identity scheme;
  reject UNC, traversal, reparse ancestors/objects and collision. No fallback.
- Allocate a random `stage_<32 lowercase hex>` directory under an existing QA
  parent. Create it with a non-NULL protected DACL at creation: current user and
  SYSTEM full management; exact package SID read/traverse/execute only. No
  inheritance, Everyone, All Application Packages or capability grants. Do not
  edit parent or ancestor ACLs. If ancestry blocks access, report failure.
- Create `hello.exe` exclusively using CREATE_NEW with a matching protected
  current-user/SYSTEM-full, exact-package-read/execute descriptor. Write the real
  bytes (not a link), flush, and validate readback from the same object. Record
  volume serial/file ID, size, link count exactly 1, SHA and exact ACL readback.
  Directory handles validate directory/reparse attributes; file must be regular.
- Use Win32 handles with OPEN_REPARSE_POINT/BACKUP_SEMANTICS where appropriate.
  Retain directory and executable handles to prevent delete/rename or write
  replacement across later launch; do not share delete on owned handles, and do
  not share write on the executable. Grant the ordinary child the read/execute
  sharing it needs. Identity, hash and exact protected ACE readback must be
  recheckable before a later orchestrator launches this path. Readback failure or
  inherited/extra/broader ACE is failure, not a warning.
  Do not retain a write-access EXE handle across image launch: after flushing and
  initial readback, a close/reopen into a compatible read-only pin is allowed
  while retaining the parent pin, with exact identity/hash/ACL revalidation.
  Cleanup may similarly transition to a DELETE-capable handle only after child
  cleanup is confirmed, with identity checks before any disposition. Document
  such transitions and fail closed if the exact object cannot be reacquired.
- Check/pin existing ancestor directory identities during path operations where
  feasible without changing ACLs. Document the boundary: this is protection from
  the capability-less child, not a guarantee against a malicious same-user
  administrator changing security settings. Never claim to control the entire
  host. Reparse/collision/identity uncertainty must retain, not adopt/delete.
- Directory acquisition proof for this bounded threat model is successful
  exclusive CreateDirectory in this live call, followed immediately (before any
  child starts) by a pinned no-follow open and exact protected owner/DACL/type
  verification. Record its initial identity then retain that pin. CreateDirectory
  itself returns no identity; this is not an atomic-create guarantee against a
  malicious same-user process. Failed open/readback, an unexpected descriptor,
  collision or detectable replacement means uncertain ownership and prohibits
  deletion. Do not add NtCreateFile or silently claim protection against excluded
  same-user administrative interference.
- Expose immutable bounded evidence containing only the owned paths, object IDs,
  digest, size and security facts. No arbitrary exception strings or credentials.

### Lifetime and cleanup

- No implicit context-manager destructor cleanup that could run while a child is
  alive. Explicit cleanup requires `child_cleanup_confirmed is True`. False or
  non-bool retains handles/objects and reports pending; it must not delete.
- Delete only the exact retained file and directory using verified handle-based
  disposition when possible. Recheck identity, link count and reparse status
  first; do not recurse or scan by prefix, unlink a replacement path, delete the
  QA parent, or follow new descendants. Unexpected children cause cleanup failure.
- Make cleanup retryable and idempotent with explicit state. Report each failed
  close/delete and retain pending ownership; success means exact objects removed
  and owned handles closed. A name collision or create/open gap without proved
  identity never grants cleanup authority. Do not automatically delete on restart
  from a path/SID; the separate journal/orchestrator is not implemented here.
- Partial creation must be represented in a retained live owner on raised error,
  so confirmed owned handles are not silently lost; uncertain objects are stated
  explicitly and never auto-deleted. An explicit safe close-only operation can
  release handles without asserting removal, retaining a report of leftovers.

### Tests and handoff

Fake-boundary tests must exercise requested creation/share flags, exact DACL
construction/readback (including no NULL/inherited/extra ACE), caller input
validation before mutation, ancestor reparse, existing names, short writes,
flush/hash/identity/link-count failures, prelaunch recheck, incomplete-child
cleanup refusal, successful cleanup, delete/close failure retention/retry,
unowned collision and directory replacement. Test actual helper behavior, not
only fake-call counts. Pure pywin32 descriptor serialization is allowed if it
does not change OS objects. If a necessary API contract cannot be verified,
escalate rather than invent it or widen scope.

Use exact project Python; run focused RED/GREEN then stage + hello/process/
security/profile tests. Report source-backed API assumptions separately from
actual OS evidence. Freeze files, no commit. Root review and isolated native
staging smoke are separate before any profile execution.

## Global constraints

No network/cloud API, Key/Credential Manager, private files, profile lifecycle,
firewall/exemption/system security changes, original runtime/model/Python or
ancestor ACL changes, download, product/QML/Golden, push or integration. Do not
run an executable or claim network/file denial from staging alone.

## Checked primary contracts

- https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle

These describe APIs, not proof that this task's staging works on this host.
