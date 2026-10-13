"""Non-monetary AI usage recording — versioned, atomic, deterministic clock.

Safety invariants:
- NEVER records API keys, authorization headers, prompts, request/response
  bodies, extracted file content, full file paths, or filenames.
- NEVER records prices, currencies, fees, or monetary budgets.
- Token counts may be UNKNOWN (None) — they are never forged as real zeros.
- Storage is schema-versioned with atomic writes; corrupted files are
  fail-closed: reads AND writes raise ``UsageStorageError``.  Corrupt data
  is never masqueraded as a normal empty store.
- Concurrent writes are serialized by a lock; the clock is injectable so
  tests are fully deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4


# ── Content kinds (non-multimodal implementation only) ───────────────────────

class UsageContentKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    SCANNED_PDF = "scanned_pdf"
    VIDEO = "video"


_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".heic"})
_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"})


def content_kind_for_file_type(file_type: str) -> str:
    """Map a file type string to a UsageContentKind value."""
    ext = (file_type or "").strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext in _IMAGE_EXTENSIONS:
        return UsageContentKind.IMAGE.value
    if ext in _VIDEO_EXTENSIONS:
        return UsageContentKind.VIDEO.value
    if ext == ".pdf":
        return UsageContentKind.SCANNED_PDF.value
    return UsageContentKind.TEXT.value


def error_category_for(error: BaseException) -> str:
    """A stable, short error category — the message NEVER enters storage."""
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    if isinstance(error, TimeoutError) or "timeout" in name or "timeout" in message:
        return "timeout"
    if "rate" in name or "rate limit" in message or "429" in message:
        return "rate_limit"
    if ("auth" in name or "unauthorized" in name or "permission" in name
            or "unauthorized" in message or "auth" in message
            or "401" in message or "403" in message or "permission denied" in message):
        return "auth"
    if any(k in name for k in ("json", "parse", "decode", "value")):
        return "parse"
    if ("capability" in name or "unsupported" in name
            or "capability" in message or "unsupported" in message or "not supported" in message):
        return "capability_unsupported"
    return "unknown"


# ── Errors ───────────────────────────────────────────────────────────────────

class UsageStorageError(RuntimeError):
    """Raised when usage storage is corrupted or cannot be written atomically.

    Fail-closed: callers must treat the store as unavailable, never as empty.
    """


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UsageRecord:
    """One non-monetary usage record.

    ``input_tokens`` / ``output_tokens`` are ``None`` when the provider did
    not report usage — never forged as 0.
    """

    provider_id: str
    profile_id: str
    model: str
    content_kind: str
    request_count: int
    cache_hit: bool
    success: bool
    error_category: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    operation_id: str = ""
    id: str = ""
    timestamp_utc: str = ""  # ISO-8601 UTC; recorder stamps it when empty

    def __post_init__(self) -> None:
        if self.request_count < 1:
            raise ValueError("request_count must be >= 1")
        for field in ("input_tokens", "output_tokens"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValueError(f"{field} must be >= 0 or None (unknown)")


@dataclass(frozen=True)
class TokenUsage:
    """Token total with an explicit known/unknown state.

    unknown means at least one contributing record had no token data — the
    UI renders a dash, never a fabricated zero.  The partial sum of the
    known records is still accumulated while unknown.
    """

    known: bool
    value: int = 0

    @classmethod
    def merge(cls, values: Sequence[int | None]) -> "TokenUsage":
        known_values = [v for v in values if v is not None]
        return cls(
            known=len(known_values) == len(values),
            value=sum(known_values),
        )

    def accumulate(self, value: int | None) -> "TokenUsage":
        """Fold one record's value into this aggregate.

        The known/unknown state is tracked SEPARATELY from the partial sum:
        once unknown, the aggregate stays unknown forever, while every known
        value keeps adding to the partial total.  This is order-independent.
        """
        return TokenUsage(
            known=self.known and value is not None,
            value=self.value + (value if value is not None else 0),
        )


@dataclass(frozen=True)
class UsageAggregate:
    """Aggregated non-monetary usage over a UTC time window."""

    provider_id: str = ""
    model: str = ""
    content_kind: str = ""
    request_count: int = 0
    network_request_count: int = 0
    cache_hit_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    input_tokens: TokenUsage = TokenUsage(known=True, value=0)
    output_tokens: TokenUsage = TokenUsage(known=True, value=0)


# ── UTC window helpers ───────────────────────────────────────────────────────

def utc_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) UTC bounds of one calendar day."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def utc_month_bounds(month: date) -> tuple[datetime, datetime]:
    """[start, end) UTC bounds of one calendar month."""
    start = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
    if month.month == 12:
        end = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _as_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize to UTC.

    Naive timestamps are interpreted as UTC; offset timestamps are
    converted.  Raises ``ValueError`` for unparseable values.
    """
    parsed = _parse_timestamp(value)
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    """Single parse entry point for ALL timestamp handling (record, load,
    aggregation).  Rejects blank and date-only values — every timestamp
    must carry a time component."""
    if not value or not value.strip():
        raise ValueError("timestamp_utc must not be blank")
    if "T" not in value:
        raise ValueError(f"timestamp_utc must include a time component: {value!r}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # naive → UTC
    return parsed


def normalize_timestamp_utc(value: str, clock: Callable[[], datetime] | None = None) -> str:
    """Normalize a caller-provided timestamp to canonical UTC ISO-8601.

    Blank values use the (injectable) clock; naive values are interpreted
    as UTC; offset values are converted to UTC.  Unparseable or date-only
    values raise ``ValueError`` with NO side effects.  The result always
    carries an explicit ``+00:00`` offset and is what gets persisted.
    """
    if not value:  # truly empty → stamp from the clock
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc).isoformat()
    if not value.strip():  # blank-but-not-empty → reject, zero side effects
        raise ValueError("timestamp_utc must not be blank")
    return _as_utc(value).isoformat()


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate_usage(
    records: Sequence[UsageRecord],
    *,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    group_by: Sequence[str] = ("provider",),
) -> list[UsageAggregate]:
    """Aggregate records by the given dimensions (provider/model/content_kind).

    Time boundaries are exclusive of ``end_utc`` (UTC).  Cache hits are
    counted separately from real network requests.
    """
    allowed = {"provider", "model", "content_kind"}
    keys = tuple(k for k in group_by if k in allowed)

    buckets: dict[tuple, UsageAggregate] = {}
    for rec in records:
        stamp = _as_utc(rec.timestamp_utc)
        if start_utc is not None and stamp < start_utc:
            continue
        if end_utc is not None and stamp >= end_utc:
            continue

        key = tuple(
            rec.provider_id if k == "provider"
            else rec.model if k == "model"
            else rec.content_kind
            for k in keys
        )
        agg = buckets.setdefault(key, UsageAggregate(
            provider_id=rec.provider_id,
            model=rec.model,
            content_kind=rec.content_kind,
        ))
        # Frozen dataclass → rebuild
        buckets[key] = UsageAggregate(
            provider_id=agg.provider_id,
            model=agg.model,
            content_kind=agg.content_kind,
            request_count=agg.request_count + rec.request_count,
            network_request_count=agg.network_request_count + (0 if rec.cache_hit else rec.request_count),
            cache_hit_count=agg.cache_hit_count + (rec.request_count if rec.cache_hit else 0),
            success_count=agg.success_count + (1 if rec.success else 0),
            failure_count=agg.failure_count + (0 if rec.success else 1),
            # Fold each record's tokens into the aggregate: the partial sum
            # accumulates across unknown records, and known flips to False
            # permanently once any contributing record is unknown — never a
            # fabricated total, never a dropped partial.
            input_tokens=agg.input_tokens.accumulate(rec.input_tokens),
            output_tokens=agg.output_tokens.accumulate(rec.output_tokens),
        )

    # Deterministic order
    return [buckets[k] for k in sorted(buckets, key=lambda k: tuple(str(x) for x in k))]


