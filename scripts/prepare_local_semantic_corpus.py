"""Prepare a deterministic synthetic corpus for offline semantic review.

This script creates source media and mechanical review artifacts only.  It does
not load a model, call a provider, or judge model quality.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Iterable

import av
import fitz
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = (
    ROOT / "tests" / "screenshots" / "qa-current" / "local-privacy"
    / "semantic-corpus-v1"
)
MAX_CORPUS_BYTES = 32 * 1024**2
VIDEO_SIZE = (640, 360)
VIDEO_FPS = 8
VIDEO_FRAMES = 48
PDF_PAGE_SIZE = (600, 800)


class CorpusError(RuntimeError):
    """Raised when safe corpus preparation or validation cannot complete."""


def _resolve_font(font_path: Path | None) -> Path:
    if font_path is not None:
        candidates = [Path(font_path)]
    else:
        windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        font_dir = windows_root / "Fonts"
        candidates = [
            font_dir / "msyh.ttc",
            font_dir / "msjh.ttc",
            font_dir / "simhei.ttf",
            font_dir / "simsun.ttc",
        ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            font = ImageFont.truetype(str(candidate), 32)
            glyphs = [bytes(font.getmask(character)) for character in "青火移"]
            if all(glyphs) and len(set(glyphs)) > 1:
                return candidate.resolve()
        except (OSError, ValueError):
            continue
    raise CorpusError("No usable CJK font was found below the Windows font directory")


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, *, font: ImageFont.FreeTypeFont,
              width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = character
            else:
                current = candidate
        lines.append(current)
    return lines


def _draw_wrapped(draw: ImageDraw.ImageDraw, position: tuple[int, int], text: str,
                  *, font: ImageFont.FreeTypeFont, fill: str, width: int,
                  spacing: int = 12) -> int:
    x, y = position
    line_height = font.size + spacing
    for line in _fit_text(draw, text, font=font, width=width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _make_fire_diagram(path: Path, font_path: Path) -> None:
    image = Image.new("RGB", (1200, 900), "#f7f3e9")
    draw = ImageDraw.Draw(image)
    title = _font(font_path, 52)
    label = _font(font_path, 34)
    small = _font(font_path, 26)
    draw.text((54, 36), "北区仓库  消防疏散路线", font=title, fill="#17324d")
    draw.rounded_rectangle((65, 135, 1135, 715), radius=18, outline="#243b53", width=8,
                           fill="#fffdf7")
    draw.line((600, 140, 600, 715), fill="#8d99a6", width=7)
    draw.line((70, 430, 1130, 430), fill="#8d99a6", width=7)
    draw.text((170, 250), "存储区", font=label, fill="#334e68")
    draw.text((760, 250), "包装区", font=label, fill="#334e68")
    draw.text((170, 530), "收货区", font=label, fill="#334e68")
    draw.text((760, 530), "设备区", font=label, fill="#334e68")
    draw.rectangle((45, 300, 85, 420), fill="#f7f3e9")
    draw.rectangle((1115, 470, 1155, 590), fill="#f7f3e9")
    draw.text((170, 365), "出口A", font=label, fill="#b42318")
    draw.text((965, 500), "出口B", font=label, fill="#b42318")
    routes = [((330, 300), (85, 360)), ((845, 300), (1115, 520)),
              ((330, 585), (85, 390)), ((845, 585), (1115, 550))]
    for start, end in routes:
        draw.line((*start, *end), fill="#0b8f55", width=16)
        ex, ey = end
        sx, sy = start
        direction = 1 if ex > sx else -1
        draw.polygon([(ex, ey), (ex - direction * 42, ey - 28),
                      (ex - direction * 42, ey + 28)], fill="#0b8f55")
    draw.rounded_rectangle((440, 760, 760, 855), radius=24, fill="#d9f2e6",
                           outline="#0b8f55", width=5)
    draw.text((530, 782), "集合点", font=label, fill="#0b6b42")
    draw.text((815, 805), "沿绿色箭头撤离", font=small, fill="#486581")
    image.save(path, "PNG")


def _make_text_pdf(path: Path, preview_dir: Path) -> list[Path]:
    pages = [
        (
            "Cedar Research Library Scanner Evaluation - Bound-Book Scanning",
            "The trial compared cradle scanners with overhead capture rigs for tightly "
            "bound monographs. The cradle reduced gutter shadow and spine stress, while "
            "the overhead rig was faster on volumes that opened flat. Fine serif text "
            "remained legible at the selected optical resolution. Operators recorded "
            "page curvature, focus consistency, handling time, and the need for rescans.\n\n"
            "Recommendation: use the cradle workflow for fragile bindings and the "
            "overhead workflow only when a volume can be opened safely without pressure.",
        ),
        (
            "Cedar Research Library Scanner Evaluation - Colour and OCR Comparison",
            "Colour targets showed that neutral greys drifted warm when the scanner "
            "profile was reused across different lamps. A fresh calibration target "
            "reduced the visible cast and improved consistency between batches.\n\n"
            "OCR review found substitution errors in small italic captions and in text "
            "printed close to illustrations. Straight body text performed better. The "
            "recommended workflow stores the calibrated master image, the OCR text, and "
            "a short exception log for pages that require manual correction.",
        ),
    ]
    document = fitz.open()
    for number, (heading, body) in enumerate(pages, start=1):
        page = document.new_page(width=PDF_PAGE_SIZE[0], height=PDF_PAGE_SIZE[1])
        page.insert_textbox(fitz.Rect(45, 45, 555, 130), heading,
                            fontname="helv", fontsize=18, color=(0.08, 0.20, 0.32))
        page.insert_textbox(fitz.Rect(55, 155, 545, 700), body,
                            fontname="helv", fontsize=12, lineheight=1.45,
                            color=(0.12, 0.15, 0.18))
        page.insert_text((275, 760), f"Page {number} of 2", fontname="helv", fontsize=10)
    document.save(path, no_new_id=True)
    document.close()
    return _render_pdf(path, preview_dir)


def _scan_page(font_path: Path, *, page_number: int) -> Image.Image:
    image = Image.new("RGB", (1200, 1600), "#fffef8")
    draw = ImageDraw.Draw(image)
    title = _font(font_path, 58)
    heading = _font(font_path, 42)
    body = _font(font_path, 34)
    small = _font(font_path, 28)
    draw.rectangle((60, 60, 1140, 1540), outline="#5b6470", width=5)
    draw.text((105, 105), "青禾咖啡馆", font=title, fill="#254d3f")
    if page_number == 1:
        draw.text((105, 220), "咖啡机维护确认", font=heading, fill="#222222")
        details = (
            "设备型号：CM-20\n"
            "维护时间：2026年8月\n\n"
            "检查项目\n"
            "1. 冲煮压力与温度稳定\n"
            "2. 蒸汽喷嘴通畅\n"
            "3. 排水盘与管路清洁\n\n"
            "结论：设备完成例行检查，可正常使用。"
        )
    else:
        draw.text((105, 220), "锅炉除垢与密封圈更换", font=heading, fill="#222222")
        details = (
            "版本：v1.1\n\n"
            "维护记录\n"
            "1. 完成锅炉除垢和清水冲洗\n"
            "2. 更换老化密封圈\n"
            "3. 复测加热与密封状态\n\n"
            "结论：无渗漏，运行状态正常。"
        )
    _draw_wrapped(draw, (115, 340), details, font=body, fill="#263238", width=940,
                  spacing=18)
    draw.text((520, 1470), f"第 {page_number} 页 / 共 2 页", font=small, fill="#59636e")
    return image


def _make_image_pdf(path: Path, preview_dir: Path, font_path: Path) -> list[Path]:
    document = fitz.open()
    for page_number in (1, 2):
        raster = _scan_page(font_path, page_number=page_number)
        buffer = io.BytesIO()
        raster.save(buffer, "PNG")
        page = document.new_page(width=PDF_PAGE_SIZE[0], height=PDF_PAGE_SIZE[1])
        page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(path, deflate=True, no_new_id=True)
    document.close()
    return _render_pdf(path, preview_dir)


def _render_pdf(path: Path, preview_dir: Path) -> list[Path]:
    previews: list[Path] = []
    with fitz.open(path) as document:
        if len(document) != 2:
            raise CorpusError(f"PDF validation failed for {path.name}: expected two pages")
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            preview = preview_dir / f"{path.stem}_page_{index + 1}.png"
            pixmap.save(preview)
            with Image.open(preview) as reopened:
                reopened.verify()
            previews.append(preview)
    return previews


def _plant_frame(font_path: Path, frame_number: int) -> Image.Image:
    stage = min(frame_number // 16, 2)
    progress = (frame_number % 16) / 15
    backgrounds = ("#eef6e8", "#e6f4fb", "#f7f0df")
    image = Image.new("RGB", VIDEO_SIZE, backgrounds[stage])
    draw = ImageDraw.Draw(image)
    title_font = _font(font_path, 38)
    label_font = _font(font_path, 24)
    titles = ("剪枝", "水培生根", "移栽")
    draw.text((36, 25), f"植物繁育阶段 {stage + 1}", font=label_font, fill="#3b4a3f")
    draw.rounded_rectangle((30, 78, 610, 325), radius=25, fill="#ffffff",
                           outline="#86a58b", width=4)
    if stage == 0:
        draw.line((310, 275, 310, 125), fill="#39844a", width=16)
        draw.line((310, 190, 235, 135), fill="#39844a", width=12)
        branch_end = 385 - int(45 * progress)
        draw.line((310, 210, branch_end, 150 + int(30 * progress)), fill="#39844a", width=12)
        draw.ellipse((205, 105, 265, 150), fill="#65a765")
        if progress < 0.72:
            draw.ellipse((360, 118, 420, 164), fill="#65a765")
        scissor_x = 485 - int(100 * progress)
        opening = 55 - int(38 * progress)
        draw.line((scissor_x, 115 + opening, scissor_x - 72, 198), fill="#424b54", width=10)
        draw.line((scissor_x, 225 - opening, scissor_x - 72, 198), fill="#424b54", width=10)
        draw.ellipse((scissor_x - 8, 92 + opening, scissor_x + 28, 128 + opening),
                     outline="#b65c35", width=8)
        draw.ellipse((scissor_x - 8, 212 - opening, scissor_x + 28, 248 - opening),
                     outline="#b65c35", width=8)
    elif stage == 1:
        draw.rectangle((225, 178, 415, 294), fill="#bde5f8", outline="#4b93b5", width=5)
        bob = int(8 * (0.5 - abs(progress - 0.5)))
        draw.line((320, 95 + bob, 320, 225), fill="#3d8b50", width=15)
        root_growth = int(15 + 70 * progress)
        for offset, x in enumerate((270, 300, 340, 370)):
            draw.arc((x, 210, x + 65, 225 + root_growth + offset * 3), 155, 315,
                     fill="#d9c09b", width=5)
        draw.ellipse((260, 102 + bob, 315, 145 + bob), fill="#67ad68")
        draw.ellipse((325, 110 + bob, 380, 152 + bob), fill="#67ad68")
        for offset in range(4):
            bubble_y = 272 - ((frame_number * 7 + offset * 29) % 85)
            draw.ellipse((245 + offset * 42, bubble_y, 255 + offset * 42, bubble_y + 10),
                         outline="#579abb", width=2)
    else:
        draw.polygon([(205, 210), (435, 210), (400, 305), (240, 305)], fill="#b46f45")
        draw.rectangle((208, 205, 432, 230), fill="#6f442d")
        top = 170 - int(75 * progress)
        leaf_width = 34 + int(30 * progress)
        draw.line((320, 220, 320, top + 18), fill="#39844a", width=15)
        draw.ellipse((320 - leaf_width - 8, top + 8, 312, top + 52), fill="#69aa63")
        draw.ellipse((328, top, 328 + leaf_width + 8, top + 48), fill="#69aa63")
        draw.arc((250, 223, 390, 285), 190, 350, fill="#d8b38a", width=4)
    draw.text((468, 250), titles[stage], font=title_font, fill="#1e4d2b")
    return image


def _validate_video_frames(decoded: list[Image.Image], timestamps: list[float | None], rate) -> None:
    """Enforce the fixed synthetic timeline before publishing its manifest."""
    if rate != VIDEO_FPS:
        raise CorpusError("MP4 validation failed: expected 8 fps")
    if len(decoded) != VIDEO_FRAMES or len(timestamps) != VIDEO_FRAMES \
            or any(image.size != VIDEO_SIZE for image in decoded):
        raise CorpusError("MP4 validation failed: expected 48 decoded 640x360 frames")
    for index, timestamp in enumerate(timestamps):
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) \
                or not math.isclose(timestamp, index / VIDEO_FPS, abs_tol=1e-7):
            raise CorpusError("MP4 validation failed: missing or invalid ordered timestamps")
    colours = ((238, 246, 232), (230, 244, 251), (247, 240, 223))
    for index, frame in enumerate(decoded):
        observed = frame.getpixel((10, 350))
        nearest = min(range(3), key=lambda stage: sum(
            (observed[channel] - colours[stage][channel]) ** 2 for channel in range(3)
        ))
        if nearest != index // 16 or max(
                abs(observed[channel] - colours[nearest][channel]) for channel in range(3)) > 12:
            raise CorpusError("MP4 validation failed: incorrect propagation stage order")
    for start in (0, 16, 32):
        difference = ImageChops.difference(decoded[start], decoded[start + 15]).convert("L")
        if ImageStat.Stat(difference).rms[0] <= 1.0:
            raise CorpusError("MP4 validation failed: a propagation stage has no visible motion")


def _make_video(path: Path, preview_dir: Path, font_path: Path) -> list[Path]:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=VIDEO_FPS)
        stream.width, stream.height = VIDEO_SIZE
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18", "preset": "fast"}
        for frame_number in range(VIDEO_FRAMES):
            frame = av.VideoFrame.from_image(_plant_frame(font_path, frame_number))
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    decoded: list[Image.Image] = []
    timestamps: list[float | None] = []
    with av.open(str(path), mode="r") as container:
        rate = container.streams.video[0].average_rate
        for frame in container.decode(video=0):
            decoded.append(frame.to_image())
            timestamps.append(frame.time)
    _validate_video_frames(decoded, timestamps, rate)
    previews: list[Path] = []
    for stage_number, index in enumerate((8, 24, 40), start=1):
        preview = preview_dir / f"case_07_stage_{stage_number}.png"
        decoded[index].save(preview, "PNG")
        previews.append(preview)
    return previews


def _make_contact_sheet(destination: Path, cases: list[dict], font_path: Path) -> Path:
    sheet = Image.new("RGB", (1200, 620), "#e9eef3")
    draw = ImageDraw.Draw(sheet)
    title_font = _font(font_path, 27)
    for index, case in enumerate(cases):
        column, row = index % 4, index // 4
        x, y = 15 + column * 295, 15 + row * 300
        draw.rounded_rectangle((x, y, x + 280, y + 285), radius=16, fill="white",
                               outline="#a9b5c1", width=3)
        preview_paths = case["preview_paths"]
        source = destination / case["source_path"]
        thumbnail: Image.Image
        if preview_paths:
            thumbnail = Image.open(destination / preview_paths[0]).convert("RGB")
        elif source.suffix == ".png":
            thumbnail = Image.open(source).convert("RGB")
        else:
            thumbnail = Image.new("RGB", (500, 350), "#fffdf7")
            text_draw = ImageDraw.Draw(thumbnail)
            snippet = source.read_text(encoding="utf-8")[:240]
            _draw_wrapped(text_draw, (18, 18), snippet, font=_font(font_path, 21),
                          fill="#263238", width=460, spacing=7)
        thumbnail.thumbnail((250, 215))
        sheet.paste(thumbnail, (x + 15 + (250 - thumbnail.width) // 2, y + 42))
        draw.text((x + 16, y + 8), case["case_id"], font=title_font, fill="#25364a")
        thumbnail.close()
    path = destination / "contact_sheet.png"
    sheet.save(path, "PNG")
    return path


def _validate_png(path: Path, expected_size: tuple[int, int], *, uniform_white: bool = False) -> None:
    try:
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise CorpusError(f"PNG validation failed for {path.name}: unexpected dimensions")
            if uniform_white and image.convert("RGB").getextrema() != (
                    (255, 255), (255, 255), (255, 255)):
                raise CorpusError(f"PNG validation failed for {path.name}: expected uniform white")
    except (OSError, ValueError) as error:
        raise CorpusError(f"PNG validation failed for {path.name}") from error


def _validate_written_media(case_04: Path, case_05: Path, preview_05: list[Path],
                            case_06: Path, preview_06: list[Path],
                            preview_07: list[Path], case_08: Path) -> None:
    _validate_png(case_04, (1200, 900))
    _validate_png(case_08, (800, 600), uniform_white=True)
    with fitz.open(case_05) as document:
        texts = [" ".join(page.get_text().split()) for page in document]
        if len(texts) != 2 or "Bound-Book Scanning" not in texts[0] \
                or "Colour and OCR Comparison" not in texts[1]:
            raise CorpusError("PDF validation failed for case_05.pdf: missing page-specific text")
    with fitz.open(case_06) as document:
        if len(document) != 2:
            raise CorpusError("PDF validation failed for case_06.pdf: expected two pages")
        for page in document:
            if page.get_text().strip() or not page.get_images(full=True):
                raise CorpusError(
                    "PDF validation failed for case_06.pdf: each page must be image-only"
                )
    for preview in [*preview_05, *preview_06]:
        _validate_png(preview, PDF_PAGE_SIZE)
    for preview in preview_07:
        _validate_png(preview, VIDEO_SIZE)


def _relative(destination: Path, path: Path) -> str:
    destination_root = destination.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(destination_root):
        raise CorpusError(f"Output escaped destination: {path.name}")
    return resolved.relative_to(destination_root).as_posix()


def _case(case_id: str, kind: str, source_path: Path, destination: Path,
          expected_facts: Iterable[str], prohibited_facts: Iterable[str],
          previews: Iterable[Path] = ()) -> dict:
    return {
        "case_id": case_id,
        "kind": kind,
        "source_path": _relative(destination, source_path),
        "bytes": source_path.stat().st_size,
        "sha256": _sha256(source_path),
        "expected_facts": list(expected_facts),
        "prohibited_facts": list(prohibited_facts),
        "preview_paths": [_relative(destination, preview) for preview in previews],
    }


def prepare_corpus(destination: Path, *, font_path: Path | None = None) -> dict:
    """Create and mechanically validate the fixed eight-case synthetic corpus."""
    destination = Path(destination)
    if destination.exists():
        raise CorpusError(f"Destination already exists: {destination}")
    resolved_font = _resolve_font(font_path)
    destination.mkdir(parents=True, exist_ok=False)
    preview_dir = destination / "previews"
    preview_dir.mkdir()

    case_01 = destination / "case_01.txt"
    _write_text(case_01, """
