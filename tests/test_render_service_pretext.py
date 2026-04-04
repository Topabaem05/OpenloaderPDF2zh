from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.layout_planner import LayoutBlock, LayoutPlanner, PlannedLayoutBlock
from openpdf2zh.services.render_service import RenderService


class _FakePage:
    def __init__(self) -> None:
        self.insert_calls: list[dict[str, object]] = []
        self.redact_calls: list[fitz.Rect] = []
        self.redactions_applied = False
        self.transformation_matrix = fitz.Matrix(1, 1)
        self.insert_results: list[tuple[float, float]] = [(12.0, 1.0)]

    def add_redact_annot(self, rect: fitz.Rect, fill) -> None:
        self.redact_calls.append(fitz.Rect(rect))

    def apply_redactions(self) -> None:
        self.redactions_applied = True

    def insert_htmlbox(self, rect: fitz.Rect, text: str, **kwargs):
        self.insert_calls.append({"rect": fitz.Rect(rect), "text": text, **kwargs})
        if self.insert_results:
            return self.insert_results.pop(0)
        return (12.0, 1.0)


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
        output_path.write_bytes(b"pdf")

    def close(self) -> None:
        self.closed = True


def _workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "workspace"
    public_dir = root / "public"
    parsed_dir = root / "parsed"
    output_dir = root / "output"
    logs_dir = root / "logs"
    public_dir.mkdir(parents=True)
    parsed_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
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


def _request(workspace: JobWorkspace) -> PipelineRequest:
    return PipelineRequest(
        input_pdf=workspace.input_pdf,
        target_language="English",
        provider="openrouter",
        model="dummy-model",
    )


def test_pretext_planner_shifts_only_within_same_column_cluster() -> None:
    class _FakeMeasurementClient:
        def measure_batch(self, requests, *, render_font_path: str = ""):
            _ = render_font_path
            results = {}
            for request in requests:
                text = str(request.get("text", ""))
                request_id = str(request["request_id"])
                scale_hint = float(request_id.rsplit(":", 1)[-1])
                if text == "text-b0001":
                    height_pt = 30.0
                    line_count = 2
                elif text == "text-b0002":
                    height_pt = 12.0
                    line_count = 1
                else:
                    height_pt = 18.0
                    line_count = 1
                results[request_id] = {
                    "line_count": line_count,
                    "height_pt": height_pt,
                    "scale_hint": scale_hint,
                }
            return results

    planner = LayoutPlanner(
        AppSettings(render_layout_engine="pretext"),
        measurement_client=_FakeMeasurementClient(),
    )
    blocks = [
        LayoutBlock(
            element={},
            original_rect=fitz.Rect(0, 0, 100, 20),
            render_rect=fitz.Rect(0, 0, 100, 20),
            translated="text-b0001",
            label="paragraph",
            font_size=10.0,
            font_name="ArialMT",
            font_family_css="'ArialMT', sans-serif",
            estimated_line_count=1,
            line_height_pt=12.0,
            letter_spacing_em=None,
            toc_page_number="",
        ),
        LayoutBlock(
            element={},
            original_rect=fitz.Rect(0, 15, 100, 35),
            render_rect=fitz.Rect(0, 15, 100, 35),
            translated="text-b0002",
            label="paragraph",
            font_size=10.0,
            font_name="ArialMT",
            font_family_css="'ArialMT', sans-serif",
            estimated_line_count=1,
            line_height_pt=12.0,
            letter_spacing_em=None,
            toc_page_number="",
        ),
        LayoutBlock(
            element={},
            original_rect=fitz.Rect(140, 15, 240, 35),
            render_rect=fitz.Rect(140, 15, 240, 35),
            translated="text-b0003",
            label="paragraph",
            font_size=10.0,
            font_name="ArialMT",
            font_family_css="'ArialMT', sans-serif",
            estimated_line_count=1,
            line_height_pt=12.0,
            letter_spacing_em=None,
            toc_page_number="",
        ),
    ]

    planned = planner.plan_page(blocks)
    planned_by_text = {item.block.translated: item for item in planned}

    assert planned_by_text["text-b0001"].vertical_shift_pt == 0.0
    assert planned_by_text["text-b0002"].vertical_shift_pt > 0.0
    assert planned_by_text["text-b0003"].vertical_shift_pt == 0.0
    for item in planned:
        assert item.planned_rect.x0 == item.block.render_rect.x0
        assert item.planned_rect.x1 == item.block.render_rect.x1


