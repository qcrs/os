# StateBus 全系统审计 Master Map + Batch 01
## Task Admission / Plan Authority / Replan / Runtime Grant 第一批源码审计

> 项目：`qcrs/os`  
> 分支：`master`  
> 源码基线：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 日期：2026-09-03

---

# 0. 结论

现有 6 个 Round 主要覆盖“子系统”，但还不足以覆盖 StateBus 的完整 E2E Runtime 主链。

建议把系统按 11 个 Runtime Plane 分层，并额外增加 5 条独立审计链 + 1 条横向 Security/Privacy 审计。

当前第一批优先审计：

> **Task → Task Contract → Adaptive Envelope → PlanProposal → Plan Compiler → PlanPolicy → ApprovedPlan → CapabilityGrant → Replan**

原因：Memory、CodeAct、IPC、Artifact 都建立在这条 Authority Chain 上。如果这里的身份、repair/replan、plan provenance 不清楚，后面所有局部安全合同都会失去统一上游。

---

# 1. 全系统分层

## Layer 0 — Task Admission / Identity

负责：

- raw user/external task；
- public task constraints；
- input assets；
- task/run/session identity；
- benchmark/private visibility boundary。

核心对象：

- `CanonicalTaskSpec`
- future `ExternalTaskEnvelope`
- future `InputAssetRef`
- future `TaskContractIdentity`

---

## Layer 1 — Planning / Routing / Role Topology

负责：

- PlanSelector；
- Planner；
- role omission/selection；
- logical capability selection；
- dependency DAG；
- semantic replan。

核心对象：

- `SemanticTaskPlan`
- `PlanProposal`
- `PlanPolicyReport`
- `ApprovedPlan`

---

## Layer 2 — Capability / Authority / Protocol

负责：

- capability discovery；
- schema/version；
- capability registry；
- provider binding；
- `CapabilityGrant`；
- handshake；
- fallback authority。

这对应原计划中的 Protocol / Capability / Handshake Round。

---

## Layer 3 — Evidence / Provenance / Hydration

负责：

- retrieval request；
- candidate pool；
- EvidencePack；
- locator；
- projection；
- coverage；
- hydration；
- ClaimSet；
- citation / numeric provenance。

这是目前缺失的一条独立真值链。

---

## Layer 4 — State / IPC Data Plane

负责：

- Ref；
- SHM；
- memfd；
- mmap；
- UDS；
- Protobuf；
- worker；
- state lifecycle。

这部分已有 Round 01 / Typed State 深审。

---

## Layer 5 — Execution Provider

负责：

- Transform DSL；
- LLM bounded Python；
- runtime builtin；
- retrieval adapter；
- sandbox；
- provider fallback。

CodeAct 已有独立审计；DSL / provider binding 仍需在 Routing / Artifact Round 中补齐。

---

## Layer 6 — Artifact / Verification / Commit

负责：

- Candidate Artifact；
- Input Manifest；
- Output Manifest；
- Validator；
- CapabilityQualityReport；
- Settlement；
- Invalidation；
- Replay Eligibility。

这是 StateBus 真正的“事实提升”边界，建议单独成 Round。

---

## Layer 7 — Long-Term Memory / Replay

负责：

- Semantic / Procedural / Episodic memory；
- hybrid retrieval；
- compatibility；
- projection；
- recipe reuse；
- artifact restore。

已有深入 Memory 审计。

---

## Layer 8 — Inference Reuse

负责：

- exact token prefix identity；
- APC；
- prefix-affinity；
- explicit KV continuation；
- EngineLocalKVHandle；
- paged KV ownership；
- physical reuse evidence。

必须与 generic State Data Plane 分开。

---

## Layer 9 — Scheduler / Reliability / Deployment

负责：

- ready queue；
- concurrency；
- resource arbitration；
- attempt lifecycle；
- timeout；
- crash；
- GC；
- worker lifecycle；
- telemetry；
- openEuler / Docker；
- Studio recovery。

