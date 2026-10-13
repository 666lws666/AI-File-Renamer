# Fixed native hello protocol prerequisite — implementation report

## Scope and behavior

Implemented only the native C# hello source, pure Python validator, validator
tests, and this report. `ProcessResult` and the prepare/token/process
foundations were not changed. The validator checks lifecycle status, exact
integer exit code, exact cleanup flag, canonical raw stdout bytes, and empty
raw stderr. It raises `HelloValidationError` on any mismatch and never parses,
trims, or repairs output. This greeting is not token or isolation evidence.

The C# entry point rejects all arguments with exit 2 and no stdout. With no
arguments it writes the fixed ASCII greeting followed by CRLF, flushes stdout,
and returns 0. An `IOException` from standard output returns 1 without
printing exception details. Source review found no environment, filesystem,
socket, credential, or profile API calls and no path/user/security identity
claim. Only standard framework namespaces (`System`, `System.IO`,
`System.Text`) are referenced.

## TDD and verification evidence

All commands used `D:\文件AI-AGENT\.venv\Scripts\python.exe` from
`D:\文件AI-AGENT\.worktrees\ai-smart-naming`.

1. Initial RED, after the success test but before the validator existed:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_local_probe_hello.py`
   exited 1. Original summary: `1 failed in 0.20s`; failure was
   `Failed: hello validator unavailable: No module named 'scripts.local_probe_hello'`.
2. Initial GREEN, after the minimal validator interface:
   the same command exited 0 with `1 passed in 0.04s`.
3. Rejection-matrix RED, before validation logic:
   the same command exited 1 with `18 failed, 1 passed in 0.46s`;
   representative failure: `Failed: DID NOT RAISE HelloValidationError`.
4. Rejection-matrix GREEN, after exact checks:
   the same command exited 0 with `19 passed in 0.08s`.
5. During self-review, two extra fixtures exposed Python's equality between
   `bytes` and `bytearray`. RED command:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_local_probe_hello.py -x`
   exited 1 with `1 failed, 18 passed in 0.28s`; the `nonbytes-stdout`
   fixture produced `Failed: DID NOT RAISE HelloValidationError`. The parser
   now requires actual `bytes` for both streams.
6. Final combined command:
   `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py`
   exited 0 with `222 passed in 5.52s`. An earlier combined run, before the
   additional byte-type fixtures, exited 0 with `220 passed in 5.18s`.

Tests use real frozen `ProcessResult` fixtures. The negative matrix covers
timeout, launch error, output limit, cleanup-incomplete and cancelled statuses;
nonzero, missing, and boolean-zero exit codes; false/nonboolean cleanup;
partial, extra and trailing lines; BOM; alternate JSON field order; wrong
version; noncanonical newline; diagnostic stderr; and non-byte stream types.

## Self-review and limitations

The parser makes no filesystem/network calls. Its `ProcessResult` import is
restricted to `TYPE_CHECKING`, so importing the validator does not import the
process runner or initialize native Windows bindings. It accepts no security
identity claim from the child and does not examine `token_evidence`.

The C# source was deliberately **not compiled or run** here. These Python
tests do not establish CLR/AppContainer runtime compatibility or actual native
stdout/exit behavior. Root owns the ordinary compiler/run check. A contained
run still requires the separately reviewed staging and ownership journal.
No profile, ACL, model, credential, network, or Git integration action was
performed for this implementation.

## Import-purity follow-up

Review found that the original runtime `ProcessResult` import indirectly
initialized Windows bindings when the validator was imported. A new test
imports the validator in a fresh Python interpreter and asserts the process
module remains absent from `sys.modules`; the child has separate module state,
so collection-time imports in pytest cannot mask the regression.

- RED: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_local_probe_hello.py -k import_does_not_initialize_process_bindings_in_fresh_interpreter`
  exited 1: `1 failed, 21 deselected in 0.24s`. The child asserted because
  `scripts.local_probe_process` had been imported.
- GREEN: the same command exited 0: `1 passed, 21 deselected in 0.10s`.
- Final required regression command:
  `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest -q tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py`
  exited 0: `223 passed in 5.13s`.

The fix changes only the Python validator's import behavior. The C# source
remains uncompiled and unrun here; these tests still do not establish CLR or
AppContainer runtime compatibility.

## Root ordinary Windows execution (not contained)

Independent scoped review approved the corrected import behavior. Root reran the
four listed suites: **223 passed in 5.71s**, exit 0. Root then compiled the reviewed
source and ran the actual resulting x64 executable using the existing Job-bound
supervisor, with bounded streams, a sanitized environment and fixed arguments.

- Evidence: ignored QA directory `ordinary-hello-aa7c70b23a39401c96e5e63bdbe310f9`.
- Compiler: installed Framework64 v4.0.30319 `csc.exe`, SHA-256
  `46809206887326d2d24db1eff1f3064de972c3451abe766b49111450a5e08e00`.
- Source SHA-256: `a6b6269d5487f6bbcd892811aa293f9289cd48e464efb3e105313cbe623c52c8`.
- Generated EXE: 3,584 bytes, SHA-256
  `9acdd9275f9bb7601424ead85ada6ec6762ad5a8cd07dd02a67b17c22a11f2df`.
- Compilation: completed/exit 0/cleanup true, 0.133s, empty stdout/stderr.
- Ordinary greeting: completed/exit 0/cleanup true, 0.071s; exact canonical
  stdout accepted by the validator, empty stderr.
- Unexpected-argument negative: completed/exit 2/cleanup true, 0.052s; both
  streams empty. Root explicitly checked this result rather than treating it as
  a failed launch.

Raw bytes, result JSON, copied source and generated executable remain in that
unique ignored directory. No profile or ACL was changed, and no contained or
network-denial run occurred. This establishes the ordinary compiler/runtime
control only; it does not establish AppContainer compatibility or privacy.
