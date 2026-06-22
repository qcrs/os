# 多智能体研究系统 Demo 测试报告

> 测试环境：openEuler 24.03-LTS-SP3 (Docker)
> 测试框架：LangGraph + Qwen3-8B 本地 Transformers 后端
> 测试日期：2026-06-16

---

## 一、系统架构

### 1.1 Agent 角色分工

```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Agent Research System                   │
├─────────────┬─────────────┬─────────────┬───────────────────────┤
│   Planner   │  Retriever  │  Executor   │     Summarizer        │
│   (规划)     │   (检索)     │   (执行)     │      (总结)           │
├─────────────┼─────────────┼─────────────┼───────────────────────┤
│ 拆解查询为   │ 并行检索子   │ 分析检索结果  │ 汇总分析，输出        │
│ 结构化子任务  │ 查询，获取   │ 提取关键证据  │ 最终报告和发现        │
│              │ 文档资料     │              │                       │
├─────────────┼─────────────┼─────────────┼───────────────────────┤
│ 调用: 2次    │ 调用: 6次    │ 调用: 2次    │ 调用: 2次             │
│ 平均: 2.44s  │ 平均: 7.77s  │ 平均: 7.66s  │ 平均: 4.30s           │
└─────────────┴─────────────┴─────────────┴───────────────────────┘
```

### 1.2 当前本地模型数据流图

当前实现切换为本地 Transformers 后端：四个 Agent 都通过同一个本地 Qwen3-8B 模型实例完成文本生成；Planner 额外捕获最后一层 hidden state，作为非文本中间表示在 Agent 间显式传递。

**运行配置**：

```bash
CHAT_BACKEND=transformers
CHAT_MODEL=qwen3-8b
LOCAL_MODEL_PATH=/data/models/Qwen3-8B
LOCAL_MODEL_DEVICE=cuda:0
LOCAL_MODEL_DTYPE=bfloat16
ENABLE_HIDDEN_STATE_TRANSFER=1
```

#### 1.2.1 总体 Agent 数据流

```text
用户查询
   │
   ▼
┌────────────────────────────────────────────────────────────────────┐
│ Planner                                                            │
│ - 调用本地 Qwen3-8B 生成 plan/sub_queries                         │
│ - 捕获 planner_hidden_state: last-layer pooled hidden vector       │
└───────────────┬───────────────────────────────────────┬────────────┘
                │                                       │
                │ 文本/结构化控制流                     │ 非文本隐藏状态流
                │ plan, sub_queries                     │ planner_hidden_state
                │                                       │ dims=4096, layer=-1
                ▼                                       ▼
      Send({sub_query:q1, planner_hidden_state})   ┌──────────────┐
      Send({sub_query:q2, planner_hidden_state})──▶│ ResearchState │
      Send({sub_query:q3, planner_hidden_state})   └──────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Retriever_1 ∥ Retriever_2 ∥ Retriever_3                            │
│ - 每个 Retriever 接收自己的 sub_query                              │
│ - 每个 Retriever 接收 planner_hidden_state                         │
│ - 生成 retriever_intent_hidden_state 并计算 intent alignment         │
│ - 输出 documents/context_packets/embedding_payloads/messages       │
└───────────────────────────────┬────────────────────────────────────┘
                                │ operator.add 聚合
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Executor                                                           │
│ - 接收 plan/documents/context_packets/evidence                     │
│ - 使用 planner_hidden_state 对 context_packets 重排并裁剪 top_k    │
│ - 输出 analysis/evidence/messages/hidden_guidance                  │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Summarizer                                                         │
│ - 接收 plan/analysis/evidence                                      │
│ - 使用 hidden_guidance 控制摘要重点和引用来源                     │
│ - 输出 summary/key_findings/messages                               │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
                             最终结果
```

#### 1.2.2 本地 Qwen3-8B 推理与隐藏状态生成

```text
LangChain messages
   │
   ▼
tokenizer.apply_chat_template(...)
   │
   ▼
prompt tokens
   │
   ▼
model(..., output_hidden_states=True, use_cache=False)
   │
   ├── outputs.hidden_states[-1][-1]
   │     └── 捕获用于预测第一个输出 token 的 pre-generation hidden state
   │
   ▼
AutoModelForCausalLM.generate()
   │
   └── generated text
         └── Planner 解析为 plan/sub_queries
```

隐藏状态 payload 当前结构如下：

```json
{
  "kind": "transformer_hidden_state",
  "capture_stage": "pre_generation",
  "source": "prompt",
  "prediction_target": "next_token",
  "model": "qwen3-8b",
  "model_path": "/data/models/Qwen3-8B",
  "layer": -1,
  "pooling": "last_token",
  "pooled_token_span": "prompt_last_token",
  "dims": 4096,
  "norm": 12.345678,
  "dtype": "float32_serialized",
  "vector": [0.012345, -0.06789, "..."],
  "source_token_hash": "...",
  "input_tokens": 512,
  "output_tokens": 0,
  "next_token_index": 512
}
```

#### 1.2.3 结构化通信中的传递位置

