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

### Docker

```bash
cp .env.example .env
docker compose -f deploy/docker/docker-compose.yml up --build
```

Open Gradio:

```text
http://localhost:7860/gradio
```

Stop Docker:

```bash
docker compose -f deploy/docker/docker-compose.yml down
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
