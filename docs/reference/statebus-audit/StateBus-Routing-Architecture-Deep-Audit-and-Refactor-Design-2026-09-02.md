# StateBus Routing Architecture 深度审计与重构设计

> 项目：`qcrs/os`（当前主展示仓库）  
> 历史参考：`qcrs/os1`  
> 文档日期：2026-09-02  
> 文档定位：Routing Architecture / Source Audit / Refactor Design Baseline  
> 状态：设计分析稿，不代表当前代码已经实现本文提出的目标架构

---

## 0. 文档目的

这份文档专门回答 StateBus 当前“路由”问题，不讨论数据集与 KV/latent communication 的完整设计。

目标不是增加一个第五个 Router Agent，而是回答以下工程问题：

1. 当前 `os/master` 的真实 adaptive 主链到底如何运行？
2. 现在已经有哪些 routing 行为，只是没有被统一抽象？
3. `PlanSelector` 应该精确插在哪个函数边界？
4. `Execution Binding / Rebinding` 应该插在哪个函数边界？
5. 当前 `CapabilityDescriptor -> PlanStepProposal -> ApprovedPlan -> CapabilityGrant -> Dispatcher` 为什么形成过深绑定？
6. 哪些 contract 需要重构？
7. 哪些 Runtime 安全/授权边界绝不能因为“智能路由”而破坏？
8. Prefix / KV / Logit / Embedding / SHM 是否属于同一种 Router？
9. MasRouter、RouteLLM、DyLAN、AgentPrune、AgentDropout、PACT 等工作分别可以借什么？
10. 第一版 Router 应该做到什么程度，哪些 advanced learned routing 暂时不应该做？

本文最终冻结如下边界：

```text
PlanSelector
    决定：是否需要 Planner，以及采用什么 logical workflow shape

PlanPolicy
    决定：这个 logical plan 是否获得 authority

ExecutionBindingPolicy
    决定：一个 approved logical step 由哪个 execution provider 实现

Dispatcher
    只执行已经绑定且已经获得 Grant 的 provider

StatePlacementPolicy
    决定：状态放 inline / SHM / memfd / mmap / CAS 等哪里

DecisionGatePolicy
    决定：是否启用 Logit Gate

InferenceReusePolicy
    决定：full recompute / APC / explicit KV continuation
```

这是本文最重要的架构结论。

---

# 1. 一句话结论

当前 StateBus 的核心问题不是“没有 Router”，而是：

> **routing 决策已经存在，但分散在 Planner、CapabilityDescriptor、Runtime fallback、LayeredStoragePolicy、RolePath feature flags 和 model-side reuse path 中；其中 logical capability 与 physical execution provider 又被 `capability_id` 深度绑定。**

因此不建议：

```text
Planner
  ↓
新增 Router Agent
  ↓
重新决定 role / capability / state
```

更合理的演进是：

```text
Task
  ↓
CanonicalTaskSpec
  ↓
RouteContext
  ↓
PlanSelector
  ├─ Safe Template
  └─ Planner
        ↓
    PlanProposal
        ↓
PlanPolicyValidator
        ↓
Approved Logical Plan
        ↓
AdaptiveRuntimeEngine
        ↓
STEP_READY
        ↓
ExecutionBindingPolicy
        ↓
Bound Provider
        ↓
fresh CapabilityGrant
        ↓
Dispatcher
```

同时将：

```text
SHM / memfd / mmap
Logit Gate
APC / explicit KV
Memory reuse
```

保留为不同 policy domain，而不是强行塞进一个统一 `StateRouter`。

---

# 2. 研究依据与事实边界

## 2.1 当前主仓库

主仓库：

- https://github.com/qcrs/os
- 默认分支：`master`

本文重点分析以下当前文件：

```text
statebus/runtime/compiler.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_plan_compiler.py
statebus/runtime/plan_policy.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/capability_registry.py
statebus/runtime/domain_packs.py
statebus/runtime/role_path.py
statebus/runtime/semantic_plan.py
statebus/runtime/driver.py
statebus/state/store.py
statebus/route_tool_catalog.py
statebus/contracts/...
docs/implementation/runtime/model-state-paths.md
```

## 2.2 历史仓库

历史演进：

- https://github.com/qcrs/os1

历史版本中曾存在明显固定工作流：

```text
retrieve
→ execute
→ summarize
```

当前 `os/master` 已经从固定 workflow 发展为：

```text
Planner proposal
→ Capability Registry
→ Plan Policy
→ Approved DAG
→ Grant
→ Dispatcher
```

因此本轮 routing 重构不应该退回“另一个 LLM 再决定一遍 workflow”的模式。

---

# 3. 当前 adaptive 主链：源码级整体认知

当前产品级 adaptive 主链可以概括为：

```text
User Request / Benchmark Input
          │
          ▼
TaskCompiler.compile()
          │
          ▼
CanonicalTaskSpec
          │
          ▼
AdaptiveTaskEnvelope
CapabilityRegistry
Available Input Refs
AdaptiveMainlineBindings
          │
          ▼
AdaptiveMainlineRunner.run()
          │
          ├─ StateStore
          ├─ MemoryStore
          ├─ Workspace
          │
          ▼
_assemble_plan()
          │
          ▼
request.propose_plan()
          │
          ▼
PlanProposal
          │
          ▼
normalize_plan
 / compile_required_input_wiring
          │
          ▼
PlanPolicyValidator
          │
          ▼
ApprovedPlan
          │
          ▼
AdaptiveRuntimeEngine.run()
          │
          ▼
ready-step scheduling
          │
          ▼
registry.get(step.capability_id)
          │
          ▼
input/ref checks
          │
          ▼
_issue_grant()
          │
          ▼
CapabilityGrant
          │
          ▼
AdaptiveCapabilityDispatcher.dispatch()
          │
          ▼
descriptor.execution_kind
          │
   ┌──────┼───────────┬──────────┐
   ▼      ▼           ▼          ▼
Retrieval DSL   Bounded Python  Builtin
          │
          ▼
Verified Artifact / Ref
          │
          ▼
next step / fallback / replan
          │
          ▼
Memory commit
```

这条链已经具备相当清晰的 Controller / Authority / Runtime 分层。

真正需要修改的是它内部若干“逻辑语义与物理实现绑死”的 contract。

---

# 4. `TaskCompiler`：它是 Task Normalizer，不应该成为 Router

