from pathlib import Path

from openpdf2zh.config import AppSettings
from openpdf2zh.ui import (
    _build_pdf_preview,
    _build_runtime_settings,
    _parse_ocr_langs,
    _serialize_ocr_langs,
)


def test_parse_ocr_langs_splits_comma_separated_values() -> None:
    assert _parse_ocr_langs("ko,en,zh") == ["ko", "en", "zh"]


def test_serialize_ocr_langs_joins_selected_values() -> None:
    assert _serialize_ocr_langs(["ko", "en", "zh"]) == "ko,en,zh"


def test_build_runtime_settings_keeps_render_font_only() -> None:
    settings = AppSettings()

    runtime_settings = _build_runtime_settings(
        settings,
        "ctranslate2",
        "/tmp/ct2-model",
        "/tmp/tokenizer.model",
        "/tmp/custom.ttf",
    )

    assert runtime_settings.render_font_path == "/tmp/custom.ttf"
    assert runtime_settings.ctranslate2_model_dir == "/tmp/ct2-model"
    assert runtime_settings.ctranslate2_tokenizer_path == "/tmp/tokenizer.model"


def test_build_runtime_settings_keeps_existing_render_font_when_no_upload() -> None:
    settings = AppSettings(render_font_path="/env/default.ttf")

    runtime_settings = _build_runtime_settings(
        settings,
        "openrouter",
        settings.ctranslate2_model_dir,
        settings.ctranslate2_tokenizer_path,
        None,
    )

    assert runtime_settings.render_font_path == "/env/default.ttf"


def test_build_pdf_preview_uses_gradio_file_route() -> None:
    preview = _build_pdf_preview(
        Path("/tmp/test file.pdf"),
        "empty message",
        "Preview title",
    )

    assert "/gradio_api/file=/tmp/test%20file.pdf" in preview
    assert "iframe" in preview


def test_build_pdf_preview_shows_empty_message() -> None:
    preview = _build_pdf_preview(None, "empty message", "Preview title")

    assert "empty message" in preview
