from __future__ import annotations

from openpdf2zh.config import AppSettings
from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.translation.contracts import TranslationRequestItem


def test_app_settings_reads_translation_max_workers(monkeypatch) -> None:
    monkeypatch.setenv("OPENPDF2ZH_TRANSLATION_MAX_WORKERS", "3")

    settings = AppSettings.from_env()

    assert settings.translation_max_workers == 3


def test_openrouter_translate_many_uses_bounded_executor_and_preserves_order(
    monkeypatch,
) -> None:
    import openpdf2zh.providers.openrouter as openrouter_module

    executor_workers: list[int] = []

    class _FakeExecutor:
        def __init__(self, *, max_workers: int) -> None:
            executor_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def map(self, function, items):
            return [function(item) for item in items]

    monkeypatch.setattr(
        openrouter_module,
        "ThreadPoolExecutor",
        _FakeExecutor,
        raising=False,
    )

    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
        max_workers=3,
    )
    monkeypatch.setattr(
        translator,
        "_translate_item",
        lambda item, *, model: f"{model}:{item.segment_id}",
    )
    items = [
        TranslationRequestItem("first", "A", "Korean"),
        TranslationRequestItem("second", "B", "Korean"),
        TranslationRequestItem("third", "C", "Korean"),
    ]

    translated = translator.translate_many(items, model="test-model")

    assert executor_workers == [3]
    assert translated == [
        "test-model:first",
        "test-model:second",
        "test-model:third",
    ]


def test_openrouter_translate_many_caps_workers_to_item_count(monkeypatch) -> None:
    import openpdf2zh.providers.openrouter as openrouter_module

    executor_workers: list[int] = []

    class _FakeExecutor:
        def __init__(self, *, max_workers: int) -> None:
            executor_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def map(self, function, items):
            return [function(item) for item in items]

    monkeypatch.setattr(
        openrouter_module,
        "ThreadPoolExecutor",
        _FakeExecutor,
        raising=False,
    )
    translator = OpenRouterTranslator(
        "sk-or-v1-test",
        api_base_url="https://openrouter.ai/api/v1/chat/completions",
        max_workers=8,
    )
    monkeypatch.setattr(
        translator,
        "_translate_item",
        lambda item, *, model: item.text,
    )

    translator.translate_many(
        [
            TranslationRequestItem("one", "A", "Korean"),
            TranslationRequestItem("two", "B", "Korean"),
        ],
        model="test-model",
    )

    assert executor_workers == [2]
