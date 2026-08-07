from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpdf2zh.document.ir import (
    DocumentIR,
    DocumentRun,
    PageIR,
    ParagraphIR,
    TextStyle,
)
from openpdf2zh.services.pdf_structure_service import (
    PdfDocumentStructure,
    PdfStructureService,
    PdfTableObject,
    PdfTextSpan,
)

BBox = list[float]


@dataclass(slots=True)
class SemanticRegion:
    region_id: str
    page_number: int
    label: str
    bbox: BBox
    content: str
    discovery_order: int
    translatable: bool


class DocumentBuilder:
    TRANSLATABLE_LABELS = frozenset(
        {
            "paragraph",
            "heading",
            "caption",
            "list item",
            "list_item",
            "table cell",
            "table_cell",
        }
    )
    PROTECTED_LABELS = frozenset(
        {
            "figure",
            "picture",
            "image",
            "chart",
            "formula",
            "equation",
            "table",
        }
    )
    MIN_SPAN_COVERAGE = 0.5
    MIN_NATIVE_TABLE_COVERAGE = 0.5
    MIN_CELL_INSIDE_SEMANTIC_TABLE = 0.8

    def __init__(self, structure_service: PdfStructureService | None = None) -> None:
        self.structure_service = structure_service or PdfStructureService()

    def build(self, pdf_path: Path | str, opendataloader_payload: object) -> DocumentIR:
        native = self.structure_service.extract(pdf_path)
        return self.build_from_structure(native, opendataloader_payload)

    def build_from_structure(
        self,
        native: PdfDocumentStructure,
        opendataloader_payload: object,
    ) -> DocumentIR:
        regions = self._extract_semantic_regions(opendataloader_payload)
        regions_by_page: dict[int, list[SemanticRegion]] = {}
        for region in regions:
            regions_by_page.setdefault(region.page_number, []).append(region)

        run_counter = 0
        paragraph_counter = 0
        pages: list[PageIR] = []
        for native_page in native.pages:
            page_regions = [
                self._convert_region_bbox(region, native_page.height)
                for region in regions_by_page.get(native_page.page_number, [])
            ]
            page_regions.extend(
                self._promote_native_table_cells(
                    page_regions,
                    native_page.tables,
                    page_number=native_page.page_number,
                )
            )
            grouped: dict[tuple[str, int | str], list[PdfTextSpan]] = {}
            group_meta: dict[tuple[str, int | str], SemanticRegion | None] = {}
            group_order: list[tuple[str, int | str]] = []

            for span in native_page.spans:
                region = self._best_region_for_span(span, page_regions)
                if region is None:
                    key: tuple[str, int | str] = ("unmapped", span.block_number)
                else:
                    key = ("region", region.region_id)
                if key not in grouped:
                    grouped[key] = []
                    group_meta[key] = region
                    group_order.append(key)
                grouped[key].append(span)

            paragraphs: list[ParagraphIR] = []
            for reading_order, key in enumerate(group_order):
                spans = grouped[key]
                region = group_meta[key]
                paragraph_counter += 1
                paragraph_bbox = (
                    region.bbox
                    if region is not None
                    else self._union_bbox(span.bbox for span in spans)
                )
                paragraph_label = region.label if region is not None else "unmapped"
                runs: list[DocumentRun] = []
                for span in spans:
                    run_counter += 1
                    translatable, protection_reason, kind = self._run_policy(region)
                    runs.append(
                        DocumentRun(
                            run_id=f"r{run_counter:06d}",
                            kind=kind,
                            text=span.text,
                            bbox=list(span.bbox),
                            char_bboxes=[list(char.bbox) for char in span.chars],
                            style=TextStyle(
                                font_name=span.style.font_name,
                                font_size=span.style.font_size,
                                color=span.style.color,
                                bold=span.style.bold,
                                italic=span.style.italic,
                                superscript=span.style.superscript,
                            ),
                            translatable=translatable,
                            protection_reason=protection_reason,
                        )
                    )
                paragraphs.append(
                    ParagraphIR(
                        paragraph_id=f"p{paragraph_counter:06d}",
                        page_number=native_page.page_number,
                        label=paragraph_label,
                        bbox=paragraph_bbox,
                        reading_order=reading_order,
                        runs=runs,
                    )
                )

            pages.append(
                PageIR(
                    page_number=native_page.page_number,
                    width=native_page.width,
                    height=native_page.height,
                    paragraphs=paragraphs,
                )
            )
        return DocumentIR(schema_version=1, pages=pages)

    def _extract_semantic_regions(self, payload: object) -> list[SemanticRegion]:
        regions: list[SemanticRegion] = []
        seen: set[tuple[int, str, tuple[float, ...], str]] = set()
        discovery_order = 0

        def walk(node: object) -> None:
            nonlocal discovery_order
            if isinstance(node, dict):
                label = self._normalize_label(node.get("type", node.get("label", "")))
                page = node.get("page number", node.get("page"))
                bbox = node.get("bounding box", node.get("bbox"))
                content = node.get("content", "")
                if (
                    label
                    and isinstance(page, int)
                    and isinstance(bbox, list)
                    and len(bbox) == 4
                ):
                    bbox_values = tuple(float(value) for value in bbox)
                    content_text = content.strip() if isinstance(content, str) else ""
                    signature = (page, label, bbox_values, content_text)
                    if signature not in seen:
                        seen.add(signature)
                        discovery_order += 1
                        regions.append(
                            SemanticRegion(
                                region_id=f"s{discovery_order:06d}",
                                page_number=page,
                                label=label,
                                bbox=list(bbox_values),
                                content=content_text,
                                discovery_order=discovery_order,
                                translatable=label in self.TRANSLATABLE_LABELS,
                            )
                        )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return regions

    def _normalize_label(self, value: object) -> str:
        return " ".join(str(value or "").strip().lower().replace("_", " ").split())

    def _convert_region_bbox(
        self, region: SemanticRegion, page_height: float
    ) -> SemanticRegion:
        left, bottom, right, top = region.bbox
        converted = [
            float(left),
            float(page_height - top),
            float(right),
            float(page_height - bottom),
        ]
        return SemanticRegion(
            region_id=region.region_id,
            page_number=region.page_number,
            label=region.label,
            bbox=converted,
            content=region.content,
            discovery_order=region.discovery_order,
            translatable=region.translatable,
        )

    def _promote_native_table_cells(
        self,
        regions: list[SemanticRegion],
        tables: list[PdfTableObject],
        *,
        page_number: int,
    ) -> list[SemanticRegion]:
        semantic_tables = [region for region in regions if region.label == "table"]
        if not semantic_tables or not tables:
            return []

        next_order = max((region.discovery_order for region in regions), default=0) + 1
        promoted: list[SemanticRegion] = []
        for table_index, table in enumerate(tables, start=1):
            table_area = max(self._area(table.bbox), 1e-9)
            matching_tables = [
                region
                for region in semantic_tables
                if self._intersection_area(table.bbox, region.bbox) / table_area
                >= self.MIN_NATIVE_TABLE_COVERAGE
            ]
            if not matching_tables:
                continue
            semantic_table = max(
                matching_tables,
                key=lambda region: self._intersection_area(table.bbox, region.bbox),
            )

            for cell_index, cell_bbox in enumerate(table.cells, start=1):
                cell_area = self._area(cell_bbox)
                if cell_area <= 0:
                    continue
                inside_ratio = (
                    self._intersection_area(cell_bbox, semantic_table.bbox) / cell_area
                )
                if inside_ratio < self.MIN_CELL_INSIDE_SEMANTIC_TABLE:
                    continue
                promoted.append(
                    SemanticRegion(
                        region_id=(
                            f"{semantic_table.region_id}-native-table-{table_index}"
                            f"-cell-{cell_index}"
                        ),
                        page_number=page_number,
                        label="table cell",
                        bbox=list(cell_bbox),
                        content="",
                        discovery_order=next_order,
                        translatable=True,
                    )
                )
                next_order += 1
        return promoted

    def _best_region_for_span(
        self,
        span: PdfTextSpan,
        regions: list[SemanticRegion],
    ) -> SemanticRegion | None:
        scored: list[tuple[float, float, int, SemanticRegion]] = []
        span_area = max(self._area(span.bbox), 1e-9)
        for region in regions:
            intersection = self._intersection_area(span.bbox, region.bbox)
            coverage = intersection / span_area
            if coverage < self.MIN_SPAN_COVERAGE:
                continue
            scored.append(
                (
                    coverage,
                    -self._area(region.bbox),
                    -region.discovery_order,
                    region,
                )
            )
        if not scored:
            return None
        return max(scored, key=lambda item: item[:3])[3]

    def _run_policy(self, region: SemanticRegion | None) -> tuple[bool, str, str]:
        if region is None:
            return False, "unmapped_pdf_object", "text"
        if region.translatable:
            return True, "", "text"
        reason = f"semantic_{region.label.replace(' ', '_')}"
        kind = "formula" if region.label in {"formula", "equation"} else "text"
        return False, reason, kind

    def _area(self, bbox: BBox) -> float:
        return max(float(bbox[2]) - float(bbox[0]), 0.0) * max(
            float(bbox[3]) - float(bbox[1]), 0.0
        )

    def _intersection_area(self, left: BBox, right: BBox) -> float:
        width = max(min(left[2], right[2]) - max(left[0], right[0]), 0.0)
        height = max(min(left[3], right[3]) - max(left[1], right[1]), 0.0)
        return width * height

    def _union_bbox(self, boxes: Any) -> BBox:
        values = [list(box) for box in boxes]
        if not values:
            return [0.0, 0.0, 0.0, 0.0]
        return [
            min(box[0] for box in values),
            min(box[1] for box in values),
            max(box[2] for box in values),
            max(box[3] for box in values),
        ]
