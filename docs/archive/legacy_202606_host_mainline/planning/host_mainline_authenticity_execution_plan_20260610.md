# StateBus 宿主机主线真实性执行计划（Phase 0-7）

日期：`2026-06-10`

适用范围：当前 `/home/qcrs/statebus/project` 的多轮 host-side 主线推进。

这份文档是**执行计划**，不是对象定义文档，也不是结果报告。它与下面几份文档配套使用：

- `docs/reference/题目.md`
- `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
- `docs/reivew/review_0609_2313.md`
- `docs/planning/implementation_plan.md`

如果旧文档中的执行顺序、优先级或边界与本文件冲突，以本文件为当前 host-mainline 多轮执行的操作性约束。

---

## 1. 固定判断与硬边界

### 1.1 固定判断

本轮及后续多轮推进，先接受下面这些判断，不再每轮从零争论：

1. 赛题核心不是开放域 agent 平台，而是：
   - `低开销通信`
   - `非文本状态传递`
   - `共享记忆复用`
   - 在可复现实验中的系统层机制验证
2. 当前仓库不是假的，但也不是自然开放 runtime；更准确的定位是：
   - `contest-shaped`
   - `host-side`
   - `controlled but honest`
   - `mechanism-oriented prototype`
3. 当前最值得保留的主骨架已经存在：
   - `protocol`
   - `statepool`
   - `memory`
   - `replay gate`
   - `eval/report split`
4. 当前最该修的不是“再加功能”，而是“让当前功能更诚实”：
   - lane 隔离
   - typed object family
   - typed handoff contract
   - Retriever / Executor 合同性真实性
5. `assist_only` 不再追 formal headline；它可以保留，但只能作为诊断层或负结果层。
6. `Planner` 不应先做成开放 DAG planner；若要改，只能改成 bounded task compiler。

### 1.2 当前明确不纳入

本计划明确**不包含**下面这些对象：

- 真实 VM 实现与验证
- Docker 交付链
- openEuler 交付部署
- 强沙箱终态
- `nsjail`
- hidden-state / KV 传递
- CodeAct 正式主路径
- open-world browser / desktop / computer-use benchmark

这些对象可以在文档中被提到，但只能作为：

- 后续阶段边界
- 当前不纳入项
- 最终交付或后验验证对象

不能把它们带回当前 host-side 主线实施。

### 1.3 当前唯一总路线

一句话路线：

> 先校正测量对象，再校正状态对象，再校正角色语义；不要先扩搜索空间，不要先追开放性。

对应成工程顺序：

1. 先修 benchmark contract
2. 再拆 object family
3. 再补 typed contract
4. 再改 Retriever / Executor
5. 再做 memory 分层
6. 最后才碰 Planner

---

## 2. 每轮执行合同

这份计划可能跨多个窗口、多个回合执行。为了防止后续漂移，每一轮都必须遵守下面的合同。

### 2.1 每轮开始前必须做的事

在任何代码修改、benchmark 重跑或方案延展之前，必须先明确写出：

1. 当前所在 phase
2. 本轮准备解决的单一对象
3. 本轮已读的本地必读文件
4. 本轮已读的 `third_party/` 本地参考文件
5. 本轮对应的 upstream 开源仓库
6. 本轮明确不做什么
7. 本轮准备运行的验证命令

### 2.2 每轮必须显式指出的阅读证据

每轮都必须指出：

- 至少 1 组本地文档 / 代码 / 证据锚点
- 至少 1 组 `third_party/` 本地文件锚点
- 至少 1 个对应 upstream repo URL

不允许只写：

- “参考了某仓库”
- “看了 README”
- “借鉴了某框架思路”

必须落到：

1. 读了哪个具体文件
2. 借的是哪一个具体机制
3. 为什么适合当前 phase
4. 为什么不照搬其余部分

### 2.3 每轮输出模板

后续每轮开始时，建议直接按下面模板汇报：

```text
当前 phase：

本轮单一目标：

