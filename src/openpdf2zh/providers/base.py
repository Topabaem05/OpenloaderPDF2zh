from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTranslator(ABC):
    @abstractmethod
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        raise NotImplementedError
