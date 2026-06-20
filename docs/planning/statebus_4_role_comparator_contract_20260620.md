# StateBus 4-Role Comparator Contract

日期：2026-06-20

适用范围：
- 当前仓库 `/home/qcrs/statebus/project`
- 用于约束后续 `4-role paired comparator` 设计、实现、测试与报告
- 这是 contract doc，不是实现说明，也不是 review 文档

状态：
- 当前版本用于冻结下一阶段主对象
- 未经显式修订，不应边实现边改语义

---

## 1. 目标

本合同要解决的不是“怎么把四个角色都接上 LLM”这么泛的问题，而是一个更窄、更硬的问题：

> 如何基于赛题要求，定义一个**公平、可复现、可归因**的  
> `4-role paired comparator`，  
> 用来正式比较  
> `pure-text carrier`  
> 与  
> `StateBus carrier`
> 在相同多 Agent 任务对象上的表现差异。

本合同服务于两个后续对象：

1. `contest_four_role_carrier_comparison_v1`
   - StateBus 内部 paired comparator
   - 同四角色、同任务、同模型、同评分
   - 只改变 carrier / state-consumption contract

2. `external_pure_text_four_role_baseline_v1`
   - external pure-text comparator
   - 同四角色、同任务、同模型、同评分
   - 不使用 StateBus 内部 typed-state/runtime helper

---

## 2. 为什么需要这份合同

根据赛题原文，系统必须同时满足：

1. 至少 3 个 Agent、至少 3 类角色
2. 支持纯文本协作模式和结构化协议协作模式
3. 在相同任务条件下做可复现实验对比
4. 统计通信开销、时延、非文本状态传递、记忆命中、整体性能提升
5. 验证共享记忆复用

当前仓库已经证明了很多机制存在，但还没有形成一个足够强的 `4-role paired comparator`。目前最主要的缺口是：

- 现有 `text_whole_lane` 是 StateBus runtime 内部 comparator，不是 external traditional pure-text baseline
- 当前 formal headline 主路径不是四个 semantic LLM agents
- 当前缺少 role-level token/latency accounting
- 当前缺少 text/protocol 双方对称的 role I/O contract
- 当前缺少 fail-closed fairness gate

所以这份合同的定位非常明确：

> 在任何 4-LLM 实现开始之前，先把比较规则冻结。

---

## 3. 赛题约束映射

本节只从赛题要求出发，不按当前实现习惯出发。

### 3.1 多 Agent 要求

赛题要求：

- 不少于 3 个 Agent 协同运行
- 覆盖规划、检索、执行、总结等至少 3 类角色

本合同固定四角色：

1. `Planner`
2. `Retriever`
3. `Executor`
4. `Summarizer`

任何 comparator object 都必须显式保留这四角色，不能在 paired compare 中把它们折叠成：

- 单一 mega-prompt agent
- 隐式 helper function
- manager-only hierarchy

### 3.2 双模式要求

赛题要求：

- 同时支持纯文本协作模式和结构化协议协作模式
- 在相同任务条件下做可复现实验对比

本合同对应为两条 lane：

1. `text carrier lane`
2. `statebus carrier lane`

两条 lane 必须：

- 同任务对象
- 同四角色图
- 同模型
- 同工具能力集合
- 同 corpus evidence universe
- 同 scoring contract
- 同 repeat policy

只允许以下变量不同：

- agent 间如何表示和传递协作信息
- role 如何消费 typed state / textual handoff
- StateBus lane 是否使用显式控制面 / 状态面 / 记忆面

### 3.3 非文本状态传递要求

赛题要求：

- 实现 embedding / 语义向量 / 隐藏状态特征 / 其他中间表示的直接交换
- 必须说明生成方式、传递方式、接收方式和后续使用方式

本合同要求：

- `statebus carrier lane` 必须显式使用 typed state
- `text carrier lane` 必须显式禁止 typed state
- typed state 的生产、传递、消费、后续使用都必须进入 telemetry

### 3.4 共享记忆要求

赛题要求：

- 保存统一记忆单元
- 支持检索
- 支持后续任务复用

本合同要求：

- 冷启动 / 热启动 / assist / replay 必须分层记录
- 不允许把普通上下文延续直接读成记忆复用
- 未出现非零 `reuse_gain` 或 `skipped_step_count` 时，不得升格为强记忆收益主张

### 3.5 性能要求

赛题要求：

- 消息次数
- token 或字符开销
- 非文本状态传递次数及数据规模
- 单任务总耗时
- 共享记忆命中率
- 整体性能提升

本合同要求：

- aggregate metrics 不够，必须加 role-level metrics
- 只要 4 角色都可能调 LLM，就必须按角色拆 usage 和 latency

---

## 4. 对象定义

### 4.1 主对象名称

当前下一阶段主对象固定命名为：

