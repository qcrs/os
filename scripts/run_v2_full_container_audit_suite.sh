#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
TIMESTAMP="${STATEBUS_AUDIT_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_V2_AUDIT_RUN_ID:-v2-full-audit-${TIMESTAMP}}"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
TARGET_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
RUN_FLAGSHIP="${STATEBUS_RUN_FLAGSHIP:-0}"
PYTEST_TIMEOUT_SECONDS="${STATEBUS_AUDIT_PYTEST_TIMEOUT_SECONDS:-7200}"
SMOKE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_SMOKE_TIMEOUT_SECONDS:-900}"
PREFLIGHT_TIMEOUT_SECONDS="${STATEBUS_AUDIT_PREFLIGHT_TIMEOUT_SECONDS:-300}"
FORMAL_TIMEOUT_SECONDS="${STATEBUS_AUDIT_FORMAL_TIMEOUT_SECONDS:-900}"
COMPARE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_COMPARE_TIMEOUT_SECONDS:-900}"
REPLAY_TIMEOUT_SECONDS="${STATEBUS_AUDIT_REPLAY_TIMEOUT_SECONDS:-1800}"
REPLAY_NEGATIVE_TIMEOUT_SECONDS="${STATEBUS_AUDIT_REPLAY_NEGATIVE_TIMEOUT_SECONDS:-600}"
FLAGSHIP_TIMEOUT_SECONDS="${STATEBUS_AUDIT_FLAGSHIP_TIMEOUT_SECONDS:-7200}"

mkdir -p "$HOST_RESULT_ROOT"

cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 full container audit suite

Host project root:
  ${HOST_PROJECT_ROOT}

Container name:
  ${CONTAINER_NAME}

Container project root:
  ${CONTAINER_PROJECT_ROOT}

Host-visible result root:
  ${HOST_RESULT_ROOT}

Container-visible result root:
  ${CONTAINER_RESULT_ROOT}

Contract:
  - all code reading, pytest, smoke, preflight, benchmark, and diagnostics run inside Docker
  - docker exec -u 0
  - source /usr/local/bin/activate_statebus_container.sh
  - /usr/bin/python3 only
  - strongest evidence path attempted first: api + local
  - fallback order: api+deterministic -> deterministic+local -> deterministic+deterministic
  - each benchmark stage gets its own runtime_root / workspace_root / socket_path
EOF

printf '[statebus-v2] starting full container audit suite\n'
printf '[statebus-v2] host-visible result root: %s\n' "$HOST_RESULT_ROOT"
printf '[statebus-v2] live console mirror: %s\n' "${HOST_RESULT_ROOT}/console.log"

docker exec -i -u 0 \
  -e STATEBUS_RUN_ID="$RUN_ID" \
  -e STATEBUS_RESULT_ROOT="$CONTAINER_RESULT_ROOT" \
  -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT" \
  -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
  -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
  -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM" \
  -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF" \
  -e STATEBUS_RUN_FLAGSHIP="$RUN_FLAGSHIP" \
  -e PYTEST_TIMEOUT_SECONDS="$PYTEST_TIMEOUT_SECONDS" \
  -e SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS" \
  -e PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS" \
  -e FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS" \
  -e COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS" \
  -e REPLAY_TIMEOUT_SECONDS="$REPLAY_TIMEOUT_SECONDS" \
  -e REPLAY_NEGATIVE_TIMEOUT_SECONDS="$REPLAY_NEGATIVE_TIMEOUT_SECONDS" \
  -e FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS" \
  "$CONTAINER_NAME" bash -lc 'bash -s' <<'EOF'
#!/usr/bin/env bash
set -uo pipefail

source /usr/local/bin/activate_statebus_container.sh
cd "$STATEBUS_PROJECT_ROOT"

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
STATUS_TSV="$RESULT_ROOT/status.tsv"
SUMMARY_MD="$RESULT_ROOT/summary.md"
SUMMARY_JSON="$RESULT_ROOT/summary.json"
CONSOLE_LOG="$RESULT_ROOT/console.log"

mkdir -p "$RESULT_ROOT"
printf 'stage\texit_code\tkind\tartifact\tlog_path\n' > "$STATUS_TSV"
exec > >(tee -a "$CONSOLE_LOG") 2>&1

LAST_STAGE_EXIT_CODE=0
LAST_STAGE_ARTIFACT="-"
PRIMARY_ROLE_PATH_MODE=""
PRIMARY_EMBEDDING_MODE=""
PRIMARY_EVIDENCE_TIER="weak"
REPLAY_EVIDENCE_OK=0
OVERALL_FAILURE=0

