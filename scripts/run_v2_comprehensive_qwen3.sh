#!/usr/bin/env bash
# =============================================================================
# StateBus v2 全量实验脚本 — Qwen3-32B 主线 (2026-07)
# =============================================================================
# 目标覆盖（参见 docs/improvement/.../31_comprehensive_gap_audit_20260711.md）：
#   G-01  same-task text vs protocol 等价对比 (--suite compare)
#   G-02  KV 主线 replay memory 激活 (--statebus-mode replay-ready)
#   G-03  ≥2 family continuous (csv_table_profile + cross_period_financial)
#   G-05  logit/KV chain 链路验证 (smoke + task_metrics.json)
#   G-11  KV 主线连续稳定性 (continuous with local_vllm)
#
# 设计原则：
#   - 全程使用 Qwen3-32B (qwen3-32b, port 53334), 替代 DeepSeek
#   - 顺序：简单 → 复杂 (preflight → logit → compare → statebus → continuous → formal)
#   - 每步结果落盘到 $RESULTS_DIR/s{N}_*/
#   - 不做统计 repeat；每个实验只跑一次
#   - 8192 context 限制：简单任务先跑，formal 最后
#
# 用法（宿主机，/home/qcrs/statebus/project 目录下）：
#   source deploy/activate_statebus_host.sh   # 激活宿主机环境（如需要）
#   export STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
#   bash scripts/run_v2_comprehensive_qwen3.sh
#
# 如需跳过某些 stage，设置环境变量，例如：
#   SKIP_STAGE_FORMAL=1 bash scripts/run_v2_comprehensive_qwen3.sh
# =============================================================================

set -euo pipefail

# ── 时间戳 & 目录 ─────────────────────────────────────────────────────────────
STAMP="${STATEBUS_COMPREHENSIVE_STAMP:-$(date +%Y%m%d_%H%M%S)}"
HOST_RUNS_ROOT="${STATEBUS_HOST_RUNS_ROOT:-/home/qcrs/statebus/runs}"
RESULTS_DIR="${HOST_RUNS_ROOT}/comprehensive_qwen3_${STAMP}"
mkdir -p "$RESULTS_DIR"
export STAMP HOST_RUNS_ROOT RESULTS_DIR

# ── 公共环境变量（所有 stage 共享）───────────────────────────────────────────
export STATEBUS_LOCAL_VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53334/v1}"
export STATEBUS_LOCAL_VLLM_MODEL="${STATEBUS_LOCAL_VLLM_MODEL:-qwen3-32b}"
export STATEBUS_VLLM_SERVED_MODEL_NAME="${STATEBUS_VLLM_SERVED_MODEL_NAME:-qwen3-32b}"
export STATEBUS_EMBED_DEVICE="${STATEBUS_EMBED_DEVICE:-cuda:1}"
export STATEBUS_EMBED_MODEL_PATH="${STATEBUS_EMBED_MODEL_PATH:-/statebus/models/Qwen3-Embedding-0.6B}"
# 全程开启 shared_evidence_prefix + dynamic pruning (E6 profile, 验证 G-05 prefix hit-rate)
export STATEBUS_PREFIX_ALIGNMENT_MODE="${STATEBUS_PREFIX_ALIGNMENT_MODE:-shared_evidence_prefix}"
export STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED="${STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED:-1}"

