#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
STAMP="${STATEBUS_LOCAL_API_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_API_RUN_ID:-v2-local-api-${STAMP}}"
HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
CONTAINER_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID}"
AUDIT_ARTIFACT_ROOT="${STATEBUS_LOCAL_API_AUDIT_ARTIFACT_ROOT:-${HOST_PROJECT_ROOT}/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_${STAMP}}"

TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-0}}"
TARGET_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
TARGET_CODEACT_SANDBOX_BACKEND="${STATEBUS_CODEACT_SANDBOX_BACKEND:-auto}"

PYTEST_MODE="${STATEBUS_LOCAL_API_PYTEST_MODE:-focused}" # focused | full | skip
RUN_FLAGSHIP="${STATEBUS_LOCAL_API_RUN_FLAGSHIP:-0}"
REPEAT_COUNT="${STATEBUS_LOCAL_API_REPEAT:-1}"
STRICT_EXIT="${STATEBUS_LOCAL_API_STRICT_EXIT:-1}"

PYTEST_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_PYTEST_TIMEOUT_SECONDS:-${PYTEST_TIMEOUT_SECONDS:-1800}}"
SMOKE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_SMOKE_TIMEOUT_SECONDS:-${SMOKE_TIMEOUT_SECONDS:-900}}"
PREFLIGHT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_PREFLIGHT_TIMEOUT_SECONDS:-${PREFLIGHT_TIMEOUT_SECONDS:-600}}"
FORMAL_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS:-${FORMAL_TIMEOUT_SECONDS:-1800}}"
COMPARE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS:-${COMPARE_TIMEOUT_SECONDS:-1800}}"
CONTINUOUS_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS:-${CONTINUOUS_TIMEOUT_SECONDS:-2400}}"
REPLAY_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS:-${REPLAY_TIMEOUT_SECONDS:-2400}}"
REPLAY_NEGATIVE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_REPLAY_NEGATIVE_TIMEOUT_SECONDS:-${REPLAY_NEGATIVE_TIMEOUT_SECONDS:-900}}"
FLAGSHIP_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS:-${FLAGSHIP_TIMEOUT_SECONDS:-7200}}"

if [[ "${STATEBUS_LOCAL_API_IN_CONTAINER:-0}" != "1" ]]; then
  mkdir -p "$HOST_RESULT_ROOT" "$AUDIT_ARTIFACT_ROOT"
  cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api comprehensive statistics run

Host project root:
  ${HOST_PROJECT_ROOT}

Container:
  ${CONTAINER_NAME}

Container project root:
  ${CONTAINER_PROJECT_ROOT}

Host result root:
  ${HOST_RESULT_ROOT}

Container result root:
  ${CONTAINER_RESULT_ROOT}

Audit artifact copy:
  ${AUDIT_ARTIFACT_ROOT}

Mode contract:
  - role_path_mode=api
  - embedding_mode=local
  - state_pool_mode=memfd for formal/compare/carrier stages
  - every stage uses its own runtime_root and workspace_root
  - AF_UNIX sockets use short /tmp/sb2-<hash>.sock paths
  - no deterministic fallback is used for claim evidence
