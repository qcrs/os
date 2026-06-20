# StateBus 四个 LLM Agent 重构实施计划

日期：2026-06-20

适用范围：
- 当前仓库 `/home/qcrs/statebus/project`
- 基于 `docs/planning/statebus_4_role_comparator_contract_20260620.md`
- 用于指导后续代码实现

定位：
- 这是 implementation-grade plan
- 目标是让实现者可以按阶段、按文件、按测试落地
- 不是方向讨论文档

---

## 1. 执行摘要

这次重构的目标不是“把四个角色都接上 LLM”这么简单，而是：

> 在不破坏 StateBus 方法身份的前提下，  
> 把当前“前后 LLM + 中间 deterministic helper”的主链路，  
> 重构成一个**合同受控的 4-role paired comparator runtime**，  
> 使 `text carrier` 和 `StateBus carrier` 能在同角色、同任务、同评分下公平比较。

本计划的主线固定为：

1. 先做 `4-role paired comparator` 基础设施
2. 再做 `StateBus lane`
3. 再做 `external pure-text lane`
4. 再做 paired smoke object
5. 再做 API repeat=1 / repeat=3
6. 最后才讨论 headline 升格

当前**明确不做**：

- open-world / freer interaction
- CodeAct 主线并入
- openEuler VM 验证
- 生产级 sandbox 强化

---

## 2. 设计原则

### 2.1 当前主问题

当前主问题不是“LLM 调得不够多”，而是：

- comparator 不够公平
- role semantic work 没有对称展开
- metrics 不足以归因

所以实现顺序必须围绕 comparator contract，而不是围绕 agent 炫技。

### 2.2 只改一类主变量

新 paired comparator 中，唯一允许作为 headline 主变量读取的差异是：

```text
carrier / state-consumption contract
```

这意味着实现过程中必须持续防止：

- text lane 变成 mega prompt
- protocol lane 保留 hidden helper 特权
- 两条 lane 看到不同任务语义

### 2.3 先 contract-compatible，再追结果

如果某个阶段实现了功能，但仍然无法满足：

- role I/O symmetry
- fairness gate
- role-level metrics
- support-aware scoring

则该阶段**不算完成**。

---

## 3. 新对象与新模块

本次实现将新增两个正式对象和若干支撑模块。

### 3.1 新 benchmark surface

1. `contest_four_role_carrier_comparison_v1`
   - 当前 StateBus 内部 paired comparator 主对象
   - lane A: `text carrier`
   - lane B: `statebus carrier`

2. `external_pure_text_four_role_baseline_v1`
   - 当前 external comparator 主对象
   - 只保留 text carrier
   - 不依赖 StateBus runtime internals

### 3.2 新实现概念

需要新增或重构出以下实现级概念：

1. `RoleExecutionContract`
2. `RoleIOView`
3. `LLM_CONTEXT_SLICE`
4. `CarrierFairnessGate`
5. `RoleUsageTrace`
6. `FourRoleComparatorRunner`

### 3.3 不应直接推翻的现有模块

以下模块应尽量保留并重用，而不是推倒重写：

- `runtime/orchestrator.py`
- `runtime/langgraph_adapter.py`
- `runtime/llm.py`
- `protocol/messages.py`
- `statepool/store.py`
- `memory/store.py`
- `tasks/sample_tasks.py`
- `eval/metrics.py`

---

## 4. 总体阶段计划

本次实施固定分为 7 个 phase。

### Phase 0: 合同对齐与对象冻结

目标：

- 不写核心实现
- 只补齐本次重构所需的 repo 内对象、命名、边界文档

交付：

- 当前已完成的合同文档
- 当前实施计划文档

通过标准：

- 所有后续实现以 `statebus_4_role_comparator_contract_20260620.md` 为唯一主合同

### Phase 1: Role-Level Runtime 抽象层

目标：

- 先把“4 semantic roles”的 runtime 抽象搭起来
- 暂不切入 API 主跑

交付：

- 统一的 role I/O contract types
- role-level usage/latency metrics
- role view builder

通过标准：

- 现有主链路仍可跑
- 新 contract objects 可在 deterministic 模式下创建和检查

### Phase 2: StateBus Lane 的 4-role semantic 化

目标：

- 让 `Planner / Retriever / Executor / Summarizer` 都能以 LLM role 方式运行
- 但仍保留 StateBus carrier / typed state / memory / orchestration 身份

