# `text` 与 `StateBus` 对比方法说明

本文档是实验可信性的核心文档。它必须回答：

1. `text` 到底是什么。
2. `StateBus` 到底是什么。
3. 它们如何被严格比较。
4. 为什么这不是换题比较。

---

## 1. 比较对象先定义清楚

### 1.1 当前 communication headline 比较的是谁和谁

当前 active communication headline（`superiority_comm_v1`）比较的是：

- **`text_whole_lane`**（自然语言全通道）：StateBus runtime 内部的自然语言 text lane。Agent 间通过自然语言文本传递 handoff 信息（完整的 evidence 文本、route/tool candidate 描述等嵌入在文本消息中）。Executor 需要从自然语言中恢复 route/tool 决策信息。

- **`state_packet_minimal`**（状态包最小路径）：StateBus runtime 的 protocol lane。Agent 间通过 Protobuf 控制帧传递动作语义，通过 StateRef 指针引用 mmap 中的 typed state（`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 等 msgpack 序列化对象）。Executor 直接消费结构化决策。

注：历史 frozen formal headline（`contest_honest_headline_v1`）也使用 `text_whole_lane` vs `state_packet_minimal` 的对比框架，但当前 active headline 已切到 `superiority_comm_v1`。下文中如果引用 frozen headline 的精确字节采样数字，只能把它们当成**机制示意**，不能把它们当成当前 comm authoritative 的 headline 均值。

### 1.2 为什么要先定义 lane / mode / transfer surface

不同 pack 可能使用不同的 text 定义和 protocol 定义。例如：

| 场景 | text 的正式定义 | 出处 |
|---|---|---|
| frozen headline | `text_whole_lane`（自然语言全通道） | `contest_honest_headline_v1` |
| 内部受控对照 | `text_strict_pure_lane`（严格纯文本通道） | `contest_dual_mode_controlled_v3` |
| typed-state 机制验证 | `natural_handoff_text`（自然交接文本） | `typed_state_mechanism_v3` |

**不先定义清楚就会把不同 pack 的 text definition 混为一谈**。

---

## 2. `text` 路径是什么

### 2.1 `text` 路径上传递的是什么

在 `text_whole_lane` 下，Agent 间 handoff 的内容是自然语言文本。例（示意型，字节数参考 frozen headline `benchmark_message_sizes.md`）：

```
Retriever → Executor handoff:
"Query: checkout regression after payment gateway deploy
 Retrieved docs: doc-42
 Visible candidates: db_pool_saturation::tool.db_pool_triage; cache_invalidation::tool.cache_hook_repair
 Visible evidence:
 [doc-42 的完整证据文本, 示意约 2800 bytes，以实际 artifact 为准]"
