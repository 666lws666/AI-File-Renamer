"""Local, bounded image preprocessing for vision-provider payloads."""
from __future__ import annotations

import io
import math
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from src.core.provider_protocol import PreparedVisualPayload, prepare_visual_payload


CancellationToken = Callable[[], bool]


class MediaProcessingError(RuntimeError):
    """Structured error that deliberately omits local paths and source bytes."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


@dataclass(frozen=True, slots=True)
class ImagePreprocessConfig:
    """Explicit safety and output limits for one decoded image."""

    max_long_edge: int = 2048
    max_pixels: int = 4_000_000
    max_decode_pixels: int = 40_000_000
    max_input_bytes: int = 50 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024
    output_mime_type: str = "image/jpeg"
    initial_quality: int = 85
    min_quality: int = 40
    quality_step: int = 10
    timeout_seconds: float = 15.0
    preprocessing_version: str = "image-v1"

    def __post_init__(self) -> None:
        positive_limits = (
            self.max_long_edge,
            self.max_pixels,
            self.max_decode_pixels,
            self.max_input_bytes,
            self.max_output_bytes,
            self.quality_step,
        )
        if any(value <= 0 for value in positive_limits):
            raise ValueError("Image preprocessing limits must be positive")
        if self.max_decode_pixels < self.max_pixels:
            raise ValueError("max_decode_pixels cannot be smaller than max_pixels")
        if self.output_mime_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise ValueError("Unsupported output MIME type")
        if not 1 <= self.min_quality <= self.initial_quality <= 95:
            raise ValueError("Image quality must satisfy 1 <= min <= initial <= 95")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.preprocessing_version.strip():
            raise ValueError("preprocessing_version is required")


class ImagePreprocessor:
    """Convert local image input into a size-limited prepared visual payload."""

    def __init__(
        self,
        config: ImagePreprocessConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or ImagePreprocessConfig()
        self._clock = clock

    def process_file(
        self,
        path: str | Path,
        *,
        source_index: int,
        cancellation_token: CancellationToken | None = None,
    ) -> PreparedVisualPayload:
        deadline = self._clock() + self.config.timeout_seconds
        self._validate_request(source_index, "local-image")
        self._checkpoint(deadline, cancellation_token, "read")
        try:
            with Path(path).open("rb") as source:
                data = source.read(self.config.max_input_bytes + 1)
        except OSError as exc:
            raise MediaProcessingError(
                "read_failed", "read", "The local image could not be read"
            ) from exc
        if len(data) > self.config.max_input_bytes:
            raise MediaProcessingError(
                "input_too_large",
                "read",
                "The local image exceeds the configured input byte limit",
            )
        return self._process_bytes(
            data,
            source_index=source_index,
            provenance="local-image",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )

    def process_bytes(
        self,
        data: bytes,
        *,
        source_index: int,
        provenance: str,
        cancellation_token: CancellationToken | None = None,
        deadline: float | None = None,
    ) -> PreparedVisualPayload:
        local_deadline = self._clock() + self.config.timeout_seconds
        deadline = local_deadline if deadline is None else min(deadline, local_deadline)
        self._validate_request(source_index, provenance)
        if not isinstance(data, bytes):
            raise MediaProcessingError(
                "invalid_request", "validate", "Image input must be bytes"
            )
        if len(data) > self.config.max_input_bytes:
            raise MediaProcessingError(
                "input_too_large",
                "read",
                "The local image exceeds the configured input byte limit",
            )
        return self._process_bytes(
            data,
            source_index=source_index,
            provenance=provenance,
            deadline=deadline,
            cancellation_token=cancellation_token,
        )

    def _process_bytes(
        self,
        data: bytes,
        *,
        source_index: int,
        provenance: str,
        deadline: float,
        cancellation_token: CancellationToken | None,
    ) -> PreparedVisualPayload:
        self._checkpoint(deadline, cancellation_token, "decode")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as opened:
                    width, height = opened.size
                    if width <= 0 or height <= 0:
                        raise MediaProcessingError(
                            "invalid_dimensions",
                            "decode",
                            "The decoded image dimensions are invalid",
                        )
                    if width * height > self.config.max_decode_pixels:
                        raise MediaProcessingError(
                            "decode_pixel_limit",
                            "decode",
                            "The image exceeds the configured decode pixel limit",
                        )
                    opened.seek(0)
                    opened.load()
                    image = ImageOps.exif_transpose(opened).copy()
        except MediaProcessingError:
            raise
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise MediaProcessingError(
                "decode_failed", "decode", "The local image could not be decoded"
            ) from exc

        self._checkpoint(deadline, cancellation_token, "resize")
        image = self._resize_to_geometry_limits(image)
        self._checkpoint(deadline, cancellation_token, "encode")
        encoded, mime_type, image = self._encode_with_byte_limit(
            image, deadline, cancellation_token
        )
        self._checkpoint(deadline, cancellation_token, "finalize")
        return prepare_visual_payload(
            kind="resized_image",
            mime_type=mime_type,
            data=encoded,
            width=image.width,
            height=image.height,
            source_index=source_index,
            preprocessing_version=self.config.preprocessing_version,
            provenance=provenance,
        )

    def _resize_to_geometry_limits(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        long_edge_scale = self.config.max_long_edge / max(width, height)
        pixel_scale = math.sqrt(self.config.max_pixels / (width * height))
        scale = min(1.0, long_edge_scale, pixel_scale)
        if scale >= 1.0:
            return image
        target = (
            max(1, math.floor(width * scale)),
            max(1, math.floor(height * scale)),
        )
        return image.resize(target, Image.Resampling.LANCZOS)

    def _encode_with_byte_limit(
        self,
        image: Image.Image,
        deadline: float,
        cancellation_token: CancellationToken | None,
    ) -> tuple[bytes, str, Image.Image]:
        mime_type = self.config.output_mime_type
        working = self._convert_for_output(image, mime_type)

        for _ in range(12):
            qualities = (
                range(
                    self.config.initial_quality,
                    self.config.min_quality - 1,
                    -self.config.quality_step,
                )
                if mime_type in {"image/jpeg", "image/webp"}
                else (None,)
            )
            last_encoded = b""
            for quality in qualities:
                self._checkpoint(deadline, cancellation_token, "encode")
                last_encoded = self._encode_once(working, mime_type, quality)
                if len(last_encoded) <= self.config.max_output_bytes:
                    return last_encoded, mime_type, working

            if working.width == 1 and working.height == 1:
                break
            ratio = math.sqrt(
                self.config.max_output_bytes / max(1, len(last_encoded))
            )
            scale = min(0.85, max(0.25, ratio * 0.92))
            target = (
                max(1, math.floor(working.width * scale)),
                max(1, math.floor(working.height * scale)),
            )
            if target == working.size:
                target = (max(1, working.width - 1), max(1, working.height - 1))
            working = working.resize(target, Image.Resampling.LANCZOS)

        raise MediaProcessingError(
            "output_too_large",
            "encode",
            "The prepared image cannot satisfy the configured output byte limit",
        )

    @staticmethod
    def _convert_for_output(image: Image.Image, mime_type: str) -> Image.Image:
        if mime_type == "image/jpeg":
            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                return background
            return image.convert("RGB")
        if mime_type == "image/png" and image.mode not in {
            "1",
            "L",
            "LA",
            "P",
            "RGB",
            "RGBA",
        }:
            return image.convert("RGBA")
        if mime_type == "image/webp" and image.mode not in {"RGB", "RGBA"}:
            return image.convert("RGB")
        return image

    @staticmethod
    def _encode_once(
        image: Image.Image, mime_type: str, quality: int | None
    ) -> bytes:
        output = io.BytesIO()
        if mime_type == "image/jpeg":
            image.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
        elif mime_type == "image/webp":
            image.save(output, format="WEBP", quality=quality, method=4)
        else:
            image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _validate_request(source_index: int, provenance: str) -> None:
        if source_index < 0 or not provenance.strip():
            raise MediaProcessingError(
                "invalid_request",
                "validate",
                "A non-negative source index and provenance are required",
            )

    def _checkpoint(
        self,
        deadline: float,
        cancellation_token: CancellationToken | None,
        stage: str,
    ) -> None:
        if cancellation_token is not None and cancellation_token():
            raise MediaProcessingError(
                "cancelled", stage, "Image preprocessing was cancelled"
            )
        if self._clock() > deadline:
            raise MediaProcessingError(
                "timeout", stage, "Image preprocessing exceeded its time limit"
            )
