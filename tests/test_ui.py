from pathlib import Path

import fitz
import gradio as gr
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.ui import (
    _build_pdf_preview,
    _build_page_label,
    _build_runtime_settings,
    _change_preview_page,
    _normalize_target_language_for_provider,
    _resolve_page_limit,
    _run_pipeline_or_raise_gradio,
    _target_language_update_for_provider,
)


def _make_preview_pdf(path: Path, pages: int = 2) -> Path:
    document = fitz.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}")
        document.save(path)
    finally:
        document.close()
    return path


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
        "groq",
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
        "groq",
        settings.ctranslate2_model_dir,
        settings.ctranslate2_tokenizer_path,
        None,
        False,
    )

    assert runtime_settings.adjust_render_letter_spacing_for_overlap is False


def test_build_pdf_preview_uses_gradio_file_route(tmp_path: Path) -> None:
    pdf_path = _make_preview_pdf(tmp_path / "test file.pdf")
    preview = _build_pdf_preview(
        pdf_path,
        "empty message",
        "Preview title",
        1,
    )

    assert "/gradio_api/file=" in preview
    assert "img" in preview
    assert "page-0001.png" in preview


def test_build_pdf_preview_shows_empty_message() -> None:
    preview = _build_pdf_preview(None, "empty message", "Preview title")

    assert "empty message" in preview


def test_preview_page_label_and_rebuild(tmp_path: Path) -> None:
    pdf_path = _make_preview_pdf(tmp_path / "test.pdf", pages=3)

    assert _build_page_label(2, 3) == "Page: 2 / 3"

    preview, page, page_label = _change_preview_page(
        str(pdf_path),
        1,
        0,
        "empty",
        "Preview title",
    )

    assert page == 1
    assert page_label == "Page: 1 / 3"
    assert "page-0001.png" in preview


def test_change_preview_page_moves_one_page_at_a_time(tmp_path: Path) -> None:
    pdf_path = _make_preview_pdf(tmp_path / "test.pdf", pages=3)

    preview, page, page_label = _change_preview_page(
        str(pdf_path),
        1,
        1,
        "empty",
        "Preview title",
    )

    assert page == 2
    assert page_label == "Page: 2 / 3"
    assert "page-0002.png" in preview


def test_resolve_page_limit_maps_ui_modes() -> None:
    assert _resolve_page_limit("first") == 1
    assert _resolve_page_limit("first20") == 20
    assert _resolve_page_limit("all") is None
    assert _resolve_page_limit("unexpected") is None


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
