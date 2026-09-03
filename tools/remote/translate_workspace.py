from __future__ import annotations

import argparse
import os
from pathlib import Path

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineRequest
from openpdf2zh.services.translation_service import TranslationService


def workspace_from_root(root: Path) -> JobWorkspace:
    input_pdfs = sorted((root / "input").glob("*.pdf"))
    if len(input_pdfs) != 1:
        raise RuntimeError(
            f"Expected one PDF under {root / 'input'}, found {len(input_pdfs)}."
        )
    return JobWorkspace(
        job_id=root.name,
        root=root,
        public_dir=root / "public",
        input_pdf=input_pdfs[0],
        parsed_dir=root / "parsed",
        output_dir=root / "output",
        logs_dir=root / "logs",
        raw_json=root / "parsed/raw.json",
        raw_markdown=root / "parsed/raw.md",
        structured_json=root / "output/structured.json",
        translated_markdown=root / "output/result.md",
        translated_pdf=root / "output/translated_mono.pdf",
        public_translated_pdf=root / "public/translated_mono.pdf",
        detected_boxes_pdf=root / "output/detected_boxes.pdf",
        public_detected_boxes_pdf=root / "public/detected_boxes.pdf",
        translation_units_jsonl=root / "output/translation_units.jsonl",
        render_report_json=root / "output/render_report.json",
        run_log=root / "logs/run.log",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate a parsed OpenPDF2ZH workspace on a GPU worker."
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--target-language", default="Korean")
    parser.add_argument(
        "--provider",
        default=os.getenv("OPENPDF2ZH_REMOTE_PROVIDER", "ctranslate2"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENPDF2ZH_REMOTE_MODEL", "auto"),
    )
    args = parser.parse_args()

    workspace = workspace_from_root(args.workspace.expanduser().resolve())
    if not workspace.raw_json.is_file():
        raise RuntimeError(f"Parsed input is missing: {workspace.raw_json}")
    workspace.output_dir.mkdir(parents=True, exist_ok=True)
    workspace.logs_dir.mkdir(parents=True, exist_ok=True)

    settings = AppSettings.from_env()
    request = PipelineRequest(
        input_pdf=workspace.input_pdf,
        target_language=args.target_language,
        provider=args.provider,
        model=args.model,
        provider_api_key=os.getenv("OPENPDF2ZH_REMOTE_API_KEY", ""),
        job_id=workspace.job_id,
        font_size=settings.base_font_size,
    )
    units = TranslationService(settings).translate_document(request, workspace)
    print(
        f"translated_units={len(units)} provider={args.provider} "
        f"device={settings.ctranslate2_device} "
        f"compute_type={settings.ctranslate2_compute_type}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
