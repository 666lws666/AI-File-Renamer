"""M4 Controlled Vocabulary domain model — 5 categories, stable concept IDs, locale display."""

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


# ── Enums ────────────────────────────────────────────────────────────────────

class VocabularyCategory(str, Enum):
    SUBJECT = "subject"
    ORGANIZATION = "organization"
    PROJECT = "project"
    STATUS = "status"
    TYPE = "type"


class VocabularySource(str, Enum):
    SYSTEM = "system"
    USER = "user"
    AI_SUGGESTION = "ai_suggestion"
    AI_AUTO = "ai_auto"


# ── Errors ───────────────────────────────────────────────────────────────────

class VocabularyIntegrityError(Exception):
    """Raised when vocabulary data fails integrity checks."""
    pass


# ── VocabularyEntry ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VocabularyEntry:
    """A single controlled vocabulary entry. Immutable."""

    category: VocabularyCategory
    concept_id: str
    display_name: str
    locale: str
    source: VocabularySource
    confidence: float = 1.0
    created_by_model: str = ""
    id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        # Validate category
        if not isinstance(self.category, VocabularyCategory):
            raise ValueError(
                f"Invalid category: {self.category!r}. Must be a VocabularyCategory enum value."
            )

        # Validate source
        if not isinstance(self.source, VocabularySource):
            raise ValueError(
                f"Invalid source: {self.source!r}. Must be a VocabularySource enum value."
            )

        # Validate concept_id
        if not self.concept_id or not self.concept_id.strip():
            raise ValueError("VocabularyEntry.concept_id must not be empty")

        # Validate locale
        if not self.locale or not self.locale.strip():
            raise ValueError("VocabularyEntry.locale must not be empty")

        # Validate display_name
        if not self.display_name or not self.display_name.strip():
            raise ValueError("VocabularyEntry.display_name must not be empty")

        # Auto-generate ID
        if not self.id:
            object.__setattr__(self, "id", str(uuid4()))

        # Auto-set created_at if not provided
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc))


# ── VocabularyStore ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VocabularySnapshot:
    """Immutable rollback point for a complete in-memory vocabulary state."""

    entries: tuple[VocabularyEntry, ...]
    overrides: tuple[tuple[str, str], ...]
    tombstones: frozenset[str]
    version: int


