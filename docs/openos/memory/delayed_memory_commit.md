# 从 CodeAct 基线到 Qdrant 记忆复用

## 1. 起点和新增内容

本次工作以 `origin/codeact-update` 为基线。该版本有 `src/memory.py` 中的旧 `InMemoryStore` / JSONL 逻辑，但没有：

- `src/memory_module/`；
- Qdrant 的 dense + BM25 长期记忆库；
- planner 对历史记忆的检索、LLM 校验和 research fan-out 缩减闭环；
- 任务结束后再决定是否写入记忆的机制。

在该基线上，本分支新增了可跨进程复用的 Qdrant memory module，并将运行期文档和长期记忆明确分开。当前记忆路径由三部分组成：

```text
任务 A 的研究结果
  -> 候选记忆
  -> Qdrant 长期记忆

任务 B 的 query
  -> planner 检索 Qdrant
  -> planner 校验候选是否可复用
  -> 保留 1 个验证型 sub-query，或正常发出 3 个 sub-query
```

新增的候选缓冲和 `memory_committer` 用来约束“任务 A 写入什么”；planner 的检索校验逻辑用来决定“任务 B 是否复用它”。两者共同构成记忆复用闭环。

## 2. 当前存储边界

| 层级 | 位置 | 内容 | 生命周期 | 是否检索 |
|---|---|---|---|---|
| Runtime Store | [`src/runtime_store.py`](../../../src/runtime_store.py) | researcher 的完整文档，按 `doc_key` 精确回填 | 单个 graph 实例 | 否，仅 `get_document()` 精确读取 |
| Long-term Memory | Qdrant，经 [`src/memory.py`](../../../src/memory.py) 调用 `memory_module` | analysis、summary、task_state 等可复用记录 | 跨任务、跨进程 | 是，由 planner 检索 |

Runtime Store 使用无索引的 `InMemoryStore`。它的作用只是让 analyst 在 context packet 校验失败或需要补全证据时取得当前任务的原文；它不承载长期记忆，也不会做语义搜索。

长期记忆由新增的 Qdrant `src/memory_module/` 管理。Qdrant 记录使用 dense embedding 与 BM25 混合检索，`MemoryModule` 会按内容 hash 去重。

## 3. 任务 A：写入可复用记忆

主线图现在是：

```text
planner
  -> researcher(s)
  -> analyst
  -> executor
  -> summarizer
  -> memory_committer
  -> END
```

`memory_committer` 是普通的确定性 LangGraph 节点，不是新增 LLM Agent，也不会发送 prompt 或增加 LLM 调用。

相关实现：

- [`src/graph.py`](../../../src/graph.py)：在 `ResearchState` 中定义候选和提交结果，并把 `memory_committer` 接在 `summarizer` 后。
- [`src/agent/analyst.py`](../../../src/agent/analyst.py)：生成 `analysis` 和可选 `task_state` 候选，不直接写 Qdrant。
- [`src/agent/summarizer.py`](../../../src/agent/summarizer.py)：生成 `summary` 候选，不直接写 Qdrant。
- [`src/agent/memory_committer.py`](../../../src/agent/memory_committer.py)：图节点入口。
- [`src/memory_writer.py`](../../../src/memory_writer.py)：候选格式、策略、去重和实际提交。

### 3.1 `ResearchState` 新字段

```python
pending_memory_candidates: Annotated[list[dict], operator.add]
memory_commit: dict
```

`pending_memory_candidates` 是本次任务的临时缓冲区。`analyst` 和 `summarizer` 的候选通过 `operator.add` 合并；只有 `memory_committer` 能调用 `qdrant_add_from_payload()`。

`memory_commit` 是最终输出，供 runner 和实验 JSON 记录写入结果。它不是结构化消息协议的一部分，因此不会把候选全文增加到 Agent 间 prompt 或 `AgentMessage` payload 中。

### 3.2 候选格式

每条候选至少包含：

