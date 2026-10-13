"""In-process preparation boundary; synthetic payloads, never media/model IO."""
import hashlib

import pytest

from src.core.provider_protocol import prepare_visual_payload
from src.services.local_ai import preparation_protocol as protocol


def visual(kind="rendered_scan_page", index=0):
    version, provenance = {
        "resized_image": ("image-v1", "local-image"),
        "rendered_scan_page": ("pdf-v1+image-v1", "local-pdf-page"),
        "video_keyframe": ("video-v1+image-v1", "local-video-frame"),
    }[kind]
    return prepare_visual_payload(kind=kind, mime_type="image/png", data=b"\x89PNG\r\n\x1a\nsynthetic",
        width=10, height=10, source_index=index, preprocessing_version=version, provenance=provenance)


def result(kind="pdf"):
    if kind == "video":
        coverage = protocol.PreparationCoverage("video", text_source="none", video_duration_seconds=10,
            video_timestamps_seconds=(0., 2., 4., 6.))
        return protocol.LocalPreparationResult("", tuple(visual("video_keyframe", i) for i in range(4)),
            coverage, ("video_sampled",), "economy")
    if kind == "text":
        return protocol.LocalPreparationResult("中文text", (), protocol.PreparationCoverage("text"), (), "balanced")
    coverage = protocol.PreparationCoverage("pdf", sections_processed=2, sections_total=2, pdf_total_pages=2,
        text_page_indices=(0, 1), rendered_page_indices=(0, 1))
    return protocol.LocalPreparationResult("中文text", (visual(index=0), visual(index=1)), coverage, (), "balanced")


@pytest.mark.parametrize("kind", ["text", "pdf", "video"])
def test_validator_matches_wire_roundtrip_without_copying_payloads(kind):
    value = result(kind)
    limits = protocol.LocalPreparationLimits()
    expected = protocol.decode_result(protocol.encode_result(value), limits=limits, quality_mode=value.effective_quality)
    validated = protocol.validate_result(value, limits=limits, quality_mode=value.effective_quality)
    assert validated == expected
    assert validated is value
    assert validated.visuals is value.visuals


@pytest.mark.parametrize("kind,change", [
    ("pdf", {"max_text_chars": 3}), ("pdf", {"max_text_utf8_bytes": 9}),
    ("pdf", {"max_visuals": 1}), ("pdf", {"max_total_visual_bytes": 20}),
    ("pdf", {"max_image_bytes": 8}), ("pdf", {"max_image_long_edge": 5}),
    ("pdf", {"max_image_pixels": 50}), ("pdf", {"max_pdf_pages": 1}),
    ("video", {"max_video_frames": 3}), ("video", {"max_video_duration_seconds": 5}),
])
def test_validator_preserves_every_caller_limit(kind, change):
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(result(kind), limits=protocol.LocalPreparationLimits(**change))


def test_validator_rejects_wrong_quality():
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(result(), quality_mode="high")


@pytest.mark.parametrize("field,value", [
    ("text", 42), pytest.param("text", "x" * (protocol.MAX_TEXT_BYTES + 1), id="text-over-utf8-cap"), ("text", "\ud800"),
    ("visuals", []), ("visuals", (object(),)), ("coverage", object()),
    ("warning_codes", []), ("warning_codes", ("C:/private",)),
    ("warning_codes", ("pdf_page_limit", "pdf_page_limit")),
    ("effective_quality", "invalid"), ("effective_quality", []),
])
def test_validator_rechecks_tampered_result_fields(field, value):
    prepared = result()
    object.__setattr__(prepared, field, value)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


@pytest.mark.parametrize("field,value", [
    ("kind", []), ("kind", "resized_image"), ("mime_type", "application/pdf"),
    ("width", True), ("height", 0), ("source_index", False), ("source_index", 9),
    ("preprocessing_version", "image-v1"), ("provenance", "C:/private"),
    ("content_digest", "0" * 64), ("byte_size", True), ("byte_size", 20),
    ("data", bytearray(b"\x89PNG\r\n\x1a\nsynthetic")),
])
def test_validator_rechecks_tampered_visual_fields(field, value):
    prepared = result()
    object.__setattr__(prepared.visuals[0], field, value)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


def test_validator_rechecks_signature_even_with_matching_digest_and_size():
    prepared = result()
    payload = prepared.visuals[0]
    data = b"not an image"
    for field, value in (("data", data), ("byte_size", len(data)), ("content_digest", hashlib.sha256(data).hexdigest())):
        object.__setattr__(payload, field, value)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


@pytest.mark.parametrize("field,value", [
    ("content_kind", []), ("content_kind", "text"), ("text_source", "none"),
    ("sections_processed", True), ("sections_total", 1), ("text_truncated", 1),
    ("text_limit_reason", "utf8_limit"), ("pdf_total_pages", 1),
    ("text_page_indices", [0, 1]), ("text_page_indices", (0, 0)),
    ("rendered_page_indices", (1, 0)), ("video_duration_seconds", float("nan")),
    ("video_timestamps_seconds", (0.,)),
])
def test_validator_reruns_tampered_coverage_validation(field, value):
    prepared = result()
    object.__setattr__(prepared.coverage, field, value)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


class StringLookalike(str):
    pass


@pytest.mark.parametrize("owner,field,value", [
    ("result", "effective_quality", StringLookalike("balanced")),
    ("coverage", "content_kind", StringLookalike("pdf")),
    ("coverage", "text_source", StringLookalike("extracted_text")),
    ("coverage", "text_limit_reason", StringLookalike("complete")),
    ("visual", "kind", StringLookalike("rendered_scan_page")),
    ("visual", "mime_type", StringLookalike("image/png")),
    ("visual", "preprocessing_version", StringLookalike("pdf-v1+image-v1")),
    ("visual", "provenance", StringLookalike("local-pdf-page")),
])
def test_validator_requires_exact_descriptor_and_coverage_primitives(owner, field, value):
    prepared = result()
    target = {"result": prepared, "coverage": prepared.coverage, "visual": prepared.visuals[0]}[owner]
    object.__setattr__(target, field, value)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


@pytest.mark.parametrize("cap", ["MAX_HEADER_BYTES", "MAX_FRAME_BYTES"])
def test_validator_preserves_equivalent_wire_byte_budget(monkeypatch, cap):
    prepared = result()
    frame = protocol.encode_result(prepared)
    size = int.from_bytes(frame[8:12], "big") if cap == "MAX_HEADER_BYTES" else len(frame)
    monkeypatch.setattr(protocol, cap, size)
    assert protocol.validate_result(prepared) is prepared
    monkeypatch.setattr(protocol, cap, size - 1)
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(prepared)


def test_decoder_delegates_caller_validation(monkeypatch):
    prepared = result()
    frame = protocol.encode_result(prepared)
    limits = protocol.LocalPreparationLimits()
    calls = []
    validate = protocol.validate_result
    def observe(value, **kwargs):
        calls.append((value, kwargs))
        return validate(value, **kwargs)
    monkeypatch.setattr(protocol, "validate_result", observe)
    assert protocol.decode_result(frame, limits=limits, quality_mode="balanced") == prepared
    assert len(calls) == 1
    assert calls[0][1] == {"limits": limits, "quality_mode": "balanced"}


def test_validator_rejects_wrong_result_type_safely():
    with pytest.raises(protocol.PreparationError, match="^invalid_result$"):
        protocol.validate_result(object())
