# Agent 工作流说明

当前主线系统包含 5 个真实业务 Agent：

```text
planner → researcher(s) → analyst → executor → summarizer
```

`researcher` 会根据 planner 拆出的多个 `sub_queries` 并行运行，之后通过 LangGraph reducer 汇总到同一个 `analyst`。主线支持 `text` 和 `structured` 两种通信模式；trueKV/cache 实验走 `cache_agents.py` 旁路线。

---

## 1. Analyst 是什么

`analyst` 是“研究分析员/证据分析员”，位于：

```text
researcher(s) → analyst → executor
```

它负责从 researcher 的材料中筛选可靠上下文、校验证据、必要时从 Store 回补原文，并让 LLM 生成结构化分析。

### Analyst 输入

| 字段 | 来源 | 含义 |
|---|---|---|
| `query` | 用户输入 | 原始问题 |
| `plan` | planner | 研究计划 |
| `documents` | researcher | text 模式下的完整研究材料 |
| `document_payloads` | researcher | structured 模式下的文档元数据 |
| `context_packets` | researcher | 压缩后的上下文包 |
| `embedding_payloads` | researcher | 文档向量，用于排序 |

### Analyst 处理流程

1. **选择上下文**：structured 模式优先使用 compact context packets，并结合词面相关性和 embedding 相似度排序。
2. **校验证据**：通过 `doc_key` 回到 Store 的 `NS_DOCS`，检查 evidence span 的 hash、offset 和文本一致性。
3. **必要时 rehydrate**：如果 compact packet 不可靠，从 Store 截取一小段原文作为 fallback evidence。
4. **生成结构化分析**：基于可靠或 rehydrated evidence 输出 `analysis`、`candidate_answers` 和 `evidence`。

### Analyst 输出

| 字段 | 含义 |
|---|---|
| `analysis` | 结构化分析正文 |
| `analysis_digest` | 压缩后的分析摘要，给 summarizer 降低 prompt 成本 |
| `candidate_answers` | 面向机器评测的候选字段答案 |
| `evidence` | claim/support/doc_key/span_id 形式的证据列表 |
| `selected_context_packets` | 被选中并校验后的上下文包 |
| `context_verification` | 校验统计，例如 reliable、rehydrated、failed 数量 |

---

## 2. 五个 Agent 分工

### 2.1 Planner

`planner` 把用户原始 `query` 拆成研究计划和 3 个互补子查询。

输入：

```text
query
```

输出：

```text
plan
sub_queries
```

写入记忆：

```text
NS_PLANS = ("plans",)
```

典型职责：

- 理解用户问题。
- 规划研究路径。
- 拆出 3 个互补 sub-query。
- structured 模式下发送结构化 `AgentMessage`。

### 2.2 Researcher

`researcher` 针对每个 `sub_query` 并行生成研究材料，并将完整材料写入 Store。

输入：

```text
sub_query
```

输出：

```text
documents
context_packets
document_payloads
embedding_payloads
```

写入记忆：

```text
NS_DOCS = ("docs",)
```

典型职责：

- 根据 sub-query 生成研究材料。
- 把完整材料写入 Store。
- 构造 compact context packet。
- 在 structured 模式下生成 embedding payload 供后续排序。

### 2.3 Analyst

`analyst` 选择上下文、校验证据、必要时 rehydrate，并生成结构化分析。

输入：

```text
query
plan
documents / context_packets
embedding_payloads
```

输出：

```text
analysis
analysis_digest
candidate_answers
evidence
selected_context_packets
context_verification
```

写入记忆：

```text
NS_ANALYSIS = ("analysis",)
```

### 2.4 Executor

`executor` 执行一个受限 CodeAct 步骤，对 analyst 的分析和证据做确定性统计检查。

输入：

```text
analysis
analysis_digest
candidate_answers
evidence
selected_context_packets
```

输出：

```text
execution_code
execution_result
execution_summary
final_answer
extracted_answers
```

写入记忆：

```text
NS_EXECUTIONS = ("executions",)
```

### 2.5 Summarizer

`summarizer` 综合 plan、analysis、evidence 和 execution artifact，输出最终总结。

输入：

