# Managed Watch manual file actions

## Scope and authority

This implements the already approved Review First Apply/Undo contract for genuine durable managed Watch results. The user has authorized autonomous technical planning and implementation within the project boundaries; it does not authorize cloud requests, security-policy changes, Golden updates, merging main, push, or release. Current source baseline is 256166139479acb26cf71ad08539f50518134370 on codex/local-privacy-mode.

## Selected architecture

Use a dedicated ManagedWatchFileOperations Qt owner borrowing the application's existing ManagedFileOperationLane, not a second file worker, synchronous legacy ReviewFirstHandler/AutoApplyHandler, or a hidden duplicate Batch workspace. Only the existing FileOperationBackend/RenameExecutor/UndoManager touches user files. A metadata-only durable operation intent belongs to the review row; source identity is the existing ReviewItem.id, not a watch/path composite or list index.

Manual approval is explicit user intent; it does not grant AI path or file-operation authority. Restored metadata never grants automatic execution. An analysis result and a saved review row are not an Auto Apply permit.

## Durable store

Advance ReviewQueue alone to schema 3, leaving AutoApplyJournal at schema 2. Preserve schema 1/2 loads read-only with neutral defaults; a successful mutation migrates. Reject future versions, duplicate IDs and malformed complete records without replacing prior memory or bytes.

Add frozen WatchFileOperationIntent(version=1, operation_id, kind, batch_id, source_path, target_path), optional ReviewItem.file_operation, string applied_path, boolean recovery_required, and ReviewItemState.UNDONE. Intent records are explicit bounded primitives, not QObject/reservation/callback/prompt/content graphs. Kind is apply or undo; an apply batch ID is nonempty, an undo intent stores the row's existing nonempty applied batch ID even though the lane's undo request uses an empty batch ID. Paths are metadata needed for recovery, never AI payload.

Provide atomic multi-row compare-and-replace. All expected and replacement rows are exact immutable ReviewItem values; timestamps are prepared before taking the store lock. The lock checks exact currently stored expected object identities after any fallible clock callbacks, persists a complete candidate, then swaps memory. An outdated candidate, write failure, or invalid later row cannot partially modify a batch. The results owner's count snapshot is refreshed before notifying observers.

## Admission and outcomes

ManagedWatchFileOperations(results=..., lane=...) has apply(tuple of unique row IDs), undo(one row ID), begin_close, workers_idle, available, error. It borrows an exact existing lane/results on the same owner thread. Construction is inert and cannot restore/execute anything.

Apply accepts 1–1000 unique, currently available rows in Awaiting Approval or Undone with valid protected-extension suggestions, no unresolved intent/recovery, and no action ownership. All requested rows must qualify or no request is admitted. Split permitted template subdirectory suggestions on forward slashes, validate every directory component and final basename with the shared filename validator; derive target parent only from the trusted row target_parent (or source parent) plus those components. Pure path assembly on Qt is allowed, but no stat/exists/resolve/history/file move on Qt.

The request carries an optional immutable allowed_roots tuple, bounded to 2000 unique nonempty path strings, for apply only. Managed Watch explicitly captures each original source parent and the approved target root BEFORE adding template subdirectories. The worker passes these roots to the existing PreflightService, so a newly created subdirectory under an existing approved target can pass while an unrelated outside parent cannot. It must not widen a supplied root to a derived plan parent. Legacy requests with no explicit roots retain the existing backend behavior; Undo must not carry apply roots. This is a value-graph extension, not a second file engine or a relaxation of preflight.

Reserve capacity first. Atomically save Applying plus one intent per selected row and a shared new batch ID before lane.commit. Install exact ownership before committing; recheck both owners and saved identities after all fallible operations. No early notification can admit a second operation. A reserve failure performs no user-file I/O or Applying write. A failed save cancels the uncommitted reservation. Close, row mutation, or lane rejection before commit cancels and rolls back only the exact still-owned candidate; rollback failure keeps durable evidence and disables new actions. Never cancel already committed user-file work.

The lane supplies an owner-affine exact current publication predicate for progress/completion. New clients reject forged/cloned/replayed/out-of-callback payloads. Keep the predicate true through actual synchronous public notification only, not after it returns. Real progress may be observed more than once but a result index is consumed once before persistence or callbacks.

Validate each result against exact reservation, index, row ID, batch ID, kind and expected destination. The existing shared engine auto-counters collisions: an Apply destination may be the approved target or the same normalized parent plus approved stem_N and protected extension, where N is a canonical positive decimal integer. The exact original target's bytes must remain untouched. Never accept an arbitrary sibling stem, parent escape or changed extension. Undo must return the exact approved original path. Pure normcase/abspath comparison cannot silently approve a different filesystem alias; an unresolved alias is recovery-required rather than invented success. Apply success becomes Applied/applied_path; Undo success becomes Undone with empty applied_path and the genuine worker-returned current fingerprint. Undo result batch ID must match the stored applied batch. Apply failure becomes Failed; Undo failure remains Applied and may be explicitly retried if no recovery is required. Each success only updates its matching row. Unknown/malformed outcomes, missing Undo fingerprint, history recovery, or destination mismatch preserve intent and require recovery, never report another row as successful. Only fixed bounded error codes reach the row; raw worker exceptions/paths/prompts must not be persisted as errors.

Progress may arrive before completion. Terminal completion supplies any missing per-item results and retires this exact operation after all per-item updates, before notifying an observer that might immediately request Undo. Partial successes are retained. Pending counts follow durable state and remain conservative while an operation is Applying.

A durable completion-save failure retains the old intent and disables new actions; it does not pretend a moved file was rolled back. Synchronous notification failure is separated from store failure and must not erase a durably saved result. Committed outcomes must still be persisted during begin_close, and workers_idle remains false through the real completion/publication tail. The borrowed lane is not closed by this owner.

## Restart boundary and explicit exclusions

A restore helper, called only before actions exist, marks unmatched Applying/intents as recovery_required with a fixed interrupted code. It never moves/stat/reads history/replays or clears ambiguity. Existing already Applied schema1/2 rows without applied_path remain readable but cannot be silently reconstructed into executable Undo approvals. A later separately reviewed off-Qt recovery inspection will resolve them.

This slice does not activate production Watch observers, grant Auto Apply, suppress self-events, build local-model UI/resource consent, wire QML, rebuild EXE, run real Qwen, or claim the whole Watch/local-privacy release. These are remaining integration Gates, not placeholders in this deliverable.

## Verification

Use local synthetic files, the actual serial lane and actual file backend/history for dynamic Apply/Undo/partial/conflict tests. Assert Qt callbacks and backend worker identities, exact row association and byte-level file preservation. Negative tests cover duplicate/oversized/invalid IDs, extension/path escapes, forged signals and duplicates, reentrant close/ignore during persistence, save/rollback failures, malformed result association, missing fingerprint, shared-lane capacity, late committed outcomes during close, interrupted restart with zero execution, and schema migration/rollback.

Do not use static source assertions as a substitute for dynamic operation Gates. Preserve original failed tests, native exit codes, warnings and cleanup evidence. Normal tests cannot update Golden or skip a new failing Gate. Root runs frozen covering, full non-screenshot, screenshots with update unset, guarded acceptance, diff/status and hash checks after independent scoped review.
