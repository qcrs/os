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

---

# Batch 02 — Evidence / Provenance / Hydration / Claim 真值链源码审计

> 审计范围：只做源码事实与问题分析，不修改代码。  
> 重点链路：
>
> `Raw Source → Retriever → EvidenceCandidate → CanonicalEvidencePack → Coverage → Hydration / Projection → Verified Artifact → ClaimSet`
>
> 本轮核心问题不是“检索效果好不好”，而是：
>
> **StateBus 最终声称“结构化事实可回溯”时，这个 provenance 到底能回溯到哪里？**
>
> 需要严格区分：
>
> ```text
> Runtime 内部一致性
> ≠
> Source-backed correctness
> ≠
> Claim-level semantic entailment
> ```

---

# 26. Batch 02 Executive Summary

这一轮源码审计后的总体结论：

> **StateBus 已经具备较完整的 Typed Evidence / Runtime-local Provenance 链，但当前更准确的是“Pack-local / Runtime-local traceability”，还不能无条件表述为“Cryptographically Source-backed Provenance”。**

当前已经真实存在：

```text
Retrieval Candidate Identity
        ↓
CanonicalEvidencePack
        ↓
Pack Hash
        ↓
HydrateManifest
        ↓
Evidence Coverage
        ↓
Evidence Projection
        ↓
row lineage
        ↓
ExecutionArtifactRef
        ↓
Artifact blob hash
        ↓
Claim supporting evidence/artifact refs
```

但两个最重要的真实性边界还没有完全闭环：

```text
Source Bytes
    ↓
Exact Locator Reconstruction
    ↓
EvidenceItem

以及

EvidenceItem / Artifact Field
    ↓
Exact Claim Support Binding
    ↓
Claim
```

因此当前推荐把 Evidence 子系统定位为：

# **Typed Evidence + Runtime-local Provenance Prototype**

而不是：

```text
Source-attested evidence system
Field-level source provenance
Semantic entailment-verified claim system
```

---

# 27. 当前 Evidence 真值链源码地图

主要源码：

```text
statebus/retrieval/corpus.py
statebus/retrieval/pipeline.py
statebus/retrieval/models.py

statebus/provenance/hydration.py

statebus/refs/models.py

statebus/runtime/retrieval_adapter.py
statebus/runtime/evidence_coverage.py
statebus/runtime/evidence_projection.py
statebus/runtime/claims.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/capability_validators.py

statebus/state/retrieval_store.py
statebus/state/disk.py
```

真实链路：

```text
CanonicalTaskSpec / Planner Retrieval Objective
                ↓
RetrieverFanoutPipeline
                ↓
┌─────────────────────────────────────────┐
│ LexicalMetadataRetriever                │
│ SemanticChunkRetriever                  │
│ TableStructureRetriever                 │
└─────────────────────────────────────────┘
                ↓
EvidenceCandidate
                ↓
RetrievalCandidatePool
                ↓
Rerank / Pruning
                ↓
DeterministicFanInBuilder
                ↓
CanonicalEvidencePack
                ↓
HydrateManifest
                ↓
EvidenceCoverageVerifier
                ↓
COMPLETE / INSUFFICIENT / CONFLICTING
                ↓
Evidence Projection
                ↓
typed_rows.json
                ↓
ExecutionArtifactRef
                ↓
DSL / CodeAct
                ↓
Verified Execution Artifact
                ↓
Summarizer
                ↓
ClaimSet
                ↓
ClaimSetValidator
```

这不是普通的：

```text
RAG → Prompt → LLM
```

而是已经存在多层 Contract 和 Ref。

这部分本身是 StateBus 很重要的工程基础。

---

# 28. Source Locator Contract 当前是什么

`statebus/refs/models.py` 中定义了三种主要 SourceLocator：

```python
TextSpanLocator(
    source_doc_hash,
    canonical_text_id,
    start_char,
    end_char,
    extractor_version,
)

TableCellLocator(
    source_doc_hash,
    table_id,
    sheet_name,
    row_idx,
    col_idx,
    extractor_version,
)

FragmentLocator(
    source_doc_hash,
    fragment_id,
    extractor_version,
    page_no,
)
```

它们表达的是：

```text
“这个 EvidenceItem 声称来自哪里”
```

但必须注意：

> Locator 本身是一个描述 Contract，不等于 Source 已经被重新验证。

目前 Locator 缺少统一 structural invariant，例如：

```text
source_doc_hash != ""
start_char >= 0
end_char > start_char
row_idx >= 0
col_idx >= 0
extractor_version != ""
```

所以目前 locator 的正确性主要依赖：

```text
trusted internal producer
```

而不是：

```text
Locator constructor / validator fail-closed
```

---

# 29. P0 — 当前 Hydration 是 Pack-backed，不是 Source-backed

这是本轮最重要的发现之一。

当前：

```python
build_hydration_registry_from_evidence_pack(pack)
```

逻辑本质是：

```text
for item in EvidencePack:
    registry.register(
        item.locator,
        item.rendered_text
    )
```

随后：

```python
registry.hydrate_locator(locator)
```

只是根据 locator stable key 从内存字典里取回：

```text
之前由 EvidencePack 写进去的 rendered_text
```

实际链：

```text
EvidencePack.rendered_text
        ↓
HydrationRegistry
        ↓
locator key
        ↓
same rendered_text
```

而不是：

```text
locator.source_doc_hash
        ↓
SourceAssetRegistry
        ↓
open exact source bytes
        ↓
extract row/cell/span
        ↓
canonicalize
        ↓
rehydrated content
```

因此当前的 Hydration 更准确叫：

# **Pack-backed deterministic hydration**

不能叫：

# **Source-backed hydration**

---

# 30. 为什么 Pack-backed 与 Source-backed 差别很大

假设 Pack 中出现：

```text
locator:
    source_doc_hash = ABC
    table_id = income
    row = 10
    col = 2

rendered_text:
    Revenue = 999
```

但真实 Source ABC：

```text
row 10 col 2
=
Revenue = 120
```

当前：

```text
HydrationRegistry
```

仍然会返回：

```text
Revenue = 999
```

因为它不重新读取 Source。

因此现在 `HydrateManifest` 能证明：

```text
“当前 Runtime 使用的是哪个 locator / stable key”
```

以及：

```text
“哪个 EvidenceItem 被恢复到下游 prompt”
```

但不能独立证明：

```text
“恢复出来的内容与原始文件当前 locator 的内容完全一致”
```

---

# 31. 当前 Claim Boundary 应该怎么描述

当前可以说：

> StateBus 对 EvidenceItem、Locator、HydrateManifest、ProjectionReport 和下游 Artifact 建立了稳定 hash/Ref 链路，因此可以审计某个 Runtime output 使用了哪些 EvidenceItem。

暂时不应该说：

> StateBus 在消费时会根据 locator 重新验证原始数据，因此所有 Evidence 都具备 source-attested correctness。

后者当前源码并不支持。

---

# 32. P0 — `source_doc_hash` 的语义目前不统一

`source_doc_hash` 这个字段在不同 Corpus 中实际上存在至少两种语义：

```text
A. 真 Content Digest
B. Synthetic Logical Source ID
```

这会导致“hash”这个名字产生过强语义。

---

# 33. Markdown / Incident 主文件：是真 Content Hash

部分路径做的是：

```python
"sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
```

例如：

```text
OfflineMarkdownLongDocCorpus
OfflineIncidentLogCorpus main log
```

这属于真正：

```text
content-addressed source identity
```

这一类没有问题。

---

# 34. P0 — CSV 当前不是 Content Hash

`OfflineCsvTableCorpus.resolve()` 当前使用：

```python
source_doc_hash = f"sha256:csv-{dataset_id}"
```

Text fragment、Table row 也沿用：

```text
sha256:csv-{dataset_id}
```

这并不是 SHA-256 digest。

例如：

```text
dataset_id = sales
```

只要 dataset_id 一样：

```text
sales_v1.csv
sales_v2.csv
```

即使内容完全不同，当前都可能得到：

```text
sha256:csv-sales
```

所以这一字段实际更像：

```text
logical_source_id
```

却被命名为：

```text
source_doc_hash
```

这会影响：

```text
Source provenance claim
Cache identity
Replay compatibility
Evidence conflict
External benchmark isolation
```

---

# 35. P0 — Incident Journal 的 source identity 会 alias 到主 Log

Incident path 同时加载：

```text
boot log
journal log
```

但是：

```text
source_doc_hash
```

来自：

```text
resolved_log_path
```

即主 log。

随后 `_text_fragments()`：

```text
log_text
journal_text
```

两部分 fragment 都收到同一个：

```text
source_doc_hash
```

结果：

```text
boot.log fragment
    → hash(boot.log)

journal.log fragment
    → 仍然 hash(boot.log)
```

这属于明确的：

# **Source Identity Aliasing**

如果以后 Claim 引用的是：

```text
journal evidence
```

locator 可能仍然声称：

```text
source = boot log
```

这会直接削弱 provenance correctness。

---

# 36. P0 — Structured Row 是多字段数据，但只有一个 Cell Locator

`OfflineMarkdownLongDocCorpus._generic_table_rows()` 会生成：

```python
structured_row = {
    "quarter": ...,
    "region": ...,
    "revenue": ...,
    "cost": ...,
}
```

整个 dict 被存入：

```python
metadata={
    "structured_row": structured_row
}
```

但 `CorpusTableRow` 只保留：

```python
TableCellLocator(
    row_idx = ...,
    col_idx = headers.index(metric_name) + 1,
)
```

也就是说：

```text
一个完整 row
包含 4~N 个字段
```

最终只由：

```text
一个 cell locator
```

作为 provenance anchor。

---

# 37. Projection 如何扩大了这个问题

`EvidenceProjectionAdapter._extract_row()` 优先使用：

```python
metadata["structured_row"]
```

因此：

```text
quarter
region
revenue
cost
```

都可以进入：

```text
typed_rows.json
```

随后 ProjectionReport 的 `row_lineage` 记录：

```text
row_index
evidence_item_id
locator
source_doc_hash
```

但是 locator 仍然只有：

```text
一个 TableCellLocator
```

因此当前的 lineage 是：

```text
Projected Row
    ↓
Producing EvidenceItem
    ↓
One locator anchor
```

而不是：

```text
Projected Field A → Source Cell A
Projected Field B → Source Cell B
Projected Field C → Source Cell C
```

所以当前不能声称：

# **Field-level Provenance**

更准确应该是：

# **Row-level / EvidenceItem-level Provenance Anchor**

---

# 38. P0/P1 — Projection 的 `VERIFIED` 实际是 Runtime 自证

Projection 流程：

```text
EvidencePack COMPLETE
        ↓
_extract_row()
        ↓
write typed_rows.json
        ↓
register_candidate()
        ↓
mark_verified()
```

这里没有一个独立步骤重新执行：

```text
typed row value
    ==
locator 对应 source value
```

因此 Projection Artifact 的 “VERIFIED” 本质是：

```text
trusted deterministic runtime transform completed
```

而不是：

```text
independent source recomputation verified
```

这个 distinction 很重要。

---

# 39. Projection Artifact 的正确定位

目前更合理：

```text
Runtime-Trusted Derived Artifact
```

而不是：

```text
Independently Verified External Artifact
```

以后 Artifact 状态最好拆成类似：

```text
CANDIDATE

RUNTIME_DERIVED
    deterministic trusted transform

VALIDATED
    schema / contract validated

VERIFIED
    independent or capability-specific verification

REPLAY_ELIGIBLE
    separate reuse admission
```

本轮只审计，不做这个修改。

---

# 40. P0 — Claim Citation 与 supporting Evidence 没有一一绑定

当前 `Claim` 有：

```python
supporting_evidence_item_ids
supporting_artifact_ref_ids
citation_locators
numeric_fields
```

这些字段彼此是平行数组/集合。

Validator 当前会分别检查：

```text
Evidence ID 是否存在
Citation locator 是否存在
Artifact 是否 VERIFIED
Numeric value 是否存在
```

但是缺少：

```text
citation locator
必须属于
这个 claim 声明的 supporting_evidence_item_ids
```

这个关系约束。

---

# 41. 具体例子

EvidencePack：

```text
E1:
    Revenue = 100
    locator = L1

E2:
    Operating cost = 80
    locator = L2
```

Claim：

```text
supporting_evidence_item_ids = [E1]

citation_locators = [L2]
```

当前检查：

```text
E1 exists   ✓
L2 exists   ✓
```

但是：

```text
E1 ↔ L2
```

并没有绑定。

所以这属于：

# **Claim-Level Provenance Binding Gap**

---

# 42. 现有测试覆盖了什么，没覆盖什么

现有 `test_adaptive_claims.py` 已经测试：

