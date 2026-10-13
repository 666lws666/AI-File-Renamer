# AppContainer hello orchestration handoff (2026-09-29)

## Scope and interface

This handoff adds only `scripts/local_appcontainer_probe.py` and its unit tests.
The fixed CLI entry point is `D:\文件AI-AGENT\.venv\Scripts\python.exe -m scripts.local_appcontainer_probe` from this worktree; it rejects every argument before effects. It does not accept a command, path, SID, compiler switch, profile name, or fallback. The default implementation wires the existing process, profile, stage, security, and hello helpers. `Dependencies` and byte inputs are Python-level test injection points, not CLI options.

The run uses a new `hello_<32hex>` QA directory; its fixed source copy, compiled output, raw bounded streams, and journal are deliberately retained as diagnostic evidence. It records SHA-256 for source, installed compiler, and compiled executable, and rejects an absent, empty, or >4 MiB executable. The installed compiler binary is **hashed in place, not copied** into the run. The compiler is run once with the fixed x64 options, sanitized minimal environment, 30-second deadline and 4096-byte stream limits. An exception or incomplete returned compiler cleanup remains unconfirmed and stops before profile preparation. No compiler failure proceeds to contained execution.

The profile is prepared without creation, trusted output staged under the derived SID, and a <=64 KiB journal intent is flushed, fsynced, and atomically replaced before profile entry. The constructed live profile helper is explicitly closed even if `prepare()` fails, to retry any retained SID/string allocation release; its own ownership flag gates deletion. The same staged executable is rechecked and run ordinarily, then after confirmed profile creation and `created` journal persistence, run with a live security context. Both hello runs use the protected stage directory as `cwd`, 15 seconds, and stdout/stderr limits of 1024/4096; the evidence run parent is not used as the child working directory. The contained result requires the exact hello, zero exit, confirmed child/Job cleanup, and parent-supervisor token evidence with exact SID, `is_appcontainer is True`, and integer-zero capabilities. Validated parent token fields are persisted in the journal; child text is never treated as token proof.

Only a confirmed returned child cleanup result permits security close, exact stage cleanup, and live profile close. If a launch raises or cleanup is unconfirmed, the journal is marked `cleanup_pending` where writable; owner/context/profile references remain live for this Python process, and the CLI returns nonzero. Collision is recorded separately and never adopted or deleted. A failed hello with completed cleanup records `completed` plus `outcome=failed`. Any cleanup or final journal failure remains nonzero. There is no restart adoption, prefix scan, automatic cleanup, `close_only` success conversion, alternate engine, model input, file/network denial test, or product integration.

`DeleteAppContainerProfile` returning S_OK does **not** establish that all Windows storage artifacts are absent. File and network denial remain unverified even if the hello protocol passes.

## Verification

TDD RED: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_appcontainer_probe.py -q` initially failed 3/3 for the expected missing module. The added post-create profile-entry regression failed 1/1 for missing explicit close before its fix. GREEN after the final fix:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_appcontainer_probe.py tests/unit/test_local_probe_stage.py tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py -q`

Initial handoff result: **334 passed in 4.45s** (33 orchestration tests and 301 existing helper tests). Review regression RED: the focused command above returned **3 failed, 33 passed** for missing token journal evidence and both prepare-close variants. After the scoped correction, the focused suite returned **36 passed in 0.75s**. Final six-suite command above returned **338 passed in 4.47s**, exit 0 (37 orchestration tests and 301 existing helper tests). Unit tests use fake Windows lifecycle boundaries; they do not create a real profile, alter ACLs, run the native compiler/probe, or use the network. The journal atomicity test alone uses real temporary filesystem writes and verifies fsync occurs before replace and a failed replace leaves the prior snapshot intact. Real contained startup, actual profile/stage cleanup, and network/file denial are unverified in this handoff. Root owns scoped review and any real native execution.

No helper/product/Golden files were changed; no commit or Git mutation was performed by the implementer.

## Root native observation and minimal environment correction

