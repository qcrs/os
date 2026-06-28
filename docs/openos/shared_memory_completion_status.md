# 共享记忆模块完成情况统计（代码核查版）

> 项目路径：`/data/mingwei/SynapseX`  
> 对照文件：`docs/openos/race9.md`  
> 核查日期：2026-06-21  
> 核查方式：只查看当前代码实现，不新增实验、不重新设计实验。

## 一、对照 race9.md 的共享记忆要求

`docs/openos/race9.md` 中与共享记忆相关的要求有两条：

1. **共享记忆模块**：系统需实现共享记忆模块，能够将任务执行过程中的中间结果、摘要、经验片段、证据链、结论或策略保存为统一的记忆单元，并为每条记忆记录至少包含记忆 ID、来源 Agent、创建时间、任务主题和摘要描述等基本元数据。
2. **检索历史记忆**：系统需支持按关键词、标签或语义相似度检索历史记忆，并允许不同 Agent 在后续任务中直接复用已有记忆。

## 二、总体完成情况

| race9.md 要求点 | 当前状态 | 代码依据 | 结论 |
|-----------------|----------|----------|------|
| 实现共享记忆模块 | ✅ 已完成 | `src/memory.py` 定义 Store、MemoryUnit 包装、写入和检索接口 | 已有独立共享记忆模块。 |
| 保存为统一记忆单元 | ✅ 已完成 | `make_memory_unit()` 统一包装所有 `store_put()` value | 写入 Store 的内容会被转换成统一 schema。 |
| 保存中间结果 | ✅ 已完成 | Planner 写入 plan，Retriever 写入 doc，Executor 写入 analysis，Summarizer 写入 summary | 覆盖任务执行过程的主要中间产物。 |
| 保存摘要 | ✅ 已完成 | Summarizer 写入 `summaries`，Retriever/Executor 也传入 `summary` 或 `digest` | 摘要类信息已保存。 |
| 保存经验片段 | ⚠️ 部分完成 | `payload` 可保存 recommendations/key_findings/plan 等经验性内容 | 具备承载能力，但没有单独的 `experience` 类型或专门经验抽取逻辑。 |
| 保存证据链 | ✅ 已完成 | Executor 写入 `evidence`、`selected_doc_keys`；`_extract_evidence_refs()` 生成 `evidence_refs` | 已形成可追溯证据引用。 |
| 保存结论 | ✅ 已完成 | Executor 的 `analysis`、`digest` 和 Summarizer 的 `summary/key_findings` | 结论可保存到 `analysis` 与 `summaries`。 |
| 保存策略 | ✅ 已完成 | Planner 的 `plan/sub_queries` 写入 `plans` | 计划和策略类内容已保存。 |
| 记忆 ID | ✅ 已完成 | `memory_id` 字段由 Store key 写入 MemoryUnit | 显式字段存在。 |
| 来源 Agent | ✅ 已完成 | `source_agent` 字段显式传入，namespace 也有默认映射 | 显式字段存在。 |
| 创建时间 | ✅ 已完成 | `created_at`、`created_at_iso` 在 `make_memory_unit()` 中生成 | 显式字段存在。 |
| 任务主题 | ✅ 已完成 | `task_topic` 显式传入，缺省时从 `query/sub_query/topic/plan` 推断 | 显式字段存在。 |
| 摘要描述 | ✅ 已完成 | `summary_description` 从 `summary/digest/text/plan` 推断 | 显式字段存在。 |
| 关键词检索 | ✅ 已完成 | `store_search_by_keywords()` | 支持关键词过滤检索。 |
| 标签检索 | ✅ 已完成 | `store_search_by_tags()` | 支持 tags 检索。 |
| 语义相似度检索 | ✅ 已完成 | `InMemoryStore(index=...)` + `store_search()` | 支持向量语义检索。 |
| 不同 Agent 后续复用记忆 | ✅ 已完成 | Planner/Retriever/Executor 会搜索历史 summaries/docs/analysis | 已有跨节点复用链路。 |

