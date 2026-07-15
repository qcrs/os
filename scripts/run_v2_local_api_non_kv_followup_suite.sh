#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
HOST_PROJECT_ROOT="${STATEBUS_HOST_PROJECT_ROOT:-/home/qcrs/statebus/project}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
CONTAINER_PROJECT_ROOT="${STATEBUS_CONTAINER_PROJECT_ROOT:-/workspace/statebus/project}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"

BASE_CORE_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_BASE_CORE_RUN_ID:-v2-local-api-non-kv-20260709_002546-core}"
BASE_CORE_RESULT_ROOT="${STATEBUS_LOCAL_API_NON_KV_BASE_CORE_RESULT_ROOT:-${HOST_RUNS_ROOT}/${BASE_CORE_RUN_ID}}"

STAMP="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RUN_ID="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID:-v2-local-api-non-kv-followup-${STAMP}}"
LR01_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_LR01_RUN_ID:-${RUN_ID}-lr01}"
FLAGSHIP_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_RUN_ID:-${RUN_ID}-flagship}"
FLAGSHIP_DIAG_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_DIAG_RUN_ID:-${RUN_ID}-flagship-families}"
EXTRA_RUN_ID="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EXTRA_RUN_ID:-${RUN_ID}-extras}"

HOST_RESULT_ROOT="${HOST_RUNS_ROOT}/${RUN_ID}"
HOST_LR01_RESULT_ROOT="${HOST_RUNS_ROOT}/${LR01_RUN_ID}"
HOST_FLAGSHIP_RESULT_ROOT="${HOST_RUNS_ROOT}/${FLAGSHIP_RUN_ID}"
HOST_FLAGSHIP_DIAG_RESULT_ROOT="${HOST_RUNS_ROOT}/${FLAGSHIP_DIAG_RUN_ID}"
HOST_EXTRA_RESULT_ROOT="${HOST_RUNS_ROOT}/${EXTRA_RUN_ID}"

CONTAINER_LR01_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${LR01_RUN_ID}"
CONTAINER_FLAGSHIP_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${FLAGSHIP_RUN_ID}"
CONTAINER_FLAGSHIP_DIAG_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${FLAGSHIP_DIAG_RUN_ID}"
CONTAINER_EXTRA_RESULT_ROOT="${CONTAINER_RUNS_ROOT}/${EXTRA_RUN_ID}"

AUDIT_ARTIFACT_ROOT="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_AUDIT_ARTIFACT_ROOT:-${HOST_PROJECT_ROOT}/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_${STAMP}}"

TARGET_CUDA_VISIBLE_DEVICES="${STATEBUS_CUDA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-1}}"
TARGET_EMBED_DEVICE="${STATEBUS_LOCAL_API_NON_KV_EMBED_DEVICE:-${STATEBUS_EMBED_DEVICE:-cuda:0}}"
TARGET_TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
TARGET_PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
TARGET_CODEACT_SANDBOX_BACKEND="${STATEBUS_CODEACT_SANDBOX_BACKEND:-auto}"

STRICT_EXIT="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_STRICT_EXIT:-1}"
ALLOW_HOST_ACTIVATION_FAILURE="${STATEBUS_LOCAL_API_NON_KV_ALLOW_HOST_ACTIVATION_FAILURE:-0}"
DRY_RUN="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_DRY_RUN:-0}"
NO_TIMEOUTS="${STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS:-0}"

RUN_LR01="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_LR01:-1}"
RUN_FLAGSHIP="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_FLAGSHIP:-1}"
RUN_FLAGSHIP_FAILED_FAMILY_DIAG="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_FLAGSHIP_FAILED_FAMILY_DIAG:-1}"
RUN_EXTRAS="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_EXTRAS:-1}"

FOLLOWUP_ROLE_PATH_MODE="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE:-api}"
FOLLOWUP_EMBEDDING_MODE="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE:-local}"
FOLLOWUP_PERSISTENCE_PROFILE="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_PERSISTENCE_PROFILE:-audit_full}"

LR01_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_LR01_TIMEOUT_SECONDS:-2400}"
FLAGSHIP_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_TIMEOUT_SECONDS:-7200}"
FLAGSHIP_DIAG_TIMEOUT_SECONDS="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_DIAG_TIMEOUT_SECONDS:-7200}"

EXTRA_PYTEST_MODE="${STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE:-full_non_kv}"
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
  LR01_TIMEOUT_SECONDS=0
  FLAGSHIP_TIMEOUT_SECONDS=0
  FLAGSHIP_DIAG_TIMEOUT_SECONDS=0
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
    echo "[statebus-v2-local-api-followup] missing host activation script" >&2
    return 1
  fi
  set +u
  # shellcheck disable=SC1091
  source "${HOST_PROJECT_ROOT}/deploy/activate_statebus_host.sh"
  local exit_code=$?
  set -u
  return "$exit_code"
}

