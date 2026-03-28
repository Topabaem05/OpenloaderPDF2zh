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
"""

TARGET_LANGUAGE_CHOICES = [
    "Simplified Chinese",
    "Traditional Chinese",
    "English",
    "Japanese",
    "Korean",
]

CTRANSLATE2_TARGET_LANGUAGE_CHOICES = ["English", "Korean"]

OCR_LANGUAGE_CHOICES = [
    ("Korean", "ko"),
    ("English", "en"),
    ("Chinese (Simplified)", "ch_sim"),
    ("Chinese (Traditional)", "ch_tra"),
    ("Japanese", "ja"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Italian", "it"),
]


def _parse_ocr_langs(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _serialize_ocr_langs(values: list[str]) -> str:
    return ",".join(value.strip() for value in values if value.strip())


def _build_runtime_settings(
    settings: AppSettings,
    provider: str,
    ctranslate2_model_dir: str,
    ctranslate2_tokenizer_path: str,
    render_font_file: str | None,
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
    )


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
            Simple Python-only PDF translation UI built with Gradio.

            **Flow:** Upload PDF → Parse → Translate → Re-render → Download artifacts
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
                force_ocr = gr.Checkbox(
                    label="Force OCR on hybrid backend",
                    value=False,
                )
                with gr.Accordion("OCR language options", open=False):
                    ocr_langs = gr.CheckboxGroup(
                        label="OCR languages",
                        choices=OCR_LANGUAGE_CHOICES,
                        value=_parse_ocr_langs(settings.default_ocr_langs),
                        show_select_all=True,
                        info="Select one or more OCR languages for scanned PDFs.",
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
                    gr.Markdown(
                        """
                        <div class="hint">
                        Drag and drop a TTF/TTC/OTF font file or click to choose one.
                        If left empty, the app uses the parsed source font family or the configured environment fallback.
                        </div>
                        """
                    )
                run_btn = gr.Button("Run translation", variant="primary")
                clear_btn = gr.Button("Reset")
                gr.Markdown(
                    """
                    <div class="hint">
                    Use <code>force OCR</code> for scanned or image-only PDFs.
                    Keep the model field editable so provider/model choices can change without code changes.
                    CTranslate2 uses either a local multilingual model plus tokenizer, or a directional quickmt model root with separate source and target tokenizers.
                    If a render font file is uploaded, translated text is rendered with that TTF/TTC/OTF resource.
                    </div>
                    """,
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
            force_ocr: bool,
            ocr_langs: list[str],
            ctranslate2_model_dir: str,
            ctranslate2_tokenizer_path: str,
            render_font_file: str | None,
            progress: gr.Progress = gr.Progress(track_tqdm=False),
        ) -> tuple[list[str], str, str, str]:
            if not input_pdf:
                raise gr.Error("Please upload a PDF file first.")
            if (
                provider == "ctranslate2"
                and target_language not in CTRANSLATE2_TARGET_LANGUAGE_CHOICES
            ):
                raise gr.Error(
                    "CTranslate2 currently supports only English and Korean targets in this local setup."
                )

            serialized_ocr_langs = _serialize_ocr_langs(ocr_langs)
            normalized_model = model.strip() or default_model_for_provider(provider)
            runner_settings = _build_runtime_settings(
                settings,
                provider,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
            )
            runner = PipelineRunner(runner_settings)

            request = PipelineRequest(
                input_pdf=Path(input_pdf),
                target_language=target_language,
                provider=provider,
                model=normalized_model,
                force_ocr=force_ocr,
                ocr_langs=serialized_ocr_langs,
                font_size=settings.base_font_size,
            )
            result = runner.run(request, progress=progress)
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

        def sync_model(selected_provider: str, current_model: str) -> str:
            return default_model_for_provider(selected_provider)

        def reset_form() -> tuple[
            None,
            str,
            str,
            str,
            bool,
            list[str],
            str,
            str,
            None,
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
                False,
                _parse_ocr_langs(settings.default_ocr_langs),
                settings.ctranslate2_model_dir,
                settings.ctranslate2_tokenizer_path,
                None,
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
            fn=sync_model,
            inputs=[provider, model],
            outputs=model,
            concurrency_limit=1,
        )

        run_btn.click(
            fn=run_job,
            inputs=[
                input_pdf,
                target_language,
                provider,
                model,
                force_ocr,
                ocr_langs,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
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
                force_ocr,
                ocr_langs,
                ctranslate2_model_dir,
                ctranslate2_tokenizer_path,
                render_font_file,
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
