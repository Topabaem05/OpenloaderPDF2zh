from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import warnings
import time
from pathlib import Path

import fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.utils.files import (
    append_run_log,
    copy_first_matching,
    run_log_heartbeat,
)


class HybridBackendManager:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._process: subprocess.Popen[str] | None = None
        self._signature: tuple[bool, str] | None = None
        atexit.register(self.stop)

    def ensure_running(self, *, force_ocr: bool, ocr_langs: str) -> None:
        if not self.settings.manage_hybrid_backend:
            return

        signature = (force_ocr, ocr_langs.strip())
        if (
            self._process
            and self._process.poll() is None
            and self._signature == signature
        ):
            return

        self.stop()
        cmd = [
            "opendataloader-pdf-hybrid",
            "--port",
            str(self.settings.hybrid_port),
        ]
        if force_ocr:
            cmd.append("--force-ocr")
            if ocr_langs.strip():
                cmd.extend(["--ocr-lang", ocr_langs.strip()])

        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        )
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Hybrid backend executable 'opendataloader-pdf-hybrid' was not found. "
                "Install opendataloader-pdf[hybrid], start it manually, or disable managed mode."
            ) from exc

        self._signature = signature
        if not wait_for_port(
            "127.0.0.1", self.settings.hybrid_port, timeout_seconds=30.0
        ):
            self.stop()
            raise RuntimeError(
                "Hybrid backend did not become ready. Start it manually or disable managed mode."
            )

    def stop(self) -> None:
        if not self._process:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._signature = None


def wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.5)
    return False


