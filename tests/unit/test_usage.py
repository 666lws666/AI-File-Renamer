"""UsageRecorder — non-monetary usage recording tests (Task 1).

Deterministic: the clock is injectable, timestamps are explicit, and all
storage lives in tmp paths.  No real API, no real credentials, no network.
"""
import json
import threading
from datetime import date, datetime, timezone

import pytest

from src.core.usage import (
    UsageAggregate,
    UsageContentKind,
    UsageRecorder,
    UsageRecord,
    UsageStorageError,
    aggregate_usage,
    content_kind_for_file_type,
    error_category_for,
    scan_for_secrets,
    utc_day_bounds,
    utc_month_bounds,
)

UTC = timezone.utc


def rec(**kw):
    base = {
        "provider_id": "deepseek",
        "profile_id": "deepseek",
        "model": "deepseek-v4-pro",
        "content_kind": UsageContentKind.TEXT.value,
        "request_count": 1,
        "cache_hit": False,
        "success": True,
        "input_tokens": 100,
        "output_tokens": 50,
        "timestamp_utc": "2026-08-03T10:00:00+00:00",
    }
    base.update(kw)
    return UsageRecord(**base)


class FakeClock:
    def __init__(self, now):
        self._now = now

    def __call__(self):
        return self._now


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "usage" / "usage.json"


# ============================================================================
# Single record append + read
# ============================================================================

def test_record_and_read_roundtrip(store_path):
    recorder = UsageRecorder(store_path)
    stamped = recorder.record(rec())
    assert stamped.id
    assert stamped.timestamp_utc == "2026-08-03T10:00:00+00:00"
    loaded = recorder.records()
    assert len(loaded) == 1
    assert loaded[0].provider_id == "deepseek"
    assert loaded[0].model == "deepseek-v4-pro"
    assert loaded[0].input_tokens == 100
    assert loaded[0].output_tokens == 50


# ============================================================================
# record(): timestamp validated + normalized to UTC BEFORE any write
# ============================================================================

def test_record_rejects_date_only_timestamp_no_side_effects(store_path):
    """A date-only timestamp must be rejected immediately — no file is
    created, no in-memory state changes, no store corruption."""
    recorder = UsageRecorder(store_path)
    with pytest.raises(ValueError):
        recorder.record(rec(timestamp_utc="2026-08-03"))
    assert not store_path.exists(), "no store may be created on rejection"
    assert recorder.records() == []
    assert recorder.is_available() is True


def test_record_rejects_invalid_timestamp_no_side_effects(store_path):
    recorder = UsageRecorder(store_path)
    with pytest.raises(ValueError):
        recorder.record(rec(timestamp_utc="not-a-date"))
    with pytest.raises(ValueError):
        recorder.record(rec(timestamp_utc="   "))
    assert not store_path.exists()
    assert recorder.records() == []


def test_record_rejection_keeps_existing_store_unchanged(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(operation_id="good"))
    before = store_path.read_bytes()
    with pytest.raises(ValueError):
        recorder.record(rec(timestamp_utc="2026-08-03"))
    assert store_path.read_bytes() == before, "rejected record must not mutate the store"


def test_record_naive_timestamp_normalized_to_utc(store_path):
    """A naive datetime is interpreted as UTC and persisted with +00:00."""
    recorder = UsageRecorder(store_path)
    stamped = recorder.record(rec(timestamp_utc="2026-08-03T10:00:00"))
    assert stamped.timestamp_utc == "2026-08-03T10:00:00+00:00"
    assert recorder.records()[0].timestamp_utc == "2026-08-03T10:00:00+00:00"
    # naive 10:00 == UTC 10:00 → lands on Aug 3 UTC
    assert len(recorder.daily_summary(day=date(2026, 8, 3))) == 1


def test_record_offset_timestamp_converted_to_utc(store_path):
    recorder = UsageRecorder(store_path)
    stamped = recorder.record(rec(timestamp_utc="2026-08-03T10:00:00+08:00"))
    assert stamped.timestamp_utc == "2026-08-03T02:00:00+00:00"
    assert recorder.records()[0].timestamp_utc == "2026-08-03T02:00:00+00:00"
    assert len(recorder.daily_summary(day=date(2026, 8, 3))) == 1


