# Token-bound diagnostic supervisor integration

Date: 2026-09-13. Baseline: `6aaf955b68e7c0e6b1af0f2141677f8bd4a90924`.

## Status and change boundary

Supervisor implementation and tests are frozen for root's independent review.
This is only the security-attribute/token-verification integration portion of L1.
It is not proof of native AppContainer launch, filesystem isolation or network
denial, and does not enable a production privacy mode.

Owned files:

- `scripts/local_probe_process.py`
- `tests/unit/test_local_probe_process.py`
- This new report.

The committed token helper and its tests were not changed. Runner, runner tests,
product source, QML, resources, corpus and Golden were not changed. No profile,
ACL, firewall, token, exemption or credential operation was added/performed; no
model or network probe was run. Existing ordinary-process tests and new integration
tests launch only their own harmless diagnostics. No Git writes were performed.

## Implemented contract

`run_bounded(..., security_context=None)` keeps the default two-attribute launch.
If supplied, context must have the exact canonical `AppContainerSecurity` type;
arbitrary objects, subclasses, inactive/closed contexts and modified ABI fields
are rejected before process/job/pipe allocation.

The optional security path retains the caller-owned context and its original ABI
object through attribute-list destruction, uses attribute count 3, and attaches
`PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` (`0x00020009`) alongside the unchanged
three-handle HANDLE_LIST and creation-time JOB_LIST. It never closes/replaces the
caller context or retries without containment.

After exact owned-child job membership is confirmed, the canonical helper's
`verify_process` implementation verifies that child's token while still suspended.
An instance-supplied verifier callback is not invoked. Deadline/cancellation is
checked again after verification and before ResumeThread. Helper failures become
fixed stage/numeric errors and follow the existing owned-tree reap path; no native
exception text is returned. Existing suspended creation, no-window flag, partial
handle adoption, output bounds and job cleanup remain unchanged.

`ProcessResult` gains a final defaulted `token_evidence` field; positional callers
remain compatible. Both the result and contained TokenEvidence are frozen.
Identity evidence is retained independently from lifecycle completion, including
cancellation/timeout after successful verification. Child stdout cannot set it;
ordinary diagnostics return None.

The sole actual diagnostic caller already imports `scripts.local_probe_process`.
With root approval, the existing supervisor-crash test now places repository root
on its isolated child's sys.path and uses that canonical package import too.
Its actual child-process crash and Job kill-on-close assertions remain intact.

## RED/GREEN evidence

| Checkpoint | Observed result |
| --- | --- |
| Initial integration RED | 15 failed, 41 passed in 2.84 seconds |
| Initial integration GREEN | 56 passed in 2.73 seconds |
| Final process suite | 59 passed in 2.80 seconds |
| Final unchanged helper + process suite | 131 passed in 2.97 seconds |

Initial failures were the absent security_context argument and token_evidence
field, not unrelated test failures. Additional tests exercise existing post-query
deadline checks, native exception sanitization and rejection of a caller verifier.

Fresh final commands, both exit 0:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_process.py -q
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_security.py tests/unit/test_local_probe_process.py -q
```

`git diff --check -- scripts/local_probe_process.py tests/unit/test_local_probe_process.py`
returned exit 0, with only repository LF-to-CRLF normalization warnings.

Integration tests inspect the actual capability pointer/size/count, attribute
ordering, native ordinary-child handles, suspended flags, job membership, token
verification/close-before-resume ordering, context lifetime through attribute
destruction and one/no creation attempt on failures. They cover attribute attach
failure, noncontainer/wrong identity/nonzero capability/query/token-close failure,
query exceptions, cancellation, deadline expiration and no child marker execution.

## Evidence limits and remaining gates

The new security-path fixture deliberately intercepts SECURITY_CAPABILITIES
attachment and simulates token query data at the narrow Win32 boundary. It still
uses the real helper parsing/verification logic and actual ordinary processes,
Jobs and pipes. Its successful TokenEvidence is synthetic and NOT a native
AppContainer claim. No context verifier or complete ProcessResult is faked.

The unchanged helper suite separately checks read-only rejection of the running
Windows test process's token. Neither suite launches a proven AppContainer.

Actual profile/staging ownership, runtime compatibility, network positive control,
explicit permission-denied negative tests and cleanup/restart gates remain pending.
Timeouts, no observed traffic and offline flags remain insufficient denial proof.
The context remains thread-confined trusted-parent state; concurrent mutation or
closing it during this call violates its ownership contract.

Root fresh verification after both implementations froze: helper/process **131 passed in2.91s**; all seven diagnostic/resource/corpus/shared-policy test files **447 passed in20.78s**. Independent full scoped review found Critical0/Important0/Minor0 in this supervisor change. The parallel naming protocol still has a separately identified metadata-prefix parsing issue; these test counts are not a full naming-quality pass. Root began only the ordinary real-inference diagnostic, without claiming AppContainer isolation.

Before actual profile/network execution, root checked Microsoft primary API contracts and clarified the L1 plan: intent journals alone do not authorize deletion; collisions and crash-uncertain ownership must not be adopted; file negative controls require actual ERROR_ACCESS_DENIED/5 after ordinary successful reads; NetworkIsolationGetAppContainerConfig results use their own documented process-heap cleanup. No such profile/network operation has run yet.
