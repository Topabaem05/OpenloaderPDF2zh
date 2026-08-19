# Vercel Frontend Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the React workbench deployable on Vercel while keeping the stateful PDF translation worker on a persistent Python backend.

**Architecture:** The Vite client reads a public backend origin from `VITE_API_BASE_URL`, sends job requests to that origin, and resolves relative artifact links against it. A dedicated Python server entrypoint applies an environment-driven CORS allowlist before Uvicorn starts. Vercel builds only the static frontend; Docker or another persistent container host runs the translation backend.

**Tech Stack:** React 19, TypeScript, Vite 7, Node.js 22 test runner, FastAPI, Starlette CORS middleware, pytest, Docker Compose, GitHub Actions, Vercel static hosting.

**Spec:** `docs/project-comparison.md`

## Global Constraints

- Preserve the Parse -> Translate -> Render pipeline.
- Preserve artifact names including `translated_mono.pdf` and `detected_boxes.pdf`.
- Do not place provider API keys in frontend environment variables.
- Keep same-origin local deployments working when no API base URL or CORS origins are configured.
- Build the frontend from `apps/web/workbench` and publish `apps/web/workbench/dist`.

---

### Task 1: Add backend-origin URL handling

**Files:**
- Create: `apps/web/workbench/src/lib/api-url.ts`
- Modify: `apps/web/workbench/src/lib/api.ts`
- Create: `apps/web/workbench/tests/api-url.test.mjs`
- Modify: `apps/web/workbench/package.json`

**Interfaces:**
- Consumes: `import.meta.env.VITE_API_BASE_URL`
- Produces: `normalizeApiBaseUrl(value)`, `buildBackendUrl(path, baseUrl)`, and `resolveBackendUrl(value, baseUrl)`.

- [x] Write failing URL tests.
- [x] Verify the missing module fails before implementation.
- [x] Implement URL normalization for create, poll, and artifact links.
- [x] Run the frontend unit tests and production build command.

### Task 2: Add explicit backend CORS configuration

**Files:**
- Modify: `src/openpdf2zh/config.py`
- Create: `src/openpdf2zh/http_config.py`
- Create: `src/openpdf2zh/server.py`
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Modify: `pyproject.toml`
- Create: `tests/test_config_cors_origins.py`
- Create: `tests/test_http_config.py`
- Create: `tests/test_server_cors_wiring.py`

**Interfaces:**
- Consumes: `OPENPDF2ZH_CORS_ALLOWED_ORIGINS`.
- Produces: `AppSettings.cors_allowed_origins`, `configure_cors(app, origins)`, and the `openpdf2zh-server` production entrypoint.

- [x] Write failing environment parsing and middleware tests.
- [x] Verify the tests fail before implementation.
- [x] Implement normalized comma-separated origins and server wiring.
- [x] Run focused Python tests.

### Task 3: Add reproducible Vercel and CI configuration

**Files:**
- Create: `vercel.json`
- Create: `apps/web/workbench/.env.example`
- Create: `.github/workflows/frontend-ci.yml`
- Modify: `.github/workflows/docker-smoke.yml`
- Modify: `.env.example`
- Modify: `compose.yaml`

**Interfaces:**
- Consumes: `VITE_API_BASE_URL` on Vercel and `OPENPDF2ZH_CORS_ALLOWED_ORIGINS` on the backend.
- Produces: deterministic Vite output at `apps/web/workbench/dist` and a Docker CORS smoke check.

- [x] Add Vercel build, output, SPA rewrite, caching, and security-header rules.
- [x] Add frontend Node 22 test/build CI.
- [x] Pass the CORS allowlist through Docker Compose and verify preflight in Docker smoke CI.
- [x] Validate JSON, YAML, focused tests, and compile commands.

### Task 4: Document architecture and remaining product gaps

**Files:**
- Modify: `README.md`
- Create: `docs/deployment-vercel.md`
- Create: `docs/project-comparison.md`

- [x] Document the split deployment contract.
- [x] Record comparison evidence and P0/P1/P2 gaps.
- [x] Add deployment and comparison links to the README.

### Task 5: Verify, commit, and deploy

- [ ] Run fresh Python tests, frontend tests, production build, JSON/YAML validation, and Python compilation.
- [ ] Create one commit from the current `main` tree.
- [ ] Fast-forward `main` after available checks pass.
- [ ] Deploy the Vercel frontend and inspect deployment/build output.
