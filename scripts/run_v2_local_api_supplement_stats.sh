#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"

BASE_RUN_ID="${STATEBUS_LOCAL_API_BASE_RUN_ID:-sb2-gpu1-20260708_084458}"
BASE_RESULT_ROOT="${STATEBUS_LOCAL_API_BASE_RESULT_ROOT:-${HOST_RUNS_ROOT}/${BASE_RUN_ID}}"
BASE_CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${BASE_RUN_ID}"
BASE_ARTIFACT_LABEL="${STATEBUS_LOCAL_API_BASE_ARTIFACT_LABEL:-local_api_${BASE_RUN_ID#sb2-gpu1-}}"

STAMP="${STATEBUS_LOCAL_API_SUPPLEMENT_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID:-${BASE_RUN_ID}-supplement-${STAMP}}"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
AUDIT_ARTIFACT_ROOT="${STATEBUS_LOCAL_API_SUPPLEMENT_AUDIT_ARTIFACT_ROOT:-${HOST_PROJECT_ROOT}/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/${BASE_ARTIFACT_LABEL}_supplement_${STAMP}}"

TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-1}}"
TARGET_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
TARGET_CODEACT_SANDBOX_BACKEND="${STATEBUS_CODEACT_SANDBOX_BACKEND:-auto}"
CODEACT_ACCEPTANCE_SANDBOX_BACKEND="${STATEBUS_CODEACT_ACCEPTANCE_SANDBOX_BACKEND:-bwrap}"
CODEACT_ACCEPTANCE_RUNS="${STATEBUS_CODEACT_ACCEPTANCE_RUNS:-5}"
CODEACT_ACCEPTANCE_TARGET="${STATEBUS_CODEACT_ACCEPTANCE_TARGET:-3}"
CODEACT_MAX_REPAIR_ATTEMPTS="${STATEBUS_CODEACT_MAX_REPAIR_ATTEMPTS:-3}"
STRICT_EXIT="${STATEBUS_LOCAL_API_SUPPLEMENT_STRICT_EXIT:-1}"
NO_TIMEOUTS="${STATEBUS_LOCAL_API_NO_TIMEOUTS:-1}"
RUN_VLLM_PREFIX_PROBE="${STATEBUS_RUN_VLLM_PREFIX_PROBE:-0}"
VLLM_METRICS_URL="${STATEBUS_VLLM_METRICS_URL:-http://127.0.0.1:8000/metrics}"
VLLM_BASE_URL="${STATEBUS_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
VLLM_MODEL="${STATEBUS_VLLM_MODEL:-${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}}"
VLLM_API_KEY="${STATEBUS_VLLM_API_KEY:-EMPTY}"

IMPORT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_IMPORT_TIMEOUT_SECONDS:-120}"
HEALTH_PROBE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_HEALTH_PROBE_TIMEOUT_SECONDS:-120}"
PY_COMPILE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_PY_COMPILE_TIMEOUT_SECONDS:-300}"
HEALTH_PYTEST_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_HEALTH_PYTEST_TIMEOUT_SECONDS:-1200}"
KV_PREFIX_HEALTH_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_KV_PREFIX_HEALTH_TIMEOUT_SECONDS:-300}"
CODEACT_SMOKE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_CODEACT_SMOKE_TIMEOUT_SECONDS:-300}"
CODEACT_ACCEPTANCE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS:-0}"
KV_PREFIX_DEMO_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_KV_PREFIX_DEMO_TIMEOUT_SECONDS:-7200}"
VLLM_PREFIX_PROBE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_VLLM_PREFIX_PROBE_TIMEOUT_SECONDS:-120}"
VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS:-1800}"
FLAGSHIP_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS:-7200}"

if [[ "$NO_TIMEOUTS" == "1" ]]; then
  IMPORT_TIMEOUT_SECONDS=0
  HEALTH_PROBE_TIMEOUT_SECONDS=0
  PY_COMPILE_TIMEOUT_SECONDS=0
  HEALTH_PYTEST_TIMEOUT_SECONDS=0
  KV_PREFIX_HEALTH_TIMEOUT_SECONDS=0
  CODEACT_SMOKE_TIMEOUT_SECONDS=0
  CODEACT_ACCEPTANCE_TIMEOUT_SECONDS=0
  KV_PREFIX_DEMO_TIMEOUT_SECONDS=0
  VLLM_PREFIX_PROBE_TIMEOUT_SECONDS=0
  VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS=0
  FLAGSHIP_TIMEOUT_SECONDS=0
fi

if [[ "${STATEBUS_LOCAL_API_SUPPLEMENT_IN_CONTAINER:-0}" != "1" ]]; then
  if [[ ! -d "$BASE_RESULT_ROOT" ]]; then
    echo "[statebus-v2-local-api-supplement] missing base result root: ${BASE_RESULT_ROOT}" >&2
    exit 1
  fi
  mkdir -p "$HOST_RESULT_ROOT" "$AUDIT_ARTIFACT_ROOT"
  cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api supplement statistics run

Base run:
  ${BASE_RUN_ID}

Base host result root:
  ${BASE_RESULT_ROOT}

Supplement host result root:
  ${HOST_RESULT_ROOT}

Supplement container result root:
  ${CONTAINER_RESULT_ROOT}

Audit artifact copy:
  ${AUDIT_ARTIFACT_ROOT}

Scope:
  - does not rerun passed formal 25-case / 5-family benchmark stages
  - runs an incremental health check over current risky surfaces: container root, GPU, py_compile, targeted pytest, KV prefix contract, CodeAct, flagship ablation
  - reruns only missing or failed heavy live evidence and newly added risk surfaces: CodeAct acceptance, KV prefix demo, and flagship ablation
  - physical GPU selection is controlled by STATEBUS_CUDA_VISIBLE_DEVICES
  - container embedding device is ${TARGET_EMBED_DEVICE}; cuda:0 means the first visible device
  - AF_UNIX sockets use short /tmp/sb2sup-<hash>.sock paths
  - docker exec uses root inside the container
  - no_timeouts=${NO_TIMEOUTS}
EOF

  if [[ "${STATEBUS_LOCAL_API_SUPPLEMENT_DRY_RUN:-0}" == "1" ]]; then
    echo "[statebus-v2-local-api-supplement] dry run"
    echo "base_run_id=${BASE_RUN_ID}"
    echo "run_id=${RUN_ID}"
    echo "host_result_root=${HOST_RESULT_ROOT}"
    echo "audit_artifact_root=${AUDIT_ARTIFACT_ROOT}"
    echo "container=${CONTAINER_NAME}"
    echo "cuda_visible_devices=${TARGET_CUDA_VISIBLE_DEVICES}"
    echo "embed_device=${TARGET_EMBED_DEVICE}"
    echo "codeact_acceptance_runs=${CODEACT_ACCEPTANCE_RUNS}"
    echo "codeact_acceptance_target=${CODEACT_ACCEPTANCE_TARGET}"
    echo "codeact_acceptance_sandbox_backend=${CODEACT_ACCEPTANCE_SANDBOX_BACKEND}"
    echo "kv_prefix_demo_timeout_seconds=${KV_PREFIX_DEMO_TIMEOUT_SECONDS}"
    echo "run_vllm_prefix_probe=${RUN_VLLM_PREFIX_PROBE}"
    echo "vllm_metrics_url=${VLLM_METRICS_URL}"
    echo "vllm_base_url=${VLLM_BASE_URL}"
    echo "vllm_model=${VLLM_MODEL}"
    echo "no_timeouts=${NO_TIMEOUTS}"
    exit 0
  fi

  echo "[statebus-v2-local-api-supplement] base run: ${BASE_RUN_ID}"
  echo "[statebus-v2-local-api-supplement] starting run: ${RUN_ID}"
  echo "[statebus-v2-local-api-supplement] host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api-supplement] audit artifact root: ${AUDIT_ARTIFACT_ROOT}"

  docker_env=(
    -e STATEBUS_LOCAL_API_SUPPLEMENT_IN_CONTAINER=1
    -e STATEBUS_LOCAL_API_BASE_RUN_ID="$BASE_RUN_ID"
    -e STATEBUS_LOCAL_API_BASE_RESULT_ROOT="$BASE_CONTAINER_RESULT_ROOT"
    -e STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID="$RUN_ID"
    -e STATEBUS_RESULT_ROOT="$CONTAINER_RESULT_ROOT"
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT"
    -e STATEBUS_LOCAL_API_NO_TIMEOUTS="$NO_TIMEOUTS"
    -e STATEBUS_LOCAL_API_IMPORT_TIMEOUT_SECONDS="$IMPORT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_HEALTH_PROBE_TIMEOUT_SECONDS="$HEALTH_PROBE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_PY_COMPILE_TIMEOUT_SECONDS="$PY_COMPILE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_HEALTH_PYTEST_TIMEOUT_SECONDS="$HEALTH_PYTEST_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_KV_PREFIX_HEALTH_TIMEOUT_SECONDS="$KV_PREFIX_HEALTH_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_CODEACT_SMOKE_TIMEOUT_SECONDS="$CODEACT_SMOKE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS="$CODEACT_ACCEPTANCE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_KV_PREFIX_DEMO_TIMEOUT_SECONDS="$KV_PREFIX_DEMO_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_VLLM_PREFIX_PROBE_TIMEOUT_SECONDS="$VLLM_PREFIX_PROBE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS="$VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS"
    -e STATEBUS_CODEACT_ACCEPTANCE_RUNS="$CODEACT_ACCEPTANCE_RUNS"
    -e STATEBUS_CODEACT_ACCEPTANCE_TARGET="$CODEACT_ACCEPTANCE_TARGET"
    -e STATEBUS_CODEACT_ACCEPTANCE_SANDBOX_BACKEND="$CODEACT_ACCEPTANCE_SANDBOX_BACKEND"
    -e STATEBUS_CODEACT_MAX_REPAIR_ATTEMPTS="$CODEACT_MAX_REPAIR_ATTEMPTS"
    -e STATEBUS_RUN_VLLM_PREFIX_PROBE="$RUN_VLLM_PREFIX_PROBE"
    -e STATEBUS_VLLM_METRICS_URL="$VLLM_METRICS_URL"
    -e STATEBUS_VLLM_BASE_URL="$VLLM_BASE_URL"
    -e STATEBUS_VLLM_MODEL="$VLLM_MODEL"
    -e STATEBUS_VLLM_API_KEY="$VLLM_API_KEY"
    -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES"
    -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE"
    -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM"
    -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF"
    -e STATEBUS_CODEACT_SANDBOX_BACKEND="$TARGET_CODEACT_SANDBOX_BACKEND"
  )

  add_optional_env() {
    local name="$1"
    local value="${!name:-}"
    if [[ -n "$value" ]]; then
      docker_env+=(-e "${name}=${value}")
    fi
  }

  for optional_name in \
    STATEBUS_LLM_API_KEY \
    OPENAI_API_KEY \
    ANTHROPIC_API_KEY \
    STATEBUS_LLM_CONFIG_FILE \
    STATEBUS_LLM_CONFIG_PATH \
    STATEBUS_LLM_ENV_FILE \
    STATEBUS_EMBED_MODEL_PATH \
    HF_HOME \
    TRANSFORMERS_CACHE
  do
    add_optional_env "$optional_name"
  done

  set +e
  docker exec -i -u 0 "${docker_env[@]}" "$CONTAINER_NAME" bash -lc 'bash -s' < "$0"
  run_exit=$?
  set -e

  if [[ -d "${HOST_RESULT_ROOT}/artifacts" ]]; then
    cp -R "${HOST_RESULT_ROOT}/artifacts/." "$AUDIT_ARTIFACT_ROOT/"
    /usr/bin/python3 - "$HOST_RESULT_ROOT" "$AUDIT_ARTIFACT_ROOT" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

