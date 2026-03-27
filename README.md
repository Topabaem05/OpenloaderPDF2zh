# OpenPDF2ZH Gradio

Python-only skeleton for a PDF translation pipeline built on:

- OpenDataLoader-PDF for parsing, layout analysis, OCR, and bounding boxes
- OpenRouter, Groq, or LibreTranslate for translation
- PyMuPDF for layout-aware PDF re-rendering
- Gradio for a simple local desktop-like web UI

## Goals

- Keep the implementation Python-only
- Replace the earlier Electron plan with a simple Gradio app
- Preserve layout as much as possible using bounding boxes
- Produce stable artifacts for downstream apps:
  - `translated_mono.pdf`
  - `structured.json`
  - `result.md`

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .
cp .env.example .env  # Windows: copy .env.example .env
python app.py
```

## Requirements

- Python 3.10+
- Java 11+
- OpenRouter, Groq, or LibreTranslate instance access if translation is enabled

## Self-hosted LibreTranslate

If you want to use the LibreTranslate open source server instead of a managed API-key service,
run your own instance and point the app to its base URL.

Quick local example from the LibreTranslate docs:

```bash
pip install libretranslate
libretranslate
```

Then either set the environment variable:

```bash
OPENPDF2ZH_LIBRETRANSLATE_URL=http://127.0.0.1:5000
LIBRETRANSLATE_API_KEY=
```

or enter the same base URL in the Gradio UI under **LibreTranslate server**.
Self-hosted LibreTranslate instances usually do not require an API key.

## Rendering notes

- The app preserves detected source text sizes from the OpenDataLoader parsed JSON when re-rendering translated text.
- You can preview the translated PDF directly in the Gradio UI after a run finishes.
- Optional custom font rendering is supported through PyMuPDF HTML rendering with `@font-face` and an archive-backed font file path.
- To force a specific TTF/TTC/OTF during rendering, set:

```bash
OPENPDF2ZH_RENDER_FONT_PATH=/absolute/path/to/font.ttf
```

## Environment Variables

See `.env.example`.

## Project Layout

```text
openpdf2zh_gradio/
├─ app.py
├─ agent.md
├─ pyproject.toml
├─ .env.example
├─ src/openpdf2zh/
│  ├─ config.py
│  ├─ models.py
│  ├─ pipeline.py
│  ├─ ui.py
│  ├─ providers/
│  │  ├─ base.py
│  │  ├─ groq.py
│  │  └─ openrouter.py
│  ├─ services/
│  │  ├─ parser_service.py
│  │  ├─ render_service.py
│  │  └─ translation_service.py
│  └─ utils/
│     └─ files.py
└─ tests/
```

## Notes

- This repository is a scaffold, not a finished production app.
- The hybrid backend can be started manually, or managed from Python as a subprocess.
- Rendering uses a conservative redact-and-reinsert flow and records overflow cases in a report file.
