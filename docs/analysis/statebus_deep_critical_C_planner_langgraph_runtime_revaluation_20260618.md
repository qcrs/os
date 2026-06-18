# 文档 C：Planner / LangGraph / Runtime 角色重估

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## 1. Planner 到底有没有真实价值

Planner 有价值，但不是 current headline 的主创新。

### 1.1 当前 headline 中 Planner 的真实角色

`contest_honest_headline_v1` 默认：

- `task_set_plan_source_default = yaml`
- `build_plan()` 从 task contract 生成固定 semantic roles；
- 当前主路径是 `retrieve -> validate -> execute -> summarize`。

因此，headline 中 Planner 更像：

> task contract compiler / role orchestrator

而不是：

> adaptive LLM planner。

这并不使系统不合格。赛题要求覆盖规划角色，不要求 formal headline 的主变量必须是 Planner openness。

### 1.2 Planner 的价值层级

Planner 应分三层：

1. 合规层：
   - Planner 角色存在；
   - plan phase 存在；
   - semantic roles 明确。
2. 工程层：
   - plan contract 让 runner、LangGraph、Orchestrator、validation gate 可组合；
   - 这对系统完整性有价值。
3. 方法层：
   - LLM-open planning 不是 current headline 的主证据；
   - 只能作为 `planner_support_v3` 或后续 secondary。

### 1.3 Planner 弱点不是当前主线 bug

当前 headline 不开放 Planner 是设计选择：为了锁定 mode/handoff object 对比。

风险在叙事，不在代码：

- 可以说系统覆盖 Planner；
- 不应说 current headline 证明了 Planner 自主规划能力；
- 不应把 Planner 和 communication/state transfer 的收益混读。

## 2. LangGraph 到底扮演什么角色

### 2.1 LangGraph 是真实接入

`runtime/langgraph_adapter.py` 真实使用：

- `StateGraph(dict)`
- nodes: planner, retriever, validate, executor, summarizer
- conditional edge after retriever
- graph state snapshots
- `graph.ainvoke(state)`

因此，LangGraph 不是文档摆设。

### 2.2 LangGraph 不是 StateBus 创新对象

每个 LangGraph node 内部调用的是 Orchestrator 的语义方法：

- `compile_task_plan`
- `resolve_skip_retrieve_execute`
- `invoke_plan_step`
- `register_step_result`
- `resolve_skip_execute`

真正的 StateBus 机制在：

- protocol/state refs；
- schema/capability validation；
- validation gate；
- StatePool；
- memory/replay；
- task commit；
- metrics/report gates。

如果换成普通 DAG runner，StateBus 的核心 claim 大概率仍然成立。LangGraph 增强的是工程 substrate 和执行可观测性，不是方法主轴。

### 2.3 LangGraph 正确口径

可以说：

> StateBus 用 LangGraph 作为 host-side graph execution substrate，让四角色执行轨迹、state refs、memory hits、replay decisions 可观测。

不应说：

> StateBus 的创新来自 LangGraph。

也不应把 LangGraph-native vs StateBus 当成 current headline axis。

## 3. Runtime 强处

### 3.1 StateRef / StatePool 真实

runtime 支持：

- mmap 默认 backend；
- shared_memory 可选；
- msgpack typed states；
- text artifact states；
- StateRef metrics；
- handoff wire/payload metrics。

Protocol side 的 non-text refs 在 repeat=10 中稳定非零。

### 3.2 Validation gate 真实

`ExecutorAgent._validate_route_step()` 会：

- 读取 `EXECUTOR_DECISION_PACKET` 或 text handoff；
- 恢复/检查 route/tool；
- 进行 S1 action refinement；
- 进行 S2 prior boundary check；
- 输出 `VALIDATION_GATE_PACKET`；
- execute phase 消费 validation packet。

这不是 no-op。

### 3.3 S2 prior action 真实

`_headline_s2_prior_action_boundary()` 会：

- 查询 `task_commit` memory；
- 匹配 required prior case ids；
- 检查 chosen route；
- 检查 rejected routes；
- prior satisfied 时允许 scoped action；
- prior missing 时 fallback 到 collect-more-evidence。

这说明 S2 已经超过静态 metadata。

### 3.4 Replay path 真实

current headline 中 S2 rows 使用 `validated_replay`，repeat=10 有非零：

- replay probes；
- replay hits；
- skipped steps；
- reuse gain。

API repeat=10 aggregate:

- text `skipped_step_count = 5`
- protocol `skipped_step_count = 5`
- both `reuse_gain = 0.0625`

这说明 current-headline replay effect 已经存在。

## 4. Runtime 弱处

### 4.1 Executor 仍是 playbook selector

Executor 是 repo-local tool registry + playbook execution。它不是：

- CodeAct；
- arbitrary tool planner；
- large tool ecosystem；
- sandboxed program synthesis runtime。

这足够做 contest prototype，但不应包装成通用 executor 创新。

### 4.2 Retriever 仍是 local corpus router

Retriever 真实检索 local corpus，但仍在 route/tool family universe 里工作。它不是开放检索系统。

### 4.3 Text route recovery 仍存在

Text side 不吃 typed refs，但 validate/executor 仍会从 natural-language handoff + evidence 中恢复 route/tool feature。

这对 internal comparator 是合理的；对 external pure-text claim 是问题。

### 4.4 Runtime shape 固定

当前固定 shape 是：

```text
planner -> retriever -> validate -> executor -> summarizer
```

这让 benchmark 可控，但也说明 current headline 不证明开放图规划。

## 5. 多 Agent 角色是否真实必要

对赛题完整性：必要。

对 current method claim：部分必要。

- Retriever：必要，生产 evidence/state packet。
- Executor：必要，消费 packet/text 并执行 playbook。
- Summarizer：必要，生成 final answer 和 memory commits。
- Planner：在 current headline 中更多是组织结构，不是性能差异来源。

因此多 Agent 不是假的，但不是每个 Agent 都是同等强创新。

## 6. 当前 runtime 最合理的解释

当前 runtime 强处：

- 可运行；
- gate 严格；
- StateRef/typed packet 真实；
- S1/S2 已接到 runtime；
- replay effect 已进入 current headline；
- metrics 比旧版本清楚。

当前 runtime 弱处：

- Planner 不强；
- LangGraph 浅用；
- Executor 任务域窄；
- Retriever/corpus route-shaped；
- text comparator 共享 StateBus helper path；
- memory replay 受控。

## 7. C 文档结论

Planner 和 LangGraph 都不应作为 current headline 的创新主轴。

推荐叙事：

- Planner：system completeness + secondary planner support；
- LangGraph：execution substrate；
- Runtime core：StateBus protocol/state/ref/memory gates；
- Main innovation：structured control + typed-state handoff；
- Secondary strength：controlled S2 prior/replay；
- Boundary：不是 open planner，不是 LangGraph-native method，不是 CodeAct/sandbox/runtime marketplace。
