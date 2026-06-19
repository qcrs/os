# 上下文压缩技术详解

> 基于 `protocol.py` 中 `build_context_packet()` 的三层压缩机制，面向多 Agent 协作场景的低开销文本压缩方案。
> 不依赖 LLM，纯算法实现，零额外 API 调用开销。

## 一、设计目标

多 Agent 协作中，Retriever 生成的文档通常 1000-2000 字符，直接传给 Executor 会导致：

1. **Executor 输入 token 膨胀** — 3 个并行 Retriever 各传全文 → Executor 上下文窗口被撑满
2. **无关信息干扰** — 全文中只有 20% 和当前 query 相关，其余 80% 是噪声
3. **重复计算** — Summarizer 再次读全文做总结，浪费 token

压缩方案的核心思想：**不传全部内容，只传和当前任务最相关的部分，原文存在共享 Store 里按需取用。**

## 二、独立传递开关

当前通信协议把三类中间状态拆成三个独立开关，避免把语义向量和文本压缩强绑定在一起。

```bash
# 是否启用文本压缩包：Retriever 构造 context_packets，Executor 使用 compact evidence
ENABLE_CONTEXT_PACKETS=1

# 是否启用语义向量传递：Retriever 生成 embedding_payloads，Executor 可用 embedding_score 排序
ENABLE_EMBEDDING_TRANSFER=1

# 是否启用隐藏状态特征传递：Planner/Retriever 捕获 hidden state，Executor 可用 hidden_score 排序
ENABLE_HIDDEN_STATE_TRANSFER=1
```

三者分别控制不同通道：

| 开关 | 控制对象 | 状态类型 | 主要作用 | 是否依赖 context packet |
|------|----------|----------|----------|--------------------------|
| `ENABLE_CONTEXT_PACKETS` | `context_packets` | 压缩文本 + 引用 + 校验 | 减少进入 Executor prompt 的文本 | 不适用 |
| `ENABLE_EMBEDDING_TRANSFER` | `embedding_payloads` | 非文本语义向量 | 对 packet 或 raw document 做语义排序 | 否 |
| `ENABLE_HIDDEN_STATE_TRANSFER` | `planner_hidden_state` / `hidden_state_payloads` | 非文本隐藏状态特征 | 做 Agent 意图对齐和上下文路由 | 否 |

`ENABLE_CONTEXT_PACKETS=0` 只关闭文本压缩包，不关闭 embedding 或 hidden state。关闭后 structured 模式会回退到 `documents` / `document_payloads`：

```text
ENABLE_CONTEXT_PACKETS=1:
  Retriever → context_packets + embedding_payloads + hidden_state_payloads
  Executor  → 通过 doc_key/ref_id 关联 hidden_state_payloads，对 context_packets 做 embedding_score / hidden_score / lexical_score 融合排序
  Prompt    → compact evidence

ENABLE_CONTEXT_PACKETS=0:
  Retriever → documents + document_payloads + embedding_payloads + hidden_state_payloads
  Executor  → 通过 doc_key/ref_id 关联 hidden_state_payloads，对 raw documents 做 embedding_score / hidden_score / lexical_score 融合排序
  Prompt    → 被选中的完整 documents
```

因此，`context_compression` 是文本中间状态压缩；`embedding` 和 `hidden_state` 是非文本中间状态传递。它们只在 Executor 的候选选择策略层组合，不在生成和传递开关上互相依赖。

## 三、三层压缩架构

```
原始文档 (1800 字符)
    ↓
┌─────────────────────────────────────────────────────┐
│  第1层: 证据片段提取 (Evidence Spans)                 │
│  从全文中挖出和 query 最相关的 top-k 句子              │
│  每个片段带精确字符偏移和 SHA-256 哈希，可验证可回溯     │
│  → 4 个片段，每个最多 180 字符                         │
├─────────────────────────────────────────────────────┤
│  第2层: 摘要压缩 (Summary)                           │
│  把证据片段按 score 排序拼接，受 360 字符预算约束        │
│  纯算法拼接，不调 LLM                                 │
│  → 360 字符的压缩摘要                                 │
├─────────────────────────────────────────────────────┤
│  第3层: Prompt 渲染 (Format for Prompt)               │
│  只给 LLM 看 [doc_key#span_id] text 极简格式          │
│  去掉所有元数据、哈希、偏移量、诊断信息                  │
│  → LLM 实际接收的上下文                               │
└─────────────────────────────────────────────────────┘
压缩后 (~620 字符，压缩率 34%)
```

## 四、第1层：证据片段提取

### 3.1 入口函数

**代码**: `protocol.py:424-486` — `retrieve_evidence_spans()`

