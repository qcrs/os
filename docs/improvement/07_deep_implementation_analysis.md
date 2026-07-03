# StateBus v2 深度实现审阅：四大模块问题与优化方向

**基于代码事实，不基于文档声明**
**时间**：2026-07-03
**范围**：结构化通信创新、Embedding 实现、记忆复用、CodeAct

---

## 一、结构化通信（控制面）

### 1.1 当前实现事实（已更正）

> **勘误**：本文档初版将 `ControlPlaneLoopbackServer` 描述为"进程内 loopback"，这是错误的。探索代码后确认如下。

`v2/control/transport.py` 中的 `ControlPlaneLoopbackServer` 使用**真实的 `socket.AF_UNIX + SOCK_STREAM`**，通过 4 字节大端长度头 + Protobuf payload 实现序列化帧传输：

```python
# v2/control/transport.py
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(str(self.socket_path))
server.listen(1)
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.connect(str(self.socket_path))
```

`send_control_message()` / `recv_control_message()` 是真实的 socket I/O 操作，不是进程内函数调用。控制帧（`ExecRequest`、`RunStart`、`SuccessResult` 等）经过 Protobuf 序列化后通过 UDS 传输。

**正确的架构描述**：4 个角色目前在同一 Python 进程中**顺序调用**，但角色间的控制帧传递已经是真实的 UDS + Protobuf 序列化通信。控制面的"结构化协议"是实际工作的，不是模拟的。

### 1.2 当前状态与可宣称点

| 维度 | 当前状态 | 可宣称 |
|---|---|---|
| 控制帧格式 | Protobuf + 4-byte framing over AF_UNIX | ✅ typed Protobuf 控制帧通过 UDS 传输 |
| 40+ schema 版本化 | `v2/contracts/constants.py` 中完整注册 | ✅ 版本化结构化协议 |
| 角色进程隔离 | 同一进程内顺序调用 | ❌ 不能说"多进程独立 Agent" |
| Executor subprocess | 已有设计方案，待实现（Step 7）| 实现后可宣称 |

### 1.3 当前已有的真实结构化创新

1. **真实 UDS + Protobuf 帧传输**（`v2/control/transport.py`）：控制面使用 `AF_UNIX` socket，帧格式固定（4-byte length + Protobuf payload），不是 JSON 文本透传
2. **40+ schema 版本化协议对象**（`v2/contracts/constants.py`）：每个消息类型都有 `statebus.*.v1/v2` 版本化 schema
3. **LLM_CONTEXT_SLICE**：role prompt 是经过预算约束的投影，不是全量上下文
4. **hydration manifest**：Retriever 的 evidence 水化方式有明确记录，比纯文本透传有本质区别
5. **Role contract audit**：`role_contract.py` machine-verifiable 的角色合同

### 1.4 优化方向：Executor Subprocess 化

控制面已有真实 UDS，下一步是让 Executor 角色在**独立 subprocess** 中运行：

- 新增 `v2/control/subprocess_worker.py`：subprocess 入口，连接 UDS → 接收 `ExecRequest` → 执行 → 发送 `SuccessResult`
- 新增 `SubprocessExecutorTransport`（`v2/control/transport.py`）：主进程启动 subprocess、监听 UDS、等待结果
- 实现后可宣称："Executor 角色在独立 Python 子进程中运行，通过 UDS + typed Protobuf 控制帧与调度器通信"

详见实现计划 Step 7。

---

## 二、Embedding 实现问题

### 2.1 DeterministicEmbeddingEncoder：严重的质量问题

`v2/memory/embedding.py:44`：

```python
@dataclass(frozen=True)
class DeterministicEmbeddingEncoder:
    dims: int = 16

    def encode(self, *, embedding_id: str, text: str) -> StructuredEmbedding:
        counts = [0.0] * self.dims
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            slot = int(sha256_digest(token), 16) % self.dims
            counts[slot] += float(len(token))
        norm = ...
        vector = tuple(round(value / norm, 6) for value in counts)
```

