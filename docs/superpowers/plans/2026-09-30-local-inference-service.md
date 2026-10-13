# Managed Local Inference Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Compose verified resources, strict naming protocols and exact-owner
AppContainer execution into one cancellable product service, usable by both
Batch and Watch without a cloud fallback or private diagnostic files.

**Architecture:** A pure prepared-request module builds bounded in-memory model
inputs. One service serializes expensive work, owns a durable recovery journal,
and retains a retryable invocation owner on incomplete cleanup. Existing native
implementations are reused; they are not copied or replaced by a generic launcher.

**Tech Stack:** Python standard library and existing product core/media contracts,
ResourceStore attestation, immutable protocol data, Windows AppContainer/Job APIs,
pytest injected seams. No new service, HTTP listener, dependency or daemon.

## Global Constraints

- Only local synthetic tests here; no real model launch by the implementer,
  cloud API/key/Credential Manager, private input, QML/Golden, main checkout,
  merge or push. Root runs the real composed model Gate after code review.
- No scripts/diagnostic imports or ordinary temporary prompt/image/output files.
- No firewall/exemption setter or security relaxation. Zero capabilities, exact
  token-before-resume validation and creation-time Job binding remain canonical.
- Resource availability is not readiness. Publish a result only after confirmed
  cleanup, a durable clean journal, no cancellation/deadline and current context.
- No fallback to cloud, another naming mode, arbitrary executable, model URL,
  unapproved flags, shell, inherited proxy environment, repaired JSON or truncated name.
- Preserve all cloud, templates, Watch configuration and existing defaults.

## Prerequisites

The reviewed product `naming_protocol.py`, `inference_launch.py`,
`inference_resources.py`, `inference_journal.py`, `host_capacity.py` and pending native owner must be
committed first. Use their actual signatures; pause on a genuine contract mismatch
instead of introducing a parallel implementation.

## Task 1: One prepared-input service and retained cleanup owner

Files:
- Create `src/services/local_ai/inference_request.py` (pure request/response data,
  validation, protocol construction and strict decoding).
- Create `src/services/local_ai/inference_owner.py` (ordered retryable cleanup of
  exactly the native objects acquired by one invocation, no orchestration/policy).
- Create `src/services/local_ai/inference_service.py` (single-slot orchestration,
  readiness and lifecycle).
- Create `tests/unit/test_local_inference_request.py`,
  `tests/unit/test_local_inference_owner.py`,
  `tests/unit/test_local_inference_service.py`.
Existing modules are read-only unless root explicitly resolves an interface defect.

### Caller contract and pure request preparation

```python
@dataclass(frozen=True, slots=True)
class LocalNamingRequest:
    text: str                         # repr=False
    visuals: tuple[PreparedVisualPayload, ...]  # repr=False
    locale: str
    naming_mode: str                   # smart or template
    template: Template | None = None  # repr=False; immutable snapshot
    quality: str = 'balanced'
    text_layout: str = 'lines'

@dataclass(frozen=True, slots=True)
class LocalInferenceResult:
    success: bool
    fields: object | None              # repr=False, immutable after publication
    error: str | None                  # fixed enum-like error code only
    engine_identity: str | None
    elapsed_seconds: float
```

Use existing `Template`, `NamingFields`, `PreparedVisualPayload` and
`SmartNamingPolicy`, not duplicate domain classes. The request is text and already
prepared images only: no source path, raw PDF/video, credentials, provider request,
custom schema, output path, arbitrary flags or mutable file handle. Constructor
validates exact supported mode/locale/quality/layout; template iff template mode.
Quality is economy/balanced/quality internally; accept the existing AppConfig
alias high at this boundary and normalize it to quality. Reject every other value;
do not silently default an invalid quality string to balanced. This preserves
existing settings while matching the media/QualityRouter vocabulary.
Never turn a mutable list into a silently shared request. Template and visual
payloads must be genuine immutable product instances; no introspection-based
duck-typing. Visual/text buffers and result fields are repr-hidden.

