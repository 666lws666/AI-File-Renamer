"""Fixed trusted preparation entry. No model, transport, credentials or GUI.

All third-party parse/decode occurs in this owned child. Its current-user token is
not a parser exploit sandbox. Video continues using both existing nested-I/O
guards. The binary protocol is written directly to the inherited Windows HANDLE
so console=False frozen executables do not depend on sys.stdout being present.
"""
from __future__ import annotations

import contextlib
import ctypes
from dataclasses import replace
import os
from pathlib import Path
import stat
import sys
import time

from .preparation_protocol import (
    IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, QUALITY_COUNTS,
    LocalPreparationResult, PreparationCoverage, PreparationError,
    bound_text, decode_request, encode_result, validate_source_path,
)


def _local_source(value, byte_limit):
    validate_source_path(value)
    path = Path(value)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint
    if kernel.GetDriveTypeW(path.anchor) not in {2, 3, 5, 6}:
        raise PreparationError("input_rejected")
    # Refuse reparse points before following them, including local junctions to
    # network targets; do not first resolve an arbitrary remote link.
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PreparationError("input_rejected")
    if not stat.S_ISREG(info.st_mode) or info.st_size > byte_limit:
        raise PreparationError("input_rejected")
    return path


def _without_sheet_labels(text, names):
    # Remove actual extractor labels, including a truncated last label. Do not
    # return author/title/sheet metadata or treat labels as comprehension.
    for name in names:
        label = f"[Sheet: {name}]"
        text = text.replace(label, "")
        marker = text.rfind("[Sheet: ")
        if marker >= 0 and label.startswith(text[marker:]):
            text = text[:marker]
    return text.strip()


