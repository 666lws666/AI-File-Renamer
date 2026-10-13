# Production managed Watch composition

Date: 2026-10-12. Baseline: `5d55b93b771efd57e3df38c00e8f8804ce3111f6`.

## Approved scope and current facts

Product Owner authorizes autonomous completion of the existing local/privacy/Watch/package scope, including ordinary technical choices and tests. This bounded milestone activates production Watch using reviewed components, not a new product feature. Completed native file-safety work is not reopened. Source default Watch is currently deliberately unavailable. Actual current four-file guarded baseline: 248 passed, three existing Pydantic warnings, zero forbidden accesses, normal MainThread-only exit. This is not model/GUI/package evidence.

## Design decision

Compose one owned `ManagedWatchRuntime` beside the existing production Batch runtime. It borrows the exact `BatchAnalysisService`, `ProcessingAuthority`, `AnalysisCatalogSource` and runtime-owned serial `ManagedFileOperationLane`. Reusing the service preserves its shared cloud execution bound; reusing the lane preserves serial history and partial Apply/Undo truth. Do not construct legacy ReviewFirstHandler/AutoApplyHandler or another analyzer/backend/history.

Construct the delivery/results/controller cycle inertly, bind every consumer, restore only descriptive interrupted states, create QML, and only then start restored ACTIVE observers. Preserve saved modes/templates/languages. Existing Watch ingress remains template-based; adding a per-watch smart policy is a later compatible task, not a silent reinterpretation of saved templates.

Alternatives rejected: enabling old observers with legacy handlers bypasses the reviewed authority/lifecycle path; leaving Watch None with a completed-looking page is an unusable core flow. A second Watch AI/file service would split resource limits/history ownership.

## Genuine publication and actions

Add a private newly-published-result hook inside ManagedWatchResults, keeping delivery._consume as the actual bound results.consume_result. Invoke only for a newly durably created successful row during genuine delivery publication, after failure/success accounting. Ordinary stateChanged is presentation only.

Auto Apply checks saved/captured Auto Apply consent, exact result/event/row, binding READY, current authority, eligible actual coverage and open owners. Check again after fallible durable APPLYING publication and all precommit callbacks, immediately before lane.commit. A denied final predicate cancels the exact reservation and restores the old row; no move occurs. Once committed, subsequent AI invalidation never discards disk truth. Unknown confidence stays None. Incomplete/unknown/quality-degraded contents stay in review; planned video keyframes remain visible sampling evidence.

A managed action facade exposes approve/ignore/retry/undo and edit counts. False is an actual refusal. Retry explicitly captures new authority under current binding; saved work/intents are never replay authority. Recovery-held or APPLYING records cannot be retried/approved. Applied history survives edits/removal. Page renders fixed notices, review limitations, Undo and recovery hold without layout redesign.

## Shared-lane self-event ownership

Use a bounded thread-safe receipt registry shared by Batch and Watch. It is an observer filter, not file-operation authority. Its keys are genuine lane operation/row identities. Hold source/proposed destination and bounded collision family before the lane can dispatch; exact Undo/compensation candidates need a narrow non-authorizing worker observation seam before any native mutation. No native move algorithm or historical identity validation changes.

Incoming candidate events must first capture their original processing context. A hold retains that exact bounded admission; it does not recapture under later mode/settings. At stabilization on a non-Qt worker, decide hold/allow/suppress using the registry. Suppression requires actual completed matching native volume/file ID/creation and content fingerprint at the exact target, not path or size/mtime alone. Unrelated replacements/siblings are processed under their original context or retired as stale. Capacity exhaustion is explicit fail-closed; unknown recovery paths remain held/visible, never treated as successful self-events.

Use at most 1000 active receipts, at most 1000 retained admissions through existing ingress ownership, and bounded late receipts with an explicit finite policy (30 seconds maximum). Collision-family matching is pure bounded parsing, not 1000 expanded path allocations per item. Expiration releases unmatched admissions with their original context, never grants new AI authority. Close seals receipt admission but retains committed settlements/actual callback tails. No filesystem, arbitrary callbacks, Qt signals or event pumping under registry/lane/controller/authority locks.

