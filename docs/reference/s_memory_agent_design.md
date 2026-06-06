# 面向多智能体协作的低开销通信、状态传递与共享记忆机制：实现方案设计文档

> 适用赛题：一种面向多智能体协作的低开销通信、状态传递与共享记忆机制  
> 推荐项目名：**S-MemoryAgent**  
> 核心目标：构建一套可运行、可复现、可评测的多 Agent 协作系统原型，重点验证结构化通信、非文本状态传递和共享记忆复用相较纯文本协作模式的效率提升。

---

## 摘要

本方案面向多智能体协作系统中的基础设施问题，设计一个名为 **S-MemoryAgent** 的原型系统。系统不以简单工作流编排为核心，而是围绕 Agent 间的底层协作机制展开，包括结构化通信协议、非文本语义状态交换、共享记忆沉淀与跨任务复用，以及可复现实验评测。

系统采用“三层协作机制”：

- **控制面：SACP 结构化通信协议**  
  将 Agent 间长自然语言消息压缩为 `action`、`params`、`result`、`capability`、`state_ref`、`memory_ref` 等高密度语义字段。

- **数据面：State Capsule 非文本状态胶囊**  
  Agent 间默认传递 embedding、向量引用、证据块引用、工具结果句柄等中间表示，避免每轮协作反复进行“内部状态—文本—内部状态”的转换。

- **记忆面：Shared Memory Graph 共享记忆层**  
  将任务执行过程中的摘要、证据、策略、代码片段、失败经验和结论沉淀为可标识、可检索、可复用的记忆单元，使后续关联任务能够直接复用历史经验。

系统支持 **纯文本协作模式** 与 **结构化协议协作模式**，并进一步支持结构化协议加状态传递、结构化协议加状态传递加共享记忆的消融实验。通过两组连续任务和不少于 10 轮稳定运行，量化对比消息次数、文本 token/字符开销、结构化消息字节数、状态传递次数、状态数据规模、任务耗时、共享记忆命中率和整体性能提升。

---

## 设计定位与创新点

### 项目定位

该赛题的重点不是“让多个 Agent 按顺序调用工具”，而是研究多 Agent 协作中的系统层机制。因此，本方案将系统定位为一个轻量级多 Agent 协作运行时，而不是简单套用现有 Agent 框架。

系统需要回答以下问题：

1. Agent 之间是否可以不再依赖冗长自然语言传递中间结果？
2. 中间语义状态是否可以以向量、引用、句柄等形式直接在 Agent 间流转？
3. 历史任务中的中间知识、策略和经验是否能够成为后续任务的可复用资产？
4. 这些机制是否能被量化证明有效，而不是只停留在设计描述？

### 核心创新

**创新一：控制面与数据面分离的 Agent 通信架构**

传统多 Agent 系统通常通过自然语言消息传递完整上下文。本方案将通信拆成两个平面：

```text
控制面：SACP 结构化消息
数据面：State Capsule / Artifact Ref / Memory Ref
```

控制面只传递动作、参数、结果状态和引用；数据面保存 embedding、证据块、执行产物和记忆对象。这样可以减少重复文本传输，并提升消息的机器可解析性。

**创新二：State Capsule 语义状态胶囊**

系统不只是“使用 embedding”，而是将非文本中间状态封装为具有元数据、生产者、编码模型、数据类型、存储位置和哈希校验的状态对象。Agent 之间默认传递 `state_id`，接收方按需读取向量或展开原始证据。

**创新三：记忆感知调度**

PlannerAgent 在规划任务前先检索共享记忆。如果历史记忆已经包含可靠策略、证据或代码模板，系统可以跳过部分检索、分析或代码生成步骤。记忆不只是被查到，还会在计划和结果中显式记录 `reused_memory_ids`，从而可量化验证复用效果。

**创新四：相似度门控文本展开**

结构化模式下，Agent 默认只传递状态引用和摘要摘要。当任务向量与证据向量相似度超过阈值时，系统不再展开全文；当置信度不足时才请求补充文本。该机制在准确性与通信开销之间提供动态平衡。

---

## 相关技术依据与可借鉴项目

### 论文与技术方向

本方案参考近期多 Agent、Agent 通信优化、状态化工作流、代码动作、长期记忆等方向的研究。需要注意的是，CCF 推荐目录是会议和期刊目录，不是单篇论文清单；在最终报告中应根据最新版 CCF 目录核对论文发表会议/期刊等级。中国计算机学会已发布第七版推荐国际学术会议和期刊目录，本文只将其作为会议等级参考来源。[^ccf]

