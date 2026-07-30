#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ -f /.dockerenv ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/docker/activate_statebus_container.sh"
  STUDIO_PYTHON="${STATEBUS_CONTAINER_PYTHON:-$(command -v python3)}"
else
  STATEBUS_ENV_PREFIX="${STATEBUS_ENV_PREFIX:-${HOME}/statebus/conda-envs/statebus_host}"
  STUDIO_PYTHON="${STATEBUS_ENV_PREFIX}/bin/python"
  if [[ ! -x "$STUDIO_PYTHON" ]]; then
    echo "StateBus project Python was not found: $STUDIO_PYTHON" >&2
    exit 2
  fi
fi

export STATEBUS_HOME="${STATEBUS_HOME:-${HOME}/statebus}"
export STATEBUS_RUNS_DIR="${STATEBUS_RUNS_DIR:-${STATEBUS_HOME}/runs}"
export STATEBUS_STUDIO_RUNS_DIR="${STATEBUS_STUDIO_RUNS_DIR:-${STATEBUS_RUNS_DIR}/studio}"
export STATEBUS_WORKDIR="${STATEBUS_WORKDIR:-${STATEBUS_HOME}/work}"
export STATEBUS_MODELS_DIR="${STATEBUS_MODELS_DIR:-${STATEBUS_HOME}/models}"
export STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-${STATEBUS_MODELS_DIR}/Qwen3-Embedding-0.6B}"
export STATEBUS_STUDIO_EMBED_DEVICE="${STATEBUS_STUDIO_EMBED_DEVICE:-cpu}"
if [[ "$STATEBUS_STUDIO_EMBED_DEVICE" == cuda* ]]; then
  export STATEBUS_STUDIO_CUDA_VISIBLE_DEVICES="${STATEBUS_STUDIO_CUDA_VISIBLE_DEVICES:-1}"
  export CUDA_VISIBLE_DEVICES="${STATEBUS_STUDIO_CUDA_VISIBLE_DEVICES}"
fi
export STATEBUS_EMBED_DEVICE="${STATEBUS_STUDIO_EMBED_DEVICE}"
export STATEBUS_LLM_CONFIG_FILE="${STATEBUS_LLM_CONFIG_FILE:-${PROJECT_ROOT}/deploy/statebus_llm.local_vllm.example}"
export STATEBUS_LLM_ENV_FILE="${STATEBUS_LLM_ENV_FILE:-${PROJECT_ROOT}/deploy/statebus_llm.env.local}"
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false

if ! "$STUDIO_PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "StateBus Studio dependencies are missing. Install requirements-studio.txt in the active project environment." >&2
  exit 2
fi

if [[ -f "$STATEBUS_LLM_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATEBUS_LLM_ENV_FILE"
fi

cd "$PROJECT_ROOT"
exec "$STUDIO_PYTHON" -m statebus.studio