```python
{
    "memory_type": "analysis" | "summary" | "task_state",
    "source_agent": "analyst" | "summarizer",
    "source_task_id": "<type>_<task_group>_<query_hash>",
    "memory_scope_id": "<task_group>_<query_hash>",
    "task_group": "...",
    "task_topic": "...",
    "value": {...},
    "summary": "...",
    "tags": [...],
    "evidence_refs": [...],
    "context_verification": {...},
}
```

其中 `memory_scope_id` 只用于一次任务内的候选去重；它不是跨任务事实版本号。

## 4. 写入门控

`memory_writer.classify_task()` 通过 `artifact_refs` 的 `kind=csv` / `kind=table_csv` 或 `.csv` 后缀识别 CSV，而不是依赖任务组名称或 LLM 的分类结果。

### 4.1 CSV 数值任务

CSV 候选仅在以下条件同时满足时进入提交：

1. `execution_result.ok` 为真。
2. `execution_trace` 中存在 `codeact.route`，且路由类型为 `table_csv`，证明实际走过 CodeAct CSV 路径。
3. query 中存在机器可检查的 `@field[...]` 格式。
4. 每个要求字段都存在，且不是空值、`unknown`、`null`、`nan` 等占位值。

任一条件失败时，`analysis` 和 `summary` 候选都会被拒绝。例如在 `ENABLE_CODEACT_EXECUTOR=0` 的无 CodeAct CSV 运行中，原因会是 `csv_codeact_not_run`。

即使 CSV 通过上述门控，提交器也不会原样写入 analyst/summarizer 的自然语言内容。它会将候选物化为确定性执行记录，主要包含：

- `final_answer`
- `extracted_answers`
- `execution_summary`
- `verification = "codeact_completed"`

同任务的 CSV `analysis` 与 `summary` 在物化后内容相同，任务内去重会保留 `summary`，避免把同一数值结论重复写入。CSV `task_state` 当前一律不提交。

这表示“受限执行完成且答案字段完整”，**不表示已经通过独立标准答案或第二个计算器验证**。当前没有给长期记忆添加 `verified` 状态字段。

### 4.2 非 CSV 研究任务

非 CSV 任务采用较宽松的准入条件：

- 候选必须有非空 `summary` 和 dict 类型的 `value`；
- `analysis` / `summary` 至少有一条同时包含 `claim` 与 `support` 的 evidence，或存在可靠/rehydrated 的 context verification；
- `task_state` 还必须包含至少一个非空的稳定字段，避免写入默认空状态。

这只是证据门控，不是事实证明。LLM 对 evidence 的解释仍可能有错误，因此非 CSV 记录不应被当作具有独立验证的事实。

### 4.3 去重与失败处理

提交前候选按 `(memory_scope_id, normalized_content)` 去重，优先级是：

```text
summary > analysis > task_state
```

随后由现有 `MemoryModule` 的内容 hash 执行跨任务的精确内容去重。若长期记忆被禁用、Qdrant 不可用或底层写入返回空，结果记录在 `memory_commit.not_stored`，不会误报为 `committed`。

## 5. 任务 B：检索、校验和复用

复用入口在 [`src/agent/planner.py`](../../../src/agent/planner.py)。每个新任务开始时，planner 从当前 query 构造记忆检索 query，并分别检索 Qdrant 中的 `summary` 和 `analysis`：

```python
for memory_type in ("summary", "analysis"):
    prior_results = qdrant_search(
        memory_query,
        memory_type=memory_type,
        top_k=LONG_TERM_MEMORY_TOP_K,
    )
```

`qdrant_search()` 使用配置的 embedding 后端生成 query 向量，并与 BM25 结果进行 hybrid 排序。检索结果不会直接作为事实使用，而是被压缩为包含 `id`、`memory_type`、`source_task_id`、`task_topic`、`score` 和 `content` 的候选列表，放进 planner prompt。

planner 必须返回：

