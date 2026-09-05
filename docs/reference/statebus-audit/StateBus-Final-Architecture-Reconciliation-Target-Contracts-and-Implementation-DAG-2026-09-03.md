# StateBus Final Architecture Reconciliation
## Batch 01–09 Target Contracts 最终统一架构、实现依赖 DAG 与项目收口方案

> **项目**：StateBus / `qcrs/os`
>
> **性质**：Final Architecture Reconciliation（非 Batch）
>
> **日期**：2026-09-03
>
> **当前源码基线**：`qcrs/os:master`
>
> **审计时 master SHA**：`8bfc6464ec236c0e121911095fc283129b0e7696`
>
> **输入依据**：
>
> - Batch 01 — Task Admission / Plan Authority
> - Batch 02 — Evidence / Provenance / Claim
> - Batch 03 — Artifact / Verification / Commit / Replay
> - Batch 04 — Protocol / Capability / Handshake
> - Batch 05 — Logical Capability / Provider Binding
> - Batch 06 — Semantic State / APC / Explicit KV / Inference Reuse
> - Batch 07 — Scheduler / Reliability / Deployment
> - Batch 08-R — Benchmark Fairness / Metric Truth / os1 Forensics
> - Batch 09 — Security / Privacy Boundary
> - 赛题原始要求：低开销通信、非文本状态传递、共享记忆、纯文本对比、openEuler、连续任务与性能验证
>
> **从本文开始冻结一个原则**：
>
> # 不再继续做大规模 Architecture Audit。
>
> 后续只允许：
>
> ```text
> 1. 按本文 DAG 做最小实现 Slice；
> 2. 发现源码事实与本文 Target 冲突时做局部 Design Reconciliation；
> 3. 根据真实实验结果调整 Policy Threshold / Benchmark；
> 4. 不因为新论文、新框架或新 feature 再重画整个系统。
> ```

---

# 0. Final Decision

过去 01–09 的审计看起来有很多模块：

```text
Task
Plan
Routing
Protocol
State
Memory
Artifact
CodeAct
APC
KV
Scheduler
Security
Benchmark
```

如果继续按模块增加功能，StateBus 会越来越像：

```text
“一个什么都有一点的 Agent Framework”
```

。

这不是最终应该保留的项目形态。

Batch 01–09 实际上已经共同收敛出了一个更简单、更系统的核心：

# **StateBus 是一个 Controller-authorized、typed-state-aware、reuse-aware 的 Multi-Agent Runtime。**

它与普通：

```text
LLM → JSON → Tool → LLM
```

工作流的根本区别不是“多几个功能”，而是每一次 Agent 协作都被分解为：

```text
Proposal
    ↓
Authority
    ↓
Data / State
    ↓
Physical Execution
    ↓
Verification
    ↓
Reusable Truth
```

。

最终主链：

```text
Public Task / Input Assets
        ↓
Task Identity + Authority Envelope
        ↓
Planner Proposal
        ↓
PlanPolicy
        ↓
Approved Logical Workflow
        ↓
READY / Admission / Scheduling
        ↓
Provider Eligibility + Runtime Binding
        ↓
Attempt-scoped CapabilityGrant
        ↓
Typed Protocol / State / Memory / Inference Reuse
        ↓
Physical Provider Execution
        ↓
Candidate Artifact
        ↓
Verification / Lifecycle
        ↓
Verified Artifact
        ├── Final Output
        └── Memory / Replay Admission
```

这就是最终架构的中心。

---

# 1. 为什么现在应该停止 Architecture Audit

继续审计当然还能找到：

```text
更多 edge case
更多 schema
更多理论安全问题
更多 scheduler policy
更多 memory taxonomy
更多 latent/KV 论文
```

。

但现在项目的主要风险已经从：

```text
“不知道架构应该是什么”
```

变成：

```text
“已经知道应该是什么，但还没有把 Target contract 落到源码主链和实验里。”
```

。

也就是说，接下来最需要优化的是：

# **Architecture → Implementation → Evidence 的闭环速度**

而不是继续提升：

```text
Architecture Analysis Depth
```

。

因此本文以后：

```text
architecture audit = CLOSED
implementation reconciliation = OPEN
benchmark evidence = OPEN
```

。

---

# 2. 最终只保留三类 Truth

Batch 09 已经给出了一个非常重要的收敛方式。

整个 StateBus 最终不应该再按十几个 feature 解释，而应该按三个 Truth Plane 解释。

---

## 2.1 Authority Truth

回答：

> **谁被允许做什么？**

Canonical objects：

```text
TaskContractIdentity

AdaptiveTaskEnvelope

PlanProposal

PlanPolicyReport

ApprovedPlanBundle

LogicalCapabilityDescriptor

ProviderEligibility

ExecutionBindingReceipt

DispatchPermit

CapabilityGrant

ProtocolInvocationBinding
```

。

---

## 2.2 Data Truth

回答：

> **一次执行到底在消费什么、产生什么、复用了什么？**

Canonical objects：

```text
InputAssetRef

SourceLocator

CanonicalEvidencePack

HydrateManifest

SemanticStateRef

DecisionStateRef

MemoryRef

ExecutionArtifactRef

InferenceInvocation

Prefix Identity

EngineLocalKVHandle
```

。

---

## 2.3 Execution Truth

回答：

> **实际发生了什么？**

Canonical objects：

```text
RunID

SessionID

AttemptID

WorkerEvent

StepAttemptRecord

ProviderResult

VerificationReceipt

ArtifactLifecycleEvent

ReplayEligibilityReceipt

MemoryConsumptionRecord

InferenceReuseReceipt

GC Receipt

Telemetry Fact
```

。

---

# 3. Final Architecture Laws

后续实现遇到任何设计冲突，都优先服从以下规则。

---

## Law 1 — Agent Proposes, Runtime Authorizes

```text
Planner / Replanner / Role
只能提出 proposal。
```

只有 Runtime 可以生成：

```text
ApprovedPlan

ExecutionBinding

CapabilityGrant

Replay Admission

Reuse Authorization
```

。

---

## Law 2 — Logical Semantics ≠ Physical Provider

```text
Planner chooses WHAT.

Runtime chooses HOW.
```

Planner 不应该知道：

```text
DSL
bounded Python
bwrap
worker PID
provider health
vLLM backend implementation
```

。

---

## Law 3 — Scheduling Changes Order, Never Authority

Scheduler 可以决定：

```text
先跑谁
什么时候跑
是否等待资源
```

不能改变：

```text
capability
input refs
output contract
risk
memory permission
```

。

---

## Law 4 — Similarity ≠ Compatibility ≠ Consumption ≠ Effect

Memory：

```text
candidate retrieved
≠
compatible
≠
actually consumed
≠
behavior changed
≠
work skipped
```

必须分别记录。

---

## Law 5 — Candidate ≠ Verified ≠ Replayable ≠ Adopted

Artifact：

```text
CANDIDATE
```

不能自动成为：

```text
VERIFIED
```

；

`VERIFIED` 也不能自动成为：

```text
REPLAY_READY
```

；

`REPLAY_READY` 也不等于：

```text
Final Answer Adopted
```

。

---

## Law 6 — Evidence Visibility ≠ Execution Authority

Retrieved document 中即使出现：

```text
“请运行 Python”
“忽略之前指令”
```

也只能影响：

```text
model reasoning surface
```

不能扩大：

```text
Capability authority。
```

---

## Law 7 — Semantic Selection ≠ State Carrier

必须区分：

```text
S0 Full Evidence Text

S1 Selected Evidence Text

S2 Same Selected Evidence via StateRef
```

。

S0→S1 证明：

```text
Selection Gain
```

。

S1→S2 证明：

```text
Carrier Gain
```

。

---

## Law 8 — Semantic State ≠ Compute Reuse

最终只保留：

```text
Semantic State Plane
    Selection
    Latent Handoff [future]
    Decision State

Compute Reuse Plane
    APC
    Engine-local Continuation
```

。

APC/KV 不是 Agent semantic state。

---

## Law 9 — Reuse Never Bypasses Truth Promotion

即使：

```text
Memory hit
APC hit
KV continuation hit
```

最终 provider output 仍然必须进入：

```text
Artifact / Verification / Lifecycle
```

正确链。

---

## Law 10 — Protocol Result Must Bind Before Business Consumption

Worker 返回：

```text
SuccessResult
```

不能因为：

```text
protobuf decode 成功
```

就进入 Artifact。

必须先验证：

```text
protocol version
invocation
grant
attempt
output contract
ref kinds
```

。

---

## Law 11 — Gold Is Evaluator Authority, Never Runtime Input

Benchmark：

```text
expected answer
expected metric effect
gold facts
```

只能进入：

```text
Evaluator
```

不能进入：

```text
Planner
Retriever
Executor
Summarizer
Memory
Routing
Runtime Policy
```

。

---

## Law 12 — Signed Regression Must Survive

所有性能 metric：

```text
positive
negative
```

都必须真实保留。

禁止：

```text
max(delta, 0)
```

。

---

# 4. Batch 01–09 最终 Reconciliation

下面不是重新复述每个 Batch，而是明确：

```text
它最终为整个系统贡献哪一个 Target Contract。
```

---

## Batch 01 — Task / Plan Authority

最终保留：

```text
TaskContractIdentity

Safe Runtime IDs

SchemaRepair ≠ SemanticReplan

PlanNormalizationReceipt

ApprovedPlanBundle

ReplanProposal
```

核心边界：

```text
Task
→ Proposal
→ Policy
→ Approved Logical Workflow
```

。

---

## Batch 02 — Evidence / Provenance / Claim

最终保留：

```text
InputAssetRef

Stable Source Identity

SourceLocator

CanonicalEvidencePack Validator

Source-backed Hydration

Field / Row Lineage

EvidenceProjectionReceipt

ClaimSupportBinding
```

核心边界：

```text
Evidence selection
≠
source truth

Runtime traceability
≠
semantic entailment proof
```

。

---

## Batch 03 — Artifact Truth

最终保留：

```text
ArtifactContentDescriptor

ArtifactDerivationReceipt

ArtifactVerificationReceipt

ArtifactLifecycleEvent

ReplayEligibilityReceipt

ArtifactLocationBinding
```

核心边界：

```text
Content
Derivation
Verification
Lifecycle
Replay
Answer Adoption
```

必须正交。

---

## Batch 04 — Protocol / Worker Boundary

最终保留：

```text
single-source protocol schema

protocol version enforcement

ProtocolInvocationBinding

GrantLedger

grant-bound ACK / Result

real WorkerEvent lifecycle

ControlResponseBinder

frame size limit
```

核心边界：

```text
Runtime Authority
必须延伸到 physical Worker boundary。
```

---

## Batch 05 — Logical Capability / Provider Binding

