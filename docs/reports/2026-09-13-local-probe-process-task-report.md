# Bounded Windows diagnostic process task report

Date: 2026-09-13. Status: diagnostic checkpoint committed as `5776792` and accepted after independent review with one nonblocking P2 below. This is not a production privacy boundary.

## Scope

- Worktree: `D:\文件AI-AGENT\.worktrees\ai-smart-naming`.
- Branch: `codex/local-privacy-mode`.
- Baseline: `82bb47676c6d97c726aea69d7424cdf26bde41dc`.
- Interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe` (Windows Python 3.14 environment).
- Only this implementer's three new files were written: `scripts/local_probe_process.py`, `tests/unit/test_local_probe_process.py`, and this report.
- No staging, commit, merge or push. The plan is root-owned. No product source, UI, packaging, Golden, credentials, registry, firewall or pagefile changes.
- Child diagnostics use harmless Python code only. No model load, inference, Provider/model API request, real credential or private document was used.

## Result and boundary

`run_bounded` implements the planned frozen `ProcessResult` contract, with raw stdout/stderr bytes, lifecycle status, exit code, PID, cleanup confirmation, elapsed time, and optional numeric Win32 error plus fixed stage. A completed lifecycle with exit code 7 is preserved as such, not converted to inference success. Captured content, arguments, environment and exception messages are not automatically logged.

The Windows binding is typed ctypes. The unnamed noninheritable Job uses `KILL_ON_JOB_CLOSE`, no breakaway option. `STARTUPINFOEX` supplies both `HANDLE_LIST` (exactly stdin/stdout/stderr child handles) and `JOB_LIST` (creation-time membership). Attribute arrays remain alive through deletion. Flags include `CREATE_SUSPENDED`, `CREATE_NO_WINDOW`, `EXTENDED_STARTUPINFO_PRESENT`, and `CREATE_UNICODE_ENVIRONMENT`. Membership is confirmed before resume. There is no unjobbed retry.

The child receives stdin EOF. The explicit environment is not merged with ambient variables. Executable and cwd must be absolute existing paths; arguments/environment reject NULs and malformed environment keys; output caps and deadlines are validated before opening handles. Windows argv quoting uses `subprocess.list2cmdline` with explicit application name, not a shell or PATH lookup.

One loop reads at most one 16 KiB chunk per stream per turn after `PeekNamedPipe`, checking cancellation/deadline between chunks. Storage is capped in raw bytes independently per stream; one extra byte can detect overflow without retaining it. Cleanup terminates only the owned Job/root handles, verifies root termination and `ActiveProcesses == 0`, and uses a separate bounded deadline. A failed confirmation returns `cleanup_incomplete`. Normal root exit also terminates descendants before bounded draining. All recorded handles and initialized attribute lists have closing paths; partial-create return values are adopted in a `finally` before reaping.

Job Objects control lifetime, not networking or filesystem permissions. This is not AppContainer, outbound isolation, a privacy guarantee, or a product local runtime.

## TDD and exact raw summaries

Initial test was written before the module. Command:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_process.py -q
```

Initial RED, exit code 1:

```text
1 failed in 0.16s
```

The assertion was `bounded process module/API is not implemented`; the file did not exist. The expanded contract tests were also run before implementation, with mandatory missing-module fixture assertions rather than skips:

```text
1 failed, 35 errors in 0.38s
```

First implementation/native run, exit code 1:

```text
1 failed, 35 passed in 2.27s
```

The sole failure was the supervisor-crash fixture's assumption that the venv `Popen.pid` was the actual Python supervisor PID. A minimal native diagnostic confirmed a venv launcher PID of 40604 with actual interpreter PID 26332, versus base interpreter PID 11676 matching the returned `Popen.pid`. This is Windows venv redirection, not `JOB_LIST` failure. The fixture now launches its actual supervisor via `sys._base_executable`, hiding its window. All normal runner tests still use the designated venv interpreter. The supervisor's own runner has a bounded deadline, and the final fixture additionally keeps precise parent/child handles with a finally cleanup fallback.

Targeted corrected supervisor test, exit code 0:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_process.py::test_supervisor_crash_kill_on_close -q
```

```text
1 passed in 0.40s
```

Additional partial-create fault tests exposed a real cleanup bookkeeping gap: a created suspended child was terminated, but returned process/thread handles were not adopted when the binding returned failure or raised. Targeted RED:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_process.py -k 'partial_create or unconfirmed or exact_raw' -q
```

