from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import gradio as gr
import pymupdf as fitz
import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.pipeline import PipelineRunner
from openpdf2zh.utils.files import start_workspace_cleanup_worker
from openpdf2zh.utils.job_limiter import JobLimiter, QueueBusyError

CSS = """
.gradio-container {zoom: 0.8;}
.app-shell {max-width: 1200px; margin: 0 auto 12px 0; text-align: left;}
.title-row {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.title-text {
  margin: 0;
  font-size: 2rem;
  font-weight: 700;
}
.bmc-slot {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1000;
}
.bmc-image {
  display: block;
  width: 260px;
  max-width: 30vw;
  height: auto;
}
.hint {color: #4b5563; font-size: 0.95rem;}
.control-panel {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 10px;
  background: #fff;
  margin-bottom: 8px;
  text-align: left;
  flex: 0 0 auto !important;
}
.control-panel * {
  text-align: left;
}
.preview-panel {
  border: 1px solid #d1d5db;
  border-radius: 12px;
  background: white;
  padding: 8px;
}
.pdf-preview-shell {
  width: 100%;
  min-height: 0;
  background: white;
  overflow: hidden;
}
.pdf-preview-viewport {
  width: 100%;
  aspect-ratio: 1 / 1.414;
  max-height: 960px;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  background: white;
}
.pdf-preview-image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.pdf-preview-empty {
  aspect-ratio: 1 / 1.414;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  text-align: center;
}
.preview-toolbar {
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}
.preview-status {
  margin: 0 !important;
  text-align: left;
}
.preview-nav-btn {
  min-width: 0 !important;
  padding: 5px 12px !important;
  font-size: 1.05rem !important;
}
.compact-action-stack {
  gap: 10px;
  width: 100%;
}
.compact-action-btn {
  width: 100% !important;
  min-width: 0 !important;
  padding: 12px 18px !important;
  font-size: 1rem !important;
  border-radius: 8px !important;
}
.stacked-note {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
}
"""

SOURCE_LANGUAGE_CHOICES = [
    "English",
    "Korean",
    "Japanese",
    "Simplified Chinese",
    "Traditional Chinese",
]

TARGET_LANGUAGE_CHOICES = [
    "Simplified Chinese",
    "Traditional Chinese",
    "English",
    "Japanese",
    "Korean",
]

CTRANSLATE2_TARGET_LANGUAGE_CHOICES = ["English", "Korean"]

MAX_INPUT_PDF_BYTES = 50 * 1024 * 1024

SECURITY_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

ADSENSE_HEAD = """
<script async src=\"https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-5911950308781579\"
     crossorigin=\"anonymous\"></script>
<meta name=\"google-adsense-account\" content=\"ca-pub-5911950308781579\">
"""

BMC_BUTTON_HTML = """
<div class="bmc-slot">
  <a href="https://buymeacoffee.com/choijjs83q" target="_blank" rel="noopener noreferrer" aria-label="Buy me a coffee">
    <img
      class="bmc-image"
      alt="Buy me a coffee"
      src="data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='720' height='200' viewBox='0 0 720 200'%3E%3Crect width='720' height='200' rx='26' fill='%23FFDD00'/%3E%3Cg fill='none' stroke='%231b1534' stroke-width='9' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M80 58c16-9 52-9 68 0'/%3E%3Cpath d='M72 76c18-8 68-8 86 0'/%3E%3Cpath d='M86 86h58l-10 80c-1 8-8 14-16 14H100c-8 0-15-6-16-14L74 86h12z'/%3E%3C/g%3E%3Cpath d='M96 98h36l-7 63c-.8 6-5.8 10-11.8 10h-6.4c-6 0-11-4-11.8-10L88 98h8z' fill='%23ffffff'/%3E%3Ctext x='188' y='126' font-size='74' font-family='Cookie, Brush Script MT, cursive' fill='%231b1534'%3EBuy me a coffee%3C/text%3E%3C/svg%3E"
    />
  </a>
</div>
"""

ADSENSE_ADS_TXT = "google.com, pub-5911950308781579, DIRECT, f08c47fec0942fa0\n"

