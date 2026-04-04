from __future__ import annotations

import json
from pathlib import Path

import fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.services.layout_planner import LayoutBlock, PlannedLayoutBlock
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.render_service import RenderService


class _FakePage:
    def __init__(self) -> None:
        self.insert_calls: list[dict[str, object]] = []
        self.redact_calls: list[fitz.Rect] = []
        self.redactions_applied = False
        self.transformation_matrix = fitz.Matrix(1, 1)
        self.insert_results: list[tuple[float, float]] = [(10.0, 1.0)]

    def add_redact_annot(self, rect, fill) -> None:
        self.redact_calls.append(rect)

    def apply_redactions(self) -> None:
        self.redactions_applied = True

    def insert_htmlbox(self, rect, text, **kwargs):
        self.insert_calls.append({"rect": rect, "text": text, **kwargs})
        if self.insert_results:
            return self.insert_results.pop(0)
        return (10.0, 1.0)


class _FakeDoc:
    def __init__(self, *pages: _FakePage) -> None:
        self._pages = list(pages) or [_FakePage()]
        self.saved_path: str | None = None
        self.closed = False

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]

    def save(self, path: str, **kwargs) -> None:
        self.saved_path = path
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4\n%fake\n")

    def close(self) -> None:
        self.closed = True


def _workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "workspace"
    public_dir = root / "public" / "job-1"
    parsed_dir = root / "parsed"
    output_dir = root / "output"
    logs_dir = root / "logs"
    parsed_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    public_dir.mkdir(parents=True)
    input_pdf = root / "input.pdf"
    input_pdf.write_text("pdf", encoding="utf-8")
    return JobWorkspace(
        job_id="job-1",
        root=root,
        public_dir=public_dir,
        input_pdf=input_pdf,
        parsed_dir=parsed_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        raw_json=parsed_dir / "raw.json",
        raw_markdown=parsed_dir / "raw.md",
        structured_json=output_dir / "structured.json",
        translated_markdown=output_dir / "result.md",
        translated_pdf=output_dir / "translated_mono.pdf",
        public_translated_pdf=public_dir / "translated_mono.pdf",
        detected_boxes_pdf=output_dir / "detected_boxes.pdf",
        public_detected_boxes_pdf=public_dir / "detected_boxes.pdf",
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
            provider="openrouter",
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
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert len(fake_page.insert_calls) == 3
    assert "Introduction" in fake_page.insert_calls[0]["text"]
    assert "xv" in fake_page.insert_calls[1]["text"]
    assert "." in fake_page.insert_calls[2]["text"]


def test_render_service_processes_each_page_in_multi_page_payload(
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
                                "bbox": [0, 0, 20, 10],
                                "translated": "page one",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            }
                        ],
                    },
                    {
                        "page": 2,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 20, 10],
                                "translated": "page two",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    page_one = _FakePage()
    page_two = _FakePage()
    fake_doc = _FakeDoc(page_one, page_two)
    monkeypatch.setattr(
        "openpdf2zh.services.render_service.fitz.open", lambda _: fake_doc
    )

    service = RenderService(AppSettings())
    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="openrouter",
            model="dummy-model",
        ),
        workspace,
    )

    assert overflow == 0
    assert page_one.redactions_applied is True
    assert page_two.redactions_applied is True
    assert len(page_one.insert_calls) == 1
    assert len(page_two.insert_calls) == 1
    assert "page one" in page_one.insert_calls[0]["text"]
    assert "page two" in page_two.insert_calls[0]["text"]

    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert [entry["page"] for entry in report["layout_plan"]] == [1, 2]


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
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(fake_page.insert_calls) == 2
    assert '">top</div>' in fake_page.insert_calls[0]["text"]
    assert '">bottom</div>' in fake_page.insert_calls[1]["text"]


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
            provider="openrouter",
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
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert fake_doc.closed is True
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
            provider="openrouter",
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
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert len(fake_page.insert_calls) == 2
    assert "letter-spacing:" not in fake_page.insert_calls[1]["text"]