| 方向 | 代表工作 | 可借鉴点 | 本项目中的用法 |
|---|---|---|---|
| 多 Agent 框架 | AutoGen | 多 Agent 可对话协作、Agent 可定制 | 作为纯文本多 Agent baseline 的参考，不直接照搬其对话式通信 |
| 多 Agent 平台 | AgentScope | 消息交换、Agent 服务、监控、分布式 actor | 参考运行时、监控和服务化思路 |
| Agent 互操作协议 | A2A Protocol | Agent 能力发现、任务生命周期、结构化数据交换 | 借鉴 Agent Card、能力注册、任务状态等概念 |
| 工具协议 | MCP | 将工具以标准接口暴露给模型或 Agent | 用于 ExecutorAgent 的工具注册和调用抽象 |
| 通信剪枝 | AgentPrune | 多 Agent 通信中存在大量冗余，可通过拓扑剪枝降低 token 开销 | 作为通信效率优化的学术依据 |
| 状态化工作流 | StateFlow | 将复杂任务求解建模为状态机，提高可控性和效率 | 用于 Planner/Scheduler 的任务状态设计 |
| 并行函数调用 | LLMCompiler | 将计划、任务分发和执行分离，识别可并行执行步骤 | 用于任务 DAG 编译与并行调度 |
| 代码动作 | CodeAct | 使用可执行 Python 代码作为统一动作空间 | 用于 ExecutorAgent / CodeActAgent 沙箱执行 |
| 长期记忆 | MemGPT | 借鉴操作系统分层内存和虚拟上下文管理 | 用于共享记忆分层和按需加载 |
| 时态知识图谱记忆 | Zep / Graphiti | 将 Agent 记忆建成时间感知知识图谱 | 用于 Shared Memory Graph 的扩展设计 |
| 向量检索 | FAISS / Milvus / Qdrant | 向量相似度检索和元数据过滤 | 用于记忆和证据的语义检索 |

### 可借鉴开源项目

| 项目 | 适合借鉴的部分 | 本项目避免的问题 |
|---|---|---|
| AutoGen | Agent 抽象、对话协作、工具调用 | 不把自然语言对话作为唯一通信机制 |
| AgentScope | 多 Agent 服务化、监控、分布式支持 | 不只做框架调用，而要实现自己的协议与评测 |
| LangGraph | 状态图、节点边、持久化状态 | 不把 LangGraph 当作最终贡献，只借鉴状态图思想 |
| Letta / MemGPT | 记忆管理、长期状态、上下文分页 | 不只做个人记忆，而做多 Agent 共享记忆 |
| Graphiti | 时间感知知识图谱 | 初版可不用图数据库，但保留图谱扩展接口 |
| FAISS | 本地向量索引 | 注意与 SQLite 元数据联动 |
| Qdrant / Milvus | 生产级向量数据库 | MVP 可先用 FAISS，增强版再替换 |

---

## 总体架构

系统整体采用模块化架构，由多 Agent 运行时、协议层、状态交换层、共享记忆层、工具层和评测层组成。

```text
┌──────────────────────────────────────────────────────────────┐
│                         Evaluation Harness                    │
│  token/字符/字节统计 | 延迟统计 | 状态规模 | 记忆命中率 | 成功率 │
└──────────────────────────────────────────────────────────────┘
                                │
┌──────────────────────────────────────────────────────────────┐
│                         Multi-Agent Runtime                   │
│  Agent Registry | Scheduler | Trace Manager | Mode Switch      │
└──────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
┌──────────────────┐  ┌──────────────────────┐  ┌────────────────────────┐
│ Protocol Layer   │  │ State Exchange Layer  │  │ Shared Memory Layer     │
│ SACP Parser      │  │ State Capsule Store   │  │ SQLite/Postgres + FAISS │
│ MsgPack/JSON     │  │ Embedding / Ref       │  │ Memory Graph            │
│ Capability       │  │ Shared Memory / mmap  │  │ Hybrid Retrieval        │
└──────────────────┘  └──────────────────────┘  └────────────────────────┘
                                │
┌──────────────────────────────────────────────────────────────┐
│                              Agents                           │
│ Planner | Retriever | Executor/CodeAct | Summarizer | Memory  │
└──────────────────────────────────────────────────────────────┘
                                │
┌──────────────────────────────────────────────────────────────┐
│                              Tools                            │
│ Local Search | File Parser | Python Sandbox | CSV/SQL | Report │
└──────────────────────────────────────────────────────────────┘
```

### 模块职责

| 模块 | 职责 |
|---|---|
| Multi-Agent Runtime | Agent 注册、能力发现、消息路由、任务调度、运行模式切换、Trace 记录 |
| Protocol Layer | 定义并解析结构化消息，完成 JSON Schema 校验、MessagePack 序列化、协议映射 |
| State Exchange Layer | 管理 embedding、状态引用、证据引用、工具结果引用和二进制状态数据 |
| Shared Memory Layer | 记忆写入、记忆检索、记忆去重、记忆复用统计、记忆生命周期管理 |
| Tool Layer | 文档检索、CSV 分析、Python 沙箱、报告生成、可选 SQL 查询 |
| Evaluation Harness | 自动运行多组任务，统计通信开销、耗时、状态传递和记忆复用指标 |

---

## Agent 角色设计

系统至少实现四类 Agent，并可扩展 MemoryAgent 和 EvaluatorAgent。

