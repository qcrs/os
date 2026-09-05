# StateBus Round 04 — Shared Memory / Memory Runtime 全链源码审计与演进设计

> 审计对象：`qcrs/os`  
> 分支：`master`  
> 审计基线：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 日期：2026-09-03  
> 范围：`Memory Commit → Persistence → Query → Hybrid Retrieval → Compatibility → Projection/Binding → Consumption → Recipe Replay → Artifact Replay → Lifecycle → External Memory Evaluation`
>
> 本轮承接 Round 03。Round 03 已确认一个必须优先修复的问题：CodeAct 发生 repair 后，当前 `execution_recipe` 可能保存初始 source，而不是最终被验证的 source。因此任何 `VALIDATED_REPLAY / EXACT_REPLAY` 的可信性，都必须先建立在 **Verified Recipe Identity** 正确的前提上。

---

# 0. Executive Summary

先给结论。

StateBus 当前 Memory Runtime **不是 toy**。它已经具备一套比较完整的机制骨架：

```text
Runtime verified result
    ↓
MemoryCommit
    ↓
SQLite / JSON registry / embedding registry
    ↓
keyword + tags + vector
    ↓
RRF
    ↓
Compatibility Gate
    ↓
ASSIST / VALIDATED_REPLAY / EXACT_REPLAY
    ↓
role input
    ↓
MemoryConsumptionRecord
    ↓
current-input recomputation / downstream artifact
```

当前已经做对了几件很重要的事情：

1. Memory 不是只靠 embedding similarity 决定 replay。
2. Runtime signature、output contract、validator digest、schema、lineage 会参与 replay compatibility。
3. 不兼容 candidate 可以留在 candidate/audit surface，但不能进入有效 match。
4. Recipe replay 会在当前 verified input 上重新执行，而不是盲目信任历史 output。
5. Memory commit 会绑定 terminal verified artifact 和 quality report。
6. 已经有 keyword / tag / vector 三路 hybrid retrieval 和 RRF。
7. Memory 是 persistent store，不是单进程 dict demo。
8. 已经开始测正向 reuse 与 incompatible negative fixture。

但是从“能跑”升级到“正式 Shared Memory Runtime”，目前仍有几类结构性问题。

## 0.1 风险优先级

| Priority | 问题 | 影响 |
|---|---|---|
| **P0** | Round 03 的 verified recipe source identity 未闭合 | `VALIDATED_REPLAY` 可能复用的不是当初真正被验证的 source |
| **P0** | 当前 `memory_behavioral_effect_count` 并不是真正的 behavioral effect | 比赛 evidence 可能把“输入被注入”误写成“行为被改变” |
| **P0/P1** | Adaptive Recipe Replay 与 `runtime/replay.py` 的 Artifact Replay 共用同一组 `ReplayClass` 术语，但行为不同 | 设计文档、Telemetry 和实验结论容易误导 |
| **P1** | Memory Query 被挂在 Retriever semantic-state 路径上 | 没有 Retriever 的动态 Plan 无法自然使用 Memory；Memory 不是独立 Runtime plane |
| **P1** | Memory Ref 没有被 `CapabilityGrant.input_ref_ids` 明确授权 | Memory 是 Dispatcher 后加的隐式输入，authority chain 不完整 |
| **P1** | 没有 Memory Namespace / tenant / project / session scope | 当前相似度 + CanonicalTaskSpec 是兼容性，不是访问控制 |
| **P1** | 同一个 task-level memory result 被广播给多个后续 step/role | 没有真正的 per-consumer projection / budget |
| **P1** | `ASSIST` memory 也携带完整 `execution_recipe` | raw Python/DSL recipe 进入 LLM prompt，造成 token、污染和权限语义混淆 |
| **P1** | Compatibility 对所有 MemoryType 使用同一套 hard gate | 对 recipe 合理，但对 strategy/evidence/route hint 过严 |
| **P1** | `allowed_memory_types` 在 Adaptive MemoryQuery 中没有设置 | 未来不同类型 memory 会混在同一 candidate pool |
| **P1** | Memory commit 依赖“本 task 已经发过 MemoryQuery” | 不查 Memory 的任务无法 commit Memory，读写路径被错误耦合 |
| **P1** | Memory commit 复用 Retriever query embedding，而不是显式 memory retrieval key | “memory 内容 embedding”和“task query key”概念混在一起 |
| **P1** | JSON registry + SQLite 双写没有事务一致性 | crash / concurrent writer 可能造成 divergence |
| **P1** | 每次 put 都重写整个 JSON registry | O(N) write amplification；embedding JSON 尤其重 |
| **P1** | FAISS `IndexFlatIP` 被注释为 O(log N)，实际上是 exact flat O(N) | 性能认知错误 |
| **P1** | 每次 embedding 更新后 FAISS lazy full rebuild；查询又 search 全部 vectors | 序列任务下可能形成 O(N²) 累计 rebuild 成本 |
| **P1** | FAISS index 没按 `(encoding, dims)` 分区 | encoder 迁移/混合 embedding 可能直接失败 |
| **P2** | 无 dedup / supersede / TTL / temporal validity / orphan GC | 长期运行会累积重复、陈旧和孤儿对象 |
| **P2** | Hybrid retrieval 无 relevance threshold / freshness policy | top-k 即使很弱也可能被注入 |
| **P2** | RRF equal-weight 固定 `k=60`，没有 query-type-aware fusion | 当前够用，但不应直接宣称最优 |
| **P2** | current controlled adaptive-memory benchmark 不是 external generalization proof | 需要 LongMemEval-V2 外部 lane |

---

# 1. 先把三种“Memory / Replay”分开

StateBus 现在实际存在至少三种相关机制：

```text
A. Semantic State
B. Adaptive Memory / Recipe Memory
C. History Artifact Replay
```

它们不能混着讲。

## 1.1 Semantic State

```text
Retriever
    ↓
dense candidate embeddings
    ↓
StateBus shared state
    ↓
cross-process Executor
    ↓
cosine top-k / budget pruning
    ↓
selected evidence
```

它解决的是：**同一个当前任务内部，Retriever → Executor 如何传非文本 semantic state**。

这是 data-plane state sharing，不是长期 memory。

## 1.2 Adaptive Memory / Recipe Memory

```text
Task N
    ↓
verified execution
    ↓
MemoryCommit
    ↓
persistent store

Task N+1
    ↓
MemoryQuery
    ↓
hybrid retrieval
    ↓
Compatibility
    ↓
ASSIST or recipe replay
```

它解决的是：**跨任务历史经验如何被发现、授权、投影、消费和重用**。

## 1.3 `runtime/replay.py` History Replay

Repo 中还有：

```text
statebus/runtime/replay.py
```

这里有：

```text
ReplayCandidate
ReplayAdmissibilityGate
HistoryReplayRecord
ReplayLedgerEntry
replay_exact_key()
```

它围绕历史 verified Artifact、历史 output path、runtime signature、input artifact hashes、exact replay key 工作，更接近 **Artifact / Output Replay**。

---

# 2. 当前最大的术语问题：两种 Replay 共用一个名字

两套机制都使用：

```text
ReplayClass.ASSIST
ReplayClass.VALIDATED_REPLAY
ReplayClass.EXACT_REPLAY
```

但真实行为不一样。

## 2.1 Adaptive Recipe Replay

当前 `_validated_recipe()`：

```text
Memory
    ↓
取 execution_recipe
    ↓
恢复 DSL operations / Python source
    ↓
对当前 verified input 重新执行
    ↓
重新 Validator
```

所以它实际是：

```text
Recipe Recompute
```

而不是历史结果直接恢复。

## 2.2 History Artifact Replay

`runtime/replay.py` 的语义更接近：

```text
历史 verified output / artifact
    ↓
exact key / compatibility
    ↓
恢复结果
    ↓
skip actual stages
```

这是更典型的：

```text
Artifact Restore
```

## 2.3 现有文档因此会误导

`docs/implementation/memory/commit-and-replay.md` 把 `VALIDATED_REPLAY / EXACT_REPLAY` 描述成“恢复已验证产物、跳过部分步骤”，这更接近 `runtime/replay.py`，但 Adaptive Dispatcher 当前主要是“复用 recipe + 当前输入重新计算”。

因此必须拆开表述。

---

# 3. 推荐重构 Replay Taxonomy

当前 `MemoryType` 同时放了：

