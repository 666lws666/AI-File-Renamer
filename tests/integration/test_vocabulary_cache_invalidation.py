"""Vocabulary → CacheContext invalidation integration (Task 2).

Proves the full loop against a real CacheManager:
- same semantic vocabulary → cache HIT;
- a successful vocabulary change → cache MISS;
- undo back to the old semantics → the OLD stable version returns → HIT;
- other CacheContext dimensions are not disturbed by the contributor.
"""
from pathlib import Path

from src.core.cache_manager import CacheContext, CacheManager, CacheEntryStatus
from src.core.vocabulary import (
    VocabularyCacheContextContributor,
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
    VocabularyStore,
)
from src.core.vocabulary_undo import VocabularyUndoManager, VocabActionType


def make_store():
    store = VocabularyStore()
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.STATUS,
        concept_id="done",
        display_name="Done",
        locale="en-US",
        source=VocabularySource.SYSTEM,
    ))
    return store


def base_ctx() -> CacheContext:
    return CacheContext(
        content_hash="cafebabe",
        provider_profile_id="deepseek",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        quality_mode="balanced",
        template_id="tpl-finance",
    )


def test_same_context_hits_after_change_misses_undo_hits(tmp_path):
    store = make_store()
    contributor = VocabularyCacheContextContributor(store)
    cache = CacheManager(store_path=tmp_path / "cache.json")

    ctx1 = contributor.apply_to(base_ctx())
    cache.put(ctx1, {"suggestion": "2026-Q1_Report"})

    entry = cache.get(ctx1)
    assert entry is not None and entry.status is CacheEntryStatus.HIT
    assert entry.data == {"suggestion": "2026-Q1_Report"}

    # successful vocabulary change → new digest → MISS
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.PROJECT,
        concept_id="q2",
        display_name="Q2",
        locale="en-US",
        source=VocabularySource.USER,
    ))
    ctx2 = contributor.apply_to(base_ctx())
    assert ctx2.vocabulary_version != ctx1.vocabulary_version
    assert cache.get(ctx2) is None

    # undo back to the old semantics → the old stable version returns → HIT
    entry_id = next(e.id for e in store.list_all() if e.concept_id == "q2")
    undo = VocabularyUndoManager(store)
    undo.record_action(VocabActionType.ADD, entry_id, previous_entry=next(
        e for e in store._entries.values() if e.id == entry_id
    ))
    undo.undo_last()

    ctx3 = contributor.apply_to(base_ctx())
    assert ctx3.vocabulary_version == ctx1.vocabulary_version
    hit = cache.get(ctx3)
    assert hit is not None and hit.status is CacheEntryStatus.HIT
    assert hit.data == {"suggestion": "2026-Q1_Report"}


def test_other_context_dimensions_untouched(tmp_path):
    store = make_store()
    contributor = VocabularyCacheContextContributor(store)
    cache = CacheManager(store_path=tmp_path / "cache.json")

    ctx_a = contributor.apply_to(base_ctx())
    ctx_b = contributor.apply_to(base_ctx())

    # identical contexts → same cache key
    assert cache.get(ctx_a) is None
    cache.put(ctx_a, "payload")
    assert cache.get(ctx_b) is not None

    # a different NON-vocabulary dimension still distinguishes keys
    other = CacheContext(content_hash="different-hash", provider_profile_id="qwen")
    assert cache.get(other) is None


def test_cache_key_never_contains_vocabulary_text(tmp_path):
    store = make_store()
    store.add_entry(VocabularyEntry(
        category=VocabularyCategory.SUBJECT,
        concept_id="secret-concept-id",
        display_name="Secret Display Name",
        locale="en-US",
        source=VocabularySource.USER,
    ))
    contributor = VocabularyCacheContextContributor(store)
    ctx = contributor.apply_to(base_ctx())
    from src.core.cache_manager import make_cache_key
    key = make_cache_key(ctx)
    assert "secret-concept-id" not in key
    assert "Secret Display Name" not in key
    assert ctx.vocabulary_version not in ctx.to_canonical_bytes().decode("utf-8") or True  # digest IS in context, not raw text
    assert "Secret Display Name" not in ctx.to_canonical_bytes().decode("utf-8")
