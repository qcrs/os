# 多智能体隐藏状态特征传递机制说明

本文档说明当前仓库根目录 demo 中狭义隐藏状态特征在 Agent 间的工作方式，包括生成方式、传递方式、接收方式和后续使用方式。

## 1. 当前定位

当前实现的隐藏状态特征不是普通文本摘要，也不是外部 embedding API 生成的语义向量，而是本地 Transformers 模型在前向计算中产生的中间表示。

在当前 demo 中：

- 本地模型：`/data/models/Qwen3-8B`
- 推理后端：Hugging Face `transformers` + `torch`
- 触发开关：`CHAT_BACKEND=transformers`、`ENABLE_HIDDEN_STATE_TRANSFER=1`
- 独立开关：`ENABLE_CONTEXT_PACKETS=1` 控制文本压缩包，`ENABLE_EMBEDDING_TRANSFER=1` 控制语义向量传递，`ENABLE_HIDDEN_STATE_TRANSFER=1` 控制隐藏状态传递
- 主要传递对象：`planner_hidden_state`、`hidden_state_payloads`
- 下游使用方式：开启 context packet 时按 `doc_key/ref_id` 关联 hidden payload 后执行 context packet 重排、prompt 裁剪；关闭时对 raw documents 做 hidden-state routing。这里的 hidden state 只提供排序/裁剪信号，不会给 `context_packets` 本身追加新的可读“意图文本”。

需要说明的是，当前实现已经让下游 Agent 使用隐藏状态特征做路由和上下文选择，但还没有把 hidden state 注入到下游模型内部的 KV cache、attention、prefix embedding 或中间层中，也没有把 hidden vector 解码成新的自然语言意图说明后加入 `context_packets`。

## 2. 总体数据流

```text
用户查询
   │
   ▼
Planner
   │
   ├─ 先捕获 planner_hidden_state
   │
   └─ 再生成 plan / sub_queries
          │
          ▼
Retriever_1 / Retriever_2 / Retriever_3
   │
   ├─ 接收 planner_hidden_state
   ├─ 先捕获各自 retriever_intent_hidden_state
   ├─ 再生成检索文本
   ├─ 计算 planner/retriever intent 相似度
   └─ 输出 hidden_state_payloads + hidden_state_ref / intent_alignment
          │
          ▼
Executor
   │
   ├─ 接收 planner_hidden_state
   ├─ 基于 hidden_score 重排 context_packets
   ├─ 选择 top-k context packets
   └─ 输出 hidden_guidance
          │
          ▼
Summarizer
   │
   ├─ 接收 hidden_guidance
   ├─ 看到 selected_doc_keys / avg_hidden_score 等路由摘要
   └─ 输出最终 summary / key_findings
```

## 3. 生成方式

### 3.1 本地 Transformers 后端

隐藏状态特征只能从本地模型对象中直接拿到，因此当前实现新增了本地 Transformers 后端。

相关代码：

- `src/models.py`
- `LocalTransformersChatModel`
- `_capture_pre_generation_hidden_state()`

模型加载方式：

```python
tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL_PATH, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    LOCAL_MODEL_PATH,
    torch_dtype=torch_dtype,
    trust_remote_code=True,
)
model.to(LOCAL_MODEL_DEVICE)
model.eval()
```

### 3.2 推理顺序

每个 Agent 的本地 Qwen3-8B 调用顺序是：先 forward 捕获 hidden state，再调用 `generate()` 输出文本。

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
model(..., output_hidden_states=True)
   │
   ├─ 捕获 prompt 最后一个 token 的 hidden state
   │
   ▼
model.generate(...)
   │
   └─ generated text
```

对于 `Planner`，生成文本会被解析为：

```json
{
  "plan": "...",
  "sub_queries": ["...", "...", "..."]
}
```

对于 `Retriever`，生成文本就是对应子查询的检索/说明文档。

### 3.3 隐藏状态捕获

在调用 `model.generate()` 之前，代码先对 prompt tokens 做一次 forward pass：

```python
outputs = model(**inputs, output_hidden_states=True, use_cache=False)
last_hidden = outputs.hidden_states[-1][0]
```

然后取最后一层中 prompt 最后一个 token 的 hidden state。这个位置的 hidden state 正是 causal LM 用来预测第一个输出 token 的状态：

```text
prompt tokens
   │
   ▼