```text
EVIDENCE
OUTCOME
STRATEGY
ROUTE_HINT
EXECUTION_ARTIFACT
VALIDATED_REPLAY
EXACT_REPLAY
```

这里混了两个维度。

## 3.1 Content Kind

```text
EVIDENCE
FACT
EVENT
PROCEDURE
STRATEGY
ROUTE_HINT
EXECUTION_RECIPE
OUTPUT_ARTIFACT
```

## 3.2 Reuse Mode

```text
ASSIST_CONTEXT
RECIPE_RECOMPUTE
ARTIFACT_RESTORE
DISALLOWED
```

## 3.3 Compatibility Level

```text
EXACT
COMPATIBLE
DEGRADED
INCOMPATIBLE
```

于是可以准确表达：

```text
MemoryKind = EXECUTION_RECIPE
ReuseMode = RECIPE_RECOMPUTE
Compatibility = EXACT
```

而不是：

```text
MemoryType = EXACT_REPLAY
ReplayClass = EXACT_REPLAY
```

这对后续 telemetry、文档、benchmark 都更干净。

---

# 4. 当前真实 Adaptive Memory 主链

源码实际主链如下：

```text
AdaptiveTaskEnvelope
    │
    ├─ allowed_memory_policies
    │
    ▼
ApprovedPlan.requested_memory_policy
    │
    ▼
Retriever EvidenceRequest.memory_policy
    │
    ▼
AdaptiveCapabilityDispatcher
._consume_retrieval_semantic_state()
    │
    ├─ semantic state publish / consume
    ├─ selected evidence
    │
    ▼
MemoryQuery
    │
    ├─ query_text = Retriever queries
    ├─ tags = Retriever target_entities
    ├─ embedding = Retriever query embedding
    ├─ canonical task spec
    ├─ runtime signature
    ├─ output contract
    ├─ lineage/schema
    └─ validator digest
    │
    ▼
MemoryIndexStore.lookup_hybrid()
    │
    ├─ SQLite FTS
    ├─ tag overlap
    ├─ vector cosine
    └─ RRF
    │
    ▼
Compatibility Gate
    │
    ├─ commit status
    ├─ validation status
    ├─ runtime signature
    ├─ output contract
    ├─ validator digest
    ├─ task family/intent/output
    ├─ schema drift
    └─ input lineage
    │
    ▼
MemoryMatchResult
    │
    ▼
_memory_inputs_for_step()
    │
    ├─ summary
    ├─ tags
    ├─ artifact lineage
    ├─ execution recipe
    ├─ replay class
    └─ compatibility reason
    │
    ▼
Executor / Summarizer
    │
    ├─ ASSIST
    └─ replay recipe
    │
    ▼
MemoryConsumptionRecord
```

运行结束后：

```text
terminal Executor Artifact
    ↓
quality report
    ↓
execution recipe
    ↓
_commit_verified_memory()
    ↓
MemoryCommit
    ↓
embedding registry
    ↓
commit registry
    ↓
SQLite index
```

---

# 5. P1：Memory Query 不是独立 Runtime Plane

当前 `MemoryQuery(...)` 是在：

```text
_consume_retrieval_semantic_state()
```

内部创建的。

这意味着：

```text
Memory Query
依赖 Retriever step 已经发生
```

## 5.1 与动态 Routing 冲突

Round 01 的目标是：easy task 可以绕过不必要 role。

例如未来 Plan：

```text
Task
    ↓
Executor
    ↓
Summarizer
```

没有 Retriever。

按当前代码：

```text
没有 Retriever
    ↓
没有 _consume_retrieval_semantic_state
    ↓
没有 MemoryQuery
    ↓
没有 MemoryMatch
```

所以 Memory 还不是一个独立 plane，而是 Retriever 的附属功能。

## 5.2 更严重：Commit 也依赖 Query

`_commit_verified_memory()` 会检查：

```python
memory_query = context.memory_queries_by_task.get(request.task_id)
if memory_query is None or memory_query.query_embedding is None:
    return "memory_query_embedding_missing"
```

也就是说：

```text
没查询 Memory
    ↓
也不能 commit Memory
```

这是明显的 Read Path / Write Path 耦合。

## 5.3 推荐目标

Memory 应变成独立 Runtime plane：

```text
Task / STEP_READY
    ↓
MemoryAdmissionPolicy
    ↓
MemoryQueryBuilder
    ↓
Memory Runtime
```

而不是：

```text
Retriever
    ↓
顺便做一次 Memory Query
```

---

# 6. Memory Query 最合适的时机：STEP_READY

对 execution memory，最自然的查询点不是 Task 开头，而是：

```text
STEP_READY
```

因为此时已经知道：

```text
logical step
consumer role
capability
input refs
output contract
current schema
current lineage
budget
```

所以推荐：

```text
STEP_READY
    ↓
MemoryAdmissionPolicy
    ↓
Memory Query
    ↓
Memory Selection
    ↓
Memory Binding
    ↓
CapabilityGrant
```

这样能与 Round 01 的 Execution Binding plane 对齐。

---

# 7. P1：Memory 不在 CapabilityGrant Authority 内

当前 `CapabilityGrant` 有：

```text
task_id
session_id
step_id
attempt_id
capability_id
input_ref_ids
output_contract
workspace
runtime budget
expiry
approved_plan_hash
```

没有：

```text
memory_ref_ids
memory_binding_hash
```

但 `_memory_inputs_for_step()` 会在 Dispatcher 里读取 `context.memory_match_results`，动态附加历史 memory。

因此一个 step 实际消费了 Memory，但这批 Ref 不在：

```text
grant.input_ref_ids
```

里。

这不是 LLM 绕权，因为查询/过滤仍由 Runtime 执行；但它意味着：

> **CapabilityGrant 没有完整表达 step 实际看到的全部 Authority Input。**

对 StateBus 这种强调 Runtime Authorizes 的系统，这是 contract 缺口。

## 7.1 推荐 `MemoryBindingReceipt`

```python
@dataclass(frozen=True)
class MemoryBindingReceipt:
    task_id: str
    step_id: str
    attempt_id: str

    query_hash: str

    candidate_memory_ids: tuple[str, ...]
    rejected_memory_ids: tuple[str, ...]
    selected_memory_ids: tuple[str, ...]

    consumer_role: str
    consumer_capability_id: str

    projection_hashes: tuple[str, ...]

    policy_version: str
    receipt_hash: str
```

随后：

```text
CapabilityGrant
    +
memory_binding_receipt_hash
```

更强版本可以直接加入：

```text
authorized_memory_ref_ids
```

---

# 8. P1：没有 Namespace / Scope Authority

当前 `MemoryQuery` 没有：

```text
tenant_id
workspace_id
project_id
user_id
session_id
memory_namespace
visibility_scope
```

`MemoryRef` 也没有对应字段。

当前主要用：

```text
CanonicalTaskSpec
runtime signature
output contract
validator digest
schema
lineage
```

来限制 replay。

但这些是 **compatibility**，不是 **authorization**。

## 8.1 为什么这会成为通用 Shared Memory 的问题

假设未来同一个 StateBus service 服务：

```text
Project A
Project B
```

二者碰巧都有：

```text
task_family = financial_report_analysis
intent = compare_metric
```

当前 semantic/lexical retrieval 理论上可以把 A 的 memory 放进 B 的 candidate pool。

即使后续 replay 还有很多 gate，也不应该让它在没有 scope 授权时进入候选面。

## 8.2 外部实现都明确做 scope

Mem0 使用：

```text
user_id
agent_id
run_id
filters
```

LangGraph `BaseStore` 直接以：

```text
namespace: tuple[str, ...]
```

隔离 user / assistant / arbitrary namespace。

## 8.3 StateBus 推荐最小 Contract

```python
@dataclass(frozen=True)
class MemoryNamespace:
    tenant_id: str
    workspace_id: str
    project_id: str = ""
    agent_scope: str = ""
    session_scope: str = ""
```

比赛单用户环境可以固定：

```text
tenant_id = local
workspace_id = statebus-contest
```

但 contract 应该有。

## 8.4 Scope 必须在 Retrieval 前过滤

顺序应是：

```text
Memory Store
    ↓
Namespace ACL
    ↓
Memory Type Policy
    ↓
Coarse Compatibility
    ↓
Retrieval / Ranking
```

