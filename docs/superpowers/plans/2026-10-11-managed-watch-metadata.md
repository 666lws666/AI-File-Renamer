# Managed Watch Metadata and Eligibility Facts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development with TDD, a fresh scoped spec/quality reviewer and root-owned verification/Git.

**Goal:** Add a path-free immutable metadata codec and factual Auto Apply review-reason policy without inventing model confidence or activating Watch.

**Architecture:** One small pure-Python module projects the reviewed AnalysisOutcome into allowlisted persistent metadata. It retains existing local/cloud coverage bounds and distinguishes complete planned video sampling from actual omitted/truncated coverage. Queue/journal integration and Qt orchestration are separate dependent tasks; this module grants neither processing authority nor file-operation permission.

**Tech Stack:** Existing frozen AnalysisOutcome/PreparationCoverage/CloudAnalysisCoverage and ContentKind; standard dataclasses; pytest under the guarded Windows project interpreter. No dependencies, filesystem or Qt.

## Global Constraints

- Continue only after C2A has passed scoped review/checkpoint; root owns Git, one source writer at a time, existing isolated codex/local-privacy-mode worktree. Do not edit main, merge or push.
- Keep the existing per-watch Auto Apply selection as consent. Do not introduce a default-off confidence opt-in or silently disable saved modes.
- Managed confidence is always None. It is not zero, failed, or a calibrated 1.0; it never triggers model retries to manufacture a probability.
- Strict invalid naming, insufficient evidence and missing required fields remain upstream hard failures. This helper cannot convert those failures into suggestions.
- Actual truncation, omitted pages/sections, metadata-only evidence, unknown required coverage or an unexpected quality downgrade requires visible review. Planned 4/6/8-frame video sampling is factual metadata and is not itself an Auto Apply veto.
- Quality aliases high/quality are equivalent; preserve complete economy as eligible facts, not low confidence.
- Store only reviewed content kind, quality, coverage counts/indices/timestamps and fixed warnings. No name, source path, raw content, context, event, credential, Provider profile, prompt, model identity or AnalysisWork in this codec.
- The local/cloud coverage label controls structural count validation, not trusted processing provenance. Reading this JSON cannot reconstruct current authority or consent.
- No cloud API/key/Credential Manager/private input, system configuration, dependency installation, actual model call, Golden change, resource/Provider/file-engine/Watch-controller/UI modification or production activation.

## Task 1: immutable metadata codec and factual review-reason policy

**Files:**

- Create src/core/managed_watch_metadata.py.
- Create tests/unit/test_managed_watch_metadata.py.
- No existing source/test changes in this independently reviewable task.

**Interfaces:**

- Consumes exact AnalysisOutcome and exact PreparationCoverage or CloudAnalysisCoverage; no bearer/work/context checks are substituted here.
- Produces frozen ManagedWatchMetadata, metadata_from_outcome(outcome, requested_quality), encode_managed_metadata(metadata), decode_managed_metadata(record), auto_apply_review_reason(metadata).
- The empty review reason means only structurally eligible facts; the next Qt acceptance task must still check authentic current work, Watch incarnation/version, fingerprint, consent and durable intent before a file-lane reservation.
- New metadata record version1 is separate from ReviewQueue/AutoApplyJournal schema. No store migration happens here.
- Fixed reasons: metadata_only, partial_content, quality_degraded, coverage_unavailable. Invalid metadata raises only invalid_managed_watch_metadata; never embed raw values in error text.

- [ ] **Step 1: Write these real failing pure-domain tests before source implementation.**

The None context in outcome() is deliberate: this task proves only metadata shape/policy and cannot be called an authority or model-quality Gate.

```python
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

```

- [ ] **Step 2: Run the new test target with the root-supplied strong guard and record actual RED.**

Logical command: pytest tests/unit/test_managed_watch_metadata.py -q.
Expected RED before source creation: missing src.core.managed_watch_metadata, not a fabricated numerical score failure. Record native process exit and forbidden accesses; do not weaken network/native-credential guards or use a system Python.

- [ ] **Step 3: Implement the complete pure module below, preserving its field allowlist and bounds.**

The implementation is intentionally not a replacement preparation wire parser or a persisted WorkContext. The existing constructor limits remain authoritative.

```python
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

```

- [ ] **Step 4: Run GREEN plus unchanged core-shape regressions.**

Use the root-supplied guarded Windows harness for exactly tests/unit/test_managed_watch_metadata.py, tests/unit/test_processing_analysis.py, tests/unit/test_local_preparation_protocol.py and tests/unit/test_analysis_catalog.py. All three unchanged target paths were verified in this worktree before handoff.

Expected: all selected assertions pass, native exit0, forbidden accesses0, no new skip/xfail/changed Golden. Report warnings instead of suppressing them.

- [ ] **Step 5: Freeze for root review and checkpoint.**

Write exact RED/GREEN commands/outputs, public interfaces, exact two-file list, hashes, scope and self-review to .superpowers/sdd/managed-watch-metadata-report.md. No staging/committing by the implementer. Root generates the full diff package, obtains fresh spec/quality review, independently runs the covering tests and commits these two files only after approval. Production Watch remains unavailable until later persistence/orchestration/runtime tasks pass.

## Root self-review boundary

The helper has no disk/network/credential/Qt operation and makes no naming, calibration or consent claim. Coverage projection is explicitly allowlisted, never automatic serialization of all future dataclass fields. PDF completeness uses bounded set size, not allocating range(total_pages); cloud200-page versus local100-page text-summary bounds remain distinct. Planned video count follows the existing selected quality4/6/8. Old queue/journal/confidence migration is outside this task and must not be implied complete.
