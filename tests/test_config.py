from openpdf2zh.config import AppSettings


def test_app_settings_reads_render_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENPDF2ZH_DUPLICATE_BOX_IOU_THRESHOLD", "0.88")
    monkeypatch.setenv("OPENPDF2ZH_DUPLICATE_BOX_IOM_THRESHOLD", "0.95")
    monkeypatch.setenv("OPENPDF2ZH_RENDER_FONT_PATH", "/tmp/custom.ttf")
    monkeypatch.setenv("OPENPDF2ZH_ADJUST_RENDER_LETTER_SPACING_FOR_OVERLAP", "false")
    monkeypatch.setenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR", "/tmp/ct2-model")
    monkeypatch.setenv("OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH", "/tmp/tokenizer.model")

    settings = AppSettings.from_env()

    assert settings.duplicate_box_iou_threshold == 0.88
    assert settings.duplicate_box_iom_threshold == 0.95
    assert settings.render_font_path == "/tmp/custom.ttf"
    assert settings.adjust_render_letter_spacing_for_overlap is False
    assert settings.ctranslate2_model_dir == "/tmp/ct2-model"
    assert settings.ctranslate2_tokenizer_path == "/tmp/tokenizer.model"


def test_app_settings_supports_legacy_overlap_threshold_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENPDF2ZH_DUPLICATE_BOX_IOM_THRESHOLD", raising=False)
    monkeypatch.delenv("OPENPDF2ZH_DUPLICATE_BOX_THRESHOLD", raising=False)
    monkeypatch.setenv("OPENPDF2ZH_BOX_OVERLAP_THRESHOLD", "0.93")

    settings = AppSettings.from_env()

    assert settings.duplicate_box_iom_threshold == 0.93


def test_app_settings_supports_legacy_duplicate_threshold_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENPDF2ZH_DUPLICATE_BOX_IOM_THRESHOLD", raising=False)
    monkeypatch.setenv("OPENPDF2ZH_DUPLICATE_BOX_THRESHOLD", "0.91")

    settings = AppSettings.from_env()

    assert settings.duplicate_box_iom_threshold == 0.91
