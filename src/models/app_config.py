"""AppConfig — persisted application settings."""

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Global application configuration persisted to JSON."""

    # AI Provider
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"

    # Prompt
    system_prompt: str = ""
    max_content_chars: int = 4000
    max_tokens: int = 4096

    # General
    language: str = "zh"
    theme: str = "light"
    max_file_size_mb: int = 50
    default_template_id: str = ""

    # Organization
    auto_organize: bool = False
    organization_root: str = ""
    organization_rule: str = "by_type"  # by_date, by_type, by_category, by_project

    class Config:
        # Allow extra fields for forward compatibility
        extra = "allow"