```json
{
  "memory_validation": {
    "usable": true,
    "confidence": 0.0,
    "reason": "...",
    "reused_memory_ids": ["..."]
  }
}
```

代码只接受同时满足以下条件的候选：

1. `usable=true`；
2. `reused_memory_ids` 确实属于本次 Qdrant 返回的候选；
3. `confidence >= PLANNER_MEMORY_CONFIDENCE_THRESHOLD`。

通过校验后，`memory_hit=true`，并且当 `REDUCE_RESEARCH_ON_MEMORY_HIT=1` 时，原本的 3 个 researcher sub-query 会缩减为 1 个。这个剩余 sub-query 的职责是核对当前任务缺少的细节，而不是无条件相信历史记忆。

被校验通过的记忆还会以 `validated_memories` 放入共享 state。analyst 只把它们作为可复用方法、稳定决策或答案模式的提示；当前 researcher/context packet 证据优先，记忆不能替代当前来源的数值和引用。

当前主线 planner 只检索 `summary` 和 `analysis`。`task_state` 可以被写入 Qdrant，但尚未加入 planner 的默认检索列表。

因此当前可信性分工是：

| 环节 | 负责内容 |
|---|---|
| 任务 A 写入前 | `memory_committer` 拒绝执行失败、字段不完整、无证据等明显不可靠候选 |
| 任务 B 读取时 | planner 检索候选、校验相关性和置信度，并只复用返回的候选 ID |
| 任务 B 研究时 | researcher/analyst 使用当前任务证据核验历史提示 |
| 任务 B 计算时 | executor / CodeAct 产出当前任务的执行结果 |

planner 的 LLM 校验可以判断相关性，不能证明 CSV 的列选择、公式或数值正确。因此 CSV 的保守写入规则比检索阶段的语义判断更重要。

## 6. 结构化通信的影响

无需修改 `AgentMessage` 或 context packet 格式：

- 候选记忆是图内写入元数据，不是下游 LLM 需要消费的研究上下文；
- `context_verification` 已从 analyst state 保留到候选中；
- `memory_committer` 没有 LLM 调用，候选不进入 prompt；
- 最终 `memory_commit` 直接由 runner 写入实验 JSON。

所以这项改动不会增加 structured mode 的消息 token 或 embedding 传输。

## 7. Embedding 与 Qdrant 配置

长期记忆仍通过 [`src/memory.py`](../../../src/memory.py) 的 embedding 适配器写入和检索。当前可选后端包括：

- `EMBEDDING_BACKEND=local_api`：调用固定地址 `http://127.0.0.1:9040/v1` 的本地 Qwen3 embedding API；写入使用 `qwen3-embedding-doc`，检索使用 `qwen3-embedding-query`。
- `EMBEDDING_BACKEND=local_hash`：离线哈希向量 fallback。
- `EMBEDDING_BACKEND=dashscope`：DashScope embedding API。

### 7.1 三种 embedding 使用方式

#### 方式 A：本地 Qwen3 embedding API

适合有本地 GPU 和 `/data/models/Qwen3-Embedding-0.6B` 的容器。主工程只实现 OpenAI-compatible 客户端，固定访问 `http://127.0.0.1:9040/v1`；embedding 服务本身是本地运维进程，不随本仓库提交。

在本地服务脚本所在的环境启动服务，例如：

```bash
/path/to/python third_party/local_embedding_api.py \
  --host 0.0.0.0 --port 9040 \
  --model-path /data/models/Qwen3-Embedding-0.6B \
  --device cuda
```

再在运行 SynapseX 的 shell 中选择该后端：

```bash
export EMBEDDING_BACKEND=local_api
export EMBEDDING_DIMS=1024
```

服务应提供 `POST /v1/embeddings`。写入长期记忆时客户端请求模型名 `qwen3-embedding-doc`；检索 query 时请求 `qwen3-embedding-query`，服务端应为后者增加检索 instruction。可先检查服务是否可达：