原 Reliability Round 应扩为这一层。

---

## Layer 10 — Benchmark / Evidence

负责：

- Controlled Mechanism Evidence；
- External Generalization；
- Text vs Structured fairness；
- native evaluator boundary；
- statistics；
- actual-use / behavioral-effect semantics；
- claim closure。

原 Benchmark Round。

---

# 2. 在现有 6 Round 之外建议新增的 Round

| Round | 主题 | 结论 |
|---|---|---|
| 01 | IPC / UDS / Protobuf / SHM / memfd / multiprocess | 已完成 |
| 02 | Shared Semantic Memory / Cross-task reuse | 已有深审 |
| 03 | CodeAct / Sandbox / Repair / Recipe | 已完成 |
| 04 | Benchmark / Experiment / External Generalization | 待最终收口 |
| 05 | Protocol / Capability / Handshake / Schema | 待做 |
| 06 | Reliability / Deployment / Crash / GC | 待做 |
| **07** | **Task Admission / Contract Identity / External Input** | **建议新增** |
| **08** | **Planner / Routing / Role Topology / Replan / Scheduler Authority** | **建议新增** |
| **09** | **Evidence / Provenance / Hydration / Claim Correctness** | **建议新增** |
| **10** | **Artifact Lifecycle / Verification / Commit / Replay Truthfulness** | **建议新增** |
| **11** | **Inference Reuse / Prefix / APC / Explicit KV / Engine-local State** | **建议新增** |
| **12** | **Security / Privacy / Trust Boundary 横向审计** | **建议新增** |

---

# 3. Batch 01：Task / Plan Authority Chain

真实主链：

```text
Raw Request / Public Task
        ↓
Task Compiler / External Adapter
        ↓
Task Contract
        ↓
AdaptiveTaskEnvelope
        ↓
PlanSelector / Planner
        ↓
PlanProposal
        ↓
Plan Mechanical Compiler
        ↓
PlanPolicy
        ↓
ApprovedPlan
        ↓
STEP_READY
        ↓
CapabilityGrant
        ↓
Dispatcher / Provider
        ↓
Artifact / State
```

这条链当前已经比较完整，但存在若干 identity / authority seam。

---

# 4. P0 — Mainline “repair” 可以改变 Semantic Plan

`PlanPolicyValidator.validate_with_single_repair()` 的设计是正确的：

```text
Repair
只能修 schema / encoding

不能改：
DAG
capability
goal
refs
budget
memory policy
```

它使用 `_is_schema_only_repair()` 显式判断语义是否变化。

但是 `AdaptiveMainlineRunner._assemble_plan()` 没有使用这个受限 repair path。

Mainline 当前：

```text
raw Proposal
    ↓
PlanPolicy
    ↓ rejected
repair_plan(...)
    ↓
arbitrary new PlanProposal
    ↓
PlanPolicy again
    ↓
ApprovedPlan
```

只要新的 Proposal 仍在 Envelope authority 内，就可能：

- 换 capability；
- 加/删 step；
- 改 dependency；
- 改 goal；
- 改 memory policy。

这些行为实际是：

```text
Semantic Replan
```

却被 telemetry / assembly record 记成：

```text
policy_repair_used
```

## Target

必须拆：

```text
SchemaRepair
    → semantic hash 不变

SemanticReplan
    → 新 PlanProposal
    → 新 PlanPolicyReport
    → 新 ApprovedPlan
    → ReplanReceipt
```

---

# 5. P0/P1 — Task Contract Identity 没完全绑死

当前 Mainline 同时存在：

```text
request.canonical_task_spec_hash
request.envelope.canonical_task_spec_hash
```

`run()` 会校验：

```text
canonical_task_spec.spec_hash
==
request.canonical_task_spec_hash
```

但当前主线没有显式执行：

```text
request.envelope.canonical_task_spec_hash
==
request.canonical_task_spec_hash
```

理论上可能出现：