run_root = Path(sys.argv[1])
artifact_root = Path(sys.argv[2])
diagnostics_root = artifact_root / "diagnostics"
runtime_files_root = diagnostics_root / "runtime_files"
runtime_files_root.mkdir(parents=True, exist_ok=True)
copied: list[dict[str, str]] = []


def copy_file(path: Path, *, reason: str) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        rel = path.relative_to(run_root)
    except ValueError:
        rel = Path(path.name)
    dest = runtime_files_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    copied.append({"reason": reason, "source": str(path), "artifact_relpath": str(dest.relative_to(artifact_root))})


work_root = run_root / "work"
for pattern, reason in (
    ("**/benchmark_reports/*.json", "nested_benchmark_report"),
    ("**/benchmark_reports/*.md", "nested_benchmark_report"),
    ("**/codeact_acceptance/**/*.json", "codeact_acceptance_artifact"),
    ("**/codeact_acceptance/**/*.md", "codeact_acceptance_artifact"),
    ("**/codeact_acceptance/**/*.py", "codeact_acceptance_artifact"),
    ("**/outputs/result.json", "statebus_case_output"),
    ("**/external_text_output.json", "external_case_output"),
    ("**/external_text_report.json", "external_case_report"),
    ("**/logs/hydration_audit.json", "hydration_audit"),
    ("**/registry/ref_registry.json", "ref_registry"),
):
    for path in work_root.glob(pattern):
        copy_file(path, reason=reason)

