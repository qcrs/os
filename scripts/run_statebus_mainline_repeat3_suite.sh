#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
RUN_ROOT="${1:-$OUT_ROOT/statebus_mainline_repeat3_suite_${STAMP}}"
LLM_CONFIG_PATH="${STATEBUS_LLM_CONFIG_PATH:-deploy/statebus_llm.yaml.local}"

mkdir -p "$RUN_ROOT"
cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

unset all_proxy || true
unset ALL_PROXY || true

echo "[statebus-mainline] run root: $RUN_ROOT"
echo "[statebus-mainline] python: $PYTHON_BIN"
echo "[statebus-mainline] llm config: $LLM_CONFIG_PATH"
echo "[statebus-mainline] contract: contest-first StateBus repeat=3 suite without open/langgraph extension surfaces."

"$PYTHON_BIN" "$ROOT/scripts/run_contest_plus_open_repeat3_suite.py" \
  --out "$RUN_ROOT" \
  --repeat 3 \
  --llm-mode api \
  --llm-config "$LLM_CONFIG_PATH" \
  --skip-open-surfaces \
  --skip-langgraph-open-smoke

echo "[statebus-mainline] done: $RUN_ROOT"
