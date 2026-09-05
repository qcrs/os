# StateBus Batch-05 — Logical Capability / Execution Provider Binding 深度源码审计与重构设计

> Repository: `https://github.com/qcrs/os`  
> Branch: `master`  
> Audited baseline: `8bfc6464ec236c0e121911095fc283129b0e7696`  
> Date: 2026-09-03  
> Scope: **Logical Capability / Execution Provider Binding only**  
> Mode: **Source audit + GitHub/Web research + migration design; no code changes**
>
> 本轮承接 Batch-04：
>
> ```text
> ApprovedPlan
>     ↓
> STEP_READY
>     ↓
> [Batch-05]
> ExecutionBindingPolicy
>     ↓
> ExecutionBindingReceipt
>     ↓
> provider-bound CapabilityGrant
>     ↓
> [Batch-04]
> ProtocolInvocationBinding
>     ↓
> Provider Dispatcher / Worker
> ```
>
> 本轮明确不进入：
>
> ```text
> Prefix / APC / Explicit KV
> Scheduler / Reliability / Deployment
> External Benchmark / Evidence Closure
> Security / Privacy Final Pass
> ```
>
> 也不重新设计 Planner / Replan 主链，只修正 Logical Capability 与 Physical Provider 的边界。

---

# 0. 本轮问题定义

这一轮真正的问题不是：

```text
“DSL 和 Python 谁更快？”
```

也不是：

```text
“要不要做一个 ProviderRouter？”
```

真正要回答的是：

```text
1. CapabilityDescriptor 现在到底描述的是：
   语义能力？
   还是执行实现？

2. Planner 现在选择的到底是：
   “我要做什么”
   还是
   “我要用什么实现做”？

3. ApprovedPlan 应该冻结什么？
   logical capability？
   provider？
   execution kind？

4. Runtime 到 STEP_READY 时，
   是否存在一个真正的 Provider 选择 seam？

5. DSL / Bounded Python：
   是两个 logical capability？
   还是同一个 logical capability 的两个 provider？

6. Retrieval / RuntimeBuiltin / Subprocess / Local vLLM：
   哪些应该成为 Execution Provider，
   哪些只是 Provider 内部依赖？

7. Provider 可不可用、risk、expressiveness、resource、
   replay、health、latency：
   哪些是硬 eligibility，
   哪些才允许进入 ranking？

8. Retry / Rebind / Fallback / Replan
   到底如何严格区分？

9. Provider 变化以后，
   ApprovedPlan hash 是否应该变化？

10. Provider 故障以后，
    Runtime 能否保持同一个 logical step，
    只重新绑定实现？

11. Memory / replay recipe
    应绑定 logical capability，
    还是 provider implementation？

12. 当前 benchmark 中 Planner 直接选 DSL/Python，
    如何迁移而不破坏现有 evidence？
```

---

# 1. Executive Summary

本轮最重要的源码结论：

> **当前 `CapabilityDescriptor` 不是纯 Logical Capability Descriptor。它已经把 Logical Semantics、Runtime Authority、Execution Implementation 三层揉在了一起。**

当前字段：

```text
capability_id
owner_role
description

input_ref_kinds
required_input_ref_kinds
input_contract_version

output_ref_kinds
output_contract_version

validator_ids
completion_criteria_contract

execution_kind
side_effect_class
max_runtime_ms
supports_replay

fallback_capability_id
```

其中前半部分更像：

```text
“这件事语义上是什么”
```

后半部分更像：

```text
“这件事由什么实现执行”
```

。

---

# 2. 当前最强的 Provider-Conflation 证据

`generic_adaptive_analysis_v2` 同时暴露：

```text
execute_analysis_dsl_v2

execute_bounded_python_v2
```

。

两者共享：

```text
input contract:
statebus.analysis_input.v2

output contract:
statebus.analysis_result.v2

validator set:
analysis_validator_ids
```

。

但不同：

```text
execution kind

risk

implementation expressiveness

runtime behavior
```

。

更关键的是：

```text
execute_analysis_dsl_v2
fallback →
execute_bounded_python_v2

execute_bounded_python_v2
fallback →
execute_analysis_dsl_v2
```

。

这已经不是普通：

```text
A capability fails → semantic fallback B
```

的形态。

它本质上更像：

```text
Logical Capability:
execute_analysis_v2

Providers:
    transform_dsl_v2
    bounded_python_bwrap_v2
```

。

---

# 3. 当前 Planner 正在选择 Provider

Planner 输入：

```python
"capability_surface":
    registry.public_view(...)
```

。

而 `public_view()` 当前包含：

```text
execution_kind
side_effect
fallback_capability_id
```

。

因此 Planner 直接看到：

```text
TRANSFORM_DSL

LLM_BOUNDED_PYTHON
```

并在 Plan 中输出：

```text
execute_analysis_dsl_v2
```

或：

```text
execute_bounded_python_v2
```

。

所以现在 Planner 并不只是在回答：

```text
“我要执行分析”
```

。

它还被迫回答：

```text
“我要用 DSL 还是 Python”
```

。

这正是 Batch-05 要拆开的核心。

---

# 4. Target 一句话

目标：

```text
Planner chooses WHAT

Runtime Binder chooses HOW
```

。

---

# 5. Target 主链

```text
Task
  ↓
Planner Capability Surface
  ↓
Logical Capability Plan
  ↓
PlanPolicy
  ↓
ApprovedPlan
  ↓
STEP_READY
  ↓
ExecutionBindingRequest
  ↓
ExecutionProviderRegistry
  +
ProviderRuntimeFacts
  ↓
Eligibility Filter
  ↓
Provider Ranking
  ↓
ExecutionBindingReceipt
  ↓
Provider-bound CapabilityGrant
  ↓
ProviderDispatcher
  ↓
ProtocolInvocationBinding
  ↓
Execution
```

。

---

# 6. Source Audit Map

本轮重点源码：

```text
statebus/contracts/adaptive.py

statebus/runtime/
    capability_registry.py
    domain_packs.py
    plan_policy.py
    adaptive_plan_compiler.py
    adaptive_mainline.py
    adaptive_runtime.py
    adaptive_dispatcher.py
    session.py

statebus/integrations/
    llm.py

statebus/benchmark/
    adaptive_formal_mainline.py
    backend_matrix.py

statebus/
    route_tool_catalog.py

tests/
    test_adaptive_capability_surface.py
    test_adaptive_codeact_integration.py
    test_adaptive_planner_policy.py
```

。

---

# 7. 当前 `ExecutionKind`

现在：

```python
class ExecutionKind(StrEnum):
    RUNTIME_BUILTIN
    RETRIEVAL_ADAPTER
    TRANSFORM_DSL
    LLM_BOUNDED_PYTHON
```

。

这个 enum 名字已经直接表明：

```text
它描述 execution implementation class
```

。

---

# 8. 但它被塞进 CapabilityDescriptor

当前：

```python
CapabilityDescriptor(
    ...
    execution_kind=...
)
```

。

因此：

```text
Capability ID
```

已经天然绑定：

```text
physical execution class
```

。

---

# 9. 当前 Dispatcher 更证明这一点

`AdaptiveCapabilityDispatcher`：

```python
self._handlers = {
    RETRIEVAL_ADAPTER: _dispatch_retrieval,
    TRANSFORM_DSL: _dispatch_transform_dsl,
    LLM_BOUNDED_PYTHON: _dispatch_llm_python,
    RUNTIME_BUILTIN: _dispatch_builtin,
}
```

。

Dispatch 过程：

```text
step.capability_id
    ↓
registry.get(capability_id)
    ↓
descriptor.execution_kind
    ↓
handler
```

。

所以当前：

```text
Capability ID
```

就是：

```text
Implementation Dispatch Key
```

的一部分。

---

# 10. 这造成三层 identity 混在一起

当前一个 Descriptor 同时承担：

```text
Semantic Interface Identity

Runtime Authority Identity

Implementation Dispatch Identity
```

。

Target 要拆成：

```text
LogicalCapabilityDescriptor

ExecutionProviderDescriptor

ExecutionBindingReceipt
```

。

---

# 11. 当前 Logical Fields

以下字段应该继续属于 Logical Capability：

```text
logical capability id/version

owner role

semantic purpose

input ref kinds

required input ref kinds

input contract

output contract

required output semantics

completion criteria contract

validator identities

allowed requirement feature vocabulary
```

。

---

# 12. 当前 Provider Fields

以下字段应迁移到 Provider：

```text
execution_kind

provider-specific risk class

max runtime

supports replay

physical prerequisites

sandbox requirement

local/remote

worker/runtime dependencies

provider readiness

cost/latency characteristics
```

。

---

# 13. `fallback_capability_id` 需要删除语义歧义

它当前可能表达：

```text
semantic fallback

implementation fallback

recovery fallback

downgrade fallback
```

。

一个字段承担四种意思。

这必须结束。

---

# 14. 当前 ApprovedPlan 的方向其实是正确的

`PlanStepProposal` 当前只有：

```text
capability_id
```

没有：

```text
provider_id
```

。

这对未来是好事。

只要把：

```text
capability_id
```

重新定义成：

```text
logical capability id
```

就可以保留 ApprovedPlan 的大部分结构。

---

# 15. ApprovedPlan 不应该绑定 Provider

冻结：

> **ApprovedPlan 应冻结语义计划，而不是某次具体执行实现。**

。

因此 Provider 变化：

```text
不应该改变 ApprovedPlan hash。
```

。

---

# 16. 当前 ApprovedPlan 为什么做不到

当前：

```text
ApprovedPlan
→ capability_registry_digest
```

。

但是当前 Registry digest 包含：

```text
execution_kind
side_effect
max_runtime
supports_replay
fallback
description
```

。

因此：

```text
provider implementation 变化
```

会改变：

```text
registry digest
```

进而影响：

```text
Plan identity
```

。

这是过度耦合。

---

# 17. Target Registry Split

必须拆成：

```text
LogicalCapabilityRegistry

ExecutionProviderRegistry
```

。

---

# 18. LogicalCapabilityRegistry

回答：

> “系统允许哪些语义能力？”

。

---

# 19. ExecutionProviderRegistry

回答：

> “当前系统安装了哪些具体执行实现？”

。

---

# 20. ProviderRuntimeFacts

回答：

> “这些实现现在能不能执行？”

。

三个问题不能由一个 Registry 回答。

---

# 21. 推荐 `LogicalCapabilityDescriptor`

```python
@dataclass(frozen=True)
class LogicalCapabilityDescriptor:
    capability_id: str
    version: str

    owner_role: str
    semantic_purpose: str

    input_ref_kinds: tuple[str, ...]
    required_input_ref_kinds: tuple[str, ...]
    input_contract_version: str

    output_ref_contracts: tuple[OutputRefContract, ...]
    output_contract_version: str

    completion_criteria_contract: dict[str, dict[str, object]]
    validator_ids: tuple[str, ...]

    allowed_requirement_features: tuple[str, ...]

    semantic_contract_hash: str
    schema_version: str
```

。

---

# 22. 为什么需要 `semantic_contract_hash`

因为仅比较：

```text
capability ID
```

不够。

仅比较：

```text
output contract
```

也不够。

Provider Rebind 必须证明：

```text
semantic contract
```

仍然完全相同。

---

# 23. Semantic Contract Hash 建议覆盖

```text
logical id/version

input contract

required input ref kinds

output contract

output ref cardinality

completion criteria semantics

validator set

allowed semantic requirement feature vocabulary
```

。

---

# 24. 不应该覆盖

```text
human description wording

provider availability

provider latency

provider version

worker PID

host/GPU

queue depth
```

。

---

# 25. 推荐 `OutputRefContract`

Batch-04 已经发现：

```text
success=True
output_refs=()
output_ref_kinds=()
```

存在 vacuous pass 风险。

因此 Logical Capability 应明确：

```python
@dataclass(frozen=True)
class OutputRefContract:
    ref_kind: str
    min_count: int
    max_count: int
```

。

例如：

```text
execute_analysis_v2

requires:
    execution_artifact ≥ 1

produces:
    execution_artifact exactly 1
```

。

---

# 26. 推荐 `ExecutionProviderDescriptor`