最终保留：

```text
LogicalCapabilityDescriptor

ExecutionProviderDescriptor

LogicalCapabilityRegistry

ExecutionProviderRegistry

ProviderRuntimeFacts

ProviderEligibilityProjection

ExecutionBindingPolicy

ExecutionBindingReceipt
```

核心：

```text
Planner chooses WHAT

Runtime chooses HOW
```

。

---

## Batch 06 — Semantic State / Inference Reuse

最终保留：

```text
Semantic State Plane

StatePlacementPolicy

InferenceInvocation

InferenceBackendCapabilities

ReuseAuthorization

ReuseScope / ReuseNamespace

InferenceReusePolicy

InferenceReuseDecision

APC as default compute reuse

Explicit KV as experimental engine-local continuation
```

冻结：

```text
Latent Hidden = future / optional

APC = P0 production-style mechanism

Explicit KV =
experimental
single worker
single sequence
TP1 / PP1
APC off
one-shot

Semantic KV Relay / LMCache / CacheBlend
不进入本项目
```

。

---

## Batch 07 — Runtime / Scheduler / Reliability

最终保留：

```text
RuntimeCoordinator

DependencyResolver

ReadyStepCandidate

Provider Eligibility Snapshot

AdmissionController

ReadyStepScheduler

DispatchPermit

Attempt-aware Supervisor

WorkerEvent

Persistent Trusted WorkerBroker

Retry / Rebind / Replan split

GC

RuntimeInvariantCheck
```

核心：

```text
DAG execution
→
real Runtime execution plane。
```

---

## Batch 08-R — Benchmark Truth

最终保留：

```text
NL-MAS

TextStruct

StateBusTyped

S0 / S1 / S2 semantic factorial

same-target cold/warm Memory

AB/BA latency

MetricSemanticsRegistry

Gold Isolation

Headline Gate
```

核心：

```text
公平实验必须先定义 treatment，
然后才能谈收益。
```

---

## Batch 09 — Security Boundary

最终保留：

```text
Controller = Authority Root

LLM = Untrusted Proposal

LLM CodeAct = mandatory bwrap

safe path

frame bound

trust scope

audit by reference
```

不做：

```text
multi-tenant zero trust
OAuth / KMS / PKI / mTLS / TEE
```

。

---

# 5. 最终一张架构图

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PUBLIC / BENCHMARK INPUT                            │
│                                                                              │
│   User Request        Input Assets / Corpus        Public Tool Surface        │
└──────────┬────────────────────┬──────────────────────────┬────────────────────┘
           │                    │                          │
           ▼                    ▼                          │
┌────────────────────┐  ┌──────────────────────┐           │
│ Task Identity      │  │ Asset / Source       │           │
│ Run / Session      │  │ Registry             │           │
└──────────┬─────────┘  └──────────┬───────────┘           │
           │                       │                       │
           ▼                       │                       │
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AUTHORITY / CONTROL PLANE                            │
│                                                                              │
│  TaskContractIdentity                                                       │
│          ↓                                                                   │
│  AdaptiveTaskEnvelope                                                       │
│          ↓                                                                   │
│  Planner → PlanProposal                                                     │
│          ↓                                                                   │
│  PlanPolicy → ApprovedPlanBundle                                             │
│          ↓                                                                   │
│  Logical Workflow DAG                                                       │
│          ↓                                                                   │
│  DependencyResolver → READY SET                                              │
│          ↓                                                                   │
│  ProviderEligibilityProjection ← ProviderRegistry / RuntimeFacts             │
│          ↓                                                                   │
│  AdmissionFilter                                                            │
│          ↓                                                                   │
│  ReadyStepScheduler ← wait age / critical path / reuse opportunity hint      │
│          ↓                                                                   │
│  DispatchPermit                                                             │
│          ↓                                                                   │
│  ExecutionBindingPolicy → ExecutionBindingReceipt                           │
│          ↓                                                                   │
│  CapabilityGrant                                                            │
│          ↓                                                                   │
│  ProtocolInvocationBinding                                                  │
└──────────┬───────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         DATA / STATE / REUSE PLANE                           │
│                                                                              │
│  Retrieval                                                                  │
│      ↓                                                                       │
│  CanonicalEvidencePack ──→ Hydration / Projection ──→ EvidenceRef            │
│      │                                                                       │
│      ├── Semantic Selection                                                  │
│      │       ↓                                                               │
│      │   StatePlacementPolicy                                                │
│      │       ↓                                                               │
│      │   Inline / SHM / memfd / mmap StateRef                                │
│      │                                                                       │
│      └── MemoryQuery → Candidate → Compatibility → Assist / Replay Decision   │
│                                                                              │
│  Model Invocation                                                           │
│      ↓                                                                       │
│  InferenceInvocation                                                        │
│      ↓                                                                       │
│  ReuseAuthorization / ReuseScope                                             │
│      ↓                                                                       │
│  InferenceReusePolicy                                                        │
│      ├── RECOMPUTE                                                           │
│      ├── APC                                                                 │
│      └── ENGINE_LOCAL_CONTINUATION [experimental]                            │
└──────────┬───────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            EXECUTION PLANE                                   │
│                                                                              │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────────────┐  │
│  │ Retrieval / DSL  │ │ Persistent       │ │ LLM CodeAct                  │  │
│  │ In-process       │ │ Trusted Worker   │ │ ephemeral mandatory bwrap    │  │
│  └────────┬─────────┘ └────────┬─────────┘ └─────────────┬────────────────┘  │
│           │                    │                         │                   │
│           └────────────────────┼─────────────────────────┘                   │
│                                │                                             │
│                           vLLM / LLM Backend                                 │
│                                │                                             │
│                    ACK / HEARTBEAT / RESULT / TRAP                           │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    EXECUTION TRUTH / VERIFICATION PLANE                      │
│                                                                              │
│  ControlResponseBinder                                                       │
│          ↓                                                                   │
│  Attempt Ledger / RuntimeSupervisor                                          │
│          ↓                                                                   │
│  Candidate Artifact + Derivation Receipt                                     │
│          ↓                                                                   │
│  Capability Validator / Quality Report                                       │
│          ↓                                                                   │
│  ArtifactVerificationReceipt                                                 │
│          ↓                                                                   │
│  Lifecycle Commit / Invalidation                                             │
│          ↓                                                                   │
│      ┌───────────────┬──────────────────────┐                                │
│      ▼               ▼                      ▼                                │
│  Final Output   ReplayEligibility      MemoryCommit                           │
│                                           │                                  │
│                                           └──── Future MemoryQuery            │
│                                                                              │
│  RuntimeSupervisor / GC / Telemetry / Invariant Checker wrap the whole flow  │
└──────────────────────────────────────────────────────────────────────────────┘

                             ─── TRUST BOUNDARY ───

┌──────────────────────────────────────────────────────────────────────────────┐
│                         PRIVATE EVALUATION PLANE                             │
│                                                                              │
│  Runtime Output + Runtime Evidence                                           │
│               ↓                                                              │
│  Private Gold / Quality Scorer                                               │
│               ↓                                                              │
│  Mechanism Activation + Metric Semantics + Fairness Gate                     │
│               ↓                                                              │
│  Final Benchmark Report                                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

# 6. 最终物理部署图

逻辑架构不能和物理执行混淆。

最终比赛版物理形态建议：

```text
openEuler 24.03-LTS-SP3 Host
│
├─ StateBus Runtime Container
│    │
│    ├─ RuntimeCoordinator / Planner Controller
│    ├─ Retrieval / Memory / Artifact services
│    ├─ UDS Control Plane
│    ├─ StateStore
│    │    ├─ POSIX Shared Memory
│    │    ├─ memfd
│    │    └─ mmap / sidecar
│    │
│    ├─ Persistent Trusted Worker(s)
│    │    └─ semantic / logit / lightweight typed operations
│    │
│    └─ Ephemeral bwrap process
│         └─ LLM-generated Python only
│
├─ Local vLLM
│    ├─ normal model generation
│    ├─ APC
│    └─ explicit KV experimental extension
│
├─ Runtime Storage
│    ├─ run/workspace
│    ├─ artifact sidecar
│    ├─ SQLite / FTS Memory index
│    └─ optional FAISS
│
└─ Evaluator
     └─ benchmark gold only here
```

---

# 7. 为什么最终不采用“每个 Agent 一个复杂微服务”

赛题要：

```text
>=3 agents
结构化通信
状态传递
共享记忆
```

不等于必须：

```text
Planner Service
Retriever Service
Executor Service
Summarizer Service
全部独立容器
```

。

StateBus 的系统创新点不是：

```text
微服务数量。
```

而是：

```text
Authority + Ref + State + Reuse + Runtime Proof。
```

因此：

```text
Agent Role
```

是 logical role；

```text
Provider / Worker
```

才是 physical execution object。

一个 Persistent Worker 可以安全承载多个：

```text
read-only / low-risk typed capabilities。
```

CodeAct 则保持：

```text
ephemeral isolated worker。
```

---

# 8. Final Task Identity Model

Batch 01 与 Batch 09 的 identity 最终统一。

不要再让：

```text
task_id
```

同时承担：

```text
benchmark case
logical task
filesystem path
session ID
rerun identity
```

。

最终：

```text
ExternalCaseID
    = benchmark/audit mapping only

RuntimeTaskID
    = logical task

RunID
    = one physical execution

SessionID
    = one runtime session / continuous task context

StepID
    = logical DAG node

AttemptID
    = one physical execution attempt
```

。

---

## 8.1 TaskContractIdentity

建议最终 contract：

```python
TaskContractIdentity(
    contract_kind,
    contract_hash,
    public_context_hash,
    input_asset_set_hash,
)
```

支持：

```text
controlled_canonical_v1
external_public_v1
interactive_public_v1
```

。

---

## 8.2 Path Identity

所有：

```text
RuntimeTaskID
RunID
SessionID
StepID
AttemptID
RefID
ArtifactID
```

必须通过：

```text
safe_component()
```

。

所有 relpath：

```text
safe_relative_path(root, relpath)
```

。

这是 Foundation contract，不属于额外 Security feature。

---

# 9. Plan Authority Final Model

最终 Planner path：

```text
TaskContractIdentity
        ↓
Planner Public Capability View
        ↓
PlanProposal
        ↓
Mechanical Normalization
        ↓
PlanPolicy
        ↓
ApprovedPlanBundle
```

。

---

## 9.1 Schema Repair

只允许：

```text
whitespace
enum casing
registered typed edge completion
deterministic field normalization
```

必须：

```text
before_semantic_hash
==
after_semantic_hash
```

。

输出：

```text
PlanNormalizationReceipt
```

。

---

## 9.2 Semantic Replan

如果改变：

```text
step
capability
goal
dependency
memory policy
output contract
```

