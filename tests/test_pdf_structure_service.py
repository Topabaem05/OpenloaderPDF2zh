from __future__ import annotations

from pathlib import Path

from tests.helpers.pdf_factory import (
    make_figure_pdf,
    make_link_pdf,
    make_rich_text_pdf,
    make_vector_table_pdf,
)


def test_pdf_structure_service_module_exists() -> None:
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "openpdf2zh"
        / "services"
        / "pdf_structure_service.py"
    )
    assert module_path.is_file()


def test_extract_preserves_native_text_span_styles(tmp_path: Path) -> None:
    from openpdf2zh.services.pdf_structure_service import PdfStructureService

    structure = PdfStructureService().extract(make_rich_text_pdf(tmp_path / "rich.pdf"))
    spans = structure.pages[0].spans

    normal = next(span for span in spans if span.text == "Normal ")
    bold = next(span for span in spans if span.text == "Bold")
    italic = next(span for span in spans if span.text == "Italic")
    superscript = next(span for span in spans if span.text == "2")

    assert normal.style.bold is False
    assert bold.style.bold is True
    assert italic.style.italic is True
    assert superscript.style.superscript is True
    assert len(normal.chars) == len(normal.text)
    assert all(len(char.bbox) == 4 for char in normal.chars)


def test_extract_preserves_images_drawings_tables_and_links(tmp_path: Path) -> None:
    from openpdf2zh.services.pdf_structure_service import PdfStructureService

    service = PdfStructureService()
    figure = service.extract(make_figure_pdf(tmp_path / "figure.pdf"))
    table = service.extract(make_vector_table_pdf(tmp_path / "table.pdf"))
    linked = service.extract(make_link_pdf(tmp_path / "link.pdf"))

    assert len(figure.pages[0].images) == 1
    assert figure.pages[0].images[0].digest

    assert len(table.pages[0].drawings) >= 6
    assert len(table.pages[0].tables) == 1
    assert table.pages[0].tables[0].row_count == 2
    assert table.pages[0].tables[0].column_count == 2
    assert len(table.pages[0].tables[0].cells) == 4

    assert len(linked.pages[0].links) == 1
    assert linked.pages[0].links[0].uri == "https://openai.com/"


def test_extract_reports_page_geometry(tmp_path: Path) -> None:
    from openpdf2zh.services.pdf_structure_service import PdfStructureService

    structure = PdfStructureService().extract(make_rich_text_pdf(tmp_path / "page.pdf"))
    page = structure.pages[0]

    assert page.page_number == 1
    assert page.width == 612.0
    assert page.height == 792.0
