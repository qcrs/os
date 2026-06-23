# 项目目标与整体方法总览

本文档回答三个根本问题：

1. 这个项目不是普通 workflow，它到底在解决什么系统问题。
2. StateBus 的方法由哪些核心机制组成。
3. 为什么 memory（记忆）、中间状态、结构化传递必须一起理解。

---

## 1. 赛题在问什么

赛题题目是：**一种面向多智能体协作的低开销通信、状态传递与共享记忆机制**。

这本身不是一个"谁调了几个工具"的应用问题，而是一个**系统层基础设施问题**。它关心的是：当多个 Agent 协作完成复杂任务时，底层通信、状态和记忆能否以更高效的方式组织，而不是靠自然语言长文本把所有信息透传一遍。

具体来说，赛题要求从三条主线同时改进：

1. **低开销通信（Communication）**：Agent 之间的交互内容能否从"冗长的自然语言描述"收敛为"动作、参数、结果、能力等高密度语义单元"，降低 token 消耗和解析开销。

2. **非文本状态传递（State Transfer）**：中间结果能否避免"内部状态→文本→内部状态"的反复转换，而是通过 embedding（嵌入向量）、语义向量、结构化特征包等方式直接传递。

3. **共享记忆复用（Memory Reuse）**：任务执行中产生的经验、证据、策略能否沉淀为可标识、可检索、可复用的记忆单元，使得后续相似任务不再从头开始。

这三个问题不是独立的——它们共同支撑"多 Agent 协作基础设施"这一核心命题。

---

## 2. StateBus 回答的三个核心问题

### 2.1 低开销通信

StateBus 把 Agent 间的消息拆成**控制面**和**数据面**两层：

- **控制面（Control Plane）** 只传"谁做什么"的动作骨架：`Plan`（执行计划）、`PlanStep`（计划步骤）、`StepResult`（步骤结果）、`Ack`（确认）等协议消息。**重状态不进入消息体**。
- **数据面（Data Plane）** 传"实际数据"：`StateRef`（状态引用）指向 `StatePool`（状态池）中的 mmap（文件内存映射）文件或共享内存。Agent 通过指针去本地做零拷贝读取。

核心结果：控制面消息体只包含指针（50-80 字节/个），而实际数据在本地 StatePool 中。`handoff_wire_bytes`（线上指针字节）≠ `handoff_payload_bytes`（本地负载字节）。这才是"不通过自然语言长文本透传全部信息"的核心实现。

### 2.2 非文本中间状态传递

StateBus 的中间状态传递走的是 StateRef 路径：

- Retriever（检索器）产出 `DENSE_EVIDENCE`（稠密证据）、`FEATURE_BUNDLE`（特征包，包含 route/tool/signals/query_terms 等结构化特征）、`EXECUTOR_DECISION_PACKET`（执行器决策包）
- Executor（执行器）通过 `StateRef` 直接消费这些非文本状态，不再依赖原始长文本做路由决策
- Summarizer（总结器）消费的是经过 adapter（适配器）整理后的结构化摘要

当前已落地的是 `embedding + feature bundle + state ref` 这一层的非文本中间态。更强的 hidden-state（隐藏状态）/KV cache（键值缓存）级表示属于后续增强对象，**当前未实现**。

### 2.3 共享记忆复用

StateBus 的记忆系统负责沉淀和复用：

- **存储层**：SQLite 存元数据（ID、来源 Agent、创建时间、任务主题、摘要描述）+ FAISS 向量索引用于语义检索
- **分层记忆**：`working_memories`（工作记忆）、`long_term_memories`（长期记忆）、`replay_episodes`（回放记录）、`task_commits`（任务提交记录）
- **复用级别**：
  - `assist`（辅助）：给当前任务辅助判断，不跳过步骤
  - `validated_replay`（验证回放）：通过 fresh-side fail-closed 验证后跳过部分步骤
  - `exact_replay`（精确回放）：更强的回放命中，可跳过检索+执行

当前已证明 exact-replay-backed `skip_execute`（跳过执行）effect 真实成立。

---

## 3. 当前方法总览

