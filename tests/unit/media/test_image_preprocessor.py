"""M3 Task 11: bounded local image preprocessing."""
from __future__ import annotations

import io
import random
from pathlib import Path

import pytest
from PIL import Image

from src.core.provider_protocol import PreparedVisualPayload
from src.services.media.image_preprocessor import (
    ImagePreprocessConfig,
    ImagePreprocessor,
    MediaProcessingError,
)


def _image_bytes(
    size: tuple[int, int],
    *,
    image_format: str = "PNG",
    mode: str = "RGB",
    color=(31, 127, 223),
) -> bytes:
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _noise_png(size: tuple[int, int]) -> bytes:
    rng = random.Random(20260729)
    data = rng.randbytes(size[0] * size[1] * 3)
    image = Image.frombytes("RGB", size, data)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_config_rejects_invalid_or_incoherent_limits():
    with pytest.raises(ValueError):
        ImagePreprocessConfig(max_long_edge=0)
    with pytest.raises(ValueError):
        ImagePreprocessConfig(max_pixels=0)
    with pytest.raises(ValueError):
        ImagePreprocessConfig(max_output_bytes=0)
    with pytest.raises(ValueError):
        ImagePreprocessConfig(min_quality=90, initial_quality=80)
    with pytest.raises(ValueError):
        ImagePreprocessConfig(output_mime_type="image/gif")


def test_long_edge_and_pixel_limits_are_both_enforced():
    processor = ImagePreprocessor(
        ImagePreprocessConfig(
            max_long_edge=1000,
            max_pixels=300_000,
            max_output_bytes=500_000,
            output_mime_type="image/jpeg",
        )
    )

    payload = processor.process_bytes(
        _image_bytes((2400, 1600)),
        source_index=0,
        provenance="synthetic-image",
    )

    assert isinstance(payload, PreparedVisualPayload)
    assert max(payload.width, payload.height) <= 1000
    assert payload.width * payload.height <= 300_000
    assert payload.kind == "resized_image"


def test_configured_output_format_converts_png_to_jpeg():
    payload = ImagePreprocessor(
        ImagePreprocessConfig(
            output_mime_type="image/jpeg",
            max_output_bytes=100_000,
        )
    ).process_bytes(
        _image_bytes((64, 32), image_format="PNG"),
        source_index=2,
        provenance="unit-test",
    )

    assert payload.mime_type == "image/jpeg"
    assert payload.data.startswith(b"\xff\xd8")
    assert payload.source_index == 2
    with Image.open(io.BytesIO(payload.data)) as decoded:
        assert decoded.size == (64, 32)
        assert decoded.mode == "RGB"


def test_alpha_can_be_preserved_as_png():
    payload = ImagePreprocessor(
        ImagePreprocessConfig(
            output_mime_type="image/png",
            max_output_bytes=100_000,
        )
    ).process_bytes(
        _image_bytes((32, 32), mode="RGBA", color=(20, 40, 60, 80)),
        source_index=0,
        provenance="alpha-fixture",
    )

    assert payload.mime_type == "image/png"
    with Image.open(io.BytesIO(payload.data)) as decoded:
        assert decoded.mode == "RGBA"


def test_max_output_bytes_triggers_quality_and_dimension_reduction():
    config = ImagePreprocessConfig(
        max_long_edge=512,
        max_pixels=512 * 512,
        max_output_bytes=18_000,
        output_mime_type="image/jpeg",
        initial_quality=88,
        min_quality=35,
    )

    payload = ImagePreprocessor(config).process_bytes(
        _noise_png((512, 512)),
        source_index=0,
        provenance="deterministic-noise",
    )

    assert payload.byte_size <= 18_000
    assert payload.width < 512 or payload.height < 512


def test_file_input_is_read_with_a_hard_byte_limit(tmp_path: Path):
    source = tmp_path / "oversized.png"
    source.write_bytes(b"x" * 101)
    processor = ImagePreprocessor(
        ImagePreprocessConfig(max_input_bytes=100, max_output_bytes=100)
    )

    with pytest.raises(MediaProcessingError) as caught:
        processor.process_file(source, source_index=0)

    assert caught.value.code == "input_too_large"
    assert str(source) not in str(caught.value)


def test_corrupt_image_returns_structured_safe_error():
    processor = ImagePreprocessor()

    with pytest.raises(MediaProcessingError) as caught:
        processor.process_bytes(
            b"not an image",
            source_index=0,
            provenance="corrupt-fixture",
        )

    assert caught.value.code == "decode_failed"
    assert caught.value.stage == "decode"
    assert "not an image" not in str(caught.value)


def test_cancellation_is_checked_before_decode():
    processor = ImagePreprocessor()

    with pytest.raises(MediaProcessingError) as caught:
        processor.process_bytes(
            _image_bytes((10, 10)),
            source_index=0,
            provenance="cancelled",
            cancellation_token=lambda: True,
        )

    assert caught.value.code == "cancelled"


def test_timeout_uses_injected_monotonic_clock():
    ticks = iter((10.0, 12.0))
    processor = ImagePreprocessor(
        ImagePreprocessConfig(timeout_seconds=1.0),
        clock=lambda: next(ticks),
    )

    with pytest.raises(MediaProcessingError) as caught:
        processor.process_bytes(
            _image_bytes((10, 10)),
            source_index=0,
            provenance="timeout",
        )

    assert caught.value.code == "timeout"


def test_caller_deadline_can_strictly_bound_child_preprocessing():
    ticks = iter((10.0, 12.0))
    processor = ImagePreprocessor(
        ImagePreprocessConfig(timeout_seconds=100.0),
        clock=lambda: next(ticks),
    )

    with pytest.raises(MediaProcessingError) as caught:
        processor.process_bytes(
            _image_bytes((10, 10)),
            source_index=0,
            provenance="parent-deadline",
            deadline=11.0,
        )

    assert caught.value.code == "timeout"
    assert caught.value.stage == "decode"


def test_output_contains_no_source_path(tmp_path: Path):
    source = tmp_path / "private-name.png"
    source.write_bytes(_image_bytes((24, 24)))

    payload = ImagePreprocessor().process_file(source, source_index=4)

    assert payload.provenance == "local-image"
    assert str(source) not in repr(payload)
    assert source.name not in repr(payload)


def test_source_index_and_provenance_are_validated_before_work():
    processor = ImagePreprocessor()

    with pytest.raises(MediaProcessingError) as negative:
        processor.process_bytes(
            b"ignored",
            source_index=-1,
            provenance="unit-test",
        )
    with pytest.raises(MediaProcessingError) as missing:
        processor.process_bytes(
            b"ignored",
            source_index=0,
            provenance="",
        )

    assert negative.value.code == "invalid_request"
    assert missing.value.code == "invalid_request"