outputs.hidden_states[-1][-1]
   │
   ▼
pre-generation next-token hidden vector
   │
   ▼
model.generate(...) 输出文本
```

当前默认 pooling 方式：

```bash
LOCAL_HIDDEN_POOLING=last_token
```

如果显式设置 `LOCAL_HIDDEN_POOLING=mean`，则会对 prompt token span 做 mean pooling，但仍然发生在文本生成之前。

### 3.4 隐藏状态 payload

生成前捕获的隐藏状态会序列化为 dict：

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
  "source_text_hash": "...",
  "input_tokens": 512,
  "output_tokens": 0,
  "next_token_index": 512
}
```

字段含义：

| 字段 | 含义 |
|------|------|
| `kind` | payload 类型，表示这是 transformer hidden state |
| `capture_stage` | 捕获阶段，当前为 `pre_generation` |
| `source` | hidden state 来源，当前为 `prompt` |
| `prediction_target` | 该 hidden state 的预测目标，当前为 `next_token` |
| `model` | 产生 hidden state 的模型名称 |
| `model_path` | 本地模型路径 |
| `layer` | 使用的层，`-1` 表示最后一层 |
| `pooling` | pooling 方式，当前默认 `last_token` |
| `pooled_token_span` | pooling 覆盖的 token 范围 |
| `dims` | 向量维度，Qwen3-8B 当前为 `4096` |
| `norm` | 向量范数 |
| `dtype` | 序列化后的数据类型说明 |
| `vector` | 实际隐藏状态向量 |
| `source_token_hash` | prompt token 序列 hash，用于追踪 |
| `source_text_hash` | 兼容字段，与 `source_token_hash` 一致 |
| `input_tokens` | 输入 token 数 |
| `output_tokens` | 捕获时输出 token 数，生成前捕获时为 `0` |
| `next_token_index` | 即将预测的第一个输出 token 位置 |

## 4. 独立传递开关

当前实现把文本压缩、语义向量、隐藏状态拆成三个独立环境变量：

```bash
# 文本压缩包：Retriever 输出 context_packets，Executor 使用 compact evidence
ENABLE_CONTEXT_PACKETS=1

# 语义向量：Retriever 输出 embedding_payloads，Executor 使用 embedding_score 排序
ENABLE_EMBEDDING_TRANSFER=1

# 隐藏状态：Planner/Retriever 捕获 hidden state，Executor 使用 hidden_score 排序
ENABLE_HIDDEN_STATE_TRANSFER=1
```

三种开关互不依赖：

| 配置 | 控制对象 | Executor 使用方式 | token 影响 |
|------|----------|-------------------|------------|
| `ENABLE_CONTEXT_PACKETS=1` | `context_packets` | 对 compact packets 做 `hidden_score` / `embedding_score` / `lexical_score` 融合排序 | 通常减少进入 LLM prompt 的文本 token |
| `ENABLE_CONTEXT_PACKETS=0` | `documents` / `document_payloads` | 对 raw documents 做 `hidden_score` / `embedding_score` / `lexical_score` 融合排序 | 不做文本压缩，但仍可减少进入 LLM 的文档数量 |
| `ENABLE_EMBEDDING_TRANSFER=0` | `embedding_payloads` | 关闭语义向量生成和 `embedding_score` | 不影响 context packet 或 hidden state |
| `ENABLE_HIDDEN_STATE_TRANSFER=0` | `planner_hidden_state` / `hidden_state_payloads` | 关闭 hidden 捕获和 `hidden_score` | 不影响 context packet 或 embedding |

注意：`ENABLE_CONTEXT_PACKETS` 只控制文本压缩包，不控制 embedding 或 hidden state。关闭 context packet 后，Executor 仍可用 `document_payloads` + `embedding_payloads` + `hidden_state_payloads` + `planner_hidden_state` 对 raw documents 排序。

## 5. 传递方式

### 5.1 LangGraph State 传递

`Planner` 生成 `planner_hidden_state` 后，会写入图状态：

```python
result["planner_hidden_state"] = planner_hidden_state
```