```text
query
plan
analysis / analysis_digest
evidence
execution_result
execution_summary
final_answer
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

---

## 3. Text 与 Structured 模式

| 模式 | Agent 数量 | 状态传递方式 | 主要目的 |
|---|---:|---|---|
| `text` | 5 个业务 Agent | 直接传递较完整文本材料 | 基线模式，便于对比 |
| `structured` | 5 个业务 Agent | `AgentMessage`、`context_packets`、`embedding_payloads`、Store 引用 | 降低自然语言通信开销，提高可校验性 |

Structured 模式只在 Python 协议层使用 context packet、embedding 和共享 Store 完成压缩、排序、校验和回补。

---

## 4. trueKV/cache 旁路线

当前仓库里需要区分两条五 Agent 链路：

| 链路 | 实现文件 | Agent 职责 | 主要用途 |
|---|---|---|---|
| 主线五 Agent | `planner.py`、`researcher.py`、`analyst.py`、`executor.py`、`summarizer.py` | 真实业务 Agent | `text` / `structured` 常规多 Agent 工作流 |
| trueKV/cache 实验旁路线 | `cache_agents.py` | 同样的五个业务职责，但函数名带 `_cache` | 长上下文连续任务里的 KV/cache 状态传递实验 |

trueKV/cache 实验时，业务角色仍然是五个：

```text
planner_cache → researcher_cache → analyst_cache → executor_cache → summarizer_cache
```

它前面额外有一个非业务 producer 节点：

```text
context_prefill → planner_cache → researcher_cache → analyst_cache → executor_cache → summarizer_cache
```

`context_prefill` 不替代任何业务 Agent。它只负责把长规则文档、长日志或代码库说明预先送进 vLLM，生成可复用的 cache/KV 状态句柄，然后把句柄放进 LangGraph state。

### 4.1 为什么没有侵入式修改五个主线文件

这是有意的隔离设计：

- 主线 `planner.py` / `researcher.py` / `analyst.py` / `executor.py` / `summarizer.py` 保持 text/structured 行为，避免破坏已有实验。
- trueKV/cache 实验逻辑集中在 `cache_agents.py`，便于单独对比、回滚和调参。
- `graph.py` 通过 `build_cache_graph()` 构造 cache 图；普通 `build_graph()` 仍构造主线五 Agent 图。

### 4.2 trueKV/cache 状态如何传递

旁路线核心字段：

```python
{
    "active_cache": cache_handle,
    "source_cache": cache_handle,
    "planner_cache": cache_handle,
    "researcher_cache": cache_handle,
    "analyst_cache": cache_handle,
    "executor_cache": cache_handle,
    "summary_cache": cache_handle,
    "cache_trace": [...]
}
```

每个 `_cache` Agent 读取上一个节点传来的 `active_cache`，调用 vLLM runtime 继续生成，然后把新的 `cache_handle` 作为 `active_cache` 传给下一个 Agent。

---

## 5. 主线示例流程

### Step 1：输入问题

```python
{
    "query": "分析 LangGraph 多智能体通信机制",
    "task_group": "default",
    "mode": "structured",
}
```

### Step 2：Planner 规划任务

```python
{
    "plan": "研究 LangGraph 的图结构、状态传递和多 agent 协作机制",
    "sub_queries": [
        "LangGraph 的 StateGraph 和节点调度机制",
        "LangGraph 的 Send fan-out 和 reducer fan-in 机制",
        "LangGraph 的 Store 和跨任务记忆机制",
    ],
}
```

### Step 3：Researcher 并行生成材料

```python
{
    "documents": [...],
    "context_packets": [...],
    "embedding_payloads": [...],
}
```

### Step 4：Analyst 筛选和分析证据

```python
{
    "analysis": "LangGraph 的多智能体通信依赖 StateGraph、Send fan-out、reducer fan-in 和 Store...",
    "analysis_digest": "LangGraph 通过图结构和状态 channel 支持多 agent 协作...",
    "candidate_answers": {...},
    "evidence": [...],
    "selected_context_packets": [...],
    "context_verification": {...},
}
```

### Step 5：Executor 执行 CodeAct

```python
{
    "execution_code": "...",
    "execution_result": {"ok": True, "metrics": {...}},
    "execution_summary": "Execution ok=True...",
    "final_answer": "...",
}
```

### Step 6：Summarizer 输出总结

```python
{
    "summary": "...",
    "key_findings": [...],
    "recommendations": [...],
}
```
