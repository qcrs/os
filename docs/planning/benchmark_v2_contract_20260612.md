# StateBus Benchmark V2 Contract

日期：`2026-06-12`

适用范围：

- 当前仓库：`/home/qcrs/statebus/project`
- 当前 host-mainline 多 Agent 赛题 benchmark 重构
- 当前已有 pack：
  - `formal_controlled`
  - `state_transfer_carrier`
  - `state_transfer_authenticity`
  - `state_transfer_pure_text`
  - `state_transfer_strict_pure_text`
  - `memory`
  - `open_planner_support`

这份文档的目标不是总结已有结果，而是定义 **下一版 benchmark 应该怎么设计、如何实施、哪些旧包冻结、哪些 claim 可以或不可以继续混读**。后续如果按 v2 推进，原则上应直接以本文件为执行合同。

---

## 1. 直接结论

当前 benchmark 的主要问题已经不是“能不能跑”，而是 **benchmark object 和 claim surface 混在一起了**。

当前至少混了 4 个不同问题：

1. `carrier efficiency`
   - 同语义，不同载体，谁更省通信、谁更快
2. `semantic state retention`
   - 非文本中间状态是否比自然文本更稳地保留中间语义
3. `memory reuse`
   - 记忆命中后能否减少重复检索、重复执行或总耗时
4. `planner openness`
   - Planner 是否真实在主路径里生成 plan，而不是固定 workflow 摆设

如果这 4 个问题继续放在一个总表或一个 formal-overview 包里同时回答，结果会继续混乱。

因此，v2 的唯一总原则是：

> 一个 pack 只回答一个问题；一个 headline 只服务一个 claim；一个表只比较一个变量。

---

## 2. 当前问题的代码级来源

### 2.1 当前 text baseline 不是一个对象

当前 repo 内部实际存在 4 种不同 text-side baseline：

- `text_packet_minimal`
- `text_brief`
- `natural_handoff_text`
- `inline_text_handoff`

它们语义完全不同：

- `text_packet_minimal`
  - 是最小 decision packet 的文本化形式
- `text_brief`
  - 是结构化 packet 的 textual shadow
- `natural_handoff_text`
  - 是自然语言 handoff
- `inline_text_handoff`
  - 是最严格的 executor-facing 消息体文本

因此，不能再把这些 baseline 统一写成“text”。

### 2.2 当前 state baseline 也不是一个对象

当前 repo 内部至少存在 2 种不同 state-side baseline：

- `state_packet_minimal`
- `state_ref`

两者语义也不同：

- `state_packet_minimal`
  - 传的是最小 typed decision packet
- `state_ref`
  - 传的是 richer typed state / feature snapshot

因此，不能再把它们统一写成“state”。

### 2.3 为什么会出现 state 比 text 更贵

当前出现 “state 比 text 更高” 不一定是系统异常，很多时候是 **比较对象本来就不一样**。

例如：

- `carrier` 类比较：
  - `text_packet_minimal` vs `state_packet_minimal`
  - 近似是“同语义，不同载体”
  - 才适合回答通信开销问题

- `pure_text` / `strict_pure_text` 类比较：
  - `natural_handoff_text` vs `state_ref`
  - `inline_text_handoff` vs `state_packet_minimal`
  - 比的是“自然语言承载语义” vs “typed state 承载语义”
  - 这时 state 更大、不一定更快，完全可能是真的

所以，当前很多争议并不是系统 bug，而是 **claim 口径错位**。

### 2.4 关键代码锚点

当前需要用下面这些实现锚点来约束 benchmark 设计：

- `natural handoff` 的真实内容：
  - [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:1558)
- Retriever 在不同 `transfer_strategy` 下写出什么对象：
  - [agents/sample_agents.py](/home/qcrs/statebus/project/agents/sample_agents.py:499)
- LangGraph 当前是固定四节点图：
  - [runtime/langgraph_adapter.py](/home/qcrs/statebus/project/runtime/langgraph_adapter.py:142)

这几个事实直接决定：

1. benchmark 必须拆 pack
2. LangGraph 不能被混成另一条 formal 主轴
3. strict pure-text 只适合做 formal-secondary 或 support 边界证明

---

## 3. V2 的目标与非目标

### 3.1 V2 要做到什么

V2 需要做到：

1. 明确区分不同 benchmark object
2. 明确区分不同 claim lane
3. 把正确性判断从单一 `task_match_rate` 升级为多级合同
4. 让每个 pack 的 headline 和 stopline 可直接复用
5. 保留现有 task family 资产，避免无必要推翻重建

### 3.2 V2 不做什么

V2 当前明确不做：

