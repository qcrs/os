#!/usr/bin/env bash
set -Eeuo pipefail

# Bounded model-assist experiment orchestrator. It never runs the
# twelve-round mainline and restores standard vLLM after a KV phase.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CANDIDATE_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
case "$CANDIDATE_ROOT" in
  /home/qcrs/statebus/os|/home/qcrs/statebus/work/os-contest-dsl-model-assist-integration) SOURCE_LABEL=candidate ;;
  *) printf 'unexpected experiment source: %s\n' "$CANDIDATE_ROOT" >&2; exit 2 ;;
esac
# Python -c searches the current directory before PYTHONPATH. Pin it to the
# checkout being measured even when the script is invoked from another repo.
cd -- "$CANDIDATE_ROOT"
FORMAL_ROOT="${STATEBUS_FORMAL_ROOT:-/home/qcrs/statebus/os}"
CONTAINER_NAME="${STATEBUS_CONTAINER_NAME:-statebus-runtime}"
HOST_PYTHON="${STATEBUS_HOST_PYTHON:-/home/qcrs/statebus/conda-envs/statebus_host/bin/python}"
CONTAINER_PYTHON="${STATEBUS_CONTAINER_PYTHON:-/home/qcrs/statebus/conda-envs/statebus_host/bin/python}"
CONTAINER_SOURCE="${STATEBUS_CONTAINER_SOURCE:-/workspace/statebus/${CANDIDATE_ROOT#/home/qcrs/statebus/}}"
PROBE_REL="scripts/experiments/contest_model_assist/run_minimal_probe.py"
CONTAINER_PROBE="${CONTAINER_SOURCE}/${PROBE_REL}"
STANDARD_ENV="${STATEBUS_STANDARD_ENV:-${FORMAL_ROOT}/deploy/vllm.env.local}"
KV_ENV_TEMPLATE="${STATEBUS_KV_ENV_TEMPLATE:-${CANDIDATE_ROOT}/deploy/vllm.env.kv.local}"
FORMAL_MANAGER="${FORMAL_ROOT}/scripts/vllm/manage_qwen3_32b.sh"
KV_MANAGER="${CANDIDATE_ROOT}/scripts/vllm/manage_qwen3_32b.sh"
HOST_TOKEN="${STATEBUS_KV_TOKEN_FILE:-${HOME}/statebus/work/vllm-qwen3-32b-kv-gpu2/kv_api.token}"
CONTAINER_TOKEN="${STATEBUS_CONTAINER_KV_TOKEN_FILE:-/workspace/statebus/work/vllm-qwen3-32b-kv-gpu2/kv_api.token}"
REPORT_ROOT="${STATEBUS_REPORT_ROOT:-${FORMAL_ROOT}/docs/reports/contest-model-assist}"
MODE=smoke
PHASE=both
FAMILY=""
RUN_ID=""
CONFIRM_SWITCH=0
DRY_RUN=0
RESTORE_NEEDED=0
REPORT_CREATED=0
KV_ENV_RUNTIME=""
STANDARD_LIVE_PASSED=not_run
KV_LIVE_PASSED=not_run
STANDARD_RESTORED=not_required
KV_REGISTRY_CLEANED=not_run

usage() {
  cat <<'EOF'
用法：run_smoke_and_formal.sh [选项]

  --mode smoke|formal       smoke 默认 F01；formal 默认 F01/O01
  --phase standard|kv|both  默认 both；kv/both 需要 --yes
  --family finance|service_ops|all
  --run-id ID               只允许字母、数字、点、下划线、短横线
  --report-root PATH        默认 /home/qcrs/statebus/os/docs/reports/contest-model-assist
  --yes                     允许停止 standard、启动 KV 并在退出时恢复 standard
  --dry-run                 只检查并打印计划，不启动服务或发送请求
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --mode) (($# >= 2)) || die "--mode requires a value"; MODE="$2"; shift 2 ;;
    --phase) (($# >= 2)) || die "--phase requires a value"; PHASE="$2"; shift 2 ;;
    --family) (($# >= 2)) || die "--family requires a value"; FAMILY="$2"; shift 2 ;;
    --run-id) (($# >= 2)) || die "--run-id requires a value"; RUN_ID="$2"; shift 2 ;;
    --report-root) (($# >= 2)) || die "--report-root requires a value"; REPORT_ROOT="$2"; shift 2 ;;
    --yes) CONFIRM_SWITCH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

case "$MODE" in smoke|formal) ;; *) die "--mode must be smoke or formal" ;; esac
case "$PHASE" in standard|kv|both) ;; *) die "--phase must be standard, kv, or both" ;; esac
if [[ -z "$FAMILY" ]]; then
  if [[ "$MODE" == formal ]]; then FAMILY=all; else FAMILY=finance; fi
fi
case "$FAMILY" in finance|service_ops|all) ;; *) die "unsupported family: $FAMILY" ;; esac
if [[ "$FAMILY" == all ]]; then
  SELECTED_FAMILIES=(finance service_ops)
