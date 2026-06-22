# SynapseX 共享记忆与长期记忆机制实现说明

本文档根据当前 `/data/mingwei/SynapseX` 代码整理，说明系统如何保存统一记忆单元、如何检索历史记忆，以及进程退出后如何在下一次类似任务中复用旧记忆。

## 1. 总体结论

当前记忆机制由两层组成：

1. **运行期共享记忆**：使用 LangGraph 的 `InMemoryStore`，在一次任务或同一进程的多轮任务中提供 `put/get/search` 和语义检索能力。
2. **长期记忆持久化**：项目在 `src/memory.py` 中额外实现 JSONL 追加写入与启动加载逻辑，使 `InMemoryStore` 中的统一 `MemoryUnit` 可以保存到磁盘，并在下一次启动时重新加载和重建语义索引。

因此，目前不是只依赖 LangGraph 原生内存态 Store；长期记忆能力由本项目在 LangGraph `InMemoryStore` 之上实现。

## 2. 关键代码位置

| 模块 | 代码位置 | 作用 |
|---|---:|---|
| 长期记忆配置 | `src/config.py:44` | 配置是否启用长期记忆和 JSONL 文件路径。 |
| Store 创建 | `src/memory.py:141` | 创建带语义索引的 `InMemoryStore`，并加载历史记忆。 |
| 统一记忆单元 | `src/memory.py:262` | `make_memory_unit()` 将不同 Agent 的输出统一封装为 `MemoryUnit`。 |
| 持久化写入 | `src/memory.py:345` | `_persist_memory_unit()` 将记忆追加写入 JSONL。 |
| 启动加载 | `src/memory.py:362` | `load_persisted_memories()` 从 JSONL 读取历史记忆。 |
| 统一写入口 | `src/memory.py:424` | `store_put()` 先构造统一记忆单元，再写 Store 和 JSONL。 |
| 语义检索 | `src/memory.py:467` | `store_search()` 调用 Store 语义搜索。 |
| 关键词检索 | `src/memory.py:484` | `store_search_by_keywords()` 基于文本字段过滤。 |
| 标签检索 | `src/memory.py:508` | `store_search_by_tags()` 基于 `tags` 过滤。 |
| 混合检索 | `src/memory.py:532` | `store_search_memories()` 支持语义 + 关键词 + 标签组合检索。 |

## 3. 配置方式

长期记忆默认启用，配置定义在 `src/config.py:44`：

```python
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSISTENT_MEMORY_ENABLED = os.getenv("PERSISTENT_MEMORY_ENABLED", "1").lower() in {
    "1", "true", "yes", "on"
}
PERSISTENT_MEMORY_PATH = os.getenv(
    "PERSISTENT_MEMORY_PATH",
    os.path.join(PROJECT_ROOT, ".memory", "shared_memory.jsonl"),
)
```

默认行为：

- `PERSISTENT_MEMORY_ENABLED=1`：启用长期记忆。
- `PERSISTENT_MEMORY_PATH=/data/mingwei/SynapseX/.memory/shared_memory.jsonl`：默认长期记忆文件。
- `.memory/` 已加入 `.gitignore`，本地记忆不会被提交到 Git。

如果要做干净实验，可以临时关闭或更换路径：

```bash
export PERSISTENT_MEMORY_ENABLED=0
# 或
export PERSISTENT_MEMORY_PATH=/tmp/synapsex_memory_test.jsonl
```

## 4. Store 创建与加载流程

`create_store()` 负责创建运行期共享记忆 Store，代码位于 `src/memory.py:141`：

```python
def create_store() -> InMemoryStore:
    embeddings = get_embeddings(dims=EMBEDDING_DIMS)
    store = InMemoryStore(
        index={
            "dims": EMBEDDING_DIMS,
            "embed": embeddings,
            "fields": ["text"],
        }
    )
    loaded_count = load_persisted_memories(store)
    if loaded_count:
        metrics.increment("persistent_memory_loaded", loaded_count)
    return store
```

实现要点：

- `InMemoryStore(index=...)` 是运行期记忆容器。
- `fields=["text"]` 表示语义索引主要索引 MemoryUnit 顶层的 `text` 字段。
- `get_embeddings()` 会优先使用 DashScope `text-embedding-v4`；未配置 `DASHSCOPE_API_KEY` 时使用 `LocalHashEmbeddings` 本地 fallback。
- `load_persisted_memories(store)` 在 Store 创建后立即执行，把历史 JSONL 记忆重新写入新的 `InMemoryStore`，从而恢复检索能力。