```text
2 failed, 3 passed, 36 deselected in 0.59s
```

The implementation was fixed by adopting returned handles in a `finally` around process creation. Final new-file run, exit code 0:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_probe_process.py -q
```

```text
41 passed in 2.32s
```

Required four-file diagnostic regression, exit code 0:

```powershell
& 'D:\文件AI-AGENT\.venv\Scripts\python.exe' -m pytest tests/unit/test_local_model_probe.py tests/unit/test_local_probe_resources.py tests/unit/test_local_semantic_corpus.py tests/unit/test_local_probe_process.py -q
```

```text
146 passed in 10.09s
```

No whole-product test run was performed by this implementer. The four-file regression is the final executed test set before this report and freeze.

## Native proof versus injected faults

Actual Windows child-process execution, without mocking creation or Job membership, covers:

- stdout/stderr capture and nonzero root exit;
- Unicode, spaces, embedded quotes, empty argv, and backslashes;
- explicit environment isolation and stdin EOF;
- timeout and active cancellation with root termination;
- separate stdout/stderr overflow;
- sustained simultaneous stream output with deadline/cancellation still taking effect;
- exact cap versus one-extra-multibyte-output boundary, measured as raw bytes;
- a normally exiting root with a sleeping grandchild, then confirmed grandchild termination;
- an extra inheritable unnamed Event excluded from the child handle list;
- deliberate actual-supervisor termination, with the sleeping child dying from kill-on-close, checked through an owned child process handle.

Narrow private `_api` fault injection supplements, and does not replace, that native proof:

- `ResumeThread` failure after real suspended creation: marker never written and PID terminated;
- membership-query failure after real suspended creation: no resume and PID terminated;
- real creation followed by a failure return or raised exception: no resume, PID terminated, both returned handles closed, no sensitive exception text in result;
- unconfirmable Job accounting: `cleanup_incomplete`, not success, while root termination is independently checked.

Pre-cancellation and malformed input tests install a fail-if-called Job-creation guard to prove no handles are opened. Windows test fixtures assert the native platform and module availability; no Windows tests were skipped or xfailed.

The supervisor handshake is a temporary JSON array containing only supervisor/child PIDs. No unrelated process enumeration or broad PID kill is used. Its parent has a timeout and finally fallback acting only on the supervisor it created and the child identified through that handshake.

## Limitations and pending work

- Native evidence is from this Windows host and interpreter, not every Windows version or host Job policy. Unsupported/incompatible creation-time Job membership is intended to fail closed.
- The launcher is synchronous; the control-loop deadline does not make an individual Windows kernel call preemptible. The cleanup deadline is separate from the run deadline.
- The helper trusts the requested executable and arguments. It does not pin or authenticate EXE/DLL/model identities, gate RAM, or contain hostile executables' networking/filesystem access.
- Simulated API failures are labeled above; they are not claims of naturally occurring OS failures.
- Actual Qwen inference, content/translation quality, JSON-schema compatibility, processing-mode/cloud lockout, AppContainer/outbound-denial proof, user-facing model management, and packaged local runtime remain unimplemented/unverified by this task. The separate 5 GiB memory guard has not been bypassed.
- Independent review subsequently found no P0/P1. Root accepted and committed the diagnostic checkpoint; all 41 process tests passed in the final combined 156-test diagnostic run. No product integration was performed.

## Independent review backlog

P2, source-derived and not independently reproduced: the trailing output drain shares the cleanup deadline. If successful reaping consumes that deadline, the loop can skip draining remaining pipe bytes while reporting process lifecycle `completed`; trailing output or an overflow could then be missed. Before promoting this diagnostic helper to a production inference runner, report incomplete draining or provide a final bounded nonblocking drain, and require complete valid structured output. `completed` currently means process lifecycle completion, not successful or complete inference. The default three-second cleanup and existing output tests passed; this finding is not a network-isolation claim.

## Primary API references

- [UpdateProcThreadAttribute: handle/job lists and attribute-value lifetime](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [CreateProcessW: application name, environment and creation contract](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
- [Job Objects: process association and termination behavior](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