```bash
curl http://127.0.0.1:9040/healthz
```

`third_party/local_embedding_api.py` 是当前机器的未跟踪辅助脚本，故 fresh clone 需要自行提供等价的 OpenAI-compatible embedding 服务，或使用下列两种方式。

#### 方式 B：DashScope embedding API

适合不运行本地 embedding 服务的联网环境：

```bash
export EMBEDDING_BACKEND=dashscope
export DASHSCOPE_API_KEY="<your-key>"
export EMBEDDING_MODEL=text-embedding-v4
export EMBEDDING_DIMS=1024
```

该方式由 `DashScopeEmbeddings` 直接调用 DashScope，不需要额外启动本地服务。

#### 方式 C：LocalHash 离线 fallback

适合 smoke test、协议测试和没有 API key 的环境：

```bash
export EMBEDDING_BACKEND=local_hash
export EMBEDDING_DIMS=1024
```

它不会加载模型或发起网络请求，但使用的是确定性的哈希词袋向量，语义检索质量低于 Qwen3 和 DashScope。未显式设置 `EMBEDDING_BACKEND` 时，代码会在存在 `DASHSCOPE_API_KEY` 的情况下选择 DashScope，否则回退到 LocalHash。

常用长期记忆环境变量：

```bash
export LONG_TERM_MEMORY_ENABLED=1
export LONG_TERM_MEMORY_QDRANT_PATH="..."
export LONG_TERM_MEMORY_COLLECTION="..."
export LONG_TERM_MEMORY_SEARCH_MODE=hybrid
export LONG_TERM_MEMORY_TOP_K=2
```

实验应使用新的 `LONG_TERM_MEMORY_QDRANT_PATH` 和 collection，避免历史 Qdrant 记录污染冷启动/热启动对比。

## 8. 可观测性与实验输出

每次图调用的最终 state 中都包含：

```python
memory_commit = {
    "task_kind": "csv" | "research",
    "accepted_count": 0,
    "rejected_count": 0,
    "committed": [...],
    "not_stored": [...],
    "rejected": [{"memory_type": "...", "reason": "..."}],
    "write_failures": [...],
}
```

数据分析 runner 会把它写入每轮记录：

- [`task/data_anas/run_group1_single.py`](../../../task/data_anas/run_group1_single.py)
- [`task/data_anas/run_group1_comparison.py`](../../../task/data_anas/run_group1_comparison.py)

公司任务 runner 也会把它写入每个 session：

- [`task/company_com/run_company_graph_single.py`](../../../task/company_com/run_company_graph_single.py)

`metrics` 还记录 `memory_candidates_seen`、`memory_candidates_rejected`、`memory_candidates_committed`、`memory_candidates_not_stored` 和 `memory_commit` 耗时。

## 9. 当前边界

当前实现尚未包含：

- 跨任务的语义冲突检测；
- 事实版本替代、过期时间和 supersedes 关系；
- CSV 数值的第二计算器/标准答案独立验证；
- 按 verified/unverified 状态过滤检索结果。

这些能力应当只在实验出现实际错误复用、记忆覆盖或时效性问题后再增量实现。

另外，本说明描述的是 `build_graph()` 主线。`build_cache_graph()` 的 [`src/agent/cache_agents.py`](../../../src/agent/cache_agents.py) 仍保留历史直接写 Qdrant 的逻辑，尚未接入 `memory_committer`；默认 CSV 和 company_com runner 不走该旁路。

## 10. 验证

新增策略测试：

```bash
PYTHONPATH=src:third_party/langgraph/libs/langgraph:third_party/langgraph/libs/checkpoint \
python3 task/data_anas/test_memory_commit.py
```

该测试覆盖：CSV CodeAct 成功、答案为 `unknown`、未走 CSV CodeAct、拒绝 CSV task_state、非 CSV 无证据拒绝、任务内去重，以及长期记忆不可用时不误报写入成功。
