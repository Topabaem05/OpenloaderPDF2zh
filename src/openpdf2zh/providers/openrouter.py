from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from openpdf2zh.providers.base import BaseTranslator


class OpenRouterTranslator(BaseTranslator):
    MAX_ATTEMPTS = 3
    RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
    SYSTEM_PROMPT = (
        "You are a translation engine for PDF text extraction. "
        "Translate the user text into the requested language. "
        "Preserve meaning, list markers, numbering, and line breaks when possible. "
        "Return only the translated text."
    )

    def __init__(
        self,
        api_key: str,
        *,
        api_base_url: str,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_base_url = api_base_url.strip()
        if not self._api_key:
            raise RuntimeError("OpenRouter API key is required.")
        if not self._api_base_url:
            raise RuntimeError("OpenRouter API base URL is required.")

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Target language: {target_language}\n"
                        "Translate the following text exactly once.\n\n"
                        f"{text}"
                    ),
                },
            ],
        }
        request = urllib_request.Request(
            self._api_base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        raw_payload = self._execute_request(request)

        try:
            data = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenRouter returned invalid JSON.") from exc

        translated = self._extract_message_content(data)
        if not translated.strip():
            raise RuntimeError("OpenRouter returned an empty translation.")
        return translated.strip()

    def _execute_request(self, request: urllib_request.Request) -> str:
        last_error: BaseException | None = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                with urllib_request.urlopen(
                    request,
                ) as response:
                    return response.read().decode("utf-8")
            except urllib_error.HTTPError as exc:
                last_error = exc
                if (
                    exc.code in self.RETRYABLE_STATUS_CODES
                    and attempt < self.MAX_ATTEMPTS
                ):
                    self._sleep_before_retry(attempt)
                    continue
                detail = self._extract_error_detail(exc)
                raise RuntimeError(
                    f"OpenRouter request failed with status {exc.code}: {detail}"
                ) from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt < self.MAX_ATTEMPTS:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(
                    f"OpenRouter request timed out after {self.MAX_ATTEMPTS} attempts."
                ) from exc
            except urllib_error.URLError as exc:
                last_error = exc
                if self._is_timeout_reason(exc.reason):
                    if attempt < self.MAX_ATTEMPTS:
                        self._sleep_before_retry(attempt)
                        continue
                    raise RuntimeError(
                        f"OpenRouter request timed out after {self.MAX_ATTEMPTS} attempts."
                    ) from exc
                raise RuntimeError(
                    f"OpenRouter request could not be completed: {exc.reason}"
                ) from exc

        raise RuntimeError("OpenRouter request failed without a response.") from last_error

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(float(attempt))

    def _is_timeout_reason(self, reason: object) -> bool:
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return True
        if isinstance(reason, str):
            return "timed out" in reason.lower() or "timeout" in reason.lower()
        return False

    def _extract_error_detail(self, exc: urllib_error.HTTPError) -> str:
        try:
            payload = exc.read().decode("utf-8")
        except OSError:
            return "unknown error"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return payload.strip() or "unknown error"
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        return payload.strip() or "unknown error"

    def _extract_message_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenRouter response did not include any choices.")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("OpenRouter choice payload is malformed.")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("OpenRouter message payload is malformed.")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            return "".join(chunks)
        raise RuntimeError("OpenRouter message content is missing.")
