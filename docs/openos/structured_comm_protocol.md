# 结构化通信协议设计与实现（简化 A2A 借鉴）

> 基于 Google A2A（Agent-to-Agent Protocol）简化，适配 LangGraph 图编排场景。
> 已落地实现，代码位于 `/data/mingwei/langgraph/examples/multi_agent_demo/`。

## 一、设计目标

| 赛题要求 | 对应 A2A 概念 | 实现方案 | 代码位置 |
|---------|-------------|---------|---------|
| 动作类型 | Task 状态机 | `ActionType` 枚举（6 种） | `protocol.py:24-31` |
| 输入参数 | Message/Part | `AgentMessage.params: dict` | `protocol.py:34-48` |
| 返回结果 | Message/Part | `AgentMessage.result: dict` | `protocol.py:34-48` |
| 能力描述 | AgentCard | `AgentCard` dataclass | `protocol.py:51-58` |
| 能力发现 | /.well-known/agent.json | `AgentRegistry.discover(action)` | `protocol.py:61-82` |
| 握手 | HTTP 握手 | Registry 查询 + 匹配 | `protocol.py:72-73` |
| 文本压缩传递 | DataPart/FilePart | `context_packets`：摘要 + evidence + 引用 + 校验 | `protocol.py` / `agents.py` |
| 语义向量传递 | DataPart | `embedding_payloads`：`{doc_key, dims, vector}` | `graph.py` / `agents.py` |
| 隐藏状态传递 | DataPart | `hidden_state_payloads`：`{ref_id, doc_key, hidden_state}` | `graph.py` / `agents.py` |

## 二、协议核心结构（已实现）

### 2.1 ActionType — 动作类型枚举

**文件**: `protocol.py:24-31`

```python
class ActionType(str, Enum):
    PLAN = "plan"              # 任务规划
    RETRIEVE = "retrieve"      # 信息检索
    ANALYZE = "analyze"        # 分析执行
    SUMMARIZE = "summarize"    # 总结生成
    QUERY_MEMORY = "query_memory"  # 查询记忆
    STORE_MEMORY = "store_memory"  # 存储记忆
```

### 2.2 AgentMessage — 结构化消息

**文件**: `protocol.py:34-48`

```python
@dataclass
class AgentMessage:
    msg_id: str                 # 消息唯一 ID（自动生成）
    timestamp: float            # 创建时间戳（自动生成）
    source: str                 # 来源 Agent 名称
    target: str                 # 目标 Agent 名称
    action: ActionType          # 动作类型
    params: dict                # 输入参数（结构化 KV）
    result: dict                # 返回结果（结构化 KV）
    embedding: list | None      # 语义向量（可选，非文本传递）
    task_group: str             # 所属任务组
    round_id: int               # 轮次编号
    status: str = "success"     # 状态
    hidden_state: dict | None     # 隐藏状态 payload（可选，非文本状态）
```

**工厂函数**: `protocol.py:87-104` — `make_message()` 自动生成 msg_id 和 timestamp

### 2.3 AgentCard — 能力描述

**文件**: `protocol.py:51-58`

```python
@dataclass
class AgentCard:
    name: str                    # Agent 名称
    description: str             # 能力描述
    actions: list[str]           # 支持的动作类型列表
    input_schema: dict           # 输入参数 JSON Schema
    output_schema: dict          # 输出参数 JSON Schema
    supports_embedding: bool     # 是否支持语义向量输入
    supports_hidden_state: bool   # 是否支持隐藏状态特征输入/输出
```

### 2.4 AgentRegistry — 能力发现

**文件**: `protocol.py:61-82`

```python
class AgentRegistry:
    def register(self, card: AgentCard)           # 注册能力卡片
    def discover(self, action: str) -> list       # 按动作类型发现可用 Agent
    def get_card(self, name: str) -> AgentCard    # 获取指定 Agent 的卡片
    def list_all(self) -> list                    # 列出所有已注册 Agent
```

**默认注册表**: `protocol.py:107-145` — `create_default_registry()` 预注册 4 个 Agent

### 2.5 ContextPacket — 压缩文本证据通道

`ContextPacket` 是文本压缩载荷，用于替代 Structured 模式下的全文透传。完整文档仍写入共享 Store，下游 Agent 只接收可控长度的摘要、证据片段、标签和引用 ID。

