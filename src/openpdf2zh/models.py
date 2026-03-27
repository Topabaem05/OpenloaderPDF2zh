from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PipelineRequest:
    input_pdf: Path
    target_language: str
    provider: str
    model: str
    force_ocr: bool = False
    ocr_langs: str = "ko,en,ch_sim"
    font_size: float = 10.0


@dataclass(slots=True)
class TranslationUnit:
    unit_id: str
    page_number: int
    label: str
    bbox: list[float]
    original: str
    font_size: float | None = None
    font_name: str = ""
    estimated_line_count: int = 1
    line_height_pt: float | None = None
    letter_spacing_em: float | None = None
    translated: str = ""


@dataclass(slots=True)
class JobWorkspace:
    job_id: str
    root: Path
    input_pdf: Path
    parsed_dir: Path
    output_dir: Path
    logs_dir: Path
    raw_json: Path
    raw_markdown: Path
    structured_json: Path
    translated_markdown: Path
    translated_pdf: Path
    detected_boxes_pdf: Path
    translation_units_jsonl: Path
    render_report_json: Path
    run_log: Path


@dataclass(slots=True)
class PipelineResult:
    workspace: JobWorkspace
    translated_unit_count: int
    overflow_count: int
    provider: str
    model: str
    target_language: str
    summary_markdown: str

    @property
    def workspace_dir(self) -> Path:
        return self.workspace.root

    def generated_files(self) -> list[str]:
        ordered = [
            self.workspace.translated_pdf,
            self.workspace.detected_boxes_pdf,
            self.workspace.structured_json,
            self.workspace.translated_markdown,
            self.workspace.translation_units_jsonl,
            self.workspace.run_log,
            self.workspace.render_report_json,
            self.workspace.raw_json,
            self.workspace.raw_markdown,
        ]
        return [str(path) for path in ordered if path.exists()]
