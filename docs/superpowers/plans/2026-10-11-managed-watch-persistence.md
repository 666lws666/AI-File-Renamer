# Managed Watch Result Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with TDD, a fresh scoped spec/quality reviewer and root-owned verification/Git.

**Goal:** Persist reviewed managed result facts and unknown confidence through the existing Watch stores without replaying processing authority or changing saved Watch choices.

**Architecture:** Extend existing ReviewItem/ReviewQueue and AutoApplyJournal records with optional immutable ManagedWatchMetadata. Versioned read compatibility preserves valid schema1 records; writing uses schema2 only after an explicit existing store mutation. This is a persistence/projection task, not observer activation, inference orchestration or an Apply permit.

**Tech Stack:** Existing atomic candidate stores, managed_watch_metadata codec, ordinary Python dataclasses/JSON and the existing Qt WatchPageController projection.

## Global Constraints

- Start only after C2A and the independent metadata codec task pass scoped review and root checkpoints. Root owns Git; one source writer in the existing isolated codex/local-privacy-mode checkout. No main edits, merge, push or release.
- Preserve all existing Watch IDs/config/status/mode and queue/journal item IDs, timestamps, paths, names, fingerprints, states and batch history identifiers. Do not rewrite files at load time or silently alter saved Auto Apply consent.
- Managed confidence is None. Preserve valid legacy numeric scores as legacy data, never synthesize a score for managed results or trigger confidence retries to manufacture one.
- Persist only the explicit managed metadata codec; no AnalysisWork, WorkContext, event/delivery token, authority session/generation, credential/profile, prompt, raw text/image/PDF/video or runtime object.
- Persisted metadata is descriptive. Loading it cannot reconstruct current processing authority, authorize Auto Apply, launch inference, submit file operations or run network/credential lookups.
- Candidate serialization and atomic write succeed before in-memory state swaps; failure preserves old memory and disk. No best-effort success after a failed write, including JSON/metadata validation errors.
- No real API/key/Credential Manager/private input, firewall/ACL changes, dependency installation, Golden update, native/model claim or unrelated refactor. No QML, Provider, file engine/history, resource model or managed Watch activation.

## Task 1: compatible store schema and truthful result projection

**Files:**

- Modify src/core/watch_review_queue.py.
- Modify src/controllers/auto_apply_handler.py: only AutoApplyJournal/_JournalEntry persistence definitions; do not change legacy AutoApplyHandler execution.
- Modify src/controllers/watch_page_controller.py: only result-row projection and related imports.
- Create tests/unit/test_managed_watch_persistence.py.
- Modify tests/unit/test_watch_page_controller.py: focused projection coverage only.

No other source/test edits.

### Exact record contract

- Add trailing ReviewItem.managed_metadata: ManagedWatchMetadata | None = None, preserving all positional fields. Change confidence annotation to float | None while keeping the old default0.0 for legacy constructors.
- Add trailing _JournalEntry.managed_metadata: ManagedWatchMetadata | None = None. No new independent journal or history store.
- ReviewQueue and AutoApplyJournal writes use schema_version2. Reads accept exact integer1 or2 (not bool), reject future/foreign schema before side effects, and never rewrite an old valid file just by opening it.
- A schema1 record has no managed_metadata and retains its existing compatible missing-field defaults. A present managed metadata payload in schema1 is rejected rather than interpreted under a different version.
- In schema2, managed_metadata is either null/absent or the exact encode_managed_metadata/decode_managed_metadata representation. Managed ReviewItem records require confidence=None and matching content_kind. The journal has no confidence/content_kind field today: do not add a guessed score; its exact managed metadata carries those descriptive facts.
- A pending managed ReviewItem may have confidence=None with no completed metadata; None must roundtrip and be distinguishable from numeric0.0. Legacy numeric finite scores0..1 continue to roundtrip. Reject bool, NaN/infinity, arbitrary objects and out-of-range numeric confidence before writing.
- A managed result must never persist numeric confidence, even if a caller provides one. Metadata type is exact ManagedWatchMetadata; dict lookalikes and foreign dataclasses fail closed.
- Existing stores legitimately retain file-operation metadata such as source_path/suggested_name. The added managed metadata object itself remains path/name/content-free. Do not conflate these two contracts or erase existing queue/history fields.
- Serialize managed_metadata explicitly through its codec. Do not use recursive asdict on that object or automatically include future coverage/dataclass fields.
- JSON encoding uses allow_nan=False. Convert validation/serialization errors to existing fixed safe ReviewQueueError/AutoApplyJournalError without embedding raw values. Preserve original exception chaining only internally.
- Loader builds and validates the complete candidate dict before assigning it. No partial publication if a later entry is corrupt; duplicate item IDs/journal keys must fail rather than silently drop an entry.
- Validate record shapes without permissive str/int/float coercion: existing required IDs/watch/source/key strings must be nonempty; size/mtime fingerprints are exact nonnegative integers (not bool); state is an existing known review/journal state; present optional name/path/category/batch/timestamp strings retain their type. Preserve compatible missing optional defaults. Reject malformed foreign records with the existing fixed safe store error before I/O/publication; writes likewise require the exact store record class. This is structural validation, not source-path authorization or a new timestamp-format migration.
- Schema migration occurs only via a successful normal add/update/remove/put operation; on failed migration write, original schema1 bytes and old in-memory objects remain unchanged.