**结论**：按 `race9.md` 的共享记忆要求核查，当前代码已完成主要功能。唯一需要说明的是“经验片段”没有作为单独 memory type 建模，而是通过 `payload` 中的 `plan`、`key_findings`、`recommendations`、`summary` 等字段承载，因此评价为“部分完成/具备承载能力”。

## 三、共享记忆模块代码结构

| 代码位置 | 功能 | 说明 |
|----------|------|------|
| `src/memory.py:27` | `MEMORY_SCHEMA_VERSION = 1` | 定义统一记忆 schema 版本。 |
| `src/memory.py:30` | `NAMESPACE_MEMORY_DEFAULTS` | 将 namespace 映射到默认 `memory_type/source_agent`。 |
| `src/memory.py:38` | `DashScopeEmbeddings` | 有 DashScope key 时使用 `text-embedding-v4`。 |
| `src/memory.py:97` | `LocalHashEmbeddings` | 无 DashScope key 时使用本地确定性 embedding fallback。 |
| `src/memory.py:129` | `get_embeddings()` | 根据环境变量选择 embedding 后端。 |
| `src/memory.py:141` | `create_store()` | 创建带语义索引的 `InMemoryStore`，并启动时加载 JSONL 长期记忆。 |
| `src/memory.py:254` | `make_memory_unit()` | 核心函数：把任意 Agent 输出包装为统一 MemoryUnit。 |
| `src/memory.py:424` | `store_put()` | 统一写入入口，写入前强制调用 `make_memory_unit()`，写入后追加持久化。 |
| `src/memory.py:345` | `_persist_memory_unit()` | 将 MemoryUnit 追加保存到 JSONL 长期记忆文件。 |
| `src/memory.py:362` | `load_persisted_memories()` | 启动时读取 JSONL，按 namespace/key 加载最新记忆并重建语义索引。 |
| `src/memory.py:458` | `store_get()` | 读取记忆并记录指标。 |
| `src/memory.py:467` | `store_search()` | 语义检索封装。 |
| `src/memory.py:484` | `store_search_by_keywords()` | 关键词检索封装。 |
| `src/memory.py:508` | `store_search_by_tags()` | 标签检索封装。 |
| `src/memory.py:532` | `store_search_memories()` | 语义 + 关键词 + 标签的混合检索封装。 |

## 四、统一记忆单元 schema 完成情况

`make_memory_unit()` 会将写入 value 包装为统一结构。当前 MemoryUnit 关键字段如下：

| 字段 | 是否满足 race9.md | 生成方式 | 代码位置 |
|------|-------------------|----------|----------|
| `memory_schema_version` | 附加字段 | 固定为 `MEMORY_SCHEMA_VERSION` | `src/memory.py:298` |
| `memory_id` | ✅ 记忆 ID | 使用 `store_put()` 传入的 Store key | `src/memory.py:299` |
| `memory_type` | 附加字段 | 显式参数、payload 字段或 namespace 默认值 | `src/memory.py:300` |
| `source_agent` | ✅ 来源 Agent | 显式参数、payload 字段或 namespace 默认值 | `src/memory.py:301` |
| `created_at` | ✅ 创建时间 | `time.time()` | `src/memory.py:296`、`src/memory.py:302` |
| `created_at_iso` | ✅ 创建时间可读形式 | UTC ISO 时间 | `src/memory.py:303` |
| `task_group` | 附加字段 | 显式参数、payload 或 key 推断 | `src/memory.py:304` |
| `task_topic` | ✅ 任务主题 | 显式参数或从 `task_topic/query/sub_query/topic/plan` 推断 | `src/memory.py:305` |
| `summary` | 附加字段 | 归一化摘要文本 | `src/memory.py:306` |
| `summary_description` | ✅ 摘要描述 | 与 `summary` 同源 | `src/memory.py:307` |
| `text` | 附加字段 | payload `text` 或摘要/主题 | `src/memory.py:308` |
| `tags` | 检索字段 | 显式 tags + 自动派生 tags | `src/memory.py:309` |
| `evidence_refs` | 证据链字段 | 显式参数、payload 或 `_extract_evidence_refs()` | `src/memory.py:310` |
| `payload` | 原始内容 | 原始 Agent 输出完整保留 | `src/memory.py:311` |

