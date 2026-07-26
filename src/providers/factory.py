"""Provider factory — create AI provider instances from configuration."""

from loguru import logger
from .base import BaseProvider
from .deepseek import DeepSeekProvider


def create_provider(config) -> BaseProvider:
    """Create an AI provider instance from application configuration.

    Args:
        config: AppConfig instance with provider settings.

    Returns:
        A BaseProvider subclass instance.

    Raises:
        ValueError: If the provider is unknown or API key is missing.
    """
    if not config.api_key:
        raise ValueError("API Key 未设置，请在设置中配置")

    provider_name = config.provider.lower()

    if provider_name == "deepseek":
        return DeepSeekProvider(
            api_key=config.api_key,
            base_url=config.base_url or "https://api.deepseek.com",
            model=config.model or "deepseek-v4-pro",
        )

    # OpenAI uses the same SDK pattern
    if provider_name == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(
            api_key=config.api_key,
            base_url=config.base_url or "https://api.openai.com/v1",
            model=config.model or "gpt-4o",
        )

    if provider_name == "claude":
        from .claude import ClaudeProvider
        return ClaudeProvider(
            api_key=config.api_key,
            base_url=config.base_url or "https://api.anthropic.com",
            model=config.model or "claude-sonnet-4-20250514",
        )

    raise ValueError(f"未知的 AI 服务商: {provider_name}")
