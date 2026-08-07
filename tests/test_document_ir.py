from __future__ import annotations

from pathlib import Path

import pytest


def test_document_ir_module_exists() -> None:
    module_path = Path(__file__).parents[1] / "src" / "openpdf2zh" / "document" / "ir.py"
    assert module_path.is_file()


def test_document_ir_exposes_rich_document_types() -> None:
    import openpdf2zh.document.ir as ir

    expected = {
        "TextStyle",
        "DocumentRun",
        "ParagraphIR",
        "PageIR",
        "DocumentIR",
    }
    assert expected.issubset(set(dir(ir)))


def test_document_ir_round_trip_preserves_run_metadata(tmp_path: Path) -> None:
    from openpdf2zh.document.ir import (
        DocumentIR,
        DocumentRun,
        PageIR,
        ParagraphIR,
        TextStyle,
    )
    from openpdf2zh.document.serialization import read_document_ir, write_document_ir

    document = DocumentIR(
        schema_version=1,
        pages=[
            PageIR(
                page_number=1,
                width=612.0,
                height=792.0,
                paragraphs=[
                    ParagraphIR(
                        paragraph_id="p0001",
                        page_number=1,
                        label="paragraph",
                        bbox=[60.0, 80.0, 300.0, 130.0],
                        reading_order=1,
                        runs=[
                            DocumentRun(
                                run_id="r0001",
                                kind="text",
                                text="Boundary layer",
                                bbox=[60.0, 80.0, 140.0, 95.0],
                                char_bboxes=[[60.0, 80.0, 66.0, 95.0]],
                                style=TextStyle(
                                    font_name="Times-Italic",
                                    font_size=11.0,
                                    color=0,
                                    bold=False,
                                    italic=True,
                                    superscript=False,
                                ),
                            ),
                            DocumentRun(
                                run_id="r0002",
                                kind="formula",
                                text="Cp = (p-p∞)/q∞",
                                bbox=[145.0, 80.0, 240.0, 95.0],
                                char_bboxes=[],
                                style=TextStyle(
                                    font_name="Times-Italic",
                                    font_size=11.0,
                                    color=0,
                                    bold=False,
                                    italic=True,
                                    superscript=False,
                                ),
                                translatable=False,
                                protection_reason="formula",
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    output = tmp_path / "document_ir.json"
    write_document_ir(output, document)
    restored = read_document_ir(output)

    assert restored == document
    assert restored.pages[0].paragraphs[0].runs[1].protection_reason == "formula"


def test_document_ir_rejects_non_positive_page_numbers() -> None:
    from openpdf2zh.document.ir import PageIR

    with pytest.raises(ValueError, match="page_number"):
        PageIR(page_number=0, width=612.0, height=792.0, paragraphs=[])


def test_workspace_exposes_document_ir_artifact(tmp_path: Path) -> None:
    import pymupdf as fitz

    from openpdf2zh.utils.files import prepare_workspace

    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page()
    document.save(source)
    document.close()

    workspace = prepare_workspace(tmp_path / "workspace", source, job_id="quality-test")

    assert workspace.document_ir_json == workspace.parsed_dir / "document_ir.json"
