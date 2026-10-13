"""M3 Task 13: bounded local extraction of representative video frames."""
from __future__ import annotations

import io
from pathlib import Path

import av
import pytest
from PIL import Image, ImageStat

from src.services.media.image_preprocessor import (
    ImagePreprocessConfig,
    MediaProcessingError,
)
from src.services.media.keyframe_extractor import (
    KeyframeExtractConfig,
    VideoKeyframeExtractor,
)


def _video_bytes(
    *,
    frame_count: int = 48,
    fps: int = 12,
    size: tuple[int, int] = (160, 96),
) -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=fps)
    stream.width = size[0]
    stream.height = size[1]
    stream.pix_fmt = "yuv420p"
    for index in range(frame_count):
        image = Image.new(
            "RGB",
            size,
            (
                (index * 17) % 256,
                (index * 37) % 256,
                (index * 67) % 256,
            ),
        )
        frame = av.VideoFrame.from_image(image)
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


def _video_with_black_transitions(
    *,
    seconds: int = 8,
    fps: int = 12,
    size: tuple[int, int] = (160, 96),
) -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=fps)
    stream.width = size[0]
    stream.height = size[1]
    stream.pix_fmt = "yuv420p"
    palette = (
        (200, 55, 55),
        (230, 145, 35),
        (210, 200, 55),
        (55, 175, 90),
        (45, 155, 195),
        (65, 95, 210),
        (135, 75, 200),
        (205, 65, 155),
    )
    for index in range(seconds * fps):
        if index > 0 and index % fps == 0:
            image = Image.new("RGB", size, (0, 0, 0))
        else:
            image = Image.new("RGB", size, palette[(index // fps) % len(palette)])
        frame = av.VideoFrame.from_image(image)
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


def _video_with_repeated_target_scenes(
    *,
    fps: int = 12,
    size: tuple[int, int] = (160, 96),
) -> bytes:
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp4")
    stream = container.add_stream("mpeg4", rate=fps)
    stream.width = size[0]
    stream.height = size[1]
    stream.pix_fmt = "yuv420p"
    scene_colors = (
        (200, 55, 55),
        (55, 175, 90),
        (45, 155, 195),
        (55, 175, 90),
        (210, 200, 55),
        (65, 95, 210),
        (135, 75, 200),
        (205, 65, 155),
    )
    for index in range(8 * fps):
        image = Image.new("RGB", size, scene_colors[index // fps])
        frame = av.VideoFrame.from_image(image)
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return output.getvalue()


def _config(**changes) -> KeyframeExtractConfig:
    return KeyframeExtractConfig(
        image_config=ImagePreprocessConfig(
            max_long_edge=120,
            max_pixels=12_000,
            max_output_bytes=30_000,
            output_mime_type="image/jpeg",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    ("quality_mode", "expected_count"),
    [("economy", 4), ("balanced", 6), ("quality", 8)],
)
def test_quality_mode_controls_four_to_eight_representative_frames(
    quality_mode: str, expected_count: int
):
    result = VideoKeyframeExtractor(_config()).extract_bytes(
        _video_bytes(),
        provenance="synthetic-video",
        quality_mode=quality_mode,
    )

    assert len(result.payloads) == expected_count
    assert len(result.timestamps_seconds) == expected_count
    assert result.timestamps_seconds == tuple(sorted(result.timestamps_seconds))
    assert result.timestamps_seconds[0] > 0
    assert result.timestamps_seconds[-1] < result.duration_seconds
    assert len({payload.content_digest for payload in result.payloads}) > 1


def test_outputs_are_only_prepared_video_keyframes():
    source = _video_bytes()
    result = VideoKeyframeExtractor(_config()).extract_bytes(
        source,
        provenance="privacy-fixture",
        quality_mode="economy",
    )

    assert all(payload.kind == "video_keyframe" for payload in result.payloads)
    assert all(payload.mime_type == "image/jpeg" for payload in result.payloads)
    assert all(not payload.data.startswith(source[:16]) for payload in result.payloads)
    assert all(max(payload.width, payload.height) <= 120 for payload in result.payloads)
    assert all(payload.width * payload.height <= 12_000 for payload in result.payloads)
    assert sum(payload.byte_size for payload in result.payloads) <= 120_000


@pytest.mark.parametrize(
    ("quality_mode", "expected_count"),
    [("economy", 4), ("balanced", 6), ("quality", 8)],
)
def test_representative_sampling_skips_black_transitions_and_duplicates(
    quality_mode: str,
    expected_count: int,
):
    result = VideoKeyframeExtractor(_config()).extract_bytes(
        _video_with_black_transitions(),
        provenance="black-transition-fixture",
        quality_mode=quality_mode,
    )

    assert len(result.payloads) == expected_count
    assert len({payload.content_digest for payload in result.payloads}) == expected_count
    for payload in result.payloads:
        with Image.open(io.BytesIO(payload.data)) as decoded:
            luminance = ImageStat.Stat(decoded.convert("L"))
        assert luminance.mean[0] > 8 or luminance.stddev[0] > 5


def test_distinct_color_targets_are_not_misclassified_as_duplicates():
    result = VideoKeyframeExtractor(_config()).extract_bytes(
        _video_with_black_transitions(),
        provenance="distinct-color-fixture",
        quality_mode="quality",
    )

    assert result.timestamps_seconds == pytest.approx(
        tuple(index + 0.5 for index in range(8)),
        abs=0.05,
    )


def test_representative_sampling_advances_past_repeated_nonblack_scene():
    result = VideoKeyframeExtractor(_config()).extract_bytes(
        _video_with_repeated_target_scenes(),
        provenance="repeated-scene-fixture",
        quality_mode="economy",
    )

    assert len(result.payloads) == 4
    assert len({payload.content_digest for payload in result.payloads}) == 4
    assert result.timestamps_seconds[1] > 3.0


def test_file_result_does_not_expose_local_path(tmp_path: Path):
    source = tmp_path / "private-video.mp4"
    source.write_bytes(_video_bytes())

    result = VideoKeyframeExtractor(_config()).extract_file(
        source,
        quality_mode="economy",
    )

    assert str(source) not in repr(result)
    assert source.name not in repr(result)
    assert all(payload.provenance == "local-video-frame" for payload in result.payloads)


def test_input_byte_limit_is_checked_before_open(tmp_path: Path):
    source = tmp_path / "too-large.mp4"
    source.write_bytes(b"x" * 101)
    extractor = VideoKeyframeExtractor(_config(max_input_bytes=100))

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_file(source, quality_mode="economy")

    assert caught.value.code == "input_too_large"
    assert str(source) not in str(caught.value)


def test_duration_limit_fails_closed_before_frame_extraction():
    extractor = VideoKeyframeExtractor(_config(max_duration_seconds=1.0))

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(frame_count=48, fps=12),
            provenance="long-fixture",
            quality_mode="balanced",
        )

    assert caught.value.code == "duration_limit"


def test_source_pixel_limit_is_checked_before_decode():
    extractor = VideoKeyframeExtractor(_config(max_source_pixels=10_000))

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(size=(160, 96)),
            provenance="large-frame-fixture",
            quality_mode="economy",
        )

    assert caught.value.code == "source_pixel_limit"


def test_decode_frame_limit_bounds_work_even_when_seeking():
    extractor = VideoKeyframeExtractor(_config(max_decode_frames=1))

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(),
            provenance="decode-budget",
            quality_mode="economy",
        )

    assert caught.value.code == "decode_frame_limit"


def test_corrupt_or_unsupported_video_returns_structured_error():
    with pytest.raises(MediaProcessingError) as caught:
        VideoKeyframeExtractor(_config()).extract_bytes(
            b"not a video",
            provenance="corrupt-fixture",
            quality_mode="economy",
        )

    assert caught.value.code == "invalid_video"
    assert caught.value.stage == "open"
    assert "not a video" not in str(caught.value)


def test_invalid_quality_mode_is_rejected_before_decode():
    with pytest.raises(MediaProcessingError) as caught:
        VideoKeyframeExtractor(_config()).extract_bytes(
            b"ignored",
            provenance="invalid-mode",
            quality_mode="ultra",
        )

    assert caught.value.code == "invalid_quality_mode"


def test_cancellation_is_checked_during_frame_sampling():
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(MediaProcessingError) as caught:
        VideoKeyframeExtractor(_config()).extract_bytes(
            _video_bytes(),
            provenance="cancelled-fixture",
            quality_mode="balanced",
            cancellation_token=cancelled,
        )

    assert caught.value.code == "cancelled"


def test_timeout_uses_injected_clock_before_opening_video():
    ticks = iter((10.0, 12.0))
    extractor = VideoKeyframeExtractor(
        _config(timeout_seconds=1.0),
        clock=lambda: next(ticks),
    )

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(),
            provenance="timeout-fixture",
            quality_mode="economy",
        )

    assert caught.value.code == "timeout"


def test_cancellation_propagates_into_keyframe_image_preprocessing(monkeypatch):
    extractor = VideoKeyframeExtractor(_config())
    child = extractor._image_preprocessor
    original_encode = child._encode_once
    cancel_requested = False

    def encode_then_cancel(image, mime_type, quality):
        nonlocal cancel_requested
        encoded = original_encode(image, mime_type, quality)
        cancel_requested = True
        return encoded

    monkeypatch.setattr(child, "_encode_once", encode_then_cancel)

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(),
            provenance="cancel-during-keyframe",
            quality_mode="economy",
            cancellation_token=lambda: cancel_requested,
        )

    assert caught.value.code == "cancelled"
    assert caught.value.stage == "finalize"


def test_parent_deadline_is_enforced_inside_keyframe_image_preprocessing(
    monkeypatch,
):
    now = 10.0

    def clock() -> float:
        return now

    extractor = VideoKeyframeExtractor(_config(timeout_seconds=1.0), clock=clock)
    child = extractor._image_preprocessor
    original_encode = child._encode_once

    def slow_encode(image, mime_type, quality):
        nonlocal now
        encoded = original_encode(image, mime_type, quality)
        now = 12.0
        return encoded

    monkeypatch.setattr(child, "_encode_once", slow_encode)

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(),
            provenance="timeout-during-keyframe",
            quality_mode="economy",
        )

    assert caught.value.code == "timeout"
    assert caught.value.stage == "finalize"


def test_total_output_byte_limit_fails_closed():
    extractor = VideoKeyframeExtractor(
        _config(max_total_output_bytes=100)
    )

    with pytest.raises(MediaProcessingError) as caught:
        extractor.extract_bytes(
            _video_bytes(),
            provenance="payload-budget",
            quality_mode="economy",
        )

    assert caught.value.code == "total_output_limit"


def test_config_rejects_frame_counts_outside_approved_range():
    with pytest.raises(ValueError):
        KeyframeExtractConfig(candidate_window_seconds=0)
    with pytest.raises(ValueError):
        KeyframeExtractConfig(max_candidate_frames_per_sample=0)
    with pytest.raises(ValueError):
        KeyframeExtractConfig(economy_frame_count=3)
    with pytest.raises(ValueError):
        KeyframeExtractConfig(quality_frame_count=9)
    with pytest.raises(ValueError):
        KeyframeExtractConfig(
            economy_frame_count=6,
            balanced_frame_count=5,
            quality_frame_count=8,
        )
