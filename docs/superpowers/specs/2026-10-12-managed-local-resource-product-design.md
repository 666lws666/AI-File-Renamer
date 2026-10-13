# Managed local resource preparation design

## Scope and approved direction

Deliver the already-approved Qwen/Qwen3.5-4B managed Windows local privacy mode
without Python/CLI setup by the user. This design follows the production Watch
checkpoint; it does not reopen the completed native file-operation foundation.
Naming mode (smart/template) and processing choice (local/cloud) remain separate.
No cloud fallback, paid service, new provider, system policy change or release is
authorized by this document. Root owns Git and evidence; implementation is serial.

## Evidence and fixed inputs

The existing engineering catalog identifies Qwen source revision
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, quantization repository
`unsloth/Qwen3.5-4B-GGUF` revision `e87f176479d0855a907a41277aca2f8ee7a09523`,
and llama.cpp CPU Windows x64 release `b10885`. Keep these exact resources:

| Resource | Bytes | SHA-256 |
|---|---:|---|
| llama-b10885-bin-win-cpu-x64.zip | 18425079 | b96fd3b2dfa7add41b0d80f93599931d839b54b4b804abc4b295bd4039dc96f1 |
| Qwen3.5-4B-Q4_K_M.gguf | 2740937888 | 00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4 |
| mmproj-F16.gguf | 672423616 | cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864 |

Total installed public-resource bytes are 3431786583. The bundle contains only
the 18425079-byte runtime ZIP, catalog and existing license notices, not model
weights. Model plus vision download is at most 3413361504 bytes before reuse.
Exact source URLs remain the pinned URLs in the engineering catalog. Do not
replace them with latest-release or user-authored manifest discovery. Existing
licenses/SOURCES.md retain the verified Apache-2.0/MIT/OpenMP provenance; no new
upstream license verification or quantization reproduction is implied.

The September 30 service report documents real synthetic scan/video/blank runs;
it is not proof of the future default product flow or frozen executable. Resource
availability is not inference readiness, and neither is semantic quality for
arbitrary documents. The hardware guard is an admission policy, not a minimum
RAM specification or speed promise.

## D1: product catalog and resource backend

Create `qwen35-4b-managed-v1.json` with the same artifact metadata and a distinct
`managed-local-resources-v1` purpose. Compute and hard-pin its canonical catalog
identity in a program-relative product loader. Reject feasibility metadata,
substituted manifests, unsupported runtimes and mismatched identities before any
network/model action. Load from the application resource root, not CWD or QA.

Construction is inert. Inject an absolute OS user-data base; default to the
existing LocalAppData/Xuxia/local-ai convention. Resources and extracted runtime
are separate catalog-ID siblings, while inference state is service-owned. No
hard-coded development paths, executable-directory state or adoption of the QA
cache. Prepare only the exact bounded directory hierarchy required by an explicit
operation; reject reparse/foreign ownership without resolving it away.

One worker-scoped `prepare_production_parents` context prepares only role parents
below the captured trusted LOCALAPPDATA anchor (an explicit existing fixture in
tests). Readiness holds it through the genuine service self-check. The context
does not create resource/runtime/state leaves or markers; the existing consumers
retain that authority. At most 8 distinct missing parents may be initialized,
using independently owned relative native directory capability and proven
first-empty-directory protection. No recursive upward discovery/adoption or
signature propagation through the inference graph is required.

Extend the existing ResourceManager rather than adding a second downloader:

- `import_bundled_runtime(source, cancelled, progress)` reads only the exact
  trusted runtime ZIP, verifies bytes/hash under pinned handles, stages and
  publishes non-replacing under the catalog lease. It does not execute the ZIP.
- `inspect` reports verified finals plus actual retained partial sizes. Expose
  separately verified bytes, acquired bytes and advisory remaining transfer bytes.
  Reject invalid/oversized files rather than clamping them into valid observations;
  never label unverified bytes valid or promise that acquired bytes are reusable.
