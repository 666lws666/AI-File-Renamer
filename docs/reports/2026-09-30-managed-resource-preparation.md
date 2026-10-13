# Managed resource preparation verification

## Scope and current verdict

This report covers the pinned catalog, explicit-consent resource transport and
Windows-owned download/offline-import service. It does not claim that local
privacy mode, model startup, product UI or redistribution packaging is complete.

Implementation `737e0b0` plus ignored-Range preservation fix `a235b8d` passed
independent scoped review. The resource preparation service also passed the
full-size native offline check and the regressions below. This is a resource
service milestone, not a complete local-mode release.

## Already established evidence

- Catalog/transport foundation: `a99e79f` and deep-JSON error-boundary fix
  `9cc4796`. Independent scoped review approved;108 focused tests passed.
- Resource store/manager initial task:160 passed,1 symlink-privilege skip. Native
  Windows tests exercised real cross-process lease exclusion/release, process-exit
  release, ancestor-rename resistance, junction and hardlink rejection, including
  a hardlink created during transfer. No security settings were changed.
- Initial31 missing-implementation failures preceded the implementation. More
  negative tests caught path-appearance, disk-accounting, partial state and native
  Unicode publication defects before the reviewed commit.
- Review caught an additional ignored-Range HTTP200 path that could truncate an
  old partial. Two real failing regressions reproduced this; the owned-store path
  now rejects that response before reading/writing, preserves old bytes and
  requires explicit restart. Legacy unowned transport compatibility is unchanged.
  Final focused run:163 passed,1 native-symlink privilege skip in1.77s.

## Public resource provenance and license text

The catalog pins three public resources totaling3,431,786,583 bytes: Windows CPU
runtime ZIP, Qwen3.5-4B Q4_K_M weight, and F16 visual projector. No new model download
was made during this milestone. Existing synthetic-QA copies are the input to the
upcoming offline import test, not an implicit product installation.

Official pinned Qwen and llama.cpp license texts were fetched over Windows HTTPS
and compared with the local copies after normalizing line endings and the terminal
newline. Both comparisons matched. Source URLs/revisions/byte counts/SHA256 are in
`resources/local-models/licenses/SOURCES.md`. The runtime archive also contains
`LICENSE-LLVM-OpenMP`; runtime preparation/packaging must preserve that notice.
These source additions alone do not assert that the Windows product package now
contains the notices.

## Native full-size offline check: PASS

Actual run `resource-native-7ef0e66f99904b2fbb3e43fa837a5685`, recorded under the
ignored local-privacy QA directory:

- Constructor, missing inspection and no-consent rejection created no cache.
- Cancelled during the actual weight copy after the runtime ZIP and1MiB of weight
  had arrived: CANCELLED, only runtime-cpu verified, no false availability.
- A fresh manager reported PARTIAL. Resumed import finished in9.2101 seconds on
  this host; all3 resources /3,431,786,583 bytes were independently verified.
- Another fresh manager rehashed and returned AVAILABLE. Source hashes were
  unchanged. The injected resource network opener recorded zero calls.

This timing is a local copy/verification observation, not a download or inference
performance promise. No model was executed by this resource test.

## Root regression at a235b8d

Using the project Windows Python and temporary user-data directories with the
real credential backend disabled:

| Check | Raw summary |
| --- | --- |
| Non-screenshot suite |2913 passed,2 skipped,3 warnings in61.89s|
| M1 screenshot suite, update mode disabled |49 passed,82 warnings in31.32s|
| M0 screenshot suite, update mode disabled |5 passed,1 skipped,4 warnings in0.47s|
| acceptance_test.py |Passed186/186, Failed0/186|

The two non-screenshot skips are native symlink creation without its privilege;
no privilege/security change was made to force them. The M0 skip is the existing
explicit-update-mode test. Warnings are the existing Pydantic class Config and
Pillow getdata deprecations, recorded as maintenance rather than hidden. M1 used
the existing documented QT_SCALE_FACTOR=0.8 for the125% Windows desktop to retain
1000x700 baselines; M0 used its original offscreen environment. No assertion,
tolerance or Golden file changed. Acceptance uses temporary settings and mocked
keyring, despite wrapper debug messages referring to the credential manager.

## Limits

- The native owned store is Windows-only and rejects unsupported/UNC roots.
- Ownership markers and leases prevent accidental or cooperating-process races;
  they are not protection against arbitrary malicious code running as the user.
- A corrupt existing final is preserved and rejected. This task does not yet
  expose a destructive repair/uninstall operation.
- AVAILABLE means verified resource bytes, not model health or privacy activation.
- Runtime extraction, trusted production inference, shared Batch/Watch mode
  authority, three-language UI/manual updates and packaged acceptance remain.
- No real cloud API/key/credential use, private media, Golden update, main-checkout
  merge, push, release or system-security change was performed.