必须产生：

```text
new PlanProposal
new PlanPolicyReport
new ApprovedPlan
ReplanReceipt
```

不能叫：

```text
repair。
```

---

## 9.3 ApprovedPlanBundle

Runtime 对一个计划的完整 provenance：

```text
PlanProposal
+
PlanPolicyReport
+
ApprovedPlan
```

。

这三个对象形成 hash chain。

---

# 10. Logical Capability Final Model

当前 `CapabilityDescriptor` 同时包含：

```text
semantic contract
execution kind
runtime limit
risk
fallback implementation
```

最终必须拆。

---

## 10.1 LogicalCapabilityDescriptor

描述：

```text
capability_id

semantic description

owner role

accepted input ref kinds

required input ref kinds

logical input contract

logical output contract

completion criteria contract

required semantic features

maximum logical risk class
```

Planner 只看到这个。

---

## 10.2 ExecutionProviderDescriptor

描述：

```text
provider_id

implements logical capability IDs

provider version

implementation kind

supported semantic features

runtime prerequisites

resource demand model

provider max runtime

sandbox requirement

health adapter

protocol version support
```

Planner 不看。

---

# 11. Provider Binding 与 Scheduler 的最终冲突解决

Batch 05：

```text
Runtime Binder chooses HOW。
```

Batch 07：

```text
Admission / Scheduler
需要 provider runtime facts。
```

这两者不能简单用：

```text
先 Binding
```

或：

```text
后 Binding
```

解决。

最终采用：

# **Two-stage Provider Decision**

。

---

## Stage A — ProviderEligibilityProjection

READY step 进入 Scheduler 前：

```text
Logical Step
    ↓
ProviderRegistry
RuntimeFacts
Risk
Required Features
Input Contracts
    ↓
ProviderEligibilityProjection
```

输出：

```text
eligible provider IDs

rejection reasons

resource demand range

expected service cost

locality / readiness hints
```

。

它不是最终 binding。

---

## Stage B — ExecutionBinding

Scheduler 选中 Step 并有资源预算以后：

```text
selected ReadyStep

current ProviderRuntimeFacts

reservation
```

再运行：

```text
ExecutionBindingPolicy
```

输出：

```text
ExecutionBindingReceipt
```

。

这样同时满足：

```text
Planner 不看 provider

Scheduler 不盲排

最终 provider 可以考虑最新 health/resource。
```

---

# 12. ExecutionBindingReceipt

建议：

```python
ExecutionBindingReceipt(
    binding_id,

    task_id,
    step_id,
    attempt_id,

    logical_capability_id,
    logical_capability_version,

    provider_id,
    provider_version,

    provider_runtime_fact_digest,
    eligibility_receipt_hash,

    reason_code,
    binding_policy_version,
)
```

。

任何 provider-specific execution 都必须有这个对象。

---

# 13. Retry / Rebind / Replan Final Taxonomy

只保留四种 machine action：

```text
RETRY_PROVIDER

REBIND_PROVIDER

REQUEST_REPLAN

FAIL
```

。

---

## Retry

```text
same logical step
same provider
new attempt
```

。

---

## Rebind

```text
same logical step
same semantic contract
different provider
new binding
new grant
```

ApprovedPlan：

```text
不变。
```

---

## Replan

```text
logical step / DAG / goal / contract
发生变化
```

必须：

```text
new PlanProposal
→ PlanPolicy
→ ApprovedPlan
```

。

---

# 14. Runtime Scheduling Final Model

最终 scheduling object：

```text
ReadyStepCandidate
```

不是：

```text
raw request
agent
LLM call。
```

。

---

## 14.1 ReadyStepCandidate

应包含：

```text
task
session
step

dependency completion

logical capability

eligible provider set

resource demand summary

wait age

critical path estimate

reuse opportunity hint

stable arrival order
```

。

---

# 15. 最终 Scheduler Pipeline

```text
ApprovedPlan
    ↓
DependencyResolver
    ↓
READY SET
    ↓
ProviderEligibilityProjection
    ↓
AdmissionFilter
    ↓
ReadyStepScheduler
    ↓
ScheduleDecisionReceipt
    ↓
Resource Reservation
    ↓
DispatchPermit
    ↓
ExecutionBinding
    ↓
CapabilityGrant
```

。

---

## 15.1 第一版策略

正式 Runtime 第一版先：

```text
DETERMINISTIC_FCFS

max_parallel = 1
```

保证行为不变。

然后再升级：

```text
WORKFLOW_AWARE_V1
```

。

---

## 15.2 WORKFLOW_AWARE_V1

不要 weighted soup。

使用 Lexicographic：

```text
1. Hard Eligibility

2. Starvation Override / Wait Age

3. Critical Path

4. Reuse Benefit

5. Provider / Resource Locality

6. Stable FCFS tie-break
```

。

---

# 16. 为什么 Scheduler 不能成为本项目新主角

赛题核心：

```text
低开销通信
状态传递
共享记忆
```

Scheduler 是：

```text
System Integrity / Runtime glue。
```

最终展示：

```text
能够稳定连续执行
能够处理 retry/rebind
能够利用 reuse hint
```

即可。

不要继续扩：

```text
token-level preemption
SLO optimizer
GPU prefetch scheduler
multi-node replica router
```

。

---

# 17. CapabilityGrant Final Semantics

最终：

```text
ApprovedPlan
+
ExecutionBinding
+
DispatchPermit
```

共同生成：

```text
CapabilityGrant
```

。

---

## 17.1 Grant 绑定

至少：

```text
task

session

step

attempt

logical capability

provider binding hash

input ref IDs

output contract

workspace root

runtime TTL

approved plan hash
```

。

---

## 17.2 Grant 不是网络密码

当前目标仍是：

```text
single trusted Controller domain。
```

所以：

```text
grant hash
```

是 authority binding record，

不是：

```text
cryptographic bearer token。
```

。

---

# 18. Protocol Final Model

物理 worker protocol：

```text
CapabilityGrant
    ↓
ProtocolInvocationBinding
    ↓
ExecRequest
    ↓
Worker
    ↓
ACK
RUN_START
HEARTBEAT
RESULT / TRAP
    ↓
ControlResponseBinder
```

。

---

# 19. ProtocolInvocationBinding

需要同时绑定：

```text
protocol version

schema identity

task/session/step/attempt

grant hash

binding hash

operation

input ref commitments

output contract
```

。

---

# 20. Worker ACK 的最终语义

ACK 只能表示：

```text
真实 Worker 收到了并接受 invocation。
```

不能由：

```text
Runtime 本地 supervisor
```

在发请求前 synthetic 生成。

---

# 21. Worker Result Final Admission

Result 必须经过：

```text
ControlResponseBinder
```

验证：

```text
protocol version

body/event type

task/session/step/attempt

invocation binding

grant

provider binding

output contract

output ref cardinality

output ref kinds
```

。

通过以后：

```text
只能得到 Candidate output refs。
```

不能直接 VERIFIED。

---

# 22. Persistent Worker 与 Ephemeral Worker

最终物理 provider 分两类。

---

## 22.1 Persistent Trusted Worker

适合：

```text
semantic selection

logit processing

lightweight typed transform

state materialization helper
```

目的：

```text
避免每个 bundle Popen
降低 process startup
使 IPC 优势可真实体现。
```

。

---

## 22.2 Ephemeral Isolated Worker

适合：

```text
LLM-generated Python CodeAct
```

必须：

```text
per attempt sandbox
mandatory bwrap
no network
minimal inputs
fresh output workspace
```

。

不要 persistent。

---

# 23. Attempt / Lifecycle Final Model

Supervisor canonical key：

```text
(task_id, step_id, attempt_id)
```

不能只用：

```text
step_id。
```

。

---

# 24. Worker Event

统一事件：

```text
ACK_RECEIVED

RUN_STARTED

HEARTBEAT

RESULT_SUCCESS

RESULT_ERROR

TRAP

CANCELLED
```

。

RuntimeSupervisor：

```text
apply_event()
```

推进状态。

---

# 25. Late Result Fencing

Invariant：

```text
active_attempt(step) = attempt-B

attempt-A late result
→ ignored + audit

never commit
```

。

---

# 26. Timeout

Timeout 不是：

```text
Result.timed_out
```

字段说了算。

正确：

```text
Runtime Timer
+
last real WorkerEvent
```

决定：

```text
ACK timeout
Heartbeat lease timeout
Execution timeout。
```

。

---

# 27. GC Final Model

terminal attempt：

```text
COMPLETED
FAILED
TRAPPED
CANCELLED
```

必须进入：

```text
GC_PENDING
    ↓
GC_DONE
```

释放：

```text
worker reservation

state refs

SHM / memfd

temp mmap

KV lease

attempt workspace temp

protocol lease
```

。

---

# 28. Evidence Plane Final Model

原始链：

```text
InputAssetRef
    ↓
Retrieval Candidate
    ↓
CanonicalEvidencePack
    ↓
HydrateManifest
    ↓
Projection
    ↓
Claim
```

。

---

# 29. Source Identity

所有 Source：

```text
hash
```

必须代表同一种语义。

优先：

```text
Content Hash
```

。

如果不能：

```text
明确声明 identity kind。
```

不能让：

```text
path-derived ID
```

和：

```text
content hash
```

混在同一字段里。

---

# 30. SourceLocator

结构化表格不能继续：

```text
整行只有一个 cell locator。
```

。

最终至少做到：

```text
row lineage
+
field lineage
```

其中 numeric claim 必须知道：

```text
value 来源于哪一 field。
```

。

---

# 31. CanonicalEvidencePack Validation

Publish 前验证：

```text
locator source belongs to source_doc_hashes

bucket consistency

locator structure valid

evidence item identity stable

pack hash valid
```

。

Persisted pack read-back：

```text
recompute hash
```

。

---

# 32. Hydration Final Boundary

当前很多链路是：

```text
Pack-backed hydration。
```

Target：

```text
Source-backed hydration
```

优先。

即：

```text
locator
→ authoritative source
→ reconstruct
```

而不是：

```text
locator
→ previously copied text
```

。

比赛 controlled dataset 如果暂时无法全部 source-backed：

必须在 Claim 中写成：

```text
Pack-backed deterministic hydration。
```

。

---

# 33. Semantic Embedding 的正确位置

```text
Authorized Evidence Surface
    ↓
Embedding
    ↓
Semantic Candidate Selection
    ↓
Candidate IDs
    ↓
Hydration
```

。

Embedding 解决：

```text
看什么。
```

不解决：

```text
事实是真是假。
```

。

---

# 34. Artifact Final Model

最重要的最终拆分：

```text
Artifact Content

Artifact Derivation

Artifact Verification

Artifact Lifecycle

Replay Eligibility

Memory Admission

Answer Adoption
```

