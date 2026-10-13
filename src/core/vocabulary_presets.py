"""M4 Vocabulary Presets — versioned General preset pack with fail-closed loading."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import NAMESPACE_URL, uuid5

from .vocabulary import (
    VocabularyCategory,
    VocabularyEntry,
    VocabularySource,
)


# Current version of the General presets. Increment when presets change to
# invalidate downstream caches.
GENERAL_PRESETS_VERSION = 2

# Path to the General presets JSON data file, relative to this module.
_PRESETS_DIR = Path(__file__).resolve().parent / "data"
_GENERAL_PRESETS_PATH = _PRESETS_DIR / "vocabulary_presets_general.json"


# ── Errors ───────────────────────────────────────────────────────────────────

class PresetIntegrityError(Exception):
    """Raised when preset data fails integrity checks."""
    pass


# ── PresetPack ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PresetPack:
    """A versioned bundle of vocabulary preset entries."""
    version: int
    entries: list[VocabularyEntry] = field(default_factory=list)


# ── Loader ───────────────────────────────────────────────────────────────────

def load_preset_pack(file_path: Path) -> PresetPack:
    """Load a versioned vocabulary preset pack from JSON with full validation.

    Fails closed on:
      - Corrupted JSON
      - Missing or non-integer version
      - Duplicate concept_id/locale pairs
      - Illegal category values
      - Non-system source in presets

    Args:
        file_path: Path to the preset JSON file.

    Returns:
        PresetPack with validated entries.

    Raises:
        PresetIntegrityError: If any integrity check fails.
    """
    # Read and parse JSON
    try:
        raw_text = file_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise PresetIntegrityError(
            f"Corrupted preset file {file_path}: {e}"
        ) from e

    if not isinstance(data, dict):
        raise PresetIntegrityError(
            f"Preset file must contain a JSON object, got {type(data).__name__}"
        )

    # Validate version
    version = data.get("version")
    if version is None:
        raise PresetIntegrityError("Preset file missing 'version' field")
    if not isinstance(version, int):
        raise PresetIntegrityError(
            f"Preset version must be an integer, got {type(version).__name__}"
        )
    if version < 1:
        raise PresetIntegrityError(
            f"Preset version must be >= 1, got {version}"
        )

    # Validate entries
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise PresetIntegrityError(
            f"Preset 'entries' must be a JSON array, got {type(raw_entries).__name__}"
        )

    entries: list[VocabularyEntry] = []
    seen_keys: set[tuple[str, str]] = set()

    for i, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise PresetIntegrityError(
                f"Preset entry {i} must be a JSON object, got {type(raw).__name__}"
            )

        # Validate category
        category_str = raw.get("category", "")
        try:
            category = VocabularyCategory(category_str)
        except ValueError:
            raise PresetIntegrityError(
                f"Preset entry {i}: illegal category {category_str!r}"
            )

        # Validate source — presets must be system source
        source_str = raw.get("source", "system")
        try:
            source = VocabularySource(source_str)
        except ValueError:
            raise PresetIntegrityError(
                f"Preset entry {i}: illegal source {source_str!r}"
            )
        if source != VocabularySource.SYSTEM:
            raise PresetIntegrityError(
                f"Preset entry {i}: source must be 'system', got {source_str!r}"
            )

        concept_id = raw.get("concept_id", "")
        display_name = raw.get("display_name", "")
        locale = raw.get("locale", "")

        if not concept_id or not concept_id.strip():
            raise PresetIntegrityError(
                f"Preset entry {i}: concept_id must not be empty"
            )
        if not display_name or not display_name.strip():
            raise PresetIntegrityError(
                f"Preset entry {i}: display_name must not be empty"
            )
        if not locale or not locale.strip():
            raise PresetIntegrityError(
                f"Preset entry {i}: locale must not be empty"
            )

        # Check for duplicate concept_id + locale
        key = (concept_id, locale)
        if key in seen_keys:
            raise PresetIntegrityError(
                f"Preset entry {i}: duplicate concept_id={concept_id!r}, locale={locale!r}"
            )
        seen_keys.add(key)

        stable_id = str(uuid5(
            NAMESPACE_URL,
            f"https://xuxia.local/vocabulary/{category.value}/{concept_id}/{locale}",
        ))
        entry = VocabularyEntry(
            id=stable_id,
            category=category,
            concept_id=concept_id,
            display_name=display_name,
            locale=locale,
            source=source,
        )
        entries.append(entry)

    return PresetPack(version=version, entries=entries)


# ── Convenience accessor with lazy caching ───────────────────────────────────

_general_presets_cache: Optional[PresetPack] = None


def get_general_presets() -> PresetPack:
    """Get the General vocabulary preset pack (lazy-loaded and cached)."""
    global _general_presets_cache
    if _general_presets_cache is None:
        _general_presets_cache = load_preset_pack(_GENERAL_PRESETS_PATH)
    return _general_presets_cache
