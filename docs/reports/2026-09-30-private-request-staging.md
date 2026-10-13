# Product-native foundations and private request staging

Date: 2026-09-30. Source checkpoint: `035aaf5` on `codex/local-privacy-mode`.

## Delivered scope

- `a98b5d1` moves six tested native components into the product package with one
  implementation each. Existing diagnostic import paths alias those modules.
- `035aaf5` adds bounded immutable prompt/schema/image buffers, written directly
  into the owned protected stage. A normal plaintext source file is not needed.
  The profile constructor also accepts the fixed product namespace.
- Independent task reviews approved both changes. They do not activate local
  processing in the shipped interface or constitute whole-product privacy PASS.

## Actual Windows staging evidence

The synthetic native run `private-stage-native-949abd7c743f48bdb5d61e7b008eae47`
used the real Windows staging and ACL implementation, not the fake-native tests.
It derived a new product namespace SID without creating a profile or child.

For `prompt.txt`, `schema.json` and `visual_00.png`:

- Readback matched the original in-memory synthetic bytes.
- Evidence had no ordinary source path or source identity.
- The package SID had read-only file rights, not execute/write rights.
- No input source copy existed beside the stage; digests were absent from repr.
- The public synthetic executable fixture was unchanged and was never executed.

Owned cleanup returned `complete=true`, `pending=false`, `handles_closed=true`,
with no remaining or uncertain paths. The stage directory was independently
absent afterwards. No model, network request, profile creation, real credential,
private file or security-setting modification was involved.

The ignored reproducible helper and result are under
`tests/screenshots/qa-current/local-privacy/`. Actual product-profile creation and
model lifetime remain for the forthcoming composed coordinator validation.

## Regression evidence

Project Windows Python; isolated temporary user-data directories and a failing
keyring backend. Formal screenshot update mode was disabled.

| Gate | Actual result |
| --- | --- |
| Native promotion focused suite | 485 passed, 4.72 s |
| Private staging focused suite | 267 passed, 1.08 s |
| Full non-screenshot suite | 2996 passed, 2 skipped, 63.76 s |
| M1 screenshot comparison | 49 passed, 30.92 s |
| M0 screenshot infrastructure | 5 passed, 1 skipped, 0.70 s |
| Acceptance script | 186/186 passed |

The two non-screenshot skips are existing platform/privilege-bound symlink cases;
no security settings were changed to enable them. The M0 skip is the explicitly
disabled update-mode test. Existing Pydantic deprecations (3) and Pillow warnings
(82 M1, 4 M0) remain maintenance backlog, not hidden or reported as clean output.
M1 used the documented `QT_SCALE_FACTOR=0.8` to reproduce the approved 100% pixel
size on this 125% Windows desktop; M0 retained its original default scaling.

No Golden update, package replacement, main-checkout merge, push or release was
performed. Next: retryable pending-process ownership, pure naming protocol, and
the production coordinator; mode fencing and UI integration follow.
