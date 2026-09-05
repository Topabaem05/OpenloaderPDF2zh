from __future__ import annotations

import json

from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.translation.contracts import TranslationRequestItem


def test_openrouter_translate_many_sends_context_and_glossary(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_execute(self, request):
        _ = self
        captured.append(json.loads(request.data.decode("utf-8")))
        return json.dumps(
            {"choices": [{"message": {"content": "경계층이 성장한다."}}]}
        )

    monkeypatch.setattr(OpenRouterTranslator, "_execute_request", fake_execute)
    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
    )
    item = TranslationRequestItem(
        segment_id="r0001",
        text="It grows downstream.",
        target_language="Korean",
        section_title="Boundary Layer",
        paragraph_text="The boundary layer grows downstream and then transitions.",
        previous_text="The boundary layer begins near the leading edge.",
        next_text="Transition follows.",
        glossary={"boundary layer": "경계층"},
    )

    result = translator.translate_many([item], model="test-model")

    assert result == ["경계층이 성장한다."]
    prompt = captured[0]["messages"][1]["content"]
    assert "Section title: Boundary Layer" in prompt
    assert (
        "Current paragraph: The boundary layer grows downstream and then transitions."
        in prompt
    )
    assert "Previous paragraph:" in prompt
    assert "Next paragraph: Transition follows." in prompt
    assert "boundary layer => 경계층" in prompt
    assert prompt.endswith("Text to translate:\nIt grows downstream.")


def test_openrouter_prompt_lists_protected_tokens_without_exposing_values(
    monkeypatch,
) -> None:
    prompts: list[str] = []

    def fake_execute(self, request):
        _ = self
        payload = json.loads(request.data.decode("utf-8"))
        prompts.append(payload["messages"][1]["content"])
        return json.dumps({"choices": [{"message": {"content": "A <TOKEN_1> B"}}]})

    monkeypatch.setattr(OpenRouterTranslator, "_execute_request", fake_execute)
    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
    )
    item = TranslationRequestItem(
        segment_id="p1",
        text="A <TOKEN_1> B",
        target_language="Korean",
        protected_tokens={"<TOKEN_1>": "Cp = (p-p0)/q0"},
    )

    translator.translate_many([item], model="test-model")

    assert "- <TOKEN_1>" in prompts[0]
    assert "Cp = (p-p0)/q0" not in prompts[0]