本轮已读本地文件：
- ...

本轮已读 third_party 本地文件：
- ...

本轮对应 upstream repo：
- ...

本轮明确不做：
- ...

本轮计划验证：
- ...
```

### 2.4 Phase 跳转条件

本计划 0~7 的顺序是强约束，不允许任意跳。

只有在上一 phase 的退出条件满足后，下一 phase 才能启动。若退出条件未满足，只能：

- 继续补当前 phase
- 或明确停下，记录阻塞

不能直接跳过。

---

## 3. 每轮公共必读集

下面这些文件属于**每轮公共必读集**。无论当前做哪一个 phase，都必须先读或复读相关段落。

### 3.1 本地文档

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
- `docs/reivew/review_0609_2313.md`
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

### 3.2 公共代码锚点

- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/task_profile.py`
- `protocol/statebus.proto`
- `memory/store.py`
- `eval/runner.py`
- `tasks/sample_tasks.py`
- `tasks/sample_benchmark.yaml`
- `tasks/open_validation_benchmark.yaml`
- `tests/test_smoke.py`

### 3.3 公共证据锚点

- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `docs/progress/host_mainline_deep_audit_20260608.md`
- `docs/progress/host_goal_phase0_headline_stopline_20260609.md`

---

## 4. 本地参考仓库与 upstream 规则

### 4.1 一级参考仓库

这些 `third_party/` 仓库是当前 plan 的一级参考源：

- `third_party/evals`
- `third_party/langgraph`
- `third_party/langgraph-bigtool`
- `third_party/semantic-router`
- `third_party/haystack`
- `third_party/memsearch`
- `third_party/AgentRx`
- `third_party/mem0`

### 4.2 二级参考仓库

下面这些仓库只在 memory API 或记忆单元组织问题上按需读取，不作为一级必读：

- `third_party/agent-memory-server`

### 4.3 引用纪律

任何一轮如果使用第三方参考，必须同时给出：

1. 本地 clone 路径
2. 具体文件
3. 对应 upstream repo
4. 借鉴点
5. 不照搬点

推荐格式：

```text
当前弱点：
本地参考文件：
upstream repo：
借鉴机制：
不照搬原因：
```

---

## 5. Phase 0：基线冻结与 stopline 固化

### 5.0 目标

把“当前到底要证明什么、不再证明什么”冻结下来，避免后续每一轮一边改实现一边改 headline。

### 5.1 本 phase 必读本地文件

- `docs/reference/题目.md`
- `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
- `docs/reivew/review_0609_2313.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/progress/contest_requirement_guardrails_20260608.md`
- `docs/progress/host_mainline_problem_map_20260609.md`
- `docs/progress/host_goal_phase0_headline_stopline_20260609.md`

### 5.2 本 phase 必读第三方与 upstream

本地：

- `third_party/evals/README.md`
- `third_party/AgentRx/README.md`

upstream：

- `https://github.com/openai/evals`
- `https://github.com/microsoft/AgentRx`

### 5.3 本 phase 要做的事

1. 冻结当前 formal headline：
   - `communication`
   - `state_transfer`
   - `memory_replay`
2. 冻结当前不再追的 headline：
   - `assist_only`
   - `开放域平台能力`
   - `CodeAct 主路径`
3. 冻结当前 out-of-scope：
   - `VM`
   - `Docker`
   - `openEuler`
   - `强沙箱`
4. 明确多轮推进中哪些模块先冻结：
   - `statepool`
   - `memory` 主存储骨架
   - `replay gate` 总框架
   - `eval` 总体出报结构

### 5.4 退出条件

- 有一份清楚的 stopline 口径
- 后续所有 phase 都能引用这条口径
- 没有人再把当前目标写成“做更通用的 agent 平台”

### 5.5 本 phase 禁止项

- 不改代码
- 不重跑大 benchmark
- 不扩工具
- 不讨论 Docker/openEuler 落地实现

---

## 6. Phase 1：Benchmark Contract 隔离化

### 6.0 目标