def test_record_clock_returning_naive_datetime_normalized(store_path):
    """Even a naive clock result is normalized to UTC before persisting."""
    clock = FakeClock(datetime(2026, 8, 3, 8, 30, 0))  # naive, no tz
    recorder = UsageRecorder(store_path, clock=clock)
    stamped = recorder.record(rec(timestamp_utc=""))
    assert stamped.timestamp_utc == "2026-08-03T08:30:00+00:00"
    assert recorder.records()[0].timestamp_utc == "2026-08-03T08:30:00+00:00"


def test_record_normalized_then_readable_immediately(store_path):
    recorder = UsageRecorder(store_path)
    stamped = recorder.record(rec(timestamp_utc="2026-08-03T18:00:00+08:00"))
    assert stamped.timestamp_utc == "2026-08-03T10:00:00+00:00"
    assert len(recorder.records()) == 1
    assert len(recorder.daily_summary(day=date(2026, 8, 3))) == 1


def test_record_without_timestamp_uses_injectable_clock(store_path):
    clock = FakeClock(datetime(2026, 8, 3, 8, 30, 0, tzinfo=UTC))
    recorder = UsageRecorder(store_path, clock=clock)
    stamped = recorder.record(rec(timestamp_utc=""))
    assert stamped.timestamp_utc == "2026-08-03T08:30:00+00:00"
    assert stamped.id, "recorder must assign an id"


def test_invalid_record_rejected(store_path):
    recorder = UsageRecorder(store_path)
    with pytest.raises(ValueError):
        recorder.record(rec(request_count=0))
    with pytest.raises(ValueError):
        recorder.record(rec(input_tokens=-1))


# ============================================================================
# Aggregation: multi provider/model, day/month boundaries, cache hit
# ============================================================================

def test_aggregate_multi_provider_and_model(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(provider_id="deepseek", model="ds-a", request_count=1, input_tokens=100, output_tokens=10))
    recorder.record(rec(provider_id="deepseek", model="ds-a", request_count=2, input_tokens=200, output_tokens=20))
    recorder.record(rec(provider_id="qwen", model="qw-b", request_count=1, input_tokens=300, output_tokens=30))

    by_provider = recorder.daily_summary(day=date(2026, 8, 3), group_by=("provider",))
    assert len(by_provider) == 2
    ds = next(a for a in by_provider if a.provider_id == "deepseek")
    qw = next(a for a in by_provider if a.provider_id == "qwen")
    assert ds.request_count == 3
    assert ds.input_tokens.known and ds.input_tokens.value == 300
    assert ds.output_tokens.value == 30
    assert qw.request_count == 1

    by_model = recorder.daily_summary(day=date(2026, 8, 3), group_by=("provider", "model"))
    assert len(by_model) == 2
    assert all(a.model in ("ds-a", "qw-b") for a in by_model)


def test_daily_boundary_excludes_next_day(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(timestamp_utc="2026-08-03T23:59:59+00:00"))
    recorder.record(rec(timestamp_utc="2026-08-04T00:00:00+00:00"))
    day3 = recorder.daily_summary(day=date(2026, 8, 3))
    day4 = recorder.daily_summary(day=date(2026, 8, 4))
    assert day3[0].request_count == 1
    assert day4[0].request_count == 1


def test_monthly_boundary(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(timestamp_utc="2026-07-31T23:59:59+00:00"))
    recorder.record(rec(timestamp_utc="2026-08-01T00:00:00+00:00"))
    july = recorder.monthly_summary(month=date(2026, 7, 1))
    aug = recorder.monthly_summary(month=date(2026, 8, 1))
    assert july[0].request_count == 1
    assert aug[0].request_count == 1


def test_utc_bounds_helpers():
    start, end = utc_day_bounds(date(2026, 8, 3))
    assert start.isoformat() == "2026-08-03T00:00:00+00:00"
    assert end.isoformat() == "2026-08-04T00:00:00+00:00"
    s2, e2 = utc_month_bounds(date(2026, 12, 1))
    assert s2.month == 12 and e2.year == 2027 and e2.month == 1


def test_cache_hit_distinguished_from_network(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(cache_hit=True, request_count=1))
    recorder.record(rec(cache_hit=False, request_count=3))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.request_count == 4
    assert agg.cache_hit_count == 1
    assert agg.network_request_count == 3


def test_success_failure_counts(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(success=True))
    recorder.record(rec(success=False, error_category="timeout"))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.success_count == 1
    assert agg.failure_count == 1


