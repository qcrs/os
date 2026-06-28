# 跨任务共享记忆复用实验

> 实验时间：2026-06-20T09:11:48.623079+00:00  
> 运行容器：`SynapseX-wmw`  
> 代码路径：`/data/mingwei/SynapseX`

## 一、实验目的

本实验验证当前共享记忆模块在跨任务场景中的两类能力：

1. **准确性**：后续任务能否从历史记忆中准确检索上一任务的摘要、证据链、结论和策略。
2. **效率**：语义检索、关键词检索、标签检索和混合检索的耗时是否足够低，是否能减少重复上下文装载。

实验以代码实现为准，直接调用 `src/memory.py` 中的真实接口：`create_store()`、`store_put()`、`store_search()`、`store_search_by_keywords()`、`store_search_by_tags()` 和 `store_search_memories()`。实验不调用 LLM，也不依赖外部 embedding API；未设置 `DASHSCOPE_API_KEY` 时使用 `LocalHashEmbeddings`，保证在新容器中可复现。

## 二、实验环境

| 项目 | 值 |
|------|----|
| 容器 | `SynapseX-wmw` |
| 镜像 | `hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3` |
| 容器内代码路径 | `/data/mingwei/SynapseX` |
| Python | `3.11.6` |
| Embedding 后端 | `LocalHashEmbeddings` |
| DashScope Key | `False` |
| `dashscope` | `1.25.23` |
| `langchain-core` | `1.4.8` |
| `langchain-openai` | `1.3.2` |
| `numpy` | `2.4.6` |
| `langgraph` | `local-source: third_party/langgraph/libs/langgraph` |

复现实验命令：

```bash
docker exec -w /data/mingwei/SynapseX SynapseX-wmw bash -lc 'unset DASHSCOPE_API_KEY http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; PYTHONPATH=/data/mingwei/SynapseX/src:/data/mingwei/SynapseX/third_party/langgraph/libs/langgraph:/data/mingwei/SynapseX/third_party/langgraph/libs/checkpoint python3 -u run_memory_reuse_experiment.py'
```

实验原始 JSON 结果保存于 `docs/openos/memory_reuse_experiment_results.json`。

## 三、任务设计

| 阶段 | 内容 | 目的 |
|------|------|------|
| Task A | 写入统一共享记忆模块相关的计划、文档、分析和总结 | 模拟上一任务形成可复用记忆 |
| Task B | 查询 MemoryUnit schema、metadata、evidence_refs、memory-reuse 等线索 | 验证后续任务能否复用 Task A 记忆 |
| 干扰项 | AutoGen、CrewAI、vector-db benchmark、graph scheduling | 验证检索不会被相近但无关记忆误导 |

共写入 `9` 条记忆，namespace 分布为：`analysis`=2, `docs`=3, `plans`=1, `summaries`=3。

## 四、统一记忆单元校验

当前 `store_put()` 会先调用 `make_memory_unit()`，将不同 Agent 写入的异构 value 包装为统一 `MemoryUnit`，并保留原始内容到 `payload`。本实验校验的必备字段为：`memory_id`, `memory_type`, `source_agent`, `created_at`, `created_at_iso`, `task_group`, `task_topic`, `summary_description`, `tags`, `payload`。

| 指标 | 结果 |
|------|------|
| 记忆单元总数 | 9 |
| 通过 schema 校验 | 9 |
| Schema 通过率 | 100.0% |
| 缺失字段 | `{}` |
| 非法字段 | `{}` |
| 来源 Agent 分布 | `executor`=2, `planner`=1, `retriever`=3, `summarizer`=3 |
| 记忆类型分布 | `analysis`=2, `document`=3, `plan`=1, `summary`=3 |
| 证据链引用完整 | True |

技术要点：

- `memory_id` 使用 Store key 显式保存，不再只依赖外部 key。
- `source_agent`、`memory_type` 可由 namespace 默认推断，也可由调用方显式传入。
- `created_at` 和 `created_at_iso` 在写入时生成，保存在 value 中，后续检索可直接读取。
- `task_topic`、`summary_description`、`tags` 在统一 schema 中稳定存在，支持跨 Agent 复用。
- `evidence_refs` 从 `analysis.evidence` 和 `selected_doc_keys` 提取，形成可追踪证据链。
- `payload` 保留原始 Agent 输出，保证兼容旧字段和后续追溯。

## 五、检索准确性结果

总体结果：`Precision@1=1.000`，`Recall@3=1.000`，`MRR=1.000`，测试项数量 `6`。

