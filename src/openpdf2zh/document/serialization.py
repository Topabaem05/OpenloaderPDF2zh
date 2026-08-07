from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openpdf2zh.document.ir import (
    DocumentIR,
    DocumentRun,
    PageIR,
    ParagraphIR,
    TextStyle,
)


def document_ir_to_dict(document: DocumentIR) -> dict[str, Any]:
    return asdict(document)


def _style_from_dict(payload: dict[str, Any]) -> TextStyle:
    color = payload.get("color")
    if isinstance(color, list) and len(color) == 3:
        color = tuple(int(value) for value in color)
    return TextStyle(
        font_name=str(payload.get("font_name", "")),
        font_size=float(payload.get("font_size", 0.0)),
        color=color,
        bold=bool(payload.get("bold", False)),
        italic=bool(payload.get("italic", False)),
        superscript=bool(payload.get("superscript", False)),
    )


def _run_from_dict(payload: dict[str, Any]) -> DocumentRun:
    style_payload = payload.get("style")
    if not isinstance(style_payload, dict):
        style_payload = {}
    return DocumentRun(
        run_id=str(payload["run_id"]),
        kind=str(payload["kind"]),
        text=str(payload.get("text", "")),
        bbox=[float(value) for value in payload["bbox"]],
        char_bboxes=[
            [float(value) for value in char_bbox]
            for char_bbox in payload.get("char_bboxes", [])
        ],
        style=_style_from_dict(style_payload),
        translatable=bool(payload.get("translatable", True)),
        protection_reason=str(payload.get("protection_reason", "")),
    )


def _paragraph_from_dict(payload: dict[str, Any]) -> ParagraphIR:
    return ParagraphIR(
        paragraph_id=str(payload["paragraph_id"]),
        page_number=int(payload["page_number"]),
        label=str(payload.get("label", "text")),
        bbox=[float(value) for value in payload["bbox"]],
        reading_order=int(payload.get("reading_order", 0)),
        runs=[_run_from_dict(run) for run in payload.get("runs", [])],
    )


def document_ir_from_dict(payload: dict[str, Any]) -> DocumentIR:
    pages: list[PageIR] = []
    for page in payload.get("pages", []):
        pages.append(
            PageIR(
                page_number=int(page["page_number"]),
                width=float(page["width"]),
                height=float(page["height"]),
                paragraphs=[
                    _paragraph_from_dict(paragraph)
                    for paragraph in page.get("paragraphs", [])
                ],
            )
        )
    return DocumentIR(schema_version=int(payload["schema_version"]), pages=pages)


def write_document_ir(path: Path, document: DocumentIR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document_ir_to_dict(document), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_document_ir(path: Path) -> DocumentIR:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Document IR root must be a JSON object")
    return document_ir_from_dict(payload)