# ============================================================================
# Token unknown/known states
# ============================================================================

def test_unknown_tokens_never_forged_as_zero(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(input_tokens=None, output_tokens=None))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.input_tokens.known is False
    assert agg.output_tokens.known is False
    assert agg.input_tokens.value == 0  # nothing known to sum


def test_mixed_known_unknown_tokens_unknown(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(input_tokens=100, output_tokens=50))
    recorder.record(rec(input_tokens=None, output_tokens=20))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    # one record had no INPUT tokens → input aggregate is unknown
    assert agg.input_tokens.known is False
    assert agg.input_tokens.value == 100  # partial sum, but state is unknown
    # both records reported OUTPUT tokens → output aggregate stays known
    assert agg.output_tokens.known is True
    assert agg.output_tokens.value == 70


def test_known_zero_is_real_zero(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(input_tokens=0, output_tokens=0))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.input_tokens.known is True
    assert agg.input_tokens.value == 0


def test_partial_sum_preserved_across_unknown_records(store_path):
    """Partial known token sums must survive unknown records in ANY order:
    50 + unknown + 100 → partial 150, known False (never 100, never 0)."""
    recorder = UsageRecorder(store_path)
    recorder.record(rec(input_tokens=50, output_tokens=None, operation_id="a"))
    recorder.record(rec(input_tokens=None, output_tokens=20, operation_id="b"))
    recorder.record(rec(input_tokens=100, output_tokens=30, operation_id="c"))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.input_tokens.known is False
    assert agg.input_tokens.value == 150, (
        "partial input sum must accumulate across the unknown record"
    )
    assert agg.output_tokens.known is False
    assert agg.output_tokens.value == 50


def test_partial_sum_unknown_first(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(input_tokens=None, operation_id="a"))
    recorder.record(rec(input_tokens=40, operation_id="b"))
    recorder.record(rec(input_tokens=60, operation_id="c"))
    agg = recorder.daily_summary(day=date(2026, 8, 3))[0]
    assert agg.input_tokens.known is False
    assert agg.input_tokens.value == 100


# ============================================================================
# Persistence: restart recovery, corrupted storage, atomic failure
# ============================================================================

def test_restart_recovery(store_path):
    recorder1 = UsageRecorder(store_path)
    recorder1.record(rec(provider_id="a"))
    recorder1.record(rec(provider_id="b"))

    recorder2 = UsageRecorder(store_path)  # "restart"
    loaded = recorder2.records()
    assert len(loaded) == 2
    assert {r.provider_id for r in loaded} == {"a", "b"}
    # identical content → identical store digest (stable persistence)
    recorder3 = UsageRecorder(store_path)
    assert recorder3.records() == loaded


def test_corrupted_storage_fail_closed(store_path):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{not-json!!!", encoding="utf-8")
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()
    with pytest.raises(UsageStorageError):
        recorder.record(rec())
    assert recorder.is_available() is False
    # the corrupt file must NOT be rewritten or masqueraded as empty
    assert store_path.read_text(encoding="utf-8") == "{not-json!!!"


def test_schema_mismatch_fail_closed(store_path):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({"schema_version": 99, "records": []}), encoding="utf-8")
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()
    assert recorder.is_available() is False


def test_invalid_record_entry_fail_closed(store_path):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({
        "schema_version": 1,
        "records": [{"provider_id": "x"}],  # missing required fields
    }), encoding="utf-8")
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()


def _write_store(store_path, records):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps({
        "schema_version": 1,
        "records": records,
    }), encoding="utf-8")


def _valid_record_json(**overrides):
    record = {
        "provider_id": "deepseek",
        "profile_id": "deepseek",
        "model": "ds-a",
        "content_kind": "text",
        "request_count": 1,
        "cache_hit": False,
        "success": True,
        "timestamp_utc": "2026-08-03T10:00:00+00:00",
    }
    record.update(overrides)
    return record


def test_load_rejects_invalid_timestamp_fail_closed(store_path):
    _write_store(store_path, [_valid_record_json(timestamp_utc="not-a-date")])
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()
    with pytest.raises(UsageStorageError):
        recorder.daily_summary(day=date(2026, 8, 3))
    assert recorder.is_available() is False
    # the corrupt store must NOT be rewritten or reported as normal empty data
    raw = store_path.read_text(encoding="utf-8")
    assert "not-a-date" in raw


