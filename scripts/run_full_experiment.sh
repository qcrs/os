#!/usr/bin/env bash
# StateBus v2 全量实验脚本 — 17 stages
#
# 用法（CodeAct bwrap 需 root）：
#   docker exec --user root statebus-dev-qcrs bash -l /workspace/statebus/project/scripts/run_full_experiment.sh
#
# 可选环境变量：
#   SKIP_FLAGSHIP=1    跳过 16_flagship_ablation（最耗时）
#   SKIP_CODEACT=1     跳过 11_codeact_acceptance（需 root）
#   SKIP_CONTINUOUS=1  跳过 09/10 continuous（耗时较长）
#   RESULT_ROOT=...    自定义结果目录（默认 /statebus/runs/full-experiment-TIMESTAMP）

set -euo pipefail

# ---- 环境加载 ----
if [[ -f /usr/local/bin/activate_statebus_container.sh ]]; then
  source /usr/local/bin/activate_statebus_container.sh
elif [[ -f "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/activate_statebus_host.sh" ]]; then
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/activate_statebus_host.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RESULT_ROOT="${RESULT_ROOT:-/statebus/runs/full-experiment-${TIMESTAMP}}"
RUNTIME_ROOT="/statebus/runs/v2-live/runtime"
WORKSPACE_ROOT="/statebus/work/v2-live/workspaces"
SOCKET_PATH="/statebus/runs/v2-live/control.sock"
JSON_DIR="$RESULT_ROOT/json"
LOG_DIR="$RESULT_ROOT/logs"

mkdir -p "$RESULT_ROOT" "$JSON_DIR" "$LOG_DIR"
cd "$PROJECT_ROOT"

log()  { echo "[$(date +%H:%M:%S)] $*"; }
sep()  { echo ""; echo "======================================"; echo "STAGE: $*"; echo "======================================"; }
pass() { echo "  [PASS] $*"; }
warn() { echo "  [WARN] $*"; }

# ---- stage 실행 함수 ----
STAGE_STATUS=()

run_stage() {
  local stage_id="$1"; shift
  local label="$1"; shift
  log "Running: $stage_id — $label"
  if python3 -m v2.benchmark.live_runner \
      --role-path-mode api \
      --embedding-mode local \
      --workspace-root "$WORKSPACE_ROOT" \
      --runtime-root "$RUNTIME_ROOT" \
      --socket-path "$SOCKET_PATH" \
      "$@" \
      > "$JSON_DIR/${stage_id}.json" \
      2> "$LOG_DIR/${stage_id}.stderr.log"; then
    STAGE_STATUS+=("$stage_id:pass")
    log "Done:    $stage_id"
  else
    STAGE_STATUS+=("$stage_id:fail")
    log "FAILED:  $stage_id  (see $LOG_DIR/${stage_id}.stderr.log)"
  fi
}

# ==========================================
# 00. GPU / env snapshot
# ==========================================
sep "00  GPU / env snapshot"
{
  echo "timestamp: $(date -Iseconds)"
  echo "hostname: $(hostname)"
  echo "python: $(python3 --version 2>&1)"
  nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader 2>/dev/null || echo "no GPU"
} > "$JSON_DIR/00_gpu_snapshot.txt" 2>&1
pass "env captured"

# ==========================================
# 01. pytest 回归
# ==========================================
sep "01  pytest v2 regression"
python3 -m pytest -q tests/v2 \
  > "$LOG_DIR/01_pytest_v2.log" 2>&1 || true
PYTEST_RESULT=$(tail -1 "$LOG_DIR/01_pytest_v2.log")
echo "  $PYTEST_RESULT"
echo "{\"pytest_summary\": \"$PYTEST_RESULT\"}" > "$JSON_DIR/01_pytest_v2.json"

# ==========================================
# 02. Preflight
# ==========================================
sep "02  Preflight"
run_stage 02_preflight "preflight" \
  --suite preflight
python3 -c "
import json
d=json.load(open('$JSON_DIR/02_preflight.json'))
print('  ok:', d.get('ok'))
print('  role_path_mode:', d.get('role_path_mode'))
print('  embedding_mode:', d.get('embedding_mode'))
" 2>/dev/null || true

