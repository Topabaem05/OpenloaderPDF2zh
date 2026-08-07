from __future__ import annotations

from pathlib import Path

import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.services.context_translation_service import ContextTranslationService


def test_app_settings_reads_glossary_path(monkeypatch, tmp_path: Path) -> None:
    glossary_path = tmp_path / "terms.csv"
    glossary_path.write_text(
        "source,target\nboundary layer,경계층\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENPDF2ZH_GLOSSARY_PATH", str(glossary_path))

    settings = AppSettings.from_env()

    assert settings.glossary_path == str(glossary_path)


def test_context_translation_service_loads_configured_glossary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    glossary_path = tmp_path / "terms.csv"
    glossary_path.write_text(
        "source,target\nboundary layer,경계층\nlift coefficient,양력 계수\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENPDF2ZH_GLOSSARY_PATH", str(glossary_path))
    settings = AppSettings.from_env()

    service = ContextTranslationService(settings)

    assert service.glossary.mapping_for_text(
        "Boundary layer and lift coefficient"
    ) == {
        "lift coefficient": "양력 계수",
        "boundary layer": "경계층",
    }


def test_context_translation_service_rejects_missing_glossary(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    settings = AppSettings(glossary_path=str(missing))

    with pytest.raises(FileNotFoundError, match="OPENPDF2ZH_GLOSSARY_PATH"):
        ContextTranslationService(settings)
