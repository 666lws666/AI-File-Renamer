"""Content extraction engine — dispatches to type-specific extractors.

Supports: PDF, DOCX, PPTX, XLSX, TXT, MD, HTML, CSV, images (metadata only).
Library loads and individual page extraction are not interruptible; cancellation
checkpoints bound this module's iteration, not every internal parser instruction.
"""

import codecs
from pathlib import Path
from zipfile import ZipFile
from loguru import logger

from ..models.file_item import FileItem, FileStatus

_MAX_TEXT_CHARS = 1_000_000
_READ_CHUNK_BYTES = 4096
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_MAX_OOXML_MEMBERS = 2048
_MAX_OOXML_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_OOXML_EXPANDED_BYTES = 64 * 1024 * 1024
_MAX_SECTIONS = 2000
_MAX_PDF_PAGES = 100
_MAX_EXPLICIT_PDF_PAGES = 200
_MAX_SLIDES = 100
_MAX_SHEETS = 5
_MAX_ROWS = 200
_MAX_COLUMNS = 100


class _ExtractionError(Exception):
    """Fixed path-free application error codes only."""


def _checkpoint(token) -> None:
    if token is not None and token():
        raise _ExtractionError("extraction_cancelled")


class _TextBudget:
    """Accumulate only a bounded prefix plus one lookahead character."""

    def __init__(self, limit: int):
        self.limit = limit
        self.parts: list[str] = []
        self.length = 0

    @property
    def full(self) -> bool:
        return self.length > self.limit

    def add(self, text: str, separator: str = "\n") -> None:
        if not text or self.full:
            return
        if self.length:
            prefix = separator[:self.limit + 1 - self.length]
            self.parts.append(prefix)
            self.length += len(prefix)
        part = text[:self.limit + 1 - self.length]
        self.parts.append(part)
        self.length += len(part)

    def finish(self, *, processed: int, total: int | None = None,
               section_limited: bool = False) -> tuple[str, dict]:
        reason = "character_limit" if self.full else "section_limit" if section_limited else "complete"
        meta = {"text_truncated": self.full or section_limited,
                "coverage_reason": reason, "sections_processed": processed}
        if total is not None:
            meta["sections_total"] = total
        return "".join(self.parts)[:self.limit], meta


def _preflight_document(path: Path, token, *, ooxml: bool = False) -> None:
    """Finite parser input budgets, not interruptibility of library internals."""
    _checkpoint(token)
    if path.stat().st_size > _MAX_DOCUMENT_BYTES:
        raise _ExtractionError("document_limit")
    if ooxml:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > _MAX_OOXML_MEMBERS:
                raise _ExtractionError("document_limit")
            expanded = 0
            for member in members:
                _checkpoint(token)
                expanded += member.file_size
                if (member.file_size > _MAX_OOXML_MEMBER_BYTES
                        or expanded > _MAX_OOXML_EXPANDED_BYTES):
                    raise _ExtractionError("document_limit")
    _checkpoint(token)


# ── Public API ──────────────────────────────────────────────────────────────

