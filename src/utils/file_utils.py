"""File path utilities: sanitization, conflict detection, normalization."""

import re
import os
from pathlib import Path
from .constants import ILLEGAL_CHARS


def sanitize_filename(name: str) -> str:
    """Remove or replace characters illegal in Windows filenames.

    Args:
        name: The raw filename (with or without extension).

    Returns:
        A sanitized filename safe for Windows.
    """
    # Replace illegal characters
    for ch in ILLEGAL_CHARS:
        name = name.replace(ch, "_")

    # Remove control characters
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)

    # Strip leading/trailing spaces and dots
    name = name.strip('. ')

    # Limit length (Windows MAX_PATH is 260, leave room for path)
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        stem = stem[:200 - len(ext) - 1]
        name = stem + ext

    # Ensure not empty
    if not name or (os.path.splitext(name)[0] == '' and len(name) <= len(os.path.splitext(name)[1])):
        name = f"unnamed_file{name}"

    return name


def resolve_conflict(target_dir: Path, desired_name: str) -> str:
    """Resolve filename conflicts by appending a counter.

    Args:
        target_dir: The directory where the file will be created.
        desired_name: The desired filename (with extension).

    Returns:
        A conflict-free filename.
    """
    base, ext = os.path.splitext(desired_name)
    candidate = desired_name

    counter = 1
    while (target_dir / candidate).exists():
        candidate = f"{base}_{counter}{ext}"
        counter += 1

    return candidate


def normalize_path(path: str | Path) -> Path:
    """Convert a path string to an absolute Path with normalized separators."""
    return Path(path).resolve()


def is_safe_path(path: Path, base_dir: Path) -> bool:
    """Check that a path is within a given base directory (prevent path traversal)."""
    try:
        path.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False
