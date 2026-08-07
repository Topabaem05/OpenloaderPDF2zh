from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from openpdf2zh.document.ir import DocumentIR, DocumentRun, ParagraphIR
from openpdf2zh.document.serialization import read_document_ir
from openpdf2zh.models import JobWorkspace, PipelineRequest, TranslationUnit
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
        self.glossary = Glossary()

    def set_glossary(self, glossary: Glossary) -> None:
        self.glossary = glossary

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

        def heartbeat_context() -> str:
            return f"current={current['translated']}/{current['total']}"

        with run_log_heartbeat(
            workspace.run_log,
            "translate-document-ir",
            context_provider=heartbeat_context,
        ):
            for start in range(0, total, self.BATCH_SIZE):
                self._check_quota(quota_guard)
                batch = requests[start : start + self.BATCH_SIZE]
                results = translator.translate_many(batch, model=request.model)
                if len(results) != len(batch):
                    raise RuntimeError(
                        "Translation provider returned a different number of results "
                        f"than requested: expected {len(batch)}, got {len(results)}."
                    )
                for item, translated in zip(batch, results, strict=True):
                    sanitized = self._sanitize_translated_text(str(translated)).strip()
                    if not sanitized:
                        raise RuntimeError(
                            f"Translation provider returned empty text for {item.segment_id}."
                        )
                    translated_texts.append(sanitized)
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
                f"translation=document_ir:done units={len(units)}",
            )
            return units

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