### Truthful UI projection

- WatchPageController._result_row preserves confidence=None; it must not call float(None), replace unknown with0.0, or invent a percentage.
- Valid legacy numeric confidence remains numeric. Missing or invalid foreign/fake projection data is represented as unknown rather than a guessed score.
- For a ReviewItem with exact managed metadata, project its content kind, warning codes, requested/effective quality and a fixed review reason from auto_apply_review_reason. These are descriptive QVariant-compatible values only, not an approval or authorization flag.
- For a legacy item/no metadata, expose a stable empty metadata projection, preserving existing id/name/state/error fields.
- Do not change action return semantics, templates/form/state management, Watch configuration or QML in this task.

### Test-first cases

- [ ] Add genuine RED tests before changing either store: managed text/image/scan/video result roundtrip, None confidence and legacy schema1 preservation.
- [ ] Confirm creating/opening an old valid file performs no write, network, credential lookup, inference or file operation.
- [ ] Roundtrip all existing record identity/fingerprint/timestamp/state/history fields together with explicit managed metadata, not merely a standalone codec.
- [ ] Schema2 pending item with None/no metadata remains None; schema1 valid numeric score remains the same. Never mutate an input record during encoding/decoding.
- [ ] Inject failed mkdir/temp/write/fsync/replace into normal managed add/update/remove/put; old memory and exact old disk bytes survive. Cover at least create and update on ReviewQueue, and put replacement on AutoApplyJournal.
- [ ] Invalid metadata, wrong confidence, NaN, extra secret/path inside metadata, duplicate IDs/keys, malformed later entry, schema bool/future version fail closed without partial publication or disk changes.
- [ ] Valid schema1 mutation writes schema2 and preserves unrelated legacy entries. Failed schema1 mutation leaves its original bytes/version unchanged.
- [ ] Raw stored metadata JSON has none of the synthetic source-content/prompt/credential/runtime/work sentinels; record-level existing path/name fields remain present as designed.
- [ ] Direct WatchPageController projection for None confidence, legacy score and managed warnings/quality/review reason produces correct values and no exception. Empty/legacy projection is backward compatible.
- [ ] No test activates Watch or pretends persistence is model quality or current-work authorization.

### Verification and checkpoint

Root supplies the existing strong Windows guard; use project venv, isolated user/temp dirs, ordinary GC, deny actual network and native credential entry points, UPDATE absent.

Cover exactly:
- tests/unit/test_managed_watch_persistence.py
- tests/unit/test_managed_watch_metadata.py
- tests/unit/test_watch_page_controller.py
- tests/integration/test_review_first.py
- tests/integration/test_auto_apply.py
- tests/integration/test_watch_safety_regressions.py
- tests/integration/test_watch_resource_guard_pipeline.py

Record actual RED/GREEN commands, outputs, native exits, forbidden count, exact five-file list/hashes and self-review to .superpowers/sdd/managed-watch-persistence-report.md. Root obtains fresh scoped review, independently verifies the covered tests and creates the exact local checkpoint. No staging or committing by the writer.

## Dependent work deliberately not implemented here

Private queued admission acceptance, current incarnation/config/fingerprint checks, bounded managed analysis runners, shared file-lane reservation/commit and publication, exact Apply/Undo reconciliation, restart fail-closed recovery, resource recovery admission and real native Watch/local inference remain separate tasks. Persisted old or new metadata is never replayable analysis authority. Production Watch stays unavailable until those tasks and runtime composition pass.
