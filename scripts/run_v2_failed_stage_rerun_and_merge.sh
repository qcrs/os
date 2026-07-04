#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
TIMESTAMP="${STATEBUS_VALIDATION_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_V2_RERUN_ID:-v2-update-rerun-${TIMESTAMP}}"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
ROLE_PATH_MODE="${STATEBUS_ROLE_PATH_MODE:-api}"
EMBEDDING_MODE="${STATEBUS_EMBEDDING_MODE:-local}"
PERSISTENCE_PROFILE="${STATEBUS_V2_PERSISTENCE_PROFILE:-benchmark_balanced}"
CODEACT_RUNS="${STATEBUS_CODEACT_ACCEPTANCE_RUNS:-5}"
TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
TARGET_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

resolve_base_root() {
  if [[ -n "${STATEBUS_BASE_RESULT_ROOT:-}" ]]; then
    printf '%s\n' "$STATEBUS_BASE_RESULT_ROOT"
    return 0
  fi
  if [[ -n "${STATEBUS_BASE_RUN_ID:-}" ]]; then
    printf '%s\n' "${HOST_RUNS_ROOT}/${STATEBUS_BASE_RUN_ID}"
    return 0
  fi
  ls -dt "${HOST_RUNS_ROOT}"/v2-update-validation-* 2>/dev/null | head -1
}

BASE_RESULT_ROOT="$(resolve_base_root || true)"
if [[ -z "${BASE_RESULT_ROOT}" ]]; then
  echo "[statebus-v2-rerun] could not resolve base result root" >&2
  exit 1
fi
if [[ ! -d "${BASE_RESULT_ROOT}" ]]; then
  echo "[statebus-v2-rerun] base result root does not exist: ${BASE_RESULT_ROOT}" >&2
  exit 1
fi
if [[ -n "${STATEBUS_FORCE_FAILED_STAGES:-}" ]]; then
  # FORCE_FAILED_STAGES bypasses status.tsv requirement
  FAILED_STAGES_CSV="${STATEBUS_FORCE_FAILED_STAGES}"
elif [[ ! -f "${BASE_RESULT_ROOT}/status.tsv" ]]; then
  echo "[statebus-v2-rerun] missing base status.tsv: ${BASE_RESULT_ROOT}/status.tsv" >&2
  exit 1
else
  FAILED_STAGES_CSV="$(
    python3 - "${BASE_RESULT_ROOT}/status.tsv" <<'PY'
import sys

failed = []
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    for index, line in enumerate(handle):
        if index == 0:
            continue
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        stage, exit_code = parts[0], parts[1]
        try:
            exit_code_int = int(exit_code)
        except ValueError:
            continue
        if exit_code_int != 0:
            failed.append(stage)
print(",".join(failed))
PY
  )"
fi

BASE_RUN_ID="$(basename "$BASE_RESULT_ROOT")"
BASE_CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${BASE_RUN_ID}"

mkdir -p "$HOST_RESULT_ROOT"

printf '%s\n' "$BASE_RESULT_ROOT" > "${HOST_RESULT_ROOT}/base_result_root.txt"
printf '%s\n' "$FAILED_STAGES_CSV" > "${HOST_RESULT_ROOT}/failed_stages.csv"

cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 failed-stage rerun bundle

Host project root:
  ${HOST_PROJECT_ROOT}

Container name:
  ${CONTAINER_NAME}

Base result root:
  ${BASE_RESULT_ROOT}

Base run id:
  ${BASE_RUN_ID}

Host-visible rerun root:
  ${HOST_RESULT_ROOT}

Container-visible rerun root:
  ${CONTAINER_RESULT_ROOT}

Contract:
  - docker exec -u 0
  - rerun only failed stages from base status.tsv
  - role-path-mode=${ROLE_PATH_MODE}
  - embedding-mode=${EMBEDDING_MODE}
  - physical CUDA devices exposed to container: ${TARGET_CUDA_VISIBLE_DEVICES}
  - container embed device: ${TARGET_EMBED_DEVICE}
  - persistence-profile=${PERSISTENCE_PROFILE}
  - writes rerun logs plus merged full summary
EOF

printf '[statebus-v2-rerun] base result root: %s\n' "$BASE_RESULT_ROOT"
printf '[statebus-v2-rerun] failed stages: %s\n' "${FAILED_STAGES_CSV:-<none>}"
printf '[statebus-v2-rerun] rerun result root: %s\n' "$HOST_RESULT_ROOT"