manifest = {
    "schema_version": "statebus.local_api_supplement_diagnostics_copy.v1",
    "run_root": str(run_root),
    "artifact_root": str(artifact_root),
    "copied_file_count": len(copied),
    "copied_files": copied,
}
(diagnostics_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    cat > "${AUDIT_ARTIFACT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api supplement result copy

Base host result root:
  ${BASE_RESULT_ROOT}

Supplement host result root:
  ${HOST_RESULT_ROOT}

Main files:
  summary.md
  summary.json
  status.tsv
  console.log
  stages/*/stdout.json
  stages/*/console.log

Diagnostics:
  diagnostics/manifest.json
  diagnostics/runtime_files/work/**/benchmark_reports/*.json
  diagnostics/runtime_files/work/**/codeact_acceptance/**
EOF
  else
    echo "[statebus-v2-local-api-supplement] warning: missing artifact root: ${HOST_RESULT_ROOT}/artifacts" >&2
  fi

  echo "[statebus-v2-local-api-supplement] run exit: ${run_exit}"
  echo "[statebus-v2-local-api-supplement] host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api-supplement] audit artifact copy: ${AUDIT_ARTIFACT_ROOT}"
  exit "$run_exit"
fi

set -uo pipefail

export STATEBUS_ACTUAL_ACTIVATION_SCRIPT="none"
export STATEBUS_ACTIVATION_STATUS="not_attempted"
export STATEBUS_ACTIVATION_ERROR=""

activate_statebus() {
  if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
    STATEBUS_ACTUAL_ACTIVATION_SCRIPT="/usr/local/bin/activate_statebus_container.sh"
    # shellcheck disable=SC1091
    if source /usr/local/bin/activate_statebus_container.sh; then
      STATEBUS_ACTIVATION_STATUS="success"
      export STATEBUS_ACTUAL_ACTIVATION_SCRIPT STATEBUS_ACTIVATION_STATUS STATEBUS_ACTIVATION_ERROR
      return 0
    fi
    STATEBUS_ACTIVATION_STATUS="failed"
    STATEBUS_ACTIVATION_ERROR="container_activation_failed"
    export STATEBUS_ACTUAL_ACTIVATION_SCRIPT STATEBUS_ACTIVATION_STATUS STATEBUS_ACTIVATION_ERROR
    return 1
  fi
  STATEBUS_ACTUAL_ACTIVATION_SCRIPT="none"
  STATEBUS_ACTIVATION_STATUS="not_found"
  export STATEBUS_ACTUAL_ACTIVATION_SCRIPT STATEBUS_ACTIVATION_STATUS STATEBUS_ACTIVATION_ERROR
  return 0
}

cd "$STATEBUS_PROJECT_ROOT"
if ! activate_statebus; then
  echo "[statebus-v2-local-api-supplement] activation failed; continuing with /usr/bin/python3" >&2
fi

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
BASE_RESULT_ROOT="$STATEBUS_LOCAL_API_BASE_RESULT_ROOT"
ARTIFACT_ROOT="$RESULT_ROOT/artifacts"
WORK_ROOT="$RESULT_ROOT/work"
STATUS_TSV="$ARTIFACT_ROOT/status.tsv"
SUMMARY_MD="$ARTIFACT_ROOT/summary.md"
SUMMARY_JSON="$ARTIFACT_ROOT/summary.json"
CONSOLE_LOG="$ARTIFACT_ROOT/console.log"

mkdir -p "$ARTIFACT_ROOT/stages" "$WORK_ROOT"
printf 'stage\texit_code\trequired\tkind\tartifact\tlog_path\tduration_s\n' > "$STATUS_TSV"
exec > >(tee -a "$CONSOLE_LOG") 2>&1

OVERALL_FAILURE=0

echo "[statebus-v2-local-api-supplement] container result root: $RESULT_ROOT"
echo "[statebus-v2-local-api-supplement] base result root: $BASE_RESULT_ROOT"
echo "[statebus-v2-local-api-supplement] run id: ${STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID}"
echo "[statebus-v2-local-api-supplement] CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-}"
echo "[statebus-v2-local-api-supplement] STATEBUS_EMBED_DEVICE: ${STATEBUS_EMBED_DEVICE:-}"
echo "[statebus-v2-local-api-supplement] CodeAct smoke backend: ${STATEBUS_CODEACT_SANDBOX_BACKEND:-}"
echo "[statebus-v2-local-api-supplement] CodeAct acceptance backend: ${STATEBUS_CODEACT_ACCEPTANCE_SANDBOX_BACKEND:-}"
echo "[statebus-v2-local-api-supplement] CodeAct acceptance runs: ${STATEBUS_CODEACT_ACCEPTANCE_RUNS:-5}"
echo "[statebus-v2-local-api-supplement] vLLM prefix probe enabled: ${STATEBUS_RUN_VLLM_PREFIX_PROBE:-0}"
echo "[statebus-v2-local-api-supplement] vLLM metrics URL: ${STATEBUS_VLLM_METRICS_URL:-http://127.0.0.1:8000/metrics}"
echo "[statebus-v2-local-api-supplement] vLLM base URL: ${STATEBUS_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
echo "[statebus-v2-local-api-supplement] vLLM model: ${STATEBUS_VLLM_MODEL:-qwen3-32b}"
echo "[statebus-v2-local-api-supplement] no timeouts: ${STATEBUS_LOCAL_API_NO_TIMEOUTS:-1}"
echo "[statebus-v2-local-api-supplement] activation script: ${STATEBUS_ACTUAL_ACTIVATION_SCRIPT}"
echo "[statebus-v2-local-api-supplement] activation status: ${STATEBUS_ACTIVATION_STATUS}"

record_stage() {
  local stage="$1"
  local exit_code="$2"
  local required="$3"
  local kind="$4"
  local artifact="$5"
  local log_path="$6"
  local duration_s="$7"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$stage" "$exit_code" "$required" "$kind" "$artifact" "$log_path" "$duration_s" >> "$STATUS_TSV"
  if [[ "$required" == "1" && "$exit_code" -ne 0 ]]; then
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

short_socket_path() {
  local label="$1"
  local digest
  digest="$(
    /usr/bin/python3 - "$STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID:$label" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  local socket_path="/tmp/sb2sup-${digest}.sock"
  if [[ "${#socket_path}" -gt 100 ]]; then
    echo "[statebus-v2-local-api-supplement] internal error: socket path too long: ${socket_path}" >&2
    return 2
  fi
  printf '%s' "$socket_path"
}

is_unlimited_timeout() {
  local timeout_s="${1:-}"
  case "${timeout_s,,}" in
    ""|"0"|"none"|"unlimited")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_json_stage() {
  local stage="$1"
  local timeout_s="$2"
  local required="$3"
  shift 3
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  local start_s end_s duration_s exit_code
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-supplement] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-supplement] timeout=${timeout_s}s"
  fi
  start_s="$(date +%s)"
  set +e
  if is_unlimited_timeout "$timeout_s"; then
    "$@" > >(tee "$stdout_json") 2> >(tee "$log_path" >&2)
  else
    timeout "$timeout_s" "$@" > >(tee "$stdout_json") 2> >(tee "$log_path" >&2)
  fi
  exit_code=$?
  set -u
  if [[ "$exit_code" -eq 0 ]] && ! json_valid "$stdout_json" >/dev/null 2>&1; then
    exit_code=3
  fi
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  record_stage "$stage" "$exit_code" "$required" "json" "$stdout_json" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${stdout_json} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 80 "$log_path" || true
  fi
  return 0
}

run_live_stage() {
  local stage="$1"
  local timeout_s="$2"
  local required="$3"
  local suite="$4"
  shift 4
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local work_stage_dir="$WORK_ROOT/$stage"
  local runtime_root="$work_stage_dir/runtime"
  local workspace_root="$work_stage_dir/workspaces"
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  local socket_path start_s end_s duration_s exit_code
  mkdir -p "$stage_dir" "$runtime_root" "$workspace_root"
  socket_path="$(short_socket_path "$stage")"
  rm -f "$socket_path"
  echo
  echo "=== ${stage} ==="
  echo "[statebus-v2-local-api-supplement] socket_path=${socket_path} len=${#socket_path}"
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-supplement] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-supplement] timeout=${timeout_s}s"
  fi
  start_s="$(date +%s)"
  set +e
  if is_unlimited_timeout "$timeout_s"; then
    /usr/bin/python3 -m v2.benchmark.live_runner \
      --suite "$suite" \
      --role-path-mode api \
      --embedding-mode local \
      --runtime-root "$runtime_root" \
      --workspace-root "$workspace_root" \
      --socket-path "$socket_path" \
      --suite-id "${STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID}-${stage}" \
      "$@" \
      > >(tee "$stdout_json") \
      2> >(tee "$log_path" >&2)
  else
    timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner \
      --suite "$suite" \
      --role-path-mode api \
      --embedding-mode local \
      --runtime-root "$runtime_root" \
      --workspace-root "$workspace_root" \
      --socket-path "$socket_path" \
      --suite-id "${STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID}-${stage}" \
      "$@" \
      > >(tee "$stdout_json") \
      2> >(tee "$log_path" >&2)
  fi
  exit_code=$?
  set -u
  rm -f "$socket_path" || true
  if [[ "$exit_code" -eq 0 ]] && ! json_valid "$stdout_json" >/dev/null 2>&1; then
    exit_code=3
  fi
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  record_stage "$stage" "$exit_code" "$required" "live_runner" "$stdout_json" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${stdout_json} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 100 "$log_path" || true
  fi
  return 0
}

run_codeact_acceptance() {
  local stage="s01_07_codeact_acceptance_api"
  local timeout_s="${STATEBUS_LOCAL_API_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS:-0}"
  local required=1
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local work_stage_dir="$WORK_ROOT/$stage"
  local stage_root="$work_stage_dir/codeact_acceptance"
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  local total_runs="${STATEBUS_CODEACT_ACCEPTANCE_RUNS:-5}"
  local target_success="${STATEBUS_CODEACT_ACCEPTANCE_TARGET:-3}"
  local sandbox_backend="${STATEBUS_CODEACT_ACCEPTANCE_SANDBOX_BACKEND:-bwrap}"
  local start_s end_s duration_s exit_code
  mkdir -p "$stage_dir" "$stage_root"
  : > "$log_path"
  echo
  echo "=== ${stage} ==="
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-supplement] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-supplement] timeout=${timeout_s}s"
  fi
  echo "[statebus-v2-local-api-supplement] runs=${total_runs} target=${target_success} sandbox_backend=${sandbox_backend}"
  start_s="$(date +%s)"
  set +e
  if is_unlimited_timeout "$timeout_s"; then
    _run_codeact_acceptance_body "$stage_root" "$total_runs" "$target_success" "$sandbox_backend" "$stdout_json" "$log_path"
  else
    export -f _run_codeact_acceptance_body
    timeout "$timeout_s" bash -c '_run_codeact_acceptance_body "$@"' bash "$stage_root" "$total_runs" "$target_success" "$sandbox_backend" "$stdout_json" "$log_path"
  fi
  exit_code=$?
  set -u
  if [[ "$exit_code" -eq 0 ]] && ! json_valid "$stdout_json" >/dev/null 2>&1; then
    exit_code=3
  fi
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  record_stage "$stage" "$exit_code" "$required" "codeact" "$stdout_json" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${stdout_json} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 100 "$log_path" || true
  fi
  return 0
}

_run_codeact_acceptance_body() {
  local stage_root="$1"
  local total_runs="$2"
  local target_success="$3"
  local sandbox_backend="$4"
  local stdout_json="$5"
  local log_path="$6"
  local success_count=0
  local run_index
  for run_index in $(seq 1 "$total_runs"); do
    local run_root="$stage_root/run-${run_index}"
    local run_log="$stage_root/run-${run_index}.log"
    mkdir -p "$run_root"
    echo "--- codeact run ${run_index}/${total_runs} ---" | tee -a "$log_path"
    /usr/bin/python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
      --role-path-mode api \
      --sandbox-backend "$sandbox_backend" \
      --max-repair-attempts "${STATEBUS_CODEACT_MAX_REPAIR_ATTEMPTS:-3}" \
      --output-root "$run_root" \
      2>&1 | tee "$run_log"
    local run_exit=${PIPESTATUS[0]}
    local summary_file
    summary_file="$(find "$run_root" -name summary.json -type f | sort | tail -n 1)"
    if [[ "$run_exit" -eq 0 && -n "$summary_file" ]]; then
      local validator_output
      validator_output="$(/usr/bin/python3 - "$summary_file" "$sandbox_backend" <<'PY'
import json
import sys

summary_path, requested_backend = sys.argv[1], sys.argv[2]
payload = json.load(open(summary_path, "r", encoding="utf-8"))
actual_backend = str(payload.get("sandbox_backend", ""))
if requested_backend == "auto":
    sandbox_ok = actual_backend in {"bwrap", "resource"}
else:
    sandbox_ok = actual_backend == requested_backend
ok = bool(payload.get("ok", False))
fallback = bool(payload.get("generation_fallback_used", True))
ast_ok = bool(payload.get("ast_policy_pass", False))
result = {
    "summary_json": summary_path,
    "ok": ok,
    "generation_fallback_used": fallback,
    "ast_policy_pass": ast_ok,
    "sandbox_requested_backend": payload.get("sandbox_requested_backend"),
    "sandbox_backend": actual_backend,
    "sandbox_fallback_reason": payload.get("sandbox_fallback_reason"),
    "generation_attempt_count": payload.get("generation_attempt_count"),
    "generation_repair_attempt_count": payload.get("generation_repair_attempt_count"),
    "generated_by": payload.get("generated_by"),
    "success": bool(ok and not fallback and ast_ok and sandbox_ok),
}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if result["success"] else 1)
PY
)"
      local validator_exit=$?
      printf '%s\n' "$validator_output" | tee -a "$log_path"
      if [[ "$validator_exit" -eq 0 ]]; then
        success_count=$((success_count + 1))
      fi
    else
      printf '{"ok":false,"success":false,"generation_fallback_used":true,"violations":["execution_failed_or_missing_summary"]}\n' | tee -a "$log_path"
    fi
  done
  /usr/bin/python3 - "$stage_root" "$total_runs" "$target_success" "$success_count" "$sandbox_backend" "$stdout_json" <<'PY'
import json
import sys
from pathlib import Path

stage_root = Path(sys.argv[1])
total_runs = int(sys.argv[2])
target_success = int(sys.argv[3])
success_count = int(sys.argv[4])
sandbox_backend = sys.argv[5]
output_path = Path(sys.argv[6])
runs = []
for run_dir in sorted(path for path in stage_root.glob("run-*") if path.is_dir()):
    summaries = sorted(run_dir.glob("**/summary.json"))
    if not summaries:
        runs.append(
            {
                "run": run_dir.name,
                "ok": False,
                "success": False,
                "generation_fallback_used": True,
                "summary_json": "",
                "violations": ["missing_summary_json"],
            }
        )
        continue
    payload = json.loads(summaries[-1].read_text(encoding="utf-8"))
    actual_backend = str(payload.get("sandbox_backend", ""))
    sandbox_ok = actual_backend in {"bwrap", "resource"} if sandbox_backend == "auto" else actual_backend == sandbox_backend
    success = bool(
        payload.get("ok", False)
        and not bool(payload.get("generation_fallback_used", True))
        and bool(payload.get("ast_policy_pass", False))
        and sandbox_ok
    )
    runs.append(
        {
            "run": run_dir.name,
            "ok": bool(payload.get("ok", False)),
            "success": success,
            "generated_by": payload.get("generated_by"),
            "generation_fallback_used": bool(payload.get("generation_fallback_used", True)),
            "generation_attempt_count": payload.get("generation_attempt_count"),
            "generation_repair_attempt_count": payload.get("generation_repair_attempt_count"),
            "ast_policy_pass": bool(payload.get("ast_policy_pass", False)),
            "sandbox_requested_backend": payload.get("sandbox_requested_backend"),
            "sandbox_backend": actual_backend,
            "sandbox_fallback_reason": payload.get("sandbox_fallback_reason"),
            "summary_json": str(summaries[-1]),
            "claim_boundary": payload.get("claim_boundary"),
        }
    )
result = {
    "schema_version": "statebus.local_api_codeact_acceptance_supplement.v1",
    "role_path_mode": "api",
    "sandbox_backend_required": sandbox_backend,
    "total_runs": total_runs,
    "success_count": success_count,
    "target_success_count": target_success,
    "target_met": success_count >= target_success,
    "claim_boundary": "bounded CodeAct demo only; not a general-purpose CodeAct benchmark superiority claim",
    "runs": runs,
}
output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  if [[ "$success_count" -ge "$target_success" ]]; then
    return 0
  fi
  return 1
}