## 5. 统一 MemoryUnit Schema

所有 Agent 原始输出不会直接写入 Store，而是先通过 `make_memory_unit()` 包装成统一格式。核心字段定义在 `src/memory.py:305`：

```python
memory_unit = {
    "memory_schema_version": MEMORY_SCHEMA_VERSION,
    "memory_id": key,
    "memory_type": str(resolved_memory_type),
    "source_agent": str(resolved_source_agent),
    "created_at": created_at,
    "created_at_iso": datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat(),
    "task_group": str(resolved_task_group),
    "task_topic": resolved_task_topic,
    "summary": resolved_summary,
    "summary_description": resolved_summary,
    "text": resolved_text,
    "tags": resolved_tags,
    "evidence_refs": resolved_evidence_refs,
    "payload": payload,
}
```

字段含义如下：

| 字段 | 含义 | 来源 |
|---|---|---|
| `memory_schema_version` | 记忆结构版本 | 代码常量。 |
| `memory_id` | 记忆 ID | `store_put()` 传入的 Store key。 |
| `memory_type` | 记忆类型，如 `plan/document/analysis/summary` | Agent 显式传入；未传时按 namespace 推断。 |
| `source_agent` | 来源 Agent | Agent 显式传入；未传时按 namespace 推断。 |
| `created_at` | 创建时间戳 | `time.time()` 自动生成。 |
| `created_at_iso` | UTC ISO 时间 | 由 `created_at` 自动转换。 |
| `task_group` | 任务组 | Agent 显式传入，或从 key/payload 推断。 |
| `task_topic` | 任务主题 | Agent 显式传入，或从 `query/sub_query/topic/plan` 推断。 |
| `summary` | 摘要 | Agent 显式传入，或从 `summary/digest/text/plan` 推断。 |
| `summary_description` | 摘要描述 | 当前等同于 `summary`。 |
| `text` | 语义检索正文 | payload 的 `text`，或摘要/主题兜底。 |
| `tags` | 标签 | Agent 显式 tags + payload tags + 自动派生 tags。 |
| `evidence_refs` | 证据引用 | Agent 显式传入，或从 `evidence/selected_doc_keys` 提取。 |
| `payload` | 原始 Agent 输出 | 完整保留原始 value。 |

同时，`make_memory_unit()` 会执行：

```python
for field_name, field_value in payload.items():
    memory_unit.setdefault(field_name, field_value)
```

这表示原始 payload 字段也会保留在顶层，兼容旧代码中 `r.value.get("text")`、`r.value.get("digest")` 等读取方式。

## 6. 写入流程

统一写入口是 `store_put()`，代码位于 `src/memory.py:424`：

```python
memory_value = make_memory_unit(...)
store.put(namespace, key, memory_value)
metrics.record_store_op("put", namespace, key, duration)
_persist_memory_unit(namespace, key, memory_value)
```

完整写入链路：

```text
Agent 原始输出 value
        │
        ▼
store_put(namespace, key, value, metadata...)
        │
        ▼
make_memory_unit() 补齐统一元数据
        │
        ├── store.put(namespace, key, memory_value)      # 写入 LangGraph InMemoryStore
        │
        └── _persist_memory_unit(namespace, key, value)  # 追加写入 JSONL 长期记忆
```

长期记忆 JSONL 单条记录格式由 `_persist_memory_unit()` 写入：

```json
{
  "file_schema_version": 1,
  "namespace": ["summaries"],
  "key": "summary_xxx",
  "value": {
    "memory_schema_version": 1,
    "memory_id": "summary_xxx",
    "source_agent": "summarizer",
    "task_topic": "...",
    "summary": "...",
    "text": "...",
    "payload": {}
  }
}
```

## 7. 启动后的历史记忆恢复

`load_persisted_memories()` 位于 `src/memory.py:362`，负责在新进程启动时恢复历史记忆：

