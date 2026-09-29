# 源码与入口索引

## Runtime

| 主题 | 入口 |
| --- | --- |
| 任务编译 | `src/statebus/runtime/compiler.py`、`src/statebus/runtime/semantic_plan.py` |
| 自适应主链 | `src/statebus/runtime/adaptive_mainline.py`、`adaptive_runtime.py`、`adaptive_dispatcher.py` |
| 固定主链兼容路径 | `src/statebus/runtime/fixed_mainline.py` |
| 计划和 capability | `src/statebus/runtime/plan_policy.py`、`capability_registry.py`、`capability_recompute.py` |
| 控制面 | `src/statebus/control/messages.py`、`transport.py`、`subprocess_worker.py` |
| State 生命周期 | `src/statebus/state/store.py`、`semantic_state.py`、`memory_store.py`、`src/statebus/runtime/state_consumption.py` |
| Evidence / Artifact | `src/statebus/provenance/`、`src/statebus/runtime/evidence_projection.py`、`artifact_verification.py` |
| Memory replay | `src/statebus/memory/`、`src/statebus/runtime/memory_projection.py`、`replay.py` |
| Telemetry / ledger | `src/statebus/runtime/telemetry.py`、`ledger.py` |
| Studio backend | `src/statebus/studio/` |
| Studio frontend | `src/studio-ui/` |

## Benchmark 与实验

| 结果链 | Python 实现 | launcher | 精选 evidence |
| --- | --- | --- | --- |
| 主链 `SB-FULL` / `P-TEXT` | `src/statebus/benchmark/contest_dsl_mainline.py`、`contest_dsl_taskpack.py`、`contest_dsl_scorer.py` | `scripts/run_contest_dsl_mainchains.sh` | `tests/evidence/mainline/` |
| Memory / State | `src/statebus/benchmark/contest_mechanisms.py`、`memory_ablation.py` | `scripts/run_contest_mechanisms.sh` | `tests/evidence/mechanisms/` |
| APC / KV / Logit | `src/statebus/benchmark/model_assist_utility/`、`src/statebus/integrations/vllm_kv/`、`src/statebus/runtime/prefix_*`、`src/statebus/runtime/logit_*` | `scripts/experiments/contest_model_assist/run_utility_suite.sh` | `tests/evidence/model-assist/` |

稳定 dispatcher：

```bash
tests/benchmarks/run_statebus.sh smoke --dry-run
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh apc --dry-run
tests/benchmarks/run_statebus.sh kv --dry-run
tests/benchmarks/run_statebus.sh logit --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

dispatcher 只选择已有 runner；不会改变 runner 合同，也不会隐式启动或停止模型服务。
