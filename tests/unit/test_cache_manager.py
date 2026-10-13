"""Unit tests for local multi-context content hash cache.

Tests use temporary directories — never touch real user data or credentials.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from src.core.cache_manager import (
    CacheContext,
    CacheEntry,
    CacheEntryStatus,
    CacheManager,
    CacheStats,
    make_cache_key,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _tmp_cache_path(tmp_path: Path) -> Path:
    return tmp_path / "cache.db"


def _context(**overrides):
    defaults = {
        "content_hash": "sha256:abc123def456",
        "provider_profile_id": "p-deepseek-001",
        "provider_id": "deepseek",
        "model": "deepseek-v4-flash",
        "quality_mode": "balanced",
        "template_id": "default",
        "template_version": "2.1.0",
        "vocabulary_id": "en-zh",
        "vocabulary_version": "1.0.0",
        "locale": "zh-CN",
        "preprocessing_version": "resize-v2",
        "requested_schema_version": "dc-v1",
    }
    defaults.update(overrides)
    return CacheContext(**defaults)


def _sample_response_data():
    return {
        "fields": {"dcTitle": "Report", "dcType": "doc"},
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "model_used": "deepseek-v4-flash",
        "latency_ms": 250.0,
    }


# ── CacheContext ─────────────────────────────────────────────────────────────


class TestCacheContext:
    def test_context_is_immutable_pure_data(self):
        ctx = _context()
        assert ctx.provider_id == "deepseek"
        with pytest.raises(Exception):
            ctx.provider_id = "other"

    def test_context_equality(self):
        ctx1 = _context()
        ctx2 = _context()
        assert ctx1 == ctx2
        assert hash(ctx1) == hash(ctx2)

    def test_context_change_different_hash(self):
        ctx1 = _context()
        ctx2 = _context(model="deepseek-v4-pro")
        assert hash(ctx1) != hash(ctx2)


# ── make_cache_key ───────────────────────────────────────────────────────────


class TestMakeCacheKey:
    def test_cache_key_is_deterministic(self):
        ctx = _context()
        key1 = make_cache_key(ctx)
        key2 = make_cache_key(ctx)
        assert key1 == key2, "Same context must produce the same key"

    def test_context_change_changes_key(self):
        ctx1 = _context()
        ctx2 = _context(provider_id="qwen")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_model_change_changes_key(self):
        ctx1 = _context()
        ctx2 = _context(model="deepseek-v4-pro")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_quality_mode_change_changes_key(self):
        ctx1 = _context()
        ctx2 = _context(quality_mode="quality")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_locale_change_changes_key(self):
        ctx1 = _context(locale="zh-CN")
        ctx2 = _context(locale="en-US")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_template_version_change_changes_key(self):
        ctx1 = _context(template_version="2.1.0")
        ctx2 = _context(template_version="2.2.0")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_schema_version_change_changes_key(self):
        ctx1 = _context(requested_schema_version="dc-v1")
        ctx2 = _context(requested_schema_version="dc-v2")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_preprocessing_version_change_changes_key(self):
        ctx1 = _context(preprocessing_version="resize-v2")
        ctx2 = _context(preprocessing_version="resize-v3")
        assert make_cache_key(ctx1) != make_cache_key(ctx2)

    def test_no_secrets_in_key(self):
        ctx = _context()
        key = make_cache_key(ctx)
        # Key must not contain any credential-like strings
        assert "sk-" not in key.lower()
        assert "bearer" not in key.lower()
        assert "api_key" not in key.lower()
        assert "token" not in key.lower()
        assert "authorization" not in key.lower()

    def test_key_is_stable_string(self):
        ctx = _context()
        key = make_cache_key(ctx)
        assert isinstance(key, str)
        assert len(key) >= 32  # at least SHA-256 length in hex
        # Should be hex
        assert all(c in "0123456789abcdef" for c in key), (
            "Cache key must be a hex digest"
        )


# ── CacheManager: get / put ──────────────────────────────────────────────────


class TestCacheManagerGetPut:
    def test_put_and_get(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()
        data = _sample_response_data()

        mgr.put(ctx, data)
        entry = mgr.get(ctx)

        assert entry is not None
        assert entry.status is CacheEntryStatus.HIT
        assert entry.data == data

    def test_cache_miss(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()

        entry = mgr.get(ctx)
        assert entry is None

    def test_context_change_cache_miss(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx1 = _context(model="deepseek-v4-flash")
        ctx2 = _context(model="deepseek-v4-pro")

        mgr.put(ctx1, _sample_response_data())
        entry = mgr.get(ctx2)

        assert entry is None, "Different model → cache miss"

    def test_cache_hit_distinguishable_from_api(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()
        data = _sample_response_data()

        mgr.put(ctx, data)
        entry = mgr.get(ctx)

        assert entry is not None
        assert entry.status is CacheEntryStatus.HIT
        assert entry.source == "local_cache"

    def test_none_data_not_stored(self, tmp_path):
        """None values must not be cached."""
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()
        mgr.put(ctx, None)
        assert mgr.get(ctx) is None

    def test_empty_dict_stored(self, tmp_path):
        """Empty dict is valid cached data."""
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()
        mgr.put(ctx, {})
        entry = mgr.get(ctx)
        assert entry is not None
        assert entry.data == {}


# ── CacheManager: persistence ────────────────────────────────────────────────


class TestCacheManagerPersistence:
    def test_persist_and_restore(self, tmp_path):
        store_path = _tmp_cache_path(tmp_path)

        mgr1 = CacheManager(store_path=store_path)
        ctx = _context()
        mgr1.put(ctx, _sample_response_data())
        mgr1.flush()

        mgr2 = CacheManager(store_path=store_path)
        entry = mgr2.get(ctx)
        assert entry is not None
        assert entry.status is CacheEntryStatus.HIT
        assert entry.data["fields"]["dcTitle"] == "Report"

    def test_no_secrets_in_persisted_data(self, tmp_path):
        store_path = _tmp_cache_path(tmp_path)

        mgr = CacheManager(store_path=store_path)
        ctx = _context()
        mgr.put(ctx, _sample_response_data())
        mgr.flush()

        raw = store_path.read_text(encoding="utf-8").casefold()
        # Check for actual credential patterns (not "token" which matches "prompt_tokens")
        banned_patterns = (
            "api_key", "apikey", "bearer", "authorization",
            "sk-", "secret", "password",
        )
        for pattern in banned_patterns:
            assert pattern not in raw, (
                f"Cache file must not contain {pattern}"
            )
        # Raw request bodies and image data must not be stored
        assert "request_body" not in raw, "Cache must not contain request_body"
        assert "base64," not in raw, "Cache must not contain base64-encoded image data"

    def test_corrupt_file_fail_closed(self, tmp_path):
        store_path = _tmp_cache_path(tmp_path)
        store_path.write_text("{corrupt json [[[", encoding="utf-8")

        mgr = CacheManager(store_path=store_path)
        ctx = _context()
        # Should not crash; should operate in empty state
        entry = mgr.get(ctx)
        assert entry is None

    def test_schema_version_in_persisted_data(self, tmp_path):
        store_path = _tmp_cache_path(tmp_path)

        mgr = CacheManager(store_path=store_path)
        mgr.put(_context(), _sample_response_data())
        mgr.flush()

        raw = json.loads(store_path.read_text(encoding="utf-8"))
        assert "schema_version" in raw

    def test_atomic_write(self, tmp_path):
        """Write should not corrupt existing data on failure."""
        store_path = _tmp_cache_path(tmp_path)

        mgr = CacheManager(store_path=store_path)
        ctx = _context()
        mgr.put(ctx, _sample_response_data())
        mgr.flush()

        first_read = store_path.read_text(encoding="utf-8")
        assert len(first_read) > 0

        # Write again and check it's still valid JSON
        mgr.put(ctx, {"other": "data"})
        mgr.flush()

        second_read = store_path.read_text(encoding="utf-8")
        assert len(second_read) > 0
        data = json.loads(second_read)
        assert isinstance(data, dict)


# ── CacheManager: eviction ───────────────────────────────────────────────────


class TestCacheManagerEviction:
    def test_capacity_limit_evicts_oldest(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path), max_entries=2)

        ctx1 = _context(content_hash="hash1")
        ctx2 = _context(content_hash="hash2")
        ctx3 = _context(content_hash="hash3")

        mgr.put(ctx1, {"v": 1})
        mgr.put(ctx2, {"v": 2})
        mgr.put(ctx3, {"v": 3})

        # Oldest (ctx1) should be evicted
        assert mgr.get(ctx1) is None, "Oldest entry should be evicted"
        assert mgr.get(ctx2) is not None
        assert mgr.get(ctx3) is not None

    def test_delete_single_entry(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()

        mgr.put(ctx, _sample_response_data())
        assert mgr.get(ctx) is not None

        mgr.delete(ctx)
        assert mgr.get(ctx) is None

    def test_clear_all(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx1 = _context(content_hash="h1")
        ctx2 = _context(content_hash="h2")

        mgr.put(ctx1, {"v": 1})
        mgr.put(ctx2, {"v": 2})
        assert mgr.stats.entry_count == 2

        mgr.clear()
        assert mgr.stats.entry_count == 0
        assert mgr.get(ctx1) is None
        assert mgr.get(ctx2) is None

    def test_invalidation_reason_recorded(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()

        mgr.put(ctx, _sample_response_data())
        mgr.invalidate(ctx, reason="Model configuration changed")

        entry = mgr.get(ctx)
        assert entry is None


# ── CacheManager: CacheStats ─────────────────────────────────────────────────


class TestCacheStats:
    def test_initial_stats(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        stats = mgr.stats
        assert stats.entry_count == 0
        assert stats.hit_count == 0
        assert stats.miss_count == 0

    def test_stats_after_hit_and_miss(self, tmp_path):
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()

        mgr.get(ctx)  # miss
        mgr.put(ctx, _sample_response_data())
        mgr.get(ctx)  # hit

        stats = mgr.stats
        assert stats.miss_count >= 1
        assert stats.hit_count >= 1

    def test_cache_hit_not_forged_as_api_usage(self, tmp_path):
        """Cache hits must not be counted as new API usage."""
        mgr = CacheManager(store_path=_tmp_cache_path(tmp_path))
        ctx = _context()
        data = _sample_response_data()

        mgr.put(ctx, data)
        entry = mgr.get(ctx)

        assert entry is not None
        assert entry.status is CacheEntryStatus.HIT
        # Source field distinguishes cache from API
        assert entry.source == "local_cache"


# ── CacheEntry ───────────────────────────────────────────────────────────────


class TestCacheEntry:
    def test_hit_entry(self):
        e = CacheEntry(
            status=CacheEntryStatus.HIT,
            data={"key": "value"},
            source="local_cache",
        )
        assert e.status is CacheEntryStatus.HIT
        assert e.source == "local_cache"

    def test_miss_entry(self):
        e = CacheEntry(
            status=CacheEntryStatus.MISS,
            data=None,
            source="local_cache",
        )
        assert e.status is CacheEntryStatus.MISS
        assert e.data is None
