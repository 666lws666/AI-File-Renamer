"""DeepSeek AI provider — uses OpenAI-compatible API endpoint."""

from loguru import logger
from .base import BaseProvider


class DeepSeekProvider(BaseProvider):
    """DeepSeek AI provider via OpenAI-compatible API.

    DeepSeek's API is compatible with the OpenAI SDK.
    We use the official openai library pointed at api.deepseek.com.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1", model: str = "deepseek-v4-pro"):
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
            from openai import OpenAI, APIError, AuthenticationError, RateLimitError

            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            logger.info(f"测试连接: {self.base_url} model={self.model}")
            logger.info(f"API Key 前缀: {self.api_key[:8]}... 后缀: ...{self.api_key[-4:]}")

            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply with just the word OK"}],
                max_tokens=10,
            )

            content = response.choices[0].message.content or ""
            logger.info(f"连接测试成功: {content[:50]}")

            return True, f"API 连接正常！\n模型: {self.model}\n返回: {content.strip()}"

        except AuthenticationError as e:
            logger.error(f"API Key 无效: {e}")
            return False, f"API Key 无效或已过期。\n请检查 Key 是否正确，或前往 platform.deepseek.com 重新生成。\n\n原始错误: {e}"
        except RateLimitError as e:
            logger.error(f"API 速率限制: {e}")
            return False, f"API 请求过于频繁，请稍后重试。\n\n原始错误: {e}"
        except APIError as e:
            logger.error(f"API 错误: {e}")
            return False, f"API 服务返回错误。\n可能是 URL 不正确或模型名称有误。\n当前 URL: {self.base_url}\n当前模型: {self.model}\n\n原始错误: {e}"
        except Exception as e:
            logger.error(f"连接失败: {type(e).__name__}: {e}")
            return False, f"连接失败 ({type(e).__name__})。\n请检查网络连接和 Base URL 是否正确。\n当前 URL: {self.base_url}\n\n原始错误: {e}"
