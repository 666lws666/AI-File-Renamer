# Local privacy L1: bounded Windows network-denial experiment

> Status (2026-09-29): token/profile/staging and native access experiments implemented. The original strict socket-code gate remains FAILED because loopback returns a timeout, not 10013. Read-only WFP corroboration permits the separately bounded model-compatibility experiment described below; it does not change that test result or establish product privacy readiness. Only owned profiles/staging ACLs have been created and cleaned; no firewall, network exemption or collection setting has been changed.

**Goal:** prove that a trusted, supervised local process can run with zero AppContainer capabilities and explicit network permission denial, before calling any model path private.

**Architecture:** extend the existing diagnostic Job/HANDLE_LIST supervisor, use a tiny locally built probe before loading models, and retain parent-owned evidence. The diagnostic must fail closed if its container, token, I/O, cleanup or network assertions fail. No product UI or cloud dispatch changes in this experiment.

## Prerequisites and boundaries

- Existing worktree: `codex/local-privacy-mode`; do not use the main checkout or replace existing uncommitted work.
- First complete and review `2026-09-13-local-inference-runner.md`, including real text and image quality. Keep failed attempts.
- Compiler discovery is read-only. Native static C is preferred if an installed supported toolchain exists. The host also has the Windows .NET Framework compiler; a minimal C# P/Invoke probe is an alternative only if actual AppContainer execution succeeds. Do not install a system toolchain or claim CLR compatibility without running it.
- Never grant access to the whole repository, original model/runtime, Python installation or user profile. Never call loopback-exemption setters, modify the firewall or relax OS security policy.
- Only random, task-owned staging copies and a task-owned current-user AppContainer profile may be created. Profile provisioning has persistent per-user filesystem/registry effects until cleanup; record them explicitly.

### Task 1: token-bound supervisor extension

Files: modify `scripts/local_probe_process.py` and `tests/unit/test_local_probe_process.py`; add a narrowly scoped security helper/test if needed. Do not mix model prompts or resource downloads here.

- [ ] Write negative tests first for malformed SID/capabilities, token-query failures, wrong container identity and nonzero capability count; no child user code may run after a failed check.
- [ ] Add ABI-correct `SID_AND_ATTRIBUTES` and `SECURITY_CAPABILITIES` without packed layout; SID and pointer storage must remain alive until the attribute list is destroyed.
- [ ] Use `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` alongside the existing exact three inherited pipe handles and creation-time Job assignment. Keep suspended creation and KILL_ON_JOB_CLOSE; no uncontained retry or alternate parent.
- [ ] Before resume, parent queries TokenIsAppContainer, TokenAppContainerSid and TokenCapabilities; require true, exact intended SID and zero capabilities. Also verify existing Job membership. Child self-report alone is insufficient.
- [ ] Preserve the ordinary diagnostic launch API by explicit optional trusted security context, not a general caller-supplied attribute/command escape hatch.
- [ ] Run all existing native process lifecycle tests plus focused fault tests, commit only this bounded change after independent review.

### Task 2: owned profile, staging and recovery

Files: add `scripts/local_appcontainer_probe.py`, `tests/unit/test_local_appcontainer_probe.py`, and a small probe source under `scripts/native/`. Exact source language follows the compiler preflight, not a guessed toolchain.

- [ ] Before provisioning, persist an ownership journal in a unique ignored QA directory: run ID, random ASCII profile name under 64 characters, derived intended SID and exact staging paths.
- [ ] Journal state must distinguish intent, confirmed creation (native S_OK), collision, cleanup pending and cleanup completed. An intent/SID alone never authorizes deletion. A crash between native creation and confirmation persistence leaves ownership uncertain: retain evidence and report, do not automatically adopt/delete that profile. The same live creator may clean up after confirmed S_OK even if later journal writing fails; persist failure details when possible. Collision entries can never enter the cleanup path.
- [ ] Create the profile for the current user with no capability SIDs. Treat HRESULT correctly and free the returned SID with FreeSid. On collision choose another random name; never adopt/delete an existing profile.
- [ ] Copy the trusted compiled probe and synthetic allowed/denied fixtures into new staging objects; reject reparse traversal and hard-link reuse. Protected DACLs on these objects grant current user/SYSTEM management and only the exact package SID's necessary read/execute access.
- [ ] Keep runtime/data outside the child's writable parent; no package write/delete/WRITE_DAC/WRITE_OWNER permission on those files. Parent evidence is outside child-write scope. Temporary writable state stays in owned profile storage.
- [ ] If ancestor traversal prevents launch, report it; do not broaden a parent ACL. No model or private file is loaded in this task.
- [ ] Cleanup only journaled owned objects after the Job is empty and handles are closed. Delete the exact owned profile; incomplete deletion remains an explicit failure and is recoverable only from that journal. No prefix scans or reused-PID termination.
- [ ] Test provisioning/copy/ACL/launch/cleanup failures with fakes, then actual successful creation and removal. Commit source and tests, never generated EXE/profile storage.