```

整段文字通过控制面可见的文本 handoff 传递。Executor 从这段文本中做两件事：
1. 解析出 route candidates（`db_pool_saturation`、`cache_invalidation`）
2. 匹配到正确的 tool（`tool.db_pool_triage`）

### 2.2 下游怎么解释这些文本

text 路径下，Executor 的消费方式仍然是"先从自然语言中恢复结构化信息，再进入后续决策与执行路径"：
- 通过正则/关键词匹配提取 `route::tool` 模式
- 对比 corpus metadata 验证 route 有效性
- 通过 playbook executor 执行对应 tool

因此 text 路径不是"Agent 随意聊天"——它仍然受同一套 route/tool helper path 约束。

### 2.3 它和"完全外部传统多 Agent baseline"是否相同

**不相同**。`text_whole_lane` 是 StateBus runtime 内部的 text lane。它仍然：
- 复用同一套 lexical route/tool helper path（词法路由/工具辅助路径）
- 使用同一套 playbook executor（执行器）
- 运行在同一套 `RunContext`、`RunSession`、`TaskMetrics` 框架内

它不是 external traditional pure-text multi-agent framework（如不经过任何 StateBus 基础设施的原生 LangGraph 或 AutoGen 实现）。这也是为什么有独立的 `external_text_baseline_audit_v3` 审计包来覆盖外部纯文本基线。

---

## 3. `StateBus` 路径是什么

### 3.1 结构化 packet、StateRef、中间状态和记忆在其中的作用

在 `state_packet_minimal` 下，从 Retriever 到 Executor 的传递链路是：

1. **Retriever** 产出 typed state（通过 corpus 检索 + feature extraction）：
   - `DENSE_EVIDENCE`：检索到的证据文本 → 写入 StatePool
   - `FEATURE_BUNDLE`：route/signals/query_terms/reuse_signature → 写入 StatePool
   - `TOOL_CANDIDATE_SET`：排序后的 tool 候选集 → 写入 StatePool
   - `EXECUTOR_DECISION_PACKET`：最终决策（route + tool_name + signals + confidence）→ 写入 StatePool

2. **StateRef 传递**：控制面消息中只包含轻量级 StateRef 引用，指向 StatePool 中的数据。精确 wire bytes 会因 pack 和 lane 不同而变化；如果需要正式数字，以当前 authoritative artifact 为准。

3. **Executor** 通过 StateRef 从 StatePool 本地读取 `EXECUTOR_DECISION_PACKET`，直接反序列化得到 `route`、`tool_name`、`signals` 等字段。

4. **Memory** 也在其中协同：Retriever 查询 MemoryStore 获取历史命中，如果命中且 replay gate 通过，Executor 的 execute step 可以被跳过。

### 3.2 它不只是"少写一点文本"

StateBus 路径的关键区别不在于"消息字数更少"，而在于：

- **传递语义变化**：从"文本载体"变成"结构化载体"。text 路径传递的是"大段文字需要下游再解析"，protocol 路径传递的是"已解好的结构化决策"。
- **零拷贝访问**：数据在 StatePool（本地 mmap），控制面只传指针。这避免了"序列化大块数据进入消息体"。
- **消费方式变化**：Executor 从"解析自然语言"变成"直接读取结构化字段"。

---

## 4. 固定变量与变化变量

| 固定了什么 | 改变了什么 | 为什么这样公平 |
|---|---|---|
| **task object**：相同的 query、family、evidence universe（证据宇宙） | **mode**：text vs protocol | 排除"不同任务"导致的差异 |
| **plan source**：同为 `llm`（当前 communication mainline）或同为 `yaml`（某些历史/机制 pack） | **mode / handoff surface**：自然语言 whole-lane text vs protocol minimal state packet | 避免把不同对象的 planner surface 混读 |
| **corpus**：相同的 corpus docs、route/tool 映射 | **Executor 消费方式**：解析自然语言 vs 直读结构化 packet | 排除数据源差异 |
| **LLM**：相同的 `deepseek-v4-flash`、相同的 Summarizer prompt 框架 | **控制面消息格式**：text frame vs protocol frame | 排除模型差异 |
| **retrieve 路径**：相同的 corpus retrieval 主逻辑、候选生成主逻辑和语料范围 | **handoff bytes**：文本内联 vs 结构化引用；正式数值以 artifact 为准 | 保证比较的主变量仍是通信载体与下游消费表面，而不是换检索对象 |
| **summary contract**：相同的总结合同 | **Summarizer 收到的输入形式**：全文 evidence vs adapter 整理后的结构化摘要 | 排除总结逻辑差异 |
| **repeat**：相同的 repeat 次数 | — | 排除时序偏差 |

**关键**：Retriever 在两种模式下共用同一套 corpus retrieval、memory assist、candidate generation 和 typed-state 生产框架；但当前代码里它仍会走 retriever-role LLM contract 做语义选择，Executor 也会走 executor-role LLM contract。差别不是“只有 carrier 不同”这么简单，而是同一 task object 下，mode/carrier surface 改变后，下游看到的语义暴露表面和消费方式也会变化。

---

## 5. handoff（交接）差异——分角色说明

### 5.1 Retriever → Executor

注：下表精确字节数来自历史 frozen headline 的 `benchmark_message_sizes.md`（`runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_message_sizes.md`），仅作示意型参考；当前 comm authoritative artifact 的均值见 `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/benchmark_report.md`（`handoff_wire_bytes`: text=212.67, protocol=397.33；`handoff_payload_bytes`: text=2919.50, protocol=5419.25）。

| 维度 | text (`text_whole_lane`) | protocol (`state_packet_minimal`) |
|---|---|---|
| handoff 内容 | 自然语言文本：完整 evidence + route::tool candidates 文本描述 | `StateRef` → `EXECUTOR_DECISION_PACKET`（msgpack） |
| wire bytes（线上） | 示例值见 frozen headline `benchmark_message_sizes.md`；当前 authoritative 均值见 `superiority_comm_v1` report | 示例值见 frozen headline `benchmark_message_sizes.md`；当前 authoritative 均值见 `superiority_comm_v1` report |
| payload bytes（本地） | 示例值见 frozen headline `benchmark_message_sizes.md`；当前 authoritative 均值见 `superiority_comm_v1` report | 示例值见 frozen headline `benchmark_message_sizes.md`；当前 authoritative 均值见 `superiority_comm_v1` report |
| 非文本状态 | 0 | `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` |
| Executor 如何消费 | 从文本中解析 route::tool 模式，匹配 corpus | 直接反序列化 `EXECUTOR_DECISION_PACKET`，读取 `route`、`tool_name`、`signals` 字段 |

**这里的关键是**：protocol 路径把原本需要以内联文本形式暴露的大部分语义，转化为了非文本 typed state。哪怕 wire bytes 不必然逐项都更小，传递语义已经从“文本恢复”变成了“结构化消费”。正式 headline 数字仍应以当前 `superiority_comm_v1` authoritative artifact 为准。

### 5.2 Executor → Summarizer

| 维度 | text | protocol |
|---|---|---|
| Summarizer 收到的输入 | 原文 evidence 文本（示意约 2800 bytes，以实际 artifact 为准） | adapter 整理后的结构化摘要（更紧凑） |
| token 消耗 | 在 `superiority_comm_v1` authoritative artifact 中：`summarizer_total_tokens` text=412.22, protocol=307.17, delta=-105.06 | protocol 侧 summarizer token 更低 |
| wall-time | Summarizer 处理全文时 wall-time 更低 | Summarizer 处理结构化字段需要重建关系，`summarize_ms` 略高（+149.86 ms，来自 `superiority_comm_v1` repeat=3 authoritative artifact） |

### 5.3 Planner（两种模式相同角色）

在历史 frozen headline 中，Planner 使用固定 yaml plan（`plan_source=yaml`），不调 LLM。因此 text 和 protocol 的 Planner 行为相同——不产生 planner token 差异。

在当前 `superiority_comm_v1` 中，headline contract 已切到 `plan_source=llm`。因此 Planner 本身也进入了 active communication 读法，并贡献了当前的 planner-led token / latency 优势。与此同时，Retriever 和 Executor 也在当前实现里使用 role-specific LLM contract，只是现有 benchmark readout 没有把它们的 token 单独拆出来。

---

## 6. prompt 与输入差异

### 6.1 哪些差异来自 carrier（载体），哪些差异不是

**来自 carrier 的差异**：
- Retriever 的 handoff：text 路径必须把所有 information（evidence、candidates）内联成文本 → 更多字节；protocol 路径用 typed struct → 更紧凑
- Executor 的输入：text 路径收到自然语言文本（需要解析）；protocol 路径收到结构化 packet（直接消费）
- Summarizer 的输入：text 路径收到全文；protocol 路径收到 adapter 整理后的结构化摘要

**不是来自 carrier 的差异**：
- Retriever 的 corpus retrieval 逻辑（两种模式相同）
- Tool Registry 和 playbook execution 逻辑（两种模式相同）
- Replay gate 逻辑（两种模式相同）
- Case contract 和 scorer 逻辑（两种模式相同）

### 6.2 prompt 设计对比较的影响

当前 protocol 的 prompt 设计已经收紧了"控制变量"，但要诚实理解边界：
- text 和 protocol 的 Retriever role contract 都存在，但上游 retrieval/candidate generation 框架相同
- text 和 protocol 的 Executor role contract 也都存在，只是其输入表面不同
- text 和 protocol 的 Summarizer prompt 框架相同，差异主要来自输入表面（全文 vs 结构化摘要）
- 在历史 frozen headline 中，Planner 不调 LLM；在当前 `superiority_comm_v1` 中，Planner 已回到 LLM headline contract
- 因此当前 communication headline 不是“所有角色都完全不变，只换一层传输壳”；更准确的说法是：在固定 task object、语料、summary/scoring contract 的前提下，比较两种 mode surface

---

## 7. 并列流程图

### 7.1 `text` 路径图

```text
  Task
    │
    ▼
  Planner (LLM plan in current communication headline; yaml only in some historical/mechanism packs)
    │ text PlanStep (内联 params)
    ▼
  Retriever (corpus retrieval)
    │ text handoff:
    │ "Query: ... Retrieved docs: doc-42, doc-101
    │  Visible candidates: db_pool_saturation::tool.db_pool_triage; ..."
    │  [handoff_textual_bytes ~2800]
    ▼
  Executor (解析文本 → 匹配 route/tool → 执行工具)
    │ text results (TOOL_ARTIFACT 文本)
    ▼
  Summarizer (LLM: 阅读全文 evidence + results → 总结)
    │ MemoryCommit → MemoryStore
    ▼
  Report
