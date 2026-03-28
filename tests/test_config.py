from openpdf2zh.config import AppSettings


def test_app_settings_reads_render_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENPDF2ZH_HYBRID_TIMEOUT_MS", "45000")
    monkeypatch.setenv("OPENPDF2ZH_RENDER_FONT_PATH", "/tmp/custom.ttf")
    monkeypatch.setenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR", "/tmp/ct2-model")
    monkeypatch.setenv("OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH", "/tmp/tokenizer.model")

    settings = AppSettings.from_env()

    assert settings.hybrid_timeout_ms == 45000
    assert settings.render_font_path == "/tmp/custom.ttf"
    assert settings.ctranslate2_model_dir == "/tmp/ct2-model"
    assert settings.ctranslate2_tokenizer_path == "/tmp/tokenizer.model"
