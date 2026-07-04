# 记忆复用完整设计

**代码基准**：`v2/memory/store.py`，`v2/memory/models.py`，`v2/memory/embedding.py`

---

## 问题一：关键词和标签检索缺失（赛题直接要求）

### 问题描述

赛题明确要求"支持按关键词、标签或语义相似度检索历史记忆"。当前 `v2/memory/store.py` 的 `lookup()` 方法只实现了 embedding cosine similarity，无关键词和标签检索路径。

`MemoryRef` 有 `tags` 字段，但 `lookup()` 不用它过滤。`commit_registry.json` 里有 `task_theme` 和 `summary` 字段，但没有全文索引。

### 解决方案

在 `MemoryIndexStore` 中加入 SQLite FTS5 后端，不替换现有 dict（向后兼容），而是并行维护。

**Step 1：在 `MemoryIndexStore.__init__` 中初始化 SQLite**

```python
# v2/memory/store.py
import sqlite3

@dataclass
class MemoryIndexStore:
    embeddings: dict[str, StructuredEmbedding] = field(default_factory=dict)
    commits: dict[str, MemoryCommit] = field(default_factory=dict)
    _db: sqlite3.Connection = field(default=None, init=False, compare=False, repr=False)

    def _init_db(self, db_path: str = ":memory:") -> None:
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                task_theme TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                source_agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                replay_class TEXT NOT NULL DEFAULT '',
                commit_status TEXT NOT NULL DEFAULT ''
            )
        """)
        self._db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                memory_id UNINDEXED,
                task_theme,
                summary,
                tags,
                content='memories',
                content_rowid='rowid'
            )
        """)
        self._db.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, memory_id, task_theme, summary, tags)
                VALUES (new.rowid, new.memory_id, new.task_theme, new.summary, new.tags);
            END
        """)
        self._db.commit()
```

**Step 2：在 commit 写入时同步更新 SQLite**

找到 `commit_candidate()` 方法（`v2/memory/store.py` lines 59-81），在写入 dict 之后加：

```python
def _index_commit(self, commit: MemoryCommit) -> None:
    """同步更新 SQLite 索引"""
    if self._db is None:
        return
    ref = commit.memory_ref
    import json as _json
    self._db.execute(
        "INSERT OR REPLACE INTO memories "
        "(memory_id, task_theme, tags, summary, source_agent, created_at, replay_class, commit_status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            ref.memory_id,
            ref.task_theme or "",
            _json.dumps(sorted(ref.tags or [])),
            ref.summary or "",
            ref.source_agent or "",
            ref.created_at or "",
            (ref.replay_class.value if ref.replay_class else ""),
            (ref.commit_status.value if ref.commit_status else ""),
        ),
    )
    self._db.commit()
```

**Step 3：实现 `lookup_by_keyword()` 和 `lookup_by_tags()`**

```python
def lookup_by_keyword(self, keyword: str, limit: int = 10) -> list[MemoryCommit]:
    """全文关键词检索（FTS5）"""
    if self._db is None:
        return []
    rows = self._db.execute(
        "SELECT memory_id FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
        (keyword, limit),
    ).fetchall()
    return [self.commits[row[0]] for row in rows if row[0] in self.commits]

def lookup_by_tags(self, tags: list[str], match_all: bool = False) -> list[MemoryCommit]:
    """标签过滤检索"""
    results = []
    for commit in self.commits.values():
        commit_tags = set(commit.memory_ref.tags or [])
        if match_all:
            if set(tags).issubset(commit_tags):
                results.append(commit)
        else:
            if set(tags) & commit_tags:
                results.append(commit)
    return results
```

### 验收测试

```bash
python -c "
import sys; sys.path.insert(0, '.')
from v2.memory.store import MemoryIndexStore
from v2.memory.models import MemoryCommit, MemoryRef, MemoryCommitStatus, ReplayClass

store = MemoryIndexStore()
store._init_db()

# 创建测试 memory
ref = MemoryRef(
    memory_id='test-001',
    task_theme='financial_analysis',
    tags=['revenue', 'ACME', 'Q1'],
    summary='ACME Q1 2026 revenue was 2.4B',
)
# ... commit 写入 store ...

results = store.lookup_by_keyword('revenue')
assert len(results) > 0, 'keyword lookup failed'
print('keyword lookup: OK')

results = store.lookup_by_tags(['ACME', 'Q1'])
assert len(results) > 0, 'tag lookup failed'
print('tag lookup: OK')
"
```