if [[ -n "${FAILED_STAGES_CSV}" ]]; then
  docker exec -i -u 0 \
    -e STATEBUS_RUN_ID="$RUN_ID" \
    -e STATEBUS_RESULT_ROOT="$CONTAINER_RESULT_ROOT" \
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT" \
    -e STATEBUS_BASE_RUN_ID="$BASE_RUN_ID" \
    -e STATEBUS_BASE_RESULT_ROOT="$BASE_CONTAINER_RESULT_ROOT" \
    -e STATEBUS_FAILED_STAGES="$FAILED_STAGES_CSV" \
    -e STATEBUS_ROLE_PATH_MODE="$ROLE_PATH_MODE" \
    -e STATEBUS_EMBEDDING_MODE="$EMBEDDING_MODE" \
    -e STATEBUS_PERSISTENCE_PROFILE="$PERSISTENCE_PROFILE" \
    -e STATEBUS_CODEACT_RUNS="$CODEACT_RUNS" \
    -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
    -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
    -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM" \
    -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF" \
    "$CONTAINER_NAME" bash -lc 'bash -s' <<'EOF'
#!/usr/bin/env bash
set -uo pipefail

source /usr/local/bin/activate_statebus_container.sh
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
cd "$STATEBUS_PROJECT_ROOT"

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
BASE_RESULT_ROOT="$STATEBUS_BASE_RESULT_ROOT"
LOG_ROOT="$RESULT_ROOT/logs"
JSON_ROOT="$RESULT_ROOT/json"
DIAG_ROOT="$RESULT_ROOT/diagnostics"
RUNTIME_ROOT="$RESULT_ROOT/runtime"
WORKSPACE_ROOT="$RESULT_ROOT/workspaces"
CODEACT_ROOT="$RESULT_ROOT/codeact"
CONSOLE_LOG="$RESULT_ROOT/console.log"
RERUN_STATUS_TSV="$RESULT_ROOT/rerun_status.tsv"

mkdir -p "$RESULT_ROOT" "$LOG_ROOT" "$JSON_ROOT" "$DIAG_ROOT" "$RUNTIME_ROOT" "$WORKSPACE_ROOT" "$CODEACT_ROOT"
printf 'stage\texit_code\tartifact\tlog_path\n' > "$RERUN_STATUS_TSV"
exec > >(tee -a "$CONSOLE_LOG") 2>&1

echo "[statebus-v2-rerun] container rerun root: $RESULT_ROOT"
echo "[statebus-v2-rerun] base container root: $BASE_RESULT_ROOT"
echo "[statebus-v2-rerun] failed stage csv: ${STATEBUS_FAILED_STAGES}"
echo "[statebus-v2-rerun] CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "[statebus-v2-rerun] STATEBUS_EMBED_DEVICE: $STATEBUS_EMBED_DEVICE"

PYTEST_TIMEOUT_ARGS=()
if python3 -m pytest --help 2>/dev/null | grep -q -- "--timeout"; then
  PYTEST_TIMEOUT_ARGS=(--timeout=300)
  echo "[statebus-v2-rerun] pytest timeout plugin detected; using ${PYTEST_TIMEOUT_ARGS[*]}"
else
  echo "[statebus-v2-rerun] pytest timeout plugin not detected; running pytest without --timeout"
fi

SOCKET_PREFIX="sbr-$$"
IFS=',' read -r -a FAILED_STAGE_ARRAY <<< "${STATEBUS_FAILED_STAGES}"

