# 核心代码地图

下面按“我要找什么”组织，而不是按目录机械罗列。函数和类名比行号稳定，阅读时可用 `rg` 定位。

## 任务与计划

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| `CanonicalTaskSpec` / compiler input/result | [`contracts/models.py`](../../../v2/contracts/models.py) | [`runtime/compiler.py`](../../../v2/runtime/compiler.py) |
| adaptive envelope / proposal / approved plan / grant | [`contracts/adaptive.py`](../../../v2/contracts/adaptive.py) | [`runtime/plan_policy.py`](../../../v2/runtime/plan_policy.py) |
| capability descriptor/registry | [`runtime/capability_registry.py`](../../../v2/runtime/capability_registry.py) | [`runtime/domain_packs.py`](../../../v2/runtime/domain_packs.py) |
| adaptive mainline assembly | [`runtime/adaptive_mainline.py`](../../../v2/runtime/adaptive_mainline.py) | [`runtime/adaptive_runtime.py`](../../../v2/runtime/adaptive_runtime.py) |
| role capability dispatch | [`runtime/adaptive_dispatcher.py`](../../../v2/runtime/adaptive_dispatcher.py) | [`runtime/role_path.py`](../../../v2/runtime/role_path.py) |

## 控制面与会话

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| Protobuf schema | [`control/statebus_v2.proto`](../../../v2/control/statebus_v2.proto) | [`control/schema.py`](../../../v2/control/schema.py) |
| typed control dataclasses/codec | [`control/messages.py`](../../../v2/control/messages.py) | [`control/transport.py`](../../../v2/control/transport.py) |
| subprocess Worker | [`control/subprocess_worker.py`](../../../v2/control/subprocess_worker.py) | [`runtime/driver.py`](../../../v2/runtime/driver.py) |
| step lifecycle / timeout | [`runtime/supervisor.py`](../../../v2/runtime/supervisor.py) | [`runtime/session.py`](../../../v2/runtime/session.py) |

## 检索、状态与来源

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| retrieval request/result/pipeline | [`retrieval/models.py`](../../../v2/retrieval/models.py)、[`retrieval/pipeline.py`](../../../v2/retrieval/pipeline.py) | [`runtime/retrieval_adapter.py`](../../../v2/runtime/retrieval_adapter.py) |
| Ref 类型 | [`refs/models.py`](../../../v2/refs/models.py) | [`contracts/models.py`](../../../v2/contracts/models.py) |
| layered state backend | [`state/store.py`](../../../v2/state/store.py) | [`state/disk.py`](../../../v2/state/disk.py) |
| dense semantic state | [`state/semantic_state.py`](../../../v2/state/semantic_state.py) | [`runtime/state_consumption.py`](../../../v2/runtime/state_consumption.py) |
| candidate probability / LogitState | [`contracts/logit.py`](../../../v2/contracts/logit.py)、[`state/logit_state.py`](../../../v2/state/logit_state.py) | [`runtime/logit_state.py`](../../../v2/runtime/logit_state.py)、[`runtime/logit_gate.py`](../../../v2/runtime/logit_gate.py) |
| locator / manifest / fan-in | [`provenance/hydration.py`](../../../v2/provenance/hydration.py) | [`runtime/evidence_projection.py`](../../../v2/runtime/evidence_projection.py) |

## 记忆与执行

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| MemoryQuery/Ref/Commit/Consumption | [`memory/models.py`](../../../v2/memory/models.py) | [`memory/store.py`](../../../v2/memory/store.py) |
| Replay decision / exact key | [`runtime/replay.py`](../../../v2/runtime/replay.py) | [`runtime/ledger.py`](../../../v2/runtime/ledger.py) |
| LLM Python CodeAct | [`runtime/llm_codeact.py`](../../../v2/runtime/llm_codeact.py) | [`runtime/codeact_sandbox.py`](../../../v2/runtime/codeact_sandbox.py) |
| Transform DSL | [`runtime/transform_dsl.py`](../../../v2/runtime/transform_dsl.py) | [`contracts/adaptive.py`](../../../v2/contracts/adaptive.py) |
| capability business validators | [`runtime/capability_validators.py`](../../../v2/runtime/capability_validators.py) | [`runtime/capability_recompute.py`](../../../v2/runtime/capability_recompute.py) |
| workspace / artifact lifecycle | [`runtime/workspace.py`](../../../v2/runtime/workspace.py) | [`runtime/commit_gate.py`](../../../v2/runtime/commit_gate.py) |

## 证据、benchmark 与 Studio

| 对象/行为 | 入口 | 相邻实现 |
|:--|:--|:--|
| Telemetry | [`runtime/telemetry.py`](../../../v2/runtime/telemetry.py) | [`benchmark/metric_aggregation.py`](../../../v2/benchmark/metric_aggregation.py) |
| formal task adapter/registry | [`benchmark/task_registry.py`](../../../v2/benchmark/task_registry.py)、[`benchmark/formal_registry_adapter.py`](../../../v2/benchmark/formal_registry_adapter.py) | [`benchmark/adaptive_formal.py`](../../../v2/benchmark/adaptive_formal.py) |
| continuous family | [`benchmark/continuous_task_family.py`](../../../v2/benchmark/continuous_task_family.py) | [`benchmark/continuous_runner.py`](../../../v2/benchmark/continuous_runner.py) |
| Logit Retry Gate challenge | [`benchmark/logit_retry_challenge.py`](../../../v2/benchmark/logit_retry_challenge.py) | [`tests/v2/test_logit_gate.py`](../../../tests/v2/test_logit_gate.py)、[`tests/v2/test_logit_retry_challenge.py`](../../../tests/v2/test_logit_retry_challenge.py) |
| Studio API/jobs | [`studio/app.py`](../../../v2/studio/app.py)、[`studio/jobs.py`](../../../v2/studio/jobs.py) | [`studio/recipes.py`](../../../v2/studio/recipes.py) |
| Studio task-flow adapter | [`studio/task_flow.py`](../../../v2/studio/task_flow.py) | [`studio-ui/src/types.ts`](../../../studio-ui/src/types.ts) |
| Studio pages/flow | [`EvidencePage.tsx`](../../../studio-ui/src/pages/EvidencePage.tsx)、[`LiveStudioPage.tsx`](../../../studio-ui/src/pages/LiveStudioPage.tsx) | [`AgentFlowCanvas.tsx`](../../../studio-ui/src/components/AgentFlowCanvas.tsx) |

顶层 `runtime/`、`agents/`、`memory/` 等仍是 host-mainline/v1 参考。修改当前正式链时先确认 import 以 `v2.` 开头，避免在旧模块中修了一个同名类却没有影响当前 Runner。