Text <=32768 UTF8 bytes, <=8 prepared visuals, <=16777216 total visual bytes; at
least nonblank text or a visual. Verify each payload's exact bytes, byte_size,
digest, positive actual-int dimensions, source_index, allowed MIME/kind and
nonblank provenance/version against the existing prepared-payload contract.
Require MIME signature agreement (JPEG/PNG/WebP) and preserve bytes exactly.
Do not decode, resize or transcode again here: those operations and pixel bounds
are the canonical preprocessing layer's job. All failures expose fixed codes.

Build the one deterministic text evidence bank once (lines/contiguous) and reuse
it for prompt/schema and decoding. Smart uses build_smart_prompt/local_schema/
decode_response; template uses its three corresponding APIs. UTF8 prompt/schema
each <=131072 bytes; private staging members are prompt.txt/schema.json plus
contiguous visual_00..07 with suffix determined by MIME, not user filenames.
Return frozen prepared data that also retains only the original bounded protocol
context needed for strict decode. No caller can supply prebuilt arbitrary argv.

Response <=262144 bytes, strict original decoder, immutable resulting mappings/
tuples or NamingFields. Smart output also goes through actual SmartNamingPolicy
rendering with an internal synthetic '.txt' extension as a semantic/safety policy
check; discard that name, return structured fields to the normal product renderer.
Template decode may legitimately leave required values None; do not invent values
or bypass the existing downstream TemplateRenderer's NEEDS_REGENERATION decision.

### Service API and shared scheduling

```python
@dataclass(frozen=True, slots=True)
class LocalInferenceConfig:
    resource_root: Path  # repr=False
    runtime_root: Path   # repr=False
    state_root: Path     # repr=False; dedicated journal + private-stage parent
    catalog: ResourceCatalog

@dataclass(frozen=True, slots=True)
class LocalServiceSnapshot:
    phase: str
    identity: str | None  # readiness anchor, NOT request protocol identity
    error: str | None
    waiting_count: int

class LocalInferenceService:
    def __init__(self, config: LocalInferenceConfig, *, _dependencies=None): ...
    def snapshot(self) -> LocalServiceSnapshot: ...
    def check_ready(self, *, cancelled=lambda: False, deadline: float,
                    is_current=lambda: True) -> LocalServiceSnapshot: ...
    def infer(self, request: LocalNamingRequest, *, cancelled=lambda: False,
              deadline: float, is_current=lambda: True) -> LocalInferenceResult: ...
    def retry_cleanup(self, *, deadline: float) -> LocalServiceSnapshot: ...
    def shutdown(self, *, deadline: float) -> LocalServiceSnapshot: ...
```

Snapshot is frozen, content-free; phases NOT_READY/PREPARING/READY/RUNNING/
CLEANUP_PENDING/RECOVERY_REQUIRED/CLOSED, identity and fixed error only. Constructing
or importing service performs no I/O/launch; cloud-only startup must remain cheap.
The single production instance will be injected into both Batch/Watch later.
Private test dependency seams may replace exact native functions/clocks with
fakes; default production path uses only the reviewed implementations.

One operation lock, max8 admitted waiters, no retained task queue; excess returns
BUSY. Waiting checks cancellation/context/deadline every <=50ms. Waiting consumes
the same caller budget. Snapshot lock is short-lived: no I/O, native calls or
external callbacks while it is held. An unresolved owner blocks inference even
when operation lock is released. retry_cleanup also serializes on operation lock;
it cannot overlap a live invocation or discard pending state.

Validate absolute finite future monotonic deadline before any I/O; maximum work
budget900s, reserve10s of that for cleanup. Huge/bool/nonfinite deadlines reject;
far-future valid deadlines are capped to now+900s, not a latency claim. Callback
exceptions fail closed with fixed failure, never leak their text. is_current
comes from the future shared processing authority; evaluate before native side
effects, through cancellation checks, and immediately before publishing success.
No result from an old mode/context is published as a current result.

### Ordered real production path

