from __future__ import annotations

from pathlib import Path

from openpdf2zh.config import AppSettings


def test_app_settings_parses_and_normalizes_cors_origins(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv(
        "OPENPDF2ZH_CORS_ALLOWED_ORIGINS",
        " https://openpdf2zh.vercel.app/, https://preview.example.com, "
        "https://openpdf2zh.vercel.app ",
    )

    settings = AppSettings.from_env()

    assert settings.cors_allowed_origins == (
        "https://openpdf2zh.vercel.app",
        "https://preview.example.com",
    )


def test_app_settings_disables_cors_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENPDF2ZH_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    settings = AppSettings.from_env()

    assert settings.cors_allowed_origins == ()