而不是全库相似度之后再看 scope。

---

# 9. P1：Memory Query 语义被 Retriever Query 绑架

当前：

```python
query_text = " ".join(result.request.queries)
tags = tuple(result.request.target_entities)
query_embedding = query_bundle.memory_query_embedding or query_bundle.query_embedding
```

也就是：

> Memory 查询语义来自 Retriever 为当前 evidence search 生成的 queries。

但 Evidence Retrieval Query 不等于 Memory Retrieval Query。

例如用户任务：

```text
比较 ACME 两个季度的收入变化
```

Retriever 可能生成：

```text
ACME 2026Q1 revenue table
ACME 2026Q2 revenue table
```

但历史 Memory 真正有价值的可能是：

```text
如何处理财务表格中 bracketed numeric range 的解析
```

或者：

```text
这个任务类型适合 bounded Python，而不是 DSL
```

检索目标完全不同。

## 9.1 LongMemEval-V2 AgentRunbook-R 的启发

它明确区分：

```text
raw_state_queries
event_query
note_query
```

即 raw state / event / procedure-note 使用不同 query intent。

StateBus 不必直接照搬三池，但至少应该区分：

```text
Task / Strategy Query
Execution Recipe Query
Evidence / Fact Query
```

## 9.2 推荐 `MemoryQueryIntent`

```python
@dataclass(frozen=True)
class MemoryQueryIntent:
    consumer_role: str
    consumer_step_id: str
    logical_capability_id: str

    requested_memory_kinds: tuple[str, ...]
    requested_reuse_modes: tuple[str, ...]

    query_goal: str
    output_contract_version: str

    max_items: int
    max_visible_bytes: int
    max_visible_tokens: int
```

Memory query key 应从当前 step 的 task/goal/capability/contract 构造，Retriever query 只作为 secondary signal。

---

# 10. P1：Memory Commit 复用 Query Embedding

当前 commit 会：

```python
memory_store.put_embedding(memory_query.query_embedding)
```

然后：

```text
MemoryRef.embedding_ref_id
=
memory_query.query_embedding.embedding_id
```

因此当前 embedding 更像：

```text
Historical Task Query Key Embedding
```

而不是：

```text
Memory Content Embedding
```

这不一定错。对于 recipe memory，task-key embedding 甚至可能很合理。

但命名和 contract 应明确区分：

```text
task_key_embedding
memory_content_embedding
```

更好的 recipe memory 可以同时保存：

```text
MemoryRecord
  ├─ task_key_embedding
  ├─ summary_embedding
  └─ optional entity keys
```

用于“相似任务”和“相似技术经验”两类召回。

---

# 11. P1：所有 MemoryType 当前可以混合召回

`MemoryQuery.allowed_memory_types` 已经支持 type filter，但 Adaptive Runtime 构造 MemoryQuery 时没有设置它。

默认空 tuple 表示不过滤。

当前还不明显，是因为 Adaptive mainline 主要生产：

```text
STRATEGY
VALIDATED_REPLAY
EXACT_REPLAY
```

但一旦未来把：

```text
NUMERIC_FACT
TEXT_CONTEXT
ROUTE_HINT
SEMANTIC_EVIDENCE
OUTCOME
```

都放进一套 store，RRF 就可能把不适合当前 consumer 的 memory 排到前面。

推荐按 consumer/capability 过滤：

```text
Executor + Bounded Python
    → EXECUTION_RECIPE, STRATEGY

Summarizer
    → FACT, EVIDENCE, OUTCOME, STRATEGY

PlanSelector
    → ROUTE_HINT, STRATEGY
```

---

# 12. P1：一个 Task-level Result 被广播给多个 Step

`_memory_inputs_for_step()` 遍历：

```text
context.memory_match_results
```

把所有 policy-approved matches 都重新包装成当前 step 的 role input。

它只是加上：

```text
consumer_role
consumer_step_id
```

没有真正做：

```text
per-role selection
per-capability selection
per-step rerank
per-step budget
```

所以现有文档“Runtime 为目标角色构造 capability 对应输入视图”的表述比当前实现更强。

## 12.1 推荐两层

```text
Task-level Candidate Retrieval
    ↓
MemoryCandidatePool
    ↓
Per-step MemoryProjectionPolicy
```

Projection policy 决定：

```text
哪些 MemoryKind
哪些 reuse mode
最大 items
最大 bytes/tokens
是否允许 recipe
是否允许 source task info
是否允许 artifact lineage
是否需要 provenance
```

---

# 13. P1：ASSIST 也拿到了完整 Execution Recipe

当前 role input 无论 replay class，都有：

```python
"execution_recipe": recipe_payload
```

所以 `ASSIST` 也可能看到完整：

```text
Python source
DSL operations
```

这不是理想的 Assist。

Assist 应该是：

```text
历史策略
摘要
事实
gotcha
procedure
```

而不是可执行 recipe。

## 13.1 四个问题

### A. Token Bloat

Python source 可能很长。

### B. Semantic Contamination

旧 source 会直接影响新 LLM。

### C. Prompt Injection Surface

Memory 里的代码/指令对模型来说天然像 instruction surface。

### D. Authority Confusion

Runtime 已经判定“不允许 replay”，但模型仍然拿到了 replay payload。

## 13.2 正确做法

```text
ASSIST
    ↓
MemoryProjection
    ↓
summary / facts / gotchas only

RECIPE_RECOMPUTE
    ↓
Runtime-only recipe_ref
    ↓
ExecutionBinder
```

可执行 recipe 不应默认进入 Agent prompt。

## 13.3 两种 Projection

Assist Projection：

```python
{
  "memory_id": "...",
  "kind": "strategy",
  "summary": "...",
  "provenance": {...},
  "confidence": ...
}
```

Replay Binding：

```python
{
  "memory_id": "...",
  "recipe_ref": "...",
  "recipe_hash": "...",
  "execution_receipt_hash": "...",
  "reuse_mode": "recipe_recompute"
}
```

第二种由 Runtime 消费，不进入 prompt。

---

# 14. P1：Compatibility Gate 对所有 Memory 太统一

当前 hard-incompatible 条件包括：

```text
runtime signature mismatch
output contract mismatch
validator digest mismatch
task family mismatch
```

对于 Execution Recipe，这是合理的。

但对于 STRATEGY / ROUTE_HINT / GOTCHA，不一定合理。

例如一条历史经验：

```text
财务表格的某个数字字段包含 bracketed range，
不要用 full-string digit concatenation
```

即使 validator digest 改了，它仍可能作为 Assist 有价值。

当前统一 gate 会直接 DISALLOW。

## 14.1 需要三套 Compatibility

### AssistCompatibilityPolicy

关注：

```text
namespace
memory kind
semantic relevance
task/step capability
time validity
source trust
```

不必要求 runtime/output/validator exact。

### RecipeCompatibilityPolicy

必须严格：

```text
provider kind
capability
policy
runtime signature
validator
output contract
input schema
recipe identity
verification strength
```

### ArtifactRestoreCompatibilityPolicy

更强：

```text
TaskContractIdentity exact
input lineage exact
artifact hash exact
runtime exact
output contract exact
validator exact
```

---

# 15. Candidate Serving 语义目前在两个 API 中不一致

`commit_candidate()` 会保留 replay_class，即使 quality floor 不通过。

旧 `lookup()`：

```text
CANDIDATE
    ↓
仍可出现
    ↓
serving 时 clamp 为 ASSIST
```

测试也明确验证这个行为。

但 current Adaptive 使用 `lookup_hybrid()`，其 `_compatibility_decision()` 会把：

```text
commit_status != COMMITTED
```

直接 hard-incompatible。

所以现在存在：

```text
lookup()
    CANDIDATE → ASSIST

lookup_hybrid()
    CANDIDATE → DISALLOWED
```

两套 serving semantics。

推荐长期 persistent memory 只服务 `COMMITTED`。

如果确实需要 same-session uncommitted experience，应创建：

```text
EphemeralSessionMemory
```

单独的 namespace/lifecycle，而不是让两个 lookup API 对 CANDIDATE 定义不同语义。

---

# 16. P0：当前 Behavioral Effect Metric 并不成立

这是本轮最重要的 evidence 问题之一。

当前 `_record_memory_consumption()`：

```python
behavioral_effect = (
    "recipe_reused_current_input_recomputed"
    if recipe_recomputed
    else "role_input_augmented"
)
```