- Explicit `repair_resource(resource_id)` may quarantine only that exact owned
  catalog final/partial under fresh writable pins and a non-overwriting suffix.
  Preserve damaged evidence. Never remove unknown children, replace a marker,
  recursively clean a root or mutate the offline source folder.
- Existing download consent, fixed URLs, isolated transport and resume-prefix
  validation remain intact. There is no download in a constructor or inspection.

Add a read-only journal inspection enum: MISSING, CLEAN, RECOVERY_REQUIRED, BUSY.
It must not create directories/markers/records, rewrite data, acquire a writable
record, delete a profile or infer process ownership from a PID. A dirty, malformed
or unowned state is unavailable and clearly explained, not automatically reset.
Current retained-owner retry remains distinct from previous-process recovery.

## D2: one bounded resource operation owner

One Qt-owned controller and one bounded runner borrow the existing coordinator,
manager and inference service. At most one running operation and one latest
pending replacement; at most one queued progress update. Immutable requests carry
catalog ID, operation ID, captured authority generation/session and cancellation/
pause state, never document content, keys, provider profiles or live settings.

Transfer, hashes, extraction and actual self-check run off the Qt thread. Accept
download/import/prepare only by explicit current action while LOCAL is selected.
Selecting local immediately fences new cloud submissions; canceling preparation
leaves LOCAL selected. Selecting cloud cancels/fences old preparation. An already
committed cloud request cannot be recalled, and this limitation remains visible.

Publish PREPARING before capturing the resulting generation. Only a current,
genuine service READY result with its engine identity may publish local READY.
Remove terminal request ownership before reentrant public signals; retain actual
Future, emission and Qt acknowledgment tails until they finish. Pause/cancel is
a request, not instantaneous completion; a blocked native read remains owned.
Finite failed drain retains controllers, workers and the Qt engine.

## D3/D4: production graph and desktop flow

Use exactly one Batch/Watch analysis/preparation/inference graph and shared file
lane. The new controller owns resource preparation, not a separate analyzer.
Catalog publication is mode-aware and readiness must come from that same service.
Partial construction registers each owner before later fallible steps.

Place a permanent processing choice/status bar below the title bar in the content
column, separate from the smart/template naming control. Add a local-resource card
after General in Preferences. Choice/resource actions apply immediately and are
not undone by Settings Cancel. Respect existing tokens and controls, visible
labels, keyboard focus, wrapped explanations and scrollable minimum-size layout.
No new navigation page, palette, hover-only instruction or decorative redesign.

First-use consent shows model/version, fixed source hosts, exact remaining bytes,
destination and advisory peak-space basis. Only public resources are requested;
documents, names, paths, prompts and keys are excluded. Public download is still
network activity. Display MISSING/PARTIAL/TRANSFERRING/VERIFYING/PREPARING/READY/
FAILED/RECOVERY_REQUIRED honestly. AVAILABLE alone says "verified, not enabled".

The three locales are zh-CN, zh-HK and en-US. Native verification must exercise
1000x700 and 900x640, real mouse/keyboard, cancellation/navigation, CJK legibility,
scrolling/overlap and zero runtime warnings. New screenshots remain QA-only;
formal Golden updates require separate explicit scoped approval.

## D5: delivery and verification boundary

Update all three existing HTML manuals and preserve their offline locale links.
Document the two independent choices, resource preparation, already-sent cloud
requests, exact privacy scope, no fallback, measured limits and safe recovery.
Do not claim control over other software, OS sync or the entire computer.

Package the exact runtime ZIP/catalog/notices and early preparation-worker
dispatch, never weights, QA directories, model raw outputs, secrets or developer
paths. Verify frozen startup outside repository/CWD with isolated user data and
fake credentials, then actual offline import/readiness/Batch/Watch/clean close.

Required evidence: synthetic source negatives, real managed model mixed corpus,
mode-switch Batch/Watch no-cloud negatives, actual Windows interface, complete
regression with UPDATE_GOLDENS off, acceptance and isolated frozen smoke. Record
each actual command/result and retain failures. P2 polish enters backlog; safety,
data damage, false readiness/privacy and unusable core flow block completion.
