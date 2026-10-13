# Direct private request staging

> Single implementation task after native promotion, followed by independent
> review. Product runner composition follows this task.

**Goal:** Prepared private prompt/schema/images can enter the exact-ACL owned
stage without first being written into an ordinary diagnostic temporary folder.
Keep the public runtime/weight file-backed staging behavior unchanged.

## Global constraints

- Reuse the single promoted native staging/ownership implementation. No second
  ACL engine, relaxed DACL, source/ancestor ACL modification or recursive cleanup.
- No model invocation, API/network/key/credential/private sample/QML/Golden/main
  edit/merge/push. Native synthetic staging and exact cleanup are authorized.
- Private buffers are data, never executables. Do not log their bytes, decoded
  text, hashes or original source paths. No original PDF/video is accepted.
- Preserve existing80-member/5GiB bundle limits and all file-backed validation,
  source handle pinning, same-user/system/package rights and cleanup guarantees.

## Task 1

Allowed files: promoted `native/model_stage.py`, `native/profile.py`, their
existing focused tests and a new `tests/unit/test_private_request_staging.py`.
Do not alter process/security/exemption primitives or profile collision rules.

Add a frozen `StageBytesMember` alongside existing StageMember. Fields are `name`
and immutable `data: bytes` (repr=False); it is always non-executable. Accept only
`prompt.txt`, `schema.json`, and `visual_00` through `visual_07` with a validated
`.jpg`, `.png` or `.webp` suffix. Reject duplicate visual indices even with different
extensions. Prompt/schema max128KiB each, each visual and their aggregate max16MiB,
nonempty data; no caller-supplied digest/source path. Compute its internal SHA256
from bytes, never expose contents/digest in repr or exception text. Validate
before creating resources and apply existing cross-member name collision rules.

Extend `stage_model_bundle` to accept the immutable union of file and byte members.
Create the new target with its exact private/read-only package DACL before writing
any private bytes, using the same native ownership path. Bound writes to1MiB and
check cancellation between chunks. Independently hash and verify size, security,
identity and link count before returning; recheck/cleanup use the existing owner.
MemberEvidence source_path can be None for bytes; existing file-member evidence
and diagnostic source-path translation must remain identical. Do not put private
bytes/hash into an error or create a separate plaintext source file.

Also allow a second fixed profile namespace `xuxia_local_[0-9a-f]{32}` alongside
the legacy diagnostic namespace, with an accurate fixed product display name.
Keep constructor/prepare side effects, exact SID validation and collision-no-
adoption unchanged; never accept arbitrary profile names or delete by name alone.

Write RED tests before implementation: mixed file/bytes bundle, bounds and unsafe
names, duplicate indices, no source file creation, exactACL-before-firstwrite,
bounded writes/cancel, failed write/hash/security and exact cleanup, repr/error
privacy, all byte members nonexecutable, source_path None, unchanged legacy
file-backed behavior, valid two namespaces and forbidden arbitrary names.
Use existing fake-native seams plus a root-owned native smoke after review.

Run focused native stage/model-stage/profile/contained-inference/newtests. Report
raw RED/GREEN and file list in `.superpowers/sdd/private-request-staging-report.md`.
Commit only allowed source/tests, no amend; no claim of product privacy activation.
