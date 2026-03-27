import json
from io import BytesIO
from urllib import error

import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.providers.libretranslate import (
    LibreTranslateTranslator,
    resolve_target_language_code,
)
from openpdf2zh.services.translation_service import TranslationService


class _DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_build_translator_returns_libretranslate_provider() -> None:
    service = TranslationService(
        AppSettings(
            libretranslate_url="http://127.0.0.1:5000",
            libretranslate_api_key="token",
        )
    )

    translator = service._build_translator("libretranslate")

    assert isinstance(translator, LibreTranslateTranslator)


def test_libretranslate_translator_posts_json(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(http_request, timeout: int) -> _DummyResponse:
        captured["url"] = http_request.full_url
        captured["payload"] = json.loads(http_request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _DummyResponse({"translatedText": "안녕하세요"})

    monkeypatch.setattr(
        "openpdf2zh.providers.libretranslate.request.urlopen",
        fake_urlopen,
    )

    translator = LibreTranslateTranslator(
        "http://127.0.0.1:5000/",
        api_key="token",
    )
    translated = translator.translate(
        "Hello",
        target_language="Korean",
        model="libretranslate",
    )

    assert translated == "안녕하세요"
    assert captured["url"] == "http://127.0.0.1:5000/translate"
    assert captured["timeout"] == 60
    assert captured["payload"] == {
        "q": "Hello",
        "source": "auto",
        "target": "ko",
        "format": "text",
        "api_key": "token",
    }


def test_resolve_target_language_code_rejects_unknown_language() -> None:
    with pytest.raises(ValueError, match="Unsupported LibreTranslate target language"):
        resolve_target_language_code("German")


def test_resolve_target_language_code_uses_libretranslate_codes() -> None:
    assert resolve_target_language_code("Simplified Chinese") == "zh"
    assert resolve_target_language_code("Traditional Chinese") == "zt"


def test_libretranslate_translator_403_without_api_key_is_actionable(
    monkeypatch,
) -> None:
    def fake_urlopen(http_request, timeout: int) -> _DummyResponse:
        raise error.HTTPError(
            http_request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":"Forbidden"}'),
        )

    monkeypatch.setattr(
        "openpdf2zh.providers.libretranslate.request.urlopen",
        fake_urlopen,
    )

    translator = LibreTranslateTranslator("https://libretranslate.example")

    with pytest.raises(RuntimeError, match="likely requires an API key"):
        translator.translate(
            "Hello",
            target_language="Korean",
            model="libretranslate",
        )


def test_libretranslate_translator_403_with_api_key_mentions_invalid_key(
    monkeypatch,
) -> None:
    def fake_urlopen(http_request, timeout: int) -> _DummyResponse:
        raise error.HTTPError(
            http_request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"error":"Forbidden"}'),
        )

    monkeypatch.setattr(
        "openpdf2zh.providers.libretranslate.request.urlopen",
        fake_urlopen,
    )

    translator = LibreTranslateTranslator(
        "https://libretranslate.example",
        api_key="token",
    )

    with pytest.raises(RuntimeError, match="may be invalid"):
        translator.translate(
            "Hello",
            target_language="Korean",
            model="libretranslate",
        )
