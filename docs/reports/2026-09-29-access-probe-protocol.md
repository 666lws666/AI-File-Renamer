# Fixed access probe: source and protocol handoff (2026-09-29)

Latest root default-CLI rerun: `access_8a67740f9376cc0c66f004295bd916d8` uses the
corrected SelectError source; external10013 and denied-file5 were observed, while
loopback remained timeout. The strict contained gate still FAILS. See the paired
`2026-09-29-appcontainer-access-orchestration.md` report for evidence and cleanup.

## Scope and status

This handoff covers only `scripts/native/AppContainerAccess.cs`, `scripts/local_probe_access.py`, and pure parser tests in `tests/unit/test_local_probe_access.py`. The implementer did **not compile or execute** the C# source. Root subsequently performed the ordinary-process native control documented below. AppContainer access denial and model isolation remain unverified by this slice; source-backed expectations are not OS denial results.

The parent must compile the fixed source with installed .NET Framework `csc.exe`, `/noconfig`, and an explicit reference to the installed framework `System.dll` for `System.Net.Sockets.Socket`. No NuGet package or external config is required. The parent owns subsequent compilation, native launch, listener/nonce receipt, token attestation, non-exemption preflight, staging identity, and cleanup review.

## Wire contract and source-backed behavior

The child accepts exactly four arguments: `ordinary|contained`, absolute same-parent local `allowed.txt` and `denied.txt` paths, and canonical decimal port 1–65535. Input rejection returns 2 with empty streams before file/socket effects. Paths containing NUL, UNC/device syntax, traversal, ADS, invalid Windows filename characters, or reserved DOS device components are rejected. Endpoints are fixed to IPv4 `127.0.0.1:<port>` and, in contained mode only, `192.0.2.1:443`; there is no DNS, HTTP, TLS, external application data, arbitrary host, or model-derived endpoint. The parent supplies paths from trusted owned stage evidence, not model text.

The file records come from `CreateFileW(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING)` and a read of at most expected length plus one. Expected bytes are `xuxia-allowed-fixture-v1\r\n` (26) and `xuxia-denied-fixture-v1\r\n` (25). Open/read errors use the immediate `GetLastWin32Error`; valid handles are closed. Each attempted TCP target uses a fresh nonblocking AF_INET/TCP socket. `WSAEWOULDBLOCK` 10035 leads to a bounded `Poll` and `SO_ERROR` query. A wait expiry is `timed_out`, not access denial. Ordinary mode sends exactly `xuxia-loopback-control-v1\n` (26 bytes) to the connected loopback listener with bounded attempts; contained mode never sends. The parent must independently verify receipt.

On a complete measurement, stdout is exactly one compact ASCII JSON object plus CRLF, at most 4096 bytes; stderr is empty. The child exits 0 only after emission and successful closure of owned handles. Permission mismatch is still a measurement and need not make the child nonzero. Invalid arguments return 2, unexpected failures return 1 without exception text. A zero child exit is not itself a denial-pass verdict.

Top-level JSON keys, with no additions or omissions: `protocol`, `version`, `mode`, `file_allowed`, `file_denied`, `loopback`, `external`. `protocol` is `xuxia-appcontainer-access`; `version` is integer 1. Each file object has `attempted`, `opened`, `open_error`, `read_attempted`, `read_error`, `content_ok`, `close_ok`. Each socket object has `attempted`, `socket_created`, `socket_error`, `connect_error`, `poll_error`, `timed_out`, `send_error`, `sent_bytes`, `close_ok`. Errors are nonnegative integer Win32/Winsock values or null; booleans cannot substitute for integers. The ordinary external object is explicitly unattempted, with null errors, false `socket_created`/`timed_out`, zero `sent_bytes`, and true `close_ok`.

`socket_error` distinguishes construction failure; `poll_error` distinguishes readiness or `SO_ERROR` query failure from connection denial; `send_error` and `sent_bytes` distinguish the positive-control send. Socket creation alone and a successful poll alone are not successful connection. No error is inferred from exception message text.

