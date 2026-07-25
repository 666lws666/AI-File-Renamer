"""AI Engine — orchestrates content → prompt → API call → structured result."""

import json
import re
from loguru import logger

from ..models.file_item import FileItem, FileStatus
from ..models.template import NamingTemplate
from ..models.app_config import AppConfig
from ..utils.constants import DEFAULT_SYSTEM_PROMPT
from ..providers.factory import create_provider


class AIEngine:
    """Orchestrates AI-powered filename suggestion for files."""

    def __init__(self, config: AppConfig):
        """Initialize with application configuration.

        Args:
            config: AppConfig with API key, provider, model settings.
        """
        self.config = config
        self.provider = None  # Lazily created

    def _get_provider(self):
        """Get or create the AI provider instance."""
        if self.provider is None:
            self.provider = create_provider(self.config)
        return self.provider

    def suggest(self, file_item: FileItem, template: NamingTemplate = None) -> None:
        """Analyze file content and generate a suggested filename.

        Updates file_item in place with ai_fields and suggested_name.

        Args:
            file_item: The FileItem with extracted content.
            template: Optional naming template. Uses default if not provided.
        """
        if file_item.status != FileStatus.EXTRACTED:
            logger.warning(f"文件状态不是 extracted: {file_item.original_name}")
            return

        file_item.status = FileStatus.SUGGESTING

        try:
            # Build prompts
            system_prompt = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
            user_prompt = self._build_user_prompt(file_item)

            # Call AI
            provider = self._get_provider()
            response_text = provider.suggest_filename(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=self.config.max_tokens,
            )

            # Parse JSON from response
            ai_fields = self._parse_response(response_text)
            file_item.ai_fields = ai_fields

            # Generate filename using template
            if template:
                from ..core.template_engine import TemplateEngine
                engine = TemplateEngine()
                suggested = engine.render(template, ai_fields, file_item)
            else:
                suggested = self._build_default_name(ai_fields, file_item)

            file_item.suggested_name = suggested
            file_item.final_name = suggested
            file_item.status = FileStatus.SUGGESTED
            logger.info(f"AI 建议: {file_item.original_name} → {suggested}")

        except Exception as e:
            logger.error(f"AI 建议失败: {file_item.original_name} — {e}")
            file_item.status = FileStatus.FAILED
            file_item.error_message = str(e)

    def _build_user_prompt(self, file_item: FileItem) -> str:
        """Build the user prompt with file content and metadata."""
        prompt = f"""请分析以下文件内容并提取结构化信息。

文件名: {file_item.original_name}
文件类型: {file_item.file_type}
文件大小: {file_item.file_size} 字节

文件内容:
---
{file_item.extracted_text}
---

文件元数据:
{json.dumps(file_item.metadata, ensure_ascii=False, indent=2)}

请返回 JSON 格式的结构化信息。"""
        return prompt

    def _parse_response(self, text: str) -> dict:
        """Extract JSON from AI response, handling markdown code fences.

        Args:
            text: Raw AI response text.

        Returns:
            Parsed JSON dict. Returns empty dict on failure.
        """
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try to find raw JSON in the text
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = text

        try:
            data = json.loads(json_str)
            logger.debug(f"解析 AI 响应: {json.dumps(data, ensure_ascii=False)[:200]}")
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}, 原始响应: {text[:500]}")
            # Return a minimal dict with raw text as title
            return {"title": text[:100].replace("\n", " ").strip(), "date": "unknown"}

    def _build_default_name(self, ai_fields: dict, file_item: FileItem) -> str:
        """Build a default filename from AI fields when no template is used.

        Format: {date}_{title}.{ext}
        """
        from ..utils.file_utils import sanitize_filename

        date = ai_fields.get("date", "unknown")
        title = ai_fields.get("title", "unnamed")
        ext = file_item.original_ext.lstrip(".")

        # Clean up title: replace spaces, remove path chars
        title = title.strip().replace(" ", "-")
        name = f"{date}_{title}.{ext}"

        return sanitize_filename(name)

    def test_connection(self) -> tuple[bool, str]:
        """Test the AI provider connection."""
        try:
            provider = self._get_provider()
            return provider.test_connection()
        except Exception as e:
            return False, str(e)