让每条 formal lane 真正只改一个因素，先修 measurement honesty，再谈后续结构改造。

### 6.1 本 phase 必读本地文件

- `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
- `tasks/sample_benchmark.yaml`
- `tasks/open_validation_benchmark.yaml`
- `tasks/sample_tasks.py`
- `runtime/task_profile.py`
- `eval/runner.py`
- `docs/progress/benchmark_fairness_audit_20260608.md`
- `docs/progress/benchmark_lane_handoff_refresh_20260608.md`
- `docs/progress/phase5_benchmark_pack_split_20260609.md`
- `docs/progress/text_brief_executor_fidelity_formal_20260609.md`
- `tests/test_smoke.py`

### 6.2 本 phase 必读第三方与 upstream

本地：

- `third_party/evals/README.md`
- `third_party/evals/docs/build-eval.md`
- `third_party/evals/docs/custom-eval.md`
- `third_party/evals/docs/run-evals.md`

upstream：

- `https://github.com/openai/evals`
- `https://github.com/sierra-research/tau-bench`

### 6.3 本 phase 要做的事

1. 把 `communication lane` 改成：
   - 同任务
   - 同工具
   - 同 memory policy
   - 同 handoff policy
   - 只改 `text vs protocol`
2. 把 `state_transfer lane` 改成：
   - 同任务
   - 同工具
   - 同 memory policy
   - 都走 `protocol`
   - 只改 `text_brief vs state_ref`
3. 把 `memory lane` 拆成两个正式视图：
   - `memory_off vs assist_only`
   - `assist_only vs replay_enabled`
4. 强化 report-level 读者合同：
   - `what changed`
   - `what fixed`
   - `what must not be concluded`
5. 明确 `open validation pack` 永远不进入 formal headline。

### 6.4 建议验证

- `pytest -q tests/test_smoke.py -k 'state_transfer_lane or memory or communication'`
- deterministic 小样本 compare
- manifest / report 内容审查

### 6.5 退出条件

- 每条 lane 都能被一句话说明“只改了什么”
- 测试能证明 lane 隔离，不靠报告文字补救
- `formal controlled` 与 `open validation` 的边界在任务集和报告里都一致

### 6.6 本 phase 禁止项

- 不改 Retrieval / Executor 算法
- 不追新 benchmark 任务族
- 不开始改 Planner 自由度

---

## 7. Phase 2：Object Family 拆分

### 7.0 目标

把当前挤在 `FEATURE_BUNDLE` 里的多种语义拆成真正的一等对象，先做 object boundary refactor，不做算法重写。

### 7.1 本 phase 必读本地文件

- `protocol/statebus.proto`
- `protocol/messages.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `agents/sample_agents.py`
- `statepool/store.py`
- `tests/test_protocol_messages.py`
- `docs/progress/text_brief_executor_fidelity_20260609.md`
- `docs/progress/executor_feature_observability_20260609.md`
- `docs/progress/executor_observability_out_of_band_20260609.md`
- `docs/planning/state_transfer_benchmark_redesign_20260610.md`

### 7.2 本 phase 必读第三方与 upstream

本地：

- `third_party/langgraph-bigtool/README.md`
- `third_party/langgraph-bigtool/langgraph_bigtool/tools.py`
- `third_party/langgraph-bigtool/langgraph_bigtool/graph.py`
- `third_party/semantic-router/README.md`
- `third_party/semantic-router/semantic_router/route.py`
- `third_party/semantic-router/semantic_router/schema.py`

upstream：

- `https://github.com/langchain-ai/langgraph-bigtool`
- `https://github.com/aurelio-labs/semantic-router`

### 7.3 本 phase 要做的事

至少引入下面三类一等状态对象：

1. `RANKED_EVIDENCE_BUNDLE`
2. `TOOL_CANDIDATE_SET`
3. `REPLAY_ELIGIBILITY_BUNDLE`

保留：

- `TOOL_ARTIFACT`
- `DENSE_EVIDENCE`
- `EMBEDDING`

