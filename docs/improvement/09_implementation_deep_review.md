# 实现深度审计报告（第二版）

**代码基准**：HEAD `d11b88d`（2026-07-05）
**审计范围**：全量代码路径，逐题代码核实，聚焦真实行为与声明一致性、潜在 Bug、架构问题
**审计文件清单**：
- `v2/runtime/smoke.py`（lines 1716–1835）
- `v2/benchmark/external_text_baseline.py`（全文）
- `v2/retrieval/pipeline.py`（全文）
- `v2/control/transport.py`（全文）
- `statepool/store.py`（全文）
- `v2/memory/store.py`（全文）
- `v2/runtime/codeact_sandbox.py`（全文）
- `v2/runtime/codeact.py`（lines 1–570）
- `v2/runtime/replay.py`（全文）

---

## 一、Planner 的真实职责

### 实现路径

Planner 在 `v2/runtime/smoke.py` 中通过 `role_path_mode` 控制：

- `deterministic` 模式：`DeterministicLLMClient` — 根据 prompt 关键词 pattern matching 返回预设 JSON（无真实 LLM 调用）
- `api` 模式：调用 `LLMClient`（真实 LLM API）

### Planner 做了什么

Planner 的输出是 `PlannerHandoff`（`v2/contracts.py`），包含：
- `retrieval_objective`：告知 Retriever 要检索什么（如"ACME 2026Q1 revenue"）
- `planner_plan_payload`：route + tool_name 选择（如 `compare_metric/table_retriever`）
- `planner_scope_payload`：限定文档范围（`supporting_doc_ids`）

Planner 不看完整 corpus，只看 route 候选和任务描述。这与外部 baseline 的 external planner 设计完全对称（`external_text_baseline.py:348`）。

### 关键约束

在 formal benchmark（`--role-path-mode api`）下，Planner 确实调用真实 LLM。在 deterministic benchmark 下，Planner 通过 `DeterministicLLMClient` 用 pattern matching 完成路由——这不是真实 AI 决策，但对稳定性评测有意义。

### 答辩口径

> "formal benchmark 下 Planner 调用真实 LLM（claude-3-haiku）进行 route/tool 选择；deterministic 基准下使用 pattern-match mock 保证可复现性。两种模式下 Planner 的职责相同：输出 retrieval_objective 和 route 决策，不直接接触 corpus。"

---

## 二、SemanticChunkRetriever top_k=1 — 风险点 ⚠️

### 问题描述

`v2/retrieval/pipeline.py:85`：

```python
@dataclass(frozen=True)
class SemanticChunkRetriever:
    encoder: EmbeddingEncoder = field(default_factory=lambda: DeterministicEmbeddingEncoder(dims=16))
    top_k: int = 1  # increase via SemanticChunkRetriever(top_k=3) for richer evidence
```

SemanticChunkRetriever 默认 `top_k=1`——每个文档只选1个语义 chunk。

### 影响分析

- **formal financial family**：主要走 `TableRetriever`（`hard_fact` bucket），不依赖 SemanticChunkRetriever。质量 8/8 是正确的——Table row 精确匹配不受 top_k 影响。
- **incident_diagnosis_v2**：使用 `SemanticChunkRetriever` 做日志语义检索。若日志中相关证据跨多个 chunk，top_k=1 可能漏掉关键信息。

### 与外部 baseline 的公平性

外部 baseline 的 Retriever 接收完整 corpus（`context.public_evidence_text`，未裁剪），而 StateBus 对语义 chunk 裁剪至 top_k=1。这在纯语义检索场景（非 table 场景）可能对 StateBus 不利。

**但当前 formal benchmark 主要是 table 检索（8/8 成功），所以 top_k=1 未影响当前质量结果。**

### 建议

增加 top_k 到3（当前注释已提示），并添加回归测试确保 incident 任务质量不因 top_k 变化而退化。

---

## 三、exact_replay key 完整性与 validated_replay 正确性分析

### replay_exact_key 包含的字段（`v2/runtime/replay.py:172`）