另外，`make_memory_unit()` 会把 payload 中的旧字段通过 `setdefault()` 保留在顶层，兼容原有读取方式；因此新 schema 不破坏旧逻辑。

## 五、不同 Agent 的记忆写入情况

| Agent | Namespace | 写入内容 | MemoryUnit 类型 | race9.md 对应内容 | 代码位置 |
|-------|-----------|----------|-----------------|-------------------|----------|
| Planner | `plans` | `plan`、`sub_queries`、`query`、plan 与 sub_queries | `plan` | 策略、中间结果、任务主题 | `src/agents.py:252` |
| Retriever | `docs` | `doc_text`、`sub_query`、`task_group` | `document` | 中间结果、证据材料 | `src/agents.py:355` |
| Executor | `analysis` | `analysis`、`digest`、`evidence`、`selected_doc_keys`、verification 信息 | `analysis` | 证据链、结论、中间结果 | `src/agents.py:689` |
| Summarizer | `summaries` | `summary`、`key_findings`、`recommendations`、`query` | `summary` | 摘要、结论、经验性建议 | `src/agents.py:911` |

### 5.1 Planner 写入

Planner 生成计划后构造 `plan_memory_id = f"plan_{task_group}_{hash_text(query)}"`，并通过 `store_put()` 写入 `NS_PLANS`。写入时显式传入：

- `memory_type="plan"`
- `source_agent="planner"`
- `task_group=task_group`
- `task_topic=query`
- `summary=plan`
- `tags=["plan", "planner", task_group]`

这满足“策略/中间结果 + 记忆 ID + 来源 Agent + 任务主题 + 摘要描述”的要求。

### 5.2 Retriever 写入

Retriever 生成文档后调用 `make_document_key()` 得到 `doc_key`，并通过 `store_put()` 写入 `NS_DOCS`。写入时显式传入：

- `memory_type="document"`
- `source_agent="retriever"`
- `task_topic=sub_query`
- `summary=summarize_text(doc_text, 240)`
- `tags=["document", "retriever", task_group, ...]`

这满足“中间结果/证据材料 + 来源 Agent + 任务主题 + 摘要描述”的要求。

#### 5.2.1 `doc_key` 如何节省 token

这里的关键不是“下游 LLM 完全不需要文档内容”，而是**不把完整文档直接塞进 Agent 间消息和 Executor prompt**。完整文档仍保存在 `NS_DOCS` 的 Store 里，`doc_key` 只是引用 ID；下游 Python 代码可以用它回源校验或补取片段，但默认只把压缩后的证据片段交给 LLM。

实际链路如下：

1. Retriever 写完整文档到 Store：`store_put(store, NS_DOCS, doc_key, {"text": doc_text, ...})`，所以全文保留在共享记忆中。
2. Structured 模式下，Retriever 不把全文作为主要下游上下文，而是调用 `build_context_packet()` 生成 `context_packet`，里面包含：
   - `doc_key`：全文引用。
   - `summary`：压缩摘要。
   - `evidence_spans`：与子查询相关的短证据片段。
   - `full_doc_ref`：namespace、key、全文 hash，用于校验。
   - `original_chars` / `compressed_chars` / `compression_ratio`：压缩统计。