def test_render_pretext_uses_original_bbox_for_redaction_and_planned_bbox_for_render(
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
                                "bbox": [0, 0, 100, 20],
                                "translated": "expanded block",
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
    def _fake_plan_page(
        blocks: list[LayoutBlock],
        *,
        render_font_path: str = "",
        fit_validator=None,
    ) -> list[PlannedLayoutBlock]:
        _ = (render_font_path, fit_validator)
        block = blocks[0]
        planned_rect = fitz.Rect(
            block.render_rect.x0,
            block.render_rect.y0,
            block.render_rect.x1,
            block.render_rect.y0 + 34.0,
        )
        return [
            PlannedLayoutBlock(
                block=block,
                planned_rect=planned_rect,
                pretext_line_count=3,
                pretext_height_pt=34.0,
                render_font_size_pt=12.0,
                render_line_height_pt=14.0,
                render_letter_spacing_em=None,
                vertical_shift_pt=0.0,
                layout_engine="pretext",
                layout_fallback="none",
                scale_hint=1.0,
            )
        ]

    monkeypatch.setattr(
        service.layout_planner,
        "plan_page",
        _fake_plan_page,
    )

    overflow = service.render(_request(workspace), workspace)

    assert overflow == 0
    assert fake_page.redactions_applied is True
    assert len(fake_page.redact_calls) == 1
    assert len(fake_page.insert_calls) == 1

    redaction_rect = fake_page.redact_calls[0]
    insert_rect = fake_page.insert_calls[0]["rect"]
    assert redaction_rect.x0 == 0
    assert redaction_rect.x1 == 100
    assert redaction_rect.y1 == 20
    assert insert_rect.x0 == redaction_rect.x0
    assert insert_rect.x1 == redaction_rect.x1
    assert insert_rect.y0 == redaction_rect.y0
    assert insert_rect.y1 > redaction_rect.y1

    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert report["layout_engine"] == "pretext"
    assert report["layout_plan"][0]["original_bbox"] == [0.0, 0.0, 100.0, 20.0]
    assert report["layout_plan"][0]["planned_bbox"][3] > 20.0


def test_render_pretext_mode_requires_helper_when_unavailable(
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
                                "translated": "needs helper",
                                "font_name": "ArialMT",
                                "font_size": 10.0,
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

    service = RenderService(
        AppSettings(
            render_layout_engine="pretext",
            pretext_helper_path=str(tmp_path / "missing-helper.py"),
        )
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.render(_request(workspace), workspace)

    message = str(exc_info.value)
    assert "Pretext helper script was not found" in message


def test_render_pretext_overflow_blocks_are_reported_without_rendering(
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
                                "bbox": [0, 0, 100, 20],
                                "translated": "overflow block",
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

    def _fake_plan_page(
        blocks: list[LayoutBlock],
        *,
        render_font_path: str = "",
        fit_validator=None,
    ) -> list[PlannedLayoutBlock]:
        _ = (render_font_path, fit_validator)
        return [
            PlannedLayoutBlock(
                block=blocks[0],
                planned_rect=fitz.Rect(0, 0, 100, 28),
                actual_render_bbox=None,
                pretext_line_count=2,
                pretext_height_pt=28.0,
                render_font_size_pt=12.0,
                render_line_height_pt=14.0,
                render_letter_spacing_em=None,
                vertical_shift_pt=0.0,
                top_delta_pt=0.0,
                bottom_delta_pt=0.0,
                final_scale_used=0.0,
                layout_engine="pretext",
                layout_fallback="postpass_overlap_overflow",
                planner_candidate_reason="none",
                post_render_overlap_pt=6.0,
                scale_hint=1.0,
            )
        ]

    monkeypatch.setattr(service.layout_planner, "plan_page", _fake_plan_page)

    overflow = service.render(_request(workspace), workspace)

    assert overflow == 1
    assert fake_page.redact_calls == []
    assert fake_page.insert_calls == []
    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert report["overflow"][0]["fallback_reason"] == "postpass_overlap_overflow"
    assert report["overflow"][0]["post_render_overlap_pt"] == 6.0


def test_render_pretext_processes_each_page_in_multi_page_payload(
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
                                "bbox": [0, 0, 100, 20],
                                "translated": "first pretext page",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "line_height_pt": 14.0,
                            }
                        ],
                    },
                    {
                        "page": 2,
                        "elements": [
                            {
                                "label": "paragraph",
                                "bbox": [0, 0, 100, 20],
                                "translated": "second pretext page",
                                "font_name": "ArialMT",
                                "font_size": 12.0,
                                "line_height_pt": 14.0,
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

    service = RenderService(AppSettings(render_layout_engine="pretext"))

    def _fake_plan_page(
        blocks: list[LayoutBlock],
        *,
        render_font_path: str = "",
        fit_validator=None,
    ) -> list[PlannedLayoutBlock]:
        _ = (render_font_path, fit_validator)
        return [
            PlannedLayoutBlock(
                block=block,
                planned_rect=fitz.Rect(block.render_rect),
                pretext_line_count=1,
                pretext_height_pt=block.render_rect.height,
                render_font_size_pt=block.font_size,
                render_line_height_pt=block.line_height_pt,
                render_letter_spacing_em=block.letter_spacing_em,
                vertical_shift_pt=0.0,
                layout_engine="pretext",
                layout_fallback="none",
                scale_hint=1.0,
            )
            for block in blocks
        ]

    monkeypatch.setattr(service.layout_planner, "plan_page", _fake_plan_page)

    overflow = service.render(_request(workspace), workspace)

    assert overflow == 0
    assert page_one.redactions_applied is True
    assert page_two.redactions_applied is True
    assert len(page_one.insert_calls) == 1
    assert len(page_two.insert_calls) == 1
    assert "first pretext page" in page_one.insert_calls[0]["text"]
    assert "second pretext page" in page_two.insert_calls[0]["text"]

    report = json.loads(workspace.render_report_json.read_text(encoding="utf-8"))
    assert [entry["page"] for entry in report["layout_plan"]] == [1, 2]
