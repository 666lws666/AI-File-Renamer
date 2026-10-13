"""Strict preparation wire contract; synthetic content only."""
import base64
import importlib
import json
import struct
from dataclasses import FrozenInstanceError, replace

import pytest


def protocol():
    return importlib.import_module("src.services.local_ai.preparation_protocol")


def test_protocol_is_available():
    assert importlib.util.find_spec("src.services.local_ai.preparation_protocol") is not None


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), 10**100])
@pytest.mark.parametrize("field", ["max_file_bytes", "max_text_chars", "max_text_utf8_bytes", "max_pdf_pages", "max_video_frames", "max_image_pixels", "max_video_duration_seconds", "timeout_seconds"])
def test_limits_reject_unbounded_values(field, value):
    with pytest.raises(ValueError):
        protocol().LocalPreparationLimits(**{field: value})


def test_request_round_trip_is_private_strict_and_frozen(tmp_path):
    p = protocol()
    request = p.PreparationRequest(str(tmp_path / "私人中文.txt"), p.LocalPreparationLimits(), "high")
    encoded = p.encode_request(request)
    assert len(base64.urlsafe_b64decode(encoded)) <= 12 * 1024
    assert p.decode_request(encoded) == request
    assert "私人" not in repr(request)
    with pytest.raises(FrozenInstanceError):
        request.quality_mode = "economy"
    for raw in [b'{"version":1,"version":1}', b'{"x":NaN}', b'{}', b'[]']:
        with pytest.raises(p.PreparationError):
            p.decode_request(base64.urlsafe_b64encode(raw).decode())


@pytest.mark.parametrize("path", ["https://example.test/a", r"\\server\share\x.txt", r"\\?\C:\x.txt", r"\\.\pipe\x", "relative.txt", "C:/x.txt:stream", "C:/NUL.txt"])
def test_request_rejects_nonlocal_paths(path):
    p = protocol()
    with pytest.raises(p.PreparationError):
        p.PreparationRequest(path, p.LocalPreparationLimits(), "balanced")


def test_result_round_trip_and_strict_frame_validation():
    p = protocol()
    result = p.LocalPreparationResult("秘密真实文字", (), p.PreparationCoverage(content_kind="text", sections_processed=1, sections_total=1), (), "balanced")
    frame = p.encode_result(result)
    assert p.decode_result(frame) == result
    assert "秘密" not in repr(result)
    for bad in [frame + b"extra", frame[:-1], b"wrong" + frame, frame[:8] + struct.pack(">I", 65537) + frame[12:]]:
        with pytest.raises(p.PreparationError):
            p.decode_result(bad)


def test_quality_cap_cannot_silently_reduce_video_policy(tmp_path):
    p = protocol()
    with pytest.raises(p.PreparationError):
        p.PreparationRequest(str(tmp_path / "a.mp4"), p.LocalPreparationLimits(max_video_frames=4), "high")


def test_byte_limit_truncates_on_utf8_boundary_truthfully():
    p = protocol()
    text, truncated = p.bound_text("中文" * 20, max_chars=100, max_bytes=7)
    assert text == "中文" and truncated
    assert p.bound_text("中文", max_chars=2, max_bytes=6) == ("中文", False)


def image_payload(data=None, *, index=0):
    from src.core.provider_protocol import prepare_visual_payload
    return prepare_visual_payload(kind="rendered_scan_page", mime_type="image/jpeg", data=data or b"\xff\xd8\xffsynthetic\xff\xd9", width=10, height=10, source_index=index, preprocessing_version="pdf-v1+image-v1", provenance="local-pdf-page")


def valid_visual_result(*, giant=False):
    p = protocol()
    data = b"\xff\xd8\xff" + b"x"*(2*1024*1024-5) + b"\xff\xd9" if giant else None
    count = 8 if giant else 1
    coverage = p.PreparationCoverage(content_kind="pdf", sections_processed=count, sections_total=count, pdf_total_pages=count, text_page_indices=tuple(range(count)), rendered_page_indices=tuple(range(count)))
    return p.LocalPreparationResult("x"*32768 if giant else "text", tuple(image_payload(data, index=i) for i in range(count)), coverage, (), "balanced")


def mutate_header(frame, mutate):
    size = struct.unpack(">I", frame[8:12])[0]
    header = json.loads(frame[12:12+size])
    mutate(header)
    raw = json.dumps(header, separators=(",", ":"), allow_nan=True).encode()
    return frame[:8] + struct.pack(">I", len(raw)) + raw + frame[12+size:]


@pytest.mark.parametrize("mutation", [
    lambda h: h.update(unexpected="path"),
    lambda h: h.update(text_bytes=-1),
    lambda h: h.update(text_bytes=True),
    lambda h: h["visuals"][0].update(byte_size=2**60),
    lambda h: h["visuals"][0].update(content_digest="0"*64),
    lambda h: h["visuals"][0].update(mime_type="application/pdf"),
    lambda h: h["visuals"][0].update(width=True),
    lambda h: h["visuals"][0].update(provenance="C:/secret"),
    lambda h: h["coverage"].update(extra="source"),
    lambda h: h["coverage"].update(rendered_page_indices=[100]),
    lambda h: h["coverage"].update(text_page_indices=[0, 0]),
    lambda h: h["coverage"].update(video_duration_seconds=float("nan")),
    lambda h: h.update(warning_codes=["C:/secret"]),
    lambda h: h.update(effective_quality="arbitrary"),
])
def test_hostile_result_fields_rejected(mutation):
    p = protocol()
    with pytest.raises(p.PreparationError):
        p.decode_result(mutate_header(p.encode_result(valid_visual_result()), mutation))


def test_duplicate_json_and_bad_signatures_rejected():
    p = protocol()
    frame = p.encode_result(valid_visual_result())
    size = struct.unpack(">I", frame[8:12])[0]
    header = frame[12:12+size]
    header = b'{"version":1,' + header[1:]
    with pytest.raises(p.PreparationError):
        p.decode_result(frame[:8]+struct.pack(">I",len(header))+header+frame[12+size:])
    with pytest.raises(p.PreparationError):
        replace(valid_visual_result(), visuals=(image_payload(b"not an image"),))


def test_full_16mib_visual_plus_text_frame_fits_17mib_parent_budget():
    p = protocol()
    result = valid_visual_result(giant=True)
    frame = p.encode_result(result)
    assert 16*1024*1024 < len(frame) < 17*1024*1024
    decoded = p.decode_result(frame, limits=p.LocalPreparationLimits(max_text_chars=32768), quality_mode="balanced")
    assert decoded.text == result.text and len(decoded.visuals) == 8


@pytest.mark.parametrize("change", [{"max_text_chars": 2}, {"max_total_visual_bytes": 8}, {"max_image_bytes": 8}, {"max_image_long_edge": 5}, {"max_image_pixels": 50}])
def test_parent_rechecks_captured_limits(change):
    p = protocol()
    with pytest.raises(p.PreparationError):
        p.decode_result(p.encode_result(valid_visual_result()), limits=p.LocalPreparationLimits(**change))


def test_truncation_requires_matching_warning_and_pdf_coverage_alignment():
    p = protocol()
    result = valid_visual_result()
    with pytest.raises(p.PreparationError):
        replace(result, coverage=replace(result.coverage, text_truncated=True, text_limit_reason="utf8_limit"))
    with pytest.raises(p.PreparationError):
        replace(result, coverage=replace(result.coverage, sections_processed=0))

