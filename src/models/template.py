"""NamingTemplate — defines the structure of output filenames."""

from uuid import uuid4
from pydantic import BaseModel, Field


class TemplateField(BaseModel):
    """A single field within a naming template."""
    name: str                        # e.g. "date", "title", "tags"
    label: str = ""                  # Display name for UI
    required: bool = True
    default_value: str = ""


# Built-in field definitions that the AI can populate
BUILTIN_FIELDS: dict[str, str] = {
    "date": "日期",
    "title": "标题",
    "type": "类型",
    "tags": "标签",
    "language": "语言",
}

# System variables (not from AI, but from file system)
SYSTEM_VARIABLES = {"ext", "original_name", "counter", "file_type"}


class NamingTemplate(BaseModel):
    """Defines how AI fields are assembled into a filename."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "默认模板"
    pattern: str = "{date}_{title}.{ext}"  # e.g. "{date}_{title}.{ext}"
    separator: str = "_"                    # Default separator between fields
    date_format: str = "%Y-%m-%d"           # strftime format for dates
    fields: list[TemplateField] = Field(default_factory=lambda: [
        TemplateField(name="date", label="日期"),
        TemplateField(name="title", label="标题"),
    ])

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]
