# Fixed probe purpose and runtime invalidation prerequisite

The approved processing integration must fence connection probes as well as
business naming sends. A candidate probe may occur before any active Provider is
bound, but must never gain authority to send file content. This task precedes the
Qt coordinator and does not alter HTTP behavior, model resources or UI layout.

## Scope

- src/core/processing_authority.py
- src/core/processing_identity.py (new pure canonical identity helper)
- src/core/processing_analysis.py (re-export the helper without behavioral change)
- src/providers/openai_compatible.py (purpose validation and commit dispatch only)
- tests/unit/test_processing_authority.py
- tests/providers/contracts/test_processing_dispatch.py
- new focused tests/unit/test_processing_identity.py if necessary

One implementation writer; root owns review, Git and full regression. No controller,
Qt/QML, retry-policy, resource/media, model, real API/key/credential, firewall/ACL,
Golden, push or release work. Use TDD and scoped independent review.

## Canonical identity

Move the reviewed cloud_engine_fingerprint implementation unchanged into the pure
processing_identity module; processing_analysis imports/re-exports it for existing
admission callers. Provider code may import this pure module without importing
analysis orchestration/media/model services. All immutable nonsecret ProviderProfile
and capability fields participate, never the credential value. Preserve digests.

## Distinct probe context

Introduce a frozen CloudProbeContext (not a WorkContext subtype). Its public record
contains starting session/generation, candidate fingerprint and model, request ID,
generation Event and optional request cancellation Event. Sensitive identity/model
fields have repr=False. The private weak identity seal/attempt ledger is issued by
the authority; reconstructed/deepcopied/cross-owner contexts are not permits.

capture_cloud_probe(*,candidate_fingerprint,candidate_model,request_id,
task_cancel_event=None) succeeds only in current non-error CLOUD. It does not need
or modify the active cloud binding and does not advance generation. Capture uses
strict bounded nonsecret strings/fingerprint and exact Event types, with no I/O,
callback, file/model/template/profile/credential lookup or Qt emission under locks.

Business capture_work/is_current/assert_current/commit_cloud_attempt remain
business-only. Add is_current_cloud_probe and commit_cloud_probe_attempt with the
same generation/cancellation/identity, <=32 unique attempt IDs and one-use receipt
semantics. Shared snapshot committed_attempts and finish_attempt cover both ledgers.
LOCAL choice immediately rejects/invalidates both. Add invalidate_work() which
advances generation/cancellation without changing mode/revision/readiness/binding;
the future coordinator uses it before publishing successful changed settings and
when closing admission. It does not by itself reopen or select another mode.

## Existing adapter and concrete send

ProcessingDispatch accepts only the explicit business/probe context union and
provides a narrow currentness helper; no signature fallback. A genuine probe context
in OpenAICompatibleAdapter.invoke is rejected BEFORE visual/request preparation,
including when the profile is already verified. invoke_probe authenticates its
candidate fingerprint and model against the immutable adapter profile. Existing
ordinary business-context probes remain compatible but guarded.

At UrllibJsonTransport.send, a probe context is accepted only for the exact fixed
body with precisely four fields: model matching the captured model; messages equal
one user message with content 'ping'; stream exactly False; max_tokens exactly int1.
Reject unknown fields, altered text/role/model, image/data content, bool max_tokens
or extra messages before encoding/opening. Both raw transport and adapter paths
must reject a fabricated probe. Perform encoding/request creation and validation
before the final dedicated probe commitment; nothing may wait/callback/serialize
between that commitment and _open. Receipt finishes in existing finally even after
mode changed during an already committed attempt. Redirect/parsing/classification/
retry/credential/header/request timeout semantics stay unchanged. Guarded fake
transports must implement the same explicit dispatch contract, never unguarded
fallback after TypeError. Retry cancellation uses the correct context currentness.

## Negative tests and completion

- Candidate with no active binding: fixed fake probe succeeds without changing
  snapshot generation, revision, active engine or current business context.
- LOCAL/no readiness/startup error/stale/cancelled context fails before opener.
- Reconstructed/copied/cross-authority probe rejected; ordinary is_current and
  commit_cloud_attempt never accept probe; probe APIs never accept WorkContext.
- Verified business invoke given a real probe cannot send/preprocess images.
- Every altered fixed-body field/type/unknown field rejects at concrete transport.
- Candidate mismatch rejects; canonical helper remains identical and key-free.
- LOCAL between attempts prevents retry; previously committed send may finish but
  its stale value cannot publish; every receipt finishes exactly once.
- invalidate_work cancels both context kinds, keeps mode/revision/readiness/engine,
  allows deliberate new admission only through still-open higher-level owners.

Run focused authority/identity/dispatch + existing Provider contracts. These are
fake transport/concurrency tests, not cloud or model-quality evidence. Root runs the
complete regression after reviewed checkpoint. No assertion weakening or skips.