EOF

  if [[ "${STATEBUS_LOCAL_API_DRY_RUN:-0}" == "1" ]]; then
    echo "[statebus-v2-local-api] dry run"
    echo "run_id=${RUN_ID}"
    echo "host_result_root=${HOST_RESULT_ROOT}"
    echo "audit_artifact_root=${AUDIT_ARTIFACT_ROOT}"
    echo "container=${CONTAINER_NAME}"
    echo "repeat_count=${REPEAT_COUNT}"
    echo "pytest_mode=${PYTEST_MODE}"
    echo "run_flagship=${RUN_FLAGSHIP}"
    echo "formal_timeout_seconds=${FORMAL_TIMEOUT_SECONDS}"
    echo "compare_timeout_seconds=${COMPARE_TIMEOUT_SECONDS}"
    echo "continuous_timeout_seconds=${CONTINUOUS_TIMEOUT_SECONDS}"
    echo "replay_timeout_seconds=${REPLAY_TIMEOUT_SECONDS}"
    echo "flagship_timeout_seconds=${FLAGSHIP_TIMEOUT_SECONDS}"
    exit 0
  fi

  echo "[statebus-v2-local-api] starting run: ${RUN_ID}"
  echo "[statebus-v2-local-api] host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api] audit artifact root: ${AUDIT_ARTIFACT_ROOT}"

  docker_env=(
    -e STATEBUS_LOCAL_API_IN_CONTAINER=1
    -e STATEBUS_LOCAL_API_RUN_ID="$RUN_ID"
    -e STATEBUS_RESULT_ROOT="$CONTAINER_RESULT_ROOT"
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT"
    -e STATEBUS_LOCAL_API_PYTEST_MODE="$PYTEST_MODE"
    -e STATEBUS_LOCAL_API_RUN_FLAGSHIP="$RUN_FLAGSHIP"
    -e STATEBUS_LOCAL_API_REPEAT="$REPEAT_COUNT"
    -e STATEBUS_LOCAL_API_STRICT_EXIT="$STRICT_EXIT"
    -e STATEBUS_LOCAL_API_PYTEST_TIMEOUT_SECONDS="$PYTEST_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS="$CONTINUOUS_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS="$REPLAY_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_REPLAY_NEGATIVE_TIMEOUT_SECONDS="$REPLAY_NEGATIVE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS"
    -e PYTEST_TIMEOUT_SECONDS="$PYTEST_TIMEOUT_SECONDS"
    -e SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS"
    -e PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS"
    -e FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS"
    -e COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS"
    -e CONTINUOUS_TIMEOUT_SECONDS="$CONTINUOUS_TIMEOUT_SECONDS"
    -e REPLAY_TIMEOUT_SECONDS="$REPLAY_TIMEOUT_SECONDS"
    -e REPLAY_NEGATIVE_TIMEOUT_SECONDS="$REPLAY_NEGATIVE_TIMEOUT_SECONDS"
    -e FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS"
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
work_root = run_root / "work"
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
        try:
            rel = Path("artifacts") / path.relative_to(artifact_root)
        except ValueError:
            rel = Path(path.name)
    dest = runtime_files_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    copied.append({"reason": reason, "source": str(path), "artifact_relpath": str(dest.relative_to(artifact_root))})


if work_root.exists():
    for path in work_root.glob("**/benchmark_reports/*"):
        if path.suffix in {".json", ".md"}:
            copy_file(path, reason="nested_benchmark_report")
    for pattern, reason in (
        ("**/external_text_output.json", "external_case_output"),
        ("**/external_text_report.json", "external_case_report"),
        ("**/outputs/result.json", "statebus_case_output"),
        ("**/state/metadata/*.json", "state_metadata"),
        ("**/logs/hydration_audit.json", "hydration_audit"),
        ("**/registry/ref_registry.json", "ref_registry"),
    ):
        for path in work_root.glob(pattern):
            copy_file(path, reason=reason)

for path in (artifact_root / "stages").glob("*/console.log"):
    copy_file(path, reason="socket_path_audit")

summary_path = artifact_root / "summary.json"
if summary_path.exists():
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        summary = {}
    for diagnostics in (summary.get("compare_case_diagnostics") or {}).values():
        if not isinstance(diagnostics, list):
            continue
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            for lane_key in ("external_observed", "statebus_observed"):
                lane = item.get(lane_key)
                if not isinstance(lane, dict):
                    continue
                for field in ("output_artifact_path", "report_path"):
                    value = str(lane.get(field, "")).strip()
                    if value:
                        copy_file(Path(value.replace("/statebus/runs", str(run_root.parent))), reason=f"failed_case_{field}")

manifest = {
    "schema_version": "statebus.local_api_diagnostics_copy.v1",
    "run_root": str(run_root),
    "artifact_root": str(artifact_root),
    "copied_file_count": len(copied),
    "copied_files": copied,
}
(diagnostics_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    cat > "${AUDIT_ARTIFACT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api result copy

Original host result root:
  ${HOST_RESULT_ROOT}

Original container result root:
  ${CONTAINER_RESULT_ROOT}

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
  diagnostics/runtime_files/work/**/external_text_*.json
  diagnostics/runtime_files/work/**/outputs/result.json
  diagnostics/runtime_files/work/**/state/metadata/*.json
  diagnostics/runtime_files/work/**/logs/hydration_audit.json
  diagnostics/runtime_files/work/**/registry/ref_registry.json
EOF
  else
    echo "[statebus-v2-local-api] warning: missing artifact root: ${HOST_RESULT_ROOT}/artifacts" >&2
  fi

  echo "[statebus-v2-local-api] run exit: ${run_exit}"
  echo "[statebus-v2-local-api] host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api] audit artifact copy: ${AUDIT_ARTIFACT_ROOT}"
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
  if [[ -f deploy/activate_statebus_host.sh ]]; then
    STATEBUS_ACTUAL_ACTIVATION_SCRIPT="deploy/activate_statebus_host.sh"
    set +u
    # shellcheck disable=SC1091
    source deploy/activate_statebus_host.sh
    local exit_code=$?
    set -u
    if [[ "$exit_code" -eq 0 ]]; then
      STATEBUS_ACTIVATION_STATUS="success"
      STATEBUS_ACTIVATION_ERROR=""
    else
      STATEBUS_ACTIVATION_STATUS="failed"
      STATEBUS_ACTIVATION_ERROR="host_activation_failed_exit_${exit_code}"
    fi
    export STATEBUS_ACTUAL_ACTIVATION_SCRIPT STATEBUS_ACTIVATION_STATUS STATEBUS_ACTIVATION_ERROR
    return "$exit_code"
  fi
  STATEBUS_ACTUAL_ACTIVATION_SCRIPT="none"
  STATEBUS_ACTIVATION_STATUS="not_found"
  STATEBUS_ACTIVATION_ERROR=""
  export STATEBUS_ACTUAL_ACTIVATION_SCRIPT STATEBUS_ACTIVATION_STATUS STATEBUS_ACTIVATION_ERROR
  return 0
}

cd "$STATEBUS_PROJECT_ROOT"
if ! activate_statebus; then
  echo "[statebus-v2-local-api] activation failed; continuing with /usr/bin/python3" >&2
fi
if [[ "$STATEBUS_ACTIVATION_STATUS" != "success" ]]; then
  STATEBUS_ACTIVATION_STATUS="${STATEBUS_ACTIVATION_STATUS}_fallback_to_usr_bin_python3"
  export STATEBUS_ACTIVATION_STATUS
fi

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
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
LAST_STAGE_EXIT_CODE=0
LAST_STAGE_ARTIFACT="-"

echo "[statebus-v2-local-api] container result root: $RESULT_ROOT"
echo "[statebus-v2-local-api] artifact root: $ARTIFACT_ROOT"
echo "[statebus-v2-local-api] work root: $WORK_ROOT"
echo "[statebus-v2-local-api] run id: ${STATEBUS_LOCAL_API_RUN_ID}"
echo "[statebus-v2-local-api] pytest mode: ${STATEBUS_LOCAL_API_PYTEST_MODE:-focused}"
echo "[statebus-v2-local-api] repeat: ${STATEBUS_LOCAL_API_REPEAT:-1}"
echo "[statebus-v2-local-api] CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-}"
echo "[statebus-v2-local-api] STATEBUS_EMBED_DEVICE: ${STATEBUS_EMBED_DEVICE:-}"
echo "[statebus-v2-local-api] STATEBUS_CODEACT_SANDBOX_BACKEND: ${STATEBUS_CODEACT_SANDBOX_BACKEND:-}"
echo "[statebus-v2-local-api] activation script: ${STATEBUS_ACTUAL_ACTIVATION_SCRIPT}"
echo "[statebus-v2-local-api] activation status: ${STATEBUS_ACTIVATION_STATUS}"

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
    /usr/bin/python3 - "$STATEBUS_LOCAL_API_RUN_ID:$label" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:16])