echo "[statebus-v2] container result root: $RESULT_ROOT"
echo "[statebus-v2] console log: $CONSOLE_LOG"
echo "[statebus-v2] CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-}"
echo "[statebus-v2] STATEBUS_EMBED_DEVICE: ${STATEBUS_EMBED_DEVICE:-}"
echo "[statebus-v2] TOKENIZERS_PARALLELISM: ${TOKENIZERS_PARALLELISM:-}"
echo "[statebus-v2] PYTORCH_CUDA_ALLOC_CONF: ${PYTORCH_CUDA_ALLOC_CONF:-}"

record_stage() {
  local stage="$1"
  local exit_code="$2"
  local kind="$3"
  local artifact="$4"
  local log_path="$5"
  printf '%s\t%s\t%s\t%s\t%s\n' "$stage" "$exit_code" "$kind" "$artifact" "$log_path" >> "$STATUS_TSV"
}

mark_required_failure_if_needed() {
  local exit_code="$1"
  if [[ "$exit_code" -ne 0 ]]; then
    OVERALL_FAILURE=1
  fi
}

json_valid() {
  local path="$1"
  /usr/bin/python3 - "$path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    json.load(handle)
PY
}

run_text_stage() {
  local stage="$1"
  local timeout_s="$2"
  shift 2
  local stage_dir="$RESULT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  timeout "$timeout_s" "$@" 2>&1 | tee "$log_path"
  local exit_code=${PIPESTATUS[0]}
  LAST_STAGE_EXIT_CODE="$exit_code"
  LAST_STAGE_ARTIFACT="-"
  record_stage "$stage" "$exit_code" "text" "-" "$log_path"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage}"
  else
    echo "[fail] ${stage} (exit ${exit_code})"
    tail -n 20 "$log_path" || true
  fi
  return 0
}

run_live_stage() {
  local stage="$1"
  local timeout_s="$2"
  local role_path_mode="$3"
  local embedding_mode="$4"
  local suite="$5"
  shift 5
  local stage_dir="$RESULT_ROOT/stages/$stage"
  local runtime_root="$stage_dir/runtime"
  local workspace_root="$stage_dir/workspaces"
  local socket_path
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  mkdir -p "$stage_dir" "$runtime_root" "$workspace_root"
  socket_path="$(short_socket_path "$stage")"
  rm -f "$socket_path"
  echo
  echo "=== ${stage} ==="
  timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner \
    --suite "$suite" \
    --role-path-mode "$role_path_mode" \
    --embedding-mode "$embedding_mode" \
    --runtime-root "$runtime_root" \
    --workspace-root "$workspace_root" \
    --socket-path "$socket_path" \
    --suite-id "${STATEBUS_RUN_ID}-${stage}" \
    "$@" \
    > >(tee "$stdout_json") \
    2> >(tee "$log_path" >&2)
  local exit_code=$?
  local artifact="$stdout_json"
  if [[ "$exit_code" -eq 0 ]] && ! json_valid "$stdout_json" >/dev/null 2>&1; then
    exit_code=3
  fi
  LAST_STAGE_EXIT_CODE="$exit_code"
  LAST_STAGE_ARTIFACT="$artifact"
  record_stage "$stage" "$exit_code" "live_runner" "$artifact" "$log_path"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${artifact}"
  else
    echo "[fail] ${stage} (exit ${exit_code})"
    tail -n 40 "$log_path" || true
  fi
  return 0
}

short_socket_path() {
  local label="$1"
  local digest
  digest="$(
    /usr/bin/python3 - "$label" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  printf '/tmp/sb-%s.sock' "$digest"
}

run_env_probe() {
  local stage="00_env_probe"
  local stage_dir="$RESULT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  {
    echo "pwd=$(pwd)"
    echo "python=$(/usr/bin/python3 --version)"
    echo "branch=$(git branch --show-current)"
    echo "commit=$(git rev-parse HEAD)"
    echo "API_KEY=${STATEBUS_LLM_API_KEY:+set}"
    echo "STATEBUS_LLM_CONFIG_FILE=${STATEBUS_LLM_CONFIG_FILE:-}"
    echo "STATEBUS_LLM_ENV_FILE=${STATEBUS_LLM_ENV_FILE:-}"
    echo "STATEBUS_HOME=${STATEBUS_HOME:-}"
    echo "LOCAL_MODEL_ROOT=$(find /statebus/models -maxdepth 2 -type d -name 'Qwen3-Embedding-0.6B' | head -n 1)"
    git status --short
  } 2>&1 | tee "$log_path"
  LAST_STAGE_EXIT_CODE=0
  LAST_STAGE_ARTIFACT="-"
  record_stage "$stage" "0" "text" "-" "$log_path"
}