def test_load_rejects_date_only_timestamp(store_path):
    """A date without a time component is not a valid record timestamp."""
    _write_store(store_path, [_valid_record_json(timestamp_utc="2026-08-03")])
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()
    assert recorder.is_available() is False


def test_load_rejects_empty_timestamp(store_path):
    _write_store(store_path, [_valid_record_json(timestamp_utc="")])
    recorder = UsageRecorder(store_path)
    with pytest.raises(UsageStorageError):
        recorder.records()
    assert recorder.is_available() is False


def test_load_accepts_offsets_and_naive_timestamps(store_path):
    """Any parseable ISO-8601 timestamp (offset or naive→UTC) loads fine."""
    _write_store(store_path, [
        _valid_record_json(timestamp_utc="2026-08-03T10:00:00+08:00"),
        _valid_record_json(timestamp_utc="2026-08-03T02:00:00"),
    ])
    recorder = UsageRecorder(store_path)
    records = recorder.records()
    assert len(records) == 2
    assert recorder.is_available() is True
    # +08:00 10:00 == 02:00 UTC → both land on Aug 3 UTC
    assert len(recorder.daily_summary(day=date(2026, 8, 3))) == 1


def test_atomic_write_failure_keeps_original(store_path, tmp_path):
    # store path whose parent is a FILE → mkdir/write must fail
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad_path = blocker / "usage.json"
    recorder = UsageRecorder(bad_path)
    with pytest.raises(UsageStorageError):
        recorder.record(rec())
    with pytest.raises(UsageStorageError):
        recorder.record(rec())
    assert not bad_path.exists()


def test_concurrent_record_is_safe(store_path):
    recorder = UsageRecorder(store_path)
    errors: list[Exception] = []

    def writer(n):
        try:
            for i in range(10):
                recorder.record(rec(provider_id=f"p{n}", operation_id=str(i)))
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(recorder.records()) == 40


# ============================================================================
# Secret sentinel scan — no key/prompt/body/path/money ever persisted
# ============================================================================

def test_secret_sentinel_scan(store_path):
    recorder = UsageRecorder(store_path)
    api_key = "sk-sentinel-abcdef0123456789"
    prompt = "PROMPT_SENTINEL_SECRET"
    body = "BODY_SENTINEL_SECRET"
    full_path = "D:\\secret\\dir\\quarterly-report.pdf"
    recorder.record(rec(
        provider_id="deepseek",
        operation_id="task-1",
    ))
    recorder.record(rec(success=False, error_category="timeout", operation_id="task-2"))

    found = scan_for_secrets(store_path, [api_key, prompt, body, full_path])
    assert found == [], f"secret material leaked into usage store: {found}"


def test_usage_schema_has_no_secret_fields():
    from dataclasses import fields
    names = {f.name for f in fields(UsageRecord)}
    for forbidden in ("api_key", "prompt", "body", "content", "path", "file_name", "price", "cost", "currency"):
        assert forbidden not in names, f"forbidden field in UsageRecord: {forbidden}"


# ============================================================================
# Content kind + error category mapping
# ============================================================================

def test_content_kind_mapping():
    assert content_kind_for_file_type("jpg") == UsageContentKind.IMAGE.value
    assert content_kind_for_file_type(".PNG") == UsageContentKind.IMAGE.value
    assert content_kind_for_file_type("mp4") == UsageContentKind.VIDEO.value
    assert content_kind_for_file_type("pdf") == UsageContentKind.SCANNED_PDF.value
    assert content_kind_for_file_type("txt") == UsageContentKind.TEXT.value
    assert content_kind_for_file_type("") == UsageContentKind.TEXT.value


def test_error_category_mapping():
    assert error_category_for(TimeoutError()) == "timeout"
    assert error_category_for(ValueError("bad json")) == "parse"
    assert error_category_for(RuntimeError("rate limit")) == "rate_limit"
    assert error_category_for(RuntimeError("unauthorized")) == "auth"
    assert error_category_for(RuntimeError("capability_unsupported")) == "capability_unsupported"
    assert error_category_for(RuntimeError("whatever")) == "unknown"


# ============================================================================
# AIEngine completion-boundary injection (unified, one recorder per outcome)
# ============================================================================