```text
fake locator
→ reject

wrong artifact task/session
→ reject

numeric claim
不能依赖另一个 artifact 的值
```

这些都是好的。

但当前缺少关键 adversarial case：

```text
valid evidence A
+
valid locator B
+
A 与 B 不对应
```

以及：

```text
valid artifact
+
numeric value 存在
+
field name 不对应
```

。

---

# 43. P0/P1 — Numeric Claim 是 Value-level，不是 Field-level

当前 validator 大致会从 supporting artifacts 中收集：

```text
所有 scalar numeric values
```

然后判断：

```text
claim.numeric_fields 中的 value
是否存在于这些 numeric values
```

问题是：

```text
numeric field name
```

没有参与 provenance binding。

---

# 44. Numeric Binding 例子

Artifact：

```json
{
  "revenue": 120,
  "cost": 50
}
```

Claim：

```json
{
  "numeric_fields": {
    "profit": 120
  }
}
```

只要：

```text
120
```

存在于 artifact，

当前 gate 就可能认为：

```text
numeric support exists
```

它证明的是：

> 120 这个数出现在 supporting artifact。

不是：

> `profit=120` 这个字段语义由 supporting artifact 中对应 field/path 支撑。

因此：

```text
value-level membership
≠
field-level provenance
```

---

# 45. P1 — Citation Bound 也不等于 Semantic Entailment

即使未来做到：

```text
Claim
→ EvidenceItem
→ Exact Locator
```

仍然不能自动说明：

```text
Claim Text
```

全部由这段证据支持。

例如：

```text
Evidence:
Revenue = 120
```

Claim：

```text
Revenue was 120 because of accounting fraud.
```

如果 numeric 和 locator 都合法，

当前 structural validator 并不会判断：

```text
because of accounting fraud
```

是不是 evidence-supported。

因此必须冻结一个非常重要的边界：

```text
Citation Exists
    ≠
Citation Bound

Citation Bound
    ≠
Semantic Entailment
```

当前 StateBus 做的是前两者中的部分工作，

不是完整 entailment verifier。

---

# 46. P0/P1 — CanonicalEvidencePack 缺少统一 Structural Validator

当前 `CanonicalEvidencePack` 主要负责：

```text
保存 EvidenceItem
+
计算 pack_hash
```

但没有统一检查一些重要 invariants。

---

# 47. 缺失 invariant 1：Locator Source Membership

理论上应检查：

```text
item.locator.source_doc_hash
∈
pack.source_doc_hashes
```

当前没有统一 enforcement。

所以 contract 层理论上可以构造：

```text
Pack.source_doc_hashes = [A]

EvidenceItem.locator.source_doc_hash = B
```

并生成合法 pack hash。

---

# 48. 缺失 invariant 2：Container Bucket 与 item.bucket 一致性

EvidenceItem 自己有：

```text
item.bucket
```

但 CanonicalEvidencePack 又有：

```text
hard_facts
structured_evidence
semantic_contexts
lexical_hints
conflicts
```

两套 bucket 表达。

CoverageVerifier 实际主要依据：

```text
item 被放在哪个 tuple
```

决定 evidence type。

例如：

```text
EvidenceItem(
    bucket="semantic_context"
)
```

如果被错误放进：

```text
hard_facts
```

Coverage 仍可能把它视为：

```text
fact/table
```

这属于：

```text
duplicate semantic source of truth
```

。

---

# 49. 缺失 invariant 3：Locator Structural Validity

需要统一检查：

```text
source_doc_hash non-empty
extractor_version non-empty

TextSpan:
    start >= 0
    end > start

Table:
    row_idx >= 0
    col_idx >= 0

Fragment:
    fragment_id non-empty
```

目前主要依赖 producer 自觉。

---

# 50. 缺失 invariant 4：Evidence Item Identity

目前去重常常使用：

```text
item_id
+
repr(locator)
```

但系统没有冻结：

```text
EvidenceIdentity = ?
```

到底应该是：

```text
item_id

还是

source + locator

还是

source + locator + canonical content hash
```

不明确。

这也是后面 fan-in conflict 问题的根源。

---

# 51. P0/P1 — Persisted EvidencePack 读回来时不重新证明 pack hash

序列化会把：

```text
pack_hash
```

写进 JSON。

反序列化：

```python
CanonicalEvidencePack(
    ...
    pack_hash=payload["pack_hash"]
)
```

直接使用文件内的 hash。

而 `__post_init__()` 只有：

```text
pack_hash 为空
```

才重新计算。

因此：

```text
JSON content 被修改
+
pack_hash 字段保持旧值
```

对象不会自动发现。

---

# 52. `JsonContractStore.read_evidence_pack()` 的语义

当前：

```text
sidecars/evidence/{pack_hash}.json
    ↓
read JSON
    ↓
evidence_pack_from_dict()
    ↓
return object
```

没有显式：

```text
recomputed canonical hash
==
requested pack_hash
==
embedded pack_hash
```

。

因此目前是：

```text
content-addressed filename convention
```

但不是严格：

```text
content-address verification on read
```

。

---

# 53. 为什么这和 Artifact 形成明显反差

Execution Artifact 的读取链更严格：

```text
resolve root
resolve exact path

path must remain under root

reject symlink

read bytes

size check

blob hash check

JSON decode

cached rows equality check
```

所以 Artifact 已经比较接近：

```text
Content-backed Authority
```

而 EvidencePack persistence 仍然更接近：

```text
Contract-backed Authority
```

这是系统里目前一个很明显的不一致。

---

# 54. P1 — HydrationRegistry 对同 Locator 冲突是 Last-write-wins

HydrationRegistry 的本质：

```python
registry[stable_locator_key] = rendered_text
```

如果：

```text
Evidence A:
locator = L
text = X

Evidence B:
locator = L
text = Y
```

后注册的会覆盖前者。

正确的 source-provenance 语义通常应该是：

```text
same exact locator
+
different canonical content
=
conflict / corruption
```

而不是：

```text
last writer wins
```

。

---

# 55. P1 — 当前存在两套 Fan-in 去重语义

至少有：

```text
runtime/retrieval_adapter.py
```

和：

```text
retrieval/pipeline.py
```

两套 stable fan-in。

它们的去重 scope 不一致。

---

# 56. Adapter Fan-in

`runtime/retrieval_adapter.py`：

```python
seen = set()

def merge(bucket):
    ...
```

`seen` 在所有 bucket 间共享。

因此：

```text
same item_id + same locator
```

一旦已经在：

```text
hard_facts
```

出现，

后续即使在：

```text
semantic_contexts
```

出现也会被去掉。

---

# 57. Pipeline Fan-in

`retrieval/pipeline.py`：

```python
def merge(bucket):
    seen = set()
```

每个 bucket 独立去重。

因此同一个：

```text
item_id + locator
```

理论上可以同时存在于多个 bucket。

---

# 58. 这为什么是问题

同一组 EvidencePack：

```text
Pack A
Pack B
```

如果经过不同 fan-in 实现：

```text
AdaptiveRetrievalAdapter
vs
RetrieverFanoutPipeline
```

可能生成不同：

```text
CanonicalEvidencePack
```

这属于：

# **Fan-in Policy Drift**

以后 Evidence fan-in 应该只有一份 canonical policy。

---

# 59. P1 — Same Locator + Different Content 不会自动产生 Conflict

当前去重 key 主要是：

```text
(item_id, repr(locator))
```

如果两个 Pack：

```text
same item_id
same locator

Pack A:
Revenue = 100

Pack B:
Revenue = 120
```

当前不会自动生成：

```text
Evidence Conflict
```

更可能是：

```text
stable sort
→ first wins
→ second silently disappears
```

。

所以当前：

```text
EvidenceCoverageStatus.CONFLICTING_EVIDENCE
```

并不代表 Runtime 有通用 contradiction detection。

它只代表：

```text
upstream 已经把 EvidenceItem
显式放进 conflicts bucket
```

。

---

# 60. P0 — Envelope 的 max_retrieval_expansions 未真正控制 Adaptive Dispatcher

`AdaptiveTaskEnvelope` 有：

```python
max_retrieval_expansions
```

但是 Adaptive Dispatcher 当前调用：

```python
run_with_single_expansion(
    ...,
    max_expansions=1,
)
```

属于硬编码。

因此如果：

```text
Envelope:
max_retrieval_expansions = 0
```

但：

```text
retrieval_expansion_factory != None
```

执行层仍可能进行一次 expansion。

这属于：

# **Authority Budget Not Enforced**

---

# 61. P0/P1 — Adaptive Expansion Scope 比 Pipeline 的安全边界更弱

`RetrieverFanoutPipeline._validate_expansion_scope()` 会限制：

```text
task_id
step_id

corpus_scope_ids
不能扩大

evidence_types
不能改变

target_entities
不能改变

time_scope
不能改变

memory_policy
不能改变
```

这条边界是比较好的。

但：

```text
AdaptiveRetrievalAdapter.run_with_single_expansion()
```

只显式检查：

```text
task_id
step_id
```

随后 expansion 只需要通过：

```text
allowed_corpus_scope_ids
```

全局 allowed set。

因此理论上：

```text
Initial request:
    corpus = A

Expansion:
    corpus = B
```

只要：

```text
B ∈ global allowed corpus set
```

就可能通过。

这属于：

# **Expansion Authority Drift**

---

# 62. Expansion 不应该是什么

Expansion 应该表达：

```text
“在同一个 Evidence Authority 范围内，
扩大 query / retrieval effort”
```

而不是：

```text
“重新选择新的 evidence authority”
```

正确关系：

```text
ExpansionScope
⊆
InitialEvidenceScope
```

不是：

```text
ExpansionScope
⊆
GlobalAllowedScope
```

。

---

# 63. P1 — `max_candidates` 当前主要是 Declarative Budget

`EvidenceRequest` 有：

```python
max_candidates
```

`validate_evidence_request()` 只检查：

```text
1 <= max_candidates <= 64
```

但后续：

```text
run_multi_query()
run()
```

没有接收：

```text
max_candidates
```

作为执行参数。

所以当前没有清晰闭环：

```text
EvidenceRequest.max_candidates
    ↓
Candidate Pool Enforcement
```

。

---

# 64. P1 — `max_prompt_visible_bytes` 同样未形成统一 Runtime Enforcement

Request 也有：

```python
max_prompt_visible_bytes
```

目前主要验证数值范围：

```text
256 ~ 262144
```

但 Retrieval Pipeline 的实际 pruning / hydration budget 是另一套配置和统计。

所以现在：

```text
Request-level prompt budget
```

和：

```text
Retrieval pruning / hydration budget
```

没有完全统一。

---

# 65. Budget Claim 应该怎么说

当前可以说：

```text
StateBus 已经记录 retrieval/pruning byte metrics，
并有独立 dynamic pruning policy。
```

暂时不要说：

```text
Every EvidenceRequest's declared candidate/prompt budget
is enforced end-to-end.
```

当前源码不完全支持这句话。

---

# 66. P1 — `corpus_scope_ids` 还不是 Physical Source Authority

`validate_evidence_request()` 会检查：

```text
request.corpus_scope_ids
⊆
allowed_corpus_scope_ids
```

但真正选择 source 文件的是：

```text
CanonicalTaskSpec.task_family
CanonicalTaskSpec.arguments.csv_path
document_path
log_path
ticker
quarter
```

。

因此：

```text
corpus_scope_ids
```

目前更像：

```text
logical request validation label
```

不是：

```text
physical InputAsset authorization
```

。

---

# 67. 这与 External Benchmark Boundary 如何衔接

之前已经设计：

```text
ExternalTaskEnvelope
+
InputAssetRef
+
TaskContractIdentity
```

Evidence Plane 应最终接：

```text
CapabilityGrant
        ↓
allowed_input_asset_ids
        ↓
AssetRegistry
        ↓
Source Resolver
        ↓
Retriever
```

而不是继续：

```text
CanonicalTaskSpec arguments
里面携带任意 path
```

。

这会让：

```text
Benchmark Boundary
Task Authority
Evidence Provenance
```

三条线真正合并。

---

# 68. P1 — EvidenceCoverage 的 locator gate 是 Pack-global

当前：

```python
locator_ok =
    not request.required_locator
    or locator_count > 0
```

也就是说：

```text
Pack 中只要至少有一个 locator
```

就可能满足：

```text
locator_coverage=True
```

。

不是：

```text
所有被要求的 evidence type
都有 locator
```

也不是：

```text
每个最终被消费的 EvidenceItem
都有 locator
```

。

Projection 后续会对实际消费 item 再做 locator check，

所以后续执行路径往往还能 fail closed。

但：

```text
EvidenceCoverageStatus.COMPLETE
```

