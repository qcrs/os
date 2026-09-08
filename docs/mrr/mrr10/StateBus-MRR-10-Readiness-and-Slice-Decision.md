# StateBus MRR-10 — Readiness and Slice Decision

## 1. Readiness conclusion

当前 source 已足以冻结 MRR-10 design，没有需要用户补充的 architecture
decision。实现应拆为两个 slice，因为存在两个可独立失败、需要分别闭合的
correctness invariant：

```text
Risk A
真实 role-local mechanism 仍可绕过 current Attempt/Binding/Grant，
并自行 retry/select/commit。

Risk B
fixed compatibility entry 仍可能通过 run_smoke/RolePathRunner 绕过
AdaptiveMainlineRunner/AdaptiveRuntimeEngine。
```

因此：

```text
MRR-10A = Role Provider Authority Convergence
MRR-10B = Fixed Compatibility Facade + Canonical Full-Graph Parity
```

10B 依赖 10A。该拆分不是工程流程拆分：10A 可用 isolated one-step Gate 证明
provider authority，而 10B 必须用 full graph 和 comparator parity 证明 fixed
entry 已收敛。

## 2. Design conflict adjudication

### Conflict 1 — 三个 role 能否拆成 single-Step provider？

**Current Source Fact**

`choose_retrieval_candidate()`、`validate_execution_choice()`、`summarize()`、
`build_evidence_request()`、`build_transform_program()`、`build_claim_set()` 都接受
显式参数并返回 role-local dataclass/contract。它们内部不直接调用 previous/next
role。真正的 method chaining 位于 `run_smoke()`；retrieval fan-out、CodeAct 和
final materialization 也由 smoke 串联。当前 dispatcher 已分别提供 retrieval、
transform/CodeAct、summarizer execution kinds。

**Options**

1. 将三个 role-local mechanisms 包装为 one-step providers；
2. 保留 `RolePathRunner` 一次执行完整链；
3. 只用 `fixed_mainline.py` 现有 deterministic handlers。

**Recommendation**

选择 1。Role methods 与 actual retrieval/transform/claim mechanisms 在 current
Attempt 内组合；所有跨 role ref 通过 Runtime admission 和下一 Step Grant 传递。

**Why**

现有 method 边界已经足够解耦；问题在 caller sequencing，不需要新 Runtime。

**Rejected Option**

2 保留第二 authority；3 只能证明 plumbing，不能通过真实 Mechanism Gate。

### Conflict 2 — Prompt rendering 是否依赖 global mutable RolePath state？

**Current Source Fact**

prompt 内容主要由显式 args、`RolePromptSlice`、prefix helpers 和 runner config
生成；runner 持有 `rendered_request_audit` mutable list，以及 handoff/logit/prefix
配置。没有 source evidence 表明 prompt 必须依赖跨 role 的 mutable execution
state。

**Options**

1. 将 rendering 变为 per-invocation helper，audit 作为 sideband 返回；
2. 让一个共享 `RolePathRunner` 跨三个 providers 保存 audit/state；
3. 删除 prompt audit。

**Recommendation**

选择 1。保留 prompt semantics 和 audit，但以 current Attempt/invocation scope
记录，不让 mutable list 成为 sequencing 或 truth source。

**Why**

显式输入足以重建 prompt；per-attempt audit 可保留复现证据且不引入共享状态。

**Rejected Option**

2 会形成隐式 cross-step state；3 会无必要地丢失兼容和诊断证据。

### Conflict 3 — LLM provider choice 能否由 ExecutionBindingReceipt 接管？

**Current Source Fact**

当前 `LLMConfig.roles[role].provider/model`、`RoleDispatchLLMClient` 和
`OpenAICompatibleLLMClient.complete()` 共同决定 physical client/endpoint/model；
canonical Runtime 已有 `ProviderEligibilityProjection`、
`ExecutionBindingReceipt` 和 `BoundCapabilityGrant`。

**Options**