源码：

```text
statebus/runtime/compiler.py
TaskCompiler.compile()
```

当前 `TaskCompiler` 处理：

```text
task_family
intent_op
target_entities
time_scope
required_outputs
required_tools
arguments
```

并支持：

```text
BENCHMARK_STRICT
    → 必须使用 precompiled CanonicalTaskSpec

interactive JSON
    → parse / validate

interactive free-form
    → heuristic compile

无法可靠理解
    → OPAQUE_FREEFORM
```

但当前代码仍然维护大量固定 allowlist：

```text
allowed_task_families
allowed_intent_ops
allowed_required_outputs
allowed_required_tools
```

这对 benchmark strict 与当前任务集是合理的，但从 generalization 角度看，它不是一个最终通用 schema。

## 4.1 TaskCompiler 应该为 routing 提供什么？

它可以提供：

```text
RouteContext.task_semantics
```

例如：

```yaml
task_family: continuous_csv_table_analysis
intent_op: groupby_aggregate
required_outputs:
  - metric_table
available_input_refs:
  - execution_artifact
```

但它不应该直接：

```python
if intent_op == "groupby_aggregate":
    provider = "dsl"
```

原因是：

```text
TaskCompiler 回答：
“What is requested?”

Execution Binder 回答：
“How should this approved operation be executed here?”
```

两者不能混。

---

# 5. `route_tool_catalog.py`：当前 generalization 的典型瓶颈

当前：

```text
statebus/route_tool_catalog.py
```

维护：

```text
INCIDENT_ROUTE_PROFILES
FINANCIAL_ROUTE_PROFILES
CONTINUOUS_CSV_ROUTE_PROFILES
CONTINUOUS_LONG_DOC_ROUTE_PROFILES
```

然后：

```python
select_route_profiles(spec)
```

通过：

```text
task_family
intent_op
```

做大量 switch。

这种方式在比赛任务封闭集内非常实用，因为它：

- deterministic；
- 易于测试；
- 可显式控制候选；
- 可确保 benchmark 不漂移。

但其问题也非常明确：

> **新 task family 往往意味着继续新增 hard-coded profile。**

所以未来 PlanSelector/BindingResolver 绝不能继续复制这种模式：

```python
if financial:
    plan A
elif csv:
    plan B
```

更合理的是：

```text
contract-driven routing
```

依据：

```text
available ref kinds
required output contract
required evidence type
required features
authorized logical capabilities
resource/risk constraints
```

而不是 benchmark family 名字。

---

# 6. `RolePathRunner.propose_plan()`：当前 Planner 已经承担 workflow routing

源码：

```text
statebus/runtime/role_path.py
RolePathRunner.propose_plan()
```

Planner 目前拿到：

```text
AdaptiveTaskEnvelope
task_goal
allowed_inputs
capability_surface
required_roles
role_cardinality
replan_context
```

Prompt 中直接暴露：

```text
capability_surface
capability_ids_by_role
risk class
memory policies
max steps
allow_llm_python
```

模型最终生成：

```text
PlanProposal
  └─ PlanStepProposal[]
       ├─ role
       ├─ capability_id
       ├─ goal
       ├─ depends_on
       ├─ input refs
       ├─ output contract
       ├─ completion criteria
       └─ required_input_fields
```

这意味着 Planner 现在已经在做：

```text
Role selection
+
workflow shape selection
+
concrete capability selection
```

因此再增加：

```text
Planner
→ Router Agent
```

会产生 semantic authority 重叠。

---

# 7. `AdaptiveMainlineRunner._assemble_plan()`：PlanSelector 的最佳 seam

源码：

```text
statebus/runtime/adaptive_mainline.py
AdaptiveMainlineRunner._assemble_plan()
```

当前第一步就是：

```python
raw_proposal = request.propose_plan()
```

随后才进入：

```text
PlanPolicyValidator
normalize_plan
repair_plan
fallback_proposal
validate_approved_plan
```

这是非常理想的 seam。

## 7.1 当前

```text
AdaptiveMainline
     ↓
always Planner
     ↓
PlanProposal
     ↓
PlanPolicy
```

## 7.2 目标

```text
AdaptiveMainline
     ↓
RouteContextBuilder
     ↓
PlanSelector
   /          \
Template      Planner
   \          /
    PlanProposal
        ↓
PlanPolicy
```

关键原则：

> **PlanSelector 只决定 Proposal Source，不直接生成 ApprovedPlan。**

无论 template 还是 Planner，都必须进入相同：

```text
PlanPolicyValidator
```

这样才能保证：

```text
routing optimization ≠ authority bypass
```

---

# 8. 为什么 PlanSelector 不应该放在 `TaskCompiler`

如果放：

```text
TaskCompiler
   ↓
直接选 workflow
```

很容易变成：

```python
if task_family == ...
```

这只是把 `route_tool_catalog` 的硬编码向前移动。

而 `_assemble_plan()` 此时已经拥有：

```text
canonical task
envelope
registry
available refs
runtime bindings
```

上下文更完整。

所以：

```text
TaskCompiler
    = Task Semantics

PlanSelector
    = Workflow Selection
```

应保持解耦。

---

# 9. 为什么 PlanSelector 不应该放在 ApprovedPlan 后

因为：

```text
ApprovedPlan
```

已经代表 PlanPolicy 批准后的 semantic DAG。

如果此时再做：

```text
ApprovedPlan
→ Router
→ 删除 Retriever
→ 添加 Executor
```

本质就是：

```text
Policy-approved plan
被 Runtime 越权重写
```

这是错误层级。

---

# 10. `adaptive_plan_compiler.py`：职责应该冻结

源码：

```text
statebus/runtime/adaptive_plan_compiler.py
compile_required_input_wiring()
```

其注释本身已经定义得很好：

```text
不选择 capability
不增加 semantic stages
不改变 goal
只补 typed dependency wiring
```

这个模块本质上像 compiler lowering：

```text
Semantic Plan
    ↓
Typed dependency wiring
```

因此：

```text
PlanSelector
BindingResolver
StatePlacementPolicy
InferenceReusePolicy
```

都不应该塞进去。

它可以因为新 contract 改字段，但职责不应该改变。

---

# 11. `PlanPolicyValidator`：StateBus 最重要的 authority boundary 之一

源码：

```text
statebus/runtime/plan_policy.py
PlanPolicyValidator
```

当前它验证：

