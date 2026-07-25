"""Abstract base class for AI providers."""

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Abstract interface for AI service providers."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    def suggest_filename(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        """Call the AI API and return the raw response text.

        Args:
            system_prompt: System-level instructions for the AI.
            user_prompt: File content and metadata for analysis.
            max_tokens: Maximum tokens in the response.

        Returns:
            Raw text response from the AI (expected to be JSON).
        """
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Test that the API credentials and endpoint work.

        Returns:
            (success, message)
        """
        ...
