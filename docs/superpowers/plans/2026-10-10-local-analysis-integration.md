# Managed local processing integration

> Execution uses subagent-driven-development, TDD, and independent task review.
> The Product Owner has authorized these already-approved feature requirements.

## Goal and honest completion boundary

The existing real-model service has passed bounded synthetic scan/video/blank
checks; that is NOT equivalent to a usable local privacy product. Finish the
actual Batch/Watch routing, generation-fenced acceptance, managed resources,
visible preparation/error states, three-language help, and Windows packaging.
Never report a mock as a model-quality result or resources AVAILABLE as READY.

## Invariants

- One shared ProcessingAuthority and one LocalInferenceService in production.
- Persist only processing-intent.json; no second processing-mode AppConfig field.
- Capture work at admission before any queue/wait; never borrow a fresh generation
  in a worker. Retain task-attempt identity and snapshot of naming choices.
- Cloud adapters receive ProcessingDispatch; final HTTP commitment is enforced by
  the concrete transport, including retries and fixed connection probes.
- Local branch runs before cloud profile/credential lookup and ignores cloud
  upload consent toggles. It never falls back or accepts arbitrary localhost.
- Resource download consent is separate from document processing. No content,
  filename, or source path in download requests. No downloads during tests.
- Stable service readiness identity and per-request inference identity are
  distinct. Do not invalidate other queued work merely because its template or
  modality produces a different request identity.
- UI-thread mode choice and final result acceptance are serialized. No callbacks,
  Qt emission, I/O, model launch or file execution under authority locks.
- Existing accepted suggestions/Apply/Undo/history survive mode changes. In-flight
  stale analysis cannot publish success/error, requeue itself, or Auto Apply.
- No new production disk content cache. Generation/model/mode isolation must be
  applied to any memory cache; do not activate dormant CacheManager for privacy.
- No real cloud API, keys, Credential Manager, private test files, firewall or
  ACL changes, formal Golden updates, push, or public release.
- Synthetic diagnostic output stays in tests/screenshots/qa-current/local-privacy.

## Task A: Extraction and local media boundary

Files: src/core/content_extractor.py, corresponding extraction tests, and the
exact keyframe_extractor.py/test files in the approved local-video-io-boundary
plan. No Provider, controllers, resource manager, QML, or model resources.

1. Bound plaintext reading before allocation using max_chars and bounded decoding;
   preserve supported encodings/current extraction semantics. Bound multi-section
   document loops and cancellation. Fixed failures must not log raw content or
   source paths; local privacy callers request redacted diagnostics.
2. Preserve page/visual/frame caps and genuine missing-content outcomes.
3. Execute the approved explicit PyAV nested-I/O denial, retaining ordinary local
   MP4 support and 4/6/8 frame behavior. Test that HLS or external resource references
   cannot perform nested network I/O through decoder auto-detection or retry.
4. TDD negative cases: bounded read spy, giant text, cancelled document iteration,
   extraction error confidentiality, real synthetic local video decode, prohibited
   nested media I/O, timeout/cancellation and cleaned child ownership.

## Task B: Shared analysis routing and immutable work preparation

Files: src/core/batch_analysis.py, new focused routing/context tests, and a small
pure shared processing-analysis contract if necessary. No QML yet.

Admission API: capture_work(source_path, task_id, *, task_attempt_id,
task_cancel_event, template_id, output_language, naming_mode,
naming_policy_version, quality_mode) -> frozen PreparedAnalysisWork.
Worker API: run_prepared(work) -> frozen AnalysisOutcome. Capture performs no
file extraction/credential lookup/model/HTTP. Snapshot the starting generation;
if it changes while preparing, reject instead of borrowing the new generation.
The coordinator binds safe profile fingerprints before admission; capture only
checks them. Local uses the stable service READY anchor, not request identity.

1. Expose explicit capture/preparation hooks for production controllers. Frozen
   work carries the authentic WorkContext plus an explicit immutable settings
   whitelist and template/Provider snapshots. Never copy AppConfig wholesale: it
   contains api_key and may retain unrelated extra values. Work contains no
   credential and sensitive snapshot fields never appear in logs/repr.
2. Preserve legacy injected analyzers as unit-only compatibility paths. Production
   composition must inject authority and managed local service and cannot silently
   choose an unguarded legacy adapter.
3. CLOUD uses captured profile/model/config, retrieves credentials only there,
   and constructs a context-bound OpenAICompatibleAdapter. LOCAL produces only a
   bounded LocalNamingRequest of extracted text and prepared images/scan pages/
   video frames, honoring language/quality/template vs smart naming.
