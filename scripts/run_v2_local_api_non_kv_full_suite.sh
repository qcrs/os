#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"

STAMP="${STATEBUS_LOCAL_API_NON_KV_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_API_NON_KV_RUN_ID:-v2-local-api-non-kv-${STAMP}}"
CORE_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_CORE_RUN_ID:-${RUN_ID}-core}"
EXTRA_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID:-${RUN_ID}-extras}"

HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
HOST_CORE_RESULT_ROOT="${HOST_RUNS_ROOT}/${CORE_RUN_ID}"
HOST_EXTRA_RESULT_ROOT="${HOST_RUNS_ROOT}/${EXTRA_RUN_ID}"
CONTAINER_EXTRA_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${EXTRA_RUN_ID}"
AUDIT_ARTIFACT_ROOT="${STATEBUS_LOCAL_API_NON_KV_AUDIT_ARTIFACT_ROOT:-${HOST_PROJECT_ROOT}/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_${STAMP}}"

TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-1}}"
REQUESTED_EMBED_DEVICE="${STATEBUS_LOCAL_API_NON_KV_EMBED_DEVICE:-${STATEBUS_EMBED_DEVICE:-cuda:0}}"
TARGET_EMBED_DEVICE="$REQUESTED_EMBED_DEVICE"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
TARGET_CODEACT_SANDBOX_BACKEND="${STATEBUS_CODEACT_SANDBOX_BACKEND:-auto}"

STRICT_EXIT="${STATEBUS_LOCAL_API_NON_KV_STRICT_EXIT:-1}"
CONTINUE_AFTER_CORE_FAILURE="${STATEBUS_LOCAL_API_NON_KV_CONTINUE_AFTER_CORE_FAILURE:-1}"
DRY_RUN="${STATEBUS_LOCAL_API_NON_KV_DRY_RUN:-0}"
ALLOW_HOST_ACTIVATION_FAILURE="${STATEBUS_LOCAL_API_NON_KV_ALLOW_HOST_ACTIVATION_FAILURE:-0}"
NO_TIMEOUTS="${STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS:-0}"

CORE_REPEAT="${STATEBUS_LOCAL_API_NON_KV_CORE_REPEAT:-1}"
CORE_PYTEST_MODE="${STATEBUS_LOCAL_API_NON_KV_CORE_PYTEST_MODE:-focused}"
CORE_RUN_FLAGSHIP="${STATEBUS_LOCAL_API_NON_KV_CORE_RUN_FLAGSHIP:-1}"
CORE_LATENCY_RERUN="${STATEBUS_LOCAL_API_NON_KV_CORE_LATENCY_RERUN:-1}"
CORE_LATENCY_RERUN_REPEAT_COUNT="${STATEBUS_LOCAL_API_NON_KV_CORE_LATENCY_RERUN_REPEAT_COUNT:-3}"

EXTRA_PYTEST_MODE="${STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE:-full_non_kv}" # full_non_kv | focused | full | skip
EXTRA_RUN_DESIGN_AUDIT="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DESIGN_AUDIT:-1}"
EXTRA_RUN_DEV_BASELINES="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DEV_BASELINES:-1}"
EXTRA_RUN_SHARED_MEMORY="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_SHARED_MEMORY:-1}"
EXTRA_RUN_CODEACT="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_CODEACT:-1}"
EXTRA_RUN_GRIDOPS="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS:-1}"
EXTRA_RUN_BENCHMARK_BALANCED="${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_BENCHMARK_BALANCED:-1}"

CODEACT_ACCEPTANCE_SANDBOX_BACKEND="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_SANDBOX_BACKEND:-bwrap}"
CODEACT_ACCEPTANCE_RUNS="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_RUNS:-5}"
CODEACT_ACCEPTANCE_TARGET="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TARGET:-3}"
CODEACT_MAX_REPAIR_ATTEMPTS="${STATEBUS_LOCAL_API_NON_KV_CODEACT_MAX_REPAIR_ATTEMPTS:-3}"

IMPORT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_IMPORT_TIMEOUT_SECONDS:-120}"
PY_COMPILE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_PY_COMPILE_TIMEOUT_SECONDS:-300}"
PYTEST_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_PYTEST_TIMEOUT_SECONDS:-2400}"
SMOKE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_SMOKE_TIMEOUT_SECONDS:-900}"
PREFLIGHT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_PREFLIGHT_TIMEOUT_SECONDS:-600}"
DESIGN_AUDIT_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_DESIGN_AUDIT_TIMEOUT_SECONDS:-300}"
FORMAL_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_FORMAL_TIMEOUT_SECONDS:-2400}"
COMPARE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_COMPARE_TIMEOUT_SECONDS:-2400}"
CONTINUOUS_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_CONTINUOUS_TIMEOUT_SECONDS:-2400}"
EXTERNAL_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_EXTERNAL_TIMEOUT_SECONDS:-1800}"
CODEACT_SMOKE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_CODEACT_SMOKE_TIMEOUT_SECONDS:-300}"
CODEACT_ACCEPTANCE_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS:-0}"

