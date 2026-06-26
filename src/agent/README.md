# Agent 工作流说明

当前系统里有 5 个真实 agent：

```text
planner → researcher(s) → analyst → executor → summarizer
```

其中 `researcher` 会根据 planner 拆出的多个 `sub_queries` 并行运行，之后通过 LangGraph 的 `operator.add` reducer 汇总到同一个 `analyst`。

---

## 1. Analyst 是什么意思，具体干什么？

`analyst` 可以理解为“研究分析员”或“证据分析员”。它不是检索器，也不是代码执行器，更不是最终总结器。

它的位置在：

```text
researcher(s) → analyst → executor
```

它的核心职责是：

1. 从多个 researcher 产出的材料里选出最相关的上下文。
2. 校验这些上下文是不是还能回溯到 Store 里的原始文档。
3. 必要时从 Store 回补一小段原文，避免压缩证据不可靠。
4. 基于选中的可靠上下文，让 LLM 生成结构化分析。
5. 输出 `analysis` 和 `evidence`，交给 executor 做后续 CodeAct 检查。

换句话说，`analyst` 是从“材料”到“可用论证”的中间层：

```text
原始研究材料 / context packets
        ↓
筛选、排序、验证、回补
        ↓
结构化分析 analysis + evidence
```

### Analyst 的输入

`analyst` 主要读取这些 state 字段：

| 字段 | 来源 | 含义 |
|---|---|---|
| `query` | 用户输入 | 原始问题 |
| `plan` | planner | 研究计划 |
| `documents` | researcher | text 模式下的完整研究材料 |
| `document_payloads` | researcher | structured 模式下的文档元数据 |
| `context_packets` | researcher | 压缩后的上下文包 |
| `embedding_payloads` | researcher | 文档向量，用于排序 |
| `hidden_state_payloads` | researcher | researcher intent hidden state，用于意图对齐排序 |
| `planner_hidden_state` | planner | planner 的 hidden state，用于和 researcher intent 做相似度判断 |

### Analyst 的处理流程

`analyst` 做的事情可以分成 4 步：

#### 1. 选择上下文

如果启用了 structured mode 和 context packet，它会调用 context packet 选择逻辑，从多个 researcher 产出的上下文包里选出 top-k。

排序信号包括：

- query / plan 的词面相关性
- embedding 相似度
- planner hidden state 和 researcher hidden state 的相似度
- packet 自身的 coverage / diagnostics

目的不是“再检索一次”，而是从已有 researcher 材料中挑出最值得进入分析 prompt 的部分。

#### 2. 校验证据

`analyst` 会根据 `context_packet.doc_key` 回到 Store 的 `NS_DOCS` 里取完整文档，然后校验：

- `full_doc_ref.text_hash` 是否匹配原文
- evidence span 的 `char_start` / `char_end` 是否有效
- evidence 文本是否能和原文片段对上
- evidence hash 是否一致

如果 evidence 可以回溯到原始文档，就认为这个 packet 结构上可靠。

#### 3. 必要时 rehydrate

如果 packet 不可靠，比如：

- Store 里找不到原文
- span offset 越界
- evidence 文本和原文片段对不上
- hash 不一致

`analyst` 会走 fallback，从 Store 里截取一小段原文作为补充 evidence。这个过程叫 `rehydrate`。

这样可以避免两种问题：

- 不可靠压缩证据直接进入分析
- 为了安全又把全文都塞进 prompt

#### 4. 生成结构化分析

最后 `analyst` 调 LLM，要求只基于可靠或 rehydrated 的证据输出 JSON：

```json
{
  "analysis": "A comprehensive analysis paragraph",
  "evidence": [
    {
      "claim": "Key claim",
      "support": "Supporting evidence",
      "doc_key": "doc id",
      "span_id": "ev1"
    }
  ],
  "confidence": 0.85
}
```

`analyst` 的输出是给 executor 用的，不是最终答案。

### Analyst 的输出

| 字段 | 含义 |
|---|---|
| `analysis` | 结构化分析正文 |
| `analysis_digest` | 压缩后的分析摘要，给 summarizer 降低 prompt 成本 |
| `evidence` | claim/support/doc_key/span_id 形式的证据列表 |
| `selected_context_packets` | 被选中并校验后的上下文包 |
| `context_verification` | 校验统计，例如 reliable、rehydrated、failed 数量 |
| `hidden_guidance` | hidden-state routing 对上下文选择的影响 |