```text
Runtime Session / Memory / Mainline
绑定 Contract Hash A

Adaptive Authority Envelope
绑定 Contract Hash B
```

## Target

不要继续多处复制 hash。

引入：

```python
TaskContractIdentity(
    contract_kind,
    contract_hash,
    public_context_hash,
    legacy_canonical_task_spec_hash,
)
```

所有：

```text
Envelope
RuntimeRequest
Session
Memory
Replay
Grant
```

引用统一 identity。

---

# 6. P0/P1 — `task_id` / `step_id` 缺 Path-safe Contract

PlanPolicy 对 step ID 主要只校验：

```text
非空
唯一
```

但 Workspace 直接使用：

```python
workspace_root / task_id
task_root / "steps" / step_id
```

如果未来 Planner / External Adapter 产生：

```text
../x
foo/bar
../../tmp
```

则 raw identifier 会进入 filesystem composition。

当前 controlled benchmark IDs 通常安全，因此这不是已证实的现网 exploit；它是 External/Interactive lane 的 contract gap。

## Target

统一：

```text
OpaqueRuntimeTaskID
SafeStepID
RunID
SessionID
AttemptID
```

建议 path component：

```regex
^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$
```

并额外禁止：

```text
..
/
\
NUL
absolute path markers
```

最终 Workspace 还必须执行：

```text
resolved_path.is_relative_to(workspace_root)
```

---

# 7. P1 — TaskCompiler 混入了 Routing Decision

Current heuristic compiler 默认：

```text
task_family = financial_report_analysis

required_tools =
    table_retriever
    semantic_retriever
```

这意味着在 Planner / Router 之前：

```text
Compiler 已经预先决定需要 Retriever/Tool
```

与目标：

```text
Task Contract
    ↓
Planner / PlanSelector
    ↓
Logical Capability Selection
```

存在职责重叠。

## Target

`TaskCompiler` 降级为：

```text
Controlled / Legacy Canonical Compiler
```

External lane 直接生成：

```text
ExternalTaskEnvelope
+
InputAssetRef
+
Public Constraints
+
TaskContractIdentity
```

不要人为补 `required_tools`。

---

# 8. P1 — External Task 仍然被 `canonical_task_spec_hash` 绑住

虽然：

```text
AdaptiveMainlineRequest.canonical_task_spec
```

可以是 `None`，

但：

```text
canonical_task_spec_hash
```

仍然是 required field。

`AdaptiveTaskEnvelope` 同样要求该 hash。

因此 External lane 尚不是平级 contract。

## Target

支持：

```text
controlled_canonical_v1
external_public_v1
interactive_public_v1
```

三类 Task Contract。

---

# 9. P1 — PlanPolicy 通用层硬编码最少 2 Step

当前：

```python
2 <= len(proposal.steps)
```

是 generic policy invariant。

这会阻止真正 easy task：

```text
Executor only
```

或其他单逻辑阶段。

比赛如果要求 >=3 agents，应该由：

```text
Competition Policy / Benchmark Configuration
```

表达，而不是 generic Runtime 永远绑定。

## Target

```python
AdaptiveTaskEnvelope:
    min_plan_steps
    max_plan_steps
```

或者：

```text
TopologyPolicy
```

场景化控制。

---

# 10. P1 — Role Cardinality 可以直接锁死 Routing

PlanPolicy 严格执行：

```text
envelope.role_cardinality
```

这是正确的 authority behavior。

真正的问题在：

```text
谁生产 role_cardinality
```

如果 External Adapter 提前写：

```text
retriever = 1..1
executor = 1..2
summarizer = 1..1
```

Planner 已经没有真正 role omission 权限。

## Target

External Routing 实验：

```text
Benchmark Adapter
不能决定 role topology

Admission / Topology Policy
只定义允许范围
```

然后 Planner 选实际 topology。

---

# 11. P1 — Normalizer Callback 没有统一“机械变换证明”

当前：

