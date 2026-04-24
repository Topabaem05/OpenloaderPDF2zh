# OpenPDF2ZH Workbench

PDF translation workbench with a Gradio UI.

## Install

### Docker

```bash
cp .env.example .env
docker compose -f deploy/docker/docker-compose.yml up --build
```

Open the app:

```text
http://localhost:7860/gradio
```

Stop the app:

```bash
docker compose -f deploy/docker/docker-compose.yml down
```

View logs:

```bash
docker compose -f deploy/docker/docker-compose.yml logs -f
```

### Local Python

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .[dev]
python -m openpdf2zh
```

Open the app:

```text
http://localhost:7860/gradio
```

## Use

1. Open the Gradio UI.
2. Upload a PDF file.
3. Choose the translation service.
4. Choose the target language.
5. Click the translate button.
6. Download the translated PDF from the result panel.

## Configuration

The Docker setup uses bundled QuickMT CTranslate2 models from:

```text
resources/models/quickmt
```

To use another model directory, set this in `.env`:

```bash
OPENPDF2ZH_HOST_MODEL_DIR=/absolute/path/to/models
```

To use OpenRouter, select `openrouter` in the UI and enter the API key before starting a translation.

Generated files are stored under:

```text
workspace/
```