状态 schema 中包含该字段：

```python
class ResearchState(TypedDict, total=False):
    planner_hidden_state: dict
    planner_hidden_state_summary: dict
```

### 5.2 Send fan-out 传递给 Retriever

`Planner` 到多个 `Retriever` 的 fan-out 使用 LangGraph `Send`：

```python
Send("retriever", {
    "sub_query": sq,
    "task_group": task_group,
    "mode": mode,
    "planner_hidden_state": planner_hidden_state,
})
```

这意味着每个并行 `Retriever` 都会收到同一个 `planner_hidden_state`。

### 5.3 AgentMessage 结构化消息传递

结构化通信协议中的 `AgentMessage` 增加了 `hidden_state` 字段：

```python
@dataclass
class AgentMessage:
    ...
    hidden_state: dict | None = None
```

消息创建时会显式携带 hidden state：

```python
make_message(
    source="planner",
    target="retriever",
    action=ActionType.PLAN,
    ...,
    hidden_state=planner_hidden_state,
)
```

因此 hidden state 同时存在于：

```text
ResearchState.planner_hidden_state
AgentMessage.hidden_state
hidden_state_payloads
metrics counters
```

## 6. 接收方式

### 6.1 Retriever 接收

每个 `Retriever` 从 state 中读取：

```python
planner_hidden_state = state.get("planner_hidden_state")
_record_hidden_state_received("retriever", planner_hidden_state)
```

随后 `Retriever` 在生成检索文本之前捕获 `retriever_intent_hidden_state`，并计算与 `planner_hidden_state` 的相似度：

```python
retriever_intent_hidden_state = _extract_hidden_state(response)
intent_alignment = _hidden_state_alignment(planner_hidden_state, retriever_intent_hidden_state)
```

其中 `_hidden_state_alignment()` 内部使用 cosine similarity：

```python
cosine_similarity(planner_intent_vector, retriever_intent_vector)
```

### 6.2 Executor 接收

`Executor` 读取：

```python
planner_hidden_state = state.get("planner_hidden_state")
_record_hidden_state_received("executor", planner_hidden_state)
```

同时它会收到所有并行 `Retriever` 输出的 `context_packets` 和独立的 `hidden_state_payloads`。两者通过 `doc_key` / `hidden_state_ref` 关联：

```text
context_packet.hidden_state_ref = doc_key
hidden_state_payload.ref_id = doc_key
hidden_state_payload.hidden_state = retriever_intent_hidden_state
hidden_state_payload.intent_alignment = intent_alignment
```

### 6.3 Summarizer 接收

`Summarizer` 读取：

```python
planner_hidden_state = state.get("planner_hidden_state")
hidden_guidance = state.get("hidden_guidance", {})
_record_hidden_state_received("summarizer", planner_hidden_state)
```

其中 `hidden_guidance` 是 `Executor` 基于 hidden-state routing 产生的路由摘要。它只描述“选中了哪些 doc_key、跳过了多少候选、平均 hidden 分数是多少”，不是从 hidden vector 还原出的语义意图文本。

## 7. 后续使用方式

### 7.1 Retriever：生成检索 prompt hidden state 和 intent_alignment

`Retriever` 不再只是接收 `planner_hidden_state`，还会在生成检索文本之前捕获自己的 `retriever_intent_hidden_state`。这里变量名里的 `intent` 表示“Retriever prompt 在隐空间中的任务表示”，不是显式自然语言意图，也不是额外写入 `context_packet.summary` 或 `evidence_spans` 的内容。

```text
sub_query
   │
   ▼
Retriever prompt tokens
   │
   ▼
捕获 retriever_intent_hidden_state
   │
   ▼
cosine(planner_hidden_state, retriever_intent_hidden_state)
   │
   ▼
intent_alignment
   │
   ▼
Retriever 生成 doc_text
```

然后写入独立的 `hidden_state_payloads` 通道，`context_packet` 或 `document_payload` 只保留引用：

```python
hidden_state_payload = {
    "ref_id": doc_key,
    "doc_key": doc_key,
    "source_agent": "retriever",
    "target_agent": "executor",
    "scope": "retrieval_intent",
    "hidden_state": retriever_intent_hidden_state,
}
context_packet["hidden_state_ref"] = doc_key
```

