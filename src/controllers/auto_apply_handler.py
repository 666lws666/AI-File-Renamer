"""Auto Apply watch pipeline — stable file → analyze → apply automatically.

Shares the EXACT same chain as Batch and Review First:
- the same analysis protocol (src.core.watch_analysis);
- FileTask metadata + RenamePlan + FilenameValidator;
- PreflightService + RenameExecutor (the same instance the Batch uses);
- the shared RenameHistory (written by the executor) → the main
  UndoManager can undo auto-applied renames.

Invariants:
- Only stable (debounced) file events start processing — the watch
  controller guarantees this before dispatch.
- Temp files / incomplete downloads / Office lock files are filtered by the
  controller before dispatch.
- The source/target recursion guard comes from WatchConfig validation
  (target must not overlap source) — never re-entered.
- Low-confidence results are retried ONLY through injected retry machinery
  (existing QualityMode / LowConfidenceRetry composition) — this handler
  never reimplements retry policy and never switches providers.
- A provider lacking the required capability returns a structured
  capability error — no fake success, no silent provider switch.
- Restart is idempotent via a persisted journal: applied tasks are never
  re-applied; interrupted tasks re-check source/target/fingerprint;
  history/disk inconsistency fails closed.
- Cancellation stops all further processing.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.core.filename_validator import validate_filename
from src.core.rename_plan import RenamePlan, SourceFingerprint
from src.core.usage import error_category_for
from src.core.watch_analysis import AnalysisResult
from src.core.managed_watch_metadata import (
    ManagedWatchMetadata, encode_managed_metadata, decode_managed_metadata,
)

ERR_FINGERPRINT_CHANGED = "fingerprint_changed"
ERR_ANALYSIS = "analysis_failed"
ERR_CAPABILITY = "capability_unsupported"
ERR_PREFLIGHT = "preflight_rejected"
ERR_APPLY = "apply_failed"
ERR_JOURNAL = "journal_unavailable"
ERR_INCONSISTENT = "history_inconsistent"
ERR_CANCELLED = "cancelled"
ERR_SOURCE_MISSING = "source_missing"


class AutoApplyJournalError(RuntimeError):
    """Journal corrupted or unwritable — fail-closed, no blind applies."""


@dataclass(frozen=True)
class _JournalEntry:
    key: str                     # watch_id + "\x00" + source_path
    fingerprint: tuple[int, int]
    state: str                   # "applied" | "interrupted" | "failed"
    suggested_name: str = ""
    target_parent: str = ""
    extension: str = ""
    batch_id: str = ""
    error_category: str = ""
    managed_metadata: ManagedWatchMetadata | None = None


class AutoApplyJournal:
    """Persistent idempotency journal — versioned, atomic, fail-closed."""

    SCHEMA_VERSION = 2

    @staticmethod
    def _encode_entry(entry: _JournalEntry) -> dict:
        if type(entry) is not _JournalEntry:
            raise ValueError()
        record = {name: getattr(entry, name) for name in (
            "key", "state", "suggested_name", "target_parent", "extension", "batch_id",
            "error_category",
        )}
        if (any(type(value) is not str for value in record.values())
                or not entry.key or entry.state not in ("applied", "interrupted", "failed", "held")
                or type(entry.fingerprint) is not tuple or len(entry.fingerprint) != 2
                or any(type(value) is not int or value < 0 for value in entry.fingerprint)):
            raise ValueError()
        record.update(size=entry.fingerprint[0], mtime_ns=entry.fingerprint[1],
            managed_metadata=(None if entry.managed_metadata is None
                              else encode_managed_metadata(entry.managed_metadata)))
        return record

    def __init__(self, file_path: str | Path):
        self._file_path = Path(file_path)
        self._lock = threading.Lock()
        self._entries: dict[str, _JournalEntry] = {}
        self._load()

    @staticmethod
    def _key(watch_id: str, source_path: str) -> str:
        return f"{watch_id}\x00{source_path}"

    def get(self, watch_id: str, source_path: str) -> _JournalEntry | None:
        with self._lock:
            return self._entries.get(self._key(watch_id, source_path))

    def put(self, entry: _JournalEntry) -> None:
        """Persist an entry.  A failed save leaves memory AND disk
        unchanged (candidate copy is swapped only after the atomic write)."""
        try:
            self._encode_entry(entry)
        except (TypeError, ValueError, AttributeError) as error:
            raise AutoApplyJournalError("auto apply journal write failed") from error
        with self._lock:
            candidate = dict(self._entries)
            candidate[entry.key] = entry
            self._save_locked(candidate)   # persist FIRST — only then swap
            self._entries = candidate

    def entries(self, state: str) -> list[_JournalEntry]:
        """Entries in one state across all watches, in deterministic order."""
        with self._lock:
            return [entry for entry in self._entries.values() if entry.state == state]

    def entries_for_watch(self, watch_id: str, state: str) -> list[_JournalEntry]:
        """Entries for one watch in insertion (deterministic) order."""
        prefix = f"{watch_id}\x00"
        with self._lock:
            return [e for e in self._entries.values()
                    if e.key.startswith(prefix) and e.state == state]

    def count_for_watch(self, watch_id: str, state: str) -> int:
        return len(self.entries_for_watch(watch_id, state))

    def count(self, state: str) -> int:
        """Entries in one state across ALL watches (pipeline-wide total)."""
        with self._lock:
            return len([e for e in self._entries.values() if e.state == state])

    def _save_locked(self, entries: dict[str, _JournalEntry]) -> None:
        tmp: Path | None = None
        try:
            data = {"schema_version": self.SCHEMA_VERSION,
                    "entries": [self._encode_entry(e) for e in entries.values()]}
            json_text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True,
                                   allow_nan=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="auto_apply_", dir=str(self._file_path.parent))
            tmp = Path(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(self._file_path))
        except (OSError, TypeError, ValueError, AttributeError) as error:
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise AutoApplyJournalError("auto apply journal write failed") from error

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = self._file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (ValueError, OSError, UnicodeError) as error:
            raise AutoApplyJournalError("auto apply journal corrupted") from error
        candidate: dict[str, _JournalEntry] = {}
        try:
            if (type(data) is not dict or type(data.get("schema_version")) is not int
                    or data["schema_version"] not in (1, 2)
                    or type(data.get("entries")) is not list):
                raise ValueError()
            for entry in data["entries"]:
                if type(entry) is not dict or (data["schema_version"] == 1
                        and "managed_metadata" in entry):
                    raise ValueError()
                metadata = entry.get("managed_metadata")
                if metadata is not None:
                    metadata = decode_managed_metadata(metadata)
                item = _JournalEntry(
                    key=entry["key"], fingerprint=(entry["size"], entry["mtime_ns"]),
                    state=entry["state"], managed_metadata=metadata,
                    **{name: entry.get(name, "") for name in (
                        "suggested_name", "target_parent", "extension", "batch_id", "error_category")},
                )
                self._encode_entry(item)
                if item.key in candidate:
                    raise ValueError()
                candidate[item.key] = item
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise AutoApplyJournalError("auto apply journal corrupted") from error
        self._entries = candidate


class AutoApplyHandler:
    """One auto-apply handler per watch controller.  All dependencies are
    injectable; tests use fakes throughout."""

    LOW_CONFIDENCE_THRESHOLD = 0.5

    def __init__(
        self,
        *,
        journal: AutoApplyJournal,
        analysis_service: object,
        executor: object,
        preflight: object,
        config_provider: Callable[[str], object | None],
        confidence_retry: Callable[[Callable[[], AnalysisResult]], AnalysisResult] | None = None,
        default_quality_mode: str = "balanced",
        on_state_changed: Callable[[], None] | None = None,
        resource_guard: object | None = None,
        on_resource_pause: Callable[[str], None] | None = None,
    ) -> None:
        self._journal = journal
        self._analysis = analysis_service
        self._executor = executor
        self._preflight = preflight
        self._config_provider = config_provider
        self._confidence_retry = confidence_retry
        self._default_quality_mode = default_quality_mode
        self._on_state_changed = on_state_changed or (lambda: None)
        self._resource_guard = resource_guard
        self._on_resource_pause = on_resource_pause or (lambda watch_id: None)
        self._journal_available = True
        self._journal_error = ""
        try:
            self._journal.get("", "")  # probe fail-closed
        except AutoApplyJournalError as error:
            self._journal_available = False
            self._journal_error = error_category_for(error)
        self._stopped = False
        self._in_flight: set[str] = set()  # (watch_id, path) keys in this session
        self._lock = threading.Lock()
        # Self-wiring: the guard aggregates EVERY registered pipeline's
        # pending counts.  Auto Apply registers its journal's held entries
        # (persisted, always consistent) as the per-watch pending and its
        # journal-wide held total as the global pending.  A shared guard
        # sums this with Review First's contribution — registration order
        # never matters.
        if self._resource_guard is not None:
            if hasattr(self._resource_guard, "register_pending_source"):
                self._resource_guard.register_pending_source(
                    "auto_apply",
                    per_watch_counter=self._held_count,
                    global_counter=lambda: self._journal.count(state="held"),
                )
            elif hasattr(self._resource_guard, "set_pending_counter"):
                self._resource_guard.set_pending_counter(self._held_count)
                # The GLOBAL pending limit compares against the pipeline-wide
                # total (all watches of this journal), never one watch's count.
                if hasattr(self._resource_guard, "set_global_pending_counter"):
                    self._resource_guard.set_global_pending_counter(
                        lambda: self._journal.count(state="held"))

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Cancel all further processing.  No background work continues."""
        self._stopped = True

    def resume(self) -> None:
        self._stopped = False

    def restore_after_restart(self) -> int:
        """Reconcile interrupted journal entries with durable rename history."""
        history = getattr(self._executor, "history", None)
        if history is None:
            return 0
        recovered = 0
        interrupted = self._journal.entries("interrupted")
        for entry in interrupted:
            watch_id, source_path = entry.key.split("\x00", 1)
            task_id = f"{watch_id}:{source_path}"
            record = history.get_latest_for_task(task_id)
            if (
                record is not None
                and os.path.isfile(str(record.new_path))
                and not os.path.exists(str(record.old_path))
            ):
                self._journal.put(_JournalEntry(
                    key=entry.key, fingerprint=entry.fingerprint, state="applied",
                    suggested_name=entry.suggested_name,
                    target_parent=entry.target_parent, extension=entry.extension,
                    batch_id=record.batch_id,
                ))
                recovered += 1
        if recovered:
            self._on_state_changed()
        return recovered

    def on_watch_resumed(self, watch_id: str) -> None:
        """Resource recovery / manual resume: re-process held entries in
        deterministic order.  No duplicates — fingerprints are re-checked
        inside the pipeline, and applied tasks are never re-applied."""
        for entry in self._journal.entries_for_watch(watch_id, state="held"):
            source_path = entry.key.split("\x00", 1)[1]
            self.handle_file_ready(watch_id, source_path)

    @property
    def journal_available(self) -> bool:
        return self._journal_available

    def _held_count(self, watch_id: str) -> int:
        return self._journal.count_for_watch(watch_id, state="held")

    # ── Pipeline entry ────────────────────────────────────────────────────

    def handle_file_ready(self, watch_id: str, source_path: str) -> None:
        """Process one stable file: analyze → preflight → apply (idempotent)."""
        if self._stopped or not self._journal_available:
            return
        config = self._config_provider(watch_id)
        if config is None:
            return

        key = AutoApplyJournal._key(watch_id, source_path)
        with self._lock:
            if key in self._in_flight:
                return  # dedupe re-delivered events in this session
            self._in_flight.add(key)
        try:
            self._process(watch_id, source_path, config)
        finally:
            with self._lock:
                self._in_flight.discard(key)

    def _process(self, watch_id: str, source_path: str, config) -> None:
        current = self._stat_fingerprint(source_path)
        if current is None:
            return  # gone — nothing to do

        entry = self._journal.get(watch_id, source_path)

        # Journal says applied → idempotent: the SAME fingerprint is the same
        # operation (already applied) — never re-analyze, never re-apply,
        # never rewrite the applied marker.  A DIFFERENT fingerprint is a
        # NEW file at the same path → fall through to a fresh operation.
        if entry is not None and entry.state == "applied":
            if entry.fingerprint == current:
                return
            # different fingerprint → new file: continue into a new analysis

        # Resource gate: while the guard blocks, the task is HELD — no
        # analysis, no apply; the file is never lost and never falsely
        # marked successful.
        if self._resource_guard is not None:
            decision = self._resource_guard.try_acquire_analysis(watch_id, current[0])
            if decision.blocked:
                self._journal.put(_JournalEntry(
                    key=AutoApplyJournal._key(watch_id, source_path),
                    fingerprint=current, state="held"))
                self._on_resource_pause(watch_id)
                return

        try:
            # Interrupted with a matching fingerprint → resume from the journal
            if (
                entry is not None and entry.state == "interrupted"
                and entry.fingerprint == current
                and entry.suggested_name and entry.target_parent
            ):
                self._apply(watch_id, source_path, entry.suggested_name,
                            entry.target_parent, entry.extension, current, config)
                return

            # Otherwise: fresh analysis (or re-analysis after a changed file)
            result = self._analyze_with_retry(watch_id, source_path, config)
            if result is None:
                return
            if not result.ok:
                category = ERR_CAPABILITY if result.error_category == "capability_unsupported" else ERR_ANALYSIS
                self._journal.put(_JournalEntry(
                    key=AutoApplyJournal._key(watch_id, source_path),
                    fingerprint=current, state="failed", error_category=category))
                self._note_failure(watch_id)
                self._on_state_changed()
                return

            validation = validate_filename(result.suggested_name, Path(source_path).suffix)
            if not validation.is_valid:
                self._journal.put(_JournalEntry(
                    key=AutoApplyJournal._key(watch_id, source_path),
                    fingerprint=current, state="failed", error_category="invalid_suggestion"))
                self._note_failure(watch_id)
                self._on_state_changed()
                return

            target_parent = config.target_dir or str(Path(source_path).parent)
            self._apply(watch_id, source_path, result.suggested_name,
                        target_parent, Path(source_path).suffix, current, config)
        finally:
            if self._resource_guard is not None:
                self._resource_guard.release_analysis(watch_id)

    # ── Analysis (shared protocol; retry only via injected machinery) ─────

    def _analyze_with_retry(self, watch_id: str, source_path: str, config):
        """Normalize analysis into a structured result — NEVER touches the
        resource guard.  Failure accounting happens exactly once per
        operation at the caller's completion boundary."""
        def once() -> AnalysisResult:
            return self._analysis.analyze(
                source_path,
                template_id=config.template_id or "",
                quality_mode=self._default_quality_mode,
            )

        try:
            result = once()
        except Exception as error:
            # normalized structured result — never a raw exception to callers
            return AnalysisResult(
                suggested_name="", confidence=0.0,
                error_category=error_category_for(error))
        if (
            isinstance(result, AnalysisResult)
            and result.ok
            and result.confidence < self.LOW_CONFIDENCE_THRESHOLD
            and self._confidence_retry is not None
        ):
            # Delegate the retry to the injected machinery (existing
            # QualityMode / LowConfidenceRetry composition) — never a second
            # retry policy here, never an implicit provider switch.
            try:
                result = self._confidence_retry(once)
            except Exception:
                result = AnalysisResult(
                    suggested_name="", confidence=0.0,
                    error_category=error_category_for(Exception("retry_failed")))
        return result

    def _note_failure(self, watch_id: str) -> None:
        """Record one failed operation on the guard (consecutive failures
        trip the failure backoff)."""
        if self._resource_guard is not None:
            self._resource_guard.note_failure(watch_id)

    def _note_success(self, watch_id: str) -> None:
        """Record one successful operation — resets the failure count under
        the unified semantic: any completed operation either fails once or
        succeeds."""
        if self._resource_guard is not None:
            self._resource_guard.note_success(watch_id)

    # ── Apply via the shared Batch engine chain ───────────────────────────

    def _apply(self, watch_id, source_path, suggested_name, target_parent,
               extension, fingerprint, config) -> None:
        batch_id = f"watch-auto-{watch_id}"
        plan = RenamePlan(
            task_id=f"{watch_id}:{source_path}",
            source_path=source_path,
            source_fingerprint=SourceFingerprint(*fingerprint),
            target_name=suggested_name,
            target_parent=target_parent,
            extension=extension,
            batch_id=batch_id,
        )

        # Journal the intent BEFORE execution → an interrupted run resumes
        self._journal.put(_JournalEntry(
            key=AutoApplyJournal._key(watch_id, source_path),
            fingerprint=fingerprint, state="interrupted",
            suggested_name=suggested_name, target_parent=target_parent,
            extension=extension, batch_id=batch_id,
        ))

        # Mandatory preflight against the CURRENT file state
        try:
            pf = self._preflight.check(plan)
        except Exception as error:
            self._journal.put(_JournalEntry(
                key=AutoApplyJournal._key(watch_id, source_path),
                fingerprint=fingerprint, state="failed",
                error_category=error_category_for(error)))
            self._note_failure(watch_id)
            return
        if not pf.can_execute:
            self._journal.put(_JournalEntry(
                key=AutoApplyJournal._key(watch_id, source_path),
                fingerprint=fingerprint, state="failed",
                error_category=ERR_PREFLIGHT))
            self._note_failure(watch_id)
            self._on_state_changed()
            return

        try:
            results = self._executor.execute([plan], batch_id=batch_id)
        except Exception as error:
            self._journal.put(_JournalEntry(
                key=AutoApplyJournal._key(watch_id, source_path),
                fingerprint=fingerprint, state="failed",
                error_category=error_category_for(error)))
            self._note_failure(watch_id)
            self._on_state_changed()
            return

        result = results[0] if results else None
        if result is not None and result.success:
            try:
                self._journal.put(_JournalEntry(
                    key=AutoApplyJournal._key(watch_id, source_path),
                    fingerprint=fingerprint, state="applied",
                    suggested_name=suggested_name, target_parent=target_parent,
                    extension=extension, batch_id=batch_id,
                    error_category="history_unavailable" if result.recovery_required else "",
                ))
            except AutoApplyJournalError:
                # The interrupted intent plus RenameHistory are enough for
                # deterministic startup reconciliation.  Do not relabel a
                # successful move as a failed apply.
                pass
            self._note_success(watch_id)
        else:
            self._journal.put(_JournalEntry(
                key=AutoApplyJournal._key(watch_id, source_path),
                fingerprint=fingerprint, state="failed",
                error_category=ERR_APPLY))
            self._note_failure(watch_id)
        self._on_state_changed()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _stat_fingerprint(self, source_path: str) -> tuple[int, int] | None:
        try:
            if not os.path.isfile(source_path):
                return None
            stat = os.stat(source_path)
            return (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return None

    # ── Test helpers ──────────────────────────────────────────────────────

    def journal_entry(self, watch_id: str, source_path: str) -> _JournalEntry | None:
        return self._journal.get(watch_id, source_path)