```python
def retrieve_evidence_spans(
    *,
    text: str,                    # 原始文档全文
    query: str,                   # 当前子查询
    max_items: int = 4,           # 最多选几个片段
    max_chars: int = 180,         # 每个片段最多多少字符
    doc_key: str | None = None,   # 文档 Store key
    min_score: float = 0.05,      # 最低分数阈值
) -> list[dict]:
```

### 3.2 候选片段拆分

**代码**: `protocol.py:574-626` — `_split_sentences_with_offsets()` + `_candidate_spans()`

先按句号/问号/感叹号/分号拆成句子级候选：

```
原文: "量子计算利用量子比特的叠加态实现并行计算。这种技术有望解决传统
       计算机无法处理的问题。IBM和Google正在积极研究量子纠错技术。"

拆分结果:
  候选1: "量子计算利用量子比特的叠加态实现并行计算。"
         char_start=0,  char_end=20
  候选2: "这种技术有望解决传统计算机无法处理的问题。"
         char_start=20, char_end=40
  候选3: "IBM和Google正在积极研究量子纠错技术。"
         char_start=40, char_end=55
```

对于超长句子（超过 `max_chars`），用滑动窗口进一步切分：

```python
# protocol.py:600-617 — 滑动窗口切分
window_size = max(max_chars, 80)   # 窗口大小
overlap = min(80, window_size // 4) # 重叠区域，避免在窗口边界截断句子
```

### 3.3 打分公式

**代码**: `protocol.py:438-448`

对每个候选片段计算和 query 的相关度：

```python
score = 0.72 * coverage + 0.18 * density + position_bonus + phrase_bonus
```

| 分量 | 权重 | 含义 | 计算方式 |
|------|------|------|---------|
| `coverage` | 0.72 | query 有多少关键词出现在片段中 | `匹配词数 / query总词数` |
| `density` | 0.18 | 片段中匹配词的密集程度 | `匹配词数 / 片段总词数` |
| `position_bonus` | 动态 | 靠前的片段略加分 | `0.05 * (1 - char_start / 总长度)` |
| `phrase_bonus` | 动态 | query 短语完整出现加分 | 每命中一个短语 +0.08，上限 0.16 |

**设计考量**:

- `coverage` 权重最高（0.72）— 确保选出的片段覆盖 query 的关键概念
- `density` 权重较低（0.18）— 避免选出"什么都提了一嘴但都不深入"的泛泛段落
- `position_bonus` 很小（0.05）— 文档开头通常有摘要/概述，略微偏好但不主导
- `phrase_bonus` — 鼓励选出 query 短语完整出现的片段，而非零散关键词

**打分示例**:

```
query = "量子计算 基本原理"

候选1: "量子计算利用量子比特的叠加态实现并行计算。"
  content_terms(query) = ["量子计算", "基本", "原理"]
  content_terms(候选1) = ["量子计算", "量子比特", "叠加态", "并行计算"]
  overlap = {"量子计算"} → 1
  coverage = 1/3 = 0.33
  density = 1/4 = 0.25
  score = 0.72*0.33 + 0.18*0.25 + 位置加分 + 短语加分 ≈ 0.33

候选2: "量子计算的基本原理包括量子叠加和量子纠缠。"
  overlap = {"量子计算", "基本", "原理"} → 3
  coverage = 3/3 = 1.0
  density = 3/6 = 0.5
  phrase_bonus = "量子计算"完整出现 → +0.08
  score = 0.72*1.0 + 0.18*0.5 + 位置加分 + 0.08 ≈ 0.89  ← 胜出
```

### 3.4 词项分词

**代码**: `protocol.py:629-639` — `_tokenize()` + `protocol.py:642-650` — `_content_terms()`

分词同时支持英文和中文：

```python
def _tokenize(text):
    # 英文: 连续字母+数字，至少2字符
    tokens = re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", lowered)
    # 中文: 2字、4字滑动窗口
    for chunk in re.findall(r"[一-鿿]+", lowered):
        tokens.extend(chunk[i:i+2] for i in range(0, len(chunk)-1, 2))  # 2字组合
        tokens.extend(chunk[i:i+4] for i in range(0, len(chunk)-3, 2))  # 4字组合
    return tokens

# 去除停用词后得到 content_terms
_STOPWORDS = {"the", "and", "for", ..., "包括", "以及", "之前", "基于", ...}
```

**示例**:

```
"量子计算的基本原理" → _tokenize → ["量子", "计算", "基本", "原理", "量子计算", "计算基本", "基本原理"]
去停用词后 → content_terms = ["量子计算", "基本", "原理"]
```

### 3.5 贪心选择（避免重叠）

**代码**: `protocol.py:458-483`

按 score 降序遍历，贪心选择不重叠的片段：

