from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest, PipelineResult
from openpdf2zh.services.parser_service import ParserService
from openpdf2zh.services.render_service import RenderService
from openpdf2zh.services.translation_service import TranslationService
from openpdf2zh.utils.files import append_run_log, prepare_workspace


class PipelineRunner:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.parser = ParserService(settings)
        self.translator = TranslationService(settings)
        self.renderer = RenderService(settings)

    def run(
        self, request: PipelineRequest, progress: Any | None = None
    ) -> PipelineResult:
        if progress is not None:
            progress(0.02, desc="Preparing workspace")

        workspace = prepare_workspace(self.settings.workspace_root, request.input_pdf)
        append_run_log(workspace.run_log, "pipeline=start")
        append_run_log(workspace.run_log, f"job_id={workspace.job_id}")
        append_run_log(workspace.run_log, f"input_pdf={workspace.input_pdf}")
        if request.page_limit is not None:
            applied_page_limit = self._limit_workspace_pdf_pages(
                workspace.input_pdf,
                request.page_limit,
            )
            append_run_log(
                workspace.run_log,
                f"page_limit={applied_page_limit}",
            )

        if progress is not None:
            progress(0.15, desc="Parsing PDF with OpenDataLoader")
        append_run_log(workspace.run_log, "phase=parse:start")
        self.parser.parse(request, workspace)
        append_run_log(workspace.run_log, "phase=parse:done")
        append_run_log(workspace.run_log, f"raw_json={workspace.raw_json}")
        append_run_log(workspace.run_log, f"raw_markdown={workspace.raw_markdown}")

        if progress is not None:
            progress(0.35, desc="Translating extracted text")
        append_run_log(workspace.run_log, "phase=translate:start")
        units = self.translator.translate_document(
            request, workspace, progress=progress
        )
        append_run_log(workspace.run_log, f"phase=translate:done units={len(units)}")
        append_run_log(workspace.run_log, f"translated_units={len(units)}")

        if progress is not None:
            progress(0.85, desc="Rendering translated PDF")
        append_run_log(workspace.run_log, "phase=render:start")
        overflow_count = self.renderer.render(request, workspace, progress=progress)
        append_run_log(
            workspace.run_log,
            f"phase=render:done overflow_count={overflow_count}",
        )
        append_run_log(workspace.run_log, f"overflow_count={overflow_count}")
        append_run_log(workspace.run_log, f"translated_pdf={workspace.translated_pdf}")
        append_run_log(
            workspace.run_log, f"structured_json={workspace.structured_json}"
        )
        append_run_log(
            workspace.run_log,
            f"translated_markdown={workspace.translated_markdown}",
        )
        append_run_log(workspace.run_log, "pipeline=done")

        if progress is not None:
            progress(1.0, desc="Done")

        summary = "\n".join(
            [
                "## Translation completed",
                "",
                f"- **Job ID:** `{workspace.job_id}`",
                f"- **Provider:** `{request.provider}`",
                f"- **Model:** `{request.model}`",
                f"- **Target language:** {request.target_language}",
                f"- **Translated blocks:** {len(units)}",
                f"- **Overflow warnings:** {overflow_count}",
                f"- **Workspace:** `{workspace.root}`",
            ]
        )
        return PipelineResult(
            workspace=workspace,
            translated_unit_count=len(units),
            overflow_count=overflow_count,
            provider=request.provider,
            model=request.model,
            target_language=request.target_language,
            summary_markdown=summary,
        )

    def _limit_workspace_pdf_pages(self, pdf_path: Path, page_limit: int) -> int:
        if page_limit <= 0:
            return 0

        source = fitz.open(pdf_path)
        try:
            total_pages = len(source)
            applied_page_limit = min(page_limit, total_pages)
            if applied_page_limit >= total_pages:
                return applied_page_limit

            trimmed = fitz.open()
            try:
                trimmed.insert_pdf(source, from_page=0, to_page=applied_page_limit - 1)
                trimmed_path = pdf_path.with_name(f"{pdf_path.stem}-trimmed.pdf")
                trimmed.save(trimmed_path)
            finally:
                trimmed.close()
            trimmed_path.replace(pdf_path)
            return applied_page_limit
        finally:
            source.close()
