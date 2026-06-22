# 结构化通信协议说明

> 本文档说明当前项目中多 Agent 结构化通信协议的实际工作流、传输内容、技术特点和代码落点。  
> 协议实现位于 `src/graph.py`、`src/agents.py`、`src/protocol.py`，按当前代码实现整理。

## 1. 总体定位

当前项目实现的是一个基于 LangGraph 的多 Agent 研究工作流：

```text
START
  │
  ▼
planner
  │
  ├─ writes to shared ResearchState:
  │    plan / sub_queries / planner_hidden_state
  │
  ├─ fan-out retrieval branch by sub_queries
  │    ├─ retriever_1 ─┐
  │    ├─ retriever_2 ─┼─ fan-in retrieved payloads
  │    └─ retriever_3 ─┘
  │
  ▼
executor
  │
  ├─ reads planner fields directly from ResearchState
  │    query / plan / planner_hidden_state
  │
  └─ reads retriever payloads from fan-in reducers
       context_packets / embedding_payloads / hidden_state_payloads
  │
  ▼
summarizer
  │
  ▼
END
```

需要注意：图上没有 `planner → executor` 的显式 edge，但 `planner` 写入的 `plan`、`sub_queries`、`planner_hidden_state` 会保留在共享 `ResearchState` 中，后续 `executor` 会直接从 state 读取 `plan` 和 `planner_hidden_state`。`retriever` 不负责把 Planner 的任务规划“转交”给 Executor；它只负责根据单个 `sub_query` 生成检索证据和非文本排序信号。

结构化通信协议的目标不是简单把上游自然语言文本拼给下游，而是把 Agent 间的中间状态拆成可追踪、可压缩、可校验、可排序的结构化载荷：

- `AgentMessage`：统一记录每次 Agent 间动作、输入参数、输出结果和追踪元数据。
- `context_packets`：压缩文本证据通道，替代 Retriever 全文透传。
- `embedding_payloads`：非文本语义向量通道，用于 Executor 相关性排序。
- `hidden_state_payloads`：非文本隐藏状态特征通道，用于 Planner/Retriever 意图对齐和上下文路由。
- `Store`：保存完整文档、计划、分析和摘要，下游通过 `doc_key` 等引用按需校验或回补。

对应代码：

| 模块 | 作用 |
|------|------|
| `src/graph.py` | 定义 `ResearchState`、LangGraph 拓扑、fan-out / fan-in 机制 |
| `src/protocol.py` | 定义 `AgentMessage`、`ActionType`、`ContextPacket` 构建、排序、校验工具 |
| `src/agents.py` | 实现 `planner`、`retriever`、`executor`、`summarizer` 的协议读写逻辑 |
| `src/config.py` | 控制 `ENABLE_CONTEXT_PACKETS`、`ENABLE_EMBEDDING_TRANSFER`、`ENABLE_HIDDEN_STATE_TRANSFER` 等开关 |
| `src/memory.py` | 提供共享 Store、持久化记忆、embedding 获取等能力 |

## 2. 图工作流

### 2.1 State Schema

`src/graph.py:25` 中的 `ResearchState` 是所有 Agent 共享的状态协议。核心字段如下：

| 字段 | 生产者 | 消费者 | 说明 |
|------|--------|--------|------|
| `query` | 用户输入 | 全部 Agent | 原始研究问题 |
| `task_group` | 用户输入 / runner | 全部 Agent | 任务分组，用于 Store key、记忆隔离和指标统计 |
| `mode` | runner | 全部 Agent | `text` 或 `structured` |
| `plan` | `planner` | `retriever`、`executor`、`summarizer` | 任务规划文本 |
| `sub_queries` | `planner` | `fan_out_retrieval` | 3 个子查询，用于并行检索 |
| `planner_hidden_state` | `planner` | `retriever`、`executor`、`summarizer` | Planner 生成阶段捕获的隐藏状态特征 |
| `documents` | `retriever` | `executor` | text 模式或关闭 context packet 时的文档全文通道 |
| `document_payloads` | `retriever` | `executor` | structured 模式关闭 context packet 时的文档元数据通道 |
| `context_packets` | `retriever` | `executor` | structured 模式的压缩证据通道 |
| `embedding_payloads` | `retriever` | `executor` | 语义向量通道 |
| `hidden_state_payloads` | `retriever` | `executor` | Retriever 隐藏状态通道 |
| `analysis` | `executor` | `summarizer` | 完整分析文本 |
| `analysis_digest` | `executor` | `summarizer` | structured 模式下给 Summarizer 的短摘要 |
| `evidence` | `executor` | `summarizer` | 结构化证据列表 |
| `hidden_guidance` | `executor` | `summarizer` | hidden-state routing 对上下文选择的影响说明 |
| `messages` | 全部 Agent | runner / metrics | `AgentMessage` 事件流 |