- 不引入 Docker/openEuler 作为 benchmark 主路径前提
- 不把 LangGraph 变成 formal headline baseline
- 不把 Planner openness 混进 state transfer formal headline
- 不先改 routing threshold 再改 benchmark
- 不先扩成开放自治 benchmark
- 不先接入外部复杂代码修复数据集作为 formal 主数据集

---

## 4. V2 总体设计原则

### 4.1 一个 pack 只回答一个问题

不能再让一个 pack 同时回答：

- 通信效率
- 语义保持
- memory reuse
- planner openness

### 4.2 单变量控制优先

每个 pack 必须显式写出：

1. 固定了什么
2. 只改了什么
3. 主指标是什么
4. 不允许读出什么结论

### 4.3 正确性合同升级

所有 task 不再只支持 family-level 单标签。

必须升级到 case-level 合同，允许区分：

- `exact_single_solution`
- `bounded_alternative`
- `abstention_allowed`

### 4.4 headline 和 support 强分离

v2 需要显式区分：

- `formal-headline`
- `formal-secondary`
- `support-only`
- `historical`

### 4.5 LangGraph 固定为 orchestration substrate

当前 repo 的 LangGraph 路径是：

- 固定四节点图
- 显式状态流
- 仍复用 public StateBus runtime primitives

因此在 v2 中：

- LangGraph 是固定编排底座
- 不是 formal 主变量
- 最多做 support-only native baseline

---

## 5. Pack 设计

### 5.1 `carrier_controlled_v2`

类型：

- `formal-headline`

回答的问题：

- 同语义，不同载体，谁更省通信、谁更快

固定：

- `mode = protocol`
- `memory = off`
- `plan_source = yaml`
- LangGraph topology
- same task family
- same query
- same retrieved docs
- same route/tool semantics

只改：

- `text_packet_minimal`
- `state_packet_minimal`

主指标：

- `control_bytes`
- `handoff_wire_bytes`
- `handoff_payload_bytes`
- `llm_total_tokens`
- `task_ms`

次指标：

- `route_exact_rate`
- `tool_exact_rate`

不能读出的结论：

- 不能把它说成“自然文本 vs typed state 公平性”
- 不能把它说成“state 一定更稳”

### 5.2 `semantic_retention_v2`

类型：

- `formal-headline`

回答的问题：

- 非文本 typed state 是否比自然语言 handoff 更能保留中间语义

比较：

- `natural_handoff_text`
- `state_ref`

固定：

- `mode = protocol`
- `memory = off`
- `plan_source = yaml`
- same task family / query / corpus_doc_ids / summary_hint

主指标：

- `route_exact_rate`
- `tool_exact_rate`
- `admissible_match_rate`
- `wrong_family_rate`
- `abstention_rate`

次指标：

- `control_bytes`
- `executor_handoff_text_bytes`
- `task_ms`

不能读出的结论：

- 不能用它证明“state 比 text 更省通信”

### 5.3 `strict_pure_text_boundary_v2`

类型：

- `formal-secondary`

回答的问题：

- 最严格 executor-facing pure-text baseline 是否真实成立

比较：

- `inline_text_handoff`
- `state_packet_minimal`

固定：

- `mode = protocol`
- `memory = off`
- `plan_source = yaml`

主指标：

- `pure_text_guard_pass_rate`
- `executor_handoff_text_bytes`
- `admissible_match_rate`

次指标：

- `control_bytes`
- `task_ms`

不能读出的结论：

- 不进入正式 aggregate
- 不作为通信效率主 headline

### 5.4 `memory_reuse_v2`

类型：

- `formal-headline`

回答的问题：

- 共享记忆命中后，是否减少重复工作

固定：

- 选择一条稳定 handoff 主线
- LangGraph topology
- same task family
- same route/tool target

只改：

- `memory_off`
- `assist`
- `validated_replay`
- `exact_replay`

主指标：

- `memory_hit_rate`
- `skipped_step_count`
- `reuse_gain`
- `task_ms`
- `llm_total_tokens`

次指标：

- `route_exact_rate`
- `tool_exact_rate`

不能读出的结论：

- 不能把 memory pack 说成 text vs protocol headline

### 5.5 `planner_support_v2`

类型：

- `support-only`

回答的问题：

- Planner 是否真实在 LangGraph StateBus 主路径里生成 plan

固定：

- same family set
- same retrieval/tool registry
- same graph topology

只改：

- `plan_source = yaml`
- `plan_source = llm`

主指标：

- `planner_llm_request_count`
- `planned_step_count`
- success rate
- route/tool admissibility

不能读出的结论：