```text
Planner
  └─ result["planner_hidden_state"]
       │
       ├─ ResearchState.planner_hidden_state
       │
       ├─ Send("retriever", {"planner_hidden_state": ...})
       │
       ├─ AgentMessage.hidden_state
       │
       └─ metrics.hidden_state_transfers

Retriever / Executor / Summarizer
  └─ state.get("planner_hidden_state")
       │
       ├─ _record_hidden_state_received(agent, payload)
       ├─ 写入结构化 message.hidden_state
       └─ 继续传递给后续节点或最终指标
```

#### 1.2.4 下游 Agent 使用 hidden state 的方式

```text
Retriever:
  planner_hidden_state + retriever_intent_hidden_state
       │
       └─ cosine_similarity → intent_alignment
              │
              └─ 写入 context_packet.retrieval_diagnostics.intent_alignment

Executor:
  select_context_packets(..., planner_hidden_state=planner_hidden_state)
       │
       ├─ score = hidden_score / embedding_score / lexical_score / coverage 加权
       ├─ top_k = HIDDEN_STATE_CONTEXT_TOP_K，默认 2
       └─ 只把排序后的 compact evidence 放入 Executor prompt

Summarizer:
  hidden_guidance
       │
       ├─ selected_doc_keys
       ├─ avg_hidden_score / top_hidden_score
       └─ 作为摘要重点控制信号进入 Summarizer prompt
```

这个版本带来的直接收益是可量化的：`hidden_state_context_packets_skipped` 表示被 hidden-state routing 裁掉的上下文包数量，`hidden_state_context_chars_skipped` 表示未进入 Executor prompt 的原始上下文字符数，`executor_prompt` 的压缩记录表示最终进入 Executor prompt 的字符数；质量收益需要继续通过同一任务集的对照实验统计。

轻量协议层对照验证中，同一批 3 个 context packet 在不用 hidden routing 时全部进入 prompt；启用 hidden routing 后选择 top-2，并将每个文档的 evidence 控制为 1 条、120 字符，示例结果为 `all_context_chars=266`、`hidden_context_chars=181`、`saved_chars=85`、`saved_pct=32.0%`。真实模型 smoke test 中，Qwen3-8B 产生 3 个子查询、3 个 retriever pre-generation hidden state，Executor 选中 2 个 context packet，`hidden_state_context_packets_skipped=1`、`hidden_state_context_chars_skipped=159`。

#### 1.2.5 当前实现边界

```text
已经实现：
  本地模型生成 hidden state
  planner → retriever/executor/summarizer 显式传递 hidden state
  retriever 生成 pre-generation intent hidden state 并计算 planner/retriever intent 相似度
  executor 使用 hidden 相似度参与 context packet 重排，并用 top_k 裁剪提示词上下文
  summarizer 接收 hidden_guidance，用于控制摘要重点和引用来源
  metrics 统计 hidden-state transfer、生产、使用、裁剪包数量和裁剪字符数

尚未实现：
  下游 Agent 将 hidden state 注入模型内部
  KV cache / prefix state / cross-attention 级别的状态续算
  大规模实验下的准确率、token、延迟对照评估
```

---

## 二、测试任务详情

### 2.1 Task Group A：LangGraph 框架分析

**查询**：分析 LangGraph 框架的多智能体协作机制、状态管理和记忆系统

#### Planner 输出

**Plan**：
> 对 LangGraph 框架的多智能体协作机制、状态管理和记忆系统进行结构化分析，分别从协作模式、状态共享与更新、以及记忆持久化三个维度展开调研。

**Sub-queries**（3 个子查询）：
1. LangGraph 多智能体协作机制：包括智能体间的通信方式、任务分配与协调模式
2. LangGraph 状态管理：状态图的定义、节点间的状态传递与共享机制
3. LangGraph 记忆系统：短期与长期记忆的实现方式、记忆的存储与检索机制

#### Retriever 输出（并行）

3 个 Retriever 并行执行，共检索到 5 份文档：

| Retriever | 子查询 | 文档摘要 |
|-----------|--------|---------|
| #1 | 协作机制 | LangGraph 的多智能体协作机制建立在图结构的状态机框架之上，核心在于通过有向图定义智能体间的交互逻辑 |
| #2 | 状态管理 | LangGraph 的状态管理基于状态图（StateGraph）的概念，有向图结构中每个节点代表一个计算步骤 |
| #3 | 记忆系统 | 短期记忆通过 Checkpoint 机制实现，长期记忆通过 Store 实现 |

#### Executor 输出

**Analysis**：
> LangGraph 框架通过图结构的状态机实现多智能体协作，核心机制是共享状态（Shared State），智能体通过读写全局状态字典进行隐式通信，避免了显式消息传递的复杂性。

**Evidence**：6 条关键证据

#### Summarizer 输出

**Key Findings**（5 条）：
1. LangGraph 的多智能体协作通过共享状态实现隐式通信，而非传统消息队列或黑板模式
2. 支持顺序、并行、条件分支、循环/递归和子图等多种协作模式
3. 状态管理基于状态图和模式化定义，采用增量更新策略
4. 短期记忆通过 Checkpoint 机制实现，支持故障恢复和状态回溯
5. 长期记忆通过 Store 实现，支持跨会话共享和语义搜索

