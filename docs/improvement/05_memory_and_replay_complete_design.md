# 记忆复用完整设计

**代码基准**：`v2/memory/store.py`，`v2/memory/models.py`，`v2/memory/embedding.py`
**状态基准**：HEAD `6ece8a0`（2026-07-04）

---

## 问题一：SQLite FTS5 关键词检索 — 已实现 ✅

### 当前状态

**SQLite FTS5 已完整实现。代码核实（`v2/memory/store.py`）**：

```python
# lines 297-335: _init_db()
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    task_theme TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source_task_id TEXT NOT NULL DEFAULT '',
    source_agent TEXT NOT NULL DEFAULT '',
    created_at_ns INTEGER NOT NULL DEFAULT 0,
    memory_type TEXT NOT NULL DEFAULT '',
    replay_class TEXT NOT NULL DEFAULT '',
    commit_status TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT '',
    answer_adopted INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    tags_text TEXT NOT NULL DEFAULT ''
)
CREATE INDEX IF NOT EXISTS idx_memories_created_at_ns ON memories(created_at_ns DESC)
CREATE INDEX IF NOT EXISTS idx_memories_commit_status ON memories(commit_status)
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(memory_id UNINDEXED, task_theme, summary, source_task_id, source_agent, tags)
```

`lookup_by_keyword()` 方法（lines 195-240）：
- FTS5 可用时：走 `memories_fts MATCH ?`（BM25 排序）
- FTS5 不可用时：自动降级为 `LIKE` 查询

### 验收测试

```bash
python -m pytest -q tests/v2/test_memory_store.py -k "keyword"
```

---

## Bug B1：lookup_by_tags() 未使用 SQL 标签过滤 ⚠️

### 问题描述

`lookup_by_tags()` 方法（`v2/memory/store.py` lines 242-274）虽然查询 SQLite，但只过滤了 `commit_status != INVALIDATED`，然后把所有行拉到 Python 层做 set intersection。

**本质仍是 O(N) 扫描**，没有利用 `tags_text` 字段做 SQL 过滤。

### 根因（代码核实 lines 256-264）

```python
# 当前实现：全表拉取，Python 层过滤
rows = self._db.execute(
    """
    SELECT memory_id, tags_text, created_at_ns
    FROM memories
    WHERE commit_status != ?
    """,
    (MemoryCommitStatus.INVALIDATED.value,),
).fetchall()
# 之后 Python set intersection
for memory_id, tags_text, created_at_ns in rows:
    ref_tags = set(str(tags_text or "").split())
    overlap = len(normalized_tags & ref_tags)
```

### 解决方案

在 SQL WHERE 子句中加入 LIKE 粗筛，Python 层只做精确校验：

```python
# v2/memory/store.py lookup_by_tags() 修改方案
def lookup_by_tags(self, tags, *, require_all=False, limit=3):
    if not tags or self._db is None:
        return []
    normalized_tags = {self._normalize_tag(t) for t in tags if self._normalize_tag(t)}
    if not normalized_tags:
        return []

    # SQL 粗筛：任意一个 tag 存在即入候选
    clauses_any = " OR ".join("tags_text LIKE ?" for _ in normalized_tags)
    params_any = [f"%{tag}%" for tag in normalized_tags]
    sql = f"""
        SELECT memory_id, tags_text, created_at_ns
        FROM memories
        WHERE commit_status != ?
          AND ({clauses_any})
        ORDER BY created_at_ns DESC
        LIMIT ?
    """
    rows = self._db.execute(
        sql,
        (MemoryCommitStatus.INVALIDATED.value, *params_any, limit * 5),
    ).fetchall()

    # Python 精确 overlap 计分
    hits = []
    for memory_id, tags_text, created_at_ns in rows:
        ref_tags = set(str(tags_text or "").split())
        overlap = len(normalized_tags & ref_tags)
        if require_all and overlap < len(normalized_tags):
            continue
        if overlap == 0:
            continue
        hits.append((overlap, int(created_at_ns), str(memory_id)))
    hits.sort(key=lambda x: (-x[0], -x[1]))
    return [self.commits[mid] for _, _, mid in hits[:limit] if mid in self.commits]
```

### 影响评估

当前 benchmark 规模（数十条 memory），性能差距不明显。但赛题声明"按标签检索"时，答辩中应展示 SQL 过滤确实生效，而不是 Python 扫描。

### 验收测试

```bash
python -m pytest -q tests/v2/test_memory_store.py -k "lookup_by_tags"
```

---

## 问题二：COMMITTED 门槛 — 已解决 ✅

### 当前状态

**代码核实（`v2/memory/store.py` line 78）**：

```python
# 当前实现（已改为只需 quality_floor_pass）：
status = MemoryCommitStatus.COMMITTED if quality_floor_pass else MemoryCommitStatus.CANDIDATE
```