**问题**：
- **只有 16 维**：这是一个 16 维的词袋 hash 向量，不是语义向量
- **无语义理解**："revenue" 和 "income" 会映射到完全不同的 slot，即使它们语义相近
- **基于词长而非词频或 TF-IDF**：`counts[slot] += float(len(token))`，这个权重没有语义意义
- **完全不能区分上下文**："季度营收下降" 和 "季度营收上升" 的 embedding 几乎相同（同样的词，不同的方向）

**影响**：deterministic 模式下的 memory lookup 和 evidence selection 几乎是随机的，不是真正的语义检索。所有 deterministic 模式下的 replay 收益数字，其"命中"主要靠任务结构（spec hash）而不是真正的 embedding 相似度。

### 2.2 SemanticChunkRetriever：top_k=1 严重限制 evidence 多样性

`v2/retrieval/pipeline.py:76`：

```python
@dataclass(frozen=True)
class SemanticChunkRetriever:
    encoder: EmbeddingEncoder = field(...)
    top_k: int = 1  # ← 只取 1 个片段！
```

加上 `TableStructureRetriever` 的 `rows[:1]`，意味着 Retriever 只会给 Executor 传递最多 2-3 个 evidence 片段，其中一个是 embedding top-1，一个是第一个匹配的表格行。

**影响**：
- Executor 和 Summarizer 拿到的 evidence 非常有限
- 当 corpus 文档包含多个相关片段时，只有第一个被使用
- 无法体现"从大量文档中精准检索"的能力

### 2.3 相似度计算不一致

`v2/retrieval/pipeline.py:97`（SemanticChunkRetriever 中）：
```python
score = sum(left * right for left, right in zip(query_embedding.vector, fragment_embedding.vector))
```
这是**点积**（dot product），不是余弦相似度。

`v2/memory/store.py:121`（MemoryIndexStore.lookup 中）：
```python
score = cosine_similarity(query_embedding, self.embeddings[ref.embedding_ref_id])
```
这是**余弦相似度**。

两个模块用了不同的相似度计算方式，语义不一致。更重要的是，embedding 已经被归一化（norm=1），所以点积等于余弦相似度——但这个等价关系是隐式的，代码没有明确注释，容易被误解。

### 2.4 v2 中没有真正的 FAISS

`v2/memory/store.py` 是纯 Python dict + cosine similarity 的线性搜索，**不使用 FAISS**。

```python
@dataclass
class MemoryIndexStore:
    embeddings: dict[str, StructuredEmbedding] = field(default_factory=dict)
    commits: dict[str, MemoryCommit] = field(default_factory=dict)
```

FAISS 在 v1 的 `memory/store.py` 中存在，但 v2 没有继承过来。

**影响**：
- v2 的 memory lookup 是 O(N) 线性扫描，N = memory 数量
- 当 memory 增长时，lookup 会变慢（benchmark 中 N 通常很小，所以没有被发现）
- "SQLite + FAISS 共享记忆"这个 claim 在 v2 中不准确——v2 是 JSON files + in-memory dict

### 2.5 优化方向

**P1（高价值）：提升 embedding 质量**

在 `api+local embedding` 模式下，`SentenceTransformerEmbeddingEncoder` 使用真实的 Qwen3-Embedding-0.6B，这个问题不存在。**但 deterministic 模式下的所有实验数字都是基于 16-dim BoW hash 的，不能用 deterministic 结果来宣称"语义检索有效"。**

解决方案：
1. 在报告中明确区分 deterministic 和 local embedding 两种模式的 evidence 质量
2. formal claim 只允许引用 `embedding_mode=local` 的实验结果
3. 改进 `DeterministicEmbeddingEncoder` 为至少 64 维，使用更好的 hash 函数（如 SimHash），以改善测试覆盖质量

**P1（高价值）：提升 top_k 和 evidence 多样性**

