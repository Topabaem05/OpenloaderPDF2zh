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
                                "bbox": [0, 0, 10, 10],
                                "content": "hello",
                            },
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [10, 10, 20, 20],
                                "content": "world",
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
            provider="libretranslate",
            model="libretranslate",
        ),
        workspace,
    )

    assert len(units) == 2
    log_text = workspace.run_log.read_text(encoding="utf-8")
    assert "translation=extracted_units total=2 provider=libretranslate" in log_text
    assert "translation=progress current=1/2 page=1 unit_id=u00001" in log_text
    assert "translation=progress current=2/2 page=1 unit_id=u00002" in log_text
    assert "translation=artifacts:done" in log_text
