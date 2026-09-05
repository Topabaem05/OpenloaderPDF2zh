from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf as fitz


@dataclass(slots=True)
class PdfQualitySnapshot:
    page_count: int
    image_count: int
    drawing_count: int
    link_count: int
    text_block_count: int
    protected_text: list[str]
    image_digests: list[str]
    links: list[str]


def _stable_image_digest(document: fitz.Document, xref: int) -> str:
    payload = document.extract_image(xref)
    image = payload.get("image", b"")
    if not isinstance(image, (bytes, bytearray)):
        return ""
    return hashlib.sha256(bytes(image)).hexdigest()


def inspect_pdf(
    pdf_path: str | Path,
    *,
    protected_text: Iterable[str] = (),
) -> PdfQualitySnapshot:
    path = Path(pdf_path)
    document = fitz.open(path)
    try:
        image_digests: list[str] = []
        links: list[str] = []
        drawing_count = 0
        text_block_count = 0
        all_text: list[str] = []

        seen_image_xrefs: set[int] = set()
        for page in document:
            all_text.append(page.get_text("text"))
            text_block_count += sum(
                1
                for block in page.get_text("blocks")
                if len(block) >= 7 and int(block[6]) == 0
            )
            drawing_count += len(page.get_drawings())

            for image in page.get_images(full=True):
                xref = int(image[0])
                if xref <= 0 or xref in seen_image_xrefs:
                    continue
                seen_image_xrefs.add(xref)
                digest = _stable_image_digest(document, xref)
                if digest:
                    image_digests.append(digest)

            for link in page.get_links():
                uri = link.get("uri")
                if isinstance(uri, str) and uri:
                    links.append(uri)
                    continue
                page_number = link.get("page")
                if isinstance(page_number, int) and page_number >= 0:
                    links.append(f"page:{page_number + 1}")

        joined_text = "\n".join(all_text)
        found_protected = [value for value in protected_text if value in joined_text]
        return PdfQualitySnapshot(
            page_count=len(document),
            image_count=len(image_digests),
            drawing_count=drawing_count,
            link_count=len(links),
            text_block_count=text_block_count,
            protected_text=found_protected,
            image_digests=sorted(image_digests),
            links=sorted(links),
        )
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect PDF regression-quality metrics.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--protected-text", action="append", default=[])
    args = parser.parse_args()
    snapshot = inspect_pdf(args.pdf, protected_text=args.protected_text)
    print(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
