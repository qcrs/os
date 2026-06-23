# StateBus 总览：可信结果、任务设计、系统流与 `text` 对比

日期：`2026-06-23`

适用范围：

- 当前仓库：`/home/qcrs/statebus/project`
- 当前实现分支：`feat/taskset-mainline-split`
- 当前 active communication headline：`superiority_comm_v1`

这份文档给第一次接触项目的人使用。它不试图覆盖所有历史路线，而是先把四件事讲清楚：

1. 当前最新可信结果是什么
2. 系统主流程怎么跑
3. 任务是怎么构造、怎么判对错的
4. `text` 和 StateBus 到底是怎么比较的

阅读边界：

- 本文优先解释当前正式读法，不展开历史 hotfix 因果链
- 本文不把 support surface 写成 headline closure
- 本文不把当前结果误写成 overall superiority
- 精确冻结口径仍以 `docs/reports/current_task_results_overview_20260622.md` 为准

---

## 1. 先看当前可信结果

当前最值得先看的不是所有历史 run，而是三组正式对象：

1. communication mainline  
   `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/benchmark_report.md`
2. typed-state support  
   `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/benchmark_report.md`  
   `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/benchmark_report.md`
3. memory secondary verdict  
   `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_report.md`

### 1.1 communication：当前 active headline

communication 当前唯一 active headline 是 `superiority_comm_v1`。它只回答三件事：

- communication 开销是否下降
- task 总时延是否同向改善
- 质量底线是否守住

当前 authoritative artifact 给出的正式读法是：

- `Communication gate = pass`
- `Formal stability gate = not_yet`

这两个 gate 不是一回事：

- `Communication gate = pass`：对象级 communication 证据已经从 `withheld` 释放
- `Formal stability gate = not_yet`：更高一级的 repeat-depth / stability 结论还没有释放

当前最重要的 headline 数字如下。

| 指标 | text | protocol | delta (`protocol - text`) |
| --- | ---: | ---: | ---: |
| `control_bytes` | `12439.64` | `11000.67` | `-1438.97` |
| `llm_total_tokens` | `1363.33` | `1193.83` | `-169.50` |
| `task_ms` | `4429.63` | `3968.14` | `-461.49` |

当前质量指标如下。

| 指标 | 数值 |
| --- | ---: |
| `route_exact_rate` | `1.00` |
| `tool_exact_rate` | `0.75` |
| `exact_match_rate` | `0.75` |
| `admissible_match_rate` | `1.00` |
| `wrong_family_rate` | `0.00` |

这组结果说明：

1. 当前 `protocol` 相比 `text`，communication 开销更低
2. 当前 `protocol` 相比 `text`，总任务耗时更低
3. 当前质量底线稳定，没有出现错误 family 扩散

当前还要补三条边界：

- Planner 稳定性现在是 `0.99` one-shot valid rate、`1` 次 repair；它已不是主 residual
- 当前 actual parity 仍有两点 diagnostic divergence：`rr-auth-distractor` 与 `rr-billing-clean`
- 这两点是诊断面，不是 headline blocker

### 1.2 typed-state：当前已经能证明什么

typed-state 当前不是主 headline，而是 formal-secondary support。它主要靠两组对象支撑。

#### `typed_state_mechanism_v3`

这个对象回答的问题很窄：

> 在同样的 protocol 语义下，最小 typed-state packet 是否真的比自然 handoff text 更紧凑、更直接，而且不破坏质量？

它固定：

- `mode = protocol`
- `runtime_reuse_contract = reuse_disabled`
- 同一个 task object

只比较：

- `natural_handoff_text`
- `state_packet_minimal`

当前关键结果如下。

| handoff_strategy | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: | ---: |
| `natural_handoff_text` | `1669.25` | `0.00` | `362.50` | `2114.44` |
| `state_packet_minimal` | `995.00` | `1249.75` | `359.00` | `1677.56` |
| `delta` | `-674.25` | `+1249.75` | `-3.50` | `-436.88` |

同时质量指标保持：

- `route_exact_rate = 1.00`
- `tool_exact_rate = 1.00`
- `exact_match_rate = 1.00`
- `wrong_family_rate = 0.00`