这个 status 本身的语义要谨慎。

---

# 69. P1 — Coverage Type 由 Container Bucket 决定

CoverageVerifier 使用：

```text
hard_facts
structured_evidence
semantic_contexts
lexical_hints
conflicts
```

来映射 Evidence Type。

而 `EvidenceItem.bucket` 自己也存一份 bucket。

没有 invariant：

```text
EvidenceItem.bucket
==
所在 CanonicalEvidencePack tuple
```

。

因此存在：

```text
semantic field duplication
```

问题。

---

# 70. Positive Finding — Cross-process Semantic Selection 的 Candidate Boundary 比较干净

`apply_semantic_state_selection()` 会做：

```text
selected_candidate_ids 与 scores 数量一致

selected IDs 不重复

selected IDs
必须属于 semantic candidate embedding surface

selected IDs
必须能映射回原 Retrieval Candidate
```

然后才重建：

```text
CanonicalEvidencePack.semantic_contexts
```

这说明：

```text
跨 PID SemanticState
```

不能凭空注入一个：

```text
不属于候选集合的 Evidence ID
```

。

这个设计是好的。

---

# 71. 这对 Embedding 方向意味着什么

当前 Embedding 虽然只是：

```text
selection state
```

但它并不是：

```text
裸 embedding → arbitrary output
```

而是：

```text
candidate surface
    ↓
binary semantic state
    ↓
cross-process selection
    ↓
selected candidate ID gate
    ↓
reconstruct canonical EvidenceItem
```

所以 Embedding 的系统完整性比单纯向量检索更强。

这部分应保留。

---

# 72. Positive Finding — Execution Artifact 的读取真实性明显更强

Adaptive Dispatcher 对 verified artifact 输入会：

```text
resolve root

resolve path

确认 resolved path 在 root 内

拒绝 symlink

读取真实 bytes

检查 size_bytes

检查 blob_hash

JSON parse

再和 cached rows 做 equality
```

因此：

```text
ExecutionArtifactRef
```

这一侧已经比较接近：

# **Content-backed Input Authority**

这是当前系统里较成熟的部分。

---

# 73. Evidence 与 Artifact 当前形成两种不同真实性等级

可以正式分成：

```text
Evidence Plane
    Contract-backed / Pack-backed

Artifact Plane
    Content-backed / Blob-verified
```

这不是一定错误。

但文档与答辩必须明确：

```text
Evidence Pack VERIFIED
```

和：

```text
Execution Artifact VERIFIED
```

当前不是完全同一等级的 verification semantics。

---

# 74. Positive Finding — Generic Capability Validator 没有偷偷使用 Benchmark Gold

`generic_analysis` validator 明确限制在：

```text
provenance presence
non-empty output
required fields
finite values
completion row budget
```

并明确：

```text
recomputation_evaluated=False
recomputation_passed=False
```

因为 generic Runtime 无法独立证明 arbitrary model-selected analysis 的 semantic correctness。

这个设计非常重要。

保留原则：

> 不知道是否 independently recomputed，就明确标 not evaluated。

不要为了指标：

```text
verified=True
```

就同时暗示：

```text
semantically correct
```

。

---

# 75. Batch 02 的 Truth Ladder

以后建议用下面这套等级描述 Evidence/Claim：

```text
L0 — Presence
对象存在

L1 — Integrity
对象内容 hash 稳定

L2 — Runtime Binding
对象绑定 task/session/grant

L3 — Evidence Binding
下游输出记录 consumed Evidence IDs

L4 — Locator Binding
EvidenceItem 绑定 SourceLocator

L5 — Source Reconstruction
Locator 可以重新从原 Source 恢复并验证内容

L6 — Field-level Provenance
每个 projected field 对应 exact source field/cell/span

L7 — Claim-level Provenance
Claim support 与 exact evidence/artifact field 一一绑定

L8 — Semantic Entailment
Claim text 的完整语义由 evidence 支撑
```

当前 StateBus 大致做到：

```text
L0 ✓
L1 ✓
L2 ✓
L3 ✓
L4 部分 ✓
L5 ✗ / 仅局部
L6 ✗
L7 部分
L8 ✗
```

这个表非常适合后面答辩和研发 roadmap。

---

# 76. 当前可以成立的 Evidence Claim

## 可以硬讲

```text
Canonical EvidencePack 使用稳定 canonical hash

EvidenceItem 带 typed locator

跨进程 SemanticState 只能在已发布 candidate surface 内选 ID

EvidencePack 有 task/session scope

Projection 会生成 row_lineage

Execution Artifact 使用 blob hash + path containment 验证

ClaimSet 会检查 supporting evidence / artifact refs

Numeric claim 要求 supporting artifact 中存在对应 numeric value
```

---

# 77. 当前不应该硬讲

暂时不要讲：

```text
所有 source_doc_hash 都是真 content hash

所有 Evidence hydration 都会重新读取原文件

所有 projected fields 都有 exact cell-level lineage

Claim citation 与 supporting evidence 已经 exact pair-bound

Claim numeric field 已经 exact field/path-bound

Claim text 已经语义 entailment verified

Evidence conflict 是 Runtime 自动检测所有矛盾

EvidenceRequest 的所有 budget 都已 end-to-end enforced
```

这些当前源码都不足以支持。

---

# 78. Batch 02 风险表

| Priority | 问题 | 类型 |
|---|---|---|
| **P0** | Hydration 是 Pack-backed，不是 Source-backed | Provenance truth |
| **P0** | CSV `source_doc_hash` 是 synthetic ID | Source identity |
| **P0** | Incident journal 与主 log hash alias | Source identity |
| **P0** | Structured row 多字段只绑定一个 CellLocator | Field lineage |
| **P0** | Claim locator 未绑定 supporting EvidenceItem | Claim provenance |
| **P0** | `max_retrieval_expansions` 被 Dispatcher 写死为 1 | Authority |
| **P0/P1** | Adaptive Expansion scope 可扩大 | Authority |
| **P0/P1** | EvidencePack 缺统一 structural/source validator | Contract integrity |
| **P0/P1** | Persisted EvidencePack 不重新验证 content hash | Persistence integrity |
| **P0/P1** | Numeric Claim 是 value-level，不是 field-level | Claim correctness |
| **P1** | Projection Artifact 由 Runtime 自身 promote VERIFIED | Verification semantics |
| **P1** | Duplicate locator 不同 content 会覆盖 | Provenance conflict |
| **P1** | 两套 fan-in semantics 不一致 | Policy drift |
| **P1** | same key/different content 不会自动 conflict | Conflict handling |
| **P1** | `max_candidates` 没真正 enforce | Budget |
| **P1** | `max_prompt_visible_bytes` 没真正 enforce | Budget |
| **P1** | corpus_scope 不是 physical source authority | Source authorization |
| **P1** | Coverage locator gate 只是 pack-global | Coverage semantics |
| **P1** | Claim citation 不等于 semantic entailment | Claim semantics |

---

# 79. 本轮不建议立刻做的事情

当前是审计阶段，不要因为发现 provenance seam 就立即：

```text
引入大型 Graph DB

引入 LangChain/LlamaIndex Document abstraction

引入复杂 distributed provenance store

给所有 claim 加 LLM Judge

引入完整数据血缘平台
```

都没有必要。

StateBus 当前最重要的是先把：

```text
identity
binding
verification semantics
```

讲清楚。

---

# 80. 后续如果进入实现，应该先收什么边界

这里只记录，不执行。

未来可能的最小收口顺序：

```text
EP-0
SourceIdentity 语义统一

EP-1
CanonicalEvidencePack structural validator

EP-2
Evidence read-time hash verification

EP-3
Expansion authority / budget enforcement

EP-4
Source-backed hydration probe

EP-5
FieldLineage

EP-6
ClaimSupportBinding
```

不要第一步就做 entailment。

---

# 81. 推荐未来 Source Identity 结构

以后可能需要拆：

```text
SourceAssetIdentity
    asset_id
    content_digest
    media_type
    source_version
    locator_namespace
```

不要继续用一个：

```text
source_doc_hash
```

同时表达：

```text
logical dataset id
content digest
physical file identity
```

。

---

# 82. 推荐未来 Evidence Identity 结构

EvidenceItem 最终应该更接近：

```text
EvidenceItem
    evidence_id

    source_asset_id
    source_content_digest

    locator

    canonical_payload_hash
    extractor_id
    extractor_version

    rendered_view_hash

    evidence_type
```

其中：

```text
rendered_text
```

只是 view，

不是 source truth。

---

# 83. 推荐未来 Source-backed Hydration 逻辑

目标：

```text
EvidenceItem
    ↓
SourceAssetIdentity
    ↓
InputAssetRegistry
    ↓
open immutable source
    ↓
LocatorResolver
    ↓
re-extract
    ↓
canonicalize
    ↓
content hash compare
    ↓
HydratedEvidence
```

而不是：

```text
EvidencePack rendered_text
    ↓
dict
    ↓
return same text
```

。

---

# 84. 推荐未来 Field-level Lineage

Structured row 不应该只用一个 cell locator。

可以表达：

```python
FieldLineage(
    field_name="revenue",
    locator=TableCellLocator(...),
    canonical_value_hash=...,
)
```

一个 row：

```text
ProjectedRowLineage
    row_index
    evidence_item_id

    fields:
        quarter → locator A
        region  → locator B
        revenue → locator C
        cost    → locator D
```

这样 Claim numeric field 才能进一步绑定。

---

# 85. 推荐未来 Claim Support Contract

现在：

```text
supporting_evidence_item_ids
citation_locators
numeric_fields
```

是分离的。

更强的模型应是：

```python
ClaimSupport(
    support_id,
    evidence_item_id,
    artifact_ref_id,
    source_locator,
    artifact_field_path,
    claimed_value,
)
```

于是：

```text
Claim
    ↓
ClaimSupport[]
```

关系天然绑定。

---

# 86. 不需要立即做 Semantic Entailment Judge

比赛项目里优先级应该是：

```text
exact provenance
>
LLM entailment judge
```

因为：

```text
Judge
```

本身又会引入：

```text
额外 LLM 调用
不稳定性
cost
judge bias
```

更适合把：

```text
semantic entailment
```

作为：

```text
optional quality layer
```

而不是 StateBus correctness 的基础。

---

# 87. Batch 02 与 Batch 01 的关系

Batch 01 解决：

```text
谁有权决定做什么
```

Batch 02 解决：

```text
做的时候依据的事实到底是什么
```

两条链合起来：

```text
Task Contract
    ↓
Plan Authority
    ↓
Evidence Authority
    ↓
Execution
```

真正的系统原则应该是：

> **Planner 只提出语义行动；Runtime 不仅授权 Capability，还必须授权其可读取的 Evidence Source / Evidence Ref。**

---

# 88. Batch 02 与 Memory 的关系

Memory 以后复用的：

```text
Evidence
Artifact
Recipe
```

如果 source identity 本身不稳定，

Memory compatibility 就可能继承错误 lineage。

所以：

```text
Memory correctness
```

不能只看：

```text
embedding similarity
task family
artifact hash
```

还需要考虑：

```text
source lineage / input lineage
```

。

---

# 89. Batch 02 与 External Benchmark 的关系

External benchmark 尤其需要这个边界。

外部数据应该：

```text
Benchmark Harness
        ↓
Public InputAssetRef
        ↓
StateBus Asset Registry
        ↓
Runtime Retrieval
```

而不是：

```text
Benchmark Adapter
先解析出 table rows / facts
        ↓
StateBus 只接收已经整理好的答案结构
```

否则 External Generalization 又会变成：

```text
Adapter Generalization
```

而不是：

```text
StateBus Runtime Generalization
```

。

---

# 90. Batch 02 与 Non-text State 的关系

Embedding SemanticState 当前在这条链中的正确位置是：

```text
Candidate Evidence Surface
        ↓
Embedding / SemanticState
        ↓
Cross-process Selection
        ↓
Candidate IDs
        ↓
Hydration / EvidencePack
```

因此：

```text
Embedding
```

解决的是：

> 在已授权 Evidence Surface 中决定“看什么”。

它不负责：

```text
证明 evidence 是真的
```

也不负责：

```text
传递上游 Agent 的 latent reasoning
```

。

这一点进一步支持之前：

```text
Embedding
Hidden/Latent
Decision
KV
```

四类状态分层。

---

# 91. Batch 02 最终系统判断

当前 Evidence Plane 的成熟度可以概括成：

```text
Candidate identity                 强
Pack integrity                     强
Task/session binding               较强
Cross-PID semantic selection       强
Projection deterministic lineage   中等偏强
Source identity                    不统一
Source reconstruction              弱
Field-level lineage                弱
Claim exact support binding        中等
Claim semantic entailment          无
```

