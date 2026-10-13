"""Bounded, local PDF page rendering using PyMuPDF."""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from src.core.provider_protocol import PreparedVisualPayload, prepare_visual_payload

from .image_preprocessor import (
    CancellationToken,
    ImagePreprocessConfig,
    ImagePreprocessor,
    MediaProcessingError,
)


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class PdfRenderConfig:
    """Safety limits for opening and rasterizing selected PDF pages."""

    max_pages: int = 6
    max_input_bytes: int = 100 * 1024 * 1024
    max_page_points: float = 14_400.0
    render_dpi: int = 144
    max_render_long_edge: int = 2048
    max_render_pixels_per_page: int = 4_000_000
    max_total_render_pixels: int = 16_000_000
    timeout_seconds: float = 30.0
    preprocessing_version: str = "pdf-v1"
    image_config: ImagePreprocessConfig = field(
        default_factory=ImagePreprocessConfig
    )

    def __post_init__(self) -> None:
        positive = (
            self.max_pages,
            self.max_input_bytes,
            self.max_page_points,
            self.render_dpi,
            self.max_render_long_edge,
            self.max_render_pixels_per_page,
            self.max_total_render_pixels,
            self.timeout_seconds,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("PDF rendering limits must be positive")
        if not self.preprocessing_version.strip():
            raise ValueError("preprocessing_version is required")


@dataclass(frozen=True, slots=True)
class PdfRenderResult:
    """Path-free result containing only selected, prepared page images."""

    total_page_count: int
    rendered_page_indices: tuple[int, ...]
    payloads: tuple[PreparedVisualPayload, ...]

    def __post_init__(self) -> None:
        if len(self.rendered_page_indices) != len(self.payloads):
            raise ValueError("Rendered page indices and payloads must align")


class PdfRenderer:
    """Render only an explicitly bounded subset of a local PDF."""

    def __init__(
        self,
        config: PdfRenderConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or PdfRenderConfig()
        self._clock = clock
        self._image_preprocessor = ImagePreprocessor(
            self.config.image_config,
            clock=clock,
        )

    def render_file(
        self,
        path: str | Path,
        *,
        page_indices: Sequence[int] | None = None,
        max_pages: int | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> PdfRenderResult:
        deadline = self._clock() + self.config.timeout_seconds
        self._checkpoint(deadline, cancellation_token, "read")
        try:
            with Path(path).open("rb") as source:
                data = source.read(self.config.max_input_bytes + 1)
        except OSError as exc:
            raise MediaProcessingError(
                "read_failed", "read", "The local PDF could not be read"
            ) from exc
        if len(data) > self.config.max_input_bytes:
            raise MediaProcessingError(
                "input_too_large",
                "read",
                "The local PDF exceeds the configured input byte limit",
            )
        return self._render_bytes(
            data,
            payload_provenance="local-pdf-page",
            page_indices=page_indices,
            max_pages=max_pages,
            deadline=deadline,
            cancellation_token=cancellation_token,
        )

    def render_bytes(
        self,
        data: bytes,
        *,
        provenance: str,
        page_indices: Sequence[int] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> PdfRenderResult:
        deadline = self._clock() + self.config.timeout_seconds
        if not isinstance(data, bytes):
            raise MediaProcessingError(
                "invalid_request", "validate", "PDF input must be bytes"
            )
        if not provenance.strip() or self._looks_like_path(provenance):
            raise MediaProcessingError(
                "invalid_request",
                "validate",
                "Path-free PDF provenance is required",
            )
        if len(data) > self.config.max_input_bytes:
            raise MediaProcessingError(
                "input_too_large",
                "read",
                "The local PDF exceeds the configured input byte limit",
            )
        return self._render_bytes(
            data,
            payload_provenance="rendered-pdf-page",
            page_indices=page_indices,
            max_pages=None,
            deadline=deadline,
            cancellation_token=cancellation_token,
        )

    def _render_bytes(
        self,
        data: bytes,
        *,
        payload_provenance: str,
        page_indices: Sequence[int] | None,
        max_pages: int | None,
        deadline: float,
        cancellation_token: CancellationToken | None,
    ) -> PdfRenderResult:
        self._checkpoint(deadline, cancellation_token, "open")
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
            raise MediaProcessingError(
                "invalid_pdf", "open", "The local PDF is corrupt or unsupported"
            ) from exc

        try:
            if not document.is_pdf:
                raise MediaProcessingError(
                    "invalid_pdf", "open", "The local document is not a PDF"
                )
            if document.needs_pass:
                raise MediaProcessingError(
                    "encrypted_pdf",
                    "open",
                    "Password-protected PDFs are not rendered without authorization",
                )
            total_page_count = document.page_count
            selected = self._select_pages(total_page_count, page_indices, max_pages=max_pages)

            payloads: list[PreparedVisualPayload] = []
            total_pixels = 0
            for page_index in selected:
                self._checkpoint(deadline, cancellation_token, "preflight")
                try:
                    page = document.load_page(page_index)
                    width_points = float(page.rect.width)
                    height_points = float(page.rect.height)
                except (RuntimeError, ValueError) as exc:
                    raise MediaProcessingError(
                        "page_load_failed",
                        "preflight",
                        "A selected PDF page could not be loaded",
                    ) from exc
                if (
                    width_points <= 0
                    or height_points <= 0
                    or max(width_points, height_points)
                    > self.config.max_page_points
                ):
                    raise MediaProcessingError(
                        "page_too_large",
                        "preflight",
                        "A selected PDF page exceeds the configured page size limit",
                    )

                scale, projected_pixels = self._render_scale(
                    width_points, height_points
                )
                if (
                    total_pixels + projected_pixels
                    > self.config.max_total_render_pixels
                ):
                    raise MediaProcessingError(
                        "total_pixel_limit",
                        "preflight",
                        "Selected PDF pages exceed the total render pixel budget",
                    )
                total_pixels += projected_pixels

                try:
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale),
                        colorspace=pymupdf.csRGB,
                        alpha=False,
                        annots=True,
                    )
                    rendered_png = pixmap.tobytes("png")
                except (RuntimeError, ValueError, MemoryError) as exc:
                    raise MediaProcessingError(
                        "render_failed",
                        "render",
                        "A selected PDF page could not be rendered",
                    ) from exc

                prepared_image = self._image_preprocessor.process_bytes(
                    rendered_png,
                    source_index=page_index,
                    provenance=payload_provenance,
                    cancellation_token=cancellation_token,
                    deadline=deadline,
                )
                payloads.append(
                    prepare_visual_payload(
                        kind="rendered_scan_page",
                        mime_type=prepared_image.mime_type,
                        data=prepared_image.data,
                        width=prepared_image.width,
                        height=prepared_image.height,
                        source_index=page_index,
                        preprocessing_version=(
                            f"{self.config.preprocessing_version}+"
                            f"{prepared_image.preprocessing_version}"
                        ),
                        provenance=payload_provenance,
                    )
                )
                self._checkpoint(deadline, cancellation_token, "render")

            return PdfRenderResult(
                total_page_count=total_page_count,
                rendered_page_indices=selected,
                payloads=tuple(payloads),
            )
        finally:
            document.close()

    def _select_pages(
        self,
        total_page_count: int,
        page_indices: Sequence[int] | None,
        *,
        max_pages: int | None = None,
    ) -> tuple[int, ...]:
        if total_page_count <= 0:
            raise MediaProcessingError(
                "empty_pdf", "preflight", "The PDF contains no renderable pages"
            )
        effective_limit = self.config.max_pages
        if max_pages is not None:
            if max_pages <= 0:
                raise MediaProcessingError(
                    "page_limit", "preflight", "PDF page limit must be positive"
                )
            effective_limit = min(effective_limit, max_pages)
        if page_indices is None:
            return tuple(range(min(total_page_count, effective_limit)))

        selected = tuple(page_indices)
        if len(selected) > effective_limit:
            raise MediaProcessingError(
                "page_limit",
                "preflight",
                "The requested page count exceeds the configured limit",
            )
        if not selected:
            raise MediaProcessingError(
                "invalid_page_index",
                "preflight",
                "At least one PDF page must be selected",
            )
        if len(set(selected)) != len(selected):
            raise MediaProcessingError(
                "duplicate_page_index",
                "preflight",
                "Duplicate PDF page indices are not allowed",
            )
        if any(
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= total_page_count
            for index in selected
        ):
            raise MediaProcessingError(
                "invalid_page_index",
                "preflight",
                "A requested PDF page index is out of range",
            )
        return selected

    def _render_scale(
        self, width_points: float, height_points: float
    ) -> tuple[float, int]:
        scale = self.config.render_dpi / 72.0
        raw_width = width_points * scale
        raw_height = height_points * scale
        scale *= min(
            1.0,
            self.config.max_render_long_edge / max(raw_width, raw_height),
            math.sqrt(
                self.config.max_render_pixels_per_page
                / (raw_width * raw_height)
            ),
        )
        for _ in range(4):
            projected_width = max(1, math.ceil(width_points * scale))
            projected_height = max(1, math.ceil(height_points * scale))
            projected_pixels = projected_width * projected_height
            if (
                max(projected_width, projected_height)
                <= self.config.max_render_long_edge
                and projected_pixels
                <= self.config.max_render_pixels_per_page
            ):
                return scale, projected_pixels
            scale *= 0.99 * min(
                self.config.max_render_long_edge
                / max(projected_width, projected_height),
                math.sqrt(
                    self.config.max_render_pixels_per_page / projected_pixels
                ),
            )
        raise MediaProcessingError(
            "render_limit_unreachable",
            "preflight",
            "The PDF page cannot satisfy configured render limits",
        )

    def _checkpoint(
        self,
        deadline: float,
        cancellation_token: CancellationToken | None,
        stage: str,
    ) -> None:
        if cancellation_token is not None and cancellation_token():
            raise MediaProcessingError(
                "cancelled", stage, "PDF rendering was cancelled"
            )
        if self._clock() > deadline:
            raise MediaProcessingError(
                "timeout", stage, "PDF rendering exceeded its time limit"
            )

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        return (
            value.startswith(("/", "\\\\", "file://"))
            or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
        )
