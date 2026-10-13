"""Local multi-context content-hash cache.

The cache key is a deterministic SHA-256 digest of every context dimension.
No API keys, tokens, paths, raw text, images, or request bodies enter the key
or persisted records.  Cache hits are distinguishable from live API responses.

Persistence is schema-versioned with atomic writes.  Corrupt files are
fail-closed (treated as empty cache).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


# ── Value types ──────────────────────────────────────────────────────────────


class CacheEntryStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"


@dataclass
class CacheEntry:
    """One cache lookup result — pure data, no secrets."""

    status: CacheEntryStatus
    data: Any | None = None
    source: str = "local_cache"


@dataclass
class CacheStats:
    """Read-only cache statistics."""

    entry_count: int = 0
    hit_count: int = 0
    miss_count: int = 0


# ── CacheContext ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CacheContext:
    """Every dimension that affects cache key derivation.

    All fields are metadata — no secrets, raw content, or paths.
    """

    content_hash: str = ""
    provider_profile_id: str = ""
    provider_id: str = ""
    model: str = ""
    quality_mode: str = "balanced"
    template_id: str = ""
    template_version: str = ""
    vocabulary_id: str = ""
    vocabulary_version: str = ""
    locale: str = "en-US"
    preprocessing_version: str = ""
    requested_schema_version: str = ""

    def to_canonical_bytes(self) -> bytes:
        """Produce a stable, deterministic serialization for hashing."""
        parts = [
            ("content_hash", self.content_hash),
            ("provider_profile_id", self.provider_profile_id),
            ("provider_id", self.provider_id),
            ("model", self.model),
            ("quality_mode", self.quality_mode),
            ("template_id", self.template_id),
            ("template_version", self.template_version),
            ("vocabulary_id", self.vocabulary_id),
            ("vocabulary_version", self.vocabulary_version),
            ("locale", self.locale),
            ("preprocessing_version", self.preprocessing_version),
            ("requested_schema_version", self.requested_schema_version),
        ]
        canonical = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return canonical.encode("utf-8")


def make_cache_key(ctx: CacheContext) -> str:
    """Derive a deterministic SHA-256 hex digest from the context."""
    return hashlib.sha256(ctx.to_canonical_bytes()).hexdigest()


# ── Cache store (in-memory + optional local persistence) ─────────────────────


_CACHE_SCHEMA_VERSION = 2


class CacheManager:
    """Thread-safe local cache with multi-context key derivation.

    - In-memory LRU with configurable ``max_entries``.
    - Optional local persistence with atomic writes and schema versioning.
    - Corrupt files are fail-closed (treated as empty cache).
    - No API keys, secrets, paths, raw text, or image bytes in the store.
    """

    def __init__(
        self,
        *,
        store_path: Path,
        max_entries: int = 1000,
    ) -> None:
        self._store_path = store_path
        self._max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, Any]] = {}
        self._access_order: list[str] = []  # front = most recently used
        self._hit_count = 0
        self._miss_count = 0

        # Attempt restore
        self._restore()

    # ── Read ─────────────────────────────────────────────────────────────

    def get(self, ctx: CacheContext) -> CacheEntry | None:
        """Look up a cached response.  Returns ``None`` on miss."""
        key = make_cache_key(ctx)
        with self._lock:
            if key not in self._store:
                self._miss_count += 1
                return None
            # Promote to MRU
            entry_data = self._store[key]
            self._access_order.remove(key)
            self._access_order.append(key)
            self._hit_count += 1
            return CacheEntry(
                status=CacheEntryStatus.HIT,
                data=entry_data.get("data"),
                source="local_cache",
            )

    def put(self, ctx: CacheContext, data: Any) -> None:
        """Store a response in the cache.  None values are not stored."""
        if data is None:
            return
        key = make_cache_key(ctx)
        with self._lock:
            # Remove old entry if updating
            if key in self._store:
                self._access_order.remove(key)
                del self._store[key]

            # Evict oldest if at capacity
            while len(self._store) >= self._max_entries and self._access_order:
                oldest = self._access_order.pop(0)
                self._store.pop(oldest, None)

            self._store[key] = {
                "data": data,
                "stored_at": time.time(),
            }
            self._access_order.append(key)

    def delete(self, ctx: CacheContext) -> None:
        """Remove a single cache entry."""
        key = make_cache_key(ctx)
        with self._lock:
            if key in self._access_order:
                self._access_order.remove(key)
            self._store.pop(key, None)

    def invalidate(self, ctx: CacheContext, *, reason: str = "") -> None:
        """Invalidate an entry with an explicit reason (same as delete for now)."""
        self.delete(ctx)

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._store.clear()
            self._access_order.clear()

    # ── Stats ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                entry_count=len(self._store),
                hit_count=self._hit_count,
                miss_count=self._miss_count,
            )

    # ── Persistence ──────────────────────────────────────────────────────

    def flush(self) -> bool:
        """Write the cache to disk atomically.  Returns True on success."""
        data = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "entries": {
                key: {
                    "data": self._store[key]["data"],
                    "stored_at": self._store[key]["stored_at"],
                }
                for key in self._store
            },
        }
        try:
            parent = self._store_path.parent
            parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._store_path.with_suffix(
                self._store_path.suffix + ".tmp"
            )
            serialized = json.dumps(
                data, ensure_ascii=False, indent=2, sort_keys=True
            )
            tmp_path.write_text(serialized, encoding="utf-8")
            tmp_path.replace(self._store_path)
            return True
        except (OSError, IOError):
            return False

    def _restore(self) -> None:
        """Restore from disk.  Corrupt files → empty cache (fail-closed)."""
        if not self._store_path.exists():
            return

        try:
            raw = self._store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return

        if not isinstance(data, dict):
            return

        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int):
            return

        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            return

        for key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            if not isinstance(key, str):
                continue
            self._store[key] = {
                "data": entry.get("data"),
                "stored_at": entry.get("stored_at", time.time()),
            }
            self._access_order.append(key)