海岚实验室 星桥项目校园网络维护报告
版本：v2.1
时间：2026年8月

本次维护针对校园网络间歇中断问题展开。巡检确认图书馆与东教学楼的接入交换机出现端口故障和异常重启，维护组已更换失效交换机，并逐项复核上联链路、供电和网络连通性。

更换完成后，图书馆阅览区与东教学楼各楼层的终端恢复稳定接入。后续将持续观察链路告警与设备温度，避免同类故障重复发生。
""")
    case_02 = destination / "case_02.txt"
    _write_text(case_02, """
山岚社区雨水花园维护指引

定期清理进水口堆积的泥沙、落叶和杂物，确保雨水可以顺畅进入种植区。清理时保留原有排水坡度，不堵塞溢流口，也不要压实表层土壤。

每次强降雨后检查进水口、溢流路径和低洼处积水情况。如发现水流受阻，应先移除沉积物，再确认排水恢复正常，并观察植物根部是否长期浸水。
""")
    case_03 = destination / "case_03.txt"
    _write_text(case_03, """
North Pier Archive Digitisation Migration Assessment
Version v3.2

The migration review compares the archive's current OCR pipeline with a proposed preservation workflow for two materially different collections: invoices and engineering drawings. Invoice pages contain predictable columns, dates, supplier references, and totals. Their OCR accuracy can be measured with field-level sampling, and corrected text supports discovery as long as the original page image remains authoritative.