然后：

```python
memory_behavioral_effect_count =
    sum(record.behavioral_effect != "unchanged")
```

所以只要 Memory 被投给 role：

```text
ASSIST
    ↓
behavioral_effect = role_input_augmented
    ↓
behavioral_effect_count + 1
```

这不等于“行为改变”。

真实 behavioral effect 应回答：

```text
如果没有这条 Memory，
Plan / Program / Claim / Output 是否会不同？
```

当前并没有做 counterfactual。

## 16.1 文档反而说对了

`compatibility-and-consumption.md` 已经明确：

```text
memory 被读取
≠
它改变了最终计划和选择
```

但 metric 实现没有做到这个区分。

## 16.2 Adaptive Memory benchmark 又把它当 Gate

`adaptive_memory.py` 要求 query/candidate/compatible/policy-approved/consumed/behavioral_effect 都大于 0。

因此：

> 当前 `behavioral_effect_count > 0` 不能作为“Memory 真正改变了行为”的证据。

## 16.3 推荐先重命名

现有指标：

```text
memory_behavioral_effect_count
```

改成：

```text
memory_input_augmented_count
```

## 16.4 真正 effect 只在两类情况算

### A. Direct Mechanistic Effect

```text
recipe replay
    ↓
code generation skipped
```

这是可直接证明的。

### B. Counterfactual Evaluated Assist

```text
with memory
vs
shadow without memory
```

比较：

```text
planner proposal hash
program hash
source hash
claim hash
quality
latency
token
```

只有决策/输出真的变化，才能叫 behavioral effect。

## 16.5 推荐 `MemoryConsumptionReceipt`

```python
@dataclass(frozen=True)
class MemoryConsumptionReceipt:
    memory_id: str
    consumer_step_id: str
    projection_hash: str

    consumption_mode: str
    # assist_context / recipe_recompute / artifact_restore

    injected: bool

    generation_skipped: bool
    sandbox_execution_skipped: bool
    artifact_reused: bool
    recipe_recomputed: bool

    counterfactual_evaluated: bool
    decision_surface_changed: bool | None

    before_hash: str
    after_hash: str

    downstream_ref_ids: tuple[str, ...]
```

---

# 17. `skipped_step_count` 也容易误导

Adaptive Recipe Replay 里：

```text
Executor Runtime step 仍然执行
DSL/Python 仍然执行
validator 仍然执行
```

只是：

```text
LLM code/program generation
```

被跳过。

所以不要叫：

```text
skipped_step_count
```

推荐拆成：

```text
generation_skipped_count
executor_llm_call_skipped_count
recipe_recompute_count
artifact_restore_count
runtime_step_skipped_count
```

---

# 18. Memory Commit 语义与文档不一致

现有文档说：

```text
quality floor pass
+
answer adopted
    ↓
COMMITTED
```

当前代码实际：

```python
status = COMMITTED if quality_floor_pass else CANDIDATE
```

`answer_adopted` 只被记录到 MemoryRef。

测试甚至专门验证：

```text
quality pass
answer_adopted = False
    ↓
COMMITTED
```

这不一定是 bug，因为 Runtime verification 本来可以独立于用户是否采纳答案。

问题是：字段名、文档、治理语义没有统一。

## 18.1 External Benchmark 更要小心

未来 IDA / LongMemEval 的 native evaluator 在 Runtime 外。

Runtime 不能把 benchmark PASS/FAIL 回灌到 Memory，作为下一 case 的 hidden evaluator signal。

推荐拆成：

```text
runtime_artifact_accepted
external_answer_adopted
```

后者不进入 replay eligibility。

---

# 19. 当前 Mainline 实际只 Commit Terminal Executor Recipe

`_commit_verified_memory()` 会找最后一个：

```text
role == executor
```

的 artifact。

所以当前 Adaptive Memory mainline 真正持久化的主角是：

```text
execution recipe
```

而不是通用：

```text
fact / evidence / route hint / outcome
```

虽然 `MemoryType` enum 已经定义了很多类型，但还没有一个统一的 Memory Admission/Writer 去生产它们。

因此不建议现在继续扩 enum，而应先把：

```text
producer
commit policy
scope
projection
consumer
```

闭环。

---

# 20. Persistent Store：当前实际上是多份状态

当前有：

```text
in-memory dict
commit_registry.json
embedding_registry.json
SQLite
FAISS
```

严格说：

```text
metadata = dict + JSON + SQLite
vector = dict + JSON + FAISS
```

## 20.1 Restart Source of Truth 实际是 JSON

`load_persisted_state()` 会：

```text
read embedding_registry.json
read commit_registry.json
    ↓
restore dict
    ↓
reindex SQLite
```

所以实际：

```text
JSON registry
```

是 restart source of truth，SQLite 是 derived search index。

现有 `hybrid-retrieval.md` 的措辞容易让人误以为 SQLite 是 canonical persistent metadata store，需要修正。

---

# 21. P1：每次写都重写整个 JSON Registry

`_persist_commit()`：

```text
read whole registry
update one key
write whole registry
```

Embedding 也是一样。

假设 N 条 memory，每次 append 都 O(N)，累计写入约：

```text
1 + 2 + ... + N
≈ O(N²)
```

Embedding JSON 更糟：如果未来使用 Qwen embedding，每条 vector 有大量 float，把所有向量存成 pretty JSON 并在每次写入时整体重写，不适合作为长期 memory store。

---

# 22. P1：当前双写没有 Transactional Consistency

Commit 路径大致：

```text
put_embedding()
    ↓
embedding JSON write

commit_candidate()
    ↓
SQLite metadata write
    ↓
commit JSON write
```

中间任何 crash 都可能产生：

```text
orphan embedding
metadata/index divergence
```

并发 writer 也没有正式看到：

```text
file lock
SQLite WAL
busy_timeout
single-writer actor
跨 commit unit transaction
```

## 22.1 当前比赛最合适的 Store 方案

不需要上 Postgres/Qdrant/Milvus。

推荐：

```text
SQLite = authoritative metadata store
FTS5 = lexical index
CAS files = large payload / recipe
FAISS or numpy = optional vector index
JSON = audit/export snapshot only
```

SQLite 开：

```text
WAL
busy_timeout
transaction
schema_version
```

大 payload，例如 Python source、DSL、长 evidence，不要塞进 JSON metadata，写入 CAS，Memory 只存 ref/hash。

---

# 23. P1：FAISS 性能描述是错的

源码注释把当前 FAISS index 写成：

```text
O(log N) embedding search
```

但实际使用：

```python
faiss.IndexFlatIP
```

这是 exact flat inner-product search，复杂度仍然是：

```text
O(N × D)
```

不是 O(log N)。

而且 `_faiss_score_map()` 当前：

```python
search(q, n_indexed)
```

也就是直接返回全部向量，然后 `_rank_commits_by_vector()` 仍然遍历 commits。

所以当前 FAISS 的主要价值是 native/vectorized dot product，不是 sublinear ANN。

---

# 24. P1：Sequential FAISS Rebuild 可能 O(N²)

每次：

```text
put_embedding()
```

都会：

```text
_faiss_dirty = True
```

下一次 query：

```text
重建整个 IndexFlatIP
```

连续任务 Memory 大小从 1、2、3 … N 增长时，累计 rebuild 工作量：

```text
1 + 2 + ... + N
≈ O(N²)
```

当前 6-case benchmark 看不出来，LongMemEval 这种长序列才会暴露。

## 24.1 现在要不要立刻上 HNSW？

不建议。

先修：

```text
错误复杂度 claim
index lifecycle
encoding/dims 分区
top-k search
```

当 LongMemEval profile 证明 dense search 是瓶颈，再考虑 HNSW/IVF/external vector DB。

---

# 25. P1：FAISS 没按 Embedding Signature 分区

`_build_faiss_index()` 当前遍历全部 `self.embeddings`，没有按：

```text
encoding
dims
```

分组。

Query 时才过滤 dims/encoding。

如果未来同一个 store 同时存在：

```text
old hashed-bow-16
new qwen-1024
```

构造 `np.array(vecs)` 就可能失败或产生非法矩阵。

推荐 index key：

```text
(embedding_encoding, dims)
```

例如：

```text
faiss_indices[("qwen3-embedding-0.6b", 1024)]
```

---

# 26. 一个潜在 FAISS ID Map 问题