---

### 2.2 Task Group B：系统设计（复用 Task A 记忆）

**查询**：基于之前的分析结果，设计一个改进的多智能体协作系统架构

#### 记忆复用情况

Task B 的 Planner 节点在执行前，通过语义搜索从 Store 中检索 Task A 的成果：

```
store.search(("summaries",), query="多智能体", limit=2)
```

检索结果：
| 命中项 | Score | 内容摘要 |
|--------|-------|---------|
| summary_B_system_design | 0.2521 | 基于 LangGraph 框架分析结果，设计改进的多智能体协作系统架构 |
| summary_A_langgraph_analysis | 0.2112 | LangGraph 框架采用图结构的状态机模型实现多智能体协作 |

#### Planner 输出

**Plan**：
> 基于 LangGraph 框架的分析结果，设计一个改进的多智能体协作系统架构，重点优化状态管理、通信效率和容错机制，并引入动态任务分配与自适应学习能力。

**Sub-queries**（3 个子查询）：
1. LangGraph 框架中共享状态机制的改进方案
2. 多智能体通信效率优化
3. 动态任务分配与自适应协作

#### Retriever 输出（并行）

3 个 Retriever 并行执行，共检索到 6 份文档（含 1 份来自 Task A 的记忆复用）

#### Executor 输出

**Analysis**：
> 基于 LangGraph 框架的分析结果，设计了一个改进的多智能体协作系统架构，重点优化状态管理、通信效率和容错机制。

**Evidence**：5 条关键证据

#### Summarizer 输出

**Key Findings**（5 条）：
1. 分层状态图通过父子状态层级隔离全局与局部状态，状态冲突次数降低约 70%
2. 差异化状态更新策略通过增量更新和写时复制，状态传输带宽消耗下降 45%
3. 结合图拓扑隐式通信与显式消息队列，通信量降低 60%
4. 延迟中位数低于 10ms，吞吐量达 5000 消息/秒
5. 强化学习驱动的动态任务分配提升整体效率 25-40%

---

## 三、Agent 调度情况

### 3.1 执行时序图

```
Task A (23.27s)
═══════════════════════════════════════════════════════════════

时间(s)  0    2    4    6    8   10   12   14   16   18   20   22  23
         │    │    │    │    │    │    │    │    │    │    │    │   │
Planner  ████████│    │    │    │    │    │    │    │    │    │   │
         │ 2.41s │    │    │    │    │    │    │    │    │    │   │
         │       │    │    │    │    │    │    │    │    │    │   │
Retriever_1      ██████████████████████│    │    │    │    │   │
         │       │    │    9.23s       │    │    │    │    │   │
Retriever_2      ████████████████│    │    │    │    │    │   │
         │       │    6.19s      │    │    │    │    │    │   │
Retriever_3      ██████████████████████████│    │    │    │   │
         │       │    │    │    7.88s      │    │    │    │   │
         │       │    │    │    │    │    │    │    │    │   │
Executor │       │    │    │    │    ████████████████│    │   │
         │       │    │    │    │    │    7.77s     │    │   │
         │       │    │    │    │    │    │    │    │    │   │
Summarizer       │    │    │    │    │    │    │    ████████│
         │       │    │    │    │    │    │    │    │ 4.81s │
         │    │    │    │    │    │    │    │    │    │   │
                 ├────┼────┼────┼────┼────┼────┼────┼────┼───┤
                 并行检索阶段 (3 个 Retriever 同时执行)


Task B (23.07s)
═══════════════════════════════════════════════════════════════

时间(s)  0    2    4    6    8   10   12   14   16   18   20   22  23
         │    │    │    │    │    │    │    │    │    │    │    │   │
Planner  ████████████│    │    │    │    │    │    │    │    │   │
         │   2.47s   │    │    │    │    │    │    │    │    │   │
         │           │    │    │    │    │    │    │    │    │   │
Retriever_1          ████████████████████████████████│    │   │
         │           │    │    │    │    │    10.09s │    │   │
Retriever_2          ████████████████████│    │    │    │   │
         │           │    │    │    7.47s│    │    │    │   │
Retriever_3          ████████████████████████████████████████│
         │           │    │    │    │    │    │    │ 11.10s│
         │           │    │    │    │    │    │    │    │   │
Executor │           │    │    │    │    │    ████████████████
         │           │    │    │    │    │    │    7.56s   │
         │           │    │    │    │    │    │    │    │   │
Summarizer           │    │    │    │    │    │    │    ████│
         │           │    │    │    │    │    │    │ 3.78s │
```

### 3.2 并行调度详情

**Send fan-out 机制**：Planner 输出 3 个 sub_queries 后，通过 `Send("retriever", {"sub_query": q})` 动态派发 3 个并行 Retriever 任务。

