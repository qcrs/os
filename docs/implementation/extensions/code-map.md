# 核心代码地图

下面按“我要找什么”组织，而不是按目录机械罗列。函数和类名比行号稳定，阅读时可用 `rg` 定位。

## 任务与计划

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| `CanonicalTaskSpec` / compiler input/result | [`contracts/models.py`](../../../statebus/contracts/models.py) | [`runtime/compiler.py`](../../../statebus/runtime/compiler.py) |
| adaptive envelope / proposal / approved plan / grant | [`contracts/adaptive.py`](../../../statebus/contracts/adaptive.py) | [`runtime/plan_policy.py`](../../../statebus/runtime/plan_policy.py) |
| capability descriptor/registry | [`runtime/capability_registry.py`](../../../statebus/runtime/capability_registry.py) | [`runtime/domain_packs.py`](../../../statebus/runtime/domain_packs.py) |
| adaptive mainline assembly | [`runtime/adaptive_mainline.py`](../../../statebus/runtime/adaptive_mainline.py) | [`runtime/adaptive_runtime.py`](../../../statebus/runtime/adaptive_runtime.py) |
| role capability dispatch | [`runtime/adaptive_dispatcher.py`](../../../statebus/runtime/adaptive_dispatcher.py) | [`runtime/role_path.py`](../../../statebus/runtime/role_path.py) |

## 控制面与会话

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| Protobuf schema | [`control/statebus_control.proto`](../../../statebus/control/statebus_control.proto) | [`control/schema.py`](../../../statebus/control/schema.py) |
| typed control dataclasses/codec | [`control/messages.py`](../../../statebus/control/messages.py) | [`control/transport.py`](../../../statebus/control/transport.py) |
| subprocess Worker | [`control/subprocess_worker.py`](../../../statebus/control/subprocess_worker.py) | [`runtime/driver.py`](../../../statebus/runtime/driver.py) |
| step lifecycle / timeout | [`runtime/supervisor.py`](../../../statebus/runtime/supervisor.py) | [`runtime/session.py`](../../../statebus/runtime/session.py) |

## 检索、状态与来源

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| retrieval request/result/pipeline | [`retrieval/models.py`](../../../statebus/retrieval/models.py)、[`retrieval/pipeline.py`](../../../statebus/retrieval/pipeline.py) | [`runtime/retrieval_adapter.py`](../../../statebus/runtime/retrieval_adapter.py) |
| Ref 类型 | [`refs/models.py`](../../../statebus/refs/models.py) | [`contracts/models.py`](../../../statebus/contracts/models.py) |
| layered state backend | [`state/store.py`](../../../statebus/state/store.py) | [`state/disk.py`](../../../statebus/state/disk.py) |
| dense semantic state | [`state/semantic_state.py`](../../../statebus/state/semantic_state.py) | [`runtime/state_consumption.py`](../../../statebus/runtime/state_consumption.py) |
| locator / manifest / fan-in | [`provenance/hydration.py`](../../../statebus/provenance/hydration.py) | [`runtime/evidence_projection.py`](../../../statebus/runtime/evidence_projection.py) |

## 模型侧状态与推理复用

```mermaid
flowchart LR
    C[Contract] --> R[Runtime wiring]
    R --> E[Engine or state integration]
    E --> A[Audit and proof]
    A --> B[Benchmark]
```

| 对象/行为 | 入口 | 相邻实现与证据 |
|:--|:--|:--|
| Embedding selection | [`state/semantic_state.py`](../../../statebus/state/semantic_state.py) | [`runtime/state_consumption.py`](../../../statebus/runtime/state_consumption.py)、`STATE_CONSUMED` receipt |
| candidate probability / LogitState | [`contracts/logit.py`](../../../statebus/contracts/logit.py)、[`runtime/logit_state.py`](../../../statebus/runtime/logit_state.py) | [`state/logit_state.py`](../../../statebus/state/logit_state.py)、[`runtime/logit_gate.py`](../../../statebus/runtime/logit_gate.py) |
| canonical Prefix / exact-token identity | [`contracts/prefix.py`](../../../statebus/contracts/prefix.py)、[`runtime/prefix_identity.py`](../../../statebus/runtime/prefix_identity.py) | [`runtime/role_path.py`](../../../statebus/runtime/role_path.py)、[`runtime/vllm_metrics.py`](../../../statebus/runtime/vllm_metrics.py) |
| Prefix 调度与反馈 | [`benchmark/kv_prefix_schedule.py`](../../../statebus/benchmark/kv_prefix_schedule.py) | [`runtime/prefix_feedback.py`](../../../statebus/runtime/prefix_feedback.py)、[`benchmark/kv_prefix_experiment.py`](../../../statebus/benchmark/kv_prefix_experiment.py) |
| 显式 KV 合同与主链接入 | [`contracts/engine_local_kv.py`](../../../statebus/contracts/engine_local_kv.py)、[`integrations/vllm_kv/role_client.py`](../../../statebus/integrations/vllm_kv/role_client.py) | [`runtime/smoke.py`](../../../statebus/runtime/smoke.py)、`runtime/engine_local_kv_mainline.json` |
| KV 私有 API 与 Worker 生命周期 | [`integrations/vllm_kv/middleware.py`](../../../statebus/integrations/vllm_kv/middleware.py)、[`integrations/vllm_kv/worker_extension.py`](../../../statebus/integrations/vllm_kv/worker_extension.py) | [`integrations/vllm_kv/connector.py`](../../../statebus/integrations/vllm_kv/connector.py)、[`integrations/vllm_kv/registry.py`](../../../statebus/integrations/vllm_kv/registry.py) |
| KV paged tensor capture/load | [`integrations/vllm_kv/paged_cache.py`](../../../statebus/integrations/vllm_kv/paged_cache.py) | [`integrations/vllm_kv/telemetry.py`](../../../statebus/integrations/vllm_kv/telemetry.py)、`KVForwardProof` |

