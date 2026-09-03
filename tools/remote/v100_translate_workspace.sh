#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 SSH_HOST WORKSPACE" >&2
  exit 2
fi

ssh_host=$1
workspace=$2
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "${script_dir}/../.." && pwd)
workspace_parent=$(cd "$(dirname "${workspace}")" && pwd)
workspace="${workspace_parent}/$(basename "${workspace}")"
job_name=$(basename "${workspace}")
remote_root="openpdf2zh-v100"
remote_workspace="${remote_root}/workspaces/${job_name}"
compute_type=${OPENPDF2ZH_REMOTE_COMPUTE_TYPE:-float16}
provider=${OPENPDF2ZH_REMOTE_PROVIDER:-ctranslate2}
model=${OPENPDF2ZH_REMOTE_MODEL:-auto}
api_base_url=${OPENPDF2ZH_REMOTE_API_BASE_URL:-https://openrouter.ai/api/v1/chat/completions}
api_key=${OPENPDF2ZH_REMOTE_API_KEY:-}

if [[ ! -f "${workspace}/parsed/raw.json" ]]; then
  echo "parsed workspace is missing ${workspace}/parsed/raw.json" >&2
  exit 2
fi

ssh "${ssh_host}" "mkdir -p '${remote_root}/repo/src' '${remote_root}/repo/tools/remote' '${remote_root}/models' '${remote_workspace}/input' '${remote_workspace}/parsed' '${remote_workspace}/output' '${remote_workspace}/logs'"
rsync -az "${repo_root}/src/" "${ssh_host}:${remote_root}/repo/src/"
rsync -az "${repo_root}/tools/remote/translate_workspace.py" "${ssh_host}:${remote_root}/repo/tools/remote/translate_workspace.py"
rsync -az "${repo_root}/resources/models/quickmt/quickmt-en-ko/" "${ssh_host}:${remote_root}/models/quickmt-en-ko/"
rsync -az "${workspace}/input/" "${ssh_host}:${remote_workspace}/input/"
rsync -az "${workspace}/parsed/" "${ssh_host}:${remote_workspace}/parsed/"

ssh "${ssh_host}" "if [[ ! -x '${remote_root}/venv/bin/python' ]]; then python3 -m venv '${remote_root}/venv'; fi; '${remote_root}/venv/bin/pip' install -q 'ctranslate2>=4.7.1,<5' 'sentencepiece>=0.2,<1' 'PyMuPDF>=1.27.2,<2' 'python-dotenv>=1.0.0'; cd '${remote_root}/repo'; PYTHONPATH=src OPENPDF2ZH_CTRANSLATE2_MODEL_DIR='../models' OPENPDF2ZH_CTRANSLATE2_DEVICE=cuda OPENPDF2ZH_CTRANSLATE2_COMPUTE_TYPE='${compute_type}' OPENPDF2ZH_OPENROUTER_API_BASE_URL='${api_base_url}' OPENPDF2ZH_REMOTE_API_KEY='${api_key}' '../venv/bin/python' tools/remote/translate_workspace.py '../workspaces/${job_name}' --provider '${provider}' --model '${model}'"

rsync -az "${ssh_host}:${remote_workspace}/output/" "${workspace}/output/"
rsync -az "${ssh_host}:${remote_workspace}/logs/" "${workspace}/logs/"