## Python interface and verdict

`validate_access_result(result, *, mode: str, expected_sid: str | None = None) -> AccessEvidence` is pure on import; it imports `ProcessResult` only for type checking. `AccessEvidence` is frozen and contains `protocol: str`, `version: int`, `mode: str`, `file_allowed: FileEvidence`, `file_denied: FileEvidence`, `loopback: SocketEvidence`, `external: SocketEvidence`, and `package_sid: str | None`. `FileEvidence` and `SocketEvidence` are frozen and expose the exact wire fields above with corresponding `bool`, `int | None`, and `int` types. Ordinary evidence has `package_sid=None`; contained evidence has the checked `expected_sid`.

The validator requires `status="completed"`, integer (not boolean) `exit_code=0`, `cleanup_complete is True`, byte stdout/stderr, empty stderr, a bounded ASCII canonical compact JSON object plus CRLF, exact schemas and types, no duplicate keys, and matching protocol/version/mode. It raises `AccessValidationError(code)` with a fixed bounded code, never raw child bytes, path, or error text.

Ordinary pass requires both exact file reads and closes, loopback socket construction and `connect_error=0`, no timeout/poll error, `send_error=0`, `sent_bytes=26`, close, and no external attempt. Contained pass additionally requires parent `token_evidence.package_sid == expected_sid`, `is_appcontainer is True`, and integer `capability_count=0`; allowed file exact read; denied file not opened with `open_error=5` and no read/content; both sockets constructed, each with `connect_error=10013`, no timeout/poll/send and successful close. Thus missing file 2, sharing violation 32, timeout/refusal/unreachable, constructor/poll failure, success where denial is expected, boolean error values, partial send, and incomplete cleanup fail closed. This verifies only those exact reported facts and the parent token check, not general product/model privacy.

## TDD and verification

Project Python: `D:\文件AI-AGENT\.venv\Scripts\python.exe`. All commands used workdir `D:\文件AI-AGENT\.worktrees\ai-smart-naming`. Initial test collection found the absent validator import. With a minimal `NotImplementedError` stub, the meaningful RED command was:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_access.py::test_accepts_complete_measurement -q`

Result: **2 failed**, both on `NotImplementedError` for genuine ordinary and contained synthetic records. After parser implementation, GREEN and related regression command:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_access.py tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py -q`

Result: **211 passed in 4.11s; final repeat: 211 passed in 2.98s**. Parser tests include positive controls; alternative file/socket error codes and facts; missing/wrong token, SID, and capability count; sent-byte errors; duplicate/extra/missing JSON fields, trailing data, BOM, size/type errors; and process/cleanup failures. These synthetic tests validate the Python verdict only and do not claim C# OS behavior. C# compilation and actual measurements remain parent-owned gates.

## Primary API references (expectations, not execution evidence)

- [Socket.Connect](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.socket.connect?view=netframework-4.8.1)
- [Socket.Poll](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.socket.poll?view=netframework-4.8.1)
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [Windows Sockets error codes](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)

## Scoped reviewer follow-up (same four-file slice)

The earlier 211-pass result above is retained as history. A parser regression now forces a decoder `RecursionError` on bounded, deeply nested JSON and requires fixed code `json`, without leaking the decoder's text. RED command: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_access.py::test_rejects_deeply_nested_json_with_fixed_error -q`; result: **1 failed**, due to an uncaught `RecursionError` from the JSON decoder. After adding `RecursionError` to the fixed-error mapping, the same new/hello/process/security command above reports **212 passed in 2.71s**.

Static C# source corrections, not native test results: zero-byte `Socket.Send` now stops with observed partial `sent_bytes` and null `send_error`, without inventing Winsock 10053; the strict Python verdict already rejects an incomplete send. Path parsing exceptions inside the input-only `ValidArgs` stage now produce false, so `Main` returns 2 with empty streams before any file/socket call. The send budget uses monotonic `Stopwatch`, no more than one second of calculated poll wait in total and at most 32 send attempts; each poll receives no more than remaining budget (capped at 100 ms). Native compilation, invalid-input exit behavior, and actual positive/negative socket/file measurements remain unperformed in this slice and must be checked by the parent.