不是一个“有严重 bug、不能用”的系统。

真正的问题是：

> **当前内部 Contract 链已经比很多 Demo 强，但外部叙事容易把“Runtime traceability”说成“Source truth verification”。**

这个边界必须在后续设计、Benchmark 和答辩中保持准确。

---

# 92. 下一轮自然入口：Artifact Lifecycle / Verification / Commit / Replay

Batch 02 已经连续碰到：

```text
Projection
→ mark_verified()

ClaimSet
→ mark_verified()

CodeAct
→ verified artifact

Memory
→ replay_ready
```

所以 Batch 03 应直接审计：

```text
Candidate Artifact
        ↓
InputManifest
        ↓
Execution
        ↓
ArtifactOutputManifest
        ↓
Validator
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

重点回答：

```text
什么叫 VERIFIED？

谁有权 promote VERIFIED？

Validator 验了什么？

QualityReport 和 Artifact 状态是否一一绑定？

Artifact 被修改以后如何 invalidation？

VERIFIED 为什么等于 replay_ready？

Replay eligibility 有没有独立 authority？

Artifact persistence 是否真正 content-addressed？

Memory Commit 是否只接收当前仍然 valid 的 artifact？
```

这一条将是：

# **Execution Truth → Reuse Truth**

的完整审计。

---

# 93. Batch 02 一句话冻结结论

> **StateBus 当前已经具备一条真实的 Typed Evidence / Runtime-local Provenance 链，但 EvidencePack、Hydration、Projection 与 Claim 之间的 source/field/support binding 还没有全部闭环；因此当前最准确的定位是“可审计的 Runtime Evidence Graph”，而不是“所有事实均被重新从原始 Source 加密级验证的 provenance system”。**

---

# StateBus Batch 03 — Artifact Lifecycle / Verification / Commit / Replay Truthfulness 全链源码审计

> 项目：`qcrs/os`  
> 分支：`master`  
> 审计基线：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 日期：2026-09-03  
> 本轮状态：**只审计 / 只分析，不修改代码**  
>
> 审计主链：
>
> ```text
> Candidate Output
>     ↓
> Artifact Content / Manifest
>     ↓
> Input / Output / Capability Validator
>     ↓
> CapabilityQualityReport
>     ↓
> VERIFIED
>     ↓
> Settlement / Invalidation
>     ↓
> Replay Eligibility
>     ↓
> Artifact Restore / Recipe Recompute
>     ↓
> Memory Admission
> ```
>
> 本轮目标不是判断“有没有 SHA256”，而是回答六个问题：
>
> 1. **Artifact 的内容身份是什么？**
> 2. **谁有权把 Candidate 提升成 VERIFIED？**
> 3. **VERIFIED 到底代表哪一级正确性？**
> 4. **Artifact 状态失效后，旧 Ref 是否还能被使用？**
> 5. **Artifact VERIFIED 为什么可以/不可以 Replay？**
> 6. **Artifact Truth、Replay Truth、Memory Truth、Answer Adoption 是否被错误地绑在一起？**

---

# 1. Executive Summary

这一轮最重要的结论是：

> **StateBus 已经有相当不错的 Artifact 内容 hash、Capability Quality Report、历史 Replay hash 校验和下游 rehydrate 校验，但 Artifact Truth Promotion 目前没有唯一 Authority Owner；Artifact 内容身份、生成过程、验证强度、Replay 资格、Memory 写入资格、Answer Adoption 仍被多个字段和多条路径混在一起。**

当前至少存在两套 Artifact “晋级”体系：

```text
A. Legacy / General Commit Gate

Candidate
   ↓
InputValidatorReport
ArtifactValidatorReport
QualityFloor
AnswerAdopted
   ↓
RuntimeCommitGate
   ↓
VERIFIED / INVALIDATED
   ↓
Settlement
   ↓
Memory Commit
```

以及：

```text
B. Adaptive Product Mainline

DSL / CodeAct / Projection / Summarizer
   ↓
各自局部 ArtifactLifecycleManager()
   ↓
register_candidate()
   ↓
mark_verified()
   ↓
AdaptiveDispatchContext.artifacts
   ↓
下游直接消费
   ↓
Mainline 最后再单独判断是否 Memory Commit
```

这两套体系的最大区别是：

```text
Legacy:
“中央 CommitGate 决定 Artifact Truth”

Adaptive:
“Producer 自己完成局部验证，然后自己 mark_verified”
```

因此现在没有一个统一的：

# **Artifact Verification Authority**

这不是说 Adaptive 路径“不验证”。

事实上：

- DSL 有 schema + business validator + recomputation；
- CodeAct 有 sandbox + output validator + capability validator；
- ClaimSet 有 claim validator；
- Projection 是 deterministic Runtime transform；
- 下游还会重新读取真实文件并验证 blob hash。

问题在于：

> **这些不同强度、不同来源的验证最终都被压扁成同一个 `RefStatus.VERIFIED`，并且 `mark_verified()` 自动赋予 `replay_ready=True`。**

这是 Batch 03 的核心架构问题。

---

# 2. 当前 Artifact Truth 主链地图

主要源码：

```text
statebus/refs/models.py

statebus/runtime/workspace.py
statebus/runtime/commit_gate.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/transform_dsl.py
statebus/runtime/llm_codeact.py
statebus/runtime/evidence_projection.py
statebus/runtime/capability_validators.py
statebus/runtime/replay.py

statebus/state/disk.py

tests/test_replay.py
tests/test_adaptive_codeact_integration.py
tests/test_adaptive_mainline_integration.py
tests/test_adaptive_claims.py
...
```

核心对象：

```text
ExecutionArtifactRef
InputManifest
ArtifactOutputManifest

ArtifactValidatorReport
InputValidatorReport
CapabilityQualityReport

ArtifactSettlementRecord
ArtifactInvalidationRecord

ArtifactLifecycleManager
RuntimeCommitGate

ReplayCandidate
ReplayLedgerEntry
HistoryReplayRecord
MemoryCommit
```

---

# 3. `ExecutionArtifactRef` 当前表达了什么

当前 Artifact Ref：

```python
ExecutionArtifactRef(
    artifact_id,
    task_id,
    step_id,
    artifact_type,

    root_id,
    relpath,

    blob_hash,
    size_bytes,

    produced_by,

    verification_state,
    replay_ready,

    workspace_relpath,
    manifest_hash,

    metadata,
)
```

它已经同时承载四类语义：

```text
A. Logical identity
    artifact_id
    task_id / step_id

B. Physical location
    root_id
    relpath
    workspace_relpath

C. Content identity
    blob_hash
    size_bytes

D. Lifecycle / reuse
    verification_state
    replay_ready

E. Derivation / sidecar pointer
    manifest_hash
    metadata
```

这在早期很方便。

但随着 Artifact 类型增多，它已经开始出现：

```text
one field
multiple semantics
```

的问题。

最典型的就是：

# `manifest_hash`

---

# 4. P0 — `manifest_hash` 的语义已经发生严重 Overload

Legacy History Replay 中：

```text
ExecutionArtifactRef.manifest_hash
=
ArtifactOutputManifest.manifest_hash
```

这是一种很清晰的语义：

```text
Artifact Ref
    ↓ manifest_hash
ArtifactOutputManifest
    ↓
output name / relpath / size / sha256
```

但是 Adaptive 主线不同 Producer 填的值并不一样。

---

# 5. Projection Artifact 的 `manifest_hash`

`EvidenceProjectionAdapter` 当前写：

```text
manifest_hash
=
EvidenceProjectionRequest.request_hash
```

所以这里的 `manifest_hash` 实际是：

```text
Projection Request Identity
```

不是：

```text
ArtifactOutputManifest Identity
```

。

---

# 6. Transform DSL Artifact 的 `manifest_hash`

`TransformDslInterpreter.run_verified()` 写：

```text
manifest_hash
=
TransformProgram.program_hash
```

所以这里实际是：

```text
Derivation / Program Identity
```

。

---

# 7. CodeAct Artifact 的 `manifest_hash`

`LlmCodeActRunner` 写：

```text
manifest_hash
=
CodeGenerationRequest.input_manifest_digest
```

这里又变成：

```text
Input Manifest / Semantic Input Identity
```

。

---

# 8. ClaimSet Artifact 的 `manifest_hash`

Summarizer 写：

```text
manifest_hash
=
sha256(claim_set.canonical_payload())
```

它几乎等于：

```text
ClaimSet Content Identity
```

。

---

# 9. 当前四种语义汇总

| Artifact Producer | `manifest_hash` 实际指向 |
|---|---|
| Legacy History Artifact | `ArtifactOutputManifest.manifest_hash` |
| Evidence Projection | Projection Request hash |
| Transform DSL | Program hash |
| LLM CodeAct | Input manifest digest |
| ClaimSet | ClaimSet content hash |

所以：

> **`ExecutionArtifactRef.manifest_hash` 已经没有统一 referent。**

这不是命名风格问题。

它会直接影响：

```text
Ref Registry
History Replay
Artifact Persistence
Cross-run Restore
Audit
Future CAS
```

。

因为 Legacy `runtime/replay.py::_load_history_artifact_ref()` 明确假设：

```text
entry.manifest_hash
    ↓
read_artifact_output_manifest(manifest_hash)
```

对 Adaptive DSL / CodeAct / Projection / Claim Artifact，这个假设并不成立。

因此当前：

# Adaptive Artifact Ref 与 Legacy Artifact Replay Contract 并不是统一 ABI。

---

# 10. Target：Artifact Content 与 Artifact Derivation 必须拆开

推荐以后不要继续用一个 `manifest_hash` 表达所有东西。

至少概念上拆成：

```text
ArtifactContentDescriptor
    ↓
“产物本身是什么”

ArtifactDerivationReceipt
    ↓
“它是怎么被生成的”

ArtifactVerificationReceipt
    ↓
“Runtime 验证了什么”

ArtifactLocationBinding
    ↓
“现在在哪里 materialize”
```

这四件事生命周期都不同。

---

# 11. P0 — `mark_verified()` 不是 Verification，它只是状态切换

当前：

```python
ArtifactLifecycleManager.mark_verified(artifact_id)
```

逻辑本质是：

```text
取当前 ArtifactRef
    ↓
verification_state = VERIFIED
replay_ready = True
    ↓
写回 dict
```

它本身没有验证：

```text
文件是否存在
size 是否一致
blob hash 是否一致
validator report 是否存在
validator report 是否通过
quality report 是否绑定该 output hash
input lineage 是否完整
CapabilityGrant 是否匹配
```

。

因此：

> `mark_verified()` 这个名字比真实行为强。

它实际更像：

```text
promote_to_verified_state()
```

并假设：

```text
调用方已经完成所有验证
```

。

---

# 12. 这本身不是绝对错误

很多系统都会有：

```text
validator
    ↓
commit state transition
```

。

问题在于当前：

```text
没有一个统一 ArtifactVerificationPolicy
来决定谁有资格调用 mark_verified
```

。

Projection、DSL、CodeAct、Summarizer 都自己构造一个新的：

```python
ArtifactLifecycleManager()
```

然后直接：

```text
register_candidate()
mark_verified()
```

。

所以 `ArtifactLifecycleManager` 并不是一个真正共享的 Runtime authority object。

---

# 13. P0 — Artifact Truth Promotion 存在两套 Authority

## Path A — `RuntimeCommitGate`

旧路径：

```text
quality floor
+
answer adopted
+
artifact validator reports
+
input validator reports
    ↓
mark_verified
    ↓
Memory commit
    ↓
Settlement
```

。

这里 promotion 是：

```text
Centralized
```

。

---

# 14. Path B — Adaptive Producers

### Evidence Projection

```text
Projection deterministic transform
    ↓
register_candidate
    ↓
mark_verified
```

。

### Transform DSL

```text
program validation
business quality validation
    ↓
run_verified()
    ↓
register_candidate
    ↓
mark_verified
```

。

### CodeAct

```text
Source Policy
Sandbox
Output Validator
CapabilityQualityReport
    ↓
register_candidate
    ↓
mark_verified
```

。

### ClaimSet

```text
ClaimSetValidator
    ↓
register_candidate
    ↓