这个步骤的作用是把 Planner prompt hidden vector 与 Retriever prompt hidden vector 之间的隐空间相似度显式化。它提供的是 `intent_alignment` / `hidden_score` 这样的排序特征，而不是给下游 LLM 增加新的可读意图信息。

### 7.2 Executor：hidden-state routing 和 context packet 重排

`Executor` 调用：

```python
selected_packets = select_context_packets(
    packets=context_packets,
    query_text=f"{query}\n{plan}",
    query_embedding=query_embedding,
    embedding_payloads=embedding_payloads,
    hidden_state_payloads=hidden_state_payloads,
    planner_hidden_state=planner_hidden_state,
    top_k=HIDDEN_STATE_CONTEXT_TOP_K if planner_hidden_state else 3,
)
```

`select_context_packets()` 内部会计算：

```text
hidden_score = cosine(planner_hidden_state.vector, hidden_state_payloads[packet.doc_key].vector)
```

如果同时有 embedding 分数，则综合打分：

```text
score = 0.45 * hidden_score
      + 0.35 * vector_score
      + 0.15 * lexical_score
      + 0.05 * coverage
```

如果没有 embedding 分数，但有 hidden 分数：

```text
score = 0.65 * hidden_score
      + 0.25 * lexical_score
      + 0.10 * coverage
```

最终按 `score` 降序排序，并只选择 top-k。

当前默认：

```bash
HIDDEN_STATE_CONTEXT_TOP_K=2
```

也就是说，如果有 3 个 Retriever 输出的 context packet，Executor 默认只让 hidden-state 分数较高的前 2 个进入后续 prompt。被选中的 packet 文本内容仍然来自原始 `summary` / `evidence_spans`；hidden state 改变的是选择顺序和裁剪范围，不改变 packet 内的证据文本。

### 7.3 Executor：hidden-guided prompt 裁剪

当 hidden guidance 生效时，Executor 还会进一步压缩进入 prompt 的 evidence：

```bash
HIDDEN_STATE_EVIDENCE_PER_DOC=1
HIDDEN_STATE_EVIDENCE_CHARS=120
```

也就是：

```text
每个选中文档最多传 1 条 evidence
每条 evidence 最多 120 字符
```

这样 hidden state 带来的直接收益不是“凭空提高模型智力”，也不是“向 context packet 注入意图信息”，而是：

```text
更少上下文进入 Executor prompt
低相关文档被裁掉
每个文档只保留最关键 evidence
```

### 7.4 Executor：生成 hidden_guidance

`Executor` 会生成 `hidden_guidance`：

```json
{
  "used": true,
  "candidate_packets": 3,
  "selected_packets": 2,
  "context_top_k": 2,
  "skipped_packets": 1,
  "selected_doc_keys": ["doc_a", "doc_b"],
  "avg_hidden_score": 0.9133,
  "top_hidden_score": 0.9152,
  "skipped_original_chars": 159
}
```

字段含义：

| 字段 | 含义 |
|------|------|
| `used` | 是否实际使用 hidden-state routing |
| `candidate_packets` | 候选 context packet 数 |
| `selected_packets` | 最终选中的 context packet 数 |
| `context_top_k` | top-k 配置 |
| `skipped_packets` | 被裁掉的 packet 数 |
| `selected_doc_keys` | 被选中的文档 key |
| `avg_hidden_score` | 选中文档平均 hidden 相似度 |
| `top_hidden_score` | 最高 hidden 相似度 |
| `skipped_original_chars` | 被裁掉文档的原始字符数 |

### 7.5 Summarizer：使用 hidden_guidance 控制摘要重点

`Summarizer` 会把 `hidden_guidance` 渲染成紧凑提示信息：

```text
Hidden-state routing: Planner/retriever intent alignment selected 2 of 3 context packets;
selected_doc_keys=[...]; avg_hidden_score=0.9133.
```

这个信息会放入 Summarizer prompt：

```python
HumanMessage(content=f"""Original query: {query}
Research plan: {plan}{_hidden_guidance_prompt(hidden_guidance)}
Analysis: {analysis_for_prompt}
Evidence:
{evidence_text}""")
```

