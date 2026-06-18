#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
RUN_ROOT="${1:-$OUT_ROOT/host_full_api_repeat3_v3_${STAMP}}"
LLM_CONFIG_PATH="${STATEBUS_LLM_CONFIG_PATH:-deploy/statebus_llm.yaml.local}"
PACKS_RAW="${STATEBUS_V3_API_REPEAT3_PACKS:-contest_dual_mode_controlled_v3,memory_dual_mode_fairness_v3,typed_state_mechanism_v3,external_text_baseline_audit_v3,text_definition_audit_v3,typed_state_authenticity_v3,typed_state_full_rich_audit_v3,carrier_microbench_v3,memory_reuse_v3,memory_policy_controlled_v3,planner_support_v3,typed_state_consumer_sensitivity_v3}"

mkdir -p "$RUN_ROOT"

cd "$ROOT"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python: $PYTHON_BIN" >&2
  exit 1
fi

unset all_proxy || true
unset ALL_PROXY || true

echo "[statebus] run root: $RUN_ROOT"
echo "[statebus] python: $PYTHON_BIN"
echo "[statebus] packs: $PACKS_RAW"
echo "[statebus] contract: full active v3 API repeat=3 suite over StateBus packs only; open surfaces skipped by default."

"$PYTHON_BIN" "$ROOT/scripts/run_v3_api_repeat3_suite.py" \
  --out "$RUN_ROOT" \
  --repeat 3 \
  --llm-config "$LLM_CONFIG_PATH" \
  --packs "$PACKS_RAW" \
  --skip-open-surfaces

cat > "$RUN_ROOT/README.txt" <<EOF
StateBus host full API repeat=3 v3 suite

Python:
  $PYTHON_BIN

LLM config:
  $LLM_CONFIG_PATH

Packs:
  $PACKS_RAW

Contract:
  - runs the active v3 StateBus packs in serialized API repeat=3 mode
  - includes regression gates unless the underlying launcher is changed
  - skips open surfaces by default so the package stays centered on StateBus formal/support packs
  - this is broader than issue-discovery smoke and is intended for suite-level result analysis
EOF

echo "[statebus] done: $RUN_ROOT"