。

---

# 35. ArtifactContentDescriptor

描述：

```text
content hash

size

media / schema

root/location binding
```

。

---

# 36. ArtifactDerivationReceipt

描述：

```text
producer step/attempt

input artifact hashes

input state refs

evidence refs

provider binding

grant

program / code source hash

output content hash
```

。

这才是：

```text
怎么产生的。
```

---

# 37. ArtifactVerificationReceipt

描述：

```text
artifact hash

validator IDs

schema pass

semantic/recompute verification

provenance pass

completion criteria

verification strength

timestamp/policy
```

。

---

# 38. Artifact Lifecycle

状态机：

```text
CANDIDATE
    ↓
VERIFIED
    ↓
INVALIDATED / REVOKED
```

。

Append-only lifecycle event，

而不是：

```text
dict overwrite。
```

。

---

# 39. Replay Eligibility

单独：

```text
ReplayEligibilityPolicy
```

产生：

```text
ReplayEligibilityReceipt。
```

它检查：

```text
artifact current lifecycle

verification

determinism

input lineage

runtime compatibility

output contract

validator identity
```

。

---

# 40. Memory Final Model

Memory 是：

```text
Historical Reuse Plane
```

不是：

```text
Truth Authority。
```

。

---

# 41. Memory Funnel

必须记录：

```text
candidate_count

compatible_count

selected_count

consumed_count

behavioral_effect_count

replay_count

skipped_step_count

skipped_llm_call_count
```

。

不要再用一个：

```text
memory_hit_rate
```

解释全部。

---

# 42. Memory Assist 与 Replay

最终明确：

```text
ASSIST
    = 给当前执行增加历史 context
      不保证降低 latency

VALIDATED_REPLAY
    = 允许复用已验证 recipe / execution result
      根据当前输入做必要验证/重算

EXACT_REPLAY
    = identity/lineage 完全一致时恢复已验证 artifact
      真正 skip generation / execution
```

。

---

# 43. Memory Fairness

同一 target：

```text
VerifiedHistorySnapshot
        ├─ Cold: consume disabled
        └─ Warm: consume enabled
```

比较：

```text
same X cold
vs
same X warm。
```

禁止：

```text
task2 和 task1 比。
```

---

# 44. State Plane Final Model

StateBus 非文本状态最终不再画成：

```text
Embedding
Logit
Hidden
APC
KV
```

五个 feature。

最终：

```text
Semantic State Plane
    ├─ Semantic Selection State
    ├─ Latent Representation State [future]
    └─ Decision State

Compute Reuse Plane
    ├─ APC
    └─ Engine-local Continuation
```

。

---

# 45. StateRef 最终统一最小字段

```text
state_id

state_kind

task/session scope

producer step

allowed consumer

storage kind

size

blob hash

schema / encoder / model compatibility

manifest / lineage
```

。

---

# 46. StatePlacementPolicy

不要所有状态固定 SHM。

输入：

```text
state kind

payload size

producer / consumer topology

lifetime

shared memory budget

security scope

durability need
```

。

输出：

```text
INLINE

SHARED_MEMORY

MEMFD

MMAP

CAS_SIDECAR
```

。

---

# 47. 为什么 Adaptive Placement 是机制优势的一部分

小 payload：

```text
inline
```

可能更快。

大 payload：

```text
StateRef + out-of-band state
```

更合适。

最终 claim：

> StateBus 不是声称 SHM 永远比 text 快，而是通过 StatePlacementPolicy 在 payload crossover 上选择合适 carrier。

这比：

```text
“共享内存一定更快”
```

更可信。

---

# 48. InferenceInvocation Final Model

Batch 06 最重要的 seam。

```python
InferenceInvocation(
    invocation_id,

    trace_id,
    task_id,
    step_id,
    attempt_id,

    purpose,

    provider_binding_hash,

    model_id,
    model_revision,

    messages_hash,
    prompt_context_hash,

    authorized_input_ref_commitments,

    latent_ref_ids,

    response_contract_hash,

    reuse_authorization_id,
)
```

。

它是：

# **一次模型推理的 Runtime identity**

而不是新的 Prompt class。

---

# 49. Inference Mainline

```text
Role / Capability Logic
        ↓
InferenceInvocationBuilder
        ↓
InferenceInvocation
        ↓
InferenceBackendCapabilities
        ↓
ReuseAuthorization
        ↓
Prompt / Prefix Compiler
        ↓
Exact Prefix Boundary + Request Membership
        ↓
InferenceReusePolicy
        ↓
Backend Adapter
        ↓
vLLM
        ↓
InferenceResult
+
InferenceReuseReceipt
```

。

---

# 50. ReuseScope

最终：

```text
TASK

SESSION

CORPUS

TRUST_DOMAIN
```

。

Cache namespace / salt 必须来自：

```text
Runtime policy
```

不是 Agent。

---

# 51. InferenceReusePolicy

只回答：

> **这一次 inference 如何复用 Transformer compute？**

Mechanism：

```text
RECOMPUTE

APC_FULL_PROMPT

ENGINE_LOCAL_CONTINUATION
```

。

---

# 52. APC Final Position

APC 是：

```text
P0 / default compute reuse mechanism。
```

使用条件：

```text
exact long enough prefix

same model/tokenizer/template

same cache namespace

same visibility scope

backend supports APC
```

。

Scheduler 可以使用：

```text
PrefixResidencyHint
```

但最终是否 APC：

```text
InferenceReusePolicy
```

在 invocation-time 决定。

---

# 53. Explicit KV Final Position

不要包装成：

```text
通用 Agent KV relay。
```

最终名字：

# **Experimental Engine-Local Host KV Continuation**

。

Claim boundary：

```text
single worker

single seq

TP1

PP1

APC off

one-shot

same parent exact token IDs

same engine generation
```

。

---

# 54. Explicit KV 的价值

不是：

```text
“我们已经解决跨 Agent Hidden/KV 任意传递。”
```

而是：

> StateBus Runtime 可以把已经完成的 Transformer prefill compute 建模成受限、可授权、可观测的 engine-local continuation handle，并验证其 break-even。

这已经足够有 AI Infra 含量。

---

# 55. Latent Hidden Final Decision

不进入当前 P0。

Target 只预留：

```text
LatentStateRef

RepresentationPolicy
```

。

第一版 correctness：

```text
latent present
→ APC/KV reuse fail closed
```

直到未来明确：

```text
model/layer/token position/alignment/fusion contract
```

再开放组合。

---

# 56. CodeAct Final Position

CodeAct 是：

```text
Execution Provider
```

不是系统主线。

但它能够证明：

```text
StateBus authority
不仅适用于固定 builtin，
也能约束 LLM generated code。
```

。

---

# 57. LLM CodeAct Final Security Contract

固定：

```text
LLM source
↓
AST/source policy
↓
one-shot Grant
↓
mandatory bwrap readiness
↓
network denied
↓
repo not mounted
↓
exact read-only inputs
↓
only output writable
↓
schema validation
↓
capability quality validation
↓
Verified Artifact
```

。

禁止：

```text
LLM CodeAct
→ generic resource sandbox fallback

LLM CodeAct
→ none backend
```

。

---

# 58. Security Final Boundary

整个项目安全目标：

```text
Trusted:
Runtime Controller
Policy / Registry
Validator
local host trust domain

Untrusted:
LLM output
generated code
retrieved content
unverified artifact / memory

Out of Scope:
host root compromise
multi-tenant zero trust
remote internet worker authentication
GPU side-channel
```

。

---

# 59. Benchmark Final Architecture

Benchmark 不再是：

```text
跑一个 L0/L1/L2/L3
然后看哪个数字好。
```

。

最终分两类。

---

# 60. Internal Mechanism Attribution

用于证明单个机制：

```text
C0 Codec

C1 Prompt / Protocol Compiler

S0 → S1 Semantic Selection

S1 → S2 State Carrier

M Assist

M Replay

APC

Explicit KV
```

。

---

# 61. External System Comparator

赛题最终主对比：

```text
External NL-MAS
vs
Full StateBus
```

。

两边固定：

```text
same public task

same public source

same model

same tools

same logical role responsibilities

same compute ceiling

same evaluator
```

。

差异允许：

```text
communication representation

state representation

Runtime protocol

memory/replay

StateBus-specific runtime mechanisms
```

。

---

# 62. Pure Text 的最终定义

赛题意义的 pure text：

```text
Agent A
→ concise natural language handoff
→ Agent B
```

允许：

```text
数字

source ID

短 bullet

正常自然语言结构
```

不允许：

```text
StateRef

MemoryRef

machine-authoritative typed packet

candidate_key

internal hidden state
```

。

Pure Text baseline 也允许简洁，

不能故意 verbose。

---

# 63. TextStruct 的位置

内部机制实验：

```text
same semantic object
Text / JSON encoding
vs
Protobuf encoding
```

使用：

```text
TextStruct。
```

不要拿 NL-MAS 做 Codec benchmark。

---

# 64. Semantic Factorial

正式：

```text
S0
Full Evidence + Text

S1
Selected Evidence + Text

S2
Same Selected Evidence + StateRef
```

。

---

# 65. Full System Workload Bucket

至少：

```text
Short / Low-Reuse

Medium / Moderate-Reuse

Long / Repeated-State
```

分别报告。

不只报平均值。

---

# 66. MetricSemanticsRegistry

所有 metric 必须注册类型。

---

## COUNTER

例如：

```text
message_count

state_transfer_count

skipped_llm_calls
```

聚合：

```text
SUM。
```

---

## DURATION

例如：

```text
TTFT

task wall

resolve ms
```

报告：

```text
raw samples

p50

p95
```

。

---

## RATE

例如：

```text
prefix hit rate
```

必须：

```text
sum(hit numerator)
/
sum(query denominator)
```

不能：

```text
sum(per-case rate)。
```

。

---

## GAUGE

例如：

```text
memory bytes

queue depth
```

定义：

```text
latest / max。
```

---

# 67. Benchmark Headline Gate

只有：

```text
Fairness PASS

Task Quality PASS

Mechanism Activation PASS

Fresh Execution PASS

Metric Semantics PASS
```

才进入 headline。

---

# 68. Current Source Truth vs Final Target

以下状态以当前 `qcrs/os:master` 审计为基准。

