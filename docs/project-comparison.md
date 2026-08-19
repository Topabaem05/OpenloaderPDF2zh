# OpenPDF2ZH Competitive Gap Analysis

**Reviewed:** 2026-08-20  
**Scope:** open-source PDF translation tools with layout preservation, web/desktop workflows, or production deployment patterns.

## Baseline

OpenPDF2ZH already has a useful core: OpenDataLoader parsing, provider-based translation, layout reconstruction, a CLI, a Gradio fallback UI, a React workbench, job progress, Docker packaging, and stable output artifacts. The main weakness was not the translation pipeline itself; it was the production boundary between the browser UI and the stateful Python worker.

## Comparison matrix

| Capability | OpenPDF2ZH after this change | PDFMathTranslate | BabelDOC | pdf2zh-app | VS Code PDF Translate | retain-pdf-en |
|---|---:|---:|---:|---:|---:|---:|
| Layout-preserving translated PDF | Yes | Yes | Yes | Yes | Yes | Yes |
| CLI and local deployment | Yes | Yes | Yes | Partial | Extension | Yes |
| Web workbench | Yes | Yes | External integrations | Yes | No | Yes |
| Arbitrary page ranges | No; first/20/all only | Yes | Yes | Yes | Yes | Not documented |
| Batch queue | Server queue, one upload at a time | Yes | Yes | No | No | No |
| Bilingual output | No | Yes | Yes | No | Yes | No |
| Glossary / terminology constraints | No | Provider-dependent | Reference preservation | Prompt customization | Service-dependent | No |
| OCR for scanned PDFs | No explicit OCR mode | Ecosystem-dependent | No explicit UI mode | No | No | Yes |
| Cancellation / resume | No | Limited | Batch workflow | No | Yes | No |
| Provider extensibility | CTranslate2 + OpenRouter-compatible path | Broad | OpenAI-compatible endpoints | Broad | Broad | API-oriented |
| Split frontend/backend deployment | Yes, documented | Deployment-specific | Library/service integration | Desktop/local | Extension | Yes |
| Vercel-ready frontend | Yes | Not the primary path | Not the primary path | No | No | No |

## Most important gaps

### P0 — production reliability

1. **Frontend/backend coupling:** the workbench previously hard-coded same-origin `/api` and `/files` paths. A Vercel frontend could render but could not submit or retrieve translated artifacts from an external worker.
2. **Cross-origin policy:** the FastAPI backend had no explicit CORS configuration for a separately hosted frontend.
3. **Deployment reproducibility:** there was no root Vercel configuration, frontend environment contract, or frontend CI workflow.
4. **Operational transparency:** the README did not explain that translation jobs are stateful, write workspace artifacts, and should remain on a container/VM rather than a short-lived static frontend host.

These gaps are addressed by the 2026-08-20 deployment change.

### P1 — user workflow

1. Arbitrary page ranges such as `1-3,7,10-12`.
2. Multiple-file batch submission with per-file status and retry.
3. Cancel queued/running jobs and resume interrupted batches.
4. Bilingual PDF output and side-by-side review.
5. Persistent job history backed by SQLite/PostgreSQL/object storage instead of process memory.

### P2 — translation quality and document coverage

1. User glossary / protected terms / reference-text constraints.
2. OCR path for scanned or image-only PDFs.
3. Better table, equation, footnote, and multi-column validation fixtures.
4. More local language pairs and pluggable OpenAI-compatible endpoints.
5. Automated visual-regression scoring for overflow, clipping, and reading order.

## Chosen architecture

```text
Browser
  -> Vercel: React/Vite static workbench
       -> HTTPS API calls using VITE_API_BASE_URL
  -> Container/VM: FastAPI + Gradio fallback + translation worker
       -> local/persistent workspace and model assets
```

The backend returns relative artifact paths for compatibility. The frontend now resolves those paths against the configured backend origin. The backend enables CORS only for origins listed in `OPENPDF2ZH_CORS_ALLOWED_ORIGINS`; an empty value preserves same-origin-only behavior.

## Reference projects

- PDFMathTranslate: https://github.com/PDFMathTranslate/PDFMathTranslate
- BabelDOC: https://github.com/funstory-ai/BabelDOC
- pdf2zh-app: https://github.com/liunuozhi/pdf2zh-app
- VS Code PDF Translate: https://github.com/Flowers-for-Tuesday/vscode-pdf-translate
- retain-pdf-en: https://github.com/newnol/retain-pdf-en
