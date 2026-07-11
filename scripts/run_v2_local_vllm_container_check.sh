#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-8b}}"
VLLM_PORT="${STATEBUS_LOCAL_VLLM_PORT:-${STATEBUS_VLLM_PORT:-53333}}"

STAMP="${STATEBUS_LOCAL_VLLM_CHECK_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_VLLM_CHECK_RUN_ID:-v2-local-vllm-check-${STAMP}}"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
HOST_CONFIG_PATH="${HOST_RESULT_ROOT}/statebus_llm.local_vllm.yaml"
CONTAINER_CONFIG_PATH="${CONTAINER_RESULT_ROOT}/statebus_llm.local_vllm.yaml"
HEALTH_TIMEOUT_S="${STATEBUS_LOCAL_VLLM_HEALTH_TIMEOUT_S:-10}"
REQUEST_TIMEOUT_S="${STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S:-120}"
PLANNER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_PLANNER_MAX_TOKENS:-1024}"
RETRIEVER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_RETRIEVER_MAX_TOKENS:-1024}"
EXECUTOR_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_EXECUTOR_MAX_TOKENS:-1536}"
SUMMARIZER_MAX_TOKENS="${STATEBUS_LOCAL_VLLM_SUMMARIZER_MAX_TOKENS:-1024}"
MAX_CONTEXT_TOKENS="${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_TOKENS:-4096}"
MAX_CONTEXT_SAFETY_MARGIN_TOKENS="${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_SAFETY_MARGIN_TOKENS:-64}"

optional_env_args=()

add_optional_env() {
  local name="$1"
  local value="${!name:-}"
  if [[ -n "$value" ]]; then
    optional_env_args+=(-e "${name}=${value}")
  fi
}

write_config() {
  mkdir -p "$HOST_RESULT_ROOT"
  cat > "$HOST_CONFIG_PATH" <<EOF
mode: local_vllm

providers:
  default:
    kind: openai_compatible
    base_url: ${VLLM_BASE_URL}
    api_key: EMPTY
    timeout_s: ${REQUEST_TIMEOUT_S}
    request_max_attempts: 1

roles:
  planner:
    provider: default
    model: ${VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${PLANNER_MAX_TOKENS}
    max_context_tokens: ${MAX_CONTEXT_TOKENS}
    max_context_safety_margin_tokens: ${MAX_CONTEXT_SAFETY_MARGIN_TOKENS}
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  retriever:
    provider: default
    model: ${VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${RETRIEVER_MAX_TOKENS}
    max_context_tokens: ${MAX_CONTEXT_TOKENS}
    max_context_safety_margin_tokens: ${MAX_CONTEXT_SAFETY_MARGIN_TOKENS}
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  executor:
    provider: default
    model: ${VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${EXECUTOR_MAX_TOKENS}
    max_context_tokens: ${MAX_CONTEXT_TOKENS}
    max_context_safety_margin_tokens: ${MAX_CONTEXT_SAFETY_MARGIN_TOKENS}
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  summarizer:
    provider: default
    model: ${VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${SUMMARIZER_MAX_TOKENS}
    max_context_tokens: ${MAX_CONTEXT_TOKENS}
    max_context_safety_margin_tokens: ${MAX_CONTEXT_SAFETY_MARGIN_TOKENS}
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
EOF
}

python_health_probe() {
  local url="$1"
  python3 - "$url" "$HEALTH_TIMEOUT_S" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.request

url = sys.argv[1]
timeout_s = float(sys.argv[2])

with urllib.request.urlopen(url, timeout=timeout_s) as response:
    payload = response.read().decode("utf-8", errors="replace")

try:
    parsed = json.loads(payload)
except json.JSONDecodeError:
    parsed = {"raw": payload}

print(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
PY
}

prepare_optional_env_args() {
  optional_env_args=()
  for optional_name in \
    CUDA_VISIBLE_DEVICES \
    TOKENIZERS_PARALLELISM \
    PYTORCH_CUDA_ALLOC_CONF \
    STATEBUS_CODEACT_SANDBOX_BACKEND \
    STATEBUS_EMBED_DEVICE \
    STATEBUS_EMBED_MODEL_PATH \
    STATEBUS_PREFIX_ALIGNMENT_MODE \
    HF_HOME \
    TRANSFORMERS_CACHE \
    STATEBUS_LLM_API_KEY \
    OPENAI_API_KEY \
    ANTHROPIC_API_KEY
  do
    add_optional_env "$optional_name"
  done
}

default_vllm_base_url() {
  local network_mode=""
  if network_mode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER_NAME" 2>/dev/null)"; then
    if [[ "$network_mode" == "host" ]]; then
      printf '%s\n' "http://127.0.0.1:${VLLM_PORT}/v1"
      return
    fi
  fi
  printf '%s\n' "http://host.docker.internal:${VLLM_PORT}/v1"
}

run_in_container() {
  prepare_optional_env_args
  docker exec -i -u 0 \
    -e STATEBUS_LLM_CONFIG_FILE="$CONTAINER_CONFIG_PATH" \
    -e STATEBUS_LOCAL_VLLM_BASE_URL="$VLLM_BASE_URL" \
    -e STATEBUS_LOCAL_VLLM_MODEL="$VLLM_MODEL" \
    "${optional_env_args[@]}" \
    "$CONTAINER_NAME" bash -lc '
      set -euo pipefail
      source /usr/local/bin/activate_statebus_container.sh
      cd "'"$CONTAINER_PROJECT_ROOT"'"
      exec "$@"
    ' -- "$@"
}

VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-$(default_vllm_base_url)}"
VLLM_HEALTH_URL="${STATEBUS_LOCAL_VLLM_HEALTH_URL:-${VLLM_BASE_URL%/v1}/health}"

if [[ $# -eq 0 ]]; then
  set -- /usr/bin/python3 -m v2.runtime.smoke --role-path-mode local_vllm
fi

write_config

echo "[statebus-local-vllm-check] run_id=$RUN_ID"
echo "[statebus-local-vllm-check] host_config=$HOST_CONFIG_PATH"
echo "[statebus-local-vllm-check] vllm_base_url=$VLLM_BASE_URL"
echo "[statebus-local-vllm-check] vllm_health_url=$VLLM_HEALTH_URL"

echo "[statebus-local-vllm-check] host health probe"
python_health_probe "$VLLM_HEALTH_URL"

echo "[statebus-local-vllm-check] container health probe"
run_in_container /usr/bin/python3 - "$VLLM_HEALTH_URL" "$HEALTH_TIMEOUT_S" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.request

url = sys.argv[1]
timeout_s = float(sys.argv[2])

with urllib.request.urlopen(url, timeout=timeout_s) as response:
    payload = response.read().decode("utf-8", errors="replace")

try:
    parsed = json.loads(payload)
except json.JSONDecodeError:
    parsed = {"raw": payload}

print(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
PY

echo "[statebus-local-vllm-check] container command: $*"
run_in_container "$@"
