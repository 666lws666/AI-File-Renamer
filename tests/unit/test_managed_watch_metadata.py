"""Pure metadata tests: not model, authority or disk-authorization evidence."""
from dataclasses import FrozenInstanceError, replace
import copy
import json
import pytest
from src.core.degradation import ContentKind
from src.core.processing_analysis import AnalysisOutcome, CloudAnalysisCoverage
from src.services.local_ai.preparation_protocol import PreparationCoverage
from src.core.managed_watch_metadata import (
    ManagedWatchMetadata, ManagedWatchMetadataError, metadata_from_outcome,
    encode_managed_metadata, decode_managed_metadata, auto_apply_review_reason,
)


def outcome(kind, coverage, *, quality="balanced", warnings=()):
    return AnalysisOutcome("DO_NOT_PERSIST_PRIVATE_NAME.txt", None, quality, kind,
                           "DO_NOT_PERSIST_ENGINE_SECRET", coverage, warnings)


def complete_text():
    return PreparationCoverage("text", sections_processed=1, sections_total=1)


def image():
    return PreparationCoverage("image", text_source="none")


def scan(indices=(0, 1)):
    return PreparationCoverage("scanned_pdf", text_source="none", sections_total=2,
                               pdf_total_pages=2, rendered_page_indices=indices)


def video(count=6):
    return PreparationCoverage("video", text_source="none",
        video_duration_seconds=10.0,
        video_timestamps_seconds=tuple(float(i) for i in range(count)))


@pytest.mark.parametrize("kind,coverage,warnings", [
    (ContentKind.TEXT, complete_text(), ()),
    (ContentKind.IMAGE, image(), ("no_text_content",)),
    (ContentKind.SCANNED_PDF, scan(), ("no_text_content",)),
    (ContentKind.VIDEO, video(), ("video_sampled", "no_text_content")),
])
def test_complete_facts_remain_eligible_without_inventing_confidence(kind, coverage, warnings):
    metadata = metadata_from_outcome(outcome(kind, coverage, warnings=warnings), "balanced")
    assert metadata.confidence is None
    assert auto_apply_review_reason(metadata) == ""
    assert decode_managed_metadata(encode_managed_metadata(metadata)) == metadata
    with pytest.raises(FrozenInstanceError):
        metadata.confidence = 1.0


@pytest.mark.parametrize("coverage,warnings,reason", [
    (replace(complete_text(), text_truncated=True, text_limit_reason="character_limit"),
     ("text_character_limit",), "partial_content"),
    (PreparationCoverage("text", sections_processed=1, sections_total=None),
     (), "coverage_unavailable"),
    (PreparationCoverage("text", sections_processed=1, sections_total=2),
     (), "partial_content"),
    (PreparationCoverage("text", text_source="metadata_only"),
     ("metadata_only",), "metadata_only"),
    (complete_text(), ("no_text_content",), "coverage_unavailable"),
])
def test_incomplete_text_never_becomes_eligible(coverage, warnings, reason):
    metadata = metadata_from_outcome(outcome(ContentKind.TEXT, coverage, warnings=warnings),
                                     "balanced")
    assert auto_apply_review_reason(metadata) == reason


def test_partial_scan_and_missing_video_samples_require_review():
    partial = metadata_from_outcome(outcome(ContentKind.SCANNED_PDF, scan((0,))), "balanced")
    assert auto_apply_review_reason(partial) == "partial_content"
    incomplete = metadata_from_outcome(outcome(ContentKind.VIDEO, video(4),
        warnings=("video_sampled",)), "balanced")
    assert auto_apply_review_reason(incomplete) == "coverage_unavailable"


def test_quality_aliases_are_equivalent_but_downgrade_is_visible():
    high = metadata_from_outcome(outcome(ContentKind.TEXT, complete_text(), quality="quality"), "high")
    assert high.effective_quality == high.requested_quality == "high"
    assert auto_apply_review_reason(high) == ""
    reduced = metadata_from_outcome(outcome(ContentKind.TEXT, complete_text(), quality="economy"), "high")
    assert auto_apply_review_reason(reduced) == "quality_degraded"


def test_cloud_two_hundred_page_summary_roundtrips_without_local_wire_relaxation():
    coverage = CloudAnalysisCoverage("pdf", sections_processed=200, sections_total=200,
        pdf_total_pages=200, text_page_indices=tuple(range(200)))
    metadata = metadata_from_outcome(outcome(ContentKind.TEXT, coverage), "balanced")
    record = encode_managed_metadata(metadata)
    assert record["coverage_kind"] == "cloud"
    assert decode_managed_metadata(record) == metadata
    assert auto_apply_review_reason(metadata) == ""
    record["coverage_kind"] = "local"
    with pytest.raises(ManagedWatchMetadataError, match="^invalid_managed_watch_metadata$"):
        decode_managed_metadata(record)


def test_encoded_data_omits_name_context_engine_and_does_not_mutate_input():
    metadata = metadata_from_outcome(outcome(ContentKind.TEXT, complete_text()), "balanced")
    record = encode_managed_metadata(metadata)
    before = copy.deepcopy(record)
    raw = json.dumps(record, allow_nan=False)
    assert "DO_NOT_PERSIST" not in raw
    assert "source_path" not in raw and "context" not in raw and "suggested_name" not in raw
    assert decode_managed_metadata(record) == metadata
    assert record == before


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(version=2),
    lambda r: r.update(version=True),
    lambda r: r.update(confidence=0.9),
    lambda r: r.update(secret="forbidden"),
    lambda r: r.update(warning_codes=["C:/private/path"]),
    lambda r: r["coverage"].update(source_path="C:/private/path"),
    lambda r: r["coverage"].update(video_timestamps_seconds=[1] * 9),
    lambda r: r["coverage"].update(text_page_indices=list(range(201))),
    lambda r: r.update(content_kind="video"),
])
def test_invalid_records_fail_with_fixed_safe_error(mutate):
    record = encode_managed_metadata(metadata_from_outcome(
        outcome(ContentKind.TEXT, complete_text()), "balanced"))
    mutate(record)
    with pytest.raises(ManagedWatchMetadataError, match="^invalid_managed_watch_metadata$"):
        decode_managed_metadata(record)


def test_missing_warning_and_foreign_coverage_are_not_accepted():
    truncated = replace(complete_text(), text_truncated=True, text_limit_reason="character_limit")
    with pytest.raises(ManagedWatchMetadataError):
        metadata_from_outcome(outcome(ContentKind.TEXT, truncated), "balanced")
    with pytest.raises(ManagedWatchMetadataError):
        ManagedWatchMetadata("text", "balanced", "balanced", {"content_kind": "text"})
