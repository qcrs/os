#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/v2_diagnostics/run_v2_local_vllm_audit_gpu1.sh [--all|--preflight|--adaptive|--llm-codeact|--adaptive-matrix|--formal|--compare|--replay|--negative]

Runs the v2 benchmark from the formal statebus container. The default is --all:
preflight, adaptive-agent smoke, Runtime-integrated LLM CodeAct smoke, a small
adaptive mode matrix, formal StateBus benchmark, formal text-vs-StateBus
comparison, continuous replay, and replay-negative audit.

Environment:
  STATEBUS_V2_CONTAINER_NAME       Container name (default: statebus-dev-qcrs)
  STATEBUS_CUDA_VISIBLE_DEVICES    Physical GPU index (default: 1)
  STATEBUS_EMBED_DEVICE            Device inside the container (default: cuda:0)
  STATEBUS_EMBED_MIN_FREE_MB       Required free GPU memory (default: 2048)
  STATEBUS_V2_LOCAL_AUDIT_RUN_ID   Reuse or name a result bundle
  STATEBUS_V2_LOCAL_AUDIT_MAX_CASES  Limit formal/compare cases for diagnostics
  STATEBUS_V2_FORMAL_TIMEOUT_S     Formal-stage timeout (default: 7200)
  STATEBUS_V2_COMPARE_TIMEOUT_S    Compare-stage timeout (default: 7200)
  STATEBUS_V2_REPLAY_TIMEOUT_S     Replay-stage timeout (default: 3600)
  STATEBUS_V2_NEGATIVE_TIMEOUT_S   Negative-audit timeout (default: 600)
  STATEBUS_V2_ADAPTIVE_TIMEOUT_S   Strict adaptive-stage timeout (default: 600)
  STATEBUS_V2_CODEACT_TIMEOUT_S    Runtime CodeAct-stage timeout (default: 600)
  STATEBUS_V2_ADAPTIVE_MATRIX_TIMEOUT_S  Small adaptive matrix timeout (default: 900)

Set STATEBUS_EMBED_DEVICE=cpu explicitly only when GPU1 cannot spare memory.
That run is useful for functional validation but not GPU-latency evidence.
EOF
}

selection="${1:---all}"
case "$selection" in
  --all|--preflight|--adaptive|--llm-codeact|--adaptive-matrix|--formal|--compare|--replay|--negative) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
container_name="${STATEBUS_V2_CONTAINER_NAME:-statebus-dev-qcrs}"
gpu_index="${STATEBUS_CUDA_VISIBLE_DEVICES:-1}"
embedding_device="${STATEBUS_EMBED_DEVICE:-cuda:0}"
if [[ "$embedding_device" == "auto" ]]; then
  embedding_device="cuda:0"
fi
minimum_free_mb="${STATEBUS_EMBED_MIN_FREE_MB:-2048}"
max_cases="${STATEBUS_V2_LOCAL_AUDIT_MAX_CASES:-0}"
run_id="${STATEBUS_V2_LOCAL_AUDIT_RUN_ID:-v2_local_vllm_audit_$(date +%Y%m%d_%H%M%S)}"
host_result_root="${STATEBUS_HOST_RUNS_ROOT:-$HOME/statebus/runs}/${run_id}"
container_result_root="/statebus/runs/${run_id}"