```python
used_ranges = []
for score, position, candidate, ... in scored:
    # 跳过和已选片段重叠的候选
    if _overlaps_existing(candidate["char_start"], candidate["char_end"], used_ranges):
        continue
    # 记录已选范围
    used_ranges.append((candidate["char_start"], candidate["char_end"]))
    evidence.append({...})
    if len(evidence) >= max_items:
        break
```

### 3.6 输出结构

每个证据片段包含完整的溯源信息：

```python
{
    "span_id": "ev1",
    "text": "量子计算利用量子比特的叠加态实现并行计算。",
    "score": 0.89,
    "matched_terms": ["量子计算", "基本", "原理"],
    "coverage": 1.0,
    "density": 0.5,
    "char_start": 0,
    "char_end": 20,
    "source_ref": {
        "doc_key": "doc_abc123",
        "char_start": 0,
        "char_end": 20,
        "text_hash": "a1b2c3d4e5f67890",  # SHA-256 前16位
    },
    "retrieval_method": "lexical_span_retrieval",
}
```

## 五、第2层：摘要压缩

### 4.1 证据拼接摘要

**代码**: `protocol.py:346-380` — `summarize_evidence_spans()`

把 top 证据片段按 score 降序拼接，受字符预算约束：

```python
def summarize_evidence_spans(*, evidence_spans, fallback_text, max_chars=360):
    ordered_spans = sorted(evidence_spans, key=lambda e: -e["score"])
    parts = []
    total_chars = 0
    for evidence in ordered_spans:
        text = evidence["text"].strip()
        prefix = f"{evidence['span_id']}: "
        remaining = max_chars - total_chars - len(prefix)
        if remaining <= 0:
            break
        snippet = text[:remaining].rstrip()
        parts.append(f"{prefix}{snippet}")
        total_chars += len(prefix) + len(snippet)
    return " ".join(parts)
```

**输出示例**:

```
ev1: 量子计算利用量子比特的叠加态实现并行计算。 ev2: 量子计算的基本原理包括量子叠加和量子纠缠。 ev3: IBM和Google正在积极研究量子纠错技术。
```

### 4.2 纯截断摘要（兜底）

**代码**: `protocol.py:383-405` — `summarize_text()`

当没有证据片段时，按句截断：

```python
def summarize_text(text, max_chars=360):
    sentences = _split_sentences(text)
    selected = []
    total = 0
    for sentence in sentences:
        if total + len(sentence) > max_chars and selected:
            break
        selected.append(sentence)
        total += len(sentence)
    return " ".join(selected)
```

**关键**: 整个压缩过程**不调 LLM**，纯字符串操作，零额外开销。

## 六、第3层：Prompt 渲染

### 5.1 极简格式

**代码**: `protocol.py:250-279` — `format_context_for_prompt()`

只给 LLM 看最关键的信息：

```python
def format_context_for_prompt(packets, *, evidence_per_doc=4):
    blocks = []
    for packet in packets:
        doc_key = packet["doc_key"]
        for evidence in packet["evidence_spans"][:evidence_per_doc]:
            text = _compact_evidence_text(evidence["text"])
            blocks.append(f"[{doc_key}#{evidence['span_id']}] {text}")
    return "\n".join(blocks)
```

**LLM 实际看到的**:

```
[doc_quantum_abc123#ev1] 量子计算利用量子比特的叠加态实现并行计算。
[doc_quantum_abc123#ev2] 量子计算的基本原理包括量子叠加和量子纠缠。
[doc_quantum_def456#ev1] 量子比特的相干时间是当前技术的主要瓶颈。
```

### 5.2 LLM 看不到的元数据

以下信息留在 Python 层，不传给 LLM：

```python
{
    "source_ref": {"char_start": 0, "char_end": 20, "text_hash": "a1b2c3d4..."},
    "verification": {"reliable": True, "valid_ref_count": 4, "invalid_refs": []},
    "retrieval_diagnostics": {
        "method": "lexical_span_retrieval",
        "query_coverage": 0.85,
        "covered_terms": ["量子计算", "原理"],
        "missing_terms": [],
        "requires_full_doc_lookup": False,
    },
    "original_chars": 1800,
    "compressed_chars": 620,
    "compression_ratio": 0.34,
}
```

## 七、验证机制

### 7.1 证据溯源验证

**代码**: `protocol.py:282-343` — `verify_context_packet()`

压缩可能丢失信息，验证机制确保证据可信：

```python
def verify_context_packet(packet, doc_text, *, query_text):
    for evidence in evidence_spans:
        char_start = evidence["source_ref"]["char_start"]
        char_end = evidence["source_ref"]["char_end"]

        # 1. 从原文按偏移量提取文本
        source_text = doc_text[char_start:char_end]

        # 2. 对比文本是否一致
        text_matches = _normalize_text(source_text) == _normalize_text(evidence["text"])

        # 3. 验证 SHA-256 哈希
        expected_hash = evidence["source_ref"]["text_hash"]
        actual_hash = _hash_text(source_text)
        hash_matches = expected_hash == actual_hash

        if not text_matches or not hash_matches:
            invalid_refs.append({"span_id": span_id, "reason": "text_or_hash_mismatch"})
```

