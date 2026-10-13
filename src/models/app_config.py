"""AppConfig — persisted application settings."""

import re
from typing import Any

from pydantic import BaseModel, Field


_CREDENTIAL_FIELD_NAMES = {
    "apikey", "token", "accesstoken", "authtoken", "refreshtoken",
    "authorization", "credential", "credentials", "secret", "clientsecret",
    "password", "passphrase",
}


def _normalized_field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def sanitise_persisted_config(value: Any) -> Any:
    """Recursively remove credential-bearing fields from persisted metadata."""
    if isinstance(value, dict):
        return {
            str(key): sanitise_persisted_config(item)
            for key, item in value.items()
            if _normalized_field_name(key) not in _CREDENTIAL_FIELD_NAMES
        }
    if isinstance(value, (list, tuple)):
        return [sanitise_persisted_config(item) for item in value]
    return value


class AppConfig(BaseModel):
    """Global application configuration persisted to JSON."""

    # AI Provider
    provider: str = "deepseek"
    api_key: str = Field(default="", exclude=True)
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    provider_profiles: list[dict[str, Any]] = Field(default_factory=list)
    active_provider_id: str = ""

    # Prompt
    system_prompt: str = ""
    max_content_chars: int = 4000
    max_tokens: int = 4096

    # General
    language: str = "zh_CN"
    theme: str = "light"
    max_file_size_mb: int = 50
    default_template_id: str = ""

    # Organization
    auto_organize: bool = False
    organization_root: str = ""
    organization_rule: str = "by_type"  # by_date, by_type, by_category, by_project

    # Quality mode — "economy" | "balanced" | "high"
    quality_mode: str = "balanced"

    # Resource limits (non-monetary)
    max_concurrent_requests: int = Field(default=4, ge=1, le=20)
    request_timeout_seconds: int = Field(default=30, ge=5, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    max_pdf_pages: int = Field(default=50, ge=1, le=200)
    max_video_keyframes: int = Field(default=8, ge=1, le=32)

    # Privacy toggles
    allow_text_cloud: bool = True
    allow_vision_cloud: bool = True
    allow_video_keyframes_cloud: bool = True

    # Cache
    cache_enabled: bool = True
    cache_max_mb: int = Field(default=500, ge=10, le=10000)
    cache_ttl_days: int = Field(default=7, ge=1, le=90)

    class Config:
        # Allow extra fields for forward compatibility
        extra = "allow"
