from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openpdf2zh.document.ir import DocumentIR, DocumentRun, ParagraphIR
from openpdf2zh.document.serialization import read_document_ir
from openpdf2zh.models import JobWorkspace, PipelineRequest, TranslationUnit
from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.services.translation_cache import TranslationCache
from openpdf2zh.services.translation_service import TranslationService
from openpdf2zh.services.usage_quota import QuotaLease
from openpdf2zh.translation.context import TranslationContextBuilder
from openpdf2zh.translation.contracts import TranslationRequestItem
from openpdf2zh.translation.glossary import Glossary
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class ContextTranslationService(TranslationService):
    BATCH_SIZE = 16

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.context_builder = TranslationContextBuilder()
        self.glossary = self._load_configured_glossary()
        self.translation_cache = self._load_translation_cache()

    def set_glossary(self, glossary: Glossary) -> None:
        self.glossary = glossary

    def _load_configured_glossary(self) -> Glossary:
        configured = self.settings.glossary_path.strip()
        if not configured:
            return Glossary()
        path = Path(configured).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"Glossary CSV was not found: {path}. "
                "Check OPENPDF2ZH_GLOSSARY_PATH."
            )
        return Glossary.from_csv(path)

    def _load_translation_cache(self) -> TranslationCache | None:
        if not self.settings.translation_cache_enabled:
            return None
        configured = self.settings.translation_cache_path.strip()
        path = (
            Path(configured).expanduser()
            if configured
            else self.settings.workspace_root / "service_state" / "translation_cache.sqlite3"
        )
        return TranslationCache(path)

    def translate_document(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
        quota_guard: QuotaLease | None = None,
    ) -> list[TranslationUnit]:
        if not workspace.document_ir_json.is_file():
            return super().translate_document(
                request,
                workspace,
                progress=progress,
                quota_guard=quota_guard,
            )

        document = read_document_ir(workspace.document_ir_json)
        requests = self.context_builder.build_runs(
            document,
            target_language=request.target_language,
            glossary=self.glossary if self.glossary else None,
        )
        translator = self._build_translator(request)
        run_index = self._build_run_index(document)
        total = len(requests)
        append_run_log(
            workspace.run_log,
            f"translation=document_ir total={total} provider={request.provider}",
        )
        translated_texts: list[str] = []
        current = {"translated": 0, "total": total}
        cache_hits = 0

        def heartbeat_context() -> str:
            return (
                f"current={current['translated']}/{current['total']} "
                f"cache_hits={cache_hits}"
            )

        with run_log_heartbeat(
            workspace.run_log,
            "translate-document-ir",
            context_provider=heartbeat_context,
        ):
            for start in range(0, total, self.BATCH_SIZE):
                self._check_quota(quota_guard)
                batch = requests[start : start + self.BATCH_SIZE]
                results, batch_cache_hits = self._translate_batch_with_cache(
                    translator,
                    batch,
                    request,
                )
                cache_hits += batch_cache_hits
                translated_texts.extend(results)
                current["translated"] = min(start + len(batch), total)
                if progress is not None:
                    progress_value = 0.35 + (
                        0.5 * current["translated"] / max(total, 1)
                    )
                    progress(
                        progress_value,
                        desc=(
                            f"Translating run {current['translated']}/{total}"
                        ),
                    )
                self._check_quota(quota_guard)

            units = self._build_units(
                requests,
                translated_texts,
                run_index,
            )
            structured = self._build_structured_payload(workspace, request, units)
            structured["schema_version"] = 2
            structured["document_ir"] = "parsed/document_ir.json"
            structured["translation_cache_hits"] = cache_hits
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
            append_run_log(
                workspace.run_log,
                f"translation=document_ir:done units={len(units)} cache_hits={cache_hits}",
            )
            return units

    def _translate_batch_with_cache(
        self,
        translator: BaseTranslator,
        batch: list[TranslationRequestItem],
        request: PipelineRequest,
    ) -> tuple[list[str], int]:
        resolved: list[str | None] = [None] * len(batch)
        missing_items: list[TranslationRequestItem] = []
        missing_indexes: list[int] = []
        cache_hits = 0

        for index, item in enumerate(batch):
            cached = None
            if self.translation_cache is not None:
                cached = self.translation_cache.get(
                    item,
                    provider=request.provider,
                    model=request.model,
                )
            if cached is None:
                missing_items.append(item)
                missing_indexes.append(index)
                continue
            resolved[index] = cached
            cache_hits += 1

        if missing_items:
            fresh_results = translator.translate_many(
                missing_items,
                model=request.model,
            )
            if len(fresh_results) != len(missing_items):
                raise RuntimeError(
                    "Translation provider returned a different number of results "
                    f"than requested: expected {len(missing_items)}, "
                    f"got {len(fresh_results)}."
                )
            for original_index, item, translated in zip(
                missing_indexes,
                missing_items,
                fresh_results,
                strict=True,
            ):
                sanitized = self._sanitize_translated_text(str(translated)).strip()
                if not sanitized:
                    raise RuntimeError(
                        f"Translation provider returned empty text for {item.segment_id}."
                    )
                resolved[original_index] = sanitized
                if self.translation_cache is not None:
                    self.translation_cache.put(
                        item,
                        provider=request.provider,
                        model=request.model,
                        translated_text=sanitized,
                    )

        if any(value is None for value in resolved):
            raise RuntimeError("Translation batch could not be fully resolved.")
        return [str(value) for value in resolved], cache_hits

    def _build_run_index(
        self,
        document: DocumentIR,
    ) -> dict[str, tuple[float, ParagraphIR, DocumentRun]]:
        index: dict[str, tuple[float, ParagraphIR, DocumentRun]] = {}
        for page in document.pages:
            for paragraph in page.paragraphs:
                for run in paragraph.runs:
                    if run.run_id in index:
                        raise ValueError(f"Duplicate DocumentIR run_id: {run.run_id}")
                    index[run.run_id] = (page.height, paragraph, run)
        return index

    def _build_units(
        self,
        requests: list[TranslationRequestItem],
        translated_texts: list[str],
        run_index: dict[str, tuple[float, ParagraphIR, DocumentRun]],
    ) -> list[TranslationUnit]:
        if len(requests) != len(translated_texts):
            raise RuntimeError("Translation request/result count mismatch")

        units: list[TranslationUnit] = []
        for index, (item, translated) in enumerate(
            zip(requests, translated_texts, strict=True),
            start=1,
        ):
            try:
                page_height, paragraph, run = run_index[item.segment_id]
            except KeyError as exc:
                raise RuntimeError(
                    f"Translated run is missing from DocumentIR: {item.segment_id}"
                ) from exc
            bbox = self._to_parser_bbox(page_height, run.bbox)
            font_size = run.style.font_size if run.style.font_size > 0 else None
            estimated_line_count = self._estimate_line_count(
                run.text,
                bbox,
                font_size,
            )
            units.append(
                TranslationUnit(
                    unit_id=f"u{index:05d}",
                    page_number=paragraph.page_number,
                    label=paragraph.label,
                    bbox=bbox,
                    original=run.text,
                    font_size=font_size,
                    font_name=run.style.font_name,
                    estimated_line_count=estimated_line_count,
                    line_height_pt=self._estimate_line_height(
                        bbox,
                        font_size,
                        estimated_line_count,
                    ),
                    letter_spacing_em=self._estimate_letter_spacing(
                        run.text,
                        bbox,
                        font_size,
                        estimated_line_count,
                    ),
                    translated=translated,
                )
            )
        return units

    def _to_parser_bbox(
        self,
        page_height: float,
        bbox: list[float],
    ) -> list[float]:
        left, top, right, bottom = [float(value) for value in bbox]
        return [
            left,
            float(page_height - bottom),
            right,
            float(page_height - top),
        ]