class VocabularyStore:
    """Pure in-memory vocabulary store with locale-aware lookups.

    No AI calls, no network, no QML. Default behavior excludes AI-sourced
    entries from formal vocabulary (candidate flow handled in Task 9).

    Supports user overrides and tombstones for system preset entries:
      - override_entry(): edit a preset's display_name without mutating the original
      - tombstone_entry(): hide a preset without physically deleting it
      - restore_entry(): restore a single entry to its preset value
      - restore_category(): restore all overrides/tombstones in a category
    """

    def __init__(self):
        self._entries: dict[str, VocabularyEntry] = {}
        # Fast lookup index: (concept_id, locale) → entry_id
        self._concept_locale_index: dict[tuple[str, str], str] = {}
        # User overrides: entry_id → new display_name
        self._overrides: dict[str, str] = {}
        # Tombstones: entry_ids that have been soft-deleted
        self._tombstones: set[str] = set()
        # Monotonic version, increments on every mutation
        self._version: int = 0

    # ── Version ───────────────────────────────────────────────────────────

    @property
    def vocabulary_version(self) -> int:
        return self._version

    def _bump_version(self) -> None:
        self._version += 1

    def snapshot(self) -> VocabularySnapshot:
        """Return a complete rollback point without exposing mutable aliases."""
        return VocabularySnapshot(
            entries=tuple(self._entries.values()),
            overrides=tuple(sorted(self._overrides.items())),
            tombstones=frozenset(self._tombstones),
            version=self._version,
        )

    def restore_snapshot(self, snapshot: VocabularySnapshot) -> None:
        """Atomically restore a previously captured in-memory state."""
        entries = {entry.id: entry for entry in snapshot.entries}
        index: dict[tuple[str, str], str] = {}
        for entry in snapshot.entries:
            key = (entry.concept_id, entry.locale)
            if key in index:
                raise VocabularyIntegrityError(
                    f"Duplicate snapshot entry: concept_id={entry.concept_id!r}, locale={entry.locale!r}"
                )
            index[key] = entry.id
        self._entries = entries
        self._concept_locale_index = index
        self._overrides = dict(snapshot.overrides)
        self._tombstones = set(snapshot.tombstones)
        self._version = snapshot.version

    def get_entry(self, entry_id: str) -> VocabularyEntry:
        """Return the original entry by stable ID."""
        try:
            return self._entries[entry_id]
        except KeyError as exc:
            raise KeyError(f"Vocabulary entry not found: {entry_id}") from exc

    # ── Core CRUD ─────────────────────────────────────────────────────────

    def add_entry(self, entry: VocabularyEntry) -> VocabularyEntry:
        """Add a vocabulary entry. Rejects duplicate concept_id+locale pairs."""
        key = (entry.concept_id, entry.locale)
        if key in self._concept_locale_index:
            raise VocabularyIntegrityError(
                f"Duplicate entry: concept_id={entry.concept_id!r}, "
                f"locale={entry.locale!r}"
            )
        self._entries[entry.id] = entry
        self._concept_locale_index[key] = entry.id
        self._bump_version()
        return entry

    def remove_entry(self, entry_id: str) -> None:
        """Remove an entry by ID. Raises KeyError if not found."""
        if entry_id not in self._entries:
            raise KeyError(f"Vocabulary entry not found: {entry_id}")
        entry = self._entries.pop(entry_id)
        key = (entry.concept_id, entry.locale)
        self._concept_locale_index.pop(key, None)
        # Clean up any override or tombstone for this entry
        self._overrides.pop(entry_id, None)
        self._tombstones.discard(entry_id)
        self._bump_version()

    # ── Override ──────────────────────────────────────────────────────────

    def override_entry(self, entry_id: str, display_name: str) -> None:
        """Override the display_name of a system preset entry.

        Does not mutate the original entry — stores an override layer.
        Only allowed for entries with source=SYSTEM.

        Raises:
            KeyError: If entry_id is not found.
            VocabularyIntegrityError: If the entry is not a system preset.
        """
        if entry_id not in self._entries:
            raise KeyError(f"Vocabulary entry not found: {entry_id}")
        entry = self._entries[entry_id]
        if entry.source != VocabularySource.SYSTEM:
            raise VocabularyIntegrityError(
                f"Cannot override non-system entry: {entry_id} (source={entry.source.value})"
            )
        if not display_name or not display_name.strip():
            raise ValueError("display_name must not be empty")
        self._overrides[entry_id] = display_name
        self._bump_version()

    # ── Tombstone ─────────────────────────────────────────────────────────

    def tombstone_entry(self, entry_id: str) -> None:
        """Soft-delete a system preset entry by marking it as a tombstone.

        The entry is hidden from queries but not physically removed.
        Only allowed for entries with source=SYSTEM.

        Raises:
            KeyError: If entry_id is not found.
            VocabularyIntegrityError: If the entry is not a system preset.
        """
        if entry_id not in self._entries:
            raise KeyError(f"Vocabulary entry not found: {entry_id}")
        entry = self._entries[entry_id]
        if entry.source != VocabularySource.SYSTEM:
            raise VocabularyIntegrityError(
                f"Cannot tombstone non-system entry: {entry_id} (source={entry.source.value})"
            )
        self._tombstones.add(entry_id)
        self._bump_version()

    # ── Restore ───────────────────────────────────────────────────────────

    def restore_entry(self, entry_id: str) -> None:
        """Restore a single entry by removing its override and/or tombstone.

        Raises:
            KeyError: If entry_id is not in overrides or tombstones.
        """
        if entry_id not in self._overrides and entry_id not in self._tombstones:
            raise KeyError(
                f"No override or tombstone found for entry: {entry_id}"
            )
        self._overrides.pop(entry_id, None)
        self._tombstones.discard(entry_id)
        self._bump_version()

    def restore_category(self, category: VocabularyCategory) -> int:
        """Restore all overrides and tombstones for entries in a category.

        Returns the number of entries restored.
        """
        count = 0
        for entry in self._entries.values():
            if entry.category != category:
                continue
            eid = entry.id
            if eid in self._overrides or eid in self._tombstones:
                self._overrides.pop(eid, None)
                self._tombstones.discard(eid)
                count += 1
        if count > 0:
            self._bump_version()
        return count

    # ── Queries ───────────────────────────────────────────────────────────

    def get_entries(
        self,
        category: VocabularyCategory,
        locale: str,
        include_ai_suggestions: bool = False,
    ) -> list[VocabularyEntry]:
        """Get all entries for a category and locale.

        Tombsoned entries are excluded. Overridden entries show their
        user-specified display_name.
        """
        results = []
        for entry in self._entries.values():
            if entry.category != category:
                continue
            if entry.locale != locale:
                continue
            if entry.id in self._tombstones:
                continue
            if not include_ai_suggestions and entry.source in (
                VocabularySource.AI_SUGGESTION,
                VocabularySource.AI_AUTO,
            ):
                continue
            # Apply override if present
            if entry.id in self._overrides:
                results.append(VocabularyEntry(
                    id=entry.id,
                    category=entry.category,
                    concept_id=entry.concept_id,
                    display_name=self._overrides[entry.id],
                    locale=entry.locale,
                    source=entry.source,
                    confidence=entry.confidence,
                    created_by_model=entry.created_by_model,
                    created_at=entry.created_at,
                ))
            else:
                results.append(entry)
        return results

    def list_all(self) -> list[VocabularyEntry]:
        """Return all entries, excluding tombstoned, applying overrides."""
        results = []
        for entry in self._entries.values():
            if entry.id in self._tombstones:
                continue
            if entry.id in self._overrides:
                results.append(VocabularyEntry(
                    id=entry.id,
                    category=entry.category,
                    concept_id=entry.concept_id,
                    display_name=self._overrides[entry.id],
                    locale=entry.locale,
                    source=entry.source,
                    confidence=entry.confidence,
                    created_by_model=entry.created_by_model,
                    created_at=entry.created_at,
                ))
            else:
                results.append(entry)
        return results

    # ── State persistence ─────────────────────────────────────────────────

    @staticmethod
    def _entry_to_json(entry: VocabularyEntry) -> dict[str, object]:
        return {
            "id": entry.id,
            "category": entry.category.value,
            "concept_id": entry.concept_id,
            "display_name": entry.display_name,
            "locale": entry.locale,
            "source": entry.source.value,
            "confidence": entry.confidence,
            "created_by_model": entry.created_by_model,
            "created_at": entry.created_at.isoformat(),
        }

    @staticmethod
    def _entry_from_json(raw: object) -> VocabularyEntry:
        if not isinstance(raw, dict):
            raise VocabularyIntegrityError("Persisted vocabulary entry must be an object")
        try:
            created_at = datetime.fromisoformat(str(raw["created_at"]))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            return VocabularyEntry(
                id=str(raw["id"]),
                category=VocabularyCategory(str(raw["category"])),
                concept_id=str(raw["concept_id"]),
                display_name=str(raw["display_name"]),
                locale=str(raw["locale"]),
                source=VocabularySource(str(raw["source"])),
                confidence=float(raw.get("confidence", 1.0)),
                created_by_model=str(raw.get("created_by_model", "")),
                created_at=created_at.astimezone(timezone.utc),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VocabularyIntegrityError(f"Invalid persisted vocabulary entry: {exc}") from exc

    def save_state(self, file_path) -> None:
        """Atomically persist overrides, tombstones, and non-system entries."""
        import os
        import tempfile
        from pathlib import Path

        file_p = Path(file_path)
        data = {
            "schema_version": 2,
            "vocabulary_version": self._version,
            "entries": [
                self._entry_to_json(entry)
                for entry in sorted(self._entries.values(), key=lambda item: item.id)
                if entry.source != VocabularySource.SYSTEM
            ],
            "overrides": dict(self._overrides),
            "tombstones": sorted(self._tombstones),
        }
        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = None
        try:
            file_p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="vocab_state_", dir=str(file_p.parent),
            )
            tmp = Path(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_text)
            os.replace(tmp_path, str(file_p))
        except Exception:
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    def load_state(self, file_path) -> None:
        """Load persisted state transactionally; malformed data changes nothing."""
        from pathlib import Path

        file_p = Path(file_path)
        if not file_p.exists():
            return
        try:
            data = json.loads(file_p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VocabularyIntegrityError(f"Invalid vocabulary state: {exc}") from exc
        if not isinstance(data, dict):
            raise VocabularyIntegrityError("Vocabulary state must be a JSON object")

        raw_entries = data.get("entries", [])
        raw_overrides = data.get("overrides", {})
        raw_tombstones = data.get("tombstones", [])
        persisted_version = data.get("vocabulary_version", 0)
        if not isinstance(raw_entries, list):
            raise VocabularyIntegrityError("Vocabulary state entries must be a list")
        if not isinstance(raw_overrides, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_overrides.items()
        ):
            raise VocabularyIntegrityError("Vocabulary state overrides must map strings to strings")
        if not isinstance(raw_tombstones, list) or not all(
            isinstance(item, str) for item in raw_tombstones
        ):
            raise VocabularyIntegrityError("Vocabulary state tombstones must be a list of strings")
        if not isinstance(persisted_version, int) or persisted_version < 0:
            raise VocabularyIntegrityError("Vocabulary version must be a non-negative integer")

        candidate_entries = dict(self._entries)
        candidate_index = dict(self._concept_locale_index)
        for raw in raw_entries:
            entry = self._entry_from_json(raw)
            if entry.source == VocabularySource.SYSTEM:
                raise VocabularyIntegrityError("System presets cannot be loaded from user state")
            key = (entry.concept_id, entry.locale)
            existing_id = candidate_index.get(key)
            if existing_id is not None and existing_id != entry.id:
                raise VocabularyIntegrityError(
                    f"Duplicate persisted entry: concept_id={entry.concept_id!r}, locale={entry.locale!r}"
                )
            if entry.id in candidate_entries and candidate_entries[entry.id] != entry:
                raise VocabularyIntegrityError(f"Duplicate persisted entry id: {entry.id}")
            candidate_entries[entry.id] = entry
            candidate_index[key] = entry.id

        # Swap only after every field and entry has passed validation.
        self._entries = candidate_entries
        self._concept_locale_index = candidate_index
        self._overrides = dict(raw_overrides)
        self._tombstones = set(raw_tombstones)
        self._version = max(self._version, persisted_version)

    # ── Semantic digest (stable cache context version) ─────────────────────

    def semantic_digest(self) -> str:
        """SHA-256 digest of the canonical SEMANTIC vocabulary content.

        Stability rules:
        - Identical semantic content across restarts/reloads → identical
          digest (it is a pure function of the content, never a process-local
          counter or random value).
        - Runtime-only fields (entry ids, created_at timestamps) are
          excluded — the same concept recreated with a new id hashes the same.
        - Tombstoned entries are hidden → excluded.
        - Unaccepted AI suggestions are candidates, NOT store entries → they
          never affect the digest.
        - Ordering/format differences are normalized (sorted rows, canonical
          JSON) → no digest change.
        """
        rows = []
        for entry in sorted(
            self._entries.values(),
            key=lambda e: (e.category.value, e.concept_id, e.locale),
        ):
            if entry.id in self._tombstones:
                continue
            rows.append({
                "category": entry.category.value,
                "concept_id": entry.concept_id,
                "locale": entry.locale,
                "display_name": self._overrides.get(entry.id, entry.display_name),
                "source": entry.source.value,
                "confidence": entry.confidence,
                "created_by_model": entry.created_by_model,
            })
        payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class VocabularyCacheContextContributor:
    """Stable semantic vocabulary version for the M3 CacheContext.

    CacheContext receives ONLY ``vocabulary_id`` and ``vocabulary_version``
    (a digest) — never the raw vocabulary text.  Any successful semantic
    change (add / edit / delete / restore / user override / accepted AI
    suggestion / auto-create / vocabulary undo-redo) changes the version, so
    stale AI cache entries naturally miss.
    """

    DEFAULT_VOCABULARY_ID = "controlled-vocabulary"

    def __init__(self, store: VocabularyStore, vocabulary_id: str = DEFAULT_VOCABULARY_ID):
        if not vocabulary_id or not vocabulary_id.strip():
            raise ValueError("vocabulary_id must not be empty")
        self._store = store
        self._vocabulary_id = vocabulary_id

    @property
    def vocabulary_id(self) -> str:
        return self._vocabulary_id

    @property
    def vocabulary_version(self) -> str:
        return self._store.semantic_digest()

    def apply_to(self, ctx) -> "object":
        """Return a copy of the CacheContext with the vocabulary dimensions
        filled in; every other dimension is preserved untouched."""
        from src.core.cache_manager import CacheContext

        return replace(ctx, vocabulary_id=self._vocabulary_id, vocabulary_version=self.vocabulary_version)
