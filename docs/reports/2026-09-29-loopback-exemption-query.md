# Read-only loopback exemption metadata preflight

## Scope and interface

This is the approved L1 Task 3 preflight helper only. It performs no setter call,
network probe, profile lifecycle, ACL update, credential access, or evidence claim
about actual socket permission denial.

`OwnedLoopbackExemptionQuery(package_sid)` validates the canonical
`S-1-15-2` plus seven unsigned 32-bit subauthority form without native calls.
Keep the owner in a variable. `owner.query()` is single-use and returns immutable
`ExemptionResult(package_sid, exempt, count, cleanup_complete=True)` **only after**
all observed allocations are released. `owner.require_not_exempt()` returns that
result for a non-exempt target and raises fixed-stage `ExemptionError` for an
exempt target or incomplete query. `owner.close()` explicitly retries only still-
owned allocations, without double-freeing previously released ones. A malformed
native layout is reported as `query_layout`: its raw count/address are retained
privately in the live owner before validation, but its uncertain allocation is
not dereferenced or blindly freed. Those raw values are never included in the
result or report. The owner must remain
live for retry/incident handling on cleanup failure. There is no destructor or
restart cleanup.

The result exposes only the requested SID, exemption boolean, count, and completed
cleanup fact; it does not enumerate or log other installed app SIDs. A query
failure, including direct status 5 (`ERROR_ACCESS_DENIED`), never becomes a
successful empty list. A negative result is metadata only and does not establish
that a contained process is denied actual loopback sockets.

## Source-backed native contracts

- [Microsoft: NetworkIsolationGetAppContainerConfig](https://learn.microsoft.com/en-us/windows/win32/api/netfw/nf-netfw-networkisolationgetappcontainerconfig) documents `DWORD` direct status, `DWORD*` count, `PSID_AND_ATTRIBUTES*` output, `FirewallAPI.dll`, and a sample that calls `HeapFree(GetProcessHeap(), 0, entry.Sid)` for each entry followed by `HeapFree` for the array.
- [Microsoft: ConvertStringSidToSidW](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsidtosidw) documents a `BOOL` result, allocated SID output, and `LocalFree` for that target-SID allocation.
- [Microsoft: IsValidSid](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-isvalidsid) documents `BOOL` validity and explicitly no extended error from `GetLastError`; [EqualSid](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-equalsid) compares actual SID identity.
- [Microsoft: HeapFree](https://learn.microsoft.com/en-us/windows/win32/api/heapapi/nf-heapapi-heapfree) documents nonzero success, zero failure, and use of the handle returned by `GetProcessHeap`.

Bindings are lazy and pointer-width-safe via `ctypes` `c_void_p`/`POINTER` and
the existing `SID_AND_ATTRIBUTES` layout. The helper checks output count against
4096, count/pointer consistency, pointer alignment and uniqueness before walking
the array. As with any in-process FFI, these structural checks cannot prove an
arbitrary address supplied by a broken native implementation is readable; the
Windows API is trusted for allocated output memory. An inconsistent layout is
therefore retained and fails closed.

## Verification performed (fake native only)

Project interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`.
The default process helper rejected process creation (`helper_unknown_error:
setup refresh had errors`), so the test commands below were rerun with
`require_escalated`. No real exemption or other native API was invoked.

1. `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py -q` — initial scaffold check: 19 setup errors because the production module did not yet exist. An empty module was added. This was not treated as the behavioral RED.
2. `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py -q --maxfail=1` — two successive fixture setup errors (missing `_Bindings`, then missing `_api`) were corrected in the test fixture; the next identical command produced 1 expected behavioral failure, missing `OwnedLoopbackExemptionQuery`.
3. `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py -q` — subsequent run: 2 layout-test expectation failures; corrected the expectation for malformed output with no allocation.
4. Same focused command — GREEN for the initial behaviors: **22 passed in 0.07s**.
5. Same focused command — RED: 1 failure exposing array ownership loss when a fake query raised after setting its output pointer; fixed output capture in `finally`.
6. Same focused command — RED: 2 failures for canonical target-identity validation and target cleanup when `GetProcessHeap` raised; fixed both.
7. Same focused command — GREEN before review: **24 passed in 0.08s**.
8. `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py tests\unit\test_local_probe_profile.py tests\unit\test_local_probe_security.py -q` — **166 passed in 0.34s** before review.
9. Review regression, `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py -q` — RED: 2 failures because an allocated outer pointer with count 0 or 4097 was not retained in the owner. After repair, the same focused command: **26 passed in 0.07s**.
10. `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests\unit\test_local_probe_exemptions.py tests\unit\test_local_probe_profile.py tests\unit\test_local_probe_security.py -q` — post-review **168 passed in 0.33s**.

Tests cover import/constructor no effects, target validation, empty/not-matching/
matching results, direct status versus stale last error, invalid counts/pointers,
invalid SID, pointer-width layout, exact target identity, per-SID-before-array
freeing, single/multiple free failures and explicit retry without double-free,
partial target allocation, raised query after outputs, and uncertain layout
retention. The review regression uses a fake-owned allocation behind an
inconsistent count, asserting private retention of its address/count, no array
read/free, no usable negative result, and continued quarantine on explicit
close. All native boundaries were fake in these tests.

## Not performed

No actual Windows exemption query, network/socket denial attempt, profile or
file-privacy validation, model isolation check, or system configuration change
was performed by this implementer. No commit was made by the implementer.

## Root native verification

After the scoped ownership fix and independent re-review approval, root ran
`D:\文件AI-AGENT\.venv\Scripts\python.exe tests/screenshots/qa-current/local-privacy/exemption_query_smoke.py`.
Exit code: **0**. Evidence directory:
`tests/screenshots/qa-current/local-privacy/exemption-smoke-e8ffcc0eee614bd3a7f6085a99709429`.

- Helper SHA-256: `0581be31eaea55319136f39925a5f41153b7a49dfda3a5ccbcd4bf9f153d185d`.
- Random prepared package SID: `S-1-15-2-3457279808-2201440844-664337956-120766991-720616928-899526897-2263020617`.
- Real read-only API returned count **0**, target exempt **false**, cleanup complete
  **true**. Query and prepared-profile owners both closed successfully.
- No profile was created, no socket attempted, and no security setting changed.
- This verifies the empty-list native path and target-allocation cleanup on this
  machine. Per-entry freeing is covered by fake-native tests, not by this empty
  native list. Actual file/network denial and model isolation remain unverified.
