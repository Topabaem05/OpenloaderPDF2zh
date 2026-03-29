# agent.md

## Project Identity

You are working on **OpenPDF2ZH Gradio**, a **Python-only** PDF translation application.
The earlier Electron direction is no longer valid.
Do **not** add Electron, Node-only UI layers, or desktop shell code unless a later requirement explicitly reintroduces them.

The product flow is:

1. Upload a PDF in a simple Gradio UI
2. Parse the PDF with OpenDataLoader-PDF
3. Translate extracted text with CTranslate2
4. Re-render a translated mono PDF with PyMuPDF
5. Save stable artifacts into a per-job workspace

## Source of UX Principles

Follow the KT Seamless Flow principles provided in the local skill reference:

- **Consistency**: keep labels, button placement, file names, and step order stable
- **Predictability**: always present the same pipeline stages: Parse → Translate → Render → Download
- **Continuity**: keep the user on one screen; do not force navigation between views
- **Clarity**: show direct status messages, actionable errors, and stable artifact names
- **Affinity**: write friendly, plain-language messages without jargon-heavy phrasing

The app should feel calm, linear, and easy to recover from.

## Hard Constraints

1. **Python only**
2. **Gradio UI only** for the first release
3. **Local-first** parsing using OpenDataLoader-PDF
4. **Bounding-box-aware** rendering with PyMuPDF
5. Output these artifacts for every successful run:
   - `translated_mono.pdf`
   - `structured.json`
   - `result.md`
6. Secrets must come from environment variables only
7. Do not hardcode API keys
8. Prefer simple files and functions over framework-heavy abstractions

## Current Architecture

```text
Gradio Blocks UI
    -> PipelineRunner
        -> ParserService
            -> OpenDataLoader-PDF
        -> TranslationService
            -> CTranslate2Translator
        -> RenderService
            -> PyMuPDF redact + HTML textbox reinsert
```

## File and Module Responsibilities

- `app.py`: local entrypoint; should stay tiny
- `src/openpdf2zh/ui.py`: Gradio layout, events, and launch configuration
- `src/openpdf2zh/pipeline.py`: orchestration only
- `src/openpdf2zh/services/parser_service.py`: OpenDataLoader integration and parser artifact handling
- `src/openpdf2zh/services/translation_service.py`: extraction of translatable units and provider calls
- `src/openpdf2zh/services/render_service.py`: bbox conversion and PDF re-rendering
- `src/openpdf2zh/providers/*.py`: thin provider-specific wrappers
- `src/openpdf2zh/models.py`: dataclasses only
- `src/openpdf2zh/utils/files.py`: workspace/file helpers only

Keep these responsibilities separated.

## Implementation Rules

### UI

- Keep the first screen single-page and simple
- Prefer `gr.Blocks` over a maze of tabs for the main workflow
- Use a progress bar and short status text
- Keep the primary action obvious: **Run translation**
- Return generated artifact paths through Gradio file outputs
- Do not add decorative complexity before the pipeline is stable

### Parsing

- Treat OpenDataLoader-PDF as the source of truth for layout and reading order
- Preserve raw parser outputs under the job workspace
- Normalize parser output into a stable internal schema saved as `structured.json`
- Keep parsing flow simple and Java-only

### Translation

- Translate per extracted text unit, not per whole document blob
- Preserve math, LaTeX, numbers, code, citations, and technical terms where appropriate
- Keep provider-specific translation logic out of the UI layer
- Avoid provider-specific logic in the UI layer

### Rendering

- Preserve original page geometry
- Convert OpenDataLoader bbox coordinates carefully before insertion
- Redact original text region first, then insert translated text
- Prefer robust fitting behavior and record overflow cases into a report file
- Never silently discard overflow or failed insertions

## What Not to Do

- Do not add Electron
- Do not add React, Vite, or frontend build tooling
- Do not move business logic into JavaScript
- Do not make the UI multi-step if a single page can handle the workflow
- Do not tightly couple provider/model choices to code constants
- Do not assume one exact OpenDataLoader JSON schema forever; keep normalization resilient

## Workspace Contract

Every run should create a job folder under `workspace/` with at least:

```text
workspace/<job_id>/
├─ input/
├─ parsed/
│  ├─ raw.json
│  └─ raw.md
├─ output/
│  ├─ structured.json
│  ├─ result.md
│  ├─ translated_mono.pdf
│  ├─ translation_units.jsonl
│  └─ render_report.json
└─ logs/
   └─ run.log
```

Keep file names stable because external tools may depend on them.

## Error Handling Expectations

- Missing API key -> explain exactly which environment variable is missing
- Hybrid backend startup failure -> instruct the user to start it manually or disable managed mode
- No translatable units -> still produce a workspace and explain why the output is minimal
- Rendering overflow -> finish the job, but surface the warning count and report path

## Coding Style

- Use standard library first
- Use dataclasses for lightweight structured data
- Keep functions short and named by intent
- Prefer explicit paths over hidden globals
- Add comments only where behavior is non-obvious
- Keep dependencies small and justified

## Definition of Done for Future Tasks

A task is complete only if:

1. The Gradio flow still works end-to-end
2. The Python-only constraint is preserved
3. Artifact names remain stable
4. The workspace output is inspectable by a human
5. Errors remain actionable and friendly
6. New code does not break the Parse → Translate → Render mental model

## Safe Extension Priorities

If you need to extend the project, do it in this order:

1. Improve normalization of parser output
2. Improve text fitting and overflow handling
3. Add batch processing
4. Add translation memory or caching
5. Add richer review UI inside Gradio

Avoid architecture churn unless the current structure blocks delivery.