交付：

- StateBus lane 的 4-role execution path
- `LLM_CONTEXT_SLICE`
- protocol lane field access logging

通过标准：

- protocol lane 不再依赖“全量 typed packet 回文本”
- deterministic smoke 下每个 role 的 visible inputs 可追踪

### Phase 3: External Pure-Text 4-role Baseline

目标：

- 做一个 role-equivalent 的 external pure-text runtime
- 不污染 StateBus runtime 内部

交付：

- external 4-role runner
- independent scoring adapter
- no lexical fallback baseline path

通过标准：

- baseline 通过 carrier purity gate
- baseline 不 import StateBus runtime internals beyond allowed shared infra

### Phase 4: Paired Smoke Object

目标：

- 先做 deterministic/local paired smoke object
- 验证 comparator 真的可以公平执行

交付：

- 最小 smoke task slice
- paired smoke runner
- fairness gate artifact

通过标准：

- 两条 lane 都能跑通
- role graph / role I/O / scoring contract 一致

### Phase 5: API Repeat=1 / Repeat=3

目标：

- 在已过 contract gate 的前提下跑 API

交付：

- repeat=1 smoke artifact
- repeat=3 serialized artifact

通过标准：

- role-level usage 落盘
- fairness gate 全通过
- 结果可归因

### Phase 6: Decide Headline Upgrade or Stop

目标：

- 不默认升格 headline
- 只根据 artifact 决定

交付：

- 结论文档
- 是否升格建议

通过标准：

- comparator 真正回答了赛题主问题

---

## 5. 文件级改造计划

本节按文件列出具体应改什么。

## 5.1 `runtime/llm.py`

### 现状

当前主要 role config 只有：

- `planner`
- `summarizer`

### 需要改造

1. 扩展 role config：
   - `retriever`
   - `executor`

2. 增加 role-level request metadata：
   - `role_name`
   - `trace_id`
   - `task_id`
   - `lane_name`

3. 为所有 LLM 结果保留标准 usage record：
   - prompt tokens
   - completion tokens
   - total tokens
   - model
   - latency ms

### 需要新增

- `RoleLLMUsageRecord`
- `RolePromptDigest`

### 验收

- 任一 role 调 LLM 后，都能统一写入 usage record

## 5.2 `eval/metrics.py`

### 现状

当前 `TaskMetrics` 主要适合：

- aggregate llm totals
- planner/summarizer split

### 需要改造

扩展到 4-role comparator 所需字段：

- `planner_prompt_tokens`
- `planner_completion_tokens`
- `planner_latency_ms`
- `retriever_prompt_tokens`
- `retriever_completion_tokens`
- `retriever_latency_ms`
- `executor_prompt_tokens`
- `executor_completion_tokens`
- `executor_latency_ms`
- `summarizer_prompt_tokens`
- `summarizer_completion_tokens`
- `summarizer_latency_ms`
- `handoff_message_count`
- `handoff_text_bytes`
- `state_transfer_count`
- `state_transfer_wire_bytes`
- `state_transfer_payload_bytes`
- `memory_lookup_count`
- `memory_write_count`
- `fairness_gate_passed`
- `fairness_gate_failure_reasons`

### 验收

- 两条 lane 的 metrics schema 一致

## 5.3 `protocol/messages.py`

### 现状

已有：

- `Plan`
- `PlanStep`
- `StepResult`
- `StateRef`

### 需要新增或扩展

建议优先以 dataclass + typed state kind 形式新增，而不是一开始就大改 `.proto`：

1. `RoleExecutionContract`
2. `RoleIOView`
3. `LLMContextSlice`
4. `RoleDecisionAudit`

### 建议字段

#### `RoleIOView`

- `role_name`
- `lane_name`
- `allowed_input_kinds`
- `allowed_text_sources`
- `forbidden_fields`
- `visible_memory_summary_ids`

#### `LLMContextSlice`

- `source_role`
- `target_role`
- `slice_kind`
- `budget_class`
- `included_fields`
- `omitted_fields`
- `text_projection`
- `backing_state_ref_ids`

### 验收

- protocol lane 每个 role 的 typed-state to prompt 投影都有显式对象

## 5.4 `runtime/task_profile.py`

### 现状

当前 profile 更偏向：

- transfer_strategy
- handoff_profile
- reuse contract

### 需要改造

加入 comparator-aware lane semantics：

