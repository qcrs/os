#!/usr/bin/env bash
set -euo pipefail

# P1 is an additive post-full suite.  It does not append stages to, mutate, or
# reinterpret the original 16-stage full-matrix result.

usage() {
  cat <<'EOF'
Usage: bash scripts/run_v2_post_full_p1_qwen3_container.sh

Required:
  STATEBUS_P1_SOURCE_FULL_RESULT_ROOT=/statebus/runs/full_qwen3_<stamp>

Optional:
  STATEBUS_P1_RESULT_ROOT=/statebus/runs/post_full_p1_qwen3_<stamp>
  STATEBUS_P1_RUN_BACKEND_MATRIX=1
  STATEBUS_P1_RUN_FLAGSHIP=1
  STATEBUS_P1_RUN_PREFIX=1
  STATEBUS_P1_PREFIX_CLEAN_SERVICE_COMMAND='your restart/reset command'
  STATEBUS_P1_PREFIX_REQUIRE_CLEAN=1
  STATEBUS_P1_PREFIX_REPEATS=4
  STATEBUS_P1_LLM_CONFIG_FILE=/path/to/statebus_llm.local_vllm.yaml
  STATEBUS_P1_ALLOW_REPAIRED_SOURCE=1
  STATEBUS_P1_REPAIRED_PYTEST_LOG=/statebus/runs/full_qwen3_<repair-stamp>/logs/01_pytest_v2.log

The prefix clean-service command is intentionally user supplied.  The runner
does not assume Docker ownership or a particular vLLM supervisor.

The repaired-source mode is opt-in. It only accepts a complete 16-stage source
whose sole failed stage is 01_pytest_v2, plus a later complete tests/v2 pass
log from the repaired worktree. The original source remains immutable.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

if [[ ! -f /usr/local/bin/activate_statebus_container.sh ]]; then
  echo "[statebus-p1] container activation script is missing; run inside statebus-dev-qcrs" >&2
  exit 2
fi

CONTAINER_USER_HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
if [[ -n "$CONTAINER_USER_HOME" ]]; then
  export HOME="$CONTAINER_USER_HOME"
  export NPM_CONFIG_PREFIX="${CONTAINER_USER_HOME}/.local"
fi

# shellcheck disable=SC1091
source /usr/local/bin/activate_statebus_container.sh

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/statebus/project}"
cd "$PROJECT_ROOT"

SOURCE_ROOT="${STATEBUS_P1_SOURCE_FULL_RESULT_ROOT:?STATEBUS_P1_SOURCE_FULL_RESULT_ROOT is required}"
SOURCE_SUMMARY="${SOURCE_ROOT}/summary.json"
if [[ ! -f "$SOURCE_SUMMARY" ]]; then
  echo "[statebus-p1] source full summary is missing: $SOURCE_SUMMARY" >&2
  exit 2
fi

STAMP="${STATEBUS_P1_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${STATEBUS_P1_RESULT_ROOT:-/statebus/runs/post_full_p1_qwen3_${STAMP}}"
STAGE_ROOT="${RESULT_ROOT}/stages"
LOG_ROOT="${RESULT_ROOT}/logs"
STATUS_FILE="${RESULT_ROOT}/status.tsv"
RUN_LOG="${RESULT_ROOT}/run.log"
SOCKET_PATH="/tmp/sbp1-${STAMP}.sock"
SOURCE_LLM_CONFIG="${STATEBUS_P1_LLM_CONFIG_FILE:-${SOURCE_ROOT}/statebus_llm.local_vllm.yaml}"
LLM_CONFIG="${RESULT_ROOT}/statebus_llm.local_vllm.yaml"
SOURCE_ELIGIBILITY="${RESULT_ROOT}/source_eligibility.json"

export STATEBUS_LOCAL_VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
export STATEBUS_LOCAL_VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
export STATEBUS_VLLM_SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
export STATEBUS_EMBEDDING_MODE=local
export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:1}"
export STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
export STATEBUS_PREFIX_ALIGNMENT_MODE="${STATEBUS_PREFIX_ALIGNMENT_MODE:-shared_evidence_prefix}"
export STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED="${STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED:-1}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export STATEBUS_LLM_CONFIG_FILE="$LLM_CONFIG"

mkdir -p "$RESULT_ROOT" "$STAGE_ROOT" "$LOG_ROOT"
: > "$STATUS_FILE"
touch "$RUN_LOG"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$RUN_LOG"
}

record_status() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$STATUS_FILE"
}

