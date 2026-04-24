# Pip CLI Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build installable pip console commands so users can launch Gradio and translate PDFs directly from the CLI, then document pip/Docker/local installation and examples in README.

**Architecture:** Add a focused `openpdf2zh.cli` module that owns argument parsing and delegates to existing `AppSettings`, `PipelineRunner`, and `ui.launch`. Keep the existing pipeline untouched except where a reusable CLI output copy helper is useful. Package metadata exposes console scripts and includes package assets only; large CTranslate2 models stay under `resources/models/quickmt` for repo/Docker usage and can be overridden by env or CLI flags.

**Tech Stack:** Python `argparse`, setuptools console scripts, pytest, existing Gradio/FastAPI/PipelineRunner stack, README Markdown.

---

## File Structure

- Modify: `pyproject.toml`
  - Add project scripts: `openpdf2zh`, `openpdf2zh-gradio`, `openpdf2zh-translate`.
  - Add package data for `src/openpdf2zh/assets/buy-me-a-coffee.svg`.
  - Add optional `build` dependency under `dev` so wheel/sdist checks can run locally.
- Create: `src/openpdf2zh/cli.py`
  - Single CLI entrypoint.
  - Subcommands: `serve`, `translate`, `models materialize`.
  - Backward-compatible default: `openpdf2zh` with no subcommand launches Gradio.
- Modify: `src/openpdf2zh/__main__.py`
  - Delegate to `openpdf2zh.cli.main`.
- Modify: `src/openpdf2zh/ui.py`
  - Let `launch(settings: AppSettings | None = None)` accept CLI-overridden settings.
- Modify: `tools/models/materialize_quickmt_models.py`
  - Expose `materialize_quickmt_models(target_root: Path) -> Path` for CLI reuse.
- Create: `tests/test_cli.py`
  - Test command parsing, Gradio serve delegation, CLI translation output copying, model materialize delegation, and errors.
- Modify: `README.md`
  - Keep only installation and usage.
  - Add pip, pipx, Docker, local editable install, Gradio run, CLI translate examples.

---

### Task 1: Package Entry Points

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for installed console script metadata**

Append this test to new file `tests/test_cli.py`:

```python
from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_console_scripts() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["openpdf2zh"] == "openpdf2zh.cli:main"
    assert scripts["openpdf2zh-gradio"] == "openpdf2zh.cli:serve_main"
    assert scripts["openpdf2zh-translate"] == "openpdf2zh.cli:translate_main"


def test_pyproject_includes_package_asset_data() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = data["tool"]["setuptools"]["package-data"]

    assert package_data["openpdf2zh"] == ["assets/buy-me-a-coffee.svg"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_cli.py::test_pyproject_exposes_console_scripts tests/test_cli.py::test_pyproject_includes_package_asset_data -v
```

Expected: FAIL with `KeyError: 'scripts'` or `KeyError: 'package-data'`.

- [ ] **Step 3: Add console scripts and package data**

Patch `pyproject.toml`:

```toml
[project.scripts]
openpdf2zh = "openpdf2zh.cli:main"
openpdf2zh-gradio = "openpdf2zh.cli:serve_main"
openpdf2zh-translate = "openpdf2zh.cli:translate_main"

[tool.setuptools.package-data]
openpdf2zh = ["assets/buy-me-a-coffee.svg"]
```

Update `dev` dependencies in `pyproject.toml`:

```toml
dev = [
  "build>=1.2,<2",
  "pytest>=8.3,<9",
  "ruff>=0.5.0",
  "setuptools>=78.1.1,<80",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_cli.py::test_pyproject_exposes_console_scripts tests/test_cli.py::test_pyproject_includes_package_asset_data -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_cli.py
git commit -m "Add pip console script metadata"
```

---

### Task 2: CLI Serve Command

**Files:**
- Create: `src/openpdf2zh/cli.py`
- Modify: `src/openpdf2zh/__main__.py`
- Modify: `src/openpdf2zh/ui.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for Gradio serve delegation**

Append this to `tests/test_cli.py`:

```python
from openpdf2zh.config import AppSettings


def test_main_defaults_to_serve(monkeypatch, tmp_path: Path) -> None:
    from openpdf2zh import cli

    calls: list[AppSettings] = []

    def fake_launch(settings: AppSettings | None = None) -> None:
        assert settings is not None
        calls.append(settings)

    monkeypatch.setattr(cli, "launch", fake_launch)

    exit_code = cli.main([
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--workspace",
        str(tmp_path / "work"),
    ])

    assert exit_code == 0
    assert calls[0].host == "0.0.0.0"
    assert calls[0].port == 9000
    assert calls[0].workspace_root == (tmp_path / "work").resolve()


