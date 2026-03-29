#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends git git-lfs openjdk-17-jre-headless
git lfs install --system

python scripts/materialize_quickmt_models.py
pip install -r requirements.txt