| Component | Current | Final |
|---|---|---|
| `AdaptiveTaskEnvelope` | 已存在 | 保留，收敛 authority |
| `PlanProposal` / `PlanPolicy` | 已存在且较强 | repair/replan provenance 收口 |
| `CapabilityGrant` | 已存在 | 加 binding / invocation truth |
| `CapabilityDescriptor` | logical + provider 混合 | 拆 logical/provider |
| `CapabilityRegistry` | 单 registry | logical + provider 两 registry |
| Adaptive DAG | READY sibling 顺序执行 | Scheduler seam + attempt runtime |
| Worker lifecycle | 部分 synthetic | real WorkerEvent |
| UDS/Protobuf | 已存在 | binding/version/frame hardening |
| EvidencePack | 已存在 | structural/source/field truth 收口 |
| Artifact lifecycle | 已存在 basic candidate/verified | truth dimensions 正交 |
| Memory hybrid retrieval | 已存在且强 | fairness + scope + replay admission |
| Shared state store | SHM/memfd/mmap/inline 已存在 | scope + placement + path safety |
| Semantic state | 已有真实 selection/consumption | S0/S1/S2 attribution + placement |
| Logit state | 已有 | 作为 Decision State 保留 |
| Latent hidden | 未正式建立 | defer |
| APC | 有真实实验链/identity | 接 InferenceInvocation 主链 |
| Explicit KV | 有 experimental mechanism | 维持受限实验 |
| CodeAct sandbox | 当前很完整 | freeze security invariant |
| openEuler | Docker base 已满足 | deployment evidence 收口 |
| Benchmark | 很丰富但 attribution 混杂 | rebuild fairness + metric truth |

---

# 69. Final Implementation Dependency DAG

这是后续真正应该执行的路线。

```text
                              ┌─────────────────────┐
                              │ F0 Baseline Freeze  │
                              └──────────┬──────────┘
                                         │
                  ┌──────────────────────┼─────────────────────────┐
                  │                      │                         │
                  ▼                      ▼                         ▼
        ┌─────────────────┐    ┌─────────────────┐       ┌─────────────────┐
        │ ID0 Identity    │    │ BEN0 Benchmark  │       │ SEC0 Existing   │
        │ + Safe Path     │    │ Truth Fix       │       │ Invariant Tests │
        └────────┬────────┘    └─────────────────┘       └─────────────────┘
                 │
       ┌─────────┼─────────────────────────────┐
       │         │                             │
       ▼         ▼                             ▼
┌────────────┐ ┌──────────────┐        ┌────────────────┐
│ PLAN0      │ │ EVD0         │        │ STATE0         │
│ Authority  │ │ Evidence     │        │ Scope/Placement│
└─────┬──────┘ └──────┬───────┘        └───────┬────────┘
      │               │                        │
      ▼               ▼                        │
┌────────────┐ ┌──────────────┐                 │
│ CAP0       │ │ ART0         │                 │
│ Logical /  │ │ Artifact     │                 │
│ Provider   │ │ Truth        │                 │
└─────┬──────┘ └──────┬───────┘                 │
      │               │                        │
      ▼               ▼                        ▼
┌────────────┐ ┌──────────────┐        ┌────────────────┐
│ PROTO0     │ │ MEM0         │        │ INF0           │
│ Binding    │ │ Replay Gate  │        │ Invocation     │
└─────┬──────┘ └──────────────┘        └───────┬────────┘
      │                                        │
      ▼                                        ▼
┌────────────┐                         ┌────────────────┐
│ RUN0       │                         │ APC0           │
│ Attempt /  │                         │ APC Mainline   │
│ Lifecycle  │                         └───────┬────────┘
└─────┬──────┘                                 │
      │                                        ▼
      ▼                                ┌────────────────┐
┌────────────┐                         │ KVX0           │
│ WORKER0    │                         │ Explicit KV    │
│ Persistent │                         │ Experimental   │
└─────┬──────┘                         └────────────────┘
      │
      ▼
┌────────────┐
│ SCHED0     │
│ Scheduler  │
│ Seam       │
└─────┬──────┘
      │
      └───────────────────────┬───────────────────────┐
                              │                       │
                              ▼                       ▼
                    ┌────────────────┐       ┌────────────────┐
                    │ INT0 Integrated│       │ BEN1 Small     │
                    │ Mainline       │       │ Representative │
                    └───────┬────────┘       │ Rerun          │
                            │                └───────┬────────┘
                            └──────────────┬─────────┘
                                           ▼
                                  ┌────────────────┐
                                  │ BEN2 Formal    │
                                  │ Benchmark      │
                                  └───────┬────────┘
                                          ▼
                                  ┌────────────────┐
                                  │ FINAL Evidence │
                                  │ / README/PPT   │
                                  └────────────────┘
```

---

# 70. DAG Critical Path

真正关键路径不是全部节点。

最终：

```text
F0
→ ID0
→ PLAN0
→ CAP0
→ PROTO0
→ RUN0
→ WORKER0
→ SCHED0
→ INT0
→ BEN2
```

这是：

```text
Authority / Execution Critical Path。
```

另一条：

```text
ID0
→ EVD0
→ ART0
→ MEM0
→ INT0
→ BEN2
```

这是：

```text
Truth / Reuse Critical Path。
```

第三条：

```text
ID0
→ STATE0
→ INF0
→ APC0
→ INT0
→ BEN2
```

是：

```text
State / AI-Infra Critical Path。
```

Benchmark truth：

```text
BEN0
```

可以从第一天并行修，

但正式结果：

```text
BEN2
```

必须等待三个 Critical Path 合流。

---

# 71. F0 — Baseline Freeze

## 目标

不改行为。

记录：

```text
source commit

current tests

current representative benchmark

current L0/L1/L2/L3 historical outputs
```

。

---

## Gate

```text
same current test pass

same deterministic simple-task output

baseline artifact archived
```

。

---

# 72. ID0 — Identity / Safe Path Foundation

## 修改范围

主要：

```text
contracts / identity seam

runtime mainline

workspace.py

state/store.py
```

。

---

## 内容

```text
TaskContractIdentity

RunID

SessionID

safe_component

safe_relative_path
```

。

---

## Gate

```text
same task can rerun with different RunID

../ invalid ID rejected

workspace cannot escape root

state ref cannot create file outside state root
```

。

---

# 73. PLAN0 — Plan Authority Cleanup

## 内容

```text
schema repair cannot change semantic plan

normalization receipt

semantic replan returns PlanProposal

ApprovedPlanBundle hash chain

fallback provenance
```

。

---

## Gate

```text
change capability in repair
→ rejected as repair

same plan mechanical normalization
→ accepted

replan
→ new ApprovedPlan identity
```

。

---

# 74. EVD0 — Evidence Truth Minimal Closure

不要把 Batch02 全部一次实现。

比赛版 P0 只做：

```text
source identity uniform

EvidencePack structural validator

locator-source membership

structured numeric field lineage

persisted pack hash recheck

Claim supporting evidence binding
```

。

Source-backed hydration：

```text
优先，
无法一次完成的 lane 明确标注 pack-backed。
```

---

# 75. ART0 — Artifact Truth Orthogonalization

比赛版 P0：

```text
ArtifactContentDescriptor

VerificationReceipt

ReplayEligibility separate

mark_verified no longer auto replay_ready

answer adoption separate

central current lifecycle lookup
```

。

P1 再做：

```text
full append-only persistent lifecycle ledger

crash-atomic transaction framework。
```

---

# 76. CAP0 — Logical Capability / Provider Split

这是最重要的结构性 refactor 之一。

第一版不要迁移所有 capability。

只先迁移：

```text
真正已经存在 provider alternatives 的 Executor capability。
```

例如：

```text
DSL
vs
bounded Python
```

。

保留旧 capability aliases 作为 migration bridge。

---

## Gate

Planner public view：

```text
不存在：
provider_id
execution_kind
bwrap
provider health
```

。

同 logical task：

```text
forced DSL
forced Python
```

ApprovedPlan semantic hash：

```text
相同。
```

---

# 77. PROTO0 — Thin Worker Authority Binding

只实现薄层。

P0：

```text
single schema source / version enforcement

MAX_CONTROL_FRAME_BYTES

ProtocolInvocationBinding

request grant/binding hash

ACK/result echo invocation binding

ControlResponseBinder
```

。

不做：

```text
gRPC

mandatory capability discovery RTT

remote authentication。
```

---

# 78. RUN0 — Attempt-aware Runtime

P0：

```text
Supervisor key = attempt

active attempt fencing

real ACK/RUN_START from transport

timer-driven timeout

retry/rebind/replan taxonomy
```

。

---

## Gate

```text
attempt A times out

attempt B starts

late result A arrives

→ never commits。
```

---

# 79. WORKER0 — Persistent Trusted Worker

这是一个很实际的 performance Slice。

迁移：

```text
semantic selection
logit state processing
lightweight state work
```

到 persistent worker。

不迁：

```text
LLM-generated Python。
```

---

## Gate

```text
same semantics

same ref/hash

worker PID reused across tasks

process-startup count 显著下降

worker generation 可 audit
```

。

---

# 80. SCHED0 — Scheduler Seam

第一步：

```text
DependencyResolver

ReadyStepCandidate

ProviderEligibilityProjection

AdmissionFilter

ReadyStepScheduler

ScheduleDecisionReceipt
```

。

最初：

```text
FCFS
max_parallel=1
```

保持行为一致。

---

## 第二步

再实现：

```text
WORKFLOW_AWARE_V1
```

但：

```text
max_parallel
```

可以仍先保持 1。

这样先证明：

```text
policy seam
```

而不是冒险并发。

---

# 81. STATE0 — State Scope + Placement

P0：

```text
StateRef owner task/session

producer/consumer binding

StatePlacementPolicy

payload-size threshold

storage decision receipt
```

。

---

## Gate

```text
small payload → inline

large payload → SHM / mmap

unauthorized consumer → reject

same selected content S1/S2 behavior equivalent
```

。

---

# 82. MEM0 — Memory Admission / Reuse

P0：

```text
verified artifact only

compatibility before replay

same-target cold/warm harness

Assist vs Validated vs Exact metrics split

trust/corpus scope
```

。

不强迫：

```text
Assist latency positive。
```

。

---

# 83. INF0 — InferenceInvocation Seam

这是 Batch06 真正进入主线的入口。

修改：

```text
LLMClient / role path
```

不能再让不同 role：

```text
各自 wrapper feature flag。
```

统一构造：

```text
InferenceInvocation。
```

---

## Gate

至少：

```text
Planner

Executor

Summarizer
```

模型调用都能生成：

```text
invocation identity
prompt hash
input commitments
backend capability receipt
```

。

---

# 84. APC0 — APC Mainline Integration

P0：

```text
ReuseScope

cache namespace / salt

Exact Prefix Boundary

Request Membership

InferenceReuseDecision

ReuseReceipt
```

。

---

## Negative Gate

```text
different scope

different tokenizer/template

different source visibility

short/ineligible prefix
```

：

```text
fail closed → recompute。
```

---

# 85. KVX0 — Explicit KV Experimental Lane

不进入系统默认。

只做：

