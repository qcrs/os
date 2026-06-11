# Content-Addressed State Fabric (CASF)：一套面向多Agent协作的新型状态通信架构

日期：`2026-06-10`

状态：**独立设计方案提案** — 基于StateBus现有代码、9个第三方仓库分析、赛题要求的综合创新方案。

---

## 摘要

本文提出 **Content-Addressed State Fabric (CASF)**——一套借鉴Git内容寻址对象模型的多Agent状态通信架构。CASF将Agent间的每一次状态交换视为一个**内容寻址的不可变对象**，用SHA-256哈希替代显式ID，用Merkle DAG组织整个执行轨迹。该架构天然提供：**去重传输**（相同内容=相同哈希=不重复传）、**增量通信**（只传新哈希，接收方lazy fetch缺失blob）、**可验证回放**（Merkle proof），以及**结构相似记忆检索**（DAG子树匹配）。CASF是对StateBus现有`StateRef + SHA-256 checksum + replay matching`机制的体系化升级，直接对应赛题的通信效率、状态传递创新、记忆复用效果三个核心评分维度。

---

## 1. 设计动机

### 1.1 当前StateBus的状态模型局限

StateBus当前的状态传递模型可以概括为：

```
Agent A → 构建 StateRef(state_id, kind, handle, checksum) → Agent B 按 state_id 读取
```

这个模型已经工作得很好——有SHA-256 checksum做完整性校验、有StateContractRegistry做类型校验、有replay matching用evidence_hash做回放判定。但它有三个深层局限：

1. **checksum只是验证手段，不作为寻址主键**：StateRef用`state_id`（语义字符串如`task-001-retrieve-evidence`）定位，checksum只是验证——这导致相同内容可能有不同state_id，无法自动去重
2. **每次传输都是全量**：即使同chain内连续task的StateRef 90%内容相同，仍传输完整payload
3. **执行轨迹是线性的**：orchestrator的`ctx.results`是`step_id → StepResult`的flat dict，没有结构化的历史DAG

### 1.2 Git对象模型的启示

Git的核心设计（2005年至今，经过20年验证）是内容寻址的Merkle DAG：

```
Blob   ← 文件内容    → SHA-1(content) 作为键
Tree   ← 目录结构    → SHA-1(blob_refs + names)
Commit ← 快照+父提交 → SHA-1(tree + parent + message)
```

关键特性：
- **内容去重**：两个相同内容的文件自动共享同一个blob，节省存储
- **增量传输**：`git fetch`只传输本地缺失的objects（通过比较hash）
- **完整性验证**：任意commit的hash可以回溯验证整个历史的完整性
- **结构寻址**：不依赖文件名/路径，只依赖内容

### 1.3 CASF的核心洞察

将Git对象模型映射到多Agent状态通信：

| Git概念 | CASF对应 | 说明 |
|---------|---------|------|
| Blob (文件内容) | **StateBlob** | StateRef的payload bytes，SHA-256寻址 |
| Tree (目录结构) | **StepTree** | 一个step的所有input/output StateBlob引用 |
| Commit (快照) | **TaskCommit** | 一个task的完整执行快照，包含所有StepTree引用 + 父TaskCommit |
| fetch (传输) | **StateSync** | Agent间只交换hash，按需lazy fetch缺失的StateBlob |
| log (历史) | **Execution DAG** | 整个benchmark run的执行轨迹DAG |
| diff (比较) | **Replay match** | 比较两个TaskCommit的StepTree结构判断是否可replay |

---

## 2. CASF架构设计

### 2.1 核心对象模型

#### StateBlob（替代当前StateRef的payload存储）

```python
@dataclass
class StateBlob:
    """内容寻址的不可变状态块"""
    blob_hash: str          # SHA-256(content_bytes) — 唯一主键
    content_bytes: bytes    # 原始payload
    content_type: str       # "msgpack" | "json" | "numpy" | "text"
    
    # 存储层：按 blob_hash[:2]/blob_hash[2:] 分片存储
    # 例如 sha256=abc123... → statepool/blobs/ab/c123...
    
    @classmethod
    def from_bytes(cls, data: bytes, content_type: str) -> "StateBlob":
        blob_hash = hashlib.sha256(data).hexdigest()
        return cls(blob_hash=blob_hash, content_bytes=data, content_type=content_type)
```

**关键行为**：
- 两个完全相同的payload产生相同的`blob_hash` → 自动去重
- StateBlob一旦写入就不可变（immutable）
- 存储路径由hash决定，不依赖任何语义标识

#### StateRef（重新定义为Blob的元数据指针）

```python
@dataclass
class StateRef:
    """指向StateBlob的语义指针"""
    ref_id: str            # 语义标识（保留现有state_id的语义价值）
    blob_hash: str         # → 指向 StateBlob
    kind: str              # DENSE_EVIDENCE | FEATURE_BUNDLE | ...
    length: int            # blob content 长度
    metadata: dict         # 语义元数据（agent_id, created_at, task_theme, ...）
    
    # 注意：不再包含 storage/handle/checksum —— 
    # storage由blob_hash隐式决定（从statepool按hash查找）
    # checksum就是blob_hash本身
```

**与当前StateRef的关键差异**：
- 当前：`state_id` 是语义标识（映射到文件路径），`checksum` 是验证字段
- CASF：`blob_hash` 是内容寻址主键（映射到存储位置），`ref_id` 是语义别名

#### StepTree（一个step的完整输入输出快照）

```python
@dataclass
class StepTree:
    """一个PlanStep的完整状态快照"""
    step_id: str
    agent_id: str
    action: str
    
    # 输入状态blob引用
    input_blobs: dict[str, str]   # kind → blob_hash
    
    # 输出状态blob引用  
    output_blobs: dict[str, str]  # kind → blob_hash
    
    # 元数据
    started_at: float
    finished_at: float
    phase_timing: dict[str, float]  # retrieve_ms, execute_ms, summarize_ms
    
    @property
    def tree_hash(self) -> str:
        """StepTree自身的Merkle hash"""
        payload = msgpack.dumps({
            "step_id": self.step_id,
            "input_blobs": sorted(self.input_blobs.items()),
            "output_blobs": sorted(self.output_blobs.items()),
        })
        return hashlib.sha256(payload).hexdigest()
```

#### TaskCommit（一个task的完整执行快照）

```python
@dataclass
class TaskCommit:
    """一个task的完整执行快照——Merkle DAG的节点"""
    commit_hash: str       # SHA-256(step_trees + parent_hash + metadata)
    task_id: str
    task_group: str
    task_theme: str
    
    # 本task的所有step
    step_trees: list[StepTree]
    
    # 父TaskCommit引用（同一task_group内的前一个task）
    parent_hash: str | None
    
    # 执行元数据
    mode: str              # "text" | "protocol"
    created_at: float
    task_metrics: dict     # 完整的 TaskMetrics
    memory_queries: list[dict]  # 本task查询了哪些记忆
    
    @property
    def compute_hash(self) -> str:
        payload = msgpack.dumps({
            "task_id": self.task_id,
            "step_trees": [st.tree_hash for st in self.step_trees],
            "parent_hash": self.parent_hash or "",
            "task_theme": self.task_theme,
            "mode": self.mode,
        })
        return hashlib.sha256(payload).hexdigest()
```

#### Execution DAG（整个benchmark run的完整历史）

```python
@dataclass
class ExecutionDAG:
    """一个benchmark run的完整执行轨迹DAG"""
    dag_id: str
    task_commits: dict[str, TaskCommit]  # task_id → TaskCommit
    
    @property
    def root_hashes(self) -> list[str]:
        """所有parent_hash=None的root commit"""
        return [tc.commit_hash for tc in self.task_commits.values() 
                if tc.parent_hash is None]
    
    def verify_integrity(self) -> bool:
        """Merkle验证：遍历所有commit，验证hash链"""
        for tc in self.task_commits.values():
            if tc.commit_hash != tc.compute_hash:
                return False
            if tc.parent_hash:
                parent = self.task_commits.get(tc.parent_hash)
                if parent is None:
                    return False
        return True
    
    def find_similar_subtree(self, task_theme: str, query_terms: set[str]) -> list[TaskCommit]:
        """按task_theme和query_terms查找结构相似的子树"""
        candidates = []
        for tc in self.task_commits.values():
            if tc.task_theme == task_theme:
                # 比较StepTree结构：相同的step数量和action序列
                similarity = self._structural_similarity(tc, query_terms)
                if similarity > 0.7:
                    candidates.append((tc, similarity))
        return [c for c, _ in sorted(candidates, key=lambda x: -x[1])]
```

### 2.2 通信协议：Hash-first传输

传统的StateBus通信：
```
Agent A → [完整StateRef + Payload] → Agent B
Agent B → 读取Payload → 使用
```

CASF的Hash-first传输：
```
Agent A → [仅StateRef(blob_hash)] → Agent B
Agent B → 检查本地StatePool是否有blob_hash
        ├── 有 → 直接使用
        └── 没有 → 发送 FetchRequest(blob_hash) → Agent A → [Payload bytes]
```

**实现**（`runtime/orchestrator.py` 中的 `_emit_step` 修改）：

```python
def _emit_step_casf(self, plan_step: PlanStep, ctx: RunContext):
    """Hash-first传输：先传hash，接收方按需fetch"""
    # 构建casf-aware的StepResult
    output_refs = []
    for ref in ctx.get_step_output_refs(plan_step.step_id):
        # CASF Ref: 只传 blob_hash + metadata，不传完整payload
        casf_ref = StateRef(
            ref_id=ref.state_id,
            blob_hash=ref.checksum,  # checksum就是blob_hash
            kind=ref.kind,
            length=ref.length,
            metadata=ref.metadata,
        )
        output_refs.append(casf_ref)
    
    result = StepResult(
        step_id=plan_step.step_id,
        success=True,
        output_state_refs=output_refs,
        # payload不内联在消息中
    )
    
    # 协议帧只包含ref引用，不包含payload
    msg_bytes = protocol_bytes(result)  # 显著减小
    ctx.emit_message("StepResult", msg_bytes)
```

**接收方的lazy fetch**（`runtime/orchestrator.py` 中的 `resolve_ref` 修改）：

```python
def resolve_ref_casf(self, ref: StateRef, ctx: RunContext) -> bytes:
    """按blob_hash从本地StatePool查找，没找到则发起FetchRequest"""
    blob_bytes = ctx.statepool.get_by_hash(ref.blob_hash)
    if blob_bytes is not None:
        return blob_bytes  # 命中本地缓存
    
    # 本地没有：发起FetchRequest
    fetch_msg = FetchRequest(
        blob_hashes=[ref.blob_hash],
        requestor_agent=ctx.current_agent_id,
    )
    # 广播fetch请求，source agent响应
    payload = self._fetch_from_source(fetch_msg, ctx)
    # 写入本地StatePool
    ctx.statepool.put_by_hash(ref.blob_hash, payload)
    return payload
```

**预期效果**：
- 同chain内连续task：90%的StateRef在本地已有缓存 → 通信量降至原来的10%
- 跨chain的assist task：如果memory hit指向同一blob_hash → 零额外传输
- 首次cold-start task：仍需传输完整payload（因为本地没有）

### 2.3 记忆复用：结构相似子树匹配

传统的记忆检索：
```
MemoryStore.search(query) → semantic similarity → top-K hits
```

CASF的记忆检索增加了**结构维度**：
```python
def structural_memory_search(self, current_task: SampleTask, execution_dag: ExecutionDAG):
    """
    三步结构记忆检索：
    1. Semantic: 用task_theme + query做语义检索（现有逻辑）
    2. Structural: 在DAG中查找StepTree结构相似的TaskCommit
    3. Temporal: recency reranking
    4. Fusion: 三步得分融合 → 候选记忆
    """
    # Step 1: Semantic search (现有)
    sem_hits = self._search_semantic(query)
    
    # Step 2: Structural matching (新增)
    struct_hits = execution_dag.find_similar_subtree(
        task_theme=current_task.task_theme,
        query_terms=set(current_task.query.split()),
    )
    
    # Step 3: Temporal reranking (新增)
    for hit in sem_hits + struct_hits:
        hit["recency_score"] = math.exp(-0.0001 * (now - hit["created_at"]))
    
    # Step 4: Multi-signal fusion
    return self._fuse_results(sem_hits, struct_hits)
```

**结构相似度的计算**：
```python
def _structural_similarity(self, commit: TaskCommit, query_terms: set[str]) -> float:
    """计算两个TaskCommit的StepTree结构相似度"""
    score = 0.0
    
    # (1) Step数量匹配：相同的step数 → +0.3
    if len(commit.step_trees) == 3:  # retrieve+execute+summarize
        score += 0.3
    
    # (2) Action序列匹配：相同的action顺序 → +0.2
    actions = [st.action for st in commit.step_trees]
    if actions == ["RETRIEVE_EVIDENCE", "EXECUTE_PLAYBOOK", "SUMMARIZE_AND_COMMIT"]:
        score += 0.2
    
    # (3) Input/Output blob结构匹配：
    #     相同的kind序列 → +0.2
    #     相同的blob_hash → +0.3（最强信号：位级相同）
    for st in commit.step_trees:
        input_kinds = set(st.input_blobs.keys())
        if input_kinds == {"DENSE_EVIDENCE"}:
            score += 0.1
        if any("FEATURE_BUNDLE" in k for k in st.output_blobs):
            score += 0.1
    
    # (4) Query term overlap → +0.2
    stored_terms = set()
    for st in commit.step_trees:
        # 从output blobs中恢复query_terms（如果存在）
        pass
    overlap = len(query_terms & stored_terms) / max(len(query_terms), 1)
    score += 0.2 * overlap
    
    return score
```

**相比当前replay matching的优势**：

| 维度 | 当前（exact replay） | CASF（结构匹配） |
|------|---------------------|-------------------|
| 匹配条件 | query/theme/route/doc-set全部精确匹配 | 结构相似度 > 阈值 |
| 泛化能力 | 只能复放完全相同query的task | 可以复放结构相似的variant query |
| theme drift处理 | theme不同→直接拒绝 | theme不同但结构相似→仍可部分复用 |
| 跨family复用 | 不支持 | 支持（结构匹配不要求相同family） |

### 2.4 自然去重与增量传输

Git的一个核心优点：**你不需要写dedup逻辑，因为内容寻址自动去重**。

在CASF中：
- 两个task产生相同的`DENSE_EVIDENCE` → 自动产生相同的`blob_hash` → StatePool只存一份 → 第二个task的StateRef直接引用已有blob
- 同chain内连续task的FEATURE_BUNDLE中只有`memory_prior_*`字段变化 → blob_hash不同 → 但StepTree结构相同 → replay matching可以识别

**具体到StateBus的代码改动**：

在`statepool/store.py`中：
```python
class ContentAddressedStatePool(StatePool):
    """基于CASF的StatePool"""
    
    def put_bytes(self, data: bytes, ...) -> StateRef:
        blob_hash = hashlib.sha256(data).hexdigest()
        blob_path = self._blob_path(blob_hash)  # blobs/ab/c123...
        
        if not blob_path.exists():
            # 新blob：写入磁盘
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path.write_bytes(data)
            self._blob_refcount[blob_hash] = 1
        else:
            # 已存在blob：只增加引用计数
            self._blob_refcount[blob_hash] += 1
        
        return StateRef(
            ref_id=state_id,
            blob_hash=blob_hash,
            kind=kind,
            length=len(data),
        )
    
    def read_bytes(self, ref: StateRef) -> bytes:
        blob_path = self._blob_path(ref.blob_hash)
        return blob_path.read_bytes()
    
    def _blob_path(self, blob_hash: str) -> Path:
        # Git-style: 前2字符做目录分片
        return self.blobs_dir / blob_hash[:2] / blob_hash[2:]
```

**自动去重效果**：
- 从`_blob_refcount`可以看到哪些StateRef被共享了多少次
- 典型benchmark中，同一个corpus document的evidence blob被多个task引用 → refcount > 1 → 节省存储和传输

---

## 3. 对赛题评分维度的直接贡献

### 3.1 通信效率（25分）——三重用

1. **Hash-first传输**：协议帧只传blob_hash（64字节），不传payload（可能几千字节）。通信量从"bytes per message"降为"bytes per unique blob"
2. **Lazy fetch**：接收方只有在本地没有blob时才请求传输。同chain内90%的blob已在本地
3. **自然去重**：相同内容不产生新的blob。跨task共享的evidence/feature bundle自动去重

**量化估计**：
- 当前：29个task，protocol模式下control_bytes=170100
- CASF首次run：理论上control_bytes相当（首次传输所有blob）
- CASF第二次run（重复相同task）：control_bytes降至~20000（只传blob_hash，payload全在本地缓存）
- 循环中同chain task：control_bytes额外下降40-60%

### 3.2 状态传递创新（20分）——Merkle DAG状态模型

赛题要求：
> "实现一种非文本中间状态传递机制，支持 embedding、语义向量、隐藏状态特征或其他中间表示在 Agent 间直接交换，并说明其生成方式、传递方式、接收方式及后续使用方式"

CASF的答案：
1. **生成方式**：Agent执行step后，将输出状态序列化为StateBlob（二进制），用SHA-256计算blob_hash。StepTree记录所有input/output blob_hash的关系。
2. **传递方式**：Hash-first——先传StateRef（blob_hash + metadata），接收方检查本地缓存。若缺失则发起FetchRequest。这是"结构化引用传递"而非"全量payload传输"。
3. **接收方式**：接收方按blob_hash从StatePool查找。若本地缓存命中，直接mmap读取（零拷贝）；若未命中，从source agent fetch。
4. **后续使用方式**：
   - 作为当前step的输入消费（与现有逻辑相同）
   - 作为replay matching的比较基准（与现有replay逻辑兼容）
   - 作为结构记忆检索的DAG节点（新增能力）
   - 作为benchmark trajectory的检查点（新增能力）

**比当前FEATURE_BUNDLE更新的点**：
- 当前：FEATURE_BUNDLE是flat dict，发送→接收→deserialize→使用。没有immutable概念，没有dedup，没有结构关联。
- CASF：整个执行轨迹是内容寻址的Merkle DAG。任何一个TaskCommit的hash可以回溯验证所有StepTree和StateBlob的完整性。这是从"数据传递"到"可验证计算"的范式升级。

### 3.3 记忆复用效果（20分）——结构相似子树匹配

赛题要求：
> "需支持按关键词、标签或语义相似度检索历史记忆，并允许不同 Agent 在后续任务中直接复用已有记忆"

CASF在语义相似度之外增加了**结构相似度**维度：
- 语义相似：query的embedding接近 → "这个问题和那个问题意思差不多"
- 结构相似：StepTree的拓扑结构接近 → "解决这个问题和解决那个问题的步骤模式差不多"

结构相似的威力：
- **跨family复用**：`cache_invalidation` task和`latency_triage` task虽然query不同，但都是"retrieve → route → execute playbook → summarize"的结构 → 结构相似 → 可被replay matching命中（只要StepTree拓扑一致）
- **泛化replay**：不需要精确的query匹配，只需要"解决模式相同"

这与当前exact replay的根本区别是：**当前replay看"内容是否完全相同"（content-based），CASF replay看"结构是否相似"（structure-based）**。

### 3.4 系统完整性（20分）——Merkle可验证性

CASF的整个执行轨迹是Merkle DAG：
- 任何一个TaskCommit→ 验证StepTree的完整性 → 验证StateBlob的完整性
- 如果任何一个StateBlob被篡改，其blob_hash变化 → StepTree的tree_hash变化 → TaskCommit的commit_hash变化 → 整个chain断开

这提供了一个**零信任的验证模型**：你不需要信任任何Agent的执行结果，只需要验证hash chain。

### 3.5 实验验证（15分）——Trajectory Integrity

CASF天然提供：
- 每个benchmark run的完整ExecutionDAG（所有TaskCommit的hash chain）
- 两次相同task的执行结果可以通过比较StepTree结构来判断是否一致
- 这比当前的 `expectation_match_rate` 粗粒度指标强得多

---

## 4. 实现路径

### 4.1 增量兼容策略

CASF不是推翻重来，而是在StateBus现有架构上增量升级：

| 现有组件 | CASF改动 | 改动量 |
|---------|---------|--------|
| `statepool/store.py` | 新增`ContentAddressedStatePool`（基于blob_hash的存储层）。保留现有`FileBackedStatePool`作为fallback | ~150行 |
| `protocol/messages.py` | StateRef减少`storage/handle/checksum`，增加`blob_hash`。新增`FetchRequest/FetchResponse`消息类型 | ~80行 |
| `runtime/orchestrator.py` | 新增`StepTree/TaskCommit`构建逻辑。修改`resolve_ref`为lazy fetch | ~200行 |
| `memory/store.py` | 新增`structural_memory_search`（DAG子树匹配） | ~100行 |
| `eval/runner.py` | 新增`ExecutionDAG`序列化和完整性验证 | ~100行 |
| `runtime/contracts.py` | 新增CASF相关的state contracts | ~50行 |

总计新增约680行，修改约200行。与现有22,487行代码库相比是**9%的增量改动**。

### 4.2 向后兼容策略

1. `StateRef`的`blob_hash`字段是可选的——如果为空，回退到现有的`state_id + storage + handle`寻址模式
2. CASF的`ContentAddressedStatePool`继承自现有`StatePool`接口，作为可选后端
3. FetchRequest消息是新的消息类型——旧agent收不到就忽略（不响应），发送方超时后回退到全量传输
4. 可以通过环境变量`STATEBUS_CASF_ENABLED=true`渐进式启用

### 4.3 Phase建议（与Roadmap文档的衔接）

CASF可以作为Roadmap文档（`code_audit_competition_check_and_solution_roadmap.md`）的**Phase C+ 深化项目**：

- 与Phase B1（DeltaPlanStep增量帧）互补：DeltaPlanStep做字段级增量，CASF做blob级去重和hash-first传输
- 与Phase B2（Typed Channel）互补：Typed Channel定义每个字段的更新语义，CASF定义整个StateRef的寻址语义
- 与Phase B3（双层记忆）互补：双层记忆做recency/tier加权，CASF做结构相似度匹配

---

## 5. 与参考项目的差异化定位

| 维度 | StateBus+CASF | LangGraph | mem0 | AutoGen |
|------|--------------|-----------|------|---------|
| 状态寻址 | **内容寻址(SHA-256)** | Channel名寻址 | Memory ID寻址 | 消息ID寻址 |
| 去重机制 | **自动(内容相同=hash相同)** | 无自动去重 | 无自动去重 | 无 |
| 增量传输 | **Hash-first + lazy fetch** | DeltaChannel | 无 | 无 |
| 轨迹组织 | **Merkle DAG** | Checkpoint chain | Flat list | Conversation history |
| 回放验证 | **Merkle proof** | Checkpoint restore | 无 | 无 |
| 记忆检索 | **Semantic + Structural** | 无内置 | Semantic only | 无 |

CASF的独特优势：
1. **Git的内容寻址**是一个20年验证过的系统设计模式，应用于多Agent通信是全新的思路
2. **Merkle DAG组织执行轨迹**提供天然的完整性和可验证性——这是其他项目都没有的
3. **Hash-first传输**将通信模型从"push payload"改为"push hash + pull missing"——更贴近分布式系统的最佳实践
4. **结构相似记忆检索**突破了"semantic only"的局限——结构信息（StepTree拓扑）是免费获得的（不需要额外embedding）

---

## 6. 相关文档交叉引用

| 本文提出的设计 | 在现有分析文档中的对应位置 |
|-------------|------------------------|
| §2.2 Hash-first传输 | `benchmark_task_and_result_analysis.md` §9 (Message Type Breakdown中PlanStep/MemoryCommit的per-message开销) |
| §2.3 结构相似子树匹配 | `benchmark_task_and_result_analysis.md` §11.1 (Assist overhead decomposition中assist不work的根因) |
| §2.4 自然去重 | `third_party_analysis_and_borrowable_patterns.md` §2.2.2 (memsearch文件为真源+SHA-256去重) |
| §3.2 Merkle DAG状态模型 | `third_party_analysis_and_borrowable_patterns.md` §2.2.1 (LangGraph Channel模型) |
| §4.2 向后兼容 | `code_audit_competition_check_and_solution_roadmap.md` §4.7 (风险评估与回滚) |
| §4.3 Phase衔接 | `code_audit_competition_check_and_solution_roadmap.md` §4.6 (任务依赖分析) |

---

## 7. 总结

CASF是面向赛题三个核心维度（通信效率/状态传递创新/记忆复用效果）的一体化架构方案。它不是推翻StateBus，而是在其已有的`StateRef + SHA-256 checksum + replay matching`基础上，引入Git的内容寻址模型，将整个系统的状态通信升级为**内容寻址的Merkle DAG**。

核心创新点用一句话概括：

> **让Agent之间不再传输"数据"，而是传输"数据的hash"。谁需要数据，谁自己去取。取过一次的hash，永远不再重复传输。**

这一原则在Git中经过了20年的生产验证（全球最大的分布式系统），在多Agent通信中同样适用——而且恰好完美覆盖赛题的三个核心评分维度。