| Agent | 角色 | 主要动作 |
|---|---|---|
| PlannerAgent | 任务规划 | 任务拆解、能力查询、记忆检索、DAG/状态机生成 |
| RetrieverAgent | 信息检索 | 文档检索、语义检索、证据块生成、证据状态写入 |
| ExecutorAgent / CodeActAgent | 工具执行 | Python 代码执行、CSV 分析、指标计算、结果产物保存 |
| SummarizerAgent | 总结生成 | 综合证据、工具结果和记忆，生成最终报告并写入新记忆 |
| MemoryAgent | 共享记忆管理 | 记忆写入、检索、去重、合并、复用统计 |
| EvaluatorAgent | 评测与质量检查 | 检查结果完整性、证据充分性、任务成功分 |

### 典型协作流程

```text
用户任务
  ↓
PlannerAgent 检索共享记忆并生成计划
  ↓
Scheduler 根据计划调用 RetrieverAgent / ExecutorAgent
  ↓
RetrieverAgent 返回 evidence_ref 与 state_id
  ↓
ExecutorAgent 执行工具或 CodeAct 代码，返回 artifact_ref
  ↓
SummarizerAgent 按需读取证据、状态和产物，生成答案
  ↓
MemoryAgent 将摘要、证据、策略、代码模板、失败经验写入共享记忆
  ↓
Evaluation Harness 记录指标
```

---

## 结构化通信协议 SACP

### 协议目标

SACP，即 **Structured Agent Collaboration Protocol**，用于替代 Agent 间冗长自然语言协作消息。它需要满足以下要求：

- 支持握手和能力发现；
- 支持动作调用、参数传递、结果返回；
- 支持状态引用和记忆引用；
- 支持错误处理和任务追踪；
- 可同时映射到纯文本模式和结构化模式；
- 可统计序列化字节数和文本 token 开销。

### 消息类型

```text
HELLO                  Agent 上线握手
CAPABILITY_ADVERTISE   Agent 能力广播
CAPABILITY_QUERY       能力查询
TASK_CREATE            创建任务
ACTION_CALL            调用某个 Agent 动作
ACTION_RESULT          返回动作结果
STATE_PUT              注册非文本状态
STATE_GET              获取非文本状态
MEMORY_SEARCH          检索共享记忆
MEMORY_WRITE           写入共享记忆
ERROR                  错误消息
HEARTBEAT              心跳
```

### 通用消息 Envelope

```json
{
  "protocol": "SACP/0.1",
  "msg_id": "msg_20260528_0001",
  "trace_id": "trace_task_001",
  "task_id": "task_001",
  "src": "PlannerAgent",
  "dst": "RetrieverAgent",
  "msg_type": "ACTION_CALL",
  "timestamp": "2026-05-28T10:00:00+09:00",
  "body": {}
}
```

### 动作调用消息

```json
{
  "protocol": "SACP/0.1",
  "msg_type": "ACTION_CALL",
  "src": "PlannerAgent",
  "dst": "RetrieverAgent",
  "body": {
    "action": "retrieve.evidence",
    "params": {
      "query_state_id": "state_task_embedding_001",
      "query_text_digest": "sha256:xxxx",
      "top_k": 5,
      "filters": {
        "tags": ["multi-agent", "protocol"]
      }
    },
    "expected_result_schema": "EvidenceRefList"
  }
}
```

### 动作结果消息

```json
{
  "protocol": "SACP/0.1",
  "msg_type": "ACTION_RESULT",
  "src": "RetrieverAgent",
  "dst": "PlannerAgent",
  "body": {
    "action": "retrieve.evidence",
    "status": "ok",
    "result": {
      "evidence_refs": [
        {
          "evidence_id": "ev_001",
          "doc_id": "doc_003",
          "chunk_id": "chunk_12",
          "state_id": "state_vec_203",
          "score": 0.91
        }
      ],
      "brief": "命中 5 个高相关证据块"
    }
  }
}
```

### 能力描述

```json
{
  "agent_id": "ExecutorAgent",
  "role": "execution",
  "capabilities": [
    {
      "name": "tool.run_python",
      "input_schema": "PythonExecutionRequest",
      "output_schema": "PythonExecutionResult",
      "cost_hint": {
        "latency_ms_p50": 500,
        "text_tokens": 0
      }
    },
    {
      "name": "tool.analyze_csv",
      "input_schema": "CSVAnalysisRequest",
      "output_schema": "CSVAnalysisResult"
    }
  ],
  "state_supported": [
    {
      "type": "embedding",
      "dim": 768,
      "dtype": "float16"
    },
    {
      "type": "artifact_ref",
      "formats": ["json", "csv", "png"]
    }
  ]
}
```

能力发现流程如下：

```text
Runtime 启动
  → Agent 发送 HELLO
  → Agent 发送 CAPABILITY_ADVERTISE
  → AgentRegistry 保存能力表
  → PlannerAgent 根据能力表选择可用 Agent
```

---

## 非文本状态传递机制

### State Capsule 定义

State Capsule 是系统中的非文本中间状态对象，用于在 Agent 间传递 embedding、语义向量、执行结果特征或证据引用。Agent 间不直接传完整向量或全文，而是传递 `state_id`。