```text
proposal schema
task identity
step budget
final output contract
memory policy
planner token budget

role cardinality
capability authorization
owner role

Python enablement
risk class
input/output contracts
dependency validity
ref kinds
completion criteria
required input fields

DAG cycle
dependency depth
execution runtime budget
final leaf contract
```

这说明 StateBus 当前并不是：

```text
LLM Planner 输出什么就执行什么
```

而是：

```text
LLM = untrusted proposal
Runtime Policy = authority
```

这个设计原则必须保留。

---

# 12. 当前 `2 <= len(steps)` 的限制

当前 PlanPolicy 明确：

```python
2 <= len(proposal.steps) <= envelope.max_plan_steps
```

因此核心 adaptive runtime 暂时不能表达：

```text
Task
→ one deterministic operation
→ done
```

如果未来希望真正证明：

```text
简单任务可以 bypass 多 Agent workflow
```

核心 runtime 可以考虑改成：

```text
1 <= steps <= max
```

但比赛 formal lane 当前仍可以继续规定：

```text
retriever: exactly 1
executor: 1~2
summarizer: exactly 1
```

即：

```text
Core Runtime Capability
≠
Formal Benchmark Contract
```

不要混淆。

---

# 13. 当前最大抽象问题：`CapabilityDescriptor`

一个 descriptor 同时包含：

```text
capability_id
owner_role
description

input/output ref kinds
input/output contracts

execution_kind
risk class
max runtime

supports_replay
validators
fallback_capability_id
completion criteria
```

问题在于，它把三个不同层次绑在一起：

```text
A. Logical Semantic Authority
   要做什么？

B. Execution Provider
   怎么做？

C. Runtime Properties
   成本/风险/资源/fallback
```

---

# 14. DSL 与 Bounded Python 是当前最明显的绑定案例

当前 generic pack 中：

```text
execute_analysis_dsl_v2
execute_bounded_python_v2
```

两个 capability：

- 同属 `executor`
- 都接收 verified analysis input
- 都输出 `execution_artifact`
- 都服务于 generic analysis
- 都可由同一 quality contract 验证

但其物理执行方式不同。

## DSL

适合：

```text
select
rename
filter
sort
aggregate
group
difference
ratio
pct change
compare periods
```

不适合：

```text
pivot
branch/recombine
custom parser
imputation
复杂 cross-row transform
未注册 statistical operation
```

## Bounded Python

适合：

```text
custom parsing
multi-stage statistics
outlier handling
imputation
cross-row alignment
pivot
branch-and-recombine
```

从 semantic authority 看，两者完全可以被理解为：

```text
Logical Capability:
    analyze_verified_data
```

而：

```text
Transform DSL
Bounded Python
```

只是两个 provider。

---

# 15. 目标：Logical Capability 与 Execution Provider 分离

建议新增：

```text
LogicalCapabilityDescriptor
ExecutionProviderDescriptor
```

## 15.1 LogicalCapabilityDescriptor

```yaml
logical_capability_id: analyze_verified_data_v1
owner_role: executor

input_ref_kinds:
  - execution_artifact
  - canonical_evidence_pack

required_input_ref_kinds:
  - execution_artifact

input_contract_version:
  statebus.analysis_input.v2

output_ref_kinds:
  - execution_artifact

output_contract_version:
  statebus.analysis_result.v2

validator_ids:
  - generic_analysis
```

它回答：

> 这个 workflow step 在语义上被授权完成什么？

## 15.2 ExecutionProviderDescriptor

DSL：

```yaml
provider_id: transform_dsl_v2
logical_capability_ids:
  - analyze_verified_data_v1
execution_kind: transform_dsl
risk_class: workspace_write
features:
  - select
  - rename
  - filter
  - sort
  - aggregate
  - grouped_aggregate
  - safe_arithmetic
  - compare_periods
requires_resources: []
supports_replay: true
max_runtime_ms: 120000
```

Python：

```yaml
provider_id: bounded_python_v2
logical_capability_ids:
  - analyze_verified_data_v1
execution_kind: llm_bounded_python
risk_class: bounded_code
features:
  - custom_parse
  - cross_row_alignment
  - branch_recombine
  - pivot
  - imputation
  - custom_statistics
requires_resources:
  - code_llm
  - bwrap
supports_replay: true
max_runtime_ms: 120000
```

---

# 16. Planner 重构：从 concrete capability 改为 logical requirement

当前 Planner：

```text
step.capability_id = execute_analysis_dsl_v2
```

目标：

```text
step.logical_capability_id = analyze_verified_data_v1
```

并可携带 bounded requirement：

```yaml
required_features:
  - grouped_aggregate
  - safe_arithmetic
```

Planner 不需要知道：

```text
DSL 当前 p50
CodeAct sandbox 是否 ready
当前机器 resource pressure
provider historical failure rate
```

这些属于 Runtime。

---

# 17. `required_features` 不能是任意自由文本

必须定义：

```text
RegisteredFeatureVocabulary
```

例如：

```text
select
filter
sort
aggregate
grouped_aggregate
safe_arithmetic
compare_periods
custom_parse
cross_row_alignment
branch_recombine
pivot
imputation
outlier_detection
custom_statistics
```

然后 PlanPolicy 校验：

```text
required_features ⊆ registered_feature_vocabulary
```

---

# 18. Execution Binding 的最佳 seam：`STEP_READY -> _issue_grant()`

源码：

```text
statebus/runtime/adaptive_runtime.py
AdaptiveRuntimeEngine.run()
```

当前 ready step 后做：

```text
descriptor = registry.get(step.capability_id)
input refs
input kind validation
_issue_grant()
dispatcher.dispatch()
```

目标：

```text
STEP_READY
    ↓
resolve actual input refs
    ↓
ExecutionBindingPolicy.resolve()
    ↓
ExecutionBindingReceipt
    ↓
_issue_grant(binding)
    ↓
CapabilityGrant
    ↓
Dispatcher
```

这是最自然的位置，因为此时 Runtime 已经知道：

```text
actual input refs
actual input ref kinds
step attempt
workspace
resource readiness
risk envelope
previous failures
runtime telemetry
```

很多信息在 Planner 阶段还不存在。

---

# 19. 重要源码事实：Runtime 已经存在“隐式 rebinding”

当前 `AdaptiveRuntimeEngine.run()` 在 bounded Python 失败时，如果：

