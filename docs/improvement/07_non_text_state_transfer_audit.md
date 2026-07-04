# 非文本状态传递完整审计

**代码基准**：`statepool/store.py`，`v2/retrieval/pipeline.py`，`v2/control/transport.py`

---

## 一、Evidence 剪枝 57~67% 为什么不影响质量

### 问题描述

连续任务 family 的 evidence bytes 从 L1 到 L2 减少 57~67%，质量20/20。这个数字看起来很大，需要解释为什么大量剪枝不会丢失关键信息。

### 根因分析：剪枝机制不是随机裁减

`v2/retrieval/pipeline.py` 的 `_rerank_candidate_pool()` 评分机制（lines 330-337）：

```python
score = candidate.score + (1.0 / (60 + candidate.rank))
if candidate.bucket == "hard_fact":
    score += 100.0    # 精确数值 > 语义上下文 > 词汇提示
elif candidate.bucket == "semantic_context":
    score += 10.0
elif candidate.bucket == "lexical_hint":
    score += 1.0
```

三类候选的绝对分数差距是 100 vs 10 vs 1——`hard_fact`（table row 精确匹配）实际上是永远被选中的，因为它比任何其他候选高出一个数量级。

`TableStructureRetriever.retrieve()`（lines 130-157）：

```python
rows = tuple(
    row for row in document.table_rows
    if row.metric_name == requested_metric or requested_metric == "revenue"
)
selected = tuple(...for index, row in enumerate(rows[:1]))  # 精确匹配的第一行
```

对于 financial task：Retriever 先找 `metric_name == requested_metric` 的 table row（精确匹配，bucket=`hard_fact`），这一行就是正确答案的来源。所有其他 evidence（文本段落、无关指标行）在得分排序后排在后面。

**被剪掉的是什么**：
- 与任务无关的文本段落（如公司战略描述、免责声明）
- 其他指标的 table row（任务要 revenue，剪掉了 operating_cost、net_income 行）
- 低相似度的 semantic_context chunk

**没被剪掉的是什么**：
- 精确匹配的 table row（回答问题所必需的数值）
- top-k 语义相关的文本段落（api/local 模式 top_k=3）

### 质量不受影响的实验证据

从 flagship ablation 数据（`v2_experiment_summary_20260703.md`）：

| Layer | evidence bytes | quality | 说明 |
|---|---|---|---|
| L0 | 15,552 B（8 cases）| 8/8 | 全量 evidence，无语义剪枝 |
| L1 | 15,552 B | 8/8 | 结构化 carrier，evidence 量不变 |
| L2 | 约 9,200 B（-41%）| 8/8 | 语义剪枝后，质量保持 |

L2 evidence 减少 41%（formal fixed-answer），质量完全不变。这是直接的控制对比实验：相同任务，相同评分合同，唯一变量是是否使用语义选择。

Continuous family 的 57~67% 减少（L1→L2）：这个比例更高是因为 continuous task（CSV/长文档）的全量 corpus 中有大量重复行和无关列，表格数据有天然的列稀疏性，被剪掉的大多是"不需要看的列"。

### 边界条件：什么情况下剪枝可能丢失信息

1. **multi-period comparison task**（如 cross_period_financial_v1）：需要两个不同时期的数值，如果 Planner 没有把两个 doc_id 都传入 `supporting_doc_ids`，Retriever 可能只检索一个文档的数据。这是 Planner 层的设计问题，不是剪枝本身的问题。

2. **新增 incident_diagnosis_v2 任务**：日志文件的 semantic pruning 依赖 Qwen3 embedding 的语义理解，理论上可能错过某些关键日志行。对此，在新任务设计中应保留 full log 作为 fallback，或在任务设计时确保关键行有明确的语义标记（如 `[ERROR]`、`[SLOW]`）。

### 验收：运行 L0 vs L2 受控对比

```bash
# 运行 formal suite 两次，比较有无语义剪枝的 evidence bytes 和 quality
python -m v2.benchmark.live_runner \
  --suite formal --benchmark-tier formal \
  --role-path-mode api --embedding-mode local \
  2>&1 | grep -E "raw_evidence_bytes|quality_floor_pass|semantic_state_transfer"

# 期望：quality_floor_pass_count=8 且 raw_evidence_bytes_seen_by_llm < full_corpus_bytes
```