```json
{
  "state_id": "state_000123",
  "type": "embedding",
  "producer_agent": "RetrieverAgent",
  "created_at": "2026-05-28T10:01:00+09:00",
  "encoder": {
    "model": "bge-small-zh-v1.5",
    "dim": 512,
    "normalize": true
  },
  "payload": {
    "storage": "shared_memory",
    "uri": "shm://sma/state_000123",
    "dtype": "float16",
    "shape": [512],
    "bytes": 1024,
    "hash": "sha256:xxxx"
  },
  "metadata": {
    "topic": "多 Agent 结构化通信",
    "tags": ["protocol", "multi-agent"],
    "source_ref": "doc_003:chunk_12",
    "summary_digest": "结构化协议字段应包含 action、params、result、capability、trace_id"
  }
}
```

### 状态生成、传递与使用

| 阶段 | 实现方式 |
|---|---|
| 生成 | Planner 对任务摘要生成 task embedding；Retriever 对证据块生成 evidence embedding；Executor 对运行结果摘要生成 result embedding；Summarizer 对结论生成 conclusion embedding |
| 存储 | MVP 使用 `numpy` 文件、SQLite 元数据和 FAISS 索引；增强版可使用共享内存、mmap、Qdrant 或 Milvus |
| 传递 | SACP 消息中只传 `state_id`、`state_type`、`bytes`、`hash` 和摘要 digest |
| 接收 | 接收 Agent 根据 `state_id` 从 StateStore 读取向量或元数据 |
| 后续使用 | 用于相似度筛选、证据排序、按需文本展开、记忆检索和计划剪枝 |

### 相似度门控文本展开

结构化模式中，Agent 不默认展开所有文本。系统根据任务向量和证据向量的相似度决定是否读取原文：

```text
similarity >= 0.82:
    只传 state_ref + evidence_ref + brief
0.65 <= similarity < 0.82:
    传 state_ref + evidence_ref + compact summary
similarity < 0.65:
    请求 Retriever 补充详细文本或重新检索
```

该机制的评测指标包括：

- 非文本状态传递次数；
- 状态传递总字节数；
- 原始文本字节数与状态字节数压缩比；
- 按需展开文本次数；
- 状态筛选后最终使用的证据数量。

---

## 共享记忆模块

### 记忆单元设计

共享记忆不是原始聊天记录，也不是普通日志，而是经过结构化整理的可复用知识单元。每条记忆至少包含赛题要求的基本元数据：

- `memory_id`
- `source_agent`
- `created_at`
- `task_topic`
- `summary`

建议扩展字段如下：

```json
{
  "memory_id": "mem_20260528_0001",
  "source_agent": "SummarizerAgent",
  "created_at": "2026-05-28T10:30:00+09:00",
  "task_id": "task_001",
  "task_topic": "多 Agent 结构化通信机制设计",
  "memory_type": "StrategyMemory",
  "tags": ["multi-agent", "protocol", "low-overhead"],
  "summary": "结构化通信协议应将 Agent 间消息压缩为 action、params、result、capability、state_ref 和 memory_ref。",
  "content": {
    "problem": "纯文本协作传递大量重复上下文，token 开销高",
    "solution": "使用 SACP 协议传递动作、参数、结果和状态引用",
    "evidence_refs": ["ev_001", "ev_002"],
    "reuse_hint": "后续涉及 Agent 通信协议设计时优先复用"
  },
  "embedding_id": "state_mem_vec_0001",
  "confidence": 0.88,
  "reuse_count": 0,
  "last_used_at": null,
  "parent_memory_ids": []
}
```

### 记忆类型

| 类型 | 内容 | 复用场景 |
|---|---|---|
| EvidenceMemory | 检索到的可靠证据、文档片段、数据片段 | 后续相似任务减少重复检索 |
| SummaryMemory | 阶段性总结、最终报告摘要 | 后续任务快速理解历史结论 |
| StrategyMemory | 某类任务的解决步骤、规划经验 | Planner 复用任务拆解策略 |
| ExecutionMemory | 工具调用参数、代码模板、运行结果 | Executor 复用代码与参数 |
| ReflectionMemory | 失败原因、修复经验、注意事项 | 避免重复失败，提高稳定性 |

### 存储与检索

MVP 推荐实现：

```text
SQLite:
  memories 表
  memory_events 表
  tasks 表
  traces 表

FAISS:
  memory_vectors.index
  evidence_vectors.index

Blob Store:
  artifacts/
  evidence_chunks/
  execution_outputs/
```

增强版可以替换为：

```text
PostgreSQL + pgvector
Qdrant
Milvus
Graphiti / Neo4j
```

检索方式包括：

- **关键词检索**：基于 SQLite FTS 或 LIKE；
- **标签检索**：按 `tags`、`memory_type`、`source_agent` 过滤；
- **语义相似度检索**：query embedding 与 memory embedding 做 top-k 检索；
- **混合检索**：结合语义、关键词、标签、时效性和置信度。

建议混合打分公式：

```text
score = 0.55 * semantic_similarity
      + 0.20 * keyword_score
      + 0.15 * tag_match_score
      + 0.05 * recency_score
      + 0.05 * confidence_score
```