| 测试项 | 模式 | Namespace | 期望命中 | Top 结果 | Rank | Hit@1 |
|--------|------|-----------|----------|----------|------|-------|
| `semantic_summary_reuse` | semantic | `summaries` | `summary_A_memory_schema` | `summary_A_memory_schema, summary_autogen_runtime, summary_crewai_roles` | 1 | 1 |
| `keyword_summary_reuse` | keyword | `summaries` | `summary_A_memory_schema` | `summary_A_memory_schema` | 1 | 1 |
| `tag_summary_reuse` | tag | `summaries` | `summary_A_memory_schema` | `summary_A_memory_schema` | 1 | 1 |
| `hybrid_summary_reuse` | hybrid | `summaries` | `summary_A_memory_schema` | `summary_A_memory_schema` | 1 | 1 |
| `semantic_doc_retrieval_modes` | semantic | `docs` | `doc_retrieval_methods` | `doc_retrieval_methods, doc_vector_db_benchmark, doc_memory_schema` | 1 | 1 |
| `hybrid_analysis_evidence_chain` | hybrid | `analysis` | `analysis_A_memory_schema` | `analysis_A_memory_schema` | 1 | 1 |

结论：在包含干扰记忆的条件下，语义、关键词、标签和混合检索均能把 Task A 的目标记忆排在第一位，后续 Agent 可以直接复用已有摘要与分析证据链。

## 六、检索效率结果

每种检索方式先预热 `5` 次，再统计 `50` 次耗时，单位为毫秒。

| 检索方式 | 次数 | 平均 | 最小 | P50 | P95 | 最大 | 最后一次 Top 结果 |
|----------|------|------|------|-----|-----|------|-------------------|
| `semantic_summary` | 50 | 0.5955 | 0.5316 | 0.5917 | 0.6694 | 0.7049 | `summary_A_memory_schema, summary_autogen_runtime, summary_crewai_roles` |
| `keyword_summary` | 50 | 0.0301 | 0.0289 | 0.0295 | 0.0317 | 0.0416 | `summary_A_memory_schema` |
| `tag_summary` | 50 | 0.0311 | 0.0297 | 0.0302 | 0.0336 | 0.0462 | `summary_A_memory_schema` |
| `hybrid_summary` | 50 | 0.8757 | 0.5869 | 0.8772 | 1.1926 | 1.2669 | `summary_A_memory_schema` |
| `hybrid_analysis` | 50 | 1.1887 | 0.8369 | 1.1533 | 1.5648 | 1.6229 | `analysis_A_memory_schema` |

观察：

- 关键词和标签检索只做本地字段过滤，平均耗时约 `0.0301` ms 和 `0.0311` ms，适合做精确约束。
- 语义检索使用 `LocalHashEmbeddings` + `InMemoryStore`，平均耗时 `0.5955` ms，可用于召回主题相近记忆。
- 混合检索先语义召回再做关键词和标签过滤，平均耗时 `0.8757` ms；开销高于纯过滤，但能同时兼顾相关性和精确性。
- 分析记忆的混合检索平均耗时 `1.1887` ms，可在后续任务中快速定位带证据链的结论。

## 七、复用效果示例

Task B 查询：`如何基于上一任务的 MemoryUnit schema 继续优化跨任务记忆复用？`

命中的摘要记忆：

- `memory_id`: `summary_A_memory_schema`
- `source_agent`: `summarizer`
- `summary_description`: MemoryUnit 统一元数据包含 created_at、source_agent 和 evidence_refs，可被后续任务直接复用。

命中的分析记忆：

- `memory_id`: `analysis_A_memory_schema`
- `source_agent`: `executor`

证据链：

| doc_key | span_id | claim |
|---------|---------|-------|
| `doc_memory_schema` | `schema-fields` | MemoryUnit schema fields are explicitly recorded. |
| `doc_retrieval_methods` | `retrieval-modes` | Semantic, keyword, tag, and hybrid retrieval enable reuse. |
| `doc_memory_schema` | `None` | selected_doc_key 引用 |
| `doc_retrieval_methods` | `None` | selected_doc_key 引用 |

估算上下文节省：

| 指标 | 值 |
|------|----|
| 全量 seeded memory 文本字符 | 1362 |
| 复用摘要 + 分析摘要字符 | 110 |
| 估算上下文压缩比例 | 91.92% |

该估算表示：后续任务无需重新装载所有历史计划、文档和分析文本，而是先检索命中的摘要与证据链引用，再按需追溯原始 `payload` 或文档 key。

## 八、结论与限制

### 结论

- 当前实现已经从“按阶段 namespace 划分的异构 value”改进为统一 `MemoryUnit` schema。
- 记忆元数据完整性达到 `100%`，满足记忆 ID、来源 Agent、创建时间、任务主题、摘要描述等基本要求。
- 跨任务复用检索在本实验中达到 `Precision@1=100%`、`Recall@3=100%`、`MRR=100%`。
- 本地检索延迟处于毫秒级，关键词/标签过滤最快，混合检索适合最终复用入口。

### 限制

- 本实验是确定性离线实验，主要验证共享记忆模块本身；未把 LLM 输出随机性纳入评估。
- `LocalHashEmbeddings` 适合离线回归测试，不代表 DashScope `text-embedding-v4` 的真实语义质量上限。
- 当前 Store 为 `InMemoryStore`，进程退出后不持久化；如需长期共享记忆，需要接入持久化 KV/向量存储。
- 样本规模为 9 条记忆，后续可扩展到更多连续任务和更大干扰集，进一步评估召回稳定性。