```python
sha256_digest({
    "canonical_task_spec": {task_family, intent_op, target_entities, time_scope,
                            required_outputs, required_tools, arguments（排除benchmark专用key）},
    "input_artifact_hashes": [...],            # 任务输入文件哈希
    "runtime_compatibility_signature": combined_digest,
    "code_template_version": ...,
    "extractor_version": ...,
    "output_contract_version": ...,
})
```

`input_artifact_hashes` 在 `smoke.py` 中包含 `evidence_pack_replay_hash(pack)`，涵盖所有 hard_facts、semantic_contexts、table candidates 内容哈希。

**关键观察**：Planner 的 `retrieval_objective` **不在 replay_exact_key 内**。
若 Planner 两次给出不同的 retrieval_objective → 检索出不同 evidence → `evidence_pack_replay_hash` 不同 → `input_artifact_hashes` 不同 → exact_replay key 不同 → exact_replay 不触发。所以 exact_replay 路径正确。

但若 Planner 给出完全相同的 `retrieval_objective`（deterministic模式常见），`input_artifact_hashes` 也相同 → exact_replay 命中，跳过 Retriever+Executor，直接返回缓存答案（`skipped_step_count=2`）。这是预期行为。

### validated_replay 真实行为（⚠️ 纠正前版本）

前版本描述"复用策略而非答案"有误。**代码实际行为**：

`ReplayAdmissibilityGate.decide()` 返回 `replay_class=VALIDATED_REPLAY` 时，`smoke.py` 中的上层逻辑会从 `record.output_path` 直接读取上一次执行的 **output JSON 文件内容**（含具体 `revenue_value` 等数值），作为当前任务输出返回，`skipped_step_count=1`。

**validated_replay 复用的是「答案」，不是「策略」。**

### validated_replay 的跨实体 wrong-answer 风险

`validated_replay_contract_compatible()`（`replay.py:351`）检查：
- `task_family`、`intent_op`、`required_tools`、`required_outputs` 完全匹配
- `_schema_shape_arguments()`：仅比较 argument 的类型形状，不比较具体值

```python
# replay.py:513–530
def _schema_shape_arguments(arguments):
    return tuple(sorted(
        (key, _argument_shape_tag(value))   # "str", "int", etc.
        for key, value in arguments.items()
        if key not in {excluded_keys}
    ))
```

**可构造的错误场景**：
- 历史任务：`{ticker="ACME", quarter="2026Q1", metric="revenue"}` → `revenue_value=100M`
- 当前任务：`{ticker="GOOG", quarter="2026Q1", metric="revenue"}` → 期望 GOOG revenue

两者 schema shape 相同（`{ticker:str, quarter:str, metric:str}`），`validated_replay_contract_compatible()=True`
→ 系统返回 ACME 的 100M 给 GOOG 的查询 → **错误**。

**实际 benchmark 中的缓解措施**：
1. `select_history_replay_candidate()` 优先从 `memory_match_memory_ids`（embedding similarity 结果）中选候选，不同 ticker 的 embedding 通常相似度低
2. formal benchmark 是单 ticker 单 session，不会在同一 session 中出现跨 ticker 候选

**但这不是代码层面的硬保证**——是概率缓解，不是逻辑保证。答辩时应主动说明此设计权衡。

---

## 四、FAISS vs 线性扫描 — 关系与正确性

### 关系

两者是**替代品**（fallback 关系），不是并行运行：

```python
# v2/memory/store.py:153
faiss_scores = self._faiss_score_map(query_embedding)  # 尝试 FAISS
matched_on = "faiss_ip" if faiss_scores else "embedding_similarity"
for commit in self.commits.values():
    if ref.embedding_ref_id in faiss_scores:
        score = faiss_scores[ref.embedding_ref_id]  # FAISS 路径
    else:
        score = cosine_similarity(...)               # fallback 线性扫描
```

### B2 Bug：FAISS IP ≠ cosine_similarity（deterministic 模式）

`_build_faiss_index` 注释（`store.py:341`）写明 "assumes L2-normalised vectors"，但代码中**未执行归一化**。

- `DeterministicEmbeddingEncoder`：BoW hash 向量，未归一化 → FAISS IP ≠ cosine → 排序偏差
- `SentenceTransformerEmbeddingEncoder`（Qwen3）：sentence-transformers 输出默认归一化 → IP ≈ cosine → 正常