### 记忆复用判定

为避免“查到了但没用”的假复用，系统需要显式记录复用关系。

```json
{
  "plan_id": "plan_002",
  "reused_memory_ids": ["mem_20260528_0001", "mem_20260528_0004"],
  "skipped_steps": [
    {
      "step": "重新设计基础通信字段",
      "reason": "已复用 mem_20260528_0001"
    }
  ]
}
```

核心指标：

```text
memory_hit_rate = memory_hit_count / memory_search_count

memory_reuse_rate = memory_reuse_count / memory_hit_count

avg_reused_memory_per_task = memory_reuse_count / task_count
```

---

## 运行模式与对比基线

系统需要支持同一任务在不同模式下运行，以证明每个机制的单独贡献。

| 组别 | 通信方式 | 非文本状态 | 共享记忆 | 目的 |
|---|---|---|---|---|
| G1 Text Baseline | 纯文本 | 否 | 否 | 传统多 Agent 自然语言协作基线 |
| G2 Structured | SACP 结构化协议 | 否 | 否 | 验证结构化通信降低 token/字符开销 |
| G3 Structured + State | SACP | 是 | 否 | 验证非文本状态传递减少文本展开 |
| G4 Structured + State + Memory | SACP | 是 | 是 | 验证共享记忆减少重复检索、重复分析和任务耗时 |

### 纯文本模式示例

```text
PlannerAgent → RetrieverAgent:

请你围绕“多 Agent 结构化通信协议设计”检索相关资料。
请重点关注 action、params、result、capability、trace_id、memory_ref 等字段。
当前任务背景是……
请返回详细证据、来源摘要和推荐设计。
```

### 结构化模式示例

```json
{
  "msg_type": "ACTION_CALL",
  "src": "PlannerAgent",
  "dst": "RetrieverAgent",
  "body": {
    "action": "retrieve.evidence",
    "params": {
      "query_state_id": "state_task_vec_001",
      "top_k": 5,
      "filters": {
        "tags": ["multi-agent", "protocol"]
      }
    }
  }
}
```

---

## 连续任务设计

赛题要求至少设计 2 组有关联性的连续任务。建议设计两条任务链，每条 5 个任务，共 10 轮连续任务，既满足稳定运行要求，又能观察记忆逐步积累和复用的效果。

### 任务链 A：多 Agent 系统设计类任务

| 任务 | 描述 | 预期产生或复用的记忆 |
|---|---|---|
| A1 | 分析多 Agent 纯文本协作的通信开销问题，设计结构化协议字段 | 写入纯文本通信开销分析、SACP 基础字段设计 |
| A2 | 基于 A1 的结构化协议，为工具调用和 CodeAct 执行增加协议扩展 | 复用 A1 的协议字段，写入 CodeAct 扩展字段 |
| A3 | 为该协议增加能力发现和 Agent 握手机制 | 复用 A1 的 capability 字段设计 |
| A4 | 为该协议增加非文本状态传递机制 | 复用 A1 的“文本编解码开销”问题分析 |
| A5 | 生成完整系统设计报告 | 复用 A1-A4 的协议、工具、状态和能力发现记忆 |

### 任务链 B：数据分析与代码执行类任务

| 任务 | 描述 | 预期产生或复用的记忆 |
|---|---|---|
| B1 | 给定服务日志 CSV，分析接口延迟瓶颈，生成性能报告 | 写入日志分析流程和 Python 聚合代码模板 |
| B2 | 给定另一份格式相似的日志 CSV，分析慢请求原因 | 复用 B1 的日志分析策略和代码模板 |
| B3 | 在 B2 基础上增加错误码分析 | 复用字段解析与聚合逻辑 |
| B4 | 生成多版本性能对比报告 | 复用历史 latency 指标和分析模板 |
| B5 | 总结一套通用日志分析 Agent 工作流 | 复用 B1-B4 的策略、代码和失败经验 |

---

## 评测方案

### 统计指标

| 指标 | 含义 |
|---|---|
| `message_count` | Agent 间消息次数 |
| `text_chars` | Agent 间文本通信字符数 |
| `estimated_tokens` | 文本 token 估算值 |
| `structured_bytes` | 结构化消息序列化后的字节数 |
| `state_transfer_count` | 非文本状态传递次数 |
| `state_transfer_bytes` | 非文本状态总数据规模 |
| `state_compression_ratio` | 原始文本字节数 / 状态字节数 |
| `llm_call_count` | LLM 调用次数 |
| `tool_call_count` | 工具调用次数 |
| `memory_search_count` | 记忆检索次数 |
| `memory_hit_count` | 记忆命中次数 |
| `memory_reuse_count` | 记忆实际复用次数 |
| `task_latency_ms` | 单任务总耗时 |
| `success_score` | 任务完成质量评分 |

### 核心计算公式

```text
token_saving_rate =
    (tokens_text_mode - tokens_structured_mode) / tokens_text_mode
```

```text
latency_reduction_rate =
    (latency_baseline - latency_optimized) / latency_baseline
```

```text
memory_hit_rate =
    memory_hit_count / memory_search_count
```