```python
@dataclass(frozen=True)
class ExecutionProviderDescriptor:
    provider_id: str
    version: str

    provider_kind: ExecutionKind

    supported_capabilities: tuple[CapabilitySupport, ...]

    supported_features: tuple[str, ...]

    side_effect_class: RiskClass
    max_runtime_ms: int
    supports_replay: bool

    prerequisites: tuple[str, ...]
    required_runtime_services: tuple[str, ...]

    verification_profile: tuple[str, ...]

    static_priority: int = 0

    schema_version: str = "statebus.execution_provider_descriptor.v1"
```

。

---

# 27. 推荐 `CapabilitySupport`

```python
@dataclass(frozen=True)
class CapabilitySupport:
    logical_capability_id: str
    logical_capability_version: str

    semantic_contract_hash: str

    input_contract_version: str
    output_contract_version: str

    supported_features: tuple[str, ...]
```

。

---

# 28. 为什么 Provider 不能只声明 Capability ID

假设：

```text
provider claims:
execute_analysis_v2
```

。

但它实际上输出：

```text
statebus.analysis_result.v1
```

而逻辑能力要求：

```text
statebus.analysis_result.v2
```

。

只用 ID：

```text
会误绑定。
```

。

---

# 29. 所以 Provider Registration 必须验证

```text
provider support.semantic_contract_hash

==

logical capability.semantic_contract_hash
```

。

---

# 30. Provider Registry Freeze

启动阶段：

```text
register logical capabilities

register providers

validate closure

freeze()
```

。

---

# 31. Provider Registry Closure Audit

至少检查：

```text
provider ID/version canonical

supported logical capability exists

semantic contract hash exact

input contract exact

output contract exact

required feature vocabulary valid

provider risk class valid

runtime limit > 0

required services known

no duplicate provider identity
```

。

---

# 32. 当前 Generic Analysis 是最适合的第一迁移对象

当前：

```text
execute_analysis_dsl_v2

execute_bounded_python_v2
```

。

Target：

```text
Logical:
execute_analysis_v2
```

。

---

# 33. Provider 1

```text
provider.transform_dsl.v2
```

。

特点：

```text
kind:
TRANSFORM_DSL

risk:
WORKSPACE_WRITE

features:
select
rename
filter
sort
group_aggregate
arithmetic_derive
period_compare
basic join?
...
```

。

---

# 34. Provider 2

```text
provider.bounded_python_bwrap.v2
```

。

特点：

```text
kind:
LLM_BOUNDED_PYTHON

risk:
BOUNDED_CODE

features:
custom_parse
pivot
cross_row_alignment
branch_recombine
imputation
custom_statistics
复杂 composition
...
```

。

---

# 35. 这不是“Python 更高级”

只是：

```text
expressiveness 不同

risk 不同

cost 不同

runtime prerequisites 不同
```

。

---

# 36. Provider 选择应由 Requirements 驱动

Plan Step 增加：

```text
required_features
```

。

---

# 37. Example

Planner 说：

```text
logical capability:
execute_analysis_v2

required_features:
    pivot
    cross_row_alignment
```

。

Binder：

```text
DSL:
does not support pivot
→ INELIGIBLE

Python:
supports pivot + cross_row_alignment
→ ELIGIBLE
```

。

---

# 38. Planner 不应该说

```text
use_python=true
```

。

---

# 39. Planner 不应该说

```text
execution_kind=LLM_BOUNDED_PYTHON
```

。

---

# 40. Planner 不应该说

```text
provider_id=bounded_python_bwrap
```

。

---

# 41. Required Feature Vocabulary 必须受控

不能让 Planner 任意写：

```text
"do whatever needed"
```

。

Logical Capability 声明：

```text
allowed_requirement_features
```

。

PlanPolicy：

```text
requested required_features
⊆ allowed feature vocabulary
```

。

否则 reject。

---

# 42. 第一版 Feature Vocabulary

Generic analysis 可以先：

```text
select

rename

filter

sort

aggregate

group_aggregate

derive_difference

derive_ratio

derive_percentage

period_compare

join

pivot

custom_parse

cross_row_alignment

branch_recombine

imputation

outlier_handling

custom_statistics
```

。

---

# 43. 不要一开始做 ontology

Feature 只是：

```text
provider expressiveness eligibility
```

。

不是：

```text
新的 DSL language
```

。

---

# 44. Feature 的来源

Planner 从：

```text
任务语义
```

声明：

```text
需要哪些能力性质
```

。

Provider 声明：

```text
自己能支持哪些
```

。

Binder 比较：

```text
required ⊆ supported
```

。

---

# 45. 这比 Planner 选 DSL/Python 更正确

因为 Planner 不需要知道：

```text
系统当前安装了什么实现
```

。

---

# 46. Provider Availability 是 Runtime Fact

当前源码中很多 provider readiness 问题是 dispatch 后才发现。

例如：

```text
retrieval_handler_not_registered

transform_program_handler_not_registered

llm_python_handler_not_registered

runtime_builtin_handler_not_registered
```

。

---

# 47. 这些不是业务执行失败

它们本质是：

```text
Provider not ready
```

。

应该在：

```text
grant 前
```

发现。

---

# 48. Target

```text
ProviderRuntimeFacts
```

。

---

# 49. 推荐 `ProviderStatus`

```text
READY

DEGRADED

UNAVAILABLE

UNKNOWN
```

。

后续 Reliability Batch 再加：

```text
EJECTED
```

。

---

# 50. 推荐 `ProviderRuntimeFacts`

```python
@dataclass(frozen=True)
class ProviderRuntimeFacts:
    provider_id: str
    provider_version: str

    status: str

    reason_codes: tuple[str, ...]

    available_prerequisites: tuple[str, ...]
    dependency_identity_hashes: tuple[str, ...]

    observed_at_ns: int

    resource_snapshot_hash: str

    ema_latency_ms: float | None = None
    recent_success_rate: float | None = None

    schema_version: str = "statebus.provider_runtime_facts.v1"
```

。

---

# 51. R0-R2 不需要真正 EMA

第一版只需要：

```text
READY / UNAVAILABLE
reason code
dependency identity
facts digest
```

。

---

# 52. 为什么 Dynamic Facts 不能进入 Provider Registry Digest

如果：

```text
provider health
```

进入 static registry hash：

```text
一次健康检查变化
→ Provider Registry Digest 变化
→ 所有 Binding identity 重算
```

。

不合理。

---

# 53. 所以三个 Digest

```text
LogicalCapabilityRegistryDigest

ExecutionProviderRegistryDigest

ProviderRuntimeFactsDigest
```

必须分开。

---

# 54. ApprovedPlan 绑定什么

只绑定：

```text
LogicalCapabilityRegistryDigest
```

。

---

# 55. ExecutionBindingReceipt 绑定什么

绑定：

```text
ExecutionProviderRegistryDigest

ProviderRuntimeFactsDigest

BindingPolicyVersion
```

。

---

# 56. CapabilityGrant 绑定什么

绑定：

```text
ApprovedPlan hash

ExecutionBindingReceipt hash

provider ID/version

logical capability ID/version
```

。

---

# 57. 推荐 `ExecutionBindingRequest`

```python
@dataclass(frozen=True)
class ExecutionBindingRequest:
    task_id: str
    step_id: str
    attempt_id: str

    approved_plan_hash: str

    logical_capability_id: str
    logical_capability_version: str
    semantic_contract_hash: str

    input_ref_ids: tuple[str, ...]
    input_ref_kinds: tuple[str, ...]

    required_features: tuple[str, ...]

    risk_ceiling: RiskClass

    runtime_budget_remaining_ms: int

    requested_replay_policy: str

    schema_version: str = "statebus.execution_binding_request.v1"
```

。

---

# 58. Binder Authority

Binder 不允许改变：

```text
step goal

logical capability

dependencies

input authority

output contract

completion criteria

required features
```

。

---

# 59. Binder 只允许决定

```text
provider
```

。

---

# 60. Provider Eligibility

冻结：

```text
Authority
∧
Contract
∧
Expressiveness
∧
ResourceAvailable
∧
RiskAllowed
∧
QualityCapable
∧
RuntimePolicyAllowed
```

。

---

# 61. Eligibility 必须先于 Ranking

这是整个 Batch-05 最重要的执行原则之一。

---

# 62. Hard Filter 1 — Authority

Provider 必须：

```text
显式注册支持 logical capability
```

。

不能：

```text
“反正也是 Python，试试看”
```

。

---

# 63. Hard Filter 2 — Contract

必须：

```text
semantic contract exact

input contract compatible

output contract exact
```

。

---

# 64. Hard Filter 3 — Expressiveness

```text
required_features
⊆
provider.supported_features
```

。

---

# 65. Hard Filter 4 — Resource / Prerequisite

例如 Python Provider：

```text
bwrap ready

code generation LLM ready

workspace available

required sandbox identity ready
```

。

否则：

```text
UNAVAILABLE
```

。

---

# 66. Hard Filter 5 — Risk

例如：

```text
Task Envelope:
risk ≤ WORKSPACE_WRITE
```

。

那么：

```text
BOUNDED_CODE provider
```

必须直接淘汰。

---

# 67. 分数不能补偿风险

不允许：

```text
Python provider latency 非常低
所以虽然 risk 超限
还是选 Python
```

。

Hard constraints：

```text
cannot be scored back in.
```

。

---

# 68. Hard Filter 6 — Quality Capability

Provider 必须能满足：

```text
Logical validator profile

completion criteria
```

。

不能：

```text
“输出格式差不多”
```

。

---

# 69. QualityCapable ≠ 当前 success rate

第一版：

```text
provider has the required validator-compatible execution profile
```

。

后续 Reliability：

```text
recent quality rate
```

可以成为 dynamic fact。

---

# 70. Hard Filter 7 — Runtime Policy

例如：

```text
LLM Python disabled

exact replay disallowed

remote network provider disallowed
```

。

都应该在 eligibility 直接 filter。

---

# 71. Ranking 才考虑什么

硬过滤后才考虑：

```text
risk preference

determinism

locality

estimated latency

expected token cost

replay warmness

recent reliability

queue/load

static preference
```

。

---

# 72. 第一版不要复杂权重模型

推荐：

```text
lexicographic ranking
```

。

例如：

```text
1. lower risk class
2. deterministic implementation preferred
3. READY over DEGRADED
4. lower estimated runtime
5. replay available
6. stable provider_id tie-break
```

。

---

# 73. 为什么先 lexicographic

因为现在：

```text
数据不足

provider 数很少

权重没有校准 evidence
```

。

直接：

```text
0.31 latency + 0.27 risk + ...
```

会显得假。

---

# 74. 后续才做 Cost Model

如果以后有：

```text
多 provider
足够 telemetry
```

再：

```text
score =
w_latency * ...
+
w_cost * ...
+
w_reliability * ...
```

。

---

# 75. External Pattern — Kubernetes

Kubernetes scheduler 明确：

```text
Filter
    ↓
Score
    ↓
Reserve / Permit / PreBind
    ↓
Bind
```

。

只给：

```text
通过 filtering
```

的节点打分。

---

# 76. StateBus 对应

```text
Eligibility Filter
    ↓
Provider Score
    ↓
ExecutionBindingReceipt
    ↓
CapabilityGrant
```

。

---

# 77. 为什么 Receipt 对应 Bind/Allocation Plan

因为选择 Provider 之后：

```text
不能只返回 provider_id
```

。

必须记录：

```text
为什么它合法

哪些候选被拒绝

依据的是哪个 runtime facts snapshot

是哪一版 policy
```

。

---

# 78. External Pattern — Nomad

Nomad placement 分：

```text
feasibility checking

ranking
```

。

Feasibility 会直接排除：

```text
unhealthy node

missing driver

constraint failure
```

。

这正好对应当前 StateBus 的：

```text
handler_not_registered
bwrap_not_ready
runtime dependency missing
```

。

---

# 79. 当前这些错误位置太晚

现在很多情况是：

```text
CapabilityGrant 已发
STEP_DISPATCHED 已记录
handler 才说 unavailable
```

。

Target：

```text
Provider unavailable
→ candidate filtered
→ 不发 grant
```

。

---

# 80. 这样 telemetry 更真实

不会把：

```text
“根本没能启动 provider”
```