class ParserService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.backend = HybridBackendManager(settings)

    def parse(
        self, request: PipelineRequest, workspace: JobWorkspace
    ) -> tuple[Path, Path]:
        hybrid_backend = self.settings.hybrid_backend

        if request.force_ocr and hybrid_backend == "off":
            raise RuntimeError(
                "Force OCR requires a hybrid backend. Set OPENPDF2ZH_HYBRID_BACKEND to docling-fast."
            )

        append_run_log(
            workspace.run_log,
            f"parser=starting hybrid_backend={hybrid_backend} force_ocr={request.force_ocr}",
        )

        with run_log_heartbeat(workspace.run_log, "parse"):
            if request.force_ocr:
                self.backend.ensure_running(force_ocr=True, ocr_langs=request.ocr_langs)
            elif self.settings.manage_hybrid_backend and hybrid_backend != "off":
                try:
                    self.backend.ensure_running(
                        force_ocr=False, ocr_langs=request.ocr_langs
                    )
                except RuntimeError as exc:
                    hybrid_backend = "off"
                    warning_message = (
                        "Hybrid backend is unavailable; falling back to Java-only parsing. "
                        "Install opendataloader-pdf[hybrid], start it manually, or set OPENPDF2ZH_HYBRID_BACKEND=off."
                    )
                    warnings.warn(
                        f"{warning_message} Detail: {exc}", RuntimeWarning, stacklevel=2
                    )
                    append_run_log(workspace.run_log, f"warning={warning_message}")

            try:
                import opendataloader_pdf
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "opendataloader-pdf is not installed in the active Python environment. "
                    "Run 'python -m pip install -e .' from the repository root and try again."
                ) from exc

            hybrid_fallback = hybrid_backend != "off" and not request.force_ocr
            hybrid_timeout = None
            if hybrid_backend != "off" and self.settings.hybrid_timeout_ms > 0:
                hybrid_timeout = str(self.settings.hybrid_timeout_ms)
            append_run_log(
                workspace.run_log,
                "parser=convert "
                f"hybrid={hybrid_backend} hybrid_fallback={hybrid_fallback} "
                f"hybrid_timeout_ms={hybrid_timeout or 'off'}",
            )
            try:
                opendataloader_pdf.convert(
                    input_path=str(workspace.input_pdf),
                    output_dir=str(workspace.parsed_dir),
                    format="json,markdown",
                    hybrid=hybrid_backend,
                    hybrid_url=f"http://127.0.0.1:{self.settings.hybrid_port}",
                    hybrid_timeout=hybrid_timeout,
                    hybrid_fallback=hybrid_fallback,
                )
            except subprocess.CalledProcessError as exc:
                if hybrid_backend == "off" or request.force_ocr:
                    raise RuntimeError(
                        "OpenDataLoader parsing failed. Check the parser output above for details."
                    ) from exc

                warning_message = (
                    "Hybrid parsing failed; retrying with Java-only mode. "
                    "The document will continue without AI backend enrichment."
                )
                warnings.warn(
                    f"{warning_message} Detail: {exc}", RuntimeWarning, stacklevel=2
                )
                append_run_log(workspace.run_log, f"warning={warning_message}")
                opendataloader_pdf.convert(
                    input_path=str(workspace.input_pdf),
                    output_dir=str(workspace.parsed_dir),
                    format="json,markdown",
                    hybrid="off",
                )

            append_run_log(workspace.run_log, "parser=convert:done")

            copy_first_matching(workspace.parsed_dir, workspace.raw_json, [".json"])
            copy_first_matching(
                workspace.parsed_dir, workspace.raw_markdown, [".md", ".markdown"]
            )
            append_run_log(workspace.run_log, "parser=artifacts:done")
            try:
                self._build_detected_boxes_preview(workspace)
            except Exception as exc:
                warning_message = (
                    "Detected text boxes preview could not be generated. "
                    "Translation will continue without the parser box preview."
                )
                warnings.warn(
                    f"{warning_message} Detail: {exc}", RuntimeWarning, stacklevel=2
                )
                append_run_log(workspace.run_log, f"warning={warning_message}")
        return workspace.raw_json, workspace.raw_markdown

    def _build_detected_boxes_preview(self, workspace: JobWorkspace) -> Path:
        payload = json.loads(workspace.raw_json.read_text(encoding="utf-8"))
        document = fitz.open(str(workspace.input_pdf))

        for entry in self._iter_detected_boxes(payload):
            page_index = entry["page_number"] - 1
            if page_index < 0 or page_index >= len(document):
                continue
            page = document[page_index]
            rect = self._pdf_bbox_to_rect(page, entry["bbox"])
            color = self._box_color(entry["label"])
            page.draw_rect(rect, color=color, width=1.1, overlay=True)

        document.save(
            str(workspace.detected_boxes_pdf),
            garbage=4,
            deflate=True,
            clean=True,
        )
        append_run_log(
            workspace.run_log,
            f"parser=detected_boxes_preview {workspace.detected_boxes_pdf}",
        )
        return workspace.detected_boxes_pdf

    def _iter_detected_boxes(self, payload: object) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                label = str(node.get("type", node.get("label", ""))).strip().lower()
                bbox = node.get("bounding box", node.get("bbox"))
                page_number = node.get("page number", node.get("page"))
                if (
                    label in {"paragraph", "heading", "caption", "list item"}
                    and isinstance(page_number, int)
                    and isinstance(bbox, list)
                    and len(bbox) == 4
                ):
                    entries.append(
                        {
                            "label": label,
                            "page_number": page_number,
                            "bbox": [float(value) for value in bbox],
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return entries

    def _box_color(self, label: str) -> tuple[float, float, float]:
        return {
            "paragraph": (0.12, 0.49, 0.95),
            "heading": (0.87, 0.29, 0.25),
            "caption": (0.14, 0.64, 0.31),
            "list item": (0.78, 0.45, 0.1),
        }.get(label, (0.5, 0.5, 0.5))

    def _pdf_bbox_to_rect(self, page: fitz.Page, bbox: list[float]) -> fitz.Rect:
        left, bottom, right, top = [float(value) for value in bbox]
        matrix = page.transformation_matrix
        point_a = fitz.Point(left, top) * matrix
        point_b = fitz.Point(right, bottom) * matrix
        return fitz.Rect(
            min(point_a.x, point_b.x),
            min(point_a.y, point_b.y),
            max(point_a.x, point_b.x),
            max(point_a.y, point_b.y),
        )
