import json
from pathlib import Path

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.services.translation_service import TranslationService
from openpdf2zh.utils.files import prepare_workspace


class _StubTranslator:
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        return f"translated:{text}"


class _RepeatingTranslator:
    def translate(self, text: str, *, target_language: str, model: str) -> str:
        return "tttttttttttttttt"


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


def test_translate_document_splits_toc_rows_into_title_units(
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
                        "page": 5,
                        "items": [
                            {
                                "type": "paragraph",
                                "page": 5,
                                "bbox": [72.598, 451.929, 240.604, 501.355],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "About the Author . . . . ix Acknowledgments . . . . xi Foreword . . . . xiii",
                            }
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

    assert [unit.original for unit in units] == [
        "About the Author",
        "Acknowledgments",
        "Foreword",
    ]
    assert [unit.toc_page_number for unit in units] == ["ix", "xi", "xiii"]
    structured = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
    assert structured["pages"][0]["elements"][0]["toc_page_number"] == "ix"
    assert structured["pages"][0]["elements"][1]["toc_page_number"] == "xi"


def test_translate_document_deduplicates_near_identical_units(
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
                                "bbox": [0, 0, 120, 40],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "hello world",
                            },
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [2, 2, 122, 42],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "hello",
                            },
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [0, 60, 120, 90],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "kept second block",
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

    assert [unit.original for unit in units] == ["hello world", "kept second block"]
    structured = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
    assert [element["content"] for element in structured["pages"][0]["elements"]] == [
        "hello world",
        "kept second block",
    ]


def test_translate_document_respects_duplicate_thresholds(
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
                                "bbox": [0, 0, 120, 40],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "hello world",
                            },
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [2, 2, 122, 42],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "hello",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    service = TranslationService(
        AppSettings(
            duplicate_box_iou_threshold=0.995,
            duplicate_box_iom_threshold=0.995,
        )
    )
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

    assert [unit.original for unit in units] == ["hello world", "hello"]


def test_translate_document_collapses_excessive_repeated_characters(
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
                                "bbox": [0, 0, 120, 40],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "original",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    service = TranslationService(AppSettings())
    monkeypatch.setattr(
        service, "_build_translator", lambda provider: _RepeatingTranslator()
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

    assert units[0].translated == "t"
    structured = json.loads(workspace.structured_json.read_text(encoding="utf-8"))
    assert structured["pages"][0]["elements"][0]["translated"] == "t"


def test_translate_document_keeps_nested_boxes_with_different_scale(
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
                                "bbox": [0, 0, 160, 60],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "same content",
                            },
                            {
                                "type": "paragraph",
                                "page": 1,
                                "bbox": [20, 15, 70, 35],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "same content",
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

    assert len(units) == 2


def test_translate_document_splits_wide_explicit_multiline_boxes(
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
                                "bbox": [0, 0, 220, 60],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "짧은 제목\n짧은 부제",
                            }
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

    assert [unit.original for unit in units] == ["짧은 제목", "짧은 부제"]
    assert units[0].bbox[1] > units[1].bbox[3]


def test_translate_document_keeps_narrow_wrapped_paragraph_boxes(
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
                                "bbox": [0, 0, 72, 36],
                                "font": "ArialMT",
                                "font size": 12.0,
                                "content": "이것은 비교적 긴 문장입니다\n좁은 폭에서 줄바꿈됩니다",
                            }
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

    assert len(units) == 1
    assert units[0].original == "이것은 비교적 긴 문장입니다\n좁은 폭에서 줄바꿈됩니다"