```text
InferenceReusePolicy 的一种 experimental mechanism。
```

---

## Experiment

```text
512

2K

4K

8K
```

parent length。

AB/BA。

输出：

```text
store ms

load ms

inherited tokens

computed prefill

TTFT

full wall
```

。

---

# 86. SEC0 — Security Invariant Freeze

利用当前成熟 CodeAct 设计，

不大改。

只测试冻结：

```text
LLM Python must use bwrap

network denied

repo denied

other task denied

one-shot grant

no generic fallback
```

。

以及：

```text
safe path

frame bound。
```

---

# 87. BEN0 — Benchmark Truth Fix

这个可以与架构实现并行。

P0：

```text
summary_hint / expected-effect leakage

signed delta

numeric tolerance

MetricSemanticsRegistry

AB/BA ordering

control/wire measurement point

Gold isolation
```

。

---

# 88. INT0 — Integrated Mainline

当以下均完成：

```text
PLAN0
CAP0
PROTO0
RUN0
STATE0
MEM0
INF0
```

才进入：

```text
Integrated Mainline。
```

目标不是加 feature，

而是验证：

```text
对象能串起来。
```

---

# 89. BEN1 — 第一轮小规模重跑

按 08-R：

```text
R0 static metric/fairness tests

R1 codec
3 payload buckets

R2 semantic S0/S1/S2
3 representative tasks

R3 memory
2 same-target pairs

R4 NL-MAS vs StateBus
5 cases AB/BA

R5 explicit KV
3 parent lengths
```

。

---

# 90. BEN2 — Formal Benchmark

BEN1 方向合理以后才扩：

```text
>= 10 continuous tasks

2 related continuous task groups

short / medium / long

pure text / StateBus

memory cold/warm

reliability soak
```

。

---

# 91. P0 / P1 / DEFER 最终分级

## P0 — 必须进入比赛 Final Version

```text
Identity / Safe Path

Repair vs Replan

Logical Capability / Provider minimal split

Protocol Invocation / Result Binding

Attempt-aware lifecycle

Persistent trusted worker

Scheduler seam

Evidence structural truth

Artifact verification / replay separation

State placement

Memory fair reuse

InferenceInvocation

APC mainline

Benchmark truth / NL-MAS fairness

CodeAct bwrap invariant

openEuler reproducibility
```

。

---

## P1 — 有余力再做

```text
WORKFLOW_AWARE scheduler scoring

true bounded parallel READY execution

full ResourceLedger

StateRef richer ACL

SO_PEERCRED

source-backed hydration for every adapter

full append-only artifact lifecycle DB

non-root Runtime container

provider health active probes
```

。

---

## Experimental — 可以展示，但不能成为核心承诺

```text
Explicit engine-local KV continuation

Logit decision gate
```

。

---

## DEFER

```text
Latent Hidden direct layer injection

Semantic KV Relay

CacheBlend

LMCache integration

Mooncake

multi-node agent runtime

distributed KV

GPU prefetch scheduler

token-level preemption
```

。

---

## OUT OF SCOPE

```text
multi-tenant zero trust

PKI / KMS

TEE

microVM fleet

Kubernetes control plane
```

。

---

# 92. 为什么 P0 仍然看起来很多

因为这里列的是：

```text
contracts / seams
```

不是每个都等于：

```text
大型 feature。
```

例如：

```text
Scheduler seam
```

第一版可以：

```text
max_parallel=1
same FCFS。
```

`Logical/Provider split` 第一版只迁：

```text
DSL/Python alternatives。
```

`Artifact truth` 第一版只拆：

```text
verification
vs
replay eligibility。
```

所以真正工作量取决于：

```text
minimal migration。
```

---

# 93. 禁止 Big-Bang Refactor

所有实现遵循：

# **Compatibility Bridge First**

。

比如：

```text
Current CapabilityDescriptor
      ↓ adapter
LogicalCapabilityDescriptor
+
ExecutionProviderDescriptor
```

旧代码在迁移期仍可读。

---

# 94. Migration Pattern

统一：

```text
Old Object
    ↓
Adapter
    ↓
New Target Contract
    ↓
New Path
```

通过 Gate 后：

```text
delete old path。
```

不要：

```text
一次把 adaptive_runtime.py
role_path.py
driver.py
全重写。
```

。

---

# 95. 推荐 Slice 规模

一个 Slice：

```text
1 个主要 contract

1 条 runtime seam

1 组 negative test

1 个 evidence artifact
```

不要一个 Slice 同时：

```text
改 Planner
改 Protocol
改 State
改 Benchmark
改 KV
```

。

---

# 96. Implementation Node Table

