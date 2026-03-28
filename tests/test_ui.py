from pathlib import Path

import gradio as gr
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.ui import (
    _build_pdf_preview,
    _build_runtime_settings,
    _normalize_target_language_for_provider,
    _run_pipeline_or_raise_gradio,
    _target_language_update_for_provider,
)


def test_build_runtime_settings_keeps_render_font_only() -> None:
    settings = AppSettings()

    runtime_settings = _build_runtime_settings(
        settings,
        "ctranslate2",
        "/tmp/ct2-model",
        "/tmp/tokenizer.model",
        "/tmp/custom.ttf",
        False,
    )

    assert runtime_settings.render_font_path == "/tmp/custom.ttf"
    assert runtime_settings.adjust_render_letter_spacing_for_overlap is False
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
        settings.adjust_render_letter_spacing_for_overlap,
    )

    assert runtime_settings.render_font_path == "/env/default.ttf"


def test_build_runtime_settings_updates_overlap_spacing_toggle() -> None:
    settings = AppSettings(adjust_render_letter_spacing_for_overlap=True)

    runtime_settings = _build_runtime_settings(
        settings,
        "openrouter",
        settings.ctranslate2_model_dir,
        settings.ctranslate2_tokenizer_path,
        None,
        False,
    )

    assert runtime_settings.adjust_render_letter_spacing_for_overlap is False


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


def test_normalize_target_language_for_ctranslate2_falls_back_to_english() -> None:
    assert (
        _normalize_target_language_for_provider("ctranslate2", "Simplified Chinese")
        == "English"
    )
    assert _normalize_target_language_for_provider("ctranslate2", "Korean") == "Korean"


def test_target_language_update_for_ctranslate2_limits_choices() -> None:
    update = _target_language_update_for_provider("ctranslate2", "Simplified Chinese")

    assert update["value"] == "English"
    assert update["choices"] == ["English", "Korean"]


def test_run_pipeline_or_raise_gradio_surfaces_runtime_error() -> None:
    class _FakeRunner:
        def run(self, request, progress=None):
            raise RuntimeError("Provider is temporarily rate-limited")

    with pytest.raises(gr.Error, match="Provider is temporarily rate-limited"):
        _run_pipeline_or_raise_gradio(_FakeRunner(), object())