```text
memory_reuse_rate =
    memory_reuse_count / memory_hit_count
```

```text
state_compression_ratio =
    original_text_bytes / state_transfer_bytes
```

### 实验输出模板

| 任务 | 模式 | 消息数 | 文本 token | 结构化字节 | 状态次数 | 状态字节 | 记忆命中率 | 总耗时 ms | 成功分 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A1 | G1 Text | 运行后生成 | 运行后生成 | - | 0 | 0 | - | 运行后生成 | 运行后生成 |
| A1 | G2 Structured | 运行后生成 | 运行后生成 | 运行后生成 | 0 | 0 | - | 运行后生成 | 运行后生成 |
| A1 | G3 Structured + State | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | - | 运行后生成 | 运行后生成 |
| A1 | G4 Full | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 | 运行后生成 |

报告中不要预先编造性能结果。可以在实验目标中写“预期 token 降低 30% 以上、耗时降低 20% 以上”，但最终表格必须由系统运行日志自动生成。

---

## 技术实现方案

### 推荐技术栈

MVP 版本：

```text
Python 3.11
asyncio
FastAPI / ZeroMQ / Unix Domain Socket
Pydantic
MessagePack
SQLite
FAISS
sentence-transformers / bge-small-zh-v1.5 / bge-m3
Docker sandbox
tiktoken 或模型 tokenizer
Streamlit dashboard
```

增强版本：

```text
gRPC / Protobuf
PostgreSQL + pgvector
Qdrant / Milvus
OpenTelemetry
Prometheus + Grafana
Docker / nsjail / bubblewrap
mmap / shared_memory
```

如果希望突出“系统赛题”属性，优先选择：

```text
Unix Domain Socket / ZeroMQ + MessagePack
shared_memory / mmap 保存向量状态
SQLite + FAISS 管理记忆和语义检索
Docker 或 nsjail 做代码执行沙箱
```

### 代码目录建议

```text
s_memory_agent/
  README.md
  pyproject.toml
  docker-compose.yml

  src/
    runtime/
      agent_runtime.py
      scheduler.py
      registry.py
      trace_manager.py
      mode_switch.py

    protocol/
      schema.py
      sacp.py
      serializer.py
      validator.py
      adapters/
        text_adapter.py
        structured_adapter.py

    agents/
      base_agent.py
      planner_agent.py
      retriever_agent.py
      executor_agent.py
      summarizer_agent.py
      memory_agent.py
      evaluator_agent.py

    state/
      state_capsule.py
      state_store.py
      embedding_model.py
      shared_memory_store.py
      vector_index.py

    memory/
      memory_schema.py
      memory_store.py
      memory_retriever.py
      memory_ranker.py
      memory_writer.py
      memory_gc.py

    tools/
      search_tool.py
      file_reader.py
      csv_analyzer.py
      python_sandbox.py
      report_writer.py

    eval/
      task_suite.py
      runner.py
      metrics.py
      compare.py
      dashboard.py

  data/
    tasks/
      chain_a.jsonl
      chain_b.jsonl
    corpus/
      papers/
      docs/
    logs/
      service_log_v1.csv
      service_log_v2.csv

  experiments/
    run_text_mode.sh
    run_structured_mode.sh
    run_state_mode.sh
    run_memory_mode.sh

  docs/
    system_design.md
    deployment.md
    experiment_report.md
    protocol_spec.md
```

### Runtime 核心流程伪代码

```python
class MultiAgentRuntime:
    def __init__(self, mode: str):
        self.mode = mode
        self.registry = AgentRegistry()
        self.scheduler = Scheduler()
        self.trace = TraceManager()
        self.memory = SharedMemoryStore()
        self.state_store = StateStore()

    async def run_task(self, task):
        task_id = self.trace.start_task(task)

        capabilities = self.registry.get_capabilities()

        if self.mode.endswith("memory"):
            memories = self.memory.search(task.query, top_k=5)
        else:
            memories = []

        plan = await self.call_agent(
            agent="PlannerAgent",
            action="plan.create",
            params={
                "task": task,
                "capabilities": capabilities,
                "memories": memories
            }
        )

        results = await self.scheduler.execute(plan)

        final = await self.call_agent(
            agent="SummarizerAgent",
            action="summary.generate",
            params={
                "task": task,
                "plan": plan,
                "results": results
            }
        )

        if self.mode.endswith("memory"):
            self.memory.write_from_task(task, plan, results, final)

        self.trace.end_task(task_id, final)
        return final
```

### 协议序列化

开发阶段可以使用 JSON，评测阶段同时记录 JSON 字节数、MessagePack 字节数和估算 token。

```python
def serialize_message(msg, fmt="msgpack"):
    if fmt == "json":
        return json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if fmt == "msgpack":
        return msgpack.packb(msg, use_bin_type=True)
    raise ValueError(fmt)
```

### StateStore 伪代码

