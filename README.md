# OpenPDF2ZH Workbench

PDF translation workbench with a React/Vite review UI, FastAPI/Gradio service, and CLI entrypoints.

## Architecture

GPT Sites serves the React workbench, private document history (D1), and original/translated files (R2). A persistent Python container runs Parse → Translate → Render. Native PDF parsing, local translation models, and layout rendering cannot run inside the Sites JavaScript Worker.

- Drag and drop a PDF, preview the original, and save it to your private server history.
- Connect a translation backend to generate layout-preserving PDFs and reopen/download results later.
- Without a backend, uploads and history work; translation is explicitly unavailable.
- Deployment guide: [`docs/deployment-sites.md`](docs/deployment-sites.md)

## Install

### pip

```bash
pip install openpdf2zh-gradio
```

Run the integrated same-origin UI:

```bash
openpdf2zh serve
```

Run the backend entrypoint for a separate frontend:

```bash
openpdf2zh-server
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

### Local Development

```bash
git clone https://github.com/Topabaem05/OpenloaderPDF2zh.git
cd OpenloaderPDF2zh
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .[dev]
python -m openpdf2zh serve
```

Build and test the React workbench:

```bash
npm --prefix apps/web/workbench ci
npm --prefix apps/web/workbench run check
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Open the integrated workbench:

```text
http://localhost:7860/
```

Open the Gradio fallback:

```text
http://localhost:7860/gradio
```

Stop Docker:

```bash
docker compose down
```

Build only:

```bash
docker build -t openpdf2zh-gradio .
```

Run the built image directly:

```bash
docker run --rm -p 7860:7860 \
  -v "$PWD/workspace:/app/workspace" \
  -v "$PWD/resources/models/quickmt:/app/resources/models/quickmt:ro" \
  openpdf2zh-gradio
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
openpdf2zh translate sample.pdf \
  --model-dir /absolute/path/to/models \
  --target-language Korean
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

---

## Related Project

[OpenLife Market](https://topabaem05.github.io/openlife-market/) - Autonomous AI agents that must sell their own research to survive. Live experiment based on arXiv:2606.31046.
