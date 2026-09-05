from __future__ import annotations

import base64
from pathlib import Path

import pymupdf as fitz

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwMAAAAwBAQAY5Z0AAAAASUVORK5CYII="
)


def _new_document(path: Path) -> tuple[fitz.Document, fitz.Page]:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    return document, page


def _save(document: fitz.Document, path: Path) -> Path:
    document.save(path)
    document.close()
    return path


def make_two_column_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    page.insert_textbox(
        fitz.Rect(48, 72, 282, 280),
        "Left column paragraph. " * 8,
        fontsize=10,
        fontname="Times-Roman",
    )
    page.insert_textbox(
        fitz.Rect(330, 72, 564, 280),
        "Right column paragraph. " * 8,
        fontsize=10,
        fontname="Times-Roman",
    )
    return _save(document, path)


def make_formula_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    formula = "Cp = (p-p0)/q0"
    page.insert_text((60, 100), "Pressure coefficient relation:", fontsize=11)
    page.insert_text((60, 128), formula, fontsize=12, fontname="Times-Italic")
    page.insert_text((60, 156), "is used throughout this chapter.", fontsize=11)
    return _save(document, path)


def make_rich_text_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    page.insert_htmlbox(
        fitz.Rect(60, 72, 360, 132),
        "Normal <b>Bold</b> <i>Italic</i> x<sup>2</sup>",
    )
    return _save(document, path)


def make_colored_background_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    rect = fitz.Rect(48, 72, 300, 126)
    page.draw_rect(rect, color=(0.2, 0.3, 0.6), fill=(0.9, 0.92, 0.98), width=1)
    page.insert_text((60, 104), "IMPORTANT NOTE", fontsize=12, fontname="Helvetica-Bold")
    return _save(document, path)


def make_vector_table_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    x_positions = [60, 230, 400]
    y_positions = [80, 120, 160]
    for x in x_positions:
        page.draw_line((x, y_positions[0]), (x, y_positions[-1]), width=1)
    for y in y_positions:
        page.draw_line((x_positions[0], y), (x_positions[-1], y), width=1)
    page.insert_text((72, 106), "Velocity", fontsize=10)
    page.insert_text((242, 106), "200 m/s", fontsize=10)
    page.insert_text((72, 146), "Pressure", fontsize=10)
    page.insert_text((242, 146), "101 kPa", fontsize=10)
    return _save(document, path)


def make_link_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    rect = fitz.Rect(60, 82, 240, 110)
    page.insert_text((60, 100), "OpenAI documentation", fontsize=11)
    page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://openai.com/"})
    return _save(document, path)


def make_figure_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    page.insert_image(fitz.Rect(60, 80, 160, 180), stream=_TINY_PNG)
    page.insert_text((60, 202), "Figure 1. Tiny embedded image.", fontsize=10)
    return _save(document, path)


def make_redaction_stress_pdf(path: Path) -> Path:
    document, page = _new_document(path)
    background = fitz.Rect(48, 72, 300, 128)
    page.draw_rect(
        background,
        color=(0.2, 0.3, 0.6),
        fill=(0.9, 0.92, 0.98),
        width=1,
    )
    page.draw_line((48, 145), (300, 145), width=1)
    page.draw_line((48, 170), (300, 170), width=1)
    page.insert_text((60, 104), "Translate me", fontsize=12, fontname="Helvetica-Bold")
    link_rect = fitz.Rect(58, 88, 150, 110)
    page.insert_link(
        {"kind": fitz.LINK_URI, "from": link_rect, "uri": "https://example.com/translate"}
    )
    page.insert_text((60, 158), "Cp = (p-p0)/q0", fontsize=11, fontname="Times-Italic")
    page.insert_image(fitz.Rect(340, 80, 420, 160), stream=_TINY_PNG)
    return _save(document, path)