```python
# 当前
SemanticChunkRetriever(top_k=1)
TableStructureRetriever(rows[:1])

# 建议
SemanticChunkRetriever(top_k=3)  # 至少3个语义候选
TableStructureRetriever(rows[:3])  # 前3个相关表格行
```

同时，需要在 `_build_candidate_pool` 中为多个 candidate 做 deduplication（避免重复）。

**P2（中价值）：v2 接入 FAISS**

将 `MemoryIndexStore` 改为使用 FAISS 的 IVF 或 Flat 索引，替代线性扫描。对当前 benchmark 规模（几十条 memory）性能差距不大，但这是一个重要的架构正确性问题，也是赛题"鼓励向量数据库"的直接加分项。

---

## 三、记忆复用：严重 Bug + 架构问题

### 3.1 严重 Bug：CANDIDATE 状态的 validated/exact replay 被跳过

`v2/memory/store.py:116`：

```python
def lookup(self, ...) -> MemoryMatchResult:
    for commit in self.commits.values():
        ref = commit.memory_ref
        if ref.commit_status == MemoryCommitStatus.INVALIDATED:
            continue
        if ref.embedding_ref_id not in self.embeddings:
            continue
        # ← 这里是问题所在！
        if ref.commit_status != MemoryCommitStatus.COMMITTED and ref.replay_class != ReplayClass.ASSIST:
            continue  # CANDIDATE 状态的 validated/exact replay 被跳过！
```

**分析**：
- 如果一个 memory commit 的 status 是 `CANDIDATE`（未最终确认），并且它的 replay_class 是 `validated_replay` 或 `exact_replay`，那么它**在 lookup 中会被跳过**。
- 这意味着：在同一个 benchmark session 中，Round 1 写入的 memory，如果是 validated_replay 类型且还在 CANDIDATE 状态，Round 2 的 lookup **根本找不到它**。
- Round 2 的 replay 收益依赖于 Round 1 的 memory 已经是 COMMITTED 状态。

**这是 continuous/replay 结果中 `validated_replay_count` 不稳定的根本原因之一。**

### 3.2 commit_candidate() 的 replay class 降级逻辑

`v2/memory/store.py:59`：

```python
def commit_candidate(self, *, commit, quality_floor_pass, answer_adopted):
    status = MemoryCommitStatus.COMMITTED if quality_floor_pass and answer_adopted else MemoryCommitStatus.CANDIDATE
    ...
    if status != MemoryCommitStatus.COMMITTED and replay_class != ReplayClass.ASSIST:
        replay_class = ReplayClass.ASSIST  # ← 未 COMMITTED 的 validated/exact replay 被降级到 ASSIST
```

**分析**：
- 如果 quality_floor_pass=False 或 answer_adopted=False，memory 状态是 CANDIDATE
- CANDIDATE 状态的 memory 如果原来是 validated_replay，会被强制降级为 ASSIST
- 这个降级是**永久性的**（写入 JSON），不是临时的

**后果**：任何未完全通过 quality floor 的 memory commit，永远只能是 ASSIST 级别，无法升级为 validated/exact replay。

这与 `replay_admissibility_contract.md` 中的 `CANDIDATE→VERIFIED→INVALIDATED` 状态机不一致。合同中 CANDIDATE 应该是临时状态，可以后续升级为 VERIFIED（等价于 COMMITTED）。但代码中 CANDIDATE 的降级是立刻且永久的。

### 3.3 没有 CANDIDATE→COMMITTED 的升级路径

在 `MemoryIndexStore` 中，没有 `upgrade_candidate_to_committed()` 方法。一旦 commit 为 CANDIDATE，没有代码路径可以把它升级为 COMMITTED，除非重新 commit（但那会是一个新的 memory_id）。

**这意味着 CANDIDATE→VERIFIED 这个状态机在 v2 中没有真正实现。**

### 3.4 v2 中没有 SQLite，没有 FTS 关键词检索