copy_phase_artifacts() {
  local phase_name="$1"
  local source_root="$2"
  local dest_root="${AUDIT_ARTIFACT_ROOT}/${phase_name}"
  mkdir -p "$dest_root"
  if [[ -d "${source_root}/artifacts" ]]; then
    cp -R "${source_root}/artifacts/." "$dest_root/"
  fi
}

optional_env_args=()

add_optional_env() {
  local name="$1"
  local value="${!name:-}"
  if [[ -n "$value" ]]; then
    optional_env_args+=(-e "${name}=${value}")
  fi
}

prepare_optional_env_args() {
  optional_env_args=()
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
}

run_followup_container_mode() {
  local phase_name="$1"
  local mode="$2"
  local run_id="$3"
  local host_phase_root="$4"
  local container_phase_root="$5"
  shift 5

  prepare_optional_env_args
  mkdir -p "$host_phase_root"

  set +e
  docker exec -i -u 0 \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_IN_CONTAINER=1 \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_MODE="$mode" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID="$run_id" \
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT" \
    -e STATEBUS_RESULT_ROOT="$container_phase_root" \
    -e STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS="$NO_TIMEOUTS" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE="$FOLLOWUP_ROLE_PATH_MODE" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE="$FOLLOWUP_EMBEDDING_MODE" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_PERSISTENCE_PROFILE="$FOLLOWUP_PERSISTENCE_PROFILE" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_LR01_TIMEOUT_SECONDS="$LR01_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_TIMEOUT_SECONDS="$FLAGSHIP_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_DIAG_TIMEOUT_SECONDS="$FLAGSHIP_DIAG_TIMEOUT_SECONDS" \
    -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
    -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
    -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM" \
    -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF" \
    -e STATEBUS_CODEACT_SANDBOX_BACKEND="$TARGET_CODEACT_SANDBOX_BACKEND" \
    -e TMPDIR="/tmp" \
    -e STATEBUS_SOCKET_DIR="/tmp" \
    "${optional_env_args[@]}" \
    "$CONTAINER_NAME" bash -lc 'bash -s' "$@" < "$0"
  local exit_code=$?
  set -e

  copy_phase_artifacts "$phase_name" "$host_phase_root"
  return "$exit_code"
}

run_extras_only() {
  prepare_optional_env_args
  mkdir -p "$HOST_EXTRA_RESULT_ROOT"

  set +e
  docker exec -i -u 0 \
    -e STATEBUS_LOCAL_API_NON_KV_IN_CONTAINER=1 \
    -e STATEBUS_PROJECT_ROOT="$CONTAINER_PROJECT_ROOT" \
    -e STATEBUS_RESULT_ROOT="$CONTAINER_EXTRA_RESULT_ROOT" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_ID="$EXTRA_RUN_ID" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_PYTEST_MODE="$EXTRA_PYTEST_MODE" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DESIGN_AUDIT="$EXTRA_RUN_DESIGN_AUDIT" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_DEV_BASELINES="$EXTRA_RUN_DEV_BASELINES" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_SHARED_MEMORY="$EXTRA_RUN_SHARED_MEMORY" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_CODEACT="$EXTRA_RUN_CODEACT" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_GRIDOPS="$EXTRA_RUN_GRIDOPS" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTRA_RUN_BENCHMARK_BALANCED="$EXTRA_RUN_BENCHMARK_BALANCED" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_SANDBOX_BACKEND="$CODEACT_ACCEPTANCE_SANDBOX_BACKEND" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_RUNS="$CODEACT_ACCEPTANCE_RUNS" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TARGET="$CODEACT_ACCEPTANCE_TARGET" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_MAX_REPAIR_ATTEMPTS="$CODEACT_MAX_REPAIR_ATTEMPTS" \
    -e STATEBUS_LOCAL_API_NON_KV_IMPORT_TIMEOUT_SECONDS="$IMPORT_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_NO_TIMEOUTS="$NO_TIMEOUTS" \
    -e STATEBUS_LOCAL_API_NON_KV_PY_COMPILE_TIMEOUT_SECONDS="$PY_COMPILE_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_PYTEST_TIMEOUT_SECONDS="$PYTEST_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_SMOKE_TIMEOUT_SECONDS="$SMOKE_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_PREFLIGHT_TIMEOUT_SECONDS="$PREFLIGHT_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_DESIGN_AUDIT_TIMEOUT_SECONDS="$DESIGN_AUDIT_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_FORMAL_TIMEOUT_SECONDS="$FORMAL_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_COMPARE_TIMEOUT_SECONDS="$COMPARE_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_CONTINUOUS_TIMEOUT_SECONDS="$CONTINUOUS_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_EXTERNAL_TIMEOUT_SECONDS="$EXTERNAL_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_SMOKE_TIMEOUT_SECONDS="$CODEACT_SMOKE_TIMEOUT_SECONDS" \
    -e STATEBUS_LOCAL_API_NON_KV_CODEACT_ACCEPTANCE_TIMEOUT_SECONDS="$CODEACT_ACCEPTANCE_TIMEOUT_SECONDS" \
    -e CUDA_VISIBLE_DEVICES="$TARGET_CUDA_VISIBLE_DEVICES" \
    -e STATEBUS_EMBED_DEVICE="$TARGET_EMBED_DEVICE" \
    -e TOKENIZERS_PARALLELISM="$TARGET_TOKENIZERS_PARALLELISM" \
    -e PYTORCH_CUDA_ALLOC_CONF="$TARGET_PYTORCH_CUDA_ALLOC_CONF" \
    -e STATEBUS_CODEACT_SANDBOX_BACKEND="$TARGET_CODEACT_SANDBOX_BACKEND" \
    -e TMPDIR="/tmp" \
    -e STATEBUS_SOCKET_DIR="/tmp" \
    "${optional_env_args[@]}" \
    "$CONTAINER_NAME" bash -lc 'bash -s' < "${HOST_PROJECT_ROOT}/scripts/run_v2_local_api_non_kv_full_suite.sh"
  local exit_code=$?
  set -e

  copy_phase_artifacts "extras" "$HOST_EXTRA_RESULT_ROOT"
  return "$exit_code"
}