1. Validate/prepare request and acquire scheduling slot. Lazily acquire and hold
   LocalInferenceJournal lease for service lifetime; stale/invalid journal means
   RECOVERY_REQUIRED, never profile/PID/path adoption. State root must already have
   an existing safe parent; use journal's exact-root create rule, not recursive
   filesystem creation. Read-only discover_windows_paths gives trusted OS paths.
2. attest_resources with remaining work deadline, vision according to request
   (the initial self-check additionally verifies the projector, without passing
   unused projector data to text inference);
   hold its leases through private staging. Engine identity is canonical SHA256
   of public resource identity, SMART_PROTOCOL_VERSION or the integration's fixed
   template protocol tag `local-template-v1`, fixed recipe_version,
   context8192/output1024/CPU4, and naming mode. The fixed launch recipe supports
   runtime release b10885 only; refuse a different catalog release, not silently
   apply measured flags to an unverified runtime.
   It must exclude machine paths/private content. Locale/template/quality/mode
   generation additionally partition future cache keys, not the resource identity.
   Readiness has a separate anchor: canonical catalog identity + ordered runtime
   member name/size/hash + fixed recipe. It is independent of naming mode and
   whether this request uses images, because the initial check already verifies
   both weights. Do not compare a smart text result identity to a template/image
   identity and falsely require a different self-check. Each request still hashes
   every weight it actually uses; changed/corrupt resources invalidate readiness.
3. Create an invocation owner BEFORE any potentially partial native acquisition.
   Allocate profile name xuxia_local_<32 random hex>, prepare SID (no profile yet),
   journal.begin before any stage or profile creation. Retain profile even when
   prepare/entry raises so temporary native allocations can be retried safely.
   Before native side effects, measure_host_capacity against the existing leased
   state root and require_host_capacity for the exact full public+private stage
   bytes. The5GiB free-memory trial floor is not a published minimum requirement.
4. stage_model_bundle directly from public StageMembers and private
   StageBytesMembers. Retain StageError.owner on every partial staging failure.
   Native stage uses state root as parent. Check 80-member/5GiB bound including
   private bytes before stage creation. Assert exact evidence names/count/size,
   public expected hashes and private derived hashes; stage_name and directory
   identity go to attach_stage, never private member hashes/content in journal.
5. Query and require no loopback exemption for prepared exact SID. Create owned
   profile (collision is failure, no adoption), enter AppContainerSecurity with
   zero capabilities. Recheck stage, all current/cancel/deadline conditions, and
   build_launch from its evidence. Resource contexts may now close because the
   verified stage itself retains immutable read pins; clean up partial context
   acquisition even if stage failed.
   Immediately before run_bounded, repeat the capacity check with staging_bytes=0
   (the stage already exists). Low memory/disk or failed measurement follows the
   same exact-owner cleanup, exposes a fixed failure, and never selects cloud.
6. run_bounded using fixed spec, stdout_limit262144, stderr_limit1048576,
   timeout_seconds=remaining work time, cleanup_timeout_seconds<=3 and remaining
   total time, cancellation object exposing is_set() that combines caller/stale/
   work deadline/shutdown. Never pass source paths or raw request text as argv.
7. Require ProcessResult completed/exit0/cleanup_complete; exact package SID,
   is_appcontainer is True and actual integer capability_count0. Strictly decode
   output; do not log/return/store either stream. PendingProcessOwner or
   ProcessOwnershipInterrupted is adopted before error handling. An unexpected
   runner escape without provable child cleanup blocks rather than guessing exit.
8. Execute exact cleanup below, durably complete journal, then check caller
   cancellation/currentness/total deadline again before publishing decoded fields.
   Late/cancelled/stale success is discarded. No output is written to disk.

### Cleanup and readiness

Invocation owner retains only acquired exact native objects and its cleanup
cursor. Confirm root AND Job tree exited/handles closed using pending owner first;
then security.close, stage.cleanup(child_cleanup_confirmed=True) (require complete),
exemption.close, profile.close, remaining resource contexts, journal.complete.
Never close/delete the next dependency after a prior step fails. Successful steps
are cleared once, failures remain retryable; retain one owner, not an unbounded
global leak list. Cleanup ignores original cancellation but obeys a new bounded
cleanup deadline. A failed terminal journal write is RECOVERY_REQUIRED; do not
relabel it successful cleanup. Keep service-level journal lease while pending.

