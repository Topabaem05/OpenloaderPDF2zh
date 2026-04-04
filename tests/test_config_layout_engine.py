from __future__ import annotations

from pathlib import Path

from openpdf2zh.config import AppSettings


def test_app_settings_layout_engine_defaults_to_legacy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENPDF2ZH_RENDER_LAYOUT_ENGINE", raising=False)
    monkeypatch.delenv("OPENPDF2ZH_PRETEXT_HELPER_PATH", raising=False)
    monkeypatch.delenv("OPENPDF2ZH_PRETEXT_HELPER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    settings = AppSettings.from_env()

    assert settings.render_layout_engine == "legacy"
    assert settings.pretext_helper_path == ""
    assert settings.pretext_helper_timeout_seconds == 20.0
    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_daily_seconds == 500
    assert settings.rate_limit_timezone == "Asia/Seoul"
    assert settings.rate_limit_storage_path.endswith("workspace/service_state/quota.sqlite3")
    assert settings.trust_forwarded_for is True


def test_app_settings_layout_engine_normalizes_values(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENPDF2ZH_RENDER_LAYOUT_ENGINE", "PRETEXT")
    monkeypatch.setenv("OPENPDF2ZH_PRETEXT_HELPER_PATH", "/tmp/pretext-helper.py")
    monkeypatch.setenv("OPENPDF2ZH_PRETEXT_HELPER_TIMEOUT_SECONDS", "45")

    pretext_settings = AppSettings.from_env()
    assert pretext_settings.render_layout_engine == "pretext"
    assert pretext_settings.pretext_helper_path == "/tmp/pretext-helper.py"
    assert pretext_settings.pretext_helper_timeout_seconds == 45.0

    monkeypatch.setenv("OPENPDF2ZH_RENDER_LAYOUT_ENGINE", "unsupported")
    fallback_settings = AppSettings.from_env()
    assert fallback_settings.render_layout_engine == "legacy"


def test_app_settings_reads_rate_limit_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENPDF2ZH_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENPDF2ZH_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("OPENPDF2ZH_RATE_LIMIT_DAILY_SECONDS", "900")
    monkeypatch.setenv("OPENPDF2ZH_RATE_LIMIT_TIMEZONE", "Asia/Tokyo")
    monkeypatch.setenv(
        "OPENPDF2ZH_RATE_LIMIT_STORAGE_PATH",
        str(tmp_path / "state" / "quota.db"),
    )
    monkeypatch.setenv("OPENPDF2ZH_TRUST_FORWARDED_FOR", "false")

    settings = AppSettings.from_env()

    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_daily_seconds == 900
    assert settings.rate_limit_timezone == "Asia/Tokyo"
    assert settings.rate_limit_storage_path == str(tmp_path / "state" / "quota.db")
    assert settings.trust_forwarded_for is False
