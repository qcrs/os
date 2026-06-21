#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="${STATEBUS_FORMAL_COMPARATOR_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUNS_ROOT="${STATEBUS_RUNS_DIR:-$ROOT/runs}"
RUN_ROOT="${1:-$RUNS_ROOT/formal_comparator_api_repeat10_${STAMP}}"
LLM_CONFIG_PATH="${STATEBUS_LLM_CONFIG_PATH:-deploy/statebus_llm.yaml.local}"

mkdir -p "$RUN_ROOT"
cd "$ROOT"

source deploy/activate_statebus_host.sh

echo "[statebus] formal comparator api r10 run root: $RUN_ROOT"
echo "[statebus] llm config: $LLM_CONFIG_PATH"
echo "[statebus] primary object: internal paired comparator (4-LLM text vs StateBus protocol)"
echo "[statebus] order: internal paired comparator -> external pure-text baseline -> frozen headline"
echo "[statebus] stopline: keep internal comparator, external baseline, and frozen headline in separate out dirs; do not merge support/audit reads into comparator or headline reads."

python -m eval.runner \
  --task-set contest_dual_mode_controlled_v3 \
  --repeat 10 \
  --modes text,protocol \
  --llm-mode api \
  --llm-config "$LLM_CONFIG_PATH" \
  --out "$RUN_ROOT/api_repeat10_internal_paired"

python -m eval.open_runner \
  --pack pure_text_open_baseline_v1 \
  --repeat 10 \
  --task-set contest_dual_mode_controlled_v3 \
  --llm-mode api \
  --llm-config "$LLM_CONFIG_PATH" \
  --out "$RUN_ROOT/api_repeat10_external_pure_text_baseline"

python -m eval.runner \
  --task-set contest_honest_headline_v1 \
  --repeat 10 \
  --modes text,protocol \
  --llm-mode api \
  --llm-config "$LLM_CONFIG_PATH" \
  --out "$RUN_ROOT/api_repeat10_frozen_headline"

cat > "$RUN_ROOT/README.txt" <<EOF
StateBus formal comparator API repeat=10 serialized run

Primary object:
  - internal paired comparator (4-LLM text vs StateBus protocol)

Run order:
  1. internal paired comparator
  2. external pure-text baseline
  3. frozen headline

Stopline:
  - keep internal comparator, external baseline, and frozen headline in separate out dirs
  - do not merge support/audit artifacts into comparator or headline reads
  - internal paired comparator is the primary repeat-depth closure object for this package
  - external and headline outputs remain secondary surfaces for this package

LLM config:
  $LLM_CONFIG_PATH
EOF

echo "[statebus] done: $RUN_ROOT"