Exact-object DACL matrix: staging directory/probe executable grant current user and SYSTEM management, exact package SID read/traverse/execute only; allowed fixture grants the package read only; denied fixture and parent evidence grant no package or inherited All Application Packages access. Use a non-NULL protected DACL on newly owned objects, never on ancestors or original resources. Child write/delete/WRITE_DAC/WRITE_OWNER remains absent outside its explicitly owned profile storage. Close parent fixture handles before controls so sharing violations cannot imitate access denial.

### Task 3: real network and filesystem assertions

Files: the Task 2 probe/helper/tests, plus `docs/reports/2026-09-13-appcontainer-feasibility.md`. Evidence remains in `tests/screenshots/qa-current/local-privacy/`.

- [ ] Read NetworkIsolationGetAppContainerConfig and reject an exempt SID. Do not call the setter. Correctly release the returned allocations.
- [ ] This function returns its DWORD error directly; failure is not an empty list. Microsoft specifies HeapFree(GetProcessHeap(),0,entry.Sid) for each returned SID, then HeapFree for the outer array. Do not use the FreeSid/LocalFree/CoTaskMemFree contracts of other APIs here. Cleanup failure is explicit, not a pass.
- [ ] Parent owns a noninheritable TCP listener on 127.0.0.1 with an ephemeral port. The identical trusted probe outside the container must connect to it using only a fixed synthetic nonce: the live positive control.
- [ ] Container child attempts the same loopback connection and a connection to literal TEST-NET address 192.0.2.1:443. No DNS, HTTP, TLS, user data or application API is involved. Each child has a short supervisor deadline.
- [ ] A passing negative requires normal socket initialization/creation followed by connect returning permission denial WSAEACCES/10013. Timeout, refused/unreachable target, no packets, or process termination are inconclusive, never PASS.
- [ ] First the ordinary positive-control probe must read both exact synthetic fixtures and verify their expected contents. Then the container must read the allowed fixture successfully and its real GENERIC_READ/OPEN_EXISTING access to the denied fixture must return ERROR_ACCESS_DENIED/5. Missing path, sharing violation, timeout or any other error fails this assertion. Do not infer universal filesystem denial: standard AppContainer retains access to resources deliberately granted to all application packages.
- [ ] Record parent token verification, exact call-stage/errors, positive control, negative outcomes, exit/Job/cleanup status and owned-resource removal. External network observation is supporting evidence, not a substitute for enforcement.
- [ ] Do not proceed to model isolation unless every assertion and cleanup passes. Then run the pinned real model in similarly narrow staging and repeat semantic acceptance; a probe alone does not prove model compatibility.

### 2026-09-29 engineering-only continuation decision

The two preceding socket-code/advancement requirements remain the definition of
the original strict probe result. They are not a universal Windows behavior
contract: this host blocks AppContainer loopback at the receiving endpoint,
while the initiating connect times out. Do not alter the validator to accept a
timeout alone, rewrite historical results, or turn the diagnostic into a product
privacy gate.

Under the Product Owner's approved autonomous technical implementation scope,
a separate model-compatibility experiment may now proceed. Its evidence basis
is documented in `docs/reports/2026-09-29-appcontainer-wfp-corroboration.md`:
successful same-listener ordinary control, exact parent-verified AppContainer
token with zero capabilities and no exemption, actual denied-file error 5,
external TEST-NET connect error 10013, and two time/port-correlated WFP loopback
BLOCK events. The receiving-side records do not directly identify the child SID.
An independent read-only review found no implementation defect requiring a new
capture or security-setting change before this bounded experiment.

The next experiment must use only hash-verified owned copies of the existing
pinned runtime/model and reviewed synthetic inputs, exact package read/execute
rights, the same suspended token verification and Job cleanup, and no ordinary
fallback. Start with text, then image input if text launches safely. Record real
outputs, token, termination and cleanup independently from semantic acceptance.
Missing containment or uncertain cleanup stops progression; no ancestor ACL
repair, firewall changes, exemptions, new network query or real API is authorized
by this continuation. Product privacy readiness still requires the later shared
Batch/Watch dispatch exclusion and lifecycle/end-to-end tests.

## Review and exit criteria

Root reviews native evidence independently of implementation reports. Focus on deterministic security/data-loss/core-execution failures; maintenance issues go to backlog. No Golden changes, real API, credentials, push or publication. A successful network probe is only L1 evidence, not completion of resource management, shared cloud-dispatch exclusion or beginner-ready local mode.

## Primary references (checked 2026-09-13)

- [Security capabilities](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-security_capabilities)
- [Process attributes and lifetime](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Token query classes](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)
- [Current-user profile creation](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile)
- [Profile deletion and incomplete cleanup](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile)
- [Read-only network exemption enumeration](https://learn.microsoft.com/en-us/windows/win32/api/netfw/nf-netfw-networkisolationgetappcontainerconfig)
- [Actual file access and sharing semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)

These sources establish API contracts, not successful execution on this host. The design deliberately separates source-backed expectations from actual test results.