PY
  )"
  local socket_path="/tmp/sb2-${digest}.sock"
  if [[ "${#socket_path}" -gt 100 ]]; then
    echo "[statebus-v2-local-api] internal error: socket path too long: ${socket_path}" >&2
    return 2
  fi
  printf '%s' "$socket_path"
}

run_text_stage() {
  local stage="$1"
  local timeout_s="$2"
  local required="$3"
  shift 3
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  local start_s end_s duration_s exit_code
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  start_s="$(date +%s)"
  set +e
  timeout "$timeout_s" "$@" 2>&1 | tee "$log_path"
  exit_code=${PIPESTATUS[0]}
  set -u
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  LAST_STAGE_EXIT_CODE="$exit_code"
  LAST_STAGE_ARTIFACT="-"
  record_stage "$stage" "$exit_code" "$required" "text" "-" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 40 "$log_path" || true
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
  echo "[statebus-v2-local-api] socket_path=${socket_path} len=${#socket_path}"
  start_s="$(date +%s)"
  set +e
  timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner \
    --suite "$suite" \
    --role-path-mode api \
    --embedding-mode local \
    --runtime-root "$runtime_root" \
    --workspace-root "$workspace_root" \
    --socket-path "$socket_path" \
    --suite-id "${STATEBUS_LOCAL_API_RUN_ID}-${stage}" \
    "$@" \
    > >(tee "$stdout_json") \
    2> >(tee "$log_path" >&2)
  exit_code=$?
  set -u
  rm -f "$socket_path" || true
  if [[ "$exit_code" -eq 0 ]] && ! json_valid "$stdout_json" >/dev/null 2>&1; then
    exit_code=3
  fi
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  LAST_STAGE_EXIT_CODE="$exit_code"
  LAST_STAGE_ARTIFACT="$stdout_json"
  record_stage "$stage" "$exit_code" "$required" "live_runner" "$stdout_json" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} -> ${stdout_json} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 60 "$log_path" || true
  fi
  return 0
}