## Root ordinary-process native verification

After scoped re-review approval, root ran
`D:\文件AI-AGENT\.venv\Scripts\python.exe tests/screenshots/qa-current/local-privacy/ordinary_access_smoke.py`.
Exit **0**; evidence directory
`tests/screenshots/qa-current/local-privacy/ordinary-access-06320b231a0342829b02876808398b5e`.

- Source SHA-256 `e116fe30bd812af007ff244be91084525bf0318509ce95101201e6040eda7c33`.
- Compiler SHA-256 `46809206887326d2d24db1eff1f3064de972c3451abe766b49111450a5e08e00`;
  referenced System.dll SHA-256 `2b3c17c6208a0b4b6beb94e1a066f99ba06cdb2ea919479e99d47e8c6d96dc71`.
- Compiled EXE: 10,240 bytes, SHA-256
  `f492bcddad2b040f8d8f9ad7cd5af7af5c50fad6fad34f90b63e32ab380290e3`.
- Compilation and ordinary process completed with exit0 and confirmed supervisor
  cleanup. Both synthetic files read exact expected bytes. Actual loopback connection
  succeeded, child reported26 bytes, and parent independently received the exact
  nonce followed by EOF. No external connection was attempted.
- Quote/control-character paths, noncanonical port and invalid argument count each
  actually exited2 with empty stdout/stderr and confirmed cleanup.
- Root fresh new/hello/process/security suites: **212 passed in 2.62s**.
- A separate real2,202-byte nested-JSON input was safely rejected as fixed `schema`
  on this Python3.14 interpreter, not `json`: the first diagnostic incorrectly
  expected a recursion exception and failed its own expected-code assertion. The
  corrected check accepted the actual fixed rejection and passed. Only the injected
  decoder-failure test proves the `RecursionError` mapping; no real recursion failure
  is claimed for this host.

No contained child, actual denied-file attempt, outbound denial, profile change,
cloud API, credential access or product privacy acceptance occurred in this control.

## Native gate observation and one-line `SelectError` correction

The parent subsequently compiled and ran the native gate. Baseline artifact `tests/screenshots/qa-current/local-privacy/access_114dc8aa7f923fb3758cde42cf98a247/contained.stdout` reports both contained sockets created but `connect_error:null` and `timed_out:true`; allowed-file read succeeded and denied-file open returned 5. A one-variable experimental source snapshot in `access_58fc7688c161e9229d4026e108d96daa` added a zero-time `SelectError` check after the bounded `SelectWrite` wait. Its `contained.stdout` reports external `connect_error:10013`, `timed_out:false`, while loopback remains `connect_error:null`, `timed_out:true`. Its journal records the ordinary control and nonce receipt. The contained gate remains **failed** under the unchanged strict parser.

The fixed C# source now incorporates only that already-exercised condition: after unsuccessful `SelectWrite` poll, check `SelectError` at zero wait before declaring timeout, then read `SO_ERROR` if either condition signals. [Microsoft's Socket.Poll documentation](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.socket.poll?view=netframework-4.8.1) distinguishes `SelectWrite` for a successful nonblocking connect from `SelectError` for a failed one. [Project Zero's AppContainer localhost analysis](https://projectzero.google/2021/08/understanding-network-access-windows-app.html) describes loopback blocking at the receive/accept layer, which yields a timeout rather than an immediate connect error. This is a plausible explanation for the observed loopback timeout, not an independent WFP measurement in these artifacts. A timeout was **not** reinterpreted as access-denied 10013; the Python verdict remains unchanged. A separately scoped WFP-level verification decision belongs to the parent/user.

After the one-line source correction, the unchanged Python regression command above reports **212 passed in 2.86s**. This command does not compile or execute the C# source. The parent's experimental run supports the narrow `SelectError` correction, but the exact final source still awaits the parent's native rerun; no contained PASS is claimed.