mark_verified
```

。

这些 Artifact 进入：

```text
AdaptiveDispatchContext.artifacts
```

以后，下游就可以按：

```text
verification_state == VERIFIED
```

消费。

---

# 15. 这意味着什么

现在 Artifact Truth 的 owner 是：

```text
Producer-local validator + Producer-local lifecycle
```

而不是：

```text
Runtime Artifact Authority
```

。

这和 StateBus 一直强调的：

```text
Agents propose;
Runtime authorizes.
```

在 Artifact 层还不完全一致。

更准确：

```text
Provider validates and self-promotes;
Runtime later consumes the promoted Ref.
```

。

---

# 16. P0 — `VERIFIED` 自动意味着 `replay_ready=True`

当前 `mark_verified()`：

```text
VERIFIED
+
replay_ready=True
```

是一起发生的。

这是这一轮最重要的设计耦合之一。

因为：

# Artifact Verification ≠ Replay Eligibility

---

# 17. 为什么两者不同

Artifact Verification 回答：

```text
“这个输出现在能不能被当前 Workflow 当成有效 Artifact 使用？”
```

Replay Eligibility 回答：

```text
“未来另一个运行能不能跳过某些计算，直接复用这个 Artifact / Recipe？”
```

后者需要额外考虑：

```text
determinism
runtime version
provider version
validator version
input identity
output contract
policy version
source/program identity
side effects
security scope
lifetime
```

。

因此：

```text
Artifact valid now
```

绝对不自动推出：

```text
Artifact safe to replay later
```

。

---

# 18. Generic Validator 正好证明这个问题

`CapabilityQualityReport` 已经有很好的 nuance：

```text
verified
recomputation_evaluated
recomputation_passed
semantic_verification_status
```

。

例如 `generic_analysis`：

```text
schema/provenance/completion checks
可以全部通过

verified = True

但是：

recomputation_evaluated = False
recomputation_passed = False
semantic_verification_status = not_evaluated
```

。

这说明 Contract 层已经承认：

```text
VERIFIED
```

并不总表示：

```text
独立语义重算已证明正确
```

。

但 Artifact 层把所有这些情况压成：

```text
RefStatus.VERIFIED
replay_ready=True
```

。

因此信息被丢失了。

---

# 19. 推荐 `VerificationStrength`

建议未来 Artifact Verification 至少区分：

```text
STRUCTURAL
    文件/hash/schema/provenance 检查

CONTRACT_VALIDATED
    Capability 业务合同已检查

INDEPENDENT_RECOMPUTATION
    Runtime 独立重算并与 output 比较

EXTERNAL_EVALUATED
    只作为外部 benchmark audit
    不进入 Runtime replay authority
```

其中：

```text
EXTERNAL_EVALUATED
```

不能把 benchmark private grader 回灌 Runtime。

它只是 Harness 的 Evidence。

---

# 20. P0 — `RuntimeCommitGate` 把 Answer Adoption 混进 Artifact Truth

当前 `RuntimeCommitGate.finalize()`：

```text
if:
    quality_floor_pass
    AND answer_adopted
    AND validator_reports_passed
    AND input_validators_passed

then:
    Artifact → VERIFIED
```

否则：

```text
Artifact → INVALIDATED
```

。

这意味着：

```text
Artifact 技术上完全正确
+
Validator 全通过
+
Quality Floor 通过
+
用户/上层没有 adopted
```

仍然会：

```text
INVALIDATED
```

。

这是错误的语义耦合。

---

# 21. 更具体的代码问题：错误 Invalidation Reason

Else 分支的 invalidation reason：

```text
input_validator_failed
else validator_failed
else quality_floor_failed
```

没有：

```text
answer_not_adopted
```

这个分支。

所以：

```text
quality_floor_pass = True
validators = True
answer_adopted = False
```

最终会记录：

```text
invalidation_reason = quality_floor_failed
quality_floor_pass = False
```

。

但真实情况明明：

```text
quality floor passed
```

。

这是一个明确的：

# **Audit Truth Bug**

。

---

# 22. Artifact Truth / Answer Adoption 应彻底分开

正确关系：

```text
Artifact Verification
    ├─ verified
    └─ invalid

Answer Adoption
    ├─ adopted
    └─ not adopted

Memory Admission
    ├─ admitted
    └─ rejected

Replay Eligibility
    ├─ eligible
    └─ ineligible
```

四个状态应该正交。

例如：

```text
Artifact:
VERIFIED

Answer:
NOT_ADOPTED

Memory:
NOT_ADMITTED

Replay:
ELIGIBLE
```

完全合法。

---

# 23. 更有意思的是：Adaptive Mainline 又使用了另一种 Adoption 语义

Adaptive `_commit_verified_memory()` 最终直接：

```python
memory_store.commit_candidate(
    quality_floor_pass=True,
    answer_adopted=True,
)
```

也就是：

```text
answer_adopted=True
```

被硬编码。

它不是用户 adoption，也不是 final answer adoption。

它只是：

```text
“Runtime 决定把 verified recipe 写 Memory”
```

。

因此现在同一个字段：

```text
answer_adopted
```

在两套路径中实际上有不同含义。

---

# 24. P0/P1 — Empty Validator Tuple 会 Vacuous Pass

`RuntimeCommitGate`：

```python
validator_reports_passed = all(validator_reports)
input_validators_passed = all(input_validator_reports)
```

准确代码是对 `report.passed` 做 `all(...)`。

如果传：

```text
validator_reports = ()
input_validator_reports = ()
```

Python：

```text
all(()) == True
```

。

所以 CommitGate Contract 本身允许：

```text
没有任何 validator report
```

却被视为：

```text
validators_passed = True
```

。

如果上层的 `quality_floor` 与 adoption 又是 True：

```text
Artifact 可以 VERIFIED
```

。

当前某些 caller 可能总会提供 report，所以这不一定已形成实际主线 bug。

但作为：

```text
Runtime Truth Promotion API
```

这是明显的 fail-open contract seam。

---

# 25. P0/P1 — Artifact Lifecycle 没有合法 Transition Policy

当前 Lifecycle Manager：

```text
register_candidate
mark_verified
mark_invalidated
```

只是覆盖状态。

例如：

```text
CANDIDATE → VERIFIED
```

可以。

但：

```text
INVALIDATED → VERIFIED
```

同样可以直接调用。

也没有：

```text
VERIFIED → VERIFIED
```

重复 promotion 限制。

没有：

```text
expected_previous_state
```

。

所以它现在不是严格 state machine。

---

# 26. 推荐真正的 Lifecycle State Machine

第一版不需要复杂：

```text
PRODUCING
    ↓
CANDIDATE
    ↓
VERIFIED
    ↓
ACTIVE
    ├─ SUPERSEDED
    ├─ INVALIDATED
    └─ EXPIRED
```

。

其中：

```text
ReplayEligibility
```

仍然保持 orthogonal。

---

# 27. P1 — `ArtifactLifecycleManager` 是局部 ephemeral object

DSL：

```python
lifecycle = ArtifactLifecycleManager()
```

CodeAct：

```python
lifecycle = ArtifactLifecycleManager()
```

Projection：

```python
lifecycle = ArtifactLifecycleManager()
```

Summarizer：

```python
lifecycle = ArtifactLifecycleManager()
```

。

每个 Producer 都临时创建自己的 manager。

返回 ArtifactRef 以后：

```text
manager 自身很快失去作用域
```

。

---

# 28. 这会导致 Logical Revocation 问题

下游 Context 中保存：

```text
一个 immutable ExecutionArtifactRef
verification_state = VERIFIED
```

假如后来 Artifact 被：

```text
INVALIDATED
```

某个旧 holder 手里的 Ref 仍然是：

```text
VERIFIED
```

。

当前下游 `_artifact_in_grant_scope()` 主要检查这个本地 Ref 的：

```text
verification_state
task
session
attempt
```

不会去一个 central lifecycle registry 查询：

```text
这个 artifact 现在是不是仍 ACTIVE
```

。

所以：

# **Stale Verified Ref 不具备中央 revocation 语义。**

---

# 29. 当前什么能挡住篡改

这里要区分：

```text
Logical Revocation
```

和：

```text
Content Tampering
```

。

Content Tampering 其实做得不错。

`_read_verified_artifact_rows()` 会：

```text
resolve root/path
确保 path 在 root 下
拒绝 symlink
读取 bytes
检查 size
检查 blob hash
JSON decode
与 cached rows 比较
```

。

所以：

```text
文件内容被改
```

通常会 fail closed。

---

# 30. 但逻辑状态失效不是同一件事

例如：

```text
artifact bytes 没变

但是后来发现：
validator 有 bug
source provenance 被撤销
policy version 失效
```

这种：

```text
Logical INVALIDATED
```

不会改变：

```text
blob hash
```

。

所以仅靠 blob hash 无法表达：

```text
这个 Artifact 还能不能被信任
```

。

必须有 central current-state / verification receipt。

---

# 31. P1 — Settlement / Invalidation 不是 Append-only Event History

`ArtifactLifecycleManager`：

```text
settlement_records[artifact_id] = record
invalidation_records[artifact_id] = record
```

。

`JsonContractStore` 也把：

```text
artifact_settlements/{artifact_id}.json
artifact_invalidations/{artifact_id}.json
```

作为单文件写入。

结果：

```text
同一个 Artifact 后续再发生 transition
```

会覆盖之前对应类型的记录。

---

# 32. 为什么 Artifact 需要 Event History

真正审计经常需要知道：

```text
CANDIDATE
    ↓ validator v1
VERIFIED
    ↓ validator bug found
INVALIDATED
    ↓ re-evaluated with validator v2
? 
```

。

如果只保留：

```text
latest settlement
latest invalidation
```

很多历史会丢失。

---

# 33. 推荐 Append-only Lifecycle Ledger

例如：

```python
ArtifactLifecycleEvent(
    event_id,
    artifact_id,
    content_digest,

    previous_state,
    new_state,

    reason,

    verification_receipt_hashes,
    replay_receipt_hash,

    created_at_ns,

    previous_event_hash,
)
```

。

不一定需要区块链。

一个简单：

```text
append-only JSONL / SQLite event table
```

就够。

---

# 34. P1 — Settlement Record 本身没有进入 Replay 的强 hash chain

`ArtifactSettlementRecord` 有：

```text
settlement_hash
```

property。

但 persistence：

```text
write_artifact_settlement_record()
```

写的是：

```text
record.canonical_payload()
```

不包含：

```text
settlement_hash
```

。

History Replay 读取：

```text
settlement_payload["replay_ready"]
```

直接使用。

没有：

```text
recompute settlement hash
+
compare expected receipt hash
```

。

在当前：

```text
local trusted filesystem
```

模型下不一定是安全漏洞。

但它说明：

```text
settlement
```

目前是：

```text
mutable local metadata
```

不是：

```text
tamper-evident receipt
```

。

---

# 35. P1 — Registry Status 与 Settlement `replay_ready` 没有强一致性检查

History Replay `_load_history_artifact_ref()`：

```text
RefRegistry entry
    ↓
entry.status

ArtifactSettlementRecord
    ↓
replay_ready

ArtifactOutputManifest
    ↓
output hash/path
```

然后构造：

```text
ExecutionArtifactRef(
    verification_state = entry.status,
    replay_ready = settlement.replay_ready
)
```

。

但是后面的 `_history_replay_records()` 只重点检查：

```text
artifact_ref.replay_ready
```

没有明确要求：

```text
artifact_ref.verification_state == VERIFIED
```

。

---

# 36. 这意味着状态不一致时可能出现危险组合

例如持久状态因为 crash / manual mutation / incomplete invalidation 形成：

```text
Registry:
INVALIDATED

Settlement:
replay_ready = True
```

当前 History Replay 仍有机会继续把它当 Replay Candidate。

它最终还会校验 output bytes hash，

但：

```text
内容没变
```

不代表：

```text
logical verification 仍有效
```

。

因此：

# Replay Admission 必须同时验证 Current Lifecycle State。

---

# 37. P1 — Invalidation 传播到 Memory / Replay 目前没有统一机制

Current Artifact 可能同时被引用在：

```text
Context.artifacts

RefRegistry

MemoryRef.artifact_ref_id

ReplayLedger

ArtifactSettlement

Adaptive Mainline manifest
```

。

Artifact invalidation 发生以后：

```text
哪些引用会被更新？
```

目前没有一个统一：

```text
Invalidation Propagation
```

协议。

---

# 38. Target 原则

Memory / Replay 中不要复制：

```text
artifact is trusted
```

这个事实。

而应该保存：

```text
artifact_id / content digest
```

每次使用时查询：

```text
ArtifactAuthorityStore
```

或读取：

```text
current lifecycle / verification receipt
```

。

这样：

```text
一次 invalidation
```

才能全局生效。

---

# 39. P1 — Artifact ID Collision 默认是 Last-write-wins

`register_candidate()`：

```python
self.artifacts[candidate.artifact_id] = candidate
```

没有：

```text
if artifact_id already active:
    reject
```

。

当前 Artifact ID 大多：

```text
task + step + attempt
```

正常 Runtime 下通常唯一。

但 Contract 层仍然没有保证：

```text
same ID cannot bind different content
```

。

这和前面 State Ref duplicate-id 问题一致。

---

# 40. 推荐 Artifact Identity 分层

不要把：

```text
artifact_id
```

同时当：

```text
logical name
content identity
generation identity
```

。

推荐：

```text
artifact_id
    logical artifact identity