这组结果说明：

1. 最小 typed-state packet 显著减少了文本 handoff 体积
2. 总 token 没有上升
3. 总耗时更低
4. 质量不退化

#### `typed_state_consumer_sensitivity_v3`

这个对象回答的问题也很窄：

> minimal packet 是否真的被消费了，而不是只是“形式上存在”？

它通过 destructive negative control 证明因果性。当前最重要的结果是：

- `missing_decision_failure_rate = 1.00`
- `wrong_decision_mistool_rate = 1.00`
- `unexpected_task_failure_count = 0`

还要注意一个经常被写错的事实：

- 当前 authoritative refresh 是 `40` 个 protocol tasks
- 覆盖 `5` 个 family
- 同时包含 full-rich helper visibility rows 和 minimal destructive-control rows

这说明：

1. 如果把 `EXECUTOR_DECISION_PACKET` 拿掉，系统会按预期失败
2. 如果把最小 packet 中的 route/tool 改错，系统会按预期 misfire
3. rich helper object 的可见性变化，不应被误读成 mainline consumer necessity

所以 typed-state 这条线当前可以正式支持：

- minimal packet 被真实生产、传递、消费

但它不能替代 communication headline。

### 1.3 memory：当前 memory 结果到底算什么

memory 当前的正式对象是 `superiority_memory_v1`。它的角色不是 communication headline，而是 `required secondary verdict`。

当前 authoritative artifact 显示：

- `Memory replay gate = pass`
- `Formal stability gate = not_yet`

当前关键指标如下。

| mode | skipped_step_count | reuse_gain | validated_reuse_task_count | task_ms | exact_match_rate | wrong_family_rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `text` | `5.00` | `0.12` | `5.00` | `120120.36` | `0.80` | `0.00` |
| `protocol` | `5.00` | `0.12` | `5.00` | `116079.67` | `0.80` | `0.00` |

Replay effect gate 同时显示：

- `Expected reusable rows = 30`
- `Reuse-mode matched rows = 30`
- `Effect-matched rows = 30`
- `Positive reuse-gain row count = 30`

这说明当前 memory 线已经能正式写成：

- runtime replay effect established
- exact-replay-backed effect established

但仍然不能正式写成：

- `memory superiority established`
- `overall superiority established`

### 1.4 先把一个最容易误解的问题说清楚：到底哪些角色用了 LLM

当前实现里，四个角色都可能进入 role-specific LLM contract：

| 角色 | 当前是否使用 LLM | 说明 |
| --- | --- | --- |
| `Planner` | 是 | 直接用 LLM 生成或修复 `Plan` |
| `Retriever` | 是 | 先做检索、候选生成、特征生产，再进入较窄的 retriever-role semantic selection |
| `Executor` | 是 | 先消费 handoff / packet，再进入较窄的 executor-role semantic selection，然后才执行工具 |
| `Summarizer` | 是 | 用 LLM 生成总结与 `MemoryCommit` |

当前 report 里只单独拆出了：

- `planner_total_tokens`
- `summarizer_total_tokens`

没有单独给出：

- `retriever_total_tokens`
- `executor_total_tokens`

因此现在能诚实说的是：

- `llm_total_tokens` 是四角色总和
- 其中已明确拆账的是 planner 和 summarizer
- 不能假装当前报告已经把四角色 token 全部细分完毕

---

## 2. 系统主流程到底怎么跑

如果只用一句话概括当前系统主流程，就是：

> `Task -> Planner -> Retriever -> Executor -> Summarizer -> Scorer / Memory`

更具体一点：

```text
SampleTask
  -> Planner
      生成 Plan / PlanStep / semantic_role
  -> Retriever
      检索语料，构造候选，生成 typed state
  -> Executor
      消费 text handoff 或 typed packet，做 route/tool 决策并执行工具
  -> Summarizer
      汇总证据和动作结果，产出最终答案与 MemoryCommit
  -> eval/runner scorer
      按 case-level contract 判对错，聚合指标并生成 report
```

### 2.1 四个角色分别做什么

