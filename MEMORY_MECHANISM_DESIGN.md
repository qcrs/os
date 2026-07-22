# 面向多智能体协作的长期共享记忆机制设计

## 1. 背景与目标

本项目是一个多智能体协作系统，核心执行链路为：

```text
planner -> researcher -> analyst -> executor -> summarizer
```

原系统已经包含 LangGraph `InMemoryStore` 和 JSONL 持久化能力，可以将部分中间结果写入 Store，并在后续任务中通过 embedding 检索复用。但原机制存在几个问题：

- 记忆读取逻辑分散在多个 agent 中，不容易控制记忆如何影响整体流程。
- 检索到的记忆不一定真的可复用，直接放入 prompt 可能污染上下文。
- 记忆命中和记忆复用没有区分，容易把“搜到候选”误认为“有效复用”。
- 对比实验中，需要清楚统计记忆是否减少了 LLM 调用、token 和执行时间。

因此，我们在项目中接入了一个独立的长期共享记忆模块，并围绕 planner 增加了“候选检索 -> 可复用校验 -> 下游传递”的机制。

## 2. 原有记忆机制

原项目主要依赖 LangGraph 的 Runtime Store。Store 支持：

- `put(namespace, key, value)`
- `get(namespace, key)`
- `search(namespace, query)`

写入 Store 时，系统会对 `value["text"]` 建立 embedding 索引，因此后续 `store_search()` 本质上是基于 `text` 字段做语义检索。

原系统中主要存在以下几类命名空间：

| 命名空间 | 主要写入者 | 主要用途 |
| --- | --- | --- |
| `NS_DOCS` | researcher | 保存当前任务检索或构造出的文档内容 |
| `NS_SUMMARIES` | summarizer | 保存任务总结，供后续任务复用 |
| `NS_ANALYSIS` | analyst | 保存分析过程、候选答案和证据摘要 |
| `NS_PLANS` | planner | 保存计划记录 |
| `NS_EXECUTIONS` | executor | 保存当前运行中的执行记录；目前不作为长期复用记忆检索 |

其中真正用于历史复用的主要是 `NS_SUMMARIES` 和 `NS_ANALYSIS`。`NS_DOCS` 更偏向当前运行过程中的文档缓存和上下文组织。`NS_EXECUTIONS` 当前只是 executor 写入 Runtime Store 的执行记录，不会写入 Qdrant 长期记忆，也不是 planner 当前检索的主要对象。

## 3. 新长期记忆模块

新加入的 `memory_module` 是独立的长期共享记忆模块，不直接依赖 Agent 或 Swarm。它提供统一接口：

```text
add(content, keywords, memory_type, source_agent, source_task_id, task_topic)
search(query, mode="dense|bm25|hybrid", top_k=5)
list(filters)
get(memory_id)
delete(memory_id)
```

每条记忆由以下结构组成：

```text
id + vector{dense,bm25} + payload
```

payload 包含：

- `content`
- `keywords`
- `memory_type`
- `source_agent`
- `source_task_id`
- `task_topic`
- `content_hash`
- `created_at`

检索模式包括：

- `dense`：embedding 语义检索。
- `bm25`：关键词稀疏检索。
- `hybrid`：dense + bm25，用 RRF 融合排序。

需要注意：`hybrid` 模式下的 score 是 RRF 融合分，不是 cosine 相似度，因此不能直接用 `0.8` 这类 cosine 阈值过滤 hybrid score。

## 4. 接入后的整体设计

接入后，系统将“长期记忆写入”和“记忆读取”分开：

- analyst / summarizer 负责写入 Qdrant 长期记忆。
- planner 负责统一检索长期记忆。
- planner 负责判断记忆是否可复用。
- analyst 不再自己主动检索历史 analysis，而是只消费 planner 传递下来的已验证记忆。

executor 当前不写入 Qdrant 长期记忆。它会写 `NS_EXECUTIONS` 到 Runtime Store，主要用于当前运行记录和调试，不参与当前长期记忆复用链路。

当前关键配置包括：

