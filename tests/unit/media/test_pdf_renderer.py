"""M3 Task 12: bounded PyMuPDF page rendering for scanned PDFs."""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src.services.media.image_preprocessor import (
    ImagePreprocessConfig,
    MediaProcessingError,
)
from src.services.media.pdf_renderer import PdfRenderConfig, PdfRenderer


def _pdf_bytes(
    page_count: int = 1,
    *,
    page_size: tuple[float, float] = (300, 200),
    scanned: bool = False,
) -> bytes:
    document = pymupdf.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=page_size[0], height=page_size[1])
            if scanned:
                image = Image.new(
                    "RGB",
                    (240, 120),
                    (20 + index * 10, 80, 160),
                )
                encoded = io.BytesIO()
                image.save(encoded, format="PNG")
                page.insert_image(page.rect, stream=encoded.getvalue())
            else:
                page.insert_text((30, 60), f"Local text page {index + 1}")
        return document.tobytes()
    finally:
        document.close()


def _config(**changes) -> PdfRenderConfig:
    image_config = ImagePreprocessConfig(
        max_long_edge=800,
        max_pixels=500_000,
        max_output_bytes=200_000,
        output_mime_type="image/jpeg",
    )
    return PdfRenderConfig(image_config=image_config, **changes)


def test_text_pdf_renders_to_prepared_scan_page_payload():
    result = PdfRenderer(_config()).render_bytes(
        _pdf_bytes(),
        provenance="synthetic-text-pdf",
    )

    assert result.total_page_count == 1
    assert result.rendered_page_indices == (0,)
    assert len(result.payloads) == 1
    payload = result.payloads[0]
    assert payload.kind == "rendered_scan_page"
    assert payload.source_index == 0
    assert payload.mime_type == "image/jpeg"
    assert not payload.data.startswith(b"%PDF")