```python
{
    "protocol": "context-packet",
    "doc_key": "doc_xxx",
    "task_group": "foundation",
    "source_query": "子查询",
    "summary": "压缩摘要",
    "evidence_spans": [
        {
            "span_id": "ev1",
            "text": "证据片段",
            "score": 0.82,
            "source_ref": {"char_start": 0, "char_end": 120, "text_hash": "..."},
        }
    ],
    "tags": ["langgraph", "memory"],
    "embedding_ref": "doc_xxx",
    "hidden_state_ref": "doc_xxx",
    "full_doc_ref": {"namespace": "docs", "key": "doc_xxx", "text_hash": "..."},
    "original_chars": 1800,
    "compressed_chars": 620,
    "compression_ratio": 0.34,
}
```

生成与使用流程：

1. `retriever` 生成 `doc_text` 后先写入 `InMemoryStore`。
2. `build_context_packet()` 从 `doc_text` 中抽取 `summary`、`evidence_spans` 和 `tags`。
3. `retriever` 返回 `context_packets`，不再在 Structured 模式下把完整 `documents` 直接放入 Executor prompt。
4. `executor` 使用 `select_context_packets()` 选择 top-k 上下文包。
5. `format_context_for_prompt()` 将选中的压缩包渲染为短 prompt。
6. `context_packet` 不内嵌完整 hidden state，只通过 `hidden_state_ref` 关联独立的 `hidden_state_payloads`。

### 2.6 三通道结构化通信载荷

当前 Structured 模式由三类互相独立但可组合的通道组成：

| 通道 | State 字段 | 类型 | 生成者 | 消费者 | 主要作用 |
|------|------------|------|--------|--------|----------|
| 文本压缩证据 | `context_packets` | 摘要、证据、引用、校验元数据 | `retriever` | `executor` | 减少进入 LLM prompt 的文本 |
| 语义向量 | `embedding_payloads` | `{doc_key, embedding_ref, dims, vector}` | `retriever` | `executor` | 计算语义相关性 `embedding_score` |
| 隐藏状态特征 | `hidden_state_payloads` | `{ref_id, doc_key, scope, hidden_state}` | `retriever` | `executor` | 计算任务意图对齐 `hidden_score` |

三者通过 `doc_key` / `ref_id` 关联，而不是父子嵌套关系：

```text
context_packet.doc_key        ┐
context_packet.embedding_ref  ├─> embedding_payload.doc_key
context_packet.hidden_state_ref ─> hidden_state_payload.ref_id
```

这样 `context_packets` 只负责“传什么文本证据”，`embedding_payloads` 负责“语义上是否相关”，`hidden_state_payloads` 负责“是否符合 Planner/Retriever 的内部任务意图”。

## 三、双模式实现

### 3.1 模式切换机制

**文件**: `graph.py:99` — `build_graph(mode)` 接受 `"text"` 或 `"structured"` 参数

**文件**: `graph.py:51` — State 中的 `mode: str` 字段传递到每个 Agent

**文件**: `agents.py:27-29` — `_get_mode(state)` 从 state 读取模式

```
run_demo.py: main()
    │
    ├─ Phase 1: build_graph(mode="text")     ← 纯文本模式
    │   └─ graph.invoke({"mode": "text", ...})
    │
    ├─ metrics.reset()                        ← 重置指标
    │
    └─ Phase 2: build_graph(mode="structured") ← 结构化模式
        └─ graph.invoke({"mode": "structured", ...})
```

### 3.2 Text 模式（自然语言透传）

**行为**: Agent 返回 `{"plan": str, "sub_queries": list[str]}`，直接放 state 字段

```
planner --[str]--> retriever --[str]--> executor --[str]--> summarizer
         "子查询文本"      "文档文本"         "分析文本"      "摘要文本"
```

**代码路径**（以 planner 为例）:
- `agents.py:51-62` — 提示词要求 LLM 输出 JSON
- `agents.py:64-76` — `JsonOutputParser` 从 LLM 输出中提取 JSON
- `agents.py:91-94` — 返回 `{"plan": plan, "sub_queries": sub_queries}`（无 messages）

### 3.3 Structured 模式（AgentMessage + ContextPacket 协议）

