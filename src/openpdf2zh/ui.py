from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.pipeline import PipelineRunner

CSS = """
.gradio-container {zoom: 0.8;}
.app-shell {max-width: 1200px; margin: 0 auto;}
.hint {color: #4b5563; font-size: 0.95rem;}
.pdf-preview-shell {
  width: 100%;
  min-height: 720px;
  border: 1px solid #d1d5db;
  border-radius: 12px;
  background: white;
  overflow: hidden;
}
.pdf-preview-shell iframe {
  width: 100%;
  height: 720px;
  border: 0;
  display: block;
  background: white;
}
.pdf-preview-empty {
  min-height: 720px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  text-align: center;
}
.compact-action-row {
  gap: 8px;
}
.compact-action-btn {
  min-width: 0 !important;
  padding: 6px 12px !important;
  font-size: 0.9rem !important;
}
"""

TARGET_LANGUAGE_CHOICES = [
    "Simplified Chinese",
    "Traditional Chinese",
    "English",
    "Japanese",
    "Korean",
]

CTRANSLATE2_TARGET_LANGUAGE_CHOICES = ["English", "Korean"]


def _build_runtime_settings(
    settings: AppSettings,
    provider: str,
    ctranslate2_model_dir: str,
    ctranslate2_tokenizer_path: str,
    render_font_file: str | None,
    adjust_render_letter_spacing_for_overlap: bool,
) -> AppSettings:
    return replace(
        settings,
        ctranslate2_model_dir=(
            ctranslate2_model_dir.strip()
            if provider == "ctranslate2"
            else settings.ctranslate2_model_dir
        ),
        ctranslate2_tokenizer_path=(
            ctranslate2_tokenizer_path.strip()
            if provider == "ctranslate2"
            else settings.ctranslate2_tokenizer_path
        ),
        render_font_path=(
            render_font_file.strip() if render_font_file else settings.render_font_path
        ),
        adjust_render_letter_spacing_for_overlap=(
            adjust_render_letter_spacing_for_overlap
        ),
    )


def _normalize_target_language_for_provider(
    provider: str,
    target_language: str,
) -> str:
    if provider == "ctranslate2":
        if target_language in CTRANSLATE2_TARGET_LANGUAGE_CHOICES:
            return target_language
        return "English"
    return target_language


def _target_language_update_for_provider(
    provider: str,
    target_language: str,
):
    normalized = _normalize_target_language_for_provider(provider, target_language)
    if provider == "ctranslate2":
        return gr.update(
            choices=CTRANSLATE2_TARGET_LANGUAGE_CHOICES,
            value=normalized,
        )
    return gr.update(choices=TARGET_LANGUAGE_CHOICES, value=normalized)


def _build_pdf_preview(path: Path | None, empty_message: str, title: str) -> str:
    if path is None:
        return (
            "<div class='pdf-preview-shell'>"
            f"<div class='pdf-preview-empty hint'>{empty_message}</div>"
            "</div>"
        )

    pdf_url = f"/gradio_api/file={quote(str(path))}"
    return (
        "<div class='pdf-preview-shell'>"
        f"<iframe src='{pdf_url}#toolbar=1&navpanes=0' title='{title}'></iframe>"
        "</div>"
    )


def _run_pipeline_or_raise_gradio(
    runner: PipelineRunner,
    request: PipelineRequest,
    progress: gr.Progress | None = None,
):
    try:
        return runner.run(request, progress=progress)
    except RuntimeError as exc:
        raise gr.Error(str(exc)) from exc