```text
step.on_failure == fallback_deterministic
descriptor.fallback_capability_id exists
```

Runtime 会：

```text
fallback_descriptor = registry.get(...)
fallback_step = replace(step, capability_id=...)
fresh fallback grant
dispatch fallback
```

也就是说：

```text
Approved step
   ↓
Provider A
   ↓ failure
Provider B
   ↓
fresh Grant
```

已经存在。

因此：

> **Execution Rebinding 并不是与现有 StateBus 完全冲突的新概念。当前代码已经有 special-case rebinding，只是没有被抽象成通用 policy。**

后续可把：

```text
hard-coded bounded-Python fallback
```

提升为：

```text
general provider bind / rebind
```

---

# 20. Rebind 与 Replan 必须严格区分

## Execution Rebind

logical semantics 不变：

```text
analyze_verified_data
```

只是实现改变：

```text
DSL
→ Python
```

要求：

```text
same logical capability
same semantic input contract
same semantic output contract
same completion requirements
same validator obligations
```

这是 physical execution change。

## Replan

semantic DAG 改变：

```text
retrieve
→ analyze
→ summarize
```

变成：

```text
retrieve-more
→ join
→ analyze
→ summarize
```

当前 Runtime 已有：

```text
request.replan()
_valid_replan()
```

并重新验证 replacement plan。

因此：

```text
Rebind != Replan
```

必须成为正式架构约束。

---

# 21. ExecutionBindingPolicy：先过滤，再优化

建议固定顺序：

```text
1 Authority Gate
2 Logical Contract Gate
3 Input Contract Gate
4 Provider Expressiveness Gate
5 Resource Availability Gate
6 Risk Gate
7 Validator / Quality Capability Gate
────────────────────────────
8 Cost Ranking
```

## 21.1 Authority Gate

```text
provider 是否属于该 logical capability？
provider 是否被 envelope 允许？
```

## 21.2 Contract Gate

```text
input contract compatible?
output contract compatible?
ref kinds compatible?
```

## 21.3 Expressiveness Gate

```text
RequiredFeatures ⊆ ProviderFeatures
```

例如 pivot required，DSL 直接 infeasible。

## 21.4 Resource Gate

例如 Python：

```text
code_llm available?
bwrap ready?
workspace usable?
```

## 21.5 Risk Gate

如果：

```text
Envelope.risk = WORKSPACE_WRITE
```

则：

```text
BOUNDED_CODE provider
```

不可被 Binder 擅自启用。

## 21.6 Quality Gate

provider 必须能满足 logical capability 的 validator obligations。

## 21.7 Cost Ranking

只有全部通过才：

\[
p^* = \arg\min_{p \in P_{eligible}} C(p)
\]

初版可用：

\[
C(p)=\hat T(p)+\alpha\hat{Tokens}(p)+\beta\hat{Bytes}(p)
\]

甚至第一版只是静态 priority 都可以。

---

# 22. 为什么不能所有 path 直接打一个统一分数

假设：

```text
DSL latency = 20 ms
Python latency = 2500 ms
```

但任务要求 pivot。

DSL 根本做不了，因此：

```text
20ms < 2500ms
```

毫无意义。

所以必须：

```text
eligible first
optimize second
```

---

# 23. 建议新增 `ExecutionBindingReceipt`

```yaml
schema_version: statebus.execution_binding_receipt.v1

binding_id: bind-task1-executor-1-attempt1
task_id: task1
step_id: executor-1
attempt_id: adaptive-attempt-1

logical_capability_id:
  analyze_verified_data_v1

candidate_provider_ids:
  - transform_dsl_v2
  - bounded_python_v2

rejected_candidates:
  - provider_id: transform_dsl_v2
    reason_codes:
      - missing_required_feature:pivot

eligible_candidates:
  - bounded_python_v2

selected_provider_id:
  bounded_python_v2

policy_version:
  statebus.execution_binding_policy.v1

resource_snapshot_hash: ...
telemetry_snapshot_hash: ...

estimated_latency_ms: 2400
estimated_token_cost: 1000
estimated_transfer_bytes: 0

fallback_provider_ids: []
receipt_hash: ...
```

价值：

- 可解释；
- 可调试；
- 可 benchmark；
- 可做 routing regret；
- 可证明 Router 没有越权；
- 可记录为什么 CodeAct 被选择。

---

# 24. `CapabilityGrant` 必须升级

当前 Grant 绑定 concrete capability。

目标至少包含：

```text
logical_capability_id
logical_capability_version
provider_id
provider_version
binding_receipt_hash
input refs
output contract
workspace
runtime limit
expiry
approved_plan_hash
```

Grant 依然是执行权限的唯一一次性证明。

Dispatcher 不应该自己再选 provider。

---

# 25. Dispatcher 的目标职责

当前：

```text
descriptor = registry.get(step.capability_id)
handler = handlers[descriptor.execution_kind]
```

目标：

```text
provider = provider_registry.get(grant.provider_id)
handler = handlers[provider.execution_kind]
```

也就是：

```text
Logical Step
   ↓
Binding
   ↓
Provider
   ↓
ExecutionKind
   ↓
Dispatcher
```

Dispatcher 不再拥有 routing authority。

---

# 26. DSL/Python provider 实现本身无需推翻

当前 `_dispatch_transform_dsl()` 已经拥有：

```text
typed input
memory replay
program generation
semantic validation
independent recompute
quality validation
single repair
artifact lifecycle
```

当前 `_dispatch_llm_python()` 拥有：

```text
verified input
evidence context
memory inputs
CodeGenerationPolicy
bwrap enforcement
LLM code generation
sandbox
quality validation
repair
artifact lifecycle
```

这些 provider 内部实现可以大量保留。

主要改 `step.capability_id` 相关 semantic/provider lookup。

---

# 27. metadata 应重新归属

## Logical Capability

```text
owner role
semantic input contract
semantic output contract
accepted/required ref kinds
completion criteria
quality semantics
validator obligations
required output fields
```

## Provider

```text
execution kind
expressiveness/features
runtime resource requirements
risk class
runtime budget
backend availability
provider-specific replay recipe
provider-specific generation/sandbox policy
performance telemetry
```

当前大量：

```text
quality_semantics_by_capability
output_schema_by_capability
codeact_contracts
```

需要重新分类。

---

# 28. `PlanPolicyValidator` 重构后的职责

继续拥有：

