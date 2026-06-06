#!/usr/bin/env bash
set -euo pipefail

STATEBUS_HOME="${STATEBUS_HOME:-$HOME/statebus}"
ENV_PREFIX="${ENV_PREFIX:-$STATEBUS_HOME/conda-envs/statebus_host}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
STATEBUS_PIP_INDEX_URL="${STATEBUS_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
STATEBUS_TORCH_SPEC="${STATEBUS_TORCH_SPEC:-torch==2.5.1+cu121}"
STATEBUS_TORCH_INDEX_URL="${STATEBUS_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"
STATEBUS_TRANSFORMERS_SPEC="${STATEBUS_TRANSFORMERS_SPEC:-transformers==4.46.3}"
STATEBUS_SENTENCE_TRANSFORMERS_SPEC="${STATEBUS_SENTENCE_TRANSFORMERS_SPEC:-sentence-transformers==5.5.1}"

echo "[statebus] host root: $STATEBUS_HOME"
echo "[statebus] conda env: $ENV_PREFIX"
echo "[statebus] pip index: $STATEBUS_PIP_INDEX_URL"
echo "[statebus] torch spec: $STATEBUS_TORCH_SPEC"
echo "[statebus] transformers spec: $STATEBUS_TRANSFORMERS_SPEC"
echo "[statebus] sentence-transformers spec: $STATEBUS_SENTENCE_TRANSFORMERS_SPEC"

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

CONDA_BASE="$("/opt/miniconda/bin/conda" info --base)"
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
  numpy \
  protobuf \
  pydantic \
  orjson \
  msgpack \
  openai \
  faiss-cpu \
  "$STATEBUS_TRANSFORMERS_SPEC" \
  "$STATEBUS_SENTENCE_TRANSFORMERS_SPEC" \
  networkx \
  pyyaml \
  rich \
  pytest \
  pytest-asyncio

echo "[statebus] host dev environment is ready"
echo "[statebus] activate with: source deploy/activate_statebus_host.sh"