def create_demo(settings: AppSettings | None = None) -> gr.Blocks:
    settings = settings or AppSettings.from_env()
    provider_choices = ["openrouter", "ctranslate2"]
    default_provider = (
        settings.default_provider
        if settings.default_provider in provider_choices
        else "openrouter"
    )

    def default_model_for_provider(selected_provider: str) -> str:
        if selected_provider == "ctranslate2":
            return "auto"
        return settings.default_model

    with gr.Blocks() as demo:
        gr.Markdown(
            """
            # OpenPDF2ZH
            """,
            elem_classes=["app-shell"],
        )

        with gr.Row(equal_height=True):
            with gr.Column(scale=4):
                input_pdf = gr.File(
                    label="Input PDF",
                    file_count="single",
                    type="filepath",
                )
                target_language = gr.Dropdown(
                    label="Target language",
                    choices=TARGET_LANGUAGE_CHOICES,
                    value=settings.default_target_language,
                )
                provider = gr.Radio(
                    label="Translation provider",
                    choices=provider_choices,
                    value=default_provider,
                )
                model = gr.Textbox(
                    label="Model ID",
                    value=default_model_for_provider(default_provider),
                    placeholder="Example: nvidia/nemotron-3-super-120b-a12b:free or auto",
                )
                with gr.Accordion("Render options", open=False):
                    ctranslate2_model_dir = gr.Textbox(
                        label="CTranslate2 model directory",
                        value=settings.ctranslate2_model_dir,
                        placeholder="/absolute/path/to/ctranslate2_models or /absolute/path/to/ctranslate2_model",
                        info="Used only when the provider is CTranslate2. You can point this to a single multilingual model directory or a root folder containing quickmt-ko-en and quickmt-en-ko subdirectories.",
                    )
                    ctranslate2_tokenizer_path = gr.Textbox(
                        label="CTranslate2 tokenizer model",
                        value=settings.ctranslate2_tokenizer_path,
                        placeholder="/absolute/path/to/tokenizer.model",
                        info="SentencePiece tokenizer model used with single multilingual CTranslate2 models. Leave blank when using directional quickmt-ko-en and quickmt-en-ko subdirectories.",
                    )
                    render_font_file = gr.File(
                        label="Custom render font file (optional)",
                        file_count="single",
                        file_types=[".ttf", ".ttc", ".otf"],
                        type="filepath",
                        interactive=True,
                    )
                    adjust_render_letter_spacing_for_overlap = gr.Checkbox(
                        label="Tighten letter spacing when render boxes overlap",
                        value=settings.adjust_render_letter_spacing_for_overlap,
                        info="When nearby translated boxes overlap or nearly collide, compress letter spacing before shrinking the text.",
                    )
                    gr.Markdown(
                        """
                        <div class="hint">
                        Drag and drop a TTF/TTC/OTF font file or click to choose one.
                        If left empty, the app uses the parsed source font family or the configured environment fallback.
                        </div>
                        """
                    )
                with gr.Row(elem_classes=["compact-action-row"]):
                    run_btn = gr.Button(
                        "Run translation",
                        variant="primary",
                        scale=0,
                        min_width=140,
                        elem_classes=["compact-action-btn"],
                    )
                    clear_btn = gr.Button(
                        "Reset",
                        scale=0,
                        min_width=84,
                        elem_classes=["compact-action-btn"],
                    )
            with gr.Column(scale=6):
                translated_pdf_preview = gr.HTML(
                    value=_build_pdf_preview(
                        None,
                        "Translated PDF preview will appear here.",
                        "Translated PDF preview",
                    ),
                    container=False,
                    padding=False,
                    apply_default_css=False,
                )
                with gr.Accordion("Detected text boxes preview", open=False):
                    detected_boxes_preview = gr.HTML(
                        value=_build_pdf_preview(
                            None,
                            "Detected text boxes preview will appear here.",
                            "Detected text boxes preview",
                        ),
                        container=False,
                        padding=False,
                        apply_default_css=False,
                    )
                with gr.Accordion("Generated files", open=False):
                    generated_files = gr.File(
                        label="Generated files",
                    )
                workspace_path = gr.Textbox(
                    label="Workspace folder",
                    interactive=False,
                )

        def run_job(
            input_pdf: str | None,
            target_language: str,
            provider: str,
            model: str,
            ctranslate2_model_dir: str,
            ctranslate2_tokenizer_path: str,
            render_font_file: str | None,
            adjust_render_letter_spacing_for_overlap: bool,
            progress: gr.Progress = gr.Progress(track_tqdm=False),
        ) -> tuple[list[str], str, str, str]:
            if not input_pdf:
                raise gr.Error("Please upload a PDF file first.")

            target_language = _normalize_target_language_for_provider(
                provider,
                target_language,
            )

            normalized_model = model.strip() or default_model_for_provider(provider)
            runner_settings = _build_runtime_settings(
                settings,
                provider,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
                adjust_render_letter_spacing_for_overlap,
            )
            runner = PipelineRunner(runner_settings)

            request = PipelineRequest(
                input_pdf=Path(input_pdf),
                target_language=target_language,
                provider=provider,
                model=normalized_model,
                font_size=settings.base_font_size,
            )
            result = _run_pipeline_or_raise_gradio(
                runner,
                request,
                progress=progress,
            )
            return (
                result.generated_files(),
                str(result.workspace_dir),
                _build_pdf_preview(
                    result.workspace.translated_pdf,
                    "Translated PDF preview will appear here.",
                    "Translated PDF preview",
                ),
                _build_pdf_preview(
                    result.workspace.detected_boxes_pdf,
                    "Detected text boxes preview will appear here.",
                    "Detected text boxes preview",
                ),
            )

        def sync_provider_state(selected_provider: str, current_target_language: str):
            return (
                default_model_for_provider(selected_provider),
                _target_language_update_for_provider(
                    selected_provider,
                    current_target_language,
                ),
            )

        def reset_form() -> tuple[
            None,
            str,
            str,
            str,
            str,
            str,
            None,
            bool,
            None,
            str,
            str,
            str,
        ]:
            return (
                None,
                settings.default_target_language,
                default_provider,
                default_model_for_provider(default_provider),
                settings.ctranslate2_model_dir,
                settings.ctranslate2_tokenizer_path,
                None,
                settings.adjust_render_letter_spacing_for_overlap,
                None,
                "",
                _build_pdf_preview(
                    None,
                    "Translated PDF preview will appear here.",
                    "Translated PDF preview",
                ),
                _build_pdf_preview(
                    None,
                    "Detected text boxes preview will appear here.",
                    "Detected text boxes preview",
                ),
            )

        provider.change(
            fn=sync_provider_state,
            inputs=[provider, target_language],
            outputs=[model, target_language],
            concurrency_limit=1,
        )

        run_btn.click(
            fn=run_job,
            inputs=[
                input_pdf,
                target_language,
                provider,
                model,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
                adjust_render_letter_spacing_for_overlap,
            ],
            outputs=[
                generated_files,
                workspace_path,
                translated_pdf_preview,
                detected_boxes_preview,
            ],
            concurrency_limit=1,
        )
        clear_btn.click(
            fn=reset_form,
            outputs=[
                input_pdf,
                target_language,
                provider,
                model,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
                adjust_render_letter_spacing_for_overlap,
                generated_files,
                workspace_path,
                translated_pdf_preview,
                detected_boxes_preview,
            ],
            concurrency_limit=1,
        )
    return demo


def launch() -> None:
    settings = AppSettings.from_env()
    demo = create_demo(settings)
    demo.queue(default_concurrency_limit=1)
    demo.launch(
        server_name=settings.host,
        server_port=settings.port,
        allowed_paths=[str(settings.workspace_root)],
        theme=gr.themes.Soft(),
        css=CSS,
    )