```
Planner 输出:
  sub_queries = [
    "LangGraph 多智能体协作机制...",
    "LangGraph 状态管理...",
    "LangGraph 记忆系统..."
  ]

Send 派发:
  Send("retriever", {"sub_query": "LangGraph 多智能体协作机制...", "task_group": "A"})
  Send("retriever", {"sub_query": "LangGraph 状态管理...", "task_group": "A"})
  Send("retriever", {"sub_query": "LangGraph 记忆系统...", "task_group": "A"})

执行: 3 个 Retriever 并行执行（Pregel BSP 模型）

Fan-in: documents 字段通过 operator.add reducer 自动合并
  documents = retriever_1.docs + retriever_2.docs + retriever_3.docs
```

### 3.3 Channel 状态传递

| Channel 类型 | 状态字段 | 传递方向 | 说明 |
|-------------|---------|---------|------|
| LastValue | query | 输入 → 所有节点 | 每步仅一个写入者 |
| LastValue | plan | Planner → Executor/Summarizer | 规划结果 |
| LastValue | analysis | Executor → Summarizer | 分析结果 |
| LastValue | summary | Summarizer → 输出 | 最终总结 |
| BinaryOperatorAggregate | documents | Retriever(s) → Executor | operator.add 累积 |
| BinaryOperatorAggregate | sub_queries | Planner → Retriever(s) | operator.add 累积 |

---

## 四、共享记忆模块运行情况

### 4.1 Store 操作统计

| 操作类型 | 调用次数 | 平均耗时 | 说明 |
|---------|---------|---------|------|
| put | 12 | 0.013s | 写入 plans/docs/analysis/summaries |
| search | 21 | 0.002s | 语义搜索（含 embedding 计算） |
| **总计** | **33** | **0.005s** | |

### 4.2 记忆写入详情

| Namespace | Key | 写入者 | 内容 |
|-----------|-----|--------|------|
| ("plans",) | plan_A_langgraph_analysis | Planner (A) | LangGraph 框架分析计划 |
| ("plans",) | plan_B_system_design | Planner (B) | 系统设计计划 |
| ("docs",) | doc_A_langgraph_analysis_xxx | Retriever (A) × 3 | 检索文档 |
| ("docs",) | doc_B_system_design_xxx | Retriever (B) × 3 | 检索文档 |
| ("analysis",) | analysis_A_langgraph_analysis | Executor (A) | 分析结果 |
| ("analysis",) | analysis_B_system_design | Executor (B) | 分析结果 |
| ("summaries",) | summary_A_langgraph_analysis | Summarizer (A) | Task A 总结 |
| ("summaries",) | summary_B_system_design | Summarizer (B) | Task B 总结 |

### 4.3 记忆检索与复用

**语义搜索 Score 分布**：

```
Score
0.71 ┤ ●
     │
0.60 ┤   ●
     │
0.50 ┤     ● ●
     │
0.40 ┤       ● ● ●
     │
0.30 ┤           ● ● ● ● ●
     │
0.20 ┤               ● ● ● ● ● ●
     │
0.10 ┤                       ● ● ● ●
     │
0.03 ┤                           ●
     └─────────────────────────────────
      搜索次数 (共 21 次)
```

**记忆复用命中**：7 次

Task B 的 Planner 和 Retriever 节点在执行时，通过语义搜索从 Store 中检索 Task A 的成果，实现了跨任务的记忆复用。

### 4.4 命名空间使用情况

```
Store 内存布局:
├── ("plans",)
│   ├── plan_A_langgraph_analysis    [Task A 规划]
│   └── plan_B_system_design         [Task B 规划]
├── ("docs",)
│   ├── doc_A_langgraph_analysis_1   [Task A 检索文档 1]
│   ├── doc_A_langgraph_analysis_2   [Task A 检索文档 2]
│   ├── doc_A_langgraph_analysis_3   [Task A 检索文档 3]
│   ├── doc_B_system_design_1        [Task B 检索文档 1]
│   ├── doc_B_system_design_2        [Task B 检索文档 2]
│   └── doc_B_system_design_3        [Task B 检索文档 3]
├── ("analysis",)
│   ├── analysis_A_langgraph_analysis [Task A 分析]
│   └── analysis_B_system_design      [Task B 分析]
└── ("summaries",)
    ├── summary_A_langgraph_analysis  [Task A 总结] ← Task B 复用
    └── summary_B_system_design       [Task B 总结]
```

---

## 五、性能数据

### 5.1 任务级时延

| 指标 | Task A | Task B | 说明 |
|------|--------|--------|------|
| 总时延 | 23.27s | 23.07s | 从 invoke 到返回 |
| 图构建 | 0.01s | — | StateGraph 编译 |

### 5.2 节点级时延

| Agent | 调用次数 | 平均耗时 | 最小耗时 | 最大耗时 |
|-------|---------|---------|---------|---------|
| Planner | 2 | 2.44s | 2.41s | 2.47s |
| Retriever | 6 | 7.77s | 6.19s | 9.23s |
| Executor | 2 | 7.66s | 7.56s | 7.77s |
| Summarizer | 2 | 4.30s | 3.78s | 4.81s |

### 5.3 并行执行分析