run_json_stage "s01_00_base_run_snapshot" 0 1 /usr/bin/python3 - "$BASE_RESULT_ROOT" <<'PY'
import csv
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
status_path = base / "artifacts" / "status.tsv"
summary_path = base / "artifacts" / "summary.json"
rows = []
if status_path.exists():
    rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))
summary = {}
if summary_path.exists():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
passed = [row["stage"] for row in rows if row.get("exit_code") == "0"]
failed = [row["stage"] for row in rows if row.get("exit_code") != "0"]
payload = {
    "schema_version": "statebus.local_api_base_snapshot.v1",
    "base_result_root": str(base),
    "base_status_exists": status_path.exists(),
    "base_summary_exists": summary_path.exists(),
    "stage_count": len(rows),
    "passed_stage_count": len(passed),
    "failed_stage_count": len(failed),
    "failed_required_stage_count": summary.get("failed_required_stage_count"),
    "passed_stages": passed,
    "failed_stages": failed,
    "not_rerun_in_supplement": [
        "01_py_compile",
        "02_pytest_full_v2",
        "03_runtime_smoke",
        "r01_04_preflight_api_local",
        "r01_05_formal_api_local_memfd",
        "r01_06_formal_carrier_compare_api_local_memfd",
        "r01_07_formal_compare_api_local_memfd",
        "r01_08_dev_compare_api_local_memfd",
        "r01_09_carrier_compare_api_local_memfd",
        "r01_10_continuous_api_local",
        "r01_11_continuous_replay_api_local",
        "r01_12_replay_negative_api_local",
    ],
    "new_live_surfaces_in_supplement": [
        "s01_08_kv_prefix_demo_api_local"
    ],
    "rerun_reason": "supplement only missing CodeAct acceptance, newly added explicit KV prefix demo, and failed flagship ablation",
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if status_path.exists() and summary_path.exists() else 1)
PY

run_json_stage "s01_00b_base_artifact_integrity_audit" 0 1 /usr/bin/python3 - "$BASE_RESULT_ROOT" <<'PY'
import csv
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
artifact_root = base / "artifacts"
status_path = artifact_root / "status.tsv"
summary_path = artifact_root / "summary.json"
expected_required_stages = {
    "00_env_probe",
    "01_py_compile",
    "02_pytest_full_v2",
    "03_runtime_smoke",
    "r01_04_preflight_api_local",
    "r01_05_formal_api_local_memfd",
    "r01_06_formal_carrier_compare_api_local_memfd",
    "r01_07_formal_compare_api_local_memfd",
    "r01_12_replay_negative_api_local",
}
allowed_optional_failures = {"r01_13_flagship_ablation_api_local"}
checks: dict[str, bool] = {}
issues: list[str] = []
rows: list[dict[str, str]] = []
summary: dict[str, object] = {}

if status_path.exists():
    rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))
else:
    issues.append("missing_status_tsv")
if summary_path.exists():
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
else:
    issues.append("missing_summary_json")

stage_names = {row.get("stage", "") for row in rows}
missing_required_stage_rows = sorted(expected_required_stages - stage_names)
failed_required_rows = [
    row.get("stage", "")
    for row in rows
    if row.get("required") == "1" and row.get("exit_code") != "0"
]
failed_optional_rows = [
    row.get("stage", "")
    for row in rows
    if row.get("required") != "1" and row.get("exit_code") != "0"
]
unexpected_optional_failures = sorted(set(failed_optional_rows) - allowed_optional_failures)
json_parse_failures: list[dict[str, str]] = []
json_artifact_count = 0
for row in rows:
    artifact = row.get("artifact", "")
    if not artifact.endswith(".json"):
        continue
    artifact_path = Path(artifact)
    if not artifact_path.exists():
        json_parse_failures.append({"stage": row.get("stage", ""), "artifact": artifact, "error": "missing"})
        continue
    if row.get("exit_code") != "0":
        continue
    json_artifact_count += 1
    try:
        json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        json_parse_failures.append(
            {"stage": row.get("stage", ""), "artifact": artifact, "error": f"{type(exc).__name__}: {exc}"}
        )

checks["status_and_summary_exist"] = status_path.exists() and summary_path.exists()
checks["expected_required_stages_present"] = not missing_required_stage_rows
checks["no_failed_required_rows"] = not failed_required_rows
checks["summary_failed_required_zero"] = int(summary.get("failed_required_stage_count", -1)) == 0
checks["optional_failures_are_known"] = not unexpected_optional_failures
checks["successful_json_artifacts_parse"] = not json_parse_failures
checks["has_successful_json_artifacts"] = json_artifact_count >= 8
ok = all(checks.values())

payload = {
    "schema_version": "statebus.local_api_base_artifact_integrity_audit.v1",
    "ok": ok,
    "base_result_root": str(base),
    "stage_count": len(rows),
    "json_artifact_count": json_artifact_count,
    "checks": checks,
    "issues": issues,
    "missing_required_stage_rows": missing_required_stage_rows,
    "failed_required_rows": failed_required_rows,
    "failed_optional_rows": failed_optional_rows,
    "allowed_optional_failures": sorted(allowed_optional_failures),
    "unexpected_optional_failures": unexpected_optional_failures,
    "json_parse_failures": json_parse_failures,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if ok else 1)
PY

run_json_stage "s01_00c_base_claim_boundary_audit" 0 1 /usr/bin/python3 - "$BASE_RESULT_ROOT" <<'PY'
import json
import math
import sys
from pathlib import Path

base = Path(sys.argv[1])
stage_root = base / "artifacts" / "stages"
summary_path = base / "artifacts" / "summary.json"
base_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
summary_key_metrics = base_summary.get("key_metrics", {}) if isinstance(base_summary, dict) else {}


def load_stage(stage: str) -> dict[str, object]:
    path = stage_root / stage / "stdout.json"
    return json.loads(path.read_text(encoding="utf-8"))


