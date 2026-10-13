# Fixed access orchestration handoff — 2026-09-29

## Scope and status

This slice extends the existing hello diagnostic lifecycle with one fixed access mode. The implementer used fake-only tests, with no native/profile/socket/ACL or Git mutation. Root subsequently executed the actual Windows diagnostic below. The strict native access gate **FAILS**, despite successful file enforcement and external-connect denial; no model/product privacy claim is made.

Changed files: `scripts/local_appcontainer_probe.py`, new `scripts/local_probe_listener.py`, new `tests/unit/test_local_appcontainer_access.py`, new `tests/unit/test_local_probe_listener.py`, and this report. The pre-existing untracked `.superpowers/` directory was not touched.

## Public interface and fixed flow

- `run_diagnostic(..., *, probe_kind="hello", framework_bytes=None)` accepts only exact `hello` or `access` before effects. No-argument CLI remains hello; exactly `--access` selects access; other arguments exit 2 before effects. `framework_bytes` is a test-only byte injection analogous to existing source/compiler injections; the actual CLI reads the fixed installed `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.dll` and journals its SHA-256.
- `Dependencies` retains its five original positional fields and adds optional `exemption` and `listener` factories. If omitted in access mode, the fixed `OwnedLoopbackExemptionQuery` and `OwnedControlListener` constructors are called lazily. Hello does not construct either owner or stage fixtures.
- Access copies fixed `AppContainerAccess.cs`, compiles with `/noconfig` and the absolute fixed System.dll `/reference:`, stages the resulting bytes with `include_fixtures=True`, and consumes only the two exact `owner.recheck().fixtures` records. Parent journal records fixture paths, byte sizes and SHA-256 before child launch.
- The owned exemption query is retained through `query()` and `require_not_exempt()`. The fixed listener binds `127.0.0.1:0`, verifies the actual bound address and port, makes listener and accepted socket non-inheritable, and independently verifies 26 exact nonce bytes followed by EOF within a two-second receipt deadline. It records only byte count and SHA-256, never received payload text. The listener stays live through the contained child.
- Ordinary and contained children receive fixed `mode, allowed, denied, port` arguments, stage cwd, 15-second supervisor bounds and respective environments. Both use the reviewed access validator; contained additionally retains the existing parent token verification. Access stdout is bounded at 4096 bytes. Typed validated measurement records and token evidence are journaled separately from preserved raw streams; stage cleanup is reported separately.
- `Outcome` adds `retained_exemption` and `retained_listener` for cleanup-pending ownership. Listener/exemption close are explicit before shared security/stage/profile cleanup. Uncertain child cleanup still returns early without deleting stage/profile. Any failed close or journal write is nonzero/pending; primary native error stages and codes are preserved across ordinary cleanup.

The journal limitations state that success covers only the two synthetic files and two fixed endpoints, that standard AppContainer can access public system resources, and `model_isolation_unverified`.

## Fake-only TDD and regression evidence

Project interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`; workdir: `D:\文件AI-AGENT\.worktrees\ai-smart-naming`. The default process helper failed with `helper_unknown_error: setup refresh had errors`, so pytest invocations used `require_escalated` for process creation. The tests themselves used injected fakes only.

1. Listener collection initially failed because its module did not exist. After a minimal scaffold, the meaningful RED test failed on `NotImplementedError` in `OwnedControlListener.__init__`. Listener GREEN: **8 passed**.
2. Access orchestration RED failed on missing `Dependencies.exemption`. After the shared-flow implementation, the new access, existing hello and listener suites were **60 passed**, then **65 passed** after failure-path cases.
3. Final specified regression command: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_appcontainer_access.py tests/unit/test_local_probe_listener.py tests/unit/test_local_appcontainer_probe.py tests/unit/test_local_probe_access.py tests/unit/test_local_probe_exemptions.py tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_stage.py tests/unit/test_local_probe_profile.py tests/unit/test_local_probe_security.py -q --tb=short` — **496 passed in 5.58s**, exit 0. `git diff --check` exited 0, with only Git's LF-to-CRLF working-copy warning.

Fake tests cover exact fixed compiler reference and child argv, fixture/journal facts, preflight ordering, listener nonce, malformed receipt and bound address, positive-control gate, exemption failure and retained owner, wrong token, alternative denial errors, CLI and kind rejection, plus all existing hello failure/cleanup cases. They do not prove Windows AppContainer enforcement or native resource behavior.

## Root gate still required

Independent review, then real `python -m scripts.local_appcontainer_probe --access`; inspect compiler/reference/source hashes, raw ordinary and contained JSON, expected SID/token, exemption count and cleanup, parent nonce receipt, exact denied-file/open error 5 and socket connect error 10013, stage/profile cleanup and known-path absence. Any mismatch is a failed experiment, not a privacy attestation. Model staging remains out of scope until that gate passes.

## Scoped evidence-ordering review fix

