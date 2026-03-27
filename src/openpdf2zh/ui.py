from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import gradio as gr

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.pipeline import PipelineRunner

CSS = """
.gradio-container {zoom: 0.8;}
.app-shell {max-width: 1200px; margin: 0 auto;}
.hint {color: #4b5563; font-size: 0.95rem;}
"""

TARGET_LANGUAGE_CHOICES = [
    "Simplified Chinese",
    "Traditional Chinese",
    "English",
    "Japanese",
    "Korean",
]

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
    libretranslate_url: str,
    libretranslate_api_key: str,
) -> AppSettings:
    if provider != "libretranslate":
        return settings

    normalized_url = libretranslate_url.strip().rstrip("/")
    if not normalized_url:
        raise gr.Error("Please enter a LibreTranslate server URL.")

    return replace(
        settings,
        libretranslate_url=normalized_url,
        libretranslate_api_key=libretranslate_api_key.strip(),
    )


def create_demo(settings: AppSettings | None = None) -> gr.Blocks:
    settings = settings or AppSettings.from_env()

    def default_model_for_provider(selected_provider: str) -> str:
        if selected_provider == "libretranslate":
            return "libretranslate"
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
                    choices=["openrouter", "groq", "libretranslate"],
                    value=settings.default_provider,
                )
                model = gr.Textbox(
                    label="Model ID",
                    value=default_model_for_provider(settings.default_provider),
                    placeholder="Example: openrouter/auto or libretranslate",
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
                with gr.Accordion("LibreTranslate server", open=False):
                    libretranslate_url = gr.Textbox(
                        label="LibreTranslate base URL",
                        value=settings.libretranslate_url,
                        placeholder="http://127.0.0.1:5000",
                        info="Used only when the provider is LibreTranslate. Self-hosted instances usually do not require an API key.",
                    )
                    libretranslate_api_key = gr.Textbox(
                        label="LibreTranslate API key (optional)",
                        value=settings.libretranslate_api_key,
                        type="password",
                        info="Leave blank for self-hosted LibreTranslate servers unless you configured API keys.",
                    )
                run_btn = gr.Button("Run translation", variant="primary")
                clear_btn = gr.Button("Reset")
                gr.Markdown(
                    """
                    <div class="hint">
                    Use <code>force OCR</code> for scanned or image-only PDFs.
                    Keep the model field editable so provider/model choices can change without code changes.
                    LibreTranslate ignores the model ID and uses the server URL configured below.
                    </div>
                    """,
                )

            with gr.Column(scale=6):
                summary = gr.Markdown(
                    "Upload a PDF and click **Run translation**.",
                    label="Run summary",
                )
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
            libretranslate_url: str,
            libretranslate_api_key: str,
            progress: gr.Progress = gr.Progress(track_tqdm=False),
        ) -> tuple[str, list[str], str]:
            if not input_pdf:
                raise gr.Error("Please upload a PDF file first.")

            serialized_ocr_langs = _serialize_ocr_langs(ocr_langs)
            normalized_model = model.strip() or default_model_for_provider(provider)
            runner_settings = _build_runtime_settings(
                settings,
                provider,
                libretranslate_url,
                libretranslate_api_key,
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
                result.summary_markdown,
                result.generated_files(),
                str(result.workspace_dir),
            )

        def sync_model(selected_provider: str, current_model: str) -> str:
            if selected_provider == "libretranslate":
                return "libretranslate"
            if current_model.strip() == "libretranslate":
                return default_model_for_provider(selected_provider)
            return current_model

        def reset_form() -> tuple[
            None,
            str,
            str,
            str,
            bool,
            list[str],
            str,
            str,
            str,
            None,
            str,
        ]:
            return (
                None,
                settings.default_target_language,
                settings.default_provider,
                default_model_for_provider(settings.default_provider),
                False,
                _parse_ocr_langs(settings.default_ocr_langs),
                settings.libretranslate_url,
                settings.libretranslate_api_key,
                "Upload a PDF and click **Run translation**.",
                None,
                "",
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
                libretranslate_url,
                libretranslate_api_key,
            ],
            outputs=[summary, generated_files, workspace_path],
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
                libretranslate_url,
                libretranslate_api_key,
                summary,
                generated_files,
                workspace_path,
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
        theme=gr.themes.Soft(),
        css=CSS,
    )