- 不进入正式 headline aggregate

### 5.6 `langgraph_native_text_support_v2`

类型：

- `support-only`

回答的问题：

- StateBus 相比普通 LangGraph message/state/store workflow 到底多了哪些系统机制

边界：

- 只用于 support
- 不用于赛题正式 headline

原因：

- LangGraph 是 orchestration runtime，不是本赛题的数据面机制对象
- 当前 repo 的 object 仍然是 StateBus 的 protocol/statepool/memory 组合

### 5.7 `historical_v1`

类型：

- `historical`

建议冻结：

- `formal_controlled`
- 当前 `state_transfer_authenticity`
- 当前 `state_transfer_pure_text`
- 当前 `state_transfer_strict_pure_text`
- 当前 `state_transfer_carrier`

用途：

- 历史对照
- 回归参考
- 旧报告兼容

不再承担：

- v2 headline
- v2 正式 claim surface

---

## 6. Task Contract V2

### 6.1 每个 task 必须具备的字段

在保留现有字段的基础上，v2 task 应新增：

- `case_id`
- `case_type`
- `eval_scope`
- `expected_family`
- `primary_expected_route`
- `primary_expected_tool`
- `acceptable_routes`
- `acceptable_tools`
- `disallowed_families`
- `abstention_allowed`
- `allowed_abstain_tool`
- `abstain_only_when`

### 6.2 `case_type` 定义

#### `exact_single_solution`

适用：

- `clean`
- 一部分证据充分的 `replay_reusable`

判断规则：

- route 必须 exact
- tool 必须 exact

#### `bounded_alternative`

适用：

- `distractor`
- 一部分 `ambiguous`

判断规则：

- primary route/tool 最优
- 允许有限 alternate route/tool
- alternate 必须预先写入合同

#### `abstention_allowed`

适用：

- 刻意做薄证据的 case
- 需要允许保守不下执行决策的 case

判断规则：

- `generic_triage`
- `tool.collect_more_evidence`
- 只在合同允许时算 admissible

### 6.3 当前四种 case 的合同建议

#### `clean`

- 默认：`exact_single_solution`

#### `distractor`

- 默认：`bounded_alternative`

说明：

- 不再强制 family-level 单标签
- 如果系统稳定选择另一条强解释，不能直接记为 system failure

#### `ambiguous`

- 默认：`bounded_alternative` 或 `abstention_allowed`

说明：

- ambiguous 不能再按 strict single-label 判错

#### `replay_reusable`

拆成两类：

1. 语义一致性 replay case
2. memory step-skipping replay case

不要再让一个 case 同时承担 semantic retention 和 replay gain 两个对象。

---

## 7. 指标合同

### 7.1 正确性指标

v2 不再只使用一个 `task_match_rate`。

必须拆成：

- `route_exact_rate`
- `tool_exact_rate`
- `exact_match_rate`
- `admissible_match_rate`
- `abstention_rate`
- `wrong_family_rate`

### 7.2 成本指标

保留：

- `control_bytes`
- `handoff_wire_bytes`
- `handoff_payload_bytes`
- `handoff_textual_bytes`
- `handoff_nontext_bytes`
- `llm_total_tokens`
- `task_ms`

新增或显式提升：

- `executor_handoff_text_bytes`

### 7.3 解释规则

#### `carrier` 类 pack

主读：

- 成本指标

次读：

- exact correctness

#### `semantic_retention` 类 pack

主读：

- exact/admissible/wrong-family/abstain

次读：

- bytes / time

#### `memory` 类 pack

主读：

- hit / skip / gain

次读：

- cost变化

---

## 8. 报告合同

每个 v2 report 固定 6 段：

1. `Pack Contract`
2. `Single Variable`
3. `Primary Metrics`
4. `Secondary Diagnostics`
5. `Case-Type Breakdown`
6. `Stopline`

### 8.1 `Pack Contract`

必须明确写：

- 这个 pack 回答什么
- 不回答什么

### 8.2 `Single Variable`

必须明确写：

- 固定了什么
- 只改了什么

### 8.3 `Primary Metrics`

只展示当前 pack 的主指标，不混无关表。

### 8.4 `Secondary Diagnostics`

放：

- route_source
- pure_text_guard
- handoff bytes
- token / time

### 8.5 `Case-Type Breakdown`

至少分：

- `clean`
- `distractor`
- `ambiguous`
- `replay`

### 8.6 `Stopline`

必须显式写：

- 当前 pack 可以支持什么 claim
- 当前 pack 不能支持什么 claim

---

## 9. LangGraph 在 V2 里的位置

### 9.1 固定定位

v2 中，LangGraph 固定为：