pick_primary_mode() {
  if [[ "${pref_api_local_exit}" -eq 0 ]]; then
    PRIMARY_ROLE_PATH_MODE="api"
    PRIMARY_EMBEDDING_MODE="local"
    PRIMARY_EVIDENCE_TIER="strong"
    return
  fi
  if [[ "${pref_api_det_exit}" -eq 0 ]]; then
    PRIMARY_ROLE_PATH_MODE="api"
    PRIMARY_EMBEDDING_MODE="deterministic"
    PRIMARY_EVIDENCE_TIER="medium"
    return
  fi
  if [[ "${pref_det_local_exit}" -eq 0 ]]; then
    PRIMARY_ROLE_PATH_MODE="deterministic"
    PRIMARY_EMBEDDING_MODE="local"
    PRIMARY_EVIDENCE_TIER="medium"
    return
  fi
  PRIMARY_ROLE_PATH_MODE="deterministic"
  PRIMARY_EMBEDDING_MODE="deterministic"
  PRIMARY_EVIDENCE_TIER="weak"
}

run_env_probe

run_text_stage "01_pytest_full" "$PYTEST_TIMEOUT_SECONDS" /usr/bin/python3 -m pytest -q
mark_required_failure_if_needed "$LAST_STAGE_EXIT_CODE"

run_text_stage "02_runtime_smoke" "$SMOKE_TIMEOUT_SECONDS" /usr/bin/python3 -m runtime.smoke
mark_required_failure_if_needed "$LAST_STAGE_EXIT_CODE"

run_live_stage "03_preflight_api_local" "$PREFLIGHT_TIMEOUT_SECONDS" "api" "local" "preflight"
pref_api_local_exit="$LAST_STAGE_EXIT_CODE"
run_live_stage "04_preflight_api_deterministic" "$PREFLIGHT_TIMEOUT_SECONDS" "api" "deterministic" "preflight"
pref_api_det_exit="$LAST_STAGE_EXIT_CODE"
run_live_stage "05_preflight_deterministic_local" "$PREFLIGHT_TIMEOUT_SECONDS" "deterministic" "local" "preflight"
pref_det_local_exit="$LAST_STAGE_EXIT_CODE"
run_live_stage "06_preflight_deterministic_deterministic" "$PREFLIGHT_TIMEOUT_SECONDS" "deterministic" "deterministic" "preflight"
pref_det_det_exit="$LAST_STAGE_EXIT_CODE"

pick_primary_mode

echo
echo "[statebus-v2] selected primary mode: ${PRIMARY_ROLE_PATH_MODE} + ${PRIMARY_EMBEDDING_MODE} (${PRIMARY_EVIDENCE_TIER})"

run_live_stage \
  "07_formal_primary" \
  "$FORMAL_TIMEOUT_SECONDS" \
  "$PRIMARY_ROLE_PATH_MODE" \
  "$PRIMARY_EMBEDDING_MODE" \
  "formal" \
  --benchmark-tier formal
formal_primary_exit="$LAST_STAGE_EXIT_CODE"
mark_required_failure_if_needed "$formal_primary_exit"

run_live_stage \
  "08_compare_primary" \
  "$COMPARE_TIMEOUT_SECONDS" \
  "$PRIMARY_ROLE_PATH_MODE" \
  "$PRIMARY_EMBEDDING_MODE" \
  "compare" \
  --benchmark-tier dev
compare_primary_exit="$LAST_STAGE_EXIT_CODE"
mark_required_failure_if_needed "$compare_primary_exit"

run_live_stage \
  "09_replay_negative_primary" \
  "$REPLAY_NEGATIVE_TIMEOUT_SECONDS" \
  "$PRIMARY_ROLE_PATH_MODE" \
  "$PRIMARY_EMBEDDING_MODE" \
  "replay-negative-audit"

run_live_stage \
  "10_continuous_replay_collection_primary" \
  "$REPLAY_TIMEOUT_SECONDS" \
  "$PRIMARY_ROLE_PATH_MODE" \
  "$PRIMARY_EMBEDDING_MODE" \
  "continuous-replay" \
  --benchmark-tier dev
continuous_primary_exit="$LAST_STAGE_EXIT_CODE"
if [[ "$continuous_primary_exit" -eq 0 ]]; then
  REPLAY_EVIDENCE_OK=1