```text
4-role paired comparator
```

不使用下列表述作为当前主对象名：

- `4-LLM architecture upgrade`
- `new headline`
- `open-world multi-agent refactor`

原因：

- 当前阶段目标是 comparator repair
- 不是证明新架构已经成立
- 不是证明开放环境已经值得并入主线

### 4.2 阶段定位

当前阶段只回答一个问题：

> 在固定四角色图下，  
> `text carrier` 和 `StateBus carrier` 的差异  
> 是否能在公平 comparator 上被测出来？

当前阶段**不**回答：

- open-world 是否更优
- freer interaction 是否更自然
- CodeAct 是否该并入
- openEuler VM 上的最终交付细节

---

## 5. 角色图冻结

### 5.1 固定角色

所有 paired comparator 运行都必须显式经过以下四角色：

1. `Planner`
2. `Retriever`
3. `Executor`
4. `Summarizer`

### 5.2 固定顺序

默认图固定为：

```text
Planner -> Retriever -> Executor -> Summarizer
```

可选插入附加验证节点，但当前 comparator 主线不允许因为 lane 不同而改变主图拓扑。

### 5.3 允许的最小图扩展

允许保留以下扩展，但必须在两条 lane 中对称：

- `validate` 子步骤
- `repair` 重试
- `memory lookup` side-effect

不允许：

- text lane 是 4 角色，protocol lane 是 5 角色
- 一条 lane 有 manager agent，另一条没有
- 一条 lane 把中间角色折叠成 mega prompt

---

## 6. 角色输入输出合同

本节是本合同的核心。

### 6.1 总原则

每个角色都必须有：

1. 明确允许输入
2. 明确禁止输入
3. 明确输出 schema
4. 明确输出 downstream contract

否则 comparator 无法归因。

### 6.2 Planner

#### 允许输入

- `task_id`
- `goal`
- `query`
- `summary_contract`
- `public task constraints`
- 可选的 memory summary abstraction
- role capability summary

#### 禁止输入

- `primary_expected_route`
- `primary_expected_tool`
- `acceptable_routes`
- `acceptable_tools`
- 任何 oracle correctness fields
- runtime hidden route hints

#### 输出

必须输出：

- retrieval objective
- ambiguity checklist
- expected output contract for retriever
- downstream target role

不要求 planner 直接输出最终 tool 决定。

### 6.3 Retriever

#### 允许输入

- planner handoff
- ranked corpus docs
- bounded memory hit abstraction
- public tool catalog summary

#### 禁止输入

- correctness oracle
- hidden route/tool answer
- statebus-only helper fields that text lane拿不到

#### 输出

必须输出：

- selected evidence subset
- evidence claims
- route hypotheses
- candidate tools
- uncertainty / missing information
- downstream target role

### 6.4 Executor

#### 允许输入

- retriever handoff
- bounded evidence projection
- tool catalog
- action contract

#### 禁止输入

- hidden lexical fallback result
- hidden deterministic tool choice
- hidden “best route” from runtime

#### 输出

必须输出：

- selected route
- selected tool
- selection rationale
- abstain/proceed decision
- tool artifact digest
- validation notes
- downstream target role

### 6.5 Summarizer

#### 允许输入

- executor handoff
- bounded evidence projection
- bounded tool artifact projection
- memory write contract

#### 禁止输入

- full oracle correctness contract
- lane-specific hidden support fields

#### 输出

必须输出：

- final summary
- confidence
- memory candidate
- reusable steps abstraction

---

## 7. Carrier 合同

### 7.1 Text Carrier Lane

定义：

- agent 间协作媒介只能是字符串消息
- 可以是 plain text
- 可以是 JSON-with-text-values
- 但本质必须是 text-only handoff

#### 强制要求

- 不允许 `StateRef`
- 不允许 typed packet
- 不允许 structured state handle
- 不允许 hidden helper side-channel

#### 可见性要求

下游 role 只能看到：

- 上游 role 明确写入消息的内容
- 它被允许访问的本地资源

#### 明确禁止

- 将全任务上下文直接拼成 mega prompt，再伪装成四角色系统
- text lane 额外看到 protocol lane 不可见的全局中间态

### 7.2 StateBus Carrier Lane

定义：

- 控制面使用结构化协议
- 状态面使用 typed state / refs
- 记忆面使用显式 store / retrieval

#### 强制要求

- 下游 role 可以消费 typed state
- 但消费必须通过显式访问合同
- raw typed state 不得无界 dump 回文本 prompt

#### 明确禁止

- 把整包 typed packet 全量文本化并塞进每个 LLM prompt
- 用 hidden helper 替代 role-level semantic decision

### 7.3 Single Variable Rule

paired compare 中唯一允许变化的主变量是：

```text
carrier / state-consumption contract
```

不是：

