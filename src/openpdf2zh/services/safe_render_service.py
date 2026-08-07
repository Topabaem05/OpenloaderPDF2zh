from __future__ import annotations

import json
import shutil
from typing import Any

import pymupdf as fitz

from openpdf2zh.document.ir import DocumentIR, DocumentRun, TextStyle
from openpdf2zh.document.serialization import read_document_ir
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.layout_planner import build_column_clusters
from openpdf2zh.services.redaction_service import RedactionResult, RedactionService
from openpdf2zh.services.render_service import RenderBlockPlan, RenderService
from openpdf2zh.services.usage_quota import QuotaLease
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class SafeRenderService(RenderService):
    """Render translated text while redacting only native translatable text runs."""

    MIN_RUN_BLOCK_COVERAGE = 0.5

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.redaction_service = RedactionService()

    def render(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
        quota_guard: QuotaLease | None = None,
    ) -> int:
        payload = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
        document_ir = self._load_document_ir(workspace)
        doc = fitz.open(str(workspace.input_pdf))
        try:
            overflow: list[dict[str, object]] = []
            layout_plan: list[dict[str, object]] = []
            layout_engine = self._resolve_layout_engine()
            page_bundles = payload.get("pages", [])
            total_pages = len(page_bundles)
            render_css, render_archive, render_font_family = self._build_render_resources()
            redaction_totals = RedactionResult(0, 0, 0)
            append_run_log(
                workspace.run_log,
                f"render=pages total={total_pages} layout_engine={layout_engine}",
            )
            current_state = {
                "page": 0,
                "total": total_pages,
                "planned": 0,
                "overflow": 0,
            }

            def heartbeat_context() -> str:
                return (
                    f"current={current_state['page']}/{current_state['total']} "
                    f"planned={current_state['planned']} overflow={current_state['overflow']}"
                )

            with run_log_heartbeat(
                workspace.run_log,
                "render",
                context_provider=heartbeat_context,
            ):
                for page_index_1based, page_bundle in enumerate(page_bundles, start=1):
                    self._check_quota(quota_guard)
                    current_state["page"] = page_index_1based
                    if progress is not None:
                        progress(
                            0.85 + (0.13 * page_index_1based / max(total_pages, 1)),
                            desc=f"Rendering page {page_index_1based}/{total_pages}",
                        )
                    page_index = int(page_bundle["page"]) - 1
                    if page_index < 0 or page_index >= len(doc):
                        continue
                    page = doc[page_index]
                    elements = sorted(
                        page_bundle.get("elements", []),
                        key=lambda element: self._element_sort_key(element),
                    )
                    planned_elements: list[dict[str, object]] = []
                    planned: list[
                        tuple[
                            fitz.Rect,
                            str,
                            str,
                            float,
                            str,
                            int,
                            float | None,
                            float | None,
                            str,
                        ]
                    ] = []
                    for element in elements:
                        translated = str(element.get("translated", "")).strip()
                        bbox = element.get("bbox") or []
                        label = str(element.get("label", "text"))
                        if not translated or len(bbox) != 4:
                            continue
                        rect = self._pdf_bbox_to_rect(page, bbox)
                        font_size = self._resolve_font_size(element, request.font_size)
                        font_name = str(element.get("font_name", "")).strip()
                        estimated_line_count = self._resolve_estimated_line_count(element)
                        line_height_pt = self._resolve_line_height_pt(element, font_size)
                        letter_spacing_em = self._resolve_letter_spacing_em(element)
                        toc_page_number = str(element.get("toc_page_number", "")).strip()
                        planned_elements.append(element)
                        planned.append(
                            (
                                rect,
                                translated,
                                label,
                                font_size,
                                font_name,
                                estimated_line_count,
                                line_height_pt,
                                letter_spacing_em,
                                toc_page_number,
                            )
                        )

                    planned = self._apply_overlap_aware_letter_spacing(planned)
                    planned_blocks = self._plan_render_blocks(
                        planned,
                        layout_engine,
                        self._resolve_page_rect(page, planned),
                        render_font_family,
                        render_css,
                        render_archive,
                    )
                    element_by_block_id = {
                        f"b{index:04d}": element
                        for index, element in enumerate(planned_elements, start=1)
                    }
                    column_blocks_by_id = {
                        cluster_block.block_id: cluster
                        for cluster in build_column_clusters(
                            planned_blocks,
                            rect_getter=lambda block: block.planned_rect,
                        )
                        for cluster_block in cluster
                    }

                    current_state["planned"] = len(planned_blocks)
                    renderable_blocks = [
                        block for block in planned_blocks if block.render_allowed
                    ]
                    page_runs = self._redaction_runs_for_blocks(
                        page_index + 1,
                        renderable_blocks,
                        document_ir,
                    )
                    page_redaction = self.redaction_service.redact_runs(page, page_runs)
                    redaction_totals = RedactionResult(
                        redaction_totals.redacted_run_count
                        + page_redaction.redacted_run_count,
                        redaction_totals.skipped_protected_count
                        + page_redaction.skipped_protected_count,
                        redaction_totals.restored_link_count
                        + page_redaction.restored_link_count,
                    )

                    for block in planned_blocks:
                        self._check_quota(quota_guard)
                        if (
                            block.layout_engine == "pretext"
                            and block.actual_render_bbox is not None
                        ):
                            append_run_log(
                                workspace.run_log,
                                "render=probe_summary "
                                f"page={page_index + 1} block_id={block.block_id} "
                                f"pretext_height_pt={round(block.planned_height_pt, 3)} "
                                f"probe_bbox={self._rect_to_bbox(block.actual_render_bbox)}",
                            )

                        if not block.render_allowed:
                            layout_plan.append(
                                self._build_layout_plan_entry(page_index + 1, block)
                            )
                            overflow.append(
                                self._build_overflow_entry(
                                    page_index + 1,
                                    block,
                                    scale=0.0,
                                )
                            )
                            continue

                        words_before = (
                            self._snapshot_page_words(page)
                            if block.layout_engine == "pretext"
                            and not block.toc_page_number
                            else []
                        )
                        if block.toc_page_number:
                            spare_height, scale = self._render_toc_entry(
                                page,
                                block.planned_rect,
                                block.translated,
                                block.toc_page_number,
                                block.font_size,
                                render_font_family,
                                block.font_name,
                                render_css,
                                render_archive,
                                block.line_height_pt,
                            )
                        else:
                            html_block = self._build_html(
                                block.translated,
                                block.label,
                                block.font_size,
                                render_font_family,
                                block.font_name,
                                block.planned_line_count,
                                block.line_height_pt,
                                block.letter_spacing_em,
                            )
                            spare_height, scale = self._insert_with_scale_policy(
                                page,
                                block.planned_rect,
                                html_block,
                                render_css,
                                render_archive,
                                block.font_size,
                                scale_candidates=(
                                    self._pretext_scale_candidates(block.font_size)
                                    if layout_engine == "pretext"
                                    else None
                                ),
                            )
                        if (
                            block.layout_engine == "pretext"
                            and not block.toc_page_number
                        ):
                            self._apply_final_render_metrics(
                                block,
                                self._extract_added_text_bbox(page, words_before),
                            )
                            self._shift_remaining_blocks_if_needed(
                                block,
                                column_blocks_by_id.get(block.block_id, []),
                            )
                        if block.layout_engine == "pretext":
                            block.final_scale_used = scale
                            append_run_log(
                                workspace.run_log,
                                "render=final_summary "
                                f"page={page_index + 1} block_id={block.block_id} "
                                f"final_bbox={self._rect_to_bbox(block.actual_render_bbox or block.planned_rect)} "
                                f"probe_final_delta={[0.0, 0.0, 0.0, 0.0] if block.actual_render_bbox is not None else None}",
                            )
                        if spare_height == -1:
                            if block.layout_engine == "pretext":
                                block.fallback_reason = "final_render_drift_rejected"
                                block.fallback_detail = (
                                    "PyMuPDF final render rejected every allowed "
                                    "pretext fallback scale."
                                )
                            overflow.append(
                                self._build_overflow_entry(
                                    page_index + 1,
                                    block,
                                    scale=scale,
                                )
                            )
                        layout_plan.append(
                            self._build_layout_plan_entry(page_index + 1, block)
                        )
                    for block in planned_blocks:
                        element = element_by_block_id.get(block.block_id)
                        if element is not None:
                            self._update_element_layout_metadata(element, block)
                    current_state["overflow"] = len(overflow)
                    if (
                        page_index_1based == 1
                        or page_index_1based == total_pages
                        or page_index_1based % 5 == 0
                    ):
                        append_run_log(
                            workspace.run_log,
                            f"render=progress current={page_index_1based}/{total_pages} "
                            f"planned={len(planned)} overflow={len(overflow)}",
                        )

            doc.save(
                str(workspace.translated_pdf),
                garbage=4,
                deflate=True,
                clean=True,
            )
            write_json(workspace.structured_json, payload)
            shutil.copy2(workspace.translated_pdf, workspace.public_translated_pdf)
            write_json(
                workspace.render_report_json,
                {
                    "layout_engine": layout_engine,
                    "overflow": overflow,
                    "layout_plan": layout_plan,
                    "redaction": {
                        "redacted_runs": redaction_totals.redacted_run_count,
                        "skipped_protected_runs": (
                            redaction_totals.skipped_protected_count
                        ),
                        "restored_links": redaction_totals.restored_link_count,
                    },
                },
            )
            append_run_log(workspace.run_log, "render=artifacts:done")
            return len(overflow)
        finally:
            doc.close()

    def _load_document_ir(self, workspace: JobWorkspace) -> DocumentIR | None:
        if not workspace.document_ir_json.is_file():
            return None
        return read_document_ir(workspace.document_ir_json)

    def _redaction_runs_for_blocks(
        self,
        page_number: int,
        blocks: list[RenderBlockPlan],
        document: DocumentIR | None,
    ) -> list[DocumentRun]:
        if not blocks:
            return []
        if document is None:
            return [self._synthetic_run(block) for block in blocks]

        page_ir = next(
            (page for page in document.pages if page.page_number == page_number),
            None,
        )
        if page_ir is None:
            return [self._synthetic_run(block) for block in blocks]

        available_runs = [run for paragraph in page_ir.paragraphs for run in paragraph.runs]
        selected: dict[str, DocumentRun] = {}
        for block in blocks:
            matched = False
            for run in available_runs:
                if self._run_matches_block(run, block.original_rect):
                    selected[run.run_id] = run
                    matched = True
            if not matched:
                synthetic = self._synthetic_run(block)
                selected[synthetic.run_id] = synthetic
        return list(selected.values())

    def _run_matches_block(self, run: DocumentRun, block_rect: fitz.Rect) -> bool:
        run_rect = fitz.Rect(run.bbox)
        if run_rect.is_empty or run_rect.is_infinite:
            return False
        intersection = run_rect & block_rect
        if intersection.is_empty:
            return False
        run_area = max(run_rect.width * run_rect.height, 1e-9)
        intersection_area = max(intersection.width * intersection.height, 0.0)
        return intersection_area / run_area >= self.MIN_RUN_BLOCK_COVERAGE

    def _synthetic_run(self, block: RenderBlockPlan) -> DocumentRun:
        rect = block.original_rect
        return DocumentRun(
            run_id=f"synthetic-{block.block_id}",
            kind="text",
            text=block.translated,
            bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
            char_bboxes=[],
            style=TextStyle(
                font_name=block.font_name,
                font_size=block.font_size,
            ),
            translatable=True,
            protection_reason="",
        )
