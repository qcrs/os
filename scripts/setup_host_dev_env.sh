#!/usr/bin/env bash
set -euo pipefail

if [[ -f "/.dockerenv" ]]; then
  echo "[statebus] scripts/setup_host_dev_env.sh is host-only and should not be run inside the Docker dev container." >&2
  echo "[statebus] Build the container image via docs/setup/docker_dev_openeuler.md, then source /usr/local/bin/activate_statebus_container.sh." >&2
  exit 1
fi

STATEBUS_HOME="${STATEBUS_HOME:-$HOME/statebus}"
ENV_PREFIX="${ENV_PREFIX:-$STATEBUS_HOME/conda-envs/statebus_host}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
STATEBUS_PIP_INDEX_URL="${STATEBUS_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
STATEBUS_TORCH_SPEC="${STATEBUS_TORCH_SPEC:-torch==2.5.1+cu121}"
STATEBUS_TORCH_INDEX_URL="${STATEBUS_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"
STATEBUS_TRANSFORMERS_SPEC="${STATEBUS_TRANSFORMERS_SPEC:-transformers==4.51.3}"
STATEBUS_SENTENCE_TRANSFORMERS_SPEC="${STATEBUS_SENTENCE_TRANSFORMERS_SPEC:-sentence-transformers==5.5.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$SCRIPT_DIR/../requirements-host.txt}"

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

echo "[statebus] host root: $STATEBUS_HOME"
echo "[statebus] conda env: $ENV_PREFIX"
echo "[statebus] pip index: $STATEBUS_PIP_INDEX_URL"
echo "[statebus] torch spec: $STATEBUS_TORCH_SPEC"
echo "[statebus] transformers spec: $STATEBUS_TRANSFORMERS_SPEC"
echo "[statebus] sentence-transformers spec: $STATEBUS_SENTENCE_TRANSFORMERS_SPEC"
echo "[statebus] requirements file: $REQUIREMENTS_FILE"

mkdir -p \
  "$STATEBUS_HOME/conda-envs" \
  "$STATEBUS_HOME/models" \
  "$STATEBUS_HOME/caches/pip" \
  "$STATEBUS_HOME/caches/hf/hub" \
  "$STATEBUS_HOME/caches/hf/transformers" \
  "$STATEBUS_HOME/caches/hf/sentence_transformers" \
  "$STATEBUS_HOME/work/statepool" \
  "$STATEBUS_HOME/logs" \
  "$STATEBUS_HOME/runs"

CONDA_BASE="$(resolve_conda_base)"
source "$CONDA_BASE/etc/profile.d/conda.sh"

if [[ ! -d "$ENV_PREFIX" ]]; then
  conda create -y -p "$ENV_PREFIX" "python=$PYTHON_VERSION"
fi

conda run -p "$ENV_PREFIX" python -m pip install --upgrade \
  --index-url "$STATEBUS_PIP_INDEX_URL" \
  pip setuptools wheel
conda run -p "$ENV_PREFIX" python -m pip install --upgrade \
  --index-url "$STATEBUS_TORCH_INDEX_URL" \
  --extra-index-url "$STATEBUS_PIP_INDEX_URL" \
  "$STATEBUS_TORCH_SPEC"
conda run -p "$ENV_PREFIX" python -m pip install \
  --index-url "$STATEBUS_PIP_INDEX_URL" \
  -r "$REQUIREMENTS_FILE"

echo "[statebus] host dev environment is ready"
echo "[statebus] activate with: source deploy/activate_statebus_host.sh"