run_env_probe() {
  local stage="00_env_probe"
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  {
    echo "pwd=$(pwd)"
    echo "python=$(/usr/bin/python3 --version)"
    echo "python_executable=$(/usr/bin/python3 -c 'import sys; print(sys.executable)')"
    echo "activation_script=${STATEBUS_ACTUAL_ACTIVATION_SCRIPT:-}"
    echo "activation_status=${STATEBUS_ACTIVATION_STATUS:-}"
    echo "activation_error=${STATEBUS_ACTIVATION_ERROR:-}"
    echo "branch=$(git branch --show-current)"
    echo "commit=$(git rev-parse HEAD)"
    echo "API_KEY=${STATEBUS_LLM_API_KEY:+set}"
    echo "OPENAI_API_KEY=${OPENAI_API_KEY:+set}"
    echo "STATEBUS_LLM_CONFIG_FILE=${STATEBUS_LLM_CONFIG_FILE:-}"
    echo "STATEBUS_LLM_CONFIG_PATH=${STATEBUS_LLM_CONFIG_PATH:-}"
    echo "STATEBUS_LLM_ENV_FILE=${STATEBUS_LLM_ENV_FILE:-}"
    echo "STATEBUS_EMBED_MODEL_PATH=${STATEBUS_EMBED_MODEL_PATH:-}"
    echo "STATEBUS_EMBED_DEVICE=${STATEBUS_EMBED_DEVICE:-}"
    echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
    echo "TOKENIZERS_PARALLELISM=${TOKENIZERS_PARALLELISM:-}"
    echo "PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-}"
    echo "socket_path_contract=/tmp/sb2-<16hex>.sock"
    echo "git_status:"
    git status --short
    /usr/bin/python3 - <<'PY'
import importlib.util
import json
import os
import sys

payload = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "torch_present": importlib.util.find_spec("torch") is not None,
    "sentence_transformers_present": importlib.util.find_spec("sentence_transformers") is not None,
    "activation_script": os.getenv("STATEBUS_ACTUAL_ACTIVATION_SCRIPT", ""),
    "activation_status": os.getenv("STATEBUS_ACTIVATION_STATUS", ""),
    "activation_error": os.getenv("STATEBUS_ACTIVATION_ERROR", ""),
    "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
    "statebus_embed_model_path": os.getenv("STATEBUS_EMBED_MODEL_PATH", ""),
    "llm_config_file": os.getenv("STATEBUS_LLM_CONFIG_FILE", ""),
    "llm_env_file": os.getenv("STATEBUS_LLM_ENV_FILE", ""),
}
if payload["torch_present"]:
    import torch

    payload.update(
        {
            "torch_version": getattr(torch, "__version__", ""),
            "torch_cuda_available": bool(torch.cuda.is_available()),
            "torch_cuda_device_count": int(torch.cuda.device_count()),
        }
    )
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
  } 2>&1 | tee "$log_path"
  record_stage "$stage" "0" "1" "text" "-" "$log_path" "0"
}

run_env_probe

run_text_stage "01_py_compile" 300 1 /usr/bin/python3 -m py_compile \
  v2/runtime/driver.py \
  v2/runtime/role_path.py \
  v2/runtime/smoke.py \
  v2/runtime/replay.py \
  v2/state/store.py \
  v2/benchmark/live_runner.py \
  v2/benchmark/minimal_runner.py \
  v2/benchmark/fixed_answer_runner.py \
  v2/benchmark/comparator_runner.py \
  v2/benchmark/external_text_baseline.py \
  v2/benchmark/task_registry.py \
  v2/benchmark/reporting.py \
  v2/benchmark/models.py \
  v2/control/transport.py \
  v2/control/subprocess_worker.py \
  v2/contracts/models.py \
  v2/refs/models.py

case "${STATEBUS_LOCAL_API_PYTEST_MODE:-focused}" in
  full)
    run_text_stage "02_pytest_full_v2" "$PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m pytest -q tests/v2
    ;;
  focused)
    run_text_stage "02_pytest_focused_v2" "$PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m pytest -q \
      tests/v2/test_state_materialization.py \
      tests/v2/test_minimal_benchmark.py \
      tests/v2/test_preflight_and_live_runner.py \
      tests/v2/test_continuous_runner.py \
      tests/v2/test_fixed_answer_and_external_baseline.py \
      tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue \
      tests/v2/test_compare_diagnostics.py \
      tests/v2/test_control_plane.py \
      tests/v2/test_uds_loopback.py \
      tests/v2/test_subprocess_executor.py
    ;;
  skip)
    echo
    echo "=== 02_pytest_skipped ==="
    record_stage "02_pytest_skipped" "0" "0" "text" "-" "-" "0"
    ;;
  *)
    echo "[statebus-v2-local-api] unsupported STATEBUS_LOCAL_API_PYTEST_MODE=${STATEBUS_LOCAL_API_PYTEST_MODE}" >&2
    OVERALL_FAILURE=1
    ;;
esac

run_text_stage "03_runtime_smoke" "$SMOKE_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m runtime.smoke

for repeat_idx in $(seq 1 "${STATEBUS_LOCAL_API_REPEAT:-1}"); do
  repeat_label="$(printf 'r%02d' "$repeat_idx")"
  run_live_stage "${repeat_label}_04_preflight_api_local" "$PREFLIGHT_TIMEOUT_SECONDS" 1 "preflight"
  run_live_stage "${repeat_label}_05_formal_api_local_memfd" "$FORMAL_TIMEOUT_SECONDS" 1 "formal" \
    --benchmark-tier formal \
    --state-pool-mode memfd
  run_live_stage "${repeat_label}_06_formal_compare_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 1 "compare" \
    --benchmark-tier formal \
    --state-pool-mode memfd
  run_live_stage "${repeat_label}_07_dev_compare_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 0 "compare" \
    --benchmark-tier dev \
    --state-pool-mode memfd
  run_live_stage "${repeat_label}_08_carrier_compare_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 0 "carrier-compare" \
    --benchmark-tier dev \
    --state-pool-mode memfd
  run_live_stage "${repeat_label}_09_continuous_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" \
    --benchmark-tier dev
  run_live_stage "${repeat_label}_10_continuous_replay_api_local" "$REPLAY_TIMEOUT_SECONDS" 0 "continuous-replay" \
    --benchmark-tier dev
  run_live_stage "${repeat_label}_11_replay_negative_api_local" "$REPLAY_NEGATIVE_TIMEOUT_SECONDS" 1 "replay-negative-audit"
  if [[ "${STATEBUS_LOCAL_API_RUN_FLAGSHIP:-0}" == "1" ]]; then
    run_live_stage "${repeat_label}_12_flagship_ablation_api_local" "$FLAGSHIP_TIMEOUT_SECONDS" 0 "flagship-ablation"
  fi
