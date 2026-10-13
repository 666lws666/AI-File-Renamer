"""M4 Template domain model — immutable, validated Dublin Core templates."""

import re
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


# ── Enums ────────────────────────────────────────────────────────────────────

class DateFormat(str, Enum):
    YYYYMMDD = "YYYYMMDD"
    YYYYMM = "YYYYMM"
    YYYY_MM_DD = "YYYY-MM-DD"
    YYYY_MM = "YYYY-MM"


class Separator(str, Enum):
    UNDERSCORE = "_"
    HYPHEN = "-"


class OrgMode(str, Enum):
    FLAT = "flat"
    SUBJECT_TREE = "subject_tree"
    TYPE_TREE = "type_tree"
    PROJECT_TREE = "project_tree"


class OutputLanguage(str, Enum):
    ZH = "zh"
    ZH_HK = "zh-HK"
    EN = "en"
    JA = "ja"
    ES = "es"


def naming_locale(language: str | OutputLanguage) -> str:
    """Validate a filename language and map it to the Provider locale."""
    return {OutputLanguage.ZH: "zh-CN", OutputLanguage.ZH_HK: "zh-HK",
            OutputLanguage.EN: "en-US", OutputLanguage.JA: "ja-JP",
            OutputLanguage.ES: "es-ES"}[OutputLanguage(language)]


# ── TemplateField ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TemplateField:
    """A single Dublin Core field within a naming template. Immutable."""

    dc_name: str
    display_name: str
    order: int = 1
    enabled: bool = True
    id: str | None = None

    def __post_init__(self):
        if not self.dc_name or not self.dc_name.strip():
            raise ValueError("TemplateField.dc_name must not be empty")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("TemplateField.display_name must not be empty")
        if self.order < 1:
            raise ValueError("TemplateField.order must be >= 1")
        if self.id is None:
            object.__setattr__(self, "id", str(uuid4()))


# ── Standard 10 Dublin Core fields ───────────────────────────────────────────

STANDARD_FIELDS: tuple[TemplateField, ...] = (
    TemplateField(dc_name="dcDate", display_name="Date", order=1),
    TemplateField(dc_name="dcTitle", display_name="Title", order=2),
    TemplateField(dc_name="dcSubject", display_name="Subject", order=3),
    TemplateField(dc_name="dcType", display_name="Type", order=4),
    TemplateField(dc_name="dcCreator", display_name="Creator", order=5),
    TemplateField(dc_name="dcIdentifier", display_name="Identifier", order=6),
    TemplateField(dc_name="extOrganization", display_name="Organization", order=7),
    TemplateField(dc_name="extProject", display_name="Project", order=8),
    TemplateField(dc_name="extStatus", display_name="Status", order=9),
    TemplateField(dc_name="extVersion", display_name="Version", order=10),
)

_STANDARD_FIELD_NAMES = {f.dc_name for f in STANDARD_FIELDS}

# Regex for extracting placeholders from pattern
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ── Template ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Template:
    """Immutable naming template with Dublin Core field configuration."""

    name: str
    pattern: str = "{dcDate}_{dcTitle}"
    date_format: DateFormat = DateFormat.YYYY_MM_DD
    separator: Separator = Separator.UNDERSCORE
    org_mode: OrgMode = OrgMode.FLAT
    output_language: OutputLanguage = OutputLanguage.ZH
    fields: tuple[TemplateField, ...] = field(default_factory=lambda: STANDARD_FIELDS)
    version: int = 1
    id: str | None = None

    def __post_init__(self):
        # ── id ──
        if self.id is None or (isinstance(self.id, str) and not self.id.strip()):
            # Empty, whitespace-only, or None explicitly passed → reject
            if self.id is not None:
                raise ValueError("Template.id must not be empty")
            object.__setattr__(self, "id", str(uuid4()))
        # At this point self.id is guaranteed non-empty

        # ── name ──
        if not self.name or not self.name.strip():
            raise ValueError("Template.name must not be empty")

        # ── date_format ──
        if not isinstance(self.date_format, DateFormat):
            raise ValueError(
                f"Invalid date_format: {self.date_format!r}. "
                f"Must be one of: {[e.value for e in DateFormat]}"
            )

        # ── separator ──
        if not isinstance(self.separator, Separator):
            raise ValueError(
                f"Invalid separator: {self.separator!r}. "
                f"Must be one of: {[e.value for e in Separator]}"
            )

        # ── org_mode ──
        if not isinstance(self.org_mode, OrgMode):
            raise ValueError(
                f"Invalid org_mode: {self.org_mode!r}. "
                f"Must be one of: {[e.value for e in OrgMode]}"
            )

        # ── output_language ──
        if not isinstance(self.output_language, OutputLanguage):
            raise ValueError(
                f"Invalid output_language: {self.output_language!r}. "
                f"Must be one of: {[e.value for e in OutputLanguage]}"
            )

        # ── fields ──
        # Accept any iterable at the boundary, but retain an immutable defensive copy.
        object.__setattr__(self, "fields", tuple(self.fields))
        if not self.fields:
            raise ValueError("Template.fields must not be empty")

        # Check for duplicate dc_name
        seen_names: set[str] = set()
        for f in self.fields:
            if f.dc_name in seen_names:
                raise ValueError(
                    f"Duplicate field dc_name in template: {f.dc_name}"
                )
            seen_names.add(f.dc_name)

        # Check for duplicate order
        seen_orders: set[int] = set()
        for f in self.fields:
            if f.order in seen_orders:
                raise ValueError(
                    f"Duplicate field order in template: {f.order}"
                )
            seen_orders.add(f.order)

        # ── pattern validation ──
        placeholders = _PLACEHOLDER_RE.findall(self.pattern)
        if not placeholders:
            raise ValueError(
                f"Template pattern must contain at least one placeholder: {self.pattern!r}"
            )

        enabled_names = {f.dc_name for f in self.fields if f.enabled}

        for ph in placeholders:
            if ph not in _STANDARD_FIELD_NAMES:
                raise ValueError(
                    f"Pattern placeholder {{{ph}}} is not a recognized field name. "
                    f"Valid names: {sorted(_STANDARD_FIELD_NAMES)}"
                )
            if ph not in enabled_names:
                raise ValueError(
                    f"Pattern placeholder {{{ph}}} references a disabled field"
                )

        # ── version ──
        if self.version < 1:
            raise ValueError("Template.version must be >= 1")

    def with_incremented_version(self) -> "Template":
        """Return a new Template with version incremented by 1."""
        object.__setattr__(self, "version", self.version)  # ensure frozen allows this pattern
        # Since frozen, we use object.__setattr__ to create modified copy
        new_id = self.id  # keep same id
        # Build a new instance via __init__-bypass or manual construction
        return Template(
            id=new_id,
            name=self.name,
            pattern=self.pattern,
            date_format=self.date_format,
            separator=self.separator,
            org_mode=self.org_mode,
            output_language=self.output_language,
            fields=self.fields,
            version=self.version + 1,
        )
