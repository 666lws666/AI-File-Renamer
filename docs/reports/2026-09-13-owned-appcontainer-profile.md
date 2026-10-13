# Owned AppContainer profile helper foundation

Date: 2026-09-13. Baseline supplied by root: `2c39e483`.

## Result and scope

The standalone profile helper and fake-boundary tests are complete and frozen
for independent review. No real AppContainer profile API was instantiated or
called. This report does NOT claim native profile creation/deletion success,
complete profile-storage cleanup, sandbox launch, network isolation or product
readiness.

Only new files were written:

- `scripts/local_probe_profile.py`
- `tests/unit/test_local_probe_profile.py`
- This report.

Existing process/security/runner modules and tests, source, resources, corpus and
Golden were not edited. The new helper is not imported into any existing runtime
chain. No profiles, ACLs, firewall rules, network exemptions, tokens, credentials
or other security settings were modified. No network/model probe or Git writes
were performed. The requested unchanged token/process regression suite performs
its existing read-only token checks and harmless child-process lifetime tests.

## Implemented ownership contract

`OwnedAppContainerProfile(name)` accepts only `xuxia_probe_` plus 32 lowercase hex
characters, before any binding. Construction is side-effect-free. Successful
entry exposes read-only name/sid strings; inactive/closed access and reentry fail.
The context is one-shot and thread-confined and has no destructor.

Entry first derives the intended SID, converts it to text, and validates shape
using the existing AppContainerSecurity constructor without entering that helper.
This shape check is not profile-ownership evidence. Temporary derivation buffers
are released before creation is attempted.

Create uses fixed synthetic display/description text and NULL capabilities/count
zero. Only exact S_OK records ownership of this exact name, immediately before any
returned-SID validation. The returned SID must be nonnull, convertible to the
canonical package-SID shape and equal to the derived intended SID. Active state
is reached only after these checks and temporary-memory cleanup succeed.

ERROR_ALREADY_EXISTS is always a collision: no adoption, deletion or automatic
new-name fallback. Every nonzero HRESULT is rejected, including S_FALSE. Invalid
HRESULT values cannot be normalized into accidental success.

The Userenv functions are bound with signed32 HRESULT return types. ProfileError
exposes fixed stage/code; HRESULTs are normalized to their complete unsigned32
values, not treated as BOOL and not replaced by GetLastError. Win32 conversion
and LocalFree errors use their Win32 numeric errors. Native exceptions are
sanitized. DLL references and explicit function signatures are retained.

Profile/derived SID allocations go only to FreeSid; converted string allocations
go only to LocalFree. Partial returned allocations are adopted for cleanup even
when the producing API fails. FreeSid's documented NULL return is checked; an
anomalous nonnull return fails with code 13 rather than assuming an undocumented
GetLastError contract. Failed release retains the allocation for explicit retry;
successful releases are not repeated.

Only an S_OK-owned live context may call Delete for its exact name. Successful
delete clears ownership; failed delete keeps ownership for explicit close retry.
If post-create validation or temporary cleanup fails, that now-owned profile is
still cleaned. If deletion also fails, the cleanup failure is raised and exact
ownership is retained. Close attempts remaining temporary releases and owned
profile deletion independently. Before-entry close is safe and never deletes.

## TDD and fresh verification

| Checkpoint | Observed result |
| --- | --- |
| Missing-module bootstrap | 1 failed, 14 fixture errors |
| Pure name/context scaffold | 15 passed |
| Ownership/HRESULT/allocator RED | 30 failed, 16 passed in 0.73 seconds |
| Core implementation GREEN | 46 passed in 0.21 seconds |
| Final fake-only profile suite | 66 passed in 0.33 seconds |
| Final profile + unchanged token/process | 197 passed in 4.13 seconds |

Final commands, both exit code 0:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_profile.py -q
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_profile.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_process.py -q
```

The profile test module has an autouse guard that forbids real DLL loading before
module import, replaces its default binding constructor with a failure guard, and
forbids the token helper's binding constructor too. Every tested profile operation
uses the narrow fake API with actual allocated SID/string buffers, never a whole
mocked context/result. One test explicitly proves valid entry cannot bypass the
default-binding guard when no fake is installed.

Tests cover signed/unsigned HRESULT equivalence, malformed HRESULTs, collision,
NULL/invalid/wrong SID text, partial failure allocations, conversion errors and
exceptions, both allocators' release failures/exceptions, simultaneous free/delete
failures, ownership-preserving delete retry, duplicate close, active reentry,
read-only properties and a journal-persist exception inside an owned context.

## Required caller journal protocol

1. Before entry, durably write an intent record with the chosen diagnostic name
   and run identifier. If intent persistence fails, do not enter the context.
2. After successful entry, durably record confirmed successful creation and the
   returned canonical SID. Keep the live context until owned work/cleanup ends.
3. If confirmation persistence fails while that context remains alive, it can
   still close safely because it personally observed S_OK; the intent record is
   not the authority for that deletion.
4. After a crash, a prewritten name/SID or derivable matching SID is NEVER enough
   to authorize deletion. A crash between OS creation and durable confirmation is
   ambiguous; this helper does not resolve that gap or perform restart recovery.
5. Collision is never owned. A caller may choose a different random name only as
   a separate journal/run decision, not by adopting or deleting the collided name.
6. Treat any deletion/free error as incomplete cleanup. Preserve the live context
   for explicit retry; do not assume a failed close cleared ownership.

## Remaining native gates

## Resume verification (2026-09-28)

Root resumed the unchanged helper after the earlier independent scoped review
(Critical: 0; Important: 0). Fresh combined diagnostics ran with the project
Windows Python: `520 passed in 78.43s`. The eight files cover inference, shared
smart policy, process supervisor, token security, owned profile, model preflight,
resources and synthetic corpus. Profile calls remain fake-only in these tests.
This confirms regression coverage, not native profile or network isolation.

### Still unverified on the host

Real profile API availability, native creation/cleanup and full removal of profile
storage remain unverified. No GetAppContainerFolderPath, staging DACL, loopback
exemption inspection, native probe process or network test is implemented here.
The helper trusts successful Windows SID-to-string conversion to provide a valid
allocated NUL-terminated string, then validates its canonical package-SID shape.

Root must independently review this helper before any authorized native use.
Native profile creation would itself be a current-user persistent state change;
the fake tests authorize no such experiment.

## Primary contracts supplied by the plan

- [CreateAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile)
- [DeriveAppContainerSidFromAppContainerName](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deriveappcontainersidfromappcontainername)
- [DeleteAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile)
- [ConvertSidToStringSidW](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertsidtostringsidw)