### Analyst 和 Executor 的区别

| Agent | 主要问题 | 输出 |
|---|---|---|
| `analyst` | “这些材料能支持什么结论？” | `analysis`、`evidence` |
| `executor` | “对这些结论和证据做一个简单可执行检查，得到什么 artifact？” | `execution_code`、`execution_result`、`execution_summary` |

所以 `analyst` 是判断和分析，`executor` 是执行一个受限 CodeAct 步骤。

---

## 2. 五个 Agent 分工

### 2.1 Planner

`planner` 是任务规划 agent。

它负责把用户的原始 `query` 拆成一个研究计划和 3 个子查询。

输入：

```text
query
```

输出：

```text
plan
sub_queries
planner_hidden_state
```

写入记忆：

```text
NS_PLANS = ("plans",)
```

典型职责：

- 理解用户问题
- 规划研究路径
- 拆出 3 个互补的 sub-query
- structured mode 下生成 planner hidden state，供后续 hidden-state routing 使用

---

### 2.2 Researcher

`researcher` 是研究材料生成和上下文打包 agent。

它会针对 planner 生成的每个 `sub_query` 并行运行。

输入：

```text
sub_query
planner_hidden_state
```

输出：

```text
documents
context_packets
document_payloads
embedding_payloads
hidden_state_payloads
```

写入记忆：

```text
NS_DOCS = ("docs",)
```

典型职责：

- 根据 sub-query 生成研究材料
- 把完整材料写入 Store
- 构造 compact context packet
- 生成 embedding payload
- 生成 researcher intent hidden state
- 计算 planner/researcher intent alignment

注意：当前 researcher 不是严格意义上的外部搜索 retriever。它主要是“研究材料生成 + 上下文打包”。如果以后接入搜索引擎、向量库或真实文档库，可以在 researcher 里扩展。

---

### 2.3 Analyst

`analyst` 是证据分析 agent。

输入：

```text
plan
documents / context_packets
embedding_payloads
hidden_state_payloads
planner_hidden_state
```

输出：

```text
analysis
analysis_digest
evidence
selected_context_packets
context_verification
hidden_guidance
```

写入记忆：

```text
NS_ANALYSIS = ("analysis",)
```

典型职责：

- 从多个 researcher 输出中选择最相关上下文
- 校验 context packet 是否可回溯
- 必要时从 Store rehydrate
- 基于可靠证据生成结构化分析
- 产出 evidence，供 executor 和 summarizer 使用

---

### 2.4 Executor

`executor` 是执行 agent，目前实现的是一个简单、安全、受限的 CodeAct 步骤。

它不是 analyst 的别名，而是真实独立节点。

输入：

```text
analysis
analysis_digest
evidence
selected_context_packets
hidden_guidance
```

输出：

```text
execution_code
execution_result
execution_summary
```

写入记忆：

```text
NS_EXECUTIONS = ("executions",)
```

当前 CodeAct 做的事情：

- 根据 `evidence` 和 `selected_context_packets` 自动生成一段小 Python 代码
- 校验 AST，只允许白名单语法节点
- 只开放基础内置函数，例如 `len`、`sum`、`sorted`、`set`、`round`
- 不允许 shell
- 不读写文件
- 不访问网络
- 执行后产出 metrics

当前 metrics 包括：

```text
evidence_count
supported_claims
unique_doc_keys
reliable_packets
rehydrated_packets
coverage_ratio
hidden_routing_used
analysis_chars
```

它的作用是给 summarizer 一个可执行检查产物，而不是让 LLM 直接口头判断所有事情。

---

### 2.5 Summarizer

`summarizer` 是最终总结 agent。

输入：

```text
query
plan
analysis / analysis_digest
evidence
execution_result
execution_summary
hidden_guidance
```

输出：

```text
summary
key_findings
recommendations
```

写入记忆：

```text
NS_SUMMARIES = ("summaries",)
```

典型职责：