write_combined_summary() {
  /usr/bin/python3 - \
    "$HOST_RESULT_ROOT" \
    "$AUDIT_ARTIFACT_ROOT" \
    "$BASE_CORE_RESULT_ROOT" \
    "$HOST_LR01_RESULT_ROOT/artifacts/summary.json" \
    "$HOST_FLAGSHIP_RESULT_ROOT/artifacts/summary.json" \
    "$HOST_FLAGSHIP_DIAG_RESULT_ROOT/artifacts/summary.json" \
    "$HOST_EXTRA_RESULT_ROOT/artifacts/summary.json" \
    <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

host_result_root = Path(sys.argv[1])
audit_artifact_root = Path(sys.argv[2])
base_core_result_root = Path(sys.argv[3])
lr01_summary_path = Path(sys.argv[4])
flagship_summary_path = Path(sys.argv[5])
flagship_diag_summary_path = Path(sys.argv[6])
extra_summary_path = Path(sys.argv[7])


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return payload if isinstance(payload, dict) else {"value": payload, "_path": str(path)}


phase_payloads = {
    "lr01": load_json(lr01_summary_path),
    "flagship": load_json(flagship_summary_path),
    "flagship_family_diag": load_json(flagship_diag_summary_path),
    "extras": load_json(extra_summary_path),
}

status_rows: list[dict[str, str]] = []
status_path = host_result_root / "status.tsv"
if status_path.exists():
    for index, line in enumerate(status_path.read_text(encoding="utf-8").splitlines()):
        if index == 0 or not line.strip():
            continue
        phase, exit_code, note = line.split("\t", 2)
        status_rows.append({"phase": phase, "exit_code": exit_code, "note": note})

combined = {
    "run_id": host_result_root.name,
    "base_core_result_root": str(base_core_result_root),
    "base_core_result_root_exists": base_core_result_root.exists(),
    "audit_artifact_root": str(audit_artifact_root),
    "phases": phase_payloads,
    "status_rows": status_rows,
    "failed_phase_count": sum(1 for row in status_rows if row["exit_code"] != "0"),
    "failed_phases": [row["phase"] for row in status_rows if row["exit_code"] != "0"],
    "notes": [
        "This follow-up suite reruns only the unstable or missing non-KV evidence.",
        "lr01 is rerun as a single serialized compare retry, not as repeat=3.",
        "flagship family diagnostics focus on incident_diagnosis_v2, long_doc_metric_replay_v1, and cross_period_financial_v1.",
        "extras are delegated to the existing non-KV extras-only in-container path.",
    ],
}

(host_result_root / "summary.json").write_text(
    json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

lines = [
    "# StateBus v2 local+api non-KV follow-up suite",
    "",
    f"- Base core result root: `{base_core_result_root}`",
    f"- Base core result root exists: `{base_core_result_root.exists()}`",
    f"- Audit artifact root: `{audit_artifact_root}`",
    f"- Failed phase count: `{combined['failed_phase_count']}`",
    "",
    "## Phase Status",
]
if status_rows:
    for row in status_rows:
        lines.append(f"- `{row['phase']}` exit `{row['exit_code']}`: {row['note']}")
else:
    lines.append("- none")

flagship_diag = phase_payloads.get("flagship_family_diag", {})
families = flagship_diag.get("failed_family_summaries", [])
if isinstance(families, list) and families:
    lines.extend(["", "## Flagship Failed Families"])
    for family in families:
        if not isinstance(family, dict):
            continue
        lines.append(
            f"- `{family.get('family_id', '')}` reasons `{family.get('stress_fail_reasons', [])}` "
            f"prompt_delta `{family.get('llm_prompt_delta_l2_vs_t2')}` "
            f"visible_saved `{family.get('prompt_visible_saved_by_state_ref_bytes')}`"
        )

lines.extend(["", "## Notes"])
for note in combined["notes"]:
    lines.append(f"- {note}")

(host_result_root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

if [[ "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_IN_CONTAINER:-0}" != "1" ]]; then
  cd "$HOST_PROJECT_ROOT"
  mkdir -p "$HOST_RESULT_ROOT" "$AUDIT_ARTIFACT_ROOT"
  printf 'phase\texit_code\tnote\n' > "${HOST_RESULT_ROOT}/status.tsv"

  if ! activate_host_env; then
    if [[ "$ALLOW_HOST_ACTIVATION_FAILURE" != "1" ]]; then
      echo "[statebus-v2-local-api-followup] host activation failed; set STATEBUS_LOCAL_API_NON_KV_ALLOW_HOST_ACTIVATION_FAILURE=1 to override" >&2
      exit 1
    fi
    echo "[statebus-v2-local-api-followup] warning: host activation failed; continuing because override is enabled" >&2
  fi

  cat > "${HOST_RESULT_ROOT}/README.host.txt" <<EOF
StateBus v2 local+api non-KV follow-up suite

Base core run id:
  ${BASE_CORE_RUN_ID}

Base core host result root:
  ${BASE_CORE_RESULT_ROOT}

Follow-up host result root:
  ${HOST_RESULT_ROOT}

Artifacts:
  lr01 follow-up: ${HOST_LR01_RESULT_ROOT}
  flagship rerun: ${HOST_FLAGSHIP_RESULT_ROOT}
  flagship family diagnostics: ${HOST_FLAGSHIP_DIAG_RESULT_ROOT}
  extras-only rerun: ${HOST_EXTRA_RESULT_ROOT}

Audit artifact root:
  ${AUDIT_ARTIFACT_ROOT}

Contract:
  - host env is activated first via source deploy/activate_statebus_host.sh
  - docker exec uses root inside the container
  - non-KV only; no local_vllm
  - lr01 rerun is single serialized compare retry, not repeat=3
  - extras are rerun without re-entering the comprehensive core wrapper
EOF

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[statebus-v2-local-api-followup] dry run"
    echo "base_core_result_root=${BASE_CORE_RESULT_ROOT}"
    echo "run_id=${RUN_ID}"
    echo "host_result_root=${HOST_RESULT_ROOT}"
    echo "audit_artifact_root=${AUDIT_ARTIFACT_ROOT}"
    echo "container=${CONTAINER_NAME}"
    echo "cuda_visible_devices=${TARGET_CUDA_VISIBLE_DEVICES}"
    echo "embed_device=${TARGET_EMBED_DEVICE}"
    echo "run_lr01=${RUN_LR01}"
    echo "run_flagship=${RUN_FLAGSHIP}"
    echo "run_flagship_failed_family_diag=${RUN_FLAGSHIP_FAILED_FAMILY_DIAG}"
    echo "run_extras=${RUN_EXTRAS}"
    echo "extra_pytest_mode=${EXTRA_PYTEST_MODE}"
    echo "no_timeouts=${NO_TIMEOUTS}"
    exit 0
  fi

  phase_exit_any=0

  if [[ "$RUN_LR01" == "1" ]]; then
    echo "[statebus-v2-local-api-followup] rerunning single lr01 compare stage: ${LR01_RUN_ID}"
    if run_followup_container_mode \
      "lr01" \
      "lr01" \
      "$LR01_RUN_ID" \
      "$HOST_LR01_RESULT_ROOT" \
      "$CONTAINER_LR01_RESULT_ROOT"
    then
      lr01_exit=0
    else
      lr01_exit=$?
      phase_exit_any=1
    fi
    printf 'lr01\t%s\t%s\n' "$lr01_exit" "single serialized formal compare retry for previous lr01 failure" >> "${HOST_RESULT_ROOT}/status.tsv"
  fi

  if [[ "$RUN_FLAGSHIP" == "1" ]]; then
    echo "[statebus-v2-local-api-followup] rerunning flagship ablation: ${FLAGSHIP_RUN_ID}"
    if run_followup_container_mode \
      "flagship" \
      "flagship" \
      "$FLAGSHIP_RUN_ID" \
      "$HOST_FLAGSHIP_RESULT_ROOT" \
      "$CONTAINER_FLAGSHIP_RESULT_ROOT"
    then
      flagship_exit=0
    else
      flagship_exit=$?
      phase_exit_any=1
    fi
    printf 'flagship\t%s\t%s\n' "$flagship_exit" "full flagship ablation rerun for fresh 6-family evidence" >> "${HOST_RESULT_ROOT}/status.tsv"
  fi

  if [[ "$RUN_FLAGSHIP_FAILED_FAMILY_DIAG" == "1" ]]; then
    echo "[statebus-v2-local-api-followup] running failed-family diagnostics: ${FLAGSHIP_DIAG_RUN_ID}"
    if run_followup_container_mode \
      "flagship_family_diag" \
      "flagship_family_diag" \
      "$FLAGSHIP_DIAG_RUN_ID" \
      "$HOST_FLAGSHIP_DIAG_RESULT_ROOT" \
      "$CONTAINER_FLAGSHIP_DIAG_RESULT_ROOT"
    then
      flagship_diag_exit=0
    else
      flagship_diag_exit=$?
      phase_exit_any=1
    fi
    printf 'flagship_family_diag\t%s\t%s\n' "$flagship_diag_exit" "incident/long_doc_metric/cross_period family-level reruns and T2 attribution diagnostics" >> "${HOST_RESULT_ROOT}/status.tsv"
  fi

  if [[ "$RUN_EXTRAS" == "1" ]]; then
    echo "[statebus-v2-local-api-followup] rerunning extras-only bundle: ${EXTRA_RUN_ID}"
    if run_extras_only; then
      extras_exit=0
    else
      extras_exit=$?
      phase_exit_any=1
    fi
    printf 'extras\t%s\t%s\n' "$extras_exit" "full non-KV extras-only rerun that was not reached in the interrupted full suite" >> "${HOST_RESULT_ROOT}/status.tsv"
  fi

  write_combined_summary

  echo "[statebus-v2-local-api-followup] combined host result root: ${HOST_RESULT_ROOT}"
  echo "[statebus-v2-local-api-followup] combined audit artifact root: ${AUDIT_ARTIFACT_ROOT}"

  if [[ "$STRICT_EXIT" == "1" && "$phase_exit_any" -ne 0 ]]; then
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
  echo "[statebus-v2-local-api-followup] warning: container activation failed; continuing with /usr/bin/python3" >&2
fi

RESULT_ROOT="$STATEBUS_RESULT_ROOT"
ARTIFACT_ROOT="$RESULT_ROOT/artifacts"
WORK_ROOT="$RESULT_ROOT/work"
STATUS_TSV="$ARTIFACT_ROOT/status.tsv"
SUMMARY_MD="$ARTIFACT_ROOT/summary.md"
SUMMARY_JSON="$ARTIFACT_ROOT/summary.json"
CONSOLE_LOG="$ARTIFACT_ROOT/console.log"
FOLLOWUP_MODE="${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_MODE:-}"

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
    /usr/bin/python3 - "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID}:${FOLLOWUP_MODE}:${label}" <<'PY'
import hashlib
import sys

print(hashlib.sha1(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  printf '/tmp/sbfu-%s.sock' "$digest"
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
    echo "[statebus-v2-local-api-followup] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-followup] timeout=${timeout_s}s"
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
  if [[ "$exit_code" -ne 0 ]]; then
    tail -n 80 "$log_path" || true
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
    echo "[statebus-v2-local-api-followup] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-followup] timeout=${timeout_s}s"
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
  if [[ "$exit_code" -ne 0 ]]; then
    tail -n 120 "$log_path" || true
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
  echo "[statebus-v2-local-api-followup] socket_path=${socket_path} len=${#socket_path}"
  if is_unlimited_timeout "$timeout_s"; then
    echo "[statebus-v2-local-api-followup] timeout=unlimited"
  else
    echo "[statebus-v2-local-api-followup] timeout=${timeout_s}s"
  fi
  start_s="$(date +%s)"
  set +e
  if is_unlimited_timeout "$timeout_s"; then
    /usr/bin/python3 -m v2.benchmark.live_runner \
      --suite "$suite" \
      --role-path-mode "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE:-api}" \
      --embedding-mode "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE:-local}" \
      --runtime-root "$runtime_root" \
      --workspace-root "$workspace_root" \
      --socket-path "$socket_path" \
      --suite-id "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID}-${stage}" \
      "$@" \
      > >(tee "$stdout_json") \
      2> >(tee "$log_path" >&2)
  else
    timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner \
      --suite "$suite" \
      --role-path-mode "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE:-api}" \
      --embedding-mode "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE:-local}" \
      --runtime-root "$runtime_root" \
      --workspace-root "$workspace_root" \
      --socket-path "$socket_path" \
      --suite-id "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID}-${stage}" \
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
  if [[ "$exit_code" -ne 0 ]]; then
    tail -n 120 "$log_path" || true
  fi
  return 0
}

write_phase_summary() {
  /usr/bin/python3 - "$STATUS_TSV" "$SUMMARY_MD" "$SUMMARY_JSON" "$FOLLOWUP_MODE" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

status_path = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
summary_json = Path(sys.argv[3])
followup_mode = sys.argv[4]
rows = list(csv.DictReader(status_path.open("r", encoding="utf-8"), delimiter="\t"))


def load_json(path_value: str) -> dict[str, Any]:
    if not path_value or path_value == "-":
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_parse_error": str(exc), "_path": str(path)}
    return payload if isinstance(payload, dict) else {"value": payload, "_path": str(path)}


payload_by_stage = {row["stage"]: load_json(row.get("artifact", "")) for row in rows}
failed = [row for row in rows if int(row.get("exit_code", "1")) != 0]
failed_required = [row for row in failed if row.get("required") == "1"]
key_metrics: dict[str, dict[str, Any]] = {}
failed_family_summaries: list[dict[str, Any]] = []

for stage, payload in payload_by_stage.items():
    if "formal_compare_latency_rerun_api_local_memfd" in stage:
        key_metrics[stage] = {
            "strict_equal_quality_comparison_valid": payload.get("strict_equal_quality_comparison_valid"),
            "quality_superiority_comparison_valid": payload.get("quality_superiority_comparison_valid"),
            "formal_superiority_claim_allowed": payload.get("formal_superiority_claim_allowed"),
            "serialized_latency_superiority_claim_allowed": payload.get("serialized_latency_superiority_claim_allowed"),
            "claim_restriction": (payload.get("metadata") or {}).get("claim_restriction")
            if isinstance(payload.get("metadata"), dict)
            else None,
            "api_task_ms_delta": payload.get("api_debug_task_ms_delta"),
            "api_prompt_tokens_delta": payload.get("api_prompt_tokens_delta"),
            "api_llm_total_tokens_delta": payload.get("api_llm_total_tokens_delta"),
        }
    elif "flagship_ablation_api_local" in stage:
        stress = payload.get("non_text_state_stress_summary", {})
        if isinstance(stress, dict):
            key_metrics[stage] = {
                "stress_family_count": stress.get("stress_family_count"),
                "stress_pass_family_count": stress.get("stress_pass_family_count"),
                "stress_fail_family_count": stress.get("stress_fail_family_count"),
                "stress_failure_reason_counts": stress.get("stress_failure_reason_counts"),
                "total_llm_prompt_saved_by_state_ref_bytes": stress.get("total_llm_prompt_saved_by_state_ref_bytes"),
                "total_prompt_visible_saved_by_state_ref_bytes": stress.get("total_prompt_visible_saved_by_state_ref_bytes"),
            }
    elif "flagship_failed_family_diagnostics" in stage:
        failed_family_summaries = list(payload.get("failed_family_summaries", [])) if isinstance(payload, dict) else []
        key_metrics[stage] = {
            "family_count": payload.get("family_count"),
            "failed_family_count": payload.get("failed_family_count"),
            "failed_family_ids": payload.get("failed_family_ids"),
            "stress_failure_reason_counts": (payload.get("stress_summary") or {}).get("stress_failure_reason_counts")
            if isinstance(payload.get("stress_summary"), dict)
            else None,
        }

summary = {
    "mode": followup_mode,
    "stage_count": len(rows),
    "failed_stage_count": len(failed),
    "failed_required_stage_count": len(failed_required),
    "failed_stages": [row["stage"] for row in failed],
    "key_metrics": key_metrics,
    "failed_family_summaries": failed_family_summaries,
}

summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    f"# StateBus v2 non-KV follow-up: {followup_mode}",
    "",
    f"- Stage count: `{len(rows)}`",
    f"- Failed stage count: `{len(failed)}`",
    f"- Failed required stage count: `{len(failed_required)}`",
    "",
    "## Failed Stages",
]
if failed:
    for row in failed:
        lines.append(f"- `{row['stage']}` exit `{row['exit_code']}`")
else:
    lines.append("- none")

if failed_family_summaries:
    lines.extend(["", "## Failed Families"])
    for family in failed_family_summaries:
        if not isinstance(family, dict):
            continue
        lines.append(
            f"- `{family.get('family_id', '')}` reasons `{family.get('stress_fail_reasons', [])}` "
            f"quality `{family.get('quality_headline_eligible')}` replay `{family.get('replay_headline_eligible')}`"
        )

lines.extend(["", "## Key Metrics"])
if key_metrics:
    for stage, metrics in key_metrics.items():
        lines.append(f"### {stage}")
        for key, value in metrics.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
else:
    lines.append("- none")

summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

echo "[statebus-v2-local-api-followup] mode=${FOLLOWUP_MODE}"
echo "[statebus-v2-local-api-followup] result_root=${RESULT_ROOT}"
echo "[statebus-v2-local-api-followup] role_path_mode=${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE:-api}"
echo "[statebus-v2-local-api-followup] embedding_mode=${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE:-local}"
echo "[statebus-v2-local-api-followup] persistence_profile=${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_PERSISTENCE_PROFILE:-audit_full}"
echo "[statebus-v2-local-api-followup] CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
echo "[statebus-v2-local-api-followup] STATEBUS_EMBED_DEVICE=${STATEBUS_EMBED_DEVICE:-}"

case "$FOLLOWUP_MODE" in
  lr01)
    export STATEBUS_COMPARATOR_SERIALIZED_REPEAT_COUNT=1
    export STATEBUS_COMPARATOR_SERIALIZED_REPEAT_INDEX=1
    export STATEBUS_COMPARATOR_TIMING_CONTRACT="serialized_formal_compare_latency_rerun_v1"
    run_live_stage \
      "lr01_14_formal_compare_latency_rerun_api_local_memfd" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_LR01_TIMEOUT_SECONDS:-2400}" \
      1 \
      "compare" \
      --benchmark-tier formal \
      --state-pool-mode memfd
    unset STATEBUS_COMPARATOR_SERIALIZED_REPEAT_INDEX
    unset STATEBUS_COMPARATOR_SERIALIZED_REPEAT_COUNT
    unset STATEBUS_COMPARATOR_TIMING_CONTRACT
    ;;
  flagship)
    run_live_stage \
      "r01_13_flagship_ablation_api_local" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_TIMEOUT_SECONDS:-7200}" \
      1 \
      "flagship-ablation" \
      --benchmark-tier dev
    ;;
  flagship_family_diag)
    diag_script="${WORK_ROOT}/flagship_failed_family_diagnostics.py"
    cat > "$diag_script" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from v2.benchmark.continuous_runner import (
    run_continuous_benchmark_suite,
    run_continuous_text_semantic_selection_family,
)
from v2.benchmark.continuous_task_family import load_continuous_task_family
from v2.benchmark.flagship_ablation import _family_evidence, _non_text_state_stress_summary
from v2.benchmark.reporting import family_report_to_dict, suite_report_to_dict


