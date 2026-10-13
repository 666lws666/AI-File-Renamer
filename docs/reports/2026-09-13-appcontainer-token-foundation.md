# AppContainer token foundation: isolated helper verification

Date: 2026-09-13. Baseline supplied by root: `62028d6b2033c1af6cae1172934dc2432f409863`.

## Result and scope

Implemented only the standalone diagnostic helper and its unit tests. The helper
owns a converted canonical package SID, exposes a retained zero-capability
`SECURITY_CAPABILITIES`, and reads a process token with `TOKEN_QUERY` to reject
anything except the exact AppContainer identity with zero capabilities.

This is NOT evidence of a launched AppContainer, network denial, model operation
inside a sandbox, or production readiness. No existing supervisor imports this
helper. No profile, ACL, firewall, loopback exemption, token or credential changes
were made. No model or network probe was run by this task. The explicitly requested
existing process-lifecycle regression tests do create their own harmless children;
they were not modified and do not run models.

Assigned files:

- `scripts/local_probe_security.py`
- `tests/unit/test_local_probe_security.py`
- `docs/reports/2026-09-13-appcontainer-token-foundation.md`

No Git staging or commits were performed. Existing runner, supervisor, source,
QML, resources, corpus and Golden files remain outside this change.

## Contract implemented

- Constructor accepts only `S-1-15-2-<seven canonical uint32 components>`;
  malformed input is rejected before binding/allocation/API calls.
- Native-aligned SID and capability structures use pointer-width fields.
- Explicit typed `ConvertStringSidToSidW`, `IsValidSid`, `EqualSid`,
  `OpenProcessToken`, `GetTokenInformation`, `CloseHandle`, and `LocalFree`
  bindings use ctypes last-error handling.
- Conversion allocations are owned by the context and released with `LocalFree`
  (not the `FreeSid` used by profile-creation APIs). Exact converted bytes are
  checked against the canonical identity.
- Context is one-shot/thread-confined. Use before entry, re-entry, use after close,
  and modified capability fields fail closed. Close invalidates the retained SID
  pointer view and is idempotent after successful release.
- Token verification queries classes 29, 31 and 30, in that order, requires DWORD
  1, exact valid package SID and capability group count zero, and only then creates
  frozen `TokenEvidence`. It opens only TOKEN_QUERY and closes returned token
  handles on all paths, including a fault-injected partial open failure.
- Two-call token queries require an insufficient-buffer sizing response, lengths
  from 1 through 65536, successful fill and returned length within allocation.
  Structure fields are not read before their minimum lengths are checked. SID
  pointers cannot overlap the pointer header or escape the returned buffer; the
  SID header is bounded before its subauthority count is read, and the full extent
  is bounded before SID validation/comparison APIs run.
- Errors expose fixed stages and numeric codes, not caller input or native
  exception text. Failed token close blocks evidence. Failed LocalFree is reported,
  leaves the context unusable and retains ownership for explicit close retry.

## TDD and fresh verification

Interpreter: `D:\\文件AI-AGENT\\.venv\\Scripts\\python.exe`.

| Checkpoint | Observed result |
| --- | --- |
| Bootstrap with missing module | 1 failed, 18 fixture errors: missing helper |
| Canonical identity validation | 19 passed |
| Context/token/buffer contract RED | 37 failed, 19 passed: missing context/API behavior |
| Initial implementation GREEN | 56 passed, including native current-process rejection |
| Handle-width/modified-ABI regression RED | 4 failed, 68 passed |
| Final helper suite | 72 passed in 0.21 seconds |
| Final helper + unchanged process suite | 113 passed in 2.96 seconds |

Final commands (both exit code 0):

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_security.py -q
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_security.py tests/unit/test_local_probe_process.py -q
```

Fake bindings replace only the Win32 boundary, not the helper under test. They use
actual allocated buffers for ABI, lifetime and hostile-pointer parsing. Fake
successful evidence must not be described as native AppContainer proof.

The separate Windows-native test allocates the synthetic canonical SID and queries
only the running test process's token. It verifies rejection of that exact identity
without creating any profile/process or changing token state. It does not exercise
a successful AppContainer token or the native zero-capability query success path.

## Remaining gates and ownership limits

The future supervisor must keep the context alive until its attribute list is
destroyed, attach SECURITY_CAPABILITIES at process creation alongside HANDLE_LIST
and JOB_LIST, then verify while the child is still suspended. This class does not
know whether a supplied process is suspended or belongs to an owned job. It neither
creates a profile nor proves ownership of one from SID shape alone.

Existing L1 owned-profile/staging/positive-control/negative-network tests remain
mandatory. Permission-denied errors must be observed; timeouts and zero observed
traffic are not denial evidence. Runtime/model access and actual native process
compatibility remain unverified. Root reported no C/C++ compiler in PATH; built-in
C# compiler availability is not proof that a CLR probe runs inside AppContainer.

The ABI structure necessarily exposes mutable native memory to trusted same-process
code. Guard checks detect changed fields on subsequent helper access; they are not
concurrency hardening against arbitrary writes in the parent's address space.
SID conversion trusts the real Win32 allocator contract; token-returned SID pointers
are independently range checked against the owned query buffer.

If CloseHandle reports failure, verification fails rather than claiming a clean
success; closure is not proven. LocalFree failure retains the allocation for an
explicit retry, not a destructor. Callers must honor context/cleanup failures.
Root independently reran helper + unchanged process tests: **113 passed in2.68s**, exit0; git diff --check passed. A separate read-only reviewer fully checked the plan/helper/tests/report and found Critical0/Important0/Minor0 in this bounded change. No reviewer result substitutes for the still-pending native container/network experiment. Root will checkpoint only these new foundation files and their task plan; concurrent naming-probe edits are excluded.

## Primary API contracts

- [SECURITY_CAPABILITIES](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-security_capabilities)
- [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)
- [Token information classes](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)
- [ConvertStringSidToSidW / LocalFree ownership](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsidtosidw)