else
  SELECTED_FAMILIES=("$FAMILY")
fi
if [[ -z "$RUN_ID" ]]; then RUN_ID="contest-model-assist-${MODE}-$(date +%Y%m%d_%H%M%S)-$$"; fi
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] || die "invalid run id: $RUN_ID"
if [[ "$PHASE" != standard && "$CONFIRM_SWITCH" != 1 && "$DRY_RUN" != 1 ]]; then
  die "KV phase requires --yes because it stops and restores the model service"
fi

case "$REPORT_ROOT" in
  /home/qcrs/statebus/os/docs/reports/contest-model-assist) ;;
  *) die "report-root must be /home/qcrs/statebus/os/docs/reports/contest-model-assist" ;;
esac
REPORT_ROOT="$(cd -- "$(dirname -- "$REPORT_ROOT")" && pwd)/$(basename -- "$REPORT_ROOT")"
RUN_ROOT_HOST="${REPORT_ROOT}/${RUN_ID}"
RUN_ROOT_CONTAINER="/workspace/statebus/${RUN_ROOT_HOST#/home/qcrs/statebus/}"

output_host() {
  printf '%s/%s-%s\n' "$RUN_ROOT_HOST" "$1" "$2"
}

output_container() {
  printf '%s/%s-%s\n' "$RUN_ROOT_CONTAINER" "$1" "$2"
}