**行为**: Agent 间不再只透传自然语言全文，而是使用 `AgentMessage` 承载动作类型、参数、结果和能力语义；长文本写入共享 Store，下游通过 `doc_key`、压缩上下文包和向量 payload 进行选择性消费。

```
planner --[AgentMessage + planner_hidden_state]--> retriever
retriever --[context_packets + embedding_payloads + hidden_state_payloads]--> executor
executor --[analysis_digest + evidence + hidden_guidance]--> summarizer
```

**核心约束**:

- `retriever` 在 Structured 模式下不再把完整 `documents` 作为下游 prompt 输入。
- 完整 `doc_text` 只保存到 `InMemoryStore`，通过 `doc_key` 引用。
- `context_packets` 使用 `operator.add` 聚合多个并行 retriever 的压缩结果。
- `embedding_payloads` 传递 `{doc_key, embedding_ref, dims, vector}`，供 executor 做语义相关性排序。
- `hidden_state_payloads` 传递 `{ref_id, doc_key, source_agent, scope, hidden_state}`，供 executor 做 Agent 意图对齐排序。
- `executor` 使用 `select_context_packets()` 融合 `lexical_score`、`embedding_score`、`hidden_score`、`coverage`，选择 top-k 压缩上下文，并用 `format_context_for_prompt()` 生成短 prompt。
- `summarizer` 在 Structured 模式下使用 `analysis_digest`，避免再次传完整 `analysis`。

**Retriever 当前代码路径**:

```python
if mode == "structured":
    context_packet = build_context_packet(
        doc_key=doc_key,
        sub_query=sub_query,
        doc_text=doc_text,
        task_group=task_group,
        embedding_ref=doc_key,
    )
    embedding_payload = {"doc_key": doc_key, "dims": len(embedding), "vector": embedding}
    hidden_state_payload = {
        "ref_id": doc_key,
        "doc_key": doc_key,
        "source_agent": "retriever",
        "target_agent": "executor",
        "scope": "retrieval_intent",
        "hidden_state": retriever_intent_hidden_state,
    }
    context_packet["hidden_state_ref"] = doc_key
    result = {
        "context_packets": [context_packet],
        "embedding_payloads": [embedding_payload],
        "hidden_state_payloads": [hidden_state_payload],
    }
```

**Executor 当前代码路径**:

```python
selected_packets = select_context_packets(
    packets=context_packets,
    query_text=f"{query}\n{plan}",
    query_embedding=query_embedding,
    embedding_payloads=embedding_payloads if use_embeddings else None,
    hidden_state_payloads=hidden_state_payloads,
    planner_hidden_state=planner_hidden_state,
    top_k=HIDDEN_STATE_CONTEXT_TOP_K if planner_hidden_state else 3,
)
verified_packets, verification_summary = _verify_and_rehydrate_packets(
    selected_packets,
    store=store,
    query_text=query_text,
)
docs_text = format_context_for_prompt(verified_packets)
```

## 四、三通道结构化通信实现

三通道不是把三份内容都塞进 prompt，而是在 LangGraph state 中把“可读文本证据”和“非文本选择信号”拆开传递：

```text
                    ┌─ context_packets ───────┐
planner_hidden_state ─> retriever              ├─> executor ranking ─> short verified prompt
                    ├─ embedding_payloads ─────┤
                    └─ hidden_state_payloads ──┘
```

落地实现的关键点：

- `context_packets` 是唯一进入下游 LLM prompt 的主要内容通道，负责压缩后的摘要、证据、引用和校验信息。
- `embedding_payloads` 和 `hidden_state_payloads` 是 Python 协议层的非文本状态，主要用于排序、路由、过滤，不按文本拼进 prompt。
- 三个通道都通过 `doc_key` / `ref_id` 关联同一份 Store 文档，避免把 hidden state 嵌入 `context_packet` 形成父子依赖。
- 三个开关独立控制，可分别做消融实验，观察 token、召回、引用命中和事实正确率的变化。

收益可以概括为：文本通道负责省 token，embedding 负责语义相关性，hidden state 负责上游意图对齐；三者组合的目标是让 Executor 只读取更少、更相关、可回查的证据。


### 4.1 通道一：ContextPacket 文本压缩证据

`context_packets` 是结构化通信协议中真正减少 LLM token 的核心通道。它不把 Retriever 生成的全文直接传给 Executor，而是传递：

