# 结构化通信协议说明

> 本文档说明当前 SynapseX 主线 `structured` 模式的实际通信协议。模型级 KV cache 传递在 `docs/openos/notext_state_transfer/kv_cache_handoff_design.md` 和 `src/agent/cache_agents.py` 的 trueKV/cache 旁路线中说明。

## 1. 总体定位

当前主线工作流是 5 个真实业务 Agent：

```text
START
  ↓
planner
  ↓ fan-out by sub_queries
researcher(s)
  ↓ fan-in by reducers
analyst
  ↓
executor
  ↓
summarizer
  ↓
END
```

Structured 模式的目标不是把上游自然语言原文完整拼给下游，而是把 Agent 间中间状态拆成可追踪、可压缩、可校验的结构化载荷：

- `AgentMessage`：统一记录 Agent 间动作、输入参数、输出结果和追踪元数据。
- `context_packets`：压缩文本证据通道，替代 researcher 全文透传。
- `embedding_payloads`：非文本语义向量通道，用于 analyst 的相关性排序。
- `Store`：保存完整文档、计划、分析、执行结果和摘要；下游通过 `doc_key` 等引用按需校验或回补。

对应代码：

| 模块 | 作用 |
|---|---|
| `src/graph.py` | 定义 `ResearchState`、LangGraph 拓扑、fan-out / fan-in 机制 |
| `src/protocol.py` | 定义 `AgentMessage`、`ActionType`、Context Packet 构建、排序、校验工具 |
| `src/agent/*.py` | 五个业务 Agent 的协议读写逻辑 |
| `src/config.py` | 控制 `ENABLE_CONTEXT_PACKETS`、`ENABLE_EMBEDDING_TRANSFER` 等开关 |
| `src/memory.py` | 提供共享 Store、持久化记忆、embedding 获取等能力 |

## 2. ResearchState

`ResearchState` 是所有 Agent 共享的状态协议，核心字段如下：

| 字段 | 生产者 | 消费者 | 说明 |
|---|---|---|---|
| `query` | 用户输入 | 全部 Agent | 原始任务 |
| `task_group` | runner | 全部 Agent | 任务分组，用于 Store key、记忆隔离和指标统计 |
| `mode` | runner | 全部 Agent | `text` 或 `structured` |
| `plan` | `planner` | `analyst`、`executor`、`summarizer` | 任务规划文本 |
| `sub_queries` | `planner` | `fan_out_research` | 多个子查询，用于并行 researcher |
| `documents` | `researcher` | `analyst` | text 模式或关闭 context packet 时的文档全文通道 |
| `document_payloads` | `researcher` | `analyst` | structured 模式关闭 context packet 时的文档元数据通道 |
| `context_packets` | `researcher` | `analyst` | structured 模式的压缩证据通道 |
| `embedding_payloads` | `researcher` | `analyst` | 语义向量通道 |
| `analysis` | `analyst` | `executor`、`summarizer` | 完整分析文本 |
| `analysis_digest` | `analyst` | `summarizer` | structured 模式下给 summarizer 的短摘要 |
| `candidate_answers` | `analyst` | `executor` | 面向机器评测的候选字段答案 |
| `evidence` | `analyst` | `executor`、`summarizer` | 结构化证据列表 |
| `selected_context_packets` | `analyst` | `executor` | 被选中并校验后的 context packets |
| `context_verification` | `analyst` | runner / metrics | 上下文校验统计 |
| `execution_result` | `executor` | `summarizer` | CodeAct 执行结果 |
| `execution_summary` | `executor` | `summarizer` | 执行摘要 |
| `final_answer` | `executor` | `summarizer` / runner | 机器评测友好的最终答案 |
| `messages` | 全部 Agent | runner / metrics | `AgentMessage` 事件流 |

`documents`、`document_payloads`、`context_packets`、`embedding_payloads`、`messages` 等列表字段使用 `Annotated[list, operator.add]` 聚合，使并行 researcher 输出可以 fan-in 到同一个 analyst 输入 state。

## 3. LangGraph 拓扑

主线图构建位于 `src/graph.py`：

```python
builder.add_node("planner", planner)
builder.add_node("researcher", researcher)
builder.add_node("analyst", analyst)
builder.add_node("executor", executor)
builder.add_node("summarizer", summarizer)

builder.add_edge(START, "planner")
builder.add_conditional_edges("planner", fan_out_research, ["researcher"])
builder.add_edge("researcher", "analyst")
builder.add_edge("analyst", "executor")
builder.add_edge("executor", "summarizer")
builder.add_edge("summarizer", END)
```

