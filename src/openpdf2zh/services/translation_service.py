from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, replace
from typing import Any, Iterable

from openpdf2zh.config import AppSettings, OPENROUTER_PROVIDER, normalize_provider
from openpdf2zh.models import JobWorkspace, PipelineRequest, TranslationUnit
from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.providers.ctranslate2 import CTranslate2Translator
from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.services.usage_quota import QuotaLease
from openpdf2zh.utils.geometry import bbox_area, bbox_area_ratio, bbox_iom, bbox_iou
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class TranslationService:
    DUPLICATE_BOX_AREA_RATIO_THRESHOLD = 0.8
    EXPLICIT_LINE_SPLIT_MAX_SEGMENTS = 4
    EXPLICIT_LINE_SPLIT_WIDTH_RATIO = 1.45
    EXPLICIT_LINE_SPLIT_HEIGHT_RATIO = 1.75
    EXCESSIVE_REPEAT_PATTERN = re.compile(r"([^\s])\1{9,}")
    EXCESSIVE_FRAGMENT_PATTERN = re.compile(r"([A-Za-z가-힣]{2,4})\1{4,}")
    EXCESSIVE_SPACED_TOKEN_PATTERN = re.compile(r"\b([A-Za-z가-힣])(?:\s+\1){4,}\b")
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
    SECTION_ITEM_PATTERN = re.compile(r"(?<!\S)\d+(?:\.\d+)+(?=\s)")
    CHAPTER_ONLY_PATTERN = re.compile(r"^Chapter\s+(?P<number>\d+)\s*$", re.IGNORECASE)
    CHAPTER_TITLE_PATTERN = re.compile(
        r"^(?P<prefix>Chapter\s+\d+)(?P<title>\s*[A-Z].+)$",
        re.IGNORECASE,
    )
    PART_ONLY_PATTERN = re.compile(r"^PART\s*$", re.IGNORECASE)
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
        units = self._postprocess_units(self._extract_units(raw_data))
        translator = self._build_translator(request)
        total_units = len(units)
        append_run_log(
            workspace.run_log,
            f"translation=extracted_units total={total_units} provider={request.provider}",
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
                    unit.translated = translator.translate(
                        unit.original,
                        target_language=request.target_language,
                        model=request.model,
                    )
                    unit.translated = self._postprocess_translated_text(
                        unit,
                        unit.translated,
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
            )
        if provider_key == OPENROUTER_PROVIDER:
            if not request.provider_api_key.strip():
                raise RuntimeError("OpenRouter API key is required.")
            return OpenRouterTranslator(
                request.provider_api_key,
                api_base_url=self.settings.openrouter_api_base_url,
            )
        raise ValueError(f"Unsupported provider: {request.provider}")

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

    def _postprocess_units(self, units: list[TranslationUnit]) -> list[TranslationUnit]:
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
        sanitized = self._sanitize_translated_text(text).strip()
        sanitized = self._apply_domain_term_corrections(unit.original, sanitized)
        fallback_candidate = self._fallback_translate_original(unit.original)

        structural_override = self._translate_structural_unit(unit)
        if structural_override is not None:
            return structural_override

        if fallback_candidate != normalized_original and sanitized == normalized_original:
            return fallback_candidate

        if self._looks_like_suspicious_translation(sanitized):
            return fallback_candidate

        return sanitized

    def _sanitize_translated_text(self, text: str) -> str:
        sanitized = self.EXCESSIVE_FRAGMENT_PATTERN.sub(
            lambda match: match.group(1),
            text,
        )
        sanitized = self.EXCESSIVE_SPACED_TOKEN_PATTERN.sub(
            lambda match: match.group(1),
            sanitized,
        )
        return self.EXCESSIVE_REPEAT_PATTERN.sub(
            lambda match: match.group(1),
            sanitized,
        )

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

    def _looks_like_suspicious_translation(self, text: str) -> bool:
        if not text:
            return False
        return self.SUSPICIOUS_TRANSLATION_PATTERN.search(text) is not None

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
        elif label == "heading":
            target_label = "paragraph"
        elif label == "paragraph" and len(title.split()) <= 8:
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

        estimated = int(round(bbox_height / max(font_size * 1.15, 1.0)))
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