```text
summary + evidence_spans + doc_key + full_doc_ref + offset/hash/verification
```

实现要点：

- **生成**：`retriever` 调用 `build_context_packet(doc_key, sub_query, doc_text, ...)`。
- **传递**：`graph.py` 中 `context_packets: Annotated[list[dict], operator.add]` 支持并行 retriever fan-in。
- **接收**：`executor` 从 state 读取 `context_packets`。
- **使用**：`select_context_packets()` 选择 top-k，`format_context_for_prompt()` 只把短 evidence 渲染给 LLM。
- **可靠性**：`full_doc_ref`、`source_ref`、`text_hash` 和 `verify_context_packet()` 支持 Store 回查和证据校验。

### 4.2 通道二：Embedding 语义向量

`embedding_payloads` 是非文本语义状态通道，不依赖 `context_packets`。它用于回答：

```text
这段内容和 query/plan 在语义上是否相关？
```

实现要点：

- **生成**：`retriever` 对 `doc_text[:500]` 生成 embedding；有 DashScope key 时用 `DashScopeEmbeddings`，否则用本地 `LocalHashEmbeddings` fallback。
- **传递**：`embedding_payloads: Annotated[list[dict], operator.add]`。
- **结构**：`{"doc_key": doc_key, "embedding_ref": doc_key, "dims": 1024, "vector": [...]}`。
- **接收**：`executor` 对 `query + plan` 生成 query embedding。
- **使用**：`select_context_packets()` / `select_document_payloads()` 计算 `embedding_score = cosine(query_embedding, doc_embedding)`。

收益：embedding 可以弥补纯关键词匹配的不足，识别“字面不同但语义相关”的候选上下文。

### 4.3 通道三：Hidden State 隐藏状态特征

`hidden_state_payloads` 是独立的非文本隐藏状态通道，不再作为 `context_packet.hidden_state` 的子字段。它用于回答：

```text
这段 Retriever 结果是否符合 Planner 当前的内部任务意图？
```

实现要点：

- **生成**：本地 Transformers 后端在 `model.generate()` 前执行 `model(..., output_hidden_states=True, use_cache=False)`，取最后一层 prompt 最后一个 token 的 hidden state。
- **Planner 侧**：生成 `planner_hidden_state`，作为任务意图向量传给下游。
- **Retriever 侧**：生成 `retriever_intent_hidden_state`，并计算 `intent_alignment = cosine(planner_hidden_state, retriever_intent_hidden_state)`。
- **传递**：`hidden_state_payloads: Annotated[list[dict], operator.add]`。
- **结构**：`{"ref_id": doc_key, "doc_key": doc_key, "scope": "retrieval_intent", "hidden_state": {...}}`。
- **关联**：`context_packet["hidden_state_ref"] = doc_key`，Executor 通过 `doc_key/ref_id` 查找对应 hidden state。
- **使用**：`hidden_score = cosine(planner_hidden_state.vector, hidden_state_payload.hidden_state.vector)`。

注意：当前 hidden state 没有注入下游模型内部的 KV cache、attention、prefix embedding 或中间层；它在 Python 协议层用于排序、路由和上下文选择。

### 4.4 三通道融合排序

Executor 对候选上下文进行融合打分：

```text
score = hidden_score * 0.45
      + embedding_score * 0.35
      + lexical_score * 0.15
      + coverage * 0.05
```

当某个通道关闭或缺失时，会自动降级为可用信号组合：

| 可用信号 | 排序策略 |
|----------|----------|
| hidden + embedding | 意图对齐 + 语义相似 + 词法/覆盖率 |
| hidden only | 意图对齐 + 词法/覆盖率 |
| embedding only | 语义相似 + 词法/覆盖率 |
| neither | 词法/覆盖率 |

### 4.5 三个独立开关

```bash
ENABLE_CONTEXT_PACKETS=1       # 文本压缩证据通道
ENABLE_EMBEDDING_TRANSFER=1    # 语义向量通道
ENABLE_HIDDEN_STATE_TRANSFER=1 # 隐藏状态特征通道
```

三者互不依赖：

- 关闭 `ENABLE_CONTEXT_PACKETS` 时，系统回退到 `documents` / `document_payloads`，但 embedding 和 hidden state 仍可用于 raw document 排序。
- 关闭 `ENABLE_EMBEDDING_TRANSFER` 时，只去掉 `embedding_score`，不影响 context packet 或 hidden state。
- 关闭 `ENABLE_HIDDEN_STATE_TRANSFER` 时，只去掉 `hidden_score`，不影响 context packet 或 embedding。