3. Executor 收到多个 `context_packet` 后，先用 `select_context_packets()` 选择少量相关 packet，默认取 top-3。
4. Executor 的 `_verify_and_rehydrate_packets()` 会用 `doc_key` 执行 `store_get(store, NS_DOCS, doc_key)`，在 Python 层读取全文做 hash、offset 和证据一致性校验。这个读取过程不进入 LLM prompt，因此不消耗模型输入 token。
5. 如果 packet 可靠，Executor 调用 `format_context_for_prompt()`，只把形如 `[doc_key#span_id] 短证据片段` 的内容放进 LLM prompt；metadata、hash、offset、diagnostics 都留在 Python 数据结构里。
6. 如果 packet 不可靠，才会从 Store 回源补充一个受限 fallback，目前 `_rehydrate_packet_from_store()` 只取全文开头约 360 字符，而不是把完整文档注入 prompt。

所以 token 节省来自四点：

- **引用代替全文传递**：Agent 间消息主要传 `doc_key`、摘要、证据片段和统计信息，不传完整 `doc_text`。
- **先排序再选取**：Executor 通过 lexical / embedding 信号选少量 packet，而不是把所有检索文档都交给 LLM。
- **证据片段压缩**：最终 prompt 中通常只包含每篇文档的少量 evidence span。
- **校验在 Python 层完成**：全文回源用于程序校验和必要补片段，不等于全文进入 LLM 上下文。

边界条件：如果关闭 `ENABLE_CONTEXT_PACKETS`，或进入 fallback raw-document 路径，Executor 会使用 `select_document_payloads()` 对原始文档排序后再拼接文档正文，此时 token 节省会明显下降。因此当前大量节省 token 的主要实现点是 `context_packet + doc_key 引用 + evidence span 渲染`，不是单独的 `doc_key` 本身。

#### 5.2.2 `evidence_spans` 如何获取

`evidence_spans` 不是由 LLM 再生成一遍，而是在 Retriever 构造 `context_packet` 时由 Python 规则检索得到。入口在 `build_context_packet()`：

```python
evidence_spans = retrieve_evidence_spans(
    text=doc_text,
    query=sub_query,
    max_items=max_evidence_items,
    max_chars=max_evidence_chars,
    doc_key=doc_key,
)
```

默认参数来自 `src/protocol.py`：

- `DEFAULT_EVIDENCE_PER_DOC = 4`：每篇文档最多保留 4 条 evidence span。
- `DEFAULT_EVIDENCE_CHARS = 180`：每条 span 默认最多约 180 字符。
- `DEFAULT_MIN_EVIDENCE_SCORE = 0.05`：低于该分数的候选一般不会进入结果。

具体步骤如下：

1. **抽取查询词**：`retrieve_evidence_spans()` 先对 `sub_query` 调用 `_content_terms()`，去掉停用词，得到查询关键词集合 `query_terms`。
2. **切分候选片段**：`_candidate_spans()` 调用 `_split_sentences_with_offsets()` 按中英文标点把 `doc_text` 切成带 `char_start/char_end` 的句子；如果单句超过 `max_chars`，再按窗口切片，窗口大小至少 80 字符，并带少量 overlap。
3. **计算相关性分数**：每个候选片段都会与 `query_terms` 做词重叠，计算：
   - `coverage = overlap / query_terms`：查询词覆盖率。
   - `density = overlap / span_terms`：片段内部关键词密度。
   - `position_bonus`：越靠近文档前部，轻微加分。
   - `phrase_bonus`：查询短语在片段中出现时加分。
   最终分数为 `0.72 * coverage + 0.18 * density + position_bonus + phrase_bonus`。
4. **筛选与兜底**：候选分数达到 `min_score` 且命中关键词才进入 `scored`；如果没有任何命中，则保留第一个候选作为 fallback，避免 packet 完全没有证据。
5. **排序与去重**：按分数降序排序；写入结果时跳过与已选 span 有重叠的字符区间，防止重复证据。
6. **生成结构化 span**：每条 evidence 会包含 `span_id`、`text`、`score`、`matched_terms`、`coverage`、`density`、`char_start`、`char_end`、`source_ref` 和 `retrieval_method`。其中 `source_ref` 保存 `doc_key`、原文 offset 和 `text_hash`。

生成结果形态大致如下：

