"""Template engine — parses templates and renders filenames from AI fields."""

import re
from datetime import datetime
from loguru import logger

from ..models.file_item import FileItem
from ..models.template import NamingTemplate
from ..utils.file_utils import sanitize_filename


class TemplateEngine:
    """Parses naming templates and renders final filenames."""

    @staticmethod
    def parse(template_str: str) -> list[str]:
        """Extract variable names from a template string.

        Example: "{date}_{title}_{tags}.{ext}" → ["date", "title", "tags", "ext"]
        """
        return re.findall(r'\{(\w+)\}', template_str)

    @staticmethod
    def render(template: NamingTemplate, ai_fields: dict, file_item: FileItem) -> str:
        """Render a filename from template + AI fields + file info.

        Args:
            template: NamingTemplate with pattern and settings.
            ai_fields: Dict from AI response (e.g., {"date": "2025-01-15", "title": "报告"}).
            file_item: FileItem for system variables like {ext}.

        Returns:
            Sanitized filename string (no path, just name + extension).
        """
        result = template.pattern

        # Build variable map: start with AI fields
        variables = dict(ai_fields)

        # Add system variables
        variables["ext"] = file_item.original_ext.lstrip(".")
        variables["original_name"] = file_item.original_path.stem
        variables["file_type"] = file_item.file_type
        variables["counter"] = ""  # Placeholder, resolved at rename time

        # If date is missing, use today
        if "date" not in variables or not variables["date"] or variables["date"] == "unknown":
            variables["date"] = datetime.now().strftime(template.date_format)

        # If tags field exists and is a list, join with separator
        for key, value in variables.items():
            if isinstance(value, list):
                variables[key] = template.separator.join(str(v) for v in value)
            elif value is None:
                variables[key] = ""

        # Substitute variables into pattern
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                # Clean values for use in filenames
                cleaned = str(value).replace(" ", "-").replace("/", "-").replace("\\", "-")
                result = result.replace(placeholder, cleaned)

        # Remove any remaining unresolved placeholders
        result = re.sub(r'\{[^}]+\}', '', result)

        # Clean up: collapse multiple separators
        sep = template.separator
        if sep:
            result = re.sub(rf'{re.escape(sep)}+', sep, result)
            result = result.strip(sep)

        result = sanitize_filename(result)

        logger.debug(f"渲染文件名: {template.pattern} → {result}")
        return result

    @staticmethod
    def render_from_pattern(pattern: str, ai_fields: dict, file_item: FileItem, separator: str = "_") -> str:
        """Render using a raw pattern string instead of a NamingTemplate object.

        Convenience method for simple cases.
        """
        from ..models.template import NamingTemplate
        temp = NamingTemplate(pattern=pattern, separator=separator)
        return TemplateEngine.render(temp, ai_fields, file_item)