当前：

```python
for i, (emb_id, emb) in enumerate(self.embeddings.items()):
    if not emb.vector:
        continue
    vecs.append(list(emb.vector))
    id_map[i] = emb_id
```

如果 empty vector 被 skip，FAISS packed row id 是 0,1,2...，但 `i` 可能跳号，导致 mapping 错位。

当前内置 encoder 基本不会产生 empty vector，所以不一定立即触发，但正确写法应是：

```python
faiss_id = len(vecs)
vecs.append(...)
id_map[faiss_id] = emb_id
```

---

# 27. Hybrid Retrieval：Safety 是对的，但 Recall 有截断风险

当前：

```python
source_limit = query.limit * 5
```

keyword/tags/vector 各取有限候选，然后 RRF，最后才做完整 compatibility。

Safety 没问题：高排名 incompatible memory 不能绕过 gate。

但 Recall 可能有问题。

例如：

```text
query.limit = 3
source_limit = 15
```

如果每一路前 15 名都不兼容，而第 16 名才是兼容项，最终会 0 match。

推荐：

```text
Namespace
MemoryKind
CommitStatus
basic task/capability compatibility
    ↓
retrieval
    ↓
RRF
    ↓
full replay compatibility
```

即：**粗过滤前置，精 compatibility 后置**。

---

# 28. RRF 本身无需现在推翻

BM25、tag overlap、cosine 的原始 score 空间不同，用 rank fusion 比强行 normalization 更稳。

当前 fixed `k=60` 和 equal weight 的限制包括：

1. 三路等权；
2. 没有 relevance threshold；
3. 没有 temporal/freshness signal。

不建议现在就加 learned reranker。

先做 A/B；必要时再加：

```text
source-specific minimum confidence
query-kind source weights
recency feature
```

---

# 29. FTS 对中文/非 ASCII 需要单独验证

当前 `_fts_query()`：

```python
re.findall(r"[a-z0-9_]+", keyword.lower())
```

英文没问题。

中文 query 会得到空 token list，然后 fallback 成整个 phrase 给 FTS5。

这是否有足够 recall 不能靠猜。

当前 competition / external benchmark 主要英文，所以不是 P0；但未来不要仅凭“用了 FTS5”就宣称 multilingual lexical retrieval。

---

# 30. P2：没有完整 Lifecycle

当前 Memory lifecycle 大体：

```text
CANDIDATE
COMMITTED
INVALIDATED
```

缺少：

```text
SUPERSEDED
EXPIRED
```

`INVALIDATED` 不能表达“过去正确、现在过时”。

例如：

```text
v1: service endpoint = A
v2: service endpoint = B
```

v1 不应该被当成生成错误，而应该是 superseded historical fact。

Graphiti 最值得借的正是：

```text
validity window
superseded not deleted
provenance
```

StateBus 不需要上 Graph DB，只需要借：

```text
valid_from
valid_to
superseded_by
source provenance
```

推荐 Lifecycle：

```text
ACTIVE
SUPERSEDED
INVALIDATED
EXPIRED
```

---

# 31. P2：没有 Dedup

当前 memory ID：

```text
memory:{task_id}:{artifact_hash_prefix}
```

不同 task 即使产生完全相同 recipe，也会生成不同 memory。

长期运行会出现大量重复：

```text
same strategy
same recipe
same gotcha
```

推荐 Content Identity：

```text
content_hash
+
namespace
+
memory_kind
+
compatibility_fingerprint
```

形成 `memory_content_key`。

如果内容相同，可以 refresh recency / add provenance / increase evidence count，而不是重复保存 payload。

---

# 32. P2：Invalidated Embedding 不会 GC

`invalidate()` 只把 MemoryCommit 设为 INVALIDATED，但 embedding 仍留在：

```text
self.embeddings
embedding_registry.json
FAISS build source
```

Correctness 没问题，因为 `_rank_commits_by_vector()` 会跳过 invalidated commit；但 storage/index/rebuild cost 会持续增加。

需要 GC：

```text
orphan embedding
superseded payload
expired memory
invalidated recipe source
```

---

# 33. Persistent Artifact Path 不是稳定 Identity

Memory metadata 目前保存：

```text
artifact_root_id
artifact_relpath
artifact_blob_hash
```

如果 workspace cleanup、run root moved、artifact archived，本地 path 会失效。

Recipe/Artifact memory 更适合：

```text
CAS ref
content hash
```

作为 identity，本地 path 只是 materialization location。

---

# 34. `MemoryRef.match_payload()` 做对了一件事

它不会把整个 metadata 都放进 match/audit payload，只保留有限 replay/runtime keys。

这是好设计，因为 candidate/audit surface 不应该默认泄露巨大 recipe/payload。

但随后 `_memory_inputs_for_step()` 又从 canonical commit 中把 `execution_recipe` 取出，加回 role input。

因此需要正式区分：

```text
Audit Projection
≠
Role Projection
```

并增加 `MemoryProjectionReceipt`，记录某个 consumer 实际看到了什么。

---

# 35. P1：Memory 只有 Count Budget，没有 Prompt-visible Budget

`MemoryQuery` 有：

```text
limit
```

但没有：

```text
max_visible_bytes
max_visible_tokens
```

由于 role input 可能含 recipe，即使 limit=5 也可能很大。

LongMemEval-V2 的官方 harness 明确区分：

```text
memory.query() 返回若干 context items
    ↓
--memory-context-max-tokens
    ↓
reader
```

StateBus 也应该区分：

```text
candidate budget
selection budget
role-visible byte/token budget
```

---

# 36. Current Adaptive Memory Benchmark 到底证明了什么

`statebus/benchmark/adaptive_memory.py` 当前：

```text
5 个 financial sequential cases
+
1 个 incompatible runtime negative
```

所有 case 共用一个 `memory_root`，并使用 `validated_replay`。

它可以证明：

```text
memory persisted across fresh runners
compatible candidate can be found
runtime-signature-incompatible candidate can be rejected
recipe reuse can skip generation
current task can still recompute + validate
memory commit can continue
```

这些都是真价值。

但不能证明：

```text
Memory generalizes across arbitrary tasks
```

因为当前是：

```text
same formal family
closed canonical spec
controlled quality validator
shared financial sequence
```

更不能用当前 `behavioral_effect_count` 证明 Assist 真正改变了模型行为。

---

# 37. Controlled Memory A/B 应该补什么

建议同一 sequence：

```text
A. no memory
B. assist
C. validated recipe replay
```

控制：同模型、同数据、同 task order。

测：

```text
quality

Planner tokens
Retriever tokens
Executor generation tokens
Summarizer tokens

Memory query latency
Executor generation latency
Sandbox execution latency
E2E latency

recipe replay count
code generation skipped
repair count
negative transfer
```

Exact Recipe Replay 也应单独测：same contract/schema/lineage，证明“跳过 source generation + 当前输入重新执行 + 结果 hash stable”。

不要把它叫 exact result replay，除非旧 artifact 被直接恢复。

---

# 38. 外部 Benchmark：LongMemEval-V2 是最合适的下一站

官方 LongMemEval-V2 当前公开说明：

```text
451 manually curated questions
5 memory abilities
up to 500 trajectories per haystack
up to 115M tokens
web + enterprise
small + medium public tiers
```

五类能力：

```text
Static state recall
Dynamic state tracking
Workflow knowledge
Environment gotchas
Premise awareness
```

这与 StateBus 的 strategy/evidence/route hint/recipe 路线非常契合。

---

# 39. LongMemEval-V2 最值得借的是 API / Privacy Boundary

官方 Memory backend 接口核心：

```python
insert(trajectory)
query(query, query_image=None)
```

Query 时 backend 只看到：

```text
question text
optional question image
opaque query_invocation_id
```

而：

```text
question ID
question type
gold answer
evaluator config
```

由 harness 私有保存。

官方 `tests/test_query_privacy.py` 甚至专门构造：

```text
secret question id
secret answer
secret evaluator
secret original goal
```

然后断言 Memory backend 只收到 opaque invocation id。

StateBus External Memory 应直接仿这类测试：

```text
test_memory_query_never_receives_private_gold
test_memory_query_never_receives_benchmark_case_id
test_memory_query_never_receives_question_type
test_memory_query_never_receives_evaluator_name
test_memory_commit_never_receives_native_grade
```

---