---

## 二、mmap vs shared_memory：设计边界与 openEuler 升级路径

### 问题描述

当前有两个数据面后端（`statepool/store.py`）：
- `FileBackedStatePool`：文件系统 + mmap 读取
- `SharedMemoryStatePool`：`multiprocessing.shared_memory`（底层 `shm_open`/`/dev/shm`）

这两个后端并存，不是非此即彼的关系。但它们的适用场景和生命周期不同，需要一套清晰的协调策略。此外，openEuler 24.03-LTS-SP3 有更底层的 IPC 机制（`memfd_create` + `SCM_RIGHTS`），可以在当前架构基础上无缝升级。

### 根因分析：两个后端解决不同问题

从 `statepool/store.py` 的设计看：

```python
# StatePoolConfig 有两个独立的 backend 配置
@dataclass(frozen=True)
class StatePoolConfig:
    default_backend: str = MMAP_FILE_STORAGE      # 一般状态
    embedding_backend: str = MMAP_FILE_STORAGE     # embedding 专用

# put_embedding 使用 embedding_backend
def put_embedding(self, *, state_id, payload, metadata=None) -> StateRef:
    return self.put_bytes(..., storage=self.config.embedding_backend)
```

**设计意图**：embedding 可以走不同的 backend（用 `embedding_backend` 单独控制），其他状态走 `default_backend`。当前两个都默认 `MMAP_FILE`，但可以把 `embedding_backend` 切换为 `PY_SHARED_MEMORY` 来加速 embedding 传递。

| 维度 | FileBackedStatePool | SharedMemoryStatePool |
|---|---|---|
| 存储位置 | 文件系统（可审计） | `/dev/shm`（POSIX tmpfs） |
| 读写方式 | file I/O + `mmap.ACCESS_READ` | `SharedMemory(name=handle)` |
| 生命周期 | 持久，session 结束后保留 | 临时，需显式 `unlink()` |
| 跨进程 | ✓（文件路径共享） | ✓（handle name 共享） |
| 跨 session | ✓（文件持久化） | ✗（进程退出后失效） |
| Replay 支持 | ✓（CAS_REPLAY_RESTORABLE_KINDS） | ✗（不持久化） |
| CAS dedup | ✓（ContentAddressedBlobStore） | ✗ |

**当前协调策略**（来自代码）：
- EMBEDDING / FEATURE_BUNDLE / RANKED_EVIDENCE_BUNDLE 等在 `CAS_REPLAY_RESTORABLE_KINDS` 中 → 自动走 CAS 文件存储（支持跨 session replay）
- 短暂的 embedding 传递（只需在当次 pipeline run 中有效）→ 可用 shm 加速

### openEuler 的更优方案：memfd_create + SCM_RIGHTS

**为什么 memfd_create 更好**：

`multiprocessing.shared_memory` 在 `/dev/shm` 中创建命名段（`/dev/shm/psm_xxxxxx`），需要显式 `unlink()` 清理。如果进程异常退出，`/dev/shm` 会留下未清理的段。

`memfd_create` 创建匿名内存文件描述符，不在文件系统中留下任何痕迹。通过 `SCM_RIGHTS` 在 UDS `sendmsg` 中传递 FD，接收方直接 `mmap` 读取。当所有持有 FD 的进程关闭，内核自动回收内存。

**openEuler 24.03-LTS-SP3 的内核版本**：基于 Linux 6.x，`memfd_create` 自 Linux 3.17 起可用，完全支持。

### 实现方案：MemfdStatePool（新增第三后端）

在 `statepool/store.py` 中新增：

