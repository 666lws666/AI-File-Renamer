"""MIME type mappings, supported file extensions, and default prompts."""

# File extension → MIME type mapping
EXT_TO_MIME: dict[str, str] = {
    # Documents
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rtf": "application/rtf",
    ".html": "text/html",
    ".htm": "text/html",
    ".epub": "application/epub+zip",
    # Images
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    # Videos (metadata-only extraction)
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
}

# Supported extensions grouped by category
DOCUMENT_EXTENSIONS: set[str] = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".csv", ".txt", ".md", ".rtf", ".html", ".htm", ".epub",
}

IMAGE_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".avif",
}

VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv",
}

SUPPORTED_EXTENSIONS: set[str] = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# File types that support text extraction
TEXT_EXTRACTABLE_EXTENSIONS: set[str] = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".rtf", ".html", ".htm", ".csv",
}

# Default AI system prompt
DEFAULT_SYSTEM_PROMPT = """You are a professional file-naming assistant. Analyze the file content and metadata provided, and extract structured information to generate a clear, descriptive, searchable filename.

Return ONLY a valid JSON object with these fields:
- "title": A concise descriptive title for this file (3-8 words, in the file's original language)
- "date": The most relevant date in YYYY-MM-DD format (from content or metadata. If no date found, use "unknown")
- "type": The document type/category (e.g., "contract", "report", "invoice", "note", "manual", "letter", "resume", "presentation")
- "tags": 1-3 keyword tags that best categorize this file
- "language": The primary language of the content (e.g., "zh", "en", "ja")

Example response:
{"title": "2025年度销售报告", "date": "2025-03-15", "type": "report", "tags": ["销售", "年度报告", "2025"], "language": "zh"}"""

# Default naming template
DEFAULT_TEMPLATE = "{date}_{title}_{tags}.{ext}"

# Maximum characters to send to AI API
DEFAULT_MAX_CONTENT_CHARS = 4000

# Maximum file size for scanning (MB)
DEFAULT_MAX_FILE_SIZE_MB = 50

# Illegal characters in Windows filenames
ILLEGAL_CHARS = r'<>:"/\|?*'