def extract(
    file_item: FileItem,
    max_chars: int = 4000,
    *,
    max_pdf_pages: int | None = None,
    cancellation_token=None,
    redacted_diagnostics: bool = False,
) -> None:
    """Extract text content and metadata from a file.

    Updates file_item in place with extracted data and status.

    Coverage is path-free: text_truncated means omitted text or unexamined
    sections, distinguished by coverage_reason (character_limit/section_limit/
    complete). sections_processed counts visited pages/paragraphs/slides/rows;
    sections_total is only included when known. line_count counts newlines in
    the returned text prefix, not necessarily the complete source file.

    Args:
        file_item: The FileItem to process.
        max_chars: Maximum characters to extract (for AI API limits).
        redacted_diagnostics: Emit only fixed error codes, never paths/content.
    """
    path = file_item.original_path
    file_item.status = FileStatus.EXTRACTING
    try:
        _checkpoint(cancellation_token)
        if (not isinstance(max_chars, int) or isinstance(max_chars, bool)
                or not 0 <= max_chars <= _MAX_TEXT_CHARS
                or (max_pdf_pages is not None and (
                    not isinstance(max_pdf_pages, int) or isinstance(max_pdf_pages, bool)
                    or max_pdf_pages < 0))):
            raise _ExtractionError("invalid_extraction_limit")
        if not path.exists():
            raise _ExtractionError("file_not_found")
        ext = file_item.original_ext
        kwargs = {"max_chars": max_chars, "cancellation_token": cancellation_token}
        if ext == ".pdf":
            text, meta = _extract_pdf(path, max_pages=max_pdf_pages, **kwargs)
        elif ext == ".docx":
            text, meta = _extract_docx(path, **kwargs)
        elif ext == ".pptx":
            text, meta = _extract_pptx(path, **kwargs)
        elif ext in (".xlsx", ".xls"):
            text, meta = _extract_xlsx(path, **kwargs)
        elif ext in (".txt", ".md", ".csv", ".html", ".htm", ".rtf"):
            text, meta = _extract_text(path, **kwargs)
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".avif"):
            text, meta = _extract_image(path, **kwargs)
        elif ext in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv",
                     ".m4v", ".ts", ".mts", ".m2ts", ".3gp", ".3g2", ".mxf",
                     ".mpg", ".mpeg", ".ogv"):
            text, meta = _extract_video(path, **kwargs)
        else:
            raise _ExtractionError("unsupported_file_type")
        _checkpoint(cancellation_token)
        file_item.extracted_text = text
        file_item.metadata = meta
        file_item.error_message = ""
        file_item.status = FileStatus.EXTRACTED
        if not redacted_diagnostics:
            logger.debug("提取: {} — {} chars", path.name, len(text))
    except Exception as exc:
        code = str(exc) if isinstance(exc, _ExtractionError) else "extraction_failed"
        if redacted_diagnostics:
            logger.error("{}", code)
        else:
            logger.error("提取失败 {}: {}", path.name, exc)
        file_item.status = FileStatus.FAILED
        file_item.error_message = code if redacted_diagnostics or isinstance(exc, _ExtractionError) else str(exc)


# ── PDF ─────────────────────────────────────────────────────────────────────

def _extract_pdf(
    path: Path,
    *,
    max_chars: int = 4000,
    max_pages: int | None = None,
    cancellation_token=None,
) -> tuple[str, dict]:
    """Extract text and metadata from PDF files."""
    from PyPDF2 import PdfReader

    _preflight_document(path, cancellation_token)
    budget = _TextBudget(max_chars)
    with open(path, "rb") as source:
        _checkpoint(cancellation_token)
        reader = PdfReader(source)
        _checkpoint(cancellation_token)
        metadata = reader.metadata or {}
        total = len(reader.pages)
        limit = min(total, _MAX_PDF_PAGES if max_pages is None else
                    min(max_pages, _MAX_EXPLICIT_PDF_PAGES))
        processed = 0
        text_pages = []
        for index in range(limit):
            _checkpoint(cancellation_token)
            value = reader.pages[index].extract_text()
            processed += 1
            _checkpoint(cancellation_token)
            value = value or ""
            # Count only body characters actually retained in the returned
            # prefix, not visited blank/scan pages or lookahead-only text.
            remaining = max_chars - budget.length - (1 if budget.length else 0)
            if value[:max(0, remaining)].strip():
                text_pages.append(index)
            budget.add(value)
            if budget.full:
                break
        text, coverage = budget.finish(processed=processed, total=total, section_limited=processed < total)
        meta = {"pages": total, "pages_processed": processed,
                "text_page_indices": tuple(text_pages),
                **{key: str(metadata.get("/" + key.title(), ""))
                   for key in ("author", "title", "subject", "creator", "producer")}, **coverage}
    return text, meta


# ── DOCX ────────────────────────────────────────────────────────────────────