其中 `documents`、`document_payloads`、`context_packets`、`messages`、`embedding_payloads`、`hidden_state_payloads` 都使用 `Annotated[list, operator.add]` 聚合。这样多个并行 `retriever` 的输出可以 fan-in 到同一个 `executor` 输入 state 中。

### 2.2 LangGraph 拓扑

图构建位于 `src/graph.py:101`：

```python
builder.add_node("planner", planner)
builder.add_node("retriever", retriever)
builder.add_node("executor", executor)
builder.add_node("summarizer", summarizer)

builder.add_edge(START, "planner")
builder.add_conditional_edges("planner", fan_out_retrieval, ["retriever"])
builder.add_edge("retriever", "executor")
builder.add_edge("executor", "summarizer")
builder.add_edge("summarizer", END)
```

`fan_out_retrieval()` 位于 `src/graph.py:76`，它把 `planner` 生成的每个 `sub_query` 包装成 LangGraph `Send`：

```python
Send("retriever", {
    "sub_query": sq,
    "task_group": task_group,
    "mode": mode,
    "planner_hidden_state": planner_hidden_state,
})
```

这一步是 structured workflow 的关键：每个 `retriever` 收到的是结构化 dict，而不是拼接好的自然语言上下文。

同时，`planner` 返回的 `plan` 并没有被丢弃，也不是由 `retriever` 再传给 `executor`。它作为全局 state 字段继续存在，`executor` 在 `src/agents.py:502` 到 `src/agents.py:510` 直接读取：

```python
query = state.get("query", "")
plan = state.get("plan", "")
context_packets = state.get("context_packets", [])
embedding_payloads = state.get("embedding_payloads", [])
hidden_state_payloads = state.get("hidden_state_payloads", [])
planner_hidden_state = state.get("planner_hidden_state")
```

因此真实的数据依赖可以理解为：

```text
planner ── writes plan / planner_hidden_state ───────────────► executor
   │                                                            ▲
   └─ fan-out sub_queries ─► retrievers ─► retrieved payloads ─┘
```

## 3. 协议核心结构

### 3.1 ActionType

`ActionType` 定义在 `src/protocol.py:30`，用于标识 Agent 间动作类型：

| Action | 含义 | 当前生产者 | 当前消费者 |
|--------|------|------------|------------|
| `plan` | 任务规划 | `planner` | `retriever` |
| `retrieve` | 信息检索 | `retriever` | `executor` |
| `analyze` | 分析执行 | `executor` | `summarizer` |
| `summarize` | 总结生成 | `summarizer` | output |
| `query_memory` | 查询记忆 | 预留 | 预留 |
| `store_memory` | 存储记忆 | 预留 | 预留 |

### 3.2 AgentMessage

`AgentMessage` 定义在 `src/protocol.py:40`，是当前 structured 模式下的统一消息外壳：

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
    hidden_state: dict | None = None
