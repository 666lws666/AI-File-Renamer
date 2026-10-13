"""M4 Unified Template Renderer — preview and formal rendering share one code path."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

from .template_model import Template, DateFormat, OrgMode
from .naming_fields import NamingFields


class RenderStatus(str, Enum):
    READY = "READY"
    NEEDS_REGENERATION = "NEEDS_REGENERATION"
    INVALID = "INVALID"


@dataclass(frozen=True)
class TemplateRenderResult:
    """Deterministic result of rendering a template against NamingFields."""

    rendered_name: str
    missing_fields: Tuple[str, ...] = ()
    status: RenderStatus = RenderStatus.READY
    errors: Tuple[str, ...] = ()

    @property
    def can_apply(self) -> bool:
        return self.status == RenderStatus.READY


# ── Date format validation ───────────────────────────────────────────────────

_DATE_FORMAT_PATTERNS = {
    DateFormat.YYYYMMDD: re.compile(r"^\d{8}$"),
    DateFormat.YYYYMM: re.compile(r"^\d{6}$"),
    DateFormat.YYYY_MM_DD: re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    DateFormat.YYYY_MM: re.compile(r"^\d{4}-\d{2}$"),
}

# Characters unsafe in path components (Windows and general)
_UNSAFE_PATH_RE = re.compile(r'[<>:"/\\|?*]')
_PATH_SEPARATOR_RE = re.compile(r"[/\\]+")

# Characters unsafe in filename stem
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"|?*]')


def _validate_date_format(value: str, date_format: DateFormat) -> bool:
    """Check if a date string matches the expected format."""
    pattern = _DATE_FORMAT_PATTERNS.get(date_format)
    if pattern is None:
        return True  # Unknown format, don't block
    return bool(pattern.match(value))


def _sanitize_path_component(value: str) -> str:
    """Make a value safe for use as a relative path component.

    Strips unsafe characters, replaces path separators, removes drive letters,
    and blocks path traversal.
    """
    if not value:
        return value
    # Remove drive letters (e.g., "C:" → "")
    value = re.sub(r"^[a-zA-Z]:", "", value)
    # Replace backslashes and forward slashes with safe_char
    value = value.replace("\\", "-").replace("/", "-")
    # Remove unsafe characters
    value = _UNSAFE_PATH_RE.sub("", value)
    # Remove leading/trailing dots and spaces (path traversal and Windows issues)
    value = value.strip(". ")
    # Collapse multiple dashes
    value = re.sub(r"-{2,}", "-", value)
    # Strip leading/trailing dashes
    value = value.strip("-")
    return value


def _sanitize_filename_stem(value: str) -> str:
    """Make a value safe for use in a filename stem."""
    if not value:
        return value
    value = _UNSAFE_FILENAME_RE.sub("", value)
    value = value.replace("/", "-").replace("\\", "-")
    value = value.strip(". ")
    return value


# ── Renderer ─────────────────────────────────────────────────────────────────

class TemplateRenderer:
    """Unified renderer: preview and formal execution use the exact same method."""

    @staticmethod
    def render(
        template: Template,
        fields: NamingFields,
        extension: str,
    ) -> TemplateRenderResult:
        """Render a template against NamingFields to produce a filename.

        Args:
            template: The Template to render.
            fields: NamingFields with Dublin Core values from AI or user.
            extension: Original file extension including dot, e.g. ".pdf".

        Returns:
            TemplateRenderResult with rendered_name, status, and can_apply.
        """
        errors: list[str] = []
        missing: list[str] = []

        # Ensure extension starts with dot or is empty
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        ext_lower = extension.lower()

        # Build field value lookup from NamingFields
        field_values: dict[str, str | None] = {
            "dcDate": fields.dcDate,
            "dcTitle": fields.dcTitle,
            "dcSubject": fields.dcSubject,
            "dcType": fields.dcType,
            "dcCreator": fields.dcCreator,
            "dcIdentifier": fields.dcIdentifier,
            "extOrganization": fields.extOrganization,
            "extProject": fields.extProject,
            "extStatus": fields.extStatus,
            "extVersion": fields.extVersion,
        }

        # Normalize pattern separator: replace alt-sep with configured sep
        pattern = template.pattern
        sep = template.separator.value
        alt_sep = "-" if sep == "_" else "_"
        pattern = pattern.replace(alt_sep, sep)

        # Extract placeholders from pattern and check which are enabled
        placeholders = re.findall(r"\{(\w+)\}", pattern)

        # Determine required fields (enabled fields that appear in pattern)
        enabled_names = {f.dc_name for f in template.fields if f.enabled}

        # Check for missing required fields
        for ph in placeholders:
            if ph not in enabled_names:
                continue  # Disabled fields are not required
            value = field_values.get(ph)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(ph)

        # Validate date format if dcDate is present
        dc_date = field_values.get("dcDate")
        if dc_date and dc_date.strip():
            if not _validate_date_format(dc_date, template.date_format):
                errors.append(
                    f"Date value {dc_date!r} does not match format {template.date_format.value}"
                )

        # If there are date format errors, result is INVALID
        if errors:
            # Still render a best-effort name for preview
            result_name = TemplateRenderer._build_name(
                pattern, field_values, template, ext_lower
            )
            return TemplateRenderResult(
                rendered_name=result_name,
                missing_fields=tuple(missing),
                status=RenderStatus.INVALID,
                errors=tuple(errors),
            )

        # If there are missing required fields, NEEDS_REGENERATION
        if missing:
            result_name = TemplateRenderer._build_name(
                pattern, field_values, template, ext_lower
            )
            error_msgs = [f"Missing required field: {m}" for m in missing]
            return TemplateRenderResult(
                rendered_name=result_name,
                missing_fields=tuple(missing),
                status=RenderStatus.NEEDS_REGENERATION,
                errors=tuple(error_msgs),
            )

        # All good → READY
        result_name = TemplateRenderer._build_name(
            pattern, field_values, template, ext_lower
        )
        return TemplateRenderResult(
            rendered_name=result_name,
            missing_fields=(),
            status=RenderStatus.READY,
            errors=(),
        )

    @staticmethod
    def _build_name(
        pattern: str,
        field_values: dict[str, str | None],
        template: Template,
        extension: str,
    ) -> str:
        """Build the final filename from pattern and field values.

        This is the single rendering path used by both preview and formal render.
        """
        result = pattern

        # Substitute placeholders
        for key, value in field_values.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                if value is None:
                    value_str = ""
                else:
                    value_str = str(value)
                # Sanitize for use in filename
                cleaned = _sanitize_filename_stem(value_str)
                # Replace spaces with separator for readability
                cleaned = cleaned.replace(" ", template.separator.value)
                result = result.replace(placeholder, cleaned)

        # Remove any remaining unresolved placeholders
        result = re.sub(r"\{[^}]+\}", "", result)

        # Collapse multiple consecutive separators
        sep = template.separator.value
        if sep:
            result = re.sub(rf"{re.escape(sep)}+", sep, result)
            result = result.strip(sep)

        # Apply organization mode prefix
        result = TemplateRenderer._apply_org_mode(result, field_values, template)

        # Append extension
        if extension:
            result = result + extension

        return result

    @staticmethod
    def _apply_org_mode(
        name: str,
        field_values: dict[str, str | None],
        template: Template,
    ) -> str:
        """Apply organization mode to prefix the filename with a safe relative path."""
        if template.org_mode == OrgMode.FLAT:
            return name

        # Map org mode to field name
        org_field_map = {
            OrgMode.SUBJECT_TREE: "dcSubject",
            OrgMode.TYPE_TREE: "dcType",
            OrgMode.PROJECT_TREE: "extProject",
        }
        field_name = org_field_map.get(template.org_mode)
        if field_name is None:
            return name

        raw_value = field_values.get(field_name)
        if raw_value is None or not str(raw_value).strip():
            # Use a default category name when the org field is missing
            default_categories = {
                OrgMode.SUBJECT_TREE: "uncategorized",
                OrgMode.TYPE_TREE: "other",
                OrgMode.PROJECT_TREE: "general",
            }
            category = default_categories.get(template.org_mode, "other")
        else:
            category = _sanitize_path_component(str(raw_value))
            if not category:
                category = "other"

        # Ensure no path traversal or absolute paths
        category = _sanitize_path_component(category)
        if not category:
            category = "other"

        return f"{category}/{name}"
