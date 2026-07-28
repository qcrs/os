# 测试与审阅清单

本页不是要求每次修改运行全量长实验，而是给出与代码风险相匹配的最小回归。纯文档修改不需要发送模型请求；Runtime、协议或存储修改应先跑 deterministic unit/integration tests，再由明确的实验任务决定是否执行 live runner。

| 修改范围 | 优先回归 |
|:--|:--|
| TaskSpec / Ref 合同 | `test_contracts_and_refs.py`、`test_adaptive_contracts.py`、`test_runtime_and_benchmark.py` |
| PlanPolicy / capability | `test_adaptive_planner_policy.py`、`test_adaptive_capability_surface.py`、`test_adaptive_mainline_integration.py` |
| Protobuf / UDS / subprocess | `test_control_plane.py`、`test_uds_loopback.py`、`test_subprocess_executor.py` |
| SemanticState / backend | `test_state_materialization.py`、`test_embedding_state_consumer.py`、`test_memfd_statepool.py` |
| LogitState / Retry Gate | `test_logit_state.py`、`test_logit_gate.py`、`test_logit_retry_challenge.py` |
| Hydration / retrieval | `test_provenance_and_evidence.py`、`test_retrieval_pipeline.py`、`test_evidence_projection.py` |
| Memory / Replay | `test_memory_store.py`、`test_hybrid_memory_query.py`、`test_memory_runtime.py`、`test_replay.py` |
| CodeAct | `test_llm_codeact_policy.py`、`test_llm_codeact_sandbox.py`、`test_adaptive_codeact_integration.py` |
| Transform DSL | `test_transform_dsl.py`、相关 capability validator 测试 |
| Telemetry / metrics | `test_metric_aggregation.py`、`test_runtime_persistence_breakdown.py` |
| Studio | `test_studio_api.py`，前端 `npm run typecheck` 与 `npm run build` |

常用 deterministic 入口：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_control_plane.py tests/v2/test_contracts_and_refs.py
python -m pytest -q tests/v2/test_studio_api.py

cd studio-ui
npm run typecheck
npm run build
```

容器路径使用项目容器环境与 `python3`，不要向系统 Python 或 base 环境安装依赖。涉及 LLM/bubblewrap/Embedding 的测试应确认当前环境与 GPU 映射，不能把因服务未就绪跳过的路径当成正式通过。

代码审阅时优先检查这些不变量：Ref 类型是否仍然分离；formal task 是否仍需预编译 spec；新的 Agent 输出是否先进入候选状态；CapabilityGrant 是否限制输入、workspace 与期限；失败产物能否被 Summarizer 看见；memory candidate 是否经过兼容与消费记录；attempt 重试是否隔离；Telemetry 是否重复计数；Studio 是否仍只接受 recipe ID。

任何涉及时延的结论都需要串行正式 rerun。并发 API launch、Studio 现场演示或单个手工 case 适合诊断，不应覆盖固定实验基线。