- 角色数不同
- prompt 目标不同
- 工具能力不同
- 记忆可见性不同
- scoring 标准不同

---

## 8. Protocol Lane 字段访问合同

这部分是 reviewer 明确指出的缺口，必须冻结。

### 8.1 字段访问原则

任何 protocol lane role 读到的 typed information 必须满足：

1. 可枚举
2. 可记录
3. 有 token budget
4. 能映射成明确的 downstream purpose

### 8.2 `LLM_CONTEXT_SLICE`

引入一个合同级概念：

```text
LLM_CONTEXT_SLICE
```

定义：

> 某个 producer 为某个指定下游 LLM role 准备的、受预算约束的局部上下文投影。

它用于替代：

- 全量 typed packet 文本化
- 全量 raw evidence 再发一次

### 8.3 `LLM_CONTEXT_SLICE` 最小字段

必须至少包含：

- `source_role`
- `target_role`
- `slice_kind`
- `budget_class`
- `included_fields`
- `omitted_fields`
- `text_projection`
- `backing_state_refs`

### 8.4 必须记录的访问日志

每次 role 执行必须记录：

- 读取了哪些 typed state kind
- 读取了哪些字段
- 生成了几个 `LLM_CONTEXT_SLICE`
- 每个 slice 的 token/char 大小

---

## 9. External Pure-Text Baseline 合同

### 9.1 外部 baseline 的地位

它不是 audit-only smoke。

它在本阶段应被定义为：

```text
formal comparator
```

### 9.2 baseline 必须满足

1. 同四角色图
2. 同任务对象
3. 同模型
4. 同工具集合
5. 同 corpus evidence universe
6. 同 scoring contract
7. text-only inter-agent handoff

### 9.3 baseline 严禁

- import StateBus runtime internals as hidden helpers
- import StateBus typed-state carriers
- lexical fallback silently correcting LLM outputs
- use correctness oracle during execution

### 9.4 baseline 允许共享

- task data
- corpus files
- tool catalog as plain data
- scoring logic as independently re-implemented judge
- same LLM infra client

---

## 10. Benchmark Object 合同

当前 paired comparator 不能直接沿用旧 headline object 而不加约束。

### 10.1 新对象必须强制四角色都“有事可做”

任务对象必须让：

- planner 需要做局部任务 framing
- retriever 需要做 evidence selection
- executor 需要做 route/tool/action selection
- summarizer 需要做 synthesis

### 10.2 新对象必须避免“单 prompt 就能吃完”

如果任务允许一个强模型直接看全局上下文然后产出正确答案，则：

- carrier effect会被淹没
- role graph变成假图

所以 paired object 必须尽量包含：

- role-local uncertainty
- support-sensitive evidence
- action-level distinction
- downstream dependency

### 10.3 当前 frozen headline 的地位

`contest_honest_headline_v1` 继续保留为：

- 历史 frozen headline object
- 当前 formal reference object

但它不自动等于新的 4-role paired comparator object。

---

## 11. Scoring 合同

### 11.1 必须保留的现有维度

至少保留：

- `exact_match_rate`
- `admissible_match_rate`
- route/tool correctness where applicable
- support/evidence correctness where applicable

### 11.2 必须新增的维度

必须新增：

- role-output validity
- support-aware correctness
- disallowed-field leakage detection
- route-support consistency
- tool-support consistency

### 11.3 明确禁止的宽松读法

不允许：

- 只看 final answer 像不像
- 明显用错 route/tool 但只要 summary 看起来合理就算通过
- 靠 hidden oracle 字段得到正确答案仍算 exact

### 11.4 admissible 的地位

`admissible` 继续保留，但不能代替 superiority judgment。

新 comparator 中必须明确区分：

- correctness contract
- mechanism contract
- superiority claim

---

## 12. Memory 与 Replay 合同

### 12.1 memory contract 必须分层

至少区分：

- cold start
- assist only
- validated replay
- exact replay

### 12.2 只有出现显式证据时才能升格

若未出现：

- `reuse_gain > 0`
- `skipped_step_count > 0`

则不得把结果升格为强记忆复用收益。

### 12.3 paired comparator 中 memory 的公平性

两条 lane 必须回答：

- 哪些 role 可读 memory
- 哪些 role 可写 memory
- 记忆以什么形式暴露给 role
- 是否允许 transcript memory
- 是否允许 typed replay artifact

### 12.4 replay 计数规则

必须明确：

- replayed output 是否计入正式 API evidence
- replay 是否计为减少 LLM 调用
- replay 命中是否单独记 role-level latency benefit

---

## 13. Telemetry 合同

### 13.1 角色级 usage 必须记录

至少包括：

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

### 13.2 carrier 级 telemetry

必须记录：

- `handoff_message_count`
- `handoff_text_bytes`
- `state_transfer_count`
- `state_transfer_wire_bytes`
- `state_transfer_payload_bytes`
- `typed_state_kind_count`