`MemoryIndexStore` 使用的是：
- `embedding_registry.json`：存储 embedding 向量
- `commit_registry.json`：存储 memory commits

**不是 SQLite，不是 FAISS。**

赛题要求"支持按关键词、标签或语义相似度检索历史记忆"——v2 中的实现是：
- 语义检索：cosine similarity on StructuredEmbedding（已实现，但 embedding 质量有问题）
- 关键词检索：**没有实现**（没有 FTS 或关键词过滤）
- 标签检索：`MemoryRef.tags` 字段存在，但 `lookup()` 没有用 tags 过滤

### 3.5 producer_run_id 来自固定 trace_id

`v2/memory/models.py:162`：`producer_run_id: str = ""`

在 `v2/runtime/smoke.py` 中，`producer_run_id` 来自固定的 `trace_id`，不是每次运行唯一的。这导致：
- 不同 session 的 memory commits 可能有相同的 producer_run_id
- 无法通过 producer_run_id 准确区分来自不同 session 的记忆

### 3.6 优化方向

**P0（阻塞 replay claim）：修复 CANDIDATE 状态 memory 的 lookup 行为**

方案一（保守）：在 `lookup()` 中，允许 CANDIDATE 状态的 memory 参与检索，但在返回时标注其为"tentative"，由调用方决定是否用于 replay。

方案二（合同正确）：实现真正的 `CANDIDATE→COMMITTED` 升级路径：
```python
def promote_candidate_to_committed(self, memory_id: str, *, quality_floor_pass: bool, answer_adopted: bool) -> MemoryCommit:
    """在任务成功结束后，把 CANDIDATE 升级为 COMMITTED"""
    ...
```

**P1（claim 正确性）：v2 接入 SQLite + 关键词检索**

在 `MemoryIndexStore` 中加入 SQLite 后端：
- `memories` 表：存储 memory_ref 元数据（id, type, task_theme, tags, summary, source_agent, created_at）
- FTS 虚拟表（`CREATE VIRTUAL TABLE memories_fts USING fts5(...)`）：支持关键词全文检索
- 保留现有的 JSON embedding 文件（不需要改变 embedding 存储）

**P1（claim 正确性）：producer_run_id 改为真实 session id**

使用 `uuid.uuid4()` 生成唯一 run id，而不是复用 trace_id。

---

## 四、CodeAct：已实现的问题和优化点

### 4.1 codeact_data_tasks.py 是什么

`v2/runtime/codeact_data_tasks.py` 是一个**纯 Python 的确定性执行引擎**，不依赖 LLM。它实现了：
- `_read_csv_rows()`：CSV 文件读取
- `_parse_number()`：数值解析
- 各种数据任务（统计相关性、提取指标等）

这就是 `deterministic policy fallback` 的底层实现——当 LLM API 生成失败时，系统会用这些确定性函数来完成 data tasks。

**这不是 CodeAct（LLM 生成 Python 代码并执行），而是预写好的工具函数。**

### 4.2 CodeActRequest 的 history_runtime_roots 字段

`v2/runtime/codeact.py:162`：
```python
history_runtime_roots: tuple[str, ...] = ()
```

这个字段被传递给 CodeActRunner，但实际的使用方式需要进一步确认。`v2/runtime/smoke.py` 中的 `_history_artifact_summaries()` 函数从 history roots 中加载历史输出作为上下文。

**问题**：history 上下文是以文本形式注入 CodeAct 的 execution_goal，而不是通过结构化 `MemoryRef` 链接。这意味着 CodeAct 的历史感知是"把旧结果的 JSON 文本粘贴到 prompt 里"，不是真正的结构化复用。

### 4.3 CodeActRunner 的 API 生成流程（根据 demo 脚本推断）

根据 `bounded_llm_codeact_demo.py` 和 `v2/runtime/codeact.py` 的结构，API 生成流程是：