def family_dir(base: Path, family_id: str) -> Path:
    mapping = {
        "incident_diagnosis_v2": base / "incident_diagnosis",
        "long_doc_metric_replay_v1": base / "long_doc_metric_replay",
        "cross_period_financial_v1": base / "cross_period_financial",
    }
    return mapping[family_id]


output_root = Path(sys.argv[1])
run_id = sys.argv[2]
project_root = Path(sys.argv[3])
persistence_profile = sys.argv[4]
role_path_mode = sys.argv[5]
embedding_mode = sys.argv[6]

family_ids = [
    "incident_diagnosis_v2",
    "long_doc_metric_replay_v1",
    "cross_period_financial_v1",
]
continuous_family_ids = {"incident_diagnosis_v2"}
sample_root = project_root / "v2" / "benchmark" / "samples" / "continuous_task_families"
diag_root = output_root / "flagship_family_diagnostics"

continuous_evidence: list[dict[str, object]] = []
replay_evidence: list[dict[str, object]] = []
raw_family_outputs: list[dict[str, object]] = []

for index, family_id in enumerate(family_ids, start=1):
    family = load_continuous_task_family(family_dir(sample_root, family_id))
    group = "continuous" if family_id in continuous_family_ids else "continuous_replay"
    group_root = diag_root / group / family_id
    suite = run_continuous_benchmark_suite(
        family=family,
        workspace_root=group_root / "statebus" / "workspaces",
        runtime_root=group_root / "statebus" / "runtime",
        socket_path=Path(f"/tmp/fd{index}.sock"),
        suite_id=f"{run_id}-{family_id}-statebus",
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        persistence_profile=persistence_profile,
    )
    t2 = run_continuous_text_semantic_selection_family(
        family=family,
        workspace_root=group_root / "t2" / "workspaces",
        runtime_root=group_root / "t2" / "runtime",
        socket_path=Path(f"/tmp/ft{index}.sock"),
        suite_id=f"{run_id}-{family_id}-t2",
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        persistence_profile=persistence_profile,
    )
    evidence = _family_evidence(family_report=suite, text_semantic_report=t2)
    if group == "continuous":
        continuous_evidence.append(evidence)
    else:
        replay_evidence.append(evidence)
    raw_family_outputs.append(
        {
            "family_id": family_id,
            "group": group,
            "suite": suite_report_to_dict(suite),
            "text_same_semantic_selection": family_report_to_dict(t2),
            "evidence": evidence,
        }
    )

