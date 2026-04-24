from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
import shutil
import threading
import warnings

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import gradio as gr

from openpdf2zh.config import (
    AppSettings,
    OPENROUTER_FIXED_MODEL,
    OPENROUTER_PROVIDER,
    normalize_provider,
)
from openpdf2zh.models import PipelineRequest
from openpdf2zh.pipeline import PipelineRunner
from openpdf2zh.services.usage_quota import QuotaExceededError, UsageQuotaService
from openpdf2zh.ui import (
    ADSENSE_HEAD_STATIC,
    BMC_IMAGE_PATH,
    CSS,
    MAX_INPUT_PDF_BYTES,
    _attach_adsense_route,
    _attach_security_middleware,
    _is_local_client_ip,
    create_demo,
)
from openpdf2zh.utils.files import make_job_id
from openpdf2zh.utils.job_limiter import JobLimiter, QueueBusyError

CTRANSLATE2_TARGET_LANGUAGE_CHOICES = {"English", "Korean"}
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PARSING = "parsing"
JOB_STATUS_TRANSLATING = "translating"
JOB_STATUS_RENDERING = "rendering"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_QUOTA_EXCEEDED = "quota_exceeded"
JOB_STATUS_QUEUE_BUSY = "queue_busy"


@dataclass(slots=True)
class JobRecord:
    job_id: str
    filename: str
    status: str
    stage: str
    progress: float
    message_ko: str
    message_en: str
    warnings: list[str]
    artifacts: dict[str, str]
    queue_snapshot: dict[str, int]
    provider: str
    target_language: str
    page_mode: str
    created_at: str
    updated_at: str
    started_at: str = ""
    finished_at: str = ""

    def to_response(self) -> dict[str, object]:
        return asdict(self)


class ApiProgressReporter:
    def __init__(self, manager: "JobManager", job_id: str) -> None:
        self.manager = manager
        self.job_id = job_id

    def __call__(self, value: float, desc: str | None = None) -> None:
        desc = (desc or "").strip()
        stage = self._stage_from_desc(desc)
        self.manager.update_progress(self.job_id, stage, value, desc)

    @staticmethod
    def _stage_from_desc(desc: str) -> str:
        normalized = desc.lower()
        if "translat" in normalized:
            return JOB_STATUS_TRANSLATING
        if "render" in normalized:
            return JOB_STATUS_RENDERING
        return JOB_STATUS_PARSING