generation
    lifecycle generation

content_digest
    immutable bytes identity
```

。

---

# 41. P1 — Workspace Artifact Write 不是 Crash-atomic

`WorkspaceManager.write_json()`：

```text
path.write_bytes(rendered)
```

。

DSL：

```text
output_path.write_bytes(payload)
```

Claim：

```text
output_path.write_bytes(payload)
```

CodeAct sandbox 自己写 output。

目前没有统一：

```text
temp
fsync
atomic rename
```

promotion protocol。

---

# 42. 为什么 hash 不能完全解决 Crash Atomicity

如果 crash 发生在：

```text
write file
    ↓
write metadata
```

之间，

重启以后可能看到：

```text
有 payload
没 registry
```

。

反过来，如果 publication 顺序错：

```text
registry ACTIVE
payload 还没 durable
```

风险更高。

正确顺序：

```text
payload durable
    ↓
verification receipts durable
    ↓
registry visibility last
```

。

---

# 43. P1 — RuntimeCommitGate 不是 Transaction

成功 path：

```text
mark_verified()
    ↓
memory_store.commit_candidate()
    ↓
record_settlement()
```

。

假设：

```text
mark_verified 成功
memory_store 写失败
```

则当前 Runtime 内：

```text
Artifact 已 VERIFIED
```

但：

```text
Memory 未 commit
Settlement 未记录
```

。

---

# 44. 失败 path 也一样

```text
mark_invalidated()
    ↓
memory_store.commit_candidate(candidate)
    ↓
record settlement
    ↓
record invalidation
```

中间任意错误都会留下 partial state。

因此它并不是：

```text
Commit Gate Transaction
```

。

更准确：

```text
Commit Gate Orchestration
```

。

---

# 45. Artifact Truth 和 Memory Truth 不应该放在同一个 Transaction

这里更深一层：

其实没有必要追求：

```text
Artifact + Memory
必须一个跨 Store ACID transaction
```

。

更合理：

```text
Artifact Verification
先独立 durable commit

然后：

MemoryAdmissionPolicy
读取 verified Artifact
    ↓
独立 Memory commit
```

。

如果 Memory commit 失败：

```text
Artifact 仍然 VERIFIED
```

这是正确的。

所以真正应该拆开的是 authority，而不是强绑 transaction。

---

# 46. Target Promotion Protocol

推荐概念流程：

```text
Provider writes temp output
        ↓
Basic structural validation
        ↓
fsync temp
        ↓
compute content digest + size
        ↓
ArtifactContentDescriptor
        ↓
ArtifactDerivationReceipt
        ↓
Capability Validators
        ↓
ArtifactVerificationReceipt
        ↓
atomic materialization / CAS insert
        ↓
Lifecycle Event:
CANDIDATE → VERIFIED
        ↓
Registry ACTIVE pointer commit last
```

之后另走：

```text
ReplayEligibilityPolicy
```

和：

```text
MemoryAdmissionPolicy
```

。

---

# 47. P1 — DSL 的 Quality Report 与最终 Materialized Output 缺显式再绑定

Adaptive DSL path 先：

```text
transform_interpreter.run(program)
    ↓
transformed
```

然后 Validator：

```text
CapabilityQualityReport.output_artifact_hash
=
hash(transformed)
```

。

接着：

```text
TransformDslInterpreter.run_verified()
```

又执行一次：

```text
self.run(program, inputs)
```

然后写 Artifact。

`run_verified()` 只检查：

```text
quality_report.verified
```

没有显式：

```text
quality_report.output_artifact_hash
==
final output_hash
```

。

---

# 48. 当前为什么通常没出问题

因为 DSL Interpreter 是 deterministic。

同一个：

```text
program + inputs
```

第二次通常会生成完全相同 stable rows。

而 Adaptive Mainline 后面的 Memory commit 也会再次验证：

```text
QualityReport.output_artifact_hash
==
Artifact.blob_hash
```

。

所以当前 Mainline Memory commit 有兜底。

---

# 49. 但下游 Artifact 消费发生在 Mainline Memory commit 之前

Artifact 一旦：

```text
run_verified()
→ mark_verified()
```

就进入 Context。

后续 Summarizer 可以读取。

因此：

```text
final output digest
和 quality report digest
```

最好在 Artifact promotion 当场绑定，

不能依赖后面的 Memory commit 再证明。

---

# 50. CodeAct 在这一点反而更完整

CodeAct：

```text
sandbox output
    ↓
_validate_output()
    ↓
output_hash
    ↓
CapabilityQualityReport(output_artifact_hash=output_hash)
    ↓
ExecutionArtifactRef(blob_hash=output_hash)
```

因此：

```text
QualityReport
Artifact
```

在同一份真实 sandbox output bytes 上绑定。

这是好的。

---

# 51. P1 — Verification Strength 被 `RefStatus` 压扁

我们可以把当前 Artifact producer 分类：

| Producer | 实际验证强度 |
|---|---|
| Evidence Projection | Trusted deterministic Runtime transform |
| Transform DSL | Contract + often independent recomputation |
| CodeAct generic | Sandbox + schema/provenance/contract，可能未 independent recompute |
| CodeAct formal business validator | 可能 independent recompute |
| ClaimSet | Structural claim/provenance validation |
| Legacy CommitGate artifact | 取决于 supplied validators / quality floor |

但全部最终：

```text
verification_state = VERIFIED
```

。

所以消费者无法单从 RefStatus 知道：

```text
这个 Artifact 到底被验证到了哪一层
```

。

---

# 52. 推荐 Verification Receipt 而不是增加十几个 RefStatus

不要做：

```text
VERIFIED_SCHEMA
VERIFIED_RECOMPUTED
VERIFIED_PROVENANCE
...
```

让状态机爆炸。

更合理：

```text
Artifact state = VERIFIED

VerificationReceipt:
    schema_passed
    provenance_passed
    contract_passed
    recomputation_evaluated
    recomputation_passed
    verification_strength
    validator identities
```

。

Consumer policy 决定：

```text
当前 capability 需要哪一级 VerificationStrength
```

。

---

# 53. History Replay 当前做对了什么

这一部分必须肯定。

`tests/test_replay.py` 已经专门构造：

```text
declared output hash
≠
actual output bytes
```

然后要求：

```text
load_history_replay_candidates()
    ↓
{}
```

。

`_matching_history_output_path()` 也确实会：

```text
read actual bytes
    ↓
sha256
    ↓
compare expected blob hash
```

。

所以：

# History Replay 不是只相信 metadata。

这是很重要的正确设计。

---

# 54. P1 — History Replay 的 Path Verification 比 Adaptive Artifact Read 弱

Adaptive `_read_verified_artifact_rows()`：

```text
root.resolve(strict=True)

path.resolve(strict=True)

path.is_relative_to(root)

reject symlink

is_file

size check

blob hash check
```

。

History `_matching_history_output_path()` 当前主要：

```text
construct path
exists
read bytes
hash match
```

。

没有同等级的：

```text
resolved containment
symlink rejection
size check
```

。

---

# 55. 为什么这个值得修

History Root 是：

```text
persisted / imported state
```

比同一 process 内刚生产的 Artifact 更应该使用严格 path validation。

Target 应统一一个：

```text
ArtifactResolver
```

，所有：

```text
current run
history replay
memory restore
```

都调用同一份 path/content verification。

---

# 56. Exact Replay Key 本身不包含 Output Hash —— 这不是 Bug

Current exact key：

```text
CanonicalTaskSpec
input artifact hashes
runtime signature
code template version
extractor version
output contract
```

没有：

```text
historical output hash
```

。

这是合理的。

因为 lookup 时是在回答：

```text
“当前 action/input identity
是否和历史 action/input identity 相同？”
```

输出 hash 是：

```text
cache result descriptor
```

的一部分，不应成为 lookup key 的必要输入。

---

# 57. 但 Exact Replay 需要 Determinism Contract

真正的问题是：

> 这些 key 是否完整捕获了所有决定输出的因素？

例如：

```text
model identity
temperature
random seed
provider version
program/source hash
tool version
environment variables
time-dependent input
external network state
```

。

如果 Artifact producer 不是 deterministic，

就算 input key 一样：

```text
output
```

也未必应该直接 restore。

因此推荐：

```text
DeterminismClass
```

。

---

# 58. 推荐 DeterminismClass

```text
DETERMINISTIC
    DSL / pure deterministic builtin

BOUNDED_REEXECUTABLE
    Code recipe 可重算，但 output 不应直接 restore

NONDETERMINISTIC
    model/tool/environment dependent

EXTERNAL_STATE_DEPENDENT
    时间/网络/外部服务依赖
```

。

然后：

```text
ARTIFACT_RESTORE
```

只允许：

```text
DETERMINISTIC
+
exact identity
```

。

而 CodeAct / LLM 过程更自然：

```text
RECIPE_RECOMPUTE
```

。

---

# 59. 这与 Round 04 Replay Taxonomy 完全一致

推荐继续冻结：

```text
ASSIST_CONTEXT
RECIPE_RECOMPUTE
ARTIFACT_RESTORE
```

。

不要继续让：

```text
EXACT_REPLAY
```

一个词同时表示：

```text
exact recipe
exact artifact
```

。

---

# 60. P1 — Adaptive Artifact 目前通常没有完整 ArtifactOutputManifest / Settlement

Adaptive Producer 创建：

```text
ExecutionArtifactRef
```

后存进 Context。

但它们一般不会自动写：

```text
ArtifactOutputManifest
ArtifactSettlementRecord
RefRegistry Entry
```

形成一个与 Legacy History Replay 一致的 bundle。

这说明：

```text
Adaptive Runtime Artifact
```

当前主要是：

```text
in-run Ref
```

。

而：

```text
Legacy Replay Artifact
```

是：

```text
persisted replay bundle
```

。

两者还没有统一 Artifact persistence ABI。

---

# 61. 这会影响什么

未来如果想：

```text
Adaptive Run A
产生 Artifact
    ↓
Run B
Exact Artifact Restore
```

不能只拿：

```text
ExecutionArtifactRef
```

就认为 old Replay loader 一定能识别。

必须先统一：

```text
ArtifactContentDescriptor
ArtifactDerivationReceipt
ArtifactVerificationReceipt
ArtifactLifecycleReceipt
ArtifactLocation
```

。

---

# 62. P1 — Root Identity 语义也不统一

Adaptive Artifact：

```text
root_id
通常是绝对 attempt workspace path
```

。

Legacy History Test：

```text
root_id = "workspace"
```

真正 Replay 查文件时又主要通过：

```text
RuntimeTaskSession.workspace_root
+
artifact relpath
```

。

所以：

```text
root_id
```

当前同时可能表示：

```text
physical absolute path
logical root name
```

。

这和 `manifest_hash` 一样，是 contract semantic overload。

---

# 63. 推荐 `ArtifactLocationBinding`

```python
ArtifactLocationBinding(
    artifact_digest,
    materialization_id,

    root_kind,
    root_id,

    relpath,

    readonly,

    created_at_ns,
)
```

。

Content identity 不依赖 location。

同一个 Artifact 可以：

```text
workspace materialization
CAS materialization
history import
```

有多个 location。

---

# 64. 外部对照 1：OCI Content Descriptor

OCI 的 Content Descriptor 核心非常简单：

```text
mediaType
digest
size
```

并强调：

```text
从不可信 source 读取内容时
先检查 size
再验证 digest
再做重处理
```

。

StateBus 不需要实现 OCI Image。

值得借的只有：

> **Artifact 的 content identity 应该极小、稳定、与 provenance 分离。**

对应：

```python
ArtifactContentDescriptor(
    media_type,
    digest,
    size_bytes,
)
```

。

当前 `ExecutionArtifactRef.blob_hash + size_bytes + artifact_type`
已经非常接近。

应该保留并强化。

---

# 65. 外部对照 2：Bazel Action Cache + CAS

Bazel Remote Cache 明确分成：

```text
Action Cache
    action hash
        ↓
    result metadata

Content Addressable Store
    content hash
        ↓
    output bytes
```

。

这个分离对 StateBus 非常有启发。

当前 StateBus 把：

```text
program hash
input manifest hash
output manifest hash
claim hash
```

都塞进：

```text
manifest_hash
```

。

更合理：

```text
Action / Derivation Identity
    ↓
ArtifactDerivationReceipt

Content Identity
    ↓
Artifact CAS Descriptor
```

。

Replay：

```text
Action/Replay Key
    ↓
Result Descriptor
    ↓
