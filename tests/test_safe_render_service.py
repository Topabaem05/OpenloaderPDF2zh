from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.document.serialization import write_document_ir
from openpdf2zh.models import PipelineRequest
from openpdf2zh.services.document_builder import DocumentBuilder
from openpdf2zh.services.protection_service import ProtectionService
from openpdf2zh.services.safe_render_service import SafeRenderService
from openpdf2zh.utils.files import prepare_workspace
from tests.helpers.pdf_factory import make_redaction_stress_pdf


def _parser_bbox(page_height: float, rect: fitz.Rect) -> list[float]:
    return [rect.x0, page_height - rect.y1, rect.x1, page_height - rect.y0]


def _image_digests(page: fitz.Page) -> list[str]:
    digests: list[str] = []
    for image in page.get_image_info(hashes=True):
        digest = image.get("digest")
        if isinstance(digest, (bytes, bytearray)):
            digests.append(bytes(digest).hex())
    return sorted(digests)


def test_safe_renderer_uses_document_ir_redaction_without_damaging_pdf_objects(
    tmp_path: Path,
) -> None:
    source = make_redaction_stress_pdf(tmp_path / "source.pdf")
    workspace = prepare_workspace(tmp_path / "workspace", source, job_id="safe-render")

    original = fitz.open(workspace.input_pdf)
    page = original[0]
    text_rect = page.search_for("Translate me")[0]
    page_height = page.rect.height
    drawings_before = len(page.get_drawings())
    images_before = _image_digests(page)
    links_before = sorted(
        link.get("uri", "") for link in page.get_links() if link.get("uri")
    )
    original.close()

    parser_payload = {
        "elements": [
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [0, 0, 612, 792],
                "content": "Translate me Cp = (p-p0)/q0",
            }
        ]
    }
    document_ir = DocumentBuilder().build(workspace.input_pdf, parser_payload)
    document_ir = ProtectionService().protect_document(document_ir)
    write_document_ir(workspace.document_ir_json, document_ir)

    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": _parser_bbox(page_height, text_rect),
                                "translated": "Translated",
                                "font_name": "Helvetica-Bold",
                                "font_size": 12.0,
                                "estimated_line_count": 1,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    overflow = SafeRenderService(AppSettings()).render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="openrouter",
            model="test-model",
        ),
        workspace,
    )

    assert overflow == 0
    translated = fitz.open(workspace.translated_pdf)
    translated_page = translated[0]
    text = translated_page.get_text("text")
    assert "Translate me" not in text
    assert "Translated" in text
    assert "Cp = (p-p0)/q0" in text
    assert len(translated_page.get_drawings()) == drawings_before
    assert _image_digests(translated_page) == images_before
    assert sorted(
        link.get("uri", "")
        for link in translated_page.get_links()
        if link.get("uri")
    ) == links_before
    translated.close()

    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert report["redaction"]["redacted_runs"] >= 1
    assert report["redaction"]["restored_links"] >= 0


def test_pipeline_uses_safe_renderer() -> None:
    from openpdf2zh.pipeline import PipelineRunner

    runner = PipelineRunner(AppSettings())

    assert isinstance(runner.renderer, SafeRenderService)