else
  run_live_stage \
    "11_continuous_replay_cross_period_primary" \
    "$REPLAY_TIMEOUT_SECONDS" \
    "$PRIMARY_ROLE_PATH_MODE" \
    "$PRIMARY_EMBEDDING_MODE" \
    "continuous-replay" \
    --benchmark-tier dev \
    --family cross_period_financial_v1
  if [[ "$LAST_STAGE_EXIT_CODE" -eq 0 ]]; then
    REPLAY_EVIDENCE_OK=1
  fi

  run_live_stage \
    "12_continuous_replay_csv_primary" \
    "$REPLAY_TIMEOUT_SECONDS" \
    "$PRIMARY_ROLE_PATH_MODE" \
    "$PRIMARY_EMBEDDING_MODE" \
    "continuous-replay" \
    --benchmark-tier dev \
    --family csv_correlation_replay_v1
  if [[ "$LAST_STAGE_EXIT_CODE" -eq 0 ]]; then
    REPLAY_EVIDENCE_OK=1
  fi

  run_live_stage \
    "13_continuous_replay_long_doc_primary" \
    "$REPLAY_TIMEOUT_SECONDS" \
    "$PRIMARY_ROLE_PATH_MODE" \
    "$PRIMARY_EMBEDDING_MODE" \
    "continuous-replay" \
    --benchmark-tier dev \
    --family long_doc_metric_replay_v1
  if [[ "$LAST_STAGE_EXIT_CODE" -eq 0 ]]; then
    REPLAY_EVIDENCE_OK=1
  fi

  if [[ "${pref_det_local_exit}" -eq 0 ]]; then
    run_live_stage \
      "14_continuous_replay_collection_det_local_fallback" \
      "$REPLAY_TIMEOUT_SECONDS" \
      "deterministic" \
      "local" \
      "continuous-replay" \
      --benchmark-tier dev
    if [[ "$LAST_STAGE_EXIT_CODE" -eq 0 ]]; then
      REPLAY_EVIDENCE_OK=1
    fi
  fi
fi

if [[ "${STATEBUS_RUN_FLAGSHIP:-0}" == "1" ]]; then
  run_live_stage \
    "15_flagship_ablation_primary" \
    "$FLAGSHIP_TIMEOUT_SECONDS" \
    "$PRIMARY_ROLE_PATH_MODE" \
    "$PRIMARY_EMBEDDING_MODE" \
    "flagship-ablation"
fi

if [[ "$REPLAY_EVIDENCE_OK" -eq 0 ]]; then
  OVERALL_FAILURE=1
fi

/usr/bin/python3 - "$STATUS_TSV" "$SUMMARY_MD" "$SUMMARY_JSON" "$PRIMARY_ROLE_PATH_MODE" "$PRIMARY_EMBEDDING_MODE" "$PRIMARY_EVIDENCE_TIER" "$REPLAY_EVIDENCE_OK" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
summary_json = Path(sys.argv[3])
primary_role = sys.argv[4]
primary_embed = sys.argv[5]
primary_tier = sys.argv[6]
replay_ok = bool(int(sys.argv[7]))

rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))
failed = [row for row in rows if row["exit_code"] != "0"]
payload = {
    "primary_mode": {
        "role_path_mode": primary_role,
        "embedding_mode": primary_embed,
        "evidence_tier": primary_tier,
    },
    "replay_evidence_observed": replay_ok,
    "stage_count": len(rows),
    "failed_stage_count": len(failed),
    "failed_stages": [row["stage"] for row in failed],
    "stages": rows,
}
summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# StateBus v2 Full Container Audit Suite",
    "",
    f"- Primary mode: `{primary_role} + {primary_embed}` (`{primary_tier}` evidence attempt)",
    f"- Replay evidence observed: `{replay_ok}`",
    f"- Stage count: `{len(rows)}`",
    f"- Failed stage count: `{len(failed)}`",
    "",
    "## Failed Stages",
]
if failed:
    for row in failed:
        lines.append(f"- `{row['stage']}` exit `{row['exit_code']}`")
else:
    lines.append("- none")
lines.extend(["", "## Stage Log", ""])
for row in rows:
    lines.append(
        f"- `{row['stage']}` exit `{row['exit_code']}` kind `{row['kind']}` artifact `{row['artifact']}`"
    )
summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

echo
echo "=== result bundle ==="
echo "$RESULT_ROOT"
echo "$STATUS_TSV"
echo "$SUMMARY_MD"
echo "$SUMMARY_JSON"

exit "$OVERALL_FAILURE"
EOF

printf '[statebus-v2] result bundle: %s\n' "$HOST_RESULT_ROOT"