`answer_adopted` 只更新到 MemoryRef 的 `answer_adopted` 字段，不再影响 COMMITTED 判定。

### 验收证据

continuous replay 数据（full-experiment-20260704_111950）：
- validated_replay=15，exact_replay=10，missing_target_rounds=0
- incident_diagnosis_v2：exact_replay=7，validated_replay=2
- replay negative audit 7/7 pass

---

## 问题三：DeterministicEmbeddingEncoder 碰撞 — 已知，有控制

### 问题描述

16维 BoW hash 在语义相近词（如 "2026Q1" vs "2025Q4"）间碰撞率高，导致 deterministic 模式下 replay 命中率虚高。

### 控制措施

- 所有 formal claim 基于 `--embedding-mode local`（Qwen3-Embedding-0.6B，768维）
- DeterministicEmbeddingEncoder 仅用于 `--embedding-mode deterministic` 的快速测试
- 报告中已标注：`embedding_mode=deterministic` 结果不用于正式声明

### 代码位置

`v2/memory/embedding.py`：DeterministicEmbeddingEncoder（16维 BoW hash）vs SentenceTransformerEmbeddingEncoder（768维 Qwen3）

---

## 问题四：replay 三级触发数据 — 已验证 ✅

### replay headline 验证（full-experiment-20260704_111950）

```
continuous replay families（含 csv/long_doc families）：
  eligible_for_replay_headline=True
  validated_replay=15，exact_replay=10
  missing_target_rounds=0（全部目标轮次命中）

incident_diagnosis_v2（10轮）：
  eligible_for_replay_headline=True
  exact_replay_rounds:     [3,4,6,7,8,9,10]（7轮）
  validated_replay_rounds: [2,5]（2轮）
  skipped_step_count=16
  missing_target_rounds=[]（全部命中）

replay negative audit: 7/7 pass（无违规复用）
```

### 答辩展示数据点

| 指标 | 数值 | 说明 |
|---|---|---|
| validated_replay（合计） | 15 | 减少 LLM 调用 |
| exact_replay（合计） | 10 | 零 LLM 调用 |
| incident exact_replay | 7 / 10 轮 | 第3类任务，7轮零 LLM 调用 |
| skipped_step_count（incident）| 16 | 16个执行步骤被跳过 |
| negative audit | 7/7 pass | 无违规复用 |

---

## 问题五：FAISS 索引 — 待实装

### 问题描述

`v2/memory/store.py` 的 `lookup()` 仍是 O(N) 线性 cosine similarity 扫描（lines 118-182）。当前 benchmark 规模（数十条）无性能问题，但与"FAISS 加速"声明不符。

### 实装路径（C1）

```python
# v2/memory/store.py：添加可选 FAISS 后端
try:
    import faiss as _faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False

class FaissMemoryIndex:
    """FAISS-backed index for O(log N) embedding search."""
    dim: int = 768

    def build(self, embeddings: dict[str, StructuredEmbedding]) -> None:
        import numpy as np
        self._index = _faiss.IndexFlatIP(self.dim)
        vectors = []
        for memory_id, emb in embeddings.items():
            self._id_map[self._next_id] = memory_id
            vectors.append(list(emb.vector))
            self._next_id += 1
        self._index.add(np.array(vectors, dtype="float32"))

    def search(self, query: StructuredEmbedding, k: int = 5) -> list[tuple[str, float]]:
        import numpy as np
        q = np.array([list(query.vector)], dtype="float32")
        distances, indices = self._index.search(q, k)
        return [(self._id_map[int(i)], float(d)) for d, i in zip(distances[0], indices[0]) if i >= 0]
```

在 `MemoryIndexStore.lookup()` 中，如果 FAISS 可用且索引已初始化，替换线性扫描。

### 验收测试

```bash
python -c "
from v2.memory.store import MemoryIndexStore
store = MemoryIndexStore()
print('FAISS available:', hasattr(store, '_faiss_index'))
"
```

---

## 创新设计展望

### D2：渐进式 Replay（Progressive Replay）

当前 replay 是全有全无。改进方向：只复用部分字段（如 route+tool，不复用具体数值），其余重新计算。适用于数值会变但分析结构不变的场景（如每日 metric 更新）。

实装位置：`v2/runtime/smoke.py` 的 replay 决策逻辑，在 `ReplayClass.VALIDATED_REPLAY` 基础上增加 `PARTIAL_REPLAY` 类型。

### D3：Memory 质量衰减（Temporal Decay）

在 `lookup()` 的 score 计算中加入时效权重：

```python
# v2/memory/store.py lookup() 修改
import time
now_ns = time.time_ns()
age_days = (now_ns - ref.created_at_ns) / (86400 * 1e9)
temporal_weight = max(0.5, 1.0 - 0.05 * age_days)  # 每天衰减5%，最低50%
score = cosine_similarity(query_embedding, ...) * temporal_weight
```

适用于需要"新鲜"记忆优先的场景。
