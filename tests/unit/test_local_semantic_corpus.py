"""Mechanical checks for the synthetic local-inference review corpus."""

import hashlib
import importlib.util
import json
from pathlib import Path

import av
import fitz
import pytest
from PIL import Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_local_semantic_corpus.py"
EXPECTED_SOURCES = {
    "case_01": ("text", "case_01.txt"),
    "case_02": ("text", "case_02.txt"),
    "case_03": ("text", "case_03.txt"),
    "case_04": ("image", "case_04.png"),
    "case_05": ("text_pdf", "case_05.pdf"),
    "case_06": ("image_pdf", "case_06.pdf"),
    "case_07": ("video", "case_07.mp4"),
    "case_08": ("image", "case_08.png"),
}


@pytest.fixture
def corpus_module():
    assert SCRIPT.is_file(), "synthetic corpus generator is missing"
    spec = importlib.util.spec_from_file_location("local_semantic_corpus_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_under(destination: Path, relative: str) -> Path:
    resolved = (destination / relative).resolve()
    assert resolved.is_relative_to(destination.resolve())
    return resolved


def test_generator_script_and_api_exist():
    assert SCRIPT.is_file(), "synthetic corpus generator is missing"
    spec = importlib.util.spec_from_file_location("local_semantic_corpus_api", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.prepare_corpus)


def test_prepare_corpus_writes_exact_opaque_cases_and_review_metadata(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)

    assert manifest["schema_version"] == 1
    assert manifest["actual_inference_run"] is False
    assert manifest["human_model_quality_reviewed"] is False
    cases = manifest["cases"]
    assert len(cases) == 8
    assert len({case["case_id"] for case in cases}) == 8
    assert {
        case["case_id"]: (case["kind"], case["source_path"])
        for case in cases
    } == EXPECTED_SOURCES
    assert json.loads((destination / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_manifest_paths_hashes_and_oracle_fields_are_inspectable(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)

    for case in manifest["cases"]:
        source = _resolve_under(destination, case["source_path"])
        assert source.is_file() and source.stat().st_size > 0
        assert case["bytes"] == source.stat().st_size
        assert case["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert len(case["sha256"]) == 64
        assert case["expected_facts"]
        assert case["prohibited_facts"]
        for preview in case["preview_paths"]:
            assert _resolve_under(destination, preview).is_file()
    assert _resolve_under(destination, manifest["contact_sheet"]).is_file()


def test_missing_cjk_font_fails_clearly_without_manifest(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    with pytest.raises(corpus_module.CorpusError, match="CJK font"):
        corpus_module.prepare_corpus(destination, font_path=tmp_path / "missing-font.ttf")
    assert not (destination / "manifest.json").exists()


def test_existing_destination_is_refused_without_modification(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("caller data", encoding="utf-8")

    with pytest.raises(corpus_module.CorpusError, match="already exists"):
        corpus_module.prepare_corpus(destination)

    assert sentinel.read_text(encoding="utf-8") == "caller data"
    assert list(destination.iterdir()) == [sentinel]


def test_text_pdf_has_two_distinct_searchable_pages_and_rendered_previews(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)
    case = next(item for item in manifest["cases"] if item["case_id"] == "case_05")

    with fitz.open(destination / case["source_path"]) as document:
        assert len(document) == 2
        page_text = [page.get_text() for page in document]
    normalized_text = [" ".join(text.split()) for text in page_text]
    assert "Bound-Book Scanning" in normalized_text[0]
    assert "gutter shadow" in page_text[0]
    assert "Colour and OCR Comparison" in normalized_text[1]
    assert "italic captions" in page_text[1]
    assert "Page 1 of 2" in page_text[0]
    assert "Page 2 of 2" in page_text[1]
    assert len(case["preview_paths"]) == 2
    for preview_path in case["preview_paths"]:
        with Image.open(destination / preview_path) as preview:
            assert preview.size == (600, 800)
            preview.verify()


def test_scanned_pdf_pages_have_images_but_no_searchable_text(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)
    case = next(item for item in manifest["cases"] if item["case_id"] == "case_06")

    with fitz.open(destination / case["source_path"]) as document:
        assert len(document) == 2
        for page in document:
            assert page.get_text().strip() == ""
            assert page.get_images(full=True), "each scanned page must embed a real raster image"
    assert len(case["preview_paths"]) == 2
    for preview_path in case["preview_paths"]:
        with Image.open(destination / preview_path) as preview:
            assert preview.size == (600, 800)
            assert ImageStat.Stat(preview.convert("L")).extrema[0][0] < 245


def test_video_decodes_exact_ordered_duration_with_motion_inside_each_stage(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)
    case = next(item for item in manifest["cases"] if item["case_id"] == "case_07")

    decoded = []
    timestamps = []
    with av.open(str(destination / case["source_path"])) as container:
        stream = container.streams.video[0]
        assert stream.average_rate == 8
        for frame in container.decode(video=0):
            decoded.append(frame.to_image())
            timestamps.append(frame.pts)
    assert len(decoded) == 48
    assert all(frame.size == (640, 360) for frame in decoded)
    assert timestamps == sorted(timestamps)

    stage_colours = ((238, 246, 232), (230, 244, 251), (247, 240, 223))
    observed_order = []
    for frame in decoded:
        colour = frame.getpixel((10, 350))
        observed_order.append(min(range(3), key=lambda index: sum(
            (colour[channel] - stage_colours[index][channel]) ** 2 for channel in range(3)
        )))
    assert observed_order == [0] * 16 + [1] * 16 + [2] * 16
    for start in (0, 16, 32):
        difference = ImageChops.difference(decoded[start], decoded[start + 15]).convert("L")
        assert ImageStat.Stat(difference).rms[0] > 1.0, "each stage must visibly evolve"
    assert len(case["preview_paths"]) == 3
    assert all(Image.open(destination / path).size == (640, 360)
               for path in case["preview_paths"])


def test_fixed_images_contact_sheet_and_total_size_are_valid(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    manifest = corpus_module.prepare_corpus(destination)
    case_04 = destination / "case_04.png"
    case_08 = destination / "case_08.png"

    with Image.open(case_04) as diagram:
        assert diagram.size == (1200, 900)
        assert ImageStat.Stat(diagram.convert("L")).extrema[0][0] < 50
    with Image.open(case_08) as blank:
        assert blank.size == (800, 600)
        assert blank.mode == "RGB"
        assert blank.getextrema() == ((255, 255), (255, 255), (255, 255))
    with Image.open(destination / manifest["contact_sheet"]) as contact_sheet:
        assert contact_sheet.size == (1200, 620)
        contact_sheet.verify()
    total_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    assert total_bytes < 32 * 1024**2


def test_exit_a_label_is_inside_an_arrow_free_region(corpus_module, tmp_path):
    destination = tmp_path / "corpus"
    corpus_module.prepare_corpus(destination)
    with Image.open(destination / "case_04.png") as diagram:
        image = diagram.convert("RGB")
        red = (180, 35, 24)
        green = (11, 143, 85)
        red_points = [
            (x, y)
            for y in range(image.height)
            for x in range(500)
            if image.getpixel((x, y)) == red
        ]
        assert red_points, "Exit A must contain visible red label pixels"
        label_box = (
            min(x for x, _ in red_points),
            min(y for _, y in red_points),
            max(x for x, _ in red_points) + 1,
            max(y for _, y in red_points) + 1,
        )
        label_pixels = image.crop(label_box).get_flattened_data()
        assert green not in label_pixels, "green evacuation arrows must not cover Exit A"
        left, top, right, bottom = label_box
        assert 160 <= left < right <= 300
        assert 350 <= top < bottom <= 410


def test_failed_written_media_validation_never_publishes_manifest(
        corpus_module, tmp_path, monkeypatch):
    destination = tmp_path / "corpus"
    original = corpus_module._make_image_pdf

    def create_then_corrupt(path, preview_dir, font_path):
        previews = original(path, preview_dir, font_path)
        path.unlink()
        invalid = fitz.open()
        invalid.new_page(width=600, height=800)
        invalid.save(path)
        invalid.close()
        return previews

    monkeypatch.setattr(corpus_module, "_make_image_pdf", create_then_corrupt)
    with pytest.raises(corpus_module.CorpusError, match="case_06"):
        corpus_module.prepare_corpus(destination)
    assert destination.exists()
    assert not (destination / "manifest.json").exists()


def test_source_hashes_are_deterministic_across_fresh_destinations(corpus_module, tmp_path):
    first = corpus_module.prepare_corpus(tmp_path / "first")
    second = corpus_module.prepare_corpus(tmp_path / "second")

    assert {
        case["case_id"]: case["sha256"] for case in first["cases"]
    } == {
        case["case_id"]: case["sha256"] for case in second["cases"]
    }


@pytest.mark.parametrize("fault", ["rate", "duplicate_time", "missing_time", "nan_time", "stage_order", "frame_count"])
def test_runtime_video_validator_rejects_invalid_temporal_contract(corpus_module, tmp_path, fault):
    destination = tmp_path / "corpus"
    corpus_module.prepare_corpus(destination)
    with av.open(str(destination / "case_07.mp4")) as container:
        rate = container.streams.video[0].average_rate
        frames = list(container.decode(video=0))
    decoded = [frame.to_image() for frame in frames]
    timestamps = [frame.time for frame in frames]
    if fault == "rate":
        rate = 4
    elif fault == "duplicate_time":
        timestamps[1] = timestamps[0]
    elif fault == "missing_time":
        timestamps[12] = None
    elif fault == "nan_time":
        timestamps[12] = float("nan")
    elif fault == "stage_order":
        decoded.reverse()
    else:
        decoded.pop()
    with pytest.raises(corpus_module.CorpusError, match="MP4 validation"):
        corpus_module._validate_video_frames(decoded, timestamps, rate)


@pytest.mark.parametrize("filename,anchors,absent", [
    ("case_01.txt", ("海岚实验室", "星桥", "v2.1", "2026年8月", "图书馆", "东教学楼", "更换失效交换机"), ("2026年8月1日",)),
    ("case_02.txt", ("山岚社区", "雨水花园", "泥沙", "排水", "强降雨"), ("2026", "作者：", "版本：")),
    ("case_03.txt", ("North Pier", "v3.2", "OCR", "invoices", "engineering drawings", "Retention rules"), ("2026",)),
])
def test_text_sources_preserve_review_anchors(corpus_module, tmp_path, filename, anchors, absent):
    destination = tmp_path / "corpus"
    corpus_module.prepare_corpus(destination)
    text = (destination / filename).read_text(encoding="utf-8")
    assert all(anchor in text for anchor in anchors)
    assert all(item not in text for item in absent)


def test_runtime_video_validation_failure_prevents_manifest(corpus_module, tmp_path, monkeypatch):
    destination = tmp_path / "corpus"
    observations = []

    def reject(decoded, timestamps, rate):
        observations.append((len(decoded), len(timestamps), rate))
        raise corpus_module.CorpusError("MP4 validation rejected by diagnostic fault")

    monkeypatch.setattr(corpus_module, "_validate_video_frames", reject)
    with pytest.raises(corpus_module.CorpusError, match="MP4 validation"):
        corpus_module.prepare_corpus(destination)
    assert observations == [(48, 48, 8)]
    assert not (destination / "manifest.json").exists()
