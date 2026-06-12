#!/usr/bin/env bash

_statebus_restore_shell_options() {
  if [[ "${_STATEBUS_HAD_ERREXIT:-0}" == "1" ]]; then
    set -o errexit
  else
    set +o errexit
  fi
  if [[ "${_STATEBUS_HAD_NOUNSET:-0}" == "1" ]]; then
    set -o nounset
  else
    set +o nounset
  fi
  if [[ "${_STATEBUS_HAD_PIPEFAIL:-0}" == "1" ]]; then
    set -o pipefail
  else
    set +o pipefail
  fi
}

_statebus_activate_main() {
  set -euo pipefail

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  resolve_conda_base() {
    if [[ -n "${CONDA_EXE:-}" ]]; then
      "$CONDA_EXE" info --base
      return
    fi
    if command -v conda >/dev/null 2>&1; then
      conda info --base
      return
    fi
    if [[ -x "/opt/miniconda/bin/conda" ]]; then
      /opt/miniconda/bin/conda info --base
      return
    fi
    echo "[statebus] conda executable not found; set CONDA_EXE or add conda to PATH" >&2
    return 1
  }

  export STATEBUS_HOME="${STATEBUS_HOME:-$HOME/statebus}"
  export STATEBUS_ENV_PREFIX="${STATEBUS_ENV_PREFIX:-$STATEBUS_HOME/conda-envs/statebus_host}"

  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$STATEBUS_HOME/caches/pip}"
  export HF_HOME="${HF_HOME:-$STATEBUS_HOME/caches/hf}"
  export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
  export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
  export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$HF_HOME/sentence_transformers}"
  export STATEBUS_WORKDIR="${STATEBUS_WORKDIR:-$STATEBUS_HOME/work}"
  export STATEBUS_STATEPOOL_DIR="${STATEBUS_STATEPOOL_DIR:-$STATEBUS_WORKDIR/statepool}"
  export STATEBUS_RUNS_DIR="${STATEBUS_RUNS_DIR:-$STATEBUS_HOME/runs}"
  export STATEBUS_LOGS_DIR="${STATEBUS_LOGS_DIR:-$STATEBUS_HOME/logs}"
  export STATEBUS_MODELS_DIR="${STATEBUS_MODELS_DIR:-$STATEBUS_HOME/models}"
  export STATEBUS_LLM_CONFIG_FILE="${STATEBUS_LLM_CONFIG_FILE:-$SCRIPT_DIR/statebus_llm.yaml.local}"
  export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-auto}"

  STATEBUS_LLM_ENV_FILE="${STATEBUS_LLM_ENV_FILE:-$SCRIPT_DIR/statebus_llm.env.local}"
  if [ -f "$STATEBUS_LLM_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$STATEBUS_LLM_ENV_FILE"
  fi

  CONDA_BASE="$(resolve_conda_base)"
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  conda activate "$STATEBUS_ENV_PREFIX"

  echo "[statebus] active env: $CONDA_PREFIX"
  echo "[statebus] model dir: $STATEBUS_MODELS_DIR"
  echo "[statebus] statepool dir: $STATEBUS_STATEPOOL_DIR"
  echo "[statebus] llm config: $STATEBUS_LLM_CONFIG_FILE"
  echo "[statebus] embed device: $STATEBUS_EMBED_DEVICE"
}

_STATEBUS_HAD_ERREXIT=0
_STATEBUS_HAD_NOUNSET=0
_STATEBUS_HAD_PIPEFAIL=0
if shopt -qo errexit; then
  _STATEBUS_HAD_ERREXIT=1
fi
if shopt -qo nounset; then
  _STATEBUS_HAD_NOUNSET=1
fi
if shopt -qo pipefail; then
  _STATEBUS_HAD_PIPEFAIL=1
fi

if _statebus_activate_main; then
  _statebus_activate_status=0
else
  _statebus_activate_status=$?
fi

_statebus_restore_shell_options

unset -f _statebus_restore_shell_options
unset -f _statebus_activate_main
unset _STATEBUS_HAD_ERREXIT _STATEBUS_HAD_NOUNSET _STATEBUS_HAD_PIPEFAIL

return "${_statebus_activate_status}" 2>/dev/null || exit "${_statebus_activate_status}"