# 40. 但 Current StateBus 不能直接接 LongMemEval

当前 Adaptive mainline 主要 commit：

```text
terminal execution recipe
```

LongMemEval 需要 ingest：

```text
历史 agent trajectories
```

所以还缺：

```text
Trajectory
    ↓
Memory Ingest Adapter
    ↓
typed experiences
    ↓
Memory Store
```

第一版不用做 AgentRunbook 那么复杂，可以先只有：

```text
Raw Experience Summary
Procedure / Gotcha Note
```

后续再扩：

```text
Raw State
Event
Procedure
Gotcha
```

---

# 41. AgentRunbook-R 的核心启发

它显式分：

```text
raw state slices
state-transition events
procedure/hint notes
```

并分别生成不同 retrieval query。

这说明长期 memory 的关键往往不是：

```text
换一个更强 vector index
```

而是：

> **Memory Representation 与 Query Intent 对齐。**

---

# 42. Mem0：值得借什么，不值得借什么

Mem0 2026 README 公开说明新一代 memory algorithm 强调：

```text
single-pass ADD-only extraction
agent-generated facts
entity linking
semantic + BM25 + entity matching
temporal reasoning
```

最值得 StateBus 借的是：

### Scope

```text
user_id
agent_id
run_id
filters
```

### Multi-signal

StateBus 已经有 semantic + keyword + tags，方向并不落后。

### Temporal

StateBus 当前明显欠缺。

但 Mem0 README 也明确说明它的 benchmark headline 包含 managed proprietary optimizations，所以不要直接拿数字与 StateBus OSS 比较。

---

# 43. LangGraph：最值得借的是 Namespace + TTL Separation

LangGraph `BaseStore` 支持：

```text
namespace: tuple[str, ...]
```

Memory 可以跨 thread 共享，但明确作用域。

另外 TTL 是独立的 Store capability，而 semantic index 是 optional retrieval capability。

这非常适合 StateBus：

```text
Lifecycle
≠
Retrieval
≠
Scope
```

三者不要混在一起。

---

# 44. Graphiti：只借 Temporal Validity / Provenance

Graphiti 的核心思想：

```text
facts have validity windows
new fact supersedes old fact
history preserved
full provenance to episodes
```

StateBus 当前不需要 Graph DB / ontology / graph traversal。

只借：

```text
valid_from
valid_to
superseded_by
provenance
```

就够了。

---

# 45. 推荐最终 Memory Runtime 架构

```text
                      ┌────────────────────┐
Task / STEP_READY ───▶│ MemoryAdmission    │
                      └─────────┬──────────┘
                                │
                                ▼
                      ┌────────────────────┐
                      │ MemoryQueryBuilder │
                      └─────────┬──────────┘
                                │
                                ▼
                      ┌────────────────────┐
                      │ Namespace / ACL    │
                      └─────────┬──────────┘
                                │
                                ▼
                      ┌────────────────────┐
                      │ Kind / Coarse Gate │
                      └─────────┬──────────┘
                                │
               ┌────────────────┼────────────────┐
               ▼                ▼                ▼
          Keyword/FTS        Tags          Dense Search
               └────────────────┼────────────────┘
                                ▼
                          RRF / Rerank
                                │
                                ▼
                   ┌────────────────────────┐
                   │ Compatibility Policy   │
                   │ Assist / Recipe / Art. │
                   └────────────┬───────────┘
                                │
                                ▼
                   ┌────────────────────────┐
                   │ Projection / Binding   │
                   └────────────┬───────────┘
                                │
                      MemoryBindingReceipt
                                │
                                ▼
                       CapabilityGrant
                                │
                                ▼
                          Role / Runtime
                                │
                                ▼
                    MemoryConsumptionReceipt
                                │
                                ▼
                    Verified Artifact/Recipe
                                │
                                ▼
                     MemoryCommitPolicy
                                │
                                ▼
                   Persistent Store/Lifecycle
```

四条原则：

```text
Scope authorizes visibility.
Relevance discovers candidates.
Compatibility authorizes reuse.
Projection authorizes what consumer sees.
```

---

# 46. 推荐 Contract：MemoryNamespace

```python
@dataclass(frozen=True)
class MemoryNamespace:
    tenant_id: str
    workspace_id: str
    project_id: str = ""
    agent_scope: str = ""
    session_scope: str = ""
```

---

# 47. 推荐 Contract：MemoryRecord

建议逐步替代 overloaded `MemoryRef`：

```python
@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    namespace: MemoryNamespace

    memory_kind: str
    summary: str

    payload_ref: str
    payload_hash: str

    source_task_id: str
    source_role: str
    provenance_refs: tuple[str, ...]

    task_contract_hash: str
    compatibility_fingerprint: str

    created_at_ns: int
    valid_from_ns: int = 0
    valid_to_ns: int = 0
    superseded_by: str = ""

    lifecycle_state: str = "active"

    retrieval_key_refs: tuple[str, ...] = ()
    verification_strength: str = ""

    metadata: dict[str, object] = field(default_factory=dict)
```

---

# 48. 推荐 Contract：MemoryQueryIntent

```python
@dataclass(frozen=True)
class MemoryQueryIntent:
    task_id: str
    step_id: str

    namespace: MemoryNamespace
    task_contract_hash: str

    consumer_role: str
    logical_capability_id: str

    query_text: str
    tags: tuple[str, ...]

    allowed_memory_kinds: tuple[str, ...]
    allowed_reuse_modes: tuple[str, ...]

    max_candidates: int
    max_selected: int

    max_visible_bytes: int
    max_visible_tokens: int
```

---

# 49. 推荐 Contract：MemoryCompatibilityFingerprint

```python
@dataclass(frozen=True)
class MemoryCompatibilityFingerprint:
    task_contract_kind: str

    logical_capability_id: str
    provider_id: str

    input_schema_digest: str
    output_contract_version: str

    validator_digest: str
    runtime_signature: str

    policy_digest: str = ""
```

不同 MemoryKind 不需要全部字段 exact 匹配，具体由 type-specific compatibility policy 决定。

---

# 50. 推荐 Contract：MemoryProjectionReceipt

```python
@dataclass(frozen=True)
class MemoryProjectionReceipt:
    task_id: str
    step_id: str
    memory_id: str

    consumer_role: str

    projected_fields: tuple[str, ...]
    omitted_fields: tuple[str, ...]

    projected_payload_hash: str

    visible_bytes: int
    visible_token_estimate: int

    projection_policy_version: str
    receipt_hash: str
```

---

# 51. 推荐 Contract：MemoryBindingReceipt

```python
@dataclass(frozen=True)
class MemoryBindingReceipt:
    task_id: str
    step_id: str
    attempt_id: str

    query_hash: str

    selected_memory_ids: tuple[str, ...]
    projection_receipt_hashes: tuple[str, ...]

    reuse_mode_by_memory_id: dict[str, str]
    rejected_reasons: dict[str, tuple[str, ...]]

    policy_version: str
```

---

# 52. 推荐 Contract：VerifiedExecutionRecipe

直接承接 Round 03：

```text
execution_kind
capability_id
output_contract_version

source_ref / source_hash

policy_digest
runtime_signature
validator_digest
quality_report_hash

input_contract_fingerprint
verification_strength
execution_receipt_hash
```

可执行 source 放 CAS，Memory 只存 ref/hash。

---

# 53. 推荐 Contract：MemoryCommitReceipt

```python
@dataclass(frozen=True)
class MemoryCommitReceipt:
    memory_id: str

    source_artifact_hash: str
    source_recipe_hash: str

    namespace_hash: str
    task_contract_hash: str

    verification_strength: str

    dedup_decision: str
    superseded_memory_ids: tuple[str, ...]

    lifecycle_state: str

    private_evaluator_input_count: int

    receipt_hash: str
```

External lane hard gate：

```text
private_evaluator_input_count == 0
```

---

# 54. 存储建议：当前项目不要引入分布式数据库

比赛阶段推荐：

```text
SQLite authoritative metadata
+ FTS5
+ CAS payloads
+ small-scale exact vector search
```

不要为了“看起来更像 production”上：

```text
Milvus
Qdrant
Elastic cluster
Neo4j
```

除非 benchmark/profile 明确证明 SQLite + local vector 不够。

---

# 55. Vector Index Strategy

阶段 1：

```text
N 小
    → exact dense matrix / IndexFlatIP
```