1. binding 选择 provider identity，adapter 用该 identity 查既有 physical config；
2. 继续由 role config 选 provider，再仅校验名字；
3. 扩展 RolePath 自己的 provider registry。

**Recommendation**

选择 1。`LLMConfig` 保留为 implementation config，不再是 authority。model/
endpoint 固定在 bound provider 的 config 中，无需修改 receipt schema。

**Why**

这直接复用 MRR-04，不新增 authority。

**Rejected Option**

2 允许 binding 后换 provider/model；3 重做 frozen capability/provider split。

### Conflict 4 — role-local schema 能否投影为 AdaptiveStepResult？

**Current Source Fact**

`AdaptiveStepResult` 已能表达 current attempt/grant、success/failure、output refs/
kinds、validator hashes、artifact candidates、metrics 和 diagnostic data。
dispatcher 已把 retrieval、transform、CodeAct 和 ClaimSet 映射到这些字段。

**Options**

1. authority fields 投影到 `AdaptiveStepResult`，其余保留 telemetry；
2. 新建 RolePath result envelope 与 Runtime 并列；
3. 丢弃 legacy decision fields。

**Recommendation**

选择 1。route/tool/reason/confidence/logit/model usage 保留为 sideband；Evidence、
Artifact、ClaimSet 使用现有 typed refs/reports。

**Why**

不丢语义，也不增加第二 result authority。

**Rejected Option**

2 违反 MRR-06/MRR-08；3 会破坏 parity 和诊断能力。

### Conflict 5 — prefix/logit instrumentation 是否可 sideband 化？

**Current Source Fact**

prefix layout/metrics 本身只影响 prompt packaging 和观察；logit extraction 可只
记录 evidence。但 smoke 的 `retry_once` 会再次调用 executor 并替换 decision，
已直接改变 control path。

**Options**

1. prefix/logit evidence 全部 sideband，control effect 只允许 Runtime policy hook；
2. adapter 内继续 logit retry；
3. 删除 instrumentation。

**Recommendation**

选择 1。telemetry mode 完全 sideband；任何 retry/rebind 必须由 Runtime fresh
Attempt 执行。现有 `run_logit_gate_attempt()` 的 direct State store path 不进入
canonical provider，因为当前 `RuntimeStateAccessAuthority` 没有 logit State
hook；logit evidence 以内联 sideband 传递。

**Why**

保留 mechanism evidence，同时维持 Attempt authority/fencing。

**Rejected Option**

2 是 provider-owned retry；3 无必要损失可观察性。

### Conflict 6 — run_smoke 是否在 Runtime 前产生 authoritative truth？

**Current Source Fact**

是。它先 direct retrieval/State publication、memory lookup、RolePath decisions、
CodeAct、summary、Artifact materialization、validator reports、quality floor 和
MemoryCommit candidate，再调用 legacy `RuntimeDriver.run()`。虽然部分对象名为
candidate，它们已经控制 Driver 的最终输入和输出内容。

**Options**

1. canonical fixed facade 从 task/recipe 开始调用 Mainline/Engine；legacy smoke
   独立作为 comparator；
2. 把 smoke 已生成 outputs 包装成 canonical provider result；
3. 让 Driver 为这些 precomputed outputs 补签 Attempt/Grant。

**Recommendation**

选择 1。

**Why**

只有让 actual work 发生在 Runtime-issued Attempt 内，authority 才真实收敛。

**Rejected Option**

2/3 是事后赋权，无法证明 provider 收到 current Binding/Grant，也无法正确处理
State/Memory lifetime 和 late-result fencing。

### Conflict 7 — parity 是否需要继续调用 legacy code？

**Current Source Fact**

legacy prompt/parser/decision helpers有复用价值；legacy `run_smoke` 能产生完整
baseline。它同时包含不可保留的 orchestration/commit authority。

**Options**

