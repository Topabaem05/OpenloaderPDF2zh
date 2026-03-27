from __future__ import annotations

import html
import json
from typing import Any

import fitz

from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class RenderService:
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
                planned: list[tuple[fitz.Rect, str, str]] = []
                for element in page_bundle.get("elements", []):
                    translated = str(element.get("translated", "")).strip()
                    bbox = element.get("bbox") or []
                    label = str(element.get("label", "text"))
                    if not translated or len(bbox) != 4:
                        continue
                    rect = self._pdf_bbox_to_rect(page, bbox)
                    planned.append((rect, translated, label))

                current_state["planned"] = len(planned)
                for rect, _, _ in planned:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                if planned:
                    page.apply_redactions()

                for rect, translated, label in planned:
                    spare_height, scale = page.insert_htmlbox(
                        rect,
                        self._build_html(translated, request.font_size),
                        scale_low=0.65,
                        opacity=1,
                        overlay=True,
                    )
                    if spare_height == -1:
                        overflow.append(
                            {
                                "page": page_index + 1,
                                "label": label,
                                "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
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
        write_json(workspace.render_report_json, {"overflow": overflow})
        append_run_log(workspace.run_log, "render=artifacts:done")
        return len(overflow)

    def _build_html(self, text: str, font_size: float) -> str:
        safe_text = html.escape(text).replace("\n", "<br/>")
        return (
            f"<div style='font-family: sans-serif; font-size: {font_size}pt; "
            "line-height: 1.2; color: #111; white-space: normal;'>"
            f"{safe_text}</div>"
        )

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