记成：

```text
“业务 step 执行失败”
```

。

---

# 81. External Pattern — Envoy

Envoy 区分：

```text
static cluster membership/config

dynamic health/outlier state

load balancing decision
```

。

。

---

# 82. StateBus 对应

```text
ExecutionProviderDescriptor
    static

ProviderRuntimeFacts
    dynamic

ExecutionBindingReceipt
    decision snapshot
```

。

---

# 83. Provider Unavailable 不应修改 Registry

例如：

```text
bwrap 临时不可用
```

不是：

```text
provider definition消失
```

。

而是：

```text
ProviderRuntimeFacts.status=UNAVAILABLE
```

。

---

# 84. External Pattern — Ray Serve LLM

Ray 当前明确区分：

```text
Ingress/model-level routing

Request/replica-level routing
```

。

这非常适合用来防止 StateBus 把所有 routing 混在一起。

---

# 85. StateBus 应有三层 routing

```text
1. Logical Capability Routing
   “做什么”

2. Execution Provider Binding
   “用哪个实现做”

3. Backend Replica / Endpoint Routing
   “这个实现里的哪一个 replica”
```

。

---

# 86. StateBus Batch-05 只负责前两层中的第二层

第三层：

```text
vLLM

Ray Serve

OpenAI-compatible backend

future provider runtime
```

自己处理即可。

---

# 87. 不要把每个 LLM endpoint 都注册成 StateBus Execution Provider

例如：

```text
bounded_python_bwrap provider
```

内部可能调用：

```text
local_vllm Qwen
```

。

StateBus 第一版只需要知道：

```text
这个 Provider 的依赖 identity / readiness
```

。

不需要再做：

```text
provider inside provider inside provider
```

。

---

# 88. 当前 `statebus.integrations.llm.ProviderConfig`

源码已经有一个名为：

```python
ProviderConfig
```

。

它表示：

```text
LLM backend config
```

。

不是本轮：

```text
Execution Provider
```

。

---

# 89. 命名必须避免冲突

本轮统一使用：

```text
ExecutionProviderDescriptor

ExecutionProviderRegistry

ProviderRuntimeFacts
```

。

必要时未来再把：

```text
ProviderConfig
```

改名：

```text
LLMProviderConfig
```

。

不是当前 P0。

---

# 90. External Pattern — WebAssembly Component Model

WIT 明确：

```text
interface/world
只定义 contract

implementation
在 component 内部
```

。

这正是 StateBus 当前缺失的抽象。

---

# 91. StateBus Logical Capability 应像 Interface

回答：

```text
输入是什么

输出是什么

语义是什么

要求什么验证
```

。

---

# 92. Provider 应像 Component Implementation

回答：

```text
我如何实现这个 interface

需要哪些 runtime dependency

风险是什么

资源是什么
```

。

---

# 93. 两者 composition 的条件

不是：

```text
名字看起来一样
```

。

而是：

```text
semantic contract exact match
```

。

---

# 94. Provider Equivalence Rule

两个 Provider 只有同时满足：

```text
same logical capability id/version

same semantic_contract_hash

same input contract

same output contract

same validator semantics

same completion criteria semantics

same required-feature semantics
```

才能成为：

```text
rebind alternatives
```

。

---

# 95. Output Contract 相同不够

例如：

```text
两个 capability
都输出 execution_artifact
```

不代表：

```text
语义相同。
```

。

---

# 96. Retrieval 不应该被错误合并

当前：

```text
retrieve_semantic_evidence_v1

retrieve_table_evidence_v1
```

虽然都：

```text
execution_kind=RETRIEVAL_ADAPTER
```

但语义不同。

---

# 97. 它们更可能仍是两个 Logical Capability

```text
retrieve_semantic_evidence_v1

retrieve_table_evidence_v1
```

。

然后同一个 provider：

```text
provider.retrieval_adapter.v1
```

可以声明支持两个。

---

# 98. 为什么

因为 Planner 的语义选择：

```text
要 narrative evidence

还是 structured table evidence
```

本来就可能是合理的 Plan choice。

---

# 99. Summarizer 也不能因为都是 RUNTIME_BUILTIN 就合并

例如：

```text
compose_cited_report

compose_comparison_report

compose_risk_memo
```

。

这些输出的：

```text
semantic purpose
```

不同。

---

# 100. Provider 抽象不能“过度归并”

第一版原则：

> **只有强 equivalence evidence 才合并成一个 logical capability 的多个 provider。**

。

---

# 101. Migration Candidate Matrix

| Current capability | Target logical | Provider | 判断 |
|---|---|---|---|
| `execute_analysis_dsl_v2` | `execute_analysis_v2` | `transform_dsl_v2` | **强确定** |
| `execute_bounded_python_v2` | `execute_analysis_v2` | `bounded_python_bwrap_v2` | **强确定** |
| `compare_periods_v1` | `compare_periods_v1` | `transform_dsl_v2` | **强候选** |
| `compare_periods_python_v1` | `compare_periods_v1` | `bounded_python_bwrap_v2` | **强候选** |
| `aggregate_metrics_v1` | `aggregate_metrics_v1` | `transform_dsl_v2` | **强候选** |
| `aggregate_metrics_python_v1` | `aggregate_metrics_v1` | `bounded_python_bwrap_v2` | **强候选** |
| `detect_anomaly_v1` | `detect_anomaly_v1` | `transform_dsl_v2` | **强候选** |
| `detect_anomaly_python_v1` | `detect_anomaly_v1` | `bounded_python_bwrap_v2` | **强候选** |
| `extract_metric_series_v1` | TBD | DSL | **暂不自动合并** |
| `bounded_metric_python_v1` | TBD | Python | **暂不自动合并** |
| `retrieve_semantic_evidence_v1` | same | retrieval adapter | **logical 保留** |
| `retrieve_table_evidence_v1` | same | retrieval adapter | **logical 保留** |
| `compose_*` | mostly same | runtime builtin / future LLM | **logical 保留** |

---

# 102. 为什么 `extract_metric_series_v1` 暂不自动和 `bounded_metric_python_v1` 合并

虽然：

```text
输出/validator
部分接近
```

但是当前：

```text
input contract
```

不完全相同。

---

# 103. Provider Equivalence 不能靠“感觉”

必须先：

```text
统一 logical input contract
```

并证明：

```text
same semantic contract
```

。

否则：

```text
保持两个 logical capabilities
```

更安全。

---

# 104. 当前 `fallback_capability_id` 的问题更严重

例如 deterministic DSL capability：

```text
compare_periods_v1
→ fallback extract_metric_series_v1
```

。

但：

```text
compare_periods
```

和：

```text
extract_metric_series
```

明显不是同一语义。

---

# 105. 所以这种 edge 绝不能迁移成 Rebind

它最多是：

```text
semantic recovery
```

。

如果真的需要：

```text
REQUEST_REPLAN
```

。

---

# 106. 当前 Generic DSL/Python 的 mutual fallback cycle

这反过来很说明问题。

两者：

```text
语义合同高度一致
```

却被写成：

```text
A fallback B
B fallback A
```

。

这正是：

```text
Provider alternatives
```

被错误建模为：

```text
Capability fallback graph
```

。

---

# 107. Target Recovery Taxonomy

核心动作只保留：

```text
RETRY_PROVIDER

REBIND_PROVIDER

REQUEST_REPLAN

FAIL
```

。

---

# 108. Retry 定义

```text
same logical capability

same provider

new attempt
```

。

---

# 109. Retry 适合

例如：

```text
transient HTTP timeout

temporary worker startup failure

retryable provider internal error
```

且 policy 允许。

---

# 110. Rebind 定义

```text
same logical capability

same semantic contract

same step

same goal

same dependencies

same input authority

same output contract

same completion criteria

same required features

different provider

fresh binding receipt

fresh grant

new attempt
```

。

---

# 111. Rebind 不允许

```text
修改 Plan
```

。

---

# 112. Rebind 后

```text
ApprovedPlan hash
必须保持不变
```

。

---

# 113. Rebind 后必须变化

```text
attempt ID

ExecutionBindingReceipt hash

provider ID

CapabilityGrant hash
```

。

---

# 114. Replan 定义

只要改变：

```text
logical capability

semantic goal

output contract

required semantics

dependency graph

role

semantic stage
```

就是：

```text
REPLAN
```

。

---

# 115. 不能用 Rebind 偷改语义

例如：

```text
compare_periods
失败
```

转：

```text
extract_metric_series
```

这是：

```text
semantic change
```

。

必须：

```text
replan
```

。

---

# 116. “Fallback” 最终只保留为人类总称

Telemetry / policy 不再用：

```text
fallback
```

做核心 machine action。

---

# 117. Current Runtime Recovery Branch

当前只有：

```text
LLM_BOUNDED_PYTHON
+
on_failure=fallback_deterministic
+
fallback_capability_id
```

触发 fresh fallback grant。

---

# 118. 这条实现有一个好性质

它已经证明：

```text
recovery
必须 fresh grant
```

。

这个 invariant 要保留。

---

# 119. 现有测试也已经冻结这一点

`test_python_failure_falls_back_only_with_a_fresh_dsl_grant`

会验证：

```text
fallback provider/capability
使用不同 grant hash
```

。

---

# 120. Batch-05 迁移应该保留测试精神

只是从：

```text
fresh fallback capability grant
```

变成：

```text
fresh provider-bound grant after rebind
```

。

---

# 121. Rebind Failure Taxonomy

需要先定义哪些失败允许 Rebind。

---

# 122. Pre-dispatch Rebindable

强适合：

```text
provider unavailable

provider handler missing

sandbox unavailable

required runtime service unavailable

worker process unavailable

provider health degraded beyond policy

provider capacity unavailable
```

。

---

# 123. Transport Rebindable

通常可：

```text
connect failure

worker startup failure

provider timeout

provider crash

protocol-level provider unavailable
```

。

但需要 bounded attempt。

---

# 124. Execution Result Rebindable

更谨慎。

可能：

```text
provider-specific execution failure
```

。

例如：

```text
DSL program cannot express a permitted feature
```

如果事前 expressiveness metadata 不完整。

---

# 125. Validator Failure 是否 Rebind

第一版建议：

```text
默认不自动无限 rebind。
```

。

可支持：

```text
single alternative-provider attempt
```

仅当：

```text
same logical contract
provider-specific output validation failure
policy explicitly allows
```

。

---

# 126. 为什么

否则：

```text
模型质量差
→ 自动切 provider
→ 再失败
→ 再切
```

容易变成：

```text
hidden search loop
```

。

---

# 127. Non-Rebindable

```text
logical input contract mismatch

unauthorized ref

risk violation

required feature unknown

no provider supports required feature

output contract semantic mismatch

plan dependency problem

task contract problem

semantic evidence insufficiency
```

。

这些应：

```text
FAIL
```

或：

```text
REQUEST_REPLAN
```

。

---

# 128. Risk Downgrade / Escalation

Provider Rebind 不允许：

```text
偷偷提升 risk ceiling
```

。

---

# 129. Example

Task：

```text
risk ceiling = WORKSPACE_WRITE
```

。

DSL unavailable。

Python：

```text
risk = BOUNDED_CODE
```

。

结果：

```text
Python INELIGIBLE
```

。

---

# 130. 不能因为 DSL unavailable 就自动执行 Python

正确：

```text
no eligible provider
→ fail / request replan
```

。

---

# 131. Planner Feature + Risk Example

Task 需要：

```text
pivot
```

。

DSL：

```text
不支持 pivot
```

。

Python：

```text
支持 pivot
```

。

---

# 132. 如果 Risk=B0UNDED_CODE

```text
Python eligible
→ select Python
```

。

---

# 133. 如果 Risk=WORKSPACE_WRITE

```text
DSL expressiveness fail

Python risk fail

→ no eligible provider
```

。

这正是正确的 fail-closed。

---

# 134. 推荐 `ExecutionBindingReceipt`

这是 Batch-05 的核心证据对象。

---

# 135. 不能只保存 `selected_provider_id`

必须保存：

```text
candidate set

hard rejection reasons

eligible set

selection rationale

policy version

runtime facts snapshot
```

。

---

# 136. 推荐结构