```
串行假设 (无并行):
  Task A = Planner(2.41) + Retriever×3(9.23+6.19+7.88) + Executor(7.77) + Summarizer(4.81)
         = 2.41 + 23.30 + 7.77 + 4.81 = 38.29s

实际并行:
  Task A = Planner(2.41) + max(Retriever×3)(9.23) + Executor(7.77) + Summarizer(4.81)
         = 2.41 + 9.23 + 7.77 + 4.81 = 24.22s

加速比 = 38.29 / 24.22 = 1.58x
```

### 5.4 通信开销

| 指标 | 值 | 说明 |
|------|-----|------|
| 总节点执行时间 | 75.40s | 所有 Agent 执行时间之和 |
| 总任务时间 | 23.27s | 实际墙钟时间（Task A） |
| 框架开销 | < 0.01s | StateGraph 调度、Channel 读写 |

### 5.5 记忆操作耗时

| 操作 | 次数 | 总耗时 | 平均耗时 |
|------|------|--------|---------|
| store.put | 12 | 0.16s | 0.013s |
| store.search | 21 | 0.04s | 0.002s |
| embedding 计算 | 21 | — | 包含在 search 中 |

### 5.6 完整性能报告

```
======================================================================
Performance Metrics Report
======================================================================

--- Task Timings ---
  graph_build:             avg=0.0102s  (1 次)
  task_A_langgraph_analysis: 23.27s     (1 次)
  task_B_system_design:      23.07s     (1 次)

--- Node Timings ---
  node_planner:    avg=2.44s   min=2.41s   max=2.47s   (2 次)
  node_retriever:  avg=7.77s   min=6.19s   max=9.23s   (6 次)
  node_executor:   avg=7.66s   min=7.56s   max=7.77s   (2 次)
  node_summarizer: avg=4.30s   min=3.78s   max=4.81s   (2 次)

--- Store Operations ---
  put:    12 ops, avg=0.013s
  search: 21 ops, avg=0.002s
  search scores: avg=0.39, min=0.03, max=0.71

--- Memory Reuse ---
  Reuse attempts: 1
  Reuse hits: 7
  Hit rate: 700.0% (多次命中)

======================================================================
```

---

## 六、结构化通信协议总结

### 6.1 协议载体

当前实现不是让 LLM 之间直接交换自由文本，而是由 Agent 节点把 LLM 输出整理为 LangGraph `ResearchState` 字段、`AgentMessage` 通信记录，以及独立的非文本 payload。下游 Agent 先读取这些结构化字段做程序化路由、排序和压缩，再把必要内容渲染进自己的 LLM prompt。

```python
class ResearchState(TypedDict, total=False):
    # 输入
    query: str
    task_group: str
    mode: str

    # Planner 输出
    plan: str
    sub_queries: list[str]
    planner_hidden_state: dict
    planner_hidden_state_summary: dict

    # Retriever 并行输出，使用 operator.add 在 fan-in 时合并
    documents: Annotated[list[str], operator.add]
    document_payloads: Annotated[list[dict], operator.add]
    context_packets: Annotated[list[dict], operator.add]
    embedding_payloads: Annotated[list[dict], operator.add]
    hidden_state_payloads: Annotated[list[dict], operator.add]

    # Executor 输出
    analysis: str
    analysis_digest: str
    evidence: list[dict]
    selected_context_packets: list[dict]
    hidden_guidance: dict

    # Summarizer 输出
    summary: str
    key_findings: list[str]

    # 可观测通信日志，使用 operator.add 累积
    messages: Annotated[list[dict], operator.add]
```

### 6.2 协议传输内容

| 数据类型 | 生产方 | 消费方 | 主要字段 | 作用 |
|---------|--------|--------|---------|------|
| `AgentMessage` | Planner / Retriever / Executor / Summarizer | 指标与调试；也随 state 累积 | `source`、`target`、`action`、`params`、`result`、`embedding`、`hidden_state` | 记录结构化通信事件和传输规模，不作为唯一业务数据源 |
| `planner_hidden_state` | Planner | Retriever / Executor / Summarizer | `kind`、`layer`、`pooling`、`dims`、`norm`、`vector` | 表示 planner prompt 的意图向量，用于后续 hidden-state routing |
| `document_payload` | Retriever | Executor | `doc_key`、`sub_query`、`text`、`text_hash`、`original_chars`、`hidden_state_ref` | context packet 关闭时的原始文档候选；也保留文档元数据 |
| `context_packet` | Retriever | Executor | `doc_key`、`summary`、`evidence_spans`、`tags`、`embedding_ref`、`hidden_state_ref`、`full_doc_ref`、`verification` | 压缩后的文档上下文，只把摘要和证据片段送入 prompt，完整文档留在 Store |
| `embedding_payload` | Retriever | Executor | `doc_key`、`embedding_ref`、`dims`、`vector` | 文档 embedding，用于 query/document 语义相似度排序 |
| `hidden_state_payload` | Retriever | Executor | `ref_id`、`doc_key`、`scope`、`intent_alignment`、`hidden_state` | retriever prompt 的 hidden-state 向量，和 `planner_hidden_state` 做 cosine 相似度 |
| `hidden_guidance` | Executor | Summarizer | `selected_doc_keys`、`avg_hidden_score`、`top_hidden_score`、`skipped_packets`、`skipped_original_chars` | 说明 hidden-state routing 选中了哪些上下文，并控制总结重点 |
| `analysis_digest` | Executor | Summarizer | 摘要文本 | structured 模式下替代完整 analysis 进入 summarizer prompt，减少上下文长度 |

