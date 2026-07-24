#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/bin/activate_statebus_container.sh
fi

cd "$ROOT"

ROLE_PATH_MODE="${STATEBUS_ROLE_PATH_MODE:-deterministic}"
EMBEDDING_MODE="${STATEBUS_EMBEDDING_MODE:-deterministic}"
FORMAL_FAMILY_DIR="${STATEBUS_V2_FORMAL_FAMILY_DIR:-$ROOT/v2/benchmark/samples/formal_financial_family}"
DEV_FAMILY_DIR="${STATEBUS_V2_DEV_FAMILY_DIR:-$ROOT/v2/benchmark/samples/fixed_answer_family}"
FORMAL_SUITE_ID="${STATEBUS_V2_FORMAL_SUITE_ID:-statebus-v2-benchmark}"
DEV_SUITE_ID="${STATEBUS_V2_DEV_SUITE_ID:-statebus-v2-benchmark}"
STATEBUS_HOME_ROOT="${STATEBUS_HOME:-/statebus}"
WORKSPACE_ROOT="${STATEBUS_V2_WORKSPACE_ROOT:-${STATEBUS_WORKDIR:-$STATEBUS_HOME_ROOT/work}/v2-live/workspaces}"
RUNTIME_ROOT="${STATEBUS_V2_RUNTIME_ROOT:-${STATEBUS_RUNS_DIR:-$STATEBUS_HOME_ROOT/runs}/v2-live/runtime}"
SOCKET_PATH="${STATEBUS_V2_SOCKET_PATH:-${STATEBUS_RUNS_DIR:-$STATEBUS_HOME_ROOT/runs}/v2-live/control.sock}"
ENABLE_SYNTHETIC_REPLAY="${STATEBUS_V2_ENABLE_SYNTHETIC_REPLAY:-0}"

run_live() {
  local suite="$1"
  shift
  python3 -m v2.benchmark.live_runner \
    --suite "$suite" \
    --role-path-mode "$ROLE_PATH_MODE" \
    --embedding-mode "$EMBEDDING_MODE" \
    --workspace-root "$WORKSPACE_ROOT" \
    --runtime-root "$RUNTIME_ROOT" \
    --socket-path "$SOCKET_PATH" \
    "$@"
}

echo "[statebus-v2] root: $ROOT"
echo "[statebus-v2] role_path_mode: $ROLE_PATH_MODE"
echo "[statebus-v2] embedding_mode: $EMBEDDING_MODE"
echo "[statebus-v2] formal_family_dir: $FORMAL_FAMILY_DIR"
echo "[statebus-v2] dev_family_dir: $DEV_FAMILY_DIR"
echo "[statebus-v2] workspace_root: $WORKSPACE_ROOT"
echo "[statebus-v2] runtime_root: $RUNTIME_ROOT"
echo "[statebus-v2] socket_path: $SOCKET_PATH"
echo "[statebus-v2] formal_suite_id: $FORMAL_SUITE_ID"
echo "[statebus-v2] dev_suite_id: $DEV_SUITE_ID"
echo "[statebus-v2] synthetic_replay_default: disabled"

echo
echo "=== preflight ==="
run_live preflight

echo
echo "=== formal benchmark ==="
run_live formal \
  --benchmark-tier formal \
  --family-dir "$FORMAL_FAMILY_DIR" \
  --suite-id "$FORMAL_SUITE_ID"

echo
echo "=== dev statebus cold-start ==="
run_live statebus \
  --benchmark-tier dev \
  --family-dir "$DEV_FAMILY_DIR" \
  --suite-id "$DEV_SUITE_ID" \
  --statebus-mode cold-start

echo
echo "=== compare cold-start ==="
run_live compare \
  --benchmark-tier dev \
  --family-dir "$DEV_FAMILY_DIR" \
  --suite-id "$DEV_SUITE_ID" \
  --statebus-mode cold-start

if [[ "$ENABLE_SYNTHETIC_REPLAY" == "1" ]]; then
  echo
  echo "=== dev statebus replay-ready synthetic probe ==="
  run_live statebus \
    --benchmark-tier dev \
    --family-dir "$DEV_FAMILY_DIR" \
    --suite-id "$DEV_SUITE_ID" \
    --statebus-mode replay-ready \
    --seed-replay-memory

  echo
  echo "=== compare replay-ready synthetic probe ==="
  run_live compare \
    --benchmark-tier dev \
    --family-dir "$DEV_FAMILY_DIR" \
    --suite-id "$DEV_SUITE_ID" \
    --statebus-mode replay-ready \
    --seed-replay-memory
fi

echo
echo "=== reports ==="
echo "$RUNTIME_ROOT/benchmark_reports/${FORMAL_SUITE_ID}-formal-suite.json"
echo "$RUNTIME_ROOT/L0/benchmark_reports/${FORMAL_SUITE_ID}-formal-L0.json"
echo "$RUNTIME_ROOT/L3/benchmark_reports/${FORMAL_SUITE_ID}-formal-L3.json"
echo "$RUNTIME_ROOT/benchmark_reports/${DEV_SUITE_ID}-cold-start-statebus.json"
echo "$RUNTIME_ROOT/benchmark_reports/${DEV_SUITE_ID}-cold-start-compare.json"
echo "$RUNTIME_ROOT/benchmark_reports/${DEV_SUITE_ID}-cold-start-compare-deterministic.json"
if [[ "$ENABLE_SYNTHETIC_REPLAY" == "1" ]]; then
  echo "$RUNTIME_ROOT/benchmark_reports/${DEV_SUITE_ID}-compare.json"
  echo "$RUNTIME_ROOT/benchmark_reports/${DEV_SUITE_ID}-compare-deterministic.json"
fi
