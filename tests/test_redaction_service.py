from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from tests.helpers.pdf_factory import make_redaction_stress_pdf


def _run_for_text(page: fitz.Page, text: str, *, translatable: bool, reason: str = ""):
    from openpdf2zh.document.ir import DocumentRun, TextStyle

    rects = page.search_for(text)
    assert rects, f"text not found: {text}"
    rect = rects[0]
    return DocumentRun(
        run_id=f"run-{text[:6]}",
        kind="formula" if reason == "formula" else "text",
        text=text,
        bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
        char_bboxes=[],
        style=TextStyle(font_name="Helvetica", font_size=11.0, color=0),
        translatable=translatable,
        protection_reason=reason,
    )


def _image_digests(page: fitz.Page) -> list[str]:
    digests: list[str] = []
    for image in page.get_image_info(hashes=True):
        digest = image.get("digest")
        if isinstance(digest, (bytes, bytearray)):
            digests.append(bytes(digest).hex())
    return sorted(digests)


def test_redaction_preserves_graphics_images_links_and_protected_formula(
    tmp_path: Path,
) -> None:
    from openpdf2zh.services.redaction_service import RedactionService

    source_path = make_redaction_stress_pdf(tmp_path / "source.pdf")
    document = fitz.open(source_path)
    page = document[0]

    drawings_before = len(page.get_drawings())
    images_before = _image_digests(page)
    links_before = sorted(
        link.get("uri", "") for link in page.get_links() if link.get("uri")
    )

    runs = [
        _run_for_text(page, "Translate me", translatable=True),
        _run_for_text(page, "Cp = (p-p0)/q0", translatable=False, reason="formula"),
    ]

    result = RedactionService().redact_runs(page, runs)
    output_path = tmp_path / "redacted.pdf"
    document.save(output_path)
    document.close()

    redacted = fitz.open(output_path)
    result_page = redacted[0]
    result_text = result_page.get_text("text")

    assert "Translate me" not in result_text
    assert "Cp = (p-p0)/q0" in result_text
    assert len(result_page.get_drawings()) == drawings_before
    assert _image_digests(result_page) == images_before
    assert sorted(
        link.get("uri", "") for link in result_page.get_links() if link.get("uri")
    ) == links_before
    assert result.redacted_run_count == 1
    assert result.skipped_protected_count == 1

    redacted.close()