if [[ "$NO_TIMEOUTS" == "1" ]]; then
  IMPORT_TIMEOUT_SECONDS=0
  PY_COMPILE_TIMEOUT_SECONDS=0
  PYTEST_TIMEOUT_SECONDS=0
  SMOKE_TIMEOUT_SECONDS=0
  PREFLIGHT_TIMEOUT_SECONDS=0
  DESIGN_AUDIT_TIMEOUT_SECONDS=0
  FORMAL_TIMEOUT_SECONDS=0
  COMPARE_TIMEOUT_SECONDS=0
  CONTINUOUS_TIMEOUT_SECONDS=0
  EXTERNAL_TIMEOUT_SECONDS=0
  CODEACT_SMOKE_TIMEOUT_SECONDS=0
  CODEACT_ACCEPTANCE_TIMEOUT_SECONDS=0
fi

activate_host_env() {
  if [[ ! -f "${HOST_PROJECT_ROOT}/deploy/activate_statebus_host.sh" ]]; then
    echo "[statebus-v2-local-api-non-kv] missing host activation script" >&2
    return 1
  fi
  set +u
  # shellcheck disable=SC1091
  source "${HOST_PROJECT_ROOT}/deploy/activate_statebus_host.sh"
  local exit_code=$?
  set -u
  return "$exit_code"
}

copy_extra_artifacts() {
  mkdir -p "${AUDIT_ARTIFACT_ROOT}/extras"
  if [[ -d "${HOST_EXTRA_RESULT_ROOT}/artifacts" ]]; then
    cp -R "${HOST_EXTRA_RESULT_ROOT}/artifacts/." "${AUDIT_ARTIFACT_ROOT}/extras/"
    cat > "${AUDIT_ARTIFACT_ROOT}/extras/README.host.txt" <<EOF
StateBus v2 local+api non-KV extra result copy

Original host extra result root:
  ${HOST_EXTRA_RESULT_ROOT}

Main files:
  summary.md
  summary.json
  status.tsv
  console.log
  stages/*/stdout.json
  stages/*/console.log
EOF
  else
    echo "[statebus-v2-local-api-non-kv] warning: missing extra artifact root: ${HOST_EXTRA_RESULT_ROOT}/artifacts" >&2
  fi
}