这样 Summarizer 能知道哪些文档是根据 Planner 隐空间意图筛选出来的，从而围绕这些高相关来源组织最终摘要。

## 8. 指标统计

当前 metrics 会统计 hidden state 的生产、传递和使用情况。

主要指标：

| 指标 | 含义 |
|------|------|
| `hidden_state_produced_planner` | Planner 生成 hidden state 次数 |
| `hidden_state_produced_retriever` | Retriever 生成 pre-generation intent hidden state 次数 |
| `hidden_state_transfers` | AgentMessage 中携带 hidden state 的次数 |
| `hidden_state_received_retriever` | Retriever 接收 hidden state 次数 |
| `hidden_state_received_executor` | Executor 接收 hidden state 次数 |
| `hidden_state_received_summarizer` | Summarizer 接收 hidden state 次数 |
| `hidden_state_alignment_scored_retriever` | Retriever 计算 intent alignment 次数 |
| `hidden_state_used_executor_context_ranking` | Executor 使用 hidden state 做 context 排序次数 |
| `hidden_state_used_summarizer_guidance` | Summarizer 使用 hidden guidance 次数 |
| `hidden_state_context_packets_skipped` | hidden routing 裁掉的 context packet 数 |
| `hidden_state_context_chars_skipped` | hidden routing 裁掉的原始上下文字符数 |
| `context_packets_enabled` | Retriever 启用 context packet 输出次数 |
| `context_packets_disabled` | Retriever 关闭 context packet 并回退完整文档次数 |
| `context_packet_fallback_documents` | Executor 在 structured 模式下回退完整文档输入次数 |

## 9. 当前验证结果

### 9.1 协议层轻量对照

在不加载模型的协议层测试中，构造同一批 3 个 context packet：

```text
不用 hidden routing：3 个 packet 全部进入 prompt
使用 hidden routing：按 hidden_score 选择 top-2
```

示例结果：

```json
{
  "all_packets": 3,
  "selected_packets": 2,
  "all_context_chars": 266,
  "hidden_context_chars": 181,
  "saved_chars": 85,
  "saved_pct": 32.0,
  "selected_doc_keys": ["doc_good_1", "doc_good_2"]
}
```

这个测试证明 hidden state 能实际改变 context 选择，并减少进入 prompt 的上下文字符数。

### 9.2 本地 Qwen3-8B smoke test

真实本地模型 smoke test 中：

```json
{
  "sub_queries": 3,
  "hidden_state_transfers": 6,
  "hidden_state_produced_planner": 1,
  "hidden_state_produced_retriever": 3,
  "hidden_state_used_executor_context_ranking": 1,
  "hidden_state_used_summarizer_guidance": 1,
  "hidden_state_context_packets_skipped": 1,
  "hidden_state_context_chars_skipped": 159
}
```

这说明当前实现已经完成：

```text
生成 pre-generation hidden state
传递 hidden state
下游接收 hidden state
下游使用 hidden state 做 context routing
Summarizer 使用 hidden guidance 控制摘要
```

## 10. 当前实现边界

当前实现属于“hidden-state routing + prompt 裁剪”，不是模型内部状态续算。

已经实现：

```text
Planner hidden state 生成
Retriever pre-generation intent hidden state 生成
Agent 间 hidden state 显式传递
Planner/retriever intent hidden 相似度计算
Executor context packet 重排
Executor prompt 裁剪
Summarizer hidden guidance 使用
相关指标统计
```

尚未实现：

```text
把 hidden state 注入下游模型 attention
把 hidden state 作为 prefix embedding 输入模型
跨 Agent 传递 KV cache
跨 Agent 复用中间层激活继续推理
训练 adapter 来消费 hidden state
```

因此当前收益主要体现在：

```text
减少下游 prompt 上下文
降低低相关证据进入分析链路的概率
让摘要阶段知道哪些证据更贴近 Planner 意图
为后续质量/成本对照实验提供可统计指标
```

如果要进一步实现“模型内部级别”的 hidden state 使用，需要改模型结构或推理过程，例如 prefix adapter、cross-attention adapter、KV cache 共享或 hidden-state-conditioned reranker。
