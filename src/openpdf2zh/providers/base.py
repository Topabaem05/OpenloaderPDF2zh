from __future__ import annotations

from abc import ABC, abstractmethod

from openpdf2zh.translation.contracts import TranslationRequestItem


class BaseTranslator(ABC):
    @abstractmethod
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        raise NotImplementedError

    def translate_many(
        self,
        items: list[TranslationRequestItem],
        *,
        model: str,
    ) -> list[str]:
        return [
            self.translate(
                item.text,
                target_language=item.target_language,
                model=model,
            )
            for item in items
        ]
