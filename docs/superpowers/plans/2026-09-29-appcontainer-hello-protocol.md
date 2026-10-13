# Fixed native hello protocol prerequisite

This is a narrow prerequisite of the approved AppContainer startup plan, not
profile creation, ACL staging, network enforcement or a product integration.
The existing prepare/token/process foundations stay untouched.

## Task and ownership

Implement only `scripts/native/AppContainerHello.cs`,
`scripts/local_probe_hello.py`, `tests/unit/test_local_probe_hello.py`, and
`docs/reports/2026-09-29-appcontainer-hello-protocol.md`. Root handles actual
compilation/execution and commits; implementer must not run csc, create native
profiles or change ACLs. No other working files may change.

1. Create a .NET Framework C# console source compatible with installed csc v4,
   fixed entry point and no dependencies beyond framework assemblies. Accept no
   command-line arguments; any argument returns exit 2 and emits no stdout.
   Success writes exactly ASCII `{"protocol":"xuxia-appcontainer-hello","version":1}`
   followed by CRLF to standard output, flushes and returns 0. Do not access
   environment, filesystem, sockets, credentials or profile APIs, or emit paths,
   user identity or exception details. A stdout I/O exception returns nonzero.
   This program reports only a greeting, never its own claimed security identity.
2. Provide pure `validate_hello_result(result: ProcessResult) -> None` and a
   specific validation exception in local_probe_hello.py. Require status completed,
   exit_code exactly integer zero (not bool), cleanup_complete exactly True,
   stdout byte-for-byte the canonical line above, and empty stderr. Reject partial,
   extra/trailing lines, BOM, alternate JSON serialization, wrong version, timeout,
   launch error, nonzero exit, incomplete cleanup and diagnostic stderr. Do not
   trim or repair evidence. No I/O/import-time actions. Token/isolation proof is
   deliberately separate and must not be implied by this parser.
3. TDD the parser with real ProcessResult fixtures, including positive protocol and
   each negative above; no fake test counts or static checks as runtime evidence.
   Use project Python; run the new test plus process/security/profile suites once
   after focused RED/GREEN. Report original outputs and limitations. Source review
   may assert no forbidden operations but cannot establish CLR AppContainer
   compatibility. Root's ordinary real compiler/run is a later check, and actual
   contained run still requires reviewed staging and ownership journal.

## Global constraints

No cloud API/network, keys, Credential Manager, user settings, model resources,
Golden, system-security change, Git integration/push, arbitrary executable path
API or bundled dependency changes. Real model diagnostics may run concurrently
but these owned files are disjoint and cannot change their results.