def prepare_request(request):
    """Child-only composition; this function is never a parent fallback."""
    from src.services.media.image_preprocessor import ImagePreprocessConfig, ImagePreprocessor

    limits = request.limits
    path = _local_source(request.source_path, limits.max_file_bytes)
    deadline = time.monotonic()+limits.timeout_seconds
    cancelled = lambda: time.monotonic() >= deadline
    image_config = ImagePreprocessConfig(
        max_long_edge=limits.max_image_long_edge, max_pixels=limits.max_image_pixels,
        max_decode_pixels=limits.max_image_decode_pixels,
        max_input_bytes=min(limits.max_file_bytes, 50*1024*1024),
        max_output_bytes=min(limits.max_image_bytes, limits.max_total_visual_bytes // limits.max_visuals),
        timeout_seconds=limits.timeout_seconds)
    extension = path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        visual = ImagePreprocessor(image_config).process_file(path, source_index=0, cancellation_token=cancelled)
        return LocalPreparationResult("", (visual,), PreparationCoverage(content_kind="image", text_source="none"), (), request.quality_mode)
    if extension in VIDEO_EXTENSIONS:
        from src.services.media.keyframe_extractor import KeyframeExtractConfig, VideoKeyframeExtractor
        config = KeyframeExtractConfig(
            max_input_bytes=limits.max_file_bytes, max_duration_seconds=limits.max_video_duration_seconds,
            max_source_pixels=limits.max_video_source_pixels, max_decode_frames=limits.max_video_decode_frames,
            candidate_window_seconds=limits.video_candidate_window_seconds,
            max_candidate_frames_per_sample=limits.max_video_candidate_frames,
            max_total_output_bytes=limits.max_total_visual_bytes,
            timeout_seconds=limits.timeout_seconds, image_config=image_config)
        result = VideoKeyframeExtractor(config).extract_file(path,
            quality_mode="quality" if request.quality_mode == "high" else request.quality_mode,
            max_frames=QUALITY_COUNTS[request.quality_mode], cancellation_token=cancelled)
        coverage = PreparationCoverage(content_kind="video", text_source="none",
            video_duration_seconds=result.duration_seconds, video_timestamps_seconds=result.timestamps_seconds)
        return LocalPreparationResult("", result.payloads, coverage, ("video_sampled",), request.quality_mode)

    if extension not in {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".html", ".htm", ".rtf"}:
        raise PreparationError("unsupported_type")
    from src.core.content_extractor import extract
    from src.models.file_item import FileItem, FileStatus
    item = FileItem(original_path=path)
    extract(item, max_chars=limits.max_text_chars, max_pdf_pages=limits.max_pdf_pages,
            cancellation_token=cancelled, redacted_diagnostics=True)
    if item.status != FileStatus.EXTRACTED:
        raise PreparationError("extraction_failed")
    text, metadata = item.extracted_text, item.metadata
    if extension in {".xlsx", ".xls"}:
        text = _without_sheet_labels(text, metadata.get("sheets", ()))
    if metadata.get("content_source") == "metadata_only":
        text = ""
    text, byte_truncated = bound_text(text, max_chars=limits.max_text_chars, max_bytes=limits.max_text_utf8_bytes)
    reason = "utf8_limit" if byte_truncated else metadata.get("coverage_reason", "complete")
    warnings = []
    if reason != "complete":
        warnings.append({"utf8_limit": "text_utf8_limit", "character_limit": "text_character_limit", "section_limit": "section_limit"}[reason])
    if not text.strip():
        warnings.append("no_text_content")
        text = ""
    coverage = PreparationCoverage(
        content_kind="text" if extension in {".txt", ".md", ".csv", ".html", ".htm", ".rtf"} else "document",
        text_source="extracted_text" if text.strip() else "none",
        sections_processed=metadata.get("sections_processed", 0), sections_total=metadata.get("sections_total"),
        text_truncated=reason != "complete", text_limit_reason=reason)
    visuals = ()
    if extension == ".pdf":
        from src.services.media.pdf_renderer import PdfRenderConfig, PdfRenderer
        page_count = metadata["pages"]
        # Render a bounded prefix even for mixed text/scan documents: nonempty
        # text on one page must not suppress visual evidence on scanned pages.
        render_cap = min(limits.max_pdf_pages, limits.max_visuals)
        config = PdfRenderConfig(max_pages=render_cap, max_input_bytes=min(limits.max_file_bytes, 64*1024*1024),
            max_page_points=limits.max_pdf_page_points, render_dpi=limits.pdf_render_dpi,
            max_render_long_edge=limits.max_image_long_edge, max_render_pixels_per_page=limits.max_image_pixels,
            max_total_render_pixels=limits.max_pdf_total_render_pixels,
            timeout_seconds=limits.timeout_seconds, image_config=image_config)
        rendered = PdfRenderer(config).render_file(path, max_pages=render_cap, cancellation_token=cancelled)
        if rendered.total_page_count != page_count:
            raise PreparationError("extraction_failed")
        visuals = rendered.payloads
        coverage = replace(coverage, content_kind="pdf" if text.strip() else "scanned_pdf",
            pdf_total_pages=page_count, text_page_indices=tuple(range(metadata["pages_processed"])),
            rendered_page_indices=rendered.rendered_page_indices)
        if len(coverage.text_page_indices) < page_count or len(visuals) < page_count:
            warnings.append("pdf_page_limit")
    return LocalPreparationResult(text, visuals, coverage, tuple(warnings), request.quality_mode)


def _write_frame(frame):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteFile.restype = wintypes.BOOL
    handle = kernel.GetStdHandle(-11 & 0xFFFFFFFF)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise PreparationError("worker_failed")
    offset = 0
    while offset < len(frame):
        chunk = frame[offset:offset+65536]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not kernel.WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None) or not written.value:
            raise PreparationError("worker_failed")
        offset += written.value


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 1:
            return 2
        request = decode_request(arguments[0])
        # Third-party Python diagnostics never contaminate the binary frame or
        # expose paths. Native stream noise also fails parent's strict framing.
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = prepare_request(request)
        _write_frame(encode_result(result))
        return 0
    except BaseException:
        return 2  # Fixed nonzero exit, no exception/path/stream publication.


if __name__ == "__main__":
    raise SystemExit(main())
