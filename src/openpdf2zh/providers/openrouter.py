from __future__ import annotations

from openai import OpenAI

from openpdf2zh.providers.base import BaseTranslator


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
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate the user's text into {target_language}. "
                        "Preserve math, LaTeX, citations, numbers, code, and technical terms when needed. "
                        "Return only the translated text."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        return content.strip() if isinstance(content, str) else str(content).strip()
