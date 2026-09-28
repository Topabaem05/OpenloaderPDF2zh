# GPT Sites deployment

The workbench is deployed privately on GPT Sites. D1 holds owner-scoped job metadata; R2 holds original and translated files. Every API and file request checks the platform-provided authenticated user ID. The Python engine still performs Parse → Translate → Render in a persistent container.

## Current operational boundary

Without a Python server, upload, original PDF preview, persistence, history and original download work. Translation is disabled in the UI and rejected by the API. There are no simulated translations. The hosted limit is 20 MiB per PDF to leave room within the Worker memory limit; the direct Python API retains its existing 50 MB limit.

## Connect the engine

1. Run this repository's Python Docker image on a persistent HTTPS host, with a durable `workspace` volume and the required QuickMT model assets.
2. Set `OPENPDF2ZH_API_TOKEN` to a random secret on that server. This protects `/api/`, `/files/` and `/gradio` from direct unauthenticated access.
3. Configure the private Site's runtime values `OPENPDF2ZH_BACKEND_URL=https://your-engine.example` and `OPENPDF2ZH_BACKEND_TOKEN` with the same secret. Mark the token secret; never put it in Git or a `VITE_` variable.
4. Redeploy the Site. Open a saved PDF and choose translation. Site requests reach the engine server-side, so browser CORS configuration is unnecessary.

The web UI uses the local CTranslate2 provider, English/Korean targets, page selection and the existing layout renderers. Model installation is still required on the engine. Layout preservation is best-effort: tables, figures and math use the existing rendering path; overflow warnings are surfaced. It is not a promise of pixel-identical typography.

## History and retention

Uploads are saved in R2 before a D1 record is created, with rollback on metadata failure. Each record belongs to a platform-authenticated user; changing a URL cannot expose another user's file. File bytes are never stored in D1 or browser storage.

The Python backend stores job metadata in `workspace/job_history.sqlite3`. On restart, interrupted jobs are marked failed; successful jobs remain available. Successful workspaces contain `.keep` and are excluded from automatic cleanup. They persist until the operator explicitly removes them. Use one Python server process for its in-process execution queue.

While the page is open, active work is polled. If the browser closes, translation continues on the Python server. Reopening a history item checks completion and archives its files to R2. Until that first reopening, completed files remain on the persistent Python workspace; keep that volume backed up. Once archived, downloads no longer depend on the engine. Failed/uncertain submissions are not automatically retried, preventing duplicate translation work.

## Build

```sh
cd apps/web/workbench
npm ci
npm test
npx tsc -p tsconfig.app.json --noEmit
npm run build
```

`dist/client` contains static files; `dist/server/index.js` is the Worker entrypoint. `dist/.openai` holds logical bindings and generated migrations. `npm run build:web` builds the standalone frontend to `dist` for local Python hosting. Preserve `.openai/hosting.json` and its Site identity for future deployments. Migrations are generated with `npm run db:generate`; never edit applied migration history.

No translation backend has been provisioned by this change. Provide a running HTTPS engine before end-to-end live translation validation.