# ── 工具函数 ──────────────────────────────────────────────────────────────────
LOG="${RESULTS_DIR}/run.log"
log()  { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
pass() { log "  ✓ $*"; }
warn() { log "  ⚠ $*"; }
die()  { log "  ✗ FATAL: $*"; exit 1; }

# 跑一次 formal suite（用 run_v2_local_vllm_formal_suite.sh）
run_formal_suite() {
    local stage="$1"; shift
    # 调用方设置好 STATEBUS_LOCAL_VLLM_FORMAL_* 变量
    bash scripts/run_v2_local_vllm_formal_suite.sh "$@" \
        >> "${RESULTS_DIR}/${stage}.log" 2>&1 \
    && pass "${stage} completed" \
    || { warn "${stage} exit non-zero — check ${RESULTS_DIR}/${stage}.log"; return 1; }
}

# 直接在容器内跑任意 live_runner 命令（用于需要自定义参数的 stage）
run_in_container() {
    local stage="$1"; shift
    local cmd="$1"; shift
    STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="${stage}" \
    ./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "$cmd" \
        >> "${RESULTS_DIR}/${stage}.log" 2>&1 \
    && pass "${stage} completed" \
    || { warn "${stage} exit non-zero — check ${RESULTS_DIR}/${stage}.log"; return 1; }
}

log "=========================================="
log "  StateBus v2 综合实验 — Qwen3-32B"
log "  STAMP=${STAMP}"
log "  RESULTS_DIR=${RESULTS_DIR}"
log "=========================================="

# =============================================================================
# Stage 0: 环境健康检查（前提，不可跳过）
# =============================================================================
log "=== Stage 0: 环境健康检查 ==="

curl -sf "${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health" \
    -o "${RESULTS_DIR}/s0_vllm_health.json" \
    || die "vLLM 服务不可达，请检查 ${STATEBUS_LOCAL_VLLM_BASE_URL%/v1}/health"

# 检查 GPU 内存（qwen3-32b 需要约 65GB）
docker exec statebus-dev-qcrs bash -c \
    "nvidia-smi --query-gpu=index,memory.used,memory.free --format=csv,noheader" \
    > "${RESULTS_DIR}/s0_gpu_memory.txt" 2>&1 || warn "nvidia-smi 不可用，跳过 GPU 检查"

pass "Stage 0 完成"

# =============================================================================
# Stage 1: Preflight — 配置与依赖检查（不调用模型）
# Track C 的真实 guided-JSON 兼容性由 Stage 3 compare 的 external lane 验证。
# 注意：preflight suite 输出 {"ok":true,"checks":[...]} 扁平格式，
#       不经过 run_v2_local_vllm_formal_suite.sh 的 jq 汇总（该脚本期望 .layers[]）。
#       直接在容器内运行并检查 ok=true。
# =============================================================================
log "=== Stage 1: Preflight (配置与依赖，不调用模型) ==="
[[ -n "${SKIP_STAGE_PREFLIGHT:-}" ]] && { warn "SKIP_STAGE_PREFLIGHT 已设置，跳过"; } || {

S1_RUN_ID="s1-preflight-${STAMP}"
S1_RUN_ROOT="${HOST_RUNS_ROOT}/${S1_RUN_ID}"
S1_CONTAINER_RUN_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}/${S1_RUN_ID}"
S1_STDOUT_JSON="${S1_RUN_ROOT}/preflight.stdout.json"
S1_CONTAINER_STDOUT_JSON="${S1_CONTAINER_RUN_ROOT}/preflight.stdout.json"
mkdir -p "$S1_RUN_ROOT"

# 在容器内直接运行 preflight suite（不走 formal_suite 包装器）
STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$S1_RUN_ID" \
./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "
mkdir -p '${S1_CONTAINER_RUN_ROOT}'
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite preflight \
  --benchmark-tier dev \
  --role-path-mode local_vllm \
  --embedding-mode local \
  --state-pool-mode auto \
  --transport loopback \
  --workspace-root '${S1_CONTAINER_RUN_ROOT}/workspaces' \
  --runtime-root '${S1_CONTAINER_RUN_ROOT}/runtime' \
  --socket-path '${S1_CONTAINER_RUN_ROOT}/control.sock' \
  --suite-id '${S1_RUN_ID}' \
  > '${S1_CONTAINER_STDOUT_JSON}'
" >> "${RESULTS_DIR}/s1_preflight.log" 2>&1 \
    || die "Stage 1 preflight 容器命令失败 — 查看 ${RESULTS_DIR}/s1_preflight.log"

# 检查 preflight ok=true（preflight 输出 {"ok":true|false,"checks":[...]}）
if [[ -f "$S1_STDOUT_JSON" ]]; then
    S1_OK=$(jq -r '.ok // false' "$S1_STDOUT_JSON" 2>/dev/null || echo "false")
    if [[ "$S1_OK" != "true" ]]; then
        warn "preflight ok=false — 详见 ${S1_STDOUT_JSON}"
        jq '.checks[] | select(.ok==false)' "$S1_STDOUT_JSON" 2>/dev/null \
            >> "${RESULTS_DIR}/s1_preflight.log" || true
        die "Stage 1 preflight FAILED — 后续 stage 依赖此基线"
    fi
    pass "Stage 1 preflight OK — $(jq '.checks | length' "$S1_STDOUT_JSON") checks passed"
else
    die "Stage 1 preflight stdout JSON 未生成 — 查看 ${RESULTS_DIR}/s1_preflight.log"
fi

}