## 记忆与执行

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| MemoryQuery/Ref/Commit/Consumption | [`memory/models.py`](../../../statebus/memory/models.py) | [`memory/store.py`](../../../statebus/memory/store.py) |
| Replay decision / exact key | [`runtime/replay.py`](../../../statebus/runtime/replay.py) | [`runtime/ledger.py`](../../../statebus/runtime/ledger.py) |
| LLM Python CodeAct | [`runtime/llm_codeact.py`](../../../statebus/runtime/llm_codeact.py) | [`runtime/codeact_sandbox.py`](../../../statebus/runtime/codeact_sandbox.py) |
| Transform DSL | [`runtime/transform_dsl.py`](../../../statebus/runtime/transform_dsl.py) | [`contracts/adaptive.py`](../../../statebus/contracts/adaptive.py) |
| capability business validators | [`runtime/capability_validators.py`](../../../statebus/runtime/capability_validators.py) | [`runtime/capability_recompute.py`](../../../statebus/runtime/capability_recompute.py) |
| workspace / artifact lifecycle | [`runtime/workspace.py`](../../../statebus/runtime/workspace.py) | [`runtime/commit_gate.py`](../../../statebus/runtime/commit_gate.py) |

## 证据、benchmark 与 Studio

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| Telemetry | [`runtime/telemetry.py`](../../../statebus/runtime/telemetry.py) | [`benchmark/metric_aggregation.py`](../../../statebus/benchmark/metric_aggregation.py) |
| formal task adapter/registry | [`benchmark/task_registry.py`](../../../statebus/benchmark/task_registry.py)、[`benchmark/formal_registry_adapter.py`](../../../statebus/benchmark/formal_registry_adapter.py) | [`benchmark/adaptive_formal.py`](../../../statebus/benchmark/adaptive_formal.py) |
| continuous family | [`benchmark/continuous_task_family.py`](../../../statebus/benchmark/continuous_task_family.py) | [`benchmark/continuous_runner.py`](../../../statebus/benchmark/continuous_runner.py) |
| Logit Retry Gate challenge | [`benchmark/logit_retry_challenge.py`](../../../statebus/benchmark/logit_retry_challenge.py) | [`tests/test_logit_gate.py`](../../../tests/test_logit_gate.py)、[`tests/test_logit_retry_challenge.py`](../../../tests/test_logit_retry_challenge.py) |
| Prefix mechanism probe | [`benchmark/kv_prefix_experiment.py`](../../../statebus/benchmark/kv_prefix_experiment.py) | [`tests/test_prefix_render_identity.py`](../../../tests/test_prefix_render_identity.py)、[`tests/test_prefix_metrics_observation.py`](../../../tests/test_prefix_metrics_observation.py) |
| KV continuation 任务与 A/B | [`benchmark/engine_local_kv_tasks.py`](../../../statebus/benchmark/engine_local_kv_tasks.py)、[`benchmark/engine_local_kv_experiment.py`](../../../statebus/benchmark/engine_local_kv_experiment.py) | [`scripts/experiments/engine_local_kv`](../../../scripts/experiments/engine_local_kv/)、[`tests/test_engine_local_kv_mainline_suite.py`](../../../tests/test_engine_local_kv_mainline_suite.py) |
| Studio API/jobs | [`studio/app.py`](../../../statebus/studio/app.py)、[`studio/jobs.py`](../../../statebus/studio/jobs.py) | [`studio/recipes.py`](../../../statebus/studio/recipes.py) |
| Studio task-flow adapter | [`studio/task_flow.py`](../../../statebus/studio/task_flow.py) | [`studio-ui/src/types.ts`](../../../studio-ui/src/types.ts) |
| Studio pages/flow | [`EvidencePage.tsx`](../../../studio-ui/src/pages/EvidencePage.tsx)、[`LiveStudioPage.tsx`](../../../studio-ui/src/pages/LiveStudioPage.tsx) | [`AgentFlowCanvas.tsx`](../../../studio-ui/src/components/AgentFlowCanvas.tsx) |