```python
import ctypes, os

MEMFD_STORAGE = "MEMFD"

def _memfd_create(name: str) -> int:
    """调用 memfd_create syscall，返回 fd（只对 Linux 有效）"""
    # MFD_CLOEXEC | MFD_ALLOW_SEALING = 0x1 | 0x2 = 0x3
    MFD_CLOEXEC = 0x0001
    SYS_memfd_create = 319  # x86_64；aarch64 = 385
    import platform
    if platform.machine() == "aarch64":
        SYS_memfd_create = 385
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    fd = libc.syscall(SYS_memfd_create, name.encode(), MFD_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "memfd_create failed")
    return fd


class MemfdStatePool:
    """
    openEuler 最优路径：memfd_create + mmap。
    不依赖 /dev/shm 命名段，无需手动 unlink，
    FD 通过 SCM_RIGHTS 经 UDS 传递给 Executor 进程。
    """

    def __init__(self, root: str | Path, *, owned_fds: dict[str, int] | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        # fd_map: state_id → fd（本进程持有）
        self.fd_map: dict[str, int] = owned_fds if owned_fds is not None else {}

    def put_bytes(
        self,
        state_id: str,
        kind: str,
        payload: bytes,
        metadata: dict[str, object] | None = None,
    ) -> StateRef:
        fd = _memfd_create(f"statebus_{state_id[:16]}")
        os.write(fd, payload)
        os.lseek(fd, 0, os.SEEK_SET)
        self.fd_map[state_id] = fd
        checksum = hashlib.sha256(payload).hexdigest()
        ref = StateRef(
            state_id=state_id,
            kind=kind,
            length=len(payload),
            metadata=dict(metadata or {}),
            storage=MEMFD_STORAGE,
            handle=str(fd),          # FD 号作为 handle
            blob_hash=checksum,
            checksum=checksum,
        )
        _write_ref_meta(self.meta_dir / f"{state_id}.json", ref)
        return ref

    def get_bytes(self, ref: StateRef) -> bytes:
        fd = int(ref.handle)
        os.lseek(fd, 0, os.SEEK_SET)
        return os.read(fd, ref.length)

    def get_embedding(self, ref: StateRef) -> np.ndarray:
        dtype = str(ref.metadata.get("dtype", "float32"))
        vector_dim = int(ref.metadata["vector_dim"])
        fd = int(ref.handle)
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, ref.length)
        return np.frombuffer(raw, dtype=dtype).copy()

    def send_fd_via_uds(self, state_id: str, sock) -> None:
        """通过 UDS SCM_RIGHTS 把 memfd FD 传给另一个进程"""
        import socket as _socket, array as _array
        fd = self.fd_map[state_id]
        fds = _array.array("i", [fd])
        cmsg = [(_socket.SOL_SOCKET, _socket.SCM_RIGHTS, fds)]
        sock.sendmsg([b"fd:" + state_id.encode()], cmsg)

    def close_all(self) -> None:
        for fd in self.fd_map.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self.fd_map.clear()
```

### mmap / shm / memfd 协调策略（分场景）

| 场景 | 推荐后端 | 理由 |
|---|---|---|
| 需要 replay 的状态（EMBEDDING, FEATURE_BUNDLE 等） | CAS（FileBackedStatePool） | 持久化，cross-session 复用，dedup |
| 同进程内临时 embedding 传递（current arch）| FileBackedStatePool（默认）| 简单可靠，无生命周期问题 |
| 跨进程 embedding 传递（当前 shm 路径）| SharedMemoryStatePool | 零拷贝，handle name 跨进程可见 |
| 跨进程 embedding 传递（openEuler 升级路径）| MemfdStatePool + SCM_RIGHTS | 无 /dev/shm 命名，自动回收，更安全 |
| 审计 bundle / telemetry | FileBackedStatePool | 必须持久化 |

**在 `StatePool.put_embedding()` 中落地**：

```python
def put_embedding(self, *, state_id, payload, metadata=None) -> StateRef:
    backend = self.config.embedding_backend
    if backend == MEMFD_STORAGE:
        return self.memfd_pool.put_bytes(state_id, "EMBEDDING", payload, metadata)
    if backend == PY_SHARED_MEMORY_STORAGE:
        return self.shared_pool.put_bytes(state_id, "EMBEDDING", payload, metadata)
    # 默认 file-backed（CAS or mmap）
    return self.put_bytes(state_id=state_id, kind="EMBEDDING", payload=payload, metadata=metadata)
```

