#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODEL_PATH="${STATEBUS_VLLM_MODEL_PATH:-/data/models/Qwen3-32B}"
SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
HOST="${STATEBUS_VLLM_HOST:-127.0.0.1}"
PORT="${STATEBUS_VLLM_PORT:-53334}"
MAX_MODEL_LEN="${STATEBUS_VLLM_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${STATEBUS_VLLM_GPU_MEMORY_UTILIZATION:-0.82}"
MAX_NUM_SEQS="${STATEBUS_VLLM_MAX_NUM_SEQS:-1}"
MAX_NUM_BATCHED_TOKENS="${STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS:-8192}"
MAX_LOGPROBS="${STATEBUS_VLLM_MAX_LOGPROBS:-20}"
ENABLE_REQUEST_ID_HEADERS="${STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS:-1}"
EXPORT_PREFIX_COUNTERS="${STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS:-1}"
DTYPE="${STATEBUS_VLLM_DTYPE:-bfloat16}"
TENSOR_PARALLEL_SIZE="${STATEBUS_VLLM_TENSOR_PARALLEL_SIZE:-1}"
VLLM_ENV_PREFIX="${STATEBUS_VLLM_ENV_PREFIX:-/home/qcrs/statebus/conda-envs/vllm-qwen-cu121}"
TOKEN_FILE="${STATEBUS_LATENT_API_TOKEN_FILE:-${STATEBUS_LATENT_TOKEN_FILE:-}}"
MODEL_CONFIG_PATH="$MODEL_PATH/config.json"
MODEL_INDEX_PATH="$MODEL_PATH/model.safetensors.index.json"
TOKENIZER_CONFIG_PATH="$MODEL_PATH/tokenizer_config.json"
TOKENIZER_PATH="$MODEL_PATH/tokenizer.json"

: "${STATEBUS_VLLM_CUDA_VISIBLE_DEVICES:?STATEBUS_VLLM_CUDA_VISIBLE_DEVICES must match the recorded service GPU}"
: "${TOKEN_FILE:?STATEBUS_LATENT_API_TOKEN_FILE must point to a pre-created 0600 token file}"

if [[ ! -s "$TOKEN_FILE" ]]; then
  printf 'latent token file is missing or empty\n' >&2
  exit 2
fi
if [[ "$(stat -c '%a' "$TOKEN_FILE")" != "600" ]]; then
  printf 'latent token file must have mode 600\n' >&2
  exit 2
fi

if [[ ! "$MAX_LOGPROBS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'STATEBUS_VLLM_MAX_LOGPROBS must be a positive integer\n' >&2
  exit 2
fi
case "${ENABLE_REQUEST_ID_HEADERS,,}" in
  1|true|yes|on)
    ENABLE_REQUEST_ID_HEADERS=1
    ;;
  0|false|no|off)
    ENABLE_REQUEST_ID_HEADERS=0
    ;;
  *)
    printf 'STATEBUS_VLLM_ENABLE_REQUEST_ID_HEADERS must be boolean\n' >&2
    exit 2
    ;;
esac
case "${EXPORT_PREFIX_COUNTERS,,}" in
  1|true|yes|on)
    EXPORT_PREFIX_COUNTERS=1
    ;;
  0|false|no|off)
    EXPORT_PREFIX_COUNTERS=0
    ;;
  *)
    printf 'STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS must be boolean\n' >&2
    exit 2
    ;;
esac

identity_files=(
  "$MODEL_CONFIG_PATH"
  "$MODEL_INDEX_PATH"
  "$TOKENIZER_CONFIG_PATH"
  "$TOKENIZER_PATH"
)
for identity_file in "${identity_files[@]}"; do
  if [[ ! -r "$identity_file" ]]; then
    printf 'latent identity file is missing or unreadable: %s\n' "$identity_file" >&2
    exit 2
  fi
done

combined_sha256() {
  sha256sum "$@" | awk '{print $1}' | sha256sum | awk '{print $1}'
}