迁移方式：

1. 先新增状态 kind 与 schema
2. 先双写新对象和旧 `FEATURE_BUNDLE`
3. 再让 `Executor` / replay gate 改读新对象
4. 最后把 `FEATURE_BUNDLE` 降级为兼容层

### 7.4 建议验证

- `tests/test_protocol_messages.py`
- `tests/test_smoke.py -k 'feature or transfer or replay'`
- artifact 检查：新 state kind 是否真实落盘、可序列化、可回放

### 7.5 退出条件

- formal path 中的新对象已经可见
- `FEATURE_BUNDLE` 不再是唯一的语义容器
- Executor 和 replay gate 至少有一部分已经显式消费新对象

### 7.6 本 phase 禁止项

- 不改 route scoring 逻辑
- 不改 memory ranking 算法
- 不把 object family 扩成开放 schema 平台

---

## 8. Phase 3：Typed Handoff Contract 补齐

### 8.0 目标

让 capability 不再只声明“会产出什么”，还要真实校验“输入是否符合 consumer contract”。

### 8.1 本 phase 必读本地文件

- `runtime/contracts.py`
- `protocol/statebus.proto`
- `protocol/messages.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `tests/test_protocol_messages.py`
- `tests/test_smoke.py`
- `docs/reference/statebus_dual_plane_deep_design.md`

### 8.2 本 phase 必读第三方与 upstream

本地：

- `third_party/haystack/README.md`
- `third_party/haystack/pydoc/pipeline_api.yml`
- `third_party/haystack/test/core/pipeline/test_validation_pipeline_io.py`
- `third_party/langgraph/libs/langgraph/README.md`

upstream：

- `https://github.com/deepset-ai/haystack`
- `https://github.com/langchain-ai/langgraph`

### 8.3 本 phase 要做的事

1. 引入轻量 `state contract registry`
2. 对每种状态声明：
   - producer
   - consumer
   - schema/version
   - required metadata
   - lifecycle / replay compatibility
3. 在 step 执行前统一校验输入 state
4. 让 `accepted_state_kinds` 不再只是文档字段，而是运行时约束的一部分

### 8.4 建议验证

- 构造非法 state 输入测试
- 校验 replay copy path 是否也遵守 contract
- 检查 UDS executor path 是否仍兼容

### 8.5 退出条件

- 非法输入 state 能在 step 执行前被拒绝
- capability、schema、runtime contract 三者不再分离
- 关键 consumer 不再只靠 agent 自己手写筛 ref

### 8.6 本 phase 禁止项

- 不新增 agent 角色
- 不引入开放状态市场

---

## 9. Phase 4：Retriever / Executor 合同性真实性

### 9.0 目标

降低 repo-local shaping 的强度，但不追求开放世界；让选择性更诚实，而不是把特化藏在 hint / theme / metadata 里。

### 9.1 本 phase 必读本地文件

- `tasks/local_corpus.py`
- `runtime/executor_runtime.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `docs/progress/retrieval_candidate_pool_refresh_20260609.md`
- `docs/progress/retrieval_candidate_pool_api_spot_check_20260609.md`
- `docs/progress/retrieval_replay_route_provenance_contract_20260609.md`
- `docs/progress/executor_low_confidence_diagnostic_20260609.md`
- `docs/progress/executor_conflict_thin_override_20260609.md`
- `docs/progress/executor_thin_support_abstain_20260609.md`
- `tests/test_smoke.py`

### 9.2 本 phase 必读第三方与 upstream

本地：

- `third_party/semantic-router/README.md`
- `third_party/semantic-router/docs/user-guide/features/threshold-optimization.md`
- `third_party/semantic-router/semantic_router/routers/hybrid.py`
- `third_party/langgraph-bigtool/langgraph_bigtool/tools.py`
- `third_party/haystack/pydoc/routers_api.yml`

upstream：

- `https://github.com/aurelio-labs/semantic-router`
- `https://github.com/langchain-ai/langgraph-bigtool`
- `https://github.com/deepset-ai/haystack`