The preceding **496 passed** result is retained as the original freeze history. Before any native run, review found two provenance gaps in failure evidence. Two new fake-only regressions first failed as expected: an incomplete stage cleanup report left `journal["stage_cleanup"]` null, and a valid parent token followed by a failed contained access verdict left `journal["token_evidence"]` null. Focused RED: **2 failed** on those exact missing journal facts. The minimal fix records the stage cleanup report before failing closed on `complete != True`, and persists the strictly checked parent token immediately after its check, before validating the contained child measurement. An invalid token still leaves the journal token field null. Raw contained streams remain preserved and no invalid measurement is promoted to validated evidence.

Focused GREEN: **2 passed**. The same ten-suite command listed above then returned **498 passed in 5.69s**, exit 0. This remains fake-only verification; no native, profile, ACL, or real socket operation was performed. No Git mutation was made.

## Root actual native runs — strict gate FAIL

Command: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m scripts.local_appcontainer_probe --access`.
All raw artifacts remain under `tests/screenshots/qa-current/local-privacy/`.

1. `access_114dc8aa7f923fb3758cde42cf98a247`: ordinary control passed;
   contained allowed-file read succeeded, denied-file open returned5, but both
   connection measurements were recorded as timeout. CLI exited1.
2. `access_58fc7688c161e9229d4026e108d96daa`: root one-variable source experiment
   additionally checked `SelectError` after `SelectWrite` had not signalled. External
   SO_ERROR became actual10013; loopback remained timeout. CLI exited1. No predicate
   changed, no timeout accepted as denial, no firewall/exemption change occurred.
3. Final corrected source, `access_8a67740f9376cc0c66f004295bd916d8`: same partial
   result, CLI exited1 (`contained_access`). Compiler, ordinary and contained child
   all completed with exit0 and confirmed process/Job cleanup. Measurement completion
   does not imply gate success. Journal `state=completed` means cleanup completed;
   `outcome=failed` remains the actual verdict.

Final run evidence:

- Source SHA-256 `5e25a4331183727adaec79f1f7f2cec9888a2d6a39565386838a81fac7f23579`;
  compiled EXE SHA-256 `c67b7e37dad4f6368a4edccb953ac9dbb79df5daa14f3fba70afecc42a37eaae`.
- Parent verified exact package SID
  `S-1-15-2-1617440111-3053343597-1903247173-1198511450-1716175989-2762746362-3317497172`,
  AppContainer=true, capability_count=0. Read-only exemption count0/nonexempt,
  allocations cleaned. Parent received exact26-byte ordinary nonce plus EOF.
- Contained allowed file: opened/read/exact-content/closed. Denied file: actual
  open_error5, not opened/read. External socket: created, actual connect_error10013,
  no timeout/send, closed. Loopback socket: created, timed_out=true, no connect_error
  or send, closed. No validated contained measurement was fabricated.
- Each run reported exact-owned cleanup complete, handles_closed=true, empty
  remaining/uncertain/failure lists. Root independently confirmed each exact stage,
  stage EXE and expected Packages/profile directory absent. This does not enumerate
  every possible Windows profile storage/registry artifact.

## Investigation and next decision

[Microsoft Poll documentation](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.socket.poll?view=netframework-4.8.1)
distinguishes successful nonblocking connection readiness from failure readiness.
The original write-only check omitted the latter; the single-variable run proved
that omission hid the external10013 on this host.

[Project Zero's first-hand AppContainer research](https://projectzero.google/2021/08/understanding-network-access-windows-app.html)
reports that loopback blocking occurs at the receive/accept layer and can appear
as a client timeout. [Microsoft's WFP troubleshooting guidance](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall)
describes correlating dropped events with package/application identity and filters.
These sources explain a plausible host result; they are not this machine's drop
trace. The plan's universal loopback10013 requirement is therefore technically
unsound, but it has **not** been silently relaxed. Current parser still fails.

Before model containment, decide on an alternative loopback evidence gate that
requires the live positive control, exact token/nonexemption, and attributable
Windows filtering-platform BLOCK evidence for this specific synthetic probe.
Timeout alone is never sufficient. No capture/session, audit policy, exemption,
firewall or administrator change has been made. If trace access requires new
authority, request it; do not collect unrelated applications' private traffic.

## Root whole-checkout regression

Frozen source full non-screenshot run, with temporary user data outside checkout
and fail-only keyring backend:
`python tests/screenshots/qa-current/local-privacy/run_isolated_regression.py tests/ --ignore=tests/screenshots -q -rs`
returned **2782 passed, 1 skipped, 3 warnings in58.51s**. Skip: Windows symlink
creation unsupported. Warnings: three existing Pydantic class-config deprecations.
`python acceptance_test.py`: **186/186, 0 failed** with its isolated configuration
and mocked credential backend. These passing regressions do not override the
strict native privacy gate failure.

Final frozen-tree screenshot command through the same isolated QA runner:
`tests/screenshots -q -rs` returned **54 passed, 1 skipped, 86 warnings in31.37s**.
Update mode was not enabled; the explicit update-mode test was the sole skip.
Warnings are existing Pillow `getdata` deprecations. No formal Golden changed.
