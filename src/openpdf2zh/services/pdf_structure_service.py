from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf as fitz

BBox = list[float]


@dataclass(slots=True)
class PdfTextStyle:
    font_name: str
    font_size: float
    color: int | None
    flags: int
    bold: bool
    italic: bool
    superscript: bool
    serif: bool
    monospace: bool


@dataclass(slots=True)
class PdfCharacter:
    text: str
    bbox: BBox
    origin: tuple[float, float]


@dataclass(slots=True)
class PdfTextSpan:
    text: str
    bbox: BBox
    chars: list[PdfCharacter]
    style: PdfTextStyle
    block_number: int
    line_number: int
    span_number: int


@dataclass(slots=True)
class PdfImageObject:
    bbox: BBox
    xref: int
    digest: str
    width: int
    height: int


@dataclass(slots=True)
class PdfDrawingObject:
    bbox: BBox
    drawing_type: str
    sequence_number: int


@dataclass(slots=True)
class PdfLinkObject:
    bbox: BBox
    kind: int
    uri: str = ""
    target_page: int | None = None


@dataclass(slots=True)
class PdfTableObject:
    bbox: BBox
    cells: list[BBox]
    row_count: int
    column_count: int


@dataclass(slots=True)
class PdfPageStructure:
    page_number: int
    width: float
    height: float
    spans: list[PdfTextSpan] = field(default_factory=list)
    images: list[PdfImageObject] = field(default_factory=list)
    drawings: list[PdfDrawingObject] = field(default_factory=list)
    links: list[PdfLinkObject] = field(default_factory=list)
    tables: list[PdfTableObject] = field(default_factory=list)


@dataclass(slots=True)
class PdfDocumentStructure:
    pages: list[PdfPageStructure] = field(default_factory=list)