### 7.2 查询覆盖率检查

```python
# query 的关键词有多少被证据覆盖
covered_terms = query_terms & context_terms
missing_terms = query_terms - context_terms
coverage = len(covered_terms) / len(query_terms)

# 覆盖率低于阈值则标记不可靠
reliable = all_refs_valid and has_evidence and coverage >= 0.35
requires_full_doc_lookup = not reliable
```

### 7.3 失败回填

当验证失败（`reliable=False`），Executor 从 Store 回填原文：

```python
# agents.py:426-479 — _verify_and_rehydrate_packets()
def _verify_and_rehydrate_packets(store, context_packets, ...):
    for packet in context_packets:
        doc_item = store.get(("docs",), packet["doc_key"])
        verification = verify_context_packet(packet, doc_item.value["text"])

        if not verification["reliable"]:
            # 回填: 取原文前 360 字符作为兜底证据
            _rehydrate_packet_from_store(packet, doc_item.value["text"])
```

## 八、包选择机制

### 8.1 混合打分

**代码**: `protocol.py:201-247` — `select_context_packets()`

当多个并行 Retriever 各自产出 ContextPacket，Executor 需要选择 top-k 最相关的：

```python
def select_context_packets(*, packets, query_text, query_embedding, embedding_payloads, top_k=3):
    for packet in packets:
        lexical = lexical_relevance(query_text, packet)    # 词面相似度
        vector_score = cosine_similarity(query_embedding, doc_vector)  # 向量相似度
        coverage = packet["retrieval_diagnostics"]["query_coverage"]

        # 有向量时: 0.65*向量 + 0.25*词面 + 0.1*覆盖率
        # 无向量时: 0.8*词面 + 0.2*覆盖率
        if vector_score is not None:
            score = 0.65 * vector_score + 0.25 * lexical + 0.1 * coverage
        else:
            score = 0.8 * lexical + 0.2 * coverage
```

### 8.2 词面相似度

**代码**: `protocol.py:527-539` — `lexical_relevance()`

Jaccard 相似度：

```python
def lexical_relevance(query_text, packet):
    query_terms = set(_content_terms(query_text))
    packet_terms = set(_content_terms(packet_text))  # summary + tags + evidence
    return len(query_terms & packet_terms) / len(query_terms | packet_terms)
```

## 九、与 Text 模式的对比

### 9.1 数据流对比

```
Text 模式:
  Retriever → 1800 字符全文 → State["documents"] → Executor 读全文 → LLM
              每个 Retriever 都传全文，3 个 = 5400 字符

Structured 模式:
  Retriever → 1800 字符全文 → Store（不传）
            → ContextPacket (620 字符) → State["context_packets"] → Executor
            → select top-k → format → LLM 只看 ~400 字符
```

### 9.2 Token 消耗对比（12 轮实验）

| Agent | Text 模式 Input | Structured 模式 Input | 节省 |
|-------|----------------|---------------------|------|
| Planner | 5,987 | 5,569 | -7.5% |
| Retriever ×36 | 2,522 | 2,432 | -7.4% |
| **Executor** | **47,606** | **17,097** | **-64.1%** |
| Summarizer | 13,146 | 10,731 | -17.4% |
| **总计** | **69,261** | **35,829** | **-48.3%** |

Executor 是最大受益者，因为上下文压缩包替代了全文透传。

### 9.3 压缩效果

| 指标 | 数值 |
|------|------|
| 压缩前总字符数 | 103,366 |
| 压缩后总字符数 | 48,030 |
| **压缩率** | **53.5%** |
| 上下文压缩包数 | 36 |
| 证据片段/文档 | 2-4 |
| 最佳 Top-K | 3 |

## 十、压缩的本质

```
传统方式（Text 模式）:
  Agent A 生成 1800 字符全文 → 原封不动传给 Agent B
  Agent B 读 1800 字符 → 其中只有 ~400 字符和任务相关

当前方式（Structured 模式）:
  Agent A 生成 1800 字符全文 → 存入共享 Store
                             → 提取 4 个证据片段 (720 字符)
                             → 生成摘要 (360 字符)
                             → 只传压缩包给 Agent B
  Agent B 收到 620 字符压缩包 → 选择 top-k → 渲染为 ~400 字符 prompt
  Agent B 需要更多上下文时 → 用 doc_key 从 Store 回填原文
```

**一句话总结**: 全文存 Store，压缩包走通信，LLM 只看和任务最相关的证据片段。