4. Local service uses its own bounded monotonic deadline (not the default 30-second
   cloud timeout: the actual CPU scan case took approximately 166 seconds), context
   currentness and combined task/generation cancellation. Apply strict returned
   fields via existing SmartNaming
   or TemplateRenderer; no raw original PDF/video, arbitrary path or extension
   supplied to inference. Local failure is a fixed safe error, never cloud fallback.
5. Watch quality_mode must actually control preprocessing/inference, not just label
   the AnalysisResult. Template overrides are immutable per operation, not global.
6. Unit tests cover cloud callbacks zero in LOCAL (including missing/unready),
   full template and smart modes, three languages, scanned PDF/video payload-only,
   size/content failures, output rejection, preserved extensions and stale results.
7. Formal prepared results retain authentic provenance and path-free coverage
   notes for the later controller/UI; do not hide them in a str subclass. Legacy
   string-return wrappers remain explicit compatibility, not production evidence.
   Extraction coverage must come from actual bounded reads/section processing,
   not guessed from len(text)==limit. Text-only local requests may use the existing
   contiguous evidence layout for many short lines without relaxing validators;
   mixed visual/text obeys its existing bounded line evidence contract.
   Outcome includes authentic context, effective quality, content kind, request
   engine identity, immutable coverage and warning codes. Filename/context/source
   are omitted from repr. Existing strict local template results are NamingFields;
   smart results are immutable mappings. Remove default basename-bearing media
   explanation text for BOTH local naming modes, retaining genuine injected OCR.

## Task C: Admission, publication, and production composition

Files: BatchWorkspaceController, WatchController/ReviewFirstHandler/
AutoApplyHandler, watch analysis provenance, qml_bootstrap, processing coordinator
and focused tests. Make a separate scoped implementation/review package.

1. Initialize authority from intent store before constructing/restoring either
   pipeline. Share service/coordinator with connection tests. Saved LOCAL starts
   NOT_READY and closed to cloud until explicit saved CLOUD choice.
2. Capture context before pool submission/debounce pipeline admission. Queued old
   work cannot be upgraded into a new generation. Binding changes invalidate work.
3. Final Batch acceptance checks both attempt ID and authentic current context on
   the Qt thread. Reject stale errors and values without contaminating replacement
   attempts; cancel stale analyzing rows truthfully.
4. Marshal Watch analysis completion and any next-step scheduling onto the same
   serialized acceptance boundary as mode choice. Auto Apply receives only accepted
   current results; held/retried work keeps its original context or requires explicit
   new admission. Existing approved rows/history are not deleted.
5. Resource/model replacement and ready/not-ready updates invalidate appropriate
   generations. Settings cancel/reset cannot undo an immediate processing choice.
6. Lifecycle close stops admission, drains intent notifications or reports failure,
   cancels analysis and shuts the model down with bounded cleanup ownership.
7. Tests use controlled Events/queued signals rather than timing sleeps: LOCAL
   while queued, while backoff, before send, after send and before acceptance;
   Batch+Watch concurrency, model failure, saved-mode restart and persistence error.

## Task D: Resource preparation and beginner-facing integration

Separate implementation/review, including native evidence before completion.

- Main workspace shows CLOUD / LOCAL PRIVACY and visible preparation state; the
  two naming methods remain independent. Settings manages model location, verified
  offline import, consented resumable download, pause/cancel/retry, self-check and
  actual failure. Never claim success from a downloaded manifest alone.
- Use the pinned compatible official/traced catalog and licenses. Changing catalog
  purpose/identity requires fresh verification/import, not adopting arbitrary QA
  directories as trusted production resources.
- Document measured requirements, disk use and slow CPU behavior without untested
  minimum-speed promises. Existing filenames/settings/templates/Watch rules stay.
- Verify three languages, real mouse clicks, CJK, minimum size, scroll/occlusion,
  native offline end-to-end model behavior and the narrowly evidenced network claim.
- Update three-language HTML guides. Run full actual current test suites, unchanged
  formal screenshot baselines, acceptance, packaged resources and isolated EXE.
- If necessary UI changes require Golden renewal, present exact affected files and
  native visual evidence for separate approval; continue other unblocked work.

## Task review and checkpoints

Each task has genuine RED/GREEN, exact file ownership, read-only independent
spec/quality review and a root-owned scoped commit. P0/P1 block; P2/P3 are backlog.
Do not roll back earlier work, merge main or publicly release without authority.