class PdfStructureService:
    """Extract native PDF geometry that semantic parsers commonly flatten away."""

    FONT_FLAG_SUPERSCRIPT = 1
    FONT_FLAG_ITALIC = 2
    FONT_FLAG_SERIF = 4
    FONT_FLAG_MONOSPACE = 8
    FONT_FLAG_BOLD = 16

    def extract(self, pdf_path: Path | str) -> PdfDocumentStructure:
        document = fitz.open(str(pdf_path))
        try:
            pages = [
                self._extract_page(page, page_index + 1)
                for page_index, page in enumerate(document)
            ]
            return PdfDocumentStructure(pages=pages)
        finally:
            document.close()

    def _extract_page(self, page: fitz.Page, page_number: int) -> PdfPageStructure:
        return PdfPageStructure(
            page_number=page_number,
            width=float(page.rect.width),
            height=float(page.rect.height),
            spans=self._extract_spans(page),
            images=self._extract_images(page),
            drawings=self._extract_drawings(page),
            links=self._extract_links(page),
            tables=self._extract_tables(page),
        )

    def _extract_spans(self, page: fitz.Page) -> list[PdfTextSpan]:
        payload = page.get_text("rawdict")
        spans: list[PdfTextSpan] = []
        blocks = payload.get("blocks", []) if isinstance(payload, dict) else []
        for block_number, block in enumerate(blocks):
            if not isinstance(block, dict) or int(block.get("type", -1)) != 0:
                continue
            for line_number, line in enumerate(block.get("lines", [])):
                if not isinstance(line, dict):
                    continue
                for span_number, span in enumerate(line.get("spans", [])):
                    if not isinstance(span, dict):
                        continue
                    chars = self._extract_characters(span.get("chars", []))
                    text = "".join(char.text for char in chars)
                    if not text:
                        continue
                    flags = int(span.get("flags", 0))
                    spans.append(
                        PdfTextSpan(
                            text=text,
                            bbox=self._bbox(span.get("bbox")),
                            chars=chars,
                            style=PdfTextStyle(
                                font_name=str(span.get("font", "")),
                                font_size=float(span.get("size", 0.0)),
                                color=(
                                    int(span["color"])
                                    if isinstance(span.get("color"), int)
                                    else None
                                ),
                                flags=flags,
                                bold=bool(flags & self.FONT_FLAG_BOLD),
                                italic=bool(flags & self.FONT_FLAG_ITALIC),
                                superscript=bool(flags & self.FONT_FLAG_SUPERSCRIPT),
                                serif=bool(flags & self.FONT_FLAG_SERIF),
                                monospace=bool(flags & self.FONT_FLAG_MONOSPACE),
                            ),
                            block_number=block_number,
                            line_number=line_number,
                            span_number=span_number,
                        )
                    )
        return spans

    def _extract_characters(self, raw_chars: object) -> list[PdfCharacter]:
        if not isinstance(raw_chars, list):
            return []
        chars: list[PdfCharacter] = []
        for raw_char in raw_chars:
            if not isinstance(raw_char, dict):
                continue
            text = raw_char.get("c")
            if not isinstance(text, str):
                continue
            origin = raw_char.get("origin", (0.0, 0.0))
            if not isinstance(origin, (tuple, list)) or len(origin) != 2:
                origin = (0.0, 0.0)
            chars.append(
                PdfCharacter(
                    text=text,
                    bbox=self._bbox(raw_char.get("bbox")),
                    origin=(float(origin[0]), float(origin[1])),
                )
            )
        return chars

    def _extract_images(self, page: fitz.Page) -> list[PdfImageObject]:
        images: list[PdfImageObject] = []
        for image in page.get_image_info(hashes=True, xrefs=True):
            if not isinstance(image, dict):
                continue
            digest = image.get("digest", b"")
            if isinstance(digest, (bytes, bytearray)):
                digest_text = bytes(digest).hex()
            else:
                digest_text = str(digest or "")
            images.append(
                PdfImageObject(
                    bbox=self._bbox(image.get("bbox")),
                    xref=int(image.get("xref", 0)),
                    digest=digest_text,
                    width=int(image.get("width", 0)),
                    height=int(image.get("height", 0)),
                )
            )
        return images

    def _extract_drawings(self, page: fitz.Page) -> list[PdfDrawingObject]:
        drawings: list[PdfDrawingObject] = []
        raw_drawings = page.get_cdrawings()
        for index, drawing in enumerate(raw_drawings):
            if not isinstance(drawing, dict):
                continue
            drawings.append(
                PdfDrawingObject(
                    bbox=self._bbox(drawing.get("rect")),
                    drawing_type=str(drawing.get("type", "")),
                    sequence_number=int(drawing.get("seqno", index)),
                )
            )
        return drawings

    def _extract_links(self, page: fitz.Page) -> list[PdfLinkObject]:
        links: list[PdfLinkObject] = []
        for link in page.get_links():
            if not isinstance(link, dict):
                continue
            target_page = link.get("page")
            links.append(
                PdfLinkObject(
                    bbox=self._bbox(link.get("from")),
                    kind=int(link.get("kind", 0)),
                    uri=str(link.get("uri", "") or ""),
                    target_page=(
                        int(target_page) + 1
                        if isinstance(target_page, int) and target_page >= 0
                        else None
                    ),
                )
            )
        return links

    def _extract_tables(self, page: fitz.Page) -> list[PdfTableObject]:
        try:
            finder = page.find_tables()
        except (AttributeError, RuntimeError, ValueError):
            return []
        tables: list[PdfTableObject] = []
        for table in getattr(finder, "tables", []):
            cells: list[BBox] = []
            for cell in getattr(table, "cells", []):
                if cell is None:
                    continue
                cells.append(self._bbox(cell))
            tables.append(
                PdfTableObject(
                    bbox=self._bbox(getattr(table, "bbox", None)),
                    cells=cells,
                    row_count=int(getattr(table, "row_count", 0)),
                    column_count=int(getattr(table, "col_count", 0)),
                )
            )
        return tables

    def _bbox(self, value: Any) -> BBox:
        if isinstance(value, fitz.Rect):
            return [float(value.x0), float(value.y0), float(value.x1), float(value.y1)]
        if isinstance(value, (tuple, list)) and len(value) == 4:
            return [float(item) for item in value]
        return [0.0, 0.0, 0.0, 0.0]