```text
task identity
logical capability authorization
role ownership
DAG validity
dependency depth
logical input/output contract
ref kind flow
field flow
completion criteria
final output contract
semantic step budget
memory policy authorization
```

移到 BindingPolicy：

```text
execution_kind
provider availability
provider feature coverage
sandbox readiness
provider max runtime
provider cost
provider fallback ordering
provider p50/p95
```

---

# 29. Risk 为什么不能完全从 PlanPolicy 移走

因为一个 logical capability 可能有：

```text
DSL: WORKSPACE_WRITE
Python: BOUNDED_CODE
```

如果 Plan 只批准 logical capability，而 Binder 可以任意 provider，就会发生权限升级。

所以 Envelope 建议升级为：

```text
allowed_logical_capability_ids
allowed_provider_ids
risk_class
```

Binder 必须同时满足：

```text
provider allowed
AND
provider risk <= envelope risk
```

---

# 30. PlanSelector 第一版设计

建议新增：

```text
PlanTemplateRegistry
PlanEligibilityChecker
PlanSelector
PlanSelectionReceipt
```

Template 不应是 benchmark operation：

错误：

```text
compute_revenue_plan
detect_outlier_plan
```

正确：

```text
direct_analysis
analysis_then_report
retrieve_analyze_report
retrieve_then_report
memory_assisted_analysis
```

即 generic workflow shape。

---

# 31. PlanSelector 示例

## Template A：Direct Analysis

```text
verified source artifact
        ↓
analyze_verified_data
```

Eligibility：

```text
verified input exists
retrieval not required
required output directly produced by analysis
logical analysis authority available
```

## Template B：Analysis + Report

```text
verified source
    ↓
analysis
    ↓
compose report
```

## Template C：Retrieve + Analyze + Report

```text
retrieval
    ↓
analysis
    ↓
compose
```

适用于真正需要 evidence/citation 的任务。

---

# 32. PlanSelector 不应该直接返回 ApprovedPlan

正确：

```text
PlanSelector
    ↓
PlanProposal
    ↓
normalization
    ↓
PlanPolicyValidator
    ↓
ApprovedPlan
```

template 与 LLM Planner 完全同等接受 Policy 审批。

---

# 33. PlanSelectionReceipt

```yaml
schema_version: statebus.plan_selection_receipt.v1

task_id: ...
selector_policy_version: ...

candidate_templates:
  - direct_analysis
  - analysis_report

rejected:
  - template_id: direct_analysis
    reason: final_output_requires_cited_report

selected_source:
  planner

selected_template_id: null
planner_invoked: true
route_context_hash: ...
receipt_hash: ...
```

---

# 34. Planner bypass 的真正价值

简单 deterministic task 如果仍先让 LLM Planner 决定“调用 deterministic tool”，系统付出：

```text
Planner tokens
Planner latency
Planner failure probability
```

只是为了得到一个可以由 contract 直接判断的 DAG。

因此 PlanSelector 的核心价值不是“更智能”，而是：

> **在安全确定的情况下避免不必要的 planning inference。**

---

# 35. Formal competition lane 不应该立即取消三角色

当前 formal lane 明确固定：

```text
retriever: 1
executor: 1~2
summarizer: 1
```

这是为了满足比赛 3 Agent / 3 Role 要求。

因此应区分：

```text
Competition Formal Lane
    保持明确 3-role collaboration

Adaptive Routing Evaluation Lane
    允许 1/2/3+ role workflow
```

否则实验不可比。

---

# 36. State Routing 重新分类：不要再用一个总 `StateRouter`

之前容易写成：

```text
text
typed ref
embedding
hidden
logit
APC
KV
```

然后 Router choose one。

这是错误抽象，因为这些机制作用层不同。

---

# 37. `LayeredStoragePolicy` 已经是成熟的 State Placement Router

源码：

```text
statebus/state/store.py
LayeredStoragePolicy
```

当前根据：

```text
object_kind
size_bytes
shared_memory_bytes_used
state_pool_mode
```

选择：

```text
INLINE
MEMFD
SHARED_MEMORY
MMAP_FILE
CAS_SIDECAR
WORKSPACE_ROOT
```

并有：

```text
shared_memory_budget_exceeded
OS backend unavailable
fallback()
```

因此 StateBus 已经存在物理 state placement routing。

未来可升级成 `StatePlacementPolicy v2`，增加：

```text
consumer locality
NUMA
remote backend
transfer telemetry
payload lifetime
fanout count
```

而不需要另造 StateRouter。

---

# 38. Embedding 属于 Retrieval / State Representation Policy

Embedding 当前用于 evidence candidate selection，会改变 downstream evidence surface。

所以它不是简单物理 backend。

是否启用 embedding 会影响语义选择，应属于：

```text
Retrieval / State Representation Policy
```

而非 Placement。

---

# 39. Logit 属于 Decision Gate Policy

当前 `RolePathRunner`：

```text
STATEBUS_LOGIT_GATE_MODE
    off
    telemetry
    retry_once
```

未来可以改成：

```text
DecisionGatePolicy
```

输入：

```text
candidate count
decision ambiguity
risk
previous rejection
confidence/entropy signals
```

输出：

```text
off
telemetry
retry_once
```

它与 KV 不属于同一个 routing problem。

---

# 40. Prefix / Explicit KV 属于 InferenceReusePolicy

当前：

```text
Prefix:
    exact-token shared prefix
    vLLM APC
    consumer still sends full prompt

Explicit KV:
    producer captures paged KV
    consumer sends handle + suffix
```

未来统一逻辑：

```text
LLM request
    ↓
InferenceReusePolicy
    ↓
compatible explicit KV?
    ├─ yes and benefit > cost
    │     → KV continuation
    │
    ├─ no
    │
exact shared prefix possible?
    ├─ yes
    │     → full prompt + APC
    │
    └─ no
          → recompute
```

---

# 41. 当前 `EngineLocalKVHandle` 已提供很好的 Policy 基础

现有 handle 包含：

```text
engine_id
engine_generation
model_id
model_revision
tokenizer_digest
task_id
producer_request_id
seq_len
block_size
token_digest
kv_bytes_actual
layer_count
dtype
storage_tier
created_at
expires_at
status
```

还有 `compatibility_digest`。

因此未来不需要从零设计 KV eligibility，只需增加 cost / benefit 信息。

---

# 42. 外部研究：MasRouter

