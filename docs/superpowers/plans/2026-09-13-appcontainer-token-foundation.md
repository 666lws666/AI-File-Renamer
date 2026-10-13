# AppContainer token foundation (diagnostic only)

Execute with subagent-driven-development and TDD. This is the independently testable helper portion of the existing L1 plan, not a claim that a sandbox is operational.

**Prerequisite evidence:** real local text and image inference now produce independently accepted sample names under compact protocol `local-summary-v2` at `62028d6b2033c1af6cae1172934dc2432f409863`. Broader language/media and refusal validation is running separately. The foundation can be prepared without loading a model or changing process/network/security state. Product integration still waits for actual network denial and full media/quality gates.

**Isolation:** the current inference runner/process helper are frozen during the real matrix. Only add the three assigned files; do not edit or import this helper into the existing supervisor yet. No profile creation, process launch, ACL/firewall/exemption changes, model execution, download, credential access or Git writes in this task.

## Task 1: owned zero-capability context and parent token verification

**Files:** new `scripts/local_probe_security.py`, `tests/unit/test_local_probe_security.py`, `docs/reports/2026-09-13-appcontainer-token-foundation.md`.

**Goal:** provide a small typed Win32 helper that later lets the existing suspended supervisor attach SECURITY_CAPABILITIES and validate the exact child token before ResumeThread. No arbitrary capabilities/attribute lists or fallback identity are accepted.

**Public contract:** `AppContainerSecurity(package_sid: str)` is an owned context manager. Within the context, `.capabilities` returns the retained ABI-correct SECURITY_CAPABILITIES instance with exact owned SID, NULL capability pointer, count0 and reserved0. `.verify_process(process_handle)` returns a frozen `TokenEvidence(package_sid, is_appcontainer=True, capability_count=0)` only after every check succeeds. `.close()` is idempotent; active re-entry/use-before-enter/use-after-close fails. Exceptions are `SecurityContextError` with fixed stage and numeric win32_error, not arbitrary input or exception text. No caller-provided capability collection or user-script hook.

- [ ] RED invalid identities first: accept only canonical full package SID `S-1-15-2-<seven uint32 components>`; reject aliases, spaces/NUL, user/capability/all-app-packages SIDs, wrong component count, negatives, leading-zero numbers and overflow. Validate before any allocation/API call. This shape is a narrow diagnostic contract, not a claim of owning a profile.
- [ ] Define SID_AND_ATTRIBUTES and SECURITY_CAPABILITIES with pointer-width ctypes fields and native alignment (24-byte capabilities on x64,16 on x86). Bind explicit W variants/argtypes/restype: ConvertStringSidToSidW, IsValidSid, EqualSid, OpenProcessToken, GetTokenInformation in Advapi32; CloseHandle and LocalFree in Kernel32. Use `use_last_error=True`, preserve allocation and structure lifetime. Returned SID from ConvertStringSidToSidW uses LocalFree, not profile API FreeSid.
- [ ] Context creation converts and validates exact SID; no capability SIDs. Reject NULL/malformed results. Properly release owned allocations on each failure/exit; no silent cleanup failure or double free. No profile is provisioned by this class.
- [ ] `verify_process` opens TOKEN_QUERY only and closes its token handle on every path. Query TokenIsAppContainer(29), TokenAppContainerSid(31), TokenCapabilities(30). Require DWORD1, exact valid intended SID and group count0. A normal process, wrong identity or nonzero capabilities is failure. No lower privilege or noncontainer fallback.
- [ ] Size queries use a bounded two-call GetTokenInformation protocol: expected insufficient-buffer sizing, nonzero sensible length <=64KiB, successful fill with valid returned length. Validate minimum sizes before ctypes reads, and SID header/extent lies within the returned SID-information buffer before reading it or calling IsValidSid/EqualSid. Keep buffers alive through comparisons. Malformed/null/out-of-buffer/truncated data must fail, not crash Python.
- [ ] Tests exercise actual helper logic with a narrow injected/fake Win32 binding only where needed: conversion/open/query/size/identity/capabilities/cleanup failures, valid exact token evidence, zero-capabilities ABI and unchanged pointer lifetime, handles released, no API on invalid SID, no success on query errors. No mocks replacing the helper under test. Use real allocated buffers for pointer tests.
- [ ] Add a Windows-native test that allocates the synthetic canonical SID and checks this running test process does NOT satisfy that exact AppContainer identity; it must fail closed without provisioning a profile or changing a token. Keep this separate from fake success tests and never call it proof of actual container launch/network denial.
- [ ] Run `python -m pytest tests/unit/test_local_probe_security.py -q`, then that test plus `tests/unit/test_local_probe_process.py`; do not run or edit active inference files. Record RED/GREEN summaries and limitations in the report. Freeze all three files without staging/commit; root independently reviews before any supervisor integration.

## Source contracts checked by root

- [SECURITY_CAPABILITIES](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-security_capabilities)
- [GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)
- [ConvertStringSidToSidW and LocalFree ownership](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsidtosidw)

This helper alone cannot deny networking. The later supervisor must attach it at creation and verify while the child remains suspended; the original L1 owned-profile/staging/positive-control/negative-network/cleanup tasks remain mandatory. Existing default process launch, model arguments, resource hashes, corpus and Golden are untouched by this task.