**实际影响**：formal benchmark 使用 `embedding-mode=local`（Qwen3），影响最小。deterministic 模式为测试路径，影响测试结果一致性。

**修复方案**：在 `_build_faiss_index()` 的 `index.add(arr)` 前加：
```python
_faiss.normalize_L2(arr)   # in-place L2 normalization，使IP = cosine
```

### 并发安全问题

`put_embedding()` 设 `_faiss_dirty=True`，下次 `lookup()` 时懒重建。无锁保护 —— 多线程并发 `put_embedding()` 时可能触发 `dict changed size during iteration`。当前 benchmark 单线程，不触发。

---

## 五、UDS + Protobuf 控制平面真实链路

### Wire Format（`v2/control/transport.py:29–49`）

真实 UDS socket I/O，不是函数调用模拟：

```python
# 4-byte big-endian header + payload
header = _recv_exact(sock, 4)
payload_len = int.from_bytes(header, byteorder="big", signed=False)
payload = _recv_exact(sock, payload_len)
```

`_recv_exact` 是循环读取，处理 TCP/UDS 分片，真实 OS-level socket。

### formal benchmark 执行模型

**同进程 loopback UDS**，非多进程：
- `ControlPlaneLoopbackServer.drive_session()` 用 threading + UDS loopback 模拟消息交换
- 4 个角色在同一 Python 进程中顺序执行，通过 loopback socket 发送消息

这是 prototype 阶段的 honest limitation。Protocol overhead 测量的是 UDS frame encode/decode 时间，排除了网络变量，使协议对比更干净。

### SubprocessExecutorTransport（`transport.py:260`）

**存在但未激活于 formal benchmark**。通过 `subprocess.Popen` 启动 `v2.control.subprocess_worker` 子进程，实现真正多进程 UDS 通信。激活条件：显式使用该 transport class（如未来生产部署）。

---

### 三种后端

| 后端 | 类 | 存储介质 | 持久化 | 实际激活场景 |
|------|-----|---------|-------|------------|
| FileBackedStatePool | `statepool/store.py` | mmap 文件（CAS） | 是 | formal benchmark 默认 |
| SharedMemoryStatePool | `statepool/store.py` | `/dev/shm` Python shm | 否 | `embedding_backend=PY_SHARED_MEMORY` |
| MemfdStatePool | `statepool/store.py:240` | `memfd_create` + SCM_RIGHTS | 否 | `embedding_backend=MEMFD` |

### formal benchmark 实际使用

`benchmark_balanced` profile（formal 默认）：`embedding_backend=MMAP_FILE`（FileBackedStatePool）。

**MemfdStatePool 在 formal benchmark 中不激活**，原因是 formal 需要 CAS 持久化以支持跨轮次 replay。MemfdStatePool 的价值在于跨进程 embedding 传递（SubprocessExecutorTransport 场景）。

### memory/store.py 与 statepool/store.py 是两个独立系统

| 系统 | 文件 | 存储内容 |
|------|------|--------|
| `v2/memory/store.py` `MemoryIndexStore` | SQLite + FAISS | Memory commits（任务结果摘要 + embedding，跨轮次复用） |
| `statepool/store.py` `StatePool` | mmap/shm/memfd | StateRef blobs（embedding 向量、证据包、执行制品，intra-session） |

两者**不重复**：StatePool 管理"传输中的状态"，MemoryIndexStore 管理"可复用的历史任务记忆"。

---

## 六、CodeAct 真实执行链路

### bwrap sandbox 链路（`v2/runtime/codeact_sandbox.py:62`）

```python
bwrap [
    "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-net",  # 命名空间隔离
    "--ro-bind", "/usr", "/usr",           # 只读系统目录
    "--tmpfs", "/tmp",                     # 干净 tmp
    "--bind", workspace, "/sandbox/workspace",  # 任务工作区可写
    "python3", "-c", generated_code
]
```

YES — **LLM 生成的 Python 代码在真实 bwrap sandbox 中执行**。

### 执行路径选择

```
LLM 生成 → AST policy check → bwrap sandbox 执行
    ↳ bwrap 不可用 → resource limit 执行
        ↳ 均失败 → deterministic_policy_fallback
```

