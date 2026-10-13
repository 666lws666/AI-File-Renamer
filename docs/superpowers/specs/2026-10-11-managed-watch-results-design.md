# Managed Watch durable result publication

Approved autonomous continuation of local/cloud managed Watch. Source dependency3496d256c3d9d8fe0a9116fb701e6a89d8d87b54. This task persists genuine delivered analysis results and accounts durable backlog; it does not execute file operations or activate production observers.

## Approach and alternatives

Use existing ReviewQueue schema2 and immutable ReviewItem for durable results, a small Qt-owner ManagedWatchResults boundary, and a one-shot authentic result claim in ManagedWatchAnalysisDelivery. Reusing legacy ReviewFirstHandler.handle_file_ready/analyze would stat/extract/analyze a second time and use a second guard path. Merely collecting in-memory callbacks loses restart evidence. Chosen: persist the already-validated genuine result, no second analysis.

Delivery publishes a result identity only during its actual public consumer callback. claim_result(result) is exact, owner-thread, one-shot and current; clones, direct foreign calls, replay after callback and duplicate claims are rejected. is_publishing_result observes the same live identity/currentness without claiming. No new receipt/token is exposed.

## Durable states

Stable success is AWAITING_APPROVAL with the original source metadata/fingerprint, protected extension, captured target parent, suggested name and exact ManagedWatchMetadata. Confidence is None, never a fabricated score. Stable fixed failure is FAILED without outcome/metadata/suggestion. Raw WatchAdmissionFailure has no source metadata and creates no invented row: record a bounded fixed per-watch notice instead.

Same-watch active source path is not overwritten or duplicated by another result. All automatic execution remains absent here; saved metadata alone is never consent or a live execution permit. Both Review First and Auto Apply watches initially retain a durable reviewable result at this publication boundary; later file-operation integration consumes only fresh eligible results with explicit current Auto Apply configuration.

Queue writes occur before any changed notification or success publication. on_changed is an optional validated synchronous owner callback, not Qt Signal.emit: receiver exceptions swallowed by Qt are not evidence of fail-safe delivery closure. Its actual callback tail is counted; a notification exception after a successful write preserves the authoritative row/counts and propagates without being mislabeled a store failure. Store failure leaves ReviewQueue old memory/disk unchanged, marks this boundary unavailable with queue_unavailable, publishes an unavailable resource contributor, and propagates only a fixed ManagedWatchResultsError so delivery closes safely. Never publish a successful row from a failed write. Content/prompts/keys/outcomes are not serialized; source path/name remain local review metadata and must never be provider payload.

## Backlog accounting

ManagedWatchResults is the sole writer of its ReviewQueue in managed production wiring; do not construct legacy handlers on the same queue. Register one unique pending-source id on the shared exact WatchResourceGuard. Callbacks capture an immutable count snapshot, not a mutable queue or caller callback. Count ACTIVE_STATES (pending,analyzing,awaiting_approval,applying), including restored records.

After each successful durable write, replace the immutable contributor snapshot via register_pending_source, incrementing guard registry revision BEFORE the actual delivery pending receipt retires. Temporary conservative overlap of one live receipt and its saved row is allowed; no undercount or subtraction of caller-supplied counts. This can briefly hold another task, never authorizes more work. On store/snapshot failure the contributor must report unavailable rather than zero. Do not unregister durable backlog on begin_close; the guard belongs to the runtime lifetime, not just worker idleness.

## Restart and user-only metadata actions

restore_interrupted() runs before delivery attachment: PENDING/ANALYZING -> CANCELLED with fixed interrupted; retain AWAITING_APPROVAL and APPLYING without executing or inventing success. APPLYING needs later authoritative file/history reconciliation, not replay. Preserve APPLIED/IGNORED/FAILED and all old saved configurations/templates.

ignore(item_id) only changes uncommitted Pending/Analyzing/Awaiting/Failed/Cancelled records to IGNORED; APPLIED/APPLYING are not changed. cancel_watch(watch_id) cancels only unapplied/uncommitted records and preserves APPLYING/APPLIED/IGNORED. Each successful metadata write refreshes counts before notification; no user-file stat/read/write/history/Undo/model/transport from these methods.

Analysis operation accounting occurs once per genuinely claimed completion: successful outcome note_success once, fixed analysis_failed/timeout/invalid_outcome/local_unavailable/cloud_unavailable note_failure once. Source-change/resource/queue/admission failures do not fabricate an inference failure. Duplicate claim creates no second note. Store or observer failure never performs automatic resource resume or cloud fallback.

## Scope and Gates

Only modify src/controllers/managed_watch_analysis.py for the scoped published identity/claim API. Only create src/controllers/managed_watch_results.py and tests/integration/test_managed_watch_results.py. Guard, ReviewQueue, metadata codec, legacy handlers, file lane, WatchController/runtime/Provider/config/UI/models/manual/resources/package and all existing tests read-only. No Git by writer; root Git only. No cloud/Key/CM/security/network/model/source-content I/O/Golden/main operation.

Real Qt queue/Futures/guard/temp ReviewQueue fixtures prove no row before queued consumer; durable exact metadata/reload; claims/duplicate/copy/replay; persisted backlog blocks future admission and ignore frees it; write/replace failure rollback with no successful row; conservative overlap and concurrent sampled-count registry invalidation; fixed raw notices; current binding/mode withdrawal; reentrant changed close and actual public tail; exactly-once failure accounting; restored active backlog and no replay; no extra source access or legacy analysis. Finite threads joined and owners drained. Root frozen scoped review, sequential full/screens/acceptance, exact local checkpoint; no project/native/model/release completion claim. Prior Qt GC crash remains open.