论文：

- MasRouter: Learning to Route LLMs for Multi-Agent Systems
- ACL 2025
- https://aclanthology.org/2025.acl-long.757/
- https://arxiv.org/abs/2502.11133

GitHub：

- https://github.com/yanweiyue/masrouter

核心代码：

- `MAR/MasRouter/mas_router.py`

MasRouter 的 routing decomposition：

```text
Task Classification
      ↓
Collaboration Mode Selection
      ↓
Agent Number Determination
      ↓
Role Allocation
      ↓
LLM Allocation
```

官方实现包含：

```text
TaskClassifier
CollabDeterminer
NumDeterminer
RoleAllocation
LLMRouter
```

并使用 SentenceEncoder、VAE、Graph Fusion 与 learned sampling。

## 可借

> MAS routing 不应该压缩成单个 decision。

这支持 StateBus 分成：

```text
Plan Selection
Execution Binding
State Placement
Decision Gate
Inference Reuse
```

## 不建议直接搬

MasRouter 的 controller 目标主要是构造 cost/performance 更优的 Agent team；StateBus 额外有：

```text
typed contract
Ref authority
risk class
sandbox policy
capability grant
replay compatibility
provenance
fail-closed behavior
```

所以 learned controller 不能直接拥有 authority。

---

# 43. 外部研究：RouteLLM

论文：

- RouteLLM: Learning to Route LLMs with Preference Data
- https://arxiv.org/abs/2406.18665

GitHub：

- https://github.com/lm-sys/RouteLLM

RouteLLM 把 Router 收敛为：

```text
Router score
    ↓
threshold
    ↓
strong / weak model
```

最值得借的是：

```text
quality-cost Pareto frontier
```

未来 StateBus 可以：

```text
Feasibility Filter
      ↓
eligible providers
      ↓
ProviderScorer
      ↓
cost/quality score
      ↓
selection
```

但不能忽略 provider expressiveness。

---

# 44. 外部研究：DyLAN

论文：

- A Dynamic LLM-Powered Agent Network for Task-Oriented Agent Collaboration
- https://arxiv.org/abs/2310.02170

GitHub：

- https://github.com/SALT-NLP/DyLAN

核心：

```text
Team Optimization
→ Agent selection
→ Task solving
```

可借：

```text
optional role contribution
workflow edge usefulness
```

不建议现在 runtime trial 多组 Agent 后再 pruning，因为与低开销目标冲突。

---

# 45. 外部研究：AgentPrune

论文：

- Cut the Crap: An Economical Communication Pipeline for LLM-based Multi-Agent Systems
- https://arxiv.org/abs/2410.02506

GitHub：

- https://github.com/yanweiyue/AgentPrune

核心是把 multi-agent communication 看作 spatial-temporal message graph，再 pruning 冗余/有害 edge。

对 StateBus 更适合的用法不是“删 Agent”，而是：

```text
drop unnecessary communication edge
drop unnecessary hydrated payload
drop unnecessary semantic state publication
```

例如下游只需要 `ExecutionArtifactRef` 时，不应该继续 hydration 完整 evidence text。

---

# 46. 外部研究：AgentDropout / V2

AgentDropout：

- https://aclanthology.org/2025.acl-long.1170/
- https://github.com/wangzx1219/AgentDropout

支持一个重要观点：

```text
不同 task 不需要固定相同团队规模
```

AgentDropoutV2：

- https://arxiv.org/abs/2602.23258
- https://github.com/TonySY2/AgentDropoutV2

更值得借的是：

```text
intercept
→ verify
→ rectify/reject
→ fallback
```

StateBus 不需要复制其 auditor Agent，而应复制：

```text
guarded selection + fallback
```

即：

```text
PlanSelector template
→ PlanPolicy reject
→ Planner fallback
```

和：

```text
Provider A
→ failure
→ Rebinding Policy
→ fresh Grant
→ Provider B
```

---

# 47. 外部研究：PACT

论文：

- What Should Agents Say? Action-state Communication for Efficient Multi-Agent Systems
- https://arxiv.org/abs/2606.05304

GitHub：

- https://github.com/iNLP-Lab/PACT

PACT 的核心不是增加 Router，而是：

```text
raw agent output
      ↓
protocolized action-state
      ↓
shared history
```

这和 StateBus typed Ref 很契合。

可借的真正思想是：

> 每条 edge 只传 downstream action 所需的最小状态。

这可以把当前 `required_input_fields` 从正确性 contract 扩展成 communication minimization hint。

---

# 48. 外部方案对照

| 工作 | 核心对象 | 可借 | 不建议直接搬 |
|---|---|---|---|
| MasRouter | collaboration / roles / LLM | 分层 routing decomposition | learned controller 直接拥有 authority |
| RouteLLM | strong/weak model | score + threshold、Pareto evaluation | 忽略 provider expressiveness |
| DyLAN | agent team | optional role contribution | runtime trial 后再删 Agent |
| AgentPrune | communication edge | edge/payload pruning | 把当前短 DAG 当复杂 message graph |
| AgentDropout | nodes + edges | task-dependent team size | 破坏 formal 3-role requirement |
| AgentDropoutV2 | information flow | guarded selection + fallback | 新增昂贵 auditor Agent |
| PACT | communication content | downstream-required action state | 只理解成文本压缩 |

---

# 49. 推荐最终 Routing Architecture

```text
                           ┌────────────────────┐
                           │   User / Task      │
                           └─────────┬──────────┘
                                     │
                                     ▼
                           ┌────────────────────┐
                           │   TaskCompiler     │
                           │ CanonicalTaskSpec  │
                           └─────────┬──────────┘
                                     │
                                     ▼
                           ┌────────────────────┐
                           │ RouteContextBuilder│
                           └─────────┬──────────┘
                                     │
                                     ▼
                           ┌────────────────────┐
                           │   PlanSelector     │
                           └──────┬───────┬─────┘
                                  │       │
                         template │       │ planner
                                  ▼       ▼
                             PlanProposal
                                  │
                                  ▼
                         adaptive_plan_compiler
                                  │
                                  ▼
                           PlanPolicyValidator
                                  │
                                  ▼
                         Approved Logical Plan
                                  │
                                  ▼
                         AdaptiveRuntimeEngine
                                  │
                                READY
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │ ExecutionBindingPolicy │
                     └───────────┬────────────┘
                                 │
                                 ▼
                     ExecutionBindingReceipt
                                 │
                                 ▼
                         CapabilityGrant
                                 │
                                 ▼
                    AdaptiveCapabilityDispatcher
                                 │
                      ┌──────────┼───────────┐
                      ▼          ▼           ▼
                    DSL       Python       Builtin
                                 │
                                 ▼
                       Verified Artifact/Ref
```