def test_render_service_pretext_uses_planned_bbox_and_richer_report(
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
                                "bbox": [10, 10, 50, 30],
                                "translated": "Shift me",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "estimated_line_count": 1,
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

    service = RenderService(AppSettings(render_layout_engine="pretext"))
    original_rect = fitz.Rect(10, 10, 50, 30)
    planned_rect = fitz.Rect(10, 40, 50, 70)
    planned_block = PlannedLayoutBlock(
        block=LayoutBlock(
            element={"translated": "Shift me"},
            original_rect=fitz.Rect(original_rect),
            render_rect=fitz.Rect(original_rect),
            translated="Shift me",
            label="paragraph",
            font_size=12.0,
            font_name="ArialMT",
            font_family_css="'ArialMT', sans-serif",
            estimated_line_count=1,
            line_height_pt=14.0,
            letter_spacing_em=None,
            toc_page_number="",
        ),
        planned_rect=fitz.Rect(planned_rect),
        pretext_line_count=2,
        pretext_height_pt=30.0,
        render_font_size_pt=12.0,
        render_line_height_pt=14.0,
        render_letter_spacing_em=None,
        vertical_shift_pt=30.0,
        layout_engine="pretext",
        layout_fallback="none",
        scale_hint=1.0,
    )
    monkeypatch.setattr(
        service.layout_planner,
        "plan_page",
        lambda blocks, render_font_path="", fit_validator=None: [planned_block],
    )

    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert fake_page.redactions_applied is True
    assert len(fake_page.redact_calls) == 1
    assert fake_page.redact_calls[0].x0 == original_rect.x0
    assert fake_page.redact_calls[0].y0 == original_rect.y0
    assert len(fake_page.insert_calls) == 1
    assert fake_page.insert_calls[0]["rect"].x0 == planned_rect.x0
    assert fake_page.insert_calls[0]["rect"].y0 == planned_rect.y0
    assert fake_page.insert_calls[0]["rect"].y1 == planned_rect.y1
    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert report["layout_engine"] == "pretext"
    assert report["layout_plan"][0]["original_bbox"] == [10.0, 10.0, 50.0, 30.0]
    assert report["layout_plan"][0]["planned_bbox"] == [10.0, 40.0, 50.0, 70.0]
    assert report["layout_plan"][0]["layout_engine"] == "pretext"


def test_render_service_pretext_applies_adjusted_typography_and_tries_full_scale_first(
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
                                "bbox": [0, 0, 80, 20],
                                "translated": "Tight typography",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "estimated_line_count": 1,
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

    service = RenderService(AppSettings(render_layout_engine="pretext"))
    monkeypatch.setattr(
        service.layout_planner,
        "plan_page",
        lambda blocks, render_font_path="", fit_validator=None: [
            PlannedLayoutBlock(
                block=blocks[0],
                planned_rect=fitz.Rect(0, 0, 80, 26),
                pretext_line_count=2,
                pretext_height_pt=24.0,
                render_font_size_pt=11.04,
                render_line_height_pt=12.32,
                render_letter_spacing_em=-0.08,
                vertical_shift_pt=0.0,
                layout_engine="pretext",
                layout_fallback="font_scale+line_height+letter_spacing",
                scale_hint=0.92,
            )
        ],
    )

    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert len(fake_page.insert_calls) == 1
    assert fake_page.insert_calls[0]["scale_low"] == 1.0
    assert "font-size: 11.04pt" in fake_page.insert_calls[0]["text"]
    assert "line-height: 12.32pt" in fake_page.insert_calls[0]["text"]
    assert "letter-spacing: -0.08em" in fake_page.insert_calls[0]["text"]


def test_render_service_pretext_uses_pymupdf_probe_to_reject_original_typography(
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
                                "bbox": [0, 0, 80, 20],
                                "translated": "Probe-driven typography",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "estimated_line_count": 1,
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

    class _UniformMeasurementClient:
        def measure_batch(self, requests, *, render_font_path: str = ""):
            _ = render_font_path
            return {
                str(request["request_id"]): {
                    "line_count": 1,
                    "height_pt": 12.0,
                }
                for request in requests
            }

    service = RenderService(AppSettings(render_layout_engine="pretext"))
    service.layout_planner.measurement_client = _UniformMeasurementClient()
    probe_calls: list[tuple[float, float | None]] = []

    def _fake_probe(
        block,
        planned_rect,
        measurement,
        render_font_family,
        render_css,
        render_archive,
        fit_cache=None,
    ):
        _ = (block, planned_rect, render_font_family, render_css, render_archive, fit_cache)
        letter_spacing = measurement.get("letter_spacing_em")
        resolved_spacing = (
            None if letter_spacing is None else float(letter_spacing)
        )
        probe_calls.append((float(measurement["font_size_pt"]), resolved_spacing))
        return resolved_spacing is not None and resolved_spacing < 0.0

    monkeypatch.setattr(service, "_probe_pretext_html_fit", _fake_probe)

    overflow = service.render(
        PipelineRequest(
            input_pdf=workspace.input_pdf,
            target_language="English",
            provider="openrouter",
            model="nvidia/nemotron-3-super-120b-a12b:free",
        ),
        workspace,
    )

    assert overflow == 0
    assert probe_calls[0] == (12.0, None)
    assert any(call[1] is not None and call[1] < 0.0 for call in probe_calls[1:])
    assert "letter-spacing: -" in fake_page.insert_calls[0]["text"]
    assert fake_page.insert_calls[0]["scale_low"] == 1.0
