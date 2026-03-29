#!/usr/bin/env bash
set -euo pipefail

if ! command -v git >/dev/null 2>&1; then
  echo "git is required during build. Use the checked-in Railpack/Nixpacks config so the build image installs git first." >&2
  exit 1
fi

if ! command -v git-lfs >/dev/null 2>&1; then
  echo "git-lfs is required during build. Use the checked-in Railpack/Nixpacks config so the build image installs git-lfs first." >&2
  exit 1
fi

if [ -z "${OPENPDF2ZH_MODEL_BUNDLE_URL:-}" ] && [ -z "${OPENPDF2ZH_MODEL_REPO_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
  echo "No quickmt model source configured. Set OPENPDF2ZH_MODEL_BUNDLE_URL (preferred) or OPENPDF2ZH_MODEL_REPO_TOKEN/GITHUB_TOKEN for Railway builds." >&2
fi

python scripts/materialize_quickmt_models.py