stage_requested() {
  local needle="$1"
  local stage
  for stage in "${FAILED_STAGE_ARRAY[@]}"; do
    if [[ "$stage" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

short_socket_path() {
  local stage_tag="$1"
  printf '/tmp/%s-%s.sock' "$SOCKET_PREFIX" "$stage_tag"
}

json_valid() {
  local path="$1"
  python3 - "$path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    json.load(handle)
PY
}

record_stage() {
  local stage="$1"
  local exit_code="$2"
  local artifact="$3"
  local log_path="$4"
  printf '%s\t%s\t%s\t%s\n' "$stage" "$exit_code" "$artifact" "$log_path" >> "$RERUN_STATUS_TSV"
}

run_text_stage() {
  local stage="$1"
  local log_path="$2"
  shift 2
  echo
  echo "=== ${stage} ==="
  "$@" 2>&1 | tee "$log_path"
  local exit_code=${PIPESTATUS[0]}
  record_stage "$stage" "$exit_code" "-" "$log_path"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${log_path}"
  else
    echo "[fail] ${stage} -> ${log_path} (exit ${exit_code})"
    tail -n 20 "$log_path" || true
  fi
  return 0
}

run_json_stage() {
  local stage="$1"
  local json_path="$2"
  local log_path="$3"
  shift 3
  echo
  echo "=== ${stage} ==="
  : > "$log_path"
  "$@" > >(tee "$json_path") 2> >(tee "$log_path" >&2)
  local exit_code=$?
  if [[ "$exit_code" -eq 0 ]] && json_valid "$json_path" >/dev/null 2>&1; then
    record_stage "$stage" "$exit_code" "$json_path" "$log_path"
    echo "[ok] ${stage} -> ${json_path}"
  else
    record_stage "$stage" "${exit_code:-1}" "$json_path" "$log_path"
    echo "[fail] ${stage} -> ${json_path} (exit ${exit_code})"
    tail -n 20 "$log_path" || true
  fi
  return 0
}

live_runner_json() {
  local runtime_root="$1"
  local workspace_root="$2"
  local socket_path="$3"
  shift 3
  python3 -m v2.benchmark.live_runner \
    --role-path-mode "$STATEBUS_ROLE_PATH_MODE" \
    --embedding-mode "$STATEBUS_EMBEDDING_MODE" \
    --persistence-profile "$STATEBUS_PERSISTENCE_PROFILE" \
    --runtime-root "$runtime_root" \
    --workspace-root "$workspace_root" \
    --socket-path "$socket_path" \
    --suite-id "$STATEBUS_RUN_ID" \
    "$@"
}

resolve_compare_suite_report() {
  local rerun_report="$RUNTIME_ROOT/06_dev_compare_coldstart/benchmark_reports/${STATEBUS_RUN_ID}-cold-start-compare.json"
  local base_report="$BASE_RESULT_ROOT/runtime/06_dev_compare_coldstart/benchmark_reports/${STATEBUS_BASE_RUN_ID}-cold-start-compare.json"
  if [[ -f "$rerun_report" ]]; then
    printf '%s\n' "$rerun_report"
    return 0
  fi
  if [[ -f "$base_report" ]]; then
    printf '%s\n' "$base_report"
    return 0
  fi
  # Fallback: read report_path from stage 06 artifact (run_full_experiment.sh layout)
  local artifact_report
  artifact_report="$(python3 -c "
import json, pathlib, sys
for base in sys.argv[1:]:
    p = pathlib.Path(base) / 'json' / '06_dev_compare_coldstart.json'
    if p.exists():
        d = json.loads(p.read_text())
        rp = d.get('report_path', '')
        if rp:
            print(rp)
            sys.exit(0)
" "$BASE_RESULT_ROOT" "$RERUN_CONTAINER_RESULT_ROOT" 2>/dev/null || true)"
  if [[ -n "$artifact_report" ]]; then
    printf '%s\n' "$artifact_report"
    return 0
  fi
  printf '%s\n' "$base_report"
}

resolve_history_runtime_root() {
  local rerun_history="$RUNTIME_ROOT/08_statebus_dev_replay_ready"
  local base_history="$BASE_RESULT_ROOT/runtime/08_statebus_dev_replay_ready"
  if [[ -d "$rerun_history" ]]; then
    printf '%s\n' "$rerun_history"
    return 0
  fi
  printf '%s\n' "$base_history"
}

run_codeact_acceptance() {
  local stage="11_codeact_acceptance"
  local stage_root="$CODEACT_ROOT/acceptance"
  local log_path="$LOG_ROOT/${stage}.log"
  local json_path="$JSON_ROOT/${stage}.json"
  mkdir -p "$stage_root"
  : > "$log_path"
  echo
  echo "=== ${stage} ==="
  local success_count=0
  local total_runs="${STATEBUS_CODEACT_RUNS}"
  local run_index
  for run_index in $(seq 1 "$total_runs"); do
    local run_root="$stage_root/run-${run_index}"
    local run_log="$stage_root/run-${run_index}.log"
    mkdir -p "$run_root"
    echo "--- codeact run ${run_index}/${total_runs} ---" | tee -a "$log_path"
    python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
      --role-path-mode "$STATEBUS_ROLE_PATH_MODE" \
      --sandbox-backend bwrap \
      --max-repair-attempts 3 \
      --output-root "$run_root" \
      2>&1 | tee "$run_log"
    local exit_code=${PIPESTATUS[0]}
    local summary_file
    summary_file="$(find "$run_root" -name summary.json -type f | head -n 1)"
    if [[ "$exit_code" -eq 0 ]] && [[ -n "$summary_file" ]]; then
      local validator_output
      validator_output="$(python3 - "$summary_file" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], "r", encoding="utf-8"))
ok = bool(payload.get("ok", False))
fallback = bool(payload.get("generation_fallback_used", True))
attempts = int(payload.get("generation_attempt_count", payload.get("attempt_count", 0)))
violations = payload.get("violations", [])
print(
    json.dumps(
        {
            "ok": ok,
            "generation_fallback_used": fallback,
            "attempt_count": attempts,
            "violations": violations,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
if ok and not fallback:
    raise SystemExit(0)
raise SystemExit(1)
PY
)"
      local validator_exit=$?
      printf '%s\n' "$validator_output" | tee -a "$log_path"
      if [[ "$validator_exit" -eq 0 ]]; then
        success_count=$((success_count + 1))
      fi
    else
      printf '{"ok": false, "generation_fallback_used": true, "attempt_count": 0, "violations": ["execution_failed"]}\n' | tee -a "$log_path"
    fi
  done
  python3 - "$stage_root" "$total_runs" "$success_count" "$json_path" <<'PY'
import json
import sys
from pathlib import Path

stage_root = Path(sys.argv[1])
total_runs = int(sys.argv[2])
success_count = int(sys.argv[3])
summaries = []
for run_dir in sorted(path for path in stage_root.glob("run-*") if path.is_dir()):
    summary_candidates = sorted(run_dir.glob("**/summary.json"))
    if not summary_candidates:
        summaries.append(
            {
                "run": run_dir.name,
                "ok": False,
                "generation_fallback_used": True,
                "attempt_count": 0,
                "violations": ["missing_summary_json"],
            }
        )
        continue
    payload = json.loads(summary_candidates[0].read_text(encoding="utf-8"))
    summaries.append(
        {
            "run": run_dir.name,
            "ok": bool(payload.get("ok", False)),
            "generation_fallback_used": bool(payload.get("generation_fallback_used", True)),
            "attempt_count": int(payload.get("generation_attempt_count", payload.get("attempt_count", 0))),
            "violations": list(payload.get("violations", [])),
        }
    )
result = {
    "total_runs": total_runs,
    "success_count": success_count,
    "target_success_count": 3,
    "target_met": success_count >= 3,
    "runs": summaries,
}
Path(sys.argv[4]).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  record_stage "$stage" "0" "$json_path" "$log_path"
  echo "[ok] ${stage} -> ${json_path}"
  return 0
}

run_stage() {
  local stage="$1"
  case "$stage" in
    00_gpu_snapshot)
      run_text_stage \
        "00_gpu_snapshot" \
        "$LOG_ROOT/00_gpu_snapshot.log" \
        nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free --format=csv,noheader,nounits
      ;;
    01_pytest_v2)
      run_text_stage \
        "01_pytest_v2" \
        "$LOG_ROOT/01_pytest_v2.log" \
        python3 -m pytest -q tests/v2 --tb=short "${PYTEST_TIMEOUT_ARGS[@]}"
      ;;
    02_preflight)
      run_json_stage \
        "02_preflight" \
        "$JSON_ROOT/02_preflight.json" \
        "$LOG_ROOT/02_preflight.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/02_preflight" \
        "$WORKSPACE_ROOT/02_preflight" \
        "$(short_socket_path 02)" \
        --suite preflight
      ;;
    03_formal_suite)
      run_json_stage \
        "03_formal_suite" \
        "$JSON_ROOT/03_formal_suite.json" \
        "$LOG_ROOT/03_formal_suite.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/03_formal_suite" \
        "$WORKSPACE_ROOT/03_formal_suite" \
        "$(short_socket_path 03)" \
        --suite formal \
        --benchmark-tier formal
      ;;
    04_formal_compare)
      run_json_stage \
        "04_formal_compare" \
        "$JSON_ROOT/04_formal_compare.json" \
        "$LOG_ROOT/04_formal_compare.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/04_formal_compare" \
        "$WORKSPACE_ROOT/04_formal_compare" \
        "$(short_socket_path 04)" \
        --suite compare \
        --benchmark-tier formal \
        --statebus-mode cold-start
      ;;
    05_carrier_compare)
      run_json_stage \
        "05_carrier_compare" \
        "$JSON_ROOT/05_carrier_compare.json" \
        "$LOG_ROOT/05_carrier_compare.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/05_carrier_compare" \
        "$WORKSPACE_ROOT/05_carrier_compare" \
        "$(short_socket_path 05)" \
        --suite carrier-compare \
        --benchmark-tier dev \
        --statebus-mode cold-start
      ;;
    06_dev_compare_coldstart)
      run_json_stage \
        "06_dev_compare_coldstart" \
        "$JSON_ROOT/06_dev_compare_coldstart.json" \
        "$LOG_ROOT/06_dev_compare_coldstart.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/06_dev_compare_coldstart" \
        "$WORKSPACE_ROOT/06_dev_compare_coldstart" \
        "$(short_socket_path 06)" \
        --suite compare \
        --benchmark-tier dev \
        --statebus-mode cold-start
      ;;
    07_statebus_dev_coldstart)
      run_json_stage \
        "07_statebus_dev_coldstart" \
        "$JSON_ROOT/07_statebus_dev_coldstart.json" \
        "$LOG_ROOT/07_statebus_dev_coldstart.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/07_statebus_dev_coldstart" \
        "$WORKSPACE_ROOT/07_statebus_dev_coldstart" \
        "$(short_socket_path 07)" \
        --suite statebus \
        --benchmark-tier dev \
        --statebus-mode cold-start
      ;;
    08_statebus_dev_replay_ready)
      run_json_stage \
        "08_statebus_dev_replay_ready" \
        "$JSON_ROOT/08_statebus_dev_replay_ready.json" \
        "$LOG_ROOT/08_statebus_dev_replay_ready.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/08_statebus_dev_replay_ready" \
        "$WORKSPACE_ROOT/08_statebus_dev_replay_ready" \
        "$(short_socket_path 08)" \
        --suite statebus \
        --benchmark-tier dev \
        --replay-mode replay-ready
      ;;
    09_continuous_collection)
      run_json_stage \
        "09_continuous_collection" \
        "$JSON_ROOT/09_continuous_collection.json" \
        "$LOG_ROOT/09_continuous_collection.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/09_continuous_collection" \
        "$WORKSPACE_ROOT/09_continuous_collection" \
        "$(short_socket_path 09)" \
        --suite continuous \
        --benchmark-tier dev
      ;;
    10_continuous_replay_collection)
      run_json_stage \
        "10_continuous_replay_collection" \
        "$JSON_ROOT/10_continuous_replay_collection.json" \
        "$LOG_ROOT/10_continuous_replay_collection.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/10_continuous_replay_collection" \
        "$WORKSPACE_ROOT/10_continuous_replay_collection" \
        "$(short_socket_path 10)" \
        --suite continuous-replay \
        --benchmark-tier dev
      ;;
    11_codeact_acceptance)
      run_codeact_acceptance
      ;;
    12_replay_negative_audit)
      run_json_stage \
        "12_replay_negative_audit" \
        "$JSON_ROOT/12_replay_negative_audit.json" \
        "$LOG_ROOT/12_replay_negative_audit.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/12_replay_negative_audit" \
        "$WORKSPACE_ROOT/12_replay_negative_audit" \
        "$(short_socket_path 12)" \
        --suite replay-negative-audit \
        --benchmark-tier dev
      ;;
    13_incident_diagnosis_v2)
      run_json_stage \
        "13_incident_diagnosis_v2" \
        "$JSON_ROOT/13_incident_diagnosis_v2.json" \
        "$LOG_ROOT/13_incident_diagnosis_v2.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/13_incident_diagnosis_v2" \
        "$WORKSPACE_ROOT/13_incident_diagnosis_v2" \
        "$(short_socket_path 13)" \
        --suite statebus \
        --benchmark-tier dev \
        --family incident_diagnosis_v2
      ;;
    14_compare_diagnostics_dev)
      run_json_stage \
        "14_compare_diagnostics_dev" \
        "$JSON_ROOT/14_compare_diagnostics_dev.json" \
        "$LOG_ROOT/14_compare_diagnostics_dev.stderr.log" \
        python3 scripts/v2_diagnostics/compare_diagnostics.py \
        --compare-suite-report "$(resolve_compare_suite_report)" \
        --family-dir v2/benchmark/samples/fixed_answer_family \
        --output-root "$DIAG_ROOT/compare"
      ;;
    15_runtime_persistence_breakdown)
      run_json_stage \
        "15_runtime_persistence_breakdown" \
        "$JSON_ROOT/15_runtime_persistence_breakdown.json" \
        "$LOG_ROOT/15_runtime_persistence_breakdown.stderr.log" \
        python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
        --output-root "$DIAG_ROOT/runtime-persistence" \
        --role-path-mode "$STATEBUS_ROLE_PATH_MODE" \
        --embedding-mode "$STATEBUS_EMBEDDING_MODE" \
        --history-runtime-root "$(resolve_history_runtime_root)"
      ;;
    16_flagship_ablation)
      run_json_stage \
        "16_flagship_ablation" \
        "$JSON_ROOT/16_flagship_ablation.json" \
        "$LOG_ROOT/16_flagship_ablation.stderr.log" \
        live_runner_json \
        "$RUNTIME_ROOT/16_flagship_ablation" \
        "$WORKSPACE_ROOT/16_flagship_ablation" \
        "$(short_socket_path 16)" \
        --suite flagship-ablation \
        --benchmark-tier dev
      ;;
    *)
      echo "[statebus-v2-rerun] unknown stage: ${stage}" >&2
      record_stage "$stage" "127" "-" "-"
      ;;
  esac
}

