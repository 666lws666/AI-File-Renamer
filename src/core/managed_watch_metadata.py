"""Pure, path-free managed Watch result metadata; never an Apply permit."""
from __future__ import annotations

from dataclasses import dataclass
from src.core.degradation import ContentKind
from src.core.processing_analysis import AnalysisOutcome, CloudAnalysisCoverage
from src.services.local_ai.preparation_protocol import (
    PreparationCoverage, PreparationError, WARNING_CODES, QUALITY_COUNTS,
)

_COVERAGE_FIELDS = (
    "content_kind", "text_source", "sections_processed", "sections_total",
    "text_truncated", "text_limit_reason", "pdf_total_pages",
    "text_page_indices", "rendered_page_indices", "video_duration_seconds",
    "video_timestamps_seconds",
)
_ARRAY_FIELDS = {
    "text_page_indices": 200,
    "rendered_page_indices": 8,
    "video_timestamps_seconds": 8,
}
_ALLOWED_KINDS = {
    "text": frozenset({"text", "document", "pdf"}),
    "image": frozenset({"image"}),
    "scanned_pdf": frozenset({"scanned_pdf"}),
    "video": frozenset({"video"}),
}
_RECORD_KEYS = frozenset({
    "version", "content_kind", "requested_quality", "effective_quality",
    "coverage_kind", "coverage", "warning_codes", "confidence",
})


class ManagedWatchMetadataError(ValueError):
    def __init__(self):
        super().__init__("invalid_managed_watch_metadata")


def _quality(value: str) -> str:
    if type(value) is not str or value not in QUALITY_COUNTS:
        raise ManagedWatchMetadataError()
    return "high" if value == "quality" else value


def _coverage(value):
    if type(value) not in (PreparationCoverage, CloudAnalysisCoverage):
        raise ManagedWatchMetadataError()
    values = {name: getattr(value, name) for name in _COVERAGE_FIELDS}
    if any(type(values[name]) is not str for name in (
        "content_kind", "text_source", "text_limit_reason"
    )):
        raise ManagedWatchMetadataError()
    try:
        return type(value)(**values)
    except (ValueError, TypeError, PreparationError):
        raise ManagedWatchMetadataError() from None


@dataclass(frozen=True, slots=True)
class ManagedWatchMetadata:
    content_kind: str
    requested_quality: str
    effective_quality: str
    coverage: PreparationCoverage | CloudAnalysisCoverage
    warning_codes: tuple[str, ...] = ()
    confidence: None = None

    def __post_init__(self):
        if (type(self.content_kind) is not str
                or self.content_kind not in _ALLOWED_KINDS
                or self.requested_quality != _quality(self.requested_quality)
                or self.effective_quality != _quality(self.effective_quality)
                or self.confidence is not None
                or type(self.warning_codes) is not tuple
                or len(self.warning_codes) > len(WARNING_CODES)
                or any(type(code) is not str or code not in WARNING_CODES
                       for code in self.warning_codes)
                or len(set(self.warning_codes)) != len(self.warning_codes)):
            raise ManagedWatchMetadataError()
        coverage = _coverage(self.coverage)
        if coverage.content_kind not in _ALLOWED_KINDS[self.content_kind]:
            raise ManagedWatchMetadataError()
        expected = {
            "character_limit": "text_character_limit",
            "utf8_limit": "text_utf8_limit",
            "section_limit": "section_limit",
        }.get(coverage.text_limit_reason)
        if expected and expected not in self.warning_codes:
            raise ManagedWatchMetadataError()
        if (coverage.text_source == "metadata_only"
                and "metadata_only" not in self.warning_codes):
            raise ManagedWatchMetadataError()


def metadata_from_outcome(outcome: AnalysisOutcome, requested_quality: str):
    if type(outcome) is not AnalysisOutcome or type(outcome.content_kind) is not ContentKind:
        raise ManagedWatchMetadataError()
    return ManagedWatchMetadata(
        content_kind=outcome.content_kind.value,
        requested_quality=_quality(requested_quality),
        effective_quality=_quality(outcome.effective_quality),
        coverage=_coverage(outcome.coverage),
        warning_codes=outcome.warning_codes,
    )


