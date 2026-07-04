#!/usr/bin/env bash
# StateBus v2 全量实验测试脚本
#
# 用法（CodeAct bwrap需root）：
#   docker exec --user root statebus-dev-qcrs bash -l /workspace/statebus/project/scripts/run_full_experiment.sh
#
# 可选环境变量：
#   SKIP_FLAGSHIP=1   跳过flagship-ablation（耗时最长）
#   SKIP_CODEACT=1    跳过CodeAct（需root）
#   SKIP_CONTINUOUS=1 跳过continuous benchmark

set -euo pipefail

# Load container environment (LLM API key, embedding model path, etc.)
if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/bin/activate_statebus_container.sh
elif [[ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/activate_statebus_host.sh" ]]; then
  # shellcheck disable=SC1091
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/activate_statebus_host.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RESULT_ROOT="/statebus/runs/full-experiment-${TIMESTAMP}"
RUNTIME_ROOT="/statebus/runs/v2-live/runtime"
WORKSPACE_ROOT="/statebus/work/v2-live/workspaces"
SOCKET_PATH="/statebus/runs/v2-live/control.sock"

mkdir -p "$RESULT_ROOT"
cd "$PROJECT_ROOT"

log() { echo "[$(date +%H:%M:%S)] $*"; }
sep() { echo ""; echo "======================================"; echo "$*"; echo "======================================"; }

sep "StateBus v2 Full Experiment"
log "Project:  $PROJECT_ROOT"
log "Results:  $RESULT_ROOT"
log "Runtime:  $RUNTIME_ROOT"

# 公共参数
COMMON_ARGS=(
  --role-path-mode api
  --embedding-mode local
  --workspace-root "$WORKSPACE_ROOT"
  --runtime-root "$RUNTIME_ROOT"
  --socket-path "$SOCKET_PATH"
)

run_suite() {
  local label="$1"; shift
  log "Starting: $label"
  python3 -m v2.benchmark.live_runner "${COMMON_ARGS[@]}" "$@" \
    > "$RESULT_ROOT/${label}.json" 2>/dev/null \
    && log "Done:     $label" \
    || log "FAILED:   $label"
}

# ----------------------------------------------------------
# 1. pytest 回归
# ----------------------------------------------------------
sep "1/9  pytest"
python3 -m pytest -q tests/v2 > "$RESULT_ROOT/01_pytest.txt" 2>&1 || true
tail -3 "$RESULT_ROOT/01_pytest.txt"

# ----------------------------------------------------------
# 2. Preflight
# ----------------------------------------------------------
sep "2/9  Preflight"
run_suite 02_preflight \
  --suite preflight

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/02_preflight.json'))
print('  ok:', d.get('ok'))
print('  role_path_mode:', d.get('role_path_mode'))
print('  embedding_mode:', d.get('embedding_mode'))
" 2>/dev/null || true

# ----------------------------------------------------------
# 3. Formal suite（L0/L1/L2/L3 layer breakdown，8 cases）
# ----------------------------------------------------------
sep "3/9  Formal Suite (L0→L3 breakdown)"
run_suite 03_formal_suite \
  --suite formal \
  --benchmark-tier formal

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/03_formal_suite.json'))
wm=d.get('waterfall_metrics',)
for k,v in sorted(wm.items()):
    print(f'  {k}: {v}')
" 2>/dev/null || true

# ----------------------------------------------------------
# 4. Formal Compare（StateBus vs External，核心论点）
# ----------------------------------------------------------
sep "4/9  Formal Compare (StateBus vs External)"
run_suite 04_formal_compare \
  --suite compare \
  --benchmark-tier formal \
  --statebus-mode cold-start

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/04_formal_compare.json'))
m=d.get('metadata',{})
cs=d.get('comparison_summary',{})
print('  formal_superiority_claim_allowed:', m.get('formal_superiority_claim_allowed'))
print('  statebus quality:', cs.get('api_debug_statebus_quality_floor_pass_count'), '/', cs.get('api_debug_case_count'))
print('  external quality:', cs.get('api_debug_external_quality_floor_pass_count'), '/', cs.get('api_debug_case_count'))
print('  quality_delta:', cs.get('api_debug_quality_floor_pass_delta'))
print('  tokens_delta:', cs.get('api_debug_llm_total_tokens_delta'))
print('  bytes_delta:', cs.get('api_debug_prompt_bytes_delta'))
print('  task_ms_delta:', cs.get('api_debug_task_ms_delta'))
print('  net_llm_ms_delta:', cs.get('api_debug_net_llm_ms_delta'))
print('  system_overhead_ms_delta:', cs.get('api_debug_system_overhead_ms_delta'))
" 2>/dev/null || true

# ----------------------------------------------------------
# 5. Carrier Compare（typed StateRef vs text_whole_lane，内部对比）
# ----------------------------------------------------------
sep "5/9  Carrier Compare (typed vs text internal)"
run_suite 05_carrier_compare \
  --suite carrier-compare \
  --benchmark-tier dev \
  --statebus-mode cold-start

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/05_carrier_compare.json'))
cs=d.get('comparison_summary',{})
for k,v in sorted(cs.items()):
    print(f'  {k}: {v}')
" 2>/dev/null || true

# ----------------------------------------------------------
# 6. StateBus cold-start（L层递增，dev family 3 cases）
# ----------------------------------------------------------
sep "6/9  StateBus cold-start"
run_suite 06_statebus_coldstart \
  --suite statebus \
  --benchmark-tier dev \
  --statebus-mode cold-start

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/06_statebus_coldstart.json'))
wm=d.get('waterfall_metrics',{})
print('  L0 scaffold:', wm.get('L0_prompt_scaffolding_bytes_total'))
print('  L1 scaffold:', wm.get('L1_prompt_scaffolding_bytes_total'))
print('  L0 handoff:', wm.get('L0_role_handoff_bytes_total'))
print('  L1 handoff:', wm.get('L1_role_handoff_bytes_total'))
print('  L2 evidence_bytes:', wm.get('L2_raw_evidence_bytes_seen_by_llm'))
print('  L2 semantic_transfer:', wm.get('L2_semantic_state_transfer_count'))
print('  L3 quality:', wm.get('L3_quality_floor_pass_count'))
print('  L3 reuse_gain:', wm.get('L3_reuse_gain'))
" 2>/dev/null || true

# ----------------------------------------------------------
# 7. StateBus replay-ready（Memory reuse 数据）
# ----------------------------------------------------------
sep "7/9  StateBus replay-ready (memory reuse)"
run_suite 07_statebus_replay \
  --suite statebus \
  --benchmark-tier dev \
  --statebus-mode replay-ready

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/07_statebus_replay.json'))
wm=d.get('waterfall_metrics',)
print('  L3 quality:', wm.get('L3_quality_floor_pass_count'))
print('  L3 reuse_gain:', wm.get('L3_reuse_gain'))
print('  L2 semantic_transfer:', wm.get('L2_semantic_state_transfer_count'))
" 2>/dev/null || true

# ----------------------------------------------------------
# 8. Replay Negative Audit
# ----------------------------------------------------------
sep "8/9  Replay Negative Audit"
run_suite 08_replay_negative_audit \
  --suite replay-negative-audit

python3 -c "
import json
d=json.load(open('$RESULT_ROOT/08_replay_negative_audit.json'))
print('  audit_pass:', d.get('audit_pass'))
print('  case_count:', d.get('case_count'))
neg_count=sum(1 for c in d.get('cases',[]) if not c.get('audit_pass',True))
print('  negative_cases:', neg_count)
" 2>/dev/null || true

# ----------------------------------------------------------
# 9. Flagship Ablation（最全：L0/L1/L2/T2/L3 + continuous + replay）
#    注：耗时最长（30-60分钟），可设 SKIP_FLAGSHIP=1 跳过
# ----------------------------------------------------------
sep "9a/9  Flagship Ablation"
if [[ "${SKIP_FLAGSHIP:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_FLAGSHIP=1)"
else
  run_suite 09_flagship_ablation \
    --suite flagship-ablation

  python3 -c "
import json
d=json.load(open('$RESULT_ROOT/09_flagship_ablation.json'))
# fixed answer evidence
fa=d.get('fixed_answer_evidence',{})
ls=fa.get('layer_summary',{})
print('  [fixed_answer layer_summary]')
for k,v in sorted(ls.items()):
    print(f'    {k}: {v}')

# continuous evidence
print('  [continuous evidence]')
for fam in d.get('continuous_evidence',[]):
    fid=fam.get('family_id','')
    l0=fam.get('l0_internal_pure_text',{}).get('llm_total_tokens','-')
    l2=fam.get('l2_structured_semantic_state',{}).get('llm_total_tokens','-')
    t2=fam.get('t2_text_same_semantic_selection',{}).get('llm_total_tokens','-')
    red=fam.get('l2_structured_semantic_state',{}).get('raw_evidence_reduction_pct_vs_l1','-')
    print(f'    {fid}: L0={l0} L2={l2} T2={t2} reduction={red}%')

# replay evidence
print('  [replay evidence]')
for fam in d.get('continuous_replay_evidence',[]):
    fid=fam.get('family_id','')
    l3=fam.get('l3_memory_replay',{})
    exact=l3.get('exact_replay_count',0)
    valid=l3.get('validated_replay_count',0)
    skipped=l3.get('skipped_step_count',0)
    print(f'    {fid}: exact_replay={exact} validated_replay={valid} skipped_steps={skipped}')
" 2>/dev/null || true
fi

# ----------------------------------------------------------
# 9b. CodeAct 生成测试（3 runs，bwrap需root）
# ----------------------------------------------------------
sep "9b/9  CodeAct bounded generation (3 runs)"
if [[ "${SKIP_CODEACT:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_CODEACT=1)"
else
  log "NOTE: bwrap requires root. Run with: docker exec --user root ..."
  CODEACT_PASS=0
  CODEACT_FALLBACK=0
  for i in 1 2 3; do
    CODEACT_OUT="$RESULT_ROOT/codeact-run-$i"
    python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
      --role-path-mode api \
      --sandbox-backend bwrap \
      --output-root "$CODEACT_OUT" 2>/dev/null || true
    SUMMARY_FILE=$(find "$CODEACT_OUT" -name "summary.json" -type f 2>/dev/null | head -1)
    if [ -n "$SUMMARY_FILE" ]; then
      python3 -c "
import json
d=json.load(open('$SUMMARY_FILE'))
fallback=d.get('generation_fallback_used',True)
ok=d.get('ok',False)
attempts=d.get('generation_attempt_count',0)
backend=d.get('sandbox_backend','?')
print(f'  run$i: ok={ok} fallback={fallback} attempts={attempts} backend={backend}')
# write to result file for later aggregation
with open('$RESULT_ROOT/09b_codeact_run${i}.json','w') as f:
    json.dump(d,f)
" 2>/dev/null || echo "  run$i: parse error"
    else
      echo "  run$i: no output"
    fi
  done
fi

# ----------------------------------------------------------
# 汇总
# ----------------------------------------------------------
sep "EXPERIMENT COMPLETE"
log "Results: $RESULT_ROOT"
echo ""
echo "Files produced:"
ls "$RESULT_ROOT"/*.json "$RESULT_ROOT"/*.txt 2>/dev/null | while read -r f; do
  sz=$(wc -c < "$f" 2>/dev/null || echo 0)
  printf "  %-50s %6d bytes\n" "$(basename "$f")" "$sz"
done
echo ""
echo "Copy to host:"
echo "  docker cp statebus-dev-qcrs:$RESULT_ROOT ./full-experiment-results/"
echo ""
log "Done at $(date -Iseconds)"