| 角色 | 主要输入 | 主要输出 | 当前真实工作 |
| --- | --- | --- | --- |
| `Planner`（规划器） | `query`、能力表、可选记忆命中 | `Plan`、`PlanStep[]` | 把任务编译成 `retrieve / validate / execute / summarize` 语义步骤 |
| `Retriever`（检索器） | `query`、`tags`、语料库、可选 `MemoryHit` | `DENSE_EVIDENCE`、`FEATURE_BUNDLE`、`TOOL_CANDIDATE_SET`、主线路径下的执行决策信息 | 先检索和生成候选，再做较窄的语义选择 |
| `Executor`（执行器） | `PlanStep`、handoff 文本或 typed packet、工具参数 | `StepResult`、`TOOL_ARTIFACT`、必要时 `VALIDATION_GATE_PACKET` | 读取 handoff，做 route/tool 决策，调用真实工具 |
| `Summarizer`（总结器） | evidence、执行结果、`summary_hint`、可选记忆上下文 | 最终答案、`MemoryCommit` | 汇总任务结果，并把可复用信息写回记忆 |

### 2.2 control plane、state plane、memory plane 是什么

当前系统最稳定的解释方式是三平面：

| 平面 | 传什么 | 典型对象 | 为什么重要 |
| --- | --- | --- | --- |
| control plane（控制面） | 谁做什么、依赖什么 | `Plan`、`PlanStep`、`StepResult` | 控制面传动作骨架，不传大块负载 |
| state plane（状态面） | 实际中间数据 | `StateRef`、`DENSE_EVIDENCE`、`EXECUTOR_DECISION_PACKET` | 非文本状态通过引用传递，而不是内联成长文本 |
| memory plane（记忆面） | 历史经验与回放线索 | `MemoryHit`、`MemoryCommit` | 支撑跨任务复用和 replay gate |

### 2.3 memory 不应被单独看成外挂模块

memory 是主流程的一部分，不是额外外挂。

它在三个位置进入系统：

1. Retriever 查询 `MemoryStore`，获得 `MemoryHit`
2. Orchestrator 在 retrieve 和 execute 之间做 replay gate，判断是否允许 `skip_execute`
3. Summarizer 写出 `MemoryCommit`，供后续任务复用

所以 memory 不是独立平行主线，而是和结构化传递、中间状态、任务编排一起工作的。

### 2.4 当前最重要的中间对象是什么

当前最关键的不是“有多少消息类型”，而是下面几个对象：

| 对象 | 作用 | 为什么重要 |
| --- | --- | --- |
| `SampleTask` | 带合同的任务对象 | benchmark 不是一句 prompt，而是带评分合同的 task |
| `Plan` / `PlanStep` | 结构化执行计划 | 明确谁做什么、依赖什么 |
| `StateRef` | 状态引用 | 控制面只传引用，重状态不内联进消息体 |
| `DENSE_EVIDENCE` | 紧凑证据状态 | 供下游消费的主证据对象 |
| `EXECUTOR_DECISION_PACKET` | 最小执行决策包 | 当前 non-text state transfer 的核心落点 |
| `MemoryHit` / `MemoryCommit` | 记忆读写对象 | 支撑跨任务复用 |

---

## 3. 任务是怎么构造的，怎么判对错

### 3.1 任务不是“一句话问题”，而是“带合同的对象”

`SampleTask` 不是一条自然语言问句。它至少同时包含四类信息：

1. 面向 Agent 的内容  
   `goal`、`query`、`summary_hint`、`tags`
2. 面向检索的内容  
   `corpus_doc_ids`、`corpus_path`
3. 面向评测的合同  
   `case_id`、`case_type`、`primary_expected_route`、`primary_expected_tool`、`acceptable_routes`、`acceptable_tools`
4. 面向变量控制的内容  
   `benchmark_lane`、`transfer_strategy`、`handoff_profile`、`runtime_reuse_contract`、`plan_source`

因此正式 benchmark 不是“问系统一个问题，看它怎么答”，而是：

> 在固定任务对象、固定语料、固定评分合同下，只改变被明确声明的变量。

### 3.2 为什么说任务是连续任务链，不是散题

StateBus 的很多正式 pack 都不是随机拼出来的独立题，而是按任务链构造的。

