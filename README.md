# OpenPDF2ZH Workbench

This 1920x1080 guide video focuses on fast parsing and the Gradio UI flow, based on a parsing backtest: OpenPDF2ZH parsed 12 pages in about 1 second, while a PDF2zh warm run took 10.89 seconds for 1 page.

<p align="center">
  <strong>OpenPDF2ZH Guide: fast parsing + Gradio UI flow (Apple-style motion)</strong>
</p>

<p align="center">
  <a href="docs/readme-video/openpdf2zh-usage-guide.mp4">
    <img src="docs/readme-video/openpdf2zh-usage-guide-preview.gif" alt="OpenPDF2ZH app usage guide video preview" width="960" />
  </a>
</p>

<p align="center">
  <a href="docs/readme-video/openpdf2zh-usage-guide.mp4">Watch the app usage guide video (MP4)</a>
</p>

`openpdf2zh_gradio` runs the FastAPI backend for the PDF translation pipeline and exposes the current Gradio UI at `/gradio`. The repository also contains the React workbench, but the Docker quick start below is Gradio-first and does not build the frontend.

## Quick Start

Run the app with one command:

```bash
make up
```

If you want to override provider or model settings before booting, copy the example environment file first:

```bash
cp .env.example .env
```

## Raw Docker Command

`make up` wraps the standard Docker Compose command:

```bash
docker compose up --build
```

Useful helpers:

```bash
make logs
make down
```

## Open the App

- Gradio UI: <http://localhost:7860/gradio>
- Root route: <http://localhost:7860/> is not the Docker quick-start UI

Uploads and generated files persist in `./workspace`.

## Minimal Configuration

- Docker injects `OPENPDF2ZH_HOST=0.0.0.0`, `OPENPDF2ZH_PORT=7860`, and `OPENPDF2ZH_WORKSPACE_ROOT=/app/workspace`.
- The default Docker setup mounts `${OPENPDF2ZH_HOST_MODEL_DIR:-./models}` to `/app/models`, so the bundled `quickmt-ko-en/` and `quickmt-en-ko/` directories work without extra steps.
- To use a different local CTranslate2 directory, set `OPENPDF2ZH_HOST_MODEL_DIR=/absolute/path/to/models` in `.env` before `make up`.
- To switch to OpenRouter, choose `openrouter` in the UI and enter the API key in the form when you start a translation.

## Troubleshooting

- `make: command not found`: install `make` or run `docker compose up --build` directly.
- `docker: command not found`: install Docker Desktop or Docker Engine first.
- If CTranslate2 cannot find a model, verify that the mounted host directory contains the expected model files and is available at `/app/models` in the container.