### 9.3 本 phase 要做的事

1. 继续降低 `task_theme/task_group/corpus_doc_ids` 的 shaping 强度
2. 把它们保留为 weak prior，而不是 primary gate
3. 让 `Executor` 显式消费 `TOOL_CANDIDATE_SET`
4. 让 replay eligibility 显式消费 `REPLAY_ELIGIBILITY_BUNDLE`
5. 保留并强化：
   - `low_confidence_abstain`
   - `ambiguous_candidates_abstain`
   - `metadata_only_abstain`

### 9.4 建议验证

- 当前 retrieval diagnostics task sets
- route provenance regression
- cross-family / theme-variant / weak-route 诊断任务

### 9.5 退出条件

- theme 不再像隐式主路由门
- tool selection provenance 可解释
- replay reject/accept 不再主要靠 metadata-only 拼接

### 9.6 本 phase 禁止项

- 不扩开放域 corpus
- 不大规模新增工具
- 不引入 browser / desktop tool family

---

## 10. Phase 5：Memory 分层与 replay 合同强化

### 10.0 目标

把 memory 从“只有 assist/replay purpose 区分”提升为更清楚的层级对象，但仍服务赛题，不往“大而全 memory intelligence”漂。

### 10.1 本 phase 必读本地文件

- `memory/store.py`
- `protocol/messages.py`
- `agents/sample_agents.py`
- `runtime/reuse_contract.py`
- `runtime/orchestrator.py`
- `docs/progress/retrieval_replay_route_artifact_20260609.md`
- `docs/progress/retrieval_replay_diagnostic_surface_20260609.md`
- `docs/progress/structured_vs_text_claim_surface_report_20260609.md`
- `tests/test_memory_store.py`
- `tests/test_smoke.py`

### 10.2 本 phase 必读第三方与 upstream

本地：

- `third_party/memsearch/README.md`
- `third_party/memsearch/src/memsearch/store.py`
- `third_party/memsearch/src/memsearch/core.py`
- `third_party/memsearch/src/memsearch/reranker.py`
- `third_party/mem0/openmemory/README.md`
- `third_party/mem0/server/schemas.py`

upstream：

- `https://github.com/zilliztech/memsearch`
- `https://github.com/mem0ai/mem0`

### 10.3 本 phase 要做的事

让 memory 至少显式拥有下面这些字段：

- `memory_type`
- `validation_status`
- `route_signature`
- `tool_signature`
- `state_fingerprint`
- `replay_scope`

推荐的 memory 分层：

1. `evidence`
2. `outcome`
3. `strategy`
4. `validated_replay`

运行时纪律：

- assist path 主要读 `evidence / strategy`
- step-skipping 只读 `validated_replay`
- 不把 replay gain 写成“广义 memory intelligence”

### 10.4 建议验证

- `tests/test_memory_store.py`
- replay route eligibility regression
- report surface review：memory tables 是否真正分层

### 10.5 退出条件

- replay 可复用对象不再只藏在 `metadata_json`
- assist 与 replay 的检索路径在 schema 和报告层都被分开
- 当前 formal headline 仍明确是 `validated replay gain`

### 10.6 本 phase 禁止项

- 不把 assist-only 强行包装成收益 headline
- 不引入重型独立 memory 服务

---

## 11. Phase 6：Planner 诚实降级为 bounded compiler

### 11.0 目标

不是把 Planner 做得更开放，而是让它更诚实：保留三阶段 macro skeleton，但把语义约束输出显式化。

### 11.1 本 phase 必读本地文件

- `agents/sample_agents.py`
- `tasks/sample_tasks.py`
- `protocol/messages.py`
- `runtime/orchestrator.py`
- `docs/reivew/review_0609_2313.md`
- `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
- `tests/test_llm_runtime.py`

### 11.2 本 phase 必读第三方与 upstream

本地：

- `third_party/langgraph/examples/plan-and-execute/plan-and-execute.ipynb`
- `third_party/langgraph/examples/llm-compiler/LLMCompiler.ipynb`
- `third_party/AgentRx/agentrx/ir/trajectory_ir.py`

upstream：

- `https://github.com/langchain-ai/langgraph`
- `https://github.com/microsoft/AgentRx`