def number(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result


def field(payload: dict[str, object], key: str, default: object = None) -> object:
    for candidate in (
        payload,
        payload.get("collection_summary"),
        payload.get("metadata"),
        payload.get("aggregated_metrics"),
        payload.get("waterfall_metrics"),
    ):
        if isinstance(candidate, dict) and key in candidate:
            return candidate[key]
    return default


def flag_true(value: object) -> bool:
    return value is True or value == 1 or value == 1.0 or str(value).strip().lower() == "true"


def flag_false(value: object) -> bool:
    return value is False or value == 0 or value == 0.0 or str(value).strip().lower() == "false"


checks: dict[str, bool] = {}
issues: list[str] = []
required_stage_payloads = {
    "formal": "r01_05_formal_api_local_memfd",
    "carrier": "r01_06_formal_carrier_compare_api_local_memfd",
    "external": "r01_07_formal_compare_api_local_memfd",
    "continuous": "r01_10_continuous_api_local",
    "continuous_replay": "r01_11_continuous_replay_api_local",
    "replay_negative": "r01_12_replay_negative_api_local",
}
payloads: dict[str, dict[str, object]] = {}
for label, stage in required_stage_payloads.items():
    try:
        payloads[label] = load_stage(stage)
    except Exception as exc:
        issues.append(f"missing_or_invalid_stage:{stage}:{type(exc).__name__}:{exc}")
        payloads[label] = {}

formal = payloads["formal"]
carrier = payloads["carrier"]
external = payloads["external"]
external_summary_metrics = (
    summary_key_metrics.get("r01_07_formal_compare_api_local_memfd", {})
    if isinstance(summary_key_metrics, dict)
    else {}
)
if not isinstance(external_summary_metrics, dict):
    external_summary_metrics = {}
continuous = payloads["continuous"]
continuous_replay = payloads["continuous_replay"]
replay_negative = payloads["replay_negative"]

token_split_fields = {
    "api_statebus_prompt_tokens",
    "api_external_prompt_tokens",
    "api_prompt_tokens_delta",
    "api_statebus_completion_tokens",
    "api_external_completion_tokens",
    "api_completion_tokens_delta",
    "api_statebus_llm_total_tokens",
    "api_external_llm_total_tokens",
    "api_llm_total_tokens_delta",
}

checks["formal_registry_25_cases"] = int(number(field(formal, "L3_case_count"))) == 25
checks["formal_registry_5_families"] = int(number(field(formal, "family_count"))) == 5
checks["formal_registry_quality_25_pass"] = int(number(field(formal, "L3_quality_pass_count"))) == 25
checks["formal_memfd_used"] = field(formal, "state_pool_mode_used") == "memfd"
checks["formal_memfd_transfer_nonzero"] = number(field(formal, "memfd_transfer_count")) >= 25

checks["carrier_full_registry_coverage"] = flag_true(field(carrier, "formal_compare_full_registry_coverage"))
checks["carrier_25_cases_5_families"] = (
    int(number(field(carrier, "formal_compare_case_count"))) == 25
    and int(number(field(carrier, "formal_compare_family_count"))) == 5
)

checks["external_full_registry_coverage"] = flag_true(field(external, "formal_compare_full_registry_coverage"))
checks["external_25_cases_5_families"] = (
    int(number(field(external, "formal_compare_case_count"))) == 25
    and int(number(field(external, "formal_compare_family_count"))) == 5
)
checks["external_fairness_gate_coverage"] = flag_true(
    field(external, "external_fairness_gate_coverage", external_summary_metrics.get("external_fairness_gate_coverage"))
)
checks["external_no_fairness_gate_failures"] = flag_true(
    field(external, "no_external_fairness_gate_failures", external_summary_metrics.get("no_external_fairness_gate_failures"))
)
checks["external_token_split_schema_present"] = (
    field(external, "comparator_token_split_schema") == "statebus.comparator.token_split.v1"
)
checks["external_token_split_fields_numeric"] = all(
    not math.isnan(number(field(external, token_field)))
    for token_field in token_split_fields
)
checks["serialized_timing_contract_present"] = (
    field(external, "timing_execution_contract") == "serialized_statebus_then_external_within_each_mode_v1"
)
checks["latency_superiority_not_claimed"] = (
    flag_false(field(external, "serialized_latency_superiority_claim_allowed"))
    and flag_false(field(external, "formal_efficiency_superiority_claim_allowed"))
    and flag_false(field(external, "formal_efficiency_claim_allowed"))
)
checks["quality_superiority_only_claim_scope"] = (
    field(external, "formal_external_claim_kind") == "quality_superiority"
    and flag_true(field(external, "formal_quality_superiority_claim_allowed"))
)

checks["continuous_3_families_30_rounds"] = (
    int(number(field(continuous, "family_count"))) == 3
    and int(number(field(continuous, "continuous_round_count"))) == 30
)
checks["continuous_semantic_transfer_and_reuse_nonzero"] = (
    number(field(continuous, "L2_semantic_state_transfer_count")) > 0
    and number(field(continuous, "L3_reuse_gain")) > 0
)
checks["continuous_replay_3_families_30_rounds"] = (
    int(number(field(continuous_replay, "family_count"))) == 3
    and int(number(field(continuous_replay, "continuous_round_count"))) == 30
)
checks["continuous_replay_validated_reuse_nonzero"] = (
    number(field(continuous_replay, "validated_replay_count")) > 0
    and number(field(continuous_replay, "validated_downgraded_reuse_count")) > 0
    and number(field(continuous_replay, "L3_reuse_gain")) > 0
)
checks["replay_negative_audit_pass"] = flag_true(field(replay_negative, "audit_pass"))

ok = all(checks.values()) and not issues
payload = {
    "schema_version": "statebus.local_api_base_claim_boundary_audit.v1",
    "ok": ok,
    "base_result_root": str(base),
    "checks": checks,
    "issues": issues,
    "token_split_fields": sorted(token_split_fields),
    "claim_readout": {
        "formal_registry_case_count": field(formal, "L3_case_count"),
        "formal_registry_family_count": field(formal, "family_count"),
        "external_claim_kind": field(external, "formal_external_claim_kind"),
        "quality_superiority_claim_allowed": field(external, "formal_quality_superiority_claim_allowed"),
        "efficiency_superiority_claim_allowed": field(external, "formal_efficiency_superiority_claim_allowed"),
        "serialized_latency_superiority_claim_allowed": field(external, "serialized_latency_superiority_claim_allowed"),
        "api_prompt_tokens_delta": field(external, "api_prompt_tokens_delta"),
        "api_completion_tokens_delta": field(external, "api_completion_tokens_delta"),
        "api_llm_total_tokens_delta": field(external, "api_llm_total_tokens_delta"),
        "continuous_reuse_gain": field(continuous, "L3_reuse_gain"),
        "continuous_replay_validated_replay_count": field(continuous_replay, "validated_replay_count"),
    },
    "claim_boundary": (
        "formal quality superiority and token reduction evidence can be read from the base run; "
        "latency/efficiency superiority remains unclaimed unless a serialized latency gate allows it"
    ),
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if ok else 1)
PY

run_json_stage "s01_01_container_root_gpu_probe" "$STATEBUS_LOCAL_API_HEALTH_PROBE_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
import json
import os
import shutil
import subprocess
import sys


def run_command(command: list[str], timeout_s: int = 10) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except Exception as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


torch_payload: dict[str, object] = {
    "present": False,
    "cuda_available": False,
    "cuda_device_count": 0,
}
try:
    import torch

    torch_payload = {
        "present": True,
        "version": getattr(torch, "__version__", ""),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()),
        "visible_device_0_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() and torch.cuda.device_count() else "",
        "memory_allocated_device_0": int(torch.cuda.memory_allocated(0)) if torch.cuda.is_available() and torch.cuda.device_count() else 0,
        "memory_reserved_device_0": int(torch.cuda.memory_reserved(0)) if torch.cuda.is_available() and torch.cuda.device_count() else 0,
    }
except Exception as exc:
    torch_payload["error"] = f"{type(exc).__name__}: {exc}"