write_combined_summary() {
  /usr/bin/python3 - \
    "$HOST_RESULT_ROOT" \
    "$AUDIT_ARTIFACT_ROOT" \
    "$HOST_CORE_RESULT_ROOT/artifacts/summary.json" \
    "$HOST_EXTRA_RESULT_ROOT/artifacts/summary.json" \
    "$CORE_RUN_ID" \
    "$EXTRA_RUN_ID" \
    "$core_exit" \
    "$extra_exit" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

host_result_root = Path(sys.argv[1])
artifact_root = Path(sys.argv[2])
core_summary_path = Path(sys.argv[3])
extra_summary_path = Path(sys.argv[4])
core_run_id = sys.argv[5]
extra_run_id = sys.argv[6]
core_exit = int(sys.argv[7])
extra_exit = int(sys.argv[8])


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return payload if isinstance(payload, dict) else {"value": payload, "_path": str(path)}


core = load_json(core_summary_path)
extra = load_json(extra_summary_path)

combined = {
    "run_id": host_result_root.name,
    "core_run_id": core_run_id,
    "extra_run_id": extra_run_id,
    "non_kv_only": True,
    "excluded_family_ids": ["kv_prefix_reuse", "kv_prefix_reuse_v1"],
    "core_exit_code": core_exit,
    "extra_exit_code": extra_exit,
    "core_failed_required_stage_count": core.get("failed_required_stage_count"),
    "extra_failed_required_stage_count": extra.get("failed_required_stage_count"),
    "core_failed_stages": core.get("failed_stages", []),
    "extra_failed_stages": extra.get("failed_stages", []),
    "paths": {
        "host_result_root": str(host_result_root),
        "audit_artifact_root": str(artifact_root),
        "core_summary_json": str(core_summary_path),
        "extra_summary_json": str(extra_summary_path),
    },
}

(host_result_root / "summary.json").write_text(
    json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

lines = [
    "# StateBus v2 local+api non-KV full suite",
    "",
    "- Non-KV only: `true`",
    "- Excluded families: `kv_prefix_reuse`, `kv_prefix_reuse_v1`",
    f"- Core run: `{core_run_id}` exit `{core_exit}`",
    f"- Extra run: `{extra_run_id}` exit `{extra_exit}`",
    f"- Core failed required stage count: `{core.get('failed_required_stage_count', 'n/a')}`",
    f"- Extra failed required stage count: `{extra.get('failed_required_stage_count', 'n/a')}`",
    "",
    "## Artifact Roots",
    f"- Combined host result root: `{host_result_root}`",
    f"- Combined audit artifact root: `{artifact_root}`",
    f"- Core artifact copy: `{artifact_root / 'core'}`",
    f"- Extra artifact copy: `{artifact_root / 'extras'}`",
    "",
    "## Notes",
    "- Host env is activated before Docker entry.",
    "- Docker stages run as `root` inside the container.",
    "- UDS sockets use short `/tmp/sbnk-<hash>.sock` paths to avoid AF_UNIX length failures.",
    "- This suite intentionally excludes KV-family experiments and KV-specific claims.",
]

(host_result_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

if [[ "${STATEBUS_LOCAL_API_NON_KV_IN_CONTAINER:-0}" != "1" ]]; then
  cd "$HOST_PROJECT_ROOT"
  mkdir -p "$HOST_RESULT_ROOT" "$AUDIT_ARTIFACT_ROOT"
  printf 'phase\texit_code\tnote\n' > "${HOST_RESULT_ROOT}/status.tsv"

  if ! activate_host_env; then
    if [[ "$ALLOW_HOST_ACTIVATION_FAILURE" != "1" ]]; then
      echo "[statebus-v2-local-api-non-kv] host activation failed; set STATEBUS_LOCAL_API_NON_KV_ALLOW_HOST_ACTIVATION_FAILURE=1 to override" >&2
      exit 1
    fi
    echo "[statebus-v2-local-api-non-kv] warning: host activation failed; continuing because override is enabled" >&2
  fi

  cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api non-KV full suite

Host project root:
  ${HOST_PROJECT_ROOT}

Container:
  ${CONTAINER_NAME}

Container project root:
  ${CONTAINER_PROJECT_ROOT}

Combined host result root:
  ${HOST_RESULT_ROOT}

Core host result root:
  ${HOST_CORE_RESULT_ROOT}

Extra host result root:
  ${HOST_EXTRA_RESULT_ROOT}

Combined audit artifact root:
  ${AUDIT_ARTIFACT_ROOT}

Contract:
  - host env is activated first via source deploy/activate_statebus_host.sh
  - docker exec uses root inside the container
  - local API path only: role_path_mode=api, embedding_mode=local
  - KV-family experiments are excluded on purpose
  - short AF_UNIX socket paths are forced under /tmp/sbnk-<hash>.sock
  - each extra stage uses its own runtime_root and workspace_root
  - container execution uses /usr/bin/python3
EOF

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[statebus-v2-local-api-non-kv] dry run"
    echo "run_id=${RUN_ID}"
    echo "core_run_id=${CORE_RUN_ID}"
    echo "extra_run_id=${EXTRA_RUN_ID}"
    echo "host_result_root=${HOST_RESULT_ROOT}"
    echo "audit_artifact_root=${AUDIT_ARTIFACT_ROOT}"
    echo "container=${CONTAINER_NAME}"
    echo "cuda_visible_devices=${TARGET_CUDA_VISIBLE_DEVICES}"
    echo "embed_device=${TARGET_EMBED_DEVICE}"
    echo "core_repeat=${CORE_REPEAT}"
    echo "core_run_flagship=${CORE_RUN_FLAGSHIP}"
    echo "core_latency_rerun=${CORE_LATENCY_RERUN}"
    echo "extra_run_design_audit=${EXTRA_RUN_DESIGN_AUDIT}"
    echo "extra_run_dev_baselines=${EXTRA_RUN_DEV_BASELINES}"
    echo "extra_run_shared_memory=${EXTRA_RUN_SHARED_MEMORY}"
    echo "extra_run_codeact=${EXTRA_RUN_CODEACT}"
    echo "extra_run_gridops=${EXTRA_RUN_GRIDOPS}"
    echo "extra_run_benchmark_balanced=${EXTRA_RUN_BENCHMARK_BALANCED}"
    echo "extra_pytest_mode=${EXTRA_PYTEST_MODE}"
    echo "no_timeouts=${NO_TIMEOUTS}"
    exit 0
  fi

  echo "[statebus-v2-local-api-non-kv] starting core comprehensive run: ${CORE_RUN_ID}"
  set +e
  env \
    STATEBUS_V2_CONTAINER_NAME="$CONTAINER_NAME" \
    STATEBUS_HOST_PROJECT_ROOT="$HOST_PROJECT_ROOT" \
    STATEBUS_HOST_RUNS_ROOT="$HOST_RUNS_ROOT" \
    STATEBUS_CONTAINER_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT" \
    STATEBUS_CONTAINER_RUNS_ROOT="$CONTAINER_RUNS_ROOT" \
    STATEBUS_LOCAL_API_RUN_ID="$CORE_RUN_ID" \
    STATEBUS_LOCAL_API_AUDIT_ARTIFACT_ROOT="${AUDIT_ARTIFACT_ROOT}/core" \
    STATEBUS_CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
    STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
    STATEBUS_LOCAL_API_PYTEST_MODE="$CORE_PYTEST_MODE" \
    STATEBUS_LOCAL_API_REPEAT="$CORE_REPEAT" \
    STATEBUS_LOCAL_API_RUN_FLAGSHIP="$CORE_RUN_FLAGSHIP" \
    STATEBUS_LOCAL_API_LATENCY_RERUN="$CORE_LATENCY_RERUN" \
    STATEBUS_LOCAL_API_LATENCY_RERUN_REPEAT_COUNT="$CORE_LATENCY_RERUN_REPEAT_COUNT" \
    STATEBUS_LOCAL_API_NO_TIMEOUTS="$NO_TIMEOUTS" \
    TMPDIR="/tmp" \
    STATEBUS_SOCKET_DIR="/tmp" \
    bash scripts/run_v2_local_api_comprehensive_stats.sh
  core_exit=$?
  set -e
  printf 'core\t%s\t%s\n' "$core_exit" "borrowed comprehensive non-KV core run" >> "${HOST_RESULT_ROOT}/status.tsv"

  if [[ "$core_exit" -ne 0 && "$CONTINUE_AFTER_CORE_FAILURE" != "1" ]]; then
    echo "[statebus-v2-local-api-non-kv] core run failed and continue-after-failure is disabled" >&2
    extra_exit=99
    printf 'extras\t%s\t%s\n' "$extra_exit" "skipped because core failed and continuation is disabled" >> "${HOST_RESULT_ROOT}/status.tsv"
    write_combined_summary
    if [[ "$STRICT_EXIT" == "1" ]]; then
      exit "$core_exit"
    fi
    exit 0
  fi

  echo "[statebus-v2-local-api-non-kv] starting extra non-KV stages: ${EXTRA_RUN_ID}"
  docker_env=(
    -e STATEBUS_LOCAL_API_NON_KV_IN_CONTAINER=1
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT"
    -e STATEBUS_RESULT_ROOT="$CONTAINER_EXTRA_RESULT_ROOT"
    -e STATEBUS_LOCAL_API_NON_KV_RUN_ID="$RUN_ID"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID="$EXTRA_RUN_ID"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE="$EXTRA_PYTEST_MODE"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DESIGN_AUDIT="$EXTRA_RUN_DESIGN_AUDIT"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DEV_BASELINES="$EXTRA_RUN_DEV_BASELINES"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_SHARED_MEMORY="$EXTRA_RUN_SHARED_MEMORY"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_CODEACT="$EXTRA_RUN_CODEACT"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS="$EXTRA_RUN_GRIDOPS"
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_BENCHMARK_BALANCED="$EXTRA_RUN_BENCHMARK_BALANCED"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_SANDBOX_BACKEND="$CODEACT_ACCEPTANCE_SANDBOX_BACKEND"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_RUNS="$CODEACT_ACCEPTANCE_RUNS"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TARGET="$CODEACT_ACCEPTANCE_TARGET"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_MAX_REPAIR_ATTEMPTS="$CODEACT_MAX_REPAIR_ATTEMPTS"
    -e STATEBUS_LOCAL_API_NON_KV_IMPORT_TIMEOUT_SECONDS="$IMPORT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS="$NO_TIMEOUTS"
    -e STATEBUS_LOCAL_API_NON_KV_PY_COMPILE_TIMEOUT_SECONDS="$PY_COMPILE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_PYTEST_TIMEOUT_SECONDS="$PYTEST_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_DESIGN_AUDIT_TIMEOUT_SECONDS="$DESIGN_AUDIT_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_CONTINUOUS_TIMEOUT_SECONDS="$CONTINUOUS_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_EXTERNAL_TIMEOUT_SECONDS="$EXTERNAL_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_SMOKE_TIMEOUT_SECONDS="$CODEACT_SMOKE_TIMEOUT_SECONDS"
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS="$CODEACT_ACCEPTANCE_TIMEOUT_SECONDS"
    -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES"
    -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE"
    -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM"
    -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF"
    -e STATEBUS_CODEACT_SANDBOX_BACKEND="$TARGET_CODEACT_SANDBOX_BACKEND"
    -e TMPDIR="/tmp"
    -e STATEBUS_SOCKET_DIR="/tmp"
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
  extra_exit=$?
  set -e
  printf 'extras\t%s\t%s\n' "$extra_exit" "non-KV extra diagnostics and family-expansion stages" >> "${HOST_RESULT_ROOT}/status.tsv"

  copy_extra_artifacts
  write_combined_summary

  echo "[statebus-v2-local-api-non-kv] core exit: ${core_exit}"
  echo "[statebus-v2-local-api-non-kv] extra exit: ${extra_exit}"
  echo "[statebus-v2-local-api-non-kv] combined host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api-non-kv] combined audit artifact root: ${AUDIT_ARTIFACT_ROOT}"

  if [[ "$STRICT_EXIT" == "1" && ( "$core_exit" -ne 0 || "$extra_exit" -ne 0 ) ]]; then
    exit 1
  fi
  exit 0
fi

set -uo pipefail

activate_container_env() {
  if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
    # shellcheck disable=SC1091
    source /usr/local/bin/activate_statebus_container.sh
    return $?
  fi
  return 0
}

cd "$STATEBUS_PROJECT_ROOT"
if ! activate_container_env; then
  echo "[statebus-v2-local-api-non-kv] warning: container activation failed; continuing with /usr/bin/python3" >&2
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

short_socket_path() {
  local label="$1"
  local digest
  digest="$(
    /usr/bin/python3 - "$STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID:$label" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  local socket_path="/tmp/sbnk-${digest}.sock"
  if [[ "${#socket_path}" -gt 90 ]]; then
    echo "[statebus-v2-local-api-non-kv] internal error: socket path too long: ${socket_path}" >&2
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
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-non-kv] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-non-kv] timeout=${timeout_s}s"
  fi
  start_s="$(date +%s)"
  set +e
  if is_unlimited_timeout "$timeout_s"; then
    "$@" 2>&1 | tee "$log_path"
  else
    timeout "$timeout_s" "$@" 2>&1 | tee "$log_path"
  fi
  exit_code=${PIPESTATUS[0]}
  set -u
  end_s="$(date +%s)"
  duration_s=$((end_s - start_s))
  record_stage "$stage" "$exit_code" "$required" "text" "-" "$log_path" "$duration_s"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "[ok] ${stage} (${duration_s}s)"
  else
    echo "[fail] ${stage} exit=${exit_code} (${duration_s}s)"
    tail -n 60 "$log_path" || true
  fi
  return 0
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
    echo "[statebus-v2-local-api-non-kv] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-non-kv] timeout=${timeout_s}s"
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
    tail -n 100 "$log_path" || true
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
  echo "[statebus-v2-local-api-non-kv] socket_path=${socket_path} len=${#socket_path}"
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-non-kv] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-non-kv] timeout=${timeout_s}s"
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
      --suite-id "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID}-${stage}" \
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
      --suite-id "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID}-${stage}" \
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
    tail -n 80 "$log_path" || true
  fi
  return 0
}