CAS Digest
```

而不是：

```text
一个 manifest_hash 搞定一切
```

。

---

# 66. 外部对照 3：Nix Content Address vs Derivation

Nix 的一个非常适合 StateBus 的思想是：

> **Output 的 content address 只取决于 output object 本身；它如何被构建，是另一条 derivation identity。**

这正好映射：

```text
Artifact Content
≠
Execution Recipe / Program
≠
Capability Grant
≠
Planner Plan
```

。

当前 StateBus 其实已经拥有这些信息，

只是没有完全分开建模。

---

# 67. 外部对照 4：SLSA Provenance

SLSA Provenance 把 Artifact provenance 大致分成：

```text
subject
    产物 identity

buildDefinition
    怎么构建
    parameters
    resolved dependencies

runDetails
    谁构建
    invocation
    execution details
```

。

StateBus 可以直接借结构思想：

```text
subject
    → ArtifactContentDescriptor

buildDefinition
    → capability
      output contract
      approved plan
      input refs
      recipe/source/program

resolvedDependencies
    → input artifact/evidence digests

builder
    → StateBus Runtime + Provider

invocationId
    → RunID / Step / Attempt

runDetails
    → ExecutionReceipt
```

。

不需要：

```text
做 SLSA 合规
做签名服务
做供应链平台
```

。

只需要学习：

# “产物是什么” 与 “产物怎么来的” 分开。

---

# 68. 不建议当前引入 Sigstore / Public Signature

当前比赛环境：

```text
single local Runtime
trusted local control plane
```

。

主要风险不是：

```text
公网第三方伪造 Artifact 签名
```

。

所以没必要：

```text
Sigstore
Transparency Log
Public PKI
```

。

如果未来：

```text
跨机器
Remote Executor
Untrusted Artifact Store
```

再考虑：

```text
signed verification receipts
```

。

现在 hash chain + local authority 足够。

---

# 69. Target Architecture

推荐 Artifact Plane 最终结构：

```text
Provider
   ↓
Temporary Output
   ↓
ArtifactContentDescriptor
   │
   ├─ type
   ├─ size
   └─ digest
   ↓
ArtifactDerivationReceipt
   │
   ├─ Task / Run / Session
   ├─ Plan
   ├─ CapabilityGrant
   ├─ Provider
   ├─ Inputs
   ├─ Program / Source / Prompt
   └─ Output Contract
   ↓
ValidatorRegistry
   ↓
ArtifactVerificationReceipt
   │
   ├─ Validator identity
   ├─ exact output digest
   ├─ schema
   ├─ provenance
   ├─ completion
   ├─ recomputation
   └─ verification strength
   ↓
LifecyclePolicy
   ↓
VERIFIED Artifact
   ↓
┌─────────────────────────┬────────────────────────┐
│                         │                        │
▼                         ▼                        ▼
ReplayEligibility     MemoryAdmission       AnswerAdoption
```

三个后续决策彼此独立。

---

# 70. Target Contract：`ArtifactContentDescriptor`

```python
@dataclass(frozen=True)
class ArtifactContentDescriptor:
    artifact_id: str
    generation: int

    media_type: str

    digest: str
    size_bytes: int

    schema_version: str
```

。

最重要原则：

```text
content descriptor
不能包含：
task ID
program hash
validator
replay flag
path
```

。

它只回答：

```text
“这些 bytes 是什么”
```

。

---

# 71. Target Contract：`ArtifactDerivationReceipt`

```python
@dataclass(frozen=True)
class ArtifactDerivationReceipt:
    artifact_id: str
    generation: int

    task_contract_hash: str
    run_id: str
    session_id: str
    step_id: str
    attempt_id: str

    approved_plan_hash: str
    capability_grant_hash: str

    logical_capability_id: str
    execution_provider_id: str

    input_artifact_digests: tuple[str, ...]
    input_evidence_digests: tuple[str, ...]

    program_hash: str = ""
    source_hash: str = ""
    prompt_bundle_hash: str = ""
    policy_digest: str = ""

    output_contract_version: str = ""

    receipt_hash: str = ""
```

。

---

# 72. Target Contract：`ArtifactVerificationReceipt`

```python
@dataclass(frozen=True)
class ArtifactVerificationReceipt:
    artifact_id: str
    generation: int

    content_digest: str

    validator_ids: tuple[str, ...]
    validator_bundle_digest: str

    report_hashes: tuple[str, ...]

    schema_passed: bool
    provenance_passed: bool
    completion_passed: bool

    recomputation_evaluated: bool
    recomputation_passed: bool

    verification_strength: str

    verified: bool

    verified_at_ns: int
    receipt_hash: str
```

。

---

# 73. Target Contract：`ReplayEligibilityReceipt`

```python
@dataclass(frozen=True)
class ReplayEligibilityReceipt:
    artifact_id: str
    generation: int
    content_digest: str

    eligible: bool

    reuse_mode: str
    # artifact_restore
    # recipe_recompute
    # not_replayable

    determinism_class: str

    exact_key: str
    compatibility_fingerprint: str

    runtime_signature: str
    provider_signature: str
    validator_signature: str

    reasons: tuple[str, ...]

    receipt_hash: str
```

。

---

# 74. Target Contract：`ArtifactLifecycleEvent`

```python
@dataclass(frozen=True)
class ArtifactLifecycleEvent:
    event_id: str

    artifact_id: str
    generation: int
    content_digest: str

    previous_state: str
    new_state: str

    reason: str

    verification_receipt_hash: str = ""
    replay_eligibility_receipt_hash: str = ""

    created_at_ns: int = 0

    previous_event_hash: str = ""
    event_hash: str = ""
```

。

---

# 75. Target Contract：`ArtifactLocationBinding`

```python
@dataclass(frozen=True)
class ArtifactLocationBinding:
    content_digest: str

    materialization_id: str

    root_kind: str
    root_id: str

    relpath: str

    readonly: bool

    created_at_ns: int
```

。

---

# 76. 为什么 Target 不一定需要“大型 CAS”

可以先只做：

```text
workspace file
+
content digest
+
central descriptor
```

。

CAS 是逻辑模型。

当前比赛第一版完全可以：

```text
sha256 digest
    ↓
workspace materialization
```

。

后续需要跨 run reuse 时再：

```text
runtime_root/cas/sha256/...
```

。

不要现在为了架构漂亮引入远端 Object Store。

---

# 77. 推荐 Truth Ladder

Artifact Truth 最适合分成：

```text
A0 — Exists
文件存在

A1 — Integrity
size + digest 验证

A2 — Scope
task/session/step/grant 绑定

A3 — Structural Validation
schema / output shape / no symlink / path

A4 — Contract Validation
capability completion criteria

A5 — Provenance Validation
input refs / evidence lineage

A6 — Independent Recomputation
Runtime independently recalculates expected output

A7 — Replay Eligibility
未来 reuse contract 独立通过

A8 — Cross-run Attestation
跨 trust boundary 的 signed provenance
```

当前 StateBus 大致：

```text
A0 ✓
A1 强
A2 较强
A3 强
A4 中强
A5 中强
A6 视 validator 而定
A7 被 VERIFIED 自动带出，语义过强
A8 不需要 / 未实现
```

。

---

# 78. 当前几个 Producer 的 Truth Level

## Evidence Projection

大致：

```text
A1 ✓
A2 ✓
A3 ✓
A4 deterministic request contract
A5 row-lineage 部分
A6 source recomputation ✗
```

所以：

```text
RUNTIME_DERIVED
```

更准确。

---

# 79. Transform DSL

通常：

```text
A1 ✓
A2 ✓
A3 ✓
A4 ✓
A5 ✓
A6 ✓
```

因为：

```text
recompute_transform_program()
```

有独立路径。

是当前最适合：

```text
ARTIFACT_RESTORE
```

候选的一类。

---

# 80. CodeAct

如果使用强业务 validator：

```text
A1-A6
```

可以比较强。

如果：

```text
generic_analysis
```

则：

```text
A6 = NOT_EVALUATED
```

所以不要统一 Replay 权限。

---

# 81. ClaimSet

大致：

```text
A1 ✓
A2 ✓
A3 ✓
A4 claim structural validation
A5 部分
A6 semantic entailment ✗
```

。

因此 ClaimSet 的：

```text
VERIFIED
```

应该理解为：

```text
claim structure/provenance checks passed
```

而不是：

```text
claim semantic truth independently proven
```

。

---

# 82. P1 — Replay Loader 应统一走 Artifact Resolver

现在有两套读取安全强度：

```text
Adaptive current artifact reader
    强

History replay path reader
    较弱
```

建议最终只有：

```python
ArtifactResolver.resolve_verified_content(
    descriptor,
    location,
    current_lifecycle,
)
```

统一负责：

```text
location root
path containment
no symlink
size
digest
current lifecycle state
verification receipt
```

。

---

# 83. P1 — Artifact Registry 应成为 Current Truth，Memory 不应复制状态

未来：

```text
MemoryRef.metadata["replay_ready"]
```

这种复制字段应该尽量减少。

Memory 只保存：

```text
artifact_id
generation
content_digest
replay_receipt_id
```

。

使用时：

```text
查询 ReplayEligibilityStore
```

。

否则：

```text
Artifact invalidated
Memory metadata still replay_ready=true
```

就会出现 stale truth。

---

# 84. `replay_ready` 建议逐步从 Artifact Ref 移出

更合理：

```text
ExecutionArtifactRef
    不带 replay_ready

ReplayEligibilityReceipt
    独立表达
```

。

过渡期可以：

```text
replay_ready
```

保留兼容，

但把它变成：

```text
derived/cached field
```

而不是 authority source。

---

# 85. P1 — Adaptive Memory Commit 的 Late Gate 是值得保留的

虽然 Artifact promotion 本身分散，

Adaptive `_commit_verified_memory()` 做了几件很好的事情：

```text
runtime 必须 completed

Artifact 必须 VERIFIED

重新读取真实 artifact bytes
并验证 blob hash

QualityReport 必须 verified

QualityReport.output_artifact_hash
==
Artifact.blob_hash

QualityReport.report_hash
==
Artifact.metadata.quality_report_hash

Execution recipe 必须存在

input lineage 必须存在
```

。

这个 gate 很有价值。

---

# 86. 但它应该改名理解

它现在更像：

# **Memory Admission Gate**

而不是：

```text
Artifact Verification Gate
```

。

Artifact 在到这里之前已经被下游消费过。

所以这条链应该保留，

但职责明确为：

```text
“是否值得进入 Long-Term Memory”
```

。

---

# 87. 和 Round 03 CodeAct Recipe Identity 的连接

Adaptive Memory Commit 虽然要求：

```text
execution recipe exists
```

但当前还没有强制：

```text
recipe.source_hash
==
CodeExecutionRecord.final_source_hash
```

。

Round 03 已经发现：

```text
repair 后最终 verified source B
但 Dispatcher recipe 可能仍保存初始 source A
```

。

因此：

```text
Artifact Truth
```

虽然可能正确，

但：

```text
Recipe Truth
```

仍可能不正确。

这再次证明：

```text
Artifact Verification
≠
Recipe Replay Eligibility
```

必须拆开。

---

# 88. 推荐未来四个独立 Gate

```text
Gate 1
Artifact Verification Gate

Gate 2
Replay Eligibility Gate

Gate 3
Memory Admission Gate

Gate 4
Answer Adoption / Presentation Gate
```

。

绝不能再：

```text
一个 CommitGate
把四件事同时决定
```

。

---

# 89. 推荐实验 / Negative Audit

当前先不实现，但后续应该补这些实验。

---

# 90. Artifact Integrity Negative

```text
verified ref
+
file bytes modified
→ reject
```

已有部分覆盖。

继续补：

```text
size mismatch
symlink
path escape
manifest output mismatch
```

。

---

# 91. Lifecycle Negative

```text
Artifact VERIFIED
    ↓
INVALIDATED
    ↓
旧 Ref holder 尝试消费
```

必须：

```text
reject
```

。

这是当前 central revocation 缺口。

---

# 92. Replay State Mismatch

构造：

```text
RefRegistry:
INVALIDATED

Settlement:
replay_ready=True

Memory:
replay_ready=True
```

Expected：

```text
0 replay candidates
```

。

---

# 93. Settlement Tamper

修改：

```text
settlement.replay_ready
false → true
```

但：

```text
没有 matching ReplayEligibilityReceipt
```

Expected：

```text
reject
```

。

---

# 94. Artifact Manifest Semantic Mismatch

构造一个 Adaptive DSL Artifact：

```text
manifest_hash = program hash
```

尝试走 Legacy ArtifactOutputManifest loader。

目标不是让它成功，

而是：

```text
明确证明当前 ABI 不兼容
```

。

然后修正 contract。

---

# 95. DSL Quality Binding Test

```text
first transformed output hash = A