Root performed the real native runs after the initial handoff; the implementer did **not** run either native diagnostic. In baseline `hello_53475df542dbc8cc15f1934ecbd27356/journal.json`, the ordinary hello passed, but contained `CreateProcessW` failed with Win32 error **203** before parent token evidence; cleanup completed. Root's controlled ignored `hello_environment_probe.py` changed only the contained child environment by adding the parent's `LOCALAPPDATA`. Its `hello_db69fe992e474d1a2abedef463661947` run passed exact parent `TokenEvidence`, hello, and cleanup. This is a one-variable local observation, not proof of general isolation. [Microsoft's AppContainer launch documentation](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer) describes profile access through `LOCALAPPDATA` and TEMP/TMP redirection.

The fixed default CLI now passes only a nonempty, existing, absolute local-DOS `LOCALAPPDATA` copied from the parent to the **contained** child environment. Compiler and ordinary environments remain minimal; no wholesale parent environment, ACL grant, fallback, or parent environment mutation was added. Missing/invalid `LOCALAPPDATA` fails before the contained launch and permits confirmed-object cleanup. If a contained result reports `launch_error`, the outcome/journal now record fixed `contained_launch` plus its numeric Win32 code; the bounded raw process record retains the supervisor's original stage/code. A launch failure is no longer mislabeled as missing token evidence.

Review-fix TDD RED: `D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_appcontainer_probe.py -q` returned **8 failed, 37 passed** before implementation; the embedded-NUL case exposed a test-fixture limitation (Windows rejects NUL in an actual environment), so it was corrected to inject a synthetic environment mapping. A further prelaunch-cleanup regression returned **1 failed** before validation was moved ahead of the uncertainty flag. Final focused command returned **46 passed in 0.79s**. Final six-suite command shown above returned **347 passed in 4.25s** (46 orchestration and 301 helper tests), exit 0. These are fake Windows lifecycle tests plus the existing real temporary journal-file test; the implementer did not repeat the native CLI. Root must review and rerun the default CLI to verify the correction.

## Root default-CLI native gate

After independent approval of the minimal correction, root ran the unmodified
default entry point `python -m scripts.local_appcontainer_probe`: exit **0**.
Evidence run: `hello_495c0033ddb0d1a52fa52480a6e1a460` under the ignored QA root.

- Script SHA-256: `fcd1751468032b5e28eb5d3d8db29f8e927357f4d99560a27ff50f195ce368f5`.
- Compiler/source hashes match the recorded inputs above. This newly compiled
  executable hash is `587a42e263600e9366bf3347ac4b18ec68da58b282596fc271fcfc3d8358c09a`;
  it is not compared against an older build's binary hash.
- Compile, ordinary and contained processes all returned exit 0 with confirmed
  cleanup. Root separately read the contained stdout's exact hello JSON.
- Parent token: `is_appcontainer=true`, capability count integer `0`, exact SID
  `S-1-15-2-82251757-1808500940-1938054162-1812248641-3068099340-852022030-4016191502`.
- Journal completed/passed. Separate read-only checks confirmed both exact stage
  paths were absent and the expected per-user Packages directory for
  `xuxia_probe_82dc9eb99368dee92dea44ec7eb1ffef` did not exist. This latter path
  check is not a claim that every possible Windows storage/registry artifact was
  independently enumerated; the API-deletion limitation remains.

No sockets, network-denial test, model or private input was used. This gate proves
contained hello startup/token validation/owned cleanup, not overall privacy mode.

## Root full non-screenshot regression

An ignored QA wrapper isolates LOCALAPPDATA/APPDATA/TEMP/TMP and explicitly uses
`keyring.backends.fail.Keyring`, preventing real credential backend access. Its
first run placed temporary data beneath the install checkout: **3 failed, 2619
passed, 1 skipped, 3 warnings**. Two failures explicitly required test data outside
the install checkout. A third was an `os.replace` PermissionError on the deeply
nested temporary path; its precise cause was not independently established.

Root corrected only the wrapper to use a new OS temporary directory outside the
checkout, keeping all product/test assertions unchanged. Those three exact tests
then passed (**3 passed, 3 existing warnings**). The subsequent complete command
`pytest tests/ --ignore=tests/screenshots -q`, through that wrapper with no test
selection exclusions, returned **2631 passed, 1 skipped, 3 warnings in 139.71s**,
exit 0. Raw output is retained as `regression-native-hello-full.txt` in the QA root.
The warnings are the existing three Pydantic class-config deprecations. Screenshot,
acceptance, package and model-isolation gates are not claimed by this run.
