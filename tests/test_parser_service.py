from __future__ import annotations

import json
from pathlib import Path

import fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace
from openpdf2zh.services.parser_service import ParserService


class _FakePage:
    def __init__(self) -> None:
        self.transformation_matrix = fitz.Matrix(1, 1)
        self.draw_calls: list[fitz.Rect] = []

    def draw_rect(self, rect: fitz.Rect, **kwargs) -> None:
        _ = kwargs
        self.draw_calls.append(fitz.Rect(rect))


class _FakeDoc:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        self.closed = False
        self.saved_path: str | None = None

    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> _FakePage:
        return self._page

    def save(self, path: str, **kwargs) -> None:
        _ = kwargs
        self.saved_path = path
        Path(path).write_bytes(b"%PDF-1.4\n%fake\n")

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
        translated_markdown=output_dir / "translated.md",
        translated_pdf=output_dir / "translated.pdf",
        public_translated_pdf=public_dir / "translated.pdf",
        detected_boxes_pdf=output_dir / "detected_boxes.pdf",
        public_detected_boxes_pdf=public_dir / "detected_boxes.pdf",
        translation_units_jsonl=output_dir / "translation_units.jsonl",
        render_report_json=output_dir / "render_report.json",
        run_log=logs_dir / "run.log",
    )


def test_build_detected_boxes_preview_closes_document(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.raw_json.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "elements": [
                            {
                                "label": "paragraph",
                                "page": 1,
                                "bbox": [0, 20, 100, 0],
                                "content": "hello",
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
        "openpdf2zh.services.parser_service.fitz.open",
        lambda _: fake_doc,
    )

    service = ParserService(AppSettings())

    preview_path = service._build_detected_boxes_preview(workspace)

    assert preview_path == workspace.detected_boxes_pdf
    assert fake_doc.closed is True
    assert fake_doc.saved_path == str(workspace.detected_boxes_pdf)
    assert len(fake_page.draw_calls) == 1