```python
normalize_plan: Callable[
    [PlanProposal],
    tuple[PlanProposal, changed_fields]
]
```

任意 callback 都可以被注入。

官方 `compile_required_input_wiring()` 的实现是合理的：

- 不选 capability；
- 不新增 semantic stage；
- 不改 goal；
- 只补 registered required typed edge。

但 Mainline 类型本身没有保证所有 Normalizer 都这么做。

## Target

```python
PlanNormalizationReceipt(
    normalization_class="mechanical_binding",
    before_semantic_hash=...,
    after_semantic_hash=...,
    changed_fields=...,
)
```

要求：

```text
before_semantic_hash
==
after_semantic_hash
```

否则必须进入 SemanticReplan。

---

# 12. P1 — Fallback Provenance 被 Mainline 弱化

`PlanPolicyValidator.fallback()` 会正式生成：

```text
PlanPolicyStatus.FALLBACK_FIXED_PLAN
fallback_after_rejection
original proposal hash
```

但 Mainline 当前直接：

```text
effective = fallback_proposal
validator.validate(effective)
```

最终 policy report 看起来只是：

```text
APPROVED / NORMALIZED
```

虽然 Runtime 另有 `fallback_used` flag，但 Policy provenance 本身不完整。

## Target

统一使用：

```text
PlanPolicyValidator.fallback()
```

或正式：

```text
FallbackSelectionReceipt
```

---

# 13. P1 — ApprovedPlan Runtime Revalidation ≠ Provenance Authentication

Adaptive Runtime 会重新构造 Proposal：

```text
ApprovedPlan.steps
+
final output contract
+
memory policy
```

然后再执行 PlanPolicy。

这可以验证：

```text
graph 现在仍然符合当前 policy
```

是好的。

但它没有重新包含原 Planner 的：

- prompt_tokens；
- completion_tokens；
- model_id；
- raw_output_hash；
- latency；
- planner notes。

也没有要求：

```text
new PlanPolicyReport hash
==
approved_plan.plan_policy_report_hash
```

因此它更准确叫：

```text
Graph Policy Revalidation
```

而不是：

```text
Approved Plan Provenance Authentication
```

## Target

序列化 / replan / remote planner 路径使用：

```python
ApprovedPlanBundle(
    proposal,
    policy_report,
    approved_plan,
)
```

Runtime 验证：

```text
proposal_hash
→ policy_report
→ approved_plan
```

完整 hash chain。

---

# 14. P1 — Replan Callback 返回 `ApprovedPlan` 类型不合理

当前：

```python
replan(
    current_approved_plan,
    completed_steps,
    error_code,
) -> ApprovedPlan | None
```

调用方直接返回“已经批准”的对象。

Runtime 虽然会二次验证，但 type ownership 已经模糊：

```text
Replanner
似乎有 Approved Authority
```

## Target

```python
replan(...) -> PlanProposal | None
```

然后：

```text
Runtime PlanPolicy
    ↓
ApprovedPlan
```

保持：

```text
Agent/Replanner proposes
Runtime approves
```

这一核心原则。

---

# 15. P1 — Adaptive DAG 当前是依赖图，不是并行 Scheduler

Runtime 会计算：

```text
ready = dependency-complete steps
```

但之后：

```text
for step in sorted(ready):
    dispatch
    wait
    process result
```

所以 sibling ready steps 当前是串行。

这不是 correctness bug。

但当前 capability 应准确定位：

```text
Adaptive dependency DAG
```

而不是：

```text
parallel multi-agent scheduler
```

Reliability/Scheduler Round 需要继续审：

- bounded concurrency；
- resource admission；
- backpressure；
- cancellation；
- retry scheduling；
- GPU/LLM serialization；
- persistent worker pool。

---

# 16. P1 — Session / Workspace Identity 过于 task-centric

当前典型：

```text
session_id = adaptive-session-{task_id}

workspace =
workspace_root / task_id

manifest =
runtime_root / adaptive_mainline_manifest.json
```

