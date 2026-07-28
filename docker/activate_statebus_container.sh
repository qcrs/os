#!/usr/bin/env bash

_statebus_container_restore_shell_options() {
  if [[ "${_STATEBUS_CONTAINER_HAD_ERREXIT:-0}" == "1" ]]; then
    set -o errexit
  else
    set +o errexit
  fi
  if [[ "${_STATEBUS_CONTAINER_HAD_NOUNSET:-0}" == "1" ]]; then
    set -o nounset
  else
    set +o nounset
  fi
  if [[ "${_STATEBUS_CONTAINER_HAD_PIPEFAIL:-0}" == "1" ]]; then
    set -o pipefail
  else
    set +o pipefail
  fi
}

_statebus_container_activate_main() {
  set -euo pipefail

  PROJECT_ROOT="${PROJECT_ROOT:-/workspace/statebus/project}"
  export STATEBUS_HOME="${STATEBUS_HOME:-/statebus}"
  export STATEBUS_ENV_PREFIX="${STATEBUS_ENV_PREFIX:-container-python}"
  export STATEBUS_PIP_INDEX_URL="${STATEBUS_PIP_INDEX_URL:-${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}}"
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$STATEBUS_HOME/caches/pip}"
  export PIP_INDEX_URL="${PIP_INDEX_URL:-$STATEBUS_PIP_INDEX_URL}"
  export HF_HOME="${HF_HOME:-$STATEBUS_HOME/caches/hf}"
  export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
  export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
  export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$HF_HOME/sentence_transformers}"
  export STATEBUS_WORKDIR="${STATEBUS_WORKDIR:-$STATEBUS_HOME/work}"
  export STATEBUS_STATEPOOL_DIR="${STATEBUS_STATEPOOL_DIR:-$STATEBUS_WORKDIR/statepool}"
  export STATEBUS_RUNS_DIR="${STATEBUS_RUNS_DIR:-$STATEBUS_HOME/runs}"
  export STATEBUS_LOGS_DIR="${STATEBUS_LOGS_DIR:-$STATEBUS_HOME/logs}"
  export STATEBUS_MODELS_DIR="${STATEBUS_MODELS_DIR:-$STATEBUS_HOME/models}"
  export NPM_CACHE="${NPM_CACHE:-$STATEBUS_HOME/caches/npm}"
  export NPM_CONFIG_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.local}"
  export PATH="$HOME/.local/bin${PATH:+:${PATH}}"
  export STATEBUS_LLM_CONFIG_FILE="${STATEBUS_LLM_CONFIG_FILE:-$PROJECT_ROOT/deploy/statebus_llm.yaml.local}"
  export STATEBUS_LLM_ENV_FILE="${STATEBUS_LLM_ENV_FILE:-$PROJECT_ROOT/deploy/statebus_llm.env.local}"
  export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-auto}"
  export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

  mkdir -p \
    "$PIP_CACHE_DIR" \
    "$HF_HOME" \
    "$HUGGINGFACE_HUB_CACHE" \
    "$TRANSFORMERS_CACHE" \
    "$SENTENCE_TRANSFORMERS_HOME" \
    "$STATEBUS_WORKDIR" \
    "$STATEBUS_STATEPOOL_DIR" \
    "$STATEBUS_RUNS_DIR" \
    "$STATEBUS_LOGS_DIR" \
    "$STATEBUS_MODELS_DIR" \
    "$NPM_CACHE" \
    "$NPM_CONFIG_PREFIX"

  if [[ -f "$STATEBUS_LLM_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATEBUS_LLM_ENV_FILE"
  fi

  cd "$PROJECT_ROOT"

  echo "[statebus-container] python: $(python3 --version 2>&1)"
  echo "[statebus-container] project root: $PROJECT_ROOT"
  echo "[statebus-container] pip index: $PIP_INDEX_URL"
  echo "[statebus-container] statepool dir: $STATEBUS_STATEPOOL_DIR"
  echo "[statebus-container] llm config: $STATEBUS_LLM_CONFIG_FILE"
  echo "[statebus-container] embed device: $STATEBUS_EMBED_DEVICE"
}

_STATEBUS_CONTAINER_HAD_ERREXIT=0
_STATEBUS_CONTAINER_HAD_NOUNSET=0
_STATEBUS_CONTAINER_HAD_PIPEFAIL=0
if shopt -qo errexit; then
  _STATEBUS_CONTAINER_HAD_ERREXIT=1
fi
if shopt -qo nounset; then
  _STATEBUS_CONTAINER_HAD_NOUNSET=1
fi
if shopt -qo pipefail; then
  _STATEBUS_CONTAINER_HAD_PIPEFAIL=1
fi

if _statebus_container_activate_main; then
  _statebus_container_activate_status=0
else
  _statebus_container_activate_status=$?
fi

_statebus_container_restore_shell_options

unset -f _statebus_container_restore_shell_options
unset -f _statebus_container_activate_main
unset _STATEBUS_CONTAINER_HAD_ERREXIT _STATEBUS_CONTAINER_HAD_NOUNSET _STATEBUS_CONTAINER_HAD_PIPEFAIL

return "${_statebus_container_activate_status}" 2>/dev/null || exit "${_statebus_container_activate_status}"
