from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, ClassVar

import pymupdf as fitz

from openpdf2zh.config import OPENROUTER_PROVIDER, AppSettings, normalize_provider
from openpdf2zh.models import JobWorkspace, PipelineRequest, TranslationUnit
from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.providers.ctranslate2 import CTranslate2Translator
from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.services.usage_quota import QuotaLease
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json
from openpdf2zh.utils.geometry import bbox_area, bbox_area_ratio, bbox_iom, bbox_iou


class TranslationService:
    DUPLICATE_BOX_AREA_RATIO_THRESHOLD = 0.8
    EXPLICIT_LINE_SPLIT_MAX_SEGMENTS = 4
    EXPLICIT_LINE_SPLIT_WIDTH_RATIO = 1.45
    EXPLICIT_LINE_SPLIT_HEIGHT_RATIO = 1.75
    EXCESSIVE_REPEAT_PATTERN = re.compile(r"([^\s])\1{9,}")
    EXCESSIVE_FRAGMENT_PATTERN = re.compile(r"([A-Za-z가-힣]{2,4})\1{4,}")
    EXCESSIVE_SPACED_TOKEN_PATTERN = re.compile(r"\b([A-Za-z가-힣])(?:\s+\1){4,}\b")
    EXCESSIVE_SPACED_FRAGMENT_PATTERN = re.compile(
        r"(?<!\S)([A-Za-z가-힣]{2,30})(?:\s+\1){3,}(?!\S)",
        re.IGNORECASE,
    )
    TARGET_SCRIPT_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
    SUSPICIOUS_TRANSLATION_PATTERN = re.compile(
        r"관련검색|검색사이트|다운로드|브랜드명|상품명|정 피곤|욕구알아보기|가필니다|e-도서|publication",
        re.IGNORECASE,
    )
    TOC_LEADER_PATTERN = re.compile(
        r"(?P<leader>(?:\.\s*){4,}|(?:·\s*){4,}|(?:․\s*){4,})(?P<page>[A-Za-z0-9ivxlcdmIVXLCDM]+)"
    )
    TOC_TRAILING_PAGE_PATTERN = re.compile(
        r"^(?P<title>.+?)\s+(?P<page>\d{1,4}|[ivxlcdmIVXLCDM]{1,8})$"
    )
    SOURCE_TOC_ROW_PATTERN = re.compile(
        r"^(?P<title>.+?)(?:(?:\.\s*){2,}|\s{2,})"
        r"(?P<page>\d{1,4}|[ivxlcdmIVXLCDM]{1,8})\s*$"
    )
    SECTION_ITEM_PATTERN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?=\s)")
    CHAPTER_ONLY_PATTERN = re.compile(r"^Chapter\s+(?P<number>\d+)\s*$", re.IGNORECASE)
    CHAPTER_TITLE_PATTERN = re.compile(
        r"^(?P<prefix>Chapter\s+\d+)(?P<title>\s*[A-Z].+)$",
        re.IGNORECASE,
    )
    PART_ONLY_PATTERN = re.compile(r"^PART\s*$", re.IGNORECASE)
    LITERAL_CONTACT_PATTERN = re.compile(
        r"^(?:"
        r"(?:https?://|www\.)\S+|"
        r"(?:Twitter|LinkedIn|YouTube|Facebook|Instagram):\s*\S+|"
        r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}/\S+|"
        r"\S+@\S+\.\S+|"
        r"(?:ISBN|ISSN)\b.*|"
        r"\d[\d\s()+-]{5,}(?:\s*\([^)]*\))?|"
        r"\d+\s+.+\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|highway|hwy\.?|"
        r"boulevard|blvd\.?|lane|ln\.?|drive|dr\.?)\b.*|"
        r"[^,]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?|"
        r".+,\s*(?:Inc\.?|LLC|Ltd\.?|Corp\.?)"
        r")$",
        re.IGNORECASE,
    )
    INLINE_LITERAL_PATTERN = re.compile(
        r"https?://[^\s)\]}]+|"
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
        r"(?<![A-Za-z0-9_])@[A-Za-z0-9_]+"
    )
    DISCRETIONARY_HYPHEN_PATTERN = re.compile(
        r"(?<=[A-Za-z])[\u00ad\u2010]\s+(?=[A-Za-z])"
    )
    RETRY_SEGMENT_PATTERN = re.compile(
        r"(?<=[.!?])\s+(?=[A-Z])|(?<=:)\s+(?=[A-Z])"
    )
    CODE_LITERAL_PATTERN = re.compile(
        r'^\s*(?:[$#>]\s|\[[^\]]+@[^\]]+\]\s*[$#]|"[^"\n]+"\s*:|'
        r"[-dlcbps][rwx-]{9}\b|/(?:[A-Za-z0-9._-]+/?)+|"
        r"(?:[│├└┌┐┬─]+\s*)+\S+)"
    )
    MONOSPACE_FONT_PATTERN = re.compile(
        r"(?:mono|courier|consolas|menlo|sourcecode|codepro)",
        re.IGNORECASE,
    )
    TABLE_LABELS = frozenset({"table cell", "table header"})
    TABLE_LITERAL_PATTERN = re.compile(
        r"[0-9A-Za-z_.,:;+*/^=<>%|(){}\[\]\\\-\s~∼≤≥≈]+"
    )
    TABLE_STRATEGIES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("lines", "lines"),
        ("lines_strict", "lines_strict"),
        ("text", "lines"),
        ("lines", "text"),
        ("text", "text"),
    )
    STRUCTURAL_TRANSLATIONS: ClassVar[dict[str, str]] = {
        "acknowledgments": "감사의 글",
        "administration": "관리",
        "constant width": "고정폭",
        "constant width italic": "고정폭 기울임꼴",
        "conventions used in this book": "이 책의 표기 규칙",
        "directory description": "디렉터리 설명",
        "execute": "실행",
        "group": "그룹",
        "how to contact us": "문의 방법",
        "italic": "기울임꼴",
        "navigating this book": "이 책의 구성",
        "numerical value": "수치 값",
        "o’reilly online learning": "O’Reilly 온라인 학습",
        "other": "기타",
        "permission mode": "권한 모드",
        "preface": "서문",
        "read": "읽기",
        "revision history for the first edition": "초판 개정 이력",
        "table of contents": "목차",
        "user": "사용자",
        "using code examples": "코드 예제 사용",
        "write": "쓰기",
    }
    FALLBACK_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
        ("Integrated Work Challenge:", "통합 과제:"),
        ("Applied Aerodynamics:", "응용 공기역학:"),
        ("Historical Note:", "역사적 참고:"),
        ("Models of the Fluid:", "유체 모델:"),
        ("Shock-Expansion Theory:", "충격-팽창 이론:"),
        ("Airplane Lift and Drag", "비행기 양력과 항력"),
        ("The Flow over a Sphere—The Real Case", "구 주위의 흐름 - 실제 사례"),
        ("The Flow over a Sphere-The Real Case", "구 주위의 흐름 - 실제 사례"),
        (
            "Relation Between Aerodynamic Drag and the Loss of Total Pressure in the Flow Field",
            "공력 항력과 유동장 전체 압력 손실의 관계",
        ),
        ("Control Volumes and Fluid Elements", "제어 체적과 유체 요소"),
        ("Applications to Supersonic Airfoils", "초음속 에어포일에 대한 적용"),
        ("Comments", "논평"),
        ("Comment", "논평"),
        ("Summary", "요약"),
        ("Problems", "문제"),
        ("Introduction and Road Map", "소개 및 로드맵"),
        ("Introduction", "소개"),
    )

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def translate_document(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
        quota_guard: QuotaLease | None = None,
    ) -> list[TranslationUnit]:
        raw_data = json.loads(workspace.raw_json.read_text(encoding="utf-8"))
        table_diagnostics: list[dict[str, object]] = []
        units = self._postprocess_units(
            self._restore_source_rows(
                self._extract_units(raw_data),
                workspace.input_pdf,
                table_diagnostics=table_diagnostics,
            )
        )
        translator = self._build_translator(request)
        total_units = len(units)
        append_run_log(
            workspace.run_log,
            f"translation=extracted_units total={total_units} provider={request.provider}",
        )
        append_run_log(
            workspace.run_log,
            "translation=table_cells "
            f"pages={len(table_diagnostics)} "
            f"accepted_tables={sum(int(item['accepted_tables']) for item in table_diagnostics)} "
            f"nonempty_cells={sum(int(item['nonempty_cells']) for item in table_diagnostics)}",
        )
        current_state = {
            "index": 0,
            "total": total_units,
            "page": "-",
            "unit_id": "-",
        }

        iterable: Iterable[TranslationUnit]
        if progress is not None and hasattr(progress, "tqdm"):
            iterable = progress.tqdm(
                units,
                desc="Translating text blocks",
                total=len(units),
                unit="block",
            )
        else:
            iterable = units

        def heartbeat_context() -> str:
            return (
                f"current={current_state['index']}/{current_state['total']} "
                f"page={current_state['page']} unit_id={current_state['unit_id']}"
            )

        with run_log_heartbeat(
            workspace.run_log,
            "translate",
            context_provider=heartbeat_context,
        ):
            for index, unit in enumerate(iterable, start=1):
                self._check_quota(quota_guard)
                current_state["index"] = index
                current_state["page"] = unit.page_number
                current_state["unit_id"] = unit.unit_id
                if progress is not None:
                    progress_value = 0.35 + (0.5 * index / max(total_units, 1))
                    progress(
                        progress_value,
                        desc=(
                            f"Translating block {index}/{total_units} "
                            f"(page {unit.page_number})"
                        ),
                    )
                try:
                    unit.translated = self._translate_unit_text(
                        translator,
                        unit,
                        target_language=request.target_language,
                        model=request.model,
                    )
                except RuntimeError as exc:
                    append_run_log(
                        workspace.run_log,
                        f"translation=error page={unit.page_number} unit_id={unit.unit_id} detail={self._single_line_error(exc)}",
                    )
                    raise
                self._check_quota(quota_guard)
                if index == 1 or index == total_units or index % 10 == 0:
                    append_run_log(
                        workspace.run_log,
                        f"translation=progress current={index}/{total_units} page={unit.page_number} unit_id={unit.unit_id}",
                    )

            self._check_quota(quota_guard)
            structured = self._build_structured_payload(workspace, request, units)
            append_run_log(workspace.run_log, "translation=writing_artifacts")
            write_json(workspace.structured_json, structured)
            workspace.translated_markdown.write_text(
                self._build_markdown(units),
                encoding="utf-8",
            )
            workspace.translation_units_jsonl.write_text(
                "\n".join(
                    json.dumps(asdict(unit), ensure_ascii=False) for unit in units
                ),
                encoding="utf-8",
            )
            append_run_log(workspace.run_log, "translation=artifacts:done")
        return units

    def _check_quota(self, quota_guard: QuotaLease | None) -> None:
        if quota_guard is None:
            return
        quota_guard.raise_if_expired()

    def _build_translator(self, request: PipelineRequest) -> BaseTranslator:
        provider_key = normalize_provider(request.provider)
        if provider_key == "ctranslate2":
            if not self.settings.ctranslate2_model_dir:
                raise RuntimeError("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR is missing.")
            return CTranslate2Translator(
                self.settings.ctranslate2_model_dir,
                self.settings.ctranslate2_tokenizer_path,
                device=self.settings.ctranslate2_device,
                compute_type=self.settings.ctranslate2_compute_type,
            )
        if provider_key == OPENROUTER_PROVIDER:
            if not request.provider_api_key.strip():
                raise RuntimeError("OpenRouter API key is required.")
            return OpenRouterTranslator(
                request.provider_api_key,
                api_base_url=self.settings.openrouter_api_base_url,
                max_workers=self.settings.translation_max_workers,
            )
        raise ValueError(f"Unsupported provider: {request.provider}")

    def _translate_unit_text(
        self,
        translator: BaseTranslator,
        unit: TranslationUnit,
        *,
        target_language: str,
        model: str,
    ) -> str:
        source = self.DISCRETIONARY_HYPHEN_PATTERN.sub("", unit.original)
        if self._should_preserve_unit(unit, source):
            return source
        normalized_unit = unit if source == unit.original else replace(unit, original=source)
        translated = self._postprocess_translated_text(
            normalized_unit,
            translator.translate(
                source,
                target_language=target_language,
                model=model,
            ),
        )
        retry_source = self._unchanged_trailing_literal_prefix(
            source,
            translated,
        )
        if retry_source:
            translated = self._postprocess_translated_text(
                normalized_unit,
                translator.translate(
                    retry_source,
                    target_language=target_language,
                    model=model,
                ),
            )
        return self._retry_unchanged_segments(
            translator,
            normalized_unit,
            translated,
            target_language=target_language,
            model=model,
        )

    def _retry_unchanged_segments(
        self,
        translator: BaseTranslator,
        unit: TranslationUnit,
        translated: str,
        *,
        target_language: str,
        model: str,
    ) -> str:
        source = " ".join(unit.original.split()).strip()
        if (
            source.casefold() != " ".join(translated.split()).strip().casefold()
            or self._is_literal_contact(source)
        ):
            return translated
        segments = [
            segment.strip()
            for segment in self.RETRY_SEGMENT_PATTERN.split(source)
            if segment.strip()
        ]
        if len(segments) <= 1:
            return translated
        return " ".join(
            self._postprocess_translated_text(
                replace(unit, original=segment),
                translator.translate(
                    segment,
                    target_language=target_language,
                    model=model,
                ),
            )
            for segment in segments
        )

    def _unchanged_trailing_literal_prefix(
        self,
        original: str,
        translated: str,
    ) -> str:
        normalized_original = " ".join(original.split()).strip()
        if (
            not normalized_original
            or normalized_original.casefold()
            != " ".join(translated.split()).strip().casefold()
            or self._is_literal_contact(normalized_original)
        ):
            return ""
        matches = list(self.INLINE_LITERAL_PATTERN.finditer(normalized_original))
        if not matches:
            return ""
        trailing_literal = matches[-1]
        if normalized_original[trailing_literal.end() :].strip(" .,;:!?"):
            return ""
        return normalized_original[: trailing_literal.start()].strip()

    def _extract_units(self, payload: Any) -> list[TranslationUnit]:
        units: list[TranslationUnit] = []
        counter = 0

        def walk(node: Any) -> None:
            nonlocal counter
            if isinstance(node, dict):
                page = node.get("page number", node.get("page"))
                bbox = node.get("bounding box", node.get("bbox"))
                label = str(node.get("type", node.get("label", "text")))
                content = node.get("content")
                font_size = node.get("font size", node.get("font_size"))
                font_name = node.get("font")
                if (
                    isinstance(page, int)
                    and isinstance(bbox, list)
                    and len(bbox) == 4
                    and isinstance(content, str)
                    and content.strip()
                ):
                    counter += 1
                    resolved_font_size = (
                        float(font_size)
                        if isinstance(font_size, (int, float))
                        else None
                    )
                    bbox_values = [float(value) for value in bbox]
                    estimated_line_count = self._estimate_line_count(
                        content,
                        bbox_values,
                        resolved_font_size,
                    )
                    units.append(
                        TranslationUnit(
                            unit_id=f"u{counter:05d}",
                            page_number=page,
                            label=label,
                            bbox=bbox_values,
                            original=content.strip(),
                            font_size=resolved_font_size,
                            font_name=(
                                font_name.strip() if isinstance(font_name, str) else ""
                            ),
                            estimated_line_count=estimated_line_count,
                            line_height_pt=self._estimate_line_height(
                                bbox_values,
                                resolved_font_size,
                                estimated_line_count,
                            ),
                            letter_spacing_em=self._estimate_letter_spacing(
                                content,
                                bbox_values,
                                resolved_font_size,
                                estimated_line_count,
                            ),
                        )
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return units

    def _restore_source_rows(
        self,
        units: list[TranslationUnit],
        source_pdf: Path,
        *,
        table_diagnostics: list[dict[str, object]] | None = None,
    ) -> list[TranslationUnit]:
        if not source_pdf.is_file() or not units:
            return units

        units_by_page: dict[int, list[TranslationUnit]] = {}
        for unit in units:
            units_by_page.setdefault(unit.page_number, []).append(unit)

        restored: list[TranslationUnit] = []
        document = fitz.open(source_pdf)
        try:
            for page_number, page_units in sorted(units_by_page.items()):
                page_index = page_number - 1
                if page_index < 0 or page_index >= len(document):
                    restored.extend(page_units)
                    continue

                page = document[page_index]
                source_lines = self._extract_source_lines(page)
                table_block_indexes = self._source_table_block_indexes(source_lines)
                table_cells, page_table_diagnostics = self._source_table_cells(
                    page,
                    page_number,
                    page_units,
                    source_lines,
                    table_block_indexes,
                )
                if table_diagnostics is not None:
                    table_diagnostics.append(page_table_diagnostics)
                if table_cells:
                    table_bboxes = page_table_diagnostics["source_bboxes"]
                    page_units = [
                        unit
                        for unit in page_units
                        if not any(
                            bbox_iom(unit.bbox, bbox) >= 0.55
                            for bbox in table_bboxes
                        )
                    ]
                    page_units.extend(table_cells)
                toc_rows: list[
                    tuple[dict[str, object], tuple[str, str]]
                ] = []
                for index, line in enumerate(source_lines):
                    parsed = self._parse_source_toc_row(str(line["text"]))
                    if parsed is None:
                        continue
                    title, toc_page_number = parsed
                    if index > 0:
                        previous = source_lines[index - 1]
                        previous_bbox = [float(value) for value in previous["bbox"]]
                        current_bbox = [float(value) for value in line["bbox"]]
                        font_size = float(line["font_size"])
                        previous_width = previous_bbox[2] - previous_bbox[0]
                        current_width = current_bbox[2] - current_bbox[0]
                        is_wrapped_prefix = (
                            self._parse_source_toc_row(str(previous["text"])) is None
                            and abs(float(previous["font_size"]) - font_size) <= 1.0
                            and abs(previous_bbox[1] - current_bbox[3])
                            <= max(font_size * 0.4, 2.0)
                            and abs(previous_bbox[0] - current_bbox[0])
                            <= max(font_size * 2.0, 20.0)
                            and previous_width >= current_width * 0.7
                        )
                        if is_wrapped_prefix:
                            title = f"{previous['text']} {title}".strip()
                            line = {
                                **line,
                                "text": f"{previous['text']} {line['text']}",
                                "bbox": [
                                    min(previous_bbox[0], current_bbox[0]),
                                    min(previous_bbox[1], current_bbox[1]),
                                    max(previous_bbox[2], current_bbox[2]),
                                    max(previous_bbox[3], current_bbox[3]),
                                ],
                                "font_size": max(
                                    float(previous["font_size"]), font_size
                                ),
                            }
                    toc_rows.append((line, (title, toc_page_number)))
                if self._is_source_toc_page(source_lines, toc_rows):
                    row_bboxes = [line["bbox"] for line, _ in toc_rows]
                    page_units = [
                        unit
                        for unit in page_units
                        if not any(
                            bbox_iom(unit.bbox, row_bbox) >= 0.55
                            for row_bbox in row_bboxes
                        )
                    ]
                    page_units.extend(
                        self._source_line_unit(
                            page_number,
                            line,
                            title,
                            toc_page_number,
                            label=(
                                "list item"
                                if re.match(r"^\d+[.)]\s", title)
                                else "paragraph"
                            ),
                        )
                        for line, (title, toc_page_number) in toc_rows
                    )

                page_restored: list[TranslationUnit] = []
                for unit in page_units:
                    if unit.label.strip().lower() in self.TABLE_LABELS:
                        page_restored.append(unit)
                        continue
                    matching_table_lines = self._sort_source_lines_by_row(
                        [
                            line
                            for line in source_lines
                            if int(line["block_index"]) in table_block_indexes
                            and bbox_iom(unit.bbox, line["bbox"]) >= 0.65
                        ]
                    )
                    if matching_table_lines and self._normalize_source_text(
                        unit.original
                    ) == self._normalize_source_text(
                        " ".join(str(line["text"]) for line in matching_table_lines)
                    ):
                        nearby_right_edges = [
                            float(candidate["bbox"][2])
                            for candidate in source_lines
                            if int(candidate["block_index"])
                            not in table_block_indexes
                            and abs(
                                float(candidate["bbox"][0]) - unit.bbox[0]
                            )
                            <= 8.0
                            and max(
                                unit.bbox[1] - float(candidate["bbox"][3]),
                                float(candidate["bbox"][1]) - unit.bbox[3],
                                0.0,
                            )
                            <= 72.0
                        ]
                        table_right = max(
                            [unit.bbox[2], *nearby_right_edges]
                        )
                        for line in matching_table_lines:
                            block_lines = [
                                candidate
                                for candidate in source_lines
                                if candidate["block_index"] == line["block_index"]
                            ]
                            color = int(line.get("font_color", 0))
                            is_light_text = all(
                                ((color >> shift) & 0xFF) >= 192
                                for shift in (16, 8, 0)
                            )
                            page_restored.append(
                                self._source_line_unit(
                                    page_number,
                                    self._expand_table_cell_line(
                                        line,
                                        block_lines,
                                        table_right=table_right,
                                    ),
                                    str(line["text"]),
                                    "",
                                    label=(
                                        "table header"
                                        if is_light_text
                                        else "table cell"
                                    ),
                                )
                            )
                        continue
                    matching_lines = self._matching_source_lines(unit, source_lines)
                    if self._should_restore_individual_rows(unit, matching_lines):
                        page_restored.extend(
                            self._source_line_unit(
                                page_number,
                                line,
                                str(line["text"]),
                                "",
                                label=unit.label,
                            )
                            for line in matching_lines
                        )
                    else:
                        page_restored.append(unit)
                restored.extend(
                    self._merge_display_fragments(page_restored, source_lines)
                )
        finally:
            document.close()

        return sorted(
            restored,
            key=lambda unit: (
                unit.page_number,
                -float(unit.bbox[3]),
                float(unit.bbox[0]),
            ),
        )

    def _merge_display_fragments(
        self,
        units: list[TranslationUnit],
        source_lines: list[dict[str, object]],
    ) -> list[TranslationUnit]:
        ordered = sorted(
            units,
            key=lambda unit: (-float(unit.bbox[3]), float(unit.bbox[0])),
        )
        merged: list[TranslationUnit] = []
        index = 0
        while index < len(ordered):
            first = ordered[index]
            block_index = self._display_source_block(first, source_lines)
            group = [first]
            next_index = index + 1
            while next_index < len(ordered):
                candidate = ordered[next_index]
                candidate_block = self._display_source_block(candidate, source_lines)
                same_source_block = (
                    block_index is not None and candidate_block == block_index
                )
                if not same_source_block and not self._continues_display_fragment(
                    group[-1], candidate
                ):
                    break
                group.append(candidate)
                next_index += 1

            if len(group) == 1:
                merged.append(first)
            else:
                merged.append(
                    replace(
                        first,
                        bbox=[
                            min(unit.bbox[0] for unit in group),
                            min(unit.bbox[1] for unit in group),
                            max(unit.bbox[2] for unit in group),
                            max(unit.bbox[3] for unit in group),
                        ],
                        original=" ".join(unit.original.strip() for unit in group),
                        translated="",
                        estimated_line_count=sum(
                            max(unit.estimated_line_count, 1) for unit in group
                        ),
                        line_height_pt=max(
                            (unit.line_height_pt or 0.0) for unit in group
                        )
                        or None,
                    )
                )
            index = next_index if len(group) > 1 else index + 1
        return merged

    def _display_source_block(
        self,
        unit: TranslationUnit,
        source_lines: list[dict[str, object]],
    ) -> int | None:
        if (unit.font_size or 0.0) < 16.0:
            return None
        matching = [
            line for line in source_lines if bbox_iom(unit.bbox, line["bbox"]) >= 0.65
        ]
        if not matching or self._normalize_source_text(unit.original) != (
            self._normalize_source_text(
                " ".join(str(line["text"]) for line in matching)
            )
        ):
            return None
        block_indexes = {int(line["block_index"]) for line in matching}
        return next(iter(block_indexes)) if len(block_indexes) == 1 else None

    def _continues_display_fragment(
        self,
        previous: TranslationUnit,
        candidate: TranslationUnit,
    ) -> bool:
        previous_size = previous.font_size or 0.0
        candidate_size = candidate.font_size or 0.0
        if (
            min(previous_size, candidate_size) < 16.0
            or abs(previous_size - candidate_size) > 1.0
            or previous.label != candidate.label
        ):
            return False
        aligned_edge = (
            abs(previous.bbox[0] - candidate.bbox[0]) <= 4.0
            or abs(previous.bbox[2] - candidate.bbox[2]) <= 4.0
        )
        top_step = previous.bbox[3] - candidate.bbox[3]
        gap = previous.bbox[1] - candidate.bbox[3]
        return (
            aligned_edge
            and top_step >= previous_size * 0.4
            and -previous_size * 0.5 <= gap <= previous_size * 0.8
        )

    def _extract_source_lines(self, page: fitz.Page) -> list[dict[str, object]]:
        lines: list[dict[str, object]] = []
        payload = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
        for block_index, block in enumerate(payload.get("blocks", [])):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(str(span.get("text", "")) for span in spans).strip()
                bbox = line.get("bbox")
                if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                rect = fitz.Rect(bbox)
                lines.append(
                    {
                        "text": text,
                        "bbox": [
                            float(rect.x0),
                            float(page.rect.height - rect.y1),
                            float(rect.x1),
                            float(page.rect.height - rect.y0),
                        ],
                        "font_size": max(
                            (float(span.get("size", 0.0)) for span in spans),
                            default=0.0,
                        ),
                        "font_name": (str(spans[0].get("font", "")) if spans else ""),
                        "font_color": (
                            int(spans[0].get("color", 0)) if spans else 0
                        ),
                        "block_index": block_index,
                    }
                )

        deduplicated: list[dict[str, object]] = []
        for line in sorted(
            lines, key=lambda item: (-float(item["bbox"][3]), float(item["bbox"][0]))
        ):
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(deduplicated)
                    if abs(float(existing["bbox"][3]) - float(line["bbox"][3])) <= 1.0
                    and bbox_iom(existing["bbox"], line["bbox"]) >= 0.8
                    and (
                        self._normalize_source_text(str(existing["text"]))
                        in self._normalize_source_text(str(line["text"]))
                        or self._normalize_source_text(str(line["text"]))
                        in self._normalize_source_text(str(existing["text"]))
                    )
                ),
                None,
            )
            if duplicate_index is None:
                deduplicated.append(line)
            elif len(str(line["text"])) > len(
                str(deduplicated[duplicate_index]["text"])
            ):
                deduplicated[duplicate_index] = line
        return deduplicated

    def _parse_source_toc_row(self, text: str) -> tuple[str, str] | None:
        match = self.SOURCE_TOC_ROW_PATTERN.match(text.strip())
        if match is None:
            return None
        title = re.sub(r"(?:\.\s*){2,}$", "", match.group("title")).strip()
        page_number = match.group("page").strip()
        if not title or not page_number:
            return None
        return title, page_number

    def _is_source_toc_page(
        self,
        source_lines: list[dict[str, object]],
        toc_rows: list[tuple[dict[str, object], tuple[str, str]]],
    ) -> bool:
        if len(toc_rows) >= 5:
            return True
        has_toc_heading = any(
            "table of contents" in self._normalize_source_text(str(line["text"]))
            for line in source_lines
        )
        return has_toc_heading and len(toc_rows) >= 2

    def _matching_source_lines(
        self,
        unit: TranslationUnit,
        source_lines: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        matching = self._sort_source_lines_by_row(
            [
                line
                for line in source_lines
                if bbox_iom(unit.bbox, line["bbox"]) >= 0.65
            ]
        )
        if len(matching) <= 1:
            return []
        source_text = self._normalize_source_text(unit.original)
        line_text = self._normalize_source_text(
            " ".join(str(line["text"]) for line in matching)
        )
        return matching if source_text == line_text else []

    def _sort_source_lines_by_row(
        self,
        source_lines: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            line
            for row in self._source_line_rows(source_lines)
            for line in sorted(row, key=lambda item: float(item["bbox"][0]))
        ]

    def _source_line_rows(
        self,
        source_lines: list[dict[str, object]],
    ) -> list[list[dict[str, object]]]:
        rows: list[list[dict[str, object]]] = []
        for line in sorted(
            source_lines,
            key=lambda item: -(
                float(item["bbox"][1]) + float(item["bbox"][3])
            )
            / 2.0,
        ):
            center = (float(line["bbox"][1]) + float(line["bbox"][3])) / 2.0
            if rows:
                anchor = sum(
                    (float(item["bbox"][1]) + float(item["bbox"][3])) / 2.0
                    for item in rows[-1]
                ) / len(rows[-1])
                if abs(anchor - center) <= 1.0:
                    rows[-1].append(line)
                    continue
            rows.append([line])
        return rows

    def _source_table_block_indexes(
        self,
        source_lines: list[dict[str, object]],
    ) -> set[int]:
        lines_by_block: dict[int, list[dict[str, object]]] = {}
        for line in source_lines:
            lines_by_block.setdefault(int(line["block_index"]), []).append(line)
        table_blocks: set[int] = set()
        for block_index, block_lines in lines_by_block.items():
            parallel_rows = sum(
                len(row) >= 2 for row in self._source_line_rows(block_lines)
            )
            if len(block_lines) >= 4 and parallel_rows >= 2:
                table_blocks.add(block_index)
        return table_blocks

    def _source_table_cells(
        self,
        page: fitz.Page,
        page_number: int,
        page_units: list[TranslationUnit],
        source_lines: list[dict[str, object]],
        table_block_indexes: set[int],
    ) -> tuple[list[TranslationUnit], dict[str, object]]:
        regions, errors = self._source_table_regions(
            page,
            page_units,
            source_lines,
            table_block_indexes,
        )
        candidates: list[dict[str, object]] = []
        for clip in regions:
            source_candidate = self._source_line_table_candidate(
                page,
                clip,
                source_lines,
            )
            if source_candidate is not None:
                candidates.append(source_candidate)
            for strategy_index, (vertical, horizontal) in enumerate(
                self.TABLE_STRATEGIES
            ):
                try:
                    finder = page.find_tables(
                        clip=clip,
                        vertical_strategy=vertical,
                        horizontal_strategy=horizontal,
                        min_words_vertical=2,
                        min_words_horizontal=1,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                    errors.append(f"{vertical}/{horizontal}: {exc}")
                    continue
                for table in finder.tables:
                    candidate = self._evaluate_table_candidate(
                        page,
                        clip,
                        [*table.cells, *(table.header.cells or [])],
                        int(table.row_count),
                        int(table.col_count),
                        f"{vertical}/{horizontal}",
                        strategy_index,
                        source_lines,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

        accepted: list[dict[str, object]] = []
        for candidate in sorted(candidates, key=self._table_candidate_sort_key):
            candidate_rect = candidate["table_rect"]
            if any(
                self._rect_iom(candidate_rect, existing["table_rect"]) >= 0.8
                for existing in accepted
            ):
                continue
            accepted.append(candidate)

        units = [
            unit
            for candidate in accepted
            for unit in self._table_candidate_units(
                page,
                page_number,
                candidate,
                source_lines,
            )
        ]
        tables = [
            {
                "strategy": str(candidate["strategy"]),
                "bbox": self._rect_values(candidate["table_rect"]),
                "source_bbox": self._page_rect_to_source_bbox(
                    page, candidate["clip"]
                ),
                "coverage": float(candidate["coverage"]),
                "duplicate_words": int(candidate["duplicate_words"]),
                "intersecting_cells": int(candidate["intersecting_cells"]),
                "physical_cells": int(candidate["physical_cell_count"]),
                "nonempty_cells": int(candidate["nonempty_cell_count"]),
            }
            for candidate in accepted
        ]
        try:
            source_drawings = len(page.get_drawings())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            source_drawings = 0
        diagnostics: dict[str, object] = {
            "page": page_number,
            "candidate_regions": len(regions),
            "accepted_tables": len(accepted),
            "nonempty_cells": len(units),
            "coverage": min(
                (float(candidate["coverage"]) for candidate in accepted),
                default=0.0,
            ),
            "duplicate_words": sum(
                int(candidate["duplicate_words"]) for candidate in accepted
            ),
            "intersecting_cells": sum(
                int(candidate["intersecting_cells"]) for candidate in accepted
            ),
            "source_drawings": source_drawings,
            "blank_pages": int(not page.get_text().strip()),
            "source_bboxes": [table["source_bbox"] for table in tables],
            "tables": tables,
            "errors": errors,
        }
        return units, diagnostics

    def _source_table_regions(
        self,
        page: fitz.Page,
        page_units: list[TranslationUnit],
        source_lines: list[dict[str, object]],
        table_block_indexes: set[int],
    ) -> tuple[list[fitz.Rect], list[str]]:
        regions = [
            self._source_bbox_to_page_rect(page, unit.bbox)
            for unit in page_units
            if "table" in unit.label.strip().casefold()
        ]
        for block_index in table_block_indexes:
            rects = [
                self._source_bbox_to_page_rect(page, line["bbox"])
                for line in source_lines
                if int(line["block_index"]) == block_index
            ]
            if rects:
                regions.append(self._union_page_rects(rects))

        errors: list[str] = []
        try:
            regions.extend(
                fitz.Rect(table.bbox)
                for table in page.find_tables(strategy="lines").tables
            )
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"lines discovery: {exc}")

        try:
            horizontal_rules = sorted(
                (
                    fitz.Rect(drawing["rect"])
                    for drawing in page.get_drawings()
                    if "rect" in drawing
                ),
                key=lambda rect: rect.y0,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"drawing discovery: {exc}")
            horizontal_rules = []
        horizontal_rules = [
            rect
            for rect in horizontal_rules
            if rect.height <= 2.0 and rect.width >= page.rect.width * 0.18
        ]
        groups: list[list[fitz.Rect]] = []
        for rule in horizontal_rules:
            for group in groups:
                anchor = group[0]
                if (
                    abs(anchor.x0 - rule.x0) <= 8.0
                    and abs(anchor.x1 - rule.x1) <= 8.0
                    and rule.y0 - group[-1].y1 <= 100.0
                ):
                    group.append(rule)
                    break
            else:
                groups.append([rule])
        for group in groups:
            if len(group) < 3:
                continue
            # ponytail: zero-height PDF rules are empty Rects, so build their
            # bounds directly instead of relying on Rect union semantics.
            rect = fitz.Rect(
                min(rule.x0 for rule in group),
                min(rule.y0 for rule in group),
                max(rule.x1 for rule in group),
                max(rule.y1 for rule in group),
            )
            regions.append(
                fitz.Rect(
                    rect.x0 - 2.0,
                    rect.y0 - 2.0,
                    rect.x1 + 2.0,
                    rect.y1 + 2.0,
                )
                & page.rect
            )

        valid = [
            rect & page.rect
            for rect in regions
            if rect.width > 1.0 and rect.height > 1.0
        ]
        unique: list[fitz.Rect] = []
        for rect in sorted(
            valid,
            key=lambda item: (-item.get_area(), *self._rect_values(item)),
        ):
            if any(self._rect_iom(rect, existing) >= 0.8 for existing in unique):
                continue
            unique.append(rect)
        return unique, errors

    def _source_line_table_candidate(
        self,
        page: fitz.Page,
        clip: fitz.Rect,
        source_lines: list[dict[str, object]],
    ) -> dict[str, object] | None:
        clipped_lines: list[dict[str, object]] = []
        for line in source_lines:
            rect = self._source_bbox_to_page_rect(page, line["bbox"])
            center = fitz.Point(
                (rect.x0 + rect.x1) / 2.0,
                (rect.y0 + rect.y1) / 2.0,
            )
            if clip.contains(center):
                clipped_lines.append(line)
        rows = self._source_line_rows(clipped_lines)
        if len(rows) < 2 or sum(len(row) >= 2 for row in rows) < 2:
            return None
        cells: list[fitz.Rect] = []
        for row in rows:
            ordered = sorted(row, key=lambda item: float(item["bbox"][0]))
            for index, line in enumerate(ordered):
                source_bbox = [float(value) for value in line["bbox"]]
                source_bbox[2] = max(
                    source_bbox[2],
                    (
                        float(ordered[index + 1]["bbox"][0]) - 1.0
                        if index + 1 < len(ordered)
                        else clip.x1
                    ),
                )
                cells.append(self._source_bbox_to_page_rect(page, source_bbox))
        return self._evaluate_table_candidate(
            page,
            clip,
            cells,
            len(rows),
            max(len(row) for row in rows),
            "source-lines",
            len(self.TABLE_STRATEGIES),
            source_lines,
        )

    def _evaluate_table_candidate(
        self,
        page: fitz.Page,
        clip: fitz.Rect,
        raw_cells: Iterable[object],
        row_count: int,
        col_count: int,
        strategy: str,
        strategy_index: int,
        source_lines: list[dict[str, object]],
    ) -> dict[str, object] | None:
        if row_count < 2 or col_count < 2:
            return None
        cells: dict[tuple[float, float, float, float], fitz.Rect] = {}
        for value in raw_cells:
            if value is None:
                continue
            rect = fitz.Rect(value)
            if rect.width <= 0 or rect.height <= 0:
                continue
            key = tuple(round(coordinate * 2.0) / 2.0 for coordinate in rect)
            cells.setdefault(key, fitz.Rect(key))
        if len(cells) < 3:
            return None

        cell_rects = list(cells.values())
        intersecting_cells = sum(
            (left & right).get_area() > 1.0
            for index, left in enumerate(cell_rects)
            for right in cell_rects[index + 1 :]
        )
        if intersecting_cells:
            return None

        words = self._page_words_in_rect(page, clip)
        if not words:
            return None
        cell_words: dict[
            tuple[float, float, float, float], list[tuple[object, ...]]
        ] = {key: [] for key in cells}
        duplicate_words = 0
        covered_words = 0
        for word in words:
            center = fitz.Point(
                (float(word[0]) + float(word[2])) / 2.0,
                (float(word[1]) + float(word[3])) / 2.0,
            )
            owners = [key for key, rect in cells.items() if rect.contains(center)]
            if owners:
                covered_words += 1
                cell_words[owners[0]].append(word)
                duplicate_words += max(0, len(owners) - 1)
        coverage = covered_words / len(words)
        if coverage < 0.98 or duplicate_words:
            return None

        line_owners: Counter[tuple[float, float, float, float]] = Counter()
        for line in source_lines:
            line_rect = self._source_bbox_to_page_rect(page, line["bbox"])
            center = fitz.Point(
                (line_rect.x0 + line_rect.x1) / 2.0,
                (line_rect.y0 + line_rect.y1) / 2.0,
            )
            if not clip.contains(center):
                continue
            owner = next(
                (key for key, rect in cells.items() if rect.contains(center)),
                None,
            )
            if owner is not None:
                line_owners[owner] += 1
        nonempty = {key: value for key, value in cell_words.items() if value}
        if not nonempty:
            return None
        return {
            "strategy": strategy,
            "strategy_index": strategy_index,
            "clip": fitz.Rect(clip),
            "table_rect": self._union_page_rects(list(cells.values())),
            "cells": cells,
            "cell_words": nonempty,
            "coverage": coverage,
            "covered_word_count": covered_words,
            "duplicate_words": duplicate_words,
            "intersecting_cells": intersecting_cells,
            "line_collisions": sum(max(0, count - 1) for count in line_owners.values()),
            "physical_cell_count": len(cells),
            "nonempty_cell_count": len(nonempty),
        }

    def _table_candidate_sort_key(
        self,
        candidate: dict[str, object],
    ) -> tuple[object, ...]:
        return (
            -int(candidate["covered_word_count"]),
            int(candidate["line_collisions"]),
            int(candidate["physical_cell_count"]),
            int(candidate["strategy_index"]),
            *self._rect_values(candidate["table_rect"]),
        )

    def _table_candidate_units(
        self,
        page: fitz.Page,
        page_number: int,
        candidate: dict[str, object],
        source_lines: list[dict[str, object]],
    ) -> list[TranslationUnit]:
        units: list[TranslationUnit] = []
        cell_words = candidate["cell_words"]
        for key, words in sorted(
            cell_words.items(),
            key=lambda item: (item[0][1], item[0][0]),
        ):
            rect = fitz.Rect(key)
            source_bbox = self._page_rect_to_source_bbox(page, rect)
            matching_lines = [
                line
                for line in source_lines
                if bbox_iom(source_bbox, line["bbox"]) >= 0.2
            ]
            ordered_words = sorted(
                words,
                key=lambda word: (
                    int(word[5]) if len(word) > 5 else 0,
                    int(word[6]) if len(word) > 6 else 0,
                    int(word[7]) if len(word) > 7 else 0,
                    float(word[1]),
                    float(word[0]),
                ),
            )
            font_size = max(
                (float(line["font_size"]) for line in matching_lines),
                default=max(
                    (float(word[3]) - float(word[1]) for word in ordered_words),
                    default=9.0,
                )
                * 0.8,
            )
            colors = [int(line.get("font_color", 0)) for line in matching_lines]
            is_light_text = bool(colors) and all(
                all(((color >> shift) & 0xFF) >= 192 for shift in (16, 8, 0))
                for color in colors
            )
            units.append(
                self._source_line_unit(
                    page_number,
                    {
                        "bbox": source_bbox,
                        "font_size": font_size,
                        "font_name": (
                            str(matching_lines[0]["font_name"])
                            if matching_lines
                            else ""
                        ),
                    },
                    " ".join(str(word[4]) for word in ordered_words),
                    "",
                    label="table header" if is_light_text else "table cell",
                )
            )
        return units

    def _page_words_in_rect(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
    ) -> list[tuple[object, ...]]:
        return [
            tuple(word)
            for word in page.get_text("words", clip=rect)
            if len(word) >= 5
            and rect.contains(
                fitz.Point(
                    (float(word[0]) + float(word[2])) / 2.0,
                    (float(word[1]) + float(word[3])) / 2.0,
                )
            )
        ]

    def _source_bbox_to_page_rect(
        self,
        page: fitz.Page,
        bbox: object,
    ) -> fitz.Rect:
        left, bottom, right, top = [float(value) for value in bbox]
        return fitz.Rect(
            left,
            page.rect.height - top,
            right,
            page.rect.height - bottom,
        )

    def _page_rect_to_source_bbox(
        self,
        page: fitz.Page,
        rect: object,
    ) -> list[float]:
        value = fitz.Rect(rect)
        return [
            float(value.x0),
            float(page.rect.height - value.y1),
            float(value.x1),
            float(page.rect.height - value.y0),
        ]

    def _union_page_rects(self, rects: list[fitz.Rect]) -> fitz.Rect:
        union = fitz.Rect(rects[0])
        for rect in rects[1:]:
            union |= rect
        return union

    def _rect_iom(self, left: object, right: object) -> float:
        left_rect = fitz.Rect(left)
        right_rect = fitz.Rect(right)
        smaller = min(left_rect.get_area(), right_rect.get_area())
        if smaller <= 0:
            return 0.0
        return (left_rect & right_rect).get_area() / smaller

    def _rect_values(self, rect: object) -> tuple[float, float, float, float]:
        value = fitz.Rect(rect)
        return tuple(round(coordinate, 3) for coordinate in value)

    def _expand_table_cell_line(
        self,
        line: dict[str, object],
        block_lines: list[dict[str, object]],
        *,
        table_right: float | None = None,
    ) -> dict[str, object]:
        expanded = dict(line)
        bbox = [float(value) for value in line["bbox"]]
        center = (bbox[1] + bbox[3]) / 2.0
        peers = sorted(
            (
                candidate
                for candidate in block_lines
                if abs(
                    (
                        float(candidate["bbox"][1])
                        + float(candidate["bbox"][3])
                    )
                    / 2.0
                    - center
                )
                <= 1.0
            ),
            key=lambda candidate: float(candidate["bbox"][0]),
        )
        next_left = next(
            (
                float(candidate["bbox"][0])
                for candidate in peers
                if float(candidate["bbox"][0]) > bbox[0] + 1.0
            ),
            None,
        )
        block_right = max(
            max(float(candidate["bbox"][2]) for candidate in block_lines),
            table_right if table_right is not None else bbox[2],
        )
        bbox[2] = max(bbox[2], (next_left - 2.0) if next_left else block_right)
        bbox[1] -= 1.0
        bbox[3] += 1.0
        expanded["bbox"] = bbox
        return expanded

    def _should_restore_individual_rows(
        self,
        unit: TranslationUnit,
        source_lines: list[dict[str, object]],
    ) -> bool:
        if len(source_lines) <= 1:
            return False
        if len(self._source_line_rows(source_lines)) == 1 and not any(
            str(line["text"]).strip() == "|" for line in source_lines
        ):
            return False
        if len({int(line["block_index"]) for line in source_lines}) > 1:
            return True

        colon_rows = sum(
            re.match(r"^[^:]{1,40}:(?!//)", str(line["text"])) is not None
            for line in source_lines
        )
        if colon_rows >= max(2, math.ceil(len(source_lines) * 0.6)):
            return True

        unit_width = abs(unit.bbox[2] - unit.bbox[0])
        if len(source_lines) < 3 or unit_width <= 0:
            return False
        short_rows = sum(
            abs(float(line["bbox"][2]) - float(line["bbox"][0])) <= unit_width * 0.8
            for line in source_lines
        )
        return short_rows >= math.ceil(len(source_lines) * 0.6) and all(
            len(str(line["text"])) <= 72 for line in source_lines
        )

    def _source_line_unit(
        self,
        page_number: int,
        line: dict[str, object],
        original: str,
        toc_page_number: str,
        *,
        label: str,
    ) -> TranslationUnit:
        bbox = [float(value) for value in line["bbox"]]
        font_size = float(line["font_size"])
        estimated_line_count = max(
            1,
            round(abs(bbox[3] - bbox[1]) / max(font_size * 1.15, 1.0)),
        )
        return TranslationUnit(
            unit_id="",
            page_number=page_number,
            label=label,
            bbox=bbox,
            original=original.strip(),
            font_size=font_size or None,
            font_name=str(line["font_name"]),
            estimated_line_count=estimated_line_count,
            line_height_pt=(
                round(font_size * 1.15, 3)
                if label in {"table cell", "table header"}
                else self._estimate_line_height(
                    bbox,
                    font_size,
                    estimated_line_count,
                )
            ),
            letter_spacing_em=None,
            toc_page_number=toc_page_number,
        )

    def _normalize_source_text(self, value: str) -> str:
        return " ".join(value.split()).strip().casefold()

    def _postprocess_units(self, units: list[TranslationUnit]) -> list[TranslationUnit]:
        units = self._merge_discretionary_hyphen_units(units)
        units = self._deduplicate_overlapping_units(units)
        processed: list[TranslationUnit] = []
        for unit in units:
            list_units = self._split_list_item_unit(unit)
            for list_unit in list_units:
                toc_units = self._split_toc_unit(list_unit)
                for toc_unit in toc_units:
                    normalized_units = self._normalize_special_units(toc_unit)
                    for normalized_unit in normalized_units:
                        processed.extend(
                            self._split_explicit_multiline_unit(normalized_unit)
                        )

        for index, unit in enumerate(processed, start=1):
            unit.unit_id = f"u{index:05d}"
        return processed

    def _merge_discretionary_hyphen_units(
        self,
        units: list[TranslationUnit],
    ) -> list[TranslationUnit]:
        merged: list[TranslationUnit] = []
        for unit in units:
            if not merged:
                merged.append(unit)
                continue
            previous = merged[-1]
            previous_size = previous.font_size or 0.0
            current_size = unit.font_size or 0.0
            joins_word = re.search(r"[A-Za-z][\u00ad\u2010-]\s*$", previous.original)
            vertical_gap = abs(float(previous.bbox[1]) - float(unit.bbox[3]))
            horizontal_overlap = min(previous.bbox[2], unit.bbox[2]) - max(
                previous.bbox[0], unit.bbox[0]
            )
            if (
                joins_word is None
                or re.match(r"^[a-z]", unit.original.strip()) is None
                or previous.page_number != unit.page_number
                or previous.label != unit.label
                or previous.toc_page_number
                or unit.toc_page_number
                or abs(previous_size - current_size) > 1.0
                or vertical_gap > max(previous_size, current_size, 1.0) * 0.5
                or horizontal_overlap <= 0
            ):
                merged.append(unit)
                continue
            bbox = [
                min(previous.bbox[0], unit.bbox[0]),
                min(previous.bbox[1], unit.bbox[1]),
                max(previous.bbox[2], unit.bbox[2]),
                max(previous.bbox[3], unit.bbox[3]),
            ]
            line_count = previous.estimated_line_count + unit.estimated_line_count
            merged[-1] = replace(
                previous,
                bbox=bbox,
                original=(
                    re.sub(r"[\u00ad\u2010-]\s*$", "", previous.original)
                    + unit.original.lstrip()
                ),
                estimated_line_count=line_count,
                line_height_pt=self._estimate_line_height(
                    bbox,
                    previous.font_size,
                    line_count,
                ),
                letter_spacing_em=None,
            )
        return merged

    def _split_explicit_multiline_unit(
        self,
        unit: TranslationUnit,
    ) -> list[TranslationUnit]:
        if unit.label.strip().lower() not in {"paragraph", "heading", "caption"}:
            return [unit]

        segments = self._extract_explicit_line_segments(unit.original)
        if len(segments) <= 1:
            return [unit]
        if not self._should_split_explicit_multiline_unit(unit, segments):
            return [unit]
        return self._subdivide_unit_bbox_with_gaps(unit, segments)

    def _deduplicate_overlapping_units(
        self, units: list[TranslationUnit]
    ) -> list[TranslationUnit]:
        filtered: list[TranslationUnit] = []

        for unit in units:
            candidate = unit
            overlapping_indexes: list[int] = []
            for index, existing in enumerate(filtered):
                if not self._is_duplicate_unit(candidate, existing):
                    continue
                overlapping_indexes.append(index)
                candidate = self._prefer_unit(existing, candidate)

            if not overlapping_indexes:
                filtered.append(candidate)
                continue

            first_index = overlapping_indexes[0]
            filtered[first_index] = candidate
            for index in reversed(overlapping_indexes[1:]):
                filtered.pop(index)

        return filtered

    def _is_duplicate_unit(
        self, candidate: TranslationUnit, existing: TranslationUnit
    ) -> bool:
        if candidate.page_number != existing.page_number:
            return False
        if candidate.label.strip().lower() != existing.label.strip().lower():
            return False

        area_ratio = bbox_area_ratio(candidate.bbox, existing.bbox)
        if area_ratio < self.DUPLICATE_BOX_AREA_RATIO_THRESHOLD:
            return False

        if (
            bbox_iou(candidate.bbox, existing.bbox)
            >= self.settings.duplicate_box_iou_threshold
        ):
            return True

        if (
            bbox_iom(candidate.bbox, existing.bbox)
            < self.settings.duplicate_box_iom_threshold
        ):
            return False

        return self._is_duplicate_content(candidate.original, existing.original)

    def _prefer_unit(
        self, existing: TranslationUnit, candidate: TranslationUnit
    ) -> TranslationUnit:
        existing_area = bbox_area(existing.bbox)
        candidate_area = bbox_area(candidate.bbox)
        if candidate_area > existing_area:
            return candidate
        if candidate_area < existing_area:
            return existing

        if len(candidate.original.strip()) > len(existing.original.strip()):
            return candidate
        return existing

    def _is_duplicate_content(self, left: str, right: str) -> bool:
        normalized_left = self._normalize_content(left)
        normalized_right = self._normalize_content(right)
        if not normalized_left or not normalized_right:
            return True
        return (
            normalized_left == normalized_right
            or normalized_left in normalized_right
            or normalized_right in normalized_left
        )

    def _normalize_content(self, value: str) -> str:
        return " ".join(value.split()).strip().lower()

    def _single_line_error(self, exc: Exception) -> str:
        return " ".join(str(exc).split())

    def _postprocess_translated_text(
        self,
        unit: TranslationUnit,
        text: str,
    ) -> str:
        normalized_original = " ".join(unit.original.split()).strip()
        if self._is_literal_contact(normalized_original):
            return normalized_original

        sanitized = self._sanitize_translated_text(text).strip()
        sanitized = self._apply_domain_term_corrections(unit.original, sanitized)
        sanitized = self._strip_appended_original(unit.original, sanitized)
        sanitized = self._restore_inline_literals(unit.original, sanitized)
        source_bullet = re.match(r"^\s*([•▪◦‣])\s*", unit.original)
        if source_bullet is not None and not re.match(r"^\s*[•▪◦‣]", sanitized):
            sanitized = f"{source_bullet.group(1)} {sanitized.lstrip()}"
        fallback_candidate = self._fallback_translate_original(unit.original)

        structural_override = self._translate_structural_unit(unit)
        if structural_override is not None:
            return structural_override

        if (
            fallback_candidate != normalized_original
            and sanitized == normalized_original
        ):
            return fallback_candidate

        if self._looks_like_suspicious_translation(unit.original, sanitized):
            return fallback_candidate

        if self._looks_excessively_repetitive(unit.original, sanitized):
            return fallback_candidate

        return sanitized

    def _should_preserve_literal(self, text: str) -> bool:
        normalized = text.strip()
        words = normalized.split()
        return bool(
            normalized
            and (
                not any(character.isalpha() for character in normalized)
                or self._is_literal_contact(normalized)
                or (words and all("@" in word for word in words))
                or self.CODE_LITERAL_PATTERN.match(normalized)
            )
        )

    def _should_preserve_unit(self, unit: TranslationUnit, text: str) -> bool:
        return (
            self._should_preserve_literal(text)
            or self._is_table_literal(unit, text)
            or bool(
                unit.font_name and self.MONOSPACE_FONT_PATTERN.search(unit.font_name)
            )
        )

    def _is_table_literal(self, unit: TranslationUnit, text: str) -> bool:
        if (
            unit.label.strip().lower() not in self.TABLE_LABELS
            or len(text) > 80
            or self.TABLE_LITERAL_PATTERN.fullmatch(text) is None
        ):
            return False
        has_operator = bool(re.search(r"[=+*/^<>≤≥≈]|\s-\s", text))
        if not has_operator and not re.search(r"\d|[%~∼]", text):
            return False
        word_count = len(re.findall(r"[A-Za-z]+", text))
        return word_count <= (4 if has_operator else 2)

    def _looks_excessively_repetitive(self, original: str, text: str) -> bool:
        tokens = re.findall(r"[A-Za-z가-힣]+|[^\w\s]", text.casefold())
        source_tokens = re.findall(r"[A-Za-z가-힣]+|[^\w\s]", original.casefold())
        if len(tokens) < max(8, len(source_tokens) * 2):
            return False
        return Counter(tokens).most_common(1)[0][1] / len(tokens) >= 0.35

    def _is_literal_contact(self, text: str) -> bool:
        if self.LITERAL_CONTACT_PATTERN.fullmatch(text) is None:
            return False
        if len(text.split()) > 6 and text.endswith((".", "!", "?")):
            return False
        return re.search(r"[.!?]\s+[A-Z]", text) is None

    def _sanitize_translated_text(self, text: str) -> str:
        sanitized = self.EXCESSIVE_FRAGMENT_PATTERN.sub(
            lambda match: match.group(1),
            text,
        )
        sanitized = self.EXCESSIVE_SPACED_TOKEN_PATTERN.sub(
            lambda match: match.group(1),
            sanitized,
        )
        sanitized = self.EXCESSIVE_SPACED_FRAGMENT_PATTERN.sub(
            lambda match: match.group(1),
            sanitized,
        )
        return self.EXCESSIVE_REPEAT_PATTERN.sub(
            lambda match: match.group(1),
            sanitized,
        )

    def _strip_appended_original(self, original: str, translated: str) -> str:
        normalized_original = " ".join(original.split()).strip()
        translated = re.sub(
            r"\s*\((?P<gloss>[A-Za-z][A-Za-z0-9 /&+.'’_-]{4,60})\)",
            lambda match: (
                ""
                if self.TARGET_SCRIPT_PATTERN.search(match.string[: match.start()])
                and re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(match.group('gloss'))}(?![A-Za-z0-9])",
                    normalized_original,
                    re.IGNORECASE,
                )
                and re.search(
                    rf"\(\s*{re.escape(match.group('gloss'))}\s*\)",
                    normalized_original,
                    re.IGNORECASE,
                )
                is None
                else match.group(0)
            ),
            translated,
        )
        normalized_translated = " ".join(translated.split()).strip()
        trailing_artifact = re.search(
            r"(?<=[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af][.!?])"
            r"(?P<word>[A-Za-z]{2,8})$",
            normalized_translated,
        )
        if (
            trailing_artifact is not None
            and re.search(
                rf"\b{re.escape(trailing_artifact.group('word'))}\b",
                normalized_original,
                re.IGNORECASE,
            )
            is None
        ):
            normalized_translated = normalized_translated[
                : trailing_artifact.start()
            ].rstrip()
            translated = normalized_translated
        if (
            not normalized_original
            or normalized_translated.casefold() == normalized_original.casefold()
        ):
            return translated

        suffix_match = re.search(
            re.escape(normalized_original) + r"\s*$",
            normalized_translated,
            re.IGNORECASE,
        )
        if suffix_match is not None:
            translated_prefix = normalized_translated[: suffix_match.start()].strip()
            if (
                translated_prefix
                and re.search(r"[A-Za-z]", normalized_original)
                and self.TARGET_SCRIPT_PATTERN.search(translated_prefix)
            ):
                return translated_prefix

        source_key = re.sub(r"[^a-z0-9]+", "", normalized_original.casefold())
        if len(source_key) < 12:
            return translated

        best_match: tuple[int, str] | None = None
        for match in re.finditer(
            r"(?<![A-Za-z])(?:\(|[A-Za-z])", normalized_translated
        ):
            prefix = normalized_translated[: match.start()].rstrip(" (")
            if not prefix or self.TARGET_SCRIPT_PATTERN.search(prefix) is None:
                continue
            suffix = normalized_translated[match.start() :].strip().strip("()")
            if self.TARGET_SCRIPT_PATTERN.search(suffix) is not None:
                continue
            suffix_key = re.sub(r"[^a-z0-9]+", "", suffix.casefold())
            if len(suffix_key) < max(10, round(len(source_key) * 0.55)) and not (
                len(suffix_key) >= 8
                and re.fullmatch(r"[A-Za-z][A-Za-z-]{7,}", suffix)
                and suffix_key not in source_key
            ):
                continue
            matcher = SequenceMatcher(None, source_key, suffix_key)
            longest = matcher.find_longest_match(0, len(source_key), 0, len(suffix_key))
            duplicate_fragment = matcher.ratio() >= 0.76 or (
                len(suffix_key) >= 12
                and len(suffix_key) >= len(source_key) * 0.3
                and longest.size / len(suffix_key) >= 0.82
            )
            hallucinated_word = bool(
                re.fullmatch(r"[A-Za-z][A-Za-z-]{7,}", suffix)
                and suffix_key not in source_key
            )
            if (duplicate_fragment or hallucinated_word) and (
                best_match is None or match.start() < best_match[0]
            ):
                best_match = (match.start(), prefix)
        if best_match is not None:
            return best_match[1]
        return translated

    def _restore_inline_literals(self, original: str, translated: str) -> str:
        restored = translated.rstrip()
        for match in self.INLINE_LITERAL_PATTERN.finditer(original):
            literal = match.group(0).rstrip(".,;:!?")
            if literal.casefold() in restored.casefold():
                continue
            if literal.startswith("@") and restored.endswith("@"):
                restored = restored[:-1].rstrip()
            restored = f"{restored} {literal}".strip()
        return restored

    def _apply_domain_term_corrections(self, original: str, translated: str) -> str:
        corrected = translated
        if "Comment" in original:
            corrected = corrected.replace("댓글", "논평")
        if "Comments" in original:
            corrected = corrected.replace("댓글", "논평")
        if "Airspeed" in original:
            corrected = corrected.replace("Airspeed", "대기속도")
        if "Vortex Sheet" in original:
            corrected = corrected.replace("Vortex Sheet", "와류 시트")
        if "Coe!cient" in original or "Coefficient" in original:
            corrected = corrected.replace("Coe!cient", "계수")
            corrected = corrected.replace("Coefficient", "계수")
        return corrected

    def _translate_structural_unit(self, unit: TranslationUnit) -> str | None:
        normalized = " ".join(unit.original.split()).strip()
        if not normalized:
            return None

        known_translation = self.STRUCTURAL_TRANSLATIONS.get(normalized.casefold())
        if known_translation is not None:
            return known_translation

        chapter_match = self.CHAPTER_ONLY_PATTERN.match(normalized)
        if chapter_match is not None:
            return f"{chapter_match.group('number')}장"

        if self.PART_ONLY_PATTERN.match(normalized):
            if unit.toc_page_number:
                return f"부 {unit.toc_page_number}"
            return "부"

        part_match = re.match(r"^PART\s+(?P<number>\d+)$", normalized, re.IGNORECASE)
        if part_match is not None:
            return f"부 {part_match.group('number')}"

        return None

    def _looks_like_suspicious_translation(self, original: str, text: str) -> bool:
        if not text:
            return False
        source = original.casefold()
        allowed_source_terms = {
            "관련검색": "related search",
            "검색사이트": "search site",
            "다운로드": "download",
            "브랜드명": "brand name",
            "상품명": "product name",
            "publication": "publication",
        }
        for match in self.SUSPICIOUS_TRANSLATION_PATTERN.finditer(text):
            required_source = allowed_source_terms.get(match.group(0).casefold())
            if required_source is None or required_source not in source:
                return True
        return False

    def _fallback_translate_original(self, original: str) -> str:
        fallback = " ".join(original.split()).strip()
        if not fallback:
            return fallback

        chapter_match = self.CHAPTER_ONLY_PATTERN.match(fallback)
        if chapter_match is not None:
            return f"{chapter_match.group('number')}장"

        part_match = re.match(r"^PART\s+(?P<number>\d+)$", fallback, re.IGNORECASE)
        if part_match is not None:
            return f"부 {part_match.group('number')}"

        for source, target in self.FALLBACK_PHRASE_REPLACEMENTS:
            fallback = fallback.replace(source, target)
        return fallback

    def _split_toc_unit(self, unit: TranslationUnit) -> list[TranslationUnit]:
        matches = list(self.TOC_LEADER_PATTERN.finditer(unit.original))
        if matches:
            segments: list[tuple[str, str]] = []
            previous_end = 0
            for match in matches:
                title = unit.original[previous_end : match.start()].strip()
                page_number = match.group("page").strip()
                if title and page_number:
                    segments.append((title, page_number))
                previous_end = match.end()

            if len(segments) <= 1 and unit.original.count(".") < 8:
                return [unit]
            if not segments:
                return [unit]

            return self._subdivide_toc_bbox(unit, segments)

        if unit.label.strip().lower() != "list item":
            return [unit]
        match = self.TOC_TRAILING_PAGE_PATTERN.match(unit.original.strip())
        if match is None:
            return [unit]

        title = match.group("title").strip()
        page_number = match.group("page").strip()
        if not title or not page_number:
            return [unit]
        return self._subdivide_toc_bbox(unit, [(title, page_number)])

    def _split_list_item_unit(self, unit: TranslationUnit) -> list[TranslationUnit]:
        if unit.label.strip().lower() != "list item":
            return [unit]

        segments = self._split_list_item_content(unit.original)
        if len(segments) <= 1:
            return [unit]

        return self._subdivide_unit_bbox(unit, segments)

    def _split_list_item_content(self, content: str) -> list[str]:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) > 1:
            return lines

        text = content.strip()
        if not text:
            return []

        section_matches = list(self.SECTION_ITEM_PATTERN.finditer(text))
        if len(section_matches) > 1:
            parts: list[str] = []
            for index, match in enumerate(section_matches):
                start = match.start()
                end = (
                    section_matches[index + 1].start()
                    if index + 1 < len(section_matches)
                    else len(text)
                )
                segment = text[start:end].strip()
                if segment:
                    parts.append(segment)
            if parts:
                return parts

        matches = list(re.finditer(r"[●•▪◦■□]|(?:(?<!\S)\d+[.)])", text))
        if len(matches) <= 1:
            return [text]

        parts: list[str] = []
        if matches[0].start() > 0:
            leading = text[: matches[0].start()].strip()
            if leading:
                parts.append(leading)

        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = text[start:end].strip()
            if segment:
                parts.append(segment)
        return parts or [text]

    def _normalize_special_units(self, unit: TranslationUnit) -> list[TranslationUnit]:
        if unit.toc_page_number and self.PART_ONLY_PATTERN.match(unit.original.strip()):
            return [
                replace(
                    unit,
                    label="paragraph",
                    original=f"PART {unit.toc_page_number}",
                    toc_page_number="",
                )
            ]

        normalized = " ".join(unit.original.split()).strip()
        if unit.toc_page_number:
            return [unit]

        inline_page_unit = self._extract_inline_page_number_unit(unit, normalized)
        if inline_page_unit is not None:
            return [inline_page_unit]

        if unit.label.strip().lower() not in {"heading", "paragraph"}:
            return [unit]

        chapter_match = self.CHAPTER_TITLE_PATTERN.match(normalized)
        if chapter_match is None:
            return [unit]

        prefix = chapter_match.group("prefix").strip()
        title = chapter_match.group("title").strip()
        if not prefix or not title:
            return [unit]

        split_units = self._subdivide_unit_bbox_with_gaps(unit, [prefix, title])
        if len(split_units) != 2:
            return [unit]

        split_units[0].original = prefix
        title_match = self.TOC_TRAILING_PAGE_PATTERN.match(title)
        if title_match is not None:
            split_units[1].original = title_match.group("title").strip()
            split_units[1].toc_page_number = title_match.group("page").strip()
        else:
            split_units[1].original = title
        return split_units

    def _extract_inline_page_number_unit(
        self,
        unit: TranslationUnit,
        normalized: str,
    ) -> TranslationUnit | None:
        match = self.TOC_TRAILING_PAGE_PATTERN.match(normalized)
        if match is None:
            return None

        title = match.group("title").strip()
        page_number = match.group("page").strip()
        if not title or not page_number:
            return None

        label = unit.label.strip().lower()
        if self.SECTION_ITEM_PATTERN.match(title):
            target_label = "list item"
        elif label == "heading" and re.match(
            r"^(?:chapter\s+)?\d+[.)]?\s+",
            title,
            re.IGNORECASE,
        ):
            target_label = "paragraph"
        else:
            return None

        return replace(
            unit,
            label=target_label,
            original=title,
            toc_page_number=page_number,
        )

    def _extract_explicit_line_segments(self, content: str) -> list[str]:
        paragraph_segments = [
            " ".join(segment.split())
            for segment in re.split(r"\n\s*\n", content)
            if segment.strip()
        ]
        if len(paragraph_segments) > 1:
            return paragraph_segments

        return [line.strip() for line in content.splitlines() if line.strip()]

    def _should_split_explicit_multiline_unit(
        self,
        unit: TranslationUnit,
        segments: list[str],
    ) -> bool:
        if len(segments) <= 1:
            return False
        if len(segments) > self.EXPLICIT_LINE_SPLIT_MAX_SEGMENTS:
            return False
        if re.search(r"\n\s*\n", unit.original):
            return True
        if unit.font_size is None or unit.font_size <= 0:
            return False

        bbox_width = abs(unit.bbox[2] - unit.bbox[0])
        bbox_height = abs(unit.bbox[3] - unit.bbox[1])
        if bbox_width <= 0 or bbox_height <= 0:
            return False

        visible_lengths = [len(re.sub(r"\s+", "", segment)) for segment in segments]
        if not visible_lengths or max(visible_lengths) <= 0:
            return False

        estimated_chars_per_line = bbox_width / max(unit.font_size * 0.55, 1.0)
        if (
            estimated_chars_per_line
            >= max(visible_lengths) * self.EXPLICIT_LINE_SPLIT_WIDTH_RATIO
        ):
            return True

        average_line_height = bbox_height / len(segments)
        return (
            average_line_height
            >= unit.font_size * self.EXPLICIT_LINE_SPLIT_HEIGHT_RATIO
            and max(visible_lengths) <= estimated_chars_per_line * 1.15
        )

    def _subdivide_unit_bbox(
        self,
        unit: TranslationUnit,
        segments: list[str],
    ) -> list[TranslationUnit]:
        left, bottom, right, top = unit.bbox
        total_height = abs(top - bottom)
        if total_height <= 0:
            return [unit]

        segment_line_counts: list[int] = []
        for segment in segments:
            segment_line_counts.append(
                max(1, self._estimate_line_count(segment, unit.bbox, unit.font_size))
            )

        total_weight = max(sum(segment_line_counts), 1)
        current_top = top
        split_units: list[TranslationUnit] = []
        for index, segment in enumerate(segments):
            weight = segment_line_counts[index]
            if index == len(segments) - 1:
                segment_bottom = bottom
            else:
                segment_height = total_height * weight / total_weight
                segment_bottom = current_top - segment_height

            segment_bbox = [left, segment_bottom, right, current_top]
            estimated_line_count = self._estimate_line_count(
                segment,
                segment_bbox,
                unit.font_size,
            )
            split_units.append(
                TranslationUnit(
                    unit_id=unit.unit_id,
                    page_number=unit.page_number,
                    label=unit.label,
                    bbox=segment_bbox,
                    original=segment,
                    font_size=unit.font_size,
                    font_name=unit.font_name,
                    estimated_line_count=estimated_line_count,
                    line_height_pt=self._estimate_line_height(
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                    letter_spacing_em=self._estimate_letter_spacing(
                        segment,
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                )
            )
            current_top = segment_bottom

        return split_units

    def _subdivide_unit_bbox_with_gaps(
        self,
        unit: TranslationUnit,
        segments: list[str],
    ) -> list[TranslationUnit]:
        left, bottom, right, top = unit.bbox
        total_height = abs(top - bottom)
        if total_height <= 0:
            return [unit]

        segment_line_counts = [
            max(1, len([line for line in segment.splitlines() if line.strip()]))
            for segment in segments
        ]
        if unit.font_size is not None and unit.font_size > 0:
            natural_heights = [
                max(unit.font_size * 1.2 * line_count, unit.font_size * 1.05)
                for line_count in segment_line_counts
            ]
            max_gap_height = unit.font_size * 0.85
        else:
            natural_heights = [1.0 for _ in segments]
            max_gap_height = 0.0

        total_natural_height = sum(natural_heights)
        gap_count = max(len(segments) - 1, 0)
        extra_height = max(total_height - total_natural_height, 0.0)
        gap_height = 0.0
        if gap_count > 0 and extra_height > 0:
            gap_height = min(extra_height / gap_count, max_gap_height)

        available_height = max(total_height - (gap_height * gap_count), 0.0)
        scale = available_height / max(total_natural_height, 1.0)
        scaled_heights = [height * scale for height in natural_heights]

        current_top = top
        split_units: list[TranslationUnit] = []
        for index, segment in enumerate(segments):
            if index == len(segments) - 1:
                segment_bottom = bottom
            else:
                segment_bottom = current_top - scaled_heights[index]

            segment_bbox = [left, segment_bottom, right, current_top]
            estimated_line_count = self._estimate_line_count(
                segment,
                segment_bbox,
                unit.font_size,
            )
            split_units.append(
                TranslationUnit(
                    unit_id=unit.unit_id,
                    page_number=unit.page_number,
                    label=unit.label,
                    bbox=segment_bbox,
                    original=segment,
                    font_size=unit.font_size,
                    font_name=unit.font_name,
                    estimated_line_count=estimated_line_count,
                    line_height_pt=self._estimate_line_height(
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                    letter_spacing_em=self._estimate_letter_spacing(
                        segment,
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                )
            )
            current_top = segment_bottom - gap_height

        return split_units

    def _subdivide_toc_bbox(
        self,
        unit: TranslationUnit,
        segments: list[tuple[str, str]],
    ) -> list[TranslationUnit]:
        left, bottom, right, top = unit.bbox
        total_height = abs(top - bottom)
        if total_height <= 0:
            return [unit]

        segment_count = len(segments)
        segment_height = total_height / max(segment_count, 1)
        current_top = top
        split_units: list[TranslationUnit] = []
        for index, (title, page_number) in enumerate(segments):
            segment_bottom = (
                bottom if index == segment_count - 1 else current_top - segment_height
            )
            segment_bbox = [left, segment_bottom, right, current_top]
            estimated_line_count = 1
            split_units.append(
                TranslationUnit(
                    unit_id=unit.unit_id,
                    page_number=unit.page_number,
                    label=unit.label,
                    bbox=segment_bbox,
                    original=title,
                    font_size=unit.font_size,
                    font_name=unit.font_name,
                    estimated_line_count=estimated_line_count,
                    line_height_pt=self._estimate_line_height(
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                    letter_spacing_em=self._estimate_letter_spacing(
                        title,
                        segment_bbox,
                        unit.font_size,
                        estimated_line_count,
                    ),
                    toc_page_number=page_number,
                )
            )
            current_top = segment_bottom

        return split_units

    def _build_structured_payload(
        self,
        workspace: JobWorkspace,
        request: PipelineRequest,
        units: list[TranslationUnit],
    ) -> dict[str, Any]:
        pages: dict[int, list[dict[str, Any]]] = {}
        for unit in units:
            pages.setdefault(unit.page_number, []).append(
                {
                    "id": unit.unit_id,
                    "label": unit.label,
                    "bbox": unit.bbox,
                    "content": unit.original,
                    "font_name": unit.font_name,
                    "font_size": unit.font_size,
                    "estimated_line_count": unit.estimated_line_count,
                    "line_height_pt": unit.line_height_pt,
                    "letter_spacing_em": unit.letter_spacing_em,
                    "toc_page_number": unit.toc_page_number,
                    "translated": unit.translated,
                }
            )
        return {
            "job_id": workspace.job_id,
            "source_pdf": workspace.input_pdf.name,
            "target_language": request.target_language,
            "provider": request.provider,
            "model": request.model,
            "layout_engine": self.settings.render_layout_engine,
            "pages": [
                {"page": page_number, "elements": elements}
                for page_number, elements in sorted(
                    pages.items(), key=lambda item: item[0]
                )
            ],
        }

    def _build_markdown(self, units: list[TranslationUnit]) -> str:
        chunks: list[str] = []
        current_page: int | None = None
        for unit in units:
            if unit.page_number != current_page:
                current_page = unit.page_number
                chunks.append(f"## Page {current_page}")
            chunks.append(unit.translated or unit.original)
            chunks.append("")
        return "\n".join(chunks).strip() + "\n"

    def _estimate_line_count(
        self,
        content: str,
        bbox: list[float],
        font_size: float | None,
    ) -> int:
        explicit_lines = max(
            1, len([line for line in content.splitlines() if line.strip()])
        )
        if font_size is None or font_size <= 0:
            return explicit_lines

        bbox_height = abs(bbox[3] - bbox[1])
        if bbox_height <= 0:
            return explicit_lines

        estimated = round(bbox_height / max(font_size * 1.15, 1.0))
        if len(content.strip()) >= 80:
            estimated = max(estimated, 2)
        return max(explicit_lines, min(max(estimated, 1), 24))

    def _estimate_line_height(
        self,
        bbox: list[float],
        font_size: float | None,
        estimated_line_count: int,
    ) -> float | None:
        if font_size is None or font_size <= 0:
            return None

        bbox_height = abs(bbox[3] - bbox[1])
        if bbox_height <= 0:
            return round(font_size * 1.2, 3)

        raw_line_height = bbox_height / max(estimated_line_count, 1)
        clamped_line_height = min(
            max(raw_line_height, font_size * 1.0), font_size * 1.8
        )
        return round(clamped_line_height, 3)

    def _estimate_letter_spacing(
        self,
        content: str,
        bbox: list[float],
        font_size: float | None,
        estimated_line_count: int,
    ) -> float | None:
        if font_size is None or font_size <= 0 or estimated_line_count != 1:
            return None

        visible_chars = len(re.sub(r"\s+", "", content))
        if visible_chars < 2 or visible_chars > 24:
            return None

        bbox_width = abs(bbox[2] - bbox[0])
        if bbox_width <= 0:
            return None

        avg_char_width = bbox_width / visible_chars
        em_value = (avg_char_width / font_size) - 0.55
        clamped_em = min(max(em_value, -0.05), 0.12)
        if math.isclose(clamped_em, 0.0, abs_tol=0.005):
            return None
        return round(clamped_em, 3)
