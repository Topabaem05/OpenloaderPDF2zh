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

python scripts/materialize_quickmt_models.py