run_verified final artifact hash = B

quality report binds A
```

即使通过 monkeypatch / nondeterministic test 强制造差异，

必须：

```text
Artifact promotion rejected
```

。

---

# 96. Adoption Orthogonality Test

```text
quality pass
validators pass
answer_adopted=False
```

Expected：

```text
Artifact VERIFIED
Answer NOT_ADOPTED
Memory policy independently decides
```

而不是：

```text
Artifact INVALIDATED
quality_floor_failed
```

。

---

# 97. Empty Validator Set Test

```text
validator_reports=()
input_validator_reports=()
```

必须根据 capability policy：

```text
REJECT
```

除非 capability 明确：

```text
requires_no_validator=True
```

。

不能依赖 `all(())`。

---

# 98. Duplicate Artifact ID Test

```text
Artifact ID X
digest A
ACTIVE

再次 register:
Artifact ID X
digest B
```

Expected：

```text
identity_collision
```

或：

```text
new generation
```

。

不能 silent overwrite。

---

# 99. Crash Atomicity Tests

注入 crash：

```text
after temp output

after digest

after verification receipt

after CAS insert

before registry ACTIVE

after registry ACTIVE
```

必须保证：

```text
没有 ACTIVE Ref
指向 incomplete / unverified output
```

。

---

# 100. Replay Determinism Test

对：

```text
DSL deterministic output
```

允许：

```text
ARTIFACT_RESTORE
```

。

对：

```text
generic LLM output
```

即使输入一样：

```text
不能自动 ARTIFACT_RESTORE
```

除非 contract 固定：

```text
source/model/seed/provider/runtime
```

且 policy 明确允许。

---

# 101. 建议未来测试清单

```text
test_verified_state_requires_verification_receipt

test_artifact_valid_but_not_adopted_remains_verified

test_commit_gate_does_not_report_quality_failure_when_only_adoption_false

test_empty_validator_set_does_not_vacuously_verify

test_invalidated_artifact_cannot_be_consumed_with_stale_ref

test_artifact_lifecycle_rejects_invalid_transition

test_artifact_id_collision_rejected

test_replay_loader_requires_current_verified_state

test_replay_loader_rejects_registry_settlement_state_mismatch

test_history_output_path_escape_rejected

test_history_output_symlink_rejected

test_history_output_size_mismatch_rejected

test_adaptive_artifact_manifest_semantics_are_typed

test_dsl_quality_report_hash_matches_final_artifact_hash

test_codeact_quality_report_hash_matches_final_artifact_hash

test_projection_verification_strength_is_runtime_derived

test_generic_validator_does_not_claim_independent_recomputation

test_replay_eligibility_separate_from_artifact_verification

test_artifact_restore_requires_deterministic_class

test_memory_commit_failure_does_not_invalidate_verified_artifact

test_artifact_invalidation_revokes_memory_replay

test_artifact_lifecycle_ledger_is_append_only

test_atomic_artifact_promotion_crash_before_registry_commit
```

。

---

# 102. 推荐迁移顺序

本轮仍然只审计。

如果未来开始实现，建议严格分 Slice。

---

# ART-R0 — Semantics / Truth Naming

只统一：

```text
VERIFIED
ReplayReady
AnswerAdopted
MemoryCommitted
```

四者语义。

不改大行为。

---

# ART-R1 — Verification Strength / Receipt

增加：

```text
ArtifactVerificationReceipt
VerificationStrength
```

并把：

```text
CapabilityQualityReport
```

正式绑定到 Artifact digest。

---

# ART-R2 — Replay Eligibility Separation

停止：

```text
mark_verified()
自动 replay_ready=True
```

。

新增独立：

```text
ReplayEligibilityPolicy
```

。

---

# ART-R3 — Content / Derivation Split

拆：

```text
ArtifactContentDescriptor
ArtifactDerivationReceipt
```

修正：

```text
manifest_hash overload
```

。

---

# ART-R4 — Central Lifecycle / Revocation

统一：

```text
current lifecycle state
```

和：

```text
append-only lifecycle event
```

。

Downstream consume 必须查 current authority。

---

# ART-R5 — Unified Artifact Resolver

Current / History / Memory restore

统一：

```text
path containment
symlink
size
digest
current state
verification receipt
```

。

---

# ART-R6 — Atomic Persistence / Optional CAS

做到：

```text
temp
fsync
atomic rename
registry commit last
```

。

CAS 只在跨 run reuse 真正需要时加入。

---

# 103. 不建议现在做

```text
❌ 上 OCI Registry

❌ 实现 SLSA Level

❌ 引入 Sigstore 公钥签名

❌ 搭远程 CAS Cluster

❌ 用区块链记录 Artifact

❌ 给每个 verification strength 新增一个 RefStatus

❌ 把所有 Artifact 都强制做 independent recomputation

❌ 用 Benchmark Gold 作为 Runtime Artifact Validator
```

。

---

# 104. 对比赛最重要的 Artifact Story

修正后最强的叙事不是：

```text
“我们给文件算了 SHA256”
```

而是：

> **StateBus 将执行结果作为一等 Artifact 对象管理：产物内容身份与生成过程分离，Runtime 将 CapabilityGrant、输入 Ref、程序/代码、输出合同和 validator receipt 绑定到产物 digest；只有通过当前任务验证的 Artifact 才能进入下游。Replay 资格与 Artifact 正确性独立判断，历史内容在恢复时重新验证 size/digest 和当前生命周期状态，Memory 只引用已经授权的 Artifact/Recipe，而不会反向决定 Artifact 是否真实。**

这比：

```text
hash + cache
```

强很多。

---

# 105. 当前可以准确写进材料的 Claim

可以说：

```text
Execution Artifact carries blob hash and byte size.

Adaptive downstream rehydrates artifact bytes from disk,
checks root containment, rejects symlink,
checks exact size and digest,
and compares them with the cached typed rows.

CodeAct binds its final output digest to CapabilityQualityReport.

Adaptive Memory admission re-reads the terminal executor artifact
and checks the quality report against the exact artifact digest.

History replay re-reads persisted output bytes
and rejects digest mismatch.
```

。

---

# 106. 当前不能过度 Claim

不要说：

```text
All VERIFIED artifacts have identical verification strength.

Every VERIFIED artifact is safe for replay.

Artifact verification is controlled by one central CommitGate.

All Adaptive artifacts have a canonical ArtifactOutputManifest.

manifest_hash always points to an Artifact manifest.

Artifact invalidation is globally propagated to all stale refs.

History replay verifies the same path/security conditions
as current-run artifact consumption.

Answer adoption is independent from artifact validity.
```

这些当前都不成立。

---

# 107. Batch 03 风险表

| Priority | 问题 | 类型 |
|---|---|---|
| **P0** | Artifact Truth Promotion 有两套 authority path | Architecture |
| **P0** | `mark_verified()` 自动 `replay_ready=True` | Replay truth |
| **P0** | `manifest_hash` 语义跨 Producer 严重漂移 | Contract ABI |
| **P0** | `answer_adopted=False` 会把有效 artifact invalidated 且错误记录 `quality_floor_failed` | Audit truth |
| **P0/P1** | Verification strength 被压扁成一个 VERIFIED | Truth semantics |
| **P0/P1** | Artifact invalidation 缺 central revocation，stale verified Ref 可继续存在 | Lifecycle |
| **P1** | Empty validator tuples vacuous pass | Fail-open contract |
| **P1** | Lifecycle Manager 是 producer-local ephemeral object | Authority |
| **P1** | Lifecycle transition 没有合法状态机约束 | Lifecycle |
| **P1** | Settlement / invalidation 非 append-only | Audit |
| **P1** | Registry status / settlement replay_ready 无强一致性检查 | Replay |
| **P1** | Invalidation 没统一传播到 Memory/Replay | Replay |
| **P1** | History replay path confinement/symlink/size 校验弱于 current artifact reader | Security/Integrity |
| **P1** | Artifact writes 缺统一 crash-atomic promotion | Durability |
| **P1** | RuntimeCommitGate promotion + Memory + settlement 非事务 | Consistency |
| **P1** | Duplicate artifact ID silent overwrite | Identity |
| **P1** | DSL QualityReport 未在 `run_verified()` 显式绑定最终 materialized output hash | Verification |
| **P1** | Adaptive artifacts 普遍没有统一 persisted manifest/settlement bundle | Cross-run ABI |
| **P1** | `root_id` 同时承担 logical/physical root 语义 | Contract |
| **P2** | Exact Replay 缺显式 determinism class | Replay policy |
| **P2** | Settlement 本身不是 tamper-evident receipt | Trust boundary |

---

# 108. Batch 03 与前两批的关系

Batch 01：

```text
Task / Plan Authority
回答：
谁有权做什么？
```

Batch 02：

```text
Evidence / Provenance
回答：
它依据什么事实？
```

Batch 03：

```text
Artifact Truth
回答：
执行结果什么时候可以被系统当成真？
```

三条链联合：

```text
Task Contract
    ↓
Approved Plan
    ↓
Evidence Authority
    ↓
CapabilityGrant
    ↓
Provider Execution
    ↓
Artifact Verification
    ↓
Verified Artifact
```

这其实已经形成 StateBus 最核心的一条：

# **Runtime Truth Pipeline**

。

---

# 109. Batch 03 与 Memory 的关系

Memory 不应该：

```text
决定 Artifact VERIFIED
```

。

正确：

```text
Artifact VERIFIED
    ↓
Memory Admission
```

。

Memory 保存的是：

```text
历史经验
```

而不是：

```text
真值 authority
```

。

---

# 110. Batch 03 与 CodeAct 的关系

CodeAct 只负责：

```text
生成 + sandbox + output candidate
```

。

Artifact Plane 负责：

```text
这个 output 是否成为 verified runtime object
```

。

未来 `VerifiedExecutionRecipe` 又由：

```text
ReplayEligibilityPolicy
```

决定是否可重用。

---

# 111. Batch 03 与 Inference Reuse 的关系

Prefix/KV 只是在复用：

```text
physical Transformer compute
```

。

它绝不能绕过：

```text
Artifact Verification
```

。

即使：

```text
KV hit
APC hit
```

最终：

```text
Artifact output
```

仍然走同样的 truth promotion。

---

# 112. 推荐下一批

完成 Artifact Truth 审计以后，下一批有两条都合理：

## 方向 A — Protocol / Capability / Handshake

把：

```text
CapabilityDescriptor
Registry
Handshake
Schema Version
CapabilityGrant
Provider Fallback
```

打穿。

这是控制面下一层。

## 方向 B — Inference Reuse / APC / KV

如果希望继续贴近非文本创新主线：

```text
Prefix
APC
EngineLocalKV
Explicit KV
```

。

从全系统审计顺序看，我更建议先：

# **Protocol / Capability / Handshake**

因为 Artifact / Memory / State / CodeAct 全部依赖：

```text
Capability Contract
```

。

把它审完后再审 KV，整个 authority chain 会更完整。

---

# 113. External Design References

本轮只借设计原则，不建议直接引入这些系统。

## OCI Image Spec — Content Descriptor

参考：

```text
https://github.com/opencontainers/image-spec/blob/main/descriptor.md
https://specs.opencontainers.org/image-spec/descriptor/
```

借鉴：

```text
media type
digest
size
content verification before use
```

。

---

## Bazel Remote Cache

参考：

```text
https://bazel.build/remote/caching
```

借鉴：

```text
Action Cache
    action identity → result metadata

CAS
    content digest → bytes
```

。

---

## Nix Content Addressing / Derivation

参考：

```text
https://releases.nixos.org/nix/
```

借鉴：

```text
content identity
≠
derivation identity
```

。

---

## SLSA Provenance v1.2

参考：

```text
https://slsa.dev/spec/v1.2/
https://slsa.dev/spec/v1.2/provenance
```

借鉴：

```text
subject
build definition
resolved dependencies
builder
run details
```

。

不要为了比赛做：

```text
SLSA compliance
```

。

---

# 114. Batch 03 冻结结论

> **StateBus 当前 Artifact 子系统已经有可靠的内容 hash 验证、较强的当前运行读取校验、CapabilityQualityReport 和历史 Replay 输出 hash 校验；真正的问题不是“Artifact 不可信”，而是 Artifact 的不同真实性维度被压缩进 `VERIFIED/replay_ready/manifest_hash` 几个过载字段，同时 Adaptive 与 Legacy 路径各自拥有一套 promotion/settlement 语义。下一阶段应把 Content、Derivation、Verification、Lifecycle、Replay Eligibility、Memory Admission、Answer Adoption 拆成正交合同，使 Artifact 成为真正统一的 Runtime Truth Object。**