for stage in \
  00_gpu_snapshot \
  01_pytest_v2 \
  02_preflight \
  03_formal_suite \
  04_formal_compare \
  05_carrier_compare \
  06_dev_compare_coldstart \
  07_statebus_dev_coldstart \
  08_statebus_dev_replay_ready \
  09_continuous_collection \
  10_continuous_replay_collection \
  11_codeact_acceptance \
  12_replay_negative_audit \
  13_incident_diagnosis_v2 \
  14_compare_diagnostics_dev \
  15_runtime_persistence_breakdown \
  16_flagship_ablation; do
  if stage_requested "$stage"; then
    run_stage "$stage"
  fi
done
EOF
fi

python3 - "$BASE_RESULT_ROOT" "$HOST_RESULT_ROOT" "$FAILED_STAGES_CSV" <<'PY'
import json
import re
import sys
from pathlib import Path

base_root = Path(sys.argv[1])
rerun_root = Path(sys.argv[2])
requested_failed = [stage for stage in sys.argv[3].split(",") if stage]

stage_order = [
    "00_gpu_snapshot",
    "01_pytest_v2",
    "02_preflight",
    "03_formal_suite",
    "04_formal_compare",
    "05_carrier_compare",
    "06_dev_compare_coldstart",
    "07_statebus_dev_coldstart",
    "08_statebus_dev_replay_ready",
    "09_continuous_collection",
    "10_continuous_replay_collection",
    "11_codeact_acceptance",
    "12_replay_negative_audit",
    "13_incident_diagnosis_v2",
    "14_compare_diagnostics_dev",
    "15_runtime_persistence_breakdown",
    "16_flagship_ablation",
]