| 环境变量 | 作用 |
| --- | --- |
| `LONG_TERM_MEMORY_ENABLED` | 是否启用 Qdrant 长期记忆 |
| `LONG_TERM_MEMORY_QDRANT_PATH` | Qdrant 本地数据路径 |
| `LONG_TERM_MEMORY_COLLECTION` | Qdrant collection 名称 |
| `LONG_TERM_MEMORY_SEARCH_MODE` | 检索模式，支持 `dense`、`bm25`、`hybrid` |
| `LONG_TERM_MEMORY_TOP_K` | 长期记忆检索 top-k |
| `PERSISTENT_MEMORY_ENABLED` | 是否启用原项目 JSONL + Store 持久化记忆 |
| `PLANNER_MEMORY_CONFIDENCE_THRESHOLD` | planner 判定记忆可复用的 confidence 阈值 |
| `REDUCE_RESEARCH_ON_MEMORY_HIT` | 记忆命中后是否减少 researcher fan-out |

## 5. Planner 统一检索记忆

当前设计中，planner 是记忆复用的唯一入口。planner 会根据当前任务 query 提取一个较短的 memory query，避免把长上下文、样例数据和 answer format 一起用于 BM25 检索。

planner 当前会检索两类长期记忆：

- `memory_type="summary"`
- `memory_type="analysis"`

如果 `PERSISTENT_MEMORY_ENABLED=1`，planner 也会读取原 Store 中的：

- `NS_SUMMARIES`
- `NS_ANALYSIS`

这样做的目的不是让所有 agent 各自查询记忆，而是将记忆选择权集中到 planner。planner 先得到候选记忆，再统一判断哪些记忆可以影响当前任务。

## 6. Planner 记忆校验机制

本机制的核心是区分“候选记忆”和“有效复用记忆”。

第一阶段：检索候选记忆。

```text
query -> qdrant_search(summary) + qdrant_search(analysis) -> reused_memories
```

这里得到的 `reused_memories` 只是候选，不代表已经命中。

第二阶段：planner 判断可复用性。

planner 需要输出结构化判断：

```json
{
  "memory_validation": {
    "usable": true,
    "confidence": 0.85,
    "reason": "该记忆与当前任务属于同一公司财报计算任务，并包含可复用的计算模式。",
    "reused_memory_ids": ["memory_xxx"]
  }
}
```

本地代码随后进行强校验：

- `reused_memory_ids` 必须来自候选记忆。
- `usable` 必须为 true。
- `confidence` 必须大于等于 `PLANNER_MEMORY_CONFIDENCE_THRESHOLD`。
- 只有通过校验的记忆才会进入 `validated_memories`。

因此当前系统中的几个字段含义不同：

| 字段 | 含义 |
| --- | --- |
| `reused_memories` | 检索得到的候选记忆 |
| `reused_memory_ids` | 候选记忆 id |
| `memory_validation` | planner 对候选记忆的可复用判断 |
| `validated_memories` | 通过 planner 校验的记忆 |
| `validated_memory_ids` | 真正允许下游复用的记忆 id |
| `memory_hit` | 是否存在通过校验的记忆 |

## 7. 记忆如何传递给下游 Agent

通过 planner 校验的记忆会进入 LangGraph state：

```text
planner output:
  validated_memories
  validated_memory_ids
  memory_validation
```

这些字段会随 state 传递给后续 agent。analyst 读取 `validated_memories`，并将它们作为 `Planner-validated reusable memories` 放入自己的上下文。

但这类记忆被明确限制为 reusable hints，而不是 evidence：

- 记忆可以提示计算方法、分析路径、历史决策或答案模式。
- 记忆不能替代当前任务的文档证据。
- 当前 `documents` / `context_packets` 中的信息优先。
- analyst 输出 evidence 时仍然应引用当前任务上下文中的证据。

这样可以避免一个常见问题：检索到相似历史任务后，模型直接照搬旧答案，导致当前任务事实错误。

## 8. 记忆如何减少 LLM 调用

原流程中，planner 默认生成多个 sub-query，researcher 会 fan-out 并行执行：

```text
sub_queries = 3
researcher 调用约 3 次
```

当 planner 判断存在可复用记忆，并且 `REDUCE_RESEARCH_ON_MEMORY_HIT=1` 时，系统会将 sub-query 缩减为 1 条：

```text
sub_queries = 1
researcher 调用约 1 次
```

这条 sub-query 的目标不是重复完整研究，而是验证缺失信息或解决不确定性。

系统通过以下指标记录这类收益：

- `research_fanout_reduced`：发生了多少次 researcher fan-out 缩减。
- `research_subqueries_saved`：节省了多少条 researcher sub-query。
- `llm_calls`：总 LLM 调用次数。
- `total_tokens`：总 token 使用量。

## 9. 实验指标设计

为了评估记忆机制是否有效，我们区分以下指标：

