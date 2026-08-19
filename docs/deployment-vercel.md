# Vercel Frontend Deployment

OpenPDF2ZH uses a split deployment. Vercel serves the React/Vite workbench; a container or VM runs FastAPI, Gradio, translation models, job threads, and workspace files.

## Why the backend remains external

The translation API accepts PDFs up to 50 MB, starts background work, maintains in-memory job records, and produces files in a workspace. Those requirements do not match a static Vercel frontend deployment or a small request-body serverless proxy. Deploy the Python service with Docker on Railway, Fly.io, Render, a VPS, or another persistent container platform.

## Backend configuration

Use the dedicated split-deployment server entrypoint. Docker and Docker Compose use it by default after this change.

Set the Vercel production and preview origins as a comma-separated allowlist:

```bash
OPENPDF2ZH_CORS_ALLOWED_ORIGINS=https://openloader-pdf2zh.vercel.app,https://your-preview-domain.example
```

Do not add a trailing slash. The parser normalizes and de-duplicates entries.

Verify the backend before connecting Vercel:

```bash
curl -fsS https://YOUR_BACKEND/api/health
```

Expected response:

```json
{"status":"ok"}
```

## Vercel configuration

The root `vercel.json` installs and builds `apps/web/workbench`, publishes its `dist` directory, preserves SPA routing, and adds baseline response headers.

Create the Vercel environment variable in Production, Preview, and Development as needed:

```text
VITE_API_BASE_URL=https://YOUR_BACKEND
```

The value is public browser configuration, not a secret. Do not put provider API keys in it.

## Local split-mode test

Terminal 1:

```bash
OPENPDF2ZH_CORS_ALLOWED_ORIGINS=http://localhost:5173 \
OPENPDF2ZH_HOST=0.0.0.0 \
OPENPDF2ZH_PORT=7860 \
python -m openpdf2zh.server
```

Terminal 2:

```bash
cd apps/web/workbench
cp .env.example .env.local
# Set VITE_API_BASE_URL=http://localhost:7860
npm ci
npm run dev
```

## Deployment checks

1. Open the Vercel URL and upload a small PDF.
2. Confirm `POST /api/jobs` is sent to the external backend origin.
3. Confirm polling reaches `GET /api/jobs/{job_id}`.
4. Confirm translated PDF and diagnostic artifact links use the backend origin.
5. Confirm an unlisted Origin does not receive `Access-Control-Allow-Origin`.
