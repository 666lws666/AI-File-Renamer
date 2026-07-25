"""OpenAI provider — stretch feature, implemented for provider switching."""

from loguru import logger
from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    """OpenAI provider via the official OpenAI SDK."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o"):
        super().__init__(api_key, base_url, model)

    def suggest_filename(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        logger.info(f"调用 OpenAI API: {self.model}")

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def test_connection(self) -> tuple[bool, str]:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Say 'OK'"}],
                max_tokens=10,
            )
            return True, f"连接成功 (模型: {self.model})"
        except Exception as e:
            return False, str(e)