```text
                      ┌─────────────┐
  Task → eval/runner   │  Planner    │  (LLM)  →  编译 Plan，分配 semantic_role
                       └──────┬──────┘
                              │ Plan + PlanStep[]
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                     ▼
   ┌──────────┐        ┌──────────┐          ┌──────────┐
   │ Retriever│        │ Executor │          │Summarizer│
   │ (检索增强+语义选择) │───→    │ (语义决策+工具执行) │  ───→    │ (LLM型)  │
   └────┬─────┘        └────┬─────┘          └────┬─────┘
        │                   │                     │
        │  StateRef[]       │  StateRef[]         │  MemoryCommit
        ▼                   ▼                     ▼
   ┌──────────────────────────────────────────────────┐
   │              StatePool (mmap / shm)               │
   │         ┌─────────────────────────────┐          │
   │         │  DENSE_EVIDENCE              │          │
   │         │  FEATURE_BUNDLE              │          │
   │         │  EXECUTOR_DECISION_PACKET     │          │
   │         │  TOOL_ARTIFACT               │          │
   │         │  EMBEDDING                   │          │
   │         └─────────────────────────────┘          │
   └──────────────────────┬───────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   MemoryStore         │
              │   (SQLite + FAISS)    │
              │   working / long_term │
              │   replay_episodes     │
              │   task_commits        │
              └───────────────────────┘
```

**核心观点**：StateBus 不是"一个 LangGraph demo + 若干 prompt"，而是以 `Orchestrator`（编排器）为语义核心、以 LangGraph 为编排外壳、以 `StateRef + StatePool + MemoryStore + formal benchmark/report gates` 为基础设施的多 Agent 运行时。

---

## 4. 为什么不是普通纯文本多 Agent

### 4.1 纯文本协作的典型问题

传统的多 Agent 系统通常以自然语言或 JSON 作为通信媒介：

- 一个 Agent 把中间结果组织成文本，传递给下一个 Agent 解析和处理
- 通信内容冗长、重复上下文多，token 消耗高
- 中间结果需要在"内部状态→文本→内部状态"之间反复转换，时延增加且可能带来语义损耗
- 任务执行中形成的中间知识和经验难以沉淀，系统处理相似任务时往往从头开始

### 4.2 StateBus 的改进点

| 问题 | 纯文本做法 | StateBus 做法 | 改进点 |
|---|---|---|---|
| 通信冗长 | 所有信息内联在文本消息中 | 控制面传动作骨架+StateRef 指针，重状态在本地 StatePool | control_bytes 下降 ~14% |
| 反复编解码 | 每次 handoff 都是"内部状态→长文本→下游解析" | typed packet 通过 msgpack 序列化，下游直接反序列化消费 | 从"自然语言解析"变成"结构化字段直读" |
| 记忆难沉淀 | 经验只存在于当次对话上下文中 | SQLite+FAISS 持久化记忆，支持语义检索和 replay gate | 跨任务复用成立 |
| 角色分工不清 | 所有角色都可能直接面对大段自然语言和重复解释 | Retriever / Executor 前面有较重的检索、候选生成、结构化 packet 与工具执行路径；四角色都可能进入 role-specific LLM contract，但暴露表面和职责不同 | LLM 负担被更强地约束到结构化合同内，而不是让所有角色只靠自由文本对话 |

### 4.3 诚实边界

- StateBus 不是"所有 Agent 都变成非 LLM 的纯系统程序"
- 当前代码里四个角色都接入了 role-specific LLM contract；区别在于 Retriever / Executor 在 LLM 前还有更重的检索、候选、校验和工具执行路径
- `text_whole_lane` comparator 仍然是 StateBus runtime 内部的 whole-lane text lane
- 它不是 external traditional pure-text multi-agent baseline
- 这是一个**受控 paired contest object 下的单一通信载体变量对照**，不是 open-world agent benchmark

---

## 5. 方法的三大组成——不要拆散

### 5.1 结构化控制与交接

- 控制面消息对象：`Hello`（握手）、`Capability`（能力发现）、`Plan`（执行计划）、`PlanStep`（步骤定义）、`StepResult`（步骤结果）、`MemoryQuery`（记忆查询）、`MemoryHit`（记忆命中）、`MemoryCommit`（记忆写入）、`ChannelPatch`（通道补丁）、`ChannelSnapshot`（通道快照）、`TaskCommit`（任务提交）
- `PlanStep` 带 `semantic_role`（语义角色），执行引擎按语义角色而非硬编码 step_id 调度
- `CapabilityTable + SchemaInterceptor` 在 plan、step、result、memory commit 层做合同校验
- 控制面不负责传完整重状态，重状态落到 StateRef 指向的数据面

### 5.2 中间状态与非文本传递