### 如果 openEuler 不支持 memfd_create（降级方案）

虽然 openEuler 24.03 应该支持，但做健壮的 fallback：

```python
def _memfd_create_safe(name: str) -> int | None:
    """尝试 memfd_create，失败时返回 None（调用方降级到 shm）"""
    try:
        return _memfd_create(name)
    except (OSError, AttributeError):
        return None

# 在 MemfdStatePool.put_bytes() 中：
fd = _memfd_create_safe(f"statebus_{state_id[:16]}")
if fd is None:
    # 降级到 SharedMemoryStatePool
    return self._shm_fallback.put_bytes(state_id, kind, payload, metadata)
```

### 验收测试

```bash
# 1. 验证 memfd_create 在当前环境可用
python3 -c "
import ctypes, os, platform
SYS_memfd = 319 if platform.machine() == 'x86_64' else 385
libc = ctypes.CDLL('libc.so.6', use_errno=True)
fd = libc.syscall(SYS_memfd, b'test', 0x0001)
print('memfd_create: fd =', fd)
assert fd > 0, 'memfd_create failed'
os.close(fd)
print('memfd_create OK')
"

# 2. 验证 MemfdStatePool 基本读写
python3 -c "
import sys; sys.path.insert(0, '.')
from statepool.store import MemfdStatePool
import numpy as np, pathlib, tempfile

with tempfile.TemporaryDirectory() as d:
    pool = MemfdStatePool(d)
    data = np.random.rand(768).astype(np.float32).tobytes()
    ref = pool.put_bytes('emb-001', 'EMBEDDING', data, {'vector_dim': 768})
    retrieved = pool.get_bytes(ref)
    assert retrieved == data, 'data mismatch'
    pool.close_all()
    print('MemfdStatePool: read/write OK')
"

# 3. 运行 formal suite 用 shm backend，验证质量不变
STATEBUS_EMBED_STATE_BACKEND=shared_memory \
python -m v2.benchmark.live_runner \
  --suite formal --benchmark-tier formal \
  --role-path-mode api --embedding-mode local \
  2>&1 | grep -E "quality_floor_pass|shared_memory_publish"
# 期望：quality_floor_pass_count=8，shared_memory_publish_count=8
```

---

## 三、StateRef 中的 mmap_publish_count=0 解释

`mmap_publish_count` 统计的是显式发布 `MMAP_FILE` 类型 StateRef 的次数（即手动调用 `FileBackedStatePool.put_bytes()` 且 kind 标注为 mmap 的次数）。

实际上 formal benchmark 发布的状态类型是 `EMBEDDING` 和 `DENSE_EVIDENCE`，这些通过 CAS 存储（`ContentAddressedBlobStore`），统计为 `semantic_state_transfer_count=8`，不计入 `mmap_publish_count`。

底层读取时（`StatePool.get_bytes()` line 353）确实使用了 `mmap.mmap(handle.fileno(), ACCESS_READ)`，但这是实现细节，不影响统计标签。

**结论**：`mmap_publish_count=0` 是正确行为，不需要修改。报告中解释：所有 StateRef 发布均通过 CAS 文件存储，统计为 semantic_state_transfer，底层读取使用 mmap 加速但不影响统计分类。

---

## 四、四环节完整实现状态（基于代码核实）

| 环节 | 实现类/方法 | embedding_mode=local | 代码位置 |
|---|---|---|---|
| **生成** | `SentenceTransformerEmbeddingEncoder.encode()` | Qwen3-Embedding-0.6B，768维 | `v2/memory/embedding.py:71` |
| **传递** | `StatePool.put_embedding()` → StateRef | CAS 文件 或 shm，ref 通过 UDS 控制帧传递 | `statepool/store.py:330` |
| **接收** | `StatePool.get_embedding(ref)` → np.ndarray | 通过 ref_id / handle 读取 | `statepool/store.py:367` |
| **使用** | `SemanticChunkRetriever._cosine_sim()` → top-k prune | cosine similarity 剪枝，corpus evidence -57~67% | `v2/retrieval/pipeline.py:98` |
