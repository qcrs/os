#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f "/.dockerenv" ]]; then
  echo "[statebus] scripts/setup_container_embed_stack.sh is intended for the Docker dev container." >&2
  exit 1
fi

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/statebus/project}"
PIP_INDEX_URL_VALUE="${STATEBUS_PIP_INDEX_URL:-${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}}"
STATEBUS_TORCH_SPEC_VALUE="${STATEBUS_TORCH_SPEC:-torch==2.5.1}"
STATEBUS_TORCH_INDEX_URL_VALUE="${STATEBUS_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$PROJECT_ROOT/requirements-container-embed.txt}"
INSTALL_SCOPE="${STATEBUS_CONTAINER_PIP_INSTALL_SCOPE:-user}"

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "[statebus] requirements file not found: $REQUIREMENTS_FILE" >&2
  exit 1
fi

PIP_INSTALL_FLAGS=(--prefer-binary)
if [[ "$INSTALL_SCOPE" == "user" ]]; then
  PIP_INSTALL_FLAGS+=(--user)
elif [[ "$INSTALL_SCOPE" != "system" ]]; then
  echo "[statebus] unsupported STATEBUS_CONTAINER_PIP_INSTALL_SCOPE: $INSTALL_SCOPE" >&2
  echo "[statebus] expected: user or system" >&2
  exit 1
fi

echo "[statebus] project root: $PROJECT_ROOT"
echo "[statebus] requirements file: $REQUIREMENTS_FILE"
echo "[statebus] install scope: $INSTALL_SCOPE"
echo "[statebus] pip index: $PIP_INDEX_URL_VALUE"
echo "[statebus] torch spec: $STATEBUS_TORCH_SPEC_VALUE"
echo "[statebus] torch index: $STATEBUS_TORCH_INDEX_URL_VALUE"

python3 -m pip install \
  "${PIP_INSTALL_FLAGS[@]}" \
  --index-url "$PIP_INDEX_URL_VALUE" \
  --upgrade \
  pip setuptools wheel
python3 -m pip install \
  "${PIP_INSTALL_FLAGS[@]}" \
  --index-url "$STATEBUS_TORCH_INDEX_URL_VALUE" \
  --extra-index-url "$PIP_INDEX_URL_VALUE" \
  "$STATEBUS_TORCH_SPEC_VALUE"
python3 -m pip install \
  "${PIP_INSTALL_FLAGS[@]}" \
  --index-url "$PIP_INDEX_URL_VALUE" \
  --extra-index-url "$STATEBUS_TORCH_INDEX_URL_VALUE" \
  -r "$REQUIREMENTS_FILE"

if [[ "$INSTALL_SCOPE" == "user" ]]; then
  echo "[statebus] embed stack installed with --user under $HOME/.local"
  echo "[statebus] source /usr/local/bin/activate_statebus_container.sh before running StateBus."
else
  echo "[statebus] embed stack installed into the container image environment"
fi
