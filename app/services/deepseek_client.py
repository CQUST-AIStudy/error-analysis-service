"""DeepSeek API client wrapper with retry and fallback logic."""

import json
import logging
from typing import Any

from openai import OpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """Encapsulates DeepSeek API calls with retry, JSON parsing, and graceful degradation."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.deepseek_model
        if settings.deepseek_api_key:
            self.client = OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                timeout=settings.request_timeout,
            )
        else:
            self.client = None

    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any] | None:
        """
        Call DeepSeek and parse the response as JSON.

        Returns parsed JSON dict on success, None on failure.
        On JSON parse failure, retries once with lower temperature.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        result = self._call_with_retry(messages, temperature, max_tokens)
        if result is None:
            return None

        # Try to parse JSON
        parsed = self._extract_json(result)
        if parsed is not None:
            return parsed

        # Retry with lower temperature for stricter JSON output
        logger.info("JSON parse failed, retrying with temperature=0.1")
        result = self._call_with_retry(messages, 0.1, max_tokens)
        if result is None:
            return None

        parsed = self._extract_json(result)
        return parsed

    def _call_with_retry(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str | None:
        """Call DeepSeek API with up to 1 retry on failure."""
        if self.client is None:
            logger.warning("DeepSeek client not available (no API key configured)")
            return None
        for attempt in range(2):
            try:
                logger.info(
                    "DeepSeek call attempt %d/2 (model=%s, temperature=%.1f, max_tokens=%d)",
                    attempt + 1,
                    self.model,
                    temperature,
                    max_tokens,
                )
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if content:
                    return content
                logger.warning("DeepSeek returned empty content")
                return None

            except Exception as e:
                logger.warning("DeepSeek call attempt %d failed: %s", attempt + 1, e)
                if attempt == 0:
                    continue
                logger.error("DeepSeek call failed after 2 attempts")
                return None

        return None

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract and parse JSON from model response text."""
        if not text:
            return None
        text = text.strip()
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON inside markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
        # Try to find the outermost {...}
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to extract JSON from response: %.200s...", text)
        return None


# Singleton factory
_deepseek_client: DeepSeekClient | None = None


def get_deepseek_client() -> DeepSeekClient:
    global _deepseek_client
    if _deepseek_client is None:
        from app.core.config import get_settings

        _deepseek_client = DeepSeekClient(get_settings())
    return _deepseek_client