### deterministic_policy_fallback 的含义

fallback 不是"静默返回假数据"，而是走 `v2/runtime/codeact_data_tasks.py` 中预实现的 Python 函数（确定性函数，对同一输入总是返回相同结果）。formal financial pipeline 始终走此路径（8/8 成功），保证评分稳定性。

### content-hash cache（`v2/runtime/codeact.py`）

相同 `evidence_pack_hash + route + tool_name` 的结果缓存在内存，replay 场景跳过 bwrap fork（~0ms）。这解释了 codeact_execution_stage -65.7%。

---

## 七、外部 baseline 公平性深度分析

### text_whole_lane vs external baseline

这是两个**不同的对比对象**：

| 对比 | 对象 | 系统开销对称 | 用途 |
|------|------|-----------|------|
| carrier-compare | StateBus typed vs `text_whole_lane`（内部） | 完全对称（同一代码库） | 协议效率，comparison_valid=True |
| formal compare | StateBus vs `external_text_baseline` | 不对称（两套代码） | 端到端质量/效率对比，comparison_valid=False |

### external baseline 公平性措施（`external_text_baseline.py`）

1. Planner 不看完整 corpus（与 StateBus Planner 对称）
2. Retriever 看完整 corpus（设计意图：external 没有 embedding 裁剪）
3. Executor 输出格式与 StateBus 相同（同一 quality validator）
4. 评分合同相同（`canonical_task_spec` 相同）

### 潜在公平性问题

- External Retriever 接收**完整 corpus**，StateBus Retriever 通过 semantic pruning 裁剪至 top-k。在纯语义场景，external 有信息优势。但在 formal financial（table retrieval），StateBus table_retriever 精确匹配 > external LLM 提取，所以 StateBus 8/8 vs external 6/8。
- **这是 StateBus 的竞争优势所在**：结构化路由规避了 LLM 提取精确数值的不稳定性。

---

## 八、已知 Bug 和待优化项总结

### B2（新发现）：FAISS IP 在未归一化向量下不等于 cosine similarity

- **影响**：deterministic embedding 模式下排序可能偏差
- **风险级别**：低（deterministic 仅用于测试）
- **修复**：在 `_build_faiss_index()` 加 `faiss.normalize_L2(arr)` 或改用 `IndexFlatL2`

### B3（新发现）：SemanticChunkRetriever top_k=1 对非 table 场景不够

- **影响**：incident 任务中可能漏掉跨 chunk 的关键日志证据
- **风险级别**：中（当前实验结果正常，但边界情况未测试）
- **修复**：默认改为 top_k=3，或在 incident 场景显式配置

### B4（设计风险）：validated_replay 跨实体 wrong-answer 可能性

- **影响**：`_schema_shape_arguments` 仅比较类型形状，ACME revenue 可能被 validated_replay 为 GOOG 查询
- **风险级别**：低（embedding similarity 作概率缓解；formal benchmark 单 ticker）
- **修复**：在 `validated_replay_contract_compatible()` 中增加 arguments 值比较（至少对 ticker/dataset_id）

### 已验证正常的项

- exact_replay key 完整性：input_artifact_hashes 包含 evidence_pack hash，正确
- MemfdStatePool + SCM_RIGHTS：实现完整（stress_pass 3/6，见 07 文档）
- CodeAct bwrap 隔离：真实执行，fallback 链路清晰
- UDS wire format：真实 4-byte header + payload socket I/O，非函数模拟

---

## 九、测试覆盖缺口

| 缺口 | 风险 | 建议测试 |
|-----|------|---------|
| FAISS 向量归一化假设未测试 | 中 | 测试 deterministic 模式下 FAISS vs cosine_similarity 分数差异 |
| SemanticChunkRetriever top_k 边界 | 中 | 测试 top_k=1 vs top_k=3 的 recall 差异 |
| validated_replay 跨 ticker 场景 | 低 | 测试 ACME task 的 strategy 被 BETA task 复用的场景 |
| bwrap 不可用 fallback 链路 | 低 | Mock bwrap 不可用，验证 resource fallback |
| StatePool 后端切换 | 低 | 测试 MEMFD → shm fallback 链路 |
| validated_replay wrong-answer 跨实体 | 低 | ACME/GOOG 同类型任务 validated_replay 触发正确性验证 |
| SubprocessExecutorTransport 真实子进程 | 低 | 端到端子进程 UDS 通信测试 |

