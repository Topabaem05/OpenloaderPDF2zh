# OpenPDF2ZH Workbench

PDF translation workbench with a React/Vite review UI, FastAPI/Gradio service, and CLI entrypoints.

## Architecture

```text
Vercel (React/Vite workbench)
        |
        | VITE_API_BASE_URL
        v
Persistent container/VM (FastAPI + Gradio + translation worker + workspace)
```

The Python backend is stateful: it accepts large PDF uploads, runs background jobs, keeps job status, loads local model assets, and writes downloadable artifacts. Vercel therefore serves the static workbench, while Docker, Railway, a VPS, or another persistent container host runs the backend.

For a split frontend/backend deployment, start the backend with `openpdf2zh-server` or the Docker image. The ordinary `openpdf2zh serve` command remains the same-origin local UI path.

- Deployment guide: [`docs/deployment-vercel.md`](docs/deployment-vercel.md)
- Competitive gap analysis and roadmap: [`docs/project-comparison.md`](docs/project-comparison.md)

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

## Vercel frontend

1. Deploy the Python backend on a persistent container host.
2. Set the backend allowlist:

```text
OPENPDF2ZH_CORS_ALLOWED_ORIGINS=https://YOUR_PROJECT.vercel.app
```

3. Import this repository into Vercel and set:

```text
VITE_API_BASE_URL=https://YOUR_BACKEND
```

The root [`vercel.json`](vercel.json) installs and builds `apps/web/workbench` automatically. Relative API and artifact paths are converted to the configured backend origin in the browser.

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FTopabaem05%2FOpenloaderPDF2zh&project-name=openloader-pdf2zh&repository-name=openloader-pdf2zh&env=VITE_API_BASE_URL)

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