- **状态种类**（State Kinds）：`DENSE_EVIDENCE`、`FEATURE_BUNDLE`、`CHANNEL_PATCH`、`CHANNEL_SNAPSHOT`、`RANKED_EVIDENCE_BUNDLE`、`TOOL_CANDIDATE_SET`、`REPLAY_ELIGIBILITY_BUNDLE`、`EXECUTOR_DECISION_PACKET`、`VALIDATION_GATE_PACKET`、`EMBEDDING`、`TOOL_ARTIFACT`
- **Channel（通道）**映射：`evidence`、`route`、`tool_candidates`、`replay_gate`、`legacy_features`、`embedding`、`artifact`
- **存储后端**：`FileBackedStatePool`（mmap 文件，默认主线）、`SharedMemoryStatePool`（Python shared_memory，可选验证路径）、`ContentAddressedBlobStore`（CAS/dedup/replay-ready blob）
- `FEATURE_BUNDLE` 的定位：route、signals、query_terms、reuse_signature、evidence hash 等结构化特征，通过 StateRef 传给 Executor，避免 Executor 只靠原始长文本做路由

### 5.3 记忆沉淀与复用

> `memory` 是整体方法的一部分，不要单独写成外插模块。

- **写入路径**：Summarizer 产出 `MemoryCommit`，写入 SQLite + FAISS
- **检索路径**：Retriever 在每次任务开始时查询 `MemoryStore`，获取 `MemoryHit`
- **复用决策**：`replay_gate`（回放门控）根据 fresh route 匹配、route provenance、tool artifact 兼容性决定是否允许 `skip_execute`
- **分层复用**：assist（参考使用）→ validated_replay（验证后跳步）→ exact_replay（精确命中跳步）
- 记忆不是"命中即复用"：它区分了命中率（`memory_hit_rate`）和真实效果（`skipped_step_count`、`reuse_gain`）

---

## 6. 当前实现边界

### 6.1 已经实现到哪

| 能力 | 状态 |
|---|---|
| 四角色（Planner/Retriever/Executor/Summarizer）主链路 | ✅ 已实现 |
| `text` / `protocol` 双模式 | ✅ 已实现 |
| Protobuf 控制帧 + CapabilityTable + SchemaInterceptor | ✅ 已实现 |
| `StateRef` + mmap/shared_memory 双后端 | ✅ 已实现 |
| SQLite + FAISS 共享记忆 | ✅ 已实现 |
| assist / validated_replay / exact_replay 分层复用 | ✅ 已实现 |
| UDS executor transport 样机 | ✅ 已实现 |
| formal pack / gate / report 体系 | ✅ 已实现 |
| `FEATURE_BUNDLE` 非文本特征态 | ✅ 已实现 |
| 历史 frozen headline 的 repeat=10 证据 | ✅ 已有历史 frozen artifact |

### 6.2 还没有实现或不该夸大的地方

| 能力 | 状态 |
|---|---|
| `nsjail` 正式安全沙箱链 | ❌ 未实现，属于后续阶段 |
| Docker 终态复现链 | ❌ 未实现，属于后续阶段 |
| openEuler 最终交付验证 | ❌ 未实现，属于后续阶段 |
| `SCM_RIGHTS` / FD passing 数据面 | ❌ 未实现，属于后续增强 |
| LLM hidden state / KV cache 直传 | ❌ 未实现，属于后续增强 |
| WASM / eBPF 等加分项正式集成 | ❌ 未实现，属于后续增强 |
| 容器级多角色分布式 Runtime | ❌ 未实现，属于后续增强 |

### 6.3 对外最诚实表述

> 已实现 `StateRef + feature/state bundle + replay-ready memory` 这一层非文本协作基础设施；更强的系统与模型级状态传递仍属于后续增强。

---

## 7. 术语解释

- **Plan（执行计划）**：Planner（规划器）产出的结构化步骤序列，包含一组 `PlanStep`，定义了谁做什么、依赖关系、语义角色。
- **StateRef（状态引用）**：一个轻量级引用对象（50-80 字节），包含 `state_id`、`kind`、`length`、`blob_hash`、`channel` 等字段。指向 StatePool 中的实际数据，用于控制面传递而不内联大量数据。
- **MemoryCommit（记忆写入记录）**：Summarizer（总结器）在 task 完成时写入 MemoryStore 的记录，包含 summary、evidence refs、replay episode 信息。
- **Protocol（结构化协议路径）**：StateBus 的结构化通信模式，Agent 间用 Protobuf 控制帧 + StateRef 指针传递信息。
- **Text mode（纯文本协作路径）**：StateBus 内部的纯文本对照模式，Agent 间用自然语言传递 handoff 信息，但仍在同一 runtime 内运行，复用同一套 tool/route helper path。
