# Bounded Windows Diagnostic Process Plan

> Use subagent-driven-development and test-driven-development. This is L0 experiment preparation, not the product local runtime or an outbound-isolation gate.

**Goal:** Launch a trusted local diagnostic child with bounded stdout/stderr, deadline and cancellation, and prove that its entire process tree is reaped. Use harmless Python children only. Do not load the model while the separate 5GiB memory guard fails.

**Architecture:** A small Windows-only diagnostic module explicitly creates a process with restricted inherited standard handles and an unnamed kill-on-close Job Object assigned at creation. The child stays suspended until membership is confirmed. One bounded polling loop owns pipe reads and cancellation. The module has no networking, Provider, UI or product integration.

**Tech Stack:** Windows 11, current Python 3.14, ctypes Win32 APIs; existing pywin32 may be used for Job/handle queries. No new dependency or system-security changes.

## Scope and ownership

- Worktree `D:\文件AI-AGENT\.worktrees\ai-smart-naming`, branch `codex/local-privacy-mode`, baseline `82bb47676c6d97c726aea69d7424cdf26bde41dc`.
- Own only new `scripts/local_probe_process.py`, new `tests/unit/test_local_probe_process.py`, and new `docs/reports/2026-09-13-local-probe-process-task-report.md`. Main owns this plan and handles Git/independent review.
- No edits to src, QML, existing scripts/tests, resources, credentials, Golden or packaging. No model load, API, network request, real Key, private file, registry/firewall/pagefile change, commit, merge or push.
- Root and other agents are read-only on these files while the implementer writes. Freeze after tests/report. Do not change scope to implement AppContainer or a user-facing launcher.
- Job Objects control lifetime, NOT networking, filesystem access or privacy. Neither successful child cleanup nor an offline CLI flag establishes local-mode privacy.

## Reference decisions

Microsoft primary references checked on 2026-09-13:

- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw
- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

Use `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` for exactly the child stdin/stdout/stderr handles, and `PROC_THREAD_ATTRIBUTE_JOB_LIST` for creation-time job membership (Windows 10+). Attribute arrays must stay alive until the attribute list is deleted. Local pywin32 STARTUPINFO does not expose lpAttributeList; use a correctly typed ctypes STARTUPINFOEX/CreateProcessW binding rather than private subprocess attributes or untyped pointer calls. Unsupported creation-time membership fails closed; do not retry unjobbed.

## Public diagnostic contract

`run_bounded(executable: Path, arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str], timeout_seconds: float, cancellation_event: threading.Event | None = None, stdout_limit: int = 262144, stderr_limit: int = 1048576, cleanup_timeout_seconds: float = 3.0) -> ProcessResult`.

Use a frozen result with `status`, `exit_code`, `stdout: bytes`, `stderr: bytes`, `pid`, `cleanup_complete`, `elapsed_seconds` and an optional sanitized numeric Win32 error/stage. Status distinguishes `completed`, `cancelled`, `timeout`, `output_limit`, `launch_error` and `cleanup_incomplete`. A nonzero child exit can still be a completed lifecycle; do not turn it into success at the inference layer. Do not echo arguments/environment or log captured content automatically. The caller separately validates pinned EXE/DLL/model identities and RAM before actual inference; this primitive makes no trust claim about arbitrary executables.

- Reject nonabsolute/missing EXE or cwd, NUL-containing args/env, invalid environment keys, nonfinite/nonpositive deadlines, invalid output bounds before opening handles. Output limits are per stream, positive integers no greater than 16MiB. Cleanup timeout is positive and at most 10 seconds. Pre-cancel returns cancelled without spawning.
- Use explicit lpApplicationName and correct Windows command-line quoting; no shell/PATH search. Supply the explicit environment only, not a merge with all ambient variables.
- No production caller is introduced by this task; no arbitrary-argument end-user CLI is required.

## Required implementation behavior

1. Unnamed noninheritable Job, KILL_ON_JOB_CLOSE, no breakaway flags. Inheritable child pipe ends only; parent ends noninheritable. stdin receives EOF, not inherited console input.
2. STARTUPINFOEX HANDLE_LIST and JOB_LIST, CREATE_SUSPENDED + CREATE_NO_WINDOW + EXTENDED_STARTUPINFO_PRESENT + CREATE_UNICODE_ENVIRONMENT. Confirm actual membership before ResumeThread. On any failure, terminate any created suspended/root process or job and reap it; never resume an unbound process.
3. One control loop alternates bounded reads from stdout/stderr after PeekNamedPipe. Limit raw bytes (not decoded character count), recheck cancellation/deadline between chunks, avoid blocking reader threads and stream starvation. Keep at most each configured cap and mark output_limit if either overflows.
4. On cancel/timeout/overflow/exception, terminate the job. On normal root exit, also terminate surviving descendants and drain only bounded remaining output. Wait for root termination and job ActiveProcesses == 0 with a separate bounded cleanup deadline. If cleanup cannot be confirmed, return cleanup_incomplete, never completed. Close every created handle and attribute allocation in all paths; kill-on-close is the supervisor-crash fallback.
5. Diagnostics must remain hidden (CREATE_NO_WINDOW). Do not enumerate/kill unrelated processes. Only child PIDs/handles created by these tests can be terminated.

## Task 1: TDD and native proof

- [x] Write initial tests first and record a genuine RED because this module/API is missing; final fixtures must fail rather than skip when implementation is absent.
- [x] Implement the minimal module; add actual native tests for: stdout+stderr capture and nonzero exit; Unicode/space/quote argv; explicit environment isolation; stdin EOF; pre-cancel no spawn; timeout; active cancellation; stdout overflow; stderr overflow; a root spawning a sleeping grandchild then exiting (grandchild must be gone); extra inheritable Event excluded; injected ResumeThread failure with no live/suspended child.
- [x] Add a bounded supervisor-crash test: a separate test supervisor launches a sleeping child under this runner, writes only its own/child PID to a temp handshake, then is deliberately terminated by its test parent; prove its child dies by kill-on-close. Keep a finally fallback that only cleans these exact owned PIDs. Test partial-create cleanup via a narrow private binding seam when needed; do not add general public hooks.
- [x] Assert invalid bounds/nonfinite values/NUL input fail before CreateProcess; prove stream flood cannot indefinitely postpone cancellation/deadline. Use real harmless Python code, no model/mock used as native proof. Windows tests must actually run here, not xfail/skip.
- [x] Run `python -m pytest tests/unit/test_local_probe_process.py -q`, then the three existing local diagnostic test files plus this new file. Record exact raw summaries. Do not run the entire product suite repeatedly during implementation; root runs the final regression.
- [x] Write the report (RED/GREEN, native tests vs mocks, files, limitations), freeze, and return without staging/committing. Independent review occurs before accepting this diagnostic checkpoint.

## Explicitly pending after this task

Actual Qwen inference, content/translation quality, JSON-schema compatibility, processing-mode/cloud lockout, AppContainer/outbound-denial proof, user-facing model management and packaged local runtime remain unimplemented/unverified. This helper must not change their status.
