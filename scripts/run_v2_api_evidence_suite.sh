#!/usr/bin/env bash
set -euo pipefail

if [[ -d /workspace/statebus/project ]]; then
  cd /workspace/statebus/project
else
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
fi

if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/bin/activate_statebus_container.sh
elif [[ -f deploy/activate_statebus_host.sh ]]; then
  # shellcheck disable=SC1091
  source deploy/activate_statebus_host.sh
fi

export STATEBUS_RUNS_DIR="${STATEBUS_RUNS_DIR:-/statebus/runs}"
export STATEBUS_WORKDIR="${STATEBUS_WORKDIR:-/statebus/work}"
export CUDA_VISIBLE_DEVICES="${STATEBUS_API_EVIDENCE_CUDA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES:-0}}"
export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:0}"
export STATEBUS_CODEACT_SANDBOX_BACKEND="${STATEBUS_API_EVIDENCE_CODEACT_SANDBOX_BACKEND:-auto}"

mode="${STATEBUS_API_EVIDENCE_MODE:-full}"
embedding_mode="${STATEBUS_API_EVIDENCE_EMBEDDING_MODE:-local}"
log_root="${STATEBUS_RUNS_DIR}/v2-api-evidence-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$log_root"

echo "[statebus-v2-api-evidence] mode: ${mode}"
echo "[statebus-v2-api-evidence] embedding_mode: ${embedding_mode}"
echo "[statebus-v2-api-evidence] CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES}"
echo "[statebus-v2-api-evidence] STATEBUS_EMBED_DEVICE: ${STATEBUS_EMBED_DEVICE}"
echo "[statebus-v2-api-evidence] STATEBUS_EMBED_MODEL_PATH: ${STATEBUS_EMBED_MODEL_PATH:-<default>}"
echo "[statebus-v2-api-evidence] STATEBUS_CODEACT_SANDBOX_BACKEND: ${STATEBUS_CODEACT_SANDBOX_BACKEND}"

run_step() {
  local label="$1"
  shift
  echo
  echo "=== ${label} ==="
  "$@" | tee "${log_root}/${label}.log"
}

local_embedding_stack_check() {
  python3 - <<'PY'
import importlib.util
import json
import os

payload = {
    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
    "statebus_embed_device": os.environ.get("STATEBUS_EMBED_DEVICE", ""),
    "sentence_transformers_present": importlib.util.find_spec("sentence_transformers") is not None,
    "torch_present": importlib.util.find_spec("torch") is not None,
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
else:
    payload.update(
        {
            "torch_version": "",
            "torch_cuda_available": False,
            "torch_cuda_device_count": 0,
        }
    )
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

run_step pytest-v2 python3 -m pytest -q tests/v2

if [[ "$embedding_mode" == "local" ]]; then
  run_step local-embedding-stack local_embedding_stack_check
fi

run_step preflight-api \
  python3 -m v2.benchmark.live_runner \
    --suite preflight \
    --role-path-mode api \
    --embedding-mode "$embedding_mode"

run_step formal-api \
  python3 -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode "$embedding_mode"

run_step carrier-compare-api \
  python3 -m v2.benchmark.live_runner \
    --suite carrier-compare \
    --benchmark-tier dev \
    --role-path-mode api \
    --embedding-mode "$embedding_mode" \
    --statebus-mode cold-start

run_step external-compare-api-debug \
  python3 -m v2.benchmark.live_runner \
    --suite compare \
    --benchmark-tier dev \
    --role-path-mode api \
    --embedding-mode "$embedding_mode" \
    --statebus-mode cold-start

run_step replay-negative-audit \
  python3 -m v2.benchmark.live_runner \
    --suite replay-negative-audit \
    --role-path-mode api \
    --embedding-mode "$embedding_mode"

if [[ "$mode" == "full" ]]; then
  run_step flagship-ablation-api \
    python3 -m v2.benchmark.live_runner \
      --suite flagship-ablation \
      --role-path-mode api \
      --embedding-mode "$embedding_mode"
else
  echo
  echo "=== flagship-ablation-api ==="
  echo "skipped because STATEBUS_API_EVIDENCE_MODE=${mode}"
fi

flagship_report="${STATEBUS_RUNS_DIR}/v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json"
carrier_report="${STATEBUS_RUNS_DIR}/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json"
compare_report="${STATEBUS_RUNS_DIR}/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json"
formal_report="${STATEBUS_RUNS_DIR}/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json"
replay_negative_report="${STATEBUS_RUNS_DIR}/v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json"

echo
echo "=== report paths ==="
for report in "$formal_report" "$carrier_report" "$compare_report" "$flagship_report" "$replay_negative_report"; do
  if [[ -f "$report" ]]; then
    echo "$report"
  else
    echo "missing: $report"
  fi
done | tee "${log_root}/report_paths.txt"

if command -v jq >/dev/null 2>&1; then
  if [[ -f "$flagship_report" ]]; then
    jq '{
      role_path_mode,
      claim_level,
      non_text_state_stress_summary,
      fixed_answer: .fixed_answer_evidence.layer_summary,
      continuous: [.continuous_evidence[] | {
        family_id,
        l0_tokens: .l0_internal_pure_text.llm_total_tokens,
        l1_tokens: .l1_structured_full_evidence.llm_total_tokens,
        l2_tokens: .l2_structured_semantic_state.llm_total_tokens,
        t2_tokens: .t2_text_same_semantic_selection.llm_total_tokens,
        l2_raw_reduction_pct_vs_l1: .l2_structured_semantic_state.raw_evidence_reduction_pct_vs_l1,
        l3_history_step_reduction_count: .l3_memory_replay.history_step_reduction_count,
        l3_runtime_driver_stage_ms: .l3_memory_replay.runtime_driver_stage_ms
      }],
      replay: [.continuous_replay_evidence[] | {
        family_id,
        l0_tokens: .l0_internal_pure_text.llm_total_tokens,
        l1_tokens: .l1_structured_full_evidence.llm_total_tokens,
        l2_tokens: .l2_structured_semantic_state.llm_total_tokens,
        t2_tokens: .t2_text_same_semantic_selection.llm_total_tokens,
        l3_tokens: .l3_memory_replay.llm_total_tokens,
        l3_exact_replay_count: .l3_memory_replay.exact_replay_count,
        l3_validated_replay_count: .l3_memory_replay.validated_replay_count,
        l3_skipped_step_count: .l3_memory_replay.skipped_step_count
      }]
    }' "$flagship_report" | tee "${log_root}/flagship_summary.json"
  fi
  if [[ -f "$carrier_report" ]]; then
    jq '{comparison_summary, mode_reports}' "$carrier_report" | tee "${log_root}/carrier_compare_summary.json"
  fi
  if [[ -f "$compare_report" ]]; then
    jq '{comparison_summary, mode_reports}' "$compare_report" | tee "${log_root}/external_compare_summary.json"
  fi
  if [[ -f "$replay_negative_report" ]]; then
    jq '{audit_pass, case_count, cases}' "$replay_negative_report" | tee "${log_root}/replay_negative_audit_summary.json"
  fi
fi

echo
echo "=== log root ==="
echo "$log_root"