stress_summary = _non_text_state_stress_summary(
    continuous_evidence=continuous_evidence,
    continuous_replay_evidence=replay_evidence,
)
stress_by_family = {
    str(item.get("family_id", "")): dict(item)
    for item in stress_summary.get("families", [])
    if isinstance(item, dict)
}

failed_family_summaries: list[dict[str, object]] = []
for item in raw_family_outputs:
    evidence = dict(item["evidence"])
    stress = stress_by_family.get(item["family_id"], {})
    suite = dict(item["suite"])
    family_summary = {
        "family_id": item["family_id"],
        "group": item["group"],
        "headline_scope": evidence.get("headline_scope"),
        "quality_headline_eligible": evidence.get("quality_headline_eligible"),
        "replay_headline_eligible": evidence.get("replay_headline_eligible"),
        "stress_pass": stress.get("stress_pass"),
        "stress_fail_reasons": stress.get("stress_fail_reasons", []),
        "interpretation": stress.get("interpretation"),
        "llm_prompt_delta_l2_vs_t2": stress.get("llm_prompt_delta_l2_vs_t2"),
        "prompt_visible_delta_l2_vs_t2": stress.get("prompt_visible_delta_l2_vs_t2"),
        "llm_prompt_saved_by_state_ref_bytes": stress.get("llm_prompt_saved_by_state_ref_bytes"),
        "prompt_visible_saved_by_state_ref_bytes": stress.get("prompt_visible_saved_by_state_ref_bytes"),
        "l3_quality_floor_pass_count": evidence.get("l3_memory_replay", {}).get("quality_floor_pass_count"),
        "l3_validated_replay_count": evidence.get("l3_memory_replay", {}).get("validated_replay_count"),
        "l3_exact_replay_count": evidence.get("l3_memory_replay", {}).get("exact_replay_count"),
        "l3_skipped_step_count": evidence.get("l3_memory_replay", {}).get("skipped_step_count"),
        "replay_gate_reason": suite.get("replay_gate_reason"),
        "statebus_suite_report_path": suite.get("report_path"),
        "text_same_semantic_selection_report_path": dict(item["text_same_semantic_selection"]).get("report_path"),
    }
    if not bool(stress.get("stress_pass", False)):
        failed_family_summaries.append(family_summary)

