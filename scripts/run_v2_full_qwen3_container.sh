#!/usr/bin/env bash
# Run the complete Qwen3-32B validation matrix from inside statebus-dev-qcrs.
# The script is valid for both root and qcrs users.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/run_v2_full_qwen3_container.sh

Run inside the StateBus container. Environment overrides:
  STATEBUS_FULL_STAMP                 fixed run stamp
  STATEBUS_FULL_RESULT_ROOT           result directory under /statebus/runs
  STATEBUS_FULL_RUN_PYTEST=0          skip the v2 regression suite
  STATEBUS_FULL_SKIP_COMPARE=1        skip full formal compare
  STATEBUS_FULL_SKIP_REPLAY=1         skip full replay-ready suite
  STATEBUS_FULL_SKIP_CONTINUOUS=1     skip both 10-round continuous families
  STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS cap each continuous family; default 0 (all rounds)
  STATEBUS_FULL_SKIP_FORMAL=1         skip full 25-case L0-L3 formal suite
  STATEBUS_FULL_SKIP_SUBPROCESS=1     skip full subprocess UDS formal suite
  STATEBUS_FULL_SKIP_CARRIER=1        skip full internal text/protocol carrier compare
  STATEBUS_FULL_SKIP_GENERICITY=1     skip paraphrased cross-family no-hint holdout
  STATEBUS_FULL_SKIP_PREFIX=1         skip shared/independent task-local prefix probes
  STATEBUS_FULL_SKIP_LATENCY_REPEAT=1 skip two extra serialized compare repeats
  STATEBUS_EMBED_DEVICE=cuda:1        local embedding device
  STATEBUS_LOCAL_VLLM_BASE_URL=...    OpenAI-compatible vLLM endpoint
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
  echo "[statebus-full] container activation script is missing; run this inside statebus-dev-qcrs" >&2
  exit 2
fi

# docker exec --user does not always update HOME. A stale HOME=/root hides the
# qcrs user-site packages and makes local embedding imports fail.
CONTAINER_USER_HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
if [[ -n "$CONTAINER_USER_HOME" ]]; then
  export HOME="$CONTAINER_USER_HOME"
  export NPM_CONFIG_PREFIX="${CONTAINER_USER_HOME}/.local"
fi

# shellcheck disable=SC1091
source /usr/local/bin/activate_statebus_container.sh

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/statebus/project}"
cd "$PROJECT_ROOT"

STAMP="${STATEBUS_FULL_STAMP:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${STATEBUS_FULL_RESULT_ROOT:-/statebus/runs/full_qwen3_${STAMP}}"
STAGE_ROOT="${RESULT_ROOT}/stages"
LOG_ROOT="${RESULT_ROOT}/logs"
STATUS_FILE="${RESULT_ROOT}/status.tsv"
RUN_LOG="${RESULT_ROOT}/run.log"
LLM_CONFIG="${RESULT_ROOT}/statebus_llm.local_vllm.yaml"
SOCKET_PATH="/tmp/sb-full-${STAMP}.sock"

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