阶段 2：当 LongMemEval profile 证明 vector search 是瓶颈：

```text
HNSW / IVF
```

不要“因为用了 FAISS”就宣称 sublinear scale；当前 IndexFlatIP 仍然是 exact linear search。

---

# 56. Temporal Policy

第一版只需要：

```text
created_at
valid_from
valid_to
superseded_by
```

Query 默认 prefer ACTIVE/current；若用户明确问历史，再允许匹配 superseded records。

---

# 57. Verification Strength 与 Replay Eligibility

延续 Round 03：

```text
STRUCTURAL
CONTRACT_VALIDATED
INDEPENDENT_RECOMPUTATION
```

建议：

### ASSIST

某些 memory kind 只需要 STRUCTURAL + provenance 即可。

### Recipe Recompute

至少 CONTRACT_VALIDATED；高风险 recipe 可要求 INDEPENDENT_RECOMPUTATION。

### Artifact Restore

要求最强 exact identity。

---

# 58. Migration Plan

不要一次重写。

## M0 — Round 03 Recipe Identity

必须最先：

```text
llm_codeact.py
adaptive_dispatcher.py
adaptive_mainline.py
```

Gate：

```text
recipe.source_hash
==
final verified source hash
```

---

# 59. M1 — Evidence / Metric Semantics

先不改 runtime 行为，只修证据语义。

### M1.1

把：

```text
memory_behavioral_effect_count
```

改成：

```text
memory_input_augmented_count
```

### M1.2

增加：

```text
counterfactual_evaluated
decision_surface_changed
generation_skipped
artifact_reused
```

### M1.3

把：

```text
skipped_step_count
```

改成：

```text
generation_skipped_count
```

### M1.4

文档区分：

```text
Adaptive Recipe Replay
vs
History Artifact Replay
```

### M1.5

修正文档中的：

```text
answer_adopted
SQLite source-of-truth
FAISS O(logN)
```

这是 Round 04 最推荐的第一刀，因为它不大改行为，却先保证比赛 evidence 不夸大。

---

# 60. M2 — Replay Taxonomy Separation

定义：

```text
MemoryKind
ReuseMode
CompatibilityLevel
```

同时保留旧 `MemoryType / ReplayClass` 兼容层，不一次性删除。

---

# 61. M3 — Independent Memory Plane

把 `MemoryQuery` 从 `_consume_retrieval_semantic_state()` 移出来。

新增：

```text
MemoryAdmissionPolicy
MemoryQueryBuilder
```

位置：

```text
STEP_READY
```

并让 Memory commit 不再依赖 `memory_queries_by_task`。

自己生成明确的 memory retrieval key embedding。

---

# 62. M4 — Scope + Projection + Binding

增加：

```text
MemoryNamespace
MemoryProjectionReceipt
MemoryBindingReceipt
```

Memory selection 在 Grant 前完成。

Grant 增加：

```text
memory_binding_receipt_hash
```

或：

```text
authorized_memory_ref_ids
```

ASSIST 不再携带 raw execution recipe。

---

# 63. M5 — Store Hardening

### M5.1
SQLite authoritative。

### M5.2
WAL + busy timeout + transaction。

### M5.3
JSON registry 改成 audit snapshot。

### M5.4
Large payload → CAS。

### M5.5
FAISS index 按 encoding+dims 分区。

### M5.6
修正 O(logN) 错误注释和 rebuild/search-all 问题。

---

# 64. M6 — Lifecycle / Temporal

增加：

```text
ACTIVE
SUPERSEDED
INVALIDATED
EXPIRED
```

随后做：

```text
dedup
GC
TTL optional
```

---

# 65. M7 — External LongMemEval-V2

最后进入。

先做 Small tier，不直接冲 Medium / 115M。

---

# 66. 推荐第一个 Codex Slice

## `MEMORY-R04-M1-EVIDENCE-SEMANTICS`

Scope 只改：

```text
statebus/memory/models.py
statebus/runtime/adaptive_dispatcher.py
statebus/benchmark/adaptive_memory.py
docs/implementation/memory/*
tests/*
```

目标：

1. `role_input_augmented` 不再算 behavioral effect。
2. Recipe reuse 明确记录 `generation_skipped / recipe_recomputed / runtime_step_executed`。
3. Docs 区分 Adaptive Recipe Replay 与 History Artifact Replay。
4. Docs 修正 `answer_adopted` commit semantics。
5. Docs/code 修正 `IndexFlatIP O(logN)` claim。
6. 不做大范围 Runtime 行为变化。

---

# 67. 第二个 Slice

## `MEMORY-R04-M2-RECIPE-IDENTITY`

与 Round 03 C0 合并：

```text
Final Verified Source
    ↓
VerifiedExecutionRecipe
    ↓
Memory Commit Identity Gate
```

---

# 68. 第三个 Slice

## `MEMORY-R04-M3-MEMORY-PLANE-DECOUPLING`

只做：

```text
MemoryQueryBuilder
MemoryAdmission
```

把 Memory Query 从 Retriever 解耦。

---

# 69. 第四个 Slice

## `MEMORY-R04-M4-SCOPE-BINDING`

增加：

```text
Namespace
BindingReceipt
ProjectionReceipt
```

并把 memory binding 纳入 CapabilityGrant authority chain。

---

# 70. 第五个 Slice

## `MEMORY-R04-M5-STORE-HARDENING`

把 SQLite 升为 source-of-truth，解决事务/JSON 写放大/FAISS 生命周期问题。

---

# 71. 推荐新增测试矩阵

## Authority / Scope

```text
test_memory_namespace_mismatch_never_enters_candidate_pool
test_memory_cross_workspace_never_role_visible
test_memory_binding_receipt_matches_grant
test_unbound_memory_ref_cannot_be_consumed
```

## Query Plane

```text
test_memory_query_works_without_retriever_step
test_memory_commit_works_when_memory_query_disabled
test_executor_memory_query_uses_step_goal_not_retriever_query
test_memory_query_filters_memory_kinds
```

## Projection

```text
test_assist_projection_omits_execution_recipe
test_replay_recipe_is_runtime_only
test_summarizer_never_receives_python_source_memory
test_memory_projection_byte_budget
test_memory_projection_token_budget
```

## Compatibility

```text
test_strategy_assist_survives_validator_version_change
test_recipe_replay_rejects_validator_version_change
test_route_hint_not_bound_to_output_contract
test_artifact_restore_requires_exact_lineage
```

## Evidence

```text
test_assist_injection_is_not_behavioral_effect_without_counterfactual
test_recipe_replay_counts_generation_skip_not_step_skip
test_behavioral_effect_requires_counterfactual_or_mechanistic_skip
```

## Store

```text
test_memory_commit_atomic
test_concurrent_memory_writers_do_not_corrupt_store
test_sqlite_restart_source_of_truth
test_json_snapshot_failure_does_not_corrupt_commit
test_orphan_embedding_gc
test_faiss_partition_by_encoding_dims
test_faiss_empty_vector_mapping
```

## Lifecycle

```text
test_superseded_not_selected_as_current
test_historical_query_can_select_superseded
test_invalidated_never_selected
test_expired_ephemeral_swept
test_duplicate_recipe_deduplicates_payload
```

## External Privacy

```text
test_external_memory_query_context_is_opaque
test_external_memory_query_has_no_question_id
test_external_memory_query_has_no_question_type
test_external_memory_query_has_no_gold_answer
test_external_memory_query_has_no_eval_function
test_native_grade_not_used_for_memory_commit
```

---

# 72. LongMemEval-V2 External Plan

## E0 — Integration / Privacy

只验证：

```text
insert/query API
opaque query context
no grader leakage
memory context budget
```

## E1 — no_retrieval

建立官方 baseline。

## E2 — Simple StateBus Memory

```text
trajectory summary
+
dense retrieval
```

先证明 adapter / store / query latency 正常。

## E3 — Typed Experience Memory

```text
procedure
gotcha
state/event
```

## E4 — Hybrid

```text
keyword
semantic
tags/entities
temporal
```

---

# 73. External 评测核心指标

至少：

```text
answer accuracy
memory query latency
memory context tokens
```

严格参加官方 leaderboard 时再计算官方 LAFS。

StateBus 自己额外记录：