---

## 问题二：Memory CANDIDATE 只能 assist 的设计再评估

### 问题描述

`v2/memory/store.py` lines 123-125：CANDIDATE 状态的 memory 在 `lookup()` 中被找到，但 replay_class 被强制降为 ASSIST。只有 COMMITTED 的 memory 才能 step-skip。

COMMITTED 条件（lines 66）：`quality_floor_pass AND answer_adopted` 都为 True。

### 分析

当前设计是保守的但有意为之。把门槛降为只要 `quality_floor_pass` 就 COMMITTED 更激进，但在 continuous 场景中，如果 Round 1 的 `answer_adopted=False`（答案被拒绝），说明该 memory 的可靠性存疑，贸然让它 step-skip 下一轮有风险。

**实际影响**：skipped_steps=19 已经成立，说明现有条件足以触发 step-skip。问题是稳定性：如果某一轮边缘通过，memory 停在 CANDIDATE，下一轮就少了一次 step-skip 机会。

### 解决方案

不改变 COMMITTED 门槛，而是在 `lookup()` 中给 CANDIDATE 一个独立的 replay_class 升级路径：

```python
# v2/memory/store.py lookup() 方法修改
# 当前（lines 123-125）：
if ref.commit_status != MemoryCommitStatus.COMMITTED:
    replay_class = ReplayClass.ASSIST

# 修改后：CANDIDATE 只有质量通过的（validation_status=VERIFIED）才升到 validated_replay
if ref.commit_status != MemoryCommitStatus.COMMITTED:
    from v2.memory.models import MemoryValidationStatus
    if ref.validation_status == MemoryValidationStatus.VERIFIED:
        # 质量验证通过但答案未被采用 → 允许 validated_replay（不允许 exact_replay）
        replay_class = min(replay_class, ReplayClass.VALIDATED_REPLAY)
    else:
        replay_class = ReplayClass.ASSIST
```

这样：
- COMMITTED → 保持原有 replay_class（可以 exact_replay）
- CANDIDATE + VERIFIED（质量通过但答案未采用）→ 最多 validated_replay
- CANDIDATE + UNCHECKED → ASSIST（最保守）

### 验收测试

```bash
python -m v2.benchmark.live_runner \
  --suite statebus --benchmark-tier dev \
  --role-path-mode api --embedding-mode local \
  --replay-mode replay-ready \
  2>&1 | grep -E "skipped_steps|validated_replay|exact_replay|quality"
# 期望：skipped_steps ≥ 19，quality=20/20
```

---

## 问题三：DeterministicEmbeddingEncoder 会导致误命中

### 问题描述

`v2/memory/embedding.py` lines 44-68：16维 BoW hash，用词长加权。

"ACME 2026Q1 revenue" 和 "ACME 2025Q4 revenue" 的 embedding 差异只取决于 "2026Q1" vs "2025Q4" 这两个词在16个slot里的分布。高概率碰撞，导致 deterministic 模式下的 replay 命中率虚高。

**关键约束**：这只影响 `--embedding-mode deterministic` 的测试结果。所有 formal claim 基于 `--embedding-mode local`（真实768维），这个问题不影响正式声明。

### 解决方案

在报告和代码注释中加入明确说明，防止混淆：

```python
# v2/memory/embedding.py DeterministicEmbeddingEncoder 类文档
"""
16-dimensional bag-of-words hash embedding.
FOR TESTING ONLY — not suitable for production semantic retrieval.
All formal claims must use SentenceTransformerEmbeddingEncoder (embedding_mode=local).
"""
```

同时，升级到至少64维并改用 SimHash 风格的哈希：

```python
@dataclass(frozen=True)
class DeterministicEmbeddingEncoder:
    dims: int = 64  # 从16升到64，减少碰撞概率

    def encode(self, *, embedding_id: str, text: str) -> StructuredEmbedding:
        import hashlib
        counts = [0.0] * self.dims
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            # 用 token 内容的 hash，而非 token 长度加权
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            slot = h % self.dims
            counts[slot] += 1.0  # 词频，而非词长
        norm = sum(v * v for v in counts) ** 0.5 or 1.0
        vector = tuple(round(v / norm, 6) for v in counts)
        return StructuredEmbedding(embedding_id=embedding_id, vector=vector)
```

---

## 问题四：replay 三级触发条件需要可视化

### 问题描述

skipped_steps=19 是最有说服力的指标，但评委看不到每次 skip 的具体原因。需要一个可以在答辩中展示的输出。

### 解决方案

在 continuous family 的 manifest 输出中加入 per-step replay 记录：

```bash
# 查看现有 replay 证据
find /statebus/runs/full-experiment-20260703_124448 \
  -name "session_manifest.json" \
  | xargs grep -l "skipped\|replay" \
  | head -5 \
  | xargs -I{} python3 -c "
import json, sys
d = json.load(open('{}'))
steps = d.get('step_results', [])
for s in steps:
    if s.get('skipped') or s.get('replay_class'):
        print(f'  step={s[\"step_id\"]} class={s.get(\"replay_class\",\"run\")} skipped={s.get(\"skipped\",False)}')
"
```

**答辩展示脚本**（放在 `scripts/show_replay_evidence.py`）：

```python
#!/usr/bin/env python3
"""展示 continuous family 的 replay 证据，用于答辩演示"""
import json, pathlib, sys

def show_replay_evidence(runs_dir: str, family_id: str):
    runs_path = pathlib.Path(runs_dir)
    print(f"\n=== Replay Evidence: {family_id} ===\n")
    print(f"{'Round':<8} {'Task':<30} {'Reuse Class':<20} {'Skipped':<10} {'Tokens':<10}")
    print("-" * 80)

    total_skipped = 0
    for manifest in sorted(runs_path.rglob("session_manifest.json")):
        d = json.loads(manifest.read_text())
        if d.get("task_family") != family_id:
            continue
        rnd = d.get("round_number", "?")
        task_id = d.get("task_id", "?")[:28]
        reuse_class = d.get("reuse_class", "cold_start")
        skipped = d.get("skipped_step_count", 0)
        tokens = d.get("llm_total_tokens", "?")
        total_skipped += skipped
        print(f"{rnd:<8} {task_id:<30} {reuse_class:<20} {skipped:<10} {tokens:<10}")

    print("-" * 80)
    print(f"Total skipped steps: {total_skipped}")

if __name__ == "__main__":
    show_replay_evidence(
        sys.argv[1] if len(sys.argv) > 1 else "/statebus/runs/full-experiment-20260703_124448",
        sys.argv[2] if len(sys.argv) > 2 else "csv_correlation_replay_v1",
    )
```

---

## 问题五：v2 缺少 FAISS（与 v1 声明不一致）

### 问题描述

`v2/memory/store.py` 是 O(N) 线性扫描。当前 benchmark 规模（几十条 memory）无性能问题，但声明"SQLite + FAISS"与实际不符。

### 解决方案

v2 中加入 FAISS 可选后端：

```python
# v2/memory/store.py：可选 FAISS 后端
try:
    import faiss as _faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False

@dataclass
class FaissMemoryIndex:
    """FAISS-backed memory index for large-scale retrieval"""
    dim: int = 768
    _index: object = field(default=None, init=False)
    _id_map: dict[int, str] = field(default_factory=dict)  # faiss_idx → memory_id
    _next_id: int = field(default=0, init=False)

    def build(self, embeddings: dict[str, StructuredEmbedding]) -> None:
        if not _HAS_FAISS:
            raise ImportError("faiss-cpu not installed")
        import numpy as np
        self._index = _faiss.IndexFlatIP(self.dim)  # Inner product (for normalized vectors)
        vectors = []
        for memory_id, emb in embeddings.items():
            self._id_map[self._next_id] = memory_id
            vectors.append(list(emb.vector))
            self._next_id += 1
        mat = np.array(vectors, dtype="float32")
        self._index.add(mat)

    def search(self, query: StructuredEmbedding, k: int = 5) -> list[tuple[str, float]]:
        import numpy as np
        q = np.array([list(query.vector)], dtype="float32")
        distances, indices = self._index.search(q, k)
        return [(self._id_map[int(i)], float(d)) for d, i in zip(distances[0], indices[0]) if i >= 0]
```

在 `MemoryIndexStore.lookup()` 中，如果 FAISS 已初始化，用 FAISS 替代线性扫描。

### 验收测试

```bash
python -c "
from v2.memory.store import MemoryIndexStore
store = MemoryIndexStore()
# 验证 faiss 可用时自动启用
print('FAISS available:', store._try_build_faiss_index())
"
```