单 case 没问题。

但以下情况需要独立 Run identity：

```text
same task rerun
concurrent same logical task
external harness retry
Studio rerun
A/B variant
```

## Target

```text
ExternalCaseID     audit-only mapping

RuntimeTaskID      opaque logical task

RunID              unique execution

SessionID          unique runtime session

AttemptID          unique attempt
```

物理路径优先：

```text
runtime_root / run_id / ...
```

---

# 17. P1 — CapabilityDescriptor 混合 Logical Capability + Provider

当前 Descriptor 同时描述：

```text
owner_role
semantic description
input/output contracts
completion criteria
```

以及：

```text
execution_kind
max_runtime_ms
fallback_capability_id
```

所以 Planner 直接选择：

```text
execute_analysis_dsl_v2
execute_bounded_python_v2
```

同时完成：

```text
what
+
how
```

## Target

```text
LogicalCapabilityDescriptor

    analyze_verified_data_v1
            ↓
ExecutionBindingPolicy

    ├─ analysis_dsl_v2
    └─ bounded_python_v2
            ↓
ExecutionBindingReceipt
```

这样才能支持：

- provider rebind；
- resource-aware dispatch；
- runtime fallback；
- benchmark DSL vs Python binding experiment。

---

# 18. 第一批风险表

| Priority | 问题 |
|---|---|
| **P0** | Mainline repair 可改变 semantic plan，却仍记为 policy repair |
| **P0/P1** | Envelope task contract hash 与 Mainline task contract hash 未显式绑定 |
| **P0/P1** | task_id / step_id 缺 path-safe invariant |
| **P1** | External lane 仍要求 canonical_task_spec_hash |
| **P1** | TaskCompiler heuristic 提前注入 required tools |
| **P1** | Generic PlanPolicy 固定 min 2 steps |
| **P1** | role_cardinality 可预锁 topology |
| **P1** | arbitrary normalizer 无 mechanical-only proof |
| **P1** | fallback provenance 没统一走 Policy fallback |
| **P1** | ApprovedPlan revalidation 不是 provenance authentication |
| **P1** | replan callback 返回 ApprovedPlan 而非 proposal |
| **P1** | DAG ready steps 当前串行 |
| **P1** | session/workspace identity task-centric |
| **P1** | CapabilityDescriptor 混 logical capability 与 provider |

---

# 19. 建议第一批 Slice

## TPA-0 — Identity Invariants

只做：

```text
Envelope task contract identity
==
Mainline task contract identity

Safe Task/Run/Step IDs

unique RunID
```

测试：

```text
test_envelope_task_contract_hash_mismatch_rejected
test_step_id_parent_traversal_rejected
test_step_id_path_separator_rejected
test_task_id_parent_traversal_rejected
test_workspace_path_remains_under_runtime_root
```

---

## TPA-1 — Repair vs Replan

Mainline `repair_plan` 必须满足：

```text
schema-only / mechanical-only
```

测试：

```text
test_plan_repair_cannot_change_capability
test_plan_repair_cannot_change_goal
test_plan_repair_cannot_add_step
test_plan_repair_cannot_change_dependency
test_plan_repair_cannot_change_memory_policy
```

Semantic change：

```text
必须走 Replan
```

---

## TPA-2 — Plan Approval Bundle

新增：

```text
Proposal Hash
Policy Report Hash
Approved Plan Hash
```

完整 binding。

测试：

```text
test_policy_report_hash_tamper_rejected
test_approved_plan_proposal_chain_verified
```

---

## TPA-3 — Replan Proposal

把：

```text
replan() -> ApprovedPlan
```

改为：

```text
replan() -> PlanProposal
```

Runtime 自己重新 approval。

---

## TPA-4 — TaskContractIdentity Bridge

保留 Legacy CanonicalTaskSpec。

先新增：

```text
TaskContractIdentity
```

并让：

