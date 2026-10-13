"""Bounded local extraction of representative video frames with PyAV."""
from __future__ import annotations

import io
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import av
from PIL import Image, ImageStat

from src.core.provider_protocol import PreparedVisualPayload, prepare_visual_payload

from .image_preprocessor import (
    CancellationToken,
    ImagePreprocessConfig,
    ImagePreprocessor,
    MediaProcessingError,
)


_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_SIGNATURE_SIZE = (16, 16)
_BLACK_MEAN_THRESHOLD = 8.0
_BLACK_STDDEV_THRESHOLD = 5.0
_DUPLICATE_DISTANCE_THRESHOLD = 2.0


def _deny_nested_io(url, flags, options):
    """The already-open local input is the decoder's only permitted resource."""
    raise OSError("nested_video_io_denied")


@dataclass(frozen=True, slots=True)
class KeyframeExtractConfig:
    """Safety limits and quality-to-frame-count mapping for local video decode."""

    economy_frame_count: int = 4
    balanced_frame_count: int = 6
    quality_frame_count: int = 8
    max_input_bytes: int = 512 * 1024 * 1024
    max_duration_seconds: float = 4 * 60 * 60
    max_source_pixels: int = 33_177_600
    max_decode_frames: int = 20_000
    candidate_window_seconds: float = 1.0
    max_candidate_frames_per_sample: int = 90
    max_total_output_bytes: int = 16 * 1024 * 1024
    timeout_seconds: float = 45.0
    preprocessing_version: str = "video-v1"
    image_config: ImagePreprocessConfig = field(
        default_factory=ImagePreprocessConfig
    )

    def __post_init__(self) -> None:
        frame_counts = (
            self.economy_frame_count,
            self.balanced_frame_count,
            self.quality_frame_count,
        )
        if not (
            4 <= frame_counts[0] <= frame_counts[1] <= frame_counts[2] <= 8
        ):
            raise ValueError(
                "Quality frame counts must be ordered and remain within 4–8"
            )
        positive = (
            self.max_input_bytes,
            self.max_duration_seconds,
            self.max_source_pixels,
            self.max_decode_frames,
            self.candidate_window_seconds,
            self.max_candidate_frames_per_sample,
            self.max_total_output_bytes,
            self.timeout_seconds,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Video extraction limits must be positive")
        if not self.preprocessing_version.strip():
            raise ValueError("preprocessing_version is required")

    def frame_count_for(self, quality_mode: str) -> int:
        try:
            return {
                "economy": self.economy_frame_count,
                "balanced": self.balanced_frame_count,
                "quality": self.quality_frame_count,
            }[quality_mode]
        except KeyError as exc:
            raise MediaProcessingError(
                "invalid_quality_mode",
                "validate",
                "Video quality mode must be economy, balanced, or quality",
            ) from exc


@dataclass(frozen=True, slots=True)
class VideoKeyframeResult:
    """Path-free video summary containing only prepared still images."""

    duration_seconds: float
    source_width: int
    source_height: int
    timestamps_seconds: tuple[float, ...]
    payloads: tuple[PreparedVisualPayload, ...]

    def __post_init__(self) -> None:
        if len(self.timestamps_seconds) != len(self.payloads):
            raise ValueError("Keyframe timestamps and payloads must align")


class VideoKeyframeExtractor:
    """Sample a local video timeline without exposing or returning the full video."""

    def __init__(
        self,
        config: KeyframeExtractConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or KeyframeExtractConfig()
        self._clock = clock
        self._image_preprocessor = ImagePreprocessor(
            self.config.image_config,
            clock=clock,
        )

    def extract_file(
        self,
        path: str | Path,
        *,
        quality_mode: str,
        max_frames: int | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> VideoKeyframeResult:
        frame_count = self.config.frame_count_for(quality_mode)
        if max_frames is not None:
            if max_frames <= 0:
                raise MediaProcessingError(
                    "frame_limit", "validate", "Video frame limit must be positive"
                )
            frame_count = min(frame_count, max_frames)
        deadline = self._clock() + self.config.timeout_seconds
        self._checkpoint(deadline, cancellation_token, "read")
        try:
            with Path(path).open("rb") as source:
                size = os.fstat(source.fileno()).st_size
                if size > self.config.max_input_bytes:
                    raise MediaProcessingError(
                        "input_too_large",
                        "read",
                        "The local video exceeds the configured input byte limit",
                    )
                return self._extract(
                    source,
                    frame_count=frame_count,
                    payload_provenance="local-video-frame",
                    deadline=deadline,
                    cancellation_token=cancellation_token,
                )
        except MediaProcessingError:
            raise
        except OSError as exc:
            raise MediaProcessingError(
                "read_failed", "read", "The local video could not be read"
            ) from exc

    def extract_bytes(
        self,
        data: bytes,
        *,
        provenance: str,
        quality_mode: str,
        cancellation_token: CancellationToken | None = None,
    ) -> VideoKeyframeResult:
        frame_count = self.config.frame_count_for(quality_mode)
        deadline = self._clock() + self.config.timeout_seconds
        if not isinstance(data, bytes):
            raise MediaProcessingError(
                "invalid_request", "validate", "Video input must be bytes"
            )
        if not provenance.strip() or self._looks_like_path(provenance):
            raise MediaProcessingError(
                "invalid_request",
                "validate",
                "Path-free video provenance is required",
            )
        if len(data) > self.config.max_input_bytes:
            raise MediaProcessingError(
                "input_too_large",
                "read",
                "The local video exceeds the configured input byte limit",
            )
        return self._extract(
            io.BytesIO(data),
            frame_count=frame_count,
            payload_provenance="prepared-video-frame",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )

    def _extract(
        self,
        source: str | BinaryIO,
        *,
        frame_count: int,
        payload_provenance: str,
        deadline: float,
        cancellation_token: CancellationToken | None,
    ) -> VideoKeyframeResult:
        self._checkpoint(deadline, cancellation_token, "open")
        try:
            container = av.open(
                source, mode="r", options={"protocol_whitelist": ""},
                io_open=_deny_nested_io,
            )
        except (av.FFmpegError, OSError, ValueError) as exc:
            raise MediaProcessingError(
                "invalid_video",
                "open",
                "The local video is corrupt or unsupported",
            ) from exc

        try:
            stream = next(
                (candidate for candidate in container.streams if candidate.type == "video"),
                None,
            )
            if stream is None:
                raise MediaProcessingError(
                    "no_video_stream",
                    "probe",
                    "The media file contains no video stream",
                )
            width = int(stream.codec_context.width or 0)
            height = int(stream.codec_context.height or 0)
            if width <= 0 or height <= 0:
                raise MediaProcessingError(
                    "invalid_dimensions",
                    "probe",
                    "The video stream dimensions are invalid",
                )
            if width * height > self.config.max_source_pixels:
                raise MediaProcessingError(
                    "source_pixel_limit",
                    "probe",
                    "The video exceeds the configured source pixel limit",
                )

            duration = self._duration_seconds(container, stream)
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise MediaProcessingError(
                    "duration_unavailable",
                    "probe",
                    "A bounded video duration could not be determined",
                )
            if duration > self.config.max_duration_seconds:
                raise MediaProcessingError(
                    "duration_limit",
                    "probe",
                    "The video exceeds the configured duration limit",
                )

            targets = tuple(
                duration * (sample + 0.5) / frame_count
                for sample in range(frame_count)
            )
            payloads: list[PreparedVisualPayload] = []
            timestamps: list[float] = []
            selected_signatures: list[bytes] = []
            decoded_frames = 0
            total_output_bytes = 0

            for sample_index, target in enumerate(targets):
                self._checkpoint(deadline, cancellation_token, "seek")
                frame, timestamp, decoded, signature = self._decode_at(
                    container,
                    stream,
                    target,
                    decoded_frames,
                    deadline,
                    cancellation_token,
                    tuple(selected_signatures),
                )
                decoded_frames += decoded
                if decoded_frames > self.config.max_decode_frames:
                    raise MediaProcessingError(
                        "decode_frame_limit",
                        "decode",
                        "Video sampling exceeded the configured decode frame limit",
                    )

                encoded = io.BytesIO()
                frame.to_image().save(encoded, format="PNG")
                prepared_image = self._image_preprocessor.process_bytes(
                    encoded.getvalue(),
                    source_index=sample_index,
                    provenance=payload_provenance,
                    cancellation_token=cancellation_token,
                    deadline=deadline,
                )
                payload = prepare_visual_payload(
                    kind="video_keyframe",
                    mime_type=prepared_image.mime_type,
                    data=prepared_image.data,
                    width=prepared_image.width,
                    height=prepared_image.height,
                    source_index=sample_index,
                    preprocessing_version=(
                        f"{self.config.preprocessing_version}+"
                        f"{prepared_image.preprocessing_version}"
                    ),
                    provenance=payload_provenance,
                )
                total_output_bytes += payload.byte_size
                if total_output_bytes > self.config.max_total_output_bytes:
                    raise MediaProcessingError(
                        "total_output_limit",
                        "encode",
                        "Prepared keyframes exceed the total output byte limit",
                    )
                payloads.append(payload)
                timestamps.append(timestamp)
                selected_signatures.append(signature)
                self._checkpoint(deadline, cancellation_token, "encode")

            if len(payloads) != frame_count:
                raise MediaProcessingError(
                    "insufficient_frames",
                    "decode",
                    "The requested representative frame count could not be produced",
                )
            return VideoKeyframeResult(
                duration_seconds=duration,
                source_width=width,
                source_height=height,
                timestamps_seconds=tuple(timestamps),
                payloads=tuple(payloads),
            )
        except MediaProcessingError:
            raise
        except (av.FFmpegError, OSError, ValueError, MemoryError) as exc:
            raise MediaProcessingError(
                "decode_failed",
                "decode",
                "Representative video frames could not be decoded",
            ) from exc
        finally:
            container.close()

    def _decode_at(
        self,
        container: av.container.InputContainer,
        stream: av.video.stream.VideoStream,
        target_seconds: float,
        already_decoded: int,
        deadline: float,
        cancellation_token: CancellationToken | None,
        selected_signatures: tuple[bytes, ...],
    ) -> tuple[av.VideoFrame, float, int, bytes]:
        if stream.time_base is None:
            raise MediaProcessingError(
                "time_base_unavailable",
                "seek",
                "The video stream has no usable timeline",
            )
        timestamp_units = max(0, int(target_seconds / float(stream.time_base)))
        try:
            container.seek(
                timestamp_units,
                stream=stream,
                backward=True,
                any_frame=False,
            )
        except (av.FFmpegError, ValueError) as exc:
            raise MediaProcessingError(
                "seek_failed",
                "seek",
                "The video timeline could not be sampled safely",
            ) from exc

        decoded = 0
        candidates_checked = 0
        candidate_deadline = target_seconds + self.config.candidate_window_seconds
        for frame in container.decode(stream):
            decoded += 1
            if already_decoded + decoded > self.config.max_decode_frames:
                raise MediaProcessingError(
                    "decode_frame_limit",
                    "decode",
                    "Video sampling exceeded the configured decode frame limit",
                )
            self._checkpoint(deadline, cancellation_token, "decode")
            timestamp = self._frame_timestamp(frame, stream)
            if timestamp < target_seconds:
                continue
            if timestamp > candidate_deadline:
                break

            candidates_checked += 1
            if candidates_checked > self.config.max_candidate_frames_per_sample:
                break
            signature, mean_luminance, stddev_luminance = self._frame_signature(frame)
            if (
                mean_luminance <= _BLACK_MEAN_THRESHOLD
                and stddev_luminance <= _BLACK_STDDEV_THRESHOLD
            ):
                continue
            if any(
                self._signature_distance(signature, previous)
                < _DUPLICATE_DISTANCE_THRESHOLD
                for previous in selected_signatures
            ):
                continue
            return frame, timestamp, decoded, signature

        raise MediaProcessingError(
            "insufficient_representative_frames",
            "decode",
            "A distinct non-black representative frame could not be selected safely",
        )

    @staticmethod
    def _frame_signature(frame: av.VideoFrame) -> tuple[bytes, float, float]:
        image = frame.to_image()
        signature = image.convert("RGB").resize(
            _SIGNATURE_SIZE,
            Image.Resampling.BILINEAR,
        )
        grayscale = image.convert("L").resize(
            _SIGNATURE_SIZE,
            Image.Resampling.BILINEAR,
        )
        statistics = ImageStat.Stat(grayscale)
        return signature.tobytes(), statistics.mean[0], statistics.stddev[0]

    @staticmethod
    def _signature_distance(left: bytes, right: bytes) -> float:
        if len(left) != len(right):
            return float("inf")
        return sum(abs(a - b) for a, b in zip(left, right, strict=True)) / len(left)

    @staticmethod
    def _duration_seconds(
        container: av.container.InputContainer,
        stream: av.video.stream.VideoStream,
    ) -> float | None:
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
        if container.duration is not None:
            return float(container.duration / av.time_base)
        return None

    @staticmethod
    def _frame_timestamp(
        frame: av.VideoFrame,
        stream: av.video.stream.VideoStream,
    ) -> float:
        if frame.time is not None:
            return float(frame.time)
        if frame.pts is not None and stream.time_base is not None:
            return float(frame.pts * stream.time_base)
        raise MediaProcessingError(
            "timestamp_unavailable",
            "decode",
            "A decoded video frame has no usable timestamp",
        )

    def _checkpoint(
        self,
        deadline: float,
        cancellation_token: CancellationToken | None,
        stage: str,
    ) -> None:
        if cancellation_token is not None and cancellation_token():
            raise MediaProcessingError(
                "cancelled", stage, "Video keyframe extraction was cancelled"
            )
        if self._clock() > deadline:
            raise MediaProcessingError(
                "timeout",
                stage,
                "Video keyframe extraction exceeded its time limit",
            )

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        return (
            value.startswith(("/", "\\\\", "file://"))
            or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
        )