ADSENSE_HEAD_STATIC = """
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-5911950308781579"
     crossorigin="anonymous"></script>
<meta name="google-adsense-account" content="ca-pub-5911950308781579">
"""


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


def _resolve_page_limit(page_mode: str) -> int | None:
    if page_mode == "all":
        return None
    if page_mode == "first20":
        return 20
    if page_mode == "first":
        return 1
    return None


def _clamp_preview_page(page_number: int, total_pages: int) -> int:
    if total_pages <= 0:
        return 1
    return min(max(int(page_number), 1), total_pages)


def _build_page_label(page_number: int, total_pages: int) -> str:
    if total_pages <= 0:
        return "Page: - / -"
    return f"Page: {_clamp_preview_page(page_number, total_pages)} / {total_pages}"


def _preview_cache_dir(pdf_path: Path) -> Path:
    cache_dir = pdf_path.parent / f".{pdf_path.stem}_preview"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _render_pdf_preview_page(
    pdf_path: Path,
    page_number: int,
) -> tuple[Path, int, int]:
    with fitz.open(pdf_path) as document:
        total_pages = len(document)
        current_page = _clamp_preview_page(page_number, total_pages)
        page = document.load_page(current_page - 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)

    image_path = _preview_cache_dir(pdf_path) / f"page-{current_page:04d}.png"
    if not image_path.exists():
        pixmap.save(image_path)
    return image_path, current_page, total_pages


def _build_pdf_preview(
    path: Path | None,
    empty_message: str,
    title: str,
    page_number: int = 1,
) -> str:
    if path is None:
        return (
            "<div class='pdf-preview-shell'>"
            f"<div class='pdf-preview-empty hint'>{empty_message}</div>"
            "</div>"
        )

    image_path, _, _ = _render_pdf_preview_page(path, page_number)
    image_url = f"/gradio_api/file={quote(str(image_path))}"
    return (
        "<div class='pdf-preview-shell'>"
        "<div class='pdf-preview-viewport'>"
        f"<img class='pdf-preview-image' src='{image_url}' alt='{title}' />"
        "</div>"
        "</div>"
    )


def _resolve_preview_state(
    preview_path: str | None,
    current_page: int,
    empty_message: str,
    title: str,
) -> tuple[str, int, str]:
    if not preview_path:
        return (
            _build_pdf_preview(None, empty_message, title),
            1,
            _build_page_label(0, 0),
        )

    pdf_path = Path(preview_path)
    image_path, resolved_page, total_pages = _render_pdf_preview_page(
        pdf_path, current_page
    )
    image_url = f"/gradio_api/file={quote(str(image_path))}"
    html = (
        "<div class='pdf-preview-shell'>"
        "<div class='pdf-preview-viewport'>"
        f"<img class='pdf-preview-image' src='{image_url}' alt='{title}' />"
        "</div>"
        "</div>"
    )
    return (
        html,
        resolved_page,
        _build_page_label(resolved_page, total_pages),
    )