```text
candidate count
scoped candidate count
compatible count
projected count
visible bytes/tokens

ingest time
store bytes

query latency:
  lexical
  vector
  fusion
  projection

negative transfer
stale memory rejection
procedure/gotcha/state contribution
recipe generation skip
counterfactual assist effect
```

---

# 74. 比赛 Evidence 不要只写 Memory Hit Rate

不要写：

```text
Memory hit = 80%
```

应该写 Funnel：

```text
100 tasks

82 issued memory queries
68 had candidates
51 had compatible candidates
33 received role-visible ASSIST
17 used verified recipe recomputation
17 skipped executor code generation
17 still reran current input + validator
15 passed quality
2 replay attempts were rejected and fell back to fresh generation
```

再加 Cost / Quality：

```text
Executor LLM calls:
baseline 100
adaptive 83

Completion tokens:
-18%

Median latency:
-XX%

Quality:
baseline X
memory X
```

这才真正对应赛题中的 shared memory / reuse / low-overhead evidence。

---

# 75. 当前应该保留的设计

不要推倒重写以下部分：

```text
MemoryQuery typed contract

keyword + tag + dense
RRF

candidate pool
source ranks
compatibility decision receipt

Runtime signature gate
output contract gate
validator gate
schema / lineage gate

MemoryConsumptionRecord 概念
persistent store 概念
negative incompatible fixture

current-input recomputation
replay 后重新 quality validate
```

当前最值得保留的原则是：

> **Semantic similarity discovers candidates; Runtime compatibility authorizes reuse.**

升级后变成：

> **Scope authorizes visibility; relevance discovers candidates; compatibility authorizes reuse; projection authorizes what the consumer sees.**

---

# 76. 当前不要做的事情

不要：

```text
换 Milvus / Qdrant 只为了“scale”
上 Neo4j / Graphiti graph DB
创建 Memory Agent
让 LLM 决定 memory ACL
让 ASSIST prompt 看到 raw executable recipe
把 native benchmark grade 回灌 Memory
继续无约束增加 MemoryType enum
把 IndexFlatIP 描述成 sublinear
把 recipe recompute 叫 result replay
把 role_input_augmented 叫 proven behavioral effect
```

---

# 77. Memory 在 Routing Architecture 中的正确位置

推荐：

```text
PlanSelector
    ↓
Approved Logical Plan
    ↓
STEP_READY
    ↓
Memory Admission
    ↓
Execution Binding
    ↓
Memory Binding
    ↓
CapabilityGrant
    ↓
Provider
```

Memory 可以提供：

```text
route hint
prior strategy
```

但最终 authority owner 仍是：

```text
PlanPolicy
ExecutionBindingPolicy
Runtime
```

Memory 不应该成为第二个 Planner。

---

# 78. 最适合比赛材料的 Memory Story

修完后可以准确讲：

> StateBus does not treat shared memory as a raw vector database. Historical state first enters a typed, scoped memory store. A new task retrieves candidates through hybrid lexical/tag/semantic search. Runtime then applies type-specific compatibility and per-role projection. Executable recipes remain opaque Runtime objects rather than prompt text. Only verified recipes can bypass code generation, and they are recomputed on current verified inputs under the same sandbox and validator. Every query, rejection, projection, consumption and reuse decision is auditable.

中文：

> **StateBus 的共享记忆不是“把历史文本做向量检索后塞回 Prompt”。Runtime 将历史经验保存为带类型、作用域、来源和验证状态的 Memory Ref；新任务先经过命名空间与类型过滤，再进行关键词/标签/语义混合召回，随后由兼容门决定仅作为辅助上下文、复用已验证执行 recipe，或拒绝复用。可执行 recipe 不直接暴露给 Agent，而由 Runtime 绑定到当前 CapabilityGrant，并在当前输入上重新执行和验证。**

---

# 79. 当前还不能硬说的两句话

在 M0/M1 前不要说：

```text
Memory behavioral effect has been proven.
```

因为当前 effect metric 不是 counterfactual。

也不要说：

```text
Validated replay always replays the exact verified program.
```

因为 Round 03 recipe source identity 仍有 gap。

当前可以准确说：

```text
StateBus has persistent typed memory contracts,
hybrid retrieval,
compatibility-gated reuse,
runtime-signature negative rejection,
and current-input recipe recomputation.
```

---

# 80. 最终评级

| 维度 | 当前评价 |
|---|---|
| Typed Memory Contract | **中强** |
| Hybrid Retrieval | **中强** |
| Candidate Auditability | **强** |
| Replay Compatibility | **强，但过于统一** |
| Recipe Recompute Safety | **强，受 Round 03 source identity bug 影响** |
| Memory Namespace / ACL | **缺失** |
| Per-role Projection | **弱** |
| Memory Binding Authority | **不完整** |
| Behavioral Effect Evidence | **当前不成立** |
| Commit Governance | **中等，文档/字段语义不一致** |
| Persistent Store Correctness | **小规模可用，长期/并发需加固** |
| Vector Index Scalability | **当前仍 exact linear，且有 rebuild 问题** |
| Temporal Memory | **缺失** |
| Dedup / Lifecycle / GC | **缺失** |
| External Generalization | **尚未验证** |
| LongMemEval Readiness | **需先补 external ingest + privacy boundary** |
| Competition Potential | **很高** |

---

# 81. 最终判断

Round 04 最重要的判断不是：

```text
Memory 要不要换一个更强 embedding
```

也不是：

```text
FAISS 要不要换 Qdrant
```

真正的问题是：

```text
Memory 现在已经有“检索 + replay”的功能，
但还没有完全成为一个独立、作用域明确、
per-consumer 授权、可证明真实收益的 Runtime Plane。
```

推荐优先顺序：

```text
Round03 C0 Verified Recipe Identity
        ↓
M1 Evidence / Metric Semantics
        ↓
M2 Replay Taxonomy
        ↓
M3 Memory Plane Decoupling
        ↓
M4 Namespace + Projection + Binding
        ↓
M5 Store Hardening
        ↓
M6 Lifecycle / Temporal
        ↓
M7 LongMemEval-V2
```

不要反过来先接 LongMemEval，然后再发现 query 只能挂在 Retriever、memory 没 namespace、recipe 全塞 prompt、metric 说不清。

---

# Appendix A — 本轮主要 StateBus 源码

```text
statebus/memory/models.py
statebus/memory/store.py
statebus/memory/embedding.py

statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/replay.py
statebus/runtime/workspace.py

statebus/contracts/adaptive.py

statebus/benchmark/adaptive_memory.py

tests/test_hybrid_memory_query.py
tests/test_memory_runtime.py
tests/test_memory_store.py

docs/implementation/memory/hybrid-retrieval.md
docs/implementation/memory/compatibility-and-consumption.md
docs/implementation/memory/commit-and-replay.md
```

---

# Appendix B — 外部 GitHub 对照

## LongMemEval-V2

Repository:

```text
https://github.com/xiaowu0162/LongMemEval-V2
```

本轮主要参考：

```text
README.md
tests/test_query_privacy.py
memory_modules/agentrunbook_r.py
```

值得吸收：

```text
opaque query context
benchmark-private evaluator isolation
memory-context token budget
typed memory pools
memory query latency evaluation
```

## Mem0

Repository:

```text
https://github.com/mem0ai/mem0
```

值得吸收：

```text
user/agent/run scope
multi-signal retrieval
entity signal
temporal retrieval
```

注意：README 的 2026 benchmark numbers 包含 managed proprietary optimizations，不能拿来和 StateBus OSS 直接比较。

## LangGraph

Repository:

```text
https://github.com/langchain-ai/langgraph
```

值得吸收：

```text
namespace-scoped store
semantic index optional
TTL lifecycle independent from semantic retrieval
```

## Graphiti

Repository:

```text
https://github.com/getzep/graphiti
```

只建议借：

```text
temporal validity
superseded history
provenance
```

不建议当前项目引入 Graph DB。

---

# Appendix C — Round 04 一句话

> **StateBus 当前 Memory 已经不是简单“embedding + RAG”：它有 typed memory、hybrid retrieval、compatibility gate 和 verified-recipe recomputation；但要真正升级成 Shared Memory Runtime，必须从“Retriever 附属查询 + 全量 role injection + 统一 replay gate”演进为“独立 Memory Plane + Namespace Authority + Type-specific Compatibility + Per-consumer Projection + Verified Recipe Binding + 可证明 Consumption Effect”。**