例如历史内部受控对象 `contest_dual_mode_controlled_v3`：

- 共 `40` 个 task
- `5` 条任务链
- 每条链 `8` 个 task

五条链分别是：

- `auth_rotation_chain`
- `billing_queue_chain`
- `checkout_release_chain`
- `deployment_config_chain`
- `inventory_rollout_chain`

每条链内部围绕同一个任务主题，再覆盖不同复杂度：

- `clean`
- `distractor`
- `ambiguous`
- `reusable`

所以它不是“20 个无关任务堆在一起”，而是“围绕同一类问题构造的一组对照任务”。

### 3.3 一个真实 family 例子：`checkout_release_chain`

这个 family 的核心问题是：

> 某次 checkout 发布后，系统出现 SQL wait、连接池等待、订单确认变慢等现象。

围绕这个 family，会出现不同 case：

- `clean`：验证标准路径能否稳定命中正确 family / route / tool
- `distractor`：给出强竞争假设，测试系统会不会被带偏
- `ambiguous`：证据不完全单向时，测试系统能否在允许边界内做出可接受选择
- `reusable`：存在前序任务经验时，测试系统能否复用，而不是从头执行

### 3.4 系统到底怎么判“对”与“错”

当前 scorer 不是靠“看起来像不像”打分，而是按 case-level contract 判定。

每个 task 都会显式声明：

- `primary_expected_route`
- `primary_expected_tool`
- `acceptable_routes`
- `acceptable_tools`
- `disallowed_families`
- `abstention_allowed`

因此，当前这些聚合指标都有明确含义：

| 指标 | 它在检查什么 |
| --- | --- |
| `route_exact_rate` | route 是否与 primary expected route 完全一致 |
| `tool_exact_rate` | tool 是否与 primary expected tool 完全一致 |
| `exact_match_rate` | route 和 tool 是否同时完全一致 |
| `admissible_match_rate` | 结果是否仍然落在合同允许的 route/tool/abstention 边界内 |
| `wrong_family_rate` | 是否落入明确禁止的 family |

这点很重要：

- `exact_match_rate` 不是唯一正确性标准
- `admissible_match_rate` 也不是“随便差不多就算对”
- 它表示结果仍然在 task 合同允许的边界内

### 3.5 为什么 negative control 很重要

`typed_state_consumer_sensitivity_v3` 是最典型的 negative control 设计：

- 正常 baseline：保留 `EXECUTOR_DECISION_PACKET`，应当成功
- 缺包：拿掉 `EXECUTOR_DECISION_PACKET`，应当 failure
- 错包：把 route/tool 改错，应当 misfire

只有正控和负控都按预期触发，才能证明：

- typed-state 不是“代码里有个字段”
- 而是被 Executor 真实消费了

---

## 4. `text` 和 StateBus 到底是怎么比较的

这是整个项目最容易被误读的地方。

### 4.1 当前 active communication headline 比较的是谁

当前 `superiority_comm_v1` 比较的是：

- `text_whole_lane`
- `state_packet_minimal`

它**不是**在比较：

- 外部传统纯文本系统 vs StateBus
- strict pure text lane vs protocol
- 一个纯手工 microbench vs 一个完整系统

也就是说，当前 communication headline 的 `text` baseline 是：

- StateBus runtime 内部的 whole-lane 自然语言 handoff 路径

它仍然运行在同一个 runtime、同一个 scorer、同一套 task object 下。

### 4.2 这是不是只换了一层传输壳

不是。

更准确的说法是：

> 在固定 task object、语料、summary contract 和 scoring contract 的前提下，比较两种 mode surface 下的整体协作行为。

当前 active communication headline 下：

- `plan_source = llm`
- `Retriever` 也会进入 role-specific LLM contract
- `Executor` 也会进入 role-specific LLM contract

所以当前 headline 不是“所有角色内部实现完全不变，只换一层 carrier 壳”的纯微基准。

如果只想看更窄的 handoff 对照，应该读：

- `typed_state_mechanism_v3`

### 4.3 两条路径里，信息是怎么流动的