```json
{
  "span_id": "ev1",
  "text": "与 sub_query 最相关的短片段",
  "score": 0.73,
  "matched_terms": ["langgraph", "memory"],
  "coverage": 0.5,
  "density": 0.2,
  "char_start": 120,
  "char_end": 260,
  "source_ref": {
    "doc_key": "doc_xxx",
    "char_start": 120,
    "char_end": 260,
    "text_hash": "..."
  },
  "retrieval_method": "lexical_span_retrieval"
}
```

这些 offset 和 hash 后续会被 Executor 的 `_verify_and_rehydrate_packets()` 使用：它通过 `doc_key` 从 Store 取回完整文档，在 Python 层检查 `doc_text[char_start:char_end]` 与 evidence 文本、hash 是否一致。只有通过校验或完成受限 rehydrate 的证据片段，才会被 `format_context_for_prompt()` 渲染进 LLM prompt。

因此，`evidence_spans` 的作用是把“完整文档”变成“可校验、可引用、短文本证据片段”，它是 token 节省和证据链可追溯的关键。

### 5.3 Executor 写入

Executor 分析完成后写入 `NS_ANALYSIS`，payload 中包含：

- `text`: 分析正文
- `digest`: 分析摘要
- `evidence`: 证据列表
- `selected_doc_keys`: 选中的文档 key
- `context_verification`: 上下文校验信息

`make_memory_unit()` 会进一步从 `evidence` 和 `selected_doc_keys` 中提取 `evidence_refs`，因此证据链有结构化引用。

### 5.4 Summarizer 写入

Summarizer 写入 `NS_SUMMARIES`，payload 包含：

- `text`: 总结正文
- `key_findings`: 关键发现
- `recommendations`: 建议
- `query`: 任务主题

这满足“摘要、结论、经验性建议沉淀为记忆”的要求。

## 六、历史记忆检索实现情况

| 检索方式 | 是否完成 | 接口 | 检索范围 | 说明 |
|----------|----------|------|----------|------|
| 语义相似度检索 | ✅ | `store_search()` | Store 的 `text` 索引字段 | 基于 `InMemoryStore(index=...)` 和 embedding。 |
| 关键词检索 | ✅ | `store_search_by_keywords()` | `text`、`summary`、`task_topic`、`tags` | 支持 `match_all` 控制全部/任一关键词匹配。 |
| 标签检索 | ✅ | `store_search_by_tags()` | `tags` | tags 会做小写、去重、空值过滤。 |
| 混合检索 | ✅ | `store_search_memories()` | 语义召回后再关键词/标签过滤 | 更适合作为跨任务复用入口。 |

### 6.1 语义检索

`create_store()` 使用如下配置创建 Store：

- `dims`: `EMBEDDING_DIMS`，默认 1024。
- `embed`: `DashScopeEmbeddings` 或 `LocalHashEmbeddings`。
- `fields`: `["text"]`。

因此只要 MemoryUnit 中有 `text` 字段，就可以进行语义相似度检索。

### 6.2 关键词检索

`store_search_by_keywords()` 会先取候选项，再调用 `_contains_keywords()`。该函数把以下字段拼成检索文本：

- `text`
- `summary`
- `task_topic`
- `tags`

因此它不是只查原始正文，而是同时查摘要、主题和标签。

### 6.3 标签检索

`store_search_by_tags()` 会先规范化查询 tags，再与 MemoryUnit 的 `tags` 集合做匹配。默认 `match_all=True`，即要求查询 tags 全部命中。

### 6.4 混合检索

`store_search_memories()` 支持组合参数：

- `query`: 语义召回。
- `keywords`: 关键词过滤。
- `tags`: 标签过滤。
- `match_all_keywords`: 是否要求全部关键词命中。
- `match_all_tags`: 是否要求全部标签命中。

这满足 `race9.md` 中“按关键词、标签或语义相似度检索历史记忆”的要求，并且额外提供了混合检索能力。

