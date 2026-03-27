from __future__ import annotations

from typing import Any

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