```text
用户任务
  -> Planner
  -> Retriever
       -> text_whole_lane: 自然语言 whole-lane handoff
       -> state_packet_minimal: DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET
  -> Executor
  -> Summarizer
  -> 最终答案 + MemoryCommit
```

关键区别集中在 `Retriever -> Executor` 这一段。

#### `text_whole_lane`

上游先把中间语义写成自然语言 handoff。  
下游再从自然语言里恢复：

- route
- tool
- evidence 关系

也就是要经历一轮“文本化再恢复”。

#### `state_packet_minimal`

上游把关键执行语义压成结构化对象：

- `DENSE_EVIDENCE`
- `EXECUTOR_DECISION_PACKET`

它们写入 `StatePool`，控制面只传 `StateRef`。  
下游通过 `StateRef` 本地读取结构化 packet，直接消费字段。

### 4.4 什么叫“非文本状态传递”

当前仓库里的“非文本状态传递”不等于“完全没有文本”。

它更准确的意思是：

- 中间状态不再只靠自然语言长段落表达
- 上游会把关键决策压成结构化对象
- 下游会通过 `StateRef` 读取状态池中的 typed state

当前最关键的落点不是抽象的“embedding 直传”，而是：

- `EXECUTOR_DECISION_PACKET`

它至少承载：

- `route`
- `tool_name`
- `route_confidence`
- `retrieved_doc_ids`
- `matched_signals`

这才是当前 non-text state transfer 最实的实现。

### 4.5 为什么说这种比较是公平的

以当前 communication mainline 为例，保持不变的有：

1. task theme
2. query
3. corpus scope
4. summary contract
5. scoring contract
6. `plan_source = llm`

改变的是：

- `mode`
- `transfer_strategy`
- `handoff_profile`

因此当前 communication headline 的结论可以读成：

> 在固定同一类任务、同一语料和同一评分合同下，`state_packet_minimal` 相比 `text_whole_lane`，communication 开销更低，而且当前 headline pack 下总 task 时延也更低。

这和“换了一套任务再比较”完全不是一回事。

---

## 5. 现在能说什么，不能说什么

### 5.1 现在能正式说什么

- `superiority_comm_v1` 已经释放 `Communication gate = pass`
- 当前 authoritative artifact 下，`protocol` 相比 `text` 的 `control_bytes`、`llm_total_tokens`、`task_ms` 都更低
- quality floor 稳定：`wrong_family_rate = 0.00`，`admissible_match_rate = 1.00`
- typed-state 机制与 consumer sensitivity 已作为 formal-secondary support 成立
- memory replay effect 已作为 required secondary verdict 成立

### 5.2 现在不能正式说什么

- `formal stability pass`
- `repeat=10 closure`
- `overall superiority`
- `memory superiority`
- `text_whole_lane = external pure-text baseline`
- `typed-state support = communication headline`

---

## 6. 如果你接下来继续读，按这个顺序

1. 先读 [`../reader_guide/01_current_trusted_results_and_boundaries.md`](../reader_guide/01_current_trusted_results_and_boundaries.md)
2. 想看系统内部模块，再读 [`../reader_guide/03_system_architecture_and_dataflow_explainer.md`](../reader_guide/03_system_architecture_and_dataflow_explainer.md)
3. 想看 task / family / case 和 walkthrough，再读 [`../reader_guide/04_task_and_benchmark_design_with_walkthrough.md`](../reader_guide/04_task_and_benchmark_design_with_walkthrough.md)
4. 想只看比较方法，再读 [`../reader_guide/05_text_vs_statebus_comparison_methodology.md`](../reader_guide/05_text_vs_statebus_comparison_methodology.md)
5. 想只看结果边界，再读 [`../reader_guide/06_result_readout_and_claim_boundary.md`](../reader_guide/06_result_readout_and_claim_boundary.md)

如果你只记住一句话，可以记这句：

> 当前最可信的主结论是：在当前 active communication headline `superiority_comm_v1` 下，StateBus 的 `protocol` 路径比内部 `text_whole_lane` 对照路径更省 communication 开销，并在不破坏质量底线的前提下获得了当前 headline 对象下更低的总任务耗时；typed-state 和 memory 现在是正式二级支撑，不是 headline closure。