并行 policy：

```text
StatePlacementPolicy
    inline / memfd / SHM / mmap / CAS

DecisionGatePolicy
    Logit off / telemetry / retry

InferenceReusePolicy
    recompute / APC / explicit KV

MemoryReusePolicy
    none / assist / replay / exact replay
```

---

# 50. Contract 重构清单

## 必须改/拆

```text
CapabilityDescriptor
CapabilityRegistry
PlanStepProposal
ApprovedPlan
CapabilityGrant
AdaptiveTaskEnvelope
AdaptiveRuntimeSignature
AdaptiveMainlineRequest
AdaptivePlannerAssemblyRecord
PlanPolicyValidator
AdaptiveRuntimeEngine
AdaptiveCapabilityDispatcher
```

## 建议新增

```text
LogicalCapabilityDescriptor
LogicalCapabilityRegistry
ExecutionProviderDescriptor
ExecutionProviderRegistry
RouteContext
PlanTemplateDescriptor
PlanSelectionReceipt
ExecutionBindingContext
ExecutionBindingReceipt
ProviderTelemetrySnapshot
```

---

# 51. `AdaptiveRuntimeSignature` 为什么需要升级

同一个 Approved Logical Plan 未来可能：

```text
Run A → DSL
Run B → Python
```

因此 signature 至少增加：

```text
logical_registry_digest
provider_registry_digest
binding_policy_version
```

具体每个 attempt 的 provider 通过：

```text
BindingReceipt + Grant + AttemptRecord
```

记录。

不要让 physical choice 改 logical plan hash。

---

# 52. 推荐源码目录

```text
statebus/runtime/routing/
    __init__.py
    context.py
    plan_selector.py
    plan_templates.py
    binding.py
    provider_registry.py
    cost.py
    telemetry.py
    receipts.py
```

Contract：

```text
statebus/contracts/routing.py
```

避免继续把 routing 塞进越来越大的：

```text
role_path.py
adaptive_runtime.py
```

---

# 53. 分阶段实施方案

## R0 — Contract Split，行为保持不变

先拆：

```text
logical capability
provider
```

但初始可以：

```text
1 logical capability
→ 1 existing provider
```

确保当前行为和测试尽量不漂移。

## R1 — DSL/Python Binding

先只做：

```text
analyze_verified_data_v1
    ├─ transform_dsl_v2
    └─ bounded_python_v2
```

并把当前 Python special fallback 改成通用 provider rebind。

这是最重要的 Routing vertical slice。

## R2 — PlanSelector

在 `_assemble_plan()` 做：

```text
Template
or
Planner
```

只上 2~3 个 generic safe templates。

## R3 — Receipts / Telemetry

落：

```text
PlanSelectionReceipt
ExecutionBindingReceipt
```

## R4 — Policy Consolidation

正式把：

```text
LayeredStoragePolicy
```

纳入 routing architecture。

逐步将 Prefix/KV env switch 收敛为 `InferenceReusePolicy`；Logit 收敛为 `DecisionGatePolicy`。

## R5 — Cost-Aware Routing

积累真实 telemetry 后再做 EWMA / cost model。

---

# 54. 为什么当前不建议直接 Learned Router / Bandit

当前任务规模与类型仍有限。

直接训练：

```text
task → best path
```

非常容易学成：

```text
financial → DSL
某 csv case → CodeAct
incident → ...
```

这只是 benchmark memorization。

正确顺序：

```text
Rule / contract
    ↓
Telemetry
    ↓
Cost model
    ↓
Offline learned scorer
    ↓
optional contextual bandit
```

---

# 55. Routing 实验最小指标

## Plan Routing

```text
planner invocation rate
template hit rate
template rejection rate
role count
step count
plan latency
planner tokens
task quality
```

比较：

```text
Fixed Full Workflow
Planner Adaptive
PlanSelector + Planner Fallback
```

## Provider Routing

```text
DSL selection count
Python selection count
provider feasibility rejection
provider fallback / rebind
provider latency
provider token
quality validation
routing overhead
```

---

# 56. Router Regret

只对 semantic-equivalent + authorized provider 枚举：

\[
p_{oracle}
=
\arg\min_{p:Q(p)\ge Q_{floor}}
Cost(p)
\]

Router regret：

\[
Regret
=
Cost(p_{selected})-Cost(p_{oracle})
\]

测：

```text
latency regret
token regret
fallback regret
quality violation count
```

这比单纯“routing accuracy”更有意义。

---

# 57. Routing Overhead 必须独立计量

如果 Router 花：

```text
2s + 1000 tokens
```

去决定是否使用 20ms DSL，系统是失败的。

所以必须记录：

```text
routing_policy_ms
routing_model_tokens
```

第一版 rule-based policy 应该几乎为零额外 token。

---

# 58. 关键 failure mode

## A. Router 越权

Envelope 不允许 CodeAct，Binder 却选 Python：必须硬拒绝。

## B. 把不同语义 path 当 provider

Embedding/no-Embedding 可能改变 evidence selection，不能直接视作 semantic equivalent physical path。

## C. 把 APC/KV 与 HiddenState 混合

```text
APC/KV = compute reuse
Hidden/C2C = semantic communication
```

不是同一类。

## D. PlanSelector 变成 task-family switch

如果最终全是：

```python
if financial:
if csv:
if incident:
```

Router 没有提高泛化性。

## E. Planner 与 Binder 重复决策

如果 Planner 的 goal 仍明确写“use DSL”，Binder 再改 Python，说明 logical/physical contract 没拆干净。

## F. Provider fallback 改变语义

只有：

```text
same logical capability
same output contract
same validator obligations
```

才能 Rebind，否则必须 Replan。

---

# 59. 推荐第一组 vertical slice

不要一开始覆盖 retrieval/memory/logit/KV/state placement 全部。

第一组只做：

```text
Logical:
    analyze_verified_data_v1

Providers:
    transform_dsl_v2
    bounded_python_v2
```

原因：

