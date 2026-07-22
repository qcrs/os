# 记忆模块功能说明

## 1. 模块定位

本项目中的记忆模块用于为多智能体系统提供长期共享记忆能力。它不是某一个 agent 的内部缓存，而是独立于 Agent/Swarm 的长期记忆组件，可以在多个任务、多个 agent 之间复用历史经验。

在当前系统中，记忆模块主要服务于以下目标：

- 保存历史任务中产生的 summary 和 analysis。
- 支持后续任务根据当前问题检索相关历史记忆。
- 由 planner 判断检索到的记忆是否真正可复用。
- 将通过校验的记忆传递给后续 analyst，辅助分析但不替代当前证据。
- 在记忆可复用时减少 researcher 调用次数，从而降低 LLM 调用和 token 消耗。

## 2. 核心功能

### 2.1 长期记忆写入

记忆模块支持将任务中产生的稳定信息写入长期存储。当前主要写入两类长期记忆：

- `summary`：由 summarizer 写入，保存任务最终总结、关键结论和最终答案。
- `analysis`：由 analyst 写入，保存分析过程、候选答案、证据摘要和可复用推理方式。

executor 当前不写入 Qdrant 长期记忆。它只会将执行结果写入 Runtime Store 的 `NS_EXECUTIONS`，用于当前运行记录和调试。

### 2.2 统一记忆数据结构

每条长期记忆包含：

- `id`：记忆唯一标识。
- `vector`：向量索引信息，包括 dense 向量和 BM25 稀疏表示。
- `payload`：记忆元数据和正文内容。

payload 主要字段包括：

- `content`：用于检索和复用的核心内容。
- `keywords`：关键词提示。
- `memory_type`：记忆类型，例如 `summary`、`analysis`。
- `source_agent`：写入该记忆的 agent。
- `source_task_id`：来源任务 id。
- `task_topic`：任务主题。
- `content_hash`：内容哈希，用于去重和追踪。
- `created_at`：创建时间。

### 2.3 多模式检索

记忆模块支持三种检索方式：

- `dense`：基于 embedding 的语义检索，适合查找语义相近的历史任务。
- `bm25`：基于关键词的稀疏检索，适合查找实体名、字段名、任务关键词。
- `hybrid`：结合 dense 和 BM25，用 RRF 融合排序。

需要注意的是，`hybrid` 模式下的 score 是 RRF 融合分，不是 cosine 相似度，因此不能直接用 `0.8` 这类 cosine 阈值过滤 hybrid score。

### 2.4 按类型过滤

检索时可以根据 `memory_type` 过滤记忆。例如当前 planner 会分别检索：

- `memory_type="summary"`
- `memory_type="analysis"`

这样可以避免所有历史内容混在一起，提高检索结果的可解释性和可控性。

### 2.5 与原 Store 机制兼容

项目原本使用 LangGraph `InMemoryStore` 和 JSONL 持久化机制。新记忆模块接入后，系统仍然可以通过配置保留原 Store 能力：

- `PERSISTENT_MEMORY_ENABLED=1`：启用原 JSONL + Store 持久化记忆。
- `LONG_TERM_MEMORY_ENABLED=1`：启用 Qdrant 长期记忆模块。

当前长期复用主要依赖 Qdrant 记忆模块，原 Store 更多用于运行时状态、docs 缓存和兼容旧实验。

## 3. 多智能体中的使用方式

### 3.1 Planner 统一检索记忆

planner 是当前系统中唯一主动检索长期记忆的 agent。它会根据当前任务问题生成较短的 memory query，然后检索 summary 和 analysis 记忆。

这样做的好处是：

- 避免多个 agent 各自检索记忆造成上下文混乱。
- 将“是否复用记忆”的决策集中到 planner。
- 让后续 agent 只消费经过筛选的记忆。

### 3.2 Planner 校验记忆是否可复用

系统不会把“检索到记忆”直接视为“记忆命中”。planner 会对候选记忆进行校验，并输出结构化结果：

