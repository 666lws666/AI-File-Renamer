"""Persistent Review First queue — versioned, atomic, fail-closed.

Items persist across restarts so unfinished reviews survive.  A corrupted
queue file raises ``ReviewQueueError`` (fail-closed): the handler must never
auto-apply from unreadable state.  Only metadata is stored — never file
content, prompts, or secrets.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
from uuid import uuid4
from src.core.rename_plan import validate_owned_residue_paths, RECOVERY_REASONS
from src.core.managed_watch_metadata import (
    ManagedWatchMetadata, encode_managed_metadata, decode_managed_metadata,
)


class ReviewItemState(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    APPLIED = "applied"
    UNDONE = "undone"
    IGNORED = "ignored"
    FAILED = "failed"
    CANCELLED = "cancelled"  # stale (fingerprint changed) or cancelled


# States that occupy a queue slot for a path (dedupe keys).
ACTIVE_STATES = frozenset({
    ReviewItemState.PENDING,
    ReviewItemState.ANALYZING,
    ReviewItemState.AWAITING_APPROVAL,
    ReviewItemState.APPLYING,
})


class ReviewQueueError(RuntimeError):
    """Raised when the queue store is corrupted or unwritable (fail-closed)."""


@dataclass(frozen=True)
class WatchFileOperationIntent:
    """Durable metadata only; never authority to replay a file operation."""

    version: int
    operation_id: str
    kind: str
    batch_id: str
    source_path: str
    target_path: str
    known_result_path: str = ''
    owned_residue_paths: tuple[str, ...] = ()
    recovery_reason: str = ''


def _intent_string(value, maximum):
    return (type(value) is str and bool(value.strip()) and len(value) <= maximum
            and "\x00" not in value)


def _encode_intent(intent):
    if (type(intent) is not WatchFileOperationIntent
            or type(intent.version) is not int or intent.version not in (1, 2)
            or type(intent.kind) is not str or intent.kind not in {"apply", "undo"}
            or not _intent_string(intent.operation_id, 256)
            or not _intent_string(intent.batch_id, 256)
            or not _intent_string(intent.source_path, 4096)
            or not _intent_string(intent.target_path, 4096)):
        raise ValueError()
    validate_owned_residue_paths(intent.owned_residue_paths)
    if (type(intent.known_result_path) is not str or len(intent.known_result_path) > 4096
            or '\x00' in intent.known_result_path or type(intent.recovery_reason) is not str):
        raise ValueError()
    graph = {name: getattr(intent, name) for name in (
        "version", "operation_id", "kind", "batch_id", "source_path", "target_path")}
    if intent.version == 1:
        if intent.known_result_path or intent.owned_residue_paths or intent.recovery_reason:
            raise ValueError()
    else:
        if intent.recovery_reason not in RECOVERY_REASONS: raise ValueError()
        paths = tuple(dict.fromkeys((*intent.owned_residue_paths,
            *((intent.known_result_path,) if intent.known_result_path else ()))))
        validate_owned_residue_paths(paths)
        graph.update(known_result_path=intent.known_result_path,
                     owned_residue_paths=list(intent.owned_residue_paths),
                     recovery_reason=intent.recovery_reason)
    return graph


def _decode_intent(record):
    keys = {'version', 'operation_id', 'kind', 'batch_id', 'source_path', 'target_path'}
    if type(record) is not dict or type(record.get('version')) is not int:
        raise ValueError()
    values = dict(record)
    if record['version'] == 2:
        keys |= {'known_result_path', 'owned_residue_paths', 'recovery_reason'}
        if type(record.get('owned_residue_paths')) is not list: raise ValueError()
        values['owned_residue_paths'] = tuple(record['owned_residue_paths'])
    if record.keys() != keys: raise ValueError()
    intent = WatchFileOperationIntent(**values)
    _encode_intent(intent)
    return intent


@dataclass(frozen=True)
class ReviewItem:
    """One reviewable file candidate.  Immutable — state changes rebuild."""

    id: str
    watch_id: str
    source_path: str
    size_bytes: int
    mtime_ns: int
    extension: str
    display_name: str
    state: ReviewItemState
    suggested_name: str = ""
    target_parent: str = ""
    confidence: float | None = 0.0
    content_kind: str = "text"
    error_category: str = ""
    batch_id: str = ""
    created_at_utc: str = ""
    updated_at_utc: str = ""
    managed_metadata: ManagedWatchMetadata | None = None
    file_operation: WatchFileOperationIntent | None = None
    applied_path: str = ""
    recovery_required: bool = False

    def with_state(self, state: ReviewItemState, **kw) -> "ReviewItem":
        """Return a copy with a new state (and optional field updates)."""
        return replace(self, state=state, **kw)

    def fingerprint(self) -> tuple[int, int]:
        return (self.size_bytes, self.mtime_ns)


_QUEUE_SCHEMA_VERSION = 3
_ITEM_STRING_FIELDS = (
    "id", "watch_id", "source_path", "extension", "display_name", "suggested_name",
    "target_parent", "content_kind", "error_category", "batch_id", "created_at_utc",
    "updated_at_utc", "applied_path",
)


def _encode_item(item: ReviewItem) -> dict:
    """Explicit store fields; managed coverage is owned exclusively by its codec."""
    if type(item) is not ReviewItem:
        raise ValueError()
    record = {name: getattr(item, name) for name in _ITEM_STRING_FIELDS}
    if (any(type(value) is not str for value in record.values())
            or any(not record[name] for name in ("id", "watch_id", "source_path"))
            or type(item.state) is not ReviewItemState
            or type(item.recovery_required) is not bool
            or len(item.applied_path) > 4096 or "\x00" in item.applied_path
            or any(type(value) is not int or value < 0
                   for value in (item.size_bytes, item.mtime_ns))):
        raise ValueError()
    confidence = item.confidence
    if confidence is not None and (type(confidence) not in (int, float)
            or not 0 <= confidence <= 1 or not math.isfinite(confidence)):
        raise ValueError()
    metadata = item.managed_metadata
    if metadata is not None:
        metadata = encode_managed_metadata(metadata)
        if confidence is not None or item.content_kind != metadata["content_kind"]:
            raise ValueError()
    record.update(size_bytes=item.size_bytes, mtime_ns=item.mtime_ns,
                  state=item.state.value, confidence=confidence, managed_metadata=metadata,
                  file_operation=None if item.file_operation is None else _encode_intent(item.file_operation),
                  recovery_required=item.recovery_required)
    return record


class ReviewQueue:
    """Thread-safe persistent queue with atomic writes."""

    def __init__(
        self,
        file_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._file_path = Path(file_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._items: dict[str, ReviewItem] = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    def add(self, item: ReviewItem) -> ReviewItem:
        """Add an item (or replace by id).  Raises ReviewQueueError on
        storage problems — a failed save leaves memory AND disk unchanged."""
        try:
            if type(item) is ReviewItem and type(item.id) is str and item.id == "":
                item = replace(item, id=str(uuid4()))
            _encode_item(item)
        except (TypeError, ValueError, AttributeError) as error:
            raise ReviewQueueError("review queue write failed") from error
        if not item.created_at_utc:
            item = replace(item, created_at_utc=self._clock().isoformat())
        item = replace(item, updated_at_utc=self._clock().isoformat())
        with self._lock:
            candidate = dict(self._items)
            candidate[item.id] = item
            self._save_locked(candidate)   # persist FIRST — only then swap
            self._items = candidate
        return item

    def update(self, item: ReviewItem) -> ReviewItem:
        """Persist an updated item (must already exist)."""
        try:
            _encode_item(item)
        except (TypeError, ValueError, AttributeError) as error:
            raise ReviewQueueError("review queue write failed") from error
        item = replace(item, updated_at_utc=self._clock().isoformat())
        with self._lock:
            if item.id not in self._items:
                raise KeyError(f"Review item not found: {item.id}")
            candidate = dict(self._items)
            candidate[item.id] = item
            self._save_locked(candidate)   # persist FIRST — only then swap
            self._items = candidate
        return item

    def get(self, item_id: str) -> ReviewItem | None:
        with self._lock:
            return self._items.get(item_id)

    def replace_many(self, changes: tuple[tuple[ReviewItem, ReviewItem], ...]) -> tuple[ReviewItem, ...]:
        """Persist one complete candidate only if every expected identity is current.

        Clock callbacks are fallible/reentrant. Prepare timestamps before taking
        the non-reentrant store lock; compare current identities afterwards.
        """
        try:
            if type(changes) is not tuple or not changes:
                raise ValueError()
            ids = set()
            for pair in changes:
                if type(pair) is not tuple or len(pair) != 2:
                    raise ValueError()
                expected, replacement = pair
                _encode_item(expected)
                _encode_item(replacement)
                if expected.id != replacement.id or expected.id in ids:
                    raise ValueError()
                ids.add(expected.id)
            saved = tuple(replace(replacement, updated_at_utc=self._clock().isoformat())
                          for _, replacement in changes)
        except Exception as error:
            raise ReviewQueueError("review queue write failed") from error
        with self._lock:
            if any(self._items.get(expected.id) is not expected for expected, _ in changes):
                raise ReviewQueueError("review queue conflict")
            candidate = dict(self._items)
            candidate.update((item.id, item) for item in saved)
            self._save_locked(candidate)
            self._items = candidate
        return saved

    def items(
        self,
        watch_id: str | None = None,
        states: frozenset[ReviewItemState] | None = None,
    ) -> list[ReviewItem]:
        with self._lock:
            result = list(self._items.values())
        if watch_id is not None:
            result = [i for i in result if i.watch_id == watch_id]
        if states is not None:
            result = [i for i in result if i.state in states]
        return sorted(result, key=lambda i: i.created_at_utc)

    def active_for_path(self, watch_id: str, source_path: str) -> ReviewItem | None:
        """The ACTIVE item for a (watch, path) pair — used for dedupe."""
        with self._lock:
            for item in self._items.values():
                if item.watch_id == watch_id and item.source_path == source_path:
                    if item.state in ACTIVE_STATES:
                        return item
        return None

    def remove(self, item_id: str) -> None:
        with self._lock:
            if item_id not in self._items:
                raise KeyError(f"Review item not found: {item_id}")
            candidate = dict(self._items)
            del candidate[item_id]
            self._save_locked(candidate)   # persist FIRST — only then swap
            self._items = candidate

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    # ── Internal: persistence ─────────────────────────────────────────────

    def _save_locked(self, items: dict[str, ReviewItem]) -> None:
        tmp: Path | None = None
        try:
            data = {
                "schema_version": _QUEUE_SCHEMA_VERSION,
                "items": [_encode_item(i) for i in items.values()],
            }
            json_text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True,
                                   allow_nan=False)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix="review_queue_",
                dir=str(self._file_path.parent),
            )
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
            raise ReviewQueueError("review queue write failed") from error

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = self._file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (ValueError, OSError, UnicodeError) as error:
            raise ReviewQueueError("review queue corrupted or unreadable") from error

        items: dict[str, ReviewItem] = {}
        try:
            if (type(data) is not dict or type(data.get("schema_version")) is not int
                    or data["schema_version"] not in (1, 2, 3)
                    or type(data.get("items")) is not list):
                raise ValueError()
            for entry in data["items"]:
                if type(entry) is not dict or (data["schema_version"] == 1
                        and "managed_metadata" in entry):
                    raise ValueError()
                new_fields = {"file_operation", "applied_path", "recovery_required"}
                if data["schema_version"] < 3 and new_fields.intersection(entry):
                    raise ValueError()
                if data["schema_version"] == 3 and not new_fields.issubset(entry):
                    raise ValueError()
                metadata = entry.get("managed_metadata")
                if metadata is not None:
                    metadata = decode_managed_metadata(metadata)
                item = ReviewItem(
                    id=entry["id"], watch_id=entry["watch_id"], source_path=entry["source_path"],
                    size_bytes=entry["size_bytes"], mtime_ns=entry["mtime_ns"],
                    state=ReviewItemState(entry["state"]),
                    confidence=entry.get("confidence", 0.0), managed_metadata=metadata,
                    file_operation=(_decode_intent(entry["file_operation"])
                        if entry.get("file_operation") is not None else None),
                    recovery_required=entry.get("recovery_required", False),
                    **{name: entry.get(name, "text" if name == "content_kind" else "")
                       for name in _ITEM_STRING_FIELDS if name not in ("id", "watch_id", "source_path")},
                )
                _encode_item(item)
                if item.id in items:
                    raise ValueError()
                items[item.id] = item
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ReviewQueueError("review queue corrupted or unreadable") from error
        self._items = items
