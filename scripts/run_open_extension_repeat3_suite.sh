#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
RUN_ROOT="${1:-$OUT_ROOT/open_extension_repeat3_suite_${STAMP}}"

mkdir -p "$RUN_ROOT"
cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

unset all_proxy || true
unset ALL_PROXY || true

echo "[open-extension] run root: $RUN_ROOT"
echo "[open-extension] python: $PYTHON_BIN"
echo "[open-extension] contract: open comparison and langgraph-native extension surfaces only; no StateBus formal/support pack rerun."

"$PYTHON_BIN" "$ROOT/scripts/run_contest_plus_open_repeat3_suite.py" \
  --out "$RUN_ROOT" \
  --repeat 3 \
  --llm-mode api \
  --skip-regression-gates \
  --skip-statebus-packs

echo "[open-extension] done: $RUN_ROOT"