```json
{
  "usable": true,
  "confidence": 0.85,
  "reason": "该记忆与当前任务属于同一类计算任务，包含可复用的分析方法。",
  "reused_memory_ids": ["memory_xxx"]
}
```

本地代码还会进行强校验：

- id 必须来自候选记忆。
- `usable` 必须为 true。
- `confidence` 必须达到阈值。
- 通过校验后才进入 `validated_memories`。

因此系统区分：

- `reused_memories`：检索得到的候选记忆。
- `validated_memories`：planner 判断后确认可复用的记忆。

### 3.3 Analyst 受控复用记忆

analyst 当前不再主动检索历史 analysis。它只读取 planner 传递下来的 `validated_memories`。

这些记忆在 analyst prompt 中被标记为 reusable hints，作用是：

- 提示历史分析思路。
- 提示可复用的计算方法。
- 提示类似任务中的答案组织方式。
- 辅助减少重复推理。

同时系统明确限制：

- 记忆不能替代当前任务证据。
- 当前 documents 或 context packets 中的信息优先。
- evidence 仍然应来自当前任务上下文。

### 3.4 记忆命中后减少 Researcher 调用

当 planner 判断存在可复用记忆，并且 `REDUCE_RESEARCH_ON_MEMORY_HIT=1` 时，系统会减少 researcher fan-out。

原始模式下 planner 通常生成 3 个 sub-query：

```text
sub_queries = 3
```

命中可复用记忆后，系统将 sub-query 缩减为 1 个 verification query：

```text
sub_queries = 1
```

这样可以减少 researcher 调用次数，并降低 LLM 调用和 token 消耗。

## 4. 主要配置项

| 配置项 | 功能 |
| --- | --- |
| `LONG_TERM_MEMORY_ENABLED` | 是否启用 Qdrant 长期记忆 |
| `LONG_TERM_MEMORY_QDRANT_PATH` | Qdrant 本地数据路径 |
| `LONG_TERM_MEMORY_COLLECTION` | Qdrant collection 名称 |
| `LONG_TERM_MEMORY_SEARCH_MODE` | 检索模式，支持 `dense`、`bm25`、`hybrid` |
| `LONG_TERM_MEMORY_TOP_K` | 长期记忆检索 top-k |
| `LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD` | dense 检索阈值 |
| `LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE` | hybrid 模式下是否额外用 dense score 过滤 |
| `PLANNER_MEMORY_CONFIDENCE_THRESHOLD` | planner 判定可复用的 confidence 阈值 |
| `REDUCE_RESEARCH_ON_MEMORY_HIT` | 记忆命中后是否减少 researcher 调用 |
| `PERSISTENT_MEMORY_ENABLED` | 是否启用原 JSONL + Store 持久化 |

## 5. 可统计指标

为评估记忆模块效果，当前系统可以统计：

- `candidate_rate`：检索到候选记忆的比例。
- `validated_hit_rate`：planner 判定可复用的比例。
- `candidate_to_validated_rate`：候选记忆转化为可复用记忆的比例。
- `reduction_rate`：实际减少 researcher 调用的比例。
- `research_subqueries_saved`：节省的 researcher 子任务数量。
- `llm_calls`：LLM 总调用次数。
- `total_tokens`：总 token 使用量。
- `elapsed_s`：任务执行时间。
- `accuracy`：任务答案正确率。

这些指标可以用于比较：

- 无记忆与有记忆的差异。
- text 模式与 structured 模式的差异。
- 记忆检索命中与实际复用之间的差异。
- 记忆机制对 tokens、执行时间和正确率的影响。

## 6. 功能总结

该记忆模块的核心功能可以概括为：

```text
长期写入 -> 多模式检索 -> planner 校验 -> state 传递 -> analyst 受控复用 -> 减少 researcher 调用
```

它的价值不只是保存历史文本，而是为多智能体系统提供一种可控的经验复用机制。通过 planner 校验和 state 显式传递，系统可以避免盲目使用历史记忆，同时在记忆可靠时减少重复检索和重复推理。
