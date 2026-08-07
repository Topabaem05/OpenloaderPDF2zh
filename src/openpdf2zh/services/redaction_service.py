from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pymupdf as fitz

from openpdf2zh.document.ir import DocumentRun


@dataclass(slots=True)
class RedactionResult:
    redacted_run_count: int
    skipped_protected_count: int
    restored_link_count: int


class RedactionService:
    """Remove only translatable text while preserving non-text PDF objects."""

    def redact_runs(
        self,
        page: fitz.Page,
        runs: Iterable[DocumentRun],
    ) -> RedactionResult:
        links_before = [dict(link) for link in page.get_links()]
        redacted_run_count = 0
        skipped_protected_count = 0

        for run in runs:
            if not run.translatable:
                skipped_protected_count += 1
                continue
            rect = self._rect(run.bbox)
            if rect.is_empty or rect.is_infinite:
                continue
            page.add_redact_annot(rect, fill=False, cross_out=False)
            redacted_run_count += 1

        restored_link_count = 0
        if redacted_run_count:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )
            restored_link_count = self._restore_missing_links(page, links_before)

        return RedactionResult(
            redacted_run_count=redacted_run_count,
            skipped_protected_count=skipped_protected_count,
            restored_link_count=restored_link_count,
        )

    def _restore_missing_links(
        self,
        page: fitz.Page,
        links_before: list[dict[str, object]],
    ) -> int:
        current_keys = {self._link_key(link) for link in page.get_links()}
        restored = 0
        for link in links_before:
            key = self._link_key(link)
            if key in current_keys:
                continue
            payload = self._insertable_link(link)
            if payload is None:
                continue
            page.insert_link(payload)
            current_keys.add(key)
            restored += 1
        return restored

    def _insertable_link(self, link: dict[str, object]) -> dict[str, object] | None:
        kind = link.get("kind")
        source_rect = link.get("from")
        if not isinstance(kind, int) or source_rect is None:
            return None

        payload: dict[str, object] = {
            "kind": kind,
            "from": fitz.Rect(source_rect),
        }
        for key in ("uri", "file", "page", "zoom"):
            value = link.get(key)
            if value is not None:
                payload[key] = value
        target = link.get("to")
        if target is not None:
            payload["to"] = fitz.Point(target)
        return payload

    def _link_key(self, link: dict[str, object]) -> tuple[object, ...]:
        rect = self._rect(link.get("from"))
        uri = str(link.get("uri", "") or "")
        page = link.get("page")
        target = link.get("to")
        target_tuple: tuple[float, float] | None = None
        if target is not None:
            try:
                point = fitz.Point(target)
                target_tuple = (round(point.x, 3), round(point.y, 3))
            except (TypeError, ValueError):
                target_tuple = None
        return (
            link.get("kind"),
            round(rect.x0, 3),
            round(rect.y0, 3),
            round(rect.x1, 3),
            round(rect.y1, 3),
            uri,
            page,
            target_tuple,
        )

    def _rect(self, bbox: object) -> fitz.Rect:
        try:
            return fitz.Rect(bbox)
        except (TypeError, ValueError):
            return fitz.Rect()