- 综合 planner 的计划
- 综合 analyst 的分析和证据
- 综合 executor 的 CodeAct 结果
- 输出面向用户的最终总结
- 写入 summary memory，供后续任务复用

---

## 3. 完整工作流

### Step 1：用户输入 query

用户输入一个研究问题：

```text
query = "分析 LangGraph 多智能体通信机制"
```

初始 state 类似：

```python
{
    "query": query,
    "task_group": "default",
    "mode": "structured"
}
```

---

### Step 2：Planner 规划任务

`planner` 读取 `query`，生成：

```python
{
    "plan": "研究 LangGraph 的图结构、状态传递和多 agent 协作机制",
    "sub_queries": [
        "LangGraph 的 StateGraph 和节点调度机制",
        "LangGraph 的 Send fan-out 和 reducer fan-in 机制",
        "LangGraph 的 Store 和跨任务记忆机制"
    ],
    "planner_hidden_state": {...}
}
```

然后 graph 通过 `fan_out_research()` 把 3 个 sub-query 发给多个 researcher。

---

### Step 3：Researcher 并行生成材料

LangGraph 会并行派发：

```text
Send("researcher", {"sub_query": sub_query_1})
Send("researcher", {"sub_query": sub_query_2})
Send("researcher", {"sub_query": sub_query_3})
```

每个 researcher 输出一份材料：

```python
{
    "documents": [...],
    "context_packets": [...],
    "embedding_payloads": [...],
    "hidden_state_payloads": [...]
}
```

多个 researcher 的 list 输出会通过 reducer 自动合并。

---

### Step 4：Analyst 筛选和分析证据

`analyst` 接收所有 researcher 的输出。

它会：

1. 根据 query/plan、embedding、hidden state 对 context packets 排序。
2. 选出 top-k packets。
3. 回 Store 校验 packet 的 evidence spans。
4. 必要时 rehydrate。
5. 调 LLM 生成结构化 `analysis` 和 `evidence`。

输出类似：

```python
{
    "analysis": "LangGraph 的多智能体通信依赖 StateGraph、Send fan-out、reducer fan-in 和 Store...",
    "analysis_digest": "LangGraph 通过图结构和状态 channel 支持多 agent 协作...",
    "evidence": [
        {
            "claim": "Send 支持动态 fan-out",
            "support": "...",
            "doc_key": "doc_xxx",
            "span_id": "ev1"
        }
    ],
    "selected_context_packets": [...],
    "context_verification": {...},
    "hidden_guidance": {...}
}
```

---

### Step 5：Executor 执行 CodeAct

`executor` 读取 analyst 的分析和证据，生成并执行一段受限 Python 代码。

生成的代码大致做这些统计：

```python
doc_keys = sorted(set(item["doc_key"] for item in evidence if item["doc_key"]))
supported_claims = sum(1 for item in evidence if item["support"])
coverage_ratio = round(supported_claims / max(len(evidence), 1), 4)
```

输出类似：

```python
{
    "execution_code": "...",
    "execution_result": {
        "ok": True,
        "stdout": "CodeAct metrics: {...}",
        "metrics": {
            "evidence_count": 3,
            "supported_claims": 3,
            "unique_doc_keys": 2,
            "coverage_ratio": 1.0,
            "reliable_packets": 2,
            "rehydrated_packets": 0,
            "hidden_routing_used": True,
            "analysis_chars": 520
        },
        "error": ""
    },
    "execution_summary": "CodeAct execution succeeded with metrics: ..."
}
```

---

### Step 6：Summarizer 生成最终结果

`summarizer` 综合：

- 原始 query
- planner 的 plan
- analyst 的 analysis/evidence
- executor 的 execution_result/execution_summary

然后输出：

```python
{
    "summary": "最终总结...",
    "key_findings": [
        "发现 1",
        "发现 2",
        "发现 3"
    ],
    "recommendations": [
        "建议 1",
        "建议 2"
    ]
}
```

---

## 4. 一句话总结

```text
planner 负责想清楚怎么查，
researcher 负责生成和打包研究材料，
analyst 负责从材料中筛选可靠证据并形成分析，
executor 负责对分析结果做一个简单可执行 CodeAct 检查，
summarizer 负责把分析和执行产物整理成最终答案。
```