run_codeact_acceptance() {
  local stage="x04d_codeact_acceptance_api"
  local timeout_s="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS:-0}"
  local required=1
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local work_stage_dir="$WORK_ROOT/$stage"
  local stage_root="$work_stage_dir/codeact_acceptance"
  local stdout_json="$stage_dir/stdout.json"
  local log_path="$stage_dir/console.log"
  local total_runs="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_RUNS:-5}"
  local target_success="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TARGET:-3}"
  local sandbox_backend="${STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_SANDBOX_BACKEND:-bwrap}"
  local start_s end_s duration_s exit_code
  mkdir -p "$stage_dir" "$stage_root"
  : > "$log_path"
  echo
  echo "=== ${stage} ==="
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-non-kv] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-non-kv] timeout=${timeout_s}s"
  fi
  echo "[statebus-v2-local-api-non-kv] runs=${total_runs} target=${target_success} sandbox_backend=${sandbox_backend}"
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
      --max-repair-attempts "${STATEBUS_LOCAL_API_NON_KV_CODEACT_MAX_REPAIR_ATTEMPTS:-3}" \
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
    "schema_version": "statebus.local_api_codeact_acceptance_non_kv.v1",
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

run_env_probe() {
  local stage="x00_env_probe"
  local stage_dir="$ARTIFACT_ROOT/stages/$stage"
  local log_path="$stage_dir/console.log"
  mkdir -p "$stage_dir"
  echo
  echo "=== ${stage} ==="
  {
    echo "pwd=$(pwd)"
    echo "python=$(/usr/bin/python3 --version)"
    echo "python_executable=$(/usr/bin/python3 -c 'import sys; print(sys.executable)')"
    echo "branch=$(git branch --show-current)"
    echo "commit=$(git rev-parse HEAD)"
    echo "API_KEY=${STATEBUS_LLM_API_KEY:+set}"
    echo "OPENAI_API_KEY=${OPENAI_API_KEY:+set}"
    echo "STATEBUS_LLM_CONFIG_FILE=${STATEBUS_LLM_CONFIG_FILE:-}"
    echo "STATEBUS_LLM_ENV_FILE=${STATEBUS_LLM_ENV_FILE:-}"
    echo "STATEBUS_EMBED_MODEL_PATH=${STATEBUS_EMBED_MODEL_PATH:-}"
    echo "STATEBUS_EMBED_DEVICE=${STATEBUS_EMBED_DEVICE:-}"
    echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
    echo "TMPDIR=${TMPDIR:-}"
    echo "STATEBUS_SOCKET_DIR=${STATEBUS_SOCKET_DIR:-}"
    echo "socket_path_contract=/tmp/sbnk-<12hex>.sock"
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
    "faiss_present": importlib.util.find_spec("faiss") is not None,
    "openai_present": importlib.util.find_spec("openai") is not None,
    "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.getenv("STATEBUS_EMBED_DEVICE", ""),
    "statebus_embed_model_path": os.getenv("STATEBUS_EMBED_MODEL_PATH", ""),
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

echo "[statebus-v2-local-api-non-kv] extra result root: $RESULT_ROOT"
echo "[statebus-v2-local-api-non-kv] artifact root: $ARTIFACT_ROOT"
echo "[statebus-v2-local-api-non-kv] work root: $WORK_ROOT"
echo "[statebus-v2-local-api-non-kv] run id: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID}"
echo "[statebus-v2-local-api-non-kv] CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-}"
echo "[statebus-v2-local-api-non-kv] STATEBUS_EMBED_DEVICE: ${STATEBUS_EMBED_DEVICE:-}"
echo "[statebus-v2-local-api-non-kv] no timeouts: ${STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS:-0}"
echo "[statebus-v2-local-api-non-kv] design audit enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DESIGN_AUDIT:-1}"
echo "[statebus-v2-local-api-non-kv] dev baselines enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DEV_BASELINES:-1}"
echo "[statebus-v2-local-api-non-kv] shared memory contrasts enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_SHARED_MEMORY:-1}"
echo "[statebus-v2-local-api-non-kv] CodeAct diagnostics enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_CODEACT:-1}"
echo "[statebus-v2-local-api-non-kv] GridOps family enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS:-1}"
echo "[statebus-v2-local-api-non-kv] benchmark_balanced enabled: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_BENCHMARK_BALANCED:-1}"

run_env_probe

run_text_stage "x01_py_compile_non_kv" "$PY_COMPILE_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m py_compile \
  scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
  scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py \
  v2/runtime/driver.py \
  v2/runtime/role_path.py \
  v2/runtime/smoke.py \
  v2/runtime/replay.py \
  v2/runtime/codeact.py \
  v2/runtime/codeact_data_tasks.py \
  v2/runtime/codeact_sandbox.py \
  v2/runtime/neural_state.py \
  v2/state/store.py \
  v2/benchmark/live_runner.py \
  v2/benchmark/continuous_runner.py \
  v2/benchmark/continuous_task_family.py \
  v2/benchmark/flagship_ablation.py \
  v2/benchmark/replay_negative_audit.py \
  v2/benchmark/fixed_answer_runner.py \
  v2/benchmark/external_text_baseline.py \
  v2/control/transport.py \
  v2/control/subprocess_worker.py

case "${STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE:-full_non_kv}" in
  full)
    run_text_stage "x02_pytest_full_v2" "$PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m pytest -q tests/v2
    ;;
  full_non_kv)
    run_text_stage "x02_pytest_full_non_kv_v2" "$PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m pytest -q \
      tests/v2 \
      --ignore=tests/v2/test_kv_prefix_control_plane.py \
      -k 'not kv_prefix'
    ;;
  focused)
    run_text_stage "x02_pytest_non_kv_focused" "$PYTEST_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m pytest -q \
      tests/v2/test_preflight_and_live_runner.py \
      tests/v2/test_minimal_benchmark.py \
      tests/v2/test_fixed_answer_and_external_baseline.py \
      tests/v2/test_compare_diagnostics.py \
      tests/v2/test_continuous_runner.py \
      tests/v2/test_continuous_task_family_loader.py \
      tests/v2/test_continuous_task_family_design.py \
      tests/v2/test_bounded_llm_codeact_demo.py \
      tests/v2/test_runtime_persistence_breakdown.py \
      tests/v2/test_registry_store.py \
      tests/v2/test_flagship_ablation.py \
      tests/v2/test_control_plane.py \
      tests/v2/test_subprocess_executor.py \
      tests/v2/test_uds_loopback.py \
      tests/v2/test_smoke.py::test_v2_smoke_benchmark_balanced_profile_hashes_prompt_slices \
      tests/v2/test_runtime_and_benchmark.py::test_codeact_runner_reuses_cached_result_for_identical_request \
      tests/v2/test_runtime_and_benchmark.py::test_telemetry_emitter_batches_flushes_for_benchmark_balanced_profile
    ;;
  skip)
    record_stage "x02_pytest_skipped" "0" "0" "text" "-" "-" "0"
    ;;
  *)
    echo "[statebus-v2-local-api-non-kv] unsupported extra pytest mode: ${STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE}" >&2
    OVERALL_FAILURE=1
    ;;
