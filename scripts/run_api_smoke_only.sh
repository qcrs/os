#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_ROOT="${STATEBUS_RUNS_DIR:-$HOME/statebus/runs}"
STAMP="$(date +%Y%m%d_%H%M%S)"
SMOKE_OUT="${1:-$OUT_ROOT/api_smoke_only_${STAMP}}"

source "$ROOT/deploy/activate_statebus_host.sh"

python -m eval.runner \
  --api-smoke \
  --llm-mode api \
  --llm-config deploy/statebus_llm.yaml.local \
  --embedding-mode deterministic \
  --repeat 1 \
  --out "$SMOKE_OUT/api_smoke_minimal_v1" \
  --quiet-progress

python -m eval.open_runner \
  --pack pure_text_open_baseline_v1 \
  --task-set tasks/pure_text_open_smoke_v1.yaml \
  --repeat 1 \
  --out "$SMOKE_OUT/pure_text_open_baseline_v1"

python -m eval.open_runner \
  --pack langgraph_native_text_open \
  --repeat 1 \
  --out "$SMOKE_OUT/langgraph_native_text_open"