### 13.3 memory telemetry

必须记录：

- `memory_lookup_count`
- `memory_hit_count`
- `memory_write_count`
- `memory_hit_rate`
- `reuse_gain`
- `skipped_step_count`

### 13.4 trace 要求

每个 task 运行必须能追溯：

- 每个 role 收到了什么类型的输入
- 每个 role 输出了什么类型的消息或 state
- 每次 fairness gate 是否通过

---

## 14. Fairness Gate

这是本合同最重要的执行门。

### 14.1 gate 必须 fail-closed

任何关键公平性条件不满足时：

- 直接判该比较无效
- 不允许“先跑再解释”

### 14.2 必查项

运行前至少检查：

1. 同 task object
2. 同 role graph
3. 同 role count
4. 同 LLM model family
5. 同主要 sampling params
6. 同 corpus availability
7. 同 tool availability
8. 同 scoring contract
9. 同 repeat policy
10. text lane 无 typed-state leakage
11. protocol lane 无 unbounded packet dump
12. no hidden deterministic helper advantage

### 14.3 建议的 gate 分类

- `object_parity_gate`
- `role_graph_gate`
- `carrier_purity_gate`
- `oracle_leakage_gate`
- `role_metric_presence_gate`
- `scoring_contract_gate`
- `serialized_api_gate`

---

## 15. Repeat 与 API 证据合同

### 15.1 正式 latency 证据必须串行

根据当前 repo 边界：

- API latency claim 只接受 serialized benchmark reruns

### 15.2 最小实施顺序

实现后必须按以下顺序验证：

1. contract freeze
2. deterministic/local smoke object
3. fairness gate pass
4. API repeat=1 smoke
5. API repeat=3 serialized
6. 如有必要再决定 repeat=10

### 15.3 不允许的顺序

不允许：

- contract 未冻结就直接跑 API headline
- fairness gate 未实现就直接比较 token
- repeat=1 就写 superiority narrative

---

## 16. 开放环境边界

### 16.1 当前结论

open-world / freer interaction **不进入当前主线**。

### 16.2 原因

当前主问题仍是：

- comparator contract 未冻结
- fairness gate 未建立
- role-level metrics 未齐
- scoring/memory/replay 未冻结

开放环境会引入新的 uncontrolled variable，使归因更差。

### 16.3 进入前提

只有在以下条件都成立后，开放环境才可作为单独 phase 进入：

1. fixed 4-role comparator 已稳定
2. role-level token/latency 已齐
3. fairness gate 已通过
4. external pure-text comparator 已成立
5. scoring contract 已可审计

---

## 17. 接受标准

在任何实现工作开始前，本合同的接受标准是：

1. 本文档被视为下一阶段唯一主合同
2. 后续实现不得绕开本文档核心定义
3. 若实现中发现合同缺口，先补合同，再改代码

在任何 paired comparator API 结果被读成正式证据前，至少要满足：

1. object 已冻结
2. role I/O schema 已冻结
3. text/protocol carrier contract 已实现
4. external baseline contract 已实现
5. role-level telemetry 已实现
6. fairness gate 已实现并通过
7. scoring contract 已实现
8. serialized API run 已落盘

---

## 18. 已知失败模式

后续实现中需要优先防的失败模式：

1. 四角色名义存在，但实际是 mega prompt
2. text lane 偷看 protocol lane 才有的信息
3. protocol lane 把 typed packet 全量文本化
4. deterministic helper 继续决定最终 route/tool
5. baseline 用 lexical fallback 暗中纠错
6. 只统计 aggregate token，不统计 role-level token
7. 把 assist 误读成 replay gain
8. API latency 用非串行结果叙述
9. admissible 被误读成 superiority
10. open-world 提前并入，破坏归因

---

## 19. 当前唯一下一步

本合同生效后，当前唯一下一步固定为：

> 先基于本合同设计一个  
> deterministic/local paired smoke object  
> 再决定任何 4-role 实现。

这一步的目标不是“证明 4-LLM 已经有效”，而是先回答两个更小的问题：

1. 本合同定义的 `paired comparator` 能否被最小实现出来；
2. text lane 与 statebus lane 是否真的能在同对象、同角色、同评分下被公平执行。

不是：

- 先全面改 4 个 agent
- 先跑 API 找正结果
- 先把 open-world 加进来

---

## 20. 相关文档

上游约束：

- `docs/reference/题目.md`
- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`

相关分析：

- `docs/analysis/statebus_four_llm_agent_refactor_design_20260620.md`
- `docs/analysis/statebus_four_llm_refactor_independent_review_20260620.md`
- `docs/analysis/statebus_external_pure_text_baseline_contract_20260620.md`

当前 frozen headline：

- `docs/reports/final_claim_matrix_and_freeze_20260618.md`
