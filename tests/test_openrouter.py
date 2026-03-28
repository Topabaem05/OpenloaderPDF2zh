import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from openpdf2zh.providers.openrouter import OpenRouterTranslator


def test_openrouter_translator_invalid_api_key_is_actionable(monkeypatch) -> None:
    class _FakeCompletions:
        def create(self, **kwargs):
            request = httpx.Request(
                "POST", "https://openrouter.ai/api/v1/chat/completions"
            )
            response = httpx.Response(401, request=request)
            raise AuthenticationError(
                "invalid api key",
                response=response,
                body={"error": {"code": "invalid_api_key"}},
            )

    class _FakeChat:
        completions = _FakeCompletions()

    translator = OpenRouterTranslator("bad-key")
    monkeypatch.setattr(translator._client, "chat", _FakeChat())

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is invalid"):
        translator.translate(
            "hello",
            target_language="English",
            model="openai/gpt-oss-safeguard-20b",
        )


def test_openrouter_translator_rate_limit_is_actionable(monkeypatch) -> None:
    class _FakeCompletions:
        def create(self, **kwargs):
            request = httpx.Request(
                "POST", "https://openrouter.ai/api/v1/chat/completions"
            )
            response = httpx.Response(
                429, request=request, headers={"retry-after": "12s"}
            )
            raise RateLimitError(
                "rate limited",
                response=response,
                body={
                    "metadata": {
                        "provider_name": "Groq",
                        "raw": "openai/gpt-oss-safeguard-20b is temporarily rate-limited upstream.",
                    }
                },
            )

    class _FakeChat:
        completions = _FakeCompletions()

    translator = OpenRouterTranslator("key")
    monkeypatch.setattr(translator._client, "chat", _FakeChat())

    with pytest.raises(RuntimeError, match="OpenRouter → upstream Groq rate-limited"):
        translator.translate(
            "hello",
            target_language="English",
            model="openai/gpt-oss-safeguard-20b",
        )


def test_openrouter_translator_requests_newline_preservation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type(
                "_Response",
                (),
                {
                    "choices": [
                        type(
                            "_Choice",
                            (),
                            {"message": type("_Message", (), {"content": "ok"})()},
                        )()
                    ]
                },
            )()

    class _FakeChat:
        completions = _FakeCompletions()

    translator = OpenRouterTranslator("key")
    monkeypatch.setattr(translator._client, "chat", _FakeChat())

    translator.translate("line1\nline2", target_language="English", model="demo")

    system_prompt = captured["messages"][0]["content"]
    assert "line-break structure" in system_prompt