def _extract_docx(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Extract text from Word documents."""
    from docx import Document

    _preflight_document(path, cancellation_token, ooxml=True)
    budget = _TextBudget(max_chars)
    with open(path, "rb") as source:
        doc = Document(source)
        _checkpoint(cancellation_token)
        paragraphs = doc.paragraphs
        total = len(paragraphs)
        processed = 0
        for para in paragraphs[:_MAX_SECTIONS]:
            _checkpoint(cancellation_token)
            value = para.text
            processed += 1
            _checkpoint(cancellation_token)
            if value.strip():
                budget.add(value)
            if budget.full:
                break
        text, coverage = budget.finish(processed=processed, total=total, section_limited=processed < total)
        props = doc.core_properties
        meta = {name: str(getattr(props, name) or "")
                for name in ("author", "title", "subject", "category", "created", "modified")}
        meta.update(paragraphs=total, **coverage)
    return text, meta


# ── PPTX ────────────────────────────────────────────────────────────────────

def _extract_pptx(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Extract text from PowerPoint presentations."""
    from pptx import Presentation

    _preflight_document(path, cancellation_token, ooxml=True)
    budget = _TextBudget(max_chars)
    with open(path, "rb") as source:
        prs = Presentation(source)
        _checkpoint(cancellation_token)
        total = len(prs.slides)
        processed = units = 0
        limited = False
        for index in range(min(total, _MAX_SLIDES)):
            _checkpoint(cancellation_token)
            slide = prs.slides[index]
            processed += 1
            first = True
            for shape in slide.shapes:
                _checkpoint(cancellation_token)
                units += 1
                if units > _MAX_SECTIONS:
                    limited = True
                    break
                if not shape.has_text_frame:
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    _checkpoint(cancellation_token)
                    units += 1
                    if units > _MAX_SECTIONS:
                        limited = True
                        break
                    value = paragraph.text
                    _checkpoint(cancellation_token)
                    if value.strip():
                        budget.add(value, "\n---\n" if first else "\n")
                        first = False
                    if budget.full:
                        break
                if budget.full or limited:
                    break
            if budget.full or limited:
                break
        text, coverage = budget.finish(processed=processed, total=total,
                                        section_limited=limited or processed < total)
    return text, {"slides": total, "slides_processed": processed, **coverage}


# ── XLSX ────────────────────────────────────────────────────────────────────

def _extract_xlsx(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Extract text from Excel spreadsheets."""
    _preflight_document(path, cancellation_token, ooxml=True)
    with open(path, "rb") as source:
        _checkpoint(cancellation_token)
        return _read_xlsx(source, max_chars=max_chars, cancellation_token=cancellation_token)


def _read_xlsx(source, *, max_chars, cancellation_token) -> tuple[str, dict]:
    import openpyxl

    budget = _TextBudget(max_chars)
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        _checkpoint(cancellation_token)
        names = wb.sheetnames
        rows_processed = sheets_processed = 0
        limited = len(names) > _MAX_SHEETS
        for name in names[:_MAX_SHEETS]:
            _checkpoint(cancellation_token)
            ws = wb[name]
            sheets_processed += 1
            budget.add(f"[Sheet: {name}]")
            if budget.full:
                break
            known_rows, known_columns = ws.max_row, ws.max_column
            limited |= ((known_rows is not None and known_rows > _MAX_ROWS)
                        or (known_columns is not None and known_columns > _MAX_COLUMNS))
            rows = ws.iter_rows(max_row=_MAX_ROWS, max_col=_MAX_COLUMNS, values_only=True)
            nonempty = visited = 0
            try:
                for row in rows:
                    _checkpoint(cancellation_token)
                    visited += 1
                    rows_processed += 1
                    has_value = False
                    for cell in row:
                        _checkpoint(cancellation_token)
                        if cell is not None:
                            value = str(cell)
                            if value.strip():
                                budget.add(value, " | " if has_value else "\n")
                                has_value = True
                        if budget.full:
                            break
                    nonempty += has_value
                    _checkpoint(cancellation_token)
                    if budget.full or nonempty >= 100:
                        limited |= known_rows is None or visited < known_rows
                        break
                if known_rows is None and visited == _MAX_ROWS:
                    limited = True
            finally:
                close = getattr(rows, "close", None)
                if close is not None:
                    close()
            if budget.full:
                break
        text, coverage = budget.finish(processed=rows_processed, section_limited=limited)
        return text, {"sheets": names, "sheet_count": len(names),
                      "sheets_processed": sheets_processed, "rows_processed": rows_processed, **coverage}
    finally:
        wb.close()


# ── Plain Text / Markdown / HTML ────────────────────────────────────────────

def _extract_text(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Extract text from plain text files (TXT, MD, CSV, HTML, RTF)."""
    remaining = 4 * (max_chars + 1) + 4  # Unicode scalars + BOM + lookahead.
    chunks = []
    eof = False
    _checkpoint(cancellation_token)
    with open(path, "rb") as source:
        while remaining:
            _checkpoint(cancellation_token)
            chunk = source.read(min(remaining, _READ_CHUNK_BYTES))
            _checkpoint(cancellation_token)
            if not chunk:
                eof = True
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    data = b"".join(chunks)
    encodings = (["utf-16"] if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
                 else ["utf-8-sig", "gbk", "gb2312", "latin-1"])
    for encoding in encodings:
        _checkpoint(cancellation_token)
        try:
            text = codecs.getincrementaldecoder(encoding)(errors="strict").decode(data, final=eof)
            break
        except UnicodeDecodeError:
            if encoding == encodings[-1]:
                raise
    budget = _TextBudget(max_chars)
    budget.add(text.replace("\r\n", "\n").replace("\r", "\n"))
    sections = 1 if data else 0
    result, coverage = budget.finish(processed=sections, total=sections if eof else None,
                                     section_limited=not eof)
    return result, {"encoding": "utf-8" if encoding == "utf-8-sig" else encoding,
                    "line_count": result.count("\n"), "bytes_read": len(data), **coverage}


# ── Image ───────────────────────────────────────────────────────────────────

def _extract_image(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Legacy metadata, not OCR; local routers discard text for both naming modes."""
    from PIL import Image
    from PIL.ExifTags import TAGS

    _checkpoint(cancellation_token)
    img = Image.open(str(path))
    try:
        _checkpoint(cancellation_token)
        exif_data = {}
        try:
            exif = img._getexif()
        except (AttributeError, OSError, ValueError):
            exif = None
        _checkpoint(cancellation_token)
        if exif:
            for tag_id, value in exif.items():
                _checkpoint(cancellation_token)
                if isinstance(value, bytes):
                    value = value[:800].decode("utf-8", errors="replace")[:200]
                exif_data[str(TAGS.get(tag_id, tag_id))] = str(value)
        parts = []
        if "DateTimeOriginal" in exif_data:
            parts.append(f"拍摄日期: {exif_data['DateTimeOriginal']}")
        if "Make" in exif_data:
            parts.append(f"相机: {exif_data['Make']} {exif_data.get('Model', '')}")
        if "ImageDescription" in exif_data:
            parts.append(f"描述: {exif_data['ImageDescription']}")
        description = "\n".join(parts) if parts else f"图片文件: {path.name}\n尺寸: {img.size[0]}x{img.size[1]}"
        budget = _TextBudget(max_chars)
        budget.add(description)
        text, coverage = budget.finish(processed=1, total=1)
        return text, {"width": img.size[0], "height": img.size[1],
                      "format": img.format or path.suffix.upper().lstrip("."), "mode": img.mode,
                      **{f"exif_{k}": v for k, v in list(exif_data.items())[:20]},
                      "content_source": "metadata_only", **coverage}
    finally:
        img.close()


# ── Video ───────────────────────────────────────────────────────────────────

def _extract_video(path: Path, *, max_chars=4000, cancellation_token=None) -> tuple[str, dict]:
    """Legacy metadata, not frames; local routers discard text for both modes."""
    _checkpoint(cancellation_token)
    stat = path.stat()
    budget = _TextBudget(max_chars)
    budget.add(f"视频文件: {path.name}\n大小: {stat.st_size / (1024*1024):.1f} MB\n修改时间: {stat.st_mtime}")
    text, coverage = budget.finish(processed=1, total=1)
    return text, {"size_mb": round(stat.st_size / (1024 * 1024), 1),
                  "format": path.suffix.upper().lstrip("."),
                  "content_source": "metadata_only", **coverage}