# ── Recorder ─────────────────────────────────────────────────────────────────

_USAGE_SCHEMA_VERSION = 1


class UsageRecorder:
    """Persistent, thread-safe, non-monetary usage recorder.

    ``clock`` is injectable for deterministic tests (must return a
    ``datetime`` in UTC).
    """

    def __init__(
        self,
        store_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store_path = Path(store_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def store_path(self) -> Path:
        return self._store_path

    def record(self, record: UsageRecord) -> UsageRecord:
        """Append one record atomically.  Raises UsageStorageError on any
        storage problem — fail-closed, never silently dropped or rewritten.

        The timestamp is validated and normalized to canonical UTC BEFORE
        any disk access: a date-only, blank, or unparseable value raises
        ``ValueError`` with ZERO side effects (no file created, no existing
        store touched, nothing persisted).  Naive values are interpreted as
        UTC; offset values are converted.  The returned record's
        ``timestamp_utc`` equals the persisted UTC string.
        """
        # Validate + normalize BEFORE any read or write (zero side effects).
        normalized_ts = normalize_timestamp_utc(
            record.timestamp_utc, clock=self._clock)
        stamped = replace(
            record,
            id=record.id or str(uuid4()),
            timestamp_utc=normalized_ts,
        )
        with self._lock:
            existing = self._load_locked()
            existing.append(stamped)
            self._write_locked(existing)
        return stamped

    def records(self) -> list[UsageRecord]:
        """Return all records.  Raises UsageStorageError if the store is
        corrupted or unreadable — corrupt data is never reported as empty."""
        with self._lock:
            return self._load_locked()

    def is_available(self) -> bool:
        """True when the store is readable; False when storage is corrupted
        or unavailable (the UI then shows the unavailable state)."""
        try:
            self.records()
            return True
        except UsageStorageError:
            return False

    # ── Aggregation over persisted records ────────────────────────────────

    def daily_summary(
        self,
        day: date | None = None,
        group_by: Sequence[str] = ("provider",),
    ) -> list[UsageAggregate]:
        """Aggregate records for one UTC calendar day (default: the clock's
        current day)."""
        target = day or self._clock().astimezone(timezone.utc).date()
        start, end = utc_day_bounds(target)
        return aggregate_usage(self.records(), start_utc=start, end_utc=end, group_by=group_by)

    def monthly_summary(
        self,
        month: date | None = None,
        group_by: Sequence[str] = ("provider",),
    ) -> list[UsageAggregate]:
        """Aggregate records for one UTC calendar month (default: the clock's
        current month)."""
        target = month or self._clock().astimezone(timezone.utc).date().replace(day=1)
        start, end = utc_month_bounds(target)
        return aggregate_usage(self.records(), start_utc=start, end_utc=end, group_by=group_by)

    # ── Internal: storage ─────────────────────────────────────────────────

    def _load_locked(self) -> list[UsageRecord]:
        if not self._store_path.exists():
            return []
        try:
            raw = self._store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as error:
            raise UsageStorageError("usage storage corrupted or unreadable") from error

        if not isinstance(data, dict):
            raise UsageStorageError("usage storage root must be a JSON object")
        if data.get("schema_version") != _USAGE_SCHEMA_VERSION:
            raise UsageStorageError(
                f"usage storage schema mismatch: {data.get('schema_version')!r}"
            )
        items = data.get("records")
        if not isinstance(items, list):
            raise UsageStorageError("usage storage 'records' must be a list")

        records: list[UsageRecord] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise UsageStorageError(f"usage record {i} must be a JSON object")
            try:
                record = UsageRecord(**item)
            except (TypeError, ValueError) as error:
                raise UsageStorageError(f"usage record {i} is invalid") from error
            # timestamp_utc must be a parseable ISO-8601 timestamp WITH a
            # time component (same single rule as record()).  Any offset or
            # naive is accepted; naive is normalized to UTC by _as_utc.
            try:
                _parse_timestamp(record.timestamp_utc)
            except ValueError:
                raise UsageStorageError(
                    f"usage record {i} has an invalid timestamp_utc") from None
            records.append(record)
        return records

    def _write_locked(self, records: list[UsageRecord]) -> None:
        data = {
            "schema_version": _USAGE_SCHEMA_VERSION,
            "records": [
                {k: v for k, v in asdict(r).items()}
                for r in records
            ],
        }
        json_text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

        tmp: Path | None = None
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                prefix="usage_",
                dir=str(self._store_path.parent),
            )
            tmp = Path(tmp_path)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json_text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(self._store_path))
        except OSError as error:
            if tmp is not None and tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise UsageStorageError("usage storage write failed") from error


# ── Integrity: secret sentinel scan (test helper) ────────────────────────────

def scan_for_secrets(store_path: str | Path, sentinels: Sequence[str]) -> list[str]:
    """Return sentinels found in the raw store bytes (regression guard).

    The schema has no secret-bearing fields, so this must always return [].
    """
    path = Path(store_path)
    if not path.exists():
        return []
    raw = path.read_bytes()
    return [s for s in sentinels if s.encode("utf-8") in raw]


def usage_store_digest(store_path: str | Path) -> str:
    """SHA-256 of the raw store file — used to prove goldens/persistence are
    untouched and stable across identical content."""
    path = Path(store_path)
    if not path.exists():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()