write_source_eligibility() {
  python3 - "$SOURCE_SUMMARY" "$SOURCE_ELIGIBILITY" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

source_summary, output_path = (Path(item) for item in sys.argv[1:])
payload = json.loads(source_summary.read_text(encoding="utf-8"))
allow_repaired = os.environ.get("STATEBUS_P1_ALLOW_REPAIRED_SOURCE", "0") == "1"
repaired_log_text = os.environ.get("STATEBUS_P1_REPAIRED_PYTEST_LOG", "").strip()

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"source full matrix is not eligible: {message}")

def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

require(payload.get("matrix_complete") is True, f"matrix_complete={payload.get('matrix_complete')!r}")
require(
    int(payload.get("continuous_max_rounds", 0) or 0) == 0,
    "continuous_max_rounds must be 0",
)

if payload.get("all_stages_passed") is True and payload.get("full_matrix_passed") is True:
    eligibility = {
        "mode": "strict_full_matrix",
        "source_summary_sha256": file_sha256(source_summary),
        "source_summary": str(source_summary),
    }
elif allow_repaired:
    stages = payload.get("stages", [])
    require(isinstance(stages, list), "stages is not a list")
    stage_statuses = {
        str(item.get("stage", "")): str(item.get("status", ""))
        for item in stages
        if isinstance(item, dict)
    }
    expected_stages = {
        "00_preflight",
        "01_pytest_v2",
        "02_compare_full",
        "03_replay_full",
        "04_continuous_csv_full",
        "05_continuous_cross_full",
        "06_formal_full",
        "07_formal_subprocess_uds_full",
        "08_genericity_holdout",
        "09_prefix_shared",
        "10_prefix_independent",
        "11_carrier_compare_full",
        "12_compare_repeat_2",
        "13_compare_repeat_3",
        "14_latency_repeat_aggregate",
        "15_tag_baseline_audit",
    }
    require(set(stage_statuses) == expected_stages, "stage registry mismatch")
    require(stage_statuses.get("01_pytest_v2") == "fail", "only pytest may require repair")
    non_pytest_failures = {
        stage: status
        for stage, status in stage_statuses.items()
        if stage != "01_pytest_v2" and status != "pass"
    }
    require(not non_pytest_failures, f"non-pytest stages are not pass: {non_pytest_failures}")
    repaired_log = Path(repaired_log_text)
    require(repaired_log_text and repaired_log.is_file(), "repaired pytest log is missing")
    repaired_contents = repaired_log.read_text(encoding="utf-8", errors="replace")
    pass_matches = re.findall(r"^(\d+) passed(?:, \d+ warnings)? in .+$", repaired_contents, flags=re.MULTILINE)
    require(pass_matches, "repaired pytest log has no passing pytest summary")
    require(int(pass_matches[-1]) >= 320, f"repaired pytest pass count is {pass_matches[-1]}")
    require(
        not re.search(r"^(FAILED|ERROR) ", repaired_contents, flags=re.MULTILINE),
        "repaired pytest log contains failed or error tests",
    )
    require(
        repaired_log.stat().st_mtime_ns >= source_summary.stat().st_mtime_ns,
        "repaired pytest evidence predates source summary",
    )
    eligibility = {
        "mode": "repaired_pytest_only",
        "source_summary": str(source_summary),
        "source_summary_sha256": file_sha256(source_summary),
        "source_stage_statuses": stage_statuses,
        "repaired_pytest_log": str(repaired_log),
        "repaired_pytest_log_sha256": file_sha256(repaired_log),
        "repaired_pytest_pass_count": int(pass_matches[-1]),
        "claim_boundary": (
            "The source full matrix remains failed at its original pytest stage. "
            "P1 admission relies on later tests/v2 repair evidence; all 15 source "
            "model and evaluation stages were already pass."
        ),
    }
else:
    raise SystemExit(
        "source requires all_stages_passed=true and full_matrix_passed=true; "
        "set STATEBUS_P1_ALLOW_REPAIRED_SOURCE=1 with repaired pytest evidence "
        "only for a pytest-only source failure"
    )

output_path.write_text(json.dumps(eligibility, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(eligibility, indent=2, sort_keys=True))
PY
}

