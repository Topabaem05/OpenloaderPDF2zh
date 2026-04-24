from __future__ import annotations

import json
from pathlib import Path
from urllib import error as urllib_error

import pytest

from openpdf2zh.config import (
    AppSettings,
    OPENROUTER_FIXED_MODEL,
    OPENROUTER_PROVIDER,
)
from openpdf2zh.models import PipelineRequest
from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.services.translation_service import TranslationService
from openpdf2zh.ui import (
    _is_local_client_ip,
    _model_for_provider,
    _should_enforce_rate_limit,
    _uses_openrouter,
    create_demo,
)


def test_openrouter_translator_serializes_chat_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "translated text"}}]}
            ).encode("utf-8")

    def _fake_urlopen(request, timeout=None):
        headers = {key.lower(): value for key, value in request.header_items()}
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = headers.get("authorization")
        captured["content_type"] = headers.get("content-type")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr(
        "openpdf2zh.providers.openrouter.urllib_request.urlopen",
        _fake_urlopen,
    )

    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
    )
    translated = translator.translate(
        "Hello world",
        target_language="Korean",
        model=OPENROUTER_FIXED_MODEL,
    )

    assert translated == "translated text"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["timeout"] is None
    assert captured["authorization"] == "Bearer sk-or-v1-test"
    assert captured["content_type"] == "application/json"
    assert captured["payload"]["model"] == OPENROUTER_FIXED_MODEL
    assert captured["payload"]["temperature"] == 0
    assert "provider" not in captured["payload"]
    assert captured["payload"]["messages"][1]["content"].startswith(
        "Target language: Korean"
    )


def test_openrouter_translator_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "translated text"}}]}
            ).encode("utf-8")

    def _fake_urlopen(request, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("The read operation timed out")
        return _FakeResponse()

    monkeypatch.setattr(
        "openpdf2zh.providers.openrouter.urllib_request.urlopen",
        _fake_urlopen,
    )
    monkeypatch.setattr("openpdf2zh.providers.openrouter.time.sleep", lambda _: None)

    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
    )

    translated = translator.translate(
        "Hello world",
        target_language="Korean",
        model=OPENROUTER_FIXED_MODEL,
    )

    assert translated == "translated text"
    assert attempts["count"] == 2


def test_openrouter_translator_wraps_timeout_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request, timeout=None):
        raise urllib_error.URLError("timed out")

    monkeypatch.setattr(
        "openpdf2zh.providers.openrouter.urllib_request.urlopen",
        _fake_urlopen,
    )
    monkeypatch.setattr("openpdf2zh.providers.openrouter.time.sleep", lambda _: None)

    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
    )

    with pytest.raises(
        RuntimeError,
        match="OpenRouter request timed out after 3 attempts.",
    ):
        translator.translate(
            "Hello world",
            target_language="Korean",
            model=OPENROUTER_FIXED_MODEL,
        )


def test_translation_service_requires_openrouter_api_key_for_groq_provider() -> None:
    service = TranslationService(AppSettings())

    with pytest.raises(RuntimeError, match="OpenRouter API key is required"):
        service._build_translator(
            PipelineRequest(
                input_pdf=Path("dummy.pdf"),
                target_language="Korean",
                provider=OPENROUTER_PROVIDER,
                model=OPENROUTER_FIXED_MODEL,
            )
        )


def test_translation_service_accepts_openrouter_alias() -> None:
    service = TranslationService(AppSettings())

    translator = service._build_translator(
        PipelineRequest(
            input_pdf=Path("dummy.pdf"),
            target_language="Korean",
            provider="openrouter",
            model=OPENROUTER_FIXED_MODEL,
            provider_api_key="sk-or-v1-test",
        )
    )

    assert isinstance(translator, OpenRouterTranslator)


def test_app_settings_openrouter_defaults_fixed_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENPDF2ZH_DEFAULT_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENPDF2ZH_DEFAULT_MODEL", "ignored-model")

    settings = AppSettings.from_env()

    assert settings.default_provider == OPENROUTER_PROVIDER
    assert settings.default_model == OPENROUTER_FIXED_MODEL


def test_ui_exposes_openrouter_controls_and_fixed_model() -> None:
    settings = AppSettings(default_provider=OPENROUTER_PROVIDER, default_model="ignored")
    demo = create_demo(settings)
    labeled_blocks = {
        getattr(block, "label", ""): block
        for block in demo.blocks.values()
        if getattr(block, "label", "")
    }

    assert _uses_openrouter("groq") is True
    assert _uses_openrouter("openrouter") is True
    assert _model_for_provider("groq", settings) == OPENROUTER_FIXED_MODEL
    assert "Service" in labeled_blocks
    assert "OpenRouter API key" in labeled_blocks
    assert "OpenRouter model" in labeled_blocks
    assert ("OpenRouter", OPENROUTER_PROVIDER) in labeled_blocks["Service"].choices
    assert labeled_blocks["OpenRouter API key"].visible is True
    assert labeled_blocks["OpenRouter model"].value == OPENROUTER_FIXED_MODEL
    provider_change = demo.fns[0].fn
    target_language_update, openrouter_controls_update = provider_change(
        OPENROUTER_PROVIDER, "English"
    )
    assert target_language_update["value"] == "English"
    assert openrouter_controls_update["visible"] is True


def test_ui_rate_limit_exempts_only_loopback_clients() -> None:
    settings = AppSettings(rate_limit_enabled=True)

    assert _is_local_client_ip("127.0.0.1") is True
    assert _is_local_client_ip("::1") is True
    assert _is_local_client_ip("localhost") is True
    assert _is_local_client_ip("1.1.1.1") is False
    assert _is_local_client_ip("192.168.0.10") is False

    assert _should_enforce_rate_limit("127.0.0.1", settings) is False
    assert _should_enforce_rate_limit("::1", settings) is False
    assert _should_enforce_rate_limit("localhost", settings) is False
    assert _should_enforce_rate_limit("1.1.1.1", settings) is True
    assert _should_enforce_rate_limit("192.168.0.10", settings) is True