Catch BaseException only to preserve exact ownership and perform/retain cleanup;
do not flatten KeyboardInterrupt/SystemExit into a false result. Re-raise after
ownership has been retained in the service. Native release success alone is not
evidence about the whole computer or other processes.

infer requires a successful current self-check, not merely present files.
check_ready performs real same-path smart inference over one fixed public
synthetic English campus-network-maintenance note, using its evidence bank and
SmartNamingPolicy validator. It may internally bypass only the initial READY
guard, never containment/attestation/decode/cleanup. Validate projector resources
as well before READY even though that first self-check is text-only. Root's later
  composed visual Gate establishes shipped projector compatibility. Explicit
check_ready changes readiness only after result cleanup; failure never enables
mode or triggers cloud. Invalid/insufficient user content does not destroy an
otherwise valid runtime self-check; resource/containment/engine failure does.

shutdown sets its cancellation event before waiting; closes journal context only
after active and pending ownership are fully clear, otherwise returns the truthful
pending state. Repeated completed shutdown is a no-op; infer after CLOSED refuses.
Do not add __del__ cleanup or unload/drop an uncertain Job merely to exit faster.

### TDD, review and integration evidence

- [ ] RED request tests: real prepared tiny PNG/JPEG/WebP, text-only/visual-only/
  mixed, exact suffixes, bad MIME/digest/count/bytes/mode/template/layout/locale,
  prompt/schema bounds, no raw PDF/video/path/flags, immutable/repr-safe data,
  smart/template decoder contracts and actual policy/renderer missing-date result.
- [ ] RED owner tests with logged fake steps: every cleanup step fails once then
  succeeds; previous successes not repeated; no later cleanup before tree exit;
  cancellation during model + failed reap -> owner retained; expired cleanup
  changes nothing; collision never deletes unrelated profile; terminal journal
  failure cannot publish success.
- [ ] RED service tests: no readiness-before-selfcheck; no side effect before
  bounds/deadline; each ordered boundary error/cancel/stale; exact native kwargs;
  malformed/token-mismatch/output overflow; model exit failure; callback exception;
  ready smart-text service also accepts template/image requests without a spurious
  identity mismatch; currentness switches while waiting/running/cleaning; deadline includes inventory/
  staging/decode/queue; retained owner blocks next launch; two callers share one
  model; ninth waiter BUSY; shutdown/retry race; BaseException retention; no content
  in streams written to disk/log/error/repr; stale journal starts no native call.
- [ ] Implement minimal three modules, rerun their tests and immediate dependency
  suites once; report exact RED/GREEN output to
  `.superpowers/sdd/local-inference-service-report.md`; scoped commit and diff check.
- [ ] Independent task review before root's actual synthetic model Gate. Tests
  replacing native functions are logic evidence only, not privacy or quality PASS.

### Integration clarifications recorded during implementation

- The template prompt API must accept keyword-only `text_layout='lines'` and use
  the same `text_evidence_spans(..., text_layout=...)` bank as schema and decoding.
  Template contiguous layout is valid only with text and without visuals, matching
  the smart prompt boundary. Default lines output and frozen locale hashes remain
  byte-for-byte compatible. The exact additional allowed files are
  `naming_protocol.py` and `test_local_naming_protocol.py`; the dependency fix is
  reviewed together with this service, not replaced by silently rejecting a valid
  request.
- A failed exit of the generator-based resource attestation context is not safely
  retryable: re-entering an exhausted `__exit__` does not repeat failed cleanup.
  The invocation owner retains the context and permanently reports
  RECOVERY_REQUIRED in this case; retry cannot clear it on an empty normal return.
  Normal context exit is called once. Other owned native cleanup steps retain
  their documented retry behavior. This task does not modify ResourceStore or
  invent a restart recovery/adoption mechanism.