esac

run_text_stage "x03_runtime_smoke" "$SMOKE_TIMEOUT_SECONDS" 1 /usr/bin/python3 -m runtime.smoke
run_live_stage "x04_preflight_api_local" "$PREFLIGHT_TIMEOUT_SECONDS" 1 "preflight"

if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_CODEACT:-1}" == "1" ]]; then
  run_json_stage "x04b_import_probe" "$IMPORT_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
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
    "schema_version": "statebus.local_api_import_probe_non_kv.v1",
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

  run_json_stage "x04c_codeact_bwrap_smoke" "$CODEACT_SMOKE_TIMEOUT_SECONDS" 1 /usr/bin/python3 - <<'PY'
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
    "schema_version": "statebus.codeact_bwrap_sandbox_check_non_kv.v1",
    "ok": bool(bwrap_smoke.get("ok")) and bool(codeact_smoke.get("ok")),
    "bwrap_smoke": bwrap_smoke,
    "codeact_bwrap_smoke": codeact_smoke,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload["ok"] else 1)
PY

  run_codeact_acceptance
fi

if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DESIGN_AUDIT:-1}" == "1" ]]; then
  run_live_stage "x05_design_csv_table_profile" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family csv_table_profile_v1
  run_live_stage "x06_design_incident_diagnosis" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family incident_diagnosis_v2
  run_live_stage "x07_design_long_doc_table" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family long_doc_table_v1
  run_live_stage "x08_design_csv_correlation_replay" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family csv_correlation_replay_v1
  run_live_stage "x09_design_cross_period_financial" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family cross_period_financial_v1
  run_live_stage "x10_design_long_doc_metric_replay" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" --family long_doc_metric_replay_v1
  if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS:-1}" == "1" ]]; then
    run_live_stage "x10b_design_gridops_world" "$DESIGN_AUDIT_TIMEOUT_SECONDS" 1 "continuous-design-audit" \
      --family-dir v2/benchmark/samples/continuous_task_families/gridops_world
  fi