if [[ ! "$gpu_index" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_CUDA_VISIBLE_DEVICES must be one physical GPU index, got %q\n' "$gpu_index" >&2
  exit 2
fi
if [[ ! "$minimum_free_mb" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_EMBED_MIN_FREE_MB must be an integer, got %q\n' "$minimum_free_mb" >&2
  exit 2
fi
if [[ ! "$max_cases" =~ ^[0-9]+$ ]]; then
  printf 'STATEBUS_V2_LOCAL_AUDIT_MAX_CASES must be an integer, got %q\n' "$max_cases" >&2
  exit 2
fi
if ! docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null | grep -qx true; then
  printf 'container is not running: %s\n' "$container_name" >&2
  exit 2
fi

if [[ "$embedding_device" == cuda:* && "$minimum_free_mb" != "0" ]]; then
  gpu_memory_report=""
  set +e
  gpu_memory_report="$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null)"
  nvidia_status=$?
  set -e
  if [[ "$nvidia_status" -ne 0 ]]; then
    set +e
    gpu_memory_report="$(docker exec "$container_name" nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null)"
    nvidia_status=$?
    set -e
  fi
  if [[ "$nvidia_status" -ne 0 ]]; then
    printf 'cannot query GPU memory with nvidia-smi on host or in %s\n' "$container_name" >&2
    printf 'Use STATEBUS_EMBED_MIN_FREE_MB=0 only when you have checked GPU memory manually.\n' >&2
    exit 2
  fi
  free_mb="$(printf '%s\n' "$gpu_memory_report" | awk -F, -v wanted="$gpu_index" '
    $1 ~ "^[[:space:]]*" wanted "[[:space:]]*$" {
      value = $2
      gsub(/[^0-9]/, "", value)
      print value
      exit
    }
  ')"
  if [[ -z "$free_mb" ]]; then
    printf 'cannot determine free memory for physical GPU %s\n' "$gpu_index" >&2
    exit 2
  fi
  if (( free_mb < minimum_free_mb )); then
    printf 'GPU%s has only %s MiB free; need at least %s MiB for local embedding.\n' \
      "$gpu_index" "$free_mb" "$minimum_free_mb" >&2
    printf 'Wait for GPU memory to free, or explicitly run STATEBUS_EMBED_DEVICE=cpu %s --%s\n' \
      "${BASH_SOURCE[0]}" "${selection#--}" >&2
    exit 3
  fi
fi

mkdir -p "$host_result_root"
printf '[v2-local-audit] selection: %s\n' "$selection"
printf '[v2-local-audit] physical GPU: %s; container embedding device: %s\n' "$gpu_index" "$embedding_device"
printf '[v2-local-audit] host result root: %s\n' "$host_result_root"

cd "$project_root"
docker exec -i -u 0 \
  -e CUDA_VISIBLE_DEVICES="$gpu_index" \
  -e STATEBUS_EMBED_DEVICE="$embedding_device" \
  -e STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED="${STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED:-1}" \
  -e PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
  -e STATEBUS_RUN_SELECTION="$selection" \
  -e STATEBUS_RUN_ID="$run_id" \
  -e STATEBUS_RESULT_ROOT="$container_result_root" \
  -e STATEBUS_V2_LOCAL_AUDIT_MAX_CASES="$max_cases" \
  -e STATEBUS_V2_FORMAL_TIMEOUT_S="${STATEBUS_V2_FORMAL_TIMEOUT_S:-7200}" \
  -e STATEBUS_V2_COMPARE_TIMEOUT_S="${STATEBUS_V2_COMPARE_TIMEOUT_S:-7200}" \
  -e STATEBUS_V2_REPLAY_TIMEOUT_S="${STATEBUS_V2_REPLAY_TIMEOUT_S:-3600}" \
  -e STATEBUS_V2_NEGATIVE_TIMEOUT_S="${STATEBUS_V2_NEGATIVE_TIMEOUT_S:-600}" \
  -e STATEBUS_V2_ADAPTIVE_TIMEOUT_S="${STATEBUS_V2_ADAPTIVE_TIMEOUT_S:-600}" \
  -e STATEBUS_V2_CODEACT_TIMEOUT_S="${STATEBUS_V2_CODEACT_TIMEOUT_S:-600}" \
  -e STATEBUS_V2_ADAPTIVE_MATRIX_TIMEOUT_S="${STATEBUS_V2_ADAPTIVE_MATRIX_TIMEOUT_S:-900}" \
  "$container_name" /bin/bash -s <<'CONTAINER_BASH'
set -euo pipefail

source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project

result_root="$STATEBUS_RESULT_ROOT"
status_tsv="$result_root/status.tsv"
selection="$STATEBUS_RUN_SELECTION"
max_cases="$STATEBUS_V2_LOCAL_AUDIT_MAX_CASES"
overall_failure=0

mkdir -p "$result_root"
printf 'stage\texit_code\tstdout_json\tstderr_log\n' > "$status_tsv"

should_run() {
  local stage="$1"
  case "$selection:$stage" in
    --all:*|--preflight:preflight|--adaptive:preflight|--adaptive:adaptive|--llm-codeact:preflight|--llm-codeact:llm-codeact|--adaptive-matrix:preflight|--adaptive-matrix:adaptive-matrix|--formal:preflight|--formal:formal|--compare:preflight|--compare:compare|--replay:preflight|--replay:replay|--negative:preflight|--negative:negative)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

record_stage() {
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$status_tsv"
}

validate_json() {
  /usr/bin/python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    json.load(handle)
PY
}

run_stage() {
  local stage="$1"
  local timeout_s="$2"
  local suite="$3"
  local benchmark_tier="$4"
  shift 4
  local stage_root="$result_root/$stage"
  local stdout_json="$stage_root/stdout.json"
  local stderr_log="$stage_root/stderr.log"
  local socket_path="/tmp/sb-${STATEBUS_RUN_ID: -10}-${stage}.sock"
  local status
  local -a args=(
    --suite "$suite"
    --role-path-mode local_vllm
    --embedding-mode local
    --runtime-root "$stage_root/runtime"
    --workspace-root "$stage_root/workspaces"
    --socket-path "$socket_path"
    --suite-id "${STATEBUS_RUN_ID}-${stage}"
  )

  if [[ -n "$benchmark_tier" ]]; then
    args+=(--benchmark-tier "$benchmark_tier")
  fi
  if [[ "$max_cases" != "0" && ( "$suite" == "formal" || "$suite" == "compare" ) ]]; then
    args+=(--max-cases "$max_cases")
  fi
  args+=("$@")
  mkdir -p "$stage_root/runtime" "$stage_root/workspaces"
  rm -f "$socket_path"
  printf '\n=== %s ===\n' "$stage"
  (
    while sleep 60; do
      printf '[running] %s has not completed yet\n' "$stage" >&2
    done
  ) &
  local heartbeat_pid=$!
  set +e
  timeout "$timeout_s" /usr/bin/python3 -m v2.benchmark.live_runner "${args[@]}" \
    > "$stdout_json" \
    2> >(tee "$stderr_log" >&2)
  status=$?
  set -e
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  if [[ "$status" -eq 0 ]] && ! validate_json "$stdout_json"; then
    status=3
  fi
  record_stage "$stage" "$status" "$stdout_json" "$stderr_log"
  if [[ "$status" -eq 0 ]]; then
    printf '[ok] %s\n' "$stage"
  else
    printf '[fail] %s (exit %s); last stderr lines:\n' "$stage" "$status" >&2
    tail -n 40 "$stderr_log" >&2 || true
    overall_failure=1
  fi
}

run_adaptive_stage() {
  local stage="adaptive"
  local stage_root="$result_root/$stage"
  local readiness_json="$stage_root/bwrap_readiness.json"
  local console_jsonl="$stage_root/console.jsonl"
  local stderr_log="$stage_root/stderr.log"
  local summary_json="$stage_root/summary.json"
  local status=0

  mkdir -p "$stage_root/runs"
  printf '\n=== %s ===\n' "$stage"
  set +e
  /usr/bin/python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py > "$readiness_json" 2> "$stderr_log"
  status=$?
  if [[ "$status" -eq 0 ]]; then
    /usr/bin/python3 - "$readiness_json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], "r", encoding="utf-8"))
if not payload.get("ok"):
    raise SystemExit("bwrap readiness payload is not ok")
PY
    status=$?
  fi
  if [[ "$status" -eq 0 ]]; then
    timeout "$STATEBUS_V2_ADAPTIVE_TIMEOUT_S" /usr/bin/python3 scripts/v2_diagnostics/run_adaptive_agent_smoke.py \
      --output-root "$stage_root/runs" \
      --embedding-model-path /statebus/models/Qwen3-Embedding-0.6B \
      --embedding-device "$STATEBUS_EMBED_DEVICE" \
      --require-model-success \
      > "$console_jsonl" 2>> "$stderr_log"
    status=$?
  fi
  set -e
  if [[ "$status" -eq 0 ]]; then
    /usr/bin/python3 - "$console_jsonl" "$readiness_json" "$summary_json" <<'PY'
import json
import sys
from pathlib import Path

console_path, readiness_path, summary_path = map(Path, sys.argv[1:])
payloads = []
for line in console_path.read_text(encoding="utf-8").splitlines():
    try:
        payloads.append(json.loads(line))
    except json.JSONDecodeError:
        continue
final = next((item for item in reversed(payloads) if "summary" in item), None)
if not isinstance(final, dict) or not final.get("ok") or not final.get("model_path_success"):
    raise SystemExit("adaptive strict acceptance payload missing or failed")
summary = final.get("summary")
if not isinstance(summary, dict) or not summary.get("runtime_completed"):
    raise SystemExit("adaptive runtime did not complete")
result = {
    "ok": True,
    "model_path_success": final["model_path_success"],
    "run_dir": final.get("run_dir", ""),
    "role_calls": summary.get("role_calls", []),
    "fallback_reasons": summary.get("fallback_reasons", {}),
    "runtime_completed": summary["runtime_completed"],
    "bwrap_readiness": json.loads(readiness_path.read_text(encoding="utf-8")),
}
summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    status=$?
  fi
  record_stage "$stage" "$status" "$summary_json" "$stderr_log"
  if [[ "$status" -eq 0 ]]; then
    printf '[ok] %s\n' "$stage"
  else
    printf '[fail] %s (exit %s); last stderr lines:\n' "$stage" "$status" >&2
    tail -n 40 "$stderr_log" >&2 || true
    overall_failure=1
  fi
}

run_llm_codeact_stage() {
  local stage="llm-codeact"
  local stage_root="$result_root/$stage"
  local readiness_json="$stage_root/bwrap_readiness.json"
  local console_jsonl="$stage_root/console.jsonl"
  local stderr_log="$stage_root/stderr.log"
  local summary_json="$stage_root/summary.json"
  local status=0

  mkdir -p "$stage_root/runs"
  printf '\n=== %s ===\n' "$stage"
  set +e
  /usr/bin/python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py > "$readiness_json" 2> "$stderr_log"
  status=$?
  if [[ "$status" -eq 0 ]]; then
    timeout "$STATEBUS_V2_CODEACT_TIMEOUT_S" /usr/bin/python3 scripts/v2_diagnostics/run_llm_codeact_smoke.py \
      --output-root "$stage_root/runs" \
      > "$console_jsonl" 2>> "$stderr_log"
    status=$?
  fi
  set -e
  if [[ "$status" -eq 0 ]]; then
    /usr/bin/python3 - "$console_jsonl" "$readiness_json" "$summary_json" <<'PY'
import json
import sys
from pathlib import Path

console_path, readiness_path, summary_path = map(Path, sys.argv[1:])
payloads = []
for line in console_path.read_text(encoding="utf-8").splitlines():
    try:
        payloads.append(json.loads(line))
    except json.JSONDecodeError:
        continue
final = next((item for item in reversed(payloads) if "summary" in item), None)
if not isinstance(final, dict) or not final.get("ok"):
    raise SystemExit("runtime-integrated CodeAct smoke did not report success")
summary = final.get("summary")
if not isinstance(summary, dict) or not summary.get("runtime_completed"):
    raise SystemExit("runtime-integrated CodeAct did not complete")
records = summary.get("execution_records", [])
if len(records) != 1 or records[0].get("sandbox_actual_backend") != "bwrap":
    raise SystemExit("CodeAct did not execute through bwrap")
if not records[0].get("output_quality_valid"):
    raise SystemExit("CodeAct artifact did not pass capability quality")
result = {
    "ok": True,
    "run_dir": final.get("run_dir", ""),
    "runtime_completed": True,
    "execution_record": records[0],
    "telemetry": summary.get("telemetry", {}),
    "bwrap_readiness": json.loads(readiness_path.read_text(encoding="utf-8")),
}
summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    status=$?
  fi
  record_stage "$stage" "$status" "$summary_json" "$stderr_log"
  if [[ "$status" -eq 0 ]]; then
    printf '[ok] %s\n' "$stage"
  else
    printf '[fail] %s (exit %s); last stderr lines:\n' "$stage" "$status" >&2
    tail -n 40 "$stderr_log" >&2 || true
    overall_failure=1
  fi
}

run_adaptive_matrix_stage() {
  local stage="adaptive-matrix"
  local stage_root="$result_root/$stage"
  local console_jsonl="$stage_root/console.jsonl"
  local stderr_log="$stage_root/stderr.log"
  local summary_json="$stage_root/summary.json"
  local status=0

  mkdir -p "$stage_root/runs"
  printf '\n=== %s ===\n' "$stage"
  set +e
  timeout "$STATEBUS_V2_ADAPTIVE_MATRIX_TIMEOUT_S" /usr/bin/python3 scripts/v2_diagnostics/run_adaptive_mode_matrix.py \
    --output-root "$stage_root/runs" \
    --require-live-model-path \
    > "$console_jsonl" 2> "$stderr_log"
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    /usr/bin/python3 - "$console_jsonl" "$summary_json" <<'PY'
import json
import sys
from pathlib import Path

console_path, summary_path = map(Path, sys.argv[1:])
payloads = []
for line in console_path.read_text(encoding="utf-8").splitlines():
    try:
        payloads.append(json.loads(line))
    except json.JSONDecodeError:
        continue
final = next((item for item in reversed(payloads) if "summary" in item), None)
if not isinstance(final, dict) or not final.get("ok"):
    raise SystemExit("adaptive matrix did not report success")
summary = final.get("summary")
if not isinstance(summary, dict) or len(summary.get("cases", [])) not in {3, 4, 5}:
    raise SystemExit("adaptive matrix must contain three to five isolated cases")
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    status=$?
  fi
  record_stage "$stage" "$status" "$summary_json" "$stderr_log"
  if [[ "$status" -eq 0 ]]; then
    printf '[ok] %s\n' "$stage"
  else
    printf '[fail] %s (exit %s); last stderr lines:\n' "$stage" "$status" >&2
    tail -n 40 "$stderr_log" >&2 || true
    overall_failure=1
  fi
}

if should_run preflight; then
  run_stage preflight 300 preflight ""
fi
if should_run adaptive; then
  run_adaptive_stage
fi
if should_run llm-codeact; then
  run_llm_codeact_stage
fi
if should_run adaptive-matrix; then
  run_adaptive_matrix_stage
fi
if should_run formal; then
  run_stage formal "$STATEBUS_V2_FORMAL_TIMEOUT_S" formal formal --state-pool-mode memfd
fi
if should_run compare; then
  run_stage compare "$STATEBUS_V2_COMPARE_TIMEOUT_S" compare formal --state-pool-mode memfd
fi
if should_run replay; then
  run_stage replay "$STATEBUS_V2_REPLAY_TIMEOUT_S" continuous-replay dev
fi
if should_run negative; then
  run_stage negative "$STATEBUS_V2_NEGATIVE_TIMEOUT_S" replay-negative-audit ""
fi

/usr/bin/python3 - "$status_tsv" "$result_root/summary.md" <<'PY'
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
with status_path.open("r", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
failed = [row for row in rows if row["exit_code"] != "0"]
payload = {"stage_count": len(rows), "failed_stage_count": len(failed), "failed_stages": failed, "stages": rows}
(summary_path.parent / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lines = ["# StateBus v2 Local-vLLM Audit", "", f"- Stage count: `{len(rows)}`", f"- Failed stage count: `{len(failed)}`", "", "## Stages"]
lines.extend(f"- `{row['stage']}`: exit `{row['exit_code']}`" for row in rows)
summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

printf '\n[v2-local-audit] result bundle: %s\n' "$result_root"
exit "$overall_failure"
CONTAINER_BASH