done

/usr/bin/python3 - "$STATUS_TSV" "$SUMMARY_MD" "$SUMMARY_JSON" <<'PY'
from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

status_path = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
summary_json = Path(sys.argv[3])

rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))


def load_json(path_value: str) -> dict[str, Any] | None:
    if not path_value or path_value == "-":
        return None
    path = Path(path_value)
    if not path.exists() and path_value.startswith("/statebus/runs/"):
        result_root = Path(os.getenv("STATEBUS_RESULT_ROOT", ""))
        if result_root:
            try:
                rel = path.relative_to(result_root)
            except ValueError:
                run_id = os.getenv("STATEBUS_LOCAL_API_RUN_ID", "")
                prefix = Path("/statebus/runs") / run_id
                try:
                    rel = path.relative_to(prefix)
                except ValueError:
                    rel = None
            if rel is not None:
                candidate = result_root / rel
                if candidate.exists():
                    path = candidate
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return value if isinstance(value, dict) else {"_non_object_json": True, "value": value}


def nested_mode_report(payload: dict[str, Any]) -> dict[str, Any]:
    mode_reports = payload.get("mode_reports")
    if not isinstance(mode_reports, list) or not mode_reports:
        return {}
    first = mode_reports[0]
    if not isinstance(first, dict):
        return {}
    nested = load_json(str(first.get("report_path", "")))
    return nested if isinstance(nested, dict) else first


def l3_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    layers = payload.get("layers")
    if isinstance(layers, list) and len(layers) > 3 and isinstance(layers[3], dict):
        telemetry = layers[3].get("telemetry_summary")
        return telemetry if isinstance(telemetry, dict) else {}
    return {}