```text
AdaptiveMainlineRequest
AdaptiveTaskEnvelope
RuntimeTaskSession
MemoryQuery
MemoryCommit
```

逐步使用。

---

## TPA-5 — Logical Capability / Provider Split

放到 identity / replan 修完之后。

不要与 TPA-0/1 一起大改。

---

# 20. Batch 02 推荐：Evidence / Provenance / Hydration / Claim

下一批建议直接审：

```text
Raw source
  ↓
Retrieval Candidate
  ↓
CanonicalEvidencePack
  ↓
HydrateManifest
  ↓
Evidence Projection
  ↓
Verified Artifact
  ↓
ClaimSet
```

重点源码：

```text
statebus/retrieval/*
statebus/provenance/hydration.py

statebus/runtime/retrieval_adapter.py
statebus/runtime/evidence_coverage.py
statebus/runtime/evidence_projection.py
statebus/runtime/claims.py

statebus/refs/models.py
```

关键问题：

```text
Candidate → EvidencePack 的 authority promotion 是否正确

locator 是否始终对应原始 source

semantic pruning 后 lineage 是否完整

HydrateManifest row/candidate 是否可错绑

Projection 是否只读取授权字段

Claim citation 是否可伪造

numeric claim 是否真的由 verified artifact 支撑

conflict 是否能传播到 final claim

raw evidence / hydrated text / prompt-visible bytes 是否准确计量
```

---

# 21. Batch 03：Artifact Lifecycle / Commit / Replay

单独审：

```text
Candidate Artifact
  ↓
Manifest
  ↓
Input Validation
  ↓
Artifact Validation
  ↓
CapabilityQualityReport
  ↓
VERIFIED
  ↓
Settlement
  ↓
Replay Eligibility
  ↓
Memory Commit
```

已有一个明确 seam：

```text
mark_verified()
同时设置
replay_ready=True
```

应该拆：

```text
ArtifactVerification
≠
ReplayEligibility
```

---

# 22. Batch 04：Inference Reuse

独立审：

```text
PrefixLineageIdentity
ExactTokenPrefixIdentity
APC observation
Prefix scheduling
EngineLocalKVHandle
KV registry
connector / middleware
worker extension
paged cache
continuation
release
```

必须明确：

```text
metadata hint
≠
engine hit

candidate handle seen
≠
KV hit

prefix identity
≠
exact token identity

control-plane handle
≠
physical KV bytes reused
```

---

# 23. 推荐最终审计顺序

```text
01 IPC / Data Plane                  已完成
02 Memory                            已有深审
03 CodeAct                           已完成

07 Task Admission / Contract Identity
        ↓
08 Planning / Routing / Replan
        ↓
09 Evidence / Provenance / Claim
        ↓
10 Artifact / Verification / Commit
        ↓
05 Protocol / Capability / Handshake
        ↓
Routing Provider Binding
        ↓
11 Inference Reuse / Prefix / KV
        ↓
06 Scheduler / Reliability / Deployment
        ↓
04 External Benchmark / Evidence Closure
        ↓
12 Security / Privacy Final Pass
```

Benchmark 最终收口放后面。

因为其指标必须建立在已经校正的：

```text
actual-use
behavioral-effect
identity
replay semantics
communication accounting
```

之上。

---

# 24. 最终判断

现有六个 Round 没有错，但它们偏“功能模块”。

StateBus 真正还需要补的是几条**纵向系统真值链**：

```text
Task → Authority
Evidence → Fact
Execution → Verified Artifact
History → Authorized Reuse
Prefix/KV → Physical Compute Reuse
```

当前第一批源码已经证明：

> **Task / Plan Authority 应成为独立高优先级 Round。**

第一刀不是继续增加 Routing feature，而是先收口：

```text
TaskContract Identity
Repair vs Replan
Safe Runtime IDs
Plan Approval Provenance
```

这些完成以后，再进入 Evidence / Artifact，后面的 Protocol、KV、Benchmark 才有稳定上游。
