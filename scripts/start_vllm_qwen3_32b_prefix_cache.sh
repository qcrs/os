#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-8000}"
MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.95}"
MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-$MAX_MODEL_LEN}"
DTYPE="${STATEBUS_VLLM_DTYPE:-bfloat16}"
ENFORCE_EAGER="${STATEBUS_VLLM_ENFORCE_EAGER:-1}"
KV_CACHE_DTYPE="${STATEBUS_VLLM_KV_CACHE_DTYPE:-}"
export VLLM_USE_V1="${VLLM_USE_V1:-0}"

args=(
  vllm serve "$MODEL_PATH"
  --served-model-name "$SERVED_MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --dtype "$DTYPE" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --enable-prefix-caching
)

if [[ "$ENFORCE_EAGER" == "1" || "$ENFORCE_EAGER" == "true" ]]; then
  args+=(--enforce-eager)
fi

if [[ -n "$KV_CACHE_DTYPE" ]]; then
  args+=(--kv-cache-dtype "$KV_CACHE_DTYPE")
fi

exec "${args[@]}"