1. 当前已有两个真实 provider；
2. 输入/输出 contract 高度接近；
3. 当前已有 fallback；
4. 可以立即验证 logical/provider split；
5. 不需要同时改 vLLM；
6. 很容易做 A/B 与 quality gate。

---

# 60. Binder 示例

## grouped aggregate

需求：

```text
grouped_aggregate
```

DSL：eligible。  
Python：eligible。  
Cost ranking 选 DSL。

## pivot

需求：

```text
pivot
```

DSL：缺 feature，reject。  
Python：eligible。  
直接选 Python，不需要 cost model。

## Python 被风险策略禁止

需求：custom parse。  
DSL：expressiveness reject。  
Python：risk/authority reject。  
结果：`NO_ELIGIBLE_PROVIDER`，进入 replan 或 fail-closed，不能偷偷执行 Python。

---

# 61. PlanSelector 示例

输入：

```text
verified execution_artifact 已存在
要求 analysis_result
没有 citation requirement
```

结果：

```text
direct_analysis template eligible
Planner invocation = 0
```

复杂任务：

```text
需要三份报告叙述证据
需要 citation
需要计算
```

template 无法安全覆盖：

```text
PlanSelector → Planner
```

Planner 再构造：

```text
Retriever
→ Executor
→ Summarizer
```

这才是真正的“轻任务 bypass，复杂任务保留 Agent reasoning”。

---

# 62. 与比赛叙事如何结合

如果做好后，StateBus 的项目叙事可以从：

```text
我们实现了 Embedding / Logit / Memory / CodeAct / APC / KV
```

提升为：

> **StateBus 是一个 typed, policy-governed adaptive multi-agent runtime。Agent 提出 semantic workflow；Runtime 在 authority、contract、risk 和 resource 约束下选择最小必要 workflow 与 execution provider，并对 state placement、decision gating 和 inference reuse 分层决策。**

这比 feature collection 更完整。

---

# 63. 最终建议冻结的设计决策

1. **不增加第五个 Router Agent。**
2. 在 `AdaptiveMainlineRunner._assemble_plan()` 增加 `PlanSelector`。
3. 拆 `CapabilityDescriptor` 为 `LogicalCapabilityDescriptor + ExecutionProviderDescriptor`。
4. 在 `AdaptiveRuntimeEngine STEP_READY -> _issue_grant()` 之间增加 `ExecutionBindingPolicy`。
5. 把当前 bounded-Python special fallback 重构为通用 Provider Rebinding。
6. PlanPolicy 继续保留 authority，Router 不得绕过。
7. 不新增统一 StateRouter；分别使用 StatePlacement / DecisionGate / InferenceReuse / MemoryReuse Policy。
8. 第一版只用 rules + contracts + resource checks。
9. 先积累 PlanSelectionReceipt / ExecutionBindingReceipt / provider telemetry，再考虑 learned routing。

---

# 64. 下一步建议

下一轮应直接对以下四个 contract 做逐字段 Before/After：

```text
CapabilityDescriptor
PlanStepProposal
ApprovedPlan
CapabilityGrant
```

同时设计：

```text
migration compatibility
schema version / hash
old descriptor adapter
PlanPolicy changes
Runtime changes
Dispatcher changes
test migration
```

只有这一层冻结之后，才建议真正开始 R0 contract split。

---

# 65. 参考资料

## StateBus

- https://github.com/qcrs/os
- https://github.com/qcrs/os1
- https://github.com/qcrs/os/blob/master/statebus/runtime/compiler.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_mainline.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_plan_compiler.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/plan_policy.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_runtime.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_dispatcher.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/domain_packs.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/role_path.py
- https://github.com/qcrs/os/blob/master/statebus/state/store.py
- https://github.com/qcrs/os/blob/master/statebus/route_tool_catalog.py
- https://github.com/qcrs/os/blob/master/docs/implementation/runtime/model-state-paths.md

## MasRouter

- https://aclanthology.org/2025.acl-long.757/
- https://arxiv.org/abs/2502.11133
- https://github.com/yanweiyue/masrouter
- https://github.com/yanweiyue/masrouter/blob/main/MAR/MasRouter/mas_router.py

## RouteLLM

- https://arxiv.org/abs/2406.18665
- https://github.com/lm-sys/RouteLLM
- https://github.com/lm-sys/RouteLLM/blob/main/routellm/routers/routers.py

## DyLAN

- https://arxiv.org/abs/2310.02170
- https://github.com/SALT-NLP/DyLAN

## AgentPrune

- https://arxiv.org/abs/2410.02506
- https://github.com/yanweiyue/AgentPrune

## AgentDropout

- https://aclanthology.org/2025.acl-long.1170/
- https://github.com/wangzx1219/AgentDropout

## AgentDropoutV2

- https://arxiv.org/abs/2602.23258
- https://github.com/TonySY2/AgentDropoutV2

## PACT

- https://arxiv.org/abs/2606.05304
- https://github.com/iNLP-Lab/PACT

---

# 66. 最终架构摘要

```text
                         USER TASK
                            │
                            ▼
                    CanonicalTaskSpec
                            │
                            ▼
                       RouteContext
                            │
                            ▼
                      PlanSelector
                    /              \
             Safe Template        Planner
                    \              /
                     \            /
                      PlanProposal
                            │
                            ▼
                    PlanPolicyValidator
                            │
                            ▼
                  Approved Logical Plan
                            │
                            ▼
                   AdaptiveRuntimeEngine
                            │
                         STEP_READY
                            │
                            ▼
                ExecutionBindingPolicy
                            │
                            ▼
                ExecutionBindingReceipt
                            │
                            ▼
                    CapabilityGrant
                            │
                            ▼
                       Dispatcher
                            │
                     ExecutionProvider
                            │
                            ▼
                    Verified Artifact
```

外围：

```text
StatePlacementPolicy
  → SHM / memfd / mmap / CAS

DecisionGatePolicy
  → Logit off / observe / retry

InferenceReusePolicy
  → recompute / APC / explicit KV

MemoryReusePolicy
  → none / assist / replay
```

其中：

```text
PlanSelector
    优化 workflow complexity

ExecutionBindingPolicy
    优化 implementation choice

PlanPolicy / Grant
    维护 authority

Validators
    维护 correctness

State / KV policies
    优化 data movement 与 inference reuse
```

这就是当前 StateBus Routing 最合理、也最接近现有源码演进路线的目标形态。
