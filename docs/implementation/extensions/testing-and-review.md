# 验证矩阵

StateBus 将合同、控制面、状态、模型侧复用、执行、记忆和界面分别映射到确定性测试与专项
实验。下表列出各模块的回归入口。

| 模块 | 回归入口 |
|:--|:--|
| TaskSpec / Ref 合同 | `tests/unit/contracts/test_contracts_and_refs.py` |
| Runtime identity / lifecycle | `tests/unit/runtime/test_runtime_identity.py`、`test_runtime_session_and_ledger.py` |
| Protobuf / subprocess | `tests/unit/runtime/test_control_plane.py`、`test_subprocess_executor.py` |
| Semantic state / memory / replay | `tests/unit/runtime/test_state_materialization.py`、`tests/unit/memory/test_memory_runtime.py`、`tests/unit/runtime/test_replay.py`、`test_replay_gate.py` |
| CodeAct | `tests/unit/codeact/test_llm_codeact_policy.py`、`test_llm_codeact_sandbox.py` |
| Transform DSL | `tests/unit/runtime/test_transform_dsl.py` |
| Logit / Prefix / KV | `tests/unit/mechanisms/test_logit_state.py`、`test_logit_gate.py`、`test_prefix_render_identity.py`、`test_engine_local_kv_role_client.py` |
| Mainline / Studio integration | `tests/integration/runtime/test_adaptive_driver.py`、`test_adaptive_dispatcher.py`、`test_fixed_canonical_mainline.py`、`tests/integration/studio/test_studio_api.py` |
| Utility / mechanism benchmark contracts | `tests/benchmarks/utility/`、`tests/benchmarks/mechanisms/` |

常用 deterministic 入口：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/unit/runtime/test_control_plane.py tests/unit/contracts/test_contracts_and_refs.py
python -m pytest -q tests/unit/mechanisms/test_prefix_render_identity.py tests/unit/mechanisms/test_logit_gate.py
python -m pytest -q tests/unit/mechanisms/test_engine_local_kv_role_client.py
python -m pytest -q tests/integration/studio/test_studio_api.py

cd src/studio-ui
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