# ==========================================
# 03. Formal Suite（L0–L3 layer breakdown）
# ==========================================
sep "03  Formal Suite (L0→L3)"
run_stage 03_formal_suite "formal suite" \
  --suite formal \
  --benchmark-tier formal
python3 -c "
import json
d=json.load(open('$JSON_DIR/03_formal_suite.json'))
wm=d.get('waterfall_metrics',{})
print('  L2 semantic_transfer:', wm.get('L2_semantic_state_transfer_count'))
print('  L2 evidence_bytes:', wm.get('L2_raw_evidence_bytes_seen_by_llm'))
print('  L3 quality:', wm.get('L3_quality_floor_pass_count'))
print('  L3 reuse_gain:', wm.get('L3_reuse_gain'))
" 2>/dev/null || true

# ==========================================
# 04. Formal Compare（StateBus vs External）
# ==========================================
sep "04  Formal Compare (StateBus vs External)"
run_stage 04_formal_compare "formal compare" \
  --suite compare \
  --benchmark-tier formal \
  --statebus-mode cold-start
python3 -c "
import json
d=json.load(open('$JSON_DIR/04_formal_compare.json'))
m=d.get('metadata',{})
cs=d.get('comparison_summary',{})
print('  formal_superiority_claim_allowed:', m.get('formal_superiority_claim_allowed'))
print('  formal_efficiency_claim_allowed:', m.get('formal_efficiency_claim_allowed'))
print('  statebus_quality:', cs.get('api_debug_statebus_quality_floor_pass_count'), '/', cs.get('api_debug_case_count'))
print('  external_quality:', cs.get('api_debug_external_quality_floor_pass_count'), '/', cs.get('api_debug_case_count'))
print('  tokens_delta:', cs.get('api_debug_llm_total_tokens_delta'))
print('  bytes_delta:', cs.get('api_debug_prompt_bytes_delta'))
print('  net_llm_ms_delta:', cs.get('api_debug_net_llm_ms_delta'))
print('  system_overhead_ms_delta:', cs.get('api_debug_system_overhead_ms_delta'))
" 2>/dev/null || true

# ==========================================
# 05. Carrier Compare（typed vs text_whole_lane）
# ==========================================
sep "05  Carrier Compare (typed vs text internal)"
run_stage 05_carrier_compare "carrier compare" \
  --suite carrier-compare \
  --benchmark-tier dev \
  --statebus-mode cold-start
python3 -c "
import json
d=json.load(open('$JSON_DIR/05_carrier_compare.json'))
cs=d.get('comparison_summary',{})
print('  task_ms_delta:', cs.get('task_ms_delta'))
print('  llm_prompt_bytes_delta:', cs.get('llm_prompt_bytes_delta'))
print('  llm_total_tokens_delta:', cs.get('llm_total_tokens_delta'))
print('  valid_mode_count:', cs.get('valid_mode_count'))
" 2>/dev/null || true

# ==========================================
# 06. Dev Compare cold-start
# ==========================================
sep "06  Dev Compare cold-start"
run_stage 06_dev_compare_coldstart "dev compare cold-start" \
  --suite compare \
  --benchmark-tier dev \
  --statebus-mode cold-start
python3 -c "
import json
d=json.load(open('$JSON_DIR/06_dev_compare_coldstart.json'))
cs=d.get('comparison_summary',{})
print('  comparison_valid:', bool(cs.get('valid_mode_count',0)))
print('  tokens_delta:', cs.get('api_debug_llm_total_tokens_delta', cs.get('tokens_delta')))
print('  bytes_delta:', cs.get('api_debug_prompt_bytes_delta', cs.get('bytes_delta')))
print('  codeact_execution_stage_ms:', cs.get('api_debug_codeact_execution_stage_ms'))
" 2>/dev/null || true

# ==========================================
# 07. StateBus dev cold-start（L层递增）
# ==========================================
sep "07  StateBus dev cold-start"
run_stage 07_statebus_dev_coldstart "statebus dev cold-start" \
  --suite statebus \
  --benchmark-tier dev \
  --statebus-mode cold-start