if [[ "${CONDA_PREFIX:-}" != "$VLLM_ENV_PREFIX" && -d "$VLLM_ENV_PREFIX" ]]; then
  if [[ -n "${CONDA_EXE:-}" ]]; then
    CONDA_BASE="$("$CONDA_EXE" info --base)"
  elif command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
  elif [[ -x "/opt/miniconda/bin/conda" ]]; then
    CONDA_BASE="$(/opt/miniconda/bin/conda info --base)"
  else
    CONDA_BASE=""
  fi
  if [[ -n "$CONDA_BASE" && -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1090
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate "$VLLM_ENV_PREFIX"
  fi
fi
if [[ "${CONDA_PREFIX:-}" != "$VLLM_ENV_PREFIX" ]]; then
  printf 'unable to activate vLLM environment: %s\n' "$VLLM_ENV_PREFIX" >&2
  exit 2
fi

if [[ "$EXPORT_PREFIX_COUNTERS" == "1" ]]; then
  export STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS=1
  export PYTHONPATH="$REPO_ROOT/scripts/vllm_exporter:$REPO_ROOT/scripts:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
else
  export STATEBUS_VLLM_EXPORT_PREFIX_COUNTERS=0
  export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
fi
export STATEBUS_LATENT_API_TOKEN_FILE="$TOKEN_FILE"
export STATEBUS_LATENT_REGISTRY_MAX_BYTES="${STATEBUS_LATENT_REGISTRY_MAX_BYTES:-67108864}"
export STATEBUS_LATENT_REGISTRY_MAX_ENTRIES="${STATEBUS_LATENT_REGISTRY_MAX_ENTRIES:-64}"
export STATEBUS_LATENT_TTL_S="${STATEBUS_LATENT_TTL_S:-60}"
export STATEBUS_LATENT_MAX_STEPS="${STATEBUS_LATENT_MAX_STEPS:-80}"
export STATEBUS_LATENT_MAX_HIDDEN_SIZE="${STATEBUS_LATENT_MAX_HIDDEN_SIZE:-8192}"
export STATEBUS_LATENT_ONE_SHOT="${STATEBUS_LATENT_ONE_SHOT:-true}"
export STATEBUS_LATENT_ALIGNMENT="${STATEBUS_LATENT_ALIGNMENT:-soft_token_topk_v1}"
export STATEBUS_LATENT_ALIGNMENT_TOP_K="${STATEBUS_LATENT_ALIGNMENT_TOP_K:-32}"
export STATEBUS_LATENT_ALIGNMENT_TEMPERATURE="${STATEBUS_LATENT_ALIGNMENT_TEMPERATURE:-1.0}"
export STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS="${STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS:-false}"
export STATEBUS_LATENT_MODEL_REVISION_DIGEST="${STATEBUS_LATENT_MODEL_REVISION_DIGEST:-$(combined_sha256 "$MODEL_CONFIG_PATH" "$MODEL_INDEX_PATH")}"
export STATEBUS_LATENT_TOKENIZER_REVISION="${STATEBUS_LATENT_TOKENIZER_REVISION:-$(combined_sha256 "$TOKENIZER_CONFIG_PATH" "$TOKENIZER_PATH")}"
export STATEBUS_LATENT_CHAT_TEMPLATE_DIGEST="${STATEBUS_LATENT_CHAT_TEMPLATE_DIGEST:-$(combined_sha256 "$TOKENIZER_CONFIG_PATH")}"
export VLLM_USE_V1="0"
export VLLM_NO_USAGE_STATS="${VLLM_NO_USAGE_STATS:-1}"
export CUDA_VISIBLE_DEVICES="$STATEBUS_VLLM_CUDA_VISIBLE_DEVICES"

case "$STATEBUS_LATENT_ALIGNMENT" in
  soft_token_topk_v1)
    ;;
  ridge_realign_v1)
    : "${STATEBUS_LATENT_ALIGNMENT_ARTIFACT:?ridge alignment requires STATEBUS_LATENT_ALIGNMENT_ARTIFACT}"
    : "${STATEBUS_LATENT_ALIGNMENT_METADATA:?ridge alignment requires STATEBUS_LATENT_ALIGNMENT_METADATA}"
    if [[ ! -r "$STATEBUS_LATENT_ALIGNMENT_ARTIFACT" ]]; then
      printf 'ridge alignment artifact is missing or unreadable\n' >&2
      exit 2
    fi
    if [[ ! -r "$STATEBUS_LATENT_ALIGNMENT_METADATA" ]]; then
      printf 'ridge alignment metadata is missing or unreadable\n' >&2
      exit 2
    fi
    ;;
  *)
    printf 'unsupported latent alignment method: %s\n' "$STATEBUS_LATENT_ALIGNMENT" >&2
    exit 2
    ;;
esac

args=(
  vllm serve "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_MODEL_NAME"
  --dtype "$DTYPE"
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
  --max-model-len "$MAX_MODEL_LEN"
  --max-num-seqs "$MAX_NUM_SEQS"
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"
  --max-logprobs "$MAX_LOGPROBS"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --enable-prefix-caching
  --enable-prompt-embeds
  --enforce-eager
  # V0's default MQ frontend client does not expose collective_rpc. Keep the
  # API middleware on the direct AsyncLLMEngine path required by the plugin.
  --disable-frontend-multiprocessing
  --worker-extension-cls v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension
  --middleware v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware
)

if [[ "$ENABLE_REQUEST_ID_HEADERS" == "1" ]]; then
  args+=(--enable-request-id-headers)
fi

printf '[statebus-vllm-latent] model_path=%s\n' "$MODEL_PATH"
printf '[statebus-vllm-latent] endpoint=http://%s:%s/v1\n' "$HOST" "$PORT"
printf '[statebus-vllm-latent] cuda_visible_devices=%s\n' "$CUDA_VISIBLE_DEVICES"
printf '[statebus-vllm-latent] tensor_parallel_size=%s\n' "$TENSOR_PARALLEL_SIZE"
printf '[statebus-vllm-latent] max_model_len=%s\n' "$MAX_MODEL_LEN"
printf '[statebus-vllm-latent] max_logprobs=%s\n' "$MAX_LOGPROBS"
printf '[statebus-vllm-latent] request_id_headers=%s\n' "$ENABLE_REQUEST_ID_HEADERS"
printf '[statebus-vllm-latent] prefix_counter_exporter=%s\n' "$EXPORT_PREFIX_COUNTERS"
printf '[statebus-vllm-latent] usage_stats=%s\n' "$([[ "$VLLM_NO_USAGE_STATS" == "1" ]] && printf disabled || printf enabled)"
printf '[statebus-vllm-latent] frontend_multiprocessing=disabled\n'
printf '[statebus-vllm-latent] latent_plugin=enabled\n'
printf '[statebus-vllm-latent] latent_alignment=%s\n' "$STATEBUS_LATENT_ALIGNMENT"
printf '[statebus-vllm-latent] latent_alignment_diagnostics=%s\n' "$STATEBUS_LATENT_ALIGNMENT_DIAGNOSTICS"

exec "${args[@]}"