def test_serve_subcommand_launches_gradio(monkeypatch, tmp_path: Path) -> None:
    from openpdf2zh import cli

    calls: list[AppSettings] = []

    def fake_launch(settings: AppSettings | None = None) -> None:
        assert settings is not None
        calls.append(settings)

    monkeypatch.setattr(cli, "launch", fake_launch)

    exit_code = cli.main([
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "7777",
        "--workspace",
        str(tmp_path / "workspace"),
        "--provider",
        "openrouter",
        "--target-language",
        "Korean",
    ])

    assert exit_code == 0
    assert calls[0].host == "127.0.0.1"
    assert calls[0].port == 7777
    assert calls[0].workspace_root == (tmp_path / "workspace").resolve()
    assert calls[0].default_provider == "groq"
    assert calls[0].default_target_language == "Korean"


def test_module_main_delegates_to_cli(monkeypatch) -> None:
    import openpdf2zh.__main__ as module_main

    calls: list[list[str]] = []

    def fake_main(argv=None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr(module_main, "main", fake_main)

    assert module_main.main(["--help"]) == 0
    assert calls == [["--help"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_cli.py::test_main_defaults_to_serve tests/test_cli.py::test_serve_subcommand_launches_gradio tests/test_cli.py::test_module_main_delegates_to_cli -v
```

Expected: FAIL with `ImportError: cannot import name 'cli'` or `AttributeError`.

- [ ] **Step 3: Allow UI launch to receive settings**

Change `src/openpdf2zh/ui.py`:

```python
def launch(settings: AppSettings | None = None) -> None:
    from openpdf2zh.webapp import create_app

    settings = settings or AppSettings.from_env()
    start_workspace_cleanup_worker(
        settings.workspace_root,
        settings.workspace_retention_hours * 3600,
        settings.workspace_cleanup_interval_seconds,
    )
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
```

- [ ] **Step 4: Add CLI parser and serve implementation**

Create `src/openpdf2zh/cli.py`:

```python
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from openpdf2zh.config import AppSettings, normalize_provider
from openpdf2zh.ui import launch


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.handler = _handle_serve
    return int(args.handler(args))


def serve_main(argv: Sequence[str] | None = None) -> int:
    return main(["serve", *(argv or [])])


def translate_main(argv: Sequence[str] | None = None) -> int:
    return main(["translate", *(argv or [])])
```

- [ ] **Step 5: Delegate module execution to CLI**

Replace `src/openpdf2zh/__main__.py`:

```python
from __future__ import annotations

from openpdf2zh.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_cli.py::test_main_defaults_to_serve tests/test_cli.py::test_serve_subcommand_launches_gradio tests/test_cli.py::test_module_main_delegates_to_cli -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openpdf2zh/cli.py src/openpdf2zh/__main__.py src/openpdf2zh/ui.py tests/test_cli.py
git commit -m "Add Gradio serve CLI"
```

---

### Task 3: CLI Translate Command

**Files:**
- Modify: `src/openpdf2zh/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for CLI translation**

Append this to `tests/test_cli.py`:

```python
from openpdf2zh.models import JobWorkspace, PipelineResult


def _workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "workspace" / "job-1"
    public_dir = tmp_path / "workspace" / "public" / "job-1"
    input_dir = root / "input"
    parsed_dir = root / "parsed"
    output_dir = root / "output"
    logs_dir = root / "logs"
    for path in (public_dir, input_dir, parsed_dir, output_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    source_pdf = input_dir / "sample.pdf"
    source_pdf.write_bytes(b"%PDF source")
    translated_pdf = output_dir / "translated_mono.pdf"
    translated_pdf.write_bytes(b"%PDF translated")
    detected_pdf = output_dir / "detected_boxes.pdf"
    detected_pdf.write_bytes(b"%PDF detected")
    result_md = output_dir / "result.md"
    result_md.write_text("# result", encoding="utf-8")
    structured_json = output_dir / "structured.json"
    structured_json.write_text("{}", encoding="utf-8")
    return JobWorkspace(
        job_id="job-1",
        root=root,
        public_dir=public_dir,
        input_pdf=source_pdf,
        parsed_dir=parsed_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        raw_json=parsed_dir / "raw.json",
        raw_markdown=parsed_dir / "raw.md",
        structured_json=structured_json,
        translated_markdown=result_md,
        translated_pdf=translated_pdf,
        public_translated_pdf=public_dir / "translated_mono.pdf",
        detected_boxes_pdf=detected_pdf,
        public_detected_boxes_pdf=public_dir / "detected_boxes.pdf",
        translation_units_jsonl=output_dir / "translation_units.jsonl",
        render_report_json=output_dir / "render_report.json",
        run_log=logs_dir / "run.log",
    )


def test_translate_subcommand_runs_pipeline_and_copies_outputs(monkeypatch, tmp_path: Path, capsys) -> None:
    from openpdf2zh import cli

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF input")
    output_dir = tmp_path / "out"
    captured_requests = []

    def fake_run(self, request, progress=None, quota_guard=None):
        captured_requests.append(request)
        workspace = _workspace(tmp_path)
        return PipelineResult(
            workspace=workspace,
            translated_unit_count=3,
            overflow_count=0,
            provider=request.provider,
            model=request.model,
            target_language=request.target_language,
            summary_markdown="ok",
        )

    monkeypatch.setattr("openpdf2zh.cli.PipelineRunner.run", fake_run)

    exit_code = cli.main([
        "translate",
        str(input_pdf),
        "--target-language",
        "Korean",
        "--provider",
        "ctranslate2",
        "--output-dir",
        str(output_dir),
        "--page-limit",
        "2",
    ])

    assert exit_code == 0
    assert captured_requests[0].input_pdf == input_pdf.resolve()
    assert captured_requests[0].target_language == "Korean"
    assert captured_requests[0].provider == "ctranslate2"
    assert captured_requests[0].model == "auto"
    assert captured_requests[0].page_limit == 2
    assert (output_dir / "translated_mono.pdf").read_bytes() == b"%PDF translated"
    assert (output_dir / "detected_boxes.pdf").read_bytes() == b"%PDF detected"
    assert (output_dir / "result.md").read_text(encoding="utf-8") == "# result"
    assert (output_dir / "structured.json").read_text(encoding="utf-8") == "{}"
    assert "translated_mono.pdf" in capsys.readouterr().out


def test_translate_rejects_non_pdf_input(tmp_path: Path) -> None:
    from openpdf2zh import cli

    input_file = tmp_path / "input.txt"
    input_file.write_text("not a pdf", encoding="utf-8")

    exit_code = cli.main(["translate", str(input_file)])

    assert exit_code == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_cli.py::test_translate_subcommand_runs_pipeline_and_copies_outputs tests/test_cli.py::test_translate_rejects_non_pdf_input -v
```

Expected: FAIL because `translate` subcommand is not implemented.

- [ ] **Step 3: Add translate subcommand arguments**

Update `build_parser()` in `src/openpdf2zh/cli.py`:

```python
from openpdf2zh.models import PipelineRequest
from openpdf2zh.pipeline import PipelineRunner
from openpdf2zh.utils.files import make_job_id
import shutil
import sys
```

Add the parser:

```python
    translate = subparsers.add_parser("translate", help="Translate a PDF from the CLI.")
    translate.add_argument("input_pdf", help="Input PDF path.")
    translate.add_argument("--output-dir", default=None, help="Directory for generated outputs.")
    translate.add_argument("--target-language", default=None, help="Target language.")
    translate.add_argument("--provider", default=None, help="Provider: ctranslate2 or openrouter.")
    translate.add_argument("--model", default=None, help="Provider model. Defaults to auto or OpenRouter fixed model.")
    translate.add_argument("--openrouter-api-key", default=None, help="OpenRouter API key.")
    translate.add_argument("--workspace", default=None, help="Workspace directory.")
    translate.add_argument("--page-limit", type=int, default=None, help="Limit pages for a quick run.")
    translate.add_argument("--font-size", type=float, default=None, help="Base render font size.")
    translate.add_argument("--layout-engine", choices=["legacy", "pretext"], default=None)
    translate.add_argument("--model-dir", default=None, help="CTranslate2 model directory.")
    translate.add_argument("--tokenizer-path", default=None, help="CTranslate2 tokenizer path.")
    translate.set_defaults(handler=_handle_translate)
```

- [ ] **Step 4: Implement translate handler**

Add to `src/openpdf2zh/cli.py`:

```python
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
        updates["ctranslate2_model_dir"] = str(Path(args.model_dir).expanduser().resolve())
    if args.tokenizer_path:
        updates["ctranslate2_tokenizer_path"] = str(Path(args.tokenizer_path).expanduser().resolve())
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
    model = args.model or settings.default_model
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
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else result.workspace.output_dir
    copied = _copy_cli_outputs(result, output_dir)
    print(result.summary_markdown)
    print("")
    print("Generated files:")
    for path in copied:
        print(f"- {path}")
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_cli.py::test_translate_subcommand_runs_pipeline_and_copies_outputs tests/test_cli.py::test_translate_rejects_non_pdf_input -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openpdf2zh/cli.py tests/test_cli.py
git commit -m "Add PDF translation CLI"
```

---

### Task 4: Model Materialization CLI

**Files:**
- Modify: `tools/models/materialize_quickmt_models.py`
- Modify: `src/openpdf2zh/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for `models materialize`**

Append this to `tests/test_cli.py`:

```python
def test_models_materialize_delegates_to_model_tool(monkeypatch, tmp_path: Path, capsys) -> None:
    from openpdf2zh import cli

    calls: list[Path] = []

    def fake_materialize(target_root: Path) -> Path:
        calls.append(target_root)
        target_root.mkdir(parents=True)
        return target_root

    monkeypatch.setattr(cli, "materialize_quickmt_models", fake_materialize)

    exit_code = cli.main([
        "models",
        "materialize",
        "--target-dir",
        str(tmp_path / "quickmt"),
    ])

    assert exit_code == 0
    assert calls == [(tmp_path / "quickmt").resolve()]
    assert str(tmp_path / "quickmt") in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_cli.py::test_models_materialize_delegates_to_model_tool -v
```

Expected: FAIL because `models` command is not implemented.

- [ ] **Step 3: Expose reusable model materialization function**

Modify `tools/models/materialize_quickmt_models.py`:

```python
def default_model_root(repo_root: Path) -> Path:
    return Path(
        os.getenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR")
        or repo_root / "resources" / "models" / "quickmt"
    ).expanduser().resolve()


def materialize_quickmt_models(target_root: Path) -> Path:
    target_root = target_root.expanduser().resolve()
    if has_real_models(target_root):
        return target_root

    materialize_from_hugging_face(target_root)

    if not has_real_models(target_root):
        raise RuntimeError(
            f"Failed to materialize quickmt models into {target_root} from Hugging Face. "
            "Check the configured Hugging Face repo IDs, revisions, and HF token if the model repository is private or gated."
        )
    return target_root


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    target_root = default_model_root(repo_root)
    result = materialize_quickmt_models(target_root)
    print(f"quickmt models materialized in {result}")
```

- [ ] **Step 4: Add `models materialize` parser and handler**

Add imports to `src/openpdf2zh/cli.py`:

```python
from tools.models.materialize_quickmt_models import (
    default_model_root,
    materialize_quickmt_models,
)
```

Add parser in `build_parser()`:

```python
    models = subparsers.add_parser("models", help="Manage local model assets.")
    model_subparsers = models.add_subparsers(dest="models_command", required=True)
    materialize = model_subparsers.add_parser("materialize", help="Download/materialize QuickMT models.")
    materialize.add_argument("--target-dir", default=None, help="Target model root.")
    materialize.set_defaults(handler=_handle_models_materialize)
```

Add handler:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_cli.py::test_models_materialize_delegates_to_model_tool -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/models/materialize_quickmt_models.py src/openpdf2zh/cli.py tests/test_cli.py
git commit -m "Add model materialization CLI"
```

---

### Task 5: README Installation and Usage Examples

**Files:**
- Modify: `README.md`
- Test: `tests/test_readme.py`

- [ ] **Step 1: Write failing README content test**

Create `tests/test_readme.py`:

```python
from __future__ import annotations

from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_installation_paths_and_cli_examples() -> None:
    text = README.read_text(encoding="utf-8")

    required = [
        "pip install openpdf2zh-gradio",
        "pipx install openpdf2zh-gradio",
        "pip install -e .[dev]",
        "docker compose up --build",
        "openpdf2zh serve",
        "openpdf2zh-gradio",
        "openpdf2zh translate sample.pdf --target-language Korean --output-dir out",
        "openpdf2zh-translate sample.pdf --target-language Korean --output-dir out",
        "openpdf2zh models materialize",
        "OPENPDF2ZH_HOST_MODEL_DIR=/absolute/path/to/models",
    ]
    for snippet in required:
        assert snippet in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_readme.py -v
```

Expected: FAIL because new pip/CLI examples are absent.

- [ ] **Step 3: Replace README with installation and usage only**

Replace `README.md` with:

```markdown
# OpenPDF2ZH Workbench

PDF translation workbench with Gradio and CLI entrypoints.

## Install

### pip

```bash
pip install openpdf2zh-gradio
```

Run Gradio:

```bash
openpdf2zh serve
```

Equivalent Gradio shortcut:

```bash
openpdf2zh-gradio
```

### pipx

```bash
pipx install openpdf2zh-gradio
openpdf2zh serve
```

### Local development

```bash
git clone https://github.com/Topabaem05/OpenloaderPDF2zh.git
cd OpenloaderPDF2zh
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .[dev]
python -m openpdf2zh serve
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Open Gradio:

```text
http://localhost:7860/gradio
```

Stop Docker:

```bash
docker compose down
```

## CLI Usage

Translate a PDF:

```bash
openpdf2zh translate sample.pdf --target-language Korean --output-dir out
```

Equivalent shortcut:

```bash
openpdf2zh-translate sample.pdf --target-language Korean --output-dir out
```

Translate with OpenRouter:

```bash
openpdf2zh translate sample.pdf \
  --provider openrouter \
  --openrouter-api-key "$OPENROUTER_API_KEY" \
  --target-language Korean \
  --output-dir out
```

Limit pages for a quick test:

```bash
openpdf2zh translate sample.pdf --page-limit 2 --output-dir out
```

Prepare bundled QuickMT models:

```bash
openpdf2zh models materialize
```

Use a custom local model directory:

```bash
OPENPDF2ZH_HOST_MODEL_DIR=/absolute/path/to/models
openpdf2zh translate sample.pdf --model-dir /absolute/path/to/models --target-language Korean
```

Generated CLI output includes:

```text
translated_mono.pdf
detected_boxes.pdf
result.md
structured.json
render_report.json
```

## Gradio Usage

1. Open `http://localhost:7860/gradio`.
2. Upload a PDF.
3. Choose the translation service.
4. Choose the target language.
5. Click the translate button.
6. Download the translated PDF from the result panel.

Generated workspace files are stored under `workspace/`.
```

- [ ] **Step 4: Run README test to verify it passes**

Run:

```bash
python -m pytest tests/test_readme.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_readme.py
git commit -m "Document pip and CLI usage"
```

---

### Task 6: Packaging Verification

**Files:**
- Modify: `README.md` only if verification exposes a documented command mismatch.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
python -m pytest tests/test_cli.py tests/test_readme.py tests/test_webapp.py
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python -m pytest
```

Expected: `63+` tests pass. The exact count will increase after adding `tests/test_cli.py` and `tests/test_readme.py`.

- [ ] **Step 3: Run lint**

Run:

```bash
python -m ruff check src tests
```

Expected: `All checks passed!`

- [ ] **Step 4: Build wheel and sdist**

Run:

```bash
python -m build
```

Expected:

```text
Successfully built openpdf2zh_gradio-0.1.0.tar.gz and openpdf2zh_gradio-0.1.0-py3-none-any.whl
```

- [ ] **Step 5: Install wheel into a temporary venv and verify commands**

Run:

```bash
tmpdir="$(mktemp -d)"
python -m venv "$tmpdir/venv"
"$tmpdir/venv/bin/pip" install dist/openpdf2zh_gradio-0.1.0-py3-none-any.whl
"$tmpdir/venv/bin/openpdf2zh" --help
"$tmpdir/venv/bin/openpdf2zh-gradio" --help
"$tmpdir/venv/bin/openpdf2zh-translate" --help
```

Expected: each help command exits `0` and prints usage text.

- [ ] **Step 6: Clean generated build artifacts**

Run:

```bash
rm -rf build dist src/openpdf2zh_gradio.egg-info
```

Expected: generated packaging artifacts are removed from the working tree.

- [ ] **Step 7: Commit final verification adjustments if needed**

If Task 6 required changes:

```bash
git add README.md pyproject.toml src tests
git commit -m "Verify pip package commands"
```

If Task 6 required no changes, do not create an empty commit.

---

## Self-Review

**Spec coverage:** The plan covers pip packaging, multiple installation methods, Gradio execution from CLI, direct CLI PDF translation, model preparation, README usage and examples, tests, lint, and wheel verification.

**Placeholder scan:** No TBD/TODO/implement-later placeholders remain. Every task contains exact files, exact code blocks, exact commands, and expected outcomes.

**Type consistency:** `openpdf2zh.cli.main`, `serve_main`, `translate_main`, `PipelineRequest`, `PipelineRunner.run`, `AppSettings`, and `materialize_quickmt_models` are used consistently across tasks.