payload = {
    "schema_version": "statebus.non_kv_flagship_failed_family_followup.v1",
    "suite_id": run_id,
    "role_path_mode": role_path_mode,
    "embedding_mode": embedding_mode,
    "persistence_profile": persistence_profile,
    "family_count": len(raw_family_outputs),
    "failed_family_count": len(failed_family_summaries),
    "failed_family_ids": [item["family_id"] for item in failed_family_summaries],
    "stress_summary": stress_summary,
    "failed_family_summaries": failed_family_summaries,
    "families": raw_family_outputs,
}

markdown_lines = [
    "# StateBus v2 non-KV flagship failed-family follow-up",
    "",
    f"- suite_id: `{run_id}`",
    f"- role_path_mode: `{role_path_mode}`",
    f"- embedding_mode: `{embedding_mode}`",
    f"- failed_family_count: `{len(failed_family_summaries)}`",
    "",
    "## Failed Families",
]
for family in failed_family_summaries:
    markdown_lines.append(
        f"- `{family['family_id']}` reasons `{family['stress_fail_reasons']}` "
        f"prompt_delta `{family['llm_prompt_delta_l2_vs_t2']}` "
        f"visible_saved `{family['prompt_visible_saved_by_state_ref_bytes']}`"
    )
if not failed_family_summaries:
    markdown_lines.append("- none")

(diag_root / "summary.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
    run_json_stage \
      "flagship_failed_family_diagnostics" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_FLAGSHIP_DIAG_TIMEOUT_SECONDS:-7200}" \
      1 \
      /usr/bin/python3 "$diag_script" \
      "$WORK_ROOT" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_RUN_ID}" \
      "$STATEBUS_PROJECT_ROOT" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_PERSISTENCE_PROFILE:-audit_full}" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_ROLE_PATH_MODE:-api}" \
      "${STATEBUS_LOCAL_API_NON_KV_FOLLOWUP_EMBEDDING_MODE:-local}"
    ;;
  *)
    echo "[statebus-v2-local-api-followup] unsupported mode: ${FOLLOWUP_MODE}" >&2
    OVERALL_FAILURE=1
    ;;
esac

write_phase_summary

if [[ "$OVERALL_FAILURE" -ne 0 ]]; then
  exit 1
fi
exit 0