class _FakeProvider:
    """Provider double — raw text response, no real API."""

    def __init__(self, response_text="{\"title\": \"Report\", \"date\": \"2026-08-03\"}"):
        self.response_text = response_text
        self.calls = 0

    def suggest_filename(self, system_prompt, user_prompt, max_tokens=4096):
        self.calls += 1
        if self.response_text is None:
            raise RuntimeError("simulated provider failure")
        return self.response_text

    def test_connection(self):
        return True, "ok"


def _make_file_item(tmp_path, file_type="txt"):
    from src.models.file_item import FileItem, FileStatus
    path = tmp_path / f"doc.{file_type}"
    path.write_text("content", encoding="utf-8")
    item = FileItem(original_path=str(path), file_type=file_type, file_size=7)
    item.extracted_text = "sample content"
    item.status = FileStatus.EXTRACTED
    return item


def test_ai_engine_records_success_at_completion(tmp_path, store_path):
    from src.core.ai_engine import AIEngine
    from src.models.app_config import AppConfig
    recorder = UsageRecorder(store_path)
    provider = _FakeProvider()
    engine = AIEngine(AppConfig(), usage_recorder=recorder)
    engine._get_provider = lambda: provider  # inject fake provider, no real API

    item = _make_file_item(tmp_path, "txt")
    engine.suggest(item)

    records = recorder.records()
    assert len(records) == 1
    rec = records[0]
    assert rec.success is True
    assert rec.error_category == ""
    assert rec.provider_id == "deepseek"
    assert rec.model == "deepseek-flash"
    assert rec.content_kind == UsageContentKind.TEXT.value
    assert rec.cache_hit is False
    assert rec.input_tokens is None and rec.output_tokens is None  # unknown, not forged


def test_ai_engine_records_failure_with_category(tmp_path, store_path):
    from src.core.ai_engine import AIEngine
    from src.models.app_config import AppConfig
    recorder = UsageRecorder(store_path)
    engine = AIEngine(AppConfig(), usage_recorder=recorder)
    engine._get_provider = lambda: _FakeProvider(response_text=None)

    item = _make_file_item(tmp_path, "txt")
    engine.suggest(item)

    records = recorder.records()
    assert len(records) == 1
    assert records[0].success is False
    assert records[0].error_category != ""


def test_ai_engine_no_recorder_no_crash(tmp_path):
    from src.core.ai_engine import AIEngine
    from src.models.app_config import AppConfig
    engine = AIEngine(AppConfig(), usage_recorder=None)
    engine._get_provider = lambda: _FakeProvider()
    item = _make_file_item(tmp_path, "txt")
    engine.suggest(item)
    assert item.status.name == "SUGGESTED"


def test_ai_engine_recorder_failure_never_breaks_flow(tmp_path, store_path):
    from src.core.ai_engine import AIEngine
    from src.models.app_config import AppConfig

    class BrokenRecorder:
        def record(self, *a, **kw):
            raise RuntimeError("storage broken")

        def is_available(self):
            return False

    engine = AIEngine(AppConfig(), usage_recorder=BrokenRecorder())
    engine._get_provider = lambda: _FakeProvider()
    item = _make_file_item(tmp_path, "txt")
    engine.suggest(item)  # must not raise
    assert item.status.name == "SUGGESTED"


def test_ai_engine_records_content_kind(tmp_path, store_path):
    from src.core.ai_engine import AIEngine
    from src.models.app_config import AppConfig
    recorder = UsageRecorder(store_path)
    engine = AIEngine(AppConfig(), usage_recorder=recorder)
    engine._get_provider = lambda: _FakeProvider()
    for ext, kind in (("jpg", "image"), ("mp4", "video"), ("pdf", "scanned_pdf"), ("docx", "text")):
        item = _make_file_item(tmp_path, ext)
        engine.suggest(item)
    kinds = {r.content_kind for r in recorder.records()}
    assert kinds == {"image", "video", "scanned_pdf", "text"}


# ============================================================================
# Aggregate determinism
# ============================================================================

def test_aggregate_deterministic_order(store_path):
    recorder = UsageRecorder(store_path)
    recorder.record(rec(provider_id="qwen"))
    recorder.record(rec(provider_id="deepseek"))
    first = recorder.daily_summary(day=date(2026, 8, 3))
    second = recorder.daily_summary(day=date(2026, 8, 3))
    assert first == second
    assert [a.provider_id for a in first] == ["deepseek", "qwen"]
