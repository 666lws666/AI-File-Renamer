# Token-bound diagnostic supervisor integration

Use subagent-driven-development and TDD. This is the remaining supervisor portion of L1 Task1; no native profile/network experiment or product integration is authorized by passing these unit tests.

Baseline: `6aaf955b68e7c0e6b1af0f2141677f8bd4a90924`. Token foundation has independent113-pass helper/process regression and Critical0/Important0 review. Naming probe is owned by another agent; root runs no model while these process files change. All runtime files must freeze before the next actual naming matrix.

## Task 1: optional exact security context at creation, verification before resume

Files owned: `scripts/local_probe_process.py`, `tests/unit/test_local_probe_process.py`, new `docs/reports/2026-09-13-token-bound-supervisor.md`. Do not edit the token helper/test, runner/test, src, resources, corpus, Golden or Git. No model/network/profile/ACL/security-policy operations.

- [ ] RED: optional `security_context` is an active exact `AppContainerSecurity`, not a caller-defined attribute/verification callback. Invalid type/inactive/modified context fails before resource creation. `None` preserves the existing launch contract.
- [ ] Add a final optional/defaulted immutable token-evidence field to ProcessResult, preserving positional compatibility. Ordinary diagnostics return None; verified security evidence is retained separately from lifecycle success and cannot be faked by child stdout.
- [ ] Import the canonical helper without duplicating its class or SID logic. Retain context and the same SECURITY_CAPABILITIES object through DeleteProcThreadAttributeList. Caller owns the context and must enclose this function with its lifetime; the function must not close or replace it.
- [ ] Allocate attribute count3 only when security is supplied, otherwise count2. Attach `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` (0x00020009) in addition to unchanged exact HANDLE_LIST and creation-time JOB_LIST. No arbitrary capabilities/attributes, alternate parent, uncontained retry or fallback.
- [ ] Preserve CREATE_SUSPENDED/NO_WINDOW, immediate handle adoption on partial CreateProcess errors, existing Job validation and bounded reaping. After Job membership and before ResumeThread call context.verify_process on the exact owned child handle. Recheck deadline/cancel before resuming. Any token query/identity/capability/cleanup exception must prevent resume and return fixed stage/numeric error with normal owned-tree cleanup, not exception text.
- [ ] Test ordering and actual attribute contents/lifetime with narrow injected Win32 bindings or existing native boundary spies, not replacing run_bounded or fabricating whole successful results. Cover attribute attach failure; wrong identity/noncontainer/nonzero capability/query failure; no resume; exactly one creation attempt; closed/mutated context; context remains owned by caller; default count2 unchanged; valid context verified before resume; cancellation during verification prevents resume; token close failure remains fail-closed.
- [ ] Run process tests, token tests and all existing diagnostic runner/policy tests. Do not edit another agent's changing runner tests; notify root to run combined regression after its freeze instead if necessary. Existing native ordinary-process tests still run, but no successful-container claim is permitted until the later explicit profile probe.
- [ ] Freeze owned files, report original RED/GREEN summaries and remaining native gates. Root reviews and checkpoints only this scope; do not stage/commit.

The real network gate later needs a live positive control and explicit permission-denied negative, not --offline/localhost assumptions. All current memory/output/deadline/resource checks remain unchanged.
