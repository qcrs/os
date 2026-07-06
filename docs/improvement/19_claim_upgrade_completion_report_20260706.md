# 19 - StateBus v2 Claim Upgrade Completion Report

**Date:** 2026-07-06
**Branch:** `feat/statebus-v2-container-runtime`
**Baseline HEAD before local commit attempt:** `4692c93`
**Scope:** Execute `18_claim_upgrade_execution_plan.md` stages 1 and 2; keep stage 3 conservative unless real API evidence exists.

---

## 1. 执行摘要

本次完成两个可升级项：

1. **memfd benchmark 主线集成。** `v2.benchmark.live_runner` 新增 `--state-pool-mode {auto,shared_memory,memfd}`，formal benchmark 可选择 memfd state-pool 后端；runtime driver、smoke metrics、suite JSON 均导出 memfd transfer/publish 指标。
2. **形式化任务家族扩展。** Formal benchmark 从原 8 个单指标财务案例扩展为 25 个案例、5 个任务家族，覆盖单指标提取、多期趋势、跨表关联、条件聚合、异常检测。

未执行高风险 Stage 3 formal external API comparison：当前环境 `STATEBUS_LLM_API_KEY` 未设置。本报告不升级任何 formal external superiority 声明。

---

## 2. 升级前后对比

| 类别 | 升级前 | 升级后 |
|---|---:|---:|
| Strong 证据声明 | 6 | 8 |
| Formal benchmark 案例数 | 8 | 25 |
| Formal task families | 1 | 5 |
| memfd benchmark 主线可观测性 | 不可观测 | 可观测，有 transfer/publish/bytes |
| Unsupported engineering claims | 6 | 4-5，取决于是否把 realtime codegen 视为已改写为保守表述 |

新增 Strong 证据项：

- **形式化多样化推理验证：** 25 cases / 5 families / 25 quality passes。
- **memfd formal benchmark 主线：** `state_pool_mode_used="memfd"`，25 transfers，25 publishes，247046 bytes。

仍不能升级的声明：

- formal external superiority
- end-to-end speed advantage
- openEuler VM validation
- generic answer restoration
- benchmark-proven realtime LLM code generation

---

## 3. 新支持的安全表述

可以声明：

> "StateBus 形式化 benchmark 已扩展到 25 个案例、5 个任务家族：财务单指标提取、多期趋势分析、跨表关联、条件聚合、异常检测。local-embedding formal run 中质量基线维持 25/25 通过。"

可以声明：

> "StateBus formal benchmark 主线已可通过 `--state-pool-mode memfd` 使用 memfd state-pool 后端。claim-upgrade local-embedding formal run 中，JSON 记录 `state_pool_mode_used=\"memfd\"`，并观测到 25 次 memfd transfer、25 次 memfd publish、247046 bytes transferred。"

必须继续限定：

> "本次 claim-upgrade 验证的是 internal local-embedding formal benchmark，不是 formal external API comparison。formal external superiority 需要单独 API compare JSON。"

---

## 4. 代码修改索引

| 区域 | 文件 |
|---|---|
| state-pool backend | `v2/state/store.py`, `v2/contracts/models.py` |
| runtime metrics | `v2/runtime/driver.py`, `v2/runtime/smoke.py` |
| benchmark flags/reporting | `v2/benchmark/live_runner.py`, `minimal_runner.py`, `fixed_answer_runner.py`, `comparator_runner.py`, `models.py`, `reporting.py` |
| formal registry | `v2/benchmark/task_registry.py` |
| formal task assets | `tasks/formal/` |
| audit script | `scripts/run_v2_full_container_audit_suite.sh` |
| tests | `tests/v2/test_state_materialization.py` |

---

## 5. Benchmark 证据索引

Primary formal claim-upgrade artifact:

```text
/tmp/statebus-claim-upgrade-formal-runtime-local-final/benchmark_reports/claim-upgrade-formal-local-final-formal-suite.json
```

Key fields verified with `jq`:

```json
{
  "case_count": 25,
  "quality_pass": 25,
  "family_count": 5,
  "state_pool_mode_used": "memfd",
  "memfd_transfer_count": 25,
  "memfd_publish_count": 25,
  "memfd_bytes_transferred": 247046,
  "L2_semantic_state_transfer_count": 25
}
```

Driver telemetry event evidence:

```text
/tmp/statebus-claim-upgrade-formal-runtime-local-final/L3/formal-anomaly-003/telemetry/runtime_events.jsonl
```

The `TASK_SUMMARY_METRICS` event contains:

```json
{
  "state_pool_mode_requested": "memfd",
  "state_pool_mode_used": "memfd",
  "memfd_transfer_count": 1,
  "memfd_bytes_transferred": 9877
}
```

Families:

- `financial_report_analysis`
- `multi_period_trend_analysis_v1`
- `cross_table_join_analysis_v1`
- `conditional_aggregation_v1`
- `anomaly_detection_v1`

---

## 6. 回归测试结果

Passed:

```bash
python -m py_compile v2/state/store.py v2/runtime/driver.py v2/runtime/smoke.py \
  v2/benchmark/live_runner.py v2/benchmark/minimal_runner.py \
  v2/benchmark/fixed_answer_runner.py v2/benchmark/comparator_runner.py \
  v2/benchmark/models.py v2/benchmark/reporting.py v2/benchmark/task_registry.py
```

```bash
bash -n scripts/run_v2_full_container_audit_suite.sh
```

```bash
python -m pytest -q \
  tests/v2/test_state_materialization.py \
  tests/v2/test_memfd_statepool.py \
  tests/v2/test_replay.py \
  tests/v2/test_runtime_and_benchmark.py \
  tests/v2/test_minimal_benchmark.py \
  tests/v2/test_preflight_and_live_runner.py
# 74 passed, 100 warnings
```

```bash
python -m pytest -q tests/v2/
# 215 passed, 100 warnings
```

Final focused rerun after adding suite-level `memfd_publish_count` serialization:

```bash
python -m pytest -q \
  tests/v2/test_state_materialization.py \
  tests/v2/test_minimal_benchmark.py \
  tests/v2/test_preflight_and_live_runner.py \
  tests/v2/test_fixed_answer_and_external_baseline.py
# 69 passed
```

```bash
python -m runtime.smoke
# text and protocol smoke passed; comparator artifact ok
```

```bash
python -m v2.benchmark.live_runner --suite preflight \
  --role-path-mode deterministic --embedding-mode deterministic
# ok=true
```

```bash
python -m v2.benchmark.live_runner \
  --suite formal --benchmark-tier formal \
  --role-path-mode deterministic --embedding-mode local \
  --state-pool-mode memfd \
  --runtime-root /tmp/statebus-claim-upgrade-formal-runtime-local-final \
  --workspace-root /tmp/statebus-claim-upgrade-formal-workspaces-local-final \
  --socket-path /tmp/statebus-claim-upgrade-formal-local-final.sock \
  --suite-id claim-upgrade-formal-local-final
# 25/25 formal quality passes, memfd path observed
```

Notes:

- The prompt mentioned `tests/v2/test_driver.py`; this file does not exist in the current worktree. Driver/replay coverage was exercised through `test_runtime_and_benchmark.py`, `test_replay.py`, `test_minimal_benchmark.py`, and `test_preflight_and_live_runner.py`.
- The local-embedding formal run was executed from the StateBus host env via `source deploy/activate_statebus_host.sh`; the base shell lacked `sentence_transformers`.

---

## 7. Git 提交历史

Local commits created on `feat/statebus-v2-container-runtime`:

```text
Implement v2 claim upgrade benchmark support
Update v2 claim upgrade documentation
```

The pre-existing local edit to `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md` remains unstaged and was not modified by this completion pass.

---

## 8. 剩余问题

| Claim | Status | Reason |
|---|---|---|
| formal external superiority | Not upgraded | `STATEBUS_LLM_API_KEY` unset; no formal API compare rerun |
| end-to-end speed advantage | Not supported | historical external comparison shows positive overhead |
| openEuler VM validation | Not supported | only container/host evidence in this repo |
| generic answer restoration | Not supported | replay deliberately uses strict admission gates |
| realtime LLM code generation benchmark proof | Conservative only | mainline claim remains bounded CodeAct, not broad realtime generation |

---

## 9. 推荐 30 秒答辩口径

> "StateBus v2 uses a UDS + Protobuf control plane and SemanticStateRef data plane across Planner, Retriever, Executor, and Summarizer. In the claim-upgrade run, the formal benchmark was expanded from 8 single-metric cases to 25 cases across 5 reasoning families, with 25/25 local-embedding quality passes. The formal benchmark mainline now supports `--state-pool-mode memfd`; the JSON evidence records `state_pool_mode_used=memfd`, 25 memfd transfers, 25 memfd publishes, and 247046 transferred bytes. We still do not claim end-to-end speed advantage, openEuler VM validation, generic answer restoration, or formal external superiority without a separate API compare run."

---

## 10. 文档更新

Updated:

- `docs/improvement/artifacts/17_final_system_audit/17f_safe_claim_language.md`
- `docs/reports/v2_experiment_summary_20260703.md`
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`