- orchestration substrate
- fixed graph execution runtime
- not a formal headline axis

### 9.2 为什么不把 LangGraph 当 formal baseline

原因有三条：

1. 当前赛题对象是：
   - 低开销通信
   - 非文本状态传递
   - 共享记忆复用
2. LangGraph 官方定位本身是 stateful orchestration runtime，不是该赛题的数据面机制 benchmark
3. 当前 repo 的 LangGraph 路径仍然主要承载固定拓扑和显式 state graph，不适合被混成“另一个系统对象”

### 9.3 可以借什么

可以借：

- state graph 明确状态流
- workflow vs agent 边界
- short-term state vs long-term store 的分层思路

不能借：

- 把 LangGraph 本身当作赛题三项主 baseline

---

## 10. 外部参考

### 10.1 LangGraph 官方资料

- LangGraph overview:
  - <https://docs.langchain.com/oss/python/langgraph/overview>
- LangGraph workflows and agents:
  - <https://docs.langchain.com/oss/python/langgraph/workflows-agents>
- LangGraph memory:
  - <https://docs.langchain.com/oss/python/langgraph/memory>

V2 中对 LangGraph 的借鉴主要用于：

- orchestration boundary 定义
- workflow / agent 区分
- state / memory 的层次化说明

### 10.2 SWE-bench / SWE-bench-Live

- SWE-bench:
  - <https://arxiv.org/abs/2310.06770>
- SWE-bench-Live:
  - <https://arxiv.org/abs/2505.23419>
- benchmark mutation / realistic query shift:
  - <https://arxiv.org/abs/2510.08996>

这些工作当前最值得借鉴的是：

- benchmark 必须可执行、可复查、可更新
- task surface 会影响 agent 表现
- correctness oracle 需要稳定

### 10.3 为什么当前不直接拿 SWE-bench-Live 当 formal 数据集

当前不建议直接拿 SWE-bench-Live 做 formal 主数据集，原因如下：

1. 对象不匹配
   - SWE-bench-Live 的对象是代码修复与 issue resolving
   - 当前赛题对象是多 Agent 协作机制

2. 环境依赖不匹配
   - SWE-bench-Live 依赖每题独立可执行环境与镜像
   - 当前 repo 是 host-first，不以 Docker 为主路径前提

3. correctness oracle 不匹配
   - SWE-bench-Live 主要用代码执行/测试结果判定
   - 当前任务主要看 route/tool/state/memory 机制

### 10.4 未来如何接入 SWE-bench-Live

建议延后，以 support-only 形式接入：

1. 先完成内部 v2 benchmark 收口
2. 再挑选小规模外部 subset
3. 只用于：
   - external support pack
   - correctness-oracle 设计参考
   - benchmark mutation 迁移实验

不建议在当前阶段：

- 直接把 SWE-bench-Live 替换成 formal 主数据集

---

## 11. 实施顺序

### Phase A：冻结旧包

执行：

1. 把当前 pack 明确标注为 `historical_v1`
2. 文档里停止把它们继续称为唯一 formal 主线

退出条件：

- v1/v2 边界写清

### Phase B：写 v2 task contract

执行：

1. 定义 `case_type`
2. 定义 admissible / abstain 规则
3. 按 family-case 重写 expectation schema

退出条件：

- 每个 case 的 correctness contract 可独立复查

### Phase C：先重做三个正式主 pack

优先顺序：

1. `carrier_controlled_v2`
2. `semantic_retention_v2`
3. `memory_reuse_v2`

退出条件：

- 三条正式 headline 都有单一对象

### Phase D：补两个 support pack

执行：

1. `planner_support_v2`
2. `langgraph_native_text_support_v2`

退出条件：

- 支持性问题与正式 claim 分离

### Phase E：最后才讨论外部 benchmark

执行：

1. 评估是否引入 SWE-bench-Live subset
2. 评估是否需要外部 correctness oracle

退出条件：

- 内部 v2 benchmark 已经稳定

---

## 12. 直接执行清单

后续如果按 v2 执行，建议严格按下面顺序推进：

1. 冻结旧 benchmark 包，明确 `historical_v1`
2. 写新的 v2 task schema
3. 重写 expectation 为 case-level contract
4. 先做 `carrier_controlled_v2`
5. 再做 `semantic_retention_v2`
6. 再做 `memory_reuse_v2`
7. 最后补 support-only 的 planner/langgraph native
8. 内部 v2 稳定后，再讨论外部 benchmark 接入

一句话 stopline：

> 先把 benchmark object 设计正确，再去调系统阈值、handoff 文本和路由策略；不要反过来做。