- `lane_family`
- `role_graph_name`
- `carrier_contract_name`
- `allow_typed_state_consumption`
- `allow_role_level_llm`
- `llm_context_budget_class`

### 验收

- task profile 能描述 comparator lane，而不仅仅是旧 transfer strategy

## 5.5 `agents/sample_agents.py`

这是本次重构最大改造点。

### 总体改造策略

不要一次性推倒重写。先把每个 role 的逻辑拆成三层：

1. `assemble_role_inputs`
2. `run_role_semantic_decision`
3. `materialize_role_outputs`

### `PlannerAgent`

#### 要改什么

- 保留 YAML path 作为 support path
- 新增 `llm_semantic_plan` path 作为 comparator path
- comparator path 不只产 `Plan`，还要产 planner handoff abstraction

#### 新函数建议

- `_build_planner_role_view()`
- `_planner_semantic_messages()`
- `_planner_semantic_output_to_contract()`

### `RetrieverAgent`

#### 当前问题

- 当前它直接生成 `feature_bundle` 并隐式决定 route/tool 候选空间

#### 要改什么

- 保留 retrieval infra
- 把 route/tool 语义解释交给 retriever LLM
- `feature_bundle` 降级为 retrieval-side feature source

#### 新函数建议

- `_build_retriever_role_view()`
- `_retriever_semantic_messages()`
- `_retriever_output_to_context_slice()`
- `_retriever_output_to_candidate_packet()`

### `ExecutorAgent`

#### 当前问题

- 当前大量 route/tool 恢复逻辑在 `runtime/executor_runtime.py`

#### 要改什么

- 最终 action selection 改成 executor LLM
- deterministic tool runtime 继续保留
- validation 作为 executor-side bounded substep

#### 新函数建议

- `_build_executor_role_view()`
- `_executor_semantic_messages()`
- `_executor_output_to_action_contract()`
- `_executor_output_to_summary_slice()`

### `SummarizerAgent`

#### 当前问题

- protocol lane 目前会把 typed packet 再 `json.dumps()`

#### 要改什么

- 统一只吃 bounded `LLM_CONTEXT_SLICE`
- 禁止整包 typed packet 回灌

#### 新函数建议

- `_build_summarizer_role_view()`
- `_summarizer_semantic_messages_v2()`
- `_build_memory_commit_from_summary_v2()`

### `build_sample_agents`

#### 要改什么

- 支持 comparator mode role config
- 注入 role-aware llm clients / traces

### 验收

- 任一 role 的 visible input 都可追踪
- protocol lane 不再依赖 hidden full-packet text dump

## 5.6 `runtime/executor_runtime.py`

### 总体原则

保留 deterministic execution backend，但降级其语义地位。

### 保留

- tool catalog
- tool execution
- validation helper
- evidence utility

### 降级

- `build_feature_bundle()` 不再作为 comparator 主路径最终决策器
- `_feature_bundle_from_text_whole_lane_handoff()` 不再承担 formal comparator 主语义恢复
- `select_tool_name()` 不再主导 4-role comparator action choice

### 新职责

- candidate generation support
- structured logging support
- deterministic tool execution support

### 新函数建议

- `build_retrieval_feature_source()`
- `build_executor_candidate_catalog_view()`
- `build_tool_artifact_projection()`

### 验收

- 4-role comparator 下的最终 route/tool 决定不来自 hidden deterministic shortcut

## 5.7 `runtime/orchestrator.py`

### 要改什么

- 保留固定图
- 加入 role I/O contract enforcement
- 加入 fairness gate hook
- 加入 role-level trace aggregation

### 新增 hook 建议

- `prepare_role_view()`
- `run_fairness_gate_pre_task()`
- `record_role_usage()`
- `record_context_slice()`
- `record_role_contract_violation()`

### 验收

- 任一 task 执行前能检查 comparator validity

## 5.8 `runtime/langgraph_adapter.py`

### 要改什么

- 保留现有固定图
- graph state 增加：
  - role usage
  - fairness gate
  - context slices
  - role views

### 不要做什么

- 不要在这阶段引入 open-ended swarm graph

### 验收

- fixed graph 仍成立
- paired comparator traces 可在 graph state 中追踪

## 5.9 `tasks/sample_tasks.py`

### 要改什么

新增 object builder，而不是覆盖旧 object：

1. `_build_contest_four_role_carrier_comparison_bundle()`
2. `_build_external_pure_text_four_role_bundle()`
3. `_build_four_role_smoke_slice_bundle()`