def load_status(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    result = {}
    for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if index == 0 or not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        if len(parts) < 4:
            continue
        stage, exit_code, artifact, log_path = parts[:4]
        result[stage] = {
            "stage": stage,
            "exit_code": int(exit_code),
            "artifact": artifact,
            "log_path": log_path,
        }
    return result


def stage_artifact_and_log(root: Path, stage: str) -> tuple[str, str]:
    if stage in {"00_gpu_snapshot", "01_pytest_v2"}:
        return "-", str(root / "logs" / f"{stage}.log")
    if stage == "11_codeact_acceptance":
        return (
            str(root / "json" / f"{stage}.json"),
            str(root / "logs" / f"{stage}.log"),
        )
    return (
        str(root / "json" / f"{stage}.json"),
        str(root / "logs" / f"{stage}.stderr.log"),
    )


def chosen_root_for(stage: str, rerun_status: dict, base_status: dict) -> Path | None:
    if stage in rerun_status:
        return rerun_root
    if stage in base_status:
        return base_root
    return None


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


base_status = load_status(base_root / "status.tsv")
rerun_status = load_status(rerun_root / "rerun_status.tsv")

merged_stages = []
for stage in stage_order:
    source = None
    status = None
    if stage in rerun_status:
        source = "rerun"
        status = rerun_status[stage]
    elif stage in base_status:
        source = "base"
        status = base_status[stage]
    if status is None:
        continue
    chosen_root = rerun_root if source == "rerun" else base_root
    artifact, log_path = stage_artifact_and_log(chosen_root, stage)
    merged_stages.append(
        {
            "stage": stage,
            "exit_code": int(status["exit_code"]),
            "source": source,
            "artifact": artifact,
            "log_path": log_path,
        }
    )

status_tsv = rerun_root / "status.tsv"
manifest_json = rerun_root / "manifest.json"
summary_json = rerun_root / "summary.json"
summary_md = rerun_root / "summary.md"

status_lines = ["stage\texit_code\tsource\tartifact\tlog_path"]
for stage in merged_stages:
    status_lines.append(
        f"{stage['stage']}\t{stage['exit_code']}\t{stage['source']}\t{stage['artifact']}\t{stage['log_path']}"
    )
status_tsv.write_text("\n".join(status_lines) + "\n", encoding="utf-8")

root_by_stage = {stage["stage"]: (rerun_root if stage["source"] == "rerun" else base_root) for stage in merged_stages}


def json_for_stage(stage: str) -> dict:
    root = root_by_stage.get(stage)
    if root is None:
        return {}
    return read_json(root / "json" / f"{stage}.json")


def log_for_stage(stage: str) -> str:
    root = root_by_stage.get(stage)
    if root is None:
        return ""
    if stage in {"00_gpu_snapshot", "01_pytest_v2"}:
        return read_text(root / "logs" / f"{stage}.log")
    if stage == "11_codeact_acceptance":
        return read_text(root / "logs" / f"{stage}.log")
    return read_text(root / "logs" / f"{stage}.stderr.log")


pytest_log = log_for_stage("01_pytest_v2")
pytest_match = re.search(r"(\d+) passed", pytest_log)
pytest_passed = int(pytest_match.group(1)) if pytest_match else None

formal_compare = json_for_stage("04_formal_compare")
carrier_compare = json_for_stage("05_carrier_compare")
dev_compare = json_for_stage("06_dev_compare_coldstart")
dev_replay = json_for_stage("08_statebus_dev_replay_ready")
continuous_collection = json_for_stage("09_continuous_collection")
continuous_replay = json_for_stage("10_continuous_replay_collection")
codeact_acceptance = json_for_stage("11_codeact_acceptance")
negative_audit = json_for_stage("12_replay_negative_audit")
incident_family = json_for_stage("13_incident_diagnosis_v2")
compare_diag = json_for_stage("14_compare_diagnostics_dev")
runtime_diag = json_for_stage("15_runtime_persistence_breakdown")
flagship = json_for_stage("16_flagship_ablation")

formal_summary = formal_compare.get("comparison_summary", {})
carrier_summary = carrier_compare.get("comparison_summary", {})
dev_compare_summary = dev_compare.get("comparison_summary", {})
dev_replay_waterfall = dev_replay.get("waterfall_metrics", {})
continuous_collection_summary = continuous_collection.get("collection_summary", {})
continuous_replay_summary = continuous_replay.get("collection_summary", {})
incident_collection_summary = incident_family.get("collection_summary", incident_family.get("waterfall_metrics", {}))
incident_l3_telemetry = {}
incident_layers = incident_family.get("layers", [])
if incident_layers:
    incident_l3_telemetry = incident_layers[-1].get("telemetry_summary", {})

codeact_runs = list(codeact_acceptance.get("runs", [])) if isinstance(codeact_acceptance, dict) else []
derived_codeact_success_count = sum(
    1 for run in codeact_runs if bool(run.get("ok")) and not bool(run.get("generation_fallback_used", True))
)
raw_success_count = codeact_acceptance.get("success_count") if isinstance(codeact_acceptance, dict) else None
if isinstance(raw_success_count, int):
    codeact_success_count = max(raw_success_count, derived_codeact_success_count)
else:
    codeact_success_count = derived_codeact_success_count
codeact_total_runs = codeact_acceptance.get("total_runs") if isinstance(codeact_acceptance, dict) else None
if not isinstance(codeact_total_runs, int):
    codeact_total_runs = len(codeact_runs) if codeact_runs else None
codeact_target_success_count = codeact_acceptance.get("target_success_count", 3) if isinstance(codeact_acceptance, dict) else 3
codeact_target_met = codeact_success_count >= codeact_target_success_count if codeact_total_runs is not None else False
if isinstance(codeact_acceptance, dict):
    codeact_acceptance["success_count"] = codeact_success_count
    codeact_acceptance["total_runs"] = codeact_total_runs
    codeact_acceptance["target_success_count"] = codeact_target_success_count
    codeact_acceptance["target_met"] = codeact_target_met

failures = [stage for stage in merged_stages if stage["exit_code"] != 0]

manifest = {
    "base_result_root": str(base_root),
    "rerun_result_root": str(rerun_root),
    "requested_failed_stages": requested_failed,
    "rerun_stage_count": len(rerun_status),
    "merged_stage_count": len(merged_stages),
    "failed_stage_count": len(failures),
    "stages": merged_stages,
}

summary = {
    "base_result_root": str(base_root),
    "rerun_result_root": str(rerun_root),
    "requested_failed_stages": requested_failed,
    "failed_stage_count": len(failures),
    "failed_stages": [stage["stage"] for stage in failures],
    "pytest_passed": pytest_passed,
    "formal_compare": {
        "formal_superiority_claim_allowed": formal_compare.get("metadata", {}).get("formal_superiority_claim_allowed"),
        "formal_efficiency_claim_allowed": formal_compare.get("metadata", {}).get("formal_efficiency_claim_allowed"),
        "comparison_valid": formal_summary.get("api_comparison_valid"),
        "quality_floor_gate_failed": formal_compare.get("metadata", {}).get("comparison_valid") is False,
        "statebus_quality": formal_summary.get("api_debug_statebus_quality_floor_pass_count"),
        "external_quality": formal_summary.get("api_debug_external_quality_floor_pass_count"),
        "quality_delta": formal_summary.get("api_debug_quality_floor_pass_delta"),
        "tokens_delta": formal_summary.get("api_debug_llm_total_tokens_delta"),
        "bytes_delta": formal_summary.get("api_debug_prompt_bytes_delta"),
        "task_ms_delta": formal_summary.get("api_debug_task_ms_delta"),
        "net_llm_ms_delta": formal_summary.get("api_debug_net_llm_ms_delta"),
        "system_overhead_ms_delta": formal_summary.get("api_debug_system_overhead_ms_delta"),
    },
    "carrier_compare": {
        "quality_delta": carrier_summary.get("api_debug_quality_floor_pass_delta"),
        "tokens_delta": carrier_summary.get("api_debug_llm_total_tokens_delta"),
        "bytes_delta": carrier_summary.get("api_debug_prompt_bytes_delta"),
    },
    "dev_compare": {
        "quality_delta": dev_compare_summary.get("api_debug_quality_floor_pass_delta"),
        "tokens_delta": dev_compare_summary.get("api_debug_llm_total_tokens_delta"),
        "bytes_delta": dev_compare_summary.get("api_debug_prompt_bytes_delta"),
        "codeact_execution_stage_ms_delta": dev_compare_summary.get("api_debug_codeact_execution_stage_ms_delta"),
    },
    "dev_replay": {
        "quality": dev_replay_waterfall.get("L3_quality_floor_pass_count"),
        "reuse_gain": dev_replay_waterfall.get("L3_reuse_gain"),
        "semantic_state_transfer_count": dev_replay_waterfall.get("L2_semantic_state_transfer_count"),
    },
    "continuous": {
        "history_reuse_gain": continuous_collection_summary.get("L3_history_reuse_gain"),
        "validated_replay_count": continuous_collection_summary.get("validated_replay_count"),
        "exact_replay_count": continuous_collection_summary.get("exact_replay_count"),
    },
    "continuous_replay": {
        "history_reuse_gain": continuous_replay_summary.get("L3_history_reuse_gain"),
        "validated_replay_count": continuous_replay_summary.get("validated_replay_count"),
        "exact_replay_count": continuous_replay_summary.get("exact_replay_count"),
        "skipped_step_count": continuous_replay_summary.get("skipped_step_count"),
    },
    "incident_diagnosis_v2": {
        "history_reuse_gain": incident_collection_summary.get("L3_history_reuse_gain"),
        "validated_replay_count": incident_l3_telemetry.get("validated_replay_count"),
        "exact_replay_count": incident_l3_telemetry.get("exact_replay_count"),
        "skipped_step_count": incident_l3_telemetry.get("skipped_step_count"),
    },
    "replay_negative_audit": {
        "audit_pass": negative_audit.get("audit_pass"),
        "case_count": negative_audit.get("case_count"),
    },
    "codeact_acceptance": codeact_acceptance,
    "compare_diagnostics_bundle": compare_diag.get("bundle_dir"),
    "runtime_persistence_bundle": runtime_diag.get("bundle_dir"),
    "stage_sources": {stage["stage"]: stage["source"] for stage in merged_stages},
}
if flagship:
    summary["flagship_ablation"] = {
        "role_path_mode": flagship.get("role_path_mode"),
        "claim_level": flagship.get("claim_level"),
        "non_text_state_stress_summary": flagship.get("non_text_state_stress_summary"),
    }

manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

md_lines = [
    "# StateBus v2 Failed-Stage Rerun Summary",
    "",
    f"- Base result root: `{base_root}`",
    f"- Rerun result root: `{rerun_root}`",
    f"- Requested failed stages: `{requested_failed}`",
    f"- Remaining failed stages: `{len(failures)}`",
    f"- Pytest passed: `{pytest_passed}`",
    "",
    "## Formal Compare",
    "",
    f"- formal_superiority_claim_allowed: `{summary['formal_compare']['formal_superiority_claim_allowed']}`",
    f"- formal_efficiency_claim_allowed: `{summary['formal_compare']['formal_efficiency_claim_allowed']}`",
    f"- statebus_quality: `{summary['formal_compare']['statebus_quality']}`",
    f"- external_quality: `{summary['formal_compare']['external_quality']}`",
    f"- tokens_delta: `{summary['formal_compare']['tokens_delta']}`",
    f"- bytes_delta: `{summary['formal_compare']['bytes_delta']}`",
    f"- net_llm_ms_delta: `{summary['formal_compare']['net_llm_ms_delta']}`",
    f"- system_overhead_ms_delta: `{summary['formal_compare']['system_overhead_ms_delta']}`",
    "",
    "## Replay And Continuous",
    "",
    f"- dev_replay_reuse_gain: `{summary['dev_replay']['reuse_gain']}`",
    f"- continuous_validated_replay_count: `{summary['continuous_replay']['validated_replay_count']}`",
    f"- continuous_exact_replay_count: `{summary['continuous_replay']['exact_replay_count']}`",
    f"- continuous_skipped_step_count: `{summary['continuous_replay']['skipped_step_count']}`",
    f"- incident_validated_replay_count: `{summary['incident_diagnosis_v2']['validated_replay_count']}`",
    f"- incident_exact_replay_count: `{summary['incident_diagnosis_v2']['exact_replay_count']}`",
    f"- incident_skipped_step_count: `{summary['incident_diagnosis_v2']['skipped_step_count']}`",
    "",
    "## CodeAct",
    "",
    f"- success_count: `{codeact_success_count}` / `{codeact_total_runs}`",
    f"- target_met: `{codeact_target_met}`",
    "",
    "## Diagnostics",
    "",
    f"- compare_diagnostics_bundle: `{summary.get('compare_diagnostics_bundle')}`",
    f"- runtime_persistence_bundle: `{summary.get('runtime_persistence_bundle')}`",
    "",
    "## Stage Status",
    "",
]
for stage in merged_stages:
    md_lines.append(
        f"- `{stage['stage']}` | source=`{stage['source']}` | exit=`{stage['exit_code']}` | artifact=`{stage['artifact']}` | log=`{stage['log_path']}`"
    )

md_lines.extend(["", "## Remaining Failed Stages", ""])
if failures:
    for failure in failures:
        md_lines.append(
            f"- `{failure['stage']}` | source=`{failure['source']}` | log=`{failure['log_path']}`"
        )
else:
    md_lines.append("- none")

summary_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
PY

printf '\n[statebus-v2-rerun] host-visible results: %s\n' "$HOST_RESULT_ROOT"
printf '[statebus-v2-rerun] merged summary: %s\n' "${HOST_RESULT_ROOT}/summary.md"
