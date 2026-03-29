from pathlib import Path

from openpdf2zh.models import PipelineRequest, TranslationUnit


def test_pipeline_request_fields() -> None:
    request = PipelineRequest(
        input_pdf=Path("sample.pdf"),
        target_language="Simplified Chinese",
        provider="openrouter",
        model="openrouter/auto",
    )
    assert request.input_pdf.name == "sample.pdf"
    assert request.target_language == "Simplified Chinese"
    assert request.page_limit is None


def test_translation_unit_defaults() -> None:
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=1,
        label="paragraph",
        bbox=[0.0, 0.0, 10.0, 10.0],
        original="hello",
    )
    assert unit.translated == ""
    assert unit.font_size is None
    assert unit.font_name == ""
    assert unit.estimated_line_count == 1
    assert unit.line_height_pt is None
    assert unit.letter_spacing_em is None