write_llm_config() {
  cat > "$LLM_CONFIG" <<EOF
mode: local_vllm

providers:
  default:
    kind: openai_compatible
    base_url: ${STATEBUS_LOCAL_VLLM_BASE_URL}
    api_key: EMPTY
    timeout_s: ${STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S:-240}
    request_max_attempts: ${STATEBUS_LOCAL_VLLM_REQUEST_MAX_ATTEMPTS:-2}
    retry_initial_delay_s: ${STATEBUS_LOCAL_VLLM_RETRY_INITIAL_DELAY_S:-2}
    retry_max_delay_s: ${STATEBUS_LOCAL_VLLM_RETRY_MAX_DELAY_S:-10}

roles:
  planner:
    provider: default
    model: ${STATEBUS_LOCAL_VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${STATEBUS_LOCAL_VLLM_PLANNER_MAX_TOKENS:-1024}
    max_context_tokens: ${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_TOKENS:-4096}
    max_context_safety_margin_tokens: 64
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  retriever:
    provider: default
    model: ${STATEBUS_LOCAL_VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${STATEBUS_LOCAL_VLLM_RETRIEVER_MAX_TOKENS:-1024}
    max_context_tokens: ${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_TOKENS:-4096}
    max_context_safety_margin_tokens: 64
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  executor:
    provider: default
    model: ${STATEBUS_LOCAL_VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${STATEBUS_LOCAL_VLLM_EXECUTOR_MAX_TOKENS:-1536}
    max_context_tokens: ${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_TOKENS:-4096}
    max_context_safety_margin_tokens: 64
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  summarizer:
    provider: default
    model: ${STATEBUS_LOCAL_VLLM_MODEL}
    json_output: true
    temperature: 0.0
    max_tokens: ${STATEBUS_LOCAL_VLLM_SUMMARIZER_MAX_TOKENS:-1024}
    max_context_tokens: ${STATEBUS_LOCAL_VLLM_MAX_CONTEXT_TOKENS:-4096}
    max_context_safety_margin_tokens: 64
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
EOF
}

verify_report() {
  local kind="$1"
  local report="$2"
  python3 - "$kind" "$report" <<'PY'
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from v2.benchmark.replay_gate import ReplayGateError, validate_replay_case_contract

kind = sys.argv[1]
path = Path(sys.argv[2])
payload = json.loads(path.read_text(encoding="utf-8"))

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{kind} gate failed: {message}")

def layers() -> list[dict[str, object]]:
    value = payload.get("layers", [])
    require(isinstance(value, list), "layers is not a list")
    return value

def require_role_calls(item: dict[str, object], expected: int) -> None:
    telemetry = item.get("telemetry_summary", {})
    for role in ("planner", "retriever", "executor", "summarizer"):
        observed = int(telemetry.get(f"{role}_call_count", 0))
        require(observed == expected, f"{item.get('layer')} {role} calls {observed}/{expected}")

def require_derived_metrics(item: dict[str, object]) -> None:
    telemetry = item.get("telemetry_summary", {})
    require(float(telemetry.get("task_ms", 0.0)) > 0.0, f"{item.get('layer')} task_ms missing")
    hits = float(telemetry.get("neural_prefix_cache_hit_count_estimate", 0.0))
    queries = float(telemetry.get("neural_prefix_cache_query_count_estimate", 0.0))
    rate = float(telemetry.get("neural_prefix_cache_hit_rate_estimate", 0.0))
    expected_rate = hits / queries if queries else 0.0
    require(abs(rate - expected_rate) < 1e-9, f"{item.get('layer')} prefix rate {rate} != {expected_rate}")
    savings_ratio = float(telemetry.get("neural_prefix_prefill_savings_ratio_estimate", 0.0))
    require(0.0 <= savings_ratio <= 1.0, f"{item.get('layer')} prefix savings ratio out of range")

if kind == "preflight":
    require(payload.get("ok") is True, "preflight ok is not true")
elif kind == "compare":
    selected = int(payload.get("selected_case_count", 0))
    available = int(payload.get("available_case_count", 0))
    summary = payload.get("comparison_summary", {})
    statebus_quality = int(summary.get(
        "local_vllm_statebus_quality_floor_pass_count",
        summary.get("local_vllm_debug_statebus_quality_floor_pass_count", 0),
    ))
    external_quality = int(summary.get(
        "local_vllm_external_quality_floor_pass_count",
        summary.get("local_vllm_debug_external_quality_floor_pass_count", 0),
    ))
    require(selected > 0 and selected == available, f"case coverage {selected}/{available}")
    require(statebus_quality == selected, f"StateBus quality {statebus_quality}/{selected}")
    require(external_quality == selected, f"external quality {external_quality}/{selected}")
    require(payload.get("strict_equal_quality_comparison_valid") is True, "strict equality invalid")
    mode_reports = payload.get("mode_reports", [])
    require(len(mode_reports) == 1, "compare must have one serialized mode report")
    detail_path = Path(str(mode_reports[0].get("report_path", "")))
    require(detail_path.exists(), f"compare detail report missing: {detail_path}")
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    fairness = detail.get("fairness_manifest", {})
    require(fairness.get("pass_hard_gate") is True, "external fairness hard gate failed")
    require(fairness.get("no_external_contamination") is True, "external contamination detected")
    for lane in ("statebus_report", "external_report"):
        cases = detail.get(lane, {}).get("cases", [])
        require(len(cases) == selected, f"{lane} case detail coverage mismatch")
        for case in cases:
            metrics = case.get("metrics", {})
            for role in ("planner", "retriever", "executor", "summarizer"):
                require(
                    int(metrics.get(f"{role}_call_count", 0)) == 1,
                    f"{lane} {case.get('task_id')} missing {role} call",
                )
elif kind == "replay":
    selected = int(payload.get("selected_case_count", 0))
    available = int(payload.get("available_case_count", 0))
    require(selected > 0 and selected == available, f"case coverage {selected}/{available}")
    require(payload.get("selected_layer") == "L3", "replay validation must select L3")
    require(payload.get("effective_statebus_mode") == "replay_ready", "mode is not replay_ready")
    metrics = payload.get("aggregated_metrics", {})
    require(int(metrics.get("case_count", 0)) == selected, "L3 case count mismatch")
    require(int(metrics.get("quality_floor_pass_count", 0)) == selected, "L3 quality mismatch")
    telemetry = payload.get("telemetry_summary", {})
    replay_count = int(telemetry.get("validated_replay_count", 0)) + int(
        telemetry.get("exact_replay_count", 0)
    )
    require(replay_count == selected, f"L3 replay coverage {replay_count}/{selected}")
    require(int(telemetry.get("skipped_step_count", 0)) >= selected, "L3 skipped_step_count is incomplete")
    cases = payload.get("cases", [])
    require(isinstance(cases, list), "replay cases is not a list")
    try:
        replay_totals = validate_replay_case_contract(cases, expected_case_count=selected)
    except ReplayGateError as exc:
        require(False, str(exc))
    for metric_name, expected in replay_totals.items():
        observed = int(telemetry.get(metric_name, 0))
        require(observed == expected, f"L3 {metric_name} {observed}/{expected}")
    require_derived_metrics(payload)
    require(payload.get("metadata", {}).get("task_family_tier") == "formal_registry", "replay tier metadata mismatch")
elif kind == "formal" or kind == "formal_subprocess":
    selected = int(payload.get("selected_case_count", 0))
    available = int(payload.get("available_case_count", 0))
    require(selected > 0 and selected == available, f"case coverage {selected}/{available}")
    layer_payloads = layers()
    require([item.get("layer") for item in layer_payloads] == ["L0", "L1", "L2", "L3"], "missing L0-L3")
    for item in layer_payloads:
        metrics = item.get("aggregated_metrics", {})
        case_count = int(metrics.get("case_count", 0))
        quality = int(metrics.get("quality_floor_pass_count", 0))
        require(case_count == selected, f"{item.get('layer')} case count {case_count}/{selected}")
        require(quality == selected, f"{item.get('layer')} quality {quality}/{selected}")
        require_role_calls(item, selected)
        require_derived_metrics(item)
        require(
            int(item.get("telemetry_summary", {}).get("logit_state_transfer_count", 0)) == selected,
            f"{item.get('layer')} logit summary coverage mismatch",
        )
        if kind == "formal_subprocess":
            require(item.get("metadata", {}).get("transport") == "subprocess", "transport is not subprocess")
    for item in layer_payloads[2:]:
        require(
            int(item.get("telemetry_summary", {}).get("semantic_state_transfer_count", 0)) == selected,
            f"{item.get('layer')} semantic state transfer coverage mismatch",
        )
elif kind == "carrier":
    selected = int(payload.get("selected_case_count", 0))
    available = int(payload.get("available_case_count", 0))
    require(selected > 0 and selected == available, f"case coverage {selected}/{available}")
    mode_reports = payload.get("mode_reports", [])
    require(len(mode_reports) == 1, "carrier compare must have one serialized mode")
    mode = mode_reports[0]
    require(mode.get("comparison_valid") is True, "carrier comparison invalid")
    require(mode.get("claim_level") == "first_pass", "carrier claim level mismatch")
    detail_path = Path(str(mode.get("report_path", "")))
    require(detail_path.exists(), f"carrier detail report missing: {detail_path}")
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    for lane in ("external_report", "statebus_report"):
        report = detail.get(lane, {})
        require(int(report.get("aggregated_metrics", {}).get("case_count", 0)) == selected, f"{lane} case mismatch")
        require(
            int(report.get("aggregated_metrics", {}).get("quality_floor_pass_count", 0)) == selected,
            f"{lane} quality mismatch",
        )
elif kind == "genericity":
    require(payload.get("ok") is True, "genericity holdout failed")
    require(payload.get("route_hint_policy") == "disabled", "route hints were not disabled")
    require(int(payload.get("selected_case_count", 0)) >= 4, "genericity case coverage too small")
    require(int(payload.get("selected_family_count", 0)) >= 4, "genericity family coverage too small")
    request_audit = payload.get("prompt_taint_audit", {})
    require(request_audit.get("pass") is True, "role request taint audit failed")
    require(
        request_audit.get("schema_version") == "statebus.role_request_taint_audit.v3",
        "role request taint audit schema mismatch",
    )
    require(
        request_audit.get("no_hint_preferred_candidate_absent") is True,
        "no-hint request still contains a preferred candidate",
    )
    require(int(request_audit.get("scanned_task_count", 0)) >= 4, "role request task coverage too small")
    for role in ("planner", "retriever", "executor", "summarizer"):
        require(
            int(request_audit.get("role_request_counts", {}).get(role, 0)) > 0,
            f"missing actual rendered request coverage for {role}",
        )
    model_equivalence = payload.get("paraphrase_model_semantic_equivalence", {})
    effective_equivalence = payload.get("paraphrase_effective_contract_equivalence", {})
    require(isinstance(model_equivalence, dict) and model_equivalence, "model paraphrase diagnostics missing")
    require(isinstance(effective_equivalence, dict) and effective_equivalence, "effective paraphrase audit missing")
    require(
        set(model_equivalence) == set(effective_equivalence),
        "model/effective paraphrase case coverage mismatch",
    )
    require(all(bool(value) for value in effective_equivalence.values()), "effective contract paraphrase drift")
    require(payload.get("effective_contract_safety_pass") is True, "effective contract safety gate failed")
    for case in payload.get("case_audit", []):
        require(case.get("quality_floor_pass") is True, f"{case.get('task_id')} quality failed")
        require(float(case.get("route_hints_enabled", -1.0)) == 0.0, f"{case.get('task_id')} used route hints")
        require(float(case.get("planner_semantic_plan_valid", 0.0)) == 1.0, f"{case.get('task_id')} semantic plan invalid")
        require(float(case.get("planner_semantic_equivalence", 0.0)) == 1.0, f"{case.get('task_id')} semantic plan incompatible")
        require(float(case.get("planner_model_generated_field_count", 0.0)) > 0.0, f"{case.get('task_id')} planner generated no fields")
        require(float(case.get("planner_downstream_consumed_field_count", 0.0)) > 0.0, f"{case.get('task_id')} planner objective not consumed")
        require(float(case.get("planner_retriever_consumed_hash_match_count", 0.0)) == 4.0, f"{case.get('task_id')} consumed objective hash mismatch")
        require(int(case.get("four_role_call_count", 0)) == 4, f"{case.get('task_id')} role graph incomplete")
elif kind == "prefix":
    summary = payload.get("summary", {})
    require(payload.get("service_health_before", {}).get("ok") is True, "vLLM health failed")
    require(int(summary.get("ok_count", 0)) == int(summary.get("request_count", 0)) > 0, "prefix requests failed")
    # vLLM releases differ: gauges are useful diagnostics, but without explicit
    # query/hit counters this artifact is intentionally non-claimable.
    require("counter_delta_valid_request_count" in summary, "counter-delta accounting missing")
    require(summary.get("latency_observation_valid") is True, "serialized cold/warm latency observation missing")
    if int(summary.get("counter_delta_valid_request_count", 0)) == 0:
        require(bool(summary.get("counter_delta_unavailable_reasons")), "counter unavailability reason missing")
elif kind == "continuous":
    selected = int(payload.get("selected_round_count", 0))
    available = int(payload.get("available_round_count", 0))
    configured_cap = int(os.environ.get("STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS", "0") or 0)
    expected = available if configured_cap <= 0 else min(configured_cap, available)
    require(selected > 0 and selected == expected, f"round coverage {selected}/{expected} (available={available})")
    layer_payloads = layers()
    require([item.get("layer") for item in layer_payloads] == ["L0", "L1", "L2", "L3"], "missing L0-L3")
    for item in layer_payloads:
        metrics = item.get("aggregated_metrics", {})
        require(int(metrics.get("case_count", 0)) == selected, f"{item.get('layer')} case count mismatch")
        require(int(metrics.get("quality_floor_pass_count", 0)) == selected, f"{item.get('layer')} quality mismatch")
        require_role_calls(item, selected)
        require_derived_metrics(item)
else:
    raise SystemExit(f"unknown report kind: {kind}")
PY
}

run_stage() {
  local stage_id="$1"
  local kind="$2"
  shift 2
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local stdout_json="${stage_dir}/stdout.json"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"

  mkdir -p "${stage_dir}/workspaces" "${stage_dir}/runtime"
  rm -f "$SOCKET_PATH"
  log "START ${stage_id}"
  if python3 -m v2.benchmark.live_runner \
      --role-path-mode local_vllm \
      --embedding-mode local \
      --state-pool-mode auto \
      --workspace-root "${stage_dir}/workspaces" \
      --runtime-root "${stage_dir}/runtime" \
      --socket-path "$SOCKET_PATH" \
      --suite-id "full-${stage_id}-${STAMP}" \
      "$@" \
      > "$stdout_json" 2> "$stderr_log"; then
    if python3 -m json.tool "$stdout_json" > /dev/null && verify_report "$kind" "$stdout_json"; then
      record_status "$stage_id" pass "$stdout_json"
      log "PASS  ${stage_id}"
      return 0
    fi
  fi
  record_status "$stage_id" fail "$stderr_log"
  log "FAIL  ${stage_id}; inspect ${stderr_log} and ${stdout_json}"
  return 0
}

run_genericity_stage() {
  local stage_id="08_genericity_holdout"
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local stdout_json="${stage_dir}/stdout.json"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"
  mkdir -p "${stage_dir}/workspaces" "${stage_dir}/runtime"
  rm -f "$SOCKET_PATH"
  log "START ${stage_id}"
  if python3 scripts/run_v2_genericity_holdout.py \
      --workspace-root "${stage_dir}/workspaces" \
      --runtime-root "${stage_dir}/runtime" \
      --socket-path "$SOCKET_PATH" \
      --suite-id "full-${stage_id}-${STAMP}" \
      --role-path-mode local_vllm \
      --embedding-mode local \
      > "$stdout_json" 2> "$stderr_log" \
      && python3 -m json.tool "$stdout_json" > /dev/null \
      && verify_report genericity "$stdout_json"; then
    record_status "$stage_id" pass "$stdout_json"
    log "PASS  ${stage_id}"
    return 0
  fi
  record_status "$stage_id" fail "$stderr_log"
  log "FAIL  ${stage_id}; inspect ${stderr_log} and ${stdout_json}"
  return 0
}

run_prefix_stage() {
  local stage_id="$1"
  local mode="$2"
  local stage_dir="${STAGE_ROOT}/${stage_id}"
  local stdout_json="${stage_dir}/stdout.json"
  local command_log="${LOG_ROOT}/${stage_id}.log"
  local stderr_log="${LOG_ROOT}/${stage_id}.stderr.log"
  mkdir -p "$stage_dir"
  log "START ${stage_id}"
  if python3 scripts/probe_local_vllm_prefix_alignment.py \
      --mode "$mode" \
      --base-url "$STATEBUS_LOCAL_VLLM_BASE_URL" \
      --health-url "${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health" \
      --metrics-url "${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/metrics" \
      --model "$STATEBUS_LOCAL_VLLM_MODEL" \
      --run-salt "${STAMP}-${mode}" \
      --output-json "$stdout_json" \
      > "$command_log" 2> "$stderr_log" \
      && python3 -m json.tool "$stdout_json" > /dev/null \
      && verify_report prefix "$stdout_json"; then
    record_status "$stage_id" pass "$stdout_json"
    log "PASS  ${stage_id}"
    return 0
  fi
  record_status "$stage_id" fail "$stderr_log"
  log "FAIL  ${stage_id}; inspect ${stderr_log} and ${stdout_json}"
  return 0
}

write_latency_repeat_summary() {
  local output_path="${RESULT_ROOT}/latency_repeat_summary.json"
  local stderr_log="${LOG_ROOT}/14_latency_repeat_aggregate.stderr.log"
  if python3 - "$output_path" \
    "${STAGE_ROOT}/02_compare_full/stdout.json" \
    "${STAGE_ROOT}/12_compare_repeat_2/stdout.json" \
    "${STAGE_ROOT}/13_compare_repeat_3/stdout.json" 2> "$stderr_log" <<'PY'
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

output_path = Path(sys.argv[1])
rows = []
for repeat_index, raw_path in enumerate(sys.argv[2:], start=1):
    path = Path(raw_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("comparison_summary", {})
    rows.append(
        {
            "repeat_index": repeat_index,
            "source_path": str(path),
            "comparison_valid": bool(payload.get("strict_equal_quality_comparison_valid")),
            "task_ms_delta": float(summary.get("local_vllm_task_ms_delta", 0.0)),
            "llm_ms_delta": float(summary.get("local_vllm_llm_ms_delta", 0.0)),
            "total_tokens_delta": float(summary.get("local_vllm_llm_total_tokens_delta", 0.0)),
            "prompt_tokens_delta": float(summary.get("local_vllm_prompt_tokens_delta", 0.0)),
        }
    )
valid = len(rows) == 3 and all(row["comparison_valid"] for row in rows)
payload = {
    "schema_version": "statebus.serialized_latency_repeat.v1",
    "ok": valid,
    "serialized": True,
    "repeat_count": len(rows),
    "all_equal_quality_comparisons_valid": valid,
    "favorable_task_ms_repeat_count": sum(row["task_ms_delta"] < 0.0 for row in rows),
    "median_task_ms_delta": statistics.median(row["task_ms_delta"] for row in rows),
    "median_llm_ms_delta": statistics.median(row["llm_ms_delta"] for row in rows),
    "median_total_tokens_delta": statistics.median(row["total_tokens_delta"] for row in rows),
    "rows": rows,
    "latency_superiority_claim_allowed": valid and all(row["task_ms_delta"] < 0.0 for row in rows),
}
output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if not valid:
    raise SystemExit(1)
PY
  then
    record_status 14_latency_repeat_aggregate pass "$output_path"
    log "PASS  14_latency_repeat_aggregate"
  else
    record_status 14_latency_repeat_aggregate fail "$stderr_log"
    log "FAIL  14_latency_repeat_aggregate; inspect ${stderr_log} and ${output_path}"
  fi
  return 0
}

write_summary() {
  python3 - "$RESULT_ROOT" "$STATUS_FILE" <<'PY'
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
status_path = Path(sys.argv[2])
stages = []
if status_path.exists():
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        stage, status, artifact = line.split("\t", 2)
        stages.append({"stage": stage, "status": status, "artifact": artifact})
expected_stages = (
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
)
stage_name_counts = Counter(item["stage"] for item in stages)
missing_stages = [stage for stage in expected_stages if stage_name_counts[stage] == 0]
duplicate_stages = sorted(stage for stage, count in stage_name_counts.items() if count > 1)
unexpected_stages = sorted(set(stage_name_counts) - set(expected_stages))
matrix_complete = not missing_stages and not duplicate_stages and not unexpected_stages
all_stages_passed = matrix_complete and all(item["status"] == "pass" for item in stages)
continuous_max_rounds = int(os.environ.get("STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS", "0") or 0)
summary = {
    "overall_ok": matrix_complete and all(item["status"] in {"pass", "skipped"} for item in stages),
    "all_stages_passed": all_stages_passed,
    "full_matrix_passed": all_stages_passed and continuous_max_rounds == 0,
    "execution_scope": "full" if continuous_max_rounds == 0 else "diagnostic_partial",
    "result_root": str(root),
    "embedding_device": os.environ.get("STATEBUS_EMBED_DEVICE", ""),
    "vllm_base_url": os.environ.get("STATEBUS_LOCAL_VLLM_BASE_URL", ""),
    "continuous_max_rounds": continuous_max_rounds,
    "expected_stage_count": len(expected_stages),
    "recorded_stage_count": len(stages),
    "matrix_complete": matrix_complete,
    "missing_stages": missing_stages,
    "duplicate_stages": duplicate_stages,
    "unexpected_stages": unexpected_stages,
    "stages": stages,
}
(root / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
}

on_exit() {
  local exit_code=$?
  rm -f "$SOCKET_PATH"
  write_summary >> "$RUN_LOG" 2>&1 || true
  if (( exit_code != 0 )); then
    log "Full suite stopped with exit code ${exit_code}"
  fi
}
trap on_exit EXIT

write_llm_config

CONTINUOUS_MAX_ARGS=()
if [[ ! "${STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS:-0}" =~ ^[0-9]+$ ]]; then
  echo "[statebus-full] STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS must be a non-negative integer" >&2
  exit 2
fi
if (( ${STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS:-0} > 0 )); then
  CONTINUOUS_MAX_ARGS=(--max-cases "${STATEBUS_FULL_CONTINUOUS_MAX_ROUNDS}")
fi

log "StateBus Qwen3 full suite"
log "user=$(id -un) uid=$(id -u)"
log "result_root=${RESULT_ROOT}"
log "vllm=${STATEBUS_LOCAL_VLLM_BASE_URL} model=${STATEBUS_LOCAL_VLLM_MODEL}"
log "embedding_mode=local device=${STATEBUS_EMBED_DEVICE} model=${STATEBUS_EMBED_MODEL_PATH}"

VLLM_HEALTH_URL="${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health"
VLLM_HEALTH_BODY="${RESULT_ROOT}/vllm_health.body.tmp"
VLLM_HEALTH_HEADERS="${RESULT_ROOT}/vllm_health.headers.tmp"
VLLM_HEALTH_STATUS="$(
  curl -sS -D "$VLLM_HEALTH_HEADERS" -o "$VLLM_HEALTH_BODY" -w '%{http_code}' "$VLLM_HEALTH_URL"
)"
python3 - "$VLLM_HEALTH_URL" "$VLLM_HEALTH_STATUS" "$VLLM_HEALTH_HEADERS" "$VLLM_HEALTH_BODY" \
  > "${RESULT_ROOT}/vllm_health.json" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

url, status_text, headers_path, body_path = sys.argv[1:]
body = Path(body_path).read_text(encoding="utf-8", errors="replace")
headers = Path(headers_path).read_text(encoding="utf-8", errors="replace")
try:
    body_json = json.loads(body) if body.strip() else None
except json.JSONDecodeError:
    body_json = None
status = int(status_text)
print(
    json.dumps(
        {
            "schema_version": "statebus.http_health_probe.v1",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "http_status": status,
            "ok": 200 <= status < 300,
            "headers": headers.splitlines(),
            "body_text": body,
            "body_json": body_json,
        },
        ensure_ascii=False,
        indent=2,
    )
)
PY
rm -f "$VLLM_HEALTH_BODY" "$VLLM_HEALTH_HEADERS"
if [[ ! "$VLLM_HEALTH_STATUS" =~ ^2[0-9][0-9]$ ]]; then
  echo "[statebus-full] vLLM health probe failed with HTTP ${VLLM_HEALTH_STATUS}" >&2
  exit 1
fi
nvidia-smi --query-gpu=index,name,memory.used,memory.free --format=csv,noheader \
  > "${RESULT_ROOT}/gpu_snapshot.txt" 2>&1 || true

python3 - <<'PY' > "${RESULT_ROOT}/embedding_check.json"
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import torch

from v2.memory.embedding import SentenceTransformerEmbeddingEncoder

model_path = Path(os.environ["STATEBUS_EMBED_MODEL_PATH"])
payload = {
    "embedding_mode": "local",
    "device": os.environ["STATEBUS_EMBED_DEVICE"],
    "model_path": str(model_path),
    "model_path_exists": model_path.exists(),
    "sentence_transformers_present": importlib.util.find_spec("sentence_transformers") is not None,
    "torch_cuda_available": bool(torch.cuda.is_available()),
    "torch_cuda_device_count": int(torch.cuda.device_count()),
    "probe_ok": False,
    "probe_dims": 0,
    "probe_error": "",
}
if not payload["model_path_exists"] or not payload["sentence_transformers_present"]:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(1)
if payload["device"].startswith("cuda") and not payload["torch_cuda_available"]:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(1)
try:
    probe = SentenceTransformerEmbeddingEncoder(
        model_path=model_path,
        device=str(payload["device"]),
    ).encode(
        embedding_id="full-suite-preflight",
        text="StateBus local embedding GPU preflight",
    )
    payload["probe_ok"] = True
    payload["probe_dims"] = probe.dims
except Exception as exc:
    payload["probe_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(payload, ensure_ascii=False, indent=2))
if not payload["probe_ok"]:
    raise SystemExit(1)
PY

run_stage 00_preflight preflight --suite preflight --benchmark-tier dev

if [[ "${STATEBUS_FULL_RUN_PYTEST:-1}" == "1" ]]; then
  log "START 01_pytest_v2"
  if env \
      -u STATEBUS_PREFIX_ALIGNMENT_MODE \
      -u STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED \
      STATEBUS_EMBED_DEVICE=cpu \
      python3 -m pytest -q tests/v2 > "${LOG_ROOT}/01_pytest_v2.log" 2>&1; then
    record_status 01_pytest_v2 pass "${LOG_ROOT}/01_pytest_v2.log"
    log "PASS  01_pytest_v2"
  else
    record_status 01_pytest_v2 fail "${LOG_ROOT}/01_pytest_v2.log"
    log "FAIL  01_pytest_v2"
  fi
else
  record_status 01_pytest_v2 skipped "STATEBUS_FULL_RUN_PYTEST=0"
fi

if [[ "${STATEBUS_FULL_SKIP_COMPARE:-0}" != "1" ]]; then
  run_stage 02_compare_full compare \
    --suite compare --benchmark-tier formal --statebus-mode cold-start
else
  record_status 02_compare_full skipped "STATEBUS_FULL_SKIP_COMPARE=1"
fi

if [[ "${STATEBUS_FULL_SKIP_REPLAY:-0}" != "1" ]]; then
  run_stage 03_replay_full replay \
    --suite statebus --benchmark-tier formal --statebus-mode replay-ready --layer L3
else
  record_status 03_replay_full skipped "STATEBUS_FULL_SKIP_REPLAY=1"
fi

if [[ "${STATEBUS_FULL_SKIP_CONTINUOUS:-0}" != "1" ]]; then
  run_stage 04_continuous_csv_full continuous \
    --suite continuous --family csv_table_profile "${CONTINUOUS_MAX_ARGS[@]}"
  run_stage 05_continuous_cross_full continuous \
    --suite continuous --family cross_period_financial "${CONTINUOUS_MAX_ARGS[@]}"
else
  record_status 04_continuous_csv_full skipped "STATEBUS_FULL_SKIP_CONTINUOUS=1"
  record_status 05_continuous_cross_full skipped "STATEBUS_FULL_SKIP_CONTINUOUS=1"
fi

if [[ "${STATEBUS_FULL_SKIP_FORMAL:-0}" != "1" ]]; then
  run_stage 06_formal_full formal \
    --suite formal --benchmark-tier formal
else
  record_status 06_formal_full skipped "STATEBUS_FULL_SKIP_FORMAL=1"
fi

if [[ "${STATEBUS_FULL_SKIP_SUBPROCESS:-0}" != "1" ]]; then
  run_stage 07_formal_subprocess_uds_full formal_subprocess \
    --suite formal --benchmark-tier formal --transport subprocess
else
  record_status 07_formal_subprocess_uds_full skipped "STATEBUS_FULL_SKIP_SUBPROCESS=1"
fi

if [[ "${STATEBUS_FULL_SKIP_GENERICITY:-0}" != "1" ]]; then
  STATEBUS_ROUTE_HINTS_ENABLED=0 run_genericity_stage
else
  record_status 08_genericity_holdout skipped "STATEBUS_FULL_SKIP_GENERICITY=1"
fi

if [[ "${STATEBUS_FULL_SKIP_PREFIX:-0}" != "1" ]]; then
  run_prefix_stage 09_prefix_shared shared_evidence_prefix
  run_prefix_stage 10_prefix_independent independent
else
  record_status 09_prefix_shared skipped "STATEBUS_FULL_SKIP_PREFIX=1"
  record_status 10_prefix_independent skipped "STATEBUS_FULL_SKIP_PREFIX=1"
fi

if [[ "${STATEBUS_FULL_SKIP_CARRIER:-0}" != "1" ]]; then
  run_stage 11_carrier_compare_full carrier \
    --suite carrier-compare --benchmark-tier formal
else
  record_status 11_carrier_compare_full skipped "STATEBUS_FULL_SKIP_CARRIER=1"
fi

if [[ "${STATEBUS_FULL_SKIP_LATENCY_REPEAT:-0}" != "1" ]]; then
  run_stage 12_compare_repeat_2 compare \
    --suite compare --benchmark-tier formal --statebus-mode cold-start
  run_stage 13_compare_repeat_3 compare \
    --suite compare --benchmark-tier formal --statebus-mode cold-start
  write_latency_repeat_summary
else
  record_status 12_compare_repeat_2 skipped "STATEBUS_FULL_SKIP_LATENCY_REPEAT=1"
  record_status 13_compare_repeat_3 skipped "STATEBUS_FULL_SKIP_LATENCY_REPEAT=1"
  record_status 14_latency_repeat_aggregate skipped "STATEBUS_FULL_SKIP_LATENCY_REPEAT=1"
fi

log "START 15_tag_baseline_audit"
if python3 scripts/audit_v2_tag_baseline.py \
    --tag "${STATEBUS_REFERENCE_TAG:-v2-non-kv-baseline-20260710}" \
    --output-json "${RESULT_ROOT}/tag_baseline_audit.json" \
    > "${LOG_ROOT}/15_tag_baseline_audit.log" 2> "${LOG_ROOT}/15_tag_baseline_audit.stderr.log"; then
  record_status 15_tag_baseline_audit pass "${RESULT_ROOT}/tag_baseline_audit.json"
  log "PASS  15_tag_baseline_audit"
else
  record_status 15_tag_baseline_audit fail "${LOG_ROOT}/15_tag_baseline_audit.stderr.log"
  log "FAIL  15_tag_baseline_audit"
fi

write_summary | tee "${RESULT_ROOT}/summary.stdout.json"
if python3 - "${RESULT_ROOT}/summary.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("overall_ok") is True else 1)
PY
then
  if python3 - "${RESULT_ROOT}/summary.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("full_matrix_passed") is True else 1)
PY
  then
    log "Full suite PASS: ${RESULT_ROOT}/summary.json"
  else
    log "Suite completed with intentional skips or diagnostic scope: ${RESULT_ROOT}/summary.json"
  fi
else
  log "Suite completed with one or more failed or missing stages: ${RESULT_ROOT}/summary.json"
  exit 1
fi