SourceFingerprint contains only size/mtime, not a content digest. A separate
worker-only read observation uses SHA-256 of the default stream under one held
read-only native file handle: at most 512 MiB, 64 KiB chunks and a 2-second soft
deadline with cooperative cancellation. Traverse ancestors through relative
non-reparse opens, not a leaf-only CreateFile path that follows parent junctions.
Require ordinary single-link NTFS metadata before/after that same handle read.
Compare actual successful native POST identity plus current digest with the
observed pre-operation digest; any missing/changed evidence forbids suppression.
This observation grants no rename authority and never rewrites historical proof.

The observation has its own retained native request/handle owner, separate from
safe_file_move._OWNER. It may reuse only that module's stateless create/info/free
primitives with its independent quarantine object, never its _Transaction or
rename path. Use FILE_OPEN only, no CREATE/WRITE/DELETE/guard creation, strict
native completion and ambiguous free/close retention. Pending or blocked reads
are real owned tails; deadline does not pretend to interrupt synchronous I/O.
Actual Windows positive controls and owned ancestor/leaf-link negatives must
prove this boundary before default Watch is enabled.

## Production startup and closure

Default owned Watch uses stores beside the explicitly supplied settings path, established compatible filenames based on prior product composition and tested with old files. Never replace corrupt stores with empty stores. Recover PENDING/ANALYZING as cancelled/interrupted; APPLYING or retained disk intents as recovery-held. Preserve awaiting review, applied/undone rows and shared history.

Create a shared file lane whenever either default Batch or default Watch requires it. Explicit None disables that injected feature; supplied controllers stay caller-owned. Register partial owners immediately for construction-failure drain. Catalog/template publication works even when Batch is explicitly disabled.

Seal processing/new Watch/file-action admission before event pumping or public failure callbacks. Stop real observers/debounce/retry owners, cancel uncommitted analysis, retain genuine Future/emission/Qt acknowledgment tails and committed file results. Short cleanup polls combine Watch, Batch, lane, probes, choice writer, preparation and inference. Return False with owners retained if deadline expires; delete QML only after actual drain. No dictionary-removal, Future.done, Timer.cancel, forced GC or process exit substitutes for completion.

## Global constraints

- Use only `D:\\文件AI-AGENT\\.worktrees\\ai-smart-naming` on `codex/local-privacy-mode`; preserve main checkout and user shortcut.
- No push, release, merge, historical rewrite, Golden update, real cloud API/key/Credential Manager/private inputs, firewall/ACL/exemption/security-policy changes.
- Cross-volume automatic moves remain disabled; no os.rename/shutil/copy/delete fallback in the reviewed engine. Preserve original files and recovery evidence.
- All test configs/stores/credentials/transports are isolated/fake; screenshots and raw diagnostics only in `tests/screenshots/qa-current/local-privacy/`.
- One source/test writer; fresh task review and root frozen verification before a source checkpoint. Source PASS is not real model/GUI/package PASS.
- No silent cloud fallback. No invented confidence or unverified readiness. No persisted pending row/intent grants analysis or disk authority.
- Exact shared analyzer/authority/catalog and serial file lane; no duplicate service graphs, no Qt callbacks from watchdog/Timer workers.

## Acceptance and downstream boundaries

Synthetic Gates cover construction/start order, Review First and eligible Auto Apply, final authorization races, fresh Retry, Ignore/Undo/refusal, recovery/corrupt stores, original-context self-events/replacements/collisions, ResourcePaused, shared Batch/Watch concurrency, local switch and actual shutdown tails. Native Gates separately exercise real Windows observer events and actual native moves; UI images/clicks and model/media semantics are root-owned. Packaging and resource-management tasks follow this checkpoint; none is claimed completed by this design.