verify_stage() {
  local kind="$1"
  local artifact="$2"
  python3 - "$kind" "$artifact" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

kind, artifact = sys.argv[1:]
payload = json.loads(Path(artifact).read_text(encoding="utf-8"))

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{kind} gate failed: {message}")

if kind == "backend":
    require(payload.get("schema_version") == "statebus.v2_backend_matrix.v1", "schema")
    require(payload.get("overall_ok") is True, "matrix validation")
    entries = payload.get("entries", [])
    require(len(entries) == 3, "backend variant coverage")
    require(all(item.get("validation", {}).get("ok") is True for item in entries), "backend entry validation")
elif kind == "flagship":
    require(payload.get("schema_version") == "statebus.non_text_flagship_ablation.v1", "schema")
    contracts = payload.get("baseline_contracts", [])
    require(any(item.get("id") == "T2_text_same_semantic_selection" for item in contracts), "T2 control missing")
    require(isinstance(payload.get("fixed_answer_evidence"), dict), "fixed ladder evidence missing")
    require(isinstance(payload.get("non_text_state_stress_summary"), dict), "StateRef stress summary missing")
elif kind == "prefix":
    require(payload.get("ok") is True, "pair parity")
    require(int(payload.get("repeat_count", 0)) >= 4, "repeat coverage")
    require(payload.get("both_orders_present") is True, "AB/BA coverage")
    require(payload.get("all_completion_contracts_valid") is True, "completion contract parity")
    require(int(payload.get("evidence_file_count", 0)) >= 2, "two-corpus coverage")
    require(payload.get("clean_service_all_ready") is True, "clean-service readiness")
    if os.environ.get("STATEBUS_P1_PREFIX_REQUIRE_CLEAN", "0") == "1":
        require(payload.get("clean_service_requested") is True, "clean-service hook was not used")
else:
    raise SystemExit(f"unknown stage kind: {kind}")
PY
}

run_backend_stage() {
  local stage_id="16_backend_matrix"
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local artifact="${stage_dir}/stdout.json"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"
  mkdir -p "${stage_dir}/workspaces" "${stage_dir}/runtime"
  rm -f "$SOCKET_PATH"
  log "START ${stage_id}"
  if python3 -m v2.benchmark.backend_matrix \
      --output "$artifact" \
      --workspace-root "${stage_dir}/workspaces" \
      --runtime-root "${stage_dir}/runtime" \
      --socket-path "$SOCKET_PATH" \
      --suite-id "post-full-${stage_id}-${STAMP}" \
      --role-path-mode local_vllm \
      --embedding-mode local \
      --persistence-profile audit_full \
      > "${stage_dir}/command.stdout.log" 2> "$stderr_log" \
      && python3 -m json.tool "$artifact" > /dev/null \
      && verify_stage backend "$artifact"; then
    record_status "$stage_id" pass "$artifact"
    log "PASS  ${stage_id}"
  else
    record_status "$stage_id" fail "$stderr_log"
    log "FAIL  ${stage_id}; inspect ${stderr_log} and ${artifact}"
  fi
}

run_flagship_stage() {
  local stage_id="17_flagship_refresh"
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local artifact="${stage_dir}/stdout.json"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"
  mkdir -p "${stage_dir}/workspaces" "${stage_dir}/runtime"
  rm -f "$SOCKET_PATH"
  log "START ${stage_id}"
  if python3 -m v2.benchmark.live_runner \
      --suite flagship-ablation \
      --role-path-mode local_vllm \
      --embedding-mode local \
      --persistence-profile audit_full \
      --workspace-root "${stage_dir}/workspaces" \
      --runtime-root "${stage_dir}/runtime" \
      --socket-path "$SOCKET_PATH" \
      --suite-id "post-full-${stage_id}-${STAMP}" \
      > "$artifact" 2> "$stderr_log" \
      && python3 -m json.tool "$artifact" > /dev/null \
      && verify_stage flagship "$artifact"; then
    record_status "$stage_id" pass "$artifact"
    log "PASS  ${stage_id}"
  else
    record_status "$stage_id" fail "$stderr_log"
    log "FAIL  ${stage_id}; inspect ${stderr_log} and ${artifact}"
  fi
}