### 4.6 三通道互补收益

| 通道 | 解决的问题 | 直接收益 | 局限 |
|------|------------|----------|------|
| `context_packets` | 具体内容是什么，证据在哪里 | 减少 LLM prompt token，保留引用和回查 | 压缩可能漏信息 |
| `embedding_payloads` | 语义上是否相关 | 提升语义召回，减少关键词漏召 | 不理解当前 Agent 内部意图 |
| `hidden_state_payloads` | 是否符合当前任务意图 | 辅助路由和重排，减少偏题上下文 | 不能替代文本事实证据 |

互补逻辑：

```text
context_packet 负责“传对内容”
embedding 负责“语义上相关”
hidden_state 负责“符合当前 Agent 意图”
```

因此三通道组合的目标不是“传更多”，而是用非文本状态帮助选择更少、更相关、可验证的文本证据进入 LLM prompt。

### 4.7 如何评估 embedding / hidden state 的独立收益

三通道全开只能证明结构化协议整体有效，不能单独证明 embedding 或 hidden state 的边际贡献。建议使用消融实验：

| 实验 | `context_packets` | `embedding` | `hidden_state` | 目的 |
|------|-------------------|-------------|----------------|------|
| A. text baseline | 0 | 0 | 0 | 纯文本基线 |
| B. context only | 1 | 0 | 0 | 只看文本压缩收益 |
| C. context + embedding | 1 | 1 | 0 | 评估 embedding 边际收益 |
| D. context + hidden | 1 | 0 | 1 | 评估 hidden state 边际收益 |
| E. all three | 1 | 1 | 1 | 评估三通道组合收益 |

重点指标：

- `total_tokens`、`input_tokens`、`executor input_tokens`
- `selected_doc_keys` 是否改变
- `context_packets_checked`、`query_coverage`、`context_saved_chars`
- `hidden_state_used_executor_context_ranking`
- `hidden_state_context_packets_skipped`
- `embedding_received`
- 人工质量评分、事实正确率、引用命中率、幻觉率

当前已完成的 12 轮三通道实验显示：Structured 模式 total tokens 从 `45,447` 降至 `32,624`，节省 `12,823` tokens，降幅 `28.22%`；但 embedding 和 hidden state 的单独贡献仍需要上述消融实验进一步量化。

## 五、Metrics 通信指标

### 5.1 新增指标

| 指标 | 说明 | 记录位置 |
|------|------|---------|
| `message_log` | 所有 `AgentMessage` 记录 | `metrics.py` |
| `record_message()` | 记录 source/target/action/字符数/embedding | `metrics.py` |
| `compression_log` | 记录上下文压缩前后字符数 | `metrics.py` |
| `record_context_compression()` | 记录 original/compressed/saved chars | `metrics.py` |
| `summary_dict()` | 返回双模式对比所需指标 | `metrics.py` |

### 5.2 报告输出

报告新增两类结构化协议指标：

- **Structured Communication Metrics**：消息总条数、参数字符总数、结果字符总数、embedding 传递次数和动作类型分布。
- **Context Compression**：压缩记录数、原始字符数、压缩字符数、节省字符数、按来源统计的压缩比例。

### 5.3 双模式对比表

`run_demo.py` 和 `run_12rounds.py` 的对比表增加以下字段，用于展示协议压缩链路本身的效果：

- `Context original chars`
- `Context compressed chars`
- `Context saved chars`

这些字段只统计 Structured 模式下的上下文压缩，不更新或替代本文后续的实验结果表。

## 六、能力发现集成

### 6.1 注册表创建

**文件**: `run_demo.py:38` — `create_default_registry()` 创建注册表

### 6.2 4 个 Agent 的 AgentCard

**文件**: `protocol.py:107-145`

| Agent | Actions | Embedding | Hidden State |
|-------|---------|-----------|--------------|
| planner | [plan] | ✗ | ✓ |
| retriever | [retrieve] | ✓ | ✓ |
| executor | [analyze] | ✓ | ✓ |
| summarizer | [summarize] | ✗ | ✓ |

### 6.3 启动时展示