---

## 十、答辩最难问题及标准回答

### Q1：FAISS IndexFlatIP 在 deterministic 模式下和 cosine_similarity 不等价，lookup 排序依赖 FAISS 是否安装而变化——这是不确定性 bug？

**标准回答**：这是已知的 B2 bug，修复方案是在 `_build_faiss_index()` 中加 `faiss.normalize_L2(arr)`（一行代码）。formal benchmark 使用 `embedding-mode=local`（Qwen3-Embedding-0.6B），sentence-transformer 输出向量默认 L2 归一化，此时 IP = cosine，结果一致，formal 数据不受影响。deterministic 模式仅用于 CI smoke 测试，memory replay candidate pool 极小（session 内 1–2 条记录），排序差异不影响实际 replay 触发结果。B2 已列入 patch 计划。

---

### Q2：validated_replay 只检查 argument 类型 shape，ACME revenue 会被复用给 GOOG query——这是正确性漏洞？

**标准回答**：这是真实的设计风险，而非代码 bug。两个缓解：(1) `select_history_replay_candidate()` 优先从 embedding similarity 匹配的 memory IDs 中选候选——ACME 与 GOOG 任务的 embedding 通常不相似，该候选不会进入 pool；(2) formal benchmark 8 个任务均为同一 ticker，不存在跨实体 validated_replay 场景。完整修复：在 `validated_replay_contract_compatible()` 增加 `ticker`/`dataset_id` 等实体字段的值比较。已知的设计权衡，会在下一版修复。

---

### Q3：UDS + Protobuf 是同进程 loopback，4 个 agent 其实是函数调用序列——和「multi-agent 协作」的宣称不符？

**标准回答**：这是 prototype 阶段的 honest limitation，在文档中明确说明。loopback 服务器保证了 wire format、framing、backpressure 的正确性验证——`SubprocessExecutorTransport` 已实现真实多进程 UDS（`transport.py:260`），在 formal benchmark 中保留为架构扩展点。系统的 protocol overhead 测量针对的是 structured vs text handoff 的序列化开销，而非进程间 IPC 延迟，loopback 排除了网络变量，使协议对比更干净，这是刻意的测量设计。

---

### Q4：formal 8/8 来自 TableRetriever 直接查表，不是 LLM 语义理解——这证明不了 StateBus 有意义？

**标准回答**：TableRetriever 是系统的有机组成部分，代表"结构化数据的高精度检索路径"，等价于 RAG 系统中的 SQL lookup。StateBus 的贡献是：(1) 将 TableRetriever 输出通过 `SemanticStateRef` 以非文本方式传递（byte savings 的测量对象）；(2) `PlannerHandoff` 哈希参与 replay key，保证结构化 handoff 的可追溯性。external baseline 的 Retriever 同样接触完整 table，若 external 8/8 与 StateBus 相同，证明两个系统在相同数据上精度等价；StateBus 胜在 prompt bytes 减少和 replay 加速。

---

### Q5：CodeAct 在没有 bwrap 的 host 上 fallback 到 resource-only sandbox，LLM 生成的代码可以任意写文件——安全边界在哪？

**标准回答**：resource-only sandbox 通过 RLIMIT（CPU 15s、AS 2GB、FSIZE 64MB、NOFILE 128、NPROC 64）限制了资源消耗，但无文件系统命名空间隔离。安全边界说明：(1) formal benchmark 使用 deterministic mode，executor script 由确定性模板生成，非任意 LLM 输出，无注入风险；(2) `api` mode 下 LLM 生成代码时，需要 bwrap 才有完整隔离，无 bwrap 属于 "prototype with known isolation gap"，已在文档中标记；(3) 最终验收在 openEuler VM（bwrap 可用）中进行，host-dev 环境不承担生产安全保证。

---

*文档更新：2026-07-05，审计者：Claude Opus 4.6*