```python
@dataclass(frozen=True)
class ExecutionBindingReceipt:
    binding_id: str

    task_id: str
    step_id: str
    attempt_id: str

    approved_plan_hash: str

    logical_capability_id: str
    logical_capability_version: str
    semantic_contract_hash: str

    provider_registry_digest: str
    provider_runtime_facts_digest: str
    binding_policy_version: str

    candidate_provider_ids: tuple[str, ...]

    rejected_candidates: tuple[ProviderRejection, ...]
    eligible_provider_ids: tuple[str, ...]

    selected_provider_id: str
    selected_provider_version: str
    selected_provider_kind: str

    selection_rank: tuple[object, ...]

    supersedes_binding_hash: str = ""
    rebind_reason_code: str = ""

    schema_version: str = "statebus.execution_binding_receipt.v1"
```

。

---

# 137. 推荐 `ProviderRejection`

```python
ProviderRejection(
    provider_id,
    reason_codes,
)
```

。

---

# 138. Reason Code 必须 machine-readable

例如：

```text
CAPABILITY_NOT_SUPPORTED

SEMANTIC_CONTRACT_MISMATCH

INPUT_CONTRACT_MISMATCH

OUTPUT_CONTRACT_MISMATCH

FEATURE_UNSUPPORTED

RISK_EXCEEDED

PROVIDER_NOT_READY

DEPENDENCY_UNAVAILABLE

RUNTIME_BUDGET_EXCEEDED

REPLAY_POLICY_UNSUPPORTED
```

。

---

# 139. 不要只写 human rationale

因为实验要统计：

```text
为什么 Provider 被过滤
```

。

---

# 140. Receipt 是 Binding Truth

最终可以证明：

```text
为什么选择 DSL

为什么没选择 Python

或者

为什么第一次选 DSL，
失败后合法 rebind Python
```

。

---

# 141. Receipt 不应包含 Secret

不要放：

```text
API key

raw endpoint token

private socket credential

完整 sensitive env
```

。

只放：

```text
identity hash / reason code
```

。

Security Final Pass 再强化。

---

# 142. Provider-bound CapabilityGrant

当前 Grant：

```text
capability_id
capability_version
...
```

。

Target 增加：

```text
logical_capability_id

logical_capability_version

provider_id

provider_version

execution_binding_hash

provider_registry_digest
```

。

---

# 143. Compatibility Migration

第一阶段可以保留：

```text
capability_id
```

作为 logical alias。

不要一次性破坏所有调用点。

---

# 144. Grant 必须继续 One Attempt

每次：

```text
retry

rebind
```

都 fresh grant。

---

# 145. Rebind 绝不能复用旧 Grant

因为旧 Grant 绑定：

```text
provider A
```

。

使用它执行 Provider B：

```text
authority invalid
```

。

---

# 146. Provider Binding 在 Runtime 哪里发生

正确 seam：

```text
STEP_READY
```

之后。

---

# 147. 为什么不是 Planner 前

Provider availability：

```text
可能变化
```

。

Planner 时选 Provider 会过早。

---

# 148. 为什么不是 Plan Compiler

`adaptive_plan_compiler.py` 已明确：

```text
不选择 capability

不加 semantic stage

只补 typed dependencies
```

。

这条 boundary 应保留。

---

# 149. Provider Binding 也不应该放 Compiler

因为它依赖：

```text
runtime readiness

resource state

provider health

current replay availability
```

。

---

# 150. 推荐 Runtime Chain

```text
ready step
    ↓
logical descriptor
    ↓
input refs resolved
    ↓
ExecutionBindingRequest
    ↓
ExecutionBindingPolicy.bind()
    ↓
BindingReceipt
    ↓
provider-bound Grant
    ↓
ProviderDispatcher
```

。

---

# 151. 当前 Runtime 顺序需要调整

现在：

```text
ready

descriptor = registry.get(capability)

input validation

issue grant

dispatch handler
```

。

---

# 152. Target

```text
ready

logical descriptor

input authority validation

binding

provider-specific max runtime / prerequisites

issue provider-bound grant

dispatch provider
```

。

---

# 153. Runtime Budget 的归属

当前：

```text
descriptor.max_runtime_ms
```

属于 CapabilityDescriptor。

但同一个 logical capability 的：

```text
DSL
Python
```

可能 runtime budget 不同。

所以：

```text
provider max_runtime_ms
```

迁移到 Provider。

---

# 154. Logical Capability 仍可以有 Semantic Budget Ceiling

例如：

```text
task envelope max execution runtime
```

。

最终 Grant：

```text
min(
task remaining budget,
logical policy budget,
provider max runtime
)
```

。

---

# 155. Provider-specific Risk

同一逻辑能力：

```text
DSL = workspace write

Python = bounded code
```

。

这直接证明：

```text
risk
```

不能只属于 Logical Capability。

---

# 156. Logical Capability 是否完全没有 Risk

可以有：

```text
minimum semantic side-effect class
```

或者：

```text
allowed provider risk ceiling
```

。

但第一版可以简化：

```text
Task Envelope 给 ceiling

Provider 声明 actual risk
```

。

---

# 157. Replay Support 的归属

当前：

```text
supports_replay
```

在 CapabilityDescriptor。

但 replay 能力很可能 provider-specific。

---

# 158. Example

同一 logical analysis：

```text
DSL provider:
可 replay program

Python provider:
可 replay source only if sandbox/version same
```

。

所以：

```text
supports_replay
```

应迁到 Provider。

---

# 159. Memory Compatibility 要一起修

当前 memory recipe `_validated_recipe()` 会比较：

```text
execution_kind

capability_id

output_contract_version
```

。

。

---

# 160. 当前这相当于

```text
Logical identity
+
Implementation identity
```

混在一个 recipe gate。

---

# 161. Target Memory Split

Provider-neutral Memory：

```text
logical capability

semantic contract

output contract

validator digest
```

。

---

# 162. Provider-specific Execution Recipe

绑定：

```text
provider ID/version

provider config digest

execution program/source identity

sandbox/runtime identity
```

。

---

# 163. 例如 DSL Replay

Recipe：

```text
logical:
execute_analysis_v2

provider:
transform_dsl_v2

program hash
```

。

---

# 164. Python Replay

Recipe：

```text
logical:
execute_analysis_v2

provider:
bounded_python_bwrap_v2

source hash

sandbox policy digest

LLM generation provenance
```

。

---

# 165. Provider unavailable 不应让 logical memory invalid

如果：

```text
Python provider down
```

。

过去产生的：

```text
logical validated artifact memory
```

仍可用于：

```text
assist / semantic matching
```

。

---

# 166. 只有 Provider-specific replay recipe

可能因为：

```text
provider version mismatch
```

不可 replay。

---

# 167. Replay Availability 可以进入 Provider Ranking

如果：

```text
同样两个 provider eligible
```

Provider A：

```text
有 validated replay recipe
```

Provider B：

```text
cold
```

。

那么：

```text
A
```

可以获得软优先级。

---

# 168. 但是 Replay 不能覆盖 Hard Constraints

例如：

```text
Provider A replay 很快
但 risk 超限
```

。

仍：

```text
INELIGIBLE
```

。

---

# 169. Provider Readiness Probe

第一阶段可以由：

```text
AdaptiveMainline assembly
```

构造。

---

# 170. DSL Provider Readiness

检查：

```text
transform_program_factory registered

transform interpreter available

validator registry ready
```

。

---

# 171. Python Provider Readiness

检查：

```text
code_policy_factory

code_source_factory or valid replay

bwrap readiness

codeact runner

required LLM backend configuration
```

。

---

# 172. Retrieval Provider Readiness

检查：

```text
retrieval_adapter

retrieval_request_factory

required corpus registration
```

。

---

# 173. Runtime Builtin Provider

检查：

```text
handler registered
```

。

---

# 174. 当前这些检查发生在 Dispatcher

建议逐步前移到：

```text
ProviderRuntimeFactBuilder
```

。

---

# 175. Dispatcher 最终应该做什么

不是：

```text
“根据 capability.execution_kind 猜 handler”
```

。

而是：

```text
根据 ExecutionBindingReceipt.selected_provider_id
找到已注册 provider executor
```

。

---

# 176. 推荐 Provider Dispatcher

```python
class ExecutionProviderDispatcher:
    providers: dict[str, ProviderExecutor]

    def dispatch(binding, grant, ...):
        executor = providers[binding.selected_provider_id]
        ...
```

。

---

# 177. `ExecutionKind` 可以保留

它作为：

```text
provider implementation category
```

仍然有用。

---

# 178. 但不再 Planner-visible

Planner 不需要看到：

```text
TRANSFORM_DSL

LLM_BOUNDED_PYTHON
```

。

---

# 179. Planner Public View Target

例如：

```json
{
  "id": "execute_analysis_v2",
  "role": "executor",
  "description": "Execute a verified analysis over approved artifacts.",
  "accepts": [
    "execution_artifact",
    "canonical_evidence_pack"
  ],
  "requires": [
    "execution_artifact"
  ],
  "produces": [
    "execution_artifact"
  ],
  "output_contract": "statebus.analysis_result.v2",
  "requirement_features": [
    "filter",
    "aggregate",
    "pivot",
    "custom_parse",
    "cross_row_alignment"
  ],
  "completion_criteria": {
    "min_rows": "...",
    "required_fields": "..."
  }
}
```

。

---

# 180. 不包含

```text
provider id

execution kind

bwrap

local_vllm

socket

runtime handler

provider latency

provider health
```

。

---

# 181. Planner 仍可表达“需要复杂处理”

通过：

```text
required_features
```

。

不是：

```text
选 Python
```

。

---

# 182. Formal Benchmark 需要迁移

当前 Formal Planner 会看到：

```text
execute_analysis_dsl_v2

execute_bounded_python_v2
```

。

并且 benchmark logic 还会检查：

```text
Planner 是否选了其中之一
```

。

---

# 183. 这是当前 evidence 的一部分

不能直接改完然后：

```text
旧结果继续声称可比
```

。

---

# 184. 推荐 Benchmark Migration

分阶段。

---

# PB-R0 — Provider Boundary Inventory

不改 behavior。

建立：

```text
LegacyCapabilityBindingMap
```

。

---

# 185. R0 Mapping

例如：

```text
execute_analysis_dsl_v2
    ↓
logical execute_analysis_v2
provider transform_dsl_v2

execute_bounded_python_v2
    ↓
logical execute_analysis_v2
provider bounded_python_bwrap_v2
```

。

---

# 186. R0 只做审计

现有：

```text
Planner
Plan
Dispatcher
```

不变。

额外记录：

```text
legacy capability
对应的 logical/provider identity
```

。

---

# PB-R1 — Shadow Binding Receipt

仍让 Planner 输出旧 capability。

Runtime：

```text
根据 legacy map
构造 BindingRequest
```

。

Binder：

```text
observe mode
```

。

---

# 187. R1 必须强制选回当前 provider

例如 Planner 选：

```text
execute_analysis_dsl_v2
```

。

Shadow binder：

```text
selected_provider =
transform_dsl_v2
```

。

不能改变执行路径。

---

# 188. R1 目的

验证：

```text
BindingReceipt

candidate set

filter reasons

digest

telemetry
```

。

而不是先追求优化。

---

# PB-R2 — Logical Planner Surface

Planner 只看到：

```text
execute_analysis_v2
```

。

Plan Step 增加：

```text
required_features
```

。

---

# 189. R2 才是真正架构切换

Binder：

```text
根据 provider eligibility
选择 DSL/Python
```

。

---

# PB-R3 — Provider-bound Grant / Dispatcher

把：

```text
execution_kind
```

从 Logical Descriptor 移到 Provider Descriptor。

---

# 190. Runtime Grant 增加

```text
provider_id

provider_version

execution_binding_hash
```

。

---

# 191. Dispatcher 改成 Provider ID dispatch

不再：

```text
descriptor.execution_kind
```

决定实现。

---

# PB-R4 — Recovery Taxonomy

替换：

```text
fallback_deterministic
```

核心逻辑。

---

# 192. Step Failure Policy Target

例如：

```text
on_failure:
    retry_provider
    rebind_provider
    request_replan
    fail
```

。

---

# 193. 也可以组合

更规范：