```

字段含义：

| 字段 | 说明 |
|------|------|
| `msg_id` | 自动生成的消息 ID，便于追踪 |
| `timestamp` | 创建时间戳 |
| `source` / `target` | 来源和目标 Agent |
| `action` | 动作类型，例如 `plan`、`retrieve`、`analyze` |
| `params` | 本次动作的结构化输入参数 |
| `result` | 本次动作的结构化输出摘要 |
| `embedding` | 可选向量，不是主要 prompt 内容 |
| `hidden_state` | 可选隐藏状态，不直接拼入 prompt |
| `task_group` | 任务组 |
| `round_id` | 轮次编号，默认 `0` |
| `status` | 执行状态，默认 `success` |

`make_message()` 位于 `src/protocol.py:87`，负责自动生成 `msg_id` 和 `timestamp`。

### 3.3 AgentCard 和能力发现

`AgentCard` 和 `AgentRegistry` 定义在 `src/protocol.py`，用于描述每个 Agent 的能力、输入输出 schema、是否支持 embedding / hidden state。默认注册表在 `create_default_registry()` 中预注册了四个 Agent：

| Agent | 支持动作 | 是否支持 embedding | 是否支持 hidden state |
|-------|----------|--------------------|------------------------|
| `planner` | `plan` | 否 | 是 |
| `retriever` | `retrieve` | 是 | 是 |
| `executor` | `analyze` | 是 | 是 |
| `summarizer` | `summarize` | 否 | 否 |

当前图执行没有通过网络握手，而是在本地 registry 中完成能力描述和发现；这些能力描述主要用于项目内协议文档、调试输出和后续路由扩展。

## 4. 端到端数据流

### 4.1 Planner 阶段

代码入口：`src/agents.py:182`

输入：

```python
{
    "query": str,
    "task_group": str,
    "mode": "text" | "structured"
}
```

主要处理：

1. 从 Store 中检索历史 summary，作为 prior context。
2. 调用模型生成 JSON：`plan` 和 3 个 `sub_queries`。
3. structured 模式且 `ENABLE_HIDDEN_STATE_TRANSFER=1` 时，捕获 `planner_hidden_state`。
4. 将 plan 写入 Store namespace `NS_PLANS`。
5. structured 模式下生成 `AgentMessage(action=plan)`。

输出 state：

```python
{
    "plan": plan,
    "sub_queries": sub_queries,
    "planner_hidden_state": planner_hidden_state,  # 可选
    "messages": [planner_message],                 # structured 模式
}
```

Planner 的 structured message 关键内容位于 `src/agents.py:277`：

```python
make_message(
    source="planner",
    target="retriever",
    action=ActionType.PLAN,
    params={"query": query, "task_group": task_group},
    result={
        "plan": plan,
        "sub_queries": sub_queries,
        "hidden_state": _hidden_state_summary(planner_hidden_state),
    },
    hidden_state=planner_hidden_state,
)
```

### 4.2 Fan-out 到并行 Retriever

代码入口：`src/graph.py:76`

`fan_out_retrieval()` 会把 `sub_queries` 拆成多个 `Send("retriever", payload)`。每个 Retriever 收到：

```python
{
    "sub_query": sq,
    "task_group": task_group,
    "mode": mode,
    "planner_hidden_state": planner_hidden_state,
}
```

因此，Retriever 不需要解析上游自然语言消息，而是直接读取结构化字段。

### 4.3 Retriever 阶段

代码入口：`src/agents.py:305`

输入：

```python
{
    "sub_query": str,
    "task_group": str,
    "mode": "text" | "structured",
    "planner_hidden_state": dict | None,
}
```

主要处理：

1. 调用模型生成 `doc_text`。
2. structured 模式下可捕获 `retriever_intent_hidden_state`。
3. 计算 `planner_hidden_state` 与 `retriever_intent_hidden_state` 的 `intent_alignment`。
4. structured 模式且 embedding 开启时，为 `doc_text[:500]` 生成 embedding。
5. 使用 `make_document_key()` 生成稳定 `doc_key`。
6. 将完整 `doc_text` 写入 Store namespace `NS_DOCS`。
7. 根据开关输出 `context_packets` 或回退到 `documents` / `document_payloads`。

structured 模式开启 `ENABLE_CONTEXT_PACKETS=1` 时，Retriever 输出：

```python
{
    "context_packets": [context_packet],
    "embedding_payloads": [embedding_payload],        # 可选
    "hidden_state_payloads": [hidden_state_payload],  # 可选
    "messages": [retriever_message],
}
```

如果 `ENABLE_CONTEXT_PACKETS=0`，则输出：

```python
{
    "documents": [doc_text, ...],
    "document_payloads": [document_payload],
    "embedding_payloads": [embedding_payload],        # 可选
    "hidden_state_payloads": [hidden_state_payload],  # 可选
    "messages": [retriever_message],
}
```

Retriever 的三类结构化载荷如下。

#### 4.3.1 document_payload

代码位置：`src/agents.py:370`

```python
{
    "doc_key": doc_key,
    "sub_query": sub_query,
    "text": doc_text,
    "text_hash": hash_text(doc_text),
    "original_chars": len(doc_text),
    "hidden_state_ref": doc_key,       # 有 hidden state 时添加
    "intent_alignment": intent_alignment,
}
```

`document_payloads` 主要用于关闭 context packet 时的 structured fallback。此时 Executor 可以仍然利用 embedding 和 hidden state 对原始 documents 排序。

#### 4.3.2 context_packet

代码位置：`src/protocol.py:132`、`src/agents.py:423`

`context_packet` 是当前协议中最重要的文本压缩载荷：

```python
{
    "protocol": "context-packet",
    "schema_version": 2,
    "doc_key": doc_key,
    "task_group": task_group,
    "source_query": sub_query,
    "summary": summary,
    "evidence_spans": [
        {
            "span_id": "ev1",
            "text": "证据片段",
            "score": 0.82,
            "matched_terms": [...],
            "source_ref": {
                "doc_key": doc_key,
                "char_start": 0,
                "char_end": 120,
                "text_hash": "...",
            },
        }
    ],
    "tags": [...],
    "embedding_ref": doc_key,
    "hidden_state_ref": doc_key,
    "original_chars": len(doc_text),
    "compressed_chars": estimate_prompt_context_chars(packet),
    "compression_ratio": 0.34,
    "retrieval_diagnostics": {
        "method": "lexical_span_retrieval",
        "evidence_count": 4,
        "query_coverage": 0.67,
        "covered_terms": [...],
        "missing_terms": [...],
        "requires_full_doc_lookup": False,
        "intent_alignment": 0.91,
    },
    "full_doc_ref": {
        "namespace": "docs",
        "key": doc_key,
        "text_hash": "...",
    },
    "verification": {...},
    "score": 0.0,
}
```

特点：

- 不传完整文档，只传摘要、证据片段、引用和校验信息。
- 完整文档保留在 Store 中，通过 `full_doc_ref.key` 回查。
- `embedding_ref` 与 `hidden_state_ref` 只保存引用，不把向量或 hidden state 嵌入文本包。
- `verification` 用于保证 evidence span 可以回溯到原始文档。

#### 4.3.3 embedding_payload

代码位置：`src/agents.py:401`

```python
{
    "doc_key": doc_key,
    "embedding_ref": doc_key,
    "dims": len(embedding),
    "vector": embedding,
}
```

`embedding_payloads` 是非文本状态。它不会直接进入 LLM prompt，而是在 Executor 的 Python 层用于计算 query/document 或 query/context 的语义相似度。

#### 4.3.4 hidden_state_payload

代码位置：`src/agents.py:377`

```python
{
    "ref_id": doc_key,
    "doc_key": doc_key,
    "source_agent": "retriever",
    "target_agent": "executor",
    "scope": "retrieval_intent",
    "sub_query": sub_query,
    "intent_alignment": intent_alignment,
    "hidden_state": retriever_intent_hidden_state,
}
```

`hidden_state_payloads` 同样不会直接进入 prompt。Executor 通过 `doc_key` 或 `hidden_state_ref` 找到对应 hidden state，用它和 `planner_hidden_state` 计算 hidden-state alignment score。

### 4.4 Fan-in 到 Executor

多个 Retriever 的输出通过 `ResearchState` 中的 `operator.add` reducer 自动合并，例如：

```python
context_packets = [packet_from_retriever_1, packet_from_retriever_2, packet_from_retriever_3]
embedding_payloads = [embedding_1, embedding_2, embedding_3]
hidden_state_payloads = [hidden_payload_1, hidden_payload_2, hidden_payload_3]
messages = [planner_msg, retriever_msg_1, retriever_msg_2, retriever_msg_3]
```

这一步没有手写聚合逻辑，依赖 `src/graph.py:42` 到 `src/graph.py:70` 的 `Annotated[list, operator.add]` 声明。

### 4.5 Executor 阶段

代码入口：`src/agents.py:493`

输入：

```python
{
    "query": str,
    "plan": str,
    "documents": list[str],
    "document_payloads": list[dict],
    "context_packets": list[dict],
    "embedding_payloads": list[dict],
    "hidden_state_payloads": list[dict],
    "planner_hidden_state": dict | None,
}
```

主要处理：

1. 判断是否启用 embedding 和 context packet。
2. 为 `query + plan` 生成 query embedding。
3. 如果有 `context_packets`，调用 `select_context_packets()` 进行融合排序。
4. 如果没有 `context_packets`，调用 `select_document_payloads()` 对原始 documents 做 fallback 排序。
5. 调用 `_verify_and_rehydrate_packets()` 从 Store 校验或回补证据。
6. 调用 `format_context_for_prompt()` 把选中的 evidence 渲染为短 prompt。
7. 调用模型生成结构化 JSON：`analysis`、`evidence`、`confidence`。
8. 生成 `analysis_digest`，写入 Store namespace `NS_ANALYSIS`。
9. structured 模式下生成 `AgentMessage(action=analyze)`。

Executor 输出：

```python
{
    "analysis": analysis,
    "analysis_digest": analysis_digest,
    "evidence": evidence,
    "hidden_guidance": hidden_guidance,
    "planner_hidden_state": planner_hidden_state,      # 可选
    "messages": [executor_message],                    # structured 模式
    "selected_context_packets": verified_packets,      # structured 模式
    "selected_documents": selected_documents_summary,  # fallback 时可选
    "context_verification": verification_summary,      # structured 模式
}
```

#### 4.5.1 Context packet 排序

代码位置：`src/protocol.py:202`

`select_context_packets()` 会把四类分数融合：

| 分数 | 来源 | 作用 |
|------|------|------|
| `lexical` | query 与 packet 文本字段的词面匹配 | 保证关键词覆盖 |
| `vector` | query embedding 与 document embedding 的 cosine similarity | 保证语义相关性 |
| `hidden_state` | `planner_hidden_state` 与 retriever hidden state 的 cosine similarity | 保证任务意图对齐 |
| `coverage` | context packet 的 query coverage | 保证证据覆盖度 |

当前权重逻辑：

```python
if hidden_score is not None and vector_score is not None:
    score = 0.45 * hidden_score + 0.35 * vector_score + 0.15 * lexical + 0.05 * coverage
