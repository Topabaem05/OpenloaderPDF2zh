from openpdf2zh.config import AppSettings


def test_app_settings_reads_libretranslate_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENPDF2ZH_LIBRETRANSLATE_URL", "http://localhost:5050")
    monkeypatch.setenv("LIBRETRANSLATE_API_KEY", "secret-key")
    monkeypatch.setenv("OPENPDF2ZH_HYBRID_TIMEOUT_MS", "45000")
    monkeypatch.setenv("OPENPDF2ZH_RENDER_FONT_PATH", "/tmp/custom.ttf")

    settings = AppSettings.from_env()

    assert settings.libretranslate_url == "http://localhost:5050"
    assert settings.libretranslate_api_key == "secret-key"
    assert settings.hybrid_timeout_ms == 45000
    assert settings.render_font_path == "/tmp/custom.ttf"