### 新任务字段建议

- `paired_comparator_group`
- `role_graph_name`
- `support_contract_level`
- `requires_role_local_decision`
- `forbid_single_prompt_collapse`
- `fairness_contract_name`

### 重要原则

- 保留旧 frozen headline object
- 新对象与旧对象并存

### 验收

- 新 bundle 不污染旧 bundle 读法

## 5.10 `eval/text_open_baseline.py`

### 当前问题

- 当前 runtime 是 audit-only，而且 still fallback-prone

### 要改什么

把它拆成两层：

1. 保留 legacy audit-only runtime
2. 新增 strict 4-role external baseline runtime

### 新类建议

- `ExternalPureTextFourRoleRuntime`
- `ExternalTextRoleView`
- `ExternalTextFairnessAudit`

### 严格要求

- 禁 lexical fallback silently correcting LLM outputs
- 不 import forbidden StateBus runtime semantics

### 验收

- 能通过 `carrier_purity_gate`

## 5.11 `eval/open_runner.py`

### 要改什么

- 支持新 pack：
  - `external_pure_text_four_role_baseline_v1`
- 支持 role-level metrics
- 支持 fairness gate artifact

### 验收

- baseline runner 输出结构与 paired compare 可对齐

## 5.12 `eval/runner.py`

### 要改什么

新增 comparator-aware benchmark path：

1. fairness gate checks
2. role-level metric aggregation
3. support-aware scoring
4. comparator report sections

### 新报告块建议

- role-level usage table
- fairness gate table
- carrier purity checks
- route/tool/support correctness table
- lane delta summary

### 验收

- paired compare artifact 可以直接回答赛题项

## 5.13 新增文件建议

建议新增：

1. `runtime/role_contracts.py`
2. `runtime/context_slice.py`
3. `eval/fairness_gates.py`
4. `eval/four_role_scoring.py`
5. `eval/four_role_compare_report.py`
6. `tasks/four_role_smoke_slice_v1.yaml`
7. `tasks/external_pure_text_four_role_baseline_v1.yaml`
8. `tasks/contest_four_role_carrier_comparison_v1.yaml`

---

## 6. 分阶段详细执行顺序

## Phase 1: Runtime 抽象准备

### 代码改动

1. 扩 `runtime/llm.py` role config
2. 扩 `eval/metrics.py`
3. 新增 `runtime/role_contracts.py`
4. 新增 `runtime/context_slice.py`

### 测试

- role config 可加载四角色
- metrics 可序列化
- context slice objects 可 round-trip

### 验收

- 现有 smoke 不被破坏

## Phase 2: Comparator Contract Enforcement

### 代码改动

1. `runtime/orchestrator.py` 加 role contract hooks
2. `runtime/langgraph_adapter.py` 加 role-view / fairness state
3. 新增 `eval/fairness_gates.py`

### 测试

- unfair role graph 被拒绝
- text lane typed-state leakage 被拒绝
- missing role metrics 被拒绝

### 验收

- fail-closed gate 起效

## Phase 3: StateBus Lane Semanticization

### 代码改动

1. `agents/sample_agents.py` 分层
2. `runtime/executor_runtime.py` 降级 helper 地位
3. `protocol/messages.py` 新 dataclasses

### 测试

- planner/retriever/executor/summarizer 都可跑 comparator path
- protocol lane 不再整包文本化

### 验收

- deterministic role-level traces 完整

## Phase 4: External Pure-Text Four-Role Runtime

### 代码改动

1. `eval/text_open_baseline.py` 新 strict runtime
2. `eval/open_runner.py` 支持新 pack
3. 新 `eval/four_role_scoring.py`

### 测试

- no forbidden imports
- no lexical fallback correction
- same role graph enforced

### 验收

- baseline 通过 purity gate

## Phase 5: New Task Bundles And Smoke Object

### 代码改动

1. `tasks/sample_tasks.py` 新 builders
2. 新 YAML bundles

### 测试

- object forces all 4 roles active
- object blocks single prompt collapse
- text/protocol share same scoring metadata

### 验收

- deterministic paired smoke object 跑通

## Phase 6: Eval / Report Integration

### 代码改动

1. `eval/runner.py` comparator report path
2. `eval/four_role_compare_report.py`

### 测试

- report contains role usage
- report contains fairness gate
- report contains route/tool/support correctness

