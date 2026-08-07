from __future__ import annotations

import re
from dataclasses import replace

from openpdf2zh.document.ir import DocumentIR, DocumentRun, PageIR, ParagraphIR

BBox = list[float]


class ProtectionService:
    URL_PATTERN = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
    DOI_PATTERN = re.compile(
        r"(?:\bdoi:\s*)?\b10\.\d{4,9}/[-._;()/:A-Z0-9]+",
        re.IGNORECASE,
    )
    EMAIL_PATTERN = re.compile(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        re.IGNORECASE,
    )
    CITATION_PATTERNS = (
        re.compile(r"\[\d+(?:\s*[-,]\s*\d+)*\]"),
        re.compile(r"\(\d+(?:\.\d+)+\)"),
    )
    FORMULA_ASSIGNMENT_PATTERN = re.compile(
        r"\b[A-Za-z][A-Za-z0-9_]{0,12}\s*=\s*.+?"
        r"(?=\s+(?:is|are|was|were|where|when|with|and|or|for|from|which|that|then|gives|denotes)\b|[,;:]|$)",
        re.IGNORECASE,
    )
    MATH_UNICODE = frozenset("∂∇∞≤≥≈∝√∫ΣΠρμθλΔσΩαβγδεζηκνξπτφχψ")
    MATH_OPERATORS = frozenset("=+-*/^<>±×÷")

    def protect_run(self, run: DocumentRun) -> list[DocumentRun]:
        if not run.translatable or not run.text:
            return [run]

        matches = self._collect_explicit_matches(run.text)
        if matches:
            return self._split_matches(run, matches)

        if self._formula_score(run) >= 3:
            return [
                replace(
                    run,
                    kind="formula",
                    translatable=False,
                    protection_reason="formula",
                )
            ]
        return [run]

    def protect_document(self, document: DocumentIR) -> DocumentIR:
        pages: list[PageIR] = []
        for page in document.pages:
            paragraphs: list[ParagraphIR] = []
            for paragraph in page.paragraphs:
                protected_runs: list[DocumentRun] = []
                for run in paragraph.runs:
                    protected_runs.extend(self.protect_run(run))
                paragraphs.append(replace(paragraph, runs=protected_runs))
            pages.append(replace(page, paragraphs=paragraphs))
        return replace(document, pages=pages)

    def _collect_explicit_matches(self, text: str) -> list[tuple[int, int, str]]:
        candidates: list[tuple[int, int, str, int]] = []
        patterns: list[tuple[re.Pattern[str], str, int]] = [
            (self.URL_PATTERN, "url", 0),
            (self.DOI_PATTERN, "doi", 1),
            (self.EMAIL_PATTERN, "email", 2),
            (self.FORMULA_ASSIGNMENT_PATTERN, "formula", 4),
        ]
        for citation_pattern in self.CITATION_PATTERNS:
            patterns.append((citation_pattern, "citation", 3))

        for pattern, reason, priority in patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                end = self._trim_trailing_punctuation(text, start, end, reason)
                if end <= start:
                    continue
                candidates.append((start, end, reason, priority))

        candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[3]))
        selected: list[tuple[int, int, str]] = []
        occupied_until = -1
        for start, end, reason, _priority in candidates:
            if start < occupied_until:
                continue
            selected.append((start, end, reason))
            occupied_until = end
        return selected

    def _trim_trailing_punctuation(
        self,
        text: str,
        start: int,
        end: int,
        reason: str,
    ) -> int:
        if reason == "citation":
            return end
        trailing = ".,;:"
        while end > start and text[end - 1] in trailing:
            end -= 1
        return end

    def _split_matches(
        self,
        run: DocumentRun,
        matches: list[tuple[int, int, str]],
    ) -> list[DocumentRun]:
        segments: list[tuple[int, int, str | None]] = []
        cursor = 0
        for start, end, reason in matches:
            if cursor < start:
                segments.append((cursor, start, None))
            segments.append((start, end, reason))
            cursor = end
        if cursor < len(run.text):
            segments.append((cursor, len(run.text), None))

        parts: list[DocumentRun] = []
        for index, (start, end, reason) in enumerate(segments, start=1):
            text = run.text[start:end]
            if not text:
                continue
            protected = reason is not None
            part_kind = "formula" if reason == "formula" else (reason or run.kind)
            parts.append(
                replace(
                    run,
                    run_id=f"{run.run_id}-s{index:02d}",
                    kind=part_kind,
                    text=text,
                    bbox=self._segment_bbox(run, start, end),
                    char_bboxes=self._segment_char_bboxes(run, start, end),
                    translatable=not protected,
                    protection_reason=reason or "",
                )
            )
        return parts

    def _segment_char_bboxes(
        self,
        run: DocumentRun,
        start: int,
        end: int,
    ) -> list[BBox]:
        if len(run.char_bboxes) != len(run.text):
            return []
        return [list(bbox) for bbox in run.char_bboxes[start:end]]

    def _segment_bbox(self, run: DocumentRun, start: int, end: int) -> BBox:
        char_bboxes = self._segment_char_bboxes(run, start, end)
        if char_bboxes:
            return self._union_bbox(char_bboxes)

        x0, y0, x1, y1 = [float(value) for value in run.bbox]
        text_length = max(len(run.text), 1)
        width = x1 - x0
        return [
            x0 + width * (start / text_length),
            y0,
            x0 + width * (end / text_length),
            y1,
        ]

    def _formula_score(self, run: DocumentRun) -> int:
        text = run.text.strip()
        if not text or len(text) > 120:
            return 0

        score = 0
        if any(operator in text for operator in "=≤≥≈∝"):
            score += 2
        if any(char in self.MATH_UNICODE for char in text):
            score += 2

        non_space = [char for char in text if not char.isspace()]
        operator_count = sum(char in self.MATH_OPERATORS for char in non_space)
        if non_space and operator_count / len(non_space) >= 0.1:
            score += 1

        word_count = len(re.findall(r"[A-Za-z]{2,}", text))
        if word_count <= 3:
            score += 1

        normalized_font = run.style.font_name.lower()
        if any(token in normalized_font for token in ("math", "symbol", "cmmi", "cmsy")):
            score += 2
        return score

    def _union_bbox(self, boxes: list[BBox]) -> BBox:
        return [
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ]
