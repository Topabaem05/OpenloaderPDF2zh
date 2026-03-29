# OpenPDF2ZH Gradio

Python-only skeleton for a PDF translation pipeline built on:

- OpenDataLoader-PDF for parsing, layout analysis, and bounding boxes
- CTranslate2 or Groq for translation
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

`pip install -e .` pulls in `opendataloader-pdf` for parsing. To refresh the upstream package in the active environment explicitly, run:

```bash
python -m pip install -U "opendataloader-pdf"
```

Upstream project: <https://github.com/opendataloader-project/opendataloader-pdf>

## Requirements

- Python 3.10+
- Java 11+
- Groq API access or a local CTranslate2 model if translation is enabled

## Local CTranslate2

If you want to run translation locally, provide a converted CTranslate2 model directory and its SentencePiece tokenizer model.

Environment variables:

```bash
OPENPDF2ZH_CTRANSLATE2_MODEL_DIR=/absolute/path/to/ctranslate2_model
OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH=/absolute/path/to/tokenizer.model
```

In the UI, choose **ctranslate2** and set the same two paths in the form.

The app also supports a directional model root that contains:

- `quickmt-ko-en/`
- `quickmt-en-ko/`

In that layout, each subdirectory should contain `model.bin`, `src.spm.model`, and `tgt.spm.model`, and `OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH` can be left blank.

## Rendering notes

- The app preserves detected source text sizes from the OpenDataLoader parsed JSON when re-rendering translated text.
- You can preview the translated PDF directly in the Gradio UI after a run finishes.
- Optional custom font rendering is supported through PyMuPDF HTML rendering with `@font-face` and an archive-backed font file path.
- Duplicate-detection cleanup for parsed boxes uses an NMS-like rule: near-identical boxes are removed by high IoU, and contained duplicates are removed only when IoM is high and the boxes are still similar in size.
- Tune it with `OPENPDF2ZH_DUPLICATE_BOX_IOU_THRESHOLD` (default `0.85`) and `OPENPDF2ZH_DUPLICATE_BOX_IOM_THRESHOLD` (default `0.9`). Higher values keep more boxes; lower values remove duplicates more aggressively.
- To force a specific TTF/TTC/OTF during rendering, set:

```bash
OPENPDF2ZH_RENDER_FONT_PATH=/absolute/path/to/font.ttf
```

## Environment Variables

See `.env.example`.

### Server queue controls

The Gradio server already uses a bounded in-process queue for document jobs.

- `OPENPDF2ZH_JOB_QUEUE_CONCURRENCY`: maximum number of translation jobs to run at the same time
- `OPENPDF2ZH_JOB_QUEUE_MAX_SIZE`: maximum number of queued requests waiting for a worker slot
- `OPENPDF2ZH_WORKSPACE_RETENTION_HOURS`: how long uploaded/generated workspaces stay on disk before automatic deletion
- `OPENPDF2ZH_WORKSPACE_CLEANUP_INTERVAL_SECONDS`: how often the server sweeps for expired workspaces

For a single host, start conservatively with small values such as:

```bash
OPENPDF2ZH_JOB_QUEUE_CONCURRENCY=2
OPENPDF2ZH_JOB_QUEUE_MAX_SIZE=8
OPENPDF2ZH_WORKSPACE_RETENTION_HOURS=24
OPENPDF2ZH_WORKSPACE_CLEANUP_INTERVAL_SECONDS=600
```

If the queue is saturated, the app now returns an explicit busy message instead of silently accepting more heavy jobs.
Completed workspaces are also deleted automatically after the configured retention period, so uploaded PDFs and translated outputs do not remain on the server indefinitely.

### Oracle Always Free Ampere A1 guidance

Oracle Always Free `VM.Standard.A1.Flex` gives up to **4 OCPUs / 24 GB RAM total** across the tenancy. Because this app parses PDFs, translates blocks, and re-renders pages on the same host, start conservatively on A1 with:

```bash
OPENPDF2ZH_JOB_QUEUE_CONCURRENCY=1
OPENPDF2ZH_JOB_QUEUE_MAX_SIZE=6
OPENPDF2ZH_WORKSPACE_RETENTION_HOURS=6
OPENPDF2ZH_WORKSPACE_CLEANUP_INTERVAL_SECONDS=600
```

Raise concurrency only after measuring CPU, RAM, and end-to-end latency on your chosen A1 allocation.

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
│  │  ├─ ctranslate2.py
│  │  └─ groq.py
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
- Rendering uses a conservative redact-and-reinsert flow and records overflow cases in a report file.