fi

if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DEV_BASELINES:-1}" == "1" ]]; then
  run_live_stage "x11_dev_statebus_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 0 "statebus" \
    --benchmark-tier dev \
    --state-pool-mode memfd
  run_live_stage "x12_dev_external_api_local" "$EXTERNAL_TIMEOUT_SECONDS" 0 "external" \
    --benchmark-tier dev
  run_live_stage "x13_dev_compare_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 0 "compare" \
    --benchmark-tier dev \
    --state-pool-mode memfd
  run_live_stage "x14_dev_carrier_compare_api_local_memfd" "$COMPARE_TIMEOUT_SECONDS" 0 "carrier-compare" \
    --benchmark-tier dev \
    --state-pool-mode memfd
fi

run_live_stage "x15_continuous_csv_table_profile_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" --family csv_table_profile_v1
run_live_stage "x16_continuous_incident_diagnosis_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" --family incident_diagnosis_v2
run_live_stage "x17_continuous_long_doc_table_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" --family long_doc_table_v1
if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS:-1}" == "1" ]]; then
  run_live_stage "x17b_continuous_gridops_world_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" \
    --family-dir v2/benchmark/samples/continuous_task_families/gridops_world
fi

run_live_stage "x18_continuous_replay_csv_correlation_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous-replay" --family csv_correlation_replay_v1
run_live_stage "x19_continuous_replay_cross_period_financial_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous-replay" --family cross_period_financial_v1
run_live_stage "x20_continuous_replay_long_doc_metric_api_local" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous-replay" --family long_doc_metric_replay_v1