Engineering drawings present a different problem. Rotated annotations, revision clouds, faint pencil marks, title blocks, and scale-dependent symbols produce misleading OCR even when the page-level confidence score appears acceptable. For these records, the assessment recommends preserving calibrated master images and using OCR only as a supplemental index rather than as a substitute for the drawing.

Retention rules must therefore remain collection-specific. Invoice packages follow the approved finance retention schedule and should preserve links between each image, extracted field set, and audit record. Engineering drawings remain under the project and asset-retention rules, including superseded revisions when they document design decisions. A single deletion rule would either retain invoices too long or remove drawings before their operational value ends.

The proposed migration separates capture quality checks, OCR acceptance thresholds, and retention metadata. It also requires exception reports for unreadable invoice fields and drawing sheets whose text layer cannot be trusted. This approach improves search while keeping preservation masters and governance decisions explicit.
""")

    case_04 = destination / "case_04.png"
    _make_fire_diagram(case_04, resolved_font)
    case_05 = destination / "case_05.pdf"
    preview_05 = _make_text_pdf(case_05, preview_dir)
    case_06 = destination / "case_06.pdf"
    preview_06 = _make_image_pdf(case_06, preview_dir, resolved_font)
    case_07 = destination / "case_07.mp4"
    preview_07 = _make_video(case_07, preview_dir, resolved_font)
    case_08 = destination / "case_08.png"
    Image.new("RGB", (800, 600), "white").save(case_08, "PNG")
    _validate_written_media(
        case_04, case_05, preview_05, case_06, preview_06, preview_07, case_08
    )

    cases = [
        _case("case_01", "text", case_01, destination,
              ["Chinese campus network maintenance report", "fictional 海岚实验室",
               "project 星桥", "version v2.1", "2026-08 month precision",
               "failed switches replaced in 图书馆 and 东教学楼"],
              ["specific day in August 2026", "unlisted locations"]),
        _case("case_02", "text", case_02, destination,
              ["山岚社区 rain-garden maintenance", "clear sediment at inlets",
               "preserve drainage", "inspect after heavy rain"],
              ["date", "author", "version", "legal company name"]),
        _case("case_03", "text", case_03, destination,
              ["North Pier archive digitisation migration assessment",
               "OCR and retention differ for invoices and engineering drawings",
               "version v3.2", "concise specific theme"],
              ["date", "generic report-only label", "verbatim full-document copy"]),
        _case("case_04", "image", case_04, destination,
              ["北区仓库 fire evacuation route", "two exits", "assembly point"],
              ["date", "version"],),
        _case("case_05", "text_pdf", case_05, destination,
              ["Cedar Research Library scanner evaluation", "bound-book scanning",
               "colour calibration", "OCR errors", "two distinct pages"],
              ["date", "version"], preview_05),
        _case("case_06", "image_pdf", case_06, destination,
              ["青禾咖啡馆 coffee-machine maintenance", "2026-08 month precision",
               "equipment CM-20", "boiler descaling", "seal replacement", "version v1.1"],
              ["searchable or hidden PDF text", "specific day in August 2026"], preview_06),
        _case("case_07", "video", case_07, destination,
              ["plant propagation", "ordered stages 剪枝, 水培生根, 移栽",
               "6 seconds", "8 fps", "640x360"],
              ["complete video supplied directly as future model input"], preview_07),
        _case("case_08", "image", case_08, destination,
              ["insufficient content", "uniform blank white image"],
              ["topic", "date", "organisation"]),
    ]
    contact_sheet = _make_contact_sheet(destination, cases, resolved_font)
    _validate_png(contact_sheet, (1200, 620))
    total_bytes = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    if total_bytes >= MAX_CORPUS_BYTES:
        raise CorpusError(f"Corpus exceeds the 32 MiB limit: {total_bytes} bytes")
    manifest = {
        "schema_version": 1,
        "corpus_id": "local-semantic-corpus-v1",
        "actual_inference_run": False,
        "human_model_quality_reviewed": False,
        "cases": cases,
        "contact_sheet": _relative(destination, contact_sheet),
        "generated_bytes_before_manifest": total_bytes,
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if total_bytes + len(manifest_text.encode("utf-8")) >= MAX_CORPUS_BYTES:
        raise CorpusError("Corpus including manifest exceeds the 32 MiB limit")
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--font-path", type=Path)
    args = parser.parse_args(argv)
    try:
        prepare_corpus(args.destination, font_path=args.font_path)
    except CorpusError as error:
        parser.exit(1, f"corpus preparation failed: {error}\n")
    print(args.destination / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
