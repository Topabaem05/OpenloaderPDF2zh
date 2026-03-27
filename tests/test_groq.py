import pytest
import httpx
from openai import AuthenticationError

from openpdf2zh.providers.groq import GroqTranslator


def test_groq_translator_invalid_api_key_is_actionable(monkeypatch) -> None:
    class _FakeCompletions:
        def create(self, **kwargs):
            request = httpx.Request(
                "POST", "https://api.groq.com/openai/v1/chat/completions"
            )
            response = httpx.Response(401, request=request)
            raise AuthenticationError(
                "invalid api key",
                response=response,
                body={"error": {"code": "invalid_api_key"}},
            )

    class _FakeChat:
        completions = _FakeCompletions()

    translator = GroqTranslator("bad-key")
    monkeypatch.setattr(translator._client, "chat", _FakeChat())

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is invalid"):
        translator.translate(
            "hello",
            target_language="English",
            model="openai/gpt-oss-safeguard-20b",
        )
