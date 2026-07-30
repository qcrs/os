# 验证矩阵

StateBus 将合同、控制面、状态、模型侧复用、执行、记忆和界面分别映射到确定性测试与专项
实验。下表列出各模块的回归入口。

| 模块 | 回归入口 |
|:--|:--|
| TaskSpec / Ref 合同 | `test_contracts_and_refs.py`、`test_adaptive_contracts.py`、`test_runtime_and_benchmark.py` |
| PlanPolicy / capability | `test_adaptive_planner_policy.py`、`test_adaptive_capability_surface.py`、`test_adaptive_mainline_integration.py` |
| Protobuf / UDS / subprocess | `test_control_plane.py`、`test_uds_loopback.py`、`test_subprocess_executor.py` |
| SemanticState / backend | `test_state_materialization.py`、`test_embedding_state_consumer.py`、`test_control_plane.py` |
| LogitState / Retry Gate | `test_logit_state.py`、`test_logit_gate.py`、`test_logit_retry_challenge.py` |
| Prefix layout / identity / observation | `test_prefix_render_identity.py`、`test_prefix_dependency_schedule.py`、`test_prefix_metrics_observation.py`、`test_prefix_feedback.py`、`test_kv_prefix_control_plane.py` |
| 显式 KV contract / Worker / 主链接入 | `test_engine_local_kv_*.py`；至少覆盖 registry/connector、middleware/client、Worker extension、role client、task compiler 与 suite aggregation |
| Hydration / retrieval | `test_provenance_and_evidence.py`、`test_retrieval_pipeline.py`、`test_evidence_projection.py` |
| Memory / Replay | `test_memory_store.py`、`test_hybrid_memory_query.py`、`test_memory_runtime.py`、`test_replay.py` |
| CodeAct | `test_llm_codeact_policy.py`、`test_llm_codeact_sandbox.py`、`test_adaptive_codeact_integration.py` |
| Transform DSL | `test_transform_dsl.py`、相关 capability validator 测试 |
| Telemetry / metrics | `test_metric_aggregation.py`、`test_runtime_persistence_breakdown.py` |
| Studio | `test_studio_api.py`，前端 `npm run typecheck` 与 `npm run build` |

常用 deterministic 入口：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/test_control_plane.py tests/test_contracts_and_refs.py
python -m pytest -q tests/test_prefix_render_identity.py tests/test_prefix_metrics_observation.py
python -m pytest -q tests/test_engine_local_kv_role_client.py tests/test_engine_local_kv_registry_connector.py
python -m pytest -q tests/test_studio_api.py

cd studio-ui
npm run typecheck
npm run build
```

容器使用项目内 Python 环境，宿主机使用 `deploy/activate_statebus_host.sh` 激活本地 conda。
LLM、bubblewrap 与 Embedding 测试同时记录服务健康状态和 GPU 映射。

回归测试覆盖 Ref 类型分离、formal task 预编译、Agent 候选状态、CapabilityGrant 输入与期限、
invalidated 产物可见性、Memory 兼容与消费记录、attempt 隔离、Telemetry 单次计数和 Studio
recipe ID 作业入口。

模型侧测试覆盖 Prefix 角色可见性交集与位置 0 布局、真实 tokenizer/chat template 的 exact
identity、KV handle 的 engine/model/tokenizer/task/token digest、Consumer Token 账、双证明、
fallback 和 release 后 registry 归零。Prefix hit、Logit Gate transfer 和 KV load 分别聚合。

正式时延实验按串行 runner 执行；并发 API、Studio 现场运行和手工 case 进入诊断记录。

文档验证包括 `git diff --check`、相对链接和 Mermaid fence；源码入口与实验数字分别链接到
确定性测试和原始 summary。
