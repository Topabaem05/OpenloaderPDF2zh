from __future__ import annotations

import json
from urllib import error, request

from openpdf2zh.providers.base import BaseTranslator

TARGET_LANGUAGE_CODES = {
    "Simplified Chinese": "zh",
    "Traditional Chinese": "zt",
    "English": "en",
    "Japanese": "ja",
    "Korean": "ko",
}


def resolve_target_language_code(target_language: str) -> str:
    try:
        return TARGET_LANGUAGE_CODES[target_language]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported LibreTranslate target language: {target_language}"
        ) from exc


class LibreTranslateTranslator(BaseTranslator):
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        payload = {
            "q": text,
            "source": "auto",
            "target": resolve_target_language_code(target_language),
            "format": "text",
        }
        if self._api_key:
            payload["api_key"] = self._api_key

        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self._base_url}/translate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=60) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = self._read_error_detail(exc)
            raise RuntimeError(self._format_http_error(exc.code, detail)) from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"LibreTranslate is unreachable at {self._base_url}. Check OPENPDF2ZH_LIBRETRANSLATE_URL."
            ) from exc

        data = json.loads(raw_body)
        translated_text = data.get("translatedText")
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise RuntimeError(
                "LibreTranslate returned an invalid translation response."
            )
        return translated_text.strip()

    def _read_error_detail(self, exc: error.HTTPError) -> str:
        raw_detail = exc.read().decode("utf-8", errors="replace").strip()
        if not raw_detail:
            return exc.reason

        try:
            data = json.loads(raw_detail)
        except json.JSONDecodeError:
            return raw_detail

        if isinstance(data, dict):
            detail = data.get("error") or data.get("message") or data.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return raw_detail

    def _format_http_error(self, status_code: int, detail: str) -> str:
        message = f"LibreTranslate request to {self._base_url}/translate failed with status {status_code}: {detail}"
        if status_code == 401:
            return f"{message}. Check LIBRETRANSLATE_API_KEY or switch to a LibreTranslate server that allows your request."
        if status_code == 403:
            if self._api_key:
                return f"{message}. The configured LIBRETRANSLATE_API_KEY may be invalid or this server may deny your account."
            return f"{message}. This LibreTranslate server likely requires an API key. Set LIBRETRANSLATE_API_KEY or point OPENPDF2ZH_LIBRETRANSLATE_URL to a local/self-hosted server."
        return message
