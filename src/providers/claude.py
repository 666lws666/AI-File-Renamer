"""Anthropic Claude provider — stretch feature, implemented for provider switching."""

from loguru import logger
from .base import BaseProvider


class ClaudeProvider(BaseProvider):
    """Anthropic Claude provider via the official Anthropic SDK."""

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com", model: str = "claude-sonnet-4-20250514"):
        super().__init__(api_key, base_url, model)

    def suggest_filename(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        logger.info(f"调用 Claude API: {self.model}")

        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    def test_connection(self) -> tuple[bool, str]:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
            response = client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Say 'OK'"}],
            )
            return True, f"连接成功 (模型: {self.model})"
        except Exception as e:
            return False, str(e)