nvidia_smi = run_command(
    [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
) if shutil.which("nvidia-smi") else {"returncode": -1, "stdout": "", "stderr": "nvidia-smi not found"}

payload = {
    "schema_version": "statebus.local_api_container_root_gpu_probe.v1",
    "ok": os.geteuid() == 0 and bool(torch_payload.get("cuda_available")),
    "effective_uid": os.geteuid(),
    "effective_gid": os.getegid(),
    "python_executable": sys.executable,
    "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
    "torch": torch_payload,
    "nvidia_smi": nvidia_smi,
    "root_required": True,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

run_json_stage "s01_02_py_compile_health" "$STATEBUS_LOCAL_API_PY_COMPILE_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
import json
import py_compile
from pathlib import Path

paths = [
    "scripts/inspect_vllm_kv_budget.py",
    "scripts/run_v2_local_api_comprehensive_stats.sh",
    "scripts/v2_diagnostics/bounded_llm_codeact_demo.py",
    "scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py",
    "v2/benchmark/continuous_runner.py",
    "v2/benchmark/flagship_ablation.py",
    "v2/benchmark/kv_analysis.py",
    "v2/benchmark/kv_prefix_experiment.py",
    "v2/benchmark/live_runner.py",
    "v2/retrieval/models.py",
    "v2/retrieval/pipeline.py",
    "v2/runtime/__init__.py",
    "v2/runtime/codeact.py",
    "v2/runtime/codeact_data_tasks.py",
    "v2/runtime/kv_budget.py",
    "v2/runtime/neural_state.py",
    "v2/runtime/role_path.py",
    "v2/runtime/smoke.py",
    "v2/runtime/vllm_metrics.py",
]
compiled = []
failures = []
for raw_path in paths:
    path = Path(raw_path)
    if not path.exists():
        failures.append({"path": raw_path, "error": "missing"})
        continue
    if path.suffix == ".py":
        try:
            py_compile.compile(str(path), doraise=True)
            compiled.append(raw_path)
        except Exception as exc:
            failures.append({"path": raw_path, "error": f"{type(exc).__name__}: {exc}"})
    else:
        compiled.append(raw_path)
payload = {
    "schema_version": "statebus.local_api_py_compile_health.v1",
    "ok": not failures,
    "compiled_or_checked_count": len(compiled),
    "compiled_or_checked": compiled,
    "failures": failures,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

run_json_stage "s01_03_targeted_pytest_health" "$STATEBUS_LOCAL_API_HEALTH_PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 - "$WORK_ROOT/s01_03_targeted_pytest_health" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
out_dir.mkdir(parents=True, exist_ok=True)
cmd = [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "tests/v2/test_bounded_llm_codeact_demo.py",
    "tests/v2/test_flagship_ablation.py",
    "tests/v2/test_runtime_and_benchmark.py::test_codeact_runner_reuses_cached_result_for_identical_request",
    "tests/v2/test_continuous_task_family_loader.py",
    "tests/v2/test_continuous_runner.py::test_continuous_runner_executes_replay_family",
    "tests/v2/test_continuous_runner.py::test_continuous_text_semantic_selection_diagnostic_does_not_transfer_state_ref",
    "tests/v2/test_retrieval_pipeline.py",
    "tests/v2/test_preflight_and_live_runner.py",
]
completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
(out_dir / "pytest.stdout.txt").write_text(completed.stdout, encoding="utf-8")
(out_dir / "pytest.stderr.txt").write_text(completed.stderr, encoding="utf-8")
combined = completed.stdout + "\n" + completed.stderr
passed_match = re.search(r"(\d+) passed", combined)
failed_match = re.search(r"(\d+) failed", combined)
payload = {
    "schema_version": "statebus.local_api_targeted_pytest_health.v1",
    "ok": completed.returncode == 0,
    "returncode": completed.returncode,
    "command": cmd,
    "stdout_path": str(out_dir / "pytest.stdout.txt"),
    "stderr_path": str(out_dir / "pytest.stderr.txt"),
    "passed_count": int(passed_match.group(1)) if passed_match else None,
    "failed_count": int(failed_match.group(1)) if failed_match else 0,
    "tail_stdout": "\n".join(completed.stdout.splitlines()[-40:]),
    "tail_stderr": "\n".join(completed.stderr.splitlines()[-40:]),
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(completed.returncode)
PY

run_json_stage "s01_04_kv_prefix_static_health" "$STATEBUS_LOCAL_API_KV_PREFIX_HEALTH_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
import hashlib
import json
from collections import Counter
from pathlib import Path

from v2.benchmark.continuous_task_family import load_continuous_task_family
from v2.runtime.neural_state import build_corpus_prefix_hash

family_dir = Path("v2/benchmark/samples/continuous_task_families/kv_prefix_reuse")
manifest_path = family_dir / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
family = load_continuous_task_family(family_dir)
task_to_dataset = {round_.task_id: round_.dataset_id for round_ in family.rounds}
probe = manifest.get("kv_prefix_probe", {})
friendly_order = list(probe.get("cache_friendly_order", []))
hostile_order = list(probe.get("cache_hostile_order", []))


def max_same_dataset_run(order: list[str]) -> int:
    best = 0
    current_dataset = None
    current_count = 0
    for task_id in order:
        dataset_id = task_to_dataset.get(task_id)
        if dataset_id == current_dataset:
            current_count += 1
        else:
            current_dataset = dataset_id
            current_count = 1
        best = max(best, current_count)
    return best


dataset_hashes = {}
source_doc_hashes = {}
for dataset in family.datasets:
    path = Path(dataset.path)
    if not path.is_absolute():
        path = Path.cwd() / path
    text = path.read_text(encoding="utf-8")
    source_doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_doc_hashes[dataset.dataset_id] = source_doc_hash
    dataset_hashes[dataset.dataset_id] = build_corpus_prefix_hash(
        source_doc_hashes=(source_doc_hash,),
        system_prompt_version="static-contract-check",
    )

dataset_round_counts = Counter(round_.dataset_id for round_ in family.rounds)
claim_boundary = str(manifest.get("source_basis", {}).get("claim_boundary", ""))
checks = {
    "family_id": family.family_id == "kv_prefix_reuse_v1",
    "claim_tier_demo_secondary": family.claim_tier == "demo_secondary",
    "not_default_formal_chain": manifest.get("source_basis", {}).get("not_default_formal_chain") is True,
    "claim_boundary_no_kv_tensor_export": "no_kv_tensor_export" in claim_boundary,
    "round_count_10": family.round_count == 10,
    "dataset_count_2": len(family.datasets) == 2,
    "distinct_dataset_prefix_hashes": len(set(dataset_hashes.values())) == len(dataset_hashes),
    "schedule_orders_cover_all_tasks": set(friendly_order) == set(task_to_dataset) and set(hostile_order) == set(task_to_dataset),
    "friendly_has_larger_same_corpus_window": max_same_dataset_run(friendly_order) > max_same_dataset_run(hostile_order),
}
payload = {
    "schema_version": "statebus.local_api_kv_prefix_static_health.v1",
    "ok": all(checks.values()),
    "family_design_audit": family.design_audit_payload(),
    "checks": checks,
    "claim_boundary": claim_boundary,
    "dataset_round_counts": dict(sorted(dataset_round_counts.items())),
    "source_doc_hashes": source_doc_hashes,
    "dataset_prefix_hashes": dataset_hashes,
    "cache_friendly_max_same_dataset_run": max_same_dataset_run(friendly_order),
    "cache_hostile_max_same_dataset_run": max_same_dataset_run(hostile_order),
    "claim_note": "static contract only; actual vLLM prefix-cache mechanism evidence requires metrics deltas and TTFT",
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

run_json_stage "s01_05_import_probe" "$STATEBUS_LOCAL_API_IMPORT_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
import dataclasses
import json
import os
import sys

import v2.runtime as runtime_pkg
import v2.runtime.codeact as codeact
import v2.runtime.codeact_data_tasks as codeact_data_tasks
import v2.runtime.neural_state as neural_state

fields = dataclasses.fields(neural_state.NeuralPrefixReuseEstimate)
field_order = [field.name for field in fields]
first_default_index = next(
    (index for index, field in enumerate(fields) if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING),
    len(fields),
)
non_default_after_default = [
    field.name
    for field in fields[first_default_index:]
    if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
]
payload = {
    "schema_version": "statebus.local_api_import_probe.v1",
    "ok": not non_default_after_default,
    "python_executable": sys.executable,
    "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
    "runtime_file": runtime_pkg.__file__,
    "codeact_file": codeact.__file__,
    "codeact_data_tasks_file": codeact_data_tasks.__file__,
    "neural_state_file": neural_state.__file__,
    "neural_prefix_reuse_estimate_class": neural_state.NeuralPrefixReuseEstimate.__name__,
    "neural_prefix_reuse_estimate_field_order": field_order,
    "non_default_after_default": non_default_after_default,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

run_json_stage "s01_06_codeact_bwrap_smoke" "$STATEBUS_LOCAL_API_CODEACT_SMOKE_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
import json

from scripts.v2_diagnostics.check_codeact_bwrap_sandbox import (
    _run_bwrap_smoke,
    _run_codeact_bwrap_smoke,
)

bwrap_smoke = _run_bwrap_smoke()
codeact_smoke = (
    _run_codeact_bwrap_smoke()
    if bwrap_smoke.get("ok")
    else {
        "ok": False,
        "reason": "skipped_because_bwrap_smoke_failed",
    }
)
payload = {
    "schema_version": "statebus.codeact_bwrap_sandbox_check.v1",
    "ok": bool(bwrap_smoke.get("ok")) and bool(codeact_smoke.get("ok")),
    "bwrap_smoke": bwrap_smoke,
    "codeact_bwrap_smoke": codeact_smoke,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

run_codeact_acceptance

run_live_stage "s01_08_kv_prefix_demo_api_local" "$STATEBUS_LOCAL_API_KV_PREFIX_DEMO_TIMEOUT_SECONDS" 1 "continuous" \
  --family kv_prefix_reuse_v1

if [[ "${STATEBUS_RUN_VLLM_PREFIX_PROBE:-0}" == "1" ]]; then
  run_json_stage "s01_09_vllm_prefix_metrics_probe" "$STATEBUS_LOCAL_API_VLLM_PREFIX_PROBE_TIMEOUT_SECONDS" 0 /usr/bin/python3 - <<'PY'
import json
import os

from v2.runtime.vllm_metrics import fetch_vllm_prefix_cache_metrics

metrics_url = os.getenv("STATEBUS_VLLM_METRICS_URL", "http://127.0.0.1:8000/metrics")
try:
    metrics = fetch_vllm_prefix_cache_metrics(metrics_url, timeout_s=5.0)
    payload = {
        "schema_version": "statebus.local_api_vllm_prefix_metrics_probe.v1",
        "ok": bool(metrics.raw_metric_names),
        "metrics_url": metrics_url,
        "metrics": metrics.canonical_payload(),
        "claim_boundary": "metrics availability probe only; compare cache-friendly vs hostile schedules separately for mechanism claim",
    }
except Exception as exc:
    payload = {
        "schema_version": "statebus.local_api_vllm_prefix_metrics_probe.v1",
        "ok": False,
        "metrics_url": metrics_url,
        "error": f"{type(exc).__name__}: {exc}",
        "claim_boundary": "optional probe failed or service not running; no vLLM prefix-cache mechanism claim",
    }
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY
  run_json_stage "s01_09b_vllm_prefix_alignment_probe" "$STATEBUS_LOCAL_API_VLLM_PREFIX_ALIGNMENT_TIMEOUT_SECONDS" 0 /usr/bin/python3 - "$WORK_ROOT/s01_09b_vllm_prefix_alignment_probe" <<'PY'
import json
import os
import sys
from pathlib import Path

from v2.benchmark.kv_prefix_experiment import (
    build_chain_inheritance_prompts,
    build_shared_prefix_role_suffix_prompts,
    run_prefix_alignment_experiment,
)

out_dir = Path(sys.argv[1])
out_dir.mkdir(parents=True, exist_ok=True)
base_url = os.getenv("STATEBUS_VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
metrics_url = os.getenv("STATEBUS_VLLM_METRICS_URL", "http://127.0.0.1:8000/metrics")
model = os.getenv("STATEBUS_VLLM_MODEL", "qwen3-32b")
api_key = os.getenv("STATEBUS_VLLM_API_KEY", "EMPTY")
max_tokens = int(os.getenv("STATEBUS_VLLM_PREFIX_PROBE_MAX_TOKENS", "48") or "48")
doc_path = Path("v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md")
shared_prefix = (
    "StateBus engine-local prefix reuse probe.\n"
    "Keep the following operating-report evidence byte-identical across role prompts.\n\n"
    "[SHARED_EVIDENCE_BEGIN]\n"
    + doc_path.read_text(encoding="utf-8").strip()
    + "\n[SHARED_EVIDENCE_END]"
)
(out_dir / "shared_prefix.txt").write_text(shared_prefix + "\n", encoding="utf-8")
strategies = {
    "shared_prefix": build_shared_prefix_role_suffix_prompts(shared_prefix=shared_prefix),
    "chain": build_chain_inheritance_prompts(shared_prefix=shared_prefix),
}
results = {}
for strategy, prompts in strategies.items():
    result = run_prefix_alignment_experiment(
        prompts=prompts,
        base_url=base_url,
        model=model,
        api_key=api_key,
        metrics_url=metrics_url,
        max_tokens=max_tokens,
        stream=True,
    )
    result_path = out_dir / f"{strategy}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results[strategy] = result

strategy_summaries = {
    strategy: {
        "prompt_count": result.get("prompt_count"),
        "response_count": len(result.get("responses", [])),
        "wall_ms": result.get("wall_ms"),
        "metrics_delta": result.get("metrics_delta"),
        "ttft_ms": [
            response.get("ttft_ms")
            for response in result.get("responses", [])
        ],
        "metrics_raw_metric_names": result.get("metrics_after", {}).get("raw_metric_names", []),
    }
    for strategy, result in results.items()
}
metrics_available = any(
    summary.get("metrics_raw_metric_names")
    for summary in strategy_summaries.values()
)
responses_complete = all(
    int(summary.get("response_count") or 0) == int(summary.get("prompt_count") or -1)
    and int(summary.get("prompt_count") or 0) > 0
    for summary in strategy_summaries.values()
)
summary = {
    "schema_version": "statebus.local_api_vllm_prefix_alignment_probe.v1",
    "ok": bool(responses_complete and metrics_available),
    "base_url": base_url,
    "metrics_url": metrics_url,
    "model": model,
    "max_tokens": max_tokens,
    "shared_prefix_bytes": len(shared_prefix.encode("utf-8")),
    "responses_complete": responses_complete,
    "metrics_available": metrics_available,
    "result_paths": {
        strategy: str(out_dir / f"{strategy}.json")
        for strategy in strategies
    },
    "strategy_summaries": strategy_summaries,
    "claim_boundary": "optional local-vLLM mechanism probe only; requires prefix-cache metrics and TTFT deltas before any mechanism claim",
}
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if summary["ok"] else 1)
PY
else
  echo
  echo "=== s01_09_vllm_prefix_metrics_probe_skipped ==="
  skip_dir="$ARTIFACT_ROOT/stages/s01_09_vllm_prefix_metrics_probe_skipped"
  mkdir -p "$skip_dir"
  skip_json="$skip_dir/stdout.json"
  skip_log="$skip_dir/console.log"
  /usr/bin/python3 - "$skip_json" <<'PY'
import json
import sys
from pathlib import Path

payload = {
    "schema_version": "statebus.local_api_vllm_prefix_metrics_probe.v1",
    "ok": True,
    "skipped": True,
    "reason": "STATEBUS_RUN_VLLM_PREFIX_PROBE is not 1",
    "claim_boundary": "no vLLM prefix-cache mechanism claim from this skipped optional probe",
}
Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
  : > "$skip_log"
  record_stage "s01_09_vllm_prefix_metrics_probe_skipped" "0" "0" "json" "$skip_json" "$skip_log" "0"

  echo
  echo "=== s01_09b_vllm_prefix_alignment_probe_skipped ==="
  align_skip_dir="$ARTIFACT_ROOT/stages/s01_09b_vllm_prefix_alignment_probe_skipped"
  mkdir -p "$align_skip_dir"
  align_skip_json="$align_skip_dir/stdout.json"
  align_skip_log="$align_skip_dir/console.log"
  /usr/bin/python3 - "$align_skip_json" <<'PY'
import json
import sys
from pathlib import Path

payload = {
    "schema_version": "statebus.local_api_vllm_prefix_alignment_probe.v1",
    "ok": True,
    "skipped": True,
    "reason": "STATEBUS_RUN_VLLM_PREFIX_PROBE is not 1",
    "claim_boundary": "no vLLM prefix-cache mechanism claim from this skipped optional probe",
}
Path(sys.argv[1]).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
  : > "$align_skip_log"
  record_stage "s01_09b_vllm_prefix_alignment_probe_skipped" "0" "0" "json" "$align_skip_json" "$align_skip_log" "0"
fi

run_live_stage "s01_10_flagship_ablation_api_local" "$STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS" 1 "flagship-ablation" \
  --benchmark-tier dev

/usr/bin/python3 - "$STATUS_TSV" "$SUMMARY_MD" "$SUMMARY_JSON" "$BASE_RESULT_ROOT" <<'PY'
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

status_path = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
summary_json = Path(sys.argv[3])
base_root = Path(sys.argv[4])
rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))


def load_json(path_value: str) -> dict[str, Any]:
    if not path_value or path_value == "-":
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return value if isinstance(value, dict) else {"_non_object_json": True, "value": value}


payload_by_stage = {row["stage"]: load_json(row.get("artifact", "")) for row in rows}
failed = [row for row in rows if int(row.get("exit_code", "1")) != 0]
failed_required = [row for row in failed if row.get("required") == "1"]
base_snapshot = payload_by_stage.get("s01_00_base_run_snapshot", {})
base_integrity_audit = payload_by_stage.get("s01_00b_base_artifact_integrity_audit", {})
base_claim_audit = payload_by_stage.get("s01_00c_base_claim_boundary_audit", {})
container_gpu = payload_by_stage.get("s01_01_container_root_gpu_probe", {})
py_compile_health = payload_by_stage.get("s01_02_py_compile_health", {})
targeted_pytest = payload_by_stage.get("s01_03_targeted_pytest_health", {})
kv_prefix_health = payload_by_stage.get("s01_04_kv_prefix_static_health", {})
import_probe = payload_by_stage.get("s01_05_import_probe", {})
bwrap_smoke = payload_by_stage.get("s01_06_codeact_bwrap_smoke", {})
codeact_acceptance = payload_by_stage.get("s01_07_codeact_acceptance_api", {})
kv_prefix_demo = payload_by_stage.get("s01_08_kv_prefix_demo_api_local", {})
vllm_prefix_probe = (
    payload_by_stage.get("s01_09_vllm_prefix_metrics_probe")
    or payload_by_stage.get("s01_09_vllm_prefix_metrics_probe_skipped", {})
)
vllm_prefix_alignment = (
    payload_by_stage.get("s01_09b_vllm_prefix_alignment_probe")
    or payload_by_stage.get("s01_09b_vllm_prefix_alignment_probe_skipped", {})
)
flagship = payload_by_stage.get("s01_10_flagship_ablation_api_local", {})
flagship_stress = flagship.get("non_text_state_stress_summary") if isinstance(flagship.get("non_text_state_stress_summary"), dict) else {}
kv_prefix_l3 = kv_prefix_demo.get("layers", [])[-1] if isinstance(kv_prefix_demo.get("layers"), list) and kv_prefix_demo.get("layers") else {}
kv_prefix_l3_metrics = kv_prefix_l3.get("telemetry_summary", {}) if isinstance(kv_prefix_l3, dict) else {}

key_metrics = {
    "base_failed_stage_count": base_snapshot.get("failed_stage_count"),
    "base_failed_required_stage_count": base_snapshot.get("failed_required_stage_count"),
    "base_artifact_integrity_ok": base_integrity_audit.get("ok"),
    "base_claim_boundary_ok": base_claim_audit.get("ok"),
    "base_formal_registry_case_count": (base_claim_audit.get("claim_readout") or {}).get("formal_registry_case_count") if isinstance(base_claim_audit.get("claim_readout"), dict) else None,
    "base_formal_registry_family_count": (base_claim_audit.get("claim_readout") or {}).get("formal_registry_family_count") if isinstance(base_claim_audit.get("claim_readout"), dict) else None,
    "base_external_claim_kind": (base_claim_audit.get("claim_readout") or {}).get("external_claim_kind") if isinstance(base_claim_audit.get("claim_readout"), dict) else None,
    "base_serialized_latency_superiority_claim_allowed": (base_claim_audit.get("claim_readout") or {}).get("serialized_latency_superiority_claim_allowed") if isinstance(base_claim_audit.get("claim_readout"), dict) else None,
    "container_effective_uid": container_gpu.get("effective_uid"),
    "container_root_ok": container_gpu.get("effective_uid") == 0 if container_gpu else None,
    "torch_cuda_available": (container_gpu.get("torch") or {}).get("cuda_available") if isinstance(container_gpu.get("torch"), dict) else None,
    "torch_cuda_device_count": (container_gpu.get("torch") or {}).get("cuda_device_count") if isinstance(container_gpu.get("torch"), dict) else None,
    "py_compile_health_ok": py_compile_health.get("ok"),
    "py_compile_checked_count": py_compile_health.get("compiled_or_checked_count"),
    "targeted_pytest_ok": targeted_pytest.get("ok"),
    "targeted_pytest_passed_count": targeted_pytest.get("passed_count"),
    "kv_prefix_static_health_ok": kv_prefix_health.get("ok"),
    "kv_prefix_claim_boundary": kv_prefix_health.get("claim_boundary"),
    "kv_prefix_cache_friendly_max_run": kv_prefix_health.get("cache_friendly_max_same_dataset_run"),
    "kv_prefix_cache_hostile_max_run": kv_prefix_health.get("cache_hostile_max_same_dataset_run"),
    "import_probe_ok": import_probe.get("ok"),
    "codeact_bwrap_smoke_ok": bwrap_smoke.get("ok"),
    "codeact_acceptance_success_count": codeact_acceptance.get("success_count"),
    "codeact_acceptance_total_runs": codeact_acceptance.get("total_runs"),
    "codeact_acceptance_target_met": codeact_acceptance.get("target_met"),
    "kv_prefix_demo_task_family": kv_prefix_demo.get("task_family"),
    "kv_prefix_demo_L3_case_count": kv_prefix_demo.get("L3_case_count"),
    "kv_prefix_demo_L3_quality_pass_count": kv_prefix_demo.get("L3_quality_pass_count"),
    "kv_prefix_demo_L3_reuse_gain": (kv_prefix_demo.get("waterfall_metrics") or {}).get("L3_reuse_gain") if isinstance(kv_prefix_demo.get("waterfall_metrics"), dict) else None,
    "kv_prefix_demo_corpus_prefix_reuse_count": (kv_prefix_demo.get("waterfall_metrics") or {}).get("L3_kv_corpus_prefix_hash_reuse_count") if isinstance(kv_prefix_demo.get("waterfall_metrics"), dict) else None,
    "kv_prefix_demo_corpus_prefill_saved_tokens_estimate": (kv_prefix_demo.get("waterfall_metrics") or {}).get("L3_kv_corpus_level_prefill_saved_tokens_estimate") if isinstance(kv_prefix_demo.get("waterfall_metrics"), dict) else None,
    "kv_prefix_demo_engine_local_prefill_saved_tokens_estimate": (kv_prefix_demo.get("waterfall_metrics") or {}).get("L3_kv_engine_local_prefill_saved_tokens_estimate") if isinstance(kv_prefix_demo.get("waterfall_metrics"), dict) else None,
    "kv_prefix_demo_semantic_state_transfer_count": kv_prefix_l3_metrics.get("semantic_state_transfer_count") if isinstance(kv_prefix_l3_metrics, dict) else None,
    "vllm_prefix_probe_ok": vllm_prefix_probe.get("ok"),
    "vllm_prefix_probe_skipped": vllm_prefix_probe.get("skipped"),
    "vllm_prefix_alignment_ok": vllm_prefix_alignment.get("ok"),
    "vllm_prefix_alignment_skipped": vllm_prefix_alignment.get("skipped"),
    "flagship_stress_family_count": flagship_stress.get("stress_family_count"),
    "flagship_stress_pass_family_count": flagship_stress.get("stress_pass_family_count"),
    "flagship_stress_fail_family_count": flagship_stress.get("stress_fail_family_count"),
    "flagship_diagnostic_only_family_count": flagship_stress.get("diagnostic_only_family_count"),
    "flagship_total_prompt_visible_saved_by_state_ref_bytes": flagship_stress.get("total_prompt_visible_saved_by_state_ref_bytes"),
    "flagship_total_llm_prompt_saved_by_state_ref_bytes": flagship_stress.get("total_llm_prompt_saved_by_state_ref_bytes"),
}
key_metrics = {key: value for key, value in key_metrics.items() if value is not None}

summary = {
    "schema_version": "statebus.local_api_supplement_summary.v1",
    "run_id": os.getenv("STATEBUS_LOCAL_API_SUPPLEMENT_RUN_ID", ""),
    "base_run_id": os.getenv("STATEBUS_LOCAL_API_BASE_RUN_ID", ""),
    "base_result_root": str(base_root),
    "result_root": os.getenv("STATEBUS_RESULT_ROOT", ""),
    "stage_count": len(rows),
    "failed_stage_count": len(failed),
    "failed_required_stage_count": len(failed_required),
    "stages": rows,
    "failed_stages": [row["stage"] for row in failed],
    "failed_required_stages": [row["stage"] for row in failed_required],
    "base_snapshot": base_snapshot,
    "base_artifact_integrity_audit": base_integrity_audit,
    "base_claim_boundary_audit": base_claim_audit,
    "container_root_gpu_probe": container_gpu,
    "py_compile_health": py_compile_health,
    "targeted_pytest_health": targeted_pytest,
    "kv_prefix_static_health": kv_prefix_health,
    "import_probe": import_probe,
    "codeact_bwrap_smoke": bwrap_smoke,
    "codeact_acceptance": codeact_acceptance,
    "kv_prefix_demo": kv_prefix_demo,
    "vllm_prefix_probe": vllm_prefix_probe,
    "vllm_prefix_alignment": vllm_prefix_alignment,
    "flagship_stress_summary": flagship_stress,
    "key_metrics": key_metrics,
    "claim_boundaries": [
        "This supplement does not supersede the base local+api comprehensive run; read evidence as base plus supplement.",
        "Formal 25-case / 5-family benchmark, formal carrier compare, formal external compare, continuous, continuous replay, and replay-negative audit are inherited from the base run and are not rerun here.",
        "Base artifact integrity and claim-boundary audits are machine checks over inherited evidence; they do not create new benchmark evidence.",
        "Container execution uses docker exec -u 0; container root and GPU visibility are checked in the health probe.",
        "Targeted pytest is a risk-surface health check over CodeAct, flagship summary, continuous replay, retrieval, and live-runner plumbing; it does not replace the base full pytest run.",
        "CodeAct evidence is bounded CodeAct acceptance only, not a general-purpose CodeAct benchmark superiority claim.",
        "KV prefix demo is an explicit demo_secondary family run; it is not part of the inherited formal 25-case / 5-family registry.",
        "KV/prefix/neural-state fields remain Engine-Local Prefix Reuse/control-plane scheduling evidence unless separately validated as actual engine KV cache reuse.",
        "KV prefix static health validates task-family and scheduling contracts only; actual vLLM prefix-cache mechanism evidence requires metrics deltas and TTFT.",
        "Optional vLLM prefix alignment probe is skipped unless STATEBUS_RUN_VLLM_PREFIX_PROBE=1 and a local vLLM OpenAI-compatible service is reachable.",
        "Latency superiority remains unclaimed unless serialized latency gate explicitly allows it.",
    ],
}
summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

lines = [
    "# StateBus v2 local+api supplement statistics",
    "",
    f"- Base run: `{summary['base_run_id']}`",
    f"- Supplement run: `{summary['run_id']}`",
    f"- Stage count: `{summary['stage_count']}`",
    f"- Failed stage count: `{summary['failed_stage_count']}`",
    f"- Failed required stage count: `{summary['failed_required_stage_count']}`",
    f"- CUDA_VISIBLE_DEVICES: `{os.getenv('CUDA_VISIBLE_DEVICES', '')}`",
    f"- STATEBUS_EMBED_DEVICE: `{os.getenv('STATEBUS_EMBED_DEVICE', '')}`",
    "",
    "## Scope",
    "",
    "- Incremental health check over current risky surfaces: container root/GPU, py_compile, targeted pytest, KV prefix static contract, import gate, CodeAct smoke/acceptance, explicit KV prefix demo, optional vLLM metrics/alignment probes, flagship ablation.",
    "- Do not rerun already passed base stages: formal 25/5, carrier compare, external compare, continuous, continuous replay, replay-negative audit.",
    "",
    "## Key Metrics",
    "",
]
if key_metrics:
    for key, value in key_metrics.items():
        lines.append(f"- `{key}`: `{value}`")
else:
    lines.append("- none")
lines.extend(["", "## Failed Required Stages", ""])
if failed_required:
    for row in failed_required:
        lines.append(f"- `{row['stage']}` exit `{row['exit_code']}`")
else:
    lines.append("- none")
lines.extend(["", "## Stage Log", ""])
for row in rows:
    lines.append(
        f"- `{row['stage']}` exit `{row['exit_code']}` required `{row['required']}` duration `{row['duration_s']}s` artifact `{row['artifact']}`"
    )
lines.extend(["", "## Claim Boundaries", ""])
for boundary in summary["claim_boundaries"]:
    lines.append(f"- {boundary}")
summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

if [[ "$OVERALL_FAILURE" -ne 0 ]]; then
  echo "[statebus-v2-local-api-supplement] required supplement stage failed"
fi

if [[ "${STATEBUS_LOCAL_API_SUPPLEMENT_STRICT_EXIT:-1}" == "1" ]]; then
  exit "$OVERALL_FAILURE"
fi
exit 0
