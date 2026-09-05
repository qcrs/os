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


