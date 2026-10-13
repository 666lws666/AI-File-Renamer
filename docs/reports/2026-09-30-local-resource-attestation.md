# Native local inference resource attestation

## Scope and source

Verified on Windows with project Python at source `010a0ce`. This Gate checks
the production resource-attestation context, not model inference, user-interface
readiness, semantic quality, or complete product privacy.

The input was the previously verified public Qwen3.5-4B quantized model,
vision projector, and pinned b10885 CPU runtime. No download, cloud request,
credential access, private file, native model launch, or security setting change
occurred. The engineering catalog remains an engineering catalog.

## Actual result

- Attested public members: **53**.
- Exact combined bytes: **3,460,111,485**.
- Public identity: `0fdd7421947eb5ae955235015385b4c62e4aec7ddac48296cbeeae84da3e746b`.
- While the context held its leases and read pins, ordinary read/write opens of
  the selected completion executable, model weight, and projector were all
  rejected with `PermissionError`; no bytes were written.
- After release, a second fresh attestation succeeded with the same identity.
- The two attestations and handle checks took **6.506 seconds** on this host.
  This is an observation, not a performance guarantee.

The ignored raw record is
`tests/screenshots/qa-current/local-privacy/inference-resources-native-f36fa7d62ffe48519c53131d4d787068/result.json`.
The reproducible local QA helper is `native_inference_resource_check.py` in the
same QA parent. These machine-specific paths and records are not distribution
resources.

## Failure coverage and limits

The scoped implementation tests report **114 passed, 1 skipped**. The skip is
the existing Windows symbolic-link privilege test. Deterministic negative tests
cover original-deadline enforcement during preparation and timeout classification
after preparation, while hashing, and immediately before publication. Cancellation,
malformed identity, mutated resources, contention and exception cleanup are covered
with synthetic owned stores. Network/process fail-fast guards run in those tests.

No formal Golden changed. Whole-product regression and real composed inference
remain separate Gates; this report does not claim they passed at this source.
