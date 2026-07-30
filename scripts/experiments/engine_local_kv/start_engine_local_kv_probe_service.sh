#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
VLLM_ENV_PREFIX="${STATEBUS_VLLM_ENV_PREFIX:-${HOME}/statebus/conda-envs/vllm-qwen-cu121}"
TOKEN_FILE="${STATEBUS_KV_API_TOKEN_FILE:?STATEBUS_KV_API_TOKEN_FILE is required}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
SERVED_MODEL="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
ENGINE_ID="${STATEBUS_KV_ENGINE_ID:-statebus-kv-qwen3-32b-gpu1}"
ENGINE_GENERATION="${STATEBUS_KV_ENGINE_GENERATION:?STATEBUS_KV_ENGINE_GENERATION is required}"
GPU_INDEX="${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:-1}"
MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-$MAX_MODEL_LEN}"
MAX_LOGPROBS="${STATEBUS_VLLM_MAX_LOGPROBS:-20}"
GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
DTYPE="${STATEBUS_VLLM_DTYPE:-bfloat16}"

if [[ ! -x "$VLLM_ENV_PREFIX/bin/vllm" ]]; then
  printf '找不到 vLLM 可执行文件：%s\n' "$VLLM_ENV_PREFIX/bin/vllm" >&2
  exit 2
fi
if [[ "$GPU_INDEX" == *","* ]]; then
  printf '显式 KV 启动脚本只支持一张物理 GPU，当前配置为：%s\n' "$GPU_INDEX" >&2
  exit 2
fi
if [[ ! -s "$TOKEN_FILE" || "$(stat -c '%a' "$TOKEN_FILE")" != "600" ]]; then
  printf 'KV API token 文件必须非空且权限为 600：%s\n' "$TOKEN_FILE" >&2
  exit 2
fi

identity_files=(
  "$MODEL_PATH/config.json"
  "$MODEL_PATH/model.safetensors.index.json"
  "$MODEL_PATH/tokenizer_config.json"
  "$MODEL_PATH/tokenizer.json"
)
for identity_file in "${identity_files[@]}"; do
  if [[ ! -r "$identity_file" ]]; then
    printf '缺少模型身份文件：%s\n' "$identity_file" >&2
    exit 2
  fi
done

combined_sha256() {
  sha256sum "$@" | awk '{print $1}' | sha256sum | awk '{print $1}'
}

export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_VISIBLE_DEVICES="$GPU_INDEX"
export VLLM_USE_V1=1
export VLLM_NO_USAGE_STATS=1
export STATEBUS_KV_API_TOKEN_FILE="$TOKEN_FILE"
export STATEBUS_KV_ENGINE_GENERATION="$ENGINE_GENERATION"
export STATEBUS_KV_MODEL_ID="$SERVED_MODEL"
export STATEBUS_KV_MODEL_REVISION_DIGEST="${STATEBUS_KV_MODEL_REVISION_DIGEST:-$(combined_sha256 "$MODEL_PATH/config.json" "$MODEL_PATH/model.safetensors.index.json")}"
export STATEBUS_KV_TOKENIZER_DIGEST="${STATEBUS_KV_TOKENIZER_DIGEST:-$(combined_sha256 "$MODEL_PATH/tokenizer_config.json" "$MODEL_PATH/tokenizer.json")}"
export STATEBUS_KV_REGISTRY_MAX_ENTRIES="${STATEBUS_KV_REGISTRY_MAX_ENTRIES:-2}"
export STATEBUS_KV_REGISTRY_MAX_BYTES="${STATEBUS_KV_REGISTRY_MAX_BYTES:-2147483648}"
export STATEBUS_KV_TTL_S="${STATEBUS_KV_TTL_S:-300}"
export STATEBUS_KV_ONE_SHOT=true
export STATEBUS_KV_PIN_MEMORY=false

kv_transfer_config="$(printf '{"kv_connector":"StateBusLocalKVConnector","engine_id":"%s","kv_role":"kv_both","kv_connector_module_path":"statebus.integrations.vllm_kv.connector"}' "$ENGINE_ID")"

printf '[statebus-vllm-kv] physical_gpu=%s\n' "$CUDA_VISIBLE_DEVICES"
printf '[statebus-vllm-kv] visible_gpu_count=1\n'
printf '[statebus-vllm-kv] endpoint=http://%s:%s\n' "$HOST" "$PORT"
printf '[statebus-vllm-kv] engine_generation=%s\n' "$ENGINE_GENERATION"
printf '[statebus-vllm-kv] automatic_prefix_caching=disabled\n'
printf '[statebus-vllm-kv] registry_pin_memory=false\n'

exec "$VLLM_ENV_PREFIX/bin/vllm" serve "$MODEL_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  --served-model-name "$SERVED_MODEL" \
  --dtype "$DTYPE" \
  --tensor-parallel-size 1 \
  --pipeline-parallel-size 1 \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --max-logprobs "$MAX_LOGPROBS" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --generation-config vllm \
  --no-enable-prefix-caching \
  --enforce-eager \
  --disable-frontend-multiprocessing \
  --disable-log-requests \
  --enable-request-id-headers \
  --kv-transfer-config "$kv_transfer_config" \
  --worker-extension-cls statebus.integrations.vllm_kv.worker_extension.StateBusKVWorkerExtension \
  --middleware statebus.integrations.vllm_kv.middleware.KVHandoffMiddleware