elif hidden_score is not None:
    score = 0.65 * hidden_score + 0.25 * lexical + 0.1 * coverage
elif vector_score is None:
    score = 0.8 * lexical + 0.2 * coverage
else:
    score = 0.65 * vector_score + 0.25 * lexical + 0.1 * coverage
```

排序结果会写回 packet：

```python
{
    ...packet,
    "score": 0.8732,
    "score_components": {
        "lexical": 0.44,
        "vector": 0.82,
        "hidden_state": 0.91,
        "coverage": 0.67,
    },
}
```

#### 4.5.2 校验与回补

代码位置：`src/agents.py:763`

`_verify_and_rehydrate_packets()` 会根据 `doc_key` 从 Store 取回完整文档，并调用 `verify_context_packet()` 检查：

- `full_doc_ref.text_hash` 是否匹配原文。
- `evidence_spans` 的 `char_start` / `char_end` 是否有效。
- evidence 文本 hash 是否能对应原文片段。
- query coverage 是否足够。

如果 packet 不可靠但完整文档存在，则 `_rehydrate_packet_from_store()` 会追加一个有限长度的 fallback evidence：

```python
{
    "span_id": "rehydrated_full_doc_head",
    "text": fallback_text,
    "source_ref": {...},
    "retrieval_method": "store_rehydration",
}
```

这样既避免全文无条件透传，又保证压缩证据不足时仍有安全回补路径。

#### 4.5.3 Prompt 渲染

代码位置：`src/protocol.py:367`

`format_context_for_prompt()` 只把 evidence 渲染成极简格式：

```text
[doc_xxx#ev1] evidence text...
[doc_yyy#ev2] evidence text...
```

哈希、偏移量、embedding、hidden state、diagnostics 等元数据保留在 Python 协议层，不直接进入 LLM prompt。

### 4.6 Summarizer 阶段

代码入口：`src/agents.py:847`

输入：

```python
{
    "query": str,
    "plan": str,
    "analysis": str,
    "analysis_digest": str,
    "evidence": list[dict],
    "hidden_guidance": dict,
    "planner_hidden_state": dict | None,
}
```

主要处理：

1. structured 模式下优先使用 `analysis_digest`，减少 summarizer prompt 长度。
2. 将 `evidence` 格式化为 bullet list。
3. 如果 `hidden_guidance.used=True`，在 prompt 中加入 hidden-state routing 摘要。
4. 调用模型生成 `summary`、`key_findings`、`recommendations`。
5. 将 summary 写入 Store namespace `NS_SUMMARIES`。
6. structured 模式下生成 `AgentMessage(action=summarize)`。

Summarizer 输出：

```python
{
    "summary": summary,
    "key_findings": key_findings,
    "planner_hidden_state_summary": {...},  # 可选
    "hidden_guidance": hidden_guidance,      # 可选
    "messages": [summarizer_message],       # structured 模式
}
```

## 5. Agent 间传输内容总表

| 边 | 传输内容 | State 字段 | 是否进入 prompt | 说明 |
|----|----------|------------|----------------|------|
| 用户 → Planner | 原始查询、任务组、模式 | `query`、`task_group`、`mode` | 是 | 初始输入 |
| Planner → Shared State → Executor | plan、planner hidden state | `plan`、`planner_hidden_state` | 是 | 没有显式 `planner → executor` edge，但 Executor 直接读共享 state |
| Planner → Fan-out → Retriever | sub-query、planner hidden state | `sub_query`、`planner_hidden_state` | 部分进入 | fan-out 时每个 Retriever 只收到一个 `sub_query`，不负责转交完整 plan |
| Planner → Retriever | 动作消息 | `messages[]` | 否 | `AgentMessage(action=plan)` 记录元数据 |
| Retriever → Executor | 压缩证据 | `context_packets` | 是，渲染后进入 | structured 模式主要文本通道 |
| Retriever → Executor | 文档全文 | `documents` | 是 | text 模式或 context packet 关闭时使用 |
| Retriever → Executor | 文档元数据 | `document_payloads` | 不一定 | structured fallback 排序使用 |
| Retriever → Executor | embedding | `embedding_payloads` | 否 | Python 层排序使用 |
| Retriever → Executor | hidden state | `hidden_state_payloads` | 否 | Python 层意图对齐使用 |
| Retriever → Executor | 动作消息 | `messages[]` | 否 | `AgentMessage(action=retrieve)` |
| Executor → Summarizer | 完整分析 | `analysis` | text 模式主要进入 | structured 模式仍保留在 state 和 Store |
| Executor → Summarizer | 分析摘要 | `analysis_digest` | 是 | structured 模式优先使用 |
| Executor → Summarizer | 证据列表 | `evidence` | 是 | claims/support/doc_key/span_id |
| Executor → Summarizer | 路由说明 | `hidden_guidance` | 是，摘要形式 | 告诉 Summarizer 上下文选择原因 |
| Executor → Summarizer | 动作消息 | `messages[]` | 否 | `AgentMessage(action=analyze)` |
| Summarizer → Output | 最终摘要 | `summary`、`key_findings` | 输出 | 最终结果 |
| Summarizer → Output | 动作消息 | `messages[]` | 否 | `AgentMessage(action=summarize)` |

## 6. 三通道设计

当前 structured 模式最核心的技术设计是把中间状态拆成三条互相独立、通过引用关联的通道：

```text
                         ┌─ context_packets ───────┐
planner_hidden_state ───►│                         │
                         ├─ embedding_payloads ────┼─► executor ranking ─► short verified prompt
retriever_hidden_state ─►│                         │
                         └─ hidden_state_payloads ─┘
```

三条通道的关联方式：

```text
context_packet.doc_key
context_packet.embedding_ref ───────► embedding_payload.doc_key
context_packet.hidden_state_ref ────► hidden_state_payload.ref_id
context_packet.full_doc_ref.key ────► Store["docs"][doc_key]
```

设计收益：

1. `context_packets` 只负责传递可读、可引用、可校验的文本证据。
2. `embedding_payloads` 只负责语义相关性，不污染 prompt。
3. `hidden_state_payloads` 只负责 Agent 内部意图对齐，不伪装成自然语言。
4. 完整文档留在 Store 中，减少跨 Agent prompt 膨胀。
5. 三个通道可独立开关、独立评估、独立做消融实验。

## 7. Text 模式与 Structured 模式对比

### 7.1 Text 模式

```text
planner → retriever → executor → summarizer
  plan      documents    analysis    summary
```

特点：

- Agent 间主要传自然语言字符串。
- Retriever 的完整文档会直接进入 Executor 上下文。
- 缺少显式消息 envelope、向量通道、hidden-state 通道和证据校验。
- 实现简单，但 token 开销更大，可追踪性较弱。

### 7.2 Structured 模式

```text
planner
  ├─ AgentMessage(action=plan)
  ├─ plan / sub_queries
  └─ planner_hidden_state

retriever
  ├─ AgentMessage(action=retrieve)
  ├─ context_packets
  ├─ embedding_payloads
  └─ hidden_state_payloads

executor
  ├─ AgentMessage(action=analyze)
  ├─ selected_context_packets
  ├─ context_verification
  ├─ analysis_digest
  ├─ evidence
  └─ hidden_guidance

summarizer
  ├─ AgentMessage(action=summarize)
  ├─ summary
  └─ key_findings
```

特点：

- 使用结构化 state 字段传递信息。
- 使用 `AgentMessage` 记录动作、参数、结果和 trace metadata。
- 使用 `context_packets` 替代全文透传。
- 使用 Store 保存完整原文，并通过 `doc_key` 引用。
- 使用 embedding 和 hidden state 在 Python 层完成排序、路由和裁剪。
- Summarizer 使用 `analysis_digest`，避免再次消费完整分析。

## 8. 技术特点

### 8.1 结构化动作语义

每次 Agent 间通信都带有明确的 `action`：

- `planner` 产生 `plan`。
- `retriever` 产生 `retrieve`。
- `executor` 产生 `analyze`。
- `summarizer` 产生 `summarize`。

这使得 runner 或 metrics 可以统计不同动作的参数大小、结果大小、是否携带 embedding、是否携带 hidden state。

### 8.2 并行 fan-out / fan-in

`planner` 输出多个 `sub_queries`，`fan_out_retrieval()` 把每个子查询分发到一个 Retriever 执行。多个 Retriever 的列表型输出通过 LangGraph reducer 自动合并。

优势：

- 子查询并行化。
- 每个 Retriever 输入清晰，只负责一个子任务。
- 聚合字段由 State schema 控制，避免手写 merge 逻辑。

### 8.3 上下文压缩

`build_context_packet()` 会从完整 `doc_text` 中抽取：

- `summary`：压缩摘要。
- `evidence_spans`：和子查询相关的证据片段。
- `tags`：关键词标签。
- `retrieval_diagnostics`：覆盖度、缺失词、是否需要全文回查。
- `full_doc_ref`：完整原文引用。
- `verification`：证据可靠性检查结果。

Executor 最终只把选中 evidence 渲染进 prompt，而不是传完整文档。

### 8.4 非文本状态传递

Embedding 和 hidden state 不作为自然语言拼接，而是作为结构化 payload 在 Python 层消费：

- embedding 用于语义相似度排序。
- hidden state 用于 Planner/Retriever 意图对齐排序。
- 排序结果以 `score_components` 和 `hidden_guidance` 形式保留，可被下游解释。

这避免了把不可读向量硬塞进 prompt，也保留了非文本中间状态的实用价值。

### 8.5 可校验证据链

每个 `context_packet` 都带有：

- `doc_key`
- `full_doc_ref`
- `text_hash`
- `char_start` / `char_end`
- `verification`

Executor 在使用前会从 Store 取回完整文档进行校验。若压缩证据不足，则用 Store 中原文生成有限长度 fallback evidence。

### 8.6 可回退设计

三个核心通道由独立开关控制：

```bash
ENABLE_CONTEXT_PACKETS=1
ENABLE_EMBEDDING_TRANSFER=1
ENABLE_HIDDEN_STATE_TRANSFER=1
```

回退逻辑：

| 场景 | 行为 |
|------|------|
| `ENABLE_CONTEXT_PACKETS=1` | Retriever 输出 `context_packets`，Executor 选择压缩证据 |
| `ENABLE_CONTEXT_PACKETS=0` | Retriever 输出 `documents` / `document_payloads`，Executor 对原始文档排序 |
| `ENABLE_EMBEDDING_TRANSFER=0` | 排序不使用 `vector_score` |
| `ENABLE_HIDDEN_STATE_TRANSFER=0` | 排序不使用 `hidden_score` |
| Store 缺失完整文档 | packet 标记为不可靠，并记录 missing doc |
| packet 校验不可靠但 Store 有原文 | 从 Store rehydrate 有界 fallback evidence |

### 8.7 共享记忆与复用

各 Agent 会把中间结果写入 Store：

| Namespace | 写入者 | 内容 |
|-----------|--------|------|
| `NS_PLANS` | `planner` | plan、sub_queries、planner hidden state summary |
| `NS_DOCS` | `retriever` | 完整 doc_text、sub_query、task_group |
| `NS_ANALYSIS` | `executor` | analysis、analysis_digest、evidence、selected_doc_keys |
| `NS_SUMMARIES` | `summarizer` | summary、key_findings、recommendations |

后续任务可以通过 `store_search()` 检索 prior summaries、prior documents 或 prior analyses，实现记忆复用。

## 9. 代码路径速查

| 功能 | 代码位置 |
|------|----------|
| State schema | `src/graph.py:25` |
| fan-out 逻辑 | `src/graph.py:76` |
| 图拓扑构建 | `src/graph.py:101` |
| Planner agent | `src/agents.py:182` |
| Retriever agent | `src/agents.py:305` |
| Executor agent | `src/agents.py:493` |
| Summarizer agent | `src/agents.py:847` |
| `ActionType` | `src/protocol.py:30` |
| `AgentMessage` | `src/protocol.py:40` |
| `make_message()` | `src/protocol.py:87` |
| `build_context_packet()` | `src/protocol.py:132` |
| `select_context_packets()` | `src/protocol.py:202` |
| `select_document_payloads()` | `src/protocol.py:274` |
| `format_context_for_prompt()` | `src/protocol.py:367` |
| `verify_context_packet()` | `src/protocol.py:400` |
| Store namespace 配置 | `src/config.py:54` |

## 10. 当前边界

当前协议已经实现了图内结构化通信、三通道状态传递、上下文压缩、排序、校验和 Store 回补，但仍有一些边界需要明确：

1. `AgentMessage` 是本地 Python dataclass，不是 HTTP 网络协议消息。
2. `AgentRegistry` 是本地能力注册表，不是网络服务发现机制。
3. hidden state 当前用于排序和路由，没有注入下游模型的 KV cache、attention 或中间层。
4. embedding 和 hidden state 不进入 LLM prompt，只作为 Python 协议层信号。
5. `round_id` 当前默认是 `0`，未实现多轮协议状态机。
6. `query_memory` 和 `store_memory` 已在 `ActionType` 中预留，但当前主工作流没有单独作为图节点执行。

## 11. 一句话总结

当前结构化通信协议可以概括为：

```text
用 AgentMessage 记录动作，
用 ResearchState 传递结构化字段，
用 context_packets 压缩可读证据，
用 embedding_payloads 和 hidden_state_payloads 做非文本排序，
用 Store 保存完整上下文并支持校验回补，
最终让下游 Agent 只消费经过选择和验证的短上下文。
```
