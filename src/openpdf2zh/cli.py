from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from openpdf2zh.config import AppSettings, OPENROUTER_FIXED_MODEL, OPENROUTER_PROVIDER, normalize_provider
from openpdf2zh.model_assets import default_model_root, materialize_quickmt_models
from openpdf2zh.models import PipelineRequest, PipelineResult
from openpdf2zh.pipeline import PipelineRunner
from openpdf2zh.ui import launch
from openpdf2zh.utils.files import make_job_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openpdf2zh",
        description="Run OpenPDF2ZH Gradio or translate PDFs from the command line.",
    )
    _add_serve_options(parser)
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Launch the Gradio web UI.")
    _add_serve_options(serve)
    serve.set_defaults(handler=_handle_serve)

    translate = subparsers.add_parser(
        "translate",
        help="Translate a PDF from the CLI.",
    )
    translate.add_argument("input_pdf", help="Input PDF path.")
    translate.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated outputs.",
    )
    translate.add_argument("--target-language", default=None, help="Target language.")
    translate.add_argument(
        "--provider",
        default=None,
        help="Provider: ctranslate2 or openrouter.",
    )
    translate.add_argument(
        "--model",
        default=None,
        help="Provider model. Defaults to auto or configured default.",
    )
    translate.add_argument("--openrouter-api-key", default=None, help="OpenRouter API key.")
    translate.add_argument("--workspace", default=None, help="Workspace directory.")
    translate.add_argument("--page-limit", type=int, default=None, help="Limit pages.")
    translate.add_argument("--font-size", type=float, default=None, help="Render font size.")
    translate.add_argument(
        "--layout-engine",
        choices=["legacy", "pretext"],
        default=None,
        help="Render layout engine.",
    )
    translate.add_argument("--model-dir", default=None, help="CTranslate2 model directory.")
    translate.add_argument("--tokenizer-path", default=None, help="CTranslate2 tokenizer path.")
    translate.set_defaults(handler=_handle_translate)

    models = subparsers.add_parser("models", help="Manage local model assets.")
    model_subparsers = models.add_subparsers(dest="models_command", required=True)
    materialize = model_subparsers.add_parser(
        "materialize",
        help="Download/materialize QuickMT models.",
    )
    materialize.add_argument("--target-dir", default=None, help="Target model root.")
    materialize.set_defaults(handler=_handle_models_materialize)

    return parser


def _add_serve_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=None, help="Server host.")
    parser.add_argument("--port", type=int, default=None, help="Server port.")
    parser.add_argument("--workspace", default=None, help="Workspace directory.")
    parser.add_argument("--provider", default=None, help="Default provider.")
    parser.add_argument("--target-language", default=None, help="Default target language.")


def _settings_from_serve_args(args: argparse.Namespace) -> AppSettings:
    settings = AppSettings.from_env()
    updates: dict[str, object] = {}
    if args.host:
        updates["host"] = args.host
    if args.port is not None:
        updates["port"] = args.port
    if args.workspace:
        updates["workspace_root"] = Path(args.workspace).expanduser().resolve()
    if args.provider:
        updates["default_provider"] = normalize_provider(args.provider)
    if args.target_language:
        updates["default_target_language"] = args.target_language
    return replace(settings, **updates)


def _handle_serve(args: argparse.Namespace) -> int:
    launch(_settings_from_serve_args(args))
    return 0


def _settings_from_translate_args(args: argparse.Namespace) -> AppSettings:
    settings = AppSettings.from_env()
    updates: dict[str, object] = {}
    if args.workspace:
        updates["workspace_root"] = Path(args.workspace).expanduser().resolve()
    if args.provider:
        updates["default_provider"] = normalize_provider(args.provider)
    if args.target_language:
        updates["default_target_language"] = args.target_language
    if args.font_size is not None:
        updates["base_font_size"] = args.font_size
    if args.layout_engine:
        updates["render_layout_engine"] = args.layout_engine
    if args.model_dir:
        updates["ctranslate2_model_dir"] = str(
            Path(args.model_dir).expanduser().resolve()
        )
    if args.tokenizer_path:
        updates["ctranslate2_tokenizer_path"] = str(
            Path(args.tokenizer_path).expanduser().resolve()
        )
    return replace(settings, **updates)


def _copy_cli_outputs(result: PipelineResult, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in (
        result.workspace.translated_pdf,
        result.workspace.detected_boxes_pdf,
        result.workspace.translated_markdown,
        result.workspace.structured_json,
        result.workspace.render_report_json,
    ):
        if source.exists():
            target = output_dir / source.name
            shutil.copy2(source, target)
            copied.append(target)
    return copied


def _handle_translate(args: argparse.Namespace) -> int:
    input_pdf = Path(args.input_pdf).expanduser().resolve()
    if input_pdf.suffix.lower() != ".pdf" or not input_pdf.is_file():
        print(f"Input must be an existing PDF: {input_pdf}", file=sys.stderr)
        return 2

    settings = _settings_from_translate_args(args)
    provider = normalize_provider(args.provider) or settings.default_provider
    if args.model:
        model = args.model
    elif provider == "ctranslate2":
        model = "auto"
    elif provider == OPENROUTER_PROVIDER:
        model = OPENROUTER_FIXED_MODEL
    else:
        model = settings.default_model
    request = PipelineRequest(
        input_pdf=input_pdf,
        target_language=args.target_language or settings.default_target_language,
        provider=provider,
        model=model,
        job_id=make_job_id(input_pdf.stem),
        provider_api_key=args.openrouter_api_key or "",
        page_limit=args.page_limit,
        font_size=settings.base_font_size,
    )

    result = PipelineRunner(settings).run(request)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else result.workspace.output_dir
    )
    copied = _copy_cli_outputs(result, output_dir)
    print(result.summary_markdown)
    print("")
    print("Generated files:")
    for path in copied:
        print(f"- {path}")
    return 0


def _handle_models_materialize(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    target_root = (
        Path(args.target_dir).expanduser().resolve()
        if args.target_dir
        else default_model_root(repo_root)
    )
    result = materialize_quickmt_models(target_root)
    print(f"quickmt models materialized in {result}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.handler = _handle_serve
    return int(args.handler(args))


def serve_main(argv: Sequence[str] | None = None) -> int:
    return main(["serve", *(list(argv) if argv is not None else sys.argv[1:])])


def translate_main(argv: Sequence[str] | None = None) -> int:
    return main(["translate", *(list(argv) if argv is not None else sys.argv[1:])])
