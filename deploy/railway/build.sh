#!/usr/bin/env bash
set -euo pipefail

WORKBENCH_DIR="apps/web/workbench"

if [ -f "$WORKBENCH_DIR/package.json" ]; then
  npm --prefix "$WORKBENCH_DIR" install
  npm --prefix "$WORKBENCH_DIR" run build
fi

python tools/models/materialize_quickmt_models.py