```python
RecoveryPolicy(
    allow_retry=True,
    max_provider_retries=1,

    allow_rebind=True,
    max_rebinds=1,

    allow_replan=True,
)
```

。

Planner 不控制 hard limits。

---

# PB-R5 — Runtime Facts / Readiness

把当前：

```text
*_handler_not_registered
```

逐步变成：

```text
provider filtered before grant
```

。

---

# PB-R6 — Evidence / Experiments

建立：

```text
same logical plan
different provider

same ApprovedPlan hash
different BindingReceipt
```

证据。

---

# 194. 可选 PB-R7

后面才考虑：

```text
health

EMA

outlier

cost model

multi-provider balancing
```

。

这已经接近 Scheduler/Reliability Batch，

不要提前。

---

# 195. Provider Selection First Policy

推荐第一版：

```text
Filter first

then deterministic rank
```

。

---

# 196. 示例：Simple Analysis

Required features：

```text
select
aggregate
```

。

Providers：

```text
DSL:
eligible
risk=WORKSPACE_WRITE

Python:
eligible
risk=BOUNDED_CODE
```

。

如果 Task 允许 BOUNDED_CODE：

```text
两者都 eligible
```

。

Ranking：

```text
lower risk
+
deterministic
```

因此：

```text
DSL wins
```

。

---

# 197. 示例：Pivot

Required：

```text
pivot
```

。

DSL：

```text
FEATURE_UNSUPPORTED
```

。

Python：

```text
eligible
```

。

选择 Python。

---

# 198. 示例：Pivot + Risk Ceiling Low

Task：

```text
risk = WORKSPACE_WRITE
```

。

DSL：

```text
feature fail
```

。

Python：

```text
risk fail
```

。

Result：

```text
NO_ELIGIBLE_PROVIDER
```

。

---

# 199. 这比当前 Planner 直接选 Python 更可靠

因为当前 Planner 可能：

```text
看到 Python
觉得适合
```

但：

```text
risk policy
```

再 reject。

Target 则：

```text
Plan 表达语义需求

Runtime 根据当前 authorized provider
做实现决定
```

。

---

# 200. Provider Ranking 是否应该看 Task Semantic Text

第一版：

```text
不应该。
```

。

---

# 201. 为什么

Task Semantic Text 已经被 Planner 转换为：

```text
logical capability

required features

completion criteria
```

。

Binder 再读自然语言：

```text
会形成第二个 semantic router
```

。

---

# 202. 所以 Binder Context 应结构化

```text
Logical capability

Feature requirements

Risk ceiling

Runtime facts

Resource facts

Replay facts

Budget
```

。

---

# 203. Binder 不是 Agent

不需要：

```text
LLM provider selector
```

。

第一版应：

```text
deterministic policy
```

。

---

# 204. 为什么

Provider binding 是：

```text
authorization + systems placement
```

。

不适合再放一个不稳定 LLM。

---

# 205. Provider Binder 也不是 Planner

不要：

```text
重新解释 user task
```

。

---

# 206. Provider Binder 更像 Scheduler Placement

这也是 Kubernetes/Nomad 类比最有价值的地方。

---

# 207. Binding Policy Version

每个 Receipt 必须记录：

```text
binding_policy_version
```

。

例如：

```text
statebus.execution_binding_policy.v1
```

。

---

# 208. Binding Policy Determinism

相同：

```text
BindingRequest

ProviderRegistry

RuntimeFacts
```

应该产生相同：

```text
selected provider
```

。

---

# 209. Runtime Facts 有 timestamp 会不会破坏 determinism

Canonical decision 输入可以绑定：

```text
facts digest
```

。

同一个 snapshot：

```text
deterministic
```

。

不同 snapshot：

```text
允许不同 selection
```

。

---

# 210. 为什么 Receipt 必须带 Facts Digest

否则后来只看到：

```text
为什么上次选 DSL
这次选 Python？
```

无法回答：

```text
当时 DSL 是否 unavailable
```

。

---

# 211. Binding Receipt 也有利于实验

可以统计：

```text
provider candidate count

eligible count

risk rejection count

expressiveness rejection count

readiness rejection count

rebind count
```

。

---

# 212. 推荐 Telemetry

```text
EXECUTION_BINDING_REQUESTED

EXECUTION_PROVIDER_REJECTED

EXECUTION_PROVIDER_SELECTED

EXECUTION_REBIND_REQUESTED

EXECUTION_REBOUND

EXECUTION_BINDING_EXHAUSTED
```

。

---

# 213. Metrics

```text
provider_candidate_count

provider_eligible_count

provider_feature_reject_count

provider_risk_reject_count

provider_unavailable_reject_count

provider_binding_count

provider_rebind_count

provider_retry_count

provider_binding_latency_ms
```

。

---

# 214. 不要混入 `replan_count`

Rebind：

```text
replan_count
必须保持 0
```

。

---

# 215. Session Model 更新

当前 `StepAttemptRecord` 有：

```text
worker_id
resource handles
fallback action
```

。

建议增加：

```text
logical_capability_id

provider_id

provider_version

execution_binding_hash

supersedes_attempt_id
```

。

---

# 216. 但 Binding Receipt 是独立 authoritative object

不要把全部 candidate/rejection details 都塞：

```text
StepAttemptRecord
```

。

Session 只存：

```text
receipt hash
```

。

---

# 217. Replan Record 不记录 Rebind

`RuntimeReplanRecord` 保持：

```text
semantic Plan mutation
```

专用。

---

# 218. Provider Rebind 另建

```text
ExecutionBindingReceipt.supersedes_binding_hash
```

就足够。

---

# 219. Attempt Budget

当前 Adaptive Runtime：

```text
total_attempt_budget
```

已经有。

。

---

# 220. Rebind 还需要 per-step bound

建议 Envelope 增：

```text
max_provider_rebinds_per_step
```

例如：

```text
1
```

。

---

# 221. Retry 也有独立 bound

```text
max_provider_retries_per_step
```

。

---

# 222. 总体仍受

```text
max_total_attempts
```

约束。

---

# 223. 不要用当前 `RuntimeLeaseConfig.max_attempts_per_step` 直接代替

因为：

```text
Lease / process lifecycle attempts
```

和：

```text
semantic execution provider rebind policy
```

职责不同。

---

# 224. 后续 Reliability Batch 再统一预算模型

Batch-05 先定义：

```text
binding recovery bounds
```

。

---

# 225. Static Provider vs Runtime Instance

第一版 Provider 粒度应该是：

```text
implementation class
```

例如：

```text
transform_dsl_v2

bounded_python_bwrap_v2

retrieval_adapter_v1

runtime_builtin_claims_v1
```

。

---

# 226. 不要第一版把每个 worker PID 做 Provider

那属于：

```text
instance / replica
```

。

---

# 227. Provider vs Replica

```text
Execution Provider:
bounded_python_bwrap_v2

Backend replica:
local_vllm instance 0 / 1 / 2
```

。

两层不同。

---

# 228. Provider vs Transport

当前：

```text
subprocess
```

也是一个 physical execution mechanism。

但它不一定是独立 logical execution provider。

---

# 229. Example

Retrieval Provider：

```text
provider.retrieval_adapter.v1
```

内部：

```text
semantic state consume
→ UDS subprocess
```

。

这只是：

```text
Provider internal execution topology
```

。

不是 Planner-level Provider。

---

# 230. Provider Descriptor 可以记录依赖

例如：

```text
required_runtime_services:
    semantic_state_subprocess_v1
```

。

---

# 231. Batch-04 ProtocolPeerManifest 可以被 Provider 引用

Provider：

```text
required peer capability:
semantic_select@v1
```

。

但 Provider Binding 不自己做：

```text
protocol negotiation
```

。

---

# 232. 正确组合

```text
Provider selected
    ↓
Provider runtime dependency resolved
    ↓
ProtocolInvocationBinding
    ↓
worker
```

。

---

# 233. APC 也不要提前混进 Provider Binding

未来 APC 是：

```text
same provider / engine
内部 execution optimization
```

或者：

```text
inference provider scoring signal
```

。

---

# 234. 但当前 Batch-05 不需要：

```text
APC-aware provider score
```

。

先把 boundary 做对。

---

# 235. Benchmark Backend Matrix 不能直接拿来当 Provider Registry

当前 `backend_matrix.py`：

```text
mmap_loopback
shared_memory_loopback
memfd_subprocess
```

。

这是：

```text
实验变量 matrix
```

。

不是 production provider registry。

---

# 236. State Pool Backend 也不是 Logical Execution Provider

```text
mmap

shared_memory

memfd
```

属于：

```text
data-plane backend
```

。

以后可以成为 provider dependency/resource facts。

不应该混进：

```text
Logical Capability → Provider
```

第一层。

---

# 237. Legacy `route_tool_catalog.py`

历史上：

```text
route
→ tool_name
```

直接绑定。

这是典型：

```text
semantic route
与 execution tool
耦合
```

。

---

# 238. 但它是 Legacy / Comparator 范畴

Batch-05 不应：

```text
拿 route_tool_catalog
作为新 ProviderRegistry
```

。

---

# 239. 新 Provider Binding 只从 Adaptive Mainline 推进

这可以避免：

```text
把旧 route/tool profile
重新带回 production architecture
```

。

---

# 240. PlanPolicy Migration

当前：

```text
descriptor.execution_kind
```

进入：

```text
LLM Python enable gate
```

。

同时：

```text
descriptor.side_effect_class
```

进入：

```text
risk gate
```

。

---

# 241. 这两个 gate 目前发生在 PlanPolicy

说明：

```text
Plan Approval
```

已经被 physical provider 属性影响。

---

# 242. Target PlanPolicy

PlanPolicy 只验证：

```text
logical capability authorized

logical input/output contract

role

dependencies

completion criteria

required features vocabulary

semantic budget
```

。

---

# 243. Provider Risk Gate 移到 Binding

因为：

```text
不同 Provider
风险不同
```

。

---

# 244. 但是 Task Envelope Risk 仍由 PlanPolicy冻结

即：

```text
risk ceiling
```

仍是 Plan Authority。

Binder 只能：

```text
选择 <= ceiling 的 provider
```

。

---

# 245. Planner 是否需要知道 Provider 风险

不需要。

它只知道：

```text
这个 logical capability
允许有哪些 requirement features
```

。

---

# 246. Logical Capability 自身无法在当前 risk ceiling 下实现怎么办

例如：

```text
required pivot

所有 provider 都 BOUNDED_CODE

task risk ceiling = WORKSPACE_WRITE
```

。

结果：

```text
Plan 本身可能语义上合法
```

但：

```text
runtime NO_ELIGIBLE_PROVIDER
```

。

---

# 247. 是否应该 PlanPolicy 提前知道

如果 Provider Registry 是静态的，

可以做：

```text
optional feasibility precheck
```

。

但不要把 Provider selection 固化进 Plan。

---

# 248. 推荐两阶段

PlanPolicy：

```text
semantic valid
```

。

Optional Preflight：

```text
at least one currently installed provider could satisfy
```

。

真正执行：

```text
STEP_READY
再 bind
```

。

---

# 249. 这样既早发现完全不可执行

又不把：

```text
provider identity
```

写进 ApprovedPlan。

---

# 250. Provider Preflight Receipt

可选：

```text
PlanFeasibilityReport
```

。

不需要第一版。

---

# 251. Mainline Assembly

`AdaptiveMainlineRunner` 是现在的 product-owned assembly point。

很适合新增：

```text
logical_registry

provider_registry

binding_policy

provider_fact_builder
```

。

---

# 252. AdaptiveMainlineBindings 拆分建议

当前：

```text
transform_program_factory

code_source_factory

code_policy_factory

builtin_handlers
```

。

这些实际上是：

```text
Provider implementation dependencies
```

。

---

# 253. Target

可以保留 context，

但增加：

```text
ProviderRuntimeEnvironment
```

来收敛。

---

# 254. Example

```python
ProviderRuntimeEnvironment(
    transform_program_factory=...,
    code_source_factory=...,
    code_policy_factory=...,
    builtin_handlers=...,
    retrieval_adapter=...,
    protocol_peer=...,
)
```

。

---

# 255. Provider Fact Builder 从 Environment 推 readiness

而不是 Dispatcher 执行到一半：