```

### 7.2 `StateBus` 路径图

```text
  Task
    │
    ▼
  Planner (LLM plan in current communication headline; yaml only in some historical/mechanism packs)
    │ protocol PlanStep (StateRef[])
    ▼
  Retriever (corpus retrieval + MemoryStore 查询)
    │ typed state: DENSE_EVIDENCE + FEATURE_BUNDLE + TOOL_CANDIDATE_SET
    │              + EXECUTOR_DECISION_PACKET + REPLAY_ELIGIBILITY_BUNDLE
    │              → StatePool (mmap)
    │ 控制面只传 StateRefLite (50-80 bytes/个)
    ▼
  Executor (反序列化 EXECUTOR_DECISION_PACKET → 直接读 route/tool → 执行工具)
    │ typed results (TOOL_ARTIFACT → StatePool)
    │ [如果 replay gate 通过 → skip_execute]
    ▼
  Summarizer (LLM: adapter 整理后的结构化摘要 → 总结)
    │ MemoryCommit → MemoryStore
    ▼
  Report
```

---

## 8. 这套比较在回答什么，不回答什么

### 8.1 当前比较能证明的范围

1. **controlled carrier variance**（受控载体差异）：在固定 task object、plan source、corpus、LLM 的前提下，改变通信载体（text vs protocol）会导致：
   - 控制面字节数下降（~14% at frozen headline）
   - 非文本状态出现（从 0 → 50 mean state transfer count）
   - Executor 消费方式从文本解析变为结构化消费
2. **quality floor 稳定**：protocol 路径不降低正确性（wrong_family_rate=0，admissible_match_rate=1.00）

### 8.2 不等于整体 superiority 的所有问题都解决了

1. **不等于 external pure-text baseline superiority**：`text_whole_lane` 是内部 comparator，不是外部传统纯文本多 Agent baseline
2. **不等于 latency superiority closure**：`summarize_ms` 仍有正残差，formal stability gate 仍是 `not_yet`
3. **不等于 all-dimensional win**：protocol 路径在某些局部字节口径上未必逐项都更少，优势主要体现在 control_bytes 整体 compactness、部分 handoff 文本缩减和当前 headline object 下的 token / task_ms 读法
4. **不等于 memory superiority**：replay effect 只证明跳过步骤，不证明 latency 下降
5. **不等于 open-world agent benchmark**：这是受控 paired contest object 下的对照实验

---

## 9. 术语解释

- **`text_whole_lane`（自然语言全通道）**：StateBus runtime 内部的自然语言 text lane，Agent 间以自然语言传递完整 evidence 和 route/tool candidate 文本。它既出现在历史 frozen headline，也出现在当前 `superiority_comm_v1` communication mainline 中，但两者的 reading contract 不能混读。
- **`text_strict_pure_lane`（严格纯文本通道）**：更严格的纯文本 lane，Executor 不接任何 typed state ref。用于内部受控对照（`contest_dual_mode_controlled_v3`），不承担 contest-facing pure-text headline。
- **`natural_handoff_text`（自然交接文本）**：typed-state 机制验证中使用的 text 对照方式，固定 `mode=protocol` 并禁用 typed state，Agent 间用自然语言传递 handoff 信息。用于 protocol-only 机制真实性验证。
- **`state_packet_minimal`（最小状态包）**：当前 protocol 路径的正式定义。Executor 输入包含 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`，通过 `StateRef` 传递，不在控制面内联。
- **`handoff_profile`（交接配置）**：定义 Agent 间 handoff 时的信息密度和格式。不同的 pack 可以使用不同的 handoff profile。
- **`transfer_strategy`（传递策略）**：状态传递的具体策略，包括 `text_whole_lane`、`text_strict_pure_lane`、`natural_handoff_text`、`state_packet_minimal`、`text_brief`（文本摘要）、`text_packet_minimal`（文本最小包）等 8 种。
