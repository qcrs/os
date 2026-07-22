# Qdrant 记忆接入改动简述

临时说明文件，方便 review，后续可删除。

## 改动目标

把 `NS_ANALYSIS` 和 `NS_SUMMARIES` 这两类可复用长期记忆改为走当前项目下的
`memory_module` / Qdrant。

`NS_DOCS` 仍保留在 LangGraph `InMemoryStore`，用于当前任务的全文回查、
context packet 校验和 rehydrate。

## 当前分工

```text
InMemoryStore:
  NS_DOCS
  NS_PLANS
  NS_EXECUTIONS
  当前任务运行期 state / doc_key 回查

memory_module / Qdrant:
  memory_type="analysis"
  memory_type="summary"
```

## 主要改动

### `src/memory.py`

新增 Qdrant 适配函数：

```python
get_qdrant_memory()
qdrant_memory_available()
qdrant_search()
qdrant_add()
qdrant_add_from_payload()
```

这些函数负责初始化 `MemoryModule`，并把原项目的 analysis / summary payload
映射成 `memory_module.add()` 需要的结构。

### `src/config.py`

新增 Qdrant 长期记忆配置：

```python
LONG_TERM_MEMORY_ENABLED
LONG_TERM_MEMORY_QDRANT_PATH
LONG_TERM_MEMORY_COLLECTION
LONG_TERM_MEMORY_ADD_LOG_PATH
LONG_TERM_MEMORY_SEARCH_MODE
LONG_TERM_MEMORY_TOP_K
LONG_TERM_MEMORY_BM25_MODEL_PATH
```

### `src/agent/planner.py`

planner 查询历史 summary 从 `store_search(NS_SUMMARIES, ...)` 改为：

```python
qdrant_search(query, memory_type="summary", top_k=2)
```

### `src/agent/analyst.py`

analyst 查询历史 analysis 从 `store_search(NS_ANALYSIS, ...)` 改为：

```python
qdrant_search(query_text, memory_type="analysis", top_k=2)
```

analyst 写 analysis 从 `store_put(NS_ANALYSIS, ...)` 改为：

```python
qdrant_add_from_payload(..., memory_type="analysis")
```

### `src/agent/summarizer.py`

summarizer 写 summary 从 `store_put(NS_SUMMARIES, ...)` 改为：

```python
qdrant_add_from_payload(..., memory_type="summary")
```

### `src/agent/cache_agents.py`

cache/KV 实验路径里的 analysis 和 summary 写入也同步改为 Qdrant。

plan 和 execution 仍按原逻辑写 InMemoryStore。

### `memory_module/embedders/bm25.py`

把 BM25 本地模型路径检查提前到 `fastembed` import 之前。

这样在模型路径不存在时，会先报路径错误，测试和失败信息更明确。

## 没有改的点

- `NS_DOCS` 没有迁移到 Qdrant。
- `NS_PLANS` / `NS_EXECUTIONS` 仍按原逻辑写 InMemoryStore。
- `exp/` 下脚本没有改。
- 原有 JSONL 持久化逻辑仍保留；但当前主 agent 路径下 analysis / summary 不再写
  JSONL，而是写 Qdrant。

## 注意事项

`memory_module` 的 hybrid 检索分数是 RRF 融合分，不是 cosine 相似度。

不要用类似 `score > 0.8` 这种 cosine 阈值过滤 hybrid 结果。目前只用
`top_k` 和 `memory_type` filter。

## 验证

已执行：

```bash
python -m compileall src memory_module

PYTHONPATH=.:src pytest -q \
  memory_module/tests/test_module.py \
  memory_module/tests/test_bm25_encoder.py \
  memory_module/tests/test_add_logger.py \
  task/data_anas/test_protocol_validation.py
```

结果：

```text
11 passed
```
