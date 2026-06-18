#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/home/qcrs/statebus/conda-envs/statebus_host/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
RUN_ROOT="${1:-$OUT_ROOT/host_test_then_api_repeat1_small_${STAMP}}"
PACKS_RAW="${STATEBUS_API_SMALL_PACKS:-contest_dual_mode_controlled_v3,planner_support_v3}"
LLM_CONFIG_PATH="${STATEBUS_LLM_CONFIG_PATH:-deploy/statebus_llm.yaml.local}"
PYTEST_EXPR="${STATEBUS_TARGETED_PYTEST_EXPR:-planner_support_v3 or validate_gate or typed_state_mechanism_v3 or wrong_family or contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate}"

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
echo "[statebus] note: API repeat=1 here is only flow/report correctness checking, not formal stability or headline evidence."

"$PYTHON_BIN" -m pytest -q \
  tests/test_llm_runtime.py \
  tests/test_state_channels_and_graph.py \
  tests/test_smoke.py \
  -k "$PYTEST_EXPR" | tee "$RUN_ROOT/targeted_pytest.log"

"$PYTHON_BIN" -m runtime.smoke | tee "$RUN_ROOT/runtime_smoke.log"

IFS=',' read -r -a PACKS <<< "$PACKS_RAW"
for raw_pack in "${PACKS[@]}"; do
  pack="$(echo "$raw_pack" | sed 's/^ *//; s/ *$//')"
  if [[ -z "$pack" ]]; then
    continue
  fi
  pack_out="$RUN_ROOT/benchmarks/$pack"
  mkdir -p "$pack_out"
  echo "[statebus] api repeat=1 pack: $pack"
  "$PYTHON_BIN" -m eval.runner \
    --task-set "$pack" \
    --repeat 1 \
    --modes text,protocol \
    --llm-mode api \
    --llm-config "$LLM_CONFIG_PATH" \
    --embedding-mode deterministic \
    --out "$pack_out" \
    --quiet-progress | tee "$RUN_ROOT/${pack}.log"
done

cat > "$RUN_ROOT/README.txt" <<EOF
StateBus host test then API repeat=1 small run

Python:
  $PYTHON_BIN

Targeted pytest expression:
  $PYTEST_EXPR

API packs:
  $PACKS_RAW

Contract:
  - targeted tests and runtime.smoke run first
  - API benchmark runs are serialized repeat=1 small-pack checks
  - this package is only for flow/report correctness inspection
  - do not treat it as formal stability evidence or headline publication proof
EOF

echo "[statebus] done: $RUN_ROOT"
