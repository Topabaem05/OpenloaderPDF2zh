# AGENTS.md
## Purpose
Guide for coding agents working in this repository.
This file combines the product constraints in `agent.md` with commands and code patterns verified from the repo.
## Repo snapshot
- Package: `openpdf2zh-gradio`
- Language: Python 3.10+
- UI: Gradio only
- Packaging: setuptools via `pyproject.toml`
- Source root: `src/`
- Entrypoint: `python app.py`
- Tests: `pytest`
- Lint: `ruff`
## Hard constraints
- Keep the project Python-only.
- Do not add Electron, React, Vite, or frontend build tooling.
- Keep the UX single-page in Gradio when possible.
- Preserve the Parse → Translate → Render mental model.
- Keep output artifacts stable: `translated_mono.pdf`, `structured.json`, `result.md`.
- Secrets must come from environment variables only.
- Do not hardcode API keys.
## Key files
- `app.py`: local entrypoint.
- `src/openpdf2zh/ui.py`: Gradio layout, callbacks, launch config.
- `src/openpdf2zh/pipeline.py`: orchestration only.
- `src/openpdf2zh/config.py`: environment-derived settings.
- `src/openpdf2zh/models.py`: dataclasses and lightweight helpers.
- `src/openpdf2zh/services/*.py`: parser, translation, rendering.
- `src/openpdf2zh/providers/*.py`: thin provider wrappers.
- `src/openpdf2zh/utils/files.py`: workspace and file helpers.
- `tests/`: pytest tests.
- `agent.md`: existing repo-specific agent guidance.
## Commands
Setup and install:
```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .[dev]
```
Run app:
```bash
python app.py
```
Test commands (use `PYTHONPATH=src` from a source checkout):
```bash
PYTHONPATH=src python -m pytest
PYTHONPATH=src python -m pytest tests/test_models.py
PYTHONPATH=src python -m pytest tests/test_models.py::test_pipeline_request_fields
```
Lint commands:
```bash
python -m ruff check src tests
python -m ruff check .
```
Notes:
- `python -m ruff check src tests` is currently clean.
- `python -m ruff check .` currently reports `E402` in `app.py` because `sys.path` is modified before the local import.
- There is no dedicated build script; editable install is the normal packaging workflow:
```bash
pip install -e .
```
## Verified repo facts
- `pyproject.toml` defines setuptools package discovery under `src`.
- `pyproject.toml` sets pytest `testpaths = ["tests"]`.
- Dev dependencies currently include `pytest` and `ruff`.
- No `Makefile` was found.
- No `.cursorrules` or `.cursor/rules/` files were found.
- No `.github/copilot-instructions.md` file was found.
- No root `AGENTS.md` existed before this file was added.
## Architecture
Intended flow:
```text
Gradio Blocks UI
    -> PipelineRunner
        -> ParserService
        -> TranslationService
        -> RenderService
```
Respect current boundaries:
- UI handles widgets, callbacks, and launch behavior.
- `pipeline.py` orchestrates services; it should not absorb provider logic.
- Providers stay thin and OpenAI-compatible.
- File helpers stay in `utils/files.py`.
- Models stay lightweight and dataclass-based.
## Code style
### Imports
Follow the order used in `config.py`, `translation_service.py`, and `ui.py`:
1. `from __future__ import annotations`
2. standard library imports
3. third-party imports
4. local `openpdf2zh` imports
### Formatting
- Use 4-space indentation.
- Keep functions short and explicit.
- Prefer vertical formatting when calls get crowded.
- Split long strings across parentheses.
- Keep repo JSON output pretty-printed with `indent=2`.
### Types
- Use modern Python typing: `str | None`, `list[T]`, `dict[str, Any]`.
- Use `Path` for filesystem values.
- Add return annotations for public functions and methods.
- Use `Any` only at dynamic boundaries such as parsed payload traversal.
### Dataclasses
- Prefer `@dataclass(slots=True)` for structured records.
- Use dataclasses for request objects, workspace metadata, translation units, and result objects.
- Keep them explicit and lightweight.
### Naming
- Classes: `PascalCase`
- Functions, methods, variables: `snake_case`
- Constants: uppercase only when truly constant
- Env vars: `OPENPDF2ZH_*`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`
- Provider identifiers: lowercase strings such as `openrouter` and `groq`
- Prefer intent-revealing names like `prepare_workspace`, `translate_document`, `generated_files`, and `wait_for_port`.
### Error handling
- Prefer explicit, actionable exceptions.
- Current patterns:
  - `RuntimeError` for missing API keys
- `ValueError` for unsupported providers
- `FileNotFoundError` when expected parser artifacts are missing
- Error messages should say exactly what is missing or what the user should do next.
- Do not swallow exceptions silently.
### Comments and docs
- Add comments only when behavior is not obvious.
- Prefer clear names over comment-heavy code.
- Preserve repo terminology: workspace, parsed output, translation units, and render report.
### Configuration
- Centralize env-derived defaults in `AppSettings.from_env()`.
- Prefer dataclass defaults over scattered `os.getenv` calls.
- New settings should follow the existing `OPENPDF2ZH_*` prefix.
### Filesystem behavior
- Use `pathlib.Path` throughout.
- Keep workspaces under `workspace/<job_id>/`.
- Preserve subdirectories: `input/`, `parsed/`, `output/`, `logs/`.
- Preserve output filenames because downstream tooling may depend on them.
### Testing style
- Tests are simple pytest functions with plain `assert` statements.
- Put new tests under `tests/`.
- Prefer focused unit tests.
- Mirror the target module name when reasonable.
- Test defaults, transformations, and failure paths directly.
## UX guidance from `agent.md`
- Keep the workflow calm, linear, and single-page.
- Prefer `gr.Blocks` over unnecessary navigation complexity.
- Show short, direct status updates.
- Keep the primary action obvious: run translation.
- Surface overflow or backend warnings instead of hiding them.
## Avoid unless explicitly requested
- Electron
- React or Vite
- JavaScript business logic
- replacing the single-page flow with a multi-step UI
- hardcoded provider/model choices in the UI layer
## Definition of done
Before considering a task complete:
1. Run relevant pytest commands.
2. Run `python -m ruff check src tests` for Python changes.
3. Keep the Python-only constraint intact.
4. Preserve artifact names and workspace layout.
5. Keep errors actionable and user-facing.
6. Match existing repo patterns instead of inventing a new style.