```text
才发现 None
```

。

---

# 256. Quality Semantics Key

当前：

```text
quality_semantics_by_capability
```

。

如果是：

```text
业务语义 validator contract
```

应继续 keyed by：

```text
logical capability
```

。

---

# 257. Output Schema Key

当前：

```text
output_schema_by_capability
```

。

同样：

```text
logical capability
```

更合理。

---

# 258. CodeAct Contracts

当前：

```text
codeact_contracts[capability]
```

。

这里更偏：

```text
provider-specific implementation contract
```

。

---

# 259. Target

可以：

```text
codeact_contracts_by_provider
```

。

但其中：

```text
semantic operation semantics
```

如果属于 logical contract，

应上移。

---

# 260. 不要为了拆分而复制两份 truth

原则：

```text
semantic meaning
放 Logical

physical execution requirements
放 Provider
```

。

---

# 261. Provider-specific Output Schema 是否允许

只有：

```text
内部 intermediate schema
```

可以。

最终：

```text
logical output contract
```

必须一致。

---

# 262. Provider 可做 Internal Normalization

例如：

```text
Python raw result

DSL raw result
```

内部不同。

但进入 Runtime Result Admission 前：

```text
都必须 normalize
到 same logical output contract
```

。

---

# 263. Provider Adapter

可以引入：

```text
ProviderResultAdapter
```

。

但第一版可由现有 handler 保持。

---

# 264. Provider Result 最终必须带

```text
binding hash
grant hash
logical output contract
provider identity
output refs
validator reports
```

。

---

# 265. Provider Binding 与 Artifact Verification

链路：

```text
Binding
    ↓
Execution
    ↓
Provider Result
    ↓
Result Binding
    ↓
Ref Admission
    ↓
Artifact Verification
    ↓
Step Completed
```

。

---

# 266. Provider success ≠ logical success

Provider 说：

```text
execution done
```

并不代表：

```text
logical capability verified
```

。

---

# 267. Logical Validators 仍是最终 Truth

这也确保：

```text
DSL
和
Python
```

能够在：

```text
相同质量合同
```

下比较。

---

# 268. Provider Ranking 不得靠 Benchmark Gold

当然。

但这里还要更具体。

---

# 269. Binder 输入禁止

```text
expected answer

benchmark task ID semantics

dataset family label

gold difficulty

which provider historically passed this benchmark case
```

。

---

# 270. Binder 可以输入

```text
public task contract

required features

runtime facts

resource facts

replay facts

provider telemetry
```

。

---

# 271. 这样 External Benchmark 才能证明 Generalization

Provider selection：

```text
不是 case whitelist
```

。

---

# 272. 推荐 Tests — Logical Contract

```text
LogicalCapabilityDescriptor
不得含 execution_kind
```

。

---

# 273. Provider Registration Test

```text
provider references unknown logical capability
→ reject
```

。

---

# 274. Semantic Hash Test

```text
provider semantic_contract_hash mismatch
→ reject
```

。

---

# 275. Registry Digest Isolation

```text
change provider health
→ logical registry digest unchanged
→ provider registry digest unchanged
→ runtime facts digest changes
```

。

---

# 276. Provider Version Isolation

```text
provider v1 → v2
```

如果 logical contract unchanged：

```text
ApprovedPlan hash unchanged
```

。

---

# 277. Logical Contract Change

```text
output contract v2 → v3
```

：

```text
logical registry digest changes

new ApprovedPlan identity
```

。

---

# 278. Planner Surface Test

assert Planner surface 不含：

```text
provider_id

execution_kind

bwrap

provider health

provider runtime limit

LLM backend
```

。

---

# 279. Required Feature Test

Planner 请求：

```text
unknown feature
```

：

```text
PlanPolicy reject
```

。

---

# 280. Eligibility Test

```text
required pivot
```

：

```text
DSL rejected FEATURE_UNSUPPORTED

Python eligible
```

。

---

# 281. Risk Test

```text
risk ceiling WORKSPACE_WRITE
```

：

```text
Python rejected RISK_EXCEEDED
```

。

---

# 282. Readiness Test

```text
transform_program_factory missing
```

：

```text
DSL filtered PROVIDER_NOT_READY
```

。

必须发生在：

```text
Grant 前
```

。

---

# 283. No Eligible Provider Test

```text
all candidates rejected
```

：

```text
no grant issued
```

。

。

---

# 284. Deterministic Ranking Test

相同 inputs：

```text
same provider selected
```

。

---

# 285. Stable Tie-break Test

分数完全一致：

```text
provider_id lexical
```

或：

```text
static priority + provider id
```

稳定决定。

---

# 286. Binding Receipt Test

相同：

```text
request + registry + facts + policy
```

：

```text
same receipt hash
```

。

---

# 287. Rebind Test

Provider A 执行前 unavailable：

```text
Binding 1:
A selected

A fails/withdrawn

Binding 2:
B selected
supersedes Binding 1
```

。

---

# 288. Rebind Invariants

assert：

```text
ApprovedPlan hash same

logical capability same

semantic contract same

step ID same

output contract same

required features same

replan_count == 0

binding hash different

grant hash different

attempt ID different
```

。

---

# 289. Replan Boundary Test

尝试：

```text
rebind to provider that only implements
different logical capability
```

：

```text
reject
```

。

---

# 290. Risk Rebind Test

A fails。

B 可执行但：

```text
risk > ceiling
```

：

```text
B rejected

no risk escalation
```

。

---

# 291. Provider-specific Replay Test

Provider A 有 replay recipe。

A eligible。

B eligible。

第一版 ranking：

```text
A may prefer replay
```

。

---

# 292. 但 logical memory compatibility unchanged

无论 Provider A/B：

```text
same logical memory
```

。

---

# 293. Real E2E Experiment A — Simple Analysis

同一个：

```text
ApprovedPlan:
execute_analysis_v2
```

。

Required：

```text
select
aggregate
```

。

---

# 294. Force Provider DSL

验证：

```text
quality passes
```

。

---

# 295. Force Provider Python

同样：

```text
logical output/validator
passes
```

。

---

# 296. 证明什么

证明：

```text
两个 provider
实现的是同一个 logical capability
```

。

不是为了证明：

```text
谁一定更快
```

。

---

# 297. Experiment B — Auto Binding

相同 Plan：

```text
两 provider eligible
```

。

Binder：

```text
select lower-risk DSL
```

。

---

# 298. Experiment C — Expressiveness Causal

任务需要：

```text
pivot / branch-recombine
```

。

DSL：

```text
filtered
```

。

Python：

```text
selected
```

。

---

# 299. 核心证据

```text
Selection reason
来自 required_features
```

。

不能来自：

```text
benchmark case ID
```

。

---

# 300. Experiment D — Forced Outage

Simple task：

```text
本来 select DSL
```

。

执行前把 DSL runtime fact 设：

```text
UNAVAILABLE
```

。

---

# 301. 如果 Risk 允许 Python

Binder：

```text
select Python
```

。

必须：

```text
same ApprovedPlan
```

。

---

# 302. Experiment E — No Risk Escalation

同样 DSL unavailable。

Task：

```text
risk ceiling WORKSPACE_WRITE
```

。

Python：

```text
BOUNDED_CODE
```

。

Expected：

```text
binding exhausted
```

。

---

# 303. Experiment F — Rebind Mid-attempt

DSL provider：

```text
provider-specific runtime failure
```

。

Policy：

```text
allow single rebind
```

。

Runtime：

```text
fresh binding
fresh grant
Python
```

。

---

# 304. Experiment G — Registry Identity

Same logical capability registry。

安装：

```text
new provider C
```

。

---

# 305. Expected

```text
old ApprovedPlan hash
仍合法
```

。

新的 Binding：

```text
candidate set
可能增加 C
```

。

这证明：

```text
Plan identity
与 Provider inventory 解耦
```

。

---

# 306. Experiment H — Provider Upgrade

Provider：

```text
transform_dsl_v2
→ transform_dsl_v3
```

。

如果：

```text
semantic contract unchanged
```

：

```text
ApprovedPlan same
Binding Receipt changes
Grant changes
```

。

---

# 307. Experiment I — Logical Contract Upgrade

Logical：

```text
analysis_result.v2 → v3
```

。

Expected：

```text
Old provider support invalid
unless explicitly supports new semantic hash
```

。

---

# 308. Experiment J — Retrieval Distinction

证明：

```text
retrieve_semantic_evidence
```

和：

```text
retrieve_table_evidence
```

仍是两个 logical capabilities。

---

# 309. 即使它们共享 Provider

也不能：

```text
Binder 把 semantic retrieval
rebind 成 table retrieval
```

。

那是 semantic replan。

---

# 310. Provider Selection Telemetry Experiment

每个 task 输出：

```text
candidate providers

rejection reasons

selected provider

binding latency

rebind count
```

。

---

# 311. External Benchmark 后续使用

TeamBench / IDA 等 external lane：

```text
只通过 public task facts
产生 required features
```

。

不要：

```text
人工标注 provider
```

。

---

# 312. 如果 external task 落到 Python 更多

这可以成为真实：

```text
expressiveness evidence
```

。

而不是：

```text
预设 Python 胜
```

。

---

# 313. Risk Table

| Priority | 问题 | 类型 |
|---|---|---|
| **P0** | `CapabilityDescriptor` 混合 semantic interface 与 execution implementation | Architecture |
| **P0** | Planner public surface 暴露 `execution_kind`，Planner 直接选择 DSL/Python | Routing Boundary |
| **P0** | Generic DSL/Python 共合同却被建模成两个 capability 并 mutual fallback | Identity |
| **P0** | ApprovedPlan registry digest 被 provider implementation 属性污染 | Plan Identity |
| **P0** | Runtime 没有 STEP_READY → provider binding seam | Runtime |
| **P0** | 当前 `fallback_capability_id` 无法区分 rebind 与 replan | Recovery |
| **P1** | Provider readiness 直到 dispatch 后才通过 `*_handler_not_registered` 失败 | Availability |
| **P1** | `execution_kind` 同时是 Planner-visible semantic hint 和 Dispatcher key | Coupling |
| **P1** | Risk 是 Descriptor 单值，无法表达同一 logical capability 的不同 provider risk | Policy |
| **P1** | `max_runtime_ms` / replay 属 provider，却绑定 Plan registry | Identity |
| **P1** | Memory execution recipe 用 `capability_id + execution_kind` 混合 logical/provider identity | Replay |
| **P1** | StepAttemptRecord 缺 provider / binding receipt identity | Audit |
| **P1** | Planner feature demand 没有 provider-neutral structured representation | Expressiveness |
| **P1** | Deterministic capability 的 fallback metadata 与 Runtime 实际 fallback scope 不一致 | Truth |
| **P1** | Existing `ProviderConfig` 命名易与 Execution Provider 混淆 | Naming |
| **P2** | Provider health / outlier / dynamic latency 尚无 runtime facts model | Reliability |
| **P2** | Replica-level routing 与 Provider binding 尚未 formal 分层 | Scaling |

---

# 314. Positive Finding — Plan Compiler Boundary 很好

`adaptive_plan_compiler.py` 已明确：

```text
不选择 capabilities

不增加 semantic stages

不改变 goals
```

。

这个 boundary 要保留。

---

# 315. Positive Finding — Fresh Grant Recovery 已经存在

现有 Python fallback：

```text
fresh attempt
fresh Grant
```

。

这个是 Batch-05 可以直接继承的正确安全属性。

---

# 316. Positive Finding — PlanPolicy 已有强 Contract Gate

当前已经验证：

```text
capability allowlist

role ownership

input refs/kinds

output contract

risk

completion criteria
```

。

拆 Provider 后不是推倒重来。

而是：

```text
把 provider-only gates
移动到 Binding phase
```

。

---

# 317. Positive Finding — Generic Capability 已经在向抽象收敛

`execute_analysis_dsl_v2` / `execute_bounded_python_v2`

都使用：

```text
statebus.analysis_input.v2

statebus.analysis_result.v2
```

。

这说明：

```text
logical interface
```

其实已经隐约存在。

只是还没有正式建模。

---

# 318. Positive Finding — Validator 是天然 Equivalence Anchor

同 logical provider：

