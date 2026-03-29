import json
from pathlib import Path

import fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.render_service import RenderService


class _FakePage:
    def __init__(self) -> None:
        self.insert_calls: list[dict[str, object]] = []
        self.redactions_applied = False
        self.transformation_matrix = fitz.Matrix(1, 1)
        self.insert_results: list[tuple[float, float]] = [(10.0, 1.0)]

    def add_redact_annot(self, rect, fill) -> None:
        return None

    def apply_redactions(self) -> None:
        self.redactions_applied = True

    def insert_htmlbox(self, rect, text, **kwargs):
        self.insert_calls.append({"rect": rect, "text": text, **kwargs})
        if self.insert_results:
            return self.insert_results.pop(0)
        return (10.0, 1.0)


class _FakeDoc:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.saved_path: str | None = None

    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> _FakePage:
        return self._page

    def save(self, path: str, **kwargs) -> None:
        self.saved_path = path


def _workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "workspace"
    parsed_dir = root / "parsed"
    output_dir = root / "output"
    logs_dir = root / "logs"
    parsed_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    input_pdf = root / "input.pdf"
    input_pdf.write_text("pdf", encoding="utf-8")
    return JobWorkspace(
        job_id="job-1",
        root=root,
        input_pdf=input_pdf,
        parsed_dir=parsed_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        raw_json=parsed_dir / "raw.json",
        raw_markdown=parsed_dir / "raw.md",
        structured_json=output_dir / "structured.json",
        translated_markdown=output_dir / "result.md",
        translated_pdf=output_dir / "translated_mono.pdf",
        detected_boxes_pdf=output_dir / "detected_boxes.pdf",
        translation_units_jsonl=output_dir / "translation_units.jsonl",
        render_report_json=output_dir / "render_report.json",
        run_log=logs_dir / "run.log",
    )


def test_render_service_uses_element_font_size_and_custom_font(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 10, 10],
                                "translated": "Hello world again forever",
                                "font_name": "ArialMT",
                                "font_size": 18.5,
                                "estimated_line_count": 2,
                                "line_height_pt": 24.0,
                                "letter_spacing_em": 0.08,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    font_path = tmp_path / "Custom.ttf"
    font_path.write_bytes(b"dummy-font")
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)

    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings(render_font_path=str(font_path)))
    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            font_size=10.0,
        ),
        workspace,
    )

    assert overflow == 0
    assert fake_page.redactions_applied is True
    assert len(fake_page.insert_calls) == 1
    call = fake_page.insert_calls[0]
    assert "font-size: 18.5pt" in call["text"]
    assert 'style="font-family: ' in call["text"]
    assert "font-family: 'customrenderfont', sans-serif" in call["text"]
    assert "line-height: 24.0pt" in call["text"]
    assert "letter-spacing: 0.08em" in call["text"]
    assert "1. Hello<br/>2. World" not in call["text"]
    assert "Hello world again forever" in call["text"]
    assert call["scale_low"] == 1.0
    assert call["rect"].x0 < 0
    assert call["rect"].x1 > 10
    assert call["rect"].y1 > 10
    assert "@font-face" in call["css"]
    assert call["archive"] is not None
    assert fake_doc.saved_path == str(workspace.translated_pdf)


def test_render_service_styles_special_characters_with_explicit_font_size() -> None:
    service = RenderService(AppSettings())

    html_block = service._build_html(
        "● Hello",
        "list item",
        10.394,
        None,
        "ArialMT",
        1,
        12.0,
        None,
    )

    assert "font-size: 10.394pt" in html_block
    assert "Noto Sans Symbols 2" in html_block
    assert ">●</span> Hello" in html_block


def test_render_service_renders_toc_entry_as_title_leader_and_page(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 120, 12],
                                "translated": "Introduction",
                                "toc_page_number": "xv",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "line_height_pt": 14.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert len(fake_page.insert_calls) == 3
    assert "Introduction" in fake_page.insert_calls[0]["text"]
    assert "xv" in fake_page.insert_calls[1]["text"]
    assert "." in fake_page.insert_calls[2]["text"]


def test_render_service_sorts_paragraph_boxes_in_reading_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 10, 10],
                                "translated": "bottom",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                            {
                                "label": "paragraph",
                                "bbox": [0, 20, 10, 30],
                                "translated": "top",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(fake_page.insert_calls) == 2
    assert '">top</div>' in fake_page.insert_calls[0]["text"]
    assert '">bottom</div>' in fake_page.insert_calls[1]["text"]


def test_render_service_sanitizes_invalid_font_family() -> None:
    service = RenderService(AppSettings())

    assert service._normalize_font_family("><") == "sans-serif"
    assert service._normalize_font_family("ArialMT") == "'ArialMT', sans-serif"
    assert service._resolve_font_family_css("><", "ArialMT") == "'ArialMT', sans-serif"
    assert service._resolve_font_family_css("><", "><") == "sans-serif"


def test_render_service_retries_with_full_shrink_after_initial_overflow(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 10, 10],
                                "translated": "Overflow candidate",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_page.insert_results = [(-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0), (5.0, 0.42)]
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert len(fake_page.insert_calls) == 4
    assert [call["scale_low"] for call in fake_page.insert_calls] == [
        0.88,
        0.76,
        0.62,
        0.0,
    ]


def test_render_service_uses_more_conservative_scale_for_small_fonts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "list item",
                                "bbox": [0, 0, 10, 10],
                                "translated": "Compact text",
                                "font_name": "ArialMT",
                                "font_size": 10.394,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert len(fake_page.insert_calls) == 1
    assert fake_page.insert_calls[0]["scale_low"] == 0.92
    assert fake_page.insert_calls[0]["rect"].x0 == 0
    assert fake_page.insert_calls[0]["rect"].y1 == 10


def test_render_service_tightens_letter_spacing_for_overlapping_boxes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 100, 30],
                                "translated": "First block",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                            {
                                "label": "paragraph",
                                "bbox": [0, 24, 100, 54],
                                "translated": "Second block",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(fake_page.insert_calls) == 2
    assert "letter-spacing: -" in fake_page.insert_calls[1]["text"]


def test_render_service_can_disable_overlap_spacing_adjustment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.structured_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 100, 30],
                                "translated": "First block",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                            {
                                "label": "paragraph",
                                "bbox": [0, 24, 100, 54],
                                "translated": "Second block",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_page = _FakePage()
    fake_doc = _FakeDoc(fake_page)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings(adjust_render_letter_spacing_for_overlap=False))
    service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="ctranslate2",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(fake_page.insert_calls) == 2
    assert "letter-spacing:" not in fake_page.insert_calls[1]["text"]
