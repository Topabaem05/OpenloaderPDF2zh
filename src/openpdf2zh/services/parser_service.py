from __future__ import annotations

import json
import warnings
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.utils.geometry import bbox_area, bbox_area_ratio, bbox_iom, bbox_iou
from openpdf2zh.utils.files import (
    append_run_log,
    copy_first_matching,
    run_log_heartbeat,
)


class ParserService:
    DUPLICATE_BOX_AREA_RATIO_THRESHOLD = 0.8

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def parse(
        self, _request: PipelineRequest, workspace: JobWorkspace
    ) -> tuple[Path, Path]:
        append_run_log(
            workspace.run_log,
            "parser=starting",
        )

        with run_log_heartbeat(workspace.run_log, "parse"):
            try:
                import opendataloader_pdf
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "opendataloader-pdf is not installed in the active Python environment. "
                    "Run 'python -m pip install -e .' from the repository root and try again."
                ) from exc

            append_run_log(
                workspace.run_log,
                "parser=convert",
            )
            try:
                opendataloader_pdf.convert(
                    input_path=str(workspace.input_pdf),
                    output_dir=str(workspace.parsed_dir),
                    format="json,markdown",
                    hybrid="off",
                )
            except Exception as exc:
                raise RuntimeError(f"OpenDataLoader parsing failed: {exc}") from exc

            append_run_log(workspace.run_log, "parser=convert:done")

            copy_first_matching(workspace.parsed_dir, workspace.raw_json, [".json"])
            copy_first_matching(
                workspace.parsed_dir, workspace.raw_markdown, [".md", ".markdown"]
            )
            append_run_log(workspace.run_log, "parser=artifacts:done")
            try:
                self._build_detected_boxes_preview(workspace)
            except Exception as exc:
                warning_message = (
                    "Detected text boxes preview could not be generated. "
                    "Translation will continue without the parser box preview."
                )
                warnings.warn(
                    f"{warning_message} Detail: {exc}", RuntimeWarning, stacklevel=2
                )
                append_run_log(workspace.run_log, f"warning={warning_message}")
        return workspace.raw_json, workspace.raw_markdown

    def _build_detected_boxes_preview(self, workspace: JobWorkspace) -> Path:
        payload = json.loads(workspace.raw_json.read_text(encoding="utf-8"))
        document = fitz.open(str(workspace.input_pdf))

        for entry in self._iter_detected_boxes(payload):
            page_index = entry["page_number"] - 1
            if page_index < 0 or page_index >= len(document):
                continue
            page = document[page_index]
            rect = self._pdf_bbox_to_rect(page, entry["bbox"])
            color = self._box_color(entry["label"])
            page.draw_rect(rect, color=color, width=1.1, overlay=True)

        document.save(
            str(workspace.detected_boxes_pdf),
            garbage=4,
            deflate=True,
            clean=True,
        )
        append_run_log(
            workspace.run_log,
            f"parser=detected_boxes_preview {workspace.detected_boxes_pdf}",
        )
        return workspace.detected_boxes_pdf

    def _iter_detected_boxes(self, payload: object) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                label = str(node.get("type", node.get("label", ""))).strip().lower()
                bbox = node.get("bounding box", node.get("bbox"))
                page_number = node.get("page number", node.get("page"))
                if (
                    label in {"paragraph", "heading", "caption", "list item"}
                    and isinstance(page_number, int)
                    and isinstance(bbox, list)
                    and len(bbox) == 4
                ):
                    entries.append(
                        {
                            "label": label,
                            "page_number": page_number,
                            "bbox": [float(value) for value in bbox],
                            "content": (
                                node.get("content", "").strip()
                                if isinstance(node.get("content"), str)
                                else ""
                            ),
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return self._deduplicate_detected_boxes(entries)

    def _deduplicate_detected_boxes(
        self, entries: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        filtered: list[dict[str, object]] = []

        for entry in entries:
            candidate = entry
            overlapping_indexes: list[int] = []
            for index, existing in enumerate(filtered):
                if not self._is_duplicate_detected_box(candidate, existing):
                    continue
                overlapping_indexes.append(index)
                candidate = self._prefer_detected_box(existing, candidate)

            if not overlapping_indexes:
                filtered.append(candidate)
                continue

            first_index = overlapping_indexes[0]
            filtered[first_index] = candidate
            for index in reversed(overlapping_indexes[1:]):
                filtered.pop(index)

        return filtered

    def _is_duplicate_detected_box(
        self,
        entry: dict[str, object],
        existing: dict[str, object],
    ) -> bool:
        if entry["page_number"] != existing["page_number"]:
            return False
        if entry["label"] != existing["label"]:
            return False

        entry_bbox = self._entry_bbox(entry)
        existing_bbox = self._entry_bbox(existing)
        area_ratio = bbox_area_ratio(entry_bbox, existing_bbox)
        if area_ratio < self.DUPLICATE_BOX_AREA_RATIO_THRESHOLD:
            return False

        if (
            bbox_iou(entry_bbox, existing_bbox)
            >= self.settings.duplicate_box_iou_threshold
        ):
            return True

        if (
            bbox_iom(entry_bbox, existing_bbox)
            < self.settings.duplicate_box_iom_threshold
        ):
            return False

        return self._is_duplicate_content(
            str(entry.get("content", "")),
            str(existing.get("content", "")),
        )

    def _prefer_detected_box(
        self,
        existing: dict[str, object],
        candidate: dict[str, object],
    ) -> dict[str, object]:
        existing_bbox = self._entry_bbox(existing)
        candidate_bbox = self._entry_bbox(candidate)
        existing_area = bbox_area(existing_bbox)
        candidate_area = bbox_area(candidate_bbox)
        if candidate_area > existing_area:
            return candidate
        if candidate_area < existing_area:
            return existing

        if len(str(candidate.get("content", ""))) > len(
            str(existing.get("content", ""))
        ):
            return candidate
        return existing

    def _entry_bbox(self, entry: dict[str, object]) -> list[float]:
        return [float(value) for value in entry["bbox"]]

    def _is_duplicate_content(self, left: str, right: str) -> bool:
        normalized_left = self._normalize_content(left)
        normalized_right = self._normalize_content(right)
        if not normalized_left or not normalized_right:
            return True
        return (
            normalized_left == normalized_right
            or normalized_left in normalized_right
            or normalized_right in normalized_left
        )

    def _normalize_content(self, value: str) -> str:
        return " ".join(value.split()).strip().lower()

    def _box_color(self, label: str) -> tuple[float, float, float]:
        return {
            "paragraph": (0.12, 0.49, 0.95),
            "heading": (0.87, 0.29, 0.25),
            "caption": (0.14, 0.64, 0.31),
            "list item": (0.78, 0.45, 0.1),
        }.get(label, (0.5, 0.5, 0.5))

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
