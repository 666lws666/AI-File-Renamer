"""Strict, path-free result wire format for the trusted preparation child.

This is a size/identity boundary, not a parser exploit or network sandbox.
No media decoding, model loading, Qt, or filesystem reads occur in this module.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
import math
from pathlib import PureWindowsPath
import re
import struct

from src.core.provider_protocol import PreparedVisualPayload, prepare_visual_payload

MAX_REQUEST_BYTES = 12 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_TEXT_BYTES = 32768
MAX_VISUAL_BYTES = 16 * 1024 * 1024
MAX_FRAME_BYTES = 17 * 1024 * 1024
MAGIC = b"LPRP\x00\x01\r\n"
QUALITY_COUNTS = {"economy": 4, "balanced": 6, "high": 8, "quality": 8}
WARNING_CODES = frozenset({"text_character_limit", "text_utf8_limit", "section_limit", "pdf_page_limit", "video_sampled", "no_text_content", "metadata_only"})
ERROR_CODES = frozenset({"invalid_request", "invalid_result", "cancelled", "timeout", "closed", "cleanup_incomplete", "worker_failed", "input_rejected", "unsupported_type", "extraction_failed"})


class PreparationError(RuntimeError):
    """Only fixed safe codes cross the parent/child boundary."""

    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "worker_failed"
        super().__init__(self.code)


def _integer(value, maximum, *, minimum=1):
    return type(value) is int and minimum <= value <= maximum


def _finite(value, maximum, *, minimum=0):
    return type(value) in (int, float) and minimum < value <= maximum and math.isfinite(value)


@dataclass(frozen=True, slots=True)
class LocalPreparationLimits:
    max_file_bytes: int = 50 * 1024 * 1024
    max_text_chars: int = 4000
    max_text_utf8_bytes: int = MAX_TEXT_BYTES
    max_pdf_pages: int = 50
    max_visuals: int = 8
    max_video_frames: int = 8
    max_total_visual_bytes: int = MAX_VISUAL_BYTES
    max_image_bytes: int = 2 * 1024 * 1024
    max_image_long_edge: int = 2048
    max_image_pixels: int = 4_000_000
    max_image_decode_pixels: int = 40_000_000
    max_pdf_page_points: float = 14_400.0
    pdf_render_dpi: int = 144
    max_pdf_total_render_pixels: int = 16_000_000
    max_video_duration_seconds: float = 14_400.0
    max_video_source_pixels: int = 33_177_600
    max_video_decode_frames: int = 20_000
    video_candidate_window_seconds: float = 1.0
    max_video_candidate_frames: int = 90
    timeout_seconds: float = 60.0

    def __post_init__(self):
        maxima = {"max_file_bytes": 512*1024*1024, "max_text_chars": 1_000_000,
                  "max_text_utf8_bytes": MAX_TEXT_BYTES, "max_pdf_pages": 200,
                  "max_visuals": 8, "max_video_frames": 8,
                  "max_total_visual_bytes": MAX_VISUAL_BYTES, "max_image_bytes": 2*1024*1024,
                  "max_image_long_edge": 2048, "max_image_pixels": 4_000_000,
                  "max_image_decode_pixels": 40_000_000, "pdf_render_dpi": 144,
                  "max_pdf_total_render_pixels": 16_000_000,
                  "max_video_source_pixels": 33_177_600, "max_video_decode_frames": 20_000,
                  "max_video_candidate_frames": 90}
        floats = {"max_pdf_page_points": 14_400, "max_video_duration_seconds": 14_400,
                  "video_candidate_window_seconds": 1, "timeout_seconds": 300}
        if (any(not _integer(getattr(self, key), cap) for key, cap in maxima.items())
                or any(not _finite(getattr(self, key), cap) for key, cap in floats.items())
                or self.max_image_decode_pixels < self.max_image_pixels):
            raise ValueError("invalid preparation limits")


def validate_source_path(value: str) -> str:
    # Windows only production boundary: reject DOS devices, ADS, UNC and URLs
    # before any pathname operation. Runtime drive/reparse checks are in worker.
    if (type(value) is not str or not value or len(value.encode("utf-8")) > 8192
            or any(ord(c) < 32 for c in value) or not re.match(r"^[A-Za-z]:[\\/]", value)
            or ":" in value[2:] or value.startswith(("\\", "/"))):
        raise PreparationError("invalid_request")
    path = PureWindowsPath(value)
    for part in path.parts[1:]:
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if (stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem)
                or part.endswith((" ", ".")) or part in {".", ".."}):
            raise PreparationError("invalid_request")
    return value


@dataclass(frozen=True, slots=True)
class PreparationRequest:
    source_path: str = field(repr=False)
    limits: LocalPreparationLimits
    quality_mode: str

    def __post_init__(self):
        validate_source_path(self.source_path)
        if type(self.limits) is not LocalPreparationLimits or self.quality_mode not in QUALITY_COUNTS:
            raise PreparationError("invalid_request")
        # Reject an incompatible frame cap rather than silently mislabel quality.
        if PureWindowsPath(self.source_path).suffix.lower() in VIDEO_EXTENSIONS:
            count = QUALITY_COUNTS[self.quality_mode]
            if min(self.limits.max_video_frames, self.limits.max_visuals) < count:
                raise PreparationError("invalid_request")


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".avif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".m4v", ".ts", ".mts", ".m2ts", ".3gp", ".3g2", ".mxf", ".mpg", ".mpeg", ".ogv"})


@dataclass(frozen=True, slots=True)
class PreparationCoverage:
    content_kind: str
    text_source: str = "extracted_text"
    sections_processed: int = 0
    sections_total: int | None = None
    text_truncated: bool = False
    text_limit_reason: str = "complete"
    pdf_total_pages: int | None = None
    text_page_indices: tuple[int, ...] = ()
    rendered_page_indices: tuple[int, ...] = ()
    video_duration_seconds: float | None = None
    video_timestamps_seconds: tuple[float, ...] = ()

    def __post_init__(self):
        valid = (type(self.content_kind) is str
                 and self.content_kind in {"text", "document", "pdf", "scanned_pdf", "image", "video"}
                 and type(self.text_source) is str
                 and self.text_source in {"extracted_text", "none", "metadata_only"}
                 and _integer(self.sections_processed, 100_000, minimum=0)
                 and (self.sections_total is None or _integer(self.sections_total, 2**31-1, minimum=0))
                 and (self.sections_total is None or self.sections_processed <= self.sections_total)
                 and type(self.text_truncated) is bool
                 and type(self.text_limit_reason) is str
                 and self.text_limit_reason in {"complete", "character_limit", "utf8_limit", "section_limit"}
                 and self.text_truncated == (self.text_limit_reason != "complete"))
        if not valid:
            raise PreparationError("invalid_result")
        for indices, cap in ((self.text_page_indices, 100), (self.rendered_page_indices, 8)):
            if (type(indices) is not tuple or len(indices) > cap
                    or any(not _integer(i, 2**31-1, minimum=0) for i in indices)
                    or tuple(sorted(set(indices))) != indices):
                raise PreparationError("invalid_result")
        if self.pdf_total_pages is not None:
            if (not _integer(self.pdf_total_pages, 2**31-1)
                    or any(i >= self.pdf_total_pages for i in self.text_page_indices + self.rendered_page_indices)):
                raise PreparationError("invalid_result")
        elif self.text_page_indices or self.rendered_page_indices:
            raise PreparationError("invalid_result")
        timestamps = self.video_timestamps_seconds
        if type(timestamps) is not tuple or len(timestamps) > 8:
            raise PreparationError("invalid_result")
        if self.video_duration_seconds is not None:
            if (not _finite(self.video_duration_seconds, 14_400)
                    or any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= self.video_duration_seconds for t in timestamps)
                    or tuple(sorted(set(timestamps))) != timestamps):
                raise PreparationError("invalid_result")
        elif timestamps:
            raise PreparationError("invalid_result")
        if ((self.content_kind in {"pdf", "scanned_pdf"}) != (self.pdf_total_pages is not None)
                or (self.content_kind == "video") != (self.video_duration_seconds is not None)):
            raise PreparationError("invalid_result")


def _visual_descriptor(payload):
    if type(payload) is not PreparedVisualPayload:
        raise PreparationError("invalid_result")
    fields_ = ("kind", "mime_type", "width", "height", "source_index", "preprocessing_version", "provenance", "content_digest", "byte_size")
    return {key: getattr(payload, key) for key in fields_}


def _make_visual(descriptor, data):
    keys = {"kind", "mime_type", "width", "height", "source_index", "preprocessing_version", "provenance", "content_digest", "byte_size"}
    _keys(descriptor, keys)
    expected = {"resized_image": ("image-v1", "local-image"),
                "rendered_scan_page": ("pdf-v1+image-v1", "local-pdf-page"),
                "video_keyframe": ("video-v1+image-v1", "local-video-frame")}
    if (type(data) is not bytes
            or any(type(descriptor[key]) is not str for key in ("kind", "mime_type", "preprocessing_version", "provenance", "content_digest"))
            or descriptor["kind"] not in expected
            or (descriptor["preprocessing_version"], descriptor["provenance"]) != expected[descriptor["kind"]]
            or not _integer(descriptor["width"], 2048) or not _integer(descriptor["height"], 2048)
            or descriptor["width"] * descriptor["height"] > 4_000_000
            or not _integer(descriptor["source_index"], 2**31-1, minimum=0)
            or not _integer(descriptor["byte_size"], 2*1024*1024)
            or descriptor["byte_size"] != len(data)
            or type(descriptor["content_digest"]) is not str
            or hashlib.sha256(data).hexdigest() != descriptor["content_digest"]):
        raise PreparationError("invalid_result")
    mime = descriptor["mime_type"]
    signature = ((mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"))
                 or (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
                 or (mime == "image/webp" and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    if not signature:
        raise PreparationError("invalid_result")
    return prepare_visual_payload(data=data, **{k: v for k, v in descriptor.items() if k not in {"byte_size", "content_digest"}})


@dataclass(frozen=True, slots=True)
class LocalPreparationResult:
    text: str = field(repr=False)
    visuals: tuple[PreparedVisualPayload, ...] = field(repr=False)
    coverage: PreparationCoverage
    warning_codes: tuple[str, ...]
    effective_quality: str

    def __post_init__(self):
        if (type(self.text) is not str or len(self.text.encode("utf-8")) > MAX_TEXT_BYTES
                or type(self.visuals) is not tuple or len(self.visuals) > 8
                or type(self.coverage) is not PreparationCoverage
                or type(self.warning_codes) is not tuple or len(self.warning_codes) > len(WARNING_CODES)
                or any(type(c) is not str or c not in WARNING_CODES for c in self.warning_codes)
                or len(set(self.warning_codes)) != len(self.warning_codes)
                or type(self.effective_quality) is not str
                or self.effective_quality not in QUALITY_COUNTS):
            raise PreparationError("invalid_result")
        # Frozen objects may still have been altered with object.__setattr__.
        PreparationCoverage.__post_init__(self.coverage)
        for visual in self.visuals:
            _make_visual(_visual_descriptor(visual), visual.data)
        if sum(v.byte_size for v in self.visuals) > MAX_VISUAL_BYTES:
            raise PreparationError("invalid_result")
        coverage = self.coverage
        required_warning = {"character_limit": "text_character_limit", "utf8_limit": "text_utf8_limit", "section_limit": "section_limit"}.get(coverage.text_limit_reason)
        if required_warning is not None and required_warning not in self.warning_codes:
            raise PreparationError("invalid_result")
        if coverage.text_source == "metadata_only" and "metadata_only" not in self.warning_codes:
            raise PreparationError("invalid_result")
        kinds = {"image": "resized_image", "video": "video_keyframe", "pdf": "rendered_scan_page", "scanned_pdf": "rendered_scan_page"}
        if any(v.kind != kinds.get(coverage.content_kind) for v in self.visuals):
            raise PreparationError("invalid_result")
        if coverage.text_source != "extracted_text" and self.text:
            raise PreparationError("invalid_result")
        if coverage.content_kind == "image" and (len(self.visuals) != 1 or self.visuals[0].source_index != 0):
            raise PreparationError("invalid_result")
        if coverage.content_kind == "video" and (len(self.visuals) != QUALITY_COUNTS[self.effective_quality]
                or len(coverage.video_timestamps_seconds) != len(self.visuals)
                or tuple(v.source_index for v in self.visuals) != tuple(range(len(self.visuals)))):
            raise PreparationError("invalid_result")
        if coverage.content_kind in {"pdf", "scanned_pdf"}:
            if (tuple(v.source_index for v in self.visuals) != coverage.rendered_page_indices
                    or coverage.sections_processed != len(coverage.text_page_indices)
                    or coverage.text_page_indices != tuple(range(coverage.sections_processed))
                    or coverage.sections_total != coverage.pdf_total_pages):
                raise PreparationError("invalid_result")


def bound_text(text, *, max_chars, max_bytes):
    prefix = text[:max_chars]
    raw = prefix.encode("utf-8")
    bounded = raw[:max_bytes].decode("utf-8", errors="ignore")
    return bounded, bounded != text


def _keys(value, keys):
    if type(value) is not dict or value.keys() != keys:
        raise PreparationError("invalid_result")


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PreparationError("invalid_result")
            result[key] = value
        return result
    def constant(value):
        raise PreparationError("invalid_result")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def encode_request(request: PreparationRequest) -> str:
    if type(request) is not PreparationRequest:
        raise PreparationError("invalid_request")
    raw = _json({"version": 1, "source_path": request.source_path, "limits": asdict(request.limits), "quality_mode": request.quality_mode})
    if len(raw) > MAX_REQUEST_BYTES:
        raise PreparationError("invalid_request")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_request(encoded: str) -> PreparationRequest:
    try:
        if type(encoded) is not str or len(encoded) > 4*((MAX_REQUEST_BYTES+2)//3):
            raise ValueError
        raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError
        value = _strict_json(raw)
        _keys(value, {"version", "source_path", "limits", "quality_mode"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError
        _keys(value["limits"], {f.name for f in fields(LocalPreparationLimits)})
        return PreparationRequest(value["source_path"], LocalPreparationLimits(**value["limits"]), value["quality_mode"])
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, RecursionError, PreparationError):
        raise PreparationError("invalid_request") from None


def _result_header(result, text_bytes):
    return _json({"version": 1, "text_bytes": text_bytes, "visuals": [_visual_descriptor(v) for v in result.visuals],
                  "coverage": asdict(result.coverage), "warning_codes": result.warning_codes, "effective_quality": result.effective_quality})


def validate_result(result: LocalPreparationResult, *, limits: LocalPreparationLimits | None = None,
                    quality_mode: str | None = None) -> LocalPreparationResult:
    """Recheck object evidence and wire-equivalent budgets without a media frame."""
    try:
        if type(result) is not LocalPreparationResult:
            raise ValueError
        LocalPreparationResult.__post_init__(result)
        text_bytes = len(result.text.encode("utf-8"))
        header = _result_header(result, text_bytes)
        visual_bytes = sum(v.byte_size for v in result.visuals)
        if len(header) > MAX_HEADER_BYTES or 12 + len(header) + text_bytes + visual_bytes > MAX_FRAME_BYTES:
            raise ValueError
        if quality_mode is not None and result.effective_quality != quality_mode:
            raise ValueError
        if limits is not None:
            coverage = result.coverage
            if (len(result.text) > limits.max_text_chars or text_bytes > limits.max_text_utf8_bytes
                    or len(result.visuals) > limits.max_visuals or visual_bytes > limits.max_total_visual_bytes
                    or any(v.byte_size > limits.max_image_bytes or max(v.width, v.height) > limits.max_image_long_edge or v.width*v.height > limits.max_image_pixels for v in result.visuals)
                    or len(coverage.text_page_indices) > limits.max_pdf_pages
                    or len(coverage.rendered_page_indices) > limits.max_pdf_pages
                    or len(coverage.video_timestamps_seconds) > limits.max_video_frames
                    or (coverage.video_duration_seconds is not None and coverage.video_duration_seconds > limits.max_video_duration_seconds)):
                raise ValueError
        return result
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, PreparationError, OverflowError):
        raise PreparationError("invalid_result") from None


def encode_result(result: LocalPreparationResult) -> bytes:
    if type(result) is not LocalPreparationResult:
        raise PreparationError("invalid_result")
    text = result.text.encode("utf-8")
    header = _result_header(result, len(text))
    if len(header) > MAX_HEADER_BYTES:
        raise PreparationError("invalid_result")
    return MAGIC + struct.pack(">I", len(header)) + header + text + b"".join(v.data for v in result.visuals)


def decode_result(frame: bytes, *, limits: LocalPreparationLimits | None = None, quality_mode: str | None = None) -> LocalPreparationResult:
    try:
        if type(frame) is not bytes or not 12 <= len(frame) <= MAX_FRAME_BYTES or frame[:8] != MAGIC:
            raise ValueError
        header_size = struct.unpack(">I", frame[8:12])[0]
        if not 0 < header_size <= MAX_HEADER_BYTES or len(frame) < 12+header_size:
            raise ValueError
        header = _strict_json(frame[12:12+header_size])
        _keys(header, {"version", "text_bytes", "visuals", "coverage", "warning_codes", "effective_quality"})
        if type(header["version"]) is not int or header["version"] != 1 or not _integer(header["text_bytes"], MAX_TEXT_BYTES, minimum=0):
            raise ValueError
        descriptors = header["visuals"]
        if type(descriptors) is not list or len(descriptors) > 8:
            raise ValueError
        sizes = []
        for item in descriptors:
            if type(item) is not dict or not _integer(item.get("byte_size"), 2*1024*1024):
                raise ValueError
            sizes.append(item["byte_size"])
        if sum(sizes) > MAX_VISUAL_BYTES or 12+header_size+header["text_bytes"]+sum(sizes) != len(frame):
            raise ValueError
        offset = 12+header_size
        text = frame[offset:offset+header["text_bytes"]].decode("utf-8")
        offset += header["text_bytes"]
        visuals = []
        for descriptor, size in zip(descriptors, sizes, strict=True):
            visuals.append(_make_visual(descriptor, frame[offset:offset+size]))
            offset += size
        coverage = header["coverage"]
        _keys(coverage, {f.name for f in fields(PreparationCoverage)})
        for key in ("text_page_indices", "rendered_page_indices", "video_timestamps_seconds"):
            if type(coverage[key]) is not list:
                raise ValueError
            coverage[key] = tuple(coverage[key])
        if type(header["warning_codes"]) is not list:
            raise ValueError
        result = LocalPreparationResult(text, tuple(visuals), PreparationCoverage(**coverage), tuple(header["warning_codes"]), header["effective_quality"])
        return validate_result(result, limits=limits, quality_mode=quality_mode)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, PreparationError, OverflowError):
        raise PreparationError("invalid_result") from None
