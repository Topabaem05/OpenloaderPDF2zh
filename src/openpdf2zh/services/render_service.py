from __future__ import annotations

from collections import Counter
import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.layout_planner import (
    FitValidationResult,
    LayoutBlock,
    LayoutPlanner,
    build_column_clusters,
)
from openpdf2zh.services.usage_quota import QuotaLease
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


@dataclass(slots=True)
class RenderBlockPlan:
    block_id: str
    original_rect: fitz.Rect
    planned_rect: fitz.Rect
    actual_render_bbox: fitz.Rect | None
    translated: str
    label: str
    font_size: float
    font_name: str
    estimated_line_count: int
    planned_line_count: int
    line_height_pt: float | None
    letter_spacing_em: float | None
    toc_page_number: str
    shift_pt: float
    planned_height_pt: float
    top_delta_pt: float
    bottom_delta_pt: float
    final_scale_used: float
    layout_engine: str
    fallback_reason: str | None
    fallback_detail: str | None
    planner_candidate_reason: str
    post_render_overlap_pt: float
    render_allowed: bool


class RenderService:
    SPECIAL_CHARACTER_PATTERN = re.compile(r"[●•▪◦■□◆◇○◎◉※★☆▶▷◀◁→←↑↓]")
    SPECIAL_CHARACTER_FONT_STACK = (
        "'Noto Sans Symbols 2', 'Segoe UI Symbol', 'Apple Symbols', sans-serif"
    )

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.layout_planner = LayoutPlanner(settings)

    def render(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
        quota_guard: QuotaLease | None = None,
    ) -> int:
        payload = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
        doc = fitz.open(str(workspace.input_pdf))
        try:
            overflow: list[dict[str, object]] = []
            layout_plan: list[dict[str, object]] = []
            layout_engine = self._resolve_layout_engine()
            page_bundles = payload.get("pages", [])
            total_pages = len(page_bundles)
            render_css, render_archive, render_font_family = self._build_render_resources()
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
                    renderable_blocks = [block for block in planned_blocks if block.render_allowed]
                    for block in renderable_blocks:
                        page.add_redact_annot(block.original_rect, fill=(1, 1, 1))
                    if renderable_blocks:
                        page.apply_redactions()

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
                                self._build_layout_plan_entry(
                                    page_index + 1,
                                    block,
                                )
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
                        if block.layout_engine == "pretext" and not block.toc_page_number:
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
                                    "PyMuPDF final render rejected every allowed pretext fallback scale."
                                )
                            overflow.append(
                                self._build_overflow_entry(
                                    page_index + 1,
                                    block,
                                    scale=scale,
                                )
                            )
                        layout_plan.append(
                            self._build_layout_plan_entry(
                                page_index + 1,
                                block,
                            )
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
                            f"render=progress current={page_index_1based}/{total_pages} planned={len(planned)} overflow={len(overflow)}",
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
                },
            )
            append_run_log(workspace.run_log, "render=artifacts:done")
            return len(overflow)
        finally:
            doc.close()

    def _check_quota(self, quota_guard: QuotaLease | None) -> None:
        if quota_guard is None:
            return
        quota_guard.raise_if_expired()

    def _resolve_layout_engine(self) -> str:
        configured = self.settings.render_layout_engine.strip().lower()
        if configured in {"legacy", "pretext"}:
            return configured
        return "legacy"

    def _rect_to_bbox(self, rect: fitz.Rect) -> list[float]:
        return [
            round(rect.x0, 3),
            round(rect.y0, 3),
            round(rect.x1, 3),
            round(rect.y1, 3),
        ]

    def _build_layout_plan_entry(
        self,
        page_number: int,
        block: RenderBlockPlan,
    ) -> dict[str, object]:
        return {
            "page": page_number,
            "block_id": block.block_id,
            "label": block.label,
            "layout_engine": block.layout_engine,
            "original_bbox": self._rect_to_bbox(block.original_rect),
            "planned_bbox": self._rect_to_bbox(block.planned_rect),
            "actual_render_bbox": (
                self._rect_to_bbox(block.actual_render_bbox)
                if block.actual_render_bbox is not None
                else None
            ),
            "estimated_line_count": block.estimated_line_count,
            "planned_line_count": block.planned_line_count,
            "planned_height_pt": round(block.planned_height_pt, 3),
            "shift_pt": round(block.shift_pt, 3),
            "vertical_shift_pt": round(block.shift_pt, 3),
            "planned_font_size": round(block.font_size, 3),
            "planned_line_height_pt": (
                round(block.line_height_pt, 3)
                if block.line_height_pt is not None
                else None
            ),
            "planned_letter_spacing_em": block.letter_spacing_em,
            "top_delta_pt": round(block.top_delta_pt, 3),
            "bottom_delta_pt": round(block.bottom_delta_pt, 3),
            "final_scale_used": round(block.final_scale_used, 3),
            "planner_candidate_reason": block.planner_candidate_reason,
            "post_render_overlap_pt": round(block.post_render_overlap_pt, 3),
            "fallback_reason": block.fallback_reason,
            "fallback_detail": block.fallback_detail,
        }

    def _build_overflow_entry(
        self,
        page_number: int,
        block: RenderBlockPlan,
        *,
        scale: float,
    ) -> dict[str, object]:
        return {
            "page": page_number,
            "label": block.label,
            "bbox": self._rect_to_bbox(block.original_rect),
            "original_bbox": self._rect_to_bbox(block.original_rect),
            "planned_bbox": self._rect_to_bbox(block.planned_rect),
            "actual_render_bbox": (
                self._rect_to_bbox(block.actual_render_bbox)
                if block.actual_render_bbox is not None
                else None
            ),
            "font_size": block.font_size,
            "line_height_pt": block.line_height_pt,
            "estimated_line_count": block.estimated_line_count,
            "planned_line_count": block.planned_line_count,
            "planned_height_pt": round(block.planned_height_pt, 3),
            "shift_pt": round(block.shift_pt, 3),
            "vertical_shift_pt": round(block.shift_pt, 3),
            "planned_font_size": round(block.font_size, 3),
            "planned_line_height_pt": (
                round(block.line_height_pt, 3)
                if block.line_height_pt is not None
                else None
            ),
            "planned_letter_spacing_em": block.letter_spacing_em,
            "top_delta_pt": round(block.top_delta_pt, 3),
            "bottom_delta_pt": round(block.bottom_delta_pt, 3),
            "final_scale_used": round(block.final_scale_used, 3),
            "planner_candidate_reason": block.planner_candidate_reason,
            "post_render_overlap_pt": round(block.post_render_overlap_pt, 3),
            "layout_engine": block.layout_engine,
            "fallback_reason": block.fallback_reason,
            "fallback_detail": block.fallback_detail,
            "scale": scale,
            "text_preview": block.translated[:160],
        }

    def _update_element_layout_metadata(
        self,
        element: dict[str, object],
        block: RenderBlockPlan,
    ) -> None:
        element["planned_bbox"] = self._rect_to_bbox(block.planned_rect)
        element["actual_render_bbox"] = (
            self._rect_to_bbox(block.actual_render_bbox)
            if block.actual_render_bbox is not None
            else None
        )
        element["pretext_line_count"] = block.planned_line_count
        element["pretext_height_pt"] = round(block.planned_height_pt, 3)
        element["vertical_shift_pt"] = round(block.shift_pt, 3)
        element["top_delta_pt"] = round(block.top_delta_pt, 3)
        element["bottom_delta_pt"] = round(block.bottom_delta_pt, 3)
        element["final_scale_used"] = round(block.final_scale_used, 3)
        element["layout_engine"] = block.layout_engine
        element["layout_fallback"] = block.fallback_reason
        element["planner_candidate_reason"] = block.planner_candidate_reason
        element["post_render_overlap_pt"] = round(block.post_render_overlap_pt, 3)
        element["planned_font_size"] = round(block.font_size, 3)
        element["planned_line_height_pt"] = (
            round(block.line_height_pt, 3)
            if block.line_height_pt is not None
            else None
        )
        element["planned_letter_spacing_em"] = block.letter_spacing_em

    def _plan_render_blocks(
        self,
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
        ],
        layout_engine: str,
        page_rect: fitz.Rect,
        render_font_family: str | None,
        render_css: str | None,
        render_archive: fitz.Archive | None,
    ) -> list[RenderBlockPlan]:
        blocks: list[RenderBlockPlan] = []
        for index, item in enumerate(planned, start=1):
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
            ) = item
            blocks.append(
                RenderBlockPlan(
                    block_id=f"b{index:04d}",
                    original_rect=fitz.Rect(rect),
                    planned_rect=fitz.Rect(rect),
                    actual_render_bbox=None,
                    translated=translated,
                    label=label,
                    font_size=font_size,
                    font_name=font_name,
                    estimated_line_count=estimated_line_count,
                    planned_line_count=estimated_line_count,
                    line_height_pt=line_height_pt,
                    letter_spacing_em=letter_spacing_em,
                    toc_page_number=toc_page_number,
                    shift_pt=0.0,
                    planned_height_pt=rect.height,
                    top_delta_pt=0.0,
                    bottom_delta_pt=0.0,
                    final_scale_used=1.0,
                    layout_engine=layout_engine,
                    fallback_reason=None,
                    fallback_detail=None,
                    planner_candidate_reason="none",
                    post_render_overlap_pt=0.0,
                    render_allowed=True,
                )
            )

        if layout_engine == "pretext":
            return self._plan_pretext_blocks(
                blocks,
                page_rect,
                render_font_family,
                render_css,
                render_archive,
            )
        return self._plan_legacy_blocks(blocks)

    def _plan_legacy_blocks(
        self, blocks: list[RenderBlockPlan]
    ) -> list[RenderBlockPlan]:
        for block in blocks:
            planned_rect = self._resolve_render_rect(block.original_rect, block.font_size)
            block.planned_rect = planned_rect
            block.actual_render_bbox = fitz.Rect(planned_rect)
            block.shift_pt = max(0.0, planned_rect.y0 - block.original_rect.y0)
            block.planned_height_pt = planned_rect.height
            block.top_delta_pt = 0.0
            block.bottom_delta_pt = 0.0
            block.final_scale_used = 1.0
            block.layout_engine = "legacy"
            block.fallback_reason = None
            block.fallback_detail = None
            block.planner_candidate_reason = "none"
            block.post_render_overlap_pt = 0.0
            block.render_allowed = True
        return blocks

    def _plan_pretext_blocks(
        self,
        blocks: list[RenderBlockPlan],
        page_rect: fitz.Rect,
        render_font_family: str | None,
        render_css: str | None,
        render_archive: fitz.Archive | None,
    ) -> list[RenderBlockPlan]:
        planner_blocks = [
            LayoutBlock(
                element={"block_id": block.block_id},
                original_rect=fitz.Rect(block.original_rect),
                render_rect=fitz.Rect(
                    self._resolve_render_rect(block.original_rect, block.font_size)
                ),
                translated=block.translated,
                label=block.label,
                font_size=block.font_size,
                font_name=block.font_name,
                font_family_css=self._resolve_font_family_css(
                    render_font_family,
                    block.font_name,
                ),
                estimated_line_count=block.estimated_line_count,
                line_height_pt=block.line_height_pt or round(block.font_size * 1.2, 3),
                letter_spacing_em=block.letter_spacing_em,
                toc_page_number=block.toc_page_number,
            )
            for block in blocks
        ]
        fit_cache: dict[tuple[object, ...], FitValidationResult] = {}
        planned_blocks = self.layout_planner.plan_page(
            planner_blocks,
            render_font_path=self.settings.render_font_path,
            fit_validator=lambda planner_block, planned_rect, measurement: self._probe_pretext_html_fit(
                planner_block,
                planned_rect,
                measurement,
                page_rect,
                render_font_family,
                render_css,
                render_archive,
                fit_cache,
            ),
        )
        planned_by_block_id: dict[str, object] = {}
        planned_fallback_queue: list[object] = []
        for planned in planned_blocks:
            block_id = str(planned.block.element.get("block_id", "")).strip()
            if block_id:
                planned_by_block_id[block_id] = planned
            else:
                planned_fallback_queue.append(planned)
        for block in blocks:
            planned = planned_by_block_id.get(block.block_id)
            if planned is None and planned_fallback_queue:
                planned = planned_fallback_queue.pop(0)
            if planned is None:
                block.planned_rect = fitz.Rect(
                    self._resolve_render_rect(block.original_rect, block.font_size)
                )
                block.actual_render_bbox = None
                block.shift_pt = max(0.0, block.planned_rect.y0 - block.original_rect.y0)
                block.planned_height_pt = block.planned_rect.height
                block.planned_line_count = block.estimated_line_count
                block.top_delta_pt = 0.0
                block.bottom_delta_pt = 0.0
                block.final_scale_used = 0.0
                block.layout_engine = "pretext"
                block.fallback_reason = "planner_missing"
                block.fallback_detail = "Layout planner did not return a block result."
                block.planner_candidate_reason = "planner_missing"
                block.post_render_overlap_pt = 0.0
                block.render_allowed = False
                continue
            block.planned_rect = fitz.Rect(planned.planned_rect)
            block.actual_render_bbox = (
                fitz.Rect(planned.actual_render_bbox)
                if planned.actual_render_bbox is not None
                else None
            )
            block.planned_height_pt = planned.planned_rect.height
            block.planned_line_count = (
                planned.pretext_line_count or block.estimated_line_count
            )
            block.font_size = planned.render_font_size_pt
            block.line_height_pt = planned.render_line_height_pt
            block.letter_spacing_em = planned.render_letter_spacing_em
            block.shift_pt = planned.vertical_shift_pt
            block.top_delta_pt = planned.top_delta_pt
            block.bottom_delta_pt = planned.bottom_delta_pt
            block.final_scale_used = planned.final_scale_used
            block.layout_engine = planned.layout_engine
            block.fallback_reason = planned.layout_fallback
            block.fallback_detail = (
                None if planned.layout_fallback == "none" else planned.layout_fallback
            )
            block.planner_candidate_reason = planned.planner_candidate_reason
            block.post_render_overlap_pt = planned.post_render_overlap_pt
            block.render_allowed = planned.layout_fallback not in {
                "planner_overflow",
                "pymupdf_probe_overflow",
                "postpass_overlap_overflow",
            }
        return blocks

    def _probe_pretext_html_fit(
        self,
        block: LayoutBlock,
        planned_rect: fitz.Rect,
        measurement: dict[str, float | int | None | str],
        page_rect: fitz.Rect,
        render_font_family: str | None,
        render_css: str | None,
        render_archive: fitz.Archive | None,
        fit_cache: dict[tuple[object, ...], FitValidationResult] | None = None,
    ) -> FitValidationResult:
        letter_spacing_em = measurement.get("letter_spacing_em")
        if not isinstance(letter_spacing_em, (int, float)):
            letter_spacing_em = None
        cache_key = (
            block.label,
            block.translated,
            block.font_name,
            round(page_rect.width, 3),
            round(page_rect.height, 3),
            round(planned_rect.width, 3),
            round(planned_rect.height, 3),
            round(float(measurement.get("font_size_pt", block.font_size)), 3),
            round(float(measurement.get("line_height_pt", block.line_height_pt)), 3),
            None if letter_spacing_em is None else round(float(letter_spacing_em), 3),
            int(measurement.get("line_count", block.estimated_line_count)),
        )
        if fit_cache is not None and cache_key in fit_cache:
            return self._clone_fit_validation_result(fit_cache[cache_key])

        html_block = self._build_html(
            block.translated,
            block.label,
            float(measurement.get("font_size_pt", block.font_size)),
            render_font_family,
            block.font_name,
            max(int(measurement.get("line_count", block.estimated_line_count)), 1),
            float(measurement.get("line_height_pt", block.line_height_pt)),
            letter_spacing_em,
        )

        scratch_doc = fitz.open()
        try:
            scratch_page = scratch_doc.new_page(
                width=max(page_rect.width, 1.0),
                height=max(page_rect.height, 1.0),
            )
            spare_height, scale = scratch_page.insert_htmlbox(
                fitz.Rect(planned_rect),
                html_block,
                css=render_css,
                scale_low=1.0,
                archive=render_archive,
                opacity=1,
                overlay=True,
            )
            actual_render_bbox = None
            if spare_height != -1:
                actual_render_bbox = self._extract_text_bbox(scratch_page)
                if actual_render_bbox is None:
                    actual_render_bbox = fitz.Rect(planned_rect)
        finally:
            scratch_doc.close()

        fits = spare_height != -1 and actual_render_bbox is not None
        result = FitValidationResult(
            fits=fits,
            actual_render_bbox=(
                fitz.Rect(actual_render_bbox)
                if actual_render_bbox is not None
                else None
            ),
            top_delta_pt=(
                float(actual_render_bbox.y0 - planned_rect.y0)
                if actual_render_bbox is not None
                else 0.0
            ),
            bottom_delta_pt=(
                float(actual_render_bbox.y1 - planned_rect.y1)
                if actual_render_bbox is not None
                else 0.0
            ),
            used_scale=float(scale),
            spare_height=float(spare_height),
        )
        if fit_cache is not None:
            fit_cache[cache_key] = self._clone_fit_validation_result(result)
        return result

    def _clone_fit_validation_result(
        self,
        result: FitValidationResult,
    ) -> FitValidationResult:
        return FitValidationResult(
            fits=result.fits,
            actual_render_bbox=(
                fitz.Rect(result.actual_render_bbox)
                if result.actual_render_bbox is not None
                else None
            ),
            top_delta_pt=result.top_delta_pt,
            bottom_delta_pt=result.bottom_delta_pt,
            used_scale=result.used_scale,
            spare_height=result.spare_height,
        )

    def _apply_final_render_metrics(
        self,
        block: RenderBlockPlan,
        actual_render_bbox: fitz.Rect | None,
    ) -> None:
        resolved_bbox = actual_render_bbox or block.actual_render_bbox or fitz.Rect(
            block.planned_rect
        )
        block.actual_render_bbox = fitz.Rect(resolved_bbox)
        block.top_delta_pt = round(
            block.actual_render_bbox.y0 - block.planned_rect.y0,
            3,
        )
        block.bottom_delta_pt = round(
            block.actual_render_bbox.y1 - block.planned_rect.y1,
            3,
        )

    def _shift_remaining_blocks_if_needed(
        self,
        rendered_block: RenderBlockPlan,
        column_blocks: list[RenderBlockPlan],
    ) -> None:
        if rendered_block.actual_render_bbox is None:
            return

        current_found = False
        previous_bottom = rendered_block.actual_render_bbox.y1
        for block in column_blocks:
            if block.block_id == rendered_block.block_id:
                current_found = True
                continue
            if not current_found:
                continue

            gap = self._gap_height_for_shift(block)
            target_y0 = max(block.planned_rect.y0, previous_bottom + gap)
            delta = round(target_y0 - block.planned_rect.y0, 3)
            if delta > 0.5:
                self._shift_block_vertically(block, delta)

            reference_rect = block.actual_render_bbox or block.planned_rect
            previous_bottom = reference_rect.y1

    def _shift_block_vertically(
        self,
        block: RenderBlockPlan,
        delta: float,
    ) -> None:
        block.planned_rect = self._shift_rect_vertically(block.planned_rect, delta)
        if block.actual_render_bbox is not None:
            block.actual_render_bbox = self._shift_rect_vertically(
                block.actual_render_bbox,
                delta,
            )
        block.shift_pt = round(block.shift_pt + delta, 3)

    def _shift_rect_vertically(self, rect: fitz.Rect, delta: float) -> fitz.Rect:
        return fitz.Rect(rect.x0, rect.y0 + delta, rect.x1, rect.y1 + delta)

    def _gap_height_for_shift(self, block: RenderBlockPlan) -> float:
        line_height_pt = block.line_height_pt or round(block.font_size * 1.2, 3)
        return max(1.0, round(line_height_pt * 0.12, 3))

    def _snapshot_page_words(
        self,
        page: fitz.Page,
    ) -> list[tuple[object, ...]]:
        try:
            words = page.get_text("words")
        except (AttributeError, TypeError):
            return []

        snapshots: list[tuple[object, ...]] = []
        for word in words:
            if len(word) < 5:
                continue
            snapshots.append(
                (
                    round(float(word[0]), 3),
                    round(float(word[1]), 3),
                    round(float(word[2]), 3),
                    round(float(word[3]), 3),
                    str(word[4]),
                    *tuple(word[5:8]),
                )
            )
        return snapshots

    def _extract_added_text_bbox(
        self,
        page: fitz.Page,
        words_before: list[tuple[object, ...]],
    ) -> fitz.Rect | None:
        words_after = self._snapshot_page_words(page)
        if not words_after:
            return None

        remaining = Counter(words_before)
        rects: list[fitz.Rect] = []
        for word in words_after:
            if remaining[word] > 0:
                remaining[word] -= 1
                continue
            rects.append(fitz.Rect(word[:4]))
        if rects:
            return self._union_rects(rects)
        return None

    def _extract_text_bbox(self, page: fitz.Page) -> fitz.Rect | None:
        rects: list[fitz.Rect] = []
        try:
            for word in page.get_text("words"):
                if len(word) < 4:
                    continue
                rects.append(fitz.Rect(word[:4]))
        except (AttributeError, TypeError):
            return None
        if rects:
            return self._union_rects(rects)

        try:
            payload = page.get_text("dict")
        except (AttributeError, TypeError):
            return None
        for block in payload.get("blocks", []):
            if not isinstance(block, dict) or block.get("type") != 0:
                continue
            bbox = block.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                rects.append(fitz.Rect(bbox))
        if rects:
            return self._union_rects(rects)
        return None

    def _union_rects(self, rects: list[fitz.Rect]) -> fitz.Rect:
        current = fitz.Rect(rects[0])
        for rect in rects[1:]:
            current |= fitz.Rect(rect)
        return current

    def _render_toc_entry(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        title: str,
        page_number: str,
        font_size: float,
        render_font_family: str | None,
        source_font_name: str,
        render_css: str | None,
        render_archive: fitz.Archive | None,
        line_height_pt: float | None,
    ) -> tuple[float, float]:
        page_width = min(max(font_size * 3.2, rect.width * 0.14), rect.width * 0.24)
        leader_width = min(max(font_size * 6.0, rect.width * 0.18), rect.width * 0.34)
        title_rect = fitz.Rect(
            rect.x0,
            rect.y0,
            rect.x1 - page_width - leader_width,
            rect.y1,
        )
        page_rect = fitz.Rect(rect.x1 - page_width, rect.y0, rect.x1, rect.y1)
        leader_rect = fitz.Rect(title_rect.x1, rect.y0, page_rect.x0, rect.y1)

        title_html = self._build_html(
            title,
            "paragraph",
            font_size,
            render_font_family,
            source_font_name,
            1,
            line_height_pt,
            None,
        )
        title_spare, title_scale = self._insert_with_scale_policy(
            page,
            title_rect,
            title_html,
            render_css,
            render_archive,
            font_size,
        )

        page_html = self._build_html(
            page_number,
            "paragraph",
            font_size,
            render_font_family,
            source_font_name,
            1,
            line_height_pt,
            None,
        )
        page_spare, page_scale = self._insert_with_scale_policy(
            page,
            page_rect,
            page_html,
            render_css,
            render_archive,
            font_size,
        )

        if leader_rect.width > font_size:
            leader_html = self._build_html(
                self._build_toc_leader_text(leader_rect.width, font_size),
                "paragraph",
                font_size,
                render_font_family,
                source_font_name,
                1,
                line_height_pt,
                0.05,
            )
            self._insert_with_scale_policy(
                page,
                leader_rect,
                leader_html,
                render_css,
                render_archive,
                font_size,
            )

        spare_height = -1.0 if title_spare == -1 or page_spare == -1 else 0.0
        return spare_height, min(title_scale, page_scale)

    def _build_toc_leader_text(self, width: float, font_size: float) -> str:
        leader_count = max(int(width / max(font_size * 0.42, 1.0)), 4)
        return "." * leader_count

    def _insert_with_scale_policy(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        html_block: str,
        render_css: str | None,
        render_archive: fitz.Archive | None,
        font_size: float,
        scale_candidates: list[float] | None = None,
    ) -> tuple[float, float]:
        candidates = scale_candidates or self._scale_candidates(font_size)
        for scale_low in candidates:
            spare_height, scale = page.insert_htmlbox(
                rect,
                html_block,
                css=render_css,
                scale_low=scale_low,
                archive=render_archive,
                opacity=1,
                overlay=True,
            )
            if spare_height != -1:
                return spare_height, scale
        return -1.0, 0.0

    def _apply_overlap_aware_letter_spacing(
        self,
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
        ],
    ) -> list[
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
    ]:
        if not self.settings.adjust_render_letter_spacing_for_overlap:
            return planned

        adjusted: list[
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
        committed_rects: list[fitz.Rect] = []

        for item in planned:
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
            ) = item

            adjusted_letter_spacing = letter_spacing_em
            candidate_rect = self._resolve_render_rect(rect, font_size)
            if not toc_page_number and self._uses_paragraph_box(label):
                overlap_penalty = self._resolve_overlap_letter_spacing_penalty(
                    candidate_rect,
                    committed_rects,
                )
                if overlap_penalty is not None:
                    adjusted_letter_spacing = self._combine_letter_spacing(
                        letter_spacing_em,
                        overlap_penalty,
                    )

            adjusted.append(
                (
                    rect,
                    translated,
                    label,
                    font_size,
                    font_name,
                    estimated_line_count,
                    line_height_pt,
                    adjusted_letter_spacing,
                    toc_page_number,
                )
            )
            committed_rects.append(candidate_rect)

        return adjusted

    def _resolve_overlap_letter_spacing_penalty(
        self,
        rect: fitz.Rect,
        previous_rects: list[fitz.Rect],
    ) -> float | None:
        strongest_penalty = 0.0

        for previous in previous_rects:
            horizontal_overlap = min(rect.x1, previous.x1) - max(rect.x0, previous.x0)
            if horizontal_overlap <= 0:
                continue

            narrower_width = max(min(rect.width, previous.width), 1.0)
            horizontal_overlap_ratio = horizontal_overlap / narrower_width
            if horizontal_overlap_ratio < 0.2:
                continue

            vertical_overlap = min(rect.y1, previous.y1) - max(rect.y0, previous.y0)
            if vertical_overlap > 0:
                overlap_ratio = vertical_overlap / max(
                    min(rect.height, previous.height),
                    1.0,
                )
                strongest_penalty = max(
                    strongest_penalty,
                    min(0.22, 0.05 + (overlap_ratio * 0.16)),
                )
                continue

            vertical_gap = max(rect.y0, previous.y0) - min(rect.y1, previous.y1)
            max_safe_gap = max(min(rect.height, previous.height) * 0.32, 4.0)
            if vertical_gap < 0 or vertical_gap > max_safe_gap:
                continue

            gap_ratio = 1.0 - (vertical_gap / max_safe_gap)
            strongest_penalty = max(
                strongest_penalty,
                min(0.16, 0.04 + (gap_ratio * 0.1)),
            )

        if strongest_penalty <= 0:
            return None
        return -round(strongest_penalty, 3)

    def _combine_letter_spacing(
        self,
        base_letter_spacing_em: float | None,
        adjustment_em: float,
    ) -> float | None:
        adjusted = (base_letter_spacing_em or 0.0) + adjustment_em
        adjusted = min(max(adjusted, -0.22), 0.12)
        if abs(adjusted) < 0.005:
            return None
        return round(adjusted, 3)

    def _scale_candidates(self, font_size: float) -> list[float]:
        if font_size >= 16.0:
            return [1.0, 0.92, 0.82, 0.68, 0.0]
        if font_size <= 11.5:
            return [0.92, 0.82, 0.68, 0.0]
        if font_size <= 16.0:
            return [0.88, 0.76, 0.62, 0.0]
        return [0.84, 0.72, 0.58, 0.0]

    def _pretext_scale_candidates(self, font_size: float) -> list[float]:
        _ = font_size
        candidates = [1.0, 0.96, 0.92]
        ordered: list[float] = []
        for value in candidates:
            rounded = round(value, 3)
            if rounded not in ordered:
                ordered.append(rounded)
        return ordered

    def _resolve_render_rect(self, rect: fitz.Rect, font_size: float) -> fitz.Rect:
        if font_size < 16.0:
            return rect

        horizontal_padding = min(max(rect.width * 0.035, font_size * 0.2), 18.0)
        vertical_padding = min(max(rect.height * 0.15, font_size * 0.9), 28.0)
        return fitz.Rect(
            rect.x0 - horizontal_padding,
            rect.y0 - (vertical_padding * 0.3),
            rect.x1 + horizontal_padding,
            rect.y1 + vertical_padding,
        )

    def _build_html(
        self,
        text: str,
        label: str,
        font_size: float,
        render_font_family: str | None,
        source_font_name: str,
        estimated_line_count: int,
        line_height_pt: float | None,
        letter_spacing_em: float | None,
    ) -> str:
        safe_text = self._format_translated_text(
            text,
            label,
            estimated_line_count,
            font_size,
        )
        font_family = self._resolve_font_family_css(
            render_font_family,
            source_font_name,
        )
        line_height_css = f"{line_height_pt}pt" if line_height_pt is not None else "1.2"
        letter_spacing_css = (
            f"letter-spacing: {letter_spacing_em}em;"
            if letter_spacing_em is not None
            else ""
        )
        return (
            f'<div style="font-family: {font_family}; font-size: {font_size}pt; '
            f'line-height: {line_height_css}; color: #111; white-space: pre-wrap; display: block; margin: 0; padding: 0; {letter_spacing_css}">'
            f"{safe_text}</div>"
        )

    def _build_render_resources(
        self,
    ) -> tuple[str | None, fitz.Archive | None, str | None]:
        if not self.settings.render_font_path:
            return None, None, None

        font_path = Path(self.settings.render_font_path).expanduser().resolve()
        if not font_path.is_file():
            raise RuntimeError(
                f"Configured render font file was not found: {font_path}. Check OPENPDF2ZH_RENDER_FONT_PATH."
            )

        font_family = "customrenderfont"
        css = (
            f"@font-face {{font-family: {font_family}; src: url('{font_path.name}');}}"
        )
        archive = fitz.Archive(str(font_path.parent))
        return css, archive, font_family

    def _normalize_font_family(self, source_font_name: str) -> str:
        return self._format_font_family_css(source_font_name)

    def _resolve_font_family_css(
        self,
        render_font_family: str | None,
        source_font_name: str,
    ) -> str:
        if render_font_family:
            resolved = self._format_font_family_css(render_font_family)
            if resolved != "sans-serif":
                return resolved
        return self._format_font_family_css(source_font_name)

    def _format_font_family_css(self, font_name: str) -> str:
        if not font_name:
            return "sans-serif"
        safe_name = re.sub(r"[^A-Za-z0-9 _\-]", "", str(font_name)).strip()
        if not safe_name:
            return "sans-serif"
        return f"'{safe_name}', sans-serif"

    def _resolve_font_size(
        self, element: dict[str, object], fallback_size: float
    ) -> float:
        value = element.get("font_size")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return fallback_size

    def _resolve_estimated_line_count(self, element: dict[str, object]) -> int:
        value = element.get("estimated_line_count")
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, float) and value > 0:
            return int(round(value))
        return 1

    def _resolve_line_height_pt(
        self, element: dict[str, object], fallback_font_size: float
    ) -> float | None:
        value = element.get("line_height_pt")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return round(fallback_font_size * 1.2, 3)

    def _resolve_letter_spacing_em(self, element: dict[str, object]) -> float | None:
        value = element.get("letter_spacing_em")
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _format_translated_text(
        self,
        text: str,
        label: str,
        estimated_line_count: int,
        font_size: float,
    ) -> str:
        normalized = text.strip()
        lines = normalized.split("\n")
        return "<br/>".join(
            self._style_special_characters(line, font_size) for line in lines
        )

    def _style_special_characters(self, text: str, font_size: float) -> str:
        escaped = html.escape(text)
        return self.SPECIAL_CHARACTER_PATTERN.sub(
            lambda match: (
                '<span style="'
                f"font-family: {self.SPECIAL_CHARACTER_FONT_STACK}; "
                f"font-size: {font_size}pt; "
                'line-height: inherit; vertical-align: baseline;">'
                f"{match.group(0)}"
                "</span>"
            ),
            escaped,
        )

    def _uses_paragraph_box(self, label: str) -> bool:
        return label.strip().lower() in {
            "paragraph",
            "list item",
            "heading",
            "caption",
        }

    def _element_sort_key(self, element: dict[str, object]) -> tuple[float, float]:
        bbox = element.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            left = float(bbox[0])
            top = float(bbox[3])
            return (-top, left)
        return (0.0, 0.0)

    def _pdf_bbox_to_rect(self, page: fitz.Page, bbox: list[float]) -> fitz.Rect:
        left, bottom, right, top = [float(value) for value in bbox]
        matrix = page.transformation_matrix
        point_a = fitz.Point(left, top) * matrix
        point_b = fitz.Point(right, bottom) * matrix
        return fitz.Rect(
            min(point_a.x, point_b.x),
            min(point_a.y, point_b.y),
            max(point_a.x, point_b.x),
            max(point_a.y, point_b.y),
        )

    def _resolve_page_rect(
        self,
        page: fitz.Page,
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
        ],
    ) -> fitz.Rect:
        page_rect = getattr(page, "rect", None)
        if page_rect is not None:
            return fitz.Rect(page_rect)
        if planned:
            union = fitz.Rect(planned[0][0])
            for rect, *_ in planned[1:]:
                union |= rect
            return union
        return fitz.Rect(0, 0, 0, 0)