check_static_paths() {
  [[ ! -e "$RUN_ROOT_HOST" ]] || die "report directory already exists: $RUN_ROOT_HOST"
  [[ "$CONTAINER_SOURCE" == "/workspace/statebus/${CANDIDATE_ROOT#/home/qcrs/statebus/}" ]] \
    || die "container source does not match host checkout: $CONTAINER_SOURCE"
  [[ "$FORMAL_ROOT" == /home/qcrs/statebus/os ]] || die "unexpected formal source: $FORMAL_ROOT"
  [[ -x "$FORMAL_MANAGER" ]] || die "formal manager not executable: $FORMAL_MANAGER"
  [[ -x "$KV_MANAGER" ]] || die "candidate manager not executable: $KV_MANAGER"
  [[ -x "$CANDIDATE_ROOT/scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh" ]] \
    || die "candidate KV launcher not executable"
  [[ -f "$CANDIDATE_ROOT/$PROBE_REL" ]] || die "candidate probe missing"
  [[ -f "$STANDARD_ENV" ]] || die "standard env missing: $STANDARD_ENV"
  [[ -f "$KV_ENV_TEMPLATE" ]] || die "KV env template missing: $KV_ENV_TEMPLATE"
  [[ -x "$HOST_PYTHON" ]] || die "host Python missing: $HOST_PYTHON"
  [[ -x "$CONTAINER_PYTHON" ]] || die "container Python missing: $CONTAINER_PYTHON"
  command -v setsid >/dev/null 2>&1 || die "setsid is required to detach service manager sessions"
  [[ -r /data/models/Qwen3-32B/config.json ]] || die "model config is not readable"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CANDIDATE_ROOT" "$HOST_PYTHON" -c \
    'import os; from pathlib import Path; import statebus; from statebus.benchmark import contest_dsl_mainline, contest_model_assist; from statebus.integrations.vllm_kv import middleware; root = Path(os.environ["PYTHONPATH"]).resolve(); modules = (statebus, contest_dsl_mainline, contest_model_assist, middleware); assert all(Path(module.__file__).resolve().is_relative_to(root) for module in modules), [module.__file__ for module in modules]; print(*(module.__file__ for module in modules), sep="\n")' \
    || die "host Python did not resolve candidate source"
  grep -Eq '^export STATEBUS_VLLM_SERVICE_MODE="?standard"?$' "$STANDARD_ENV" \
    || die "standard env must select service mode standard"
  grep -Eq '^export STATEBUS_VLLM_ENABLE_PREFIX_CACHING="?1"?$' "$STANDARD_ENV" \
    || die "standard env must enable APC"
  grep -Eq '^export STATEBUS_VLLM_SERVICE_MODE="?kv"?$' "$KV_ENV_TEMPLATE" \
    || die "KV env must select service mode kv"
  grep -Eq '^export STATEBUS_VLLM_ENABLE_PREFIX_CACHING="?0"?$' "$KV_ENV_TEMPLATE" \
    || die "KV env must disable APC"
  if [[ "$PHASE" != standard ]]; then
    [[ -s "$HOST_TOKEN" ]] || die "KV token file is missing or empty: $HOST_TOKEN"
    [[ "$(stat -c '%a' "$HOST_TOKEN")" == 600 ]] || die "KV token file must be mode 600: $HOST_TOKEN"
  fi
  docker inspect "$CONTAINER_NAME" >/dev/null 2>&1 || die "container not found: $CONTAINER_NAME"
  [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" == true ]] || die "container is not running"
  docker exec "$CONTAINER_NAME" test -f "$CONTAINER_PROBE" || die "candidate probe is not visible in container"
  docker exec "$CONTAINER_NAME" test -x "$CONTAINER_SOURCE/scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh" \
    || die "candidate KV launcher is not visible in container"
  docker exec -w "$CONTAINER_SOURCE" \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH="$CONTAINER_SOURCE" \
    "$CONTAINER_NAME" "$CONTAINER_PYTHON" -c \
    'import os; from pathlib import Path; import statebus; from statebus.benchmark import contest_dsl_mainline, contest_model_assist; root = Path(os.environ["PYTHONPATH"]).resolve(); modules = (statebus, contest_dsl_mainline, contest_model_assist); assert all(Path(module.__file__).resolve().is_relative_to(root) for module in modules), [module.__file__ for module in modules]; print(*(module.__file__ for module in modules), sep="\n")' \
    || die "container Python did not resolve candidate source"
  if [[ "$PHASE" != standard ]]; then
    docker exec "$CONTAINER_NAME" test -s "$CONTAINER_TOKEN" || die "KV token is not visible in container"
    [[ "$(docker exec "$CONTAINER_NAME" stat -c '%a' "$CONTAINER_TOKEN")" == 600 ]] \
      || die "container KV token must be mode 600"
    [[ "$HOST_TOKEN" == /home/qcrs/statebus/* ]] || die "KV host token is outside the container mount"
    [[ "$CONTAINER_TOKEN" == "/workspace/statebus/${HOST_TOKEN#/home/qcrs/statebus/}" ]] \
      || die "host and container KV token paths do not map to one file"
    bash -c 'source "$1"; [[ "$STATEBUS_KV_API_TOKEN_FILE" == "$2" ]]' \
      _ "$KV_ENV_TEMPLATE" "$HOST_TOKEN" || die "KV env token path does not match host token path"
    [[ "$(STATEBUS_VLLM_ENV_FILE="$KV_ENV_TEMPLATE" "$KV_MANAGER" print-config | sed -n 's/^模式=//p')" == kv ]] \
      || die "candidate manager did not resolve KV mode"
  fi
}

start_manager_detached() {
  local env_file="$1" manager="$2"
  # The manager starts vLLM in the background. A new session prevents the
  # orchestrator's PTY cleanup from terminating the restored service.
  setsid --wait env STATEBUS_VLLM_ENV_FILE="$env_file" "$manager" start
}

capture_identity() {
  printf 'candidate_branch=%s\n' "$(git -C "$CANDIDATE_ROOT" branch --show-current)"
  printf 'candidate_head=%s\n' "$(git -C "$CANDIDATE_ROOT" rev-parse HEAD)"
  printf 'candidate_dirty_entries=%s\n' "$(git -C "$CANDIDATE_ROOT" status --porcelain | wc -l | tr -d ' ')"
  printf 'formal_branch=%s\n' "$(git -C "$FORMAL_ROOT" branch --show-current)"
  printf 'formal_head=%s\n' "$(git -C "$FORMAL_ROOT" rev-parse HEAD)"
  printf 'formal_dirty_entries=%s\n' "$(git -C "$FORMAL_ROOT" status --porcelain | wc -l | tr -d ' ')"
}

write_manifest() {
  mkdir -- "$RUN_ROOT_HOST"
  REPORT_CREATED=1
  {
    printf 'schema_version=statebus.contest_model_assist_experiment_run.v1\n'
    printf 'run_id=%s\nmode=%s\nphase=%s\nfamily=%s\n' "$RUN_ID" "$MODE" "$PHASE" "$FAMILY"
    printf 'source_label=%s\ncandidate_root=%s\ncontainer_source=%s\nformal_root=%s\nreport_root=%s\n' "$SOURCE_LABEL" "$CANDIDATE_ROOT" "$CONTAINER_SOURCE" "$FORMAL_ROOT" "$RUN_ROOT_HOST"
    printf 'candidate_manager=%s\ncandidate_kv_launcher=%s\nformal_manager=%s\n' "$KV_MANAGER" "$CANDIDATE_ROOT/scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh" "$FORMAL_MANAGER"
    printf 'host_python=%s\ncontainer_python=%s\nstandard_env=%s\nkv_env_template=%s\nkv_token_path=%s\ncontainer_kv_token_path=%s\n' "$HOST_PYTHON" "$CONTAINER_PYTHON" "$STANDARD_ENV" "$KV_ENV_TEMPLATE" "$HOST_TOKEN" "$CONTAINER_TOKEN"
    printf 'model=qwen3-32b\nmax_context=8192\nprovider_timeout_s=480\nembedding_model=/statebus/models/Qwen3-Embedding-0.6B\nembedding_device=cuda:0\n'
    for family in "${SELECTED_FAMILIES[@]}"; do
      printf 'standard_output_%s=%s\n' "$family" "$(output_host standard "$family")"
      printf 'kv_output_%s=%s\n' "$family" "$(output_host kv "$family")"
    done
    capture_identity
  } > "$RUN_ROOT_HOST/execution-manifest.env"
}

write_commands() {
  cat > "$RUN_ROOT_HOST/commands.md" <<EOF
# Contest model-assist run commands

- run id: $RUN_ID
- mode: $MODE
- phase: $PHASE
- family: $FAMILY
- candidate root: $CANDIDATE_ROOT
- report root: $RUN_ROOT_HOST

## Reproduce this run

\`\`\`bash
cd $CANDIDATE_ROOT
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \\
  --mode $MODE --phase $PHASE --family $FAMILY --report-root $REPORT_ROOT --run-id NEW_RUN_ID --yes
\`\`\`

Use a new run ID; this report directory is immutable evidence.

## Summarize without rerunning

\`\`\`bash
EOF
  if [[ "$PHASE" == standard || "$PHASE" == both ]]; then
    for family in "${SELECTED_FAMILIES[@]}"; do
      printf 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="%s" \\\n  %s scripts/experiments/contest_model_assist/run_minimal_probe.py \\\n  --summarize %s\n' \
        "$CANDIDATE_ROOT" "$HOST_PYTHON" "$(output_host standard "$family")" >> "$RUN_ROOT_HOST/commands.md"
    done
  fi
  if [[ "$PHASE" == kv || "$PHASE" == both ]]; then
    for family in "${SELECTED_FAMILIES[@]}"; do
      printf 'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="%s" \\\n  %s scripts/experiments/contest_model_assist/run_minimal_probe.py \\\n  --summarize %s\n' \
        "$CANDIDATE_ROOT" "$HOST_PYTHON" "$(output_host kv "$family")" >> "$RUN_ROOT_HOST/commands.md"
    done
  fi
  cat >> "$RUN_ROOT_HOST/commands.md" <<EOF
\`\`\`

## Formal follow-up

Only after this smoke is reviewed and a separate maintenance window is approved:

\`\`\`bash
cd $CANDIDATE_ROOT
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \\
  --mode formal --phase both --family all --report-root $REPORT_ROOT --run-id NEW_FORMAL_RUN_ID --yes
\`\`\`

The orchestrator switches standard APC-on service to candidate APC-off KV service,
verifies the KV audit, and restores standard before returning. It does not run the
12-round mainline or full benchmark.
EOF
}

write_status() {
  (( REPORT_CREATED )) || return 0
  {
    printf 'schema_version=statebus.contest_model_assist_run_status.v1\n'
    printf 'run_id=%s\nmode=%s\nphase=%s\nfamily=%s\n' "$RUN_ID" "$MODE" "$PHASE" "$FAMILY"
    printf 'standard_live_passed=%s\nkv_live_passed=%s\nkv_registry_cleaned=%s\nstandard_restored=%s\n' \
      "$STANDARD_LIVE_PASSED" "$KV_LIVE_PASSED" "$KV_REGISTRY_CLEANED" "$STANDARD_RESTORED"
    printf 'exit_code=%s\n' "$1"
  } > "$RUN_ROOT_HOST/run-status.env"
}

print_plan() {
  printf 'run_id=%s mode=%s phase=%s family=%s\n' "$RUN_ID" "$MODE" "$PHASE" "$FAMILY"
  printf 'candidate_root=%s\ncontainer_source=%s\nreport_root=%s\n' "$CANDIDATE_ROOT" "$CONTAINER_SOURCE" "$RUN_ROOT_HOST"
  printf 'standard: APC on; Logit + APC\nKV: APC off; kv_replay + kv_continuation\n'
  printf 'embedding: /statebus/models/Qwen3-Embedding-0.6B, device cuda:0 in container\n'
  printf 'service switch requires a maintenance window with no other requests; --yes confirms operator ownership\n'
  if [[ "$PHASE" == standard || "$PHASE" == both ]]; then
    for family in "${SELECTED_FAMILIES[@]}"; do
      if [[ "$family" == finance ]]; then
        printf 'plan standard/%s: F01 logit -> F01 apc\n' "$family"
      else
        printf 'plan standard/%s: O01 apc -> O01 logit\n' "$family"
      fi
    done
  fi
  if [[ "$PHASE" == kv || "$PHASE" == both ]]; then
    for family in "${SELECTED_FAMILIES[@]}"; do
      if [[ "$family" == finance ]]; then
        printf 'plan kv/%s: F01 kv_replay -> F01 kv_continuation\n' "$family"
      else
        printf 'plan kv/%s: O01 kv_continuation -> O01 kv_replay\n' "$family"
      fi
    done
  fi
  nvidia-smi -L
  nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
  nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
}

standard_health() {
  local manager_status
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" health >/dev/null
  curl --noproxy '*' --fail --silent --show-error --max-time 10 http://127.0.0.1:53334/v1/models >/dev/null
  manager_status="$(STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" status)"
  [[ "$manager_status" == *"进程=运行中 pid="*" mode=standard"* && "$manager_status" == *"端点=健康"* ]]
}

run_probe() {
  local phase="$1" family="$2" output_container_path="$3"
  local apc_enabled apc_ready apc_url apc_exclusive kv_url kv_token
  if [[ "$phase" == standard ]]; then
    apc_enabled=1; apc_ready=1; apc_url=http://127.0.0.1:53334/metrics; apc_exclusive=1
    kv_url=""; kv_token=""
  else
    apc_enabled=0; apc_ready=0; apc_url=""; apc_exclusive=0
    kv_url=http://127.0.0.1:53334; kv_token="$CONTAINER_TOKEN"
  fi
  docker exec -w "$CONTAINER_SOURCE" \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH="$CONTAINER_SOURCE" \
    -e PROJECT_ROOT="$CONTAINER_SOURCE" \
    -e STATEBUS_LLM_CONFIG_FILE="$CONTAINER_SOURCE/deploy/statebus_llm.g6b2-qwen3-32b.example" \
    -e STATEBUS_APC_ENABLED="$apc_enabled" -e STATEBUS_APC_SERVICE_READY="$apc_ready" \
    -e STATEBUS_APC_METRICS_URL="$apc_url" -e STATEBUS_APC_METRICS_EXCLUSIVE="$apc_exclusive" \
    -e STATEBUS_KV_API_BASE_URL="$kv_url" -e STATEBUS_KV_API_TOKEN_FILE="$kv_token" \
    -e STATEBUS_KV_API_TIMEOUT_S=480 -e STATEBUS_KV_TOKENIZER_TIMEOUT_S=120 \
    -e STATEBUS_ENGINE_LOCAL_KV_PARENT_TOKENS=0 -e STATEBUS_ENGINE_LOCAL_KV_TTL_S=300 \
    -e STATEBUS_ENGINE_LOCAL_KV_SEED=7 \
    "$CONTAINER_NAME" "$CONTAINER_PYTHON" "$CONTAINER_PROBE" \
    --phase "$phase" --family "$family" --source-label "$SOURCE_LABEL" \
    --output "$output_container_path" --live \
    --embedding-model /statebus/models/Qwen3-Embedding-0.6B \
    --embedding-device cuda:0 --tokenizer-path /data/models/Qwen3-32B
}

verify_probe_output() {
  local phase="$1" family="$2" output_host_path="$3"
  "$HOST_PYTHON" - "$phase" "$family" "$output_host_path" <<'PY'
import json
from pathlib import Path
import sys

phase, family, root_text = sys.argv[1:]
root = Path(root_text)
rows = json.loads((root / "task_results.json").read_text(encoding="utf-8"))
selected = [row for row in rows if row.get("phase") == phase and row.get("family") == family and row.get("status") != "not_started"]
expected = {
    ("standard", "finance"): ("logit", "apc"),
    ("standard", "service_ops"): ("apc", "logit"),
    ("kv", "finance"): ("kv_replay", "kv_continuation"),
    ("kv", "service_ops"): ("kv_continuation", "kv_replay"),
}[(phase, family)]
if tuple(row.get("profile") for row in selected) != expected:
    raise SystemExit(f"missing_or_reordered_rows:{phase}:{family}:{root}")
bad = [row for row in selected if row.get("status") != "success"]
if bad:
    raise SystemExit(f"probe_rows_failed:{phase}:{[(r.get('task_id'), r.get('profile'), r.get('status')) for r in bad]}")
for row in selected:
    if row.get("quality") is not True or row.get("business_quality") is not True:
        raise SystemExit(f"business_quality_missing:{row.get('task_id')}:{row.get('profile')}")
    events = (row.get("mechanism") or {}).get("model_assist") or []
    if row["profile"] == "logit" and not any(
        event.get("role") == "executor"
        and event.get("observations", {}).get("logit", {}).get("available") is True
        for event in events
    ):
        raise SystemExit(f"same_call_logit_missing:{row.get('task_id')}")
    if row["profile"] == "apc":
        if not any(event.get("effective_mode") == "apc_full_prompt" for event in events):
            raise SystemExit(f"apc_provider_route_missing:{row.get('task_id')}")
        windows = [event for event in events if event.get("event") == "apc_task_window"]
        if len(windows) != 1 or not (
            (windows[0].get("before") is not None and windows[0].get("after") is not None)
            or (windows[0].get("observation") or {}).get("status") == "unavailable"
        ):
            raise SystemExit(f"apc_task_window_missing:{row.get('task_id')}")
if phase == "kv":
    replay = next(row for row in selected if row["profile"] == "kv_replay")
    replay_audit = ((replay.get("mechanism") or {}).get("engine_local_kv") or {})
    if int(replay_audit.get("capture_count", 0)) or int(replay_audit.get("load_count", 0)):
        raise SystemExit(f"kv_replay_used_handle:{replay.get('task_id')}")
    if not any(call.get("lane") == "full_replay" and call.get("success") for call in replay_audit.get("consumer_calls", [])):
        raise SystemExit(f"kv_replay_missing:{replay.get('task_id')}")
    continuation = [row for row in selected if row.get("profile") == "kv_continuation"]
    for row in continuation:
        audit = ((row.get("mechanism") or {}).get("engine_local_kv") or {})
        if int(audit.get("capture_count", 0)) <= 0:
            raise SystemExit(f"kv_capture_missing:{row.get('task_id')}")
        if int(audit.get("load_count", 0)) <= 0:
            raise SystemExit(f"kv_load_missing:{row.get('task_id')}")
        if not any(call.get("status") == "released" for call in audit.get("release_calls", [])):
            raise SystemExit(f"kv_release_missing:{row.get('task_id')}")
        consumers = audit.get("consumer_calls") or []
        proofs = [
            call.get("telemetry", {})
            for call in consumers
            if call.get("lane") == "kv_continuation"
        ]
        if not any(
            int(proof.get("inherited_kv_tokens", 0)) > 0
            and int(proof.get("connector_load_count", 0)) > 0
            and str(proof.get("forward_proof_hash", ""))
            and (proof.get("extra", {}).get("scheduler_kv_proof") or {}).get("action") == "load"
            for proof in proofs
        ):
            raise SystemExit(f"kv_forward_proof_missing:{row.get('task_id')}")
print(f"verified_phase={phase} rows={len(selected)}")
PY
}

run_phase() {
  local phase="$1" family output_host_path output_container_path
  for family in "${SELECTED_FAMILIES[@]}"; do
    output_host_path="$(output_host "$phase" "$family")"
    output_container_path="$(output_container "$phase" "$family")"
    run_probe "$phase" "$family" "$output_container_path"
    verify_probe_output "$phase" "$family" "$output_host_path"
  done
}

make_runtime_kv_env() {
  [[ -s "$HOST_TOKEN" ]] || die "KV token file is missing or empty: $HOST_TOKEN"
  [[ "$(stat -c '%a' "$HOST_TOKEN")" == 600 ]] || die "KV token file must be mode 600: $HOST_TOKEN"
  KV_ENV_RUNTIME="${RUN_ROOT_HOST}/vllm.env.kv.runtime"
  cp -- "$KV_ENV_TEMPLATE" "$KV_ENV_RUNTIME"
  printf '\n# generated by run_smoke_and_formal.sh; token contents are never copied\n' >> "$KV_ENV_RUNTIME"
  printf 'export STATEBUS_KV_ENGINE_GENERATION="qwen3-32b-kv-%s"\n' "$RUN_ID" >> "$KV_ENV_RUNTIME"
}

kv_authenticated_health() {
  local output="$1"
  {
    printf 'Authorization: Bearer '
    tr -d '\r\n' < "$HOST_TOKEN"
    printf '\n'
  } | curl --noproxy '*' --header @- --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:53334/statebus/kv/health > "$output"
}

check_kv_registry() {
  "$HOST_PYTHON" - "$RUN_ROOT_HOST/kv-health-before.json" "$RUN_ROOT_HOST/kv-health-after.json" <<'PY'
import json
from pathlib import Path
import sys

before, after = (json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:])
if after.get("status") != "ready" or after.get("engine_generation") != before.get("engine_generation"):
    raise SystemExit("kv_health_changed_or_not_ready")
for field in ("registry_entries", "registry_bytes"):
    if not isinstance(before.get(field), int) or not isinstance(after.get(field), int):
        raise SystemExit(f"kv_registry_field_missing:{field}")
    if after[field] != before[field]:
        raise SystemExit(f"kv_registry_not_restored:{field}:{before[field]}->{after[field]}")
print("kv_registry_cleaned=true")
PY
}

switch_to_kv() {
  make_runtime_kv_env
  standard_health || die "standard service is not healthy before KV handoff"
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" print-config > "$RUN_ROOT_HOST/standard-before-config.txt"
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" status > "$RUN_ROOT_HOST/standard-before-manager.txt"
  RESTORE_NEEDED=1
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" stop
  STATEBUS_VLLM_ENV_FILE="$KV_ENV_RUNTIME" "$KV_MANAGER" print-config > "$RUN_ROOT_HOST/kv-service-config.txt"
  start_manager_detached "$KV_ENV_RUNTIME" "$KV_MANAGER"
  STATEBUS_VLLM_ENV_FILE="$KV_ENV_RUNTIME" "$KV_MANAGER" health
  STATEBUS_VLLM_ENV_FILE="$KV_ENV_RUNTIME" "$KV_MANAGER" status > "$RUN_ROOT_HOST/kv-manager.txt"
  grep -Eq '进程=运行中 pid=[0-9]+ mode=kv' "$RUN_ROOT_HOST/kv-manager.txt" \
    || die "candidate KV manager does not own a running KV service"
  kv_authenticated_health "$RUN_ROOT_HOST/kv-health-before.json"
  "$HOST_PYTHON" - "$RUN_ROOT_HOST/kv-health-before.json" "$RUN_ID" <<'PY'
import json
from pathlib import Path
import sys

health = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if health.get("status") != "ready" or health.get("automatic_prefix_caching") is not False:
    raise SystemExit("kv_service_not_ready_or_apc_enabled")
if health.get("model") != "qwen3-32b" or health.get("max_model_len") != 8192:
    raise SystemExit("kv_service_model_or_context_mismatch")
if health.get("engine_generation") != f"qwen3-32b-kv-{sys.argv[2]}":
    raise SystemExit("kv_generation_mismatch")
PY
  KV_REGISTRY_CLEANED=not_checked
}

restore_standard() {
  local status=0
  set +e
  if [[ -n "$KV_ENV_RUNTIME" ]]; then
    STATEBUS_VLLM_ENV_FILE="$KV_ENV_RUNTIME" "$KV_MANAGER" stop
    [[ $? -eq 0 ]] || status=1
  fi
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" print-config > "$RUN_ROOT_HOST/standard-restoration-config.txt"
  [[ $? -eq 0 ]] || status=1
  start_manager_detached "$STANDARD_ENV" "$FORMAL_MANAGER"
  [[ $? -eq 0 ]] || status=1
  curl --noproxy '*' --fail --silent --show-error --max-time 10 http://127.0.0.1:53334/health > "$RUN_ROOT_HOST/standard-restoration-health.txt"
  [[ $? -eq 0 ]] || status=1
  curl --noproxy '*' --fail --silent --show-error --max-time 10 http://127.0.0.1:53334/v1/models > "$RUN_ROOT_HOST/standard-restoration-models.json"
  [[ $? -eq 0 ]] || status=1
  "$HOST_PYTHON" - "$RUN_ROOT_HOST/standard-restoration-models.json" <<'PY'
import json
from pathlib import Path
import sys

models = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not any(model.get("id") == "qwen3-32b" for model in models.get("data", [])):
    raise SystemExit("standard_model_not_restored")
PY
  [[ $? -eq 0 ]] || status=1
  STATEBUS_VLLM_ENV_FILE="$STANDARD_ENV" "$FORMAL_MANAGER" status > "$RUN_ROOT_HOST/standard-restoration-manager.txt"
  [[ $? -eq 0 ]] || status=1
  grep -Eq '进程=运行中 pid=[0-9]+ mode=standard' "$RUN_ROOT_HOST/standard-restoration-manager.txt" || status=1
  grep -q '端点=健康' "$RUN_ROOT_HOST/standard-restoration-manager.txt" || status=1
  set -e
  if (( status == 0 )); then
    STANDARD_RESTORED=true
  else
    STANDARD_RESTORED=false
  fi
  (( status == 0 )) || printf 'standard restoration failed; inspect manager/logs\n' >&2
  return "$status"
}

on_exit() {
  local rc=$?
  if (( RESTORE_NEEDED )); then
    if [[ -s "$RUN_ROOT_HOST/kv-health-before.json" ]]; then
      if kv_authenticated_health "$RUN_ROOT_HOST/kv-health-after.json" && check_kv_registry; then
        KV_REGISTRY_CLEANED=true
      else
        KV_REGISTRY_CLEANED=false
        rc=1
      fi
    fi
    restore_standard || rc=1
  fi
  write_status "$rc"
  exit "$rc"
}

main() {
  check_static_paths
  print_plan
  if (( DRY_RUN )); then
    printf 'dry_run=true; no service switch and no model request\n'
    return 0
  fi
  write_manifest
  write_commands
  if [[ "$PHASE" == standard || "$PHASE" == both ]]; then
    STANDARD_LIVE_PASSED=false
    standard_health || die "standard service is not healthy"
    run_phase standard
    STANDARD_LIVE_PASSED=true
  fi
  if [[ "$PHASE" == kv || "$PHASE" == both ]]; then
    KV_LIVE_PASSED=false
    STANDARD_RESTORED=false
    switch_to_kv
    run_phase kv
    KV_LIVE_PASSED=true
  fi
  if [[ "$PHASE" == standard ]]; then
    standard_health || die "standard service became unhealthy"
  fi
}

trap on_exit EXIT
main "$@"
