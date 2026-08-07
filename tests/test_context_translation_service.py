from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.document.ir import (
    DocumentIR,
    DocumentRun,
    PageIR,
    ParagraphIR,
    TextStyle,
)
from openpdf2zh.document.serialization import write_document_ir
from openpdf2zh.models import PipelineRequest
from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.services.context_translation_service import ContextTranslationService
from openpdf2zh.translation.contracts import TranslationRequestItem
from openpdf2zh.utils.files import prepare_workspace


class _CaptureTranslator(BaseTranslator):
    def __init__(self) -> None:
        self.items: list[TranslationRequestItem] = []

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        return f"{target_language}:{text}"

    def translate_many(
        self,
        items: list[TranslationRequestItem],
        *,
        model: str,
    ) -> list[str]:
        self.items.extend(items)
        return [f"KO:{item.text.strip()}" for item in items]


class _TestService(ContextTranslationService):
    def __init__(self, settings: AppSettings, translator: BaseTranslator) -> None:
        super().__init__(settings)
        self._translator = translator

    def _build_translator(self, request: PipelineRequest) -> BaseTranslator:
        _ = request
        return self._translator


def _run(
    run_id: str,
    text: str,
    bbox: list[float],
    *,
    translatable: bool = True,
    reason: str = "",
) -> DocumentRun:
    return DocumentRun(
        run_id=run_id,
        kind="formula" if reason == "formula" else "text",
        text=text,
        bbox=bbox,
        char_bboxes=[],
        style=TextStyle(font_name="Times-Roman", font_size=11.0, color=0),
        translatable=translatable,
        protection_reason=reason,
    )


def _document_ir() -> DocumentIR:
    return DocumentIR(
        schema_version=1,
        pages=[
            PageIR(
                page_number=1,
                width=300.0,
                height=400.0,
                paragraphs=[
                    ParagraphIR(
                        paragraph_id="p-heading",
                        page_number=1,
                        label="heading",
                        bbox=[40.0, 40.0, 180.0, 60.0],
                        reading_order=0,
                        runs=[_run("r-heading", "Boundary Layer", [40, 40, 120, 55])],
                    ),
                    ParagraphIR(
                        paragraph_id="p-body",
                        page_number=1,
                        label="paragraph",
                        bbox=[40.0, 80.0, 260.0, 120.0],
                        reading_order=1,
                        runs=[
                            _run("r-a", "The relation ", [40, 80, 100, 95]),
                            _run(
                                "r-formula",
                                "Cp = (p-p0)/q0",
                                [102, 80, 180, 95],
                                translatable=False,
                                reason="formula",
                            ),
                            _run("r-b", " is used here.", [182, 80, 250, 95]),
                        ],
                    ),
                ],
            )
        ],
    )


def test_context_translation_service_translates_only_translatable_runs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=300, height=400)
    document.save(source)
    document.close()
    workspace = prepare_workspace(tmp_path / "workspace", source, job_id="context")
    write_document_ir(workspace.document_ir_json, _document_ir())

    translator = _CaptureTranslator()
    service = _TestService(AppSettings(), translator)
    units = service.translate_document(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="Korean",
            provider="openrouter",
            model="test-model",
        ),
        workspace,
    )

    assert [unit.original for unit in units] == [
        "Boundary Layer",
        "The relation ",
        " is used here.",
    ]
    assert all("Cp = (p-p0)/q0" not in item.text for item in translator.items)
    body_item = next(item for item in translator.items if item.segment_id == "r-b")
    assert body_item.section_title == "Boundary Layer"
    assert body_item.previous_text == "Boundary Layer"

    structured = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
    assert structured["schema_version"] == 2
    assert structured["document_ir"] == "parsed/document_ir.json"
    contents = [
        element["content"]
        for page in structured["pages"]
        for element in page["elements"]
    ]
    assert "Cp = (p-p0)/q0" not in contents
    assert workspace.translated_markdown.is_file()
    assert workspace.translation_units_jsonl.is_file()


def test_context_translation_service_converts_native_bbox_to_parser_coordinates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    document = fitz.open()
    document.new_page(width=300, height=400)
    document.save(source)
    document.close()
    workspace = prepare_workspace(tmp_path / "workspace", source, job_id="coords")
    write_document_ir(workspace.document_ir_json, _document_ir())

    service = _TestService(AppSettings(), _CaptureTranslator())
    units = service.translate_document(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="Korean",
            provider="openrouter",
            model="test-model",
        ),
        workspace,
    )
    body = next(unit for unit in units if unit.original == "The relation ")

    assert body.bbox == [40.0, 305.0, 100.0, 320.0]


def test_pipeline_uses_context_translation_service() -> None:
    from openpdf2zh.pipeline import PipelineRunner

    runner = PipelineRunner(AppSettings())

    assert isinstance(runner.translator, ContextTranslationService)
