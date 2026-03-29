import subprocess
import sys
import types
from pathlib import Path

import fitz
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.services.parser_service import ParserService
from openpdf2zh.utils.files import prepare_workspace


class _PreviewPage:
    def __init__(self) -> None:
        self.transformation_matrix = fitz.Matrix(1, 1)
        self.rectangles: list[
            tuple[fitz.Rect, tuple[float, float, float], float, bool]
        ] = []

    def draw_rect(self, rect, color, width, overlay) -> None:
        self.rectangles.append((rect, color, width, overlay))


class _PreviewDoc:
    def __init__(self, page_count: int = 1) -> None:
        self.pages = [_PreviewPage() for _ in range(page_count)]
        self.saved_path: str | None = None

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> _PreviewPage:
        return self.pages[index]

    def save(self, path: str, **kwargs) -> None:
        self.saved_path = path


def test_parser_service_convert_uses_java_only_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_convert(
        *,
        input_path: str,
        output_dir: str,
        format: str,
        hybrid: str,
    ) -> None:
        captured["input_path"] = input_path
        captured["output_dir"] = output_dir
        captured["format"] = format
        captured["hybrid"] = hybrid
        parsed_dir = Path(output_dir)
        (parsed_dir / "result.json").write_text("{}", encoding="utf-8")
        (parsed_dir / "result.md").write_text("# parsed\n", encoding="utf-8")

    monkeypatch.setitem(
        sys.modules, "opendataloader_pdf", types.SimpleNamespace(convert=fake_convert)
    )

    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    parser = ParserService(AppSettings())
    request = PipelineRequest(
        input_pdf=source_pdf,
        target_language="English",
        provider="ctranslate2",
        model="nvidia/nemotron-3-super-120b-a12b:free",
    )

    parser.parse(request, workspace)

    assert captured["input_path"] == str(workspace.input_pdf)
    assert captured["output_dir"] == str(workspace.parsed_dir)
    assert captured["format"] == "json,markdown"
    assert captured["hybrid"] == "off"


def test_parser_service_surfaces_convert_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_convert(**kwargs) -> None:
        raise subprocess.CalledProcessError(1, ["opendataloader-pdf"])

    monkeypatch.setitem(
        sys.modules, "opendataloader_pdf", types.SimpleNamespace(convert=fake_convert)
    )

    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    parser = ParserService(AppSettings())
    request = PipelineRequest(
        input_pdf=source_pdf,
        target_language="English",
        provider="ctranslate2",
        model="nvidia/nemotron-3-super-120b-a12b:free",
    )

    with pytest.raises(RuntimeError, match="OpenDataLoader parsing failed"):
        parser.parse(request, workspace)


def test_build_detected_boxes_preview_creates_overlay_pdf(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    workspace.raw_json.write_text(
        '{"pages": [{"page": 1, "items": ['
        '{"type": "paragraph", "page": 1, "bbox": [0, 0, 10, 10], "content": "hello"},'
        '{"type": "heading", "page": 1, "bbox": [10, 10, 20, 20], "content": "title"}]}]}',
        encoding="utf-8",
    )
    preview_doc = _PreviewDoc()
    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.fitz.open", lambda _: preview_doc
    )

    parser = ParserService(AppSettings())
    output_path = parser._build_detected_boxes_preview(workspace)

    assert output_path == workspace.detected_boxes_pdf
    assert preview_doc.saved_path == str(workspace.detected_boxes_pdf)
    assert len(preview_doc.pages[0].rectangles) == 2


def test_build_detected_boxes_preview_deduplicates_near_identical_boxes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    workspace.raw_json.write_text(
        '{"pages": [{"page": 1, "items": ['
        '{"type": "paragraph", "page": 1, "bbox": [0, 0, 12, 12], "content": "hello world"},'
        '{"type": "paragraph", "page": 1, "bbox": [0.4, 0.4, 11.8, 11.8], "content": "hello"},'
        '{"type": "heading", "page": 1, "bbox": [20, 20, 30, 30], "content": "title"}]}]}',
        encoding="utf-8",
    )
    preview_doc = _PreviewDoc()
    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.fitz.open", lambda _: preview_doc
    )

    parser = ParserService(AppSettings())
    parser._build_detected_boxes_preview(workspace)

    assert len(preview_doc.pages[0].rectangles) == 2


def test_build_detected_boxes_preview_respects_duplicate_thresholds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    workspace.raw_json.write_text(
        '{"pages": [{"page": 1, "items": ['
        '{"type": "paragraph", "page": 1, "bbox": [0, 0, 12, 12], "content": "hello world"},'
        '{"type": "paragraph", "page": 1, "bbox": [0.3, 0.3, 12.3, 12.3], "content": "hello"}]}]}',
        encoding="utf-8",
    )
    preview_doc = _PreviewDoc()
    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.fitz.open", lambda _: preview_doc
    )

    parser = ParserService(
        AppSettings(
            duplicate_box_iou_threshold=0.995,
            duplicate_box_iom_threshold=0.995,
        )
    )
    parser._build_detected_boxes_preview(workspace)

    assert len(preview_doc.pages[0].rectangles) == 2


def test_build_detected_boxes_preview_keeps_nested_boxes_with_different_scale(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    workspace.raw_json.write_text(
        '{"pages": [{"page": 1, "items": ['
        '{"type": "paragraph", "page": 1, "bbox": [0, 0, 30, 30], "content": "hello world"},'
        '{"type": "paragraph", "page": 1, "bbox": [5, 5, 15, 15], "content": "hello world"}]}]}',
        encoding="utf-8",
    )
    preview_doc = _PreviewDoc()
    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.fitz.open", lambda _: preview_doc
    )

    parser = ParserService(AppSettings())
    parser._build_detected_boxes_preview(workspace)

    assert len(preview_doc.pages[0].rectangles) == 2