**文件**: `run_demo.py:40` — `registry.summary()` 打印所有已注册 Agent

## 七、性能展示

赛题要求：系统需统计并展示 Agent 间消息次数、文本通信 token 或字符开销、非文本状态传递次数及数据规模、单任务总耗时、共享记忆命中率及整体性能提升情况。

### 7.1 统计指标与代码位置

| 指标 | 说明 | 采集位置 | 展示位置 |
|------|------|---------|---------|
| Agent 间消息次数 | `message_log` 列表长度 | `metrics.py:27` — `record_message()` 追加 | `metrics.py:115-122` report 输出 / `run_demo.py:118-140` 对比表 |
| 文本通信字符开销 | 每条消息的 `param_chars` + `result_chars` | `metrics.py:38-42` — `char_count()` 计算 | `metrics.py:123-125` report 输出 |
| 非文本传递次数 | embedding / hidden state payload 计数 | `metrics.py` counters | `metrics.py` report / `summary_dict()` |
| 非文本数据规模 | embedding 1024 维、hidden state 4096 维 | `agents.py` / `models.py` | `metrics.py` 报告维度和次数 |
| 单任务总耗时 | `task_start` → `task_end` 时间差 | `metrics.py:74-80` — `stop_task()` 计算 | `metrics.py:113` report 输出 / `run_demo.py:138` 对比表 |
| 共享记忆命中率 | `memory_reuse_hits` / 总查询次数 | `metrics.py:59` — `record_store_op("search")` 时累加 | `metrics.py:108` report 输出 / `run_demo.py:137` 对比表 |
| 整体性能提升 | text 模式 vs structured 模式的各项差值 | `run_demo.py:118-140` — `print_comparison()` 计算差值百分比 | `run_demo.py:118-140` 终端输出对比表 |

### 7.2 双模式对比机制

**文件**: `run_demo.py:52-140`

执行流程：
1. **Phase 1** — text 模式跑 Task Group A + B，收集 `text_summary`（`run_demo.py:60-84`）
2. `metrics.reset()` 清空所有指标（`run_demo.py:86`）
3. **Phase 2** — structured 模式跑 Task Group A + B，收集 `struct_summary`（`run_demo.py:88-112`）
4. **Phase 3** — `print_comparison()` 输出对比表（`run_demo.py:118-140`）

`summary_dict()` 返回的 dict 结构（`metrics.py:137-148`）：
```python
{
    "message_count": len(message_log),        # Agent 间消息次数
    "param_chars": sum(参数字符数),             # 文本通信开销（参数）
    "result_chars": sum(结果字符数),            # 文本通信开销（结果）
    "embedding_transfers": embedding传递次数,
    "hidden_state_payloads_sent": hidden state payload发送次数,
    "hidden_state_payloads_received": hidden state payload接收次数,
    "total_task_time": 任务总耗时(秒),         # 单任务总耗时
    "total_node_time": 节点执行总耗时(秒),     # 纯计算时间
    "memory_reuse_hits": 记忆命中次数,         # 共享记忆命中率
}
```

### 7.3 最新 12 轮三通道实验对比数据

> 12 轮连续任务对比（v4 三通道结构化通信协议）

**实验条件**：容器 `multi-agent_wmw`，本地 `/data/models/Qwen3-8B`，`CHAT_BACKEND=transformers`，同时开启 `ENABLE_CONTEXT_PACKETS=1`、`ENABLE_EMBEDDING_TRANSFER=1`、`ENABLE_HIDDEN_STATE_TRANSFER=1`。

说明：容器内未设置 `DASHSCOPE_API_KEY`，因此 embedding 使用 `LocalHashEmbeddings` 本地 fallback。

#### LLM Token 对比（核心指标）

| 指标 | Text 模式 | Structured 三通道 | 差值 |
|------|-----------|------------------|------|
| LLM 调用次数 | 72 | 72 | 0 |
| **Input tokens** | **32,166** | **19,503** | **-12,663 (-39.37%)** |
| **Output tokens** | **13,281** | **13,121** | **-160 (-1.20%)** |
| **Total tokens** | **45,447** | **32,624** | **-12,823 (-28.22%)** |
| **Wall-clock 时间** | **633.1s** | **636.0s** | **+2.9s (+0.46%)** |

按 Agent 分解：