1. 共享纯 helpers/one-step mechanisms，保留独立 legacy comparator lane；
2. canonical path 内调用 legacy full runner；
3. 不运行 legacy baseline，只比较 fixtures。

**Recommendation**

选择 1。Parity harness 在两个隔离运行间比较 semantic outcomes；canonical
运行不消费 legacy identifiers/refs。

**Why**

既保留行为基线，又防止 comparator 成为 truth root。

**Rejected Option**

2 再次绕过 Runtime；3 不能证明真实 fixed behavior parity。

### Conflict 8 — MRR-10 能否保持 benchmark entry untouched？

**Current Source Fact**

`fixed_answer_runner.py::run_fixed_answer_benchmark_family()` 当前直接调用
`run_smoke()`；`run_fixed_answer_internal_carrier_compare_suite()` 也依赖该 family。
MRR-10 的 provider/facade 可以在 runtime 层完成，不要求修改 benchmark caller。

**Options**

1. MRR-10 不改 benchmark；用 runtime-level integration/parity harness 验证；
2. 同时切换 fixed benchmark entry；
3. 删除 `run_smoke`。

**Recommendation**

选择 1。

**Why**

provider authority convergence 与 benchmark ownership 独立；入口迁移留在后续
阶段不会阻止 MRR-10 证明 canonical runtime path。

**Rejected Option**

2 越界进入 MRR-11；3 违反 Compatibility Bridge First 和本轮 hard rule。

## 3. Source Gate blueprint

Source Gate 必须以 code review + targeted contract assertions 证明：

1. 三个真实 role provider entry 都接收 current `BoundCapabilityGrant` 和
   Runtime-supplied attempt workspace；没有 `RuntimeSessionManager.create_attempt`
   或等价 Attempt creation；
2. provider source 不 import/invoke next role、`AdaptiveRuntimeEngine.run()`、
   `RolePathRunner` orchestration、Memory store lookup/commit、artifact verifier 或
   state store direct authority；
3. physical client 由 `bound_grant.provider_id/provider_version` 映射，role config
   不能覆盖；
4. provider 只返回 candidate `AdaptiveStepResult` / typed proposal；没有
   authoritative VERIFIED、Memory admission 或 result settlement；
5. fixed compatibility wrapper 只翻译 request/bindings 并 delegate 到
   `AdaptiveMainlineRunner`，不循环 steps、不创建 Attempt、不调用 next role；
6. legacy `RolePathRunner` / `run_smoke` 不被 canonical fixed path import/call。

静态字符串检查只能作辅助证据；Gate 的主要证据必须来自 current Attempt/
Binding/Grant 的运行时断言。

## 4. Mechanism Gate blueprint

Mechanism Gate 不能使用 `fixed_mainline.py` 当前 `_compatibility_result()` fake
refs 作为成功证据。必须实际运行：

```text
retriever:
  RolePath evidence/candidate prompt + parser
  + registered retrieval callable / AdaptiveRetrievalAdapter

executor:
  RolePath executor decision / TransformProgram or CodeAct candidate
  + registered dispatcher execution path

summarizer:
  RolePath summary/ClaimSet prompt + parser
  + ClaimSetValidator / verified input path
```

每个 role 的 mechanism run 必须恰好属于一个 current Attempt；失败时返回
candidate failure，不在 provider 内重复完整 role call。

## 5. Integration Gate blueprint

一个 representative fixed task 必须真实经过：

```text
RuntimeIdentity / TaskContract
  → StaticRoleRecipe
  → PlanProposal / normalization / policy
  → ApprovedPlanBundle
  → one AdaptiveMainlineRunner
  → one AdaptiveRuntimeEngine authority
  → retriever
  → executor
  → summarizer
```

断言：

- 三个 role 具有同一个 `RuntimeTaskID` 和同一 canonical session lineage；
- 三个 role 具有 distinct current `StepAttemptRecord.attempt_id`；
- 每个 provider call 都有匹配 step/capability/provider 的 Runtime-issued
  `ExecutionBindingReceipt` 和 `BoundCapabilityGrant`；