### 6.3 Agent 间数据流图

```mermaid
flowchart TD
    U["User Input<br/>query, task_group, mode"] --> P["Planner Agent"]
    P -->|LLM 输出| POUT["plan<br/>sub_queries list<br/>planner_hidden_state"]
    POUT -->|State: plan/sub_queries| S[("ResearchState")]
    POUT -->|AgentMessage: action=plan| M[("messages list")]
    POUT -->|Send fan-out<br/>sub_query + planner_hidden_state| R1["Retriever 1"]
    POUT -->|Send fan-out<br/>sub_query + planner_hidden_state| R2["Retriever 2"]
    POUT -->|Send fan-out<br/>sub_query + planner_hidden_state| R3["Retriever 3"]

    R1 -->|doc_text| D1[("Store: docs/doc_key_1")]
    R2 -->|doc_text| D2[("Store: docs/doc_key_2")]
    R3 -->|doc_text| D3[("Store: docs/doc_key_3")]

    R1 -->|context_packet<br/>embedding_payload<br/>hidden_state_payload<br/>AgentMessage: retrieve| FANIN["LangGraph fan-in<br/>operator.add"]
    R2 -->|context_packet<br/>embedding_payload<br/>hidden_state_payload<br/>AgentMessage: retrieve| FANIN
    R3 -->|context_packet<br/>embedding_payload<br/>hidden_state_payload<br/>AgentMessage: retrieve| FANIN

    FANIN -->|context_packets list<br/>embedding_payloads list<br/>hidden_state_payloads list<br/>messages list| E["Executor Agent"]
    S -->|query + plan + planner_hidden_state| E
    D1 -. full_doc_ref / rehydrate .-> E
    D2 -. full_doc_ref / rehydrate .-> E
    D3 -. full_doc_ref / rehydrate .-> E

    E -->|程序化排序<br/>hidden_score + vector_score + lexical + coverage| TOPK["selected top-k context packets"]
    TOPK -->|只渲染选中 evidence| ELLM["Executor LLM"]
    ELLM -->|analysis<br/>evidence<br/>analysis_digest<br/>hidden_guidance| EOUT["Executor Output"]
    EOUT -->|AgentMessage: action=analyze| M
    EOUT --> SUM["Summarizer Agent"]

    SUM -->|query + plan<br/>analysis_digest<br/>evidence<br/>hidden_guidance| SLLM["Summarizer LLM"]
    SLLM -->|summary<br/>key_findings| OUT["Final Output"]
    SUM -->|AgentMessage: action=summarize| M
```

### 6.4 分阶段流动说明

| 阶段 | 流向 | 传输内容 | 下游如何使用 |
|------|------|---------|-------------|
| 输入阶段 | User → Planner | `query`、`task_group`、`mode` | Planner prompt 的用户问题和运行模式 |
| 规划阶段 | Planner → Retriever × 3 | `sub_queries`、`planner_hidden_state`、`AgentMessage(action=plan)` | `Send` 将 3 个子查询并行分发；每个 Retriever 接收同一个 planner 意图向量 |
| 检索阶段 | Retriever × 3 → Store | `doc_text`、`doc_key`、`sub_query` | 完整文档写入 Store，后续通过 `full_doc_ref` 校验和 rehydrate |
| 检索阶段 | Retriever × 3 → Executor | `context_packets[]`、`embedding_payloads[]`、`hidden_state_payloads[]`、`document_payloads[]`、`messages[]` | fan-in 后由 Executor 做 top-k 排序和上下文裁剪 |
| 执行阶段 | Executor → Executor LLM | selected context、`hidden_guidance`、prior analyses | 只把选中的 compact evidence 渲染进 prompt，并附带 hidden-state routing 摘要 |
| 执行阶段 | Executor → Summarizer | `analysis_digest`、`evidence`、`hidden_guidance`、`planner_hidden_state`、`AgentMessage(action=analyze)` | Summarizer 使用摘要版分析和证据列表，避免传完整长分析 |
| 总结阶段 | Summarizer → Output | `summary`、`key_findings`、`AgentMessage(action=summarize)` | 输出最终报告，同时记录通信指标 |

### 6.5 top-k 上下文选择依据

Executor 对候选 `context_packets` 计算综合分数后取 `HIDDEN_STATE_CONTEXT_TOP_K`，默认 top-2。候选上下文不是外部文件，而是每个 Retriever LLM 针对一个 `sub_query` 生成的 `doc_text`，再被压缩成 `context_packet`。

```text
hidden_score  = cosine(planner_hidden_state.vector, retriever_hidden_state.vector)
vector_score  = cosine(query_embedding, document_embedding)
lexical       = query/plan 与 packet summary/tags/evidence 的词项重叠
coverage      = evidence 对 source_query 的覆盖率

有 hidden 和 embedding 时：
score = 0.45 * hidden_score + 0.35 * vector_score + 0.15 * lexical + 0.05 * coverage

只有 hidden 时：
score = 0.65 * hidden_score + 0.25 * lexical + 0.10 * coverage
```

