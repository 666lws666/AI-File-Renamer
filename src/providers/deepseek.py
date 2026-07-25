"""DeepSeek AI provider — uses OpenAI-compatible API endpoint."""

from loguru import logger
from .base import BaseProvider


class DeepSeekProvider(BaseProvider):
    """DeepSeek AI provider via OpenAI-compatible API.

    DeepSeek's API is compatible with the OpenAI SDK.
    We use the official openai library pointed at api.deepseek.com.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        super().__init__(api_key, base_url, model)

    def suggest_filename(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        """Call DeepSeek API to analyze file content."""
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        logger.info(f"调用 DeepSeek API: {self.model}")
        logger.debug(f"系统提示词: {system_prompt[:200]}...")
        logger.debug(f"用户提示词长度: {len(user_prompt)} chars")

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,  # Low temperature for consistent structured output
        )

        content = response.choices[0].message.content or ""
        logger.info(f"DeepSeek 响应: {len(content)} chars")

        # Log token usage
        if hasattr(response, "usage") and response.usage:
            logger.info(f"Token 用量: {response.usage.total_tokens} (输入: {response.usage.prompt_tokens}, 输出: {response.usage.completion_tokens})")

        return content

    def test_connection(self) -> tuple[bool, str]:
        """Test DeepSeek API connection."""
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello, respond with 'OK' only."}],
                max_tokens=10,
            )

            content = response.choices[0].message.content or ""
            logger.info(f"连接测试成功: {content[:50]}")

            return True, f"连接成功 (模型: {self.model})"

        except Exception as e:
            logger.error(f"连接测试失败: {e}")
            return False, str(e)
