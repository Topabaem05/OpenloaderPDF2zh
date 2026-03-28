from __future__ import annotations

from openai import APIStatusError, AuthenticationError, OpenAI, RateLimitError

from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.providers.errors import build_rate_limit_message, is_rate_limited_error


class OpenRouterTranslator(BaseTranslator):
    def __init__(
        self,
        api_key: str,
        *,
        app_name: str = "OpenPDF2ZH",
        app_url: str = "",
    ) -> None:
        headers: dict[str, str] = {}
        if app_url:
            headers["HTTP-Referer"] = app_url
        if app_name:
            headers["X-Title"] = app_name
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers=headers or None,
        )

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Translate the user's text into {target_language}. "
                            "Preserve math, LaTeX, citations, numbers, code, and technical terms when needed. "
                            "Preserve the original paragraph and line-break structure whenever the input already contains explicit newlines. "
                            "Return only the translated text."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
            )
        except AuthenticationError as exc:
            raise RuntimeError(
                "OPENROUTER_API_KEY is invalid. Update OPENROUTER_API_KEY in your active environment and try again."
            ) from exc
        except (APIStatusError, RateLimitError) as exc:
            if not is_rate_limited_error(exc):
                raise
            raise RuntimeError(
                build_rate_limit_message(exc, route_name="OpenRouter", model=model)
            ) from exc
        content = response.choices[0].message.content
        return content.strip() if isinstance(content, str) else str(content).strip()