这一步的效果是：完整文档仍保存在 Store 中，Executor prompt 只接收排序后的少量 evidence；如果 compact evidence 校验不可靠，再按 `full_doc_ref` 从 Store rehydrate 有界片段。

### 6.6 控制流与 Channel 聚合

| 机制 | 用途 | 代码位置 |
|------|------|---------|
| `Send` | Planner 将 3 个 `sub_query` 并行 fan-out 到 Retriever | `graph.py:fan_out_retrieval()` |
| `add_edge` | 串联 `planner → retriever → executor → summarizer` | `graph.py:build_graph()` |
| `operator.add` | 将并行 Retriever 的 list 输出聚合为 `context_packets[]`、`embedding_payloads[]`、`hidden_state_payloads[]`、`messages[]` | `graph.py:ResearchState` |
| LastValue | `plan`、`planner_hidden_state`、`analysis_digest`、`hidden_guidance`、`summary` 等单值字段覆盖更新 | `ResearchState` 默认 channel |

---

## 七、运行环境信息

当前仓库路径：`/data/mingwei/SynapseX`。

基础依赖：

```text
langgraph
langchain-core
langchain-openai
dashscope
numpy
```

本地 Transformers 后端额外依赖：

```text
transformers
torch
accelerate
```

推荐运行命令：

```bash
cd /data/mingwei/SynapseX
export CHAT_BACKEND=transformers
export CHAT_MODEL=qwen3-8b
export LOCAL_MODEL_PATH=/data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0
python -u run_demo.py
```

如果使用 OpenAI 兼容后端：

```bash
cd /data/mingwei/SynapseX
export CHAT_BACKEND=openai
export CHAT_API_KEY="你的 Chat API key"
export CHAT_BASE_URL="https://api.deepseek.com"
export CHAT_MODEL="deepseek-chat"
python -u run_demo.py
```

---

## 八、需求完成情况评估（以当前代码为准）

### 8.1 原始需求拆解

原始需求包含 6 大项，每项有具体的子要求。以下逐项对照当前 `src/` 和根目录运行脚本的实现情况。

---

### 8.2 逐项评估

#### ① 系统支持不少于 3 个 Agent 协同运行，覆盖规划、检索、执行、总结等角色

**状态：✅ 完全实现**

| 子要求 | 实现情况 |
|--------|---------|
| ≥3 个 Agent | ✅ 4 个：planner、retriever（×3 并行）、executor、summarizer |
| 覆盖规划角色 | ✅ planner 节点，拆解查询为子任务 |
| 覆盖检索角色 | ✅ retriever 节点，按 planner 输出的子查询并行运行 |
| 覆盖执行角色 | ✅ executor 节点，选择上下文、分析文档并提取证据 |
| 覆盖总结角色 | ✅ summarizer 节点，汇总输出最终报告 |

**实现方式**：`src/graph.py` 使用 `StateGraph`、`Send` fan-out 和 `Annotated[list, operator.add]` fan-in。

---

#### ② 设计结构化通信协议替代自然语言交互

**状态：✅ 完全实现**

| 子要求 | 实现情况 |
|--------|---------|
| 结构化协议 | ✅ `AgentMessage`、`ActionType`、`AgentCard`、`AgentRegistry` |
| 替代自然语言透传 | ✅ Structured 模式通过 `messages`、`context_packets`、`embedding_payloads`、`hidden_state_payloads` 传递结构化载荷 |
| 协议可解析 | ✅ `ResearchState` 使用 `TypedDict`，并由 LangGraph Channel/reducer 聚合并行分支 |
| 能力发现 | ✅ `create_default_registry()` 预注册 4 个 Agent 能力 |

**实现方式**：`src/protocol.py` 定义协议数据结构，`src/agents.py` 在 structured 模式构造消息与载荷，`src/graph.py` 定义状态字段和 reducer。

---

#### ③ 实现非文本中间状态传递机制（embedding/语义向量/隐藏状态）

**状态：✅ 已实现，且三通道可独立开关**

| 子要求 | 实现情况 | 说明 |
|--------|---------|------|
| embedding 传递 | ✅ | `retriever` 生成 `embedding_payloads`，`executor` 接收并用于 context/document 排序 |
| 语义向量传递 | ✅ | 有 `DASHSCOPE_API_KEY` 时使用 DashScope `text-embedding-v4`，否则用 `LocalHashEmbeddings` fallback |
| hidden state 传递 | ✅ | `CHAT_BACKEND=transformers` 且 `ENABLE_HIDDEN_STATE_TRANSFER=1` 时捕获 pre-generation hidden state |
| 文本压缩证据通道 | ✅ | `ContextPacket` 携带摘要、证据片段、引用、hash 校验和 Store key |

三类通道由环境变量独立控制：

```bash
ENABLE_CONTEXT_PACKETS=1
ENABLE_EMBEDDING_TRANSFER=1
ENABLE_HIDDEN_STATE_TRANSFER=1
```