1. 读取 `PERSISTENT_MEMORY_PATH` 指向的 JSONL 文件。
2. 逐行解析 JSON 记录。
3. 按 `(namespace, key)` 保存最新一条记录，处理重复写入场景。
4. 如果历史记录不是统一 `MemoryUnit`，则重新调用 `make_memory_unit()` 包装。
5. 调用 `store.put(namespace, key, value)` 写回新的 `InMemoryStore`。
6. 因为 Store 配置了 `fields=["text"]`，重新写入时会重建语义索引。

跨进程复用链路：

```text
第一次执行任务
  Agent 写入 store_put()
  ├─ 当前进程可立即搜索 InMemoryStore
  └─ 同步追加到 .memory/shared_memory.jsonl

进程退出
  InMemoryStore 消失
  JSONL 文件仍保留

下一次执行类似任务
  create_store()
  └─ load_persisted_memories()
     └─ 历史 MemoryUnit 重新进入 InMemoryStore 并可被 search/get 复用
```

## 8. 检索能力

当前支持四类检索入口。

### 8.1 按 key 读取

`store_get(store, namespace, key)` 调用 `store.get()`，用于已知 memory ID 的精确读取。

### 8.2 语义相似度检索

`store_search()` 位于 `src/memory.py:467`：

```python
results = store.search(namespace, query=query, limit=limit)
```

该方法使用 `InMemoryStore` 的向量索引，对 MemoryUnit 的 `text` 字段做语义召回。

### 8.3 关键词检索

`store_search_by_keywords()` 位于 `src/memory.py:484`，先取候选记忆，再用 `_contains_keywords()` 过滤。过滤字段包括：

- `text`
- `summary`
- `task_topic`
- `tags`

`match_all=True` 时要求全部关键词命中；默认 `False` 表示任一关键词命中即可。

### 8.4 标签检索

`store_search_by_tags()` 位于 `src/memory.py:508`，基于 MemoryUnit 的 `tags` 过滤。标签在 `_normalize_tags()` 中会统一小写、去空、去重。

### 8.5 混合检索

`store_search_memories()` 位于 `src/memory.py:532`，推荐作为跨任务复用入口：

```python
store_search_memories(
    store,
    namespace,
    query="语义查询文本",
    keywords=["关键词"],
    tags=["summary", "task_group"],
    limit=5,
)
```

执行顺序：

1. 如果传入 `query`，先做语义召回；否则取 namespace 下候选项。
2. 再按关键词过滤。
3. 再按标签过滤。
4. 返回满足条件的前 `limit` 条记忆。

## 9. 各 Agent 如何写入和复用记忆

Store namespace 在 `src/config.py:54` 定义：

```python
NS_PLANS = ("plans",)
NS_DOCS = ("docs",)
NS_ANALYSIS = ("analysis",)
NS_SUMMARIES = ("summaries",)
```

### 9.1 Planner

Planner 在执行前会从历史 summary 中检索相关先验知识，代码位于 `src/agents.py:196`：

```python
prior_results = store_search(store, NS_SUMMARIES, query, limit=2)
```

如果命中，会把历史摘要拼入 prompt，并增加 `memory_reuse_hits` 指标。

Planner 生成计划后写入 `NS_PLANS`，代码位于 `src/agents.py:253`：

```python
store_put(
    store,
    NS_PLANS,
    plan_memory_id,
    {"text": plan, "sub_queries": sub_queries, "query": query, ...},
    memory_type="plan",
    source_agent="planner",
    task_group=task_group,
    task_topic=query,
    summary=plan,
    tags=["plan", "planner", task_group],
)
```

### 9.2 Retriever

Retriever 为每个子查询生成文档后写入 `NS_DOCS`，代码位于 `src/agents.py:357`：

```python
store_put(
    store,
    NS_DOCS,
    doc_key,
    {"text": doc_text, "sub_query": sub_query, "task_group": task_group},
    memory_type="document",
    source_agent="retriever",
    task_group=task_group,
    task_topic=sub_query,
    summary=summarize_text(doc_text, 240),
    tags=["document", "retriever", task_group, *sub_query.split()[:6]],
)
```

Retriever 随后还会搜索相关文档，用于结构化上下文组织，代码位于 `src/agents.py:393`。

### 9.3 Executor

Executor 执行前会检索历史分析结果，代码位于 `src/agents.py:519`：