run_prefix_stage() {
  local stage_id="18_prefix_parity_clean_repeats"
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local artifact="${stage_dir}/repeat_summary.json"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"
  local clean_command="${STATEBUS_P1_PREFIX_CLEAN_SERVICE_COMMAND:-}"
  local -a prefix_args
  prefix_args=(
    --output-root "$stage_dir"
    --repeats "${STATEBUS_P1_PREFIX_REPEATS:-4}"
    --max-tokens "${STATEBUS_P1_PREFIX_MAX_TOKENS:-64}"
    --base-url "$STATEBUS_LOCAL_VLLM_BASE_URL"
    --health-url "${STATEBUS_P1_PREFIX_HEALTH_URL:-http://127.0.0.1:53334/health}"
    --metrics-url "${STATEBUS_P1_PREFIX_METRICS_URL:-http://127.0.0.1:53334/metrics}"
    --model "$STATEBUS_LOCAL_VLLM_MODEL"
    --evidence-file v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md
    --evidence-file v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md
  )
  if [[ -n "$clean_command" ]]; then
    prefix_args+=(--clean-service-command "$clean_command")
  fi
  mkdir -p "$stage_dir"
  rm -f "$SOCKET_PATH"
  log "START ${stage_id}"
  if python3 scripts/run_vllm_prefix_alignment_repeats.py "${prefix_args[@]}" \
      > "${stage_dir}/command.stdout.log" 2> "$stderr_log" \
      && python3 -m json.tool "$artifact" > /dev/null \
      && verify_stage prefix "$artifact"; then
    record_status "$stage_id" pass "$artifact"
    log "PASS  ${stage_id}"
  else
    record_status "$stage_id" fail "$stderr_log"
    log "FAIL  ${stage_id}; inspect ${stderr_log} and ${artifact}"
  fi
}

if [[ ! -f "$SOURCE_LLM_CONFIG" ]]; then
  echo "[statebus-p1] compatible local-vLLM config is missing: $SOURCE_LLM_CONFIG" >&2
  exit 2
fi
if ! write_source_eligibility > "${RESULT_ROOT}/source_eligibility.stdout.json"; then
  echo "[statebus-p1] source eligibility validation failed" >&2
  exit 2
fi
cp "$SOURCE_SUMMARY" "${RESULT_ROOT}/source_full_summary.json"
if [[ "${STATEBUS_P1_ALLOW_REPAIRED_SOURCE:-0}" == "1" ]]; then
  cp "${STATEBUS_P1_REPAIRED_PYTEST_LOG:?STATEBUS_P1_REPAIRED_PYTEST_LOG is required in repaired-source mode}" \
    "${RESULT_ROOT}/repaired_pytest_v2.log"
fi
cp "$SOURCE_LLM_CONFIG" "$LLM_CONFIG"
{
  printf 'source_result_root=%s\n' "$SOURCE_ROOT"
  printf 'source_summary=%s\n' "$SOURCE_SUMMARY"
  printf 'source_eligibility=%s\n' "$SOURCE_ELIGIBILITY"
  printf 'repaired_pytest_log=%s\n' "${STATEBUS_P1_REPAIRED_PYTEST_LOG:-}"
  printf 'source_llm_config=%s\n' "$SOURCE_LLM_CONFIG"
  printf 'git_revision=%s\n' "$(git rev-parse HEAD)"
  git status --short
} > "${RESULT_ROOT}/manifest.txt"

log "StateBus Qwen3 P1 post-full suite"
log "source_full_result=${SOURCE_ROOT}"
log "result_root=${RESULT_ROOT}"

if [[ "${STATEBUS_P1_RUN_BACKEND_MATRIX:-1}" == "1" ]]; then
  run_backend_stage
else
  record_status "16_backend_matrix" skipped "STATEBUS_P1_RUN_BACKEND_MATRIX=0"
fi
if [[ "${STATEBUS_P1_RUN_FLAGSHIP:-1}" == "1" ]]; then
  run_flagship_stage
else
  record_status "17_flagship_refresh" skipped "STATEBUS_P1_RUN_FLAGSHIP=0"
fi
if [[ "${STATEBUS_P1_RUN_PREFIX:-1}" == "1" ]]; then
  run_prefix_stage
else
  record_status "18_prefix_parity_clean_repeats" skipped "STATEBUS_P1_RUN_PREFIX=0"
fi

python3 - "$RESULT_ROOT" "$STATUS_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

result_root = Path(sys.argv[1])
status_file = Path(sys.argv[2])
stages = []
for line in status_file.read_text(encoding="utf-8").splitlines():
    stage, status, artifact = line.split("\t", 2)
    stages.append({"stage": stage, "status": status, "artifact": artifact})
payload = {
    "schema_version": "statebus.v2_post_full_p1_summary.v1",
    "execution_scope": "post_full_p1_extension",
    "source_full_summary": str(result_root / "source_full_summary.json"),
    "source_eligibility": str(result_root / "source_eligibility.json"),
    "claim_boundary": (
        "additive P1 evidence only; source 16-stage full matrix remains immutable; "
        "prefix evidence is engine-local reuse only and does not claim KV tensor transfer"
    ),
    "stages": stages,
    "all_stages_passed": bool(stages) and all(item["status"] == "pass" for item in stages),
    "completed_stage_count": len(stages),
}
(result_root / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY
