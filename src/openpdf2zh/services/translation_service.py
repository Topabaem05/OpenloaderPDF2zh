from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Iterable

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest, TranslationUnit
from openpdf2zh.providers.base import BaseTranslator
from openpdf2zh.providers.groq import GroqTranslator
from openpdf2zh.providers.libretranslate import LibreTranslateTranslator
from openpdf2zh.providers.openrouter import OpenRouterTranslator
from openpdf2zh.utils.files import append_run_log, run_log_heartbeat, write_json


class TranslationService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def translate_document(
        self,
        request: PipelineRequest,
        workspace: JobWorkspace,
        progress: Any | None = None,
    ) -> list[TranslationUnit]:
        raw_data = json.loads(workspace.raw_json.read_text(encoding="utf-8"))
        units = list(self._extract_units(raw_data))
        translator = self._build_translator(request.provider)
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
                unit.translated = translator.translate(
                    unit.original,
                    target_language=request.target_language,
                    model=request.model,
                )
                if index == 1 or index == total_units or index % 10 == 0:
                    append_run_log(
                        workspace.run_log,
                        f"translation=progress current={index}/{total_units} page={unit.page_number} unit_id={unit.unit_id}",
                    )

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

    def _build_translator(self, provider: str) -> BaseTranslator:
        provider_key = provider.strip().lower()
        if provider_key == "openrouter":
            if not self.settings.openrouter_api_key:
                raise RuntimeError("OPENROUTER_API_KEY is missing.")
            return OpenRouterTranslator(
                self.settings.openrouter_api_key,
                app_name=self.settings.openrouter_app_name,
                app_url=self.settings.openrouter_app_url,
            )
        if provider_key == "groq":
            if not self.settings.groq_api_key:
                raise RuntimeError("GROQ_API_KEY is missing.")
            return GroqTranslator(self.settings.groq_api_key)
        if provider_key == "libretranslate":
            if not self.settings.libretranslate_url:
                raise RuntimeError("OPENPDF2ZH_LIBRETRANSLATE_URL is missing.")
            return LibreTranslateTranslator(
                self.settings.libretranslate_url,
                api_key=self.settings.libretranslate_api_key,
            )
        raise ValueError(f"Unsupported provider: {provider}")

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
                if (
                    isinstance(page, int)
                    and isinstance(bbox, list)
                    and len(bbox) == 4
                    and isinstance(content, str)
                    and content.strip()
                ):
                    counter += 1
                    units.append(
                        TranslationUnit(
                            unit_id=f"u{counter:05d}",
                            page_number=page,
                            label=label,
                            bbox=[float(value) for value in bbox],
                            original=content.strip(),
                        )
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return units

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
                    "translated": unit.translated,
                }
            )
        return {
            "job_id": workspace.job_id,
            "source_pdf": workspace.input_pdf.name,
            "target_language": request.target_language,
            "provider": request.provider,
            "model": request.model,
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