def _change_preview_page(
    preview_path: str | None,
    current_page: int,
    delta: int,
    empty_message: str,
    title: str,
) -> tuple[str, int, str]:
    return _resolve_preview_state(
        preview_path,
        current_page + delta,
        empty_message,
        title,
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
    job_limiter = JobLimiter(
        max_concurrency=settings.job_queue_concurrency,
        max_waiting=settings.job_queue_max_size,
    )
    job_submission_limit = (
        settings.job_queue_concurrency + settings.job_queue_max_size + 2
    )
    provider_choices = [("CTranslate2", "ctranslate2")]
    provider_values = [value for _, value in provider_choices]
    default_provider = (
        settings.default_provider
        if settings.default_provider in provider_values
        else "ctranslate2"
    )

    def default_model_for_provider(selected_provider: str) -> str:
        if selected_provider == "ctranslate2":
            return "auto"
        return settings.default_model

    with gr.Blocks() as demo:
        with gr.Row(elem_classes=["app-shell", "title-row"]):
            gr.Markdown("<h1 class='title-text'>OpenPDF2ZH</h1>")
        with gr.Row(equal_height=False):
            with gr.Column(scale=4):
                input_pdf = gr.File(
                    label="Input PDF",
                    file_count="single",
                    file_types=[".pdf"],
                    type="filepath",
                )
                with gr.Column(elem_classes=["control-panel"]):
                    provider = gr.Dropdown(
                        label="Service",
                        choices=provider_choices,
                        value=default_provider,
                    )
                with gr.Column(elem_classes=["control-panel"]):
                    with gr.Row():
                        source_language = gr.Dropdown(
                            label="Translate from",
                            choices=SOURCE_LANGUAGE_CHOICES,
                            value="English",
                        )
                        target_language = gr.Dropdown(
                            label="Translate to",
                            choices=TARGET_LANGUAGE_CHOICES,
                            value=settings.default_target_language,
                        )
                with gr.Column(elem_classes=["control-panel"]):
                    page_mode = gr.Radio(
                        label="Pages",
                        choices=[
                            ("First", "first"),
                            ("First 20 pages", "first20"),
                            ("All", "all"),
                        ],
                        value="first",
                    )
                    gr.Markdown(
                        '<div class="hint">All 선택 시 PDF는 50MB를 초과할 수 없습니다.</div>'
                    )
                with gr.Accordion("Render options", open=False):
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
                with gr.Column(elem_classes=["compact-action-stack"]):
                    run_btn = gr.Button(
                        "Translate",
                        variant="primary",
                        min_width=0,
                        elem_classes=["compact-action-btn"],
                    )
                    clear_btn = gr.Button(
                        "Cancel",
                        min_width=0,
                        elem_classes=["compact-action-btn"],
                    )
                    gr.Markdown(
                        """
                        <div class='hint stacked-note'>
                          <div>Note: PDF documents composed only of images may not be recognized correctly.</div>
                          <div>주의: 이미지로만 구성된 PDF 문서는 제대로 인식되지 않을 수 있습니다.</div>
                        </div>
                        """
                    )
                    gr.HTML(BMC_BUTTON_HTML)

            with gr.Column(scale=6):
                translated_preview_path = gr.State(value=None)
                translated_preview_page = gr.State(value=1)
                detected_preview_path = gr.State(value=None)
                detected_preview_page = gr.State(value=1)
                with gr.Column(elem_classes=["preview-panel"]):
                    translated_pdf_preview = gr.HTML(
                        value=_build_pdf_preview(
                            None,
                            "Translated PDF preview will appear here.",
                            "Translated PDF preview",
                            1,
                        ),
                        container=False,
                        padding=False,
                        apply_default_css=False,
                    )
                    with gr.Row(elem_classes=["preview-toolbar"]):
                        translated_prev_page = gr.Button(
                            "←",
                            scale=0,
                            min_width=58,
                            elem_classes=["preview-nav-btn"],
                        )
                        translated_next_page = gr.Button(
                            "→",
                            scale=0,
                            min_width=58,
                            elem_classes=["preview-nav-btn"],
                        )
                        translated_page_label = gr.Markdown(
                            value=_build_page_label(0, 0),
                            elem_classes=["preview-status"],
                        )
                with gr.Accordion("Detected text boxes preview", open=False):
                    with gr.Column(elem_classes=["preview-panel"]):
                        detected_boxes_preview = gr.HTML(
                            value=_build_pdf_preview(
                                None,
                                "Detected text boxes preview will appear here.",
                                "Detected text boxes preview",
                                1,
                            ),
                            container=False,
                            padding=False,
                            apply_default_css=False,
                        )
                        with gr.Row(elem_classes=["preview-toolbar"]):
                            detected_prev_page = gr.Button(
                                "←",
                                scale=0,
                                min_width=58,
                                elem_classes=["preview-nav-btn"],
                            )
                            detected_next_page = gr.Button(
                                "→",
                                scale=0,
                                min_width=58,
                                elem_classes=["preview-nav-btn"],
                            )
                            detected_page_label = gr.Markdown(
                                value=_build_page_label(0, 0),
                                elem_classes=["preview-status"],
                            )
                with gr.Accordion("Generated files", open=False):
                    generated_files = gr.File(
                        label="Generated files",
                    )
                workspace_path = gr.State(value="")

        def run_job(
            input_pdf: str | None,
            source_language: str,
            target_language: str,
            provider: str,
            page_mode: str,
            render_font_file: str | None,
            adjust_render_letter_spacing_for_overlap: bool,
            progress: gr.Progress = gr.Progress(track_tqdm=False),
        ) -> tuple[list[str], str, str, int, str, str, str, int, str, str]:
            if not input_pdf:
                raise gr.Error("Please upload a PDF file first.")
            if Path(input_pdf).stat().st_size > MAX_INPUT_PDF_BYTES:
                raise gr.Error("PDF files up to 50MB are supported.")

            _ = source_language
            target_language = _normalize_target_language_for_provider(
                provider,
                target_language,
            )

            try:
                with job_limiter.acquire():
                    runner_settings = _build_runtime_settings(
                        settings,
                        provider,
                        settings.ctranslate2_model_dir,
                        settings.ctranslate2_tokenizer_path,
                        render_font_file,
                        adjust_render_letter_spacing_for_overlap,
                    )
                    runner = PipelineRunner(runner_settings)

                    request = PipelineRequest(
                        input_pdf=Path(input_pdf),
                        target_language=target_language,
                        provider=provider,
                        model=default_model_for_provider(provider),
                        page_limit=_resolve_page_limit(page_mode),
                        font_size=settings.base_font_size,
                    )
                    result = _run_pipeline_or_raise_gradio(
                        runner,
                        request,
                        progress=progress,
                    )
            except QueueBusyError as exc:
                raise gr.Error(str(exc)) from exc

            translated_preview = _resolve_preview_state(
                str(result.workspace.public_translated_pdf),
                1,
                "Translated PDF preview will appear here.",
                "Translated PDF preview",
            )
            detected_preview = _resolve_preview_state(
                str(result.workspace.public_detected_boxes_pdf),
                1,
                "Detected text boxes preview will appear here.",
                "Detected text boxes preview",
            )
            return (
                result.generated_files(),
                "",
                str(result.workspace.public_translated_pdf),
                translated_preview[1],
                translated_preview[2],
                translated_preview[0],
                str(result.workspace.public_detected_boxes_pdf),
                detected_preview[1],
                detected_preview[2],
                detected_preview[0],
            )

        def sync_provider_state(selected_provider: str, current_target_language: str):
            return _target_language_update_for_provider(
                selected_provider,
                current_target_language,
            )

        def reset_form() -> tuple[
            None,
            str,
            str,
            str,
            str,
            None,
            bool,
            None,
            str,
            None,
            int,
            str,
            str,
            None,
            int,
            str,
            str,
        ]:
            return (
                None,
                "English",
                settings.default_target_language,
                default_provider,
                "first",
                None,
                settings.adjust_render_letter_spacing_for_overlap,
                None,
                "",
                None,
                1,
                _build_page_label(0, 0),
                _build_pdf_preview(
                    None,
                    "Translated PDF preview will appear here.",
                    "Translated PDF preview",
                    1,
                ),
                None,
                1,
                _build_page_label(0, 0),
                _build_pdf_preview(
                    None,
                    "Detected text boxes preview will appear here.",
                    "Detected text boxes preview",
                    1,
                ),
            )

        def previous_translated_preview_page(
            preview_path: str | None,
            current_page: int,
        ) -> tuple[str, int, str]:
            return _change_preview_page(
                preview_path,
                current_page,
                -1,
                "Translated PDF preview will appear here.",
                "Translated PDF preview",
            )

        def next_translated_preview_page(
            preview_path: str | None,
            current_page: int,
        ) -> tuple[str, int, str]:
            return _change_preview_page(
                preview_path,
                current_page,
                1,
                "Translated PDF preview will appear here.",
                "Translated PDF preview",
            )

        def previous_detected_preview_page(
            preview_path: str | None,
            current_page: int,
        ) -> tuple[str, int, str]:
            return _change_preview_page(
                preview_path,
                current_page,
                -1,
                "Detected text boxes preview will appear here.",
                "Detected text boxes preview",
            )

        def next_detected_preview_page(
            preview_path: str | None,
            current_page: int,
        ) -> tuple[str, int, str]:
            return _change_preview_page(
                preview_path,
                current_page,
                1,
                "Detected text boxes preview will appear here.",
                "Detected text boxes preview",
            )

        provider.change(
            fn=sync_provider_state,
            inputs=[provider, target_language],
            outputs=[target_language],
            concurrency_limit=1,
        )

        run_btn.click(
            fn=run_job,
            inputs=[
                input_pdf,
                source_language,
                target_language,
                provider,
                page_mode,
                render_font_file,
                adjust_render_letter_spacing_for_overlap,
            ],
            outputs=[
                generated_files,
                workspace_path,
                translated_preview_path,
                translated_preview_page,
                translated_page_label,
                translated_pdf_preview,
                detected_preview_path,
                detected_preview_page,
                detected_page_label,
                detected_boxes_preview,
            ],
            concurrency_limit=job_submission_limit,
        )
        translated_prev_page.click(
            fn=previous_translated_preview_page,
            inputs=[translated_preview_path, translated_preview_page],
            outputs=[
                translated_pdf_preview,
                translated_preview_page,
                translated_page_label,
            ],
            concurrency_limit=1,
        )
        translated_next_page.click(
            fn=next_translated_preview_page,
            inputs=[translated_preview_path, translated_preview_page],
            outputs=[
                translated_pdf_preview,
                translated_preview_page,
                translated_page_label,
            ],
            concurrency_limit=1,
        )
        detected_prev_page.click(
            fn=previous_detected_preview_page,
            inputs=[detected_preview_path, detected_preview_page],
            outputs=[
                detected_boxes_preview,
                detected_preview_page,
                detected_page_label,
            ],
            concurrency_limit=1,
        )
        detected_next_page.click(
            fn=next_detected_preview_page,
            inputs=[detected_preview_path, detected_preview_page],
            outputs=[
                detected_boxes_preview,
                detected_preview_page,
                detected_page_label,
            ],
            concurrency_limit=1,
        )
        clear_btn.click(
            fn=reset_form,
            outputs=[
                input_pdf,
                source_language,
                target_language,
                provider,
                page_mode,
                render_font_file,
                adjust_render_letter_spacing_for_overlap,
                generated_files,
                workspace_path,
                translated_preview_path,
                translated_preview_page,
                translated_page_label,
                translated_pdf_preview,
                detected_preview_path,
                detected_preview_page,
                detected_page_label,
                detected_boxes_preview,
            ],
            concurrency_limit=1,
        )
    return demo


def _attach_adsense_route(app: FastAPI) -> None:
    @app.get("/ads.txt", include_in_schema=False)
    async def ads_txt() -> PlainTextResponse:
        return PlainTextResponse(ADSENSE_ADS_TXT)


def _attach_security_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if request.url.scheme == "https" or "https" in forwarded_proto.lower():
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


def launch() -> None:
    settings = AppSettings.from_env()
    start_workspace_cleanup_worker(
        settings.workspace_root,
        settings.workspace_retention_hours * 3600,
        settings.workspace_cleanup_interval_seconds,
    )
    demo = create_demo(settings)
    demo.queue(
        default_concurrency_limit=settings.job_queue_concurrency,
        max_size=(settings.job_queue_concurrency + settings.job_queue_max_size + 4),
    )
    app = FastAPI()
    _attach_adsense_route(app)
    _attach_security_middleware(app)
    app = gr.mount_gradio_app(
        app,
        demo,
        path="/",
        server_name=settings.host,
        server_port=settings.port,
        allowed_paths=[str(settings.public_root)],
        theme=gr.themes.Soft(),
        css=CSS,
        head=ADSENSE_HEAD_STATIC,
        max_file_size="50mb",
    )
    uvicorn.run(app, host=settings.host, port=settings.port)