```text
应通过相同 logical validators
```

。

这是判断：

```text
两个实现是否真的等价
```

的重要依据。

---

# 319. Positive Finding — Runtime Result 已有 Grant Binding

高层：

```text
AdaptiveStepResult.grant_hash
```

会和 Runtime Grant 比较。

未来只需要进一步：

```text
Grant 绑定 BindingReceipt / Provider
```

即可。

---

# 320. Positive Finding — ApprovedPlan 不含 Provider ID

这意味着结构迁移成本比想象低。

---

# 321. Recommended File Layout

第一版：

```text
statebus/contracts/
    capability.py
    provider.py
    execution_binding.py

statebus/runtime/
    logical_capability_registry.py
    execution_provider_registry.py
    provider_runtime_facts.py
    execution_binding_policy.py
    provider_dispatcher.py
```

。

---

# 322. 是否立即移动现有 CapabilityDescriptor 文件

不需要。

R0 可以：

```text
新增 contracts
+
compatibility adapters
```

。

---

# 323. Legacy Adapter

```python
LegacyCapabilityBindingMap
```

。

只用于迁移。

---

# 324. 不允许长期成为隐藏路由表

它最终要删除。

---

# 325. Provider Registry API

```python
register(provider)

get(provider_id)

providers_for(logical_capability_id)

freeze()

digest
```

。

---

# 326. Logical Registry API

和当前 Registry 接近：

```python
register(logical)

get(logical_capability_id)

public_view(...)

freeze()

authority_digest

planner_surface_digest
```

。

---

# 327. 继续保留两个 Digest

Batch-04 已建议：

```text
authority digest

planner surface digest
```

。

Batch-05 完全兼容。

---

# 328. Logical Authority Digest

不含：

```text
description wording
```

。

---

# 329. Planner Surface Digest

包含：

```text
description
planner-visible feature descriptions
```

。

---

# 330. Provider Registry Digest

只含：

```text
static provider declarations
```

。

---

# 331. Provider Runtime Facts Digest

每个 Binding snapshot 计算。

---

# 332. Binding Cost

第一版应该非常低。

Provider 数量：

```text
个位数
```

。

Filter/Rank：

```text
纯内存结构
```

。

无需：

```text
网络服务

数据库

LLM
```

。

---

# 333. 对赛题通信开销几乎没有影响

Binding 发生：

```text
Controller 内部
```

。

。

---

# 334. Receipt Persistence 可以 Balance

Formal：

```text
完整 receipt
```

。

Benchmark balanced：

```text
只持久化 hash + compact rejection codes
```

。

---

# 335. 不要为了 Audit 把巨大 Provider manifest 每次重复写

可以：

```text
Registry digest
+
receipt delta
```

。

---

# 336. Provider Score 可解释

推荐 Receipt 记录：

```text
selection_rank
```

而不是：

```text
opaque 0.731982
```

。

---

# 337. 第一版 Rank 示例

```text
(
    risk_rank,
    deterministic_penalty,
    degraded_penalty,
    estimated_latency_bucket,
    replay_penalty,
    provider_id
)
```

。

最小者胜。

---

# 338. 不建议第一版使用随机 tie-break

因为：

```text
evidence / audit
```

更需要 determinism。

---

# 339. 后续负载均衡才可能需要 randomization

那属于：

```text
Scheduler / Reliability / Deployment
```

。

---

# 340. No Eligible Provider Result

需要正式对象。

例如：

```python
ExecutionBindingFailure(
    task_id,
    step_id,
    logical_capability_id,
    candidate_rejections,
    failure_code="NO_ELIGIBLE_PROVIDER",
)
```

。

---

# 341. Runtime 如何处理

根据 step recovery policy：

```text
request_replan
```

或：

```text
fail
```

。

---

# 342. Binder 本身不能 Replan

它只说：

```text
我没有合法 Provider。
```

。

---

# 343. Replan 仍由 Runtime / Planner authority

这样不会出现：

```text
Binder偷偷选另一个 capability
```

。

---

# 344. Provider Binding 与 Fallback DAG

当前一些 recovery 会：

```text
替换 unexecuted subgraph
```

。

这是：

```text
Replan
```

。

保持。

---

# 345. 不能把 Provider Rebind 写进 Plan DAG

Provider：

```text
不是 semantic stage
```

。

---

# 346. 所以 Planner 不应输出：

```text
try_dsl
then_python
```

。

这会污染 DAG。

---

# 347. Correct

Planner：

```text
execute_analysis_v2
```

。

Runtime：

```text
bind DSL

if provider-specific failure:
rebind Python
```

。

---

# 348. 这也减少 Plan 长度

不需要：

```text
把 recovery alternatives
作为 semantic nodes
```

。

---

# 349. Provider Binding 对 Generality 的价值

现在 Planner 学到：

```text
“某类 task 选 Python”
```

可能高度依赖：

```text
当前 benchmark capability naming
```

。

---

# 350. 拆以后

Planner 只学：

```text
需要 pivot
需要 join
需要 custom parse
```

。

这更接近：

```text
transferable task semantics
```

。

---

# 351. 对 External Dataset 更友好

新 dataset：

```text
没见过
```

也可以：

```text
required_features
→ provider eligibility
```

。

---

# 352. 这正好回应项目最初的 generalization concern

不是：

```text
训练/提示 Planner 记住更多 dataset profile
```

。

而是：

```text
让 system contract
把 semantic requirement
与 physical implementation
解耦
```

。

---

# 353. 对简历/比赛项目的价值

修完以后：

```text
不是“LLM 选 tool”
```

。

而是一个真正：

```text
Controller-owned capability scheduler
```

。

---

# 354. 可叙述成

> Planner 只生成 provider-neutral logical plan；Controller 在 step-ready 时依据 capability contract、required expressiveness、risk ceiling、provider readiness 与 resource facts 进行 hard eligibility filtering，再对合法 providers 做 deterministic ranking，并生成 binding receipt。Provider 故障可以在保持 ApprovedPlan 不变的情况下重新绑定实现；只有 semantic contract 或 DAG 改变才触发 replan。

。

---

# 355. 这个叙事比“Router 选 DSL/Python”强很多

因为有：

```text
authority boundary

placement boundary

recovery semantics

audit receipt

runtime facts
```

。

---

# 356. Hard Exclusions

本 Batch 明确不做：

```text
❌ 新增 LLM Provider Router Agent

❌ Planner 输出 provider_id

❌ Planner 输出 execution_kind

❌ Planner 输出 use_python=true

❌ 把所有同 output contract capability 自动合并

❌ 用 score 补偿 risk/contract failure

❌ Rebind 时修改 ApprovedPlan

❌ Rebind 时复用旧 Grant

❌ 把 logical capability change 叫 Rebind

❌ 把 provider change 记成 Replan

❌ 让 Provider Binder 重新读取自然语言任务做第二次 semantic routing

❌ 用 benchmark labels 做 provider selection

❌ 把 backend_matrix.py 变 production registry

❌ 把每个 Worker PID 做 Provider

❌ 把每个 LLM endpoint 做 StateBus Provider

❌ 同时重构 APC / KV / Scheduler

❌ 复制 Kubernetes/Nomad 全套 scheduler framework

❌ 一开始加入复杂 weighted learned ranking
```

。

---

# 357. Recommended Implementation Slices

---

## PB-R0 — Boundary Inventory / Compatibility Mapping

### Goal

没有 behavior change。

---

# 358. R0 Deliverables

新增：

```text
LogicalCapabilityDescriptor
ExecutionProviderDescriptor
CapabilitySupport
```

但暂时只做：

```text
shadow metadata
```

。

---

# 359. R0 建立显式 mapping

只对审计确认的 pairs：

```text
execute_analysis_dsl_v2
execute_bounded_python_v2
```

。

---

# 360. 不自动猜 mapping

必须：

```text
reviewed manifest
```

。

---

# 361. R0 Acceptance

```text
all existing tests unchanged

formal benchmark path unchanged

no provider selection behavior change
```

。

---

## PB-R1 — Shadow Binding Receipt

---

# 362. R1

在 STEP_READY：

```text
构造 BindingRequest

生成 candidate/rejection/selected receipt
```

。

但强制：

```text
selected provider
=
legacy capability mapped provider
```

。

---

# 363. R1 Acceptance

```text
ApprovedPlan unchanged

quality unchanged

dispatch path unchanged

BindingReceipt reproducible
```

。

---

## PB-R2 — Logical Planner Surface

---

# 364. R2

Planner：

```text
execute_analysis_v2
```

。

新增：

```text
required_features
```

。

---

# 365. 移除 Planner Surface 中

```text
execution_kind

provider-specific risk

fallback implementation
```

。

---

# 366. PlanPolicy

验证：

```text
required_features vocabulary
```

。

---

# 367. R2 Acceptance

```text
Planner cannot name provider

Plan hashes provider-neutral
```

。

---

## PB-R3 — Real Provider Binding

---

# 368. R3

实现：

```text
ExecutionProviderRegistry

ProviderRuntimeFacts

ExecutionBindingPolicy
```

。

---

# 369. Hard Filters

至少：

```text
capability support

semantic contract

features

risk

readiness
```

。

---

# 370. R3 Ranking

第一版：

```text
deterministic lexicographic
```

。

---

# 371. R3 Acceptance

Simple analysis：

```text
DSL selected
```

。

Pivot：

```text
Python selected
```

在 risk 允许时。

---

## PB-R4 — Provider-bound Grant / Dispatcher

---

# 372. R4

Grant 增：

```text
provider id/version

binding hash
```

。

---

# 373. Dispatcher

从：

```text
ExecutionKind map
```

迁：

```text
provider registry
```

。

---

# 374. R4 Acceptance

任何：

```text
binding/grant/provider mismatch
```

fail closed。

---

## PB-R5 — Recovery

---

# 375. R5

替换：

```text
fallback_deterministic
```

核心 behavior。

---

# 376. 引入：

```text
RETRY_PROVIDER

REBIND_PROVIDER

REQUEST_REPLAN

FAIL
```

。

---

# 377. R5 Acceptance

Provider A failure：

```text
Provider B rebind

same plan

fresh grant
```

。

---

## PB-R6 — Readiness / Runtime Facts

---

# 378. R6

把：

```text
handler_not_registered

bwrap unavailable

runtime dependency unavailable
```

前移。

---

# 379. R6 Acceptance

provider unavailable：

```text
no grant
no fake dispatch
clear binding rejection reason
```

。

---

## PB-R7 — Experiment Closure

---

# 380. R7

建立：

```text
same plan / multi-provider

expressiveness causal

risk causal

outage rebind

registry identity isolation
```

evidence。

---

# 381. 不需要在 R7 加 learned cost model

。

---

# 382. Codex Parent Task — PB-01

```text
Title:
Separate Logical Capability and Provider Contracts

Mode:
SLICE_EXECUTE

Do:
- add new contract classes
- add compatibility mapping for explicitly approved pairs
- no runtime selection changes
- no Planner output changes
- preserve old CapabilityDescriptor compatibility

Do not:
- modify dispatch behavior
- modify benchmark quality logic
- modify APC/KV
```

。

---

# 383. Acceptance

```text
existing tests pass

new semantic hash tests pass

mapping only contains audited equivalence groups
```

。

---

# 384. Codex Parent Task — PB-02

```text
Title:
Add Shadow Execution Binding Receipts
```

。

---

# 385. Do

```text
build binding request

enumerate candidate providers

record rejection reasons

force legacy provider selection

persist receipt hash
```

。

---

# 386. Do not

```text
change selected execution path
```

。

---

# 387. Codex Parent Task — PB-03

```text
Title:
Expose Provider-Neutral Planner Capabilities
```

。

---

# 388. Do

```text
logical public view

required_features

PlanPolicy feature validation

formal benchmark migration
```

。

---

# 389. Do not

```text
let Planner select provider
```

。

---

# 390. Codex Parent Task — PB-04

```text
Title:
Enable Runtime Provider Binding
```

。

---

# 391. Do

```text
filter
rank
receipt
provider-bound grant
provider dispatcher
```

。

---

# 392. Codex Parent Task — PB-05

```text
Title:
Separate Retry Rebind Replan
```

。

---

# 393. Do