def test_scanned_pdf_renders_visible_page_image():
    result = PdfRenderer(_config()).render_bytes(
        _pdf_bytes(scanned=True),
        provenance="synthetic-scan",
    )

    with Image.open(io.BytesIO(result.payloads[0].data)) as rendered:
        center = rendered.convert("RGB").getpixel(
            (rendered.width // 2, rendered.height // 2)
        )
    assert center[2] > center[0]


def test_default_selection_is_capped_by_max_pages():
    result = PdfRenderer(_config(max_pages=2)).render_bytes(
        _pdf_bytes(page_count=5),
        provenance="five-page-pdf",
    )

    assert result.total_page_count == 5
    assert result.rendered_page_indices == (0, 1)
    assert [payload.source_index for payload in result.payloads] == [0, 1]


def test_explicit_page_selection_rejects_too_many_or_out_of_range_pages():
    renderer = PdfRenderer(_config(max_pages=2))
    pdf = _pdf_bytes(page_count=4)

    with pytest.raises(MediaProcessingError) as too_many:
        renderer.render_bytes(
            pdf,
            provenance="explicit-pages",
            page_indices=(0, 1, 2),
        )
    with pytest.raises(MediaProcessingError) as out_of_range:
        renderer.render_bytes(
            pdf,
            provenance="explicit-pages",
            page_indices=(4,),
        )

    assert too_many.value.code == "page_limit"
    assert out_of_range.value.code == "invalid_page_index"


def test_duplicate_page_indices_are_rejected():
    with pytest.raises(MediaProcessingError) as caught:
        PdfRenderer(_config()).render_bytes(
            _pdf_bytes(page_count=2),
            provenance="duplicate-pages",
            page_indices=(0, 0),
        )

    assert caught.value.code == "duplicate_page_index"


def test_encrypted_pdf_fails_closed_without_password():
    document = pymupdf.open(stream=_pdf_bytes(), filetype="pdf")
    try:
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        document.close()

    with pytest.raises(MediaProcessingError) as caught:
        PdfRenderer(_config()).render_bytes(
            encrypted,
            provenance="encrypted-fixture",
        )

    assert caught.value.code == "encrypted_pdf"
    assert "secret" not in str(caught.value)


def test_corrupt_pdf_returns_structured_error():
    with pytest.raises(MediaProcessingError) as caught:
        PdfRenderer(_config()).render_bytes(
            b"%PDF-corrupt",
            provenance="corrupt-fixture",
        )

    assert caught.value.code == "invalid_pdf"
    assert caught.value.stage == "open"


def test_oversized_source_page_is_rejected_before_pixmap_allocation():
    renderer = PdfRenderer(_config(max_page_points=500))

    with pytest.raises(MediaProcessingError) as caught:
        renderer.render_bytes(
            _pdf_bytes(page_size=(600, 300)),
            provenance="oversized-page",
        )

    assert caught.value.code == "page_too_large"
    assert caught.value.stage == "preflight"


def test_rendered_dimensions_and_total_pixel_budget_are_bounded():
    config = _config(
        render_dpi=288,
        max_render_long_edge=400,
        max_render_pixels_per_page=100_000,
        max_total_render_pixels=220_000,
        max_pages=2,
    )
    result = PdfRenderer(config).render_bytes(
        _pdf_bytes(page_count=2, page_size=(600, 400)),
        provenance="bounded-render",
    )

    assert all(max(item.width, item.height) <= 400 for item in result.payloads)
    assert all(item.width * item.height <= 100_000 for item in result.payloads)
    assert sum(item.width * item.height for item in result.payloads) <= 220_000


def test_total_pixel_budget_fails_before_rendering_excess_page():
    config = _config(
        render_dpi=72,
        max_render_long_edge=1000,
        max_render_pixels_per_page=1_000_000,
        max_total_render_pixels=100_000,
        max_pages=2,
    )

    with pytest.raises(MediaProcessingError) as caught:
        PdfRenderer(config).render_bytes(
            _pdf_bytes(page_count=2, page_size=(300, 200)),
            provenance="total-budget",
        )

    assert caught.value.code == "total_pixel_limit"


def test_file_input_is_bounded_and_result_never_contains_path(tmp_path: Path):
    source = tmp_path / "private-scan.pdf"
    source.write_bytes(_pdf_bytes(scanned=True))
    renderer = PdfRenderer(_config())

    result = renderer.render_file(source)

    assert str(source) not in repr(result)
    assert source.name not in repr(result)
    assert all(payload.provenance == "local-pdf-page" for payload in result.payloads)

    too_small = PdfRenderer(_config(max_input_bytes=10))
    with pytest.raises(MediaProcessingError) as caught:
        too_small.render_file(source)
    assert caught.value.code == "input_too_large"


def test_cancellation_is_checked_between_pages():
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(MediaProcessingError) as caught:
        PdfRenderer(_config(max_pages=3)).render_bytes(
            _pdf_bytes(page_count=3),
            provenance="cancelled-render",
            cancellation_token=cancelled,
        )

    assert caught.value.code == "cancelled"


def test_timeout_uses_injected_clock_before_opening_pdf():
    ticks = iter((10.0, 12.0))
    renderer = PdfRenderer(_config(timeout_seconds=1.0), clock=lambda: next(ticks))

    with pytest.raises(MediaProcessingError) as caught:
        renderer.render_bytes(
            _pdf_bytes(),
            provenance="timeout-render",
        )

    assert caught.value.code == "timeout"


def test_cancellation_propagates_into_child_image_preprocessing(monkeypatch):
    renderer = PdfRenderer(_config())
    child = renderer._image_preprocessor
    original_encode = child._encode_once
    cancel_requested = False

    def encode_then_cancel(image, mime_type, quality):
        nonlocal cancel_requested
        encoded = original_encode(image, mime_type, quality)
        cancel_requested = True
        return encoded

    monkeypatch.setattr(child, "_encode_once", encode_then_cancel)

    with pytest.raises(MediaProcessingError) as caught:
        renderer.render_bytes(
            _pdf_bytes(),
            provenance="cancel-during-child",
            cancellation_token=lambda: cancel_requested,
        )

    assert caught.value.code == "cancelled"
    assert caught.value.stage == "finalize"


def test_parent_deadline_is_enforced_inside_child_image_preprocessing(monkeypatch):
    now = 10.0

    def clock() -> float:
        return now

    renderer = PdfRenderer(_config(timeout_seconds=1.0), clock=clock)
    child = renderer._image_preprocessor
    original_encode = child._encode_once

    def slow_encode(image, mime_type, quality):
        nonlocal now
        encoded = original_encode(image, mime_type, quality)
        now = 12.0
        return encoded

    monkeypatch.setattr(child, "_encode_once", slow_encode)

    with pytest.raises(MediaProcessingError) as caught:
        renderer.render_bytes(
            _pdf_bytes(),
            provenance="timeout-during-child",
        )

    assert caught.value.code == "timeout"
    assert caught.value.stage == "finalize"