### 验收

- artifact 能独立阅读

## Phase 7: API Runs

### 执行顺序

1. repeat=1 serialized smoke
2. repeat=3 serialized benchmark
3. 再决定是否值得 repeat=10

### 验收

- role-level metrics 非空
- fairness gate 全通过
- no hidden fallback

---

## 7. 测试计划

### 7.1 单元测试新增建议

新增测试文件：

1. `tests/test_role_contracts.py`
2. `tests/test_context_slices.py`
3. `tests/test_fairness_gates.py`
4. `tests/test_four_role_text_baseline.py`
5. `tests/test_four_role_statebus_lane.py`
6. `tests/test_four_role_scoring.py`

### 7.2 关键测试点

#### 合同测试

- 四角色图必须完整
- text lane 不可见 typed state
- protocol lane 不可无界 dump typed packet

#### scoring 测试

- final answer correct but wrong support should fail support-aware check
- hidden oracle leakage should fail
- admissible != superiority

#### baseline purity 测试

- external baseline 不可 import forbidden runtime modules
- external baseline 不可 silent lexical fallback

#### metrics 测试

- role-level token fields must exist
- aggregated totals must equal role sums

### 7.3 smoke 测试

先只跑 deterministic/local：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/test_role_contracts.py tests/test_context_slices.py tests/test_fairness_gates.py tests/test_four_role_scoring.py
python -m runtime.smoke
```

### 7.4 API 测试顺序

只有在上面通过后，才允许跑：

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner --task-set contest_four_role_carrier_comparison_v1 --repeat 1 --modes text,protocol --llm-mode api --llm-config deploy/statebus_llm.yaml.local --out runs/contest_four_role_carrier_comparison_v1_api_r1

python -m eval.open_runner --pack external_pure_text_four_role_baseline_v1 --repeat 1 --llm-mode api --llm-config deploy/statebus_llm.yaml.local --out runs/external_pure_text_four_role_baseline_v1_api_r1 --task-set external_pure_text_four_role_baseline_v1
```

---

## 8. 每阶段完成标准

### Phase 1 完成

- 四角色 LLM config 与 metrics schema 已落地

### Phase 2 完成

- fairness gate fail-closed 生效

### Phase 3 完成

- StateBus lane 4 semantic roles 可运行

### Phase 4 完成

- external pure-text 4-role baseline 可运行且 purity gate 通过

### Phase 5 完成

- deterministic/local paired smoke object 跑通

### Phase 6 完成

- report 可独立解释 comparator

### Phase 7 完成

- serialized API repeat artifacts 落盘

---

## 9. 明确禁止事项

实现期间明确禁止：

1. 直接覆盖或改写 `contest_honest_headline_v1` 语义
2. 直接把 open-world 并入主线
3. 在 text lane 中塞全局 mega prompt
4. 在 protocol lane 中继续整包文本化 typed state
5. 在 external baseline 中保留 silent lexical fallback
6. 在 fairness gate 缺失时跑 headline 叙事
7. 用 repeat=1 结果直接写 superiority claim

---

## 10. 当前唯一推荐执行顺序

如果现在真的开始写代码，只推荐这一条顺序：

1. Phase 1: role config + metrics + role/context contract
2. Phase 2: fairness gates
3. Phase 3: StateBus lane semanticization
4. Phase 4: external pure-text 4-role baseline
5. Phase 5: deterministic/local paired smoke object
6. Phase 6: report/scoring integration
7. Phase 7: API repeat=1 then repeat=3

不要反过来。

尤其不要：

- 先改四个 agent 再想规则
- 先跑 API 再补 fairness gate
- 先把 open-world 加进来

如果某一阶段没有通过本计划里定义的验收条件，后续阶段默认**禁止开始**。  
也就是说，本计划是串行 gate，不是可以自由并行推进的愿望清单。

---

## 11. 相关文档

主合同：

- `docs/planning/statebus_4_role_comparator_contract_20260620.md`

上游分析：

- `docs/analysis/statebus_independent_full_repo_review_20260620.md`
- `docs/analysis/statebus_independent_followup_deep_diagnosis_20260620.md`
- `docs/analysis/statebus_external_pure_text_baseline_contract_20260620.md`
- `docs/analysis/statebus_four_llm_agent_refactor_design_20260620.md`

历史 frozen headline：

- `docs/reports/final_claim_matrix_and_freeze_20260618.md`