| Agent | Text (in/out) | Structured (in/out) | Token 变化 |
|-------|---------------|----------------------|------------|
| planner | 4,920 / 1,761 | 4,359 / 1,601 | -721 (-10.8%) |
| retriever ×36 | 2,626 / 6,912 | 2,541 / 6,912 | -85 (-0.9%) |
| executor | 19,984 / 2,304 | 7,391 / 2,304 | **-12,593 (-56.5%)** |
| summarizer | 4,636 / 2,304 | 5,212 / 2,304 | +576 (+8.3%) |

#### 三通道启用情况

| 指标 | 数值 |
|------|------|
| `context_packets_enabled` | 36 |
| `context_packets_disabled` | 0 |
| `embedding_transfers` | 36 |
| `embedding_received` | 36 |
| `hidden_state_payloads_sent` | 36 |
| `hidden_state_payloads_received` | 36 |
| `hidden_state_produced_planner` | 12 |
| `hidden_state_produced_retriever` | 36 |
| `hidden_state_used_executor_context_ranking` | 12 |
| `hidden_state_context_packets_skipped` | 12 |
| `hidden_state_context_chars_skipped` | 4,261 |
| `context_saved_chars` | 7,102 |

#### 净效果

- **LLM token 总量**：-12,823 tokens (-28.22%)
- **Input tokens 节省**：-12,663 tokens (-39.37%)
- **Executor 是最大受益者**：input tokens 从 19,984 降至 7,391，减少 12,593 tokens
- **三通道均被实际使用**：context packet 36 次、embedding 36 次、hidden state payload 36 次
- **时间基本持平**：+2.9s (+0.46%)

结果文件：`examples/multi_agent_demo/results_12rounds.json`。

## 八、文件改动清单

### v1 基础协议（4 轮短任务）

| 文件 | 类型 | 改动内容 |
|------|------|---------|
| `protocol.py` | 修改 | ActionType、AgentMessage、AgentCard、AgentRegistry |
| `metrics.py` | 修改 | 新增 message_log、通信指标报告 |
| `agents.py` | 修改 | Structured 模式下使用 AgentMessage 协议 |
| `graph.py` | 修改 | State 加 mode/messages/embedding_payloads 字段 |
| `run_demo.py` | 修改 | 双模式对比机制 |

### v3 上下文压缩协议（12 轮连续任务）

| 文件 | 类型 | 改动内容 |
|------|------|---------|
| `protocol.py` | 修改 | 新增 ContextPacket、build_context_packet()、select_context_packets()、format_context_for_prompt()、summarize_text()、extract_evidence_spans()、extract_tags() |
| `metrics.py` | 修改 | 新增 compression_log、record_context_compression()、上下文压缩指标报告 |
| `agents.py` | 修改 | retriever 使用 build_context_packet() 压缩文档，executor 使用 select_context_packets() + format_context_for_prompt()，summarizer 使用 analysis_digest |
| `graph.py` | 修改 | State 新增 context_packets 字段（Annotated[list[dict], operator.add]） |
| `run_12rounds.py` | 新增 | 12 轮连续任务测试脚本，支持双模式对比 |

`config.py`、`models.py`、`memory.py` 本次协议压缩说明不涉及结果更新。

## 九、赛题对应关系

| 赛题要求 | 状态 | 实现 |
|---------|------|------|
| 动作类型 | ✅ | `ActionType` 枚举（6 种） — `protocol.py:24-31` |
| 输入参数 | ✅ | `AgentMessage.params: dict` — `protocol.py:42` |
| 返回结果 | ✅ | `AgentMessage.result: dict` — `protocol.py:43` |
| 能力描述 | ✅ | `AgentCard` — `protocol.py:51-58` |
| 能力发现 | ✅ | `AgentRegistry.discover()` — `protocol.py:72-73` |
| 握手 | ✅ | Registry 查询 + 匹配 — `protocol.py:72-73` |
| 非文本传递 | ✅ | `embedding_payloads` + 独立 `hidden_state_payloads`，通过 `doc_key/ref_id` 与 `context_packets` 关联 |
| 不得自然语言透传 | ✅ | structured 模式：全文入 Store，下游消费 ContextPacket + Store key 引用 |
| 双模式对比 | ✅ | text vs structured — `run_demo.py:60-140`，12 轮连续任务 — `run_12rounds.py` |
