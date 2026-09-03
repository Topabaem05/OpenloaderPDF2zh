#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 SSH_HOST WORKSPACE [PAGES]" >&2
  exit 2
fi

ssh_host=$1
workspace=$2
pages=${3:-}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
workspace_parent=$(cd "$(dirname "${workspace}")" && pwd)
workspace="${workspace_parent}/$(basename "${workspace}")"
job_name=$(basename "${workspace}")
remote_root="openpdf2zh-v100"
remote_workspace="${remote_root}/workspaces/${job_name}"
model=${OPENPDF2ZH_REMOTE_MODEL:?Set OPENPDF2ZH_REMOTE_MODEL.}
api_base_url=${OPENPDF2ZH_REMOTE_API_BASE_URL:-http://127.0.0.1:8081/v1/chat/completions}
proxy_port=${OPENPDF2ZH_BABELDOC_PROXY_PORT:-18081}
qps=${OPENPDF2ZH_BABELDOC_QPS:-1}

if [[ ! ${job_name} =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "workspace name must contain only letters, digits, dot, underscore, or dash" >&2
  exit 2
fi
if [[ ! -d "${workspace}/input" ]]; then
  echo "workspace input directory is missing: ${workspace}/input" >&2
  exit 2
fi

ssh "${ssh_host}" "mkdir -p '${remote_root}/repo/tools/remote' '${remote_workspace}/input' '${remote_workspace}/babeldoc-output'"
rsync -az "${script_dir}/openai_reasoning_proxy.py" "${ssh_host}:${remote_root}/repo/tools/remote/openai_reasoning_proxy.py"
rsync -az "${workspace}/input/" "${ssh_host}:${remote_workspace}/input/"

printf -v remote_command \
  'REMOTE_ROOT=%q JOB_NAME=%q PAGES=%q MODEL=%q API_BASE_URL=%q PROXY_PORT=%q QPS=%q bash -s' \
  "${remote_root}" "${job_name}" "${pages}" "${model}" "${api_base_url}" "${proxy_port}" "${qps}"

ssh "${ssh_host}" "${remote_command}" <<'REMOTE'
set -euo pipefail

remote_workspace="${REMOTE_ROOT}/workspaces/${JOB_NAME}"
mapfile -d '' input_pdfs < <(find "${remote_workspace}/input" -maxdepth 1 -type f -name '*.pdf' -print0)
if [[ ${#input_pdfs[@]} -ne 1 ]]; then
  echo "expected one PDF under ${remote_workspace}/input, found ${#input_pdfs[@]}" >&2
  exit 2
fi

if [[ ! -x "${REMOTE_ROOT}/babeldoc-venv/bin/babeldoc" ]]; then
  python3 -m venv "${REMOTE_ROOT}/babeldoc-venv"
  "${REMOTE_ROOT}/babeldoc-venv/bin/pip" install --no-cache-dir 'BabelDOC==0.6.4'
fi

proxy="${REMOTE_ROOT}/repo/tools/remote/openai_reasoning_proxy.py"
"${REMOTE_ROOT}/venv/bin/python" "${proxy}" --self-test
"${REMOTE_ROOT}/venv/bin/python" "${proxy}" \
  --port "${PROXY_PORT}" --upstream "${API_BASE_URL}" \
  > "${remote_workspace}/babeldoc-output/proxy.log" 2>&1 &
proxy_pid=$!
trap 'kill "${proxy_pid}" 2>/dev/null || true' EXIT

proxy_ready=false
for _ in 1 2 3 4 5; do
  if curl -fsS "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; then
    proxy_ready=true
    break
  fi
  sleep 1
done
if [[ ${proxy_ready} != true ]]; then
  echo "OpenAI compatibility proxy failed to start" >&2
  exit 1
fi

page_args=()
if [[ -n ${PAGES} ]]; then
  page_args=(--pages "${PAGES}" --only-include-translated-page)
fi

"${REMOTE_ROOT}/babeldoc-venv/bin/babeldoc" \
  --files "${input_pdfs[0]}" \
  "${page_args[@]}" \
  --lang-in en --lang-out ko \
  --output "${remote_workspace}/babeldoc-output" \
  --qps "${QPS}" --pool-max-workers "${QPS}" \
  --no-auto-extract-glossary --no-dual \
  --watermark-output-mode no_watermark \
  --primary-font-family serif \
  --enable-json-mode-if-requested \
  --openai --openai-model "${MODEL}" \
  --openai-base-url "http://127.0.0.1:${PROXY_PORT}/v1" \
  --openai-api-key local --no-send-temperature \
  --custom-system-prompt "/no_think Follow the requested JSON schema exactly and return one object for every input id. Translate faithfully into Korean. Preserve placeholders, citations, equations, code, and proper names." \
  2>&1 | tee "${remote_workspace}/babeldoc-output/run.log"
REMOTE

mkdir -p "${workspace}/babeldoc-output"
rsync -az "${ssh_host}:${remote_workspace}/babeldoc-output/" "${workspace}/babeldoc-output/"