```text
fresh grants

same-plan rebind

semantic replan boundary

telemetry
```

。

---

# 394. Key Invariants Checklist

实现 review 时必须逐条确认。

---

# 395. Logical Invariants

```text
[ ] Planner cannot select Provider

[ ] ApprovedPlan contains no Provider identity

[ ] Logical registry digest excludes Provider inventory

[ ] Logical semantic contract changes alter Plan identity

[ ] Provider health changes do not alter Plan identity
```

。

---

# 396. Binding Invariants

```text
[ ] All hard eligibility gates run before ranking

[ ] Score cannot recover a hard-rejected provider

[ ] BindingReceipt records candidate + rejected + eligible + selected

[ ] Runtime facts digest is captured

[ ] Selection is deterministic for same snapshot
```

。

---

# 397. Grant Invariants

```text
[ ] Grant binds logical capability

[ ] Grant binds provider

[ ] Grant binds binding receipt

[ ] Retry receives fresh grant

[ ] Rebind receives fresh grant

[ ] old grant cannot authorize new provider
```

。

---

# 398. Recovery Invariants

```text
[ ] Retry = same provider

[ ] Rebind = different provider, same logical contract

[ ] Replan = semantic plan change

[ ] Rebind leaves ApprovedPlan hash unchanged

[ ] Rebind does not increment replan count

[ ] No risk escalation during rebind
```

。

---

# 399. Quality Invariants

```text
[ ] Providers for same logical capability share logical validators

[ ] Provider success is not Step success before validation

[ ] Output contract is exact

[ ] Required output cardinality is enforced
```

。

---

# 400. Benchmark Invariants

```text
[ ] benchmark origin not in binding request

[ ] gold not visible

[ ] provider choice driven by public features/runtime facts

[ ] forced provider experiments keep logical plan fixed
```

。

---

# 401. Batch-05 Truth Ladder

可以定义：

```text
L0
Planner selected a registered logical capability

L1
Logical contract validated

L2
Runtime built provider candidate set

L3
Hard eligibility proved

L4
Provider ranked among eligible candidates

L5
BindingReceipt committed

L6
Provider-bound Grant issued

L7
Provider invocation executed

L8
Result bound to Grant/Binding

L9
Artifact verified
```

。

---

# 402. 当前成熟度

大致：

```text
L0:
强，但 capability 不是纯 logical

L1:
强

L2:
不存在

L3:
部分散落在 Dispatcher

L4:
不存在

L5:
不存在

L6:
Grant 存在，但不 provider-bound

L7:
强

L8:
高层 grant binding 部分存在

L9:
Batch-03 已较强
```

。

---

# 403. 最终推荐架构

```text
             Planner / PlanSelector
                      │
                      ▼
        LogicalCapabilityRegistry
                      │
                      ▼
                  PlanStep
    logical_capability + required_features
                      │
                      ▼
                 PlanPolicy
                      │
                      ▼
                ApprovedPlan
                      │
                      ▼
                  STEP_READY
                      │
                      ▼
          ExecutionBindingRequest
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
ExecutionProviderRegistry   ProviderRuntimeFacts
          └───────────┬───────────┘
                      ▼
             Eligibility Filters
                      │
                      ▼
              Eligible Providers
                      │
                      ▼
            Deterministic Ranking
                      │
                      ▼
           ExecutionBindingReceipt
                      │
                      ▼
          Provider-bound CapabilityGrant
                      │
                      ▼
             Provider Dispatcher
                      │
                      ▼
          ProtocolInvocationBinding
                      │
                      ▼
               Provider / Worker
                      │
                      ▼
            Bound Physical Result
                      │
                      ▼
              Artifact Verification
```

。

---

# 404. 这和现有 Routing 总架构的对应关系

冻结：

```text
PlanSelector
    ↓
Approved Logical Plan
    ↓
AdaptiveRuntimeEngine
    ↓
STEP_READY
    ↓
ExecutionBindingPolicy
    ↓
ExecutionBindingReceipt
    ↓
CapabilityGrant(provider bound)
    ↓
Provider Dispatcher
```

。

这和之前 Routing Audit 完全一致。

---

# 405. 不需要新建三个 Router Agent

依然成立。

---

# 406. PlanSelector 与 Binder 的职责

PlanSelector：

```text
semantic choice
```

。

Binder：

```text
physical implementation choice
```

。

---

# 407. Scheduler 与 Binder 的职责

Binder：

```text
这个 step 用哪个 provider
```

。

Scheduler：

```text
哪个 ready step 先执行
```

。

---

# 408. APC 与 Binder 的职责

Binder：

```text
哪个 execution provider
```

。

APC policy：

```text
这个 inference invocation
是否复用 prefix/KV
```

。

---

# 409. 不要提前互相耦合

以后可以：

```text
APC residency
成为 provider score signal
```

。

但不是 Batch-05 correctness requirement。

---

# 410. Provider Binding 与 Deployment

Deployment 后续会管理：

```text
provider instances

replicas

health

capacity

placement
```

。

Batch-05 只预留：

```text
ProviderRuntimeFacts
```

。

---

# 411. Provider Binding 与 Security

Security 后续会强化：

```text
provider trust

signing

peer credentials

network scope
```

。

Batch-05 只保持：

```text
risk / authority / receipt identity
```

。

---

# 412. 当前应该先改哪里

优先顺序：

```text
1. Contracts split

2. Shadow receipt

3. Planner surface

4. Real binding

5. Provider-bound grant

6. Recovery taxonomy

7. Runtime readiness
```

。

---

# 413. 不建议先改 Dispatcher

如果一上来：

```text
把 Dispatcher 改 provider_id
```

但：

```text
Planner 还在输出 DSL/Python capability
```

就会形成：

```text
双重 identity transitional mess
```

。

---

# 414. 所以 R0/R1 必须先 shadow

。

---

# 415. 不建议先删 Legacy Capability IDs

先保留 alias：

```text
旧 benchmark

旧 tests

旧 manifests
```

。

---

# 416. 什么时候删

等：

```text
logical planner surface

provider binding

formal benchmark
```

全部迁移后。

---

# 417. Migration Compatibility Manifest

建议有：

```yaml
legacy_capabilities:
  execute_analysis_dsl_v2:
    logical_capability: execute_analysis_v2
    provider: transform_dsl_v2

  execute_bounded_python_v2:
    logical_capability: execute_analysis_v2
    provider: bounded_python_bwrap_v2
```

。

---

# 418. 这个 Manifest 必须 Controller-owned

不是：

```text
benchmark adapter
```

。

---

# 419. 但它只是迁移工具

最终：

```text
delete
```

。

---

# 420. 何时可以宣称 Provider Binding 已完成

至少要有证据：

```text
1.
Planner 输出 provider-neutral plan

2.
同一 ApprovedPlan
可以合法绑定至少两个 providers

3.
BindingReceipt
能解释 filter/rank

4.
Provider outage
触发 rebind

5.
Rebind 不改变 Plan hash

6.
Risk ceiling
不会因为 fallback/rebind 被提升

7.
不同 provider
最终经过同一 quality contract

8.
no eligible provider
fail closed
```

。

---

# 421. 仅仅创建 ProviderRegistry 不算完成

。

---

# 422. 仅仅把 `execution_kind` 移字段也不算完成

。

---

# 423. 关键是行为边界改变

从：

```text
Planner chooses implementation
```

变：

```text
Runtime binds implementation
```

。

---

# 424. Batch-05 最终冻结结论

> **StateBus 当前最值得修的不是再加一层“Router”，而是把已经混合在 `CapabilityDescriptor` 中的 semantic capability 与 physical execution implementation 拆开。源码已经给出了非常明确的证据：Generic `execute_analysis_dsl_v2` 与 `execute_bounded_python_v2` 共享同一 `statebus.analysis_input.v2 → statebus.analysis_result.v2`、同一 validator 集，却只因 `execution_kind/risk/expressiveness` 不同被建模成两个 Planner-visible capability，甚至互相声明 fallback；这实际上是在用 capability fallback graph 模拟 provider alternatives。Target 应让 Planner 只选择 provider-neutral logical capability 并声明 required features，让 ApprovedPlan 只绑定 LogicalCapabilityRegistry；Step Ready 后由 deterministic ExecutionBindingPolicy 对 ProviderRegistry + RuntimeFacts 做 hard eligibility filtering，再对合法 providers 排序并产生 ExecutionBindingReceipt。Provider failure 只要不改变 logical semantic contract，就使用 fresh binding + fresh Grant 做 rebind，ApprovedPlan hash 与 replan_count 保持不变；一旦 logical capability、output contract、goal 或 DAG 变化，则必须走 replan。这个边界能同时解决当前 execution_kind 泄漏、risk/provider coupling、fallback 歧义、handler readiness 发现过晚、memory recipe identity 混杂等问题，并为后续 APC/Scheduler/Deployment 提供稳定接口。**

---

# 425. External Research References

## StateBus source

```text
https://github.com/qcrs/os/blob/master/statebus/contracts/adaptive.py

https://github.com/qcrs/os/blob/master/statebus/runtime/capability_registry.py
https://github.com/qcrs/os/blob/master/statebus/runtime/domain_packs.py
https://github.com/qcrs/os/blob/master/statebus/runtime/plan_policy.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_plan_compiler.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_mainline.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_runtime.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_dispatcher.py
https://github.com/qcrs/os/blob/master/statebus/runtime/session.py

https://github.com/qcrs/os/blob/master/statebus/integrations/llm.py

https://github.com/qcrs/os/blob/master/statebus/benchmark/adaptive_formal_mainline.py
https://github.com/qcrs/os/blob/master/statebus/benchmark/backend_matrix.py

https://github.com/qcrs/os/blob/master/tests/test_adaptive_codeact_integration.py
```

## Kubernetes Scheduler

```text
https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/
https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/
https://kubernetes.io/docs/reference/scheduling/config/
```

借鉴：

```text
Filter before Score

Bind is distinct from selection

Reserve / Bind decisions are explicit lifecycle points
```

GitHub source：

```text
https://github.com/kubernetes/kubernetes/blob/master/staging/src/k8s.io/kube-scheduler/framework/interface.go
```

。

## Kubernetes Dynamic Resource Allocation

```text
https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/dra-api/
```

借鉴：

```text
DeviceClass
≈ category/interface

ResourceClaim
≈ structured requirement

ResourceSlice / actual device
≈ concrete provider/runtime resource
```

只借分层思想，不复制 Kubernetes machinery。

## Nomad Scheduling

```text
https://developer.hashicorp.com/nomad/docs/concepts/scheduling/how-scheduling-works
```

借鉴：

```text
feasibility checking

then ranking

unhealthy / missing driver
filtered before scoring
```

。

## Envoy Health / Outlier

```text
https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/outlier.html
```

借鉴：

```text
static cluster/provider definition

!=

dynamic health/degraded/ejection facts
```

。

## Ray Serve LLM Routing

```text
https://docs.ray.io/en/latest/serve/llm/architecture/routing-policies.html
https://docs.ray.io/en/latest/serve/llm/user-guides/prefix-aware-routing.html
```

借鉴：

```text
model-level routing

!=

replica-level routing
```

对应：

```text
logical capability

!=

execution provider

!=

backend replica
```

。

GitHub：

```text
https://github.com/ray-project/ray/blob/master/python/ray/llm/_internal/serve/routing_policies/prefix_aware/prefix_aware_router.py
```

。

## WebAssembly Component Model / WIT

```text
https://component-model.bytecodealliance.org/design/wit.html
https://component-model.bytecodealliance.org/design/worlds.html
https://component-model.bytecodealliance.org/design/components.html
```

借鉴：

```text
interface/world defines contract

implementation stays internal

composition is legal only when imports/exports/contracts match
```

。

---

# 426. Next Batch Boundary

Batch-05 完成后，下一条主线可以进入：

```text
Prefix / APC / Explicit KV
```

。

它将建立在本轮 Provider Binding seam 上：

```text
Logical Step
    ↓
Provider Binding
    ↓
Inference Invocation
    ↓
Reuse Policy
    ↓
APC / Explicit KV / Recompute
```

。

这样 APC 不会再作为：

```text
Planner capability
```

或：

```text
semantic routing choice
```

出现。
