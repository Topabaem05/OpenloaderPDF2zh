import json
from pathlib import Path

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.services.translation_service import TranslationService
from openpdf2zh.utils.files import prepare_workspace


class _StubTranslator:
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        return f"translated:{text}"


def test_translate_document_writes_progress_entries_to_run_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    workspace.raw_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "items": [
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [0, 0, 120, 44],
                                "font": "NanumMyeongjo",
                                "font size": 18.5,
                                "content": "hello",
                            },
                            {
                                "type": "list item",
                                "page": 1,
                                "bbox": [10, 52, 140, 120],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "● alpha entry ● beta entry",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    service = TranslationService(AppSettings())
    monkeypatch.setattr(
        service, "_build_translator", lambda provider: _StubTranslator()
    )

    units = service.translate_document(
        PipelineRequest(
            input_pdf=source_pdf,
            target_language="English",
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(units) == 3
    assert units[0].font_name == "NanumMyeongjo"
    assert units[0].font_size == 18.5
    assert units[0].estimated_line_count == 2
    assert units[0].line_height_pt is not None
    assert units[1].label == "list item"
    assert units[1].original == "● alpha entry"
    assert units[2].original == "● beta entry"
    assert units[1].bbox[3] == 120.0
    assert units[2].bbox[1] == 52.0
    structured = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
    assert structured["pages"][0]["elements"][0]["font_name"] == "NanumMyeongjo"
    assert structured["pages"][0]["elements"][0]["font_size"] == 18.5
    assert structured["pages"][0]["elements"][1]["content"] == "● alpha entry"
    assert structured["pages"][0]["elements"][2]["content"] == "● beta entry"
    assert structured["pages"][0]["elements"][1]["line_height_pt"] is not None
    log_text = workspace.run_log.read_text(encoding="utf-8")
    assert "translation=extracted_units total=3 provider=openrouter" in log_text
    assert "translation=progress current=1/3 page=1 unit_id=u00001" in log_text
    assert "translation=progress current=3/3 page=1 unit_id=u00003" in log_text
    assert "translation=artifacts:done" in log_text