python3 -c "
import json
d=json.load(open('$JSON_DIR/07_statebus_dev_coldstart.json'))
wm=d.get('waterfall_metrics',{})
print('  L0 scaffold:', wm.get('L0_prompt_scaffolding_bytes_total'))
print('  L1 scaffold:', wm.get('L1_prompt_scaffolding_bytes_total'))
print('  L2 evidence_bytes:', wm.get('L2_raw_evidence_bytes_seen_by_llm'))
print('  L2 semantic_transfer:', wm.get('L2_semantic_state_transfer_count'))
print('  L3 quality:', wm.get('L3_quality_floor_pass_count'))
print('  L3 reuse_gain:', wm.get('L3_reuse_gain'))
" 2>/dev/null || true

# ==========================================
# 08. StateBus dev replay-ready（memory reuse）
# ==========================================
sep "08  StateBus dev replay-ready"
run_stage 08_statebus_dev_replay_ready "statebus dev replay-ready" \
  --suite statebus \
  --benchmark-tier dev \
  --statebus-mode replay-ready
python3 -c "
import json
d=json.load(open('$JSON_DIR/08_statebus_dev_replay_ready.json'))
wm=d.get('waterfall_metrics',{})
print('  L3 quality:', wm.get('L3_quality_floor_pass_count'))
print('  L3 reuse_gain:', wm.get('L3_reuse_gain'))
print('  L2 semantic_transfer:', wm.get('L2_semantic_state_transfer_count'))
" 2>/dev/null || true

