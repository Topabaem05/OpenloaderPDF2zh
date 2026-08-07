from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from tests.helpers.pdf_factory import make_rich_text_pdf


def test_document_builder_module_exists() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "openpdf2zh"
        / "services"
        / "document_builder.py"
    )
    assert module_path.is_file()


def _to_parser_bbox(page_height: float, rect: fitz.Rect) -> list[float]:
    return [rect.x0, page_height - rect.y1, rect.x1, page_height - rect.y0]


def test_builder_merges_semantic_region_with_native_runs(tmp_path: Path) -> None:
    from openpdf2zh.services.document_builder import DocumentBuilder

    pdf = make_rich_text_pdf(tmp_path / "rich.pdf")
    doc = fitz.open(pdf)
    page = doc[0]
    text_rect = fitz.Rect(58, 70, 200, 110)
    payload = {
        "elements": [
            {
                "type": "heading",
                "page number": 1,
                "bounding box": _to_parser_bbox(page.rect.height, text_rect),
                "content": "Normal Bold Italic x2",
            }
        ]
    }
    doc.close()

    document = DocumentBuilder().build(pdf, payload)
    paragraph = document.pages[0].paragraphs[0]

    assert paragraph.label == "heading"
    assert [run.text for run in paragraph.runs][:3] == ["Normal ", "Bold", " "]
    bold_run = next(run for run in paragraph.runs if run.text == "Bold")
    italic_run = next(run for run in paragraph.runs if run.text == "Italic")
    superscript_run = next(run for run in paragraph.runs if run.text == "2")
    assert bold_run.style.bold is True
    assert italic_run.style.italic is True
    assert superscript_run.style.superscript is True
    assert all(run.translatable for run in paragraph.runs)


def test_builder_protects_unmapped_native_text(tmp_path: Path) -> None:
    from openpdf2zh.services.document_builder import DocumentBuilder

    pdf = make_rich_text_pdf(tmp_path / "unmapped.pdf")
    document = DocumentBuilder().build(pdf, {})
    runs = [run for paragraph in document.pages[0].paragraphs for run in paragraph.runs]

    assert runs
    assert all(run.translatable is False for run in runs)
    assert {run.protection_reason for run in runs} == {"unmapped_pdf_object"}


def test_builder_prefers_specific_protected_region_over_broad_paragraph(
    tmp_path: Path,
) -> None:
    from openpdf2zh.services.document_builder import DocumentBuilder
    from openpdf2zh.services.pdf_structure_service import PdfStructureService

    pdf = make_rich_text_pdf(tmp_path / "specific.pdf")
    native = PdfStructureService().extract(pdf)
    page = native.pages[0]
    bold_span = next(span for span in page.spans if span.text == "Bold")
    all_text = fitz.Rect(
        min(span.bbox[0] for span in page.spans),
        min(span.bbox[1] for span in page.spans),
        max(span.bbox[2] for span in page.spans),
        max(span.bbox[3] for span in page.spans),
    )
    bold_rect = fitz.Rect(bold_span.bbox)
    payload = {
        "items": [
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": _to_parser_bbox(page.height, all_text),
                "content": "Normal Bold Italic x2",
            },
            {
                "type": "figure",
                "page number": 1,
                "bounding box": _to_parser_bbox(page.height, bold_rect),
                "content": "Bold",
            },
        ]
    }

    document = DocumentBuilder().build(pdf, payload)
    bold_runs = [
        run
        for paragraph in document.pages[0].paragraphs
        for run in paragraph.runs
        if run.text == "Bold"
    ]

    assert len(bold_runs) == 1
    assert bold_runs[0].translatable is False
    assert bold_runs[0].protection_reason == "semantic_figure"


def test_builder_keeps_page_geometry_and_reading_order(tmp_path: Path) -> None:
    from openpdf2zh.services.document_builder import DocumentBuilder

    pdf = make_rich_text_pdf(tmp_path / "geometry.pdf")
    document = DocumentBuilder().build(pdf, {})
    page = document.pages[0]

    assert page.width == 612.0
    assert page.height == 792.0
    assert [p.reading_order for p in page.paragraphs] == list(range(len(page.paragraphs)))