| 指标 | 含义 |
| --- | --- |
| `candidate_rate` | 检索到候选记忆的任务比例 |
| `validated_hit_rate` | planner 判定可复用的任务比例 |
| `candidate_to_validated_rate` | 候选记忆转化为可复用记忆的比例 |
| `reduction_rate` | 实际触发 researcher 缩减的任务比例 |
| `research_subqueries_saved` | 节省的 researcher 子任务数量 |
| `llm_calls` | LLM 总调用次数 |
| `total_tokens` | 总 token 数 |
| `elapsed_s` | 总执行时间 |
| `accuracy` | 任务答案正确率 |

这些指标可以支持两类分析：

第一，记忆是否被正确检索和复用：

```text
candidate -> planner validated -> research reduced
```

第二，记忆是否带来性能收益：

```text
LLM calls / total tokens / elapsed time / accuracy
```

## 10. 当前实验观察

从当前实验结果看，记忆机制体现出几个现象：

1. 结构化模式更容易形成有效复用。

   在 company_com 任务中，structured 模式下 planner 更容易判断历史记忆可复用，validated hit rate 通常高于 text 模式。

2. 候选命中不等于有效复用。

   text 模式有时也能检索到较多候选记忆，但 planner 会拒绝其中一部分，因为它们只是关键词相似，并不能真正帮助当前任务。

3. 记忆复用可以减少 researcher 调用。

   当 planner 校验通过后，系统可以将 researcher fan-out 从多条 sub-query 缩减到一条 verification sub-query，从而减少 LLM 调用次数和 token 使用。

4. token 下降不必然带来时间等比例下降。

   总耗时还受到本地模型响应波动、embedding、Qdrant 检索、Python 调度和 I/O 等因素影响。因此性能分析需要同时看 `llm_calls`、`total_tokens` 和 `elapsed_s`。

5. 记忆 top-k 不宜过大。

   实验中发现，更多记忆不一定更好。过多候选会增加 planner 判断负担，也可能污染 analyst 上下文。因此当前倾向使用较小的 top-k，例如 `LONG_TERM_MEMORY_TOP_K=2`。

## 11. 设计特点

当前记忆机制的主要特点包括：

- 长期记忆模块与 agent 解耦，可以独立维护和替换。
- 记忆同时支持 dense、BM25 和 hybrid 检索。
- planner 统一负责记忆检索，避免多个 agent 各自读取导致上下文混乱。
- 引入 planner validation，将“检索命中”和“可复用命中”分开。
- 通过 state 显式传递 `validated_memories`，而不是隐式共享上下文。
- 下游 analyst 只把记忆当作提示，不把记忆当作证据。
- 记忆命中后可以减少 researcher fan-out，从而减少 LLM 调用。

## 12. 局限与后续优化

当前机制仍有一些限制：

1. 记忆质量依赖写入内容。

   如果 summary 或 analysis 写得过长、过泛或缺少可复用信息，检索命中率和复用质量都会下降。

2. planner 判断依赖模型能力。

   当前是否复用主要由 planner LLM 判断。小模型可能难以稳定判断记忆是否真正可复用。

3. confidence 阈值需要实验调参。

   阈值过高会导致命中率偏低，阈值过低可能引入错误记忆。当前通过 `PLANNER_MEMORY_CONFIDENCE_THRESHOLD` 控制。

4. 不同任务可能需要不同 payload schema。

   例如财报计算任务、CSV 分析任务和代码生成任务需要复用的信息不同。后续可以为不同 `memory_type` 或不同任务组设计更结构化的 payload。

5. 还可以加入记忆后置验证。

   当前机制在 planner 阶段判断记忆是否可复用。后续可以在 analyst 或 executor 后增加验证，判断使用该记忆是否真的提升了结果。

## 13. 总结

本项目中的长期共享记忆机制不是简单地“检索历史文本并塞进 prompt”，而是将记忆复用拆成三个步骤：

```text
检索候选记忆 -> planner 判断可复用性 -> 下游 agent 受控复用
```

这种设计使记忆机制更适合多智能体协作场景：

- planner 负责全局决策；
- researcher 负责补充当前任务信息；
- analyst 只消费经过 planner 校验的记忆；
- executor 基于当前 state 生成执行结果，但当前不写入 Qdrant 长期记忆；
- summarizer 基于当前 state 生成总结，并写入 summary 类型长期记忆。

最终，记忆模块既可以作为长期知识库复用历史任务经验，也可以通过减少 researcher fan-out 来降低 LLM 调用次数和 token 成本。