# =============================================================================
# Stage 2: Logit KV 链路验证 — statebus dev 单 case (~10min)
# 验证目标：Track A logit_state_transfer_count=1, peak_position 非末位,
#           varentropy>0, neural_prefix_shared_prefix_bytes>0 (G-05)
# 8192 限制：dev tier 任务短，首先跑
# =============================================================================
log "=== Stage 2: Logit + KV 链路验证 (dev tier, one pinned case) ==="
[[ -n "${SKIP_STAGE_LOGIT:-}" ]] && { warn "SKIP_STAGE_LOGIT 已设置，跳过"; } || {

RUN_ID_LOGIT="s2-logit-verify-${STAMP}"
STATEBUS_LOCAL_VLLM_FORMAL_STAMP="$STAMP" \
STATEBUS_LOCAL_VLLM_FORMAL_SUITE=statebus \
STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER=dev \
STATEBUS_LOCAL_VLLM_FORMAL_EMBEDDING_MODE=local \
STATEBUS_LOCAL_VLLM_FORMAL_MAX_CASES=1 \
STATEBUS_LOCAL_VLLM_FORMAL_CASE_ID=fixed-answer-worker-001 \
STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID="$RUN_ID_LOGIT" \
run_formal_suite "s2_logit_verify"

# 验证 logit 字段值
LOGIT_RUN_DIR="${HOST_RUNS_ROOT}/${RUN_ID_LOGIT}"
python3 - <<PYEOF > "${RESULTS_DIR}/s2_logit_report.json"
import json, glob, os, sys
run_dir = "${LOGIT_RUN_DIR}"
files = glob.glob(f"{run_dir}/workspaces/L3/fixed-answer-worker-001/logs/task_metrics.json")
results = []
for f in files:
    with open(f, encoding="utf-8") as handle:
        m = json.load(handle)
    results.append({
        "file": f,
        "logit_state_transfer_count": m.get("logit_state_transfer_count"),
        "logit_peak_position": m.get("logit_peak_position"),
        "logit_varentropy": m.get("logit_varentropy"),
        "logit_top_gap": m.get("logit_top_gap"),
        "logit_state_mean_entropy": m.get("logit_state_mean_entropy"),
        "logit_sequence_length": m.get("logit_sequence_length"),
        "logit_decision_entropy": m.get("logit_decision_entropy"),
        "neural_prefix_shared_prefix_bytes": m.get("neural_prefix_shared_prefix_bytes"),
        "state_pool_shared_memory_mode_count": m.get("state_pool_shared_memory_mode_count"),
    })
print(json.dumps({"stage": "s2_logit_verify", "cases": results}, indent=2))
PYEOF
S2_OK=$(jq -r '
  (.cases | length) == 1 and
  (.cases[0].logit_state_transfer_count // 0) > 0 and
  (.cases[0].logit_sequence_length // 0) > 0 and
  (.cases[0].logit_peak_position // -1) >= 0 and
  (.cases[0].logit_peak_position < .cases[0].logit_sequence_length)
' "${RESULTS_DIR}/s2_logit_report.json")
[[ "$S2_OK" == "true" ]] || die "Stage 2 logit gate failed"
pass "Stage 2 logit report 写入 ${RESULTS_DIR}/s2_logit_report.json"

}

# =============================================================================
# Stage 3: Compare — Qwen3 text lane vs protocol lane (G-01 修复, ~1.5h)
# 验证目标：same-task text vs protocol token/byte delta, quality delta=0
#   formal_external_claim_kind 字段从 debug_only 升级为 formal_quality_superiority
# 8192 限制：compare 每 case 只跑 2 lane，比 formal L0-L3 轻
# =============================================================================
log "=== Stage 3: Compare suite — text vs protocol (G-01) ==="
[[ -n "${SKIP_STAGE_COMPARE:-}" ]] && { warn "SKIP_STAGE_COMPARE 已设置，跳过"; } || {

STATEBUS_LOCAL_VLLM_FORMAL_STAMP="$STAMP" \
STATEBUS_LOCAL_VLLM_FORMAL_SUITE=compare \
STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER=formal \
STATEBUS_LOCAL_VLLM_FORMAL_EMBEDDING_MODE=local \
STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID="s3-compare-qwen3-${STAMP}" \
run_formal_suite "s3_compare" \
    || die "Stage 3 compare failed"

}

# =============================================================================
# Stage 4: Statebus replay-ready — KV 主线 + 自动 bootstrap replay (G-02, ~1.5h)
# 验证目标：L3 replay-ready 自动先跑 L0 bootstrap 建立 history，
#   再跑 replay_ready，产生 reuse_gain>0 / validated_replay>0 的 KV 主线证据
# 注：fixed_answer_runner.py:549 已内置 history_backed_replay_enabled 逻辑，
#   只需 --statebus-mode replay-ready 即可，无需手动分两次
# =============================================================================
log "=== Stage 4: Statebus replay-ready (G-02 KV 主线 replay memory) ==="
[[ -n "${SKIP_STAGE_REPLAY:-}" ]] && { warn "SKIP_STAGE_REPLAY 已设置，跳过"; } || {

RUN_ID_REPLAY="s4-statebus-replay-${STAMP}"
CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
CONTAINER_RUN_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID_REPLAY}"
CONTAINER_SOCKET="${CONTAINER_RUN_ROOT}/control.sock"
HOST_RUN_ROOT="${HOST_RUNS_ROOT}/${RUN_ID_REPLAY}"
mkdir -p "$HOST_RUN_ROOT"

REPLAY_CMD="
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite statebus \
  --benchmark-tier formal \
  --statebus-mode replay-ready \
  --role-path-mode local_vllm \
  --embedding-mode local \
  --state-pool-mode auto \
  --workspace-root '${CONTAINER_RUN_ROOT}/workspaces' \
  --runtime-root '${CONTAINER_RUN_ROOT}/runtime' \
  --socket-path '${CONTAINER_SOCKET}' \
  --suite-id '${RUN_ID_REPLAY}' \
  > '${CONTAINER_RUN_ROOT}/stdout.json'
"
STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$RUN_ID_REPLAY" \
    ./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "$REPLAY_CMD" \
    >> "${RESULTS_DIR}/s4_replay.log" 2>&1 \
    && pass "Stage 4 replay-ready 完成" \
    || die "Stage 4 replay-ready failed"

}

# =============================================================================
# Stage 5: Continuous multi-family (G-03 ≥2 families, G-11 KV 连续稳定性, ~2h)
# 用 csv_table_profile (简单，短 doc) 和 cross_period_financial (复杂) 各跑一次
# 两个 family 覆盖"≥2 组关联性连续任务"要求
# 8192 限制：csv family 在前（短文本），financial 在后（长文本）
# =============================================================================
log "=== Stage 5a: Continuous csv_table_profile (G-03/G-11, 第1 family) ==="
[[ -n "${SKIP_STAGE_CONTINUOUS:-}" ]] && { warn "SKIP_STAGE_CONTINUOUS 已设置，跳过"; } || {

for FAMILY_ID in csv_table_profile cross_period_financial; do
    log "  → family: ${FAMILY_ID}"
    RUN_ID_CONT="s5-continuous-${FAMILY_ID}-${STAMP}"
    CONTAINER_RUNS_ROOT="${STATEBUS_CONTAINER_RUNS_ROOT:-/statebus/runs}"
    CONTAINER_RUN_ROOT="${CONTAINER_RUNS_ROOT}/${RUN_ID_CONT}"
    CONTAINER_SOCKET="${CONTAINER_RUN_ROOT}/control.sock"
    HOST_RUN_ROOT="${HOST_RUNS_ROOT}/${RUN_ID_CONT}"
    mkdir -p "$HOST_RUN_ROOT"

    CONT_CMD="
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite continuous \
  --family '${FAMILY_ID}' \
  --role-path-mode local_vllm \
  --embedding-mode local \
  --state-pool-mode auto \
  --statebus-mode cold-start \
  --workspace-root '${CONTAINER_RUN_ROOT}/workspaces' \
  --runtime-root '${CONTAINER_RUN_ROOT}/runtime' \
  --socket-path '${CONTAINER_SOCKET}' \
  --suite-id '${RUN_ID_CONT}' \
  > '${CONTAINER_RUN_ROOT}/stdout.json'
"
    STATEBUS_LOCAL_VLLM_CHECK_RUN_ID="$RUN_ID_CONT" \
        ./scripts/run_v2_local_vllm_container_check.sh /bin/bash -lc "$CONT_CMD" \
        >> "${RESULTS_DIR}/s5_continuous_${FAMILY_ID}.log" 2>&1 \
        && pass "Stage 5 continuous ${FAMILY_ID} 完成" \
        || die "Stage 5 continuous ${FAMILY_ID} failed"
done

}

# =============================================================================
# Stage 6: Formal L0-L3 — Qwen3-32B 全量 25 case (替代 DeepSeek E6, ~3-4h)
# 验证目标：L0-L3 质量 delta=0, L3 vs L0 token delta (G-01 补充), 25/25
# 这是最重的 stage，放在最后
# 8192 context：financial 长文本，放最后确保 GPU 不受前面任务影响
# =============================================================================
log "=== Stage 6: Formal L0-L3 全量 — Qwen3-32B E7 (G-01 final, ~3-4h) ==="
[[ -n "${SKIP_STAGE_FORMAL:-}" ]] && { warn "SKIP_STAGE_FORMAL 已设置，跳过"; } || {

STATEBUS_LOCAL_VLLM_FORMAL_STAMP="$STAMP" \
STATEBUS_LOCAL_VLLM_FORMAL_SUITE=formal \
STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER=formal \
STATEBUS_LOCAL_VLLM_FORMAL_EMBEDDING_MODE=local \
STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID="s6-formal-qwen3-e7-${STAMP}" \
run_formal_suite "s6_formal_e7" \
    || die "Stage 6 formal failed"

}

# =============================================================================
# 最终汇总报告
# =============================================================================
log "=========================================="
log "  所有 stage 完成，生成汇总报告"
log "=========================================="

python3 - <<'PYEOF' | tee "${RESULTS_DIR}/final_summary.json"
import glob
import json
import os

results_dir = os.environ.get("RESULTS_DIR", "")
summary = {"overall_ok": True, "stamp": os.environ.get("STAMP", ""), "stages": {}}

def read_first_json(pattern):
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        return {}, "missing"
    try:
        with open(files[0], encoding="utf-8") as handle:
            return json.load(handle), "ok"
    except (OSError, json.JSONDecodeError):
        return {}, "invalid_json"

def layer_payload(payload, layer_name):
    for layer in payload.get("layers", []):
        if layer.get("layer") == layer_name:
            return layer
    return {}

host_runs = os.environ.get("HOST_RUNS_ROOT", "/home/qcrs/statebus/runs")
stamp = os.environ.get("STAMP", "")

# Stage 3: compare — 关键字段
compare_stdout, compare_status = read_first_json(
    f"{host_runs}/s3-compare-qwen3-{stamp}/formal_suite.stdout.json"
)
compare_metrics = compare_stdout.get("comparison_summary", {})
summary["stages"]["s3_compare"] = {
    "status": compare_status,
    "case_count": compare_stdout.get("formal_compare_case_count"),
    "statebus_total_tokens": compare_metrics.get("local_vllm_statebus_llm_total_tokens"),
    "external_total_tokens": compare_metrics.get("local_vllm_external_llm_total_tokens"),
    "statebus_vs_external_token_delta": compare_metrics.get("local_vllm_llm_total_tokens_delta"),
    "statebus_vs_external_prompt_token_delta": compare_metrics.get("local_vllm_prompt_tokens_delta"),
    "statebus_quality_pass_count": compare_metrics.get(
        "local_vllm_statebus_quality_floor_pass_count",
        compare_metrics.get("local_vllm_debug_statebus_quality_floor_pass_count"),
    ),
    "external_quality_pass_count": compare_metrics.get(
        "local_vllm_external_quality_floor_pass_count",
        compare_metrics.get("local_vllm_debug_external_quality_floor_pass_count"),
    ),
    "formal_external_claim_kind": compare_stdout.get("formal_external_claim_kind"),
    "quality_superiority_claim_allowed": compare_stdout.get("formal_quality_superiority_claim_allowed"),
    "strict_equal_quality_comparison_valid": compare_stdout.get("strict_equal_quality_comparison_valid"),
}

# Stage 4: replay — 关键字段
replay_stdout_path = f"{host_runs}/s4-statebus-replay-{stamp}/stdout.json"
if os.path.exists(replay_stdout_path):
    try:
        with open(replay_stdout_path, encoding="utf-8") as handle:
            replay_data = json.load(handle)
        replay_status = "ok"
    except (OSError, json.JSONDecodeError):
        replay_data = {}
        replay_status = "invalid_json"
    replay_l3 = layer_payload(replay_data, "L3")
    replay_metrics = replay_l3.get("telemetry_summary", {})
    summary["stages"]["s4_replay"] = {
        "status": replay_status,
        "selected_case_count": replay_data.get("selected_case_count"),
        "effective_statebus_mode": replay_data.get("effective_statebus_mode"),
        "effective_replay_history_source": replay_data.get("effective_replay_history_source"),
        "reuse_gain": replay_metrics.get("reuse_gain"),
        "validated_replay_count": replay_metrics.get("validated_replay_count"),
        "exact_replay_count": replay_metrics.get("exact_replay_count"),
        "skipped_step_count": replay_metrics.get("skipped_step_count"),
        "memory_match_count": replay_metrics.get("memory_match_count"),
    }
else:
    summary["stages"]["s4_replay"] = {"status": "missing"}

# Stage 6: formal — 关键字段
formal_stdout, formal_status = read_first_json(
    f"{host_runs}/s6-formal-qwen3-e7-{stamp}/formal_suite.stdout.json"
)
summary["stages"]["s6_formal"] = {
    "status": formal_status,
    "selected_case_count": formal_stdout.get("selected_case_count"),
    "protocol_vs_text_token_delta": formal_stdout.get("comparison_summary", {}).get("protocol_vs_text_token_delta"),
    "layers": [
        {
            "layer": l.get("layer"),
            "case_count": l.get("aggregated_metrics", {}).get("case_count"),
            "quality_floor_pass_count": l.get("aggregated_metrics", {}).get("quality_floor_pass_count"),
        }
        for l in formal_stdout.get("layers", [])
    ],
}

print(json.dumps(summary, indent=2, ensure_ascii=False))
PYEOF

log "results_dir=${RESULTS_DIR}"
log "summary=${RESULTS_DIR}/final_summary.json"