class JobManager:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.job_limiter = JobLimiter(
            max_concurrency=settings.job_queue_concurrency,
            max_waiting=settings.job_queue_max_size,
        )
        self.quota_service = (
            UsageQuotaService(
                settings.rate_limit_storage_path,
                daily_limit_seconds=settings.rate_limit_daily_seconds,
                timezone_name=settings.rate_limit_timezone,
            )
            if settings.rate_limit_enabled
            else None
        )
        self._records: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    async def submit_job(
        self,
        upload: UploadFile,
        *,
        provider: str,
        target_language: str,
        page_mode: str,
        render_layout_engine: str,
        adjust_render_letter_spacing_for_overlap: bool,
        openrouter_api_key: str,
        render_font_file: UploadFile | None,
        client_ip: str,
    ) -> dict[str, object]:
        filename = Path(upload.filename or "document.pdf").name
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Please upload a PDF file.")

        job_id = make_job_id(Path(filename).stem)
        incoming_dir = (self.settings.workspace_root / "_incoming").resolve()
        incoming_dir.mkdir(parents=True, exist_ok=True)
        input_path = incoming_dir / f"{job_id}-{filename}"
        input_size = await self._save_upload(upload, input_path)
        if input_size > MAX_INPUT_PDF_BYTES:
            input_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="PDF files up to 50MB are supported.")

        render_font_path = ""
        if render_font_file is not None and render_font_file.filename:
            font_name = Path(render_font_file.filename).name
            render_font_path = str(incoming_dir / f"{job_id}-{font_name}")
            await self._save_upload(render_font_file, Path(render_font_path))

        normalized_provider = normalize_provider(provider) or "ctranslate2"
        if normalized_provider == OPENROUTER_PROVIDER and not openrouter_api_key.strip():
            input_path.unlink(missing_ok=True)
            if render_font_path:
                Path(render_font_path).unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
        normalized_target = self._normalize_target_language(
            normalized_provider,
            target_language,
        )
        created_at = self._now_iso()
        record = JobRecord(
            job_id=job_id,
            filename=filename,
            status=JOB_STATUS_QUEUED,
            stage=JOB_STATUS_QUEUED,
            progress=0.0,
            message_ko="대기열에 등록했어요. 곧 작업을 시작할게요.",
            message_en="The job is queued. Processing will start shortly.",
            warnings=[],
            artifacts={},
            queue_snapshot=self._queue_snapshot(),
            provider=normalized_provider,
            target_language=normalized_target,
            page_mode=page_mode,
            created_at=created_at,
            updated_at=created_at,
        )
        with self._lock:
            self._records[job_id] = record

        self._start_job_thread(
            job_id=job_id,
            input_path=input_path,
            provider=normalized_provider,
            target_language=normalized_target,
            page_mode=page_mode,
            render_layout_engine=render_layout_engine,
            adjust_render_letter_spacing_for_overlap=adjust_render_letter_spacing_for_overlap,
            openrouter_api_key=openrouter_api_key.strip(),
            render_font_path=render_font_path,
            client_ip=client_ip,
        )
        return record.to_response()

    def get_job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise KeyError(job_id)
            record.queue_snapshot = self._queue_snapshot()
            record.updated_at = self._now_iso()
            return record.to_response()

    def update_progress(self, job_id: str, stage: str, progress: float, detail: str) -> None:
        with self._lock:
            record = self._records[job_id]
            record.status = stage
            record.stage = stage
            record.progress = max(0.0, min(float(progress), 1.0))
            record.message_ko, record.message_en = self._messages_for_stage(stage, detail)
            if not record.started_at:
                record.started_at = self._now_iso()
            record.updated_at = self._now_iso()
            record.queue_snapshot = self._queue_snapshot()

    def _start_job_thread(self, **kwargs: object) -> None:
        worker = threading.Thread(
            target=self._run_job,
            kwargs=kwargs,
            name=f"job-{kwargs['job_id']}",
            daemon=True,
        )
        worker.start()

    def _run_job(
        self,
        *,
        job_id: str,
        input_path: Path,
        provider: str,
        target_language: str,
        page_mode: str,
        render_layout_engine: str,
        adjust_render_letter_spacing_for_overlap: bool,
        openrouter_api_key: str,
        render_font_path: str,
        client_ip: str,
    ) -> None:
        reporter = ApiProgressReporter(self, job_id)
        quota_service = self.quota_service
        quota_guard = None

        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                with self.job_limiter.acquire():
                    runner_settings = self._build_runtime_settings(
                        provider=provider,
                        render_font_path=render_font_path,
                        adjust_render_letter_spacing_for_overlap=(
                            adjust_render_letter_spacing_for_overlap
                        ),
                        render_layout_engine=render_layout_engine,
                    )
                    runner = PipelineRunner(runner_settings)
                    request = PipelineRequest(
                        input_pdf=input_path,
                        target_language=target_language,
                        provider=provider,
                        model=self._model_for_provider(provider),
                        job_id=job_id,
                        provider_api_key=openrouter_api_key if provider == OPENROUTER_PROVIDER else "",
                        client_ip=client_ip,
                        page_limit=self._resolve_page_limit(page_mode),
                        font_size=self.settings.base_font_size,
                    )
                    if quota_service is not None and self._should_enforce_rate_limit(client_ip):
                        quota_guard = quota_service.acquire(client_ip)
                    if quota_guard is None:
                        result = runner.run(request, progress=reporter)
                    else:
                        with quota_guard:
                            result = runner.run(request, progress=reporter, quota_guard=quota_guard)

                warning_messages = [
                    str(item.message)
                    for item in caught_warnings
                    if str(item.message).strip()
                ]
                if result.overflow_count > 0:
                    warning_messages.append(
                        f"Rendered with {result.overflow_count} overflow warning(s)."
                    )
                public_structured_json = result.workspace.public_dir / "structured.json"
                public_result_md = result.workspace.public_dir / "result.md"
                if result.workspace.structured_json.exists():
                    shutil.copy2(result.workspace.structured_json, public_structured_json)
                if result.workspace.translated_markdown.exists():
                    shutil.copy2(result.workspace.translated_markdown, public_result_md)
                artifacts = {
                    "translated_pdf": f"/files/{job_id}/translated_mono.pdf",
                    "detected_boxes_pdf": f"/files/{job_id}/detected_boxes.pdf",
                    "structured_json": f"/files/{job_id}/structured.json",
                    "result_md": f"/files/{job_id}/result.md",
                }
                with self._lock:
                    record = self._records[job_id]
                    record.status = JOB_STATUS_SUCCEEDED
                    record.stage = JOB_STATUS_SUCCEEDED
                    record.progress = 1.0
                    record.message_ko = "번역이 완료되었어요. 결과를 바로 검토할 수 있어요."
                    record.message_en = "Translation completed. You can review the results now."
                    record.warnings = warning_messages
                    record.artifacts = artifacts
                    record.updated_at = self._now_iso()
                    record.finished_at = self._now_iso()
                    record.queue_snapshot = self._queue_snapshot()
        except QueueBusyError as exc:
            self._mark_failed(job_id, JOB_STATUS_QUEUE_BUSY, str(exc))
        except QuotaExceededError as exc:
            self._mark_failed(job_id, JOB_STATUS_QUOTA_EXCEEDED, str(exc))
        except Exception as exc:
            self._mark_failed(job_id, JOB_STATUS_FAILED, str(exc))
        finally:
            input_path.unlink(missing_ok=True)
            if render_font_path:
                Path(render_font_path).unlink(missing_ok=True)

    def _mark_failed(self, job_id: str, status: str, detail: str) -> None:
        message_ko, message_en = self._messages_for_terminal_status(status, detail)
        with self._lock:
            record = self._records[job_id]
            record.status = status
            record.stage = status
            record.message_ko = message_ko
            record.message_en = message_en
            record.updated_at = self._now_iso()
            record.finished_at = self._now_iso()
            record.queue_snapshot = self._queue_snapshot()

    def _queue_snapshot(self) -> dict[str, int]:
        active, waiting = self.job_limiter.snapshot()
        return {
            "active": active,
            "waiting": waiting,
            "capacity": self.settings.job_queue_concurrency + self.settings.job_queue_max_size,
        }

    def _messages_for_stage(self, stage: str, detail: str) -> tuple[str, str]:
        if stage == JOB_STATUS_TRANSLATING:
            return (
                "텍스트를 번역하고 있어요. 문서 길이에 따라 시간이 조금 걸릴 수 있어요.",
                "Translating text. This can take a moment for longer documents.",
            )
        if stage == JOB_STATUS_RENDERING:
            return (
                "번역본 PDF를 다시 조립하고 있어요.",
                "Rendering the translated PDF.",
            )
        if stage == JOB_STATUS_PARSING:
            return (
                "문서를 분석하고 구조를 읽고 있어요.",
                "Parsing the document and reading its structure.",
            )
        return (
            f"작업을 준비하고 있어요. {detail}".strip(),
            f"Preparing the job. {detail}".strip(),
        )

    def _messages_for_terminal_status(self, status: str, detail: str) -> tuple[str, str]:
        if status == JOB_STATUS_QUEUE_BUSY:
            return (
                "서버 작업량이 많아요. 잠시 후 다시 시도해 주세요.",
                "The server is busy. Please try again shortly.",
            )
        if status == JOB_STATUS_QUOTA_EXCEEDED:
            return (
                "오늘 사용 가능한 실행 시간을 모두 사용했어요. 초기화 시점을 확인해 주세요.",
                "The daily runtime quota has been exhausted. Check the reset time and try again later.",
            )
        if "OpenRouter API key is required" in detail:
            return (
                "OpenRouter 키가 필요해요. 키를 입력한 뒤 다시 시도해 주세요.",
                "An OpenRouter API key is required. Add the key and try again.",
            )
        return (
            f"작업을 완료하지 못했어요. {detail}".strip(),
            f"The job could not be completed. {detail}".strip(),
        )

    def _should_enforce_rate_limit(self, client_ip: str) -> bool:
        return self.settings.rate_limit_enabled and not _is_local_client_ip(client_ip)

    def _resolve_page_limit(self, page_mode: str) -> int | None:
        if page_mode == "all":
            return None
        if page_mode == "first20":
            return 20
        return 1

    def _normalize_target_language(self, provider: str, target_language: str) -> str:
        if provider == "ctranslate2" and target_language not in CTRANSLATE2_TARGET_LANGUAGE_CHOICES:
            return "English"
        return target_language

    def _model_for_provider(self, provider: str) -> str:
        if provider == OPENROUTER_PROVIDER:
            return OPENROUTER_FIXED_MODEL
        if provider == "ctranslate2":
            return "auto"
        return self.settings.default_model

    def _build_runtime_settings(
        self,
        *,
        provider: str,
        render_font_path: str,
        adjust_render_letter_spacing_for_overlap: bool,
        render_layout_engine: str,
    ) -> AppSettings:
        return replace(
            self.settings,
            render_font_path=render_font_path.strip() if render_font_path else self.settings.render_font_path,
            adjust_render_letter_spacing_for_overlap=adjust_render_letter_spacing_for_overlap,
            render_layout_engine=(
                render_layout_engine
                if render_layout_engine in {"legacy", "pretext"}
                else self.settings.render_layout_engine
            ),
            ctranslate2_model_dir=self.settings.ctranslate2_model_dir,
            ctranslate2_tokenizer_path=self.settings.ctranslate2_tokenizer_path,
        )

    async def _save_upload(self, upload: UploadFile, target_path: Path) -> int:
        size = 0
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_INPUT_PDF_BYTES and target_path.suffix.lower() == ".pdf":
                    handle.write(chunk)
                    break
                handle.write(chunk)
        await upload.close()
        return size

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_env()
    settings.public_root.mkdir(parents=True, exist_ok=True)
    manager = JobManager(settings)
    app = FastAPI()
    app.state.job_manager = manager
    _attach_adsense_route(app)
    _attach_security_middleware(app)
    app.mount("/files", StaticFiles(directory=settings.public_root), name="files")

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        request: Request,
        file: UploadFile = File(...),
        provider: str = Form("ctranslate2"),
        target_language: str = Form("English"),
        page_mode: str = Form("first"),
        render_layout_engine: str = Form("legacy"),
        adjust_render_letter_spacing_for_overlap: bool = Form(True),
        openrouter_api_key: str = Form(""),
        render_font_file: UploadFile | None = File(None),
    ) -> dict[str, object]:
        client_ip = _resolve_client_ip(request, settings)
        return await manager.submit_job(
            file,
            provider=provider,
            target_language=target_language,
            page_mode=page_mode,
            render_layout_engine=render_layout_engine,
            adjust_render_letter_spacing_for_overlap=adjust_render_letter_spacing_for_overlap,
            openrouter_api_key=openrouter_api_key,
            render_font_file=render_font_file,
            client_ip=client_ip,
        )

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        try:
            return manager.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    demo = create_demo(settings)
    demo.queue(
        default_concurrency_limit=settings.job_queue_concurrency,
        max_size=(settings.job_queue_concurrency + settings.job_queue_max_size + 4),
    )
    app = gr.mount_gradio_app(
        app,
        demo,
        path="/gradio",
        server_name=settings.host,
        server_port=settings.port,
        allowed_paths=[str(settings.public_root), str(BMC_IMAGE_PATH)],
        theme=gr.themes.Soft(),
        css=CSS,
        head=ADSENSE_HEAD_STATIC,
        max_file_size="50mb",
    )

    frontend_dist = (
        Path(__file__).resolve().parents[2] / "apps" / "web" / "workbench" / "dist"
    ).resolve()
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False, response_model=None)
    def frontend_index():
        return _frontend_index_response(frontend_dist)

    @app.get("/gradio", include_in_schema=False, response_model=None)
    def gradio_root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/gradio/", status_code=307)

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def frontend_routes(path: str):
        if path == "gradio" or path.startswith(("api/", "files/", "gradio/", "assets/")):
            raise HTTPException(status_code=404, detail="Not found.")
        return _frontend_index_response(frontend_dist)

    return app


def _frontend_index_response(frontend_dist: Path) -> HTMLResponse | FileResponse:
    index_path = frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>OpenPDF2ZH</title>
          </head>
          <body style="font-family: system-ui, sans-serif; padding: 32px; background: #f5f3ef;">
            <h1>OpenPDF2ZH frontend build is missing.</h1>
            <p>Run <code>npm --prefix apps/web/workbench install</code> and <code>npm --prefix apps/web/workbench run build</code>.</p>
            <p><a href="/gradio">Open fallback Gradio UI</a></p>
          </body>
        </html>
        """
    )


def _resolve_client_ip(request: Request, settings: AppSettings) -> str:
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        for candidate in forwarded.split(","):
            normalized = candidate.strip()
            if normalized:
                return normalized
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    client = request.client
    return str(getattr(client, "host", "") or "").strip()