```
1. 构造 generation prompt（包含 execution_goal + input schema + output contract）
2. 调用 LLM API
3. 解析响应，提取 Python 代码
4. 运行 AST policy 检查
5. 如果 pass → 写入 script 文件 → 执行（bwrap 或 resource）
6. 如果 fail → 构造 repair prompt → 重试（最多 N 次）
7. 如果 N 次全部 fail → deterministic policy fallback
```

**问题 1：step 3 的解析不够鲁棒**

从 `v2/runtime/codeact.py` 的结构看，解析是从 LLM 文本中提取代码的，但可能没有处理所有 LLM 输出格式（markdown codeblock、JSON包裹等），导致 parse 失败后直接进入 repair loop（即使代码本身是正确的，只是格式不对）。

**问题 2：repair prompt 缺乏具体错误信息**

repair loop 的成功率很低（3次全失败）。关键原因是 repair prompt 可能没有把 AST policy 的具体违规行号和建议传递给 LLM。

**问题 3：AST policy allowlist 没有在 generation prompt 中明确说明**

LLM 不知道哪些 import 是允许的，会倾向于使用 `os`、`subprocess` 等标准库，这些很可能在 blocklist 中。

### 4.4 sandbox_backend 的问题

`v2/runtime/codeact_sandbox.py` 中：
- `bwrap` 模式：需要 root + SYS_ADMIN + seccomp=unconfined，只在特权 Docker profile 下可用
- `resource` 模式：只有 RLIMIT_* 限制，无 namespace 隔离，在 host 上直接运行

在标准非 root 容器中，bwrap 可能不可用（因为 unshare 需要某些 capability），会自动 fallback 到 resource 模式。

**这意味着 "bwrap sandbox" 的 claim 必须明确说明需要特权 profile，不适用于标准非 root 环境。**

### 4.5 CodeAct 与 StateBus 的集成断层

`CodeActRequest.execution_context` 包含了执行所需的上下文，但它的类型是 `dict[str, object]`，非常宽泛，没有 typed schema。

`CodeActRequest.selected_doc_hashes` 和 `evidence_pack_hash` 存在，说明 evidence 信息被传递了，但在实际的 code generation prompt 中，evidence 是以 `revenue_value` 等具体字段传入的，而不是通过 `StateRef` 消费 evidence pack 的方式。

**这意味着 CodeAct 的"从 StateRef 消费 evidence"这个链路实际上是通过把 evidence 的关键字段直接注入 prompt 来实现的，不是真正的 typed-state 消费。**

### 4.6 优化方向

**P0（质量）：改进 generation prompt，明确 AST allowlist**

详见 `04_codeact_stabilization.md`。

**P1（架构）：改进 code parser，支持多种 LLM 输出格式**

详见 `04_codeact_stabilization.md`。

**P1（创新）：CodeAct artifact 作为 SemanticStateRef 传递给下一轮**

当前 CodeAct 的执行结果（`CodeActExecutionRecord`）没有通过 `ExecutionArtifactRef` 进入 StateRef 体系，而是直接作为文件路径保存。

改进方案：
1. CodeAct 执行成功后，将 output artifact 注册为 `ExecutionArtifactRef`
2. 在下一轮 continuous task 中，通过 `history_runtime_roots` + `MemoryRef.artifact_ref_id` 查找历史 artifact
3. 如果历史 artifact 仍然有效（input hash 匹配），触发 validated_replay（跳过 CodeAct 执行，直接消费历史结果）

这是 `replay_admissibility_contract.md` 中 validated_replay 的核心场景，但目前还没有完整实现。

**P2（展示）：记录 CodeAct 的 replay 收益**

在 `CodeActExecutionRecord` 中加入：
```python
replay_class: str = "cold_start"  # "cold_start" | "validated_replay" | "exact_replay"
previous_artifact_ref_id: str = ""  # 如果是 replay，指向被复用的历史 artifact
replay_tokens_saved: int = 0  # 跳过执行节省的 LLM tokens
```
