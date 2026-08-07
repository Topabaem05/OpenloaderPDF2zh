from __future__ import annotations

from pathlib import Path

from openpdf2zh.translation.contracts import TranslationRequestItem


def _item(
    *,
    previous_text: str = "Previous paragraph",
    glossary: dict[str, str] | None = None,
) -> TranslationRequestItem:
    return TranslationRequestItem(
        segment_id="r1",
        text="The boundary layer grows.",
        target_language="Korean",
        section_title="Boundary Layer",
        previous_text=previous_text,
        next_text="Transition follows.",
        glossary=glossary or {"boundary layer": "경계층"},
    )


def test_translation_cache_round_trip(tmp_path: Path) -> None:
    from openpdf2zh.services.translation_cache import TranslationCache

    cache = TranslationCache(tmp_path / "translations.sqlite3")
    item = _item()

    assert cache.get(item, provider="openrouter", model="test-model") is None

    cache.put(
        item,
        provider="openrouter",
        model="test-model",
        translated_text="경계층이 성장한다.",
    )

    assert cache.get(
        item,
        provider="openrouter",
        model="test-model",
    ) == "경계층이 성장한다."


def test_translation_cache_key_changes_with_context_and_glossary(tmp_path: Path) -> None:
    from openpdf2zh.services.translation_cache import TranslationCache

    cache = TranslationCache(tmp_path / "translations.sqlite3")
    base = _item()
    changed_context = _item(previous_text="Different previous paragraph")
    changed_glossary = _item(glossary={"boundary layer": "경계 레이어"})

    keys = {
        cache.key_for(base, provider="openrouter", model="test-model"),
        cache.key_for(
            changed_context,
            provider="openrouter",
            model="test-model",
        ),
        cache.key_for(
            changed_glossary,
            provider="openrouter",
            model="test-model",
        ),
    }

    assert len(keys) == 3


def test_translation_cache_key_changes_with_provider_model_and_target(
    tmp_path: Path,
) -> None:
    from openpdf2zh.services.translation_cache import TranslationCache

    cache = TranslationCache(tmp_path / "translations.sqlite3")
    item = _item()
    japanese = TranslationRequestItem(
        segment_id=item.segment_id,
        text=item.text,
        target_language="Japanese",
        section_title=item.section_title,
        previous_text=item.previous_text,
        next_text=item.next_text,
        glossary=item.glossary,
    )

    keys = {
        cache.key_for(item, provider="openrouter", model="model-a"),
        cache.key_for(item, provider="openrouter", model="model-b"),
        cache.key_for(item, provider="ctranslate2", model="model-a"),
        cache.key_for(japanese, provider="openrouter", model="model-a"),
    }

    assert len(keys) == 4