if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_SHARED_MEMORY:-1}" == "1" ]]; then
  run_live_stage "x21_formal_api_local_shared_memory" "$FORMAL_TIMEOUT_SECONDS" 0 "formal" \
    --benchmark-tier formal \
    --state-pool-mode shared_memory
  run_live_stage "x22_formal_carrier_compare_api_local_shared_memory" "$COMPARE_TIMEOUT_SECONDS" 0 "carrier-compare" \
    --benchmark-tier formal \
    --state-pool-mode shared_memory
  run_live_stage "x23_formal_compare_api_local_shared_memory" "$COMPARE_TIMEOUT_SECONDS" 0 "compare" \
    --benchmark-tier formal \
    --state-pool-mode shared_memory
  run_live_stage "x23b_formal_api_local_shared_memory_subprocess" "$FORMAL_TIMEOUT_SECONDS" 0 "formal" \
    --benchmark-tier formal \
    --state-pool-mode shared_memory \
    --transport subprocess
fi

if [[ "${STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_BENCHMARK_BALANCED:-1}" == "1" ]]; then
  run_live_stage "x24_formal_api_local_memfd_benchmark_balanced" "$FORMAL_TIMEOUT_SECONDS" 0 "formal" \
    --benchmark-tier formal \
    --state-pool-mode memfd \
    --persistence-profile benchmark_balanced
  run_live_stage "x25_formal_carrier_compare_api_local_memfd_benchmark_balanced" "$COMPARE_TIMEOUT_SECONDS" 0 "carrier-compare" \
    --benchmark-tier formal \
    --state-pool-mode memfd \
    --persistence-profile benchmark_balanced
  run_live_stage "x26_formal_compare_api_local_memfd_benchmark_balanced" "$COMPARE_TIMEOUT_SECONDS" 0 "compare" \
    --benchmark-tier formal \
    --state-pool-mode memfd \
    --persistence-profile benchmark_balanced
  run_live_stage "x27_continuous_collection_api_local_benchmark_balanced" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous" \
    --persistence-profile benchmark_balanced
  run_live_stage "x28_continuous_replay_collection_api_local_benchmark_balanced" "$CONTINUOUS_TIMEOUT_SECONDS" 0 "continuous-replay" \
    --persistence-profile benchmark_balanced
fi

/usr/bin/python3 - "$STATUS_TSV" "$SUMMARY_MD" "$SUMMARY_JSON" <<'PY'
from __future__ import annotations

import csv
import json
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
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return payload if isinstance(payload, dict) else {"value": payload, "_path": str(path)}


def layer_metric(payload: dict[str, Any], layer_index: int, group_name: str, key: str) -> Any:
    layers = payload.get("layers")
    if not isinstance(layers, list) or not (0 <= layer_index < len(layers)):
        return None
    layer = layers[layer_index]
    if not isinstance(layer, dict):
        return None
    group = layer.get(group_name)
    if not isinstance(group, dict):
        return None
    return group.get(key)


def nested_mode_report(payload: dict[str, Any]) -> dict[str, Any]:
    mode_reports = payload.get("mode_reports")
    if not isinstance(mode_reports, list) or not mode_reports:
        return {}
    first = mode_reports[0]
    if not isinstance(first, dict):
        return {}
    nested = load_json(str(first.get("report_path", "")))
    return nested if isinstance(nested, dict) else {}


