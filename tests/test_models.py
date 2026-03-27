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


def test_translation_unit_defaults() -> None:
    unit = TranslationUnit(
        unit_id="u00001",
        page_number=1,
        label="paragraph",
        bbox=[0.0, 0.0, 10.0, 10.0],
        original="hello",
    )
    assert unit.translated == ""