```python
prior_analyses = store_search(store, NS_ANALYSIS, plan, limit=2)
```

如果命中，会把历史分析摘要加入 prompt，并记录 `memory_reuse_hits`。

Executor 生成分析后写入 `NS_ANALYSIS`，代码位于 `src/agents.py:689`：

```python
store_put(
    store,
    NS_ANALYSIS,
    analysis_memory_id,
    {
        "text": analysis,
        "digest": analysis_digest,
        "evidence": evidence,
        "plan": plan,
        "selected_doc_keys": selected_doc_keys,
        "context_verification": verification_summary,
        "hidden_guidance": hidden_guidance,
    },
    memory_type="analysis",
    source_agent="executor",
    task_group=task_group,
    task_topic=query,
    summary=analysis_digest,
    tags=["analysis", "executor", task_group],
)
```

其中 `evidence` 和 `selected_doc_keys` 会被 `make_memory_unit()` 提取为 `evidence_refs`，形成证据链。

### 9.4 Summarizer

Summarizer 生成最终摘要后写入 `NS_SUMMARIES`，代码位于 `src/agents.py:911`：

```python
store_put(
    store,
    NS_SUMMARIES,
    summary_memory_id,
    {
        "text": summary,
        "key_findings": key_findings,
        "recommendations": recommendations,
        "query": query,
        "hidden_guidance": hidden_guidance,
    },
    memory_type="summary",
    source_agent="summarizer",
    task_group=task_group,
    task_topic=query,
    summary=summary,
    tags=["summary", "summarizer", task_group],
)
```

这些 summary 会被后续 Planner 优先检索，从而形成跨任务复用闭环。

## 10. Demo 中的复用展示

`run_demo.py:93` 提供了 `demonstrate_memory_reuse()`：

```python
results = store_search(store, NS_SUMMARIES, query, limit=3)
```

它会搜索 summary namespace，并列出 `summaries/plans/docs/analysis` 四类 namespace 中已有的记忆数量，用于展示 Store 中已经存在可复用记忆。

## 11. 技术要点

1. **统一 schema**：不同 Agent 写入的异构内容都被包装为统一 `MemoryUnit`，便于跨 Agent 读取。
2. **兼容旧逻辑**：原始 payload 保存在 `payload`，同时旧字段继续保留在顶层，避免破坏原有 `r.value.get("text")` 代码。
3. **运行期高效检索**：仍使用 LangGraph `InMemoryStore` 的内存检索和向量索引。
4. **长期记忆可恢复**：JSONL 文件保存完整 MemoryUnit，新进程启动时重新加载到 Store。
5. **多检索方式**：支持 key 精确读取、语义检索、关键词过滤、标签过滤和混合检索。
6. **证据链保留**：Executor 的 `evidence`、`selected_doc_keys` 会被整理成 `evidence_refs`，用于追踪结论来源。
7. **离线可运行**：无 DashScope key 时使用 `LocalHashEmbeddings`，保证基础检索流程可用。

## 12. 当前边界与注意事项

| 项目 | 当前状态 | 说明 |
|---|---|---|
| 持久化介质 | JSONL 文件 | 简单可靠，便于调试；不是数据库。 |
| 写入模式 | append-only | 同一 `(namespace, key)` 多次写入时，加载阶段使用最新一条。 |
| 删除/压缩 | 暂未实现 | 长期运行后可增加 compaction 或迁移到 SQLite/向量库。 |
| 并发写入锁 | 暂未实现 | 当前适合单进程或低并发 demo；高并发建议加文件锁或数据库。 |
| 语义质量 | 依赖 embedding | DashScope 效果更好；LocalHashEmbeddings 是离线 fallback。 |
| Store 本体 | 仍是 InMemoryStore | 进程内 Store 退出会消失，但 JSONL 长期记忆会在下次启动恢复。 |

## 13. 结论

当前 SynapseX 已经实现长期共享记忆：

- Agent 写入时统一封装为 `MemoryUnit`。
- 运行期写入 LangGraph `InMemoryStore`，支持语义检索。
- 同步追加保存到 `.memory/shared_memory.jsonl`。
- 新进程启动时自动加载历史 MemoryUnit 并重建索引。
- 后续类似任务可通过 Planner、Executor 或通用检索函数复用历史摘要、计划、文档、分析和证据链。