### 11.3 本 phase 要做的事

只允许把 Planner 改成输出 bounded fields，例如：

- `task_intent`
- `evidence_focus`
- `freshness_requirement`
- `reuse_guard`
- `summary_contract`

运行时仍拥有固定 macro topology：

- `retrieve`
- `execute`
- `summarize`

不允许把当前工作改成开放 DAG planner 项目。

### 11.4 建议验证

- planner output parser regression
- text/protocol 双模式 planner contract 稳定性
- summary / retrieval / replay contract 是否仍一致

### 11.5 退出条件

- Planner 不再被包装成自由规划器
- bounded fields 对下游有真实消费路径
- repeat-10 稳定性没有因为 Planner 语义扩张而显著恶化

### 11.6 本 phase 禁止项

- 不扩 DAG
- 不新增角色
- 不引入开放工具生态

---

## 12. Phase 7：Formal 重跑、报告收口与文档同步

### 12.0 目标

在前面 0~6 完成后，才正式进入 artifact closure，更新 formal pack 与 open validation pack 的证据层。

### 12.1 本 phase 必读本地文件

- `docs/start_here.md`
- `docs/new_window_prompt.md`
- `eval/runner.py`
- `tasks/sample_benchmark.yaml`
- `tasks/open_validation_benchmark.yaml`
- `docs/progress/structured_vs_text_claim_surface_report_20260609.md`
- `docs/progress/phase5_benchmark_pack_borrow_list_20260609.md`
- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`

### 12.2 本 phase 必读第三方与 upstream

本地：

- `third_party/evals/README.md`
- `third_party/evals/docs/run-evals.md`
- `third_party/AgentRx/agentrx/ir/trajectory_ir.py`
- `third_party/AgentRx/agentrx/reports/metrics.py`

upstream：

- `https://github.com/openai/evals`
- `https://github.com/microsoft/AgentRx`
- `https://github.com/sierra-research/tau-bench`
- `https://github.com/xlang-ai/OSWorld`
- `https://github.com/web-arena-x/webarena`

### 12.3 本 phase 要做的事

严格按下面顺序：

1. `pytest -q`
2. `python -m runtime.smoke`
3. deterministic targeted rerun
4. deterministic repeat-10
5. serialized API repeat-10
6. open validation refresh（`repeat 1-3`）
7. 报告、README、进度文档同步

报告口径必须固定为：

- `communication`：结构化控制面收益
- `state_transfer`：typed non-text handoff 收益
- `memory`：validated replay gain
- `assist_only`：诊断或负结果层

### 12.4 退出条件

- formal controlled pack 有独立、干净、隔离的证据
- open validation pack 保持 support-only
- 文档口径与 artifact 目录一致
- 没有把 worktree 推进误写成正式已证据化事实

### 12.5 本 phase 禁止项

- 不混写 formal 与 support evidence
- 不在 artifact 未落盘前改 headline
- 不把 VM / Docker / openEuler 部署拉回来

---

## 13. 各 phase 的优先级裁决

### 13.1 必须先做

下面三项是当前最核心、最贴题的主矛盾：

1. `Phase 1`：benchmark contract 隔离
2. `Phase 2`：object family 拆分
3. `Phase 3`：typed handoff contract

### 13.2 高价值但次一级

1. `Phase 4`：Retriever / Executor 合同性真实性
2. `Phase 5`：memory 分层与 replay 合同强化

### 13.3 有条件再做

1. `Phase 6`：Planner bounded compiler

### 13.4 最后收口

1. `Phase 7`：formal rerun / report closure

---



这是当前最贴赛题、最容易形成亮点、也最不容易跑偏的组合。