## 七、不同 Agent 复用已有记忆的代码链路

| 复用位置 | 检索 namespace | 复用内容 | 代码位置 | 完成情况 |
|----------|----------------|----------|----------|----------|
| Planner | `summaries` | 历史任务总结，作为 prior context | `src/agents.py:197` | ✅ |
| Retriever | `docs` | 相似历史文档，拼入当前 documents | `src/agents.py:392` | ✅ |
| Executor | `analysis` | 历史分析摘要，作为 prior analysis context | `src/agents.py:519` | ✅ |
| Evidence verifier | `docs` | 根据 `doc_key` 从 Store 取回原文验证证据 | `src/agents.py:782` | ✅ |

当前代码不仅写入记忆，也已经在后续 Agent 节点中读取并复用：

- Planner 在规划前搜索历史 `summaries`。
- Retriever 在检索后搜索相似历史 `docs`，如有命中则增加 `memory_reuse_hits`。
- Executor 在分析前搜索历史 `analysis` 并构造 `prior_context`。
- 证据校验阶段可通过 `store_get()` 按 `doc_key` 回查文档。

因此，“允许不同 Agent 在后续任务中直接复用已有记忆”在代码中已落地。

## 八、完成度评分（仅共享记忆模块）

| 维度 | 分值建议 | 当前得分 | 说明 |
|------|----------|----------|------|
| 统一记忆单元 schema | 25 | 24 | 字段完整，兼容旧 payload；缺少正式 schema 类型定义或 dataclass。 |
| 基础元数据完整性 | 20 | 20 | `memory_id/source_agent/created_at/task_topic/summary_description` 均显式保存。 |
| 记忆内容覆盖 | 20 | 18 | 计划、文档、分析、总结、证据链、建议均覆盖；经验片段未单独建模。 |
| 历史记忆检索 | 20 | 20 | 关键词、标签、语义、混合检索均实现。 |
| 跨 Agent 复用 | 15 | 14 | Planner/Retriever/Executor/证据校验均复用 Store；复用策略仍较简单。 |
| **合计** | **100** | **96** | 共享记忆模块功能基本满足 `race9.md` 要求。 |

## 九、当前不足

| 不足 | 影响 | 建议 |
|------|------|------|
| JSONL 追加文件会增长 | 长期运行后文件可能变大，但加载时同一 namespace/key 只取最新记录 | 后续可增加 compaction 或迁移到 SQLite/Postgres/向量数据库。 |
| “经验片段”未单独建模 | 经验、建议、策略混在 `payload` 中 | 可新增 `memory_type="experience"` 或单独经验抽取写入流程。 |
| schema 由 dict 约定 | 缺少强类型校验 | 可增加 `TypedDict`、Pydantic model 或 dataclass。 |
| 关键词/标签检索为候选后过滤 | 大规模数据下效率有限 | 持久化时可增加倒排索引或标签索引。 |
| 自动标签派生较简单 | 标签质量依赖内容和调用方 | 可加入领域标签表或更稳定的规则/模型抽取。 |

## 十、最终结论

仅对照 `docs/openos/race9.md` 的共享记忆模块要求，当前 `/data/mingwei/SynapseX` 代码实现情况如下：

- **共享记忆模块**：已实现。
- **统一记忆单元**：已实现，核心字段齐全。
- **记忆 ID、来源 Agent、创建时间、任务主题、摘要描述**：均已显式保存。
- **中间结果、摘要、证据链、结论、策略**：均已有写入路径。
- **经验片段**：具备保存载体，但未单独建模。
- **关键词检索**：已实现。
- **标签检索**：已实现。
- **语义相似度检索**：已实现。
- **不同 Agent 后续复用已有记忆**：已在 Planner、Retriever、Executor 和证据校验链路中实现。

综合判断：共享记忆模块达到 `race9.md` 要求，可评价为 **基本完成 / 接近完整完成**。后续主要改进方向是长期记忆文件 compaction、强 schema 校验和经验片段专门建模。