| Node | Depends | 主要目标 | 核心文件 |
|---|---|---|---|
| F0 | - | baseline freeze | tests / benchmark artifacts |
| ID0 | F0 | identity + path | contracts, workspace.py, state/store.py |
| PLAN0 | ID0 | repair/replan/provenance | plan_policy.py, adaptive_mainline.py |
| EVD0 | ID0 | evidence structure/lineage | refs, retrieval, evidence_projection |
| ART0 | ID0,EVD0 | verification/replay split | workspace.py, commit_gate.py |
| CAP0 | PLAN0 | logical/provider split | adaptive.py, capability_registry.py, domain_packs.py |
| PROTO0 | CAP0 | invocation/result binding | control/* |
| RUN0 | PROTO0 | attempt lifecycle | adaptive_runtime.py, supervisor.py, session.py |
| WORKER0 | RUN0 | persistent trusted worker | control/transport.py, worker broker |
| SCHED0 | CAP0,RUN0 | ready scheduler seam | adaptive_runtime.py / new scheduler seam |
| STATE0 | ID0 | scope/placement | state/store.py, refs/models.py |
| MEM0 | ART0,STATE0 | replay admission | memory/*, replay.py |
| INF0 | CAP0,ID0 | inference identity | integrations/llm.py, role_path.py |
| APC0 | INF0 | APC formal reuse | prefix*, vllm integration |
| KVX0 | INF0,APC0 | continuation experiment | engine_local_kv*, integration |
| SEC0 | ID0,PROTO0 | invariant freeze | codeact*, docker |
| BEN0 | F0 | metric/fairness truth | benchmark/* |
| INT0 | RUN0,SCHED0,STATE0,MEM0,INF0 | end-to-end | adaptive mainline |
| BEN1 | INT0,BEN0,APC0 | representative run | benchmark harness |
| BEN2 | BEN1 | formal evidence | formal suites |

---

# 97. 哪些节点最可能带来“机制性能收益”

架构修复本身未必降低 latency。

真正可能直接贡献性能的：

```text
WORKER0
persistent worker

STATE0
adaptive StatePlacementPolicy

MEM0
validated/exact replay admission

APC0
exact prefix reuse

KVX0
long-parent continuation

Semantic Selection
S0→S1
```

。

---

# 98. 哪些节点主要贡献“可信度”

```text
ID0

PLAN0

EVD0

ART0

CAP0

PROTO0

RUN0

BEN0

SEC0
```

。

它们的价值是：

```text
让评审相信性能数据到底来自什么机制。
```

这在比赛里非常重要。

---

# 99. Final Performance Story

最终不要说：

```text
StateBus 所有机制都比 Text 快。
```

。

应该说：

> **StateBus 将 Agent 协作拆成 control、semantic-state、memory-reuse 与 inference-reuse 等不同成本面，并由 Runtime 根据 payload、兼容性、可跳过 work 和 prefix identity 自适应选择机制。小任务可退化到接近普通 inline/text 路径；随着中间状态、上下文和可复用工作量增大，reference-based state、validated replay 与 compute reuse 开始跨过 break-even，从而获得明显收益。**

---

# 100. Final Adaptive Policy

最终真正值得展示的是：

# **Adaptive Mechanism Selection**

。

概念：

```python
if state_payload_small:
    inline
else:
    state_ref

if semantic_selection_not_useful:
    full_evidence
else:
    selected_evidence

if replay_not_compatible:
    recompute
elif replay_saved_work_small:
    assist_or_recompute
else:
    validated_or_exact_replay

if exact_prefix_short_or_ineligible:
    recompute
elif backend_apc_supported:
    apc

if experimental_continuation_eligible
and saved_prefill_cost > store_load_cost:
    continuation
```

。

---

# 101. 这是不是“为了让实验好看”

不是。

正确系统本来就不应该：

```text
Every Mechanism Always On。
```

真实 Infra Policy 必须考虑：

```text
overhead
break-even
resource
compatibility。
```

。

因此：

```text
Adaptive Policy
```

本身就是项目系统价值。

---

# 102. Final Competition Mapping

赛题要求 | 最终 StateBus 对应
---|---
>=3 Agent | Planner / Retriever / Executor / Summarizer
结构化通信 | UDS + typed protocol + Capability/Ref contracts
动作/参数/结果/能力 | Logical capability + request/result schema + public capability view
握手/能力发现/映射 | frozen registry + self-describing invocation + optional discovery
纯文本与结构化 A/B | External NL-MAS + TextStruct + StateBusTyped
非文本中间状态 | Semantic/Decision StateRef + SHM/memfd/mmap
共享记忆 | hybrid keyword/tag/vector MemoryStore
跨任务复用 | Assist / Validated Replay / Exact Replay
2 组关联连续任务 | same-target history snapshot chains
通信指标 | messages/text tokens/wire/state bytes
时延 | task wall + model wall + mechanism overhead + TTFT
Memory hit | candidate/compatible/consumed/replay funnel
调度 | ReadyStepScheduler / RuntimeCoordinator
10+ 连续任务 | formal continuous suite / reliability soak
CodeAct | mandatory bwrap bounded Python
openEuler | 24.03-LTS-SP3 container

---

# 103. Final README / 答辩应该怎么解释

不要按目录讲：

```text
我们有 Protobuf
我们有 SHM
我们有 FAISS
我们有 CodeAct
我们有 KV
```

。

正确顺序：

---

## 第一层：问题

传统多 Agent：

```text
每一跳：
内部状态
→ 自然语言
→ token
→ 文本解析
→ 再生成内部状态
```

并且历史 work 经常：

```text
重新做。
```

---

## 第二层：StateBus 核心

```text
Control Plane
只传高密度 typed metadata / refs

State Plane
直接交换非文本 state

Memory Plane
保存并验证可复用历史 object

Compute Reuse Plane
复用 repeated Transformer prefill
```

。

---

## 第三层：为什么不会变成“错误高速传播”

因为：

```text
PlanPolicy

Grant

Compatibility

Verification

Replay Admission
```

隔离：

```text
Model Proposal
和
Runtime Truth。
```

---

## 第四层：为什么不是 Feature Stack

所有机制最终都接到：

```text
Runtime-owned contracts。
```

并通过：

```text
Adaptive Policy
```

选择。

---

# 104. Final Project One-liner

推荐：

> **StateBus is a controller-authorized multi-agent runtime that replaces repeated natural-language handoffs with typed control and reference-based state exchange, while safely reusing verified memory and repeated inference computation under explicit runtime identity, compatibility and lifecycle contracts.**

中文：

> **StateBus 是一个由 Runtime Controller 统一授权的多智能体协作运行时，通过 typed control 与 reference-based state exchange 减少重复文本化，并在明确的身份、兼容性与生命周期约束下复用已验证的共享记忆和重复推理计算。**

---

# 105. Final AI Infra Positioning

项目不应该定位为：

```text
又一个 Agent Framework。
```

更合适：

# **Agent Runtime / AI Inference Infrastructure**

原因：

核心问题都是：

```text
IPC / serialization

state placement

memory hierarchy

resource/lifecycle

provider binding

reuse admission

prefix/KV compute reuse

benchmark causal attribution
```

。

这些是 Infra 问题。

---

# 106. Final Feature Hierarchy

## Core

```text
Typed Control

Ref-based State

Verified Shared Memory

Runtime Authority
```

。

---

## Performance

```text
Semantic Selection

Adaptive State Placement

Persistent Worker

Replay

APC

Experimental KV Continuation
```

。

---

## Integrity

```text
Artifact Verification

Attempt Lifecycle

Scheduler

CodeAct Sandbox

Telemetry

Evaluator Isolation
```

。

---

# 107. 哪些旧 Headline 暂时冻结

在 BEN2 前，不使用：

```text
“Protobuf 节省 X% LLM token”

“Structured protocol 本身减少 47% total token”

“StateRef 一定更快”

“Memory hit 90%”

“Full StateBus 一定更低 latency”

“Explicit KV 通用跨 Agent KV transfer”
```

。

---

# 108. BEN2 后可恢复什么 Claim

如果证据通过：

```text
Typed control
→ control/wire byte gain

Protocol compiler
→ model-visible collaboration token gain

Semantic selection
→ prompt context gain

StateRef
→ large-state carrier crossover

Replay
→ real skipped work

APC
→ computed prefill / TTFT gain

Explicit KV
→ long-parent continuation break-even

Full StateBus
→ quality-cost frontier
```

。

---

# 109. Final Formal Experiments

最终实验包建议只有六组。

---

## E1 — Communication

```text
same semantic object

TextStruct
vs
Protobuf
```

+

```text
inline payload
vs
Ref handoff
```

。

---

## E2 — Semantic State

```text
S0 / S1 / S2
```

。

---

## E3 — Memory

```text
same target cold/warm

Assist
Validated Replay
Exact Replay
```

。

---

## E4 — Full System

```text
External NL-MAS
vs
Full StateBus
```

short/medium/long。

---

## E5 — Inference Reuse

```text
APC exact prefix

Explicit KV parent-length sweep
```

。

---

## E6 — Reliability

```text
20–50 continuous tasks

worker restart

ack timeout

late result

GC

memory persistence

openEuler restart
```

。

---

# 110. 结果报告的最终 Cost Decomposition

不要只报：

```text
task latency。
```

最终：

```text
T_model

T_control

T_state

T_memory

T_execution

T_integrity

T_e2e
```

。

其中：

```text
T_integrity
=
validation
artifact commit
telemetry
sandbox overhead
```

。

这样即使 Full StateBus 某些短任务更慢，

也能解释：

```text
为什么。
```

---

# 111. Model Call Accounting

必须分：

```text
logical_llm_call_count

physical_model_request_count
```

。

因为：

```text
retry
replay
exact replay
cache
```

都可能让两者不同。

---

# 112. Communication Accounting

最终：

```text
control_wire_bytes

text_handoff_bytes

state_plane_bytes

artifact_bytes

memory_materialization_bytes
```

分开。

不要继续：

```text
一个 communication_bytes。
```

---

# 113. Final Non-text State Accounting

至少：

```text
state_publish_count

state_resolve_count

state_consume_count

state_bytes

storage backend

resolve_ms

consumer behavioral effect
```

。

---

# 114. Break-even 是最终最值得做的分析

对于：

```text
StateRef

Replay

Persistent Worker

APC

Explicit KV
```

都寻找：

```text
B*
```

即：

> **机制收益开始覆盖自身 overhead 的最小 workload size。**

这比：

```text
单点最好结果
```

更像真正 Infra 项目。

---

# 115. Final Development Order — 建议实际执行

如果接下来真的进入 Codex 实现，建议严格按：

```text
01 F0
02 ID0
03 PLAN0
04 BEN0
05 CAP0
06 PROTO0
07 RUN0
08 WORKER0
09 SCHED0

并行：
EVD0
→ ART0
→ MEM0

并行：
STATE0
→ INF0
→ APC0

然后：
INT0
→ BEN1
→ BEN2
```

。

KVX0：

```text
在 INF0/APC0 稳定以后插入，
不阻塞主线。
```

---

# 116. 为什么 BEN0 要很早做

因为每完成一个 Slice，

都应该立即通过：

```text
fairness/metric truth
```

观察。

否则最后再修 Benchmark：

```text
不知道前面哪些性能数字还能信。
```

。

---

# 117. 为什么 ART0 不应该拖到最后

Memory / Replay 的可信度完全依赖：

```text
Artifact Truth。
```

如果：

```text
VERIFIED
和
replay_ready
```

还混在一起，

Memory 性能结果很难讲清楚。

---

# 118. 为什么 CAP0 必须在 Scheduler 前

如果 Planner 仍然选：

```text
execute_dsl

execute_python
```

Scheduler 根本不知道：

```text
它调度的是 semantic work
还是 implementation choice。
```

Rebind 也无法成立。

所以：

```text
Logical/Provider split
→ Scheduler。
```

---

# 119. 为什么 PROTO0 必须在 real Worker Lifecycle 前

如果 Result 没有：

```text
grant/binding/attempt
```

的完整 wire binding，

真实 WorkerEvent 接进来以后：

```text
late result
wrong result
```

无法稳定 fence。

所以：

```text
Protocol binding
→ Attempt runtime。
```

---

# 120. 为什么 INF0 必须在 APC 前

没有：

```text
InferenceInvocation
```

APC 永远只是：

```text
Role-specific wrapper flag。
```

以后：

```text
Planner
Executor
Summarizer
```

还会各写一套。

所以：

```text
Inference identity
→ Reuse Policy
→ APC。
```

---

# 121. 为什么 Latent Hidden 不阻塞比赛

赛题要求：

```text
embedding / semantic vector / hidden / other intermediate representation
```

是：

```text
OR
```

。

当前：

```text
Semantic embedding / dense state
```

已经满足真实非文本跨 Agent/PID 交换，

并且能够说明：

```text
generation
transfer
resolve
consumption
behavioral effect。
```

因此没有必要为了：

```text
更“高级”
```

强行实现 layer hidden injection。

---

# 122. 为什么 Explicit KV 也不阻塞比赛

赛题不要求 KV。

它属于：

```text
AI Infra depth extension。
```

主链有：

```text
typed communication

state transfer

memory reuse
```

已经满足。

Explicit KV 成功：

```text
加分。
```

失败：

```text
不应该拖垮 Core。
```

---

# 123. Final Source Ownership Map

| Target | Owner |
|---|---|
| Task Identity | Runtime Controller |
| Plan Proposal | Planner |
| Plan Approval | PlanPolicy |
| Logical Capability | LogicalCapabilityRegistry |
| Provider Definition | ExecutionProviderRegistry |
| Provider Health | Runtime Facts |
| Step Order | Scheduler |
| Resource Permission | Admission / DispatchPermit |
| Physical Binding | ExecutionBindingPolicy |
| Execution Permission | CapabilityGrant |
| Wire Invocation | ProtocolInvocationBinding |
| Evidence Truth | Evidence/Provenance Plane |
| State Placement | StatePlacementPolicy |
| Memory Compatibility | Memory Runtime Policy |
| Inference Reuse | InferenceReusePolicy |
| Worker Lifecycle | RuntimeSupervisor |
| Artifact Truth | Artifact Verification/Lifecycle |
| Replay Eligibility | ReplayEligibilityPolicy |
| Final Quality | Evaluator |
| Gold | Evaluator only |

---

# 124. 关键 Ownership 禁止反转

禁止：

```text
Planner chooses provider

Worker chooses its own grant

Memory promotes artifact VERIFIED

Scheduler changes capability

Evidence creates execution authority

Evaluator gold enters Planner

vLLM decides StateBus reuse scope

LLM CodeAct chooses sandbox permission
```

。

---

# 125. Final Runtime Object Graph

一条真实 task 最终至少能串出：

```text
TaskContractIdentity
│
├─ RunID
├─ SessionID
│
└─ ApprovedPlanBundle
     │
     ├─ Step A
     │    ├─ ReadyStepCandidate
     │    ├─ ExecutionBindingReceipt
     │    ├─ DispatchPermit
     │    ├─ CapabilityGrant
     │    ├─ AttemptID
     │    ├─ ProtocolInvocationBinding
     │    ├─ consumed Ref IDs
     │    ├─ ProviderResult
     │    └─ ArtifactVerificationReceipt
     │
     └─ Step B ...
```

。

这条 Object Graph 本身就是：

```text
Runtime Audit Trail。
```

---

# 126. Final Data Object Graph

```text
InputAssetRef
   ↓
SourceLocator
   ↓
EvidenceItem
   ↓
CanonicalEvidencePack
   ↓
SemanticStateRef
   ↓
StateConsumptionRecord
   ↓
ExecutionArtifactRef
   ↓
ArtifactDerivationReceipt
   ↓
ArtifactVerificationReceipt
   ↓
MemoryRef
   ↓
MemoryConsumptionRecord
```

。

---

# 127. Final Inference Object Graph

```text
InferenceInvocation
    ↓
ReuseAuthorization
    ↓
ReuseNamespace
    ↓
Prefix Boundary / Membership
    ↓
InferenceReuseDecision
    ↓
vLLM Request
    ↓
InferenceResult
    ↓
InferenceReuseReceipt
```

。

Explicit KV：

```text
InferenceReuseDecision
    ↓
EngineLocalKVHandle
    ↓
KVForwardProof
```

。

---

# 128. Final Telemetry Rule

Telemetry 不应该再承担：

```text
所有 raw object persistence。
```

原则：

# **Audit by Reference, not by Content**

记录：

```text
object ID

hash

state

decision reason

size

metric

receipt hash
```

。

大 payload：

```text
在 canonical store 中。
```

---

# 129. Final Repository Evolution Strategy

最终不要创建：

```text
statebus_v2/
```

平行重写。

沿当前模块：

```text
contracts/
control/
runtime/
state/
memory/
refs/
benchmark/
```

增加 seam。

等新路径稳定：

```text
逐步删 compatibility bridge。
```

---

# 130. 建议新增模块，但不强制

如果需要，最多新增：

```text
statebus/contracts/identity.py

statebus/contracts/provider.py

statebus/runtime/execution_binding.py

statebus/runtime/scheduler.py

statebus/runtime/inference_invocation.py

statebus/runtime/path_safety.py

statebus/benchmark/metric_semantics.py
```

。

不要一次拆几十个文件。

---

# 131. Existing Source Files 与 Target

## `statebus/contracts/adaptive.py`

当前：

```text
Task
Plan
Capability
Grant
```

集中。

Target：

```text
保留 compatibility exports，
逐步把 provider/identity 新 contract 独立。
```

。

---

## `statebus/runtime/adaptive_runtime.py`

当前承担过多：

```text
dependency
grant
dispatch
supervisor
fallback
replan
telemetry
```

Target 不要求重写，

只逐步抽 seam：

```text
DependencyResolver

Scheduler

ExecutionBinding

Attempt lifecycle。
```

---

## `statebus/runtime/role_path.py`

当前也是高复杂度文件。

后续不要继续往里面：

```text
APC
KV
state
benchmark
```

塞 branch。

Inference 调用统一走：

```text
InferenceInvocation。
```

---

# 132. Final Success Definition

项目最终成功不是：

```text
所有 Target Contract 都做到论文级完整。
```

而是：

```text
Core contracts 真正进入主链

关键性能 mechanism 有单变量证据

full system 有公平 external baseline

连续任务稳定

所有 headline 能追溯到真实 mechanism。
```

。

---

# 133. Final Architecture Reconciliation Exit Gate

本文结束以后，Architecture Freeze 条件：

```text
[x] Project one-liner fixed

[x] Authority/Data/Execution Truth fixed

[x] Planner / Runtime / Provider ownership fixed

[x] Logical vs Provider split fixed

[x] Protocol / Grant / Result boundary fixed

[x] Evidence / Artifact / Memory truth boundary fixed

[x] Semantic State vs Compute Reuse split fixed

[x] APC / Explicit KV role fixed

[x] Scheduler role fixed

[x] Security trust boundary fixed

[x] Pure Text / TextStruct / StateBus comparator fixed

[x] Implementation dependency DAG fixed

[x] P0 / P1 / Defer fixed
```

。

后续任何新问题：

```text
不重新开启 Batch 10。
```

只判断：

```text
它属于哪个 frozen contract？
```

然后做：

```text
implementation fix
或
local contract amendment。
```

---

# 134. Final Recommendation

从现在开始：

# **停止讨论“StateBus 最终应该是什么”。**

它已经足够明确：

> StateBus 是一个以 Runtime Controller 为 authority root 的多 Agent Runtime；Planner 只产生 logical workflow proposal，Runtime 负责 capability authorization、provider binding、scheduling 和 attempt lifecycle；Agent 之间通过 typed control 与 reference-based state 交换数据，历史结果只有在 artifact verification 和 compatibility gate 后才能进入 memory/replay；模型推理由 Runtime-owned InferenceInvocation 统一承载，并根据 reuse scope 在 recompute、APC 与受限 engine-local continuation 之间选择；最终所有性能结论通过 pure-text NL-MAS、机制级 factorial ablation 和 typed metric semantics 进行公平验证。

接下来项目只剩两件事：

```text
1. 按 Implementation DAG 把 Target seam 落到源码；
2. 用 Batch08-R 定义的公平实验重新建立最终 evidence。
```

这应该成为 StateBus 后续所有开发的唯一主线。

---

# Appendix A — Target Contract Catalog

| Contract | Plane | Purpose |
|---|---|---|
| `TaskContractIdentity` | Authority | task semantic identity |
| `RunID` | Execution | physical run identity |
| `PlanNormalizationReceipt` | Authority | prove mechanical-only normalization |
| `ApprovedPlanBundle` | Authority | proposal-policy-plan provenance |
| `LogicalCapabilityDescriptor` | Authority | Planner-visible semantics |
| `ExecutionProviderDescriptor` | Execution | provider implementation definition |
| `ProviderEligibilityProjection` | Runtime | provider feasibility before scheduling |
| `ExecutionBindingReceipt` | Runtime | final provider selection |
| `ScheduleDecisionReceipt` | Runtime | why a READY step was selected |
| `DispatchPermit` | Runtime | resource/admission permit |
| `CapabilityGrant` | Authority | attempt execution authority |
| `ProtocolInvocationBinding` | Protocol | bind grant/binding to wire request |
| `WorkerEvent` | Execution | physical lifecycle truth |
| `InputAssetRef` | Data | public source object |
| `CanonicalEvidencePack` | Data | selected structured evidence |
| `EvidenceProjectionReceipt` | Data | deterministic field projection proof |
| `ClaimSupportBinding` | Truth | claim ↔ evidence support |
| `SemanticStateRef` | State | non-text intermediate state |
| `StatePlacementReceipt` | State | carrier/storage policy decision |
| `StateConsumptionRecord` | State | actual consumer behavior |
| `ArtifactContentDescriptor` | Truth | content identity |
| `ArtifactDerivationReceipt` | Truth | how artifact was produced |
| `ArtifactVerificationReceipt` | Truth | what was validated |
| `ArtifactLifecycleEvent` | Truth | current truth state |
| `ReplayEligibilityReceipt` | Reuse | whether artifact may replay |
| `MemoryCompatibilityDecision` | Reuse | candidate compatibility |
| `MemoryConsumptionRecord` | Reuse | actual memory use/effect |
| `InferenceInvocation` | Inference | model-call runtime identity |
| `ReuseAuthorization` | Inference | allowed reuse scope |
| `InferenceReuseDecision` | Inference | recompute/APC/KV selection |
| `InferenceReuseReceipt` | Inference | observed reuse evidence |
| `EngineLocalKVHandle` | Inference | experimental KV continuation identity |
| `KVForwardProof` | Inference | physical KV reuse proof |
| `MetricSemantics` | Benchmark | aggregation semantics |
| `ComparisonContract` | Benchmark | fairness definition |

---

# Appendix B — Core Invariants

```text
INV-01
Every ApprovedPlan refers to exactly one TaskContractIdentity.

INV-02
Every physical attempt belongs to one Run/Session/Step.

INV-03
Every provider execution has one ExecutionBindingReceipt.

INV-04
Every dispatched provider attempt has one fresh CapabilityGrant.

INV-05
Every worker result binds to the current invocation/attempt.

INV-06
Every consumed Ref is authorized for the consumer.

INV-07
Every VERIFIED Artifact has a VerificationReceipt.

INV-08
Replay requires current lifecycle + explicit ReplayEligibility.

INV-09
Memory retrieval never implies replay permission.

INV-10
Scheduler never changes logical authority.

INV-11
APC/KV never change semantic output contract.

INV-12
Gold never appears in Runtime-visible input.

INV-13
Rate metrics are derived from numerator/denominator.

INV-14
Performance regressions remain signed.

INV-15
LLM-generated Python never runs outside mandatory bwrap.
```

---

# Appendix C — Final P0 Checklist

```text
Foundation
[ ] safe IDs / paths
[ ] TaskContractIdentity / RunID
[ ] repair vs replan

Authority
[ ] logical capability / provider split
[ ] provider eligibility
[ ] binding receipt
[ ] fresh provider-bound grant

Protocol
[ ] single-source/version enforcement
[ ] frame bound
[ ] invocation binding
[ ] real ACK/result binding

Runtime
[ ] attempt-aware supervisor
[ ] late result fencing
[ ] real worker lifecycle
[ ] persistent trusted worker
[ ] scheduler seam
[ ] GC closeout

Data Truth
[ ] EvidencePack validation
[ ] numeric field lineage
[ ] VerificationReceipt
[ ] verification != replay eligibility

State / Reuse
[ ] State scope
[ ] StatePlacementPolicy
[ ] same-target memory counterfactual
[ ] InferenceInvocation
[ ] ReuseScope/cache salt
[ ] APC mainline

Benchmark
[ ] NL-MAS
[ ] TextStruct codec lane
[ ] S0/S1/S2
[ ] MetricSemanticsRegistry
[ ] AB/BA
[ ] Gold isolation
[ ] headline gate

Deployment
[ ] openEuler evidence
[ ] CodeAct bwrap invariants
[ ] continuous task soak
```

---

# Appendix D — Documents Reconciled

```text
StateBus-System-Audit-Master-Map-and-Batch01-Task-Plan-Authority-2026-09-03.md

StateBus-System-Audit-Master-Map-Batch01-Batch02-Evidence-Provenance-Audit-2026-09-03.md

StateBus-Batch03-Artifact-Lifecycle-Verification-Commit-Replay-Truthfulness-Audit-2026-09-03.md

StateBus-Batch04-Protocol-Capability-Handshake-Deep-Audit-2026-09-03.md

StateBus-Batch05-Logical-Capability-Provider-Binding-Deep-Audit-2026-09-03.md

StateBus-Batch06-Inference-Reuse-Prefix-APC-Explicit-KV-Deep-Audit-and-NonText-Rebuild-2026-09-03.md

StateBus-Batch07-ReadySet-Scheduler-Reliability-Deployment-Deep-Audit-and-Evolution-Design-2026-09-03.md

StateBus-Batch08-R-os1-Experiment-Forensics-Fair-Comparison-and-Gain-Repair-Deep-Audit-2026-09-03.md

StateBus-Batch09-Security-Privacy-Boundary-and-End-to-End-Chain-Final-Audit-2026-09-03.md

题目(1).md
```

---

# Appendix E — Current Main Source Map

当前源码基线：

```text
qcrs/os
master
8bfc6464ec236c0e121911095fc283129b0e7696
```

关键现有模块：

```text
statebus/contracts/adaptive.py
statebus/contracts/llm_codeact.py
statebus/contracts/prefix.py
statebus/contracts/engine_local_kv.py

statebus/runtime/plan_policy.py
statebus/runtime/capability_registry.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/role_path.py
statebus/runtime/supervisor.py
statebus/runtime/workspace.py
statebus/runtime/commit_gate.py
statebus/runtime/llm_codeact.py
statebus/runtime/codeact_sandbox.py
statebus/runtime/telemetry.py

statebus/control/*
statebus/state/*
statebus/memory/*
statebus/refs/*
statebus/benchmark/*

docker/Dockerfile
docker/entrypoint.sh
```

这些是后续 Implementation Reconciliation 的 Source Truth 起点。

---

# Final Freeze

```text
NO Batch 10.

NO architecture feature expansion.

NEXT:
Implementation DAG
→ representative rerun
→ formal benchmark
→ final evidence / delivery.
```
