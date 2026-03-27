import sys
import subprocess
import types
from pathlib import Path

import fitz
import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.models import PipelineRequest
from openpdf2zh.services.parser_service import HybridBackendManager, ParserService
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


def test_hybrid_backend_manager_raises_actionable_error_when_binary_missing(
    monkeypatch,
) -> None:
    def fake_popen(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.subprocess.Popen", fake_popen
    )

    manager = HybridBackendManager(AppSettings())

    with pytest.raises(RuntimeError, match=r"opendataloader-pdf\[hybrid\]"):
        manager.ensure_running(force_ocr=False, ocr_langs="ko,en")


def test_parser_service_falls_back_to_java_only_when_backend_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, str] = {}

    def fake_popen(*args, **kwargs):
        raise FileNotFoundError("missing")

    def fake_convert(
        *,
        input_path: str,
        output_dir: str,
        format: str,
        hybrid: str,
        hybrid_url: str | None = None,
        hybrid_timeout: str | None = None,
        hybrid_fallback: bool = False,
    ) -> None:
        captured["hybrid"] = hybrid
        parsed_dir = Path(output_dir)
        (parsed_dir / "result.json").write_text("{}", encoding="utf-8")
        (parsed_dir / "result.md").write_text("# parsed\n", encoding="utf-8")

    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.subprocess.Popen", fake_popen
    )
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
        provider="libretranslate",
        model="libretranslate",
        force_ocr=False,
        ocr_langs="ko,en,ch_sim",
    )

    with pytest.warns(RuntimeWarning, match="falling back to Java-only parsing"):
        parser.parse(request, workspace)

    assert captured["hybrid"] == "off"
    assert "warning=Hybrid backend is unavailable" in workspace.run_log.read_text(
        encoding="utf-8"
    )


def test_parser_service_retries_java_only_after_hybrid_convert_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    class _AliveProcess:
        def poll(self):
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int) -> None:
            return None

    def fake_popen(*args, **kwargs):
        return _AliveProcess()

    def fake_wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
        return True

    def fake_convert(
        *,
        input_path: str,
        output_dir: str,
        format: str,
        hybrid: str,
        hybrid_url: str | None = None,
        hybrid_timeout: str | None = None,
        hybrid_fallback: bool = False,
    ) -> None:
        calls.append(
            {
                "hybrid": hybrid,
                "hybrid_url": hybrid_url,
                "hybrid_timeout": hybrid_timeout,
                "hybrid_fallback": hybrid_fallback,
            }
        )
        if hybrid != "off":
            raise subprocess.CalledProcessError(1, ["opendataloader-pdf"])

        parsed_dir = Path(output_dir)
        (parsed_dir / "result.json").write_text("{}", encoding="utf-8")
        (parsed_dir / "result.md").write_text("# parsed\n", encoding="utf-8")

    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.wait_for_port", fake_wait_for_port
    )
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
        provider="libretranslate",
        model="libretranslate",
        force_ocr=False,
        ocr_langs="ko,en,ch_sim",
    )

    with pytest.warns(RuntimeWarning, match="retrying with Java-only mode"):
        parser.parse(request, workspace)

    assert calls == [
        {
            "hybrid": "docling-fast",
            "hybrid_url": "http://127.0.0.1:5002",
            "hybrid_timeout": "120000",
            "hybrid_fallback": True,
        },
        {
            "hybrid": "off",
            "hybrid_url": None,
            "hybrid_timeout": None,
            "hybrid_fallback": False,
        },
    ]
    assert (
        "warning=Hybrid parsing failed; retrying with Java-only mode."
        in workspace.run_log.read_text(encoding="utf-8")
    )


def test_parser_service_force_ocr_requires_available_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_popen(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(
        "openpdf2zh.services.parser_service.subprocess.Popen", fake_popen
    )

    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_text("fake pdf", encoding="utf-8")
    workspace = prepare_workspace(tmp_path / "workspace", source_pdf)
    parser = ParserService(AppSettings())
    request = PipelineRequest(
        input_pdf=source_pdf,
        target_language="English",
        provider="libretranslate",
        model="libretranslate",
        force_ocr=True,
        ocr_langs="ko,en,ch_sim",
    )

    with pytest.raises(RuntimeError, match=r"opendataloader-pdf\[hybrid\]"):
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
