from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class RenderService:
    SPECIAL_CHARACTER_PATTERN = re.compile(r"[●•▪◦■□◆◇○◎◉※★☆▶▷◀◁→←↑↓]")
    SPECIAL_CHARACTER_FONT_STACK = (
        "'Noto Sans Symbols 2', 'Segoe UI Symbol', 'Apple Symbols', sans-serif"
    )

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def render(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
    ) -> int:
        payload = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
        doc = fitz.open(str(workspace.input_pdf))
        overflow: list[dict[str, object]] = []
        page_bundles = payload.get("pages", [])
        total_pages = len(page_bundles)
        render_css, render_archive, render_font_family = self._build_render_resources()
        append_run_log(workspace.run_log, f"render=pages total={total_pages}")
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

                current_state["planned"] = len(planned)
                for rect, _, _, _, _, _, _, _, _ in planned:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                if planned:
                    page.apply_redactions()

                for (
                    rect,
                    translated,
                    label,
                    font_size,
                    font_name,
                    estimated_line_count,
                    line_height_pt,
                    letter_spacing_em,
                    toc_page_number,
                ) in planned:
                    if toc_page_number:
                        spare_height, scale = self._render_toc_entry(
                            page,
                            rect,
                            translated,
                            toc_page_number,
                            font_size,
                            render_font_family,
                            font_name,
                            render_css,
                            render_archive,
                            line_height_pt,
                        )
                    else:
                        html_block = self._build_html(
                            translated,
                            label,
                            font_size,
                            render_font_family,
                            font_name,
                            estimated_line_count,
                            line_height_pt,
                            letter_spacing_em,
                        )
                        render_rect = self._resolve_render_rect(rect, font_size)
                        spare_height, scale = self._insert_with_scale_policy(
                            page,
                            render_rect,
                            html_block,
                            render_css,
                            render_archive,
                            font_size,
                        )
                    if spare_height == -1:
                        overflow.append(
                            {
                                "page": page_index + 1,
                                "label": label,
                                "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                                "font_size": font_size,
                                "line_height_pt": line_height_pt,
                                "estimated_line_count": estimated_line_count,
                                "scale": scale,
                                "text_preview": translated[:160],
                            }
                        )
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
        shutil.copy2(workspace.translated_pdf, workspace.public_translated_pdf)
        write_json(workspace.render_report_json, {"overflow": overflow})
        append_run_log(workspace.run_log, "render=artifacts:done")
        return len(overflow)

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
    ) -> tuple[float, float]:
        for scale_low in self._scale_candidates(font_size):
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
