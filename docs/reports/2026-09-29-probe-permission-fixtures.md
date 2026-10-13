# Fixed permission fixtures: implementation handoff

Scope: only the trusted local staging helper and its fake-native unit tests were changed. No native AppContainer run, profile creation, real ACL mutation, process launch, network access, or fixture access-denial assertion was performed here. The root owner retains the later native validation gate.

## Contract implemented

- `stage_probe(..., *, include_fixtures=False)` preserves omitted/false hello behavior and rejects non-boolean values before native calls.
- True creates only `allowed.txt` and `denied.txt` under the exact owned stage directory, with fixed CRLF byte payloads and per-object immutable evidence (path/name, volume/file ID, SHA-256, size, one link, security facts).
- Both have protected, present, non-NULL DACLs: current user and SYSTEM get `FILE_ALL_ACCESS`; only the allowed file has the exact package SID's `FILE_GENERIC_READ` (`0x120089`). The denied file has no package ACE. Directory and EXE descriptors remain unchanged.
- Existing CREATE_NEW, nofollow open, identity/path/type/link/volume/content/security readback, partial owner, and exact handle-based cleanup paths are reused. Fixture creation handles are closed; `recheck()` temporarily reopens, verifies, and closes them. A failed close leaves its handle with the owner.
- Cleanup orders fixtures before EXE and directory and stops on the first failed object; retry and `close_only()` retain the existing explicit ownership semantics. A literal-True child cleanup confirmation is still required.

## Verification

Project interpreter: `D:\文件AI-AGENT\.venv\Scripts\python.exe`.

Focused RED, before implementation:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_stage.py -q`

Result: 83 failed, 17 passed. The new tests and existing stage tests failed at the missing `include_fixtures` keyword, confirming the new API was absent. This broad RED count is not a claim that 83 independent behaviors were broken.

Focused GREEN:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_stage.py -q --tb=short`

Result: 116 passed. After adding further fixture fault and omitted-default coverage, the final required regression command was:

`D:\文件AI-AGENT\.venv\Scripts\python.exe -m pytest tests/unit/test_local_probe_stage.py tests/unit/test_local_probe_hello.py tests/unit/test_local_probe_process.py tests/unit/test_local_probe_security.py tests/unit/test_local_probe_profile.py tests/unit/test_local_appcontainer_probe.py -q --tb=short`

Result: 389 passed in 5.60 seconds, exit code 0. Tests use the existing fake native boundary; pywin32 descriptor serialization is checked without applying an ACL.

## Limitations and handoff gate

Fake-native success proves helper sequencing and exact expected descriptor facts, not Windows access enforcement. The real positive ordinary reads of both files, AppContainer allowed read, denied read returning `ERROR_ACCESS_DENIED/5`, and complete native cleanup remain unverified and must be performed by the root owner before claiming the L1 permission probe passes. No commit was made.

## Root native fixture staging check

After scoped independent approval, root reran the six suites: **389 passed in
11.36s**, exit 0. Root then performed actual staging, ordinary reads and cleanup
using only fixed synthetic bytes; no profile was created and no child started.

Run: `fixture-smoke-b1abbf4edd7b4a9288d011a889f94fcb` under ignored local-privacy QA.
Stager SHA-256: `e223549b52d09fa4f4c6241eba1485b8fdc9d43e68d40b5d7f01f6ff5798aff2`.
The ordinary reads matched all 26 allowed bytes and 25 denied bytes. Windows ACL
readback showed exact package mask `0x120089` only on allowed.txt, no package ACE on
denied.txt. Cleanup reported complete/handles closed/no remaining or uncertain
paths. Separate literal-path checks confirmed both fixtures and stage directory
were absent. Native script exited 0; result.json retains full object/hash facts.

This confirms actual staging/readback/ordinary reads/cleanup, **not** AppContainer
allowed/denied read behavior or any network denial. Those gates remain next.