def encode_managed_metadata(metadata: ManagedWatchMetadata) -> dict:
    if type(metadata) is not ManagedWatchMetadata:
        raise ManagedWatchMetadataError()
    metadata.__post_init__()
    coverage = {name: getattr(metadata.coverage, name) for name in _COVERAGE_FIELDS}
    for name in _ARRAY_FIELDS:
        coverage[name] = list(coverage[name])
    return {
        "version": 1,
        "content_kind": metadata.content_kind,
        "requested_quality": metadata.requested_quality,
        "effective_quality": metadata.effective_quality,
        "coverage_kind": ("cloud" if type(metadata.coverage) is CloudAnalysisCoverage
                          else "local"),
        "coverage": coverage,
        "warning_codes": list(metadata.warning_codes),
        "confidence": None,
    }


def decode_managed_metadata(record: dict) -> ManagedWatchMetadata:
    if (type(record) is not dict or record.keys() != _RECORD_KEYS
            or type(record["version"]) is not int or record["version"] != 1
            or record["coverage_kind"] not in ("local", "cloud")
            or type(record["coverage_kind"]) is not str
            or record["confidence"] is not None
            or type(record["warning_codes"]) is not list
            or len(record["warning_codes"]) > len(WARNING_CODES)
            or type(record["coverage"]) is not dict
            or record["coverage"].keys() != frozenset(_COVERAGE_FIELDS)):
        raise ManagedWatchMetadataError()
    values = dict(record["coverage"])
    for name, cap in _ARRAY_FIELDS.items():
        value = values[name]
        if type(value) is not list or len(value) > cap:
            raise ManagedWatchMetadataError()
        values[name] = tuple(value)
    cls = CloudAnalysisCoverage if record["coverage_kind"] == "cloud" else PreparationCoverage
    try:
        coverage = cls(**values)
    except (ValueError, TypeError, PreparationError):
        raise ManagedWatchMetadataError() from None
    return ManagedWatchMetadata(
        record["content_kind"], record["requested_quality"],
        record["effective_quality"], coverage,
        tuple(record["warning_codes"]), record["confidence"],
    )


def auto_apply_review_reason(metadata: ManagedWatchMetadata) -> str:
    """Empty means eligible facts, not consent, authority or disk authorization."""
    if type(metadata) is not ManagedWatchMetadata:
        raise ManagedWatchMetadataError()
    metadata.__post_init__()
    coverage = metadata.coverage
    warnings = frozenset(metadata.warning_codes)
    if coverage.text_source == "metadata_only" or "metadata_only" in warnings:
        return "metadata_only"
    if (coverage.text_truncated
            or warnings & {"text_character_limit", "text_utf8_limit",
                           "section_limit", "pdf_page_limit"}):
        return "partial_content"
    if (metadata.content_kind == "text"
            and (coverage.text_source != "extracted_text" or "no_text_content" in warnings)):
        return "coverage_unavailable"
    if metadata.requested_quality != metadata.effective_quality:
        return "quality_degraded"
    if coverage.content_kind in {"pdf", "scanned_pdf"}:
        represented = set(coverage.text_page_indices + coverage.rendered_page_indices)
        total = coverage.pdf_total_pages
        if total is None:
            return "coverage_unavailable"
        if len(represented) != total:
            return "partial_content"
    elif metadata.content_kind == "text":
        if (coverage.text_source != "extracted_text"
                or coverage.sections_total is None
                or coverage.sections_total < 1):
            return "coverage_unavailable"
        if coverage.sections_processed != coverage.sections_total:
            return "partial_content"
    elif metadata.content_kind == "video":
        if (coverage.video_duration_seconds is None
                or len(coverage.video_timestamps_seconds)
                != QUALITY_COUNTS[metadata.effective_quality]):
            return "coverage_unavailable"
    # Complete image/scan understanding has no numeric confidence claim.
    # Planned video sampling is visible metadata, not an automatic veto.
    return ""