# ==========================================
# 09. Continuous collection（csv + long_doc replay families）
# ==========================================
sep "09  Continuous collection"
if [[ "${SKIP_CONTINUOUS:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_CONTINUOUS=1)"
  echo '{"skipped":true}' > "$JSON_DIR/09_continuous_collection.json"
else
  run_stage 09_continuous_collection "continuous collection" \
    --suite continuous \
    --benchmark-tier formal
  python3 -c "
import json
d=json.load(open('$JSON_DIR/09_continuous_collection.json'))
cs=d.get('collection_summary',{})
print('  L3_history_reuse_gain:', cs.get('L3_history_reuse_gain'))
print('  validated_replay_count:', cs.get('validated_replay_count'))
print('  exact_replay_count:', cs.get('exact_replay_count'))
print('  eligible_for_replay_headline:', d.get('eligible_for_replay_headline'))
" 2>/dev/null || true
fi

# ==========================================
# 10. Continuous replay collection（replay headline gate）
# ==========================================
sep "10  Continuous replay collection"
if [[ "${SKIP_CONTINUOUS:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_CONTINUOUS=1)"
  echo '{"skipped":true}' > "$JSON_DIR/10_continuous_replay_collection.json"
else
  run_stage 10_continuous_replay_collection "continuous replay collection" \
    --suite continuous-replay \
    --benchmark-tier formal
  python3 -c "
import json
d=json.load(open('$JSON_DIR/10_continuous_replay_collection.json'))
cs=d.get('collection_summary',{})
print('  L3_history_reuse_gain:', cs.get('L3_history_reuse_gain'))
print('  validated_replay_count:', cs.get('validated_replay_count'))
print('  exact_replay_count:', cs.get('exact_replay_count'))
print('  replay_missing_target_round_count:', cs.get('replay_missing_target_round_count'))
print('  eligible_for_replay_headline:', d.get('eligible_for_replay_headline'))
" 2>/dev/null || true
fi

# ==========================================
# 11. CodeAct acceptance（5 runs，bwrap 需 root）
# ==========================================
sep "11  CodeAct LLM generation acceptance (5 runs)"
if [[ "${SKIP_CODEACT:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_CODEACT=1)"
  echo '{"skipped":true,"success_count":0,"total_runs":0}' > "$JSON_DIR/11_codeact_acceptance.json"
  STAGE_STATUS+=("11_codeact_acceptance:skipped")
else
  CODEACT_TMPDIR="$RESULT_ROOT/codeact-tmp"
  mkdir -p "$CODEACT_TMPDIR"
  TOTAL_RUNS=5
  for i in $(seq 1 $TOTAL_RUNS); do
    CODEACT_OUT="$RESULT_ROOT/codeact-run-$i"
    # stdout → summary line for display; summary.json written to output dir
    python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
      --role-path-mode api \
      --sandbox-backend bwrap \
      --max-repair-attempts 3 \
      --output-root "$CODEACT_OUT" \
      2>"$LOG_DIR/11_codeact_run${i}.stderr.log" \
      | tee "$CODEACT_TMPDIR/run${i}.stdout" || true
    echo "  run${i}: $(grep '^ok=' "$CODEACT_TMPDIR/run${i}.stdout" 2>/dev/null | head -1)"
  done
  # Aggregate: parse each run's summary.json into a temp file, then merge
  python3 - "$CODEACT_TMPDIR" "$JSON_DIR/11_codeact_acceptance.json" "$RESULT_ROOT" <<'PYEOF'
import json, pathlib, sys

tmpdir   = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
runs_dir = pathlib.Path(sys.argv[3])

runs = []
for i in range(1, 6):
    codeact_out = runs_dir / f"codeact-run-{i}"
    # find the canonical summary.json (not *.log files)
    candidates = [p for p in codeact_out.rglob("summary.json")
                  if ".log" not in str(p)]
    if not candidates:
        runs.append({"run": f"run-{i}", "ok": False,
                     "generation_fallback_used": True, "attempt_count": 0})
        continue
    d = json.loads(candidates[0].read_text())
    runs.append({
        "run": f"run-{i}",
        "ok": bool(d.get("ok", False)),
        "generation_fallback_used": bool(d.get("generation_fallback_used", True)),
        "attempt_count": int(d.get("generation_attempt_count", 0)),
        "violations": list(d.get("violations", [])),
        "sandbox_backend": str(d.get("sandbox_backend", "")),
    })

success_count = sum(1 for r in runs if r["ok"] and not r["generation_fallback_used"])
target_met    = success_count >= 3
result = {
    "success_count": success_count,
    "total_runs":    len(runs),
    "target_success_count": 3,
    "target_met":    target_met,
    "runs": runs,
}
out_path.write_text(json.dumps(result, indent=2))
print(f"  success_count: {success_count} / {len(runs)}  target_met: {target_met}")
PYEOF
  CODEACT_EXIT=$?
  if [[ $CODEACT_EXIT -eq 0 ]]; then
    STAGE_STATUS+=("11_codeact_acceptance:pass")
  else
    STAGE_STATUS+=("11_codeact_acceptance:fail")
  fi
fi

# ==========================================
# 12. Replay Negative Audit
# ==========================================
sep "12  Replay Negative Audit"
run_stage 12_replay_negative_audit "replay negative audit" \
  --suite replay-negative-audit
python3 -c "
import json
d=json.load(open('$JSON_DIR/12_replay_negative_audit.json'))
print('  audit_pass:', d.get('audit_pass'))
print('  case_count:', d.get('case_count'))
neg=sum(1 for c in d.get('cases',[]) if not c.get('audit_pass',True))
print('  negative_cases:', neg)
" 2>/dev/null || true

# ==========================================
# 13. incident_diagnosis_v2（第3类任务族）
# ==========================================
sep "13  incident_diagnosis_v2 (3rd task family)"
run_stage 13_incident_diagnosis_v2 "incident diagnosis v2" \
  --suite statebus \
  --benchmark-tier dev \
  --family incident_diagnosis_v2 \
  --statebus-mode replay-ready
python3 -c "
import json
d=json.load(open('$JSON_DIR/13_incident_diagnosis_v2.json'))
ep=d.get('evidence_pack',{})
delta=ep.get('l0_l3_delta',{})
print('  eligible_for_replay_headline:', d.get('eligible_for_replay_headline'))
print('  validated_replay_count:', delta.get('validated_replay_count'))
print('  exact_replay_count:', delta.get('exact_replay_count'))
print('  skipped_step_count:', delta.get('skipped_step_count'))
print('  l1_l2_evidence_reduction_bytes:', ep.get('l1_l2_non_text_delta',{}).get('raw_evidence_bytes_seen_by_llm'))
" 2>/dev/null || true

# ==========================================
# 14. Compare diagnostics dev（独立诊断脚本）
# ==========================================
sep "14  Compare diagnostics dev"
DIAG_ROOT="$RESULT_ROOT/diagnostics"
mkdir -p "$DIAG_ROOT/compare"
log "Running: 14_compare_diagnostics_dev"
# Read the actual compare suite report path from stage 06 artifact
DEV_COMPARE_REPORT=$(python3 -c "
import json, pathlib
p = pathlib.Path('$JSON_DIR/06_dev_compare_coldstart.json')
d = json.loads(p.read_text()) if p.exists() else {}
print(d.get('report_path', ''))
" 2>/dev/null || true)
if [[ -z "$DEV_COMPARE_REPORT" ]]; then
  echo '{"skipped":true,"reason":"stage_06_artifact_missing"}' > "$JSON_DIR/14_compare_diagnostics_dev.json"
  STAGE_STATUS+=("14_compare_diagnostics_dev:skip_no_report")
  log "SKIPPED: 14_compare_diagnostics_dev (stage 06 artifact not found)"
elif python3 scripts/v2_diagnostics/compare_diagnostics.py \
    --compare-suite-report "$DEV_COMPARE_REPORT" \
    --family-dir v2/benchmark/samples/fixed_answer_family \
    --output-root "$DIAG_ROOT/compare" \
    > "$JSON_DIR/14_compare_diagnostics_dev.json" \
    2> "$LOG_DIR/14_compare_diagnostics_dev.stderr.log"; then
  STAGE_STATUS+=("14_compare_diagnostics_dev:pass")
  log "Done:    14_compare_diagnostics_dev"
else
  echo '{"skipped":true,"reason":"compare_diagnostics_failed"}' > "$JSON_DIR/14_compare_diagnostics_dev.json"
  STAGE_STATUS+=("14_compare_diagnostics_dev:skip_failed")
  log "SKIPPED: 14_compare_diagnostics_dev (diagnostics script failed, non-critical)"
fi
python3 -c "
import json
d=json.load(open('$JSON_DIR/14_compare_diagnostics_dev.json'))
for k,v in sorted(d.items()):
    if not isinstance(v,(dict,list)):
        print(f'  {k}: {v}')
" 2>/dev/null || true

# ==========================================
# 15. Runtime persistence breakdown（独立诊断脚本）
# ==========================================
sep "15  Runtime persistence breakdown"
mkdir -p "$DIAG_ROOT/runtime-persistence"
log "Running: 15_runtime_persistence_breakdown"
if python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
    --output-root "$DIAG_ROOT/runtime-persistence" \
    --role-path-mode api \
    --embedding-mode local \
    --history-runtime-root "$RUNTIME_ROOT/08_statebus_dev_replay_ready" \
    > "$JSON_DIR/15_runtime_persistence_breakdown.json" \
    2> "$LOG_DIR/15_runtime_persistence_breakdown.stderr.log"; then
  STAGE_STATUS+=("15_runtime_persistence_breakdown:pass")
  log "Done:    15_runtime_persistence_breakdown"
else
  echo '{"skipped":true,"reason":"history_runtime_root_not_found"}' > "$JSON_DIR/15_runtime_persistence_breakdown.json"
  STAGE_STATUS+=("15_runtime_persistence_breakdown:skip_no_history")
  log "SKIPPED: 15_runtime_persistence_breakdown (history runtime root not found)"
fi
python3 -c "
import json
d=json.load(open('$JSON_DIR/15_runtime_persistence_breakdown.json'))
for k,v in sorted(d.items()):
    if not isinstance(v,(dict,list)):
        print(f'  {k}: {v}')
" 2>/dev/null || true

# ==========================================
# 16. Flagship Ablation（最全证据链）
# ==========================================
sep "16  Flagship Ablation (full evidence chain)"
if [[ "${SKIP_FLAGSHIP:-0}" == "1" ]]; then
  log "SKIPPED (SKIP_FLAGSHIP=1)"
  echo '{"skipped":true}' > "$JSON_DIR/16_flagship_ablation.json"
else
  run_stage 16_flagship_ablation "flagship ablation" \
    --suite flagship-ablation
  python3 -c "
import json
d=json.load(open('$JSON_DIR/16_flagship_ablation.json'))
print('  claim_level:', d.get('claim_level'))
print('  stress_family_count:', d.get('stress_family_count'))
print('  stress_pass_family_count:', d.get('stress_pass_family_count'))
print('  total_llm_prompt_saved_bytes:', d.get('total_llm_prompt_saved_by_state_ref_bytes'))
print('  total_prompt_visible_saved_bytes:', d.get('total_prompt_visible_saved_by_state_ref_bytes'))
# internal compare
ic=d.get('internal_fixed_answer_compare',{})
if ic:
    print('  internal_compare_valid:', ic.get('comparison_valid'))
    print('  internal_tokens_delta:', ic.get('tokens_delta'))
    print('  internal_bytes_delta:', ic.get('bytes_delta'))
" 2>/dev/null || true
fi

# ==========================================
# FINAL SUMMARY
# ==========================================
sep "SUMMARY"

# 阶段状态表
echo ""
echo "Stage Status:"
printf "  %-40s %s\n" "STAGE" "STATUS"
printf "  %-40s %s\n" "-----" "------"
for entry in "${STAGE_STATUS[@]}"; do
  stage="${entry%%:*}"
  status="${entry##*:}"
  printf "  %-40s %s\n" "$stage" "$status"
done

# 核心指标汇总
echo ""
echo "Key Metrics:"
python3 -c "
import json, pathlib, sys

jdir = pathlib.Path('$JSON_DIR')

def load(name):
    p = jdir / name
    return json.loads(p.read_text()) if p.exists() else {}

# pytest
pt = (jdir / '01_pytest_v2.json')
if pt.exists():
    print('  pytest:', load('01_pytest_v2.json').get('pytest_summary', '?'))

# formal compare
fc = load('04_formal_compare.json')
m = fc.get('metadata', {})
cs = fc.get('comparison_summary', {})
print('  [formal_compare]')
print('    superiority_claim:', m.get('formal_superiority_claim_allowed'))
print('    efficiency_claim:', m.get('formal_efficiency_claim_allowed'))
print('    statebus/external quality:', cs.get('api_debug_statebus_quality_floor_pass_count'), '/', cs.get('api_debug_external_quality_floor_pass_count'))
print('    tokens_delta:', cs.get('api_debug_llm_total_tokens_delta'))
print('    bytes_delta:', cs.get('api_debug_prompt_bytes_delta'))

# carrier compare
cc = load('05_carrier_compare.json')
ccs = cc.get('comparison_summary', {})
print('  [carrier_compare]')
print('    task_ms_delta:', ccs.get('task_ms_delta'))
print('    llm_prompt_bytes_delta:', ccs.get('llm_prompt_bytes_delta'))

# replay
rp = load('10_continuous_replay_collection.json')
rcs = rp.get('collection_summary', {})
print('  [continuous_replay]')
print('    validated_replay:', rcs.get('validated_replay_count'))
print('    exact_replay:', rcs.get('exact_replay_count'))
print('    missing_target_rounds:', rcs.get('replay_missing_target_round_count'))
print('    eligible_for_replay_headline:', rp.get('eligible_for_replay_headline'))

# incident
inc = load('13_incident_diagnosis_v2.json')
print('  [incident_diagnosis_v2]')
print('    eligible_for_replay_headline:', inc.get('eligible_for_replay_headline'))
print('    skipped_step_count:', inc.get('collection_summary',{}).get('skipped_step_count', inc.get('skipped_step_count')))

# codeact
ca = load('11_codeact_acceptance.json')
print('  [codeact_acceptance]')
print('    success_count:', ca.get('success_count'), '/', ca.get('total_runs'))
print('    target_met:', ca.get('target_met'))

# replay audit
ra = load('12_replay_negative_audit.json')
print('  [replay_negative_audit]')
print('    audit_pass:', ra.get('audit_pass'))
print('    case_count:', ra.get('case_count'))
" 2>/dev/null || true

echo ""
log "Results: $RESULT_ROOT"
echo "  json/   — stage artifacts"
echo "  logs/   — stderr logs"
echo ""
echo "Copy to host:"
echo "  docker cp statebus-dev-qcrs:$RESULT_ROOT ./full-experiment-results-${TIMESTAMP}/"
echo ""
log "Done at $(date -Iseconds)"