- downstream input ref 来自 upstream admitted result，不来自 legacy smoke；
- executor Artifact 先 candidate 后 Runtime verification；
- summarizer 只读 verified ref；
- final completion 来自 Runtime admission/settlement。

## 6. Parity Gate blueprint

legacy comparator 与 canonical fixed path 使用同一个 logical task input，但必须
隔离 runtime roots 和 identifiers。比较：

```text
logical role order
semantic role output classes
selected route/tool semantics when applicable
Artifact verification outcome class
Memory outcome class
final semantic result class
```

不比较：timing、UUID、Attempt IDs、token/byte counts、prefix cache counters、
logit serialization、manifest path、telemetry ordering或 raw prompt bytes。

legacy pass 不能覆盖 canonical failure；canonical Gate 必须先独立满足 Source、
Mechanism 和 Integration invariants。

## 7. Test blueprint

实现阶段最多使用三个 primary targeted tests 和一个 adjacent regression：

1. **Primary — one-step provider authority contract**：真实 retriever/executor/
   summarizer adapters 分别在 Runtime-issued `BoundCapabilityGrant` 下执行一次；
   spy 证明无 Attempt creation、next-role call、provider override、State/Memory/
   Artifact commit。
2. **Primary — canonical fixed full-graph integration**：representative task 经
   `StaticRoleRecipe` / `ApprovedPlanBundle` / `AdaptiveMainlineRunner` /
   `AdaptiveRuntimeEngine` 完成三角色链，断言同 RuntimeTaskID、distinct Attempts、
   matching bindings/grants、artifact verification/result admissions。
3. **Primary — semantic parity**：隔离运行 legacy comparator 与 canonical fixed
   path，比较 role order、role-local semantics、route/tool、Artifact outcome、
   Memory outcome 和 final answer class。
4. **Adjacent regression（最多一个）**：现有 prompt/parser/config compatibility，
   覆盖 structured handoff 和 deterministic/local-vLLM request semantics，但不
   要求 telemetry byte equality。

本设计轮不运行这些测试。

## 8. Slice entry and exit

### MRR-10A entry

- frozen MRR-01–09 contracts可直接使用；
- current dispatcher role seams 和 RolePath methods 已定位；
- no benchmark changes required。

### MRR-10A exit

- real one-step providers exist and receive `BoundCapabilityGrant`；
- provider selection, retry, State/Memory/Artifact truth 留在 Runtime；
- Mechanism Gate + one-step Source Gate pass。

### MRR-10B entry

- 10A accepted；
- fixed recipe/plan bundle compile path remains frozen。

### MRR-10B exit

- fixed facade delegates to one Mainline/Engine full graph；
- no canonical import/call to legacy full RolePath/smoke orchestration；
- Integration Gate + Parity Gate pass；
- benchmark entry remains untouched。

## 9. Final Design Decision

```text
MRR-10 READINESS
================

RolePath as Runtime:
REJECTED

RolePath as Plan/Prompt/Provider Compatibility Source:
ACCEPTED

Canonical Execution Authority:
AdaptiveRuntimeEngine

Canonical Product Assembly:
AdaptiveMainlineRunner

Static Fixed Plan:
StaticRoleRecipe / ApprovedPlanBundle

Provider Adapter Extraction:
REQUIRED

Compatibility Facade:
REQUIRED

RolePathRunner Final Form:
B — reusable helpers/providers extracted; RolePathRunner legacy-only

run_smoke:
LEGACY_COMPARATOR for MRR-10

MRR-10 Slice Structure:
MRR-10A + MRR-10B

MRR-10 Implementation Readiness:
READY

Competition Gate:
UNVALIDATED
```

Competition status marker：`COMPETITION_GATE_UNVALIDATED`。

`READY` 表示 design/source boundary 已足以进入以后经授权的 implementation，
不表示 MRR-10 已实现或已通过 Gate。