`fan_out_research()` 将 `planner` 生成的每个 `sub_query` 包装成 LangGraph `Send`：

```python
Send("researcher", {
    "sub_query": sub_query,
    "task_group": task_group,
    "mode": mode,
})
```

每个 researcher 收到的是结构化 dict，而不是拼接好的自然语言上下文。

## 4. AgentMessage

`AgentMessage` 是 structured 模式下统一消息外壳：

```python
@dataclass
class AgentMessage:
    msg_id: str
    timestamp: float
    source: str
    target: str
    action: ActionType
    params: dict
    result: dict
    embedding: list | None
    task_group: str
    round_id: int
    status: str = "success"
```

字段含义：

| 字段 | 说明 |
|---|---|
| `msg_id` | 自动生成的消息 ID，便于追踪 |
| `timestamp` | 创建时间戳 |
| `source` / `target` | 来源和目标 Agent |
| `action` | 动作类型，例如 `plan`、`research`、`analyze` |
| `params` | 本次动作的结构化输入参数 |
| `result` | 本次动作的结构化输出摘要 |
| `embedding` | 可选向量载荷；通常大向量通过 `embedding_payloads` 单独传递 |
| `task_group` | 任务分组 |
| `round_id` | 多轮任务中的轮次 |
| `status` | 执行状态 |

`metrics.record_message()` 会统计消息次数、参数字符数、结果字符数和 embedding transfer 次数。

## 5. Context Packet

`context_packets` 是 structured 模式的核心压缩文本通道。完整 researcher 文档保存在 Store 中，packet 只传递：

- `doc_key`：完整文档在 Store 里的引用。
- `source_query`：对应 sub-query。
- `summary`：压缩摘要。
- `evidence_spans`：可回溯的证据片段。
- `full_doc_ref`：原文 hash 和 Store 引用。
- `verification` / `retrieval_diagnostics`：覆盖率、可靠性和回补提示。

Analyst 使用 `select_context_packets()` 对 packets 排序，排序信号包括：

- query / plan 与 packet 内容的词面相关性；
- 可选 embedding 相似度；
- packet 自带 coverage / diagnostics。

随后 analyst 会用 `verify_context_packet()` 回 Store 校验证据。如果 compact evidence 不可靠，会从 Store 读取原文头部片段进行 rehydrate。

## 6. Embedding Payload

Structured 模式可以启用 embedding 通道：

```python
{
    "doc_key": "doc_xxx",
    "embedding_ref": "doc_xxx",
    "dims": 1024,
    "vector": [...]
}
```

该向量不会拼进 LLM prompt。它只在 Python 协议层参与 context packet 或 document payload 的排序。排序后进入 prompt 的仍然是被选中的 compact evidence 文本。

## 7. Store 与共享记忆

Structured 模式不依赖全文透传，而是通过 Store 保存完整材料：

| Namespace | 写入 Agent | 内容 |
|---|---|---|
| `NS_PLANS` | `planner` | plan、sub_queries |
| `NS_DOCS` | `researcher` | 完整研究材料 |
| `NS_ANALYSIS` | `analyst` | analysis、digest、candidate_answers、evidence、selected_doc_keys |
| `NS_EXECUTIONS` | `executor` | execution_code、execution_result、execution_summary、final_answer |
| `NS_SUMMARIES` | `summarizer` | summary、key_findings、recommendations |

下游 Agent 可以通过 `doc_key`、`memory_id` 等引用回查 Store，而不是要求上游把所有文本重新传一遍。

## 8. 与 trueKV 的边界

Structured 模式解决的是“低开销结构化通信”和“可检索共享记忆”，不是模型内部 KV cache 复用。

| 机制 | 所在路径 | 是否直接复用模型中间状态 |
|---|---|---|
| `structured` | `src/agent/planner.py` 等主线五 Agent | 否 |
| `trueKV/cache` | `src/agent/cache_agents.py`、`src/true_kv_handoff_runtime.py` | 是，传递 vLLM cache/KV 句柄和元数据 |

因此，如果实验目标是赛题里的“非文本模型中间状态传递”，应使用 trueKV/cache 旁路线；如果实验目标是结构化通信、压缩上下文和共享记忆，则使用主线 structured 模式。
