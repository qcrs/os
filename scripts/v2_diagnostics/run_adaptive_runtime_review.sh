#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/v2_diagnostics/run_adaptive_runtime_review.sh [--deterministic|--live]

Runs the bounded-adaptive Runtime review suite in statebus-dev-qcrs.

--deterministic (default)
  Runs projection, quality, Dispatcher, CodeAct, three-task DSL, bwrap, and
  strict/shadow control checks. It never calls vLLM, formal 25-case, replay,
  or serialized repeat benchmarks.

--live
  Performs read-only vLLM /health and /v1/models checks first. Only if both
  respond does it run the small four-mode matrix: strict_fixed,
  adaptive_shadow, adaptive_bounded_dsl, and adaptive_bounded_codeact.
  It does not run the formal or serialized benchmark stages.

Environment:
  STATEBUS_V2_CONTAINER_NAME       Container name (default: statebus-dev-qcrs)
  STATEBUS_RUNTIME_REVIEW_RUN_ID   Optional result directory suffix
EOF
}

mode="${1:---deterministic}"
case "$mode" in
  --deterministic|--live) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

container_name="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
run_id="${STATEBUS_RUNTIME_REVIEW_RUN_ID:-adaptive_runtime_review_$(date +%Y%m%d_%H%M%S)}"

if ! docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  printf 'container is not running: %s\n' "$container_name" >&2
  exit 2
fi

docker exec -i -u 0 \
  -e STATEBUS_RUNTIME_REVIEW_MODE="$mode" \
  -e STATEBUS_RUNTIME_REVIEW_RUN_ID="$run_id" \
  "$container_name" bash -s <<'CONTAINER_BASH'
set -euo pipefail

source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project

mode="$STATEBUS_RUNTIME_REVIEW_MODE"
result_root="/statebus/runs/$STATEBUS_RUNTIME_REVIEW_RUN_ID"
status_tsv="$result_root/status.tsv"
mkdir -p "$result_root"
printf 'stage\texit_code\tstdout\tstderr\n' > "$status_tsv"

run_stage() {
  local stage="$1"
  shift
  local stdout="$result_root/$stage.stdout.log"
  local stderr="$result_root/$stage.stderr.log"
  local status=0
  printf '\n=== %s ===\n' "$stage"
  set +e
  "$@" > "$stdout" 2> "$stderr"
  status=$?
  set -e
  printf '%s\t%s\t%s\t%s\n' "$stage" "$status" "$stdout" "$stderr" >> "$status_tsv"
  if [[ "$status" -ne 0 ]]; then
    printf '[fail] %s (exit %s)\n' "$stage" "$status" >&2
    tail -n 40 "$stderr" >&2 || true
    return "$status"
  fi
  printf '[ok] %s\n' "$stage"
}

run_stage focused-runtime-tests \
  python3 -m pytest -q \
  tests/v2/test_adaptive_contracts.py \
  tests/v2/test_adaptive_planner_policy.py \
  tests/v2/test_adaptive_driver.py \
  tests/v2/test_adaptive_retrieval.py \
  tests/v2/test_adaptive_claims.py \
  tests/v2/test_adaptive_role_prompts.py \
  tests/v2/test_adaptive_smoke_diagnostics.py \
  tests/v2/test_evidence_projection.py \
  tests/v2/test_capability_validators.py \
  tests/v2/test_adaptive_dispatcher.py \
  tests/v2/test_adaptive_codeact_integration.py \
  tests/v2/test_adaptive_capability_surface.py \
  tests/v2/test_adaptive_lightweight_task_gates.py \
  tests/v2/test_transform_dsl.py \
  tests/v2/test_llm_codeact_policy.py \
  tests/v2/test_llm_codeact_sandbox.py
run_stage bwrap-readiness python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
run_stage deterministic-mode-matrix \
  python3 scripts/v2_diagnostics/run_adaptive_mode_matrix.py \
  --deterministic-only \
  --output-root "$result_root/matrix"

if [[ "$mode" == "--live" ]]; then
  run_stage vllm-health curl --max-time 5 -fsS http://127.0.0.1:53334/health
  run_stage vllm-models curl --max-time 5 -fsS http://127.0.0.1:53334/v1/models
  run_stage live-four-mode-matrix \
    python3 scripts/v2_diagnostics/run_adaptive_mode_matrix.py \
    --require-live-model-path \
    --output-root "$result_root/matrix"
fi

python3 - "$status_tsv" "$result_root/summary.json" <<'PY'
import csv
import json
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8"), delimiter="\t"))
summary = {
    "schema_version": "statebus.adaptive_runtime_review.v1",
    "stage_count": len(rows),
    "failed_stages": [row["stage"] for row in rows if row["exit_code"] != "0"],
    "stages": rows,
}
summary["ok"] = not summary["failed_stages"]
Path(sys.argv[2]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
PY

printf '\n[result] %s\n' "$result_root"
CONTAINER_BASH