```python
class StateStore:
    def put_embedding(self, vector, metadata):
        state_id = new_id("state")
        vector = vector.astype("float16")
        path = f"states/{state_id}.npy"
        np.save(path, vector)

        record = {
            "state_id": state_id,
            "type": "embedding",
            "dtype": "float16",
            "shape": list(vector.shape),
            "bytes": vector.nbytes,
            "path": path,
            "metadata": metadata
        }
        db.insert("states", record)
        return record

    def get_embedding(self, state_id):
        record = db.get("states", state_id)
        return np.load(record["path"])
```

### MemoryStore 伪代码

```python
class MemoryStore:
    def write(self, memory):
        memory_id = new_id("mem")
        embedding = embed(memory["summary"] + "\n" + str(memory["content"]))

        state = state_store.put_embedding(
            embedding,
            metadata={
                "memory_id": memory_id,
                "type": "memory_embedding"
            }
        )

        memory["memory_id"] = memory_id
        memory["embedding_id"] = state["state_id"]
        memory["created_at"] = now_iso()
        db.insert("memories", memory)

        vector_index.add(memory_id, embedding)
        return memory_id

    def search(self, query, tags=None, top_k=5):
        query_vec = embed(query)
        vector_hits = vector_index.search(query_vec, top_k=top_k * 3)
        keyword_hits = db.keyword_search(query, tags=tags)

        merged = hybrid_rank(vector_hits, keyword_hits, tags)
        return merged[:top_k]
```

---

## CodeAct 与安全沙箱

赛题鼓励支持基于 CodeAct 模式的 Agent 执行机制。本方案中，ExecutorAgent 可以接收 Planner 生成的工具调用请求，也可以由 LLM 生成 Python 代码并在轻量沙箱中运行。

### CodeAct 消息扩展

```json
{
  "action": "tool.run_python",
  "params": {
    "code_ref": "artifact_code_001",
    "sandbox_policy": {
      "network": false,
      "cpu_limit_sec": 5,
      "memory_limit_mb": 512,
      "timeout_sec": 10,
      "mount": "readonly_input_tmp_output"
    }
  }
}
```

### 安全策略

| 风险 | 防护 |
|---|---|
| 任意系统命令 | AST 检查并禁用 `os.system`、`subprocess`、`socket` 等 |
| 文件越权读取 | 只挂载临时目录，输入只读，输出单独目录 |
| 网络访问 | Docker / nsjail 禁用网络 |
| 长时间运行 | 设置 timeout、CPU quota |
| 内存耗尽 | 设置 memory limit |
| 恶意依赖安装 | 禁止 pip install 或使用白名单依赖 |

---

## 实现路线图

### 阶段一：多 Agent 与双模式跑通

完成内容：

- PlannerAgent、RetrieverAgent、ExecutorAgent、SummarizerAgent；
- Runtime、AgentRegistry、TraceManager；
- 纯文本模式；
- 结构化模式；
- 一条简单任务链可运行。

验收标准：

- 至少 3 个 Agent 协同完成一个多步骤任务；
- 能输出完整 trace；
- text mode 与 structured mode 都能运行。

### 阶段二：SACP 协议与能力发现

完成内容：

- SACP schema；
- HELLO、CAPABILITY_ADVERTISE、ACTION_CALL、ACTION_RESULT、ERROR；
- Pydantic 校验；
- MessagePack 序列化；
- Agent 能力注册表。

验收标准：

- 每个 Agent 启动时注册能力；
- Planner 能根据 capability 选择 Agent；
- 能统计每条消息的文本长度和结构化字节数。

### 阶段三：State Capsule 状态传递

完成内容：

- EmbeddingModel；
- StateStore；
- state_id 传递；
- evidence_ref 与 artifact_ref；
- 相似度门控展开。

验收标准：

- Retriever 不再直接把全文传给 Summarizer；
- 系统能记录状态传递次数和状态字节数；
- 能展示状态传递相较全文传递的压缩效果。

### 阶段四：共享记忆复用

完成内容：

- Memory schema；
- memory.write；
- memory.search；
- FAISS 语义检索；
- SQLite 元数据检索；
- 混合排序；
- reused_memory_ids 记录。

验收标准：

- A2 能复用 A1 的协议记忆；
- B2 能复用 B1 的日志分析代码模板；
- 能统计 memory_hit_rate 与 memory_reuse_rate。

### 阶段五：评测与展示

完成内容：

- 任务链 A1-A5、B1-B5；
- G1-G4 四组实验；
- metrics.csv；
- comparison_report.md；
- Streamlit 或命令行 dashboard；
- 演示视频脚本。

验收标准：

- 系统稳定执行不少于 10 轮连续任务；
- 自动生成实验表格；
- 能清晰展示通信开销、状态传递和记忆复用带来的改进。

---

## 与赛题要求的对应关系

| 赛题要求 | 本方案实现方式 | 验收材料 |
|---|---|---|
| 不少于 3 个 Agent | Planner、Retriever、Executor、Summarizer，另加 MemoryAgent | 运行日志、架构图 |
| 覆盖规划、检索、执行、总结 | 四类 Agent 分工明确 | demo trace |
| 结构化通信机制 | SACP 协议 | `protocol_spec.md` |
| 包含动作、参数、结果、能力描述 | `action`、`params`、`result`、`capability` 字段 | 消息样例 |
| 支持握手/能力发现 | HELLO、CAPABILITY_ADVERTISE、AgentRegistry | 启动日志 |
| 支持纯文本和结构化模式 | `mode=text` 与 `mode=structured` | 对比实验 |
| 非文本状态传递 | State Capsule、embedding、state_id、artifact_ref | 状态统计表 |
| 共享记忆模块 | SQLite + FAISS / Qdrant | memory 表 |
| 记忆元数据 | memory_id、source_agent、created_at、task_topic、summary | 记忆样例 |
| 关键词/标签/语义检索 | SQL/FTS + tag filter + vector search | 检索 demo |
| 后续任务复用记忆 | Planner 记录 reused_memory_ids | trace 日志 |
| 2 组连续任务 | A 链系统设计，B 链日志分析 | `tasks/*.jsonl` |
| 统计性能指标 | Evaluation Harness | `metrics.csv` |
| 不少于 10 轮连续任务 | A1-A5 + B1-B5 | 执行日志 |
| 架构模块完整 | runtime、protocol、state、memory、eval | 源码目录 |
| CodeAct 鼓励项 | ExecutorAgent 代码生成与沙箱执行 | 演示视频 |

---

## 演示视频脚本建议

演示视频建议控制在 5 到 8 分钟，重点展示机制而不是只展示最终答案。

```text
1. 系统启动
   展示 Agent 注册、能力发现、运行模式。

2. 纯文本模式运行 A1
   展示 Agent 间长文本消息和 token 统计。

3. 结构化模式运行 A1
   展示 SACP 消息、action/params/result/state_ref，并对比通信开销。

4. 运行 A2 展示记忆复用
   Planner 先查共享记忆，命中 A1 的协议字段记忆，跳过重复设计。

5. 运行 B1/B2 展示 CodeAct
   ExecutorAgent 生成 Python，在沙箱中分析 CSV；B2 复用 B1 的代码模板。

6. 展示评测面板
   展示消息数、文本 token、结构化字节数、状态传递次数、记忆命中率、耗时对比。
```

---

## 最终提交物

```text
1. 完整源码
   - src/
   - tests/
   - examples/
   - docker-compose.yml

2. 系统设计文档
   - system_design.md

3. 协议文档
   - protocol_spec.md

4. 部署文档
   - deployment.md

5. 实验报告
   - experiment_report.md
   - metrics.csv
   - comparison_charts/

6. 演示视频
   - text mode
   - structured mode
   - state passing
   - shared memory reuse
   - CodeAct sandbox
   - evaluation dashboard
```

---

## 推荐写作结论

最终报告可以这样概括系统贡献：

> 本系统不是一个简单的多 Agent 工作流编排器，而是在 Agent 协作底层引入了三类系统机制：第一，SACP 结构化协议将自然语言协作压缩为动作、参数、结果、能力和引用；第二，State Capsule 通过 embedding 和 artifact reference 直接传递非文本语义状态，减少重复文本编解码；第三，Shared Memory Graph 将任务中的证据、策略、代码和反思沉淀为可检索、可复用的记忆单元。通过纯文本、结构化、结构化加状态、结构化加状态加记忆四组实验，系统可以量化展示 token、耗时、消息数和重复计算的下降。

---

## 参考资料

[^ccf]: 中国计算机学会推荐国际学术会议和期刊目录，第七版说明。https://www.ccf.org.cn/Academic_Evaluation/By_category/

[^autogen]: AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation. https://arxiv.org/abs/2308.08155

[^agentscope]: AgentScope: A Flexible yet Robust Multi-Agent Platform. https://arxiv.org/abs/2402.14034

[^a2a]: Agent2Agent Protocol Specification. https://a2a-protocol.org/latest/specification/

[^mcp]: Model Context Protocol Tools Specification. https://modelcontextprotocol.io/specification/2025-06-18/server/tools

[^agentprune]: Cut the Crap: An Economical Communication Pipeline for LLM-Based Multi-Agent Systems / AgentPrune. https://arxiv.org/abs/2410.02506

[^stateflow]: StateFlow: Enhancing LLM Task-Solving through State-Driven Workflows. https://arxiv.org/abs/2403.11322

[^llmcompiler]: An LLM Compiler for Parallel Function Calling. https://arxiv.org/abs/2312.04511

[^codeact]: Executable Code Actions Elicit Better LLM Agents. https://arxiv.org/abs/2402.01030

[^memgpt]: MemGPT: Towards LLMs as Operating Systems. https://arxiv.org/abs/2310.08560

[^zep]: Zep: A Temporal Knowledge Graph Architecture for Agent Memory. https://arxiv.org/abs/2501.13956

[^aflow]: AFlow: Automating Agentic Workflow Generation. https://proceedings.iclr.cc/paper_files/paper/2025/hash/5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html

[^faiss]: FAISS GitHub Repository. https://github.com/facebookresearch/faiss

[^qdrant]: Qdrant Documentation. https://qdrant.tech/documentation/

[^milvus]: Milvus Vector Database. https://milvus.io/