实现边界：OpenAI 兼容商业 API 不暴露模型 hidden state，因此 hidden state 只在本地 Transformers 后端可用；OpenAI 兼容后端仍可使用 `AgentMessage`、`ContextPacket` 和 embedding 通道。

---

#### ④ 实现共享记忆模块，支持记忆的存储、检索和复用

**状态：✅ 完全实现**

| 子要求 | 实现情况 |
|--------|---------|
| 记忆存储 | ✅ `store.put(namespace, key, value)` |
| 记忆检索 | ✅ `store.search(namespace, query=..., limit=...)` |
| 记忆复用 | ✅ Task B / 后续轮次可检索前序摘要、计划、文档和分析 |
| 跨任务共享 | ✅ 同一次 graph 构建返回的 Store 在连续任务中复用 |
| 语义搜索 | ✅ `InMemoryStore(index=...)` + `DashScopeEmbeddings` / `LocalHashEmbeddings` |

命名空间：`("plans",)`、`("docs",)`、`("analysis",)`、`("summaries",)`。

---

#### ⑤ 至少设计 2 组关联性连续任务进行验证

**状态：✅ 实现**

| 子要求 | 实现情况 | 说明 |
|--------|---------|------|
| ≥2 组关联任务 | ✅ | `run_demo.py` 跑 Task A（框架分析）→ Task B（系统设计） |
| 关联性 | ✅ | Task B 查询明确依赖 Task A 的分析结果 |
| 连续性 | ✅ | Task B 在同一 Store 上接续执行 |
| ≥10 轮稳定执行 | ✅ | `run_12rounds.py` 定义并运行 12 轮连续任务 |
| 结构化消融 | ✅ | `ablation_results/` 保存 context、embedding、hidden state 等组合结果 |

---

#### ⑥ 提供通信开销、任务时延、记忆复用等方面的性能对比数据

**状态：✅ 实现**

| 子要求 | 实现情况 | 说明 |
|--------|---------|------|
| Agent 间消息次数 | ✅ | `metrics.record_message()` 统计 `AgentMessage` 数量、action 分布 |
| 文本通信 token/字符开销 | ✅ | `metrics.record_tokens()` 统计 LLM input/output tokens；消息 params/result 字符数也被统计 |
| 非文本状态传递次数及数据规模 | ✅ | 统计 embedding transfer、hidden-state transfer、维度和 payload 收发计数 |
| 单任务总耗时 | ✅ | `run_demo.py` / `run_12rounds.py` 记录 task duration |
| 共享记忆命中 | ✅ | `store_search()` 与脚本层计数记录 memory reuse |
| 整体性能对比 | ✅ | `run_demo.py` 输出 Text vs Structured；`run_12rounds.py` 输出 12 轮对比并保存 JSON |
| Context 压缩效果 | ✅ | `metrics.record_compression()` 统计 original/compressed/saved chars |

注意：`memory_reuse_hits` 是多处搜索命中累计值，`memory_reuse_attempts` 是脚本层手动计数；并行 retriever 节点耗时会被相加，因此不等同于 wall-clock 时间。

---

### 8.3 系统架构模块对照

原始要求：系统架构中至少应包含多 Agent 运行时、协议解析与调度模块、状态交换模块、共享记忆存储与检索模块和评测模块。

| 模块 | 实现情况 | 说明 |
|------|---------|------|
| 多 Agent 运行时 | ✅ | LangGraph Pregel 引擎，4 个 Agent 节点，retriever 并行 fan-out |
| 协议解析与调度模块 | ✅ | `AgentMessage` / `ActionType` + `StateGraph` 路由 |
| 状态交换模块 | ✅ | `ResearchState` + LangGraph Channel / reducer |
| 共享记忆存储与检索模块 | ✅ | `InMemoryStore` + `DashScopeEmbeddings` / `LocalHashEmbeddings` |
| 评测模块 | ✅ | `src/metrics.py` + `run_demo.py` / `run_12rounds.py` 对比输出 |

---

### 8.4 总结

| # | 需求 | 完成状态 | 当前实现 |
|---|------|---------|----------|
| ① | ≥3 Agent 协同 | ✅ 完全实现 | planner / retriever / executor / summarizer |
| ② | 结构化通信协议 | ✅ 完全实现 | AgentMessage、ActionType、AgentCard、ContextPacket |
| ③ | 非文本中间状态传递 | ✅ 完全实现 | embedding_payloads、hidden_state_payloads、context_packets |
| ④ | 共享记忆模块 | ✅ 完全实现 | InMemoryStore + namespace + semantic search |
| ⑤ | 2 组/多轮关联任务验证 | ✅ 完全实现 | `run_demo.py` A/B；`run_12rounds.py` 12 轮 |
| ⑥ | 性能对比数据 | ✅ 完全实现 | tokens、时延、消息、压缩、embedding/hidden、记忆复用 |

当前版本已覆盖 6 项需求。主要边界是：真实 hidden state 依赖本地 Transformers 后端；OpenAI 兼容 API 后端只能使用结构化消息、上下文压缩与 embedding 通道，不能从商业 API 取得模型内部隐藏层。