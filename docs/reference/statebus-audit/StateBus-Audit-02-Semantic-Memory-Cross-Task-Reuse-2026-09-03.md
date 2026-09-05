# StateBus 全面系统审计 · Round 02
# Semantic Shared Memory / Cross-Task Reuse 深度源码审计

> **项目**：StateBus / `qcrs/os`  
> **审计日期**：2026-09-03  
> **GitHub 基线**：`master` → `8bfc6464ec236c0e121911095fc283129b0e7696`  
> **本轮主题**：长期语义记忆、跨任务复用、Hybrid Retrieval、Replay、Memory Commit、Consumption Evidence  
> **不属于本轮的 Shared Memory**：POSIX SHM / memfd / mmap 已在 Round 01 审计。本文的 “Shared Memory” 指赛题意义上的 **Agent 共享语义记忆 / 历史经验复用**。
>
> 本文从三个标准同时审视当前实现：
>
> 1. **赛题要求**：共享记忆是否真实减少重复工作、是否能跨 Agent / 跨 Task 使用、是否可验证；
> 2. **系统正确性**：Memory 的写入、检索、兼容、重放、失效、权限和生命周期是否可靠；
> 3. **外部可信度**：能否在 LongMemEval-V2 等公开 Benchmark 上证明不是固定任务 scaffolding。

---

# 0. Executive Summary

本轮最重要的判断不是：

> “StateBus 的 Memory 太简单，需要换一个向量数据库。”

而是：

> **StateBus 已经有一条真实的 `Retrieve → Compatibility Gate → Role Input → Verified Recipe Reuse → Current-Input Recompute → Validator → Commit` 记忆闭环；真正的问题是它目前把 “语义记忆、执行经验、精确缓存” 混在一个 Memory 平面里，而且 Memory 查询仍然被绑定在 Semantic Retriever 和 CanonicalTaskSpec 上。**

当前主链大致是：

```text
Retriever
   │
   ├─ text query
   ├─ tags
   └─ query embedding
         │
         ▼
MemoryIndexStore.lookup_hybrid()
         │
         ├─ SQLite FTS
         ├─ tag overlap
         └─ vector similarity / FAISS
         │
         ▼
        RRF
         │
         ▼
MemoryCompatibilityDecision
         │
         ├─ ASSIST
         ├─ VALIDATED_REPLAY
         ├─ EXACT_REPLAY
         └─ DISALLOWED
         │
         ▼
memory_inputs_for_step()
         │
         ├─ Executor
         └─ Summarizer / downstream role
         │
         ▼
Verified recipe reuse
         │
         ▼
CURRENT INPUT recomputation
         │
         ▼
Quality Validator
         │
         ▼
Verified Artifact
         │
         ▼
AdaptiveMainline._commit_verified_memory()
```

这已经不是假的 “vector DB demo”。

尤其：

```text
VALIDATED_REPLAY
```

当前并不是：

```text
拿历史答案直接复制
```

而是：

```text
拿历史 verified execution recipe
↓
对当前输入重新执行
↓
重新过 Runtime Validator
```

这是当前 Memory 子系统最有价值的设计。

但本轮也发现一组必须在比赛前收敛的问题。

---

# 1. Round 02 P0 结论

建议先冻结以下 P0。

## P0-1：Memory Plane 被绑在 Semantic Retrieval 上

当前 `MemoryQuery` 不是一个独立 Runtime stage。

它是在：

```text
retrieval semantic state
→ cross-process semantic selection
→ query_embedding_from_dense_state()
```

之后才构造。

也就是说：

```text
没有 semantic retrieval
→ 没有 MemoryQuery
→ 没有 MemoryMatch
→ 通常也无法 Memory Commit
```

这与：

```text
Memory = Runtime 独立能力平面
```

不一致。

更严重的是：

```text
Planner
```

天然无法在 Planning 阶段利用历史：

```text
strategy
route hint
previous failure
workflow knowledge
```

因为 Memory 查询发生得太晚。

---

## P0-2：当前只有 “每 Task 一个 MemoryQuery”

源码主动拒绝：

```text
hybrid_memory_query_already_issued_for_task
```

所以现在无法自然表达：

```text
Planner query:
  workflow / strategy memories

Retriever query:
  evidence memories

Executor query:
  verified procedure memories

Summarizer query:
  reporting / claim memories
```

当前实际上是：

```text
Retriever 产生一条 query
↓
同一批 Memory Match
↓
fan-out 给后续不同 Role
```

。

这限制了真正的 Agent Shared Memory。

---

## P0-3：Exact Replay 在两套系统里的语义不同

目前至少存在：

```text
A. runtime/replay.py
B. Adaptive Memory + adaptive_dispatcher.py
```

两套 replay。

### `runtime/replay.py`

`EXACT_REPLAY` 的语义接近真正：

```text
Exact Artifact Cache
```

Key 包含：

```text
CanonicalTaskSpec
input artifact hashes
Runtime compatibility signature
code template version
extractor version
output contract
```

。

### Adaptive Memory

即使 Memory 被判为：

```text
EXACT_REPLAY
```

`_validated_recipe()` 仍然只是取：

```text
execution_recipe
```

。

DSL：

```text
recipe
↓
current input
↓
TransformInterpreter
↓
recompute
```

CodeAct：

```text
stored Python source
↓
current input
↓
sandbox execute again
↓
validator
```

。

所以这里更准确的名字应该是：

```text
VERIFIED_PROCEDURE_REUSE
```

而不是 exact artifact replay。

这是一个必须拆开的语义边界。

---

## P0-4：Compatibility Policy 已经发生双实现漂移

Adaptive `MemoryIndexStore._compatibility_decision()`：

```text
task_family
intent_op
required_outputs
```

用于 validated contract compatibility。

而 `runtime/replay.py::validated_replay_contract_compatible()` 还检查：

```text
required_tools
argument schema shape
```

。

即：

```text
Adaptive Memory Policy
≠
History Replay Policy
```

。

这是典型的：

# Policy Drift

如果继续维护两套：

```text
同一个历史 recipe
```

可能在 A 路径：

```text
VALIDATED_REPLAY
```

在 B 路径：

```text
ASSIST / reject
```

。

必须统一。

---

## P0-5：Memory Actual-Use 指标存在过度 claim

当前：

```text
memory input 被注入 role input
```

时，`MemoryConsumptionRecord.behavioral_effect` 自动写：

```text
role_input_augmented
```

。

然后：

```text
memory_behavioral_effect_count
```

统计：

```text
behavioral_effect != "unchanged"
```

。

所以：

```text
Memory 被放进 prompt/input
```

就会变成：

```text
Memory 改变了行为
```

。

这是不成立的。

必须区分：

```text
retrieved
visible
injected
read
used
decision_changed
work_skipped
quality_improved
```

。

赛题答辩尤其不能把：

```text
input augmented
```

说成：

```text
memory saved work
```

。

---

## P0-6：FAISS 全局索引存在真实映射 / 多 Encoder 风险

当前 `_build_faiss_index()`：

```python
for i, (emb_id, emb) in enumerate(self.embeddings.items()):
    if not emb.vector:
        continue

    vecs.append(...)
    id_map[i] = emb_id
```

如果：

```text
embedding 0 = empty vector
embedding 1 = valid
```

则：

```text
vecs row 0 = embedding 1
id_map[1] = embedding 1
```

FAISS search 返回：

```text
idx = 0
```

却找不到：

```text
id_map[0]
```

。

这是一个实质性的 row-ID bug。

同时全局 FAISS index 把所有：

```text
embedding encoding
dims
```

混在一起构建。

如果未来同时存在：

```text
Qwen3 Embedding 1024d
另一版本 768d
deterministic 16d
```

：

```text
np.array(vecs)
```

可能直接 ragged / fail；

即使 dimension 相同但 encoder 不同：

```text
同一个向量空间假设也不成立
```

。

索引必须按：

```text
EncoderIdentity
=
(model digest, revision, pooling, normalization, dims)
```

分 shard。

---

## P0-7：Memory 缺少 Namespace / Authority Scope

当前 MemoryRef 有：

```text
source_task_id
source_agent
tags
task_theme
source_role_path
```

但没有真正：

```text
namespace
tenant
project
user
agent visibility
role visibility
capability visibility
sensitivity
authority
```

。

经过 Compatibility Gate 的 Memory：

```text
_memory_inputs_for_step()
```

会被构造成任意下游 Step 的 role input。

当前缺少：

```text
这条 Memory 是否允许被这个 Role 看见？
```

以及：

```text
这条 Memory 是否有权限影响执行？
```

两层。

这既是 correctness，也是未来 Memory Poisoning 防御的基础。

---

## P0-8：Memory 持久化缺少事务型真源

现在同时有：

```text
embedding_registry.json
commit_registry.json
memory_index.sqlite3
```

。

其中：

```text
JSON Registry
```

负责完整恢复；

SQLite 更像检索 index。

`_persist_commit()` 顺序：

```text
_index_commit()
→ SQLite COMMIT

再：
_read_registry()
_write_registry()
```

。

而 JSON 写入使用：

```text
path.write_text(...)
```

没有：

```text
temp
fsync
atomic rename
```

。

发生 crash 时：

```text
SQLite
≠
JSON Registry
```

是可能的。

另外：

```text
put_commit
```

可以用相同 `memory_id` 直接覆盖；

没有 immutable identity / compare-and-swap。

长期共享记忆不应该这样工作。

---

# 2. 当前 Memory 子系统应该怎样评价

准确的评价是：

```text
不是：
“只有一个简单向量库”

也不是：
“已经是通用 Agent Memory OS”
```

更接近：

# `Verified Experience / Recipe Reuse Prototype`

当前最成熟的是：

```text
previous successful execution
↓
retrieve by task similarity
↓
check Runtime + contract
↓
reuse executable recipe
↓
recompute current data
↓
revalidate
```

。

而：

```text
semantic facts
episodic history
route hints
agent profile
cross-role knowledge
conflict-aware evolving knowledge
```

虽然 `MemoryType` enum 已经预留，但主产品写入链还没有真正实现完整语义。

---

# 3. 赛题中的 Shared Memory 到底要证明什么

赛题强调：

```text
共享记忆
跨 Agent
跨连续任务
减少重复工作
```

所以不能只证明：

```text
MemoryIndexStore 中有历史对象
```

。

正式证据链应该是：

```text
Task N
↓
产生经验
↓
Runtime 验证
↓
Memory Write Admission
↓
长期 Memory Commit

Task N+K
↓
Memory Query
↓
候选召回
↓
Compatibility / Authority Gate
↓
实际 Consumer 使用
↓
减少生成 / 重算 / Tool 调用
OR 提升质量
↓
仍然通过当前任务 Validator
```

。

最关键的是最后两步：

```text
Benefit
+
Current-task correctness
```

。

---

# 4. 当前 Memory 数据模型审计

当前 `MemoryType`：

```text
EVIDENCE
OUTCOME
STRATEGY
STRATEGY_CACHE
SEMANTIC_EVIDENCE
NUMERIC_FACT
TEXT_CONTEXT
ROUTE_HINT
EXECUTION_ARTIFACT
VALIDATED_REPLAY
EXACT_REPLAY
```

表面上非常丰富。

但这些 enum 现在混了三个不同维度。

---

# 5. MemoryType 当前混合了“内容类型”和“复用模式”

例如：

```text
EVIDENCE
NUMERIC_FACT
TEXT_CONTEXT
```

是：

```text
what is stored
```

。

而：

```text
VALIDATED_REPLAY
EXACT_REPLAY
```

是：

```text
how it may be reused
```

。

这是 orthogonal dimensions。

例如一个：

```text
verified execution procedure
```

可以是：

```text
MemoryKind.PROCEDURAL
ReuseMode.VALIDATED
```

而不是：

```text
MemoryType.VALIDATED_REPLAY
```

。

---

# 6. 推荐 Memory Model v3

建议拆成：

```python
MemoryKind
```

：

```text
SEMANTIC
EPISODIC
PROCEDURAL
```

再细分：

```text
SEMANTIC
  ├─ FACT
  ├─ EVIDENCE_SUMMARY
  ├─ ENTITY_STATE
  └─ CONSTRAINT

EPISODIC
  ├─ TASK_OUTCOME
  ├─ FAILURE_EPISODE
  └─ SUCCESS_EPISODE

PROCEDURAL
  ├─ EXECUTION_RECIPE
  ├─ TOOL_WORKFLOW
  ├─ ROUTING_HINT
  └─ RECOVERY_PROCEDURE
```

。

单独：

```python
ReuseAuthority
```

：

```text
CONTEXT_ONLY
ASSIST
VERIFIED_PROCEDURE
```

。

而：

```text
EXACT artifact output
```

不要继续当 MemoryType。

---

# 7. Exact Replay 应拆成 Cache Plane

建议：

```text
Memory Plane
≠
Exact Artifact Cache
```

。

### Exact Artifact Cache

Key：

```text
TaskContractIdentity
+
InputLineage
+
RuntimeSignature
+
ProviderVersion
+
OutputContract
+
ValidatorVersion
```

Value：

```text
Verified Artifact
```

命中：

```text
可以恢复历史 output
```

。

### Procedural Memory

Key：

```text
task compatibility fingerprint
+
semantic / metadata retrieval
```

Value：

```text
verified recipe
workflow
code source
strategy
```

命中：

```text
必须 current-input re-execute
+
current validator
```

。

二者概念上完全不同。

---

# 8. 当前 `MemoryQuery` 的优点

它已经同时承载：

```text
query_text
tags
query_embedding
```

并附带：

```text
task/spec
memory policy
Runtime signature
output contract
lineage
schema
validator
```

。

这非常好。

它意味着：

```text
Retrieval Ranking
```

与：

```text
Replay Safety
```

至少已经在合同层分开。

---

# 9. 当前 Hybrid Retrieval 结构是合理的

目前：

```text
Keyword
Tag
Vector
↓
RRF
↓
Compatibility Gate
```

而不是：

```text
vector similarity
=
replay permission
```

。

这是重要优点。

高语义相似：

```text
只能发现候选
```

不能绕过：

```text
Runtime
contract
schema
validator
```

。

保留。

---

# 10. 为什么 RRF 比直接加 raw scores 更合理

当前三路：

```text
FTS BM25
tag overlap
cosine similarity
```

数值空间不同。

所以：

```text
0.91 cosine
+
4.7 BM25
```

没有数学意义。

RRF：

```text
1 / (k + rank)
```

只融合排序。

这一步是正确的。

---

# 11. 但当前 RRF 缺少 Relevance Gate

当前：

```text
vector #1
```

无论 cosine：

```text
0.92
```

还是：

```text
0.02
```

都获得：

```text
1 / (60 + 1)
```

。

如果其他 retrieval signal 为空：

```text
一个非常差的 vector match
```

仍可能进入 Memory Match。

Compatibility 只能回答：

```text
能不能安全复用
```

不能回答：

```text
这条 memory 和当前问题到底相关不相关
```

。

---

# 12. 推荐 Retrieval 两阶段 Gate

```text
Source-level relevance eligibility
↓
RRF
↓
Compatibility / Authority
```

。

例如：

```text
vector:
cosine >= threshold

keyword:
BM25 / lexical support >= threshold

entity:
shared entity count >= 1

tags:
exact scoped tag overlap
```

。

然后 RRF。

而不是：

```text
所有 source top-N
都自动成为候选
```

。

---

# 13. Mem0 当前有一个值得借的点：明确 Threshold

Mem0 2026 当前 Search API 已公开：

```text
threshold
```

默认：

```text
0.1
```

用于最低 relevance cutoff。

它的 V3 retrieval 也是：

```text
semantic
+
BM25
+
entity
```

multi-signal。

StateBus 不需要复制 Mem0，但应该吸收：

> **Memory Retrieval 必须允许 abstain。**

---

# 14. 推荐 `MemoryRetrievalEvidence`

对于每个 Candidate：

```python
MemoryRetrievalEvidence(
    vector_score,
    lexical_score,
    tag_overlap,
    entity_overlap,
    recency_score,
    source_support_count,
    passed_relevance_gate,
)
```

。

这样 RRF 之后：

```text
为什么召回
```

真正可审计。

---

# 15. 当前 Memory Query 最大架构问题：太晚

当前查询是在：

```text
Retriever 的 Semantic State 已经构建
```

之后发生。

这意味着：

```text
Memory 不参与 Planner
```

。

但很多 Memory 真正最有价值的是：

```text
“以前这种任务用哪个 capability？”
“这个环境曾出现什么坑？”
“这种 schema 应该如何解析？”
“上次失败原因是什么？”
```

这些应该在：

```text
PlanSelector / Planner
```

之前或期间可见。

---

# 16. 推荐 `MemoryBroker`

Memory 应成为 Runtime 独立 subsystem：

```text
Task admitted
     │
     ▼
MemoryBroker
     │
     ├── TaskStart query
     ├── StepReady query
     ├── PostStep write candidate
     └── TaskCommit
```

而不是：

```text
Retriever 的副作用
```

。

---

# 17. MemoryBroker 的四个时机

## TaskStart

用于：

```text
Planner
PlanSelector
```

召回：

```text
workflow memory
route hint
previous failure
environment gotcha
```

。

## StepReady

针对当前：

```text
role
logical capability
input type
```

查询特定 memory。

## PostStep

只创建：

```text
MemoryCandidate
```

不立即提升。

## TaskCommit

在：

```text
final verification
```

之后统一决定：

```text
ACTIVE
QUARANTINE
REJECT
```

。

---

# 18. 需要从 “One Query Per Task” 改成 Query Scope

建议：

```python
MemoryQueryScope(
    query_id,
    task_id,
    step_id,
    consumer_role,
    logical_capability_id,
    requested_memory_kinds,
)
```

。

例如：

```text
planner:
  PROCEDURAL / EPISODIC

retriever:
  SEMANTIC

executor:
  PROCEDURAL

summarizer:
  SEMANTIC / EPISODIC
```

。

---

# 19. Letta 给 StateBus 最值得借的不是“聊天记忆”

Letta 当前 Memory Block 可以：

```text
创建
attach 到 Agent
detach
重新 attach
```

。

同一个 block 可以：

```text
共享给多个 Agent
```

也可以：

```text
动态撤销访问
```

。

对 StateBus 最有价值的是：

# Memory Visibility 是显式运行时能力

而不是：

```text
检索出来
→ 所有下游 role 都看见
```

。

---

# 20. 推荐 Memory Namespace

可以设计：

```python
MemoryNamespace(
    tenant_id,
    project_id,
    task_family_scope,
    agent_scope,
    role_scope,
    capability_scope,
)
```

。

并区分：

```text
PRIVATE_AGENT
TASK_SHARED
PROJECT_SHARED
GLOBAL_VERIFIED
```

。

赛题最常用：

```text
TASK_SHARED
PROJECT_SHARED
```

。

---

# 21. Namespace 不只是数据隔离

它应该同时回答：

```text
谁能查？
谁能读？
谁能引用？
谁能执行里面的 recipe？
谁能升级 Authority？
谁能删除？
```

。

所以需要：

```text
MemoryVisibilityPolicy
```

而不仅是：

```text
SQL filter
```

。

---

# 22. LangGraph / LangMem 也证明 Namespace 是基础抽象

LangGraph 的长期 Memory：

```text
namespace tuple
+
key
```

可以按：

```text
user
org
application
```

划分。

LangMem 同时明确区分：

```text
Semantic
Episodic
Procedural
```

。

这些思想和 StateBus 的 Runtime governance 非常契合。

不需要引入 LangGraph，本质设计可以自己实现。

---

# 23. 当前 Compatibility Gate 的优点

当前明确 hard-reject：

```text
memory not committed
runtime signature mismatch
output contract mismatch
validator digest mismatch
task family mismatch
```

。

这种：

```text
semantic retrieval
≠
execution permission
```

是正确方向。

---

# 24. 但 `same_family` 不应该是所有 Memory 的硬边界

当前不同：

```text
task_family
```

会：

```text
hard INCOMPATIBLE
```

。

这对于：

```text
validated execution recipe
```

有合理性。

但对于：

```text
general strategy
environment gotcha
tool failure
route hint
```

过强。

例如：

```text
financial csv cleaning
```

与：

```text
weather csv cleaning
```

可能共享：

```text
delimiter detection
missing value handling
IQR outlier procedure
```

。

如果 task family 不同：

```text
当前 ASSIST 也完全进不来
```

。

---

# 25. Compatibility 应按 Memory Kind 分层

不要一个 Gate 统管所有。

### Semantic / Assist

关注：

```text
visibility
relevance
provenance
freshness
authority
```

不一定要求：

```text
same task family
```

。

### Procedural

要求：

```text
logical capability compatibility
input contract
output contract
argument/schema shape
runtime/provider constraints
validator
```

。

### Exact Cache

要求：

```text
exact identity
exact inputs
exact runtime
exact output contract
```

。

---

# 26. 推荐统一 `MemoryCompatibilityPolicy`

输入：

```python
MemoryCompatibilityContext(
    memory_kind,
    task_contract_identity,
    logical_capability,
    input_contract,
    output_contract,
    schema_fingerprint,
    runtime_signature,
    validator_signature,
    lineage,
)
```

输出：

```python
MemoryCompatibilityDecision(
    visibility,
    relevance,
    semantic_compatibility,
    execution_compatibility,
    authority,
    reuse_mode,
    reasons,
)
```

。

然后：

```text
runtime/replay.py
MemoryIndexStore
AdaptiveDispatcher
```

全部调用同一个 policy。

---

# 27. 当前 `runtime/replay.py` 其实已经有更好的 Contract Shape 思想

它比较：

```text
task_family
intent_op
required_tools
required_outputs
argument schema shape
```

而不是：

```text
argument exact values
```

。

这很适合：

```text
recipe reuse
```

。

例如：

```text
ticker=ACME
```

和：

```text
ticker=BETA
```

可以：

```text
same procedure
different current data
```

。

这是应保留的设计。

---

# 28. 但未来不要继续以 CanonicalTaskSpec 为通用 Compatibility Identity

Benchmark Boundary Round 已经冻结：

```text
ExternalTaskEnvelope
```

不应该被迫人工填：

```text
task_family
intent_op
required_tools
```

。

否则：

```text
External generalization
```

又退回 closed-set adapter。

所以 Memory 最终需要：

```text
TaskContractIdentity
+
MemoryCompatibilityFingerprint
```

。

---

# 29. 推荐 `MemoryCompatibilityFingerprint`

不是 benchmark label。

它应该由 Runtime 已验证信息生成，例如：

```text
logical capability ID
input media / schema
output contract
validator IDs
sandbox / provider constraints
required public tool class
```

。

不包括：

```text
benchmark category
gold
question type
dataset label
```

。

---

# 30. 当前 Exact Lineage 处理基本合理

Exact replay：

```text
query input lineage
==
stored input lineage
```

才允许 exact。

这是合理的。

而 validated recipe reuse：

```text
lineage 可以不同
```

也合理。

因为它本来就是：

```text
新数据
+
旧 procedure
```

。

这里不要错误地把：

```text
validated replay lineage 不一致
```

当 Bug。

真正的问题是：

```text
validated contract fingerprint
是否足够严格
```

。

---

# 31. 当前 Schema Drift 存在 Fail-Open 边界

当前：

```text
schema_drift = current_schema
               AND stored_schema
               AND unequal
```

。

如果：

```text
current schema != ""
stored schema == ""
```

：

```text
schema_drift=False
```

。

对：

```text
Validated procedure execution
```

更安全的策略应该是：

```text
required compatibility evidence missing
→ downgrade / reject
```

而不是：

```text
unknown == compatible
```

。

---

# 32. 推荐 Missing Evidence Policy

区分：

```text
MISMATCH
UNKNOWN
MATCH
```

。

例如：

```text
input_schema:
  UNKNOWN

validator:
  MATCH

runtime:
  MATCH
```

。

Reuse mode：

```text
Exact:
  UNKNOWN → reject

Validated Procedure:
  UNKNOWN critical fields → ASSIST / reject

Assist:
  可以保留
```

。

---

# 33. 当前 Write Gate 有哪些强点

Adaptive commit 前已经检查：

```text
Runtime completed

CanonicalTaskSpec exists

input lineage exists

Memory query embedding exists

final Executor artifact verified

artifact file hash matches

QualityReport bound to same artifact hash

execution recipe exists
```

。

然后才构造 `MemoryCommit`。

这一点比：

```text
LLM 自己说“记住这个”
```

强很多。

---

# 34. 最重要的正面判断：当前 Adaptive Commit 没直接使用 Benchmark Gold

Adaptive Memory metadata 明确：

```text
benchmark_gold_used = False
```

并且 commit gate 使用：

```text
Runtime QualityReport
+
Artifact hash
```

。

在当前 adaptive mainline 源码里，没有看到：

```text
expected_facts
gold answer
native benchmark grade
```

直接参与这个 commit。

这是应该保留的 boundary。

---

# 35. 但 “Runtime Verified” 不应自动等于 “长期可信”

这个区别非常重要。

一个结果：

```text
对当前 task validator 通过
```

只能说明：

```text
当前 artifact 合格
```

。

不自动意味着：

```text
这个经验适合长期传播
```

。

例如：

```text
current task:
custom formula / special schema

procedure:
虽然当前通过
但泛化风险很高
```

。

需要第二层：

```text
Memory Write Admission
```

。

---

# 36. 当前 `commit_candidate()` 的真正行为

当前代码：

```text
quality_floor_pass=True
→ COMMITTED

quality_floor_pass=False
→ CANDIDATE
```

。

`answer_adopted` 只是被记录：

```text
并不参与 status promotion
```

。

测试甚至明确保护：

```text
quality pass
+
answer_adopted=False
→ COMMITTED
```

。

这与现有 `commit-and-replay.md` 的文字有漂移。

---

# 37. 这里需要一个明确 Architecture Decision

建议不要继续用：

```text
quality_floor_pass
answer_adopted
replay_ready
```

三个 bool 隐式拼出 Memory authority。

新增：

```python
MemoryAdmissionDecision(
    admitted,
    authority_level,
    allowed_memory_kind,
    allowed_reuse_modes,
    provenance_class,
    reasons,
)
```

。

---

# 38. 推荐 Memory Lifecycle

现在：

```text
CANDIDATE
COMMITTED
INVALIDATED
```

不够。

推荐：

```text
CANDIDATE
  ↓
ACTIVE
  ↓
SUPERSEDED
  ↓
STALE
  ↓
QUARANTINED
  ↓
INVALIDATED
```

不是线性唯一流程，而是显式状态。

---

# 39. 为什么需要 `SUPERSEDED`

例如历史 Memory：

```text
“API v1 requires field X”
```

新 Memory：

```text
“API v2 removed field X”
```

不应该：

```text
两条都 ACTIVE
靠 vector rank 猜
```

。

应该有：

```text
new supersedes old
```

关系。

---

# 40. 为什么需要 `STALE`

Runtime / tool / schema 更新时：

```text
旧 recipe
```

未必“错误”，只是：

```text
compatibility evidence outdated
```

。

所以：

```text
STALE
```

比：

```text
INVALIDATED
```

更准确。

可以：

```text
用于低权重 ASSIST
但禁止 executable reuse
```

。

---

# 41. 为什么需要 `QUARANTINED`

未来出现：

```text
memory poisoning
provenance anomaly
conflicting evidence
```

时：

```text
不能直接删除
```

。

应该：

```text
保留审计
禁止影响 active execution
```

。

---

# 42. 2026 Memory Poisoning 已经不是理论问题

近期研究已经系统性展示：

```text
跨 session persistent memory
```

可以成为：

```text
delayed prompt injection
```

载体。

例如 2026 的 sleeper-memory poisoning 工作研究：

```text
攻击内容先进入长期记忆
↓
多个 session 后被召回
↓
再影响 Agent action
```

。

对 StateBus 尤其重要：

```text
Memory 可以跨 Agent
且可能包含 executable recipe
```

风险比普通聊天 memory 更高。

---

# 43. StateBus 有一个天然优势：Runtime Authority

你们不应该采用：

```text
“Memory 内容可信度分数高
所以允许执行”
```

这种纯语义方式。

应该延续：

```text
Agent proposes
Runtime authorizes
```

到 Memory。

---

# 44. 推荐 Origin-Bound Memory Authority

每条 Memory 记录：

```text
origin class

USER_DECLARED
VERIFIED_TOOL_OUTPUT
VERIFIED_RUNTIME_ARTIFACT
AGENT_GENERATED
EXTERNAL_UNTRUSTED
BENCHMARK_PUBLIC
```

以及：

```text
producer role
capability grant
input lineage
validator
write policy
```

。

关键：

```text
Summary / LLM rewrite
不能提高原始 authority
```

。

---

# 45. 记忆 “被 summarizer 重写” 不应洗白 Provenance

例如：

```text
网页恶意内容
  authority = UNTRUSTED
↓
Agent summarizer
↓
“看起来像 Agent 自己生成”
```

不能变成：

```text
TRUSTED_AGENT_MEMORY
```

。

Authority 应：

```text
origin-bound
```

传播。

这与 StateBus 的：

```text
lineage
Ref
Grant
```

非常适配。

---

# 46. 当前 MemoryRef provenance 还不够

已有：

```text
source_task_id
source_agent
source_role_path
producer_run_id
artifact_ref_id
manifest_hash
```

很好。

但缺：

```text
origin authority
visibility namespace
write policy
input trust labels
supersedes
derived_from memory ids
```

。

---

# 47. 推荐 Memory Provenance

```python
MemoryProvenance(
    origin_class,
    source_task_contract_hash,
    producer_role,
    producer_capability_grant_hash,
    source_artifact_hashes,
    source_memory_ids,
    validator_hashes,
    runtime_signature,
    visibility_namespace,
)
```

。

这不是为了“安全炫技”。

它可以同时支持：

```text
污染定位
失效传播
可解释答辩
Memory benchmark privacy
```

。

---

# 48. 当前 Memory Index 的另一个根本问题：Embedding 语义不清

Adaptive commit：

```python
memory_store.put_embedding(memory_query.query_embedding)
```

然后 MemoryRef：

```text
embedding_ref_id
=
当前 source task query embedding
```

。

这意味着 vector retrieval 索引的是：

# “当时任务 Query”

不是：

```text
Memory summary
execution recipe
artifact semantic content
```

。

---

# 49. 这不是一定错误

对于：

```text
case-based / episodic retrieval
```

它很合理：

```text
“当前任务像以前哪个任务？”
```

。

但它不是：

```text
“哪条 Memory 内容语义上最相关？”
```

。

两个概念必须拆开。

---

# 50. 推荐 Embedding Role

```text
task_key_embedding
content_embedding
entity_embeddings
```

。

### task_key_embedding

适合：

```text
episodic / procedural memory
```

回答：

```text
这个任务像哪个历史经验？
```

。

### content_embedding

适合：

```text
semantic fact / evidence
```

回答：

```text
哪条知识内容与 query 相关？
```

。

---

# 51. 当前 `embedding_ref_id` 一个字段不足

推荐：

```python
MemoryEmbeddingRefs(
    task_key_embedding_ref="",
    content_embedding_ref="",
    entity_embedding_refs=(),
)
```

。

---

# 52. Encoder Identity 目前过弱

SentenceTransformer：

```text
encoding =
sentence-transformers:{model_path.name}
```

。

例如：

```text
models/Qwen3-Embedding-0.6B
```

目录内模型被替换：

```text
revision A
→ revision B
```

但：

```text
encoding string
```

没变。

Memory Store 会认为：

```text
同向量空间
```

。

---

# 53. 推荐 `EncoderIdentity`

```python
EncoderIdentity(
    model_id,
    model_revision,
    model_digest,
    pooling,
    normalize,
    dims,
    tokenizer_digest,
)
```

。

Index shard key：

```text
encoder_identity_hash
```

。

---

# 54. Deterministic Encoder 不适合中文正式 Memory 质量证明

当前 deterministic tokenizer：

```regex
[a-z0-9]+
```

。

纯中文：

```text
tokens = []
```

最终：

```text
all-zero vector
```

。

所以：

```text
deterministic embedding
```

只适合：

```text
unit test
controlled deterministic benchmark
```

不能成为：

```text
中文通用 Memory retrieval
```

的质量证据。

---

# 55. FAISS 修复建议

不要一个 global index。

结构：

```python
_faiss_indices: dict[EncoderIdentityHash, FaissShard]
```

每个 shard：

```text
dims fixed
encoding fixed
identity fixed
```

。

构建：

```python
row = len(vecs)
vecs.append(...)
id_map[row] = emb_id
```

不能使用：

```python
enumerate(all embeddings)
```

中的 `i`。

---

# 56. FAISS 还需要 Zero Vector Policy

zero vector：

```text
没有 meaningful semantic direction
```

。

不能：

```text
静默进入 cosine index
```

。

建议：

```text
vector_valid=False
```

并只保留：

```text
keyword / tags
```

候选路径。

---

# 57. 当前持久化层应该怎样收敛

目前：

```text
JSON Registries = full state
SQLite = search index
```

。

建议明确唯一真源。

最简单：

# SQLite = metadata transactional truth

另外：

```text
large recipe / artifact metadata
```

可 CAS。

---

# 58. 推荐持久化结构

SQLite：

```text
memory_records
memory_versions
memory_embeddings
memory_edges
memory_visibility
memory_events
```

。

CAS：

```text
large recipe source
large episode
artifact reference sidecar
```

。

不要继续：

```text
每次 put
读取整个 JSON
重写整个 registry
```

。

这随着 Memory 增长会：

```text
O(N) write amplification
```

。

---

# 59. Current JSON Registry 的扩展性问题

每增加一条 memory：

```text
read whole file
parse whole JSON
modify
serialize all
write whole file
```

。

连续：

```text
10000 memories
```

时：

```text
每次写回成本
```

会越来越大。

而赛题恰好希望：

```text
连续任务积累
```

。

所以这是需要修的系统点，不只是“数据库洁癖”。

---

# 60. 推荐 Memory ID 不再带 Task ID 语义

当前：

```text
memory:{task_id}:{artifact_hash prefix}
```

。

Controlled lane 没问题。

External benchmark：

```text
task_id
```

可能编码：

```text
category
difficulty
task type
```

。

Benchmark Boundary 已经冻结：

```text
Runtime task ID 必须 opaque
```

。

Memory ID 最好：

```text
content / random identity
```

，例如：

```text
mem_<uuid>
```

或：

```text
mem_<content digest prefix>
```

。

Audit 外再映射 benchmark ID。

---

# 61. Current Mainline 写入的 Memory Type 其实很单一

虽然 enum 有 11 类，Adaptive Commit 当前只主要生成：

```text
EXACT_REPLAY
VALIDATED_REPLAY
STRATEGY
```

对应：

```text
final executor artifact
+
execution recipe
```

。

所以答辩不要说：

```text
“系统已经完整维护语义事实、数值事实、文本上下文、路由记忆……”
```

如果产品 mainline 没有真实 write path。

更准确：

> **当前产品主线已完成 verified procedural memory / replay memory；更一般的 semantic / episodic memory contract 已预留，但仍需完成独立写入和生命周期策略。**

---

# 62. `source_role_path` 当前是硬编码

Adaptive commit：

```text
("planner", "retriever", "executor")
```

。

未来 Routing 已允许：

```text
Planner bypass
Retriever bypass
不同 DAG
```

。

所以：

```text
source_role_path
```

不能硬编码。

必须从：

```text
ApprovedPlan
+
actual completed dependency path
```

生成。

---

# 63. Memory Visibility 当前没有 Role Projection

`_memory_inputs_for_step()` 把相同 Memory payload 构造给不同下游 role。

其中甚至包含：

```text
execution_recipe
execution_recipe_hash
artifact lineage
```

。

未来：

```text
Summarizer
```

可能不需要看 raw Python source / recipe。

Planner：

```text
也未必要拿 artifact path
```

。

---

# 64. 推荐 Role-specific Memory Projection

和 StateBus 其他 Ref 一样：

```text
MemoryRef
↓
MemoryProjectionPolicy
↓
Role-specific view
```

。

### Planner

```text
summary
success/failure outcome
route hints
cost/quality stats
```

。

### Executor

```text
validated recipe
input/output contract
provenance
```

。

### Summarizer

```text
verified facts
claim references
artifact lineage
```

。

不要全量广播。

---

# 65. 当前 Memory Consumption Record 的结构其实很好

已经记录：

```text
query hash
memory ID
consumer role
consumer step
input ref
ReplayClass
compatibility
payload hash
before surface
after surface
behavioral effect
downstream refs
skipped generation
skipped LLM
recipe recomputed
```

。

这是非常好的审计骨架。

问题不在字段，而在：

```text
behavioral effect
```

现在如何赋值。

---

# 66. 当前 `behavioral_effect` 是构造出来的，不是观测出来的

当前：

```text
recipe reused
→ recipe_reused_current_input_recomputed

else
→ role_input_augmented
```

。

也就是说：

```text
只要 memory input 存在
```

就不会：

```text
unchanged
```

。

然后指标统计：

```text
effect != unchanged
```

。

这是循环定义。

---

# 67. Memory Effect 应该分层

推荐：

```text
RETRIEVED
APPROVED
PROJECTED
READ
USED
WORK_SKIPPED
DECISION_CHANGED
QUALITY_CHANGED
```

。

其中只有：

```text
WORK_SKIPPED
DECISION_CHANGED
QUALITY_CHANGED
```

可用于：

```text
Memory benefit headline
```

。

---

# 68. 怎样证明 ASSIST Memory 真正改变行为

至少三种方法。

## 方法 A：Explicit Memory Citation

Role 输出：

```text
consumed_memory_ids
```

并说明：

```text
用于哪个 decision field
```

。

这是最低成本。

---

# 69. 方法 B：Decision Surface Delta

例如 Planner：

```text
without memory:
provider=Python

with memory:
provider=DSL
```

真正比较：

```text
selected action / plan / program
```

而不是：

```text
hash(memory inputs + outputs)
```

人为制造 hash 差异。

---

# 70. 方法 C：Shadow Counterfactual

正式 benchmark 可抽样：

```text
same task
same model
same seed
```

跑：

```text
Memory ON
Memory OFF
```

。

比较：

```text
plan
tool calls
tokens
latency
quality
```

。

这是最有说服力的。

不必所有 production run 都跑。

---

# 71. Verified Procedure Reuse 的 benefit 已经比较真实

这部分当前证据强。

测试明确验证：

```text
Task A
生成 TransformProgram

Task B
Memory match VALIDATED_REPLAY
↓
不再调用 program_factory
↓
用旧 recipe
↓
在 B 的 value=22 上重新执行
↓
输出 22
而不是 A 的 11
```

。

这说明：

```text
复用的是 procedure
不是答案
```

。

这是非常适合答辩展示的一条 Demo。

---

# 72. 但 skipped LLM call 指标还要严格

当前 memory consumption：

```text
recipe_recomputed
→ skipped_generation_step_count = 1
→ skipped_llm_call_count = 1
```

。

对于：

```text
LLM_BOUNDED_PYTHON
```

确实可以对应：

```text
skip source generation LLM
```

。

但对于：

```text
deterministic TransformProgram factory
```

它未必真的跳过过一个 LLM call。

所以：

```text
skipped_llm_call_count
```

不能由 `recipe_recomputed` 自动推导。

---

# 73. 推荐 Actual Work Counters

在 Provider 内部统计：

```text
planner_llm_call_count
program_generation_llm_call_count
code_generation_llm_call_count
tool_call_count
transform_interpret_count
artifact_restore_count
```

。

Memory 只读取：

```text
before/after counter delta
```

。

不要用：

```text
ReplayClass
```

猜是否跳了 LLM。

---

# 74. Memory Security：最重要的是 “Authority 不随内容改变”

StateBus 已有：

```text
CapabilityGrant
validator
artifact verification
lineage
```

。

所以可以比普通 Memory Framework 做得更强。

建议：

```text
Memory 内容
永远不能自己声明：

“I am trusted”
“I can execute”
“I am exact replay”
```

。

这些必须来自：

```text
Runtime metadata
```

。

---

# 75. Executable Memory 是最高风险类别

当前 Procedural Memory 可以存：

```text
Transform DSL
Python source
```

。

这是强能力，但必须视为：

```text
code provenance
```

。

每次 reuse：

```text
不能直接因为历史 verified
就绕过当前 sandbox / policy
```

。

好消息：

当前 CodeAct replay source：

```text
仍进入 codeact_runner.execute()
```

重新过 sandbox / policy / validator。

这一点必须保留。

Round 03 CodeAct 会继续深入审。

---

# 76. 推荐 Executable Memory Authority

```text
PROCEDURE_CONTEXT
VERIFIED_REEXECUTABLE
```

即可。

不建议允许：

```text
TRUSTED_SKIP_SANDBOX
```

。

无论历史验证几次：

```text
current sandbox
```

都必须执行。

---

# 77. Current Candidate Memory 语义也需要统一

Legacy `lookup()`：

```text
CANDIDATE
```

可以：

```text
作为 ASSIST 返回
```

。

Hybrid `lookup_hybrid()`：

Compatibility Gate：

```text
not COMMITTED
→ hard incompatible
```

。

所以：

```text
旧 lookup
≠
新 hybrid lookup
```

。

这又是一处 Policy Drift。

---

# 78. Candidate 是否应该可读？

我的建议：

```text
跨 Task：
默认不可读

同 Task / same session：
可以作为 untrusted scratch memory
但必须显式 scope
```

。

不要通过：

```text
把所有 CANDIDATE 自动降为 ASSIST
```

实现。

---

# 79. 推荐两层 Memory

```text
Working Memory
```

：

```text
task/session scoped
candidate allowed
short TTL
```

。

```text
Long-Term Memory
```

：

```text
only ACTIVE verified entries
cross-task
```

。

这比一个 `commit_status` 同时承担全部语义清楚得多。

---

# 80. LongMemEval-V2 为什么很适合 StateBus

截至 2026-09，官方 LongMemEval-V2：

```text
451 questions
5 memory abilities
up to 500 trajectories
up to 115M tokens
web + enterprise
small + medium public tiers
```

。

其关注的 5 类能力包括：

```text
static state recall
dynamic state tracking
workflow knowledge
environment gotchas
premise awareness
```

。

这与 StateBus：

```text
Semantic
Episodic
Procedural
```

几乎天然对应。

---

# 81. LongMemEval-V2 最值得复制的是 Privacy Boundary

官方 backend `query()` 只收到：

```text
question text
optional image
```

外加：

```text
opaque query_invocation_id
```

。

它的 `test_query_privacy.py` 明确构造：

```text
secret question id
secret answer
secret evaluator
question type
metadata
```

然后断言：

```text
Memory backend 看不到
```

。

这应该直接成为 StateBus External Memory Adapter 的模板。

---

# 82. StateBus LongMemEval Adapter 设计

Runtime：

```text
insert(trajectory)
query(question, optional image)
```

。

不要输入：

```text
question_id
question_type
gold
evaluator
category
```

。

StateBus 外部 Harness：

```text
benchmark case mapping
native evaluator
score
```

全部保持在 Runtime 外。

---

# 83. External Memory Lane 第一阶段不要启用 Exact Replay

LongMemEval 主要评估：

```text
memory retrieval usefulness
```

不是：

```text
artifact cache
```

。

第一阶段建议：

```text
Semantic + Episodic + Procedural retrieval
```

而：

```text
Exact Artifact Cache
```

关闭。

否则：

```text
Benchmark Memory
```

和：

```text
Task Cache
```

会混。

---

# 84. LangMem 对 StateBus 最值得吸收的第二点：Memory Formation

它区分：

```text
hot path
background
```

。

对于 StateBus：

### Hot path

适合：

```text
execution recipe
verified failure
critical environment constraint
```

因为 Runtime 已经有强 Validator。

### Background / Post-task

适合：

```text
consolidation
dedupe
semantic summarization
supersede
conflict detection
```

。

---

# 85. StateBus 不需要 Agent 自主随便改 Long-Term Memory

很多通用 framework：

```text
Agent 调 memory tool
→ write/update/delete
```

。

StateBus 的优势就是：

```text
Runtime governed
```

。

推荐：

```text
Agent:
propose memory candidate

Runtime:
validate
admit
scope
commit
```

。

继续保持：

```text
Agents propose;
Runtime authorizes.
```

---

# 86. Mem0 2026 新算法给出的另一个启发

Mem0 当前公开路线：

```text
semantic
+
BM25
+
entity
```

多信号检索；

同时强化：

```text
entity scope
time-aware retrieval
```

。

这说明当前 StateBus：

```text
text + tags + vector
```

方向没错。

下一步不是再加一个更大的 vector DB，而是：

```text
entity signal
+
time / freshness
+
visibility filters
```

。

---

# 87. 是否应该立刻上 Knowledge Graph？

不建议。

当前 Memory 问题优先级：

```text
authority
namespace
policy
retrieval threshold
lifecycle
metrics correctness
```

都高于：

```text
graph database
```

。

实体关系第一版完全可以：

```text
SQLite entity table
+
memory_entity edge
```

。

如果外部 benchmark 证明图结构有收益，再扩展。

---

# 88. Memory Aging / Freshness 当前缺失

目前虽然有：

```text
created_at_ns
```

但 retrieval / compatibility 基本没有使用：

```text
age
last_used
use_count
last_verified
valid_until
```

。

长期运行：

```text
Memory 会无限累积
```

。

---

# 89. 推荐 Freshness Model

不是简单：

```text
越老分数越低
```

。

按 MemoryKind：

### Fact

可能：

```text
valid_until / superseded
```

更重要。

### Procedure

看：

```text
Runtime/provider/schema version
```

。

### Episode

可以：

```text
recency + success confidence
```

。

---

# 90. 推荐 Memory Statistics

每条：

```text
retrieval_count
approved_count
consumption_count
beneficial_use_count
harmful_use_count
last_retrieved_at
last_validated_at
last_failed_at
```

。

这些不是作为“自动信任”的依据。

而是：

```text
debug
ranking feature
quarantine trigger
benchmark
```

。

---

# 91. 需要 Conflict / Supersede Detection

尤其：

```text
Semantic Fact Memory
```

。

例如：

```text
M1:
service endpoint = v1

M2:
service endpoint = v2
```

。

不能只靠向量排名。

Memory Write Policy 应检查：

```text
same subject / key
new evidence
```

决定：

```text
coexist
supersede
conflict
```

。

---

# 92. 为什么 Mem0 的历史 UPDATE/DELETE 争议值得注意

2026 Mem0 已把 OSS 新算法改为：

```text
ADD-only
```

并强化：

```text
entity linking
multi-signal retrieval
temporal reasoning
```

。

这反映一个现实：

```text
自动 UPDATE / DELETE
```

在长期记忆里非常容易破坏历史。

所以 StateBus 不应该急着：

```text
LLM 判断旧记忆过时
→ 直接删除
```

。

建议：

```text
append
+
supersede relation
+
soft invalidation
```

。

---

# 93. 推荐 Immutable Memory Version

每条 Memory version：

```text
immutable
```

更新：

```text
create new version
```

并：

```text
supersedes old
```

。

不直接 mutate：

```text
历史内容
```

。

这和 StateBus Ref / Hash 哲学一致。

---

# 94. Memory Persist Integrity 当前要补什么

至少：

```text
MemoryRef hash
Recipe hash
Source artifact hash
Embedding identity
```

在：

```text
load
consume
```

重新验证。

当前保存了：

```text
execution_recipe_hash
```

但 `_memory_inputs_for_step()` 只是：

```text
读 recipe
读 claimed hash
```

并没有在这里显式：

```text
sha256(recipe) == execution_recipe_hash
```

。

应该加。

---

# 95. Recipe Integrity Check

读取：

```python
recipe = metadata["execution_recipe"]
claimed = metadata["execution_recipe_hash"]
actual = sha256(recipe)

if actual != claimed:
    quarantine
```

。

对于 Python：

```text
source_hash
```

也必须重新验证。

---

# 96. Memory Read 要避免“索引可信、实体不可信”

SQLite / FAISS：

```text
只负责 candidate discovery
```

。

正式打开 Memory 后：

```text
必须从 canonical record
重新验证：
hash
status
authority
visibility
compatibility
```

。

这是和当前：

```text
RRF 后 Compatibility
```

一致的思想。

---

# 97. 推荐 Store 结构 v3

```text
MemoryStore
│
├── CanonicalRecordStore
│
│    immutable versioned memory
│
├── RetrievalIndex
│
│    ├── FTS
│
│    ├── vector shards
│
│    ├── entity index
│
│    └── temporal index
│
├── MemoryAuthorityStore
│
├── MemoryLifecycleStore
└── MemoryEventLedger
```

。

Index 可以随时重建。

Canonical memory 才是 Truth。

---

# 98. Memory Store Concurrency

当前：

```text
sqlite3.Connection
dict
JSON registry
```

没有明确并发模型。

如果以后 Round 01 的：

```text
persistent workers
parallel ready steps
```

上线：

```text
多个 Memory query/write
```

很容易并发。

建议：

```text
MemoryBroker
```

作为唯一 writer。

读取可并行。

第一版不需要复杂分布式事务。

---

# 99. Current continuous benchmark 对 Memory 证明到什么程度

已有 continuous family 测试可以证明：

```text
history roots
artifact reuse
strategy reuse
history step reduction
```

并且某些 family：

```text
10 rounds
```

连续执行。

这是：

# Controlled Continuous Evidence

有价值。

---

# 100. 但不能把当前连续 benchmark 当成通用 Memory generalization

因为任务 manifest 已经显式描述：

```text
reuse_contract
produces
consumes
```

例如：

```text
strategy:iqr_outlier
```

。

这适合证明：

```text
Runtime memory/replay mechanism works
```

不适合证明：

```text
未知任务环境下 Memory 会自动发现并泛化
```

。

所以必须继续保持：

```text
Controlled Evidence
vs
External Generalization Evidence
```

分开。

---

# 101. Memory Benchmark 应新增五类 Negative Cases

只有正向 reuse 不够。

### Case 1

```text
similar query
different schema
→ reject procedure
```

。

### Case 2

```text
same family
different validator
→ reject
```

。

### Case 3

```text
high vector similarity
low semantic relevance
→ abstain
```

。

### Case 4

```text
stale/superseded memory
→ do not execute
```

。

### Case 5

```text
poisoned external input produced memory candidate
→ quarantine / no authority elevation
```

。

---

# 102. 赛题最有说服力的 Memory A/B

建议三组：

```text
No Memory
Fixed Full Memory
Adaptive Memory
```

。

### No Memory

每任务：

```text
从零执行
```

。

### Fixed Full Memory

把所有历史都塞给 Agent。

证明：

```text
token 膨胀
干扰
latency
```

。

### Adaptive StateBus

```text
retrieve
filter
scope
reuse
```

。

这比：

```text
有 Memory vs 无 Memory
```

更能体现你们 Runtime 价值。

---

# 103. 正式指标

建议：

```text
memory_candidate_count

memory_relevance_pass_count

memory_compatible_count

memory_visible_count

memory_consumed_count

memory_beneficial_use_count

memory_harmful_use_count

memory_abstain_count

exact_cache_hit_count

procedure_reuse_count

semantic_assist_count

generation_call_saved_count

tool_call_saved_count

token_saved

latency_saved

quality_delta

false_replay_count

stale_rejection_count

poison_rejection_count

write_amplification_bytes

memory_index_size

query_latency_p50/p95
```

。

---

# 104. 最重要的分母

例如：

```text
procedure_reuse_precision
=
validated successful reuse
/
all attempted procedure reuse
```

。

```text
harmful_memory_rate
=
memory-on quality worse than no-memory
/
memory-used tasks
```

。

```text
memory_utilization
=
beneficial consumed memory
/
retrieved memory
```

。

不是只报：

```text
hit rate
```

。

---

# 105. Memory Benefit Curve

连续任务：

```text
1
5
10
20
50
...
```

画：

```text
quality
tokens
latency
generation calls
query latency
memory size
```

随历史增长变化。

真正要证明：

```text
随着经验增加
收益增长或稳定
```

而不是：

```text
Memory 越多
检索越差
```

。

---

# 106. LongMemEval-V2 Integration 建议阶段

## LM-0

接口适配：

```text
insert(trajectory)
query(question)
```

。

只跑 public Small subset bring-up。

---

# 107. LM-1

完整官方：

```text
Small tier
```

。

禁：

```text
benchmark metadata
gold
evaluator
question type
```

进入 Runtime。

---

# 108. LM-2

加入：

```text
namespace
typed memory
multi-signal retrieval
```

做 ablation。

---

# 109. LM-3

再比较：

```text
StateBus Memory
vs
simple vector RAG
vs
no retrieval
```

。

不要第一版就试图打 SOTA。

目标：

```text
证明 StateBus Shared Memory 是 general external memory backend
```

。

---

# 110. StateBus Memory Target Architecture

最终建议：

```text
                    ┌──────────────────────────┐
                    │      Runtime Task        │
                    └────────────┬─────────────┘
                                 │
                        TaskContractIdentity
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │       MemoryBroker       │
                    └────────────┬─────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
       Semantic Memory      Episodic Memory     Procedural Memory
       facts/evidence       outcomes/failures   verified recipes
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 │
                                 ▼
                    Retrieval Eligibility
                   namespace / authority
                     relevance / freshness
                                 │
                                 ▼
                           Hybrid Retrieval
                      FTS + vector + entity
                                 │
                                 ▼
                       Compatibility Policy
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
                ▼                ▼                ▼
             ASSIST       VERIFIED_PROCEDURE    REJECT
                                  │
                                  ▼
                       Current-input execution
                                  │
                                  ▼
                              Validator


Separate plane:

                 Exact Artifact Cache
                 exact identity only
```

。

---

# 111. 推荐 Contract

## `MemoryNamespace`

```python
@dataclass(frozen=True)
class MemoryNamespace:
    tenant_id: str
    project_id: str
    scope_kind: str
    scope_id: str
```

。

---

# 112. `MemoryRecord`

```python
@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    version_id: str

    memory_kind: MemoryKind
    subtype: str

    namespace: MemoryNamespace

    summary: str
    payload_ref_id: str

    provenance: MemoryProvenance
    authority: MemoryAuthority

    task_key_embedding_ref: str = ""
    content_embedding_ref: str = ""

    created_at_ns: int = 0
    valid_until_ns: int = 0

    lifecycle_state: MemoryLifecycleState
    supersedes: tuple[str, ...] = ()

    schema_version: str = "statebus.memory_record.v3"
```

。

---

# 113. `MemoryQueryV2`

```python
@dataclass(frozen=True)
class MemoryQueryV2:
    query_id: str

    task_contract_identity: TaskContractIdentity

    consumer_role: str
    consumer_step_id: str
    logical_capability_id: str

    namespaces: tuple[MemoryNamespace, ...]
    requested_kinds: tuple[MemoryKind, ...]

    text_query: str = ""
    tags: tuple[str, ...] = ()
    task_embedding_ref: str = ""
    content_embedding_ref: str = ""

    retrieval_budget: MemoryRetrievalBudget

    compatibility_fingerprint: str = ""
```

。

---

# 114. `MemoryAdmissionDecision`

```python
@dataclass(frozen=True)
class MemoryAdmissionDecision:
    candidate_id: str
    admitted: bool

    lifecycle_state: str
    authority_level: str

    allowed_reuse_modes: tuple[str, ...]

    validator_hashes: tuple[str, ...]
    reasons: tuple[str, ...]
```

。

---

# 115. `MemoryConsumptionReceipt`

```python
@dataclass(frozen=True)
class MemoryConsumptionReceipt:
    query_id: str
    memory_id: str

    consumer_role: str
    consumer_step_id: str

    projected_fields: tuple[str, ...]

    read_confirmed: bool
    explicit_reference: bool

    work_skipped: tuple[str, ...]
    decision_fields_changed: tuple[str, ...]

    downstream_ref_ids: tuple[str, ...]

    benefit_class: str
```

。

不要让：

```text
role_input_augmented
```

自动等于：

```text
benefit
```

。

---

# 116. Exact Cache Contract

```python
ExactArtifactCacheKey(
    task_contract_hash,
    input_lineage_hash,
    runtime_signature,
    provider_signature,
    output_contract,
    validator_signature,
)
```

。

Value：

```text
verified ExecutionArtifactRef
```

。

这与 Semantic Memory 分开。

---

# 117. P0 修改清单

## MEM-P0-1：MemoryBroker 解耦 Retriever

先不改算法。

只是把：

```text
query construction
```

从：

```text
semantic retrieval function
```

搬成可独立调用。

Acceptance：

```text
无 Semantic State 的任务也能 Memory Query
```

。

---

# 118. MEM-P0-2：Replay Taxonomy Split

冻结：

```text
Exact Artifact Cache
Verified Procedure Reuse
Assist Memory
```

三种含义。

不要继续：

```text
EXACT_REPLAY
```

一词两义。

---

# 119. MEM-P0-3：统一 Compatibility Policy

删除/收敛：

```text
MemoryIndexStore 独立规则
runtime/replay.py 独立规则
```

到：

```text
MemoryCompatibilityPolicy
```

。

至少统一：

```text
required_tools
argument shape
schema unknown policy
runtime signature
output contract
validator
```

。

---

# 120. MEM-P0-4：修 FAISS

```text
dense row ID mapping
encoder shard
dims validation
zero-vector exclusion
```

。

新增 regression test。

---

# 121. MEM-P0-5：Namespace + Role Visibility

先实现最小：

```text
TASK
PROJECT
ROLE
```

scope。

所有 Memory Query 必须带：

```text
namespace
```

。

所有 Consumer 必须过：

```text
visibility policy
```

。

---

# 122. MEM-P0-6：Write Admission Policy

明确：

```text
Quality pass
≠
Long-term memory admitted
```

。

新增：

```text
MemoryAdmissionDecision
```

。

修正文档与测试语义冲突。

---

# 123. MEM-P0-7：Actual-Use Metric 修正

Headline 不能用：

```text
role_input_augmented
```

。

只计算：

```text
verified work saved
explicit decision changed
quality improved
```

。

---

# 124. MEM-P0-8：Canonical Store Transactionality

至少：

```text
atomic record writes
duplicate ID conflict
recipe hash verify
```

。

推荐：

```text
SQLite canonical metadata truth
+
CAS payload
```

。

---

# 125. P1 修改清单

```text
TaskContractIdentity bridge

task_key_embedding / content_embedding split

EncoderIdentity

freshness / valid_until

supersede relation

QUARANTINED / STALE lifecycle

entity index

retrieval relevance threshold

per-role Memory projection

per-step queries

actual runtime counters for skipped LLM/tool calls

immutable memory versioning

origin-bound authority

candidate scratch namespace
```

。

---

# 126. P2 修改清单

```text
background consolidation

contradiction graph

temporal ranking

counterfactual memory benefit sampler

automatic stale sweeps

memory poisoning benchmark

LongMemEval multimodal image memory

advanced entity graph
```

。

---

# 127. 不建议做

```text
❌ 直接换 Pinecone / Milvus / Qdrant 然后叫“Memory 升级”

❌ 上 Knowledge Graph 解决所有问题

❌ 让 LLM 自己决定是否 trusted

❌ 让 Agent 直接 mutate verified memory

❌ 只按 cosine top-k 注入

❌ 只报 memory hit rate

❌ 用 benchmark question type 做 retrieval filter

❌ 让 native benchmark grade 写回 memory

❌ 把 exact cache 和 semantic memory 继续混在一起

❌ 用所有历史直接塞 prompt 作为“共享记忆”
```

。

---

# 128. 推荐实施 Slice

## MEM-R0 — Correctness & Semantics

```text
FAISS mapping fix

compatibility policy unification

exact cache / procedure naming split

actual-use metric correction

docs drift correction
```

。

不改变外部 benchmark。

---

# 129. MEM-R1 — MemoryBroker

新增：

```text
TaskStart Memory Query
StepReady Memory Query
```

。

第一版只让：

```text
Executor procedural memory
```

迁移过去。

旧 semantic retriever query 保留 fallback。

---

# 130. MEM-R2 — Namespace / Visibility

加入：

```text
task/project/role scope
```

。

测试：

```text
executor-private memory
summarizer invisible

project shared memory
both visible when allowed
```

。

---

# 131. MEM-R3 — Store v3

```text
transactional metadata
immutable version
atomic commit
hash verification
encoder shard
```

。

---

# 132. MEM-R4 — Semantic / Episodic / Procedural Split

不追求一次填满所有功能。

先：

```text
PROCEDURAL:
existing verified recipes

EPISODIC:
success/failure summary

SEMANTIC:
verified fact/evidence summary
```

。

每类独立 write policy。

---

# 133. MEM-R5 — LongMemEval-V2 Adapter

严格：

```text
opaque runtime query ID
public question
public trajectory
```

。

Memory backend：

```text
0 access to:
question_id
question_type
gold
evaluator
category
```

。

---

# 134. MEM-R6 — Memory Benefit Experiment

同一 external / controlled task family：

```text
No Memory

Read-only Memory

Full Write-back Memory
```

比较：

```text
accuracy
tokens
latency
retrieval latency
harmful memory rate
generation calls
```

。

---

# 135. 必须新增的测试

```text
test_memory_query_without_semantic_retrieval

test_planner_can_query_procedural_memory

test_multiple_step_scoped_memory_queries

test_memory_namespace_blocks_cross_role_access

test_memory_namespace_blocks_cross_project_access

test_procedure_memory_requires_capability_compatible_contract

test_validated_policy_matches_history_replay_policy

test_unknown_schema_does_not_fail_open_for_procedure_reuse

test_exact_artifact_cache_is_not_procedure_reuse

test_faiss_empty_vector_id_map

test_faiss_partitions_by_encoder_identity

test_faiss_rejects_mixed_dims

test_zero_vector_not_used_for_semantic_rank

test_memory_retrieval_abstains_below_threshold

test_memory_recipe_hash_verified_on_load

test_memory_recipe_hash_verified_before_execute

test_duplicate_memory_id_conflict_rejected

test_memory_record_atomic_commit

test_memory_superseded_not_executable

test_stale_procedure_downgrades_to_assist

test_quarantined_memory_not_projected

test_memory_origin_authority_not_upgraded_by_summary

test_candidate_memory_not_cross_task_visible

test_role_input_augmented_not_counted_as_behavioral_benefit

test_skipped_llm_call_count_comes_from_actual_provider_counter

test_memory_benefit_counterfactual_no_effect

test_longmemeval_private_metadata_not_runtime_visible

test_private_benchmark_grade_never_updates_memory

test_opaque_external_task_id_used_in_memory
```

。

---

# 136. 当前实现最值得保留的 10 点

```text
1. MemoryRef 是 typed Ref，而不是 prompt blob

2. Retrieval 与 Compatibility 分开

3. RRF 多路 retrieval

4. Runtime signature compatibility

5. output contract compatibility

6. validator digest

7. input lineage

8. verified artifact commit gate

9. validated recipe 对 current input 重算

10. MemoryConsumptionRecord / ReplayLedger 审计思想
```

。

这些是项目真正的基础。

---

# 137. 当前实现最容易答辩被追问的 10 点

```text
1. 为什么 Memory 查询只能在 Retriever 后？

2. Planner 为什么不能直接用历史策略？

3. Exact Replay 为什么 Adaptive 路径还会重执行？

4. 11 种 MemoryType 哪些产品主线真的会写？

5. 不同 Role 为什么拿到相同 Memory payload？

6. 一个 unrelated vector top-1 为什么不会被注入？

7. Memory 怎么区分用户/Agent/项目？

8. Memory 怎么过期/冲突/更新？

9. 为什么“input augmented”就算 behavioral effect？

10. 你怎么证明 Benchmark Gold 没通过 Memory 泄漏？
```

。

这十个问题，完成本轮 P0 后基本都能回答。

---

# 138. 比赛叙事建议

不要说：

> “StateBus 实现了向量数据库和历史缓存。”

建议：

> **StateBus 将共享记忆设计为 Runtime-governed experience plane。历史状态首先作为带 provenance 与 authority 的 typed Memory candidate 写入，经过 current-runtime compatibility、visibility、schema 和 validator policy 后才可被 Agent 读取。执行经验不会直接复用旧答案，而是以 verified procedure 的形式在当前输入上重新执行并再次验证；完全相同输入的输出复用则由独立 Exact Artifact Cache 处理。Semantic / Episodic / Procedural memories 通过 scoped hybrid retrieval 查询，Runtime 记录从 candidate、approval、projection 到 actual consumption 和 verified work saving 的完整 evidence chain。**

这比：

```text
“我们有 Memory”
```

强很多。

---

# 139. Round 02 最终结论

当前 Memory 子系统可以冻结成：

## KEEP

```text
MemoryRef typed contract

hybrid text/tag/vector retrieval

RRF

post-retrieval compatibility gate

Runtime signature

output contract

validator digest

input lineage

verified recipe reuse

current-input recompute

quality validator

consumption record

replay ledger
```

。

## FIX NOW

```text
Retriever coupling

single-query-per-task

Replay taxonomy ambiguity

Compatibility policy duplication

FAISS global index bug

namespace / visibility absence

write admission ambiguity

behavioral effect metric overclaim

registry transactionality
```

。

## BUILD NEXT

```text
MemoryBroker

Semantic / Episodic / Procedural split

Exact Artifact Cache split

Memory namespace

Origin-bound authority

EncoderIdentity

retrieval abstention

immutable version / supersede / stale / quarantine
```

。

## EXTERNAL PROOF

```text
LongMemEval-V2
```

应该成为：

```text
Memory Generalization
```

第一主 benchmark。

---

# 140. Round 03 预告：CodeAct

下一轮建议直接审：

```text
LLM generation
↓
CodeGenerationRequest
↓
prompt construction
↓
source extraction
↓
static policy
↓
bwrap / fallback sandbox
↓
resource limits
↓
filesystem exposure
↓
execution
↓
repair loop
↓
quality validator
↓
artifact publication
↓
Memory procedure reuse
```

重点查：

```text
1. CodeAct Sandbox 是否真的隔离

2. bwrap fallback 是否 fail-open

3. Python AST / source policy 有哪些绕过点

4. generated code 可以访问什么文件 / network / env

5. timeout / memory / CPU / process count 限制是否真实

6. repair loop 是否会改变授权范围

7. Runtime validation 是否足够防止“代码运行成功但结果错”

8. Stored Python recipe 被 Memory reuse 时是否会被重新 policy check

9. CodeAct 与 DSL 谁应该被 Binder 选择

10. 当前 25/25 CodeAct benchmark 到底证明了什么、有没有 adapter scaffolding
```

。

---

# Appendix A. 本轮审计源码

```text
statebus/memory/models.py
statebus/memory/store.py
statebus/memory/embedding.py

statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/commit_gate.py
statebus/runtime/ledger.py
statebus/runtime/replay.py

tests/test_hybrid_memory_query.py
tests/test_memory_store.py
tests/test_memory_runtime.py
tests/test_replay.py
tests/test_adaptive_mainline_integration.py
tests/test_continuous_runner.py

docs/implementation/memory/hybrid-retrieval.md
docs/implementation/memory/compatibility-and-consumption.md
docs/implementation/memory/commit-and-replay.md
```

---

# Appendix B. 外部参考

## LongMemEval-V2

Official GitHub:

https://github.com/xiaowu0162/LongMemEval-V2

重点：

```text
451 questions
5 abilities
up to 500 trajectories
up to 115M tokens
query privacy
opaque query_invocation_id
native evaluator outside Memory backend
```

特别参考：

```text
tests/test_query_privacy.py
```

---

## LangGraph / LangMem

Memory overview:

https://docs.langchain.com/oss/python/concepts/memory

Stores:

https://docs.langchain.com/oss/python/langgraph/stores

LangMem:

https://langchain-ai.github.io/langmem/concepts/conceptual_guide/

重点借：

```text
Semantic / Episodic / Procedural taxonomy
namespace
hot-path / background formation
metadata filtering
memory consolidation
```

。

---

## Letta

Docs:

https://docs.letta.com/

Memory Blocks:

https://docs.letta.com/tutorials/attaching-detaching-blocks/

重点借：

```text
Agent-visible memory block
attach/detach
shared across agents
visibility is explicit
```

。

---

## Mem0

GitHub:

https://github.com/mem0ai/mem0

Search:

https://docs.mem0.ai/core-concepts/memory-operations/search

重点借：

```text
entity scope
semantic + BM25 + entity hybrid
retrieval threshold
time-aware retrieval
```

。

不建议直接照搬：

```text
LLM-managed trust
graph complexity
```

。

---

# Appendix C. Security Research

2026 已出现多项 persistent Memory poisoning 研究，包括：

```text
Hidden in Memory:
Sleeper Memory Poisoning in LLM Agents

Securing LLM-Agent Long-Term Memory Against Poisoning:
Non-Malleable, Origin-Bound Authority...
```

对于 StateBus 最关键的工程结论不是实现论文全部防御，而是：

```text
origin authority 在 write time 绑定
summary 不提升 authority
retrieval relevance 不等于 execution authority
Memory influence 仍必须经过 Runtime Grant / Validator
```

。

---

# Appendix D. 推荐开发顺序

```text
MEM-R0
Correctness / taxonomy / metric

   ↓

MEM-R1
MemoryBroker

   ↓

MEM-R2
Namespace / Visibility

   ↓

MEM-R3
Transactional Store / Encoder Shard

   ↓

MEM-R4
Semantic / Episodic / Procedural Split

   ↓

MEM-R5
LongMemEval-V2

   ↓

MEM-R6
Benefit / Poison / Aging Experiments
```

---

# Final Architecture Principle

StateBus 的 Shared Memory 最终不应该成为：

```text
一个“Agent 都能搜的向量库”
```

而应该成为：

# **A typed, scoped, provenance-bound, runtime-governed experience plane.**

也就是：

```text
能搜到
≠
能看

能看
≠
能相信

能相信
≠
能执行

能执行
≠
能跳过当前验证
```

这一层级如果建立起来，Shared Memory 才会真正成为 StateBus 与普通 Agent Framework 拉开差异的系统能力。
