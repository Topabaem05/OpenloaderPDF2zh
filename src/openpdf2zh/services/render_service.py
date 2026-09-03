from __future__ import annotations

import html
import json
import re
import shutil
from collections import Counter
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
    flow_gap_pt: float
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
    fixed_position: bool
    preserve_original: bool


class RenderService:
    SPECIAL_CHARACTER_PATTERN = re.compile(r"[●•▪◦■□◆◇○◎◉※★☆▶▷◀◁→←↑↓]")
    SPECIAL_CHARACTER_FONT_STACK = (
        "'Noto Sans Symbols 2', 'Segoe UI Symbol', 'Apple Symbols', sans-serif"
    )
    # Only body-level text is held to the configured size range. Headings and
    # captions carry the document's visual hierarchy, so clamping a 31.5pt title to
    # body size destroys the layout it is supposed to preserve.
    BODY_LABELS = frozenset({"paragraph", "list item"})
    DISPLAY_FONT_SIZE_THRESHOLD = 16.0

    CJK_FONT_FAMILY = "customcjkfont"
    CJK_RUN_PATTERN = re.compile(
        r"[\u1100-\u11ff\u3000-\u303f\u3130-\u318f\u3400-\u4dbf"
        r"\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff"
        r"\uff00-\uffef]+"
    )
    INLINE_LITERAL_PATTERN = re.compile(
        r"(?:(?:https?://|www\.)[^\s<>()\[\]{}]*[A-Za-z0-9/#=_~%-]|"
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
    )
    PAGE_MARKER_PATTERN = re.compile(r"^[\s\-–—|()\[\]0-9ivxlcdm]+$", re.IGNORECASE)

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.layout_planner = LayoutPlanner(settings)
        self._cjk_font_available = False
        self._glyph_span_em: float | None = None

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
            render_css, render_archive, render_font_family = (
                self._build_render_resources()
            )
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
                            bool,
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
                        estimated_line_count = self._resolve_estimated_line_count(
                            element
                        )
                        line_height_pt = self._resolve_line_height_pt(
                            element, font_size
                        )
                        letter_spacing_em = self._resolve_letter_spacing_em(element)
                        toc_page_number = str(
                            element.get("toc_page_number", "")
                        ).strip()
                        preserve_original = self._should_preserve_original(
                            element,
                            translated,
                            rect,
                            getattr(page, "rect", None),
                            font_size,
                            toc_page_number,
                        )
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
                                preserve_original,
                            )
                        )

                    if layout_engine == "legacy":
                        planned = self._apply_overlap_aware_letter_spacing(planned)
                    else:
                        for obstacle in self._source_footer_obstacles(
                            page,
                            [item[0] for item in planned],
                        ):
                            planned_elements.append({})
                            planned.append(
                                (
                                    obstacle,
                                    "",
                                    "preserved original",
                                    1.0,
                                    "",
                                    1,
                                    max(obstacle.height, 1.0),
                                    None,
                                    "",
                                    True,
                                )
                            )
                    page_rect = self._resolve_page_rect(page, planned)
                    planned_blocks = self._plan_render_blocks(
                        planned,
                        layout_engine,
                        page_rect,
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
                        block
                        for block in planned_blocks
                        if block.render_allowed and not block.preserve_original
                    ]
                    for block in renderable_blocks:
                        page.add_redact_annot(block.original_rect, fill=None)
                    if renderable_blocks:
                        page.apply_redactions(
                            images=fitz.PDF_REDACT_IMAGE_NONE,
                            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                            text=fitz.PDF_REDACT_TEXT_REMOVE,
                        )
                        for block in planned_blocks:
                            if block.preserve_original:
                                self._restore_original_clip(
                                    page,
                                    workspace.input_pdf,
                                    page_index,
                                    block.original_rect,
                                )

                    for block in planned_blocks:
                        self._check_quota(quota_guard)
                        if block.preserve_original:
                            layout_plan.append(
                                self._build_layout_plan_entry(
                                    page_index + 1,
                                    block,
                                )
                            )
                            continue
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
                        is_table_cell = block.label.strip().lower() in {
                            "table cell",
                            "table header",
                        }
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
                                    [1.0, 0.92, 0.82, 0.68]
                                    if is_table_cell
                                    else (
                                        self._pretext_scale_candidates(
                                            block.font_size
                                        )
                                        if layout_engine == "pretext"
                                        else None
                                    )
                                ),
                                minimum_scale=(
                                    9.0 / block.font_size
                                    if is_table_cell and block.font_size > 0
                                    else None
                                ),
                            )
                        block.final_scale_used = scale
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
                            append_run_log(
                                workspace.run_log,
                                "render=final_summary "
                                f"page={page_index + 1} block_id={block.block_id} "
                                f"final_bbox={self._rect_to_bbox(block.actual_render_bbox or block.planned_rect)} "
                                f"probe_final_delta={[0.0, 0.0, 0.0, 0.0] if block.actual_render_bbox is not None else None}",
                            )
                        if spare_height == -1:
                            if is_table_cell:
                                self._restore_original_clip(
                                    page,
                                    workspace.input_pdf,
                                    page_index,
                                    block.original_rect,
                                )
                                block.preserve_original = True
                                block.fallback_reason = (
                                    "table_cell_overflow_preserved_original"
                                )
                                block.fallback_detail = (
                                    "The translated table cell did not fit at 9pt; "
                                    "the original cell clip was restored."
                                )
                            elif block.layout_engine == "pretext":
                                self._restore_original_clip(
                                    page,
                                    workspace.input_pdf,
                                    page_index,
                                    block.original_rect,
                                )
                                block.preserve_original = True
                                block.fallback_reason = (
                                    "final_render_drift_preserved_original"
                                )
                                block.fallback_detail = (
                                    "PyMuPDF final render rejected every allowed "
                                    "pretext fallback scale; the original source "
                                    "clip was restored."
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

    def _restore_original_clip(
        self,
        page: fitz.Page,
        source_pdf: Path,
        page_index: int,
        rect: fitz.Rect,
    ) -> None:
        with fitz.open(str(source_pdf)) as source_doc:
            page.show_pdf_page(
                rect,
                source_doc,
                page_index,
                clip=rect,
                keep_proportion=False,
                overlay=True,
            )

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
            "flow_gap_pt": round(block.flow_gap_pt, 3),
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
            "fixed_position": block.fixed_position,
            "preserve_original": block.preserve_original,
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
            "flow_gap_pt": round(block.flow_gap_pt, 3),
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
            "fixed_position": block.fixed_position,
            "preserve_original": block.preserve_original,
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
        element["flow_gap_pt"] = round(block.flow_gap_pt, 3)
        element["top_delta_pt"] = round(block.top_delta_pt, 3)
        element["bottom_delta_pt"] = round(block.bottom_delta_pt, 3)
        element["final_scale_used"] = round(block.final_scale_used, 3)
        element["layout_engine"] = block.layout_engine
        element["layout_fallback"] = block.fallback_reason
        element["planner_candidate_reason"] = block.planner_candidate_reason
        element["post_render_overlap_pt"] = round(block.post_render_overlap_pt, 3)
        element["planned_font_size"] = round(block.font_size, 3)
        element["planned_line_height_pt"] = (
            round(block.line_height_pt, 3) if block.line_height_pt is not None else None
        )
        element["planned_letter_spacing_em"] = block.letter_spacing_em
        element["fixed_position"] = block.fixed_position
        element["preserve_original"] = block.preserve_original

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
                bool,
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
                preserve_original,
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
                    flow_gap_pt=0.0,
                    planned_height_pt=rect.height,
                    top_delta_pt=0.0,
                    bottom_delta_pt=0.0,
                    final_scale_used=1.0,
                    layout_engine=layout_engine,
                    fallback_reason=None,
                    fallback_detail=None,
                    planner_candidate_reason="none",
                    post_render_overlap_pt=0.0,
                    render_allowed=not preserve_original,
                    fixed_position=(
                        preserve_original
                        or label.strip().lower() in {"table cell", "table header"}
                        or self._is_fixed_position(
                            rect,
                            page_rect,
                            font_size,
                        )
                    ),
                    preserve_original=preserve_original,
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
            if block.preserve_original:
                block.planned_rect = fitz.Rect(block.original_rect)
                block.actual_render_bbox = fitz.Rect(block.original_rect)
                block.planned_height_pt = block.original_rect.height
                block.layout_engine = "legacy"
                block.fallback_reason = "preserved_original"
                block.render_allowed = False
                continue
            planned_rect = self._resolve_render_rect(
                block.original_rect, block.font_size
            )
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
                render_rect=fitz.Rect(self._resolve_pretext_render_rect(block)),
                translated=block.translated,
                label=(
                    "preserved original" if block.preserve_original else block.label
                ),
                font_size=block.font_size,
                font_name=block.font_name,
                font_family_css=self._resolve_measurement_font_family_css(
                    render_font_family,
                    block.font_name,
                ),
                estimated_line_count=block.estimated_line_count,
                line_height_pt=block.line_height_pt or round(block.font_size * 1.2, 3),
                letter_spacing_em=block.letter_spacing_em,
                toc_page_number=block.toc_page_number,
                fixed_position=block.fixed_position,
            )
            for block in blocks
        ]
        self._expand_narrow_flow_blocks(planner_blocks)
        fit_cache: dict[tuple[object, ...], FitValidationResult] = {}
        planned_blocks = self.layout_planner.plan_page(
            planner_blocks,
            render_font_path=self.settings.render_font_path,
            fit_validator=lambda planner_block, planned_rect, measurement: (
                self._probe_pretext_html_fit(
                    planner_block,
                    planned_rect,
                    measurement,
                    page_rect,
                    render_font_family,
                    render_css,
                    render_archive,
                    fit_cache,
                )
            ),
            page_rect=page_rect,
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
                block.shift_pt = max(
                    0.0, block.planned_rect.y0 - block.original_rect.y0
                )
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
            block.flow_gap_pt = planned.flow_gap_pt
            block.top_delta_pt = planned.top_delta_pt
            block.bottom_delta_pt = planned.bottom_delta_pt
            block.final_scale_used = planned.final_scale_used
            block.layout_engine = planned.layout_engine
            block.fallback_reason = (
                "preserved_original"
                if block.preserve_original
                else planned.layout_fallback
            )
            block.fallback_detail = (
                None if planned.layout_fallback == "none" else planned.layout_fallback
            )
            block.planner_candidate_reason = planned.planner_candidate_reason
            block.post_render_overlap_pt = planned.post_render_overlap_pt
            block.render_allowed = (
                not block.preserve_original
                and planned.layout_fallback
                not in {
                    "planner_overflow",
                    "pymupdf_probe_overflow",
                    "postpass_overlap_overflow",
                }
            )
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
        resolved_bbox = (
            actual_render_bbox
            or block.actual_render_bbox
            or fitz.Rect(block.planned_rect)
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

            if block.fixed_position or block.toc_page_number:
                break

            gap = max(block.flow_gap_pt, 0.0)
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
        leader_width = min(max(font_size * 2.0, rect.width * 0.08), rect.width * 0.16)
        line_height = line_height_pt or font_size * 1.2
        line_count = max(1, round(rect.height / max(line_height, 1.0)))
        bottom_line_y0 = max(rect.y0, rect.y1 - line_height)
        title_rect = fitz.Rect(
            rect.x0,
            rect.y0,
            rect.x1 - page_width - leader_width,
            rect.y1,
        )
        page_rect = fitz.Rect(
            rect.x1 - page_width,
            bottom_line_y0,
            rect.x1,
            rect.y1,
        )
        leader_rect = fitz.Rect(
            title_rect.x1,
            bottom_line_y0,
            page_rect.x0,
            rect.y1,
        )

        title_html = self._build_html(
            title,
            "paragraph",
            font_size,
            render_font_family,
            source_font_name,
            line_count,
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
        minimum_scale: float | None = None,
    ) -> tuple[float, float]:
        candidates = scale_candidates or self._scale_candidates(font_size)
        floor_scale = (
            self._scale_floor(font_size)
            if minimum_scale is None
            else min(max(minimum_scale, 0.0), 1.0)
        )
        # scale_low=0 lets MuPDF shrink without limit, which crushed TOC entries to
        # ~1.8pt. Drop candidates below the configured minimum and keep the floor
        # itself as the tightest fit still allowed.
        allowed = [value for value in candidates if value >= floor_scale]
        if floor_scale > 0 and (not allowed or min(allowed) > floor_scale):
            allowed.append(floor_scale)
        for scale_low in allowed:
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

    def _scale_floor(self, font_size: float) -> float:
        minimum = self.settings.render_font_size_min
        if minimum <= 0 or font_size <= 0:
            return 0.0
        if font_size < minimum:
            # Source text legitimately smaller than the minimum keeps the legacy
            # free-shrink ladder so it still fits its own box.
            return 0.0
        return min(1.0, minimum / font_size)

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
                bool,
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
            bool,
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
                bool,
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
                preserve_original,
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
                    preserve_original,
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
            # Korean runs roughly 1.3-1.6x longer than English, and the CJK face is
            # taller per line, so body text needs room below its source box before
            # shrinking the type is considered.
            return fitz.Rect(
                rect.x0,
                rect.y0,
                rect.x1,
                rect.y1 + self._body_growth_allowance(rect, font_size),
            )

        horizontal_padding = min(max(rect.width * 0.035, font_size * 0.2), 18.0)
        vertical_padding = min(max(rect.height * 0.15, font_size * 0.9), 28.0)
        return fitz.Rect(
            rect.x0 - horizontal_padding,
            rect.y0,
            rect.x1 + horizontal_padding,
            rect.y1 + vertical_padding,
        )

    def _resolve_pretext_render_rect(self, block: RenderBlockPlan) -> fitz.Rect:
        if block.fixed_position:
            return fitz.Rect(block.original_rect)
        if block.font_size >= 16.0:
            expanded = self._resolve_render_rect(block.original_rect, block.font_size)
            return fitz.Rect(
                expanded.x0,
                block.original_rect.y0,
                expanded.x1,
                block.original_rect.y1,
            )
        # Pretext measures the required height. Pre-growing every body box shifts
        # the whole column even when the translated text already fits.
        return fitz.Rect(block.original_rect)

    def _expand_narrow_flow_blocks(self, blocks: list[LayoutBlock]) -> None:
        body_blocks = [
            block
            for block in blocks
            if not block.fixed_position
            and not block.toc_page_number
            and block.label.strip().lower() in self.BODY_LABELS
        ]
        clusters: list[list[LayoutBlock]] = []
        for block in sorted(body_blocks, key=lambda item: item.render_rect.x0):
            for cluster in clusters:
                if abs(cluster[0].render_rect.x0 - block.render_rect.x0) <= 4.0:
                    cluster.append(block)
                    break
            else:
                clusters.append([block])

        runs: list[list[LayoutBlock]] = []
        for cluster in clusters:
            for block in sorted(cluster, key=lambda item: item.original_rect.y0):
                if (
                    not runs
                    or abs(runs[-1][0].render_rect.x0 - block.render_rect.x0) > 4.0
                    or block.original_rect.y0 - runs[-1][-1].original_rect.y1
                    > max(12.0, block.font_size * 1.5)
                ):
                    runs.append([block])
                else:
                    runs[-1].append(block)

        for run in runs:
            column_right = max(
                block.render_rect.x1
                for block in body_blocks
                if abs(block.render_rect.x0 - run[0].render_rect.x0) <= 4.0
            )
            for block in run:
                right_limit = column_right
                for other in body_blocks:
                    vertical_overlap = min(
                        block.original_rect.y1,
                        other.original_rect.y1,
                    ) - max(block.original_rect.y0, other.original_rect.y0)
                    overlap_ratio = vertical_overlap / max(
                        min(
                            block.original_rect.height,
                            other.original_rect.height,
                        ),
                        1.0,
                    )
                    if (
                        other is not block
                        and other.original_rect.x0 > block.original_rect.x0 + 4.0
                        and overlap_ratio >= 0.25
                    ):
                        right_limit = min(right_limit, other.original_rect.x0 - 2.0)
                if right_limit - block.render_rect.x1 < block.font_size * 2.0:
                    continue
                block.render_rect.x1 = right_limit

    def _is_fixed_position(
        self,
        rect: fitz.Rect,
        page_rect: fitz.Rect,
        font_size: float,
    ) -> bool:
        edge_band = max(24.0, min(72.0, page_rect.height * 0.1))
        short_line = rect.height <= max(18.0, font_size * 2.0)
        return short_line and rect.y1 >= page_rect.y1 - edge_band

    def _source_footer_obstacles(
        self,
        page: fitz.Page,
        planned_rects: list[fitz.Rect],
    ) -> list[fitz.Rect]:
        page_rect = getattr(page, "rect", None)
        if not isinstance(page_rect, fitz.Rect):
            return []
        edge_band = max(24.0, min(72.0, page_rect.height * 0.1))
        edge_start = page_rect.y1 - edge_band
        obstacles: list[fitz.Rect] = []

        try:
            payload = page.get_text("dict")
        except (AttributeError, RuntimeError, ValueError):
            payload = {"blocks": []}
        for block in payload.get("blocks", []):
            for line in block.get("lines", []):
                bbox = line.get("bbox")
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                rect = fitz.Rect(bbox)
                if rect.y0 < edge_start or rect.height > 18.0:
                    continue
                if any(
                    rect.intersects(planned)
                    and (rect & planned).get_area() >= rect.get_area() * 0.5
                    for planned in planned_rects
                ):
                    continue
                obstacles.append(rect)

        try:
            drawings = page.get_drawings()
        except (AttributeError, RuntimeError, ValueError):
            drawings = []
        for drawing in drawings:
            rect = fitz.Rect(drawing.get("rect", fitz.Rect()))
            if (
                rect.y0 >= edge_start
                and rect.height <= 2.0
                and rect.width >= page_rect.width * 0.25
            ):
                obstacles.append(
                    fitz.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, rect.y0 + 1.0))
                )
        return obstacles

    def _should_preserve_original(
        self,
        element: dict[str, object],
        translated: str,
        rect: fitz.Rect,
        page_rect: fitz.Rect | None,
        font_size: float,
        toc_page_number: str,
    ) -> bool:
        source = str(element.get("content", "")).strip()
        if source and " ".join(source.split()) == " ".join(translated.split()):
            return True
        if page_rect is None:
            return False
        return self._is_fixed_position(rect, page_rect, font_size) and bool(
            toc_page_number or self.PAGE_MARKER_PATTERN.fullmatch(source)
        )

    def _body_growth_allowance(self, rect: fitz.Rect, font_size: float) -> float:
        # Only widen the box when a CJK render font is in play. Without it the source
        # font is reused, the line advance is unchanged, and the original box still
        # holds -- so callers keep the previous exact-box behaviour.
        if font_size <= 0 or not self.settings.render_cjk_font_path:
            return 0.0
        line_advance = font_size * self._render_glyph_span_em()
        # One extra line is enough to absorb the taller CJK line advance. Anything
        # larger cascades: the planner shifts every following block down to clear the
        # grown box, which is what pushed blocks 245pt off their source position.
        return round(min(line_advance, rect.height * 0.25), 3)

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
        text_color = "#fff" if label.strip().lower() == "table header" else "#111"
        return (
            f'<div style="font-family: {font_family}; font-size: {font_size}pt; '
            f"line-height: {line_height_css}; color: {text_color}; white-space: pre-wrap; "
            f"word-break: keep-all; overflow-wrap: break-word; display: block; "
            f'margin: 0; padding: 0; {letter_spacing_css}">'
            f"{safe_text}</div>"
        )

    def _build_render_resources(
        self,
    ) -> tuple[str | None, fitz.Archive | None, str | None]:
        primary = self._resolve_font_file(
            self.settings.render_font_path,
            "OPENPDF2ZH_RENDER_FONT_PATH",
        )
        cjk = self._resolve_font_file(
            self.settings.render_cjk_font_path,
            "OPENPDF2ZH_RENDER_CJK_FONT_PATH",
        )
        if primary is None and cjk is None:
            return None, None, None

        # A latin-only render font has no CJK glyphs, so MuPDF silently swaps in its
        # own fallback (Droid Sans) and the page ends up mixing typefaces. MuPDF
        # ignores both unicode-range and multi-family fallback lists, so CJK runs are
        # wrapped in an explicit span instead (see _style_cjk_runs).
        css_parts: list[str] = []
        archive = fitz.Archive()
        for font_path, family in (
            (primary, "customrenderfont"),
            (cjk, self.CJK_FONT_FAMILY),
        ):
            if font_path is None:
                continue
            css_parts.append(
                f"@font-face {{font-family: {family}; src: url('{font_path.name}');}}"
            )
            # ponytail: register the single file, not its directory, so an unrelated
            # font folder is not exposed to the renderer.
            archive.add(font_path.read_bytes(), font_path.name)
        self._cjk_font_available = cjk is not None
        return "".join(css_parts), archive, ("customrenderfont" if primary else None)

    def _resolve_font_file(self, configured: str, env_name: str) -> Path | None:
        if not configured:
            return None
        font_path = Path(configured).expanduser().resolve()
        if not font_path.is_file():
            raise RuntimeError(
                f"Configured render font file was not found: {font_path}. Check {env_name}."
            )
        return font_path

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

    def _resolve_measurement_font_family_css(
        self,
        render_font_family: str | None,
        source_font_name: str,
    ) -> str:
        family = self._resolve_font_family_css(render_font_family, source_font_name)
        if not self._cjk_font_available:
            return family
        base = family.removesuffix(", sans-serif")
        return f"{base}, '{self.CJK_FONT_FAMILY}', sans-serif"

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
            source = float(value)
        else:
            source = fallback_size
        label = str(element.get("label", "text")).strip().lower()
        if label in {"table cell", "table header"}:
            return round(min(max(source, 9.0), 11.0), 3)
        if label not in self.BODY_LABELS or source >= self.DISPLAY_FONT_SIZE_THRESHOLD:
            return round(source, 3)
        return self._floor_font_size(self._clamp_font_size(source), source)

    def _clamp_font_size(self, font_size: float) -> float:
        maximum = self.settings.render_font_size_max
        if maximum > 0:
            font_size = min(font_size, maximum)
        return round(font_size, 3)

    def _floor_font_size(self, font_size: float, source_font_size: float) -> float:
        """Raise body text to the minimum, but leave already-small source text alone.

        Imprint pages, ISBN lines and figure credits are set below the minimum in the
        source; enlarging them only pushes them out of their original box.
        """
        minimum = self.settings.render_font_size_min
        if minimum <= 0 or source_font_size < minimum:
            return font_size
        return max(font_size, minimum)

    def _resolve_estimated_line_count(self, element: dict[str, object]) -> int:
        value = element.get("estimated_line_count")
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, float) and value > 0:
            return round(value)
        return 1

    def _resolve_line_height_pt(
        self, element: dict[str, object], fallback_font_size: float
    ) -> float | None:
        value = element.get("line_height_pt")
        if isinstance(value, (int, float)) and value > 0:
            line_height = float(value)
        else:
            line_height = round(fallback_font_size * 1.2, 3)
        return self._floor_line_height_pt(line_height, fallback_font_size)

    def _floor_line_height_pt(self, line_height_pt: float, font_size: float) -> float:
        """Keep the line advance at least as tall as the render font's glyph box.

        The source line height belongs to the source font. A CJK face is usually
        taller per em (KoPubWorld Batang spans 1.54em against Times New Roman's
        1.11em), so inheriting the source value makes consecutive lines of the same
        paragraph physically overlap.
        """
        if font_size <= 0:
            return line_height_pt
        return round(max(line_height_pt, font_size * self._render_glyph_span_em()), 3)

    def _render_glyph_span_em(self) -> float:
        if self._glyph_span_em is not None:
            return self._glyph_span_em

        span = 0.0
        for configured in (
            self.settings.render_cjk_font_path,
            self.settings.render_font_path,
        ):
            if not configured:
                continue
            try:
                font = fitz.Font(fontfile=str(Path(configured).expanduser()))
            except (fitz.mupdf.FzErrorBase, OSError, ValueError):
                # An unreadable or non-font file must not break rendering; the
                # default 1.2em advance still applies.
                continue
            span = max(span, font.ascender - font.descender)
        self._glyph_span_em = span or 1.2
        return self._glyph_span_em

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
        styled = self.SPECIAL_CHARACTER_PATTERN.sub(
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
        styled = self.INLINE_LITERAL_PATTERN.sub(
            lambda match: (
                (
                    '<span style="display: inline-block; max-width: 100%; '
                    'white-space: normal; word-break: normal; '
                    'overflow-wrap: anywhere; vertical-align: baseline;">'
                    f"{match.group(0)}</span>"
                )
                if "-" in match.group(0)
                else match.group(0)
            ),
            styled,
        )
        return self._style_cjk_runs(styled)

    def _style_cjk_runs(self, text: str) -> str:
        if not self._cjk_font_available:
            return text
        return self.CJK_RUN_PATTERN.sub(
            lambda match: (
                f'<span style="font-family: {self.CJK_FONT_FAMILY}; '
                'line-height: inherit; white-space: nowrap;">'
                f"{match.group(0)}"
                "</span>"
            ),
            text,
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
