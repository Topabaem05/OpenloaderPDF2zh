from __future__ import annotations

from dataclasses import dataclass, field

BBox = list[float]
ColorValue = int | tuple[int, int, int] | None


def _validate_bbox(name: str, bbox: BBox) -> None:
    if len(bbox) != 4:
        raise ValueError(f"{name} must contain exactly four coordinates")
    if float(bbox[2]) < float(bbox[0]) or float(bbox[3]) < float(bbox[1]):
        raise ValueError(f"{name} must be ordered as [x0, y0, x1, y1]")


@dataclass(slots=True)
class TextStyle:
    font_name: str = ""
    font_size: float = 0.0
    color: ColorValue = None
    bold: bool = False
    italic: bool = False
    superscript: bool = False


@dataclass(slots=True)
class DocumentRun:
    run_id: str
    kind: str
    text: str
    bbox: BBox
    char_bboxes: list[BBox]
    style: TextStyle
    translatable: bool = True
    protection_reason: str = ""

    def __post_init__(self) -> None:
        _validate_bbox("bbox", self.bbox)
        for char_bbox in self.char_bboxes:
            _validate_bbox("char_bbox", char_bbox)
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.kind.strip():
            raise ValueError("kind must not be empty")


@dataclass(slots=True)
class ParagraphIR:
    paragraph_id: str
    page_number: int
    label: str
    bbox: BBox
    reading_order: int
    runs: list[DocumentRun] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.page_number <= 0:
            raise ValueError("page_number must be positive")
        if self.reading_order < 0:
            raise ValueError("reading_order must be non-negative")
        if not self.paragraph_id.strip():
            raise ValueError("paragraph_id must not be empty")
        _validate_bbox("bbox", self.bbox)

    @property
    def original_text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(slots=True)
class PageIR:
    page_number: int
    width: float
    height: float
    paragraphs: list[ParagraphIR] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.page_number <= 0:
            raise ValueError("page_number must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("page width and height must be positive")


@dataclass(slots=True)
class DocumentIR:
    schema_version: int
    pages: list[PageIR] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