def extract_metrics(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    comparison = payload.get("comparison_summary") if isinstance(payload.get("comparison_summary"), dict) else {}
    collection = payload.get("collection_summary") if isinstance(payload.get("collection_summary"), dict) else {}
    if "preflight" in stage:
      metrics.update(
          {
              "ok": payload.get("ok"),
              "missing_reasons": payload.get("missing_reasons"),
              "embedding_device": payload.get("embedding_device") or metadata.get("embedding_device"),
              "embedding_model_path": payload.get("embedding_model_path") or metadata.get("embedding_model_path"),
              "llm_config_source": payload.get("llm_config_source") or metadata.get("llm_config_source"),
          }
      )
    if "import_probe" in stage:
      metrics.update(
          {
              "ok": payload.get("ok"),
              "runtime_file": payload.get("runtime_file"),
              "codeact_file": payload.get("codeact_file"),
              "neural_state_file": payload.get("neural_state_file"),
              "non_default_after_default": payload.get("non_default_after_default"),
          }
      )
    if "codeact_bwrap_smoke" in stage:
      metrics.update(
          {
              "ok": payload.get("ok"),
              "bwrap_ok": (payload.get("bwrap_smoke") or {}).get("ok") if isinstance(payload.get("bwrap_smoke"), dict) else None,
              "codeact_bwrap_ok": (payload.get("codeact_bwrap_smoke") or {}).get("ok") if isinstance(payload.get("codeact_bwrap_smoke"), dict) else None,
          }
      )
    if "codeact_acceptance" in stage:
      metrics.update(
          {
              "success_count": payload.get("success_count"),
              "total_runs": payload.get("total_runs"),
              "target_success_count": payload.get("target_success_count"),
              "target_met": payload.get("target_met"),
              "sandbox_backend_required": payload.get("sandbox_backend_required"),
          }
      )
    if "design_" in stage:
      metrics.update(
          {
              "family_id": payload.get("family_id"),
              "claim_tier": payload.get("claim_tier"),
              "round_count": payload.get("round_count"),
              "dataset_count": payload.get("dataset_count"),
              "allowed_reuse_classes": payload.get("allowed_reuse_classes"),
          }
      )
    if "continuous_" in stage:
      metrics.update(
          {
              "family_id": payload.get("task_family") or payload.get("family_id") or metadata.get("family_id"),
              "family_count": collection.get("family_count") or payload.get("family_count"),
              "persistence_profile": payload.get("persistence_profile") or metadata.get("persistence_profile"),
              "continuous_round_count": collection.get("continuous_round_count"),
              "replay_target_round_count": collection.get("replay_target_round_count"),
              "validated_replay_count": collection.get("validated_replay_count"),
              "exact_replay_count": collection.get("exact_replay_count"),
              "semantic_state_transfer_count": layer_metric(payload, 2, "telemetry_summary", "semantic_state_transfer_count"),
              "reuse_gain": layer_metric(payload, 3, "aggregated_metrics", "reuse_gain"),
          }
      )
    if "shared_memory" in stage or "formal_" in stage or "compare" in stage or "statebus" in stage or "external" in stage:
      metrics.update(
          {
              "suite_id": payload.get("suite_id"),
              "benchmark_tier": payload.get("benchmark_tier") or metadata.get("benchmark_tier"),
              "family_case_count": payload.get("family_case_count"),
              "family_count": payload.get("family_count"),
              "L3_case_count": payload.get("L3_case_count"),
              "L3_quality_pass_count": payload.get("L3_quality_pass_count"),
              "persistence_profile": payload.get("persistence_profile") or metadata.get("persistence_profile"),
              "state_pool_mode_requested": payload.get("state_pool_mode_requested") or metadata.get("state_pool_mode_requested"),
              "state_pool_mode_used": payload.get("state_pool_mode_used") or metadata.get("state_pool_mode_used"),
              "transport": payload.get("transport") or metadata.get("transport"),
              "memfd_transfer_count": payload.get("memfd_transfer_count") or metadata.get("memfd_transfer_count"),
              "shared_memory_publish_count": layer_metric(payload, 3, "telemetry_summary", "shared_memory_publish_count"),
              "formal_compare_case_count": metadata.get("formal_compare_case_count"),
              "formal_compare_family_count": metadata.get("formal_compare_family_count"),
              "formal_compare_full_registry_coverage": metadata.get("formal_compare_full_registry_coverage"),
              "strict_equal_quality_comparison_valid": metadata.get("strict_equal_quality_comparison_valid"),
              "protocol_vs_external_task_ms_delta": comparison.get("protocol_vs_external_task_ms_delta"),
              "protocol_vs_external_token_delta": comparison.get("protocol_vs_external_total_tokens_delta"),
          }
      )
      if "compare" in stage:
          nested = nested_mode_report(payload)
          fairness = nested.get("fairness_manifest") if isinstance(nested.get("fairness_manifest"), dict) else {}
          metrics["fairness_suite_verdict"] = fairness.get("suite_verdict")
    return {key: value for key, value in metrics.items() if value not in (None, "", [], {})}


payload_by_stage: dict[str, dict[str, Any]] = {}
key_metrics: dict[str, dict[str, Any]] = {}
for row in rows:
    payload = load_json(row.get("artifact", ""))
    if not isinstance(payload, dict):
        continue
    payload_by_stage[row["stage"]] = payload
    metrics = extract_metrics(row["stage"], payload)
    if metrics:
        key_metrics[row["stage"]] = metrics

failed_required = [row for row in rows if row["required"] == "1" and row["exit_code"] != "0"]
failed_all = [row for row in rows if row["exit_code"] != "0"]

summary = {
    "run_id": str(summary_json.parent.parent.name),
    "non_kv_only": True,
    "excluded_family_ids": ["kv_prefix_reuse", "kv_prefix_reuse_v1"],
    "stage_count": len(rows),
    "failed_stage_count": len(failed_all),
    "failed_required_stage_count": len(failed_required),
    "failed_stages": [row["stage"] for row in failed_all],
    "failed_required_stages": [row["stage"] for row in failed_required],
    "key_metrics": key_metrics,
    "stages": rows,
}
summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# StateBus v2 local+api non-KV extra stages",
    "",
    "- Non-KV only: `true`",
    "- Excluded families: `kv_prefix_reuse`, `kv_prefix_reuse_v1`",
    f"- Stage count: `{len(rows)}`",
    f"- Failed stage count: `{len(failed_all)}`",
    f"- Failed required stage count: `{len(failed_required)}`",
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

lines.extend(["", "## Stage Log", ""])
for row in rows:
    lines.append(
        f"- `{row['stage']}` exit `{row['exit_code']}` required `{row['required']}` "
        f"duration `{row['duration_s']}s` artifact `{row['artifact']}`"
    )

summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

if [[ "$OVERALL_FAILURE" -ne 0 ]]; then
  exit 1
fi
exit 0
