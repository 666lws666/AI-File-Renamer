"""M4 Vocabulary AI Manager — candidate storage, review workflow (no real AI calls)."""

import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from .vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
    VocabularyIntegrityError,
)


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    MODIFIED_ACCEPTED = "modified_accepted"
    MAPPED = "mapped"
    USED_ONCE = "used_once"
    IGNORED = "ignored"


@dataclass(frozen=True)
class VocabularyCandidate:
    """A structured AI vocabulary suggestion awaiting user review.

    Immutable. Stored separately from the formal vocabulary until a decision is made.
    """

    category: VocabularyCategory
    concept_id: str
    display_name: str
    locale: str
    confidence: float = 0.0
    source_model: str = ""
    task_id: str = ""
    id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not isinstance(self.category, VocabularyCategory):
            raise ValueError(
                f"Invalid category: {self.category!r}"
            )
        if not self.concept_id or not self.concept_id.strip():
            raise ValueError("VocabularyCandidate.concept_id must not be empty")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("VocabularyCandidate.display_name must not be empty")
        if not self.locale or not self.locale.strip():
            raise ValueError("VocabularyCandidate.locale must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not self.id:
            object.__setattr__(self, "id", str(uuid4()))
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc))


class VocabularyAIManager:
    """Manages AI vocabulary suggestions with a review workflow.

    Suggestions enter a candidate area and NEVER go directly to the formal
    vocabulary. The user must explicitly act: accept, modify+accept, map,
    use once, or ignore.

    No real AI calls — this manager only processes already-structured
    suggestion data.
    """

    def __init__(self, store: VocabularyStore):
        self._store = store
        self._candidates: dict[str, VocabularyCandidate] = {}
        self._status: dict[str, SuggestionStatus] = {}
        self._mapped_to: dict[str, str] = {}  # candidate_id → existing_entry_id

    def snapshot(self) -> tuple[dict, dict, dict]:
        """Capture decision state so a surrounding persistence transaction can roll back."""
        return (
            dict(self._candidates),
            dict(self._status),
            dict(self._mapped_to),
        )

    def restore_snapshot(self, snapshot: tuple[dict, dict, dict]) -> None:
        """Restore a decision snapshot after a failed durable save."""
        candidates, status, mapped_to = snapshot
        self._candidates = dict(candidates)
        self._status = dict(status)
        self._mapped_to = dict(mapped_to)

    # ── Add suggestion ────────────────────────────────────────────────────

    def add_suggestion(self, candidate: VocabularyCandidate) -> VocabularyCandidate:
        """Add an AI suggestion to the candidate area."""
        self._candidates[candidate.id] = candidate
        self._status[candidate.id] = SuggestionStatus.PENDING
        return candidate

    # ── Accept ────────────────────────────────────────────────────────────

    def accept(self, candidate_id: str) -> VocabularyEntry:
        """Accept a suggestion: creates a formal entry with source=AI_SUGGESTION."""
        candidate = self._get_pending(candidate_id)
        entry = VocabularyEntry(
            category=candidate.category,
            concept_id=candidate.concept_id,
            display_name=candidate.display_name,
            locale=candidate.locale,
            source=VocabularySource.AI_SUGGESTION,
            confidence=candidate.confidence,
            created_by_model=candidate.source_model,
        )
        self._store.add_entry(entry)
        self._status[candidate_id] = SuggestionStatus.ACCEPTED
        return entry

    # ── Modify then accept ────────────────────────────────────────────────

    def modify_and_accept(self, candidate_id: str, new_display_name: str) -> VocabularyEntry:
        """Modify the display_name of a suggestion, then accept it."""
        if not new_display_name or not new_display_name.strip():
            raise ValueError("display_name must not be empty")
        candidate = self._get_pending(candidate_id)
        entry = VocabularyEntry(
            category=candidate.category,
            concept_id=candidate.concept_id,
            display_name=new_display_name,
            locale=candidate.locale,
            source=VocabularySource.AI_SUGGESTION,
            confidence=candidate.confidence,
            created_by_model=candidate.source_model,
        )
        self._store.add_entry(entry)
        self._status[candidate_id] = SuggestionStatus.MODIFIED_ACCEPTED
        return entry

    # ── Map to existing ───────────────────────────────────────────────────

    def map_to_existing(self, candidate_id: str, existing_entry_id: str) -> None:
        """Map a suggestion to an existing vocabulary entry (no new entry created)."""
        _ = self._get_pending(candidate_id)  # validate candidate exists
        if existing_entry_id not in self._store._entries:
            raise KeyError(
                f"Existing vocabulary entry not found: {existing_entry_id}"
            )
        self._status[candidate_id] = SuggestionStatus.MAPPED
        self._mapped_to[candidate_id] = existing_entry_id

    # ── Use once ──────────────────────────────────────────────────────────

    def use_once(self, candidate_id: str) -> VocabularyEntry:
        """Return a temporary entry for one-time use.

        Does NOT add to formal vocabulary. Does NOT change version.
        The candidate remains available for future decisions.
        """
        candidate = self._get_pending(candidate_id)
        return VocabularyEntry(
            category=candidate.category,
            concept_id=candidate.concept_id,
            display_name=candidate.display_name,
            locale=candidate.locale,
            source=VocabularySource.AI_SUGGESTION,
            confidence=candidate.confidence,
            created_by_model=candidate.source_model,
        )

    # ── Ignore ────────────────────────────────────────────────────────────

    def ignore(self, candidate_id: str) -> None:
        """Ignore/discard a suggestion."""
        _ = self._get_pending(candidate_id)
        self._status[candidate_id] = SuggestionStatus.IGNORED

    # ── List candidates ───────────────────────────────────────────────────

    def list_candidates(
        self,
        category: Optional[VocabularyCategory] = None,
        locale: Optional[str] = None,
    ) -> list[VocabularyCandidate]:
        """List pending candidates, optionally filtered by category and/or locale."""
        results = []
        for cid, candidate in self._candidates.items():
            if self._status.get(cid) != SuggestionStatus.PENDING:
                continue
            if category is not None and candidate.category != category:
                continue
            if locale is not None and candidate.locale != locale:
                continue
            results.append(candidate)
        return results

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_pending(self, candidate_id: str) -> VocabularyCandidate:
        """Get a pending candidate, raising on missing or already processed."""
        if candidate_id not in self._candidates:
            raise KeyError(f"Candidate not found: {candidate_id}")
        status = self._status.get(candidate_id)
        if status != SuggestionStatus.PENDING:
            raise ValueError(
                f"Candidate {candidate_id} already processed: {status.value}"
            )
        return self._candidates[candidate_id]

    # ── Auto-Create (opt-in) ──────────────────────────────────────────────

    def set_auto_create_config(self, config: "AutoCreateConfig") -> None:
        self._auto_config = config

    @property
    def auto_create_config(self) -> "AutoCreateConfig":
        if not hasattr(self, "_auto_config"):
            self._auto_config = AutoCreateConfig()
        return self._auto_config

    def try_auto_create(self, candidate: VocabularyCandidate) -> bool:
        """Try to auto-create a formal entry from a candidate.

        Returns True if the entry was created, False otherwise (fail-closed).

        Requirements:
          - auto_create must be enabled
          - confidence >= threshold
          - must not duplicate existing concept_id+locale in store
          - must pass rate limiting
        """
        config = self.auto_create_config
        reason = ""

        # Check enabled
        if not config.enabled:
            reason = "Auto-create is disabled"
            self._record_audit(candidate, False, reason)
            return False

        # Check confidence
        if candidate.confidence < config.confidence_threshold:
            reason = (
                f"Confidence {candidate.confidence} below threshold "
                f"{config.confidence_threshold}"
            )
            self._record_audit(candidate, False, reason)
            return False

        # Dedup: check store for same concept_id + locale
        store_key = (candidate.concept_id, candidate.locale)
        if store_key in self._store._concept_locale_index:
            reason = (
                f"Duplicate concept_id={candidate.concept_id!r}, "
                f"locale={candidate.locale!r}"
            )
            self._record_audit(candidate, False, reason)
            return False

        # Rate limiting
        now = _time.monotonic()
        if not hasattr(self, "_auto_create_timestamps"):
            self._auto_create_timestamps: list[float] = []
        # Prune old timestamps
        window = config.rate_limit_window_seconds
        self._auto_create_timestamps = [
            ts for ts in self._auto_create_timestamps
            if now - ts < window
        ]
        if len(self._auto_create_timestamps) >= config.max_per_window:
            reason = (
                f"Rate limit: {len(self._auto_create_timestamps)}/"
                f"{config.max_per_window} in {window}s window"
            )
            self._record_audit(candidate, False, reason)
            return False

        # All checks passed — create entry
        entry = VocabularyEntry(
            category=candidate.category,
            concept_id=candidate.concept_id,
            display_name=candidate.display_name,
            locale=candidate.locale,
            source=VocabularySource.AI_AUTO,
            confidence=candidate.confidence,
            created_by_model=candidate.source_model,
        )
        self._store.add_entry(entry)
        self._auto_create_timestamps.append(now)
        self._record_audit(candidate, True, "")
        return True

    # ── Audit log ─────────────────────────────────────────────────────────

    def get_audit_log(self) -> list["AutoCreateAuditEntry"]:
        if not hasattr(self, "_audit_log"):
            self._audit_log: list[AutoCreateAuditEntry] = []
        return list(self._audit_log)

    def _record_audit(
        self, candidate: VocabularyCandidate, success: bool, reason: str,
    ) -> None:
        if not hasattr(self, "_audit_log"):
            self._audit_log: list[AutoCreateAuditEntry] = []
        self._audit_log.append(AutoCreateAuditEntry(
            candidate_id=candidate.id,
            concept_id=candidate.concept_id,
            success=success,
            reason=reason,
            confidence=candidate.confidence,
            source_model=candidate.source_model,
            task_id=candidate.task_id,
            category=candidate.category.value,
            locale=candidate.locale,
        ))


# ── Auto-Create Config & Audit ───────────────────────────────────────────────

@dataclass
class AutoCreateConfig:
    """Configuration for opt-in auto-create vocabulary.

    Default: disabled. Must be explicitly enabled by the user.
    Watch Auto Apply scenarios must keep this disabled.
    """
    enabled: bool = False
    confidence_threshold: float = 0.9
    rate_limit_window_seconds: float = 60.0
    max_per_window: int = 5

    def __post_init__(self):
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold must be 0.0-1.0, got {self.confidence_threshold}"
            )
        if self.max_per_window < 1:
            raise ValueError(
                f"max_per_window must be >= 1, got {self.max_per_window}"
            )
        if self.rate_limit_window_seconds <= 0:
            raise ValueError(
                f"rate_limit_window_seconds must be > 0, got {self.rate_limit_window_seconds}"
            )


@dataclass(frozen=True)
class AutoCreateAuditEntry:
    """Immutable audit record for an auto-create attempt."""
    candidate_id: str
    concept_id: str
    success: bool
    reason: str
    confidence: float
    source_model: str
    task_id: str
    category: str
    locale: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
