from __future__ import annotations

from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.translation.contracts import TranslationRequestItem


class _EchoTranslator(BaseTranslator):
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        return f"{target_language}:{model}:{text}"


def test_base_translator_translate_many_preserves_item_order() -> None:
    translator = _EchoTranslator()
    items = [
        TranslationRequestItem("one", "alpha", "Korean"),
        TranslationRequestItem("two", "beta", "Japanese"),
    ]

    translated = translator.translate_many(items, model="test-model")

    assert translated == [
        "Korean:test-model:alpha",
        "Japanese:test-model:beta",
    ]