def compact_metrics(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    comparison = payload.get("comparison_summary") if isinstance(payload.get("comparison_summary"), dict) else {}
    collection = payload.get("collection_summary") if isinstance(payload.get("collection_summary"), dict) else {}
    telemetry = l3_telemetry(payload)
    metrics: dict[str, Any] = {}

    if "preflight" in stage:
        metrics.update(
            {
                "preflight_ok": payload.get("ok"),
                "missing_reason": payload.get("missing_reason"),
                "role_path_mode": metadata.get("role_path_mode"),
                "embedding_mode": metadata.get("embedding_mode"),
                "embedding_model_path": metadata.get("embedding_model_path"),
                "embedding_device": metadata.get("embedding_device"),
                "llm_config_source": metadata.get("llm_config_source"),
            }
        )
    elif "formal_api_local" in stage and "compare" not in stage:
        metrics.update(
            {
                "suite_id": payload.get("suite_id"),
                "role_path_mode": metadata.get("role_path_mode"),
                "embedding_mode": metadata.get("embedding_mode"),
                "L3_case_count": payload.get("L3_case_count"),
                "L3_quality_pass_count": payload.get("L3_quality_pass_count"),
                "family_count": payload.get("family_count"),
                "state_pool_mode_requested": payload.get("state_pool_mode_requested"),
                "state_pool_mode_used": payload.get("state_pool_mode_used"),
                "memfd_transfer_count": payload.get("memfd_transfer_count"),
                "memfd_publish_count": payload.get("memfd_publish_count"),
                "memfd_bytes_transferred": payload.get("memfd_bytes_transferred"),
                "semantic_state_transfer_count": telemetry.get("semantic_state_transfer_count"),
                "shared_memory_publish_count": telemetry.get("shared_memory_publish_count"),
                "mmap_publish_count": telemetry.get("mmap_publish_count"),
                "api_planner_call_count": telemetry.get("planner_call_count"),
                "api_retriever_call_count": telemetry.get("retriever_call_count"),
                "api_executor_call_count": telemetry.get("executor_call_count"),
                "api_summarizer_call_count": telemetry.get("summarizer_call_count"),
            }
        )
    elif "compare" in stage or "carrier_compare" in stage:
        nested = nested_mode_report(payload)
        fairness = nested.get("fairness_manifest") if isinstance(nested.get("fairness_manifest"), dict) else {}
        metrics.update(
            {
                "benchmark_tier": metadata.get("benchmark_tier"),
                "role_path_mode": metadata.get("role_path_mode"),
                "embedding_mode": metadata.get("embedding_mode"),
                "fixed_answer_external_comparison_valid": metadata.get(
                    "fixed_answer_external_comparison_valid"
                ),
                "external_comparator_claim_scope": metadata.get("external_comparator_claim_scope"),
                "formal_compare_scope_label": metadata.get("formal_compare_scope_label"),
                "formal_compare_case_count": metadata.get("formal_compare_case_count"),
                "formal_compare_family_count": metadata.get("formal_compare_family_count"),
                "formal_registry_case_count": metadata.get("formal_registry_case_count"),
                "formal_compare_full_registry_coverage": metadata.get(
                    "formal_compare_full_registry_coverage"
                ),
                "strict_equal_quality_comparison_valid": metadata.get(
                    "strict_equal_quality_comparison_valid"
                ),
                "quality_superiority_comparison_valid": metadata.get(
                    "quality_superiority_comparison_valid"
                ),
                "formal_quality_superiority_claim_allowed": metadata.get(
                    "formal_quality_superiority_claim_allowed"
                ),
                "formal_efficiency_superiority_claim_allowed": metadata.get(
                    "formal_efficiency_superiority_claim_allowed"
                ),
                "formal_external_claim_kind": metadata.get("formal_external_claim_kind"),
                "formal_superiority_claim_allowed": metadata.get("formal_superiority_claim_allowed"),
                "formal_efficiency_claim_allowed": metadata.get("formal_efficiency_claim_allowed"),
                "formal_headline_eligible": metadata.get("formal_headline_eligible"),
                "api_comparison_valid": comparison.get("api_comparison_valid"),
                "api_strict_equal_quality_comparison_valid": comparison.get(
                    "api_strict_equal_quality_comparison_valid"
                ),
                "api_quality_superiority_comparison_valid": comparison.get(
                    "api_quality_superiority_comparison_valid"
                ),
                "api_llm_total_tokens_delta": comparison.get("api_llm_total_tokens_delta"),
                "api_prompt_bytes_delta": comparison.get("api_prompt_bytes_delta"),
                "api_control_bytes_delta": comparison.get("api_control_bytes_delta"),
                "api_task_ms_delta": comparison.get("api_task_ms_delta"),
                "external_fairness_gate_coverage": fairness.get("external_fairness_gate_coverage"),
                "no_external_fairness_gate_failures": fairness.get("no_external_fairness_gate_failures"),
                "external_fairness_gate_pass_count": fairness.get("external_fairness_gate_pass_count"),
                "external_fairness_gate_failed_case_count": fairness.get(
                    "external_fairness_gate_failed_case_count"
                ),
                "state_pool_mode_used": payload.get("state_pool_mode_used") or metadata.get("state_pool_mode_used"),
                "memfd_transfer_count": payload.get("memfd_transfer_count") or metadata.get("memfd_transfer_count"),
            }
        )
    elif "continuous_replay" in stage:
        metrics.update(
            {
                "family_count": collection.get("family_count"),
                "continuous_round_count": collection.get("continuous_round_count"),
                "replay_target_round_count": collection.get("replay_target_round_count"),
                "replay_observed_round_count": collection.get("replay_observed_round_count"),
                "replay_missing_target_round_count": collection.get("replay_missing_target_round_count"),
                "validated_replay_count": collection.get("validated_replay_count"),
                "validated_downgraded_reuse_count": collection.get("validated_downgraded_reuse_count"),
                "exact_replay_count": collection.get("exact_replay_count"),
                "answer_restoration_replay_count": collection.get("answer_restoration_replay_count"),
                "L2_semantic_state_transfer_count": collection.get("L2_semantic_state_transfer_count"),
                "L3_reuse_gain": collection.get("L3_reuse_gain"),
            }
        )
    elif "continuous_api_local" in stage:
        metrics.update(
            {
                "family_count": collection.get("family_count"),
                "continuous_round_count": collection.get("continuous_round_count"),
                "L2_semantic_state_transfer_count": collection.get("L2_semantic_state_transfer_count"),
                "L3_reuse_gain": collection.get("L3_reuse_gain"),
            }
        )
    elif "replay_negative" in stage:
        metrics.update(
            {
                "audit_pass": payload.get("audit_pass"),
                "case_count": payload.get("case_count"),
                "failed_case_count": payload.get("failed_case_count"),
            }
        )
    elif "flagship_ablation" in stage:
        stress = payload.get("non_text_state_stress_summary")
        stress = stress if isinstance(stress, dict) else {}
        metrics.update(
            {
                "stress_family_count": stress.get("stress_family_count"),
                "stress_pass_family_count": stress.get("stress_pass_family_count"),
                "total_llm_prompt_saved_by_state_ref_bytes": stress.get(
                    "total_llm_prompt_saved_by_state_ref_bytes"
                ),
                "total_prompt_visible_saved_by_state_ref_bytes": stress.get(
                    "total_prompt_visible_saved_by_state_ref_bytes"
                ),
            }
        )

    return {key: value for key, value in metrics.items() if value is not None}


def sample_index() -> dict[str, dict[str, Any]]:
    samples: dict[str, dict[str, Any]] = {}
    for root in (
        Path("v2/benchmark/samples/formal_financial_family"),
        Path("v2/benchmark/samples/fixed_answer_family"),
    ):
        for path in root.glob("*.json"):
            payload = load_json(str(path))
            if isinstance(payload, dict) and payload.get("task_id"):
                samples[str(payload["task_id"])] = payload
    return samples


SAMPLES_BY_ID = sample_index()


def expected_case_fields(task_id: str) -> dict[str, Any]:
    sample = SAMPLES_BY_ID.get(task_id, {})
    expected_facts = sample.get("expected_facts") if isinstance(sample.get("expected_facts"), dict) else {}
    canonical = sample.get("canonical_task_spec") if isinstance(sample.get("canonical_task_spec"), dict) else {}
    arguments = canonical.get("arguments") if isinstance(canonical.get("arguments"), dict) else {}
    return {
        "route": sample.get("expected_route"),
        "tool_name": sample.get("expected_tool_name"),
        "metric_name": expected_facts.get("metric_name") or arguments.get("metric"),
        "metric_value": expected_facts.get("metric_value", expected_facts.get("revenue_value")),
        "legacy_revenue_value": expected_facts.get("revenue_value"),
        "selected_doc_hashes": expected_facts.get("selected_doc_hashes", []),
    }


def compact_observed_case(case: dict[str, Any], *, lane: str) -> dict[str, Any]:
    output = load_json(str(case.get("output_artifact_path", ""))) or {}
    audit_paths = case.get("audit_paths") if isinstance(case.get("audit_paths"), dict) else {}
    report = load_json(str(audit_paths.get("external_text_report", ""))) or {}
    retriever_payload = {}
    role_payloads = report.get("role_payloads") if isinstance(report.get("role_payloads"), dict) else {}
    if isinstance(role_payloads.get("retriever"), dict):
        retriever_payload = role_payloads["retriever"]
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    quality_floor = case.get("quality_floor") if isinstance(case.get("quality_floor"), dict) else {}
    return {
        "lane": lane,
        "route": output.get("route", report.get("route")),
        "tool_name": output.get("tool_name", report.get("tool_name")),
        "metric_name": output.get("metric_name", report.get("metric_name")),
        "metric_value": output.get("metric_value", report.get("metric_value")),
        "legacy_revenue_value": output.get("revenue_value", report.get("revenue_value")),
        "retriever_metric_name": retriever_payload.get("metric_name"),
        "retriever_metric_value": retriever_payload.get("metric_value"),
        "retriever_revenue_value": retriever_payload.get("revenue_value"),
        "selected_doc_hashes": output.get("selected_doc_hashes", []),
        "quality_floor_pass": quality_floor.get("quality_floor_pass"),
        "quality_floor_fail_reason": quality_floor.get("quality_floor_fail_reason"),
        "route_exact": metrics.get("route_exact"),
        "tool_exact": metrics.get("tool_exact"),
        "metric_name_exact": metrics.get("metric_name_exact"),
        "metric_value_exact": metrics.get("metric_value_exact"),
        "revenue_exact": metrics.get("revenue_exact"),
        "selected_doc_hashes_exact": metrics.get("selected_doc_hashes_exact"),
        "output_artifact_path": case.get("output_artifact_path"),
        "report_path": audit_paths.get("external_text_report", ""),
    }


def compare_case_diagnostics(stage: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "compare" not in stage or "carrier_compare" in stage:
        return []
    nested = nested_mode_report(payload)
    statebus_cases = nested.get("statebus_report", {}).get("cases", [])
    external_cases = nested.get("external_report", {}).get("cases", [])
    if not isinstance(statebus_cases, list) or not isinstance(external_cases, list):
        return []
    statebus_by_task = {
        str(case.get("task_id", "")): case
        for case in statebus_cases
        if isinstance(case, dict) and case.get("task_id")
    }
    diagnostics: list[dict[str, Any]] = []
    for external_case in external_cases:
        if not isinstance(external_case, dict):
            continue
        task_id = str(external_case.get("task_id", ""))
        statebus_case = statebus_by_task.get(task_id, {})
        external_qf = external_case.get("quality_floor") if isinstance(external_case.get("quality_floor"), dict) else {}
        statebus_qf = statebus_case.get("quality_floor") if isinstance(statebus_case.get("quality_floor"), dict) else {}
        case_passed = external_qf.get("quality_floor_pass") is True and statebus_qf.get("quality_floor_pass") is True
        diagnostics.append(
            {
                "stage": stage,
                "task_id": task_id,
                "case_passed": case_passed,
                "diagnostic_reason": "compare_case_trace" if case_passed else "quality_floor_failure",
                "expected": expected_case_fields(task_id),
                "external_observed": compact_observed_case(external_case, lane="external"),
                "statebus_observed": compact_observed_case(statebus_case, lane="statebus")
                if isinstance(statebus_case, dict)
                else {},
            }
        )
    return diagnostics


key_metrics: dict[str, dict[str, Any]] = {}
case_diagnostics: dict[str, list[dict[str, Any]]] = {}
for row in rows:
    payload = load_json(row.get("artifact", ""))
    if isinstance(payload, dict):
        metrics = compact_metrics(row["stage"], payload)
        if metrics:
            key_metrics[row["stage"]] = metrics
        diagnostics = compare_case_diagnostics(row["stage"], payload)
        if diagnostics:
            case_diagnostics[row["stage"]] = diagnostics

failed_required = [row for row in rows if row["required"] == "1" and row["exit_code"] != "0"]
failed_all = [row for row in rows if row["exit_code"] != "0"]

environment = {
    "activation_script": os.getenv("STATEBUS_ACTUAL_ACTIVATION_SCRIPT", ""),
    "activation_status": os.getenv("STATEBUS_ACTIVATION_STATUS", ""),
    "activation_error": os.getenv("STATEBUS_ACTIVATION_ERROR", ""),
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
    "statebus_embed_model_path": os.getenv("STATEBUS_EMBED_MODEL_PATH", ""),
    "llm_config_file": os.getenv("STATEBUS_LLM_CONFIG_FILE", ""),
    "llm_env_file": os.getenv("STATEBUS_LLM_ENV_FILE", ""),
}
try:
    import torch  # type: ignore

    environment["torch_version"] = getattr(torch, "__version__", "")
    environment["torch_cuda_available"] = bool(torch.cuda.is_available())
    environment["torch_cuda_device_count"] = int(torch.cuda.device_count())
except Exception as exc:
    environment["torch_probe_error"] = str(exc)
for package_name in ("sentence-transformers", "faiss-cpu", "protobuf", "pytest"):
    try:
        environment[f"package_{package_name}_version"] = importlib.metadata.version(package_name)
    except Exception:
        environment[f"package_{package_name}_version"] = ""

summary = {
    "run_id": os.getenv("STATEBUS_LOCAL_API_RUN_ID", ""),
    "mode": {"role_path_mode": "api", "embedding_mode": "local"},
    "environment": environment,
    "stage_count": len(rows),
    "failed_stage_count": len(failed_all),
    "failed_required_stage_count": len(failed_required),
    "failed_stages": [row["stage"] for row in failed_all],
    "failed_required_stages": [row["stage"] for row in failed_required],
    "key_metrics": key_metrics,
    "compare_case_diagnostics": case_diagnostics,
    "stages": rows,
}
summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# StateBus v2 local+api comprehensive statistics",
    "",
    "- Mode: `role_path_mode=api`, `embedding_mode=local`",
    f"- Stage count: `{len(rows)}`",
    f"- Failed stage count: `{len(failed_all)}`",
    f"- Failed required stage count: `{len(failed_required)}`",
    f"- Activation script: `{environment.get('activation_script', '')}`",
    f"- Activation status: `{environment.get('activation_status', '')}`",
    f"- Python executable: `{environment.get('python_executable', '')}`",
    "",
    "## Failed Required Stages",
]
if failed_required:
    for row in failed_required:
        lines.append(f"- `{row['stage']}` exit `{row['exit_code']}`")
else:
    lines.append("- none")

lines.extend(["", "## Key Metrics", ""])
if key_metrics:
    for stage, metrics in key_metrics.items():
        lines.append(f"### {stage}")
        for key, value in metrics.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
else:
    lines.append("- none parsed")

lines.extend(["", "## Compare Case Structured Fields", ""])
if case_diagnostics:
    for stage, diagnostics in case_diagnostics.items():
        lines.append(f"### {stage}")
        for item in diagnostics:
            expected = item.get("expected", {})
            external = item.get("external_observed", {})
            statebus = item.get("statebus_observed", {})
            lines.append(
                "- `{task_id}` pass `{case_passed}` reason `{reason}`; "
                "expected `{metric_name}={metric_value}`; "
                "external metric `{external_metric_name}={external_metric_value}` "
                "legacy revenue `{external_revenue}` qf `{external_qf}`; "
                "statebus metric `{statebus_metric_name}={statebus_metric_value}` qf `{statebus_qf}`".format(
                    task_id=item.get("task_id", ""),
                    case_passed=item.get("case_passed", ""),
                    reason=item.get("diagnostic_reason", ""),
                    metric_name=expected.get("metric_name", ""),
                    metric_value=expected.get("metric_value", ""),
                    external_metric_name=external.get("metric_name", external.get("retriever_metric_name", "")),
                    external_metric_value=external.get("metric_value", external.get("retriever_metric_value", "")),
                    external_revenue=external.get("legacy_revenue_value", external.get("retriever_revenue_value", "")),
                    external_qf=external.get("quality_floor_pass", ""),
                    statebus_metric_name=statebus.get("metric_name", ""),
                    statebus_metric_value=statebus.get("metric_value", ""),
                    statebus_qf=statebus.get("quality_floor_pass", ""),
                )
            )
        lines.append("")
else:
    lines.append("- none")

lines.extend(["", "## Stage Log", ""])
for row in rows:
    lines.append(
        f"- `{row['stage']}` exit `{row['exit_code']}` required `{row['required']}` "
        f"duration `{row['duration_s']}s` artifact `{row['artifact']}`"
    )

summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

echo
echo "=== result bundle ==="
echo "$ARTIFACT_ROOT"
echo "$SUMMARY_MD"
echo "$SUMMARY_JSON"
echo "$STATUS_TSV"

if [[ "${STATEBUS_LOCAL_API_STRICT_EXIT:-1}" == "1" ]]; then
  exit "$OVERALL_FAILURE"
fi
exit 0
