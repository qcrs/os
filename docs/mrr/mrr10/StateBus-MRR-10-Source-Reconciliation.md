# StateBus MRR-10 — Source Reconciliation

> 这是设计/source review，不是 implementation record。本文以当前 checkout
> 的 source fact 为准，不使用 Git history、SHA 或旧设计替代当前代码。

## 1. Review scope and source authority

本轮读取并交叉检查了：

- `statebus/runtime/role_path.py`
- `statebus/runtime/smoke.py`
- `statebus/runtime/driver.py`
- `statebus/runtime/compiler.py`
- `statebus/runtime/static_role_recipe.py`
- `statebus/runtime/fixed_mainline.py`
- `statebus/runtime/adaptive_mainline.py`
- `statebus/runtime/adaptive_runtime.py`
- `statebus/runtime/adaptive_dispatcher.py`
- `statebus/runtime/provider_registry.py`
- `statebus/runtime/retrieval_adapter.py`
- `statebus/runtime/domain_packs.py`
- `statebus/runtime/logit_gate.py`
- `statebus/integrations/llm.py`
- `statebus/benchmark/fixed_answer_runner.py`

冻结 authority 仍来自 MRR-01 至 MRR-09：`RuntimeIdentity`、
`TaskContractIdentity`、`PlanProposal`、`PlanNormalizationReceipt`、
`PlanPolicyReport`、`ApprovedPlanBundle`、`RuntimeTaskSession`、
`StepAttemptRecord`、`AttemptResultAdmissionReceipt`、
`ProviderEligibilityProjection`、`ExecutionBindingReceipt`、
`CapabilityGrant`、`BoundCapabilityGrant`、`StateAccessGrant`、`StatePin`、
`ArtifactVerificationReceipt`、`MemoryAdmissionReceipt`、
`ReplayEligibilityReceipt` 和 `MemoryConsumptionRecord` 均不在 MRR-10 重定义。

## 2. Executive finding

当前不是“RolePath 接入 Adaptive Runtime”这么简单。`run_smoke` 的真实顺序是：

```text
TaskCompiler
  → RolePath planner
  → direct retrieval fan-out
  → direct semantic State publication/consumption
  → RolePath retriever
  → RolePath executor decision
  → optional logit retry
  → direct CodeAct execution
  → RolePath summarizer
  → output Artifact materialization
  → MemoryCommit construction / lookup effects
  → legacy RuntimeDriver.run()
```

因此在 `RuntimeDriver` 启动前，RolePath/smoke 已经决定了角色顺序、重试后的
executor decision、执行输出、summary、Artifact 文件、Memory candidate 和
State transport。后面的 `RuntimeDriver` 再创建自己的 session/attempt/control/
commit，形成两套 execution authority。该现状违反 canonical architecture。

`AdaptiveMainlineRunner`、`AdaptiveRuntimeEngine`、`AdaptiveCapabilityDispatcher`
已经提供了目标 authority；但 `fixed_mainline.py` 当前的
`deterministic_retrieve_handler`、`deterministic_execute_handler`、
`deterministic_summarize_handler` 只是 deterministic compatibility handlers，
并未承载现有真实 RolePath/CodeAct/retrieval/summarizer mechanism。因此它们
可以证明 canonical wiring，不足以通过 MRR-10 Mechanism Gate。

## 3. RolePathRunner responsibility inventory

### 3.1 Current ownership truth

以下每行都是 `CURRENT_SOURCE_FACT`。`RolePathRunner` 本体与把它变成完整 fixed
链的 `run_smoke` / legacy Driver 分开标记，避免把 caller authority 错算成一个
纯 role method 的内部行为。

| Responsibility | `CURRENT_SOURCE_FACT` |
| --- | --- |
| plan proposal | **YES in RolePathRunner** — `propose_plan()` 返回 `PlanProposal`；`plan_workflow()` 返回旧 semantic `PlannerRoleResult`，不是 approved plan |
| prompt rendering | **YES in RolePathRunner** — `_render_prompt()`、role instructions、`RolePromptSlice` 和 prefix layout |
| retriever candidate decision | **YES in RolePathRunner** — `choose_retrieval_candidate()` 选择并校验 candidate/route/tool |
| executor decision validation | **YES in RolePathRunner** — `validate_execution_choice()` 产生 action decision 和 logit diagnostics |
| summarizer completion | **YES in RolePathRunner** — `summarize()`；另有 `build_claim_set()` / citation repair candidate |
| role sequencing | **NO in individual RolePath methods; YES in fixed RolePath chain** — `run_smoke()` 直接按 planner→retriever→executor→summarizer 调用 |
| next-role invocation | **NO in individual method; YES in caller** — smoke 在上一步返回后显式调用下一 role；legacy Driver 也推进 step |
| retry/fallback | **YES** — `_complete_json_role()`、retriever/executor selection loops；smoke logit retry；legacy Driver fallback/replan |
| provider/model selection | **YES in surrounding RolePath LLM path** — smoke 按 role 构造 clients，`LLMConfig.roles[role]` 指定 provider/model，client 再选 endpoint |
| LLM request construction | **YES through integration helper** — RolePath 传 prompt/schema，`OpenAICompatibleLLMClient.complete()` 构造 physical request |
| structured response parsing | **YES in RolePathRunner/helpers** — JSON/tagged parsers和 per-role schemas |
| State read/write | **NO direct State API in RolePathRunner; YES in fixed chain** — smoke 在 canonical Runtime 前 publish/read dense semantic State |
| Artifact creation | **NO direct Artifact authority in RolePathRunner; YES in fixed chain** — smoke 在 Driver 前 materialize output bundle和manifest |
| Memory lookup/write | **NO direct Memory API in RolePathRunner; YES in fixed chain** — smoke lookup/seed/current commit，Driver 持久化 |
| prefix/logit instrumentation | **YES across RolePathRunner + smoke** — prefix layout/audit/logit extraction；smoke `retry_once` 还能改变 decision |
| final result assembly | **NO in individual RolePath methods; YES in fixed chain** — smoke 合并 executor/summarizer payload，Driver settle/reload，smoke 返回 final result |

### 3.2 Five-way classification

分类只能是下列五项之一：`REUSE`、`MOVE_TO_RUNTIME`、
`ADAPT_AS_PROVIDER`、`KEEP_LEGACY_COMPARATOR_ONLY`、`DELETE_LATER_MRR13`。

| Responsibility | `CURRENT_SOURCE_FACT` | Classification | Target owner / boundary |
| --- | --- | --- | --- |
| Planner prompt / semantic planning | `RolePathRunner.plan_workflow()` 在 `role_path.py:1723` 渲染 planner prompt，调用 `_complete_json_role`，返回 `PlannerRoleResult`；`propose_plan()` 在 `:2235` 返回不可信 `PlanProposal` | `ADAPT_AS_PROVIDER` | 作为 `PlanSource` / planner adapter；只返回 `PlanProposal` 或 semantic planning candidate，不返回 ApprovedPlan、Attempt、Grant |
| Fixed topology | `StaticRoleRecipe` 在 `static_role_recipe.py` 固定三步 topology，并由 `compile_static_role_recipe_plan()` 生成 `ApprovedPlanBundle` | `REUSE` | `StaticRoleRecipeCompiler` 是 fixed plan source；不得让 RolePath 重写 topology |
| Prompt templates / rendering | `_render_prompt`、role instructions、`RolePromptSlice`、prefix helpers 和 candidate schemas 分散在 `role_path.py` / `smoke.py` | `REUSE` | provider adapter 的纯输入编译和 sideband audit；不拥有顺序 |
| Retrieval candidate decision | `choose_retrieval_candidate()` `:1794` 构造 visible candidate surface，调用 LLM，校验 route/tool/candidate | `ADAPT_AS_PROVIDER` | 当前 retriever Attempt 的 provider adapter；返回 candidate/route diagnostic，不能选下一角色或 physical provider |
| Evidence request | `build_evidence_request()` `:2470` 生成有 scope 的 `EvidenceRequest` | `ADAPT_AS_PROVIDER` | retriever provider 的 untrusted request candidate；`AdaptiveRetrievalAdapter` 和 coverage authority 执行/验证 |
| Executor decision validation | `validate_execution_choice()` `:1916` 调用 LLM，可能进行 logit recheck，返回 `ExecutorRoleDecision` | `ADAPT_AS_PROVIDER` | executor provider 的 current-step decision candidate；route/tool eligibility 和 execution binding 由 Runtime 解释 |
| Transform / CodeAct proposal | `build_transform_program()` `:2548` 生成 `TransformProgram`；smoke 随后直接调用 CodeAct | `ADAPT_AS_PROVIDER` | executor adapter 返回 typed program/action candidate；`AdaptiveCapabilityDispatcher` 执行并返回 artifact candidate |
| Summarizer completion | `summarize()` `:2156` 调用 LLM 返回 summary；`build_claim_set()` `:2631` 生成 ClaimSet，`repair_claim_citations()` `:2767` 做 citation repair | `ADAPT_AS_PROVIDER` | summarizer adapter 只消费当前 Grant 授权 refs，返回 claim/current result candidate |
| Role sequencing | `run_smoke` 按 planner→retrieval→executor→summarizer 直接调用；`RuntimeDriver` 又有 `_run_non_executor_step()` | `MOVE_TO_RUNTIME` | `ApprovedPlanBundle` + Engine READY-set；RolePath 不得 method-chain |
| Next-role invocation | smoke 中 executor 结束后显式进入 summarizer；legacy Driver 的 control loop 也推进下一 step | `MOVE_TO_RUNTIME` | `AdaptiveRuntimeEngine.run()` 的 step loop / dependency readiness |
| Retry / malformed JSON attempts | `_complete_json_role()` 按 `json_response_max_attempts` 重试；smoke 的 logit gate 会再次调用 executor；Driver 有 attempt retry/fallback/replan | `MOVE_TO_RUNTIME` | Runtime failure policy 决定 Attempt retry/rebind/replan/fallback；provider 单次失败只返回 `error_code` / `retryable` 和 non-authoritative diagnostic |
| Route/tool/provider selection | RolePath 选择 candidate route/tool；`LLMConfig.roles[role].provider/model` 与 `RoleDispatchLLMClient` 选择 physical client | `MOVE_TO_RUNTIME` | `ProviderEligibilityProjection` + `ExecutionBindingReceipt`；route/tool 只能作为 logical candidate / diagnostic |
| LLM request construction | `OpenAICompatibleLLMClient.complete()` 构造 request、schema、headers、model，并按 role config 选 provider | `REUSE` | 保留 single-call physical request construction；adapter 必须使用 Runtime-issued binding，不得从 role config 自行决定 authority |
| LLM completion retry | `_create_completion_with_retry()` 会重发 completion，并可能做 context-window adjustment | `KEEP_LEGACY_COMPARATOR_ONLY` | canonical provider 返回 failure metadata；fresh logical retry 只能由 Runtime 发起 |
| Structured response parsing | `extract_json_object`, `parse_tagged_json`, `tagged_json_block` 和各 role schema | `REUSE` | pure parser/schema helper；parse failure 变成 provider diagnostic |
| Direct semantic State publication / read | smoke 直接调用 dense state publish/consume，并把 semantic state ref 写入后续 payload | `MOVE_TO_RUNTIME` | `RuntimeStateAccessAuthority` + `StateAccessGrant` / `StatePin`；provider 只能消费当前 Attempt 授权 ref |
| Artifact candidate content | executor/summarizer 产生 output payload、ClaimSet、summary；dispatcher 已有 candidate artifact path | `ADAPT_AS_PROVIDER` | provider 返回 candidate content/ref；不带 authoritative verification |
| Artifact workspace materialization | smoke 在 Driver 前直接 materialize `summary_json`、logs 和 manifest | `MOVE_TO_RUNTIME` | current Attempt workspace + dispatcher/Runtime artifact lifecycle |
| Artifact verification | smoke 先构造 validator reports/quality floor；legacy Driver 另有 `RuntimeCommitGate` | `MOVE_TO_RUNTIME` | `ArtifactVerificationReceipt` / RuntimeArtifactVerificationAuthority |
| Memory lookup / replay selection | smoke 直接 `MemoryIndexStore.lookup_hybrid`、构造 `MemoryCommit` 和 `replay_ready` metadata | `MOVE_TO_RUNTIME` | Engine `_select_memory_for_attempt`、`ReplayEligibilityReceipt`、Dispatcher grant-scoped memory inputs、Mainline memory admission |
| Memory write / commit | smoke 构造 `current_memory_commit`；legacy Driver 负责 commit/replay ledger | `MOVE_TO_RUNTIME` | `MemoryAdmissionReceipt` + `MemoryConsumptionRecord`；`AdaptiveMainlineRunner._commit_verified_memory()` |
| Prefix layout / prompt hydration | `compile_prefix_layout`、shared prefix、prompt slices、vLLM prefix metrics | `REUSE` | provider sideband / request audit；遵守 control-plane-only/no KV tensor export claim |
| Logit extraction | executor decision 携带 exact logit result/candidate surface | `REUSE` | inline diagnostic evidence sideband；不能直接授权 binding/commit |
| Logit State transport | `logit_gate.py::run_logit_gate_attempt()` 创建独立 State store，直接 publish/read/release logit State；canonical `RuntimeStateAccessAuthority` 当前只给受限 retrieval dense semantic State 明确 hook | `KEEP_LEGACY_COMPARATOR_ONLY` | canonical provider 不复用该 direct State path；logit evidence inline 返回 sideband |
| Logit retry / gate action | smoke 在 gate 非 accept 时重新调用 executor，改变后续 execution choice | `MOVE_TO_RUNTIME` | Runtime policy/hook；若仅 telemetry，则不得改变 control path |
| Final result assembly | smoke 合并 executor payload + summary，写 output；Driver 又 settle/reload；`SmokeResult` 暴露 legacy truth | `MOVE_TO_RUNTIME` | `AttemptResultAdmissionReceipt`、Runtime completion、下游 final adoption；legacy output 仅 comparator |
| Audit / telemetry | `rendered_request_audit`、runtime metrics、prefix/logit audit、benchmark metrics | `REUSE` | sideband evidence；不成为 authority root |
| Legacy orchestration shell | `RolePathRunner` 与 `run_smoke` 将上述步骤串成可运行 fixed path | `KEEP_LEGACY_COMPARATOR_ONLY` | MRR-10 保留 comparator；MRR-13 后可删除 legacy-only surface，当前不做 cleanup |

上述分类意味着：任何能影响 Attempt、Binding、Grant、State、Memory、Artifact
truth 或最终 adoption 的逻辑都不能以 RolePath compatibility logic 的形式继续
拥有 authority。

## 4. Planner adjudication

当前有两种 planner 语义，必须分开：

1. `plan_workflow()` 是旧 fixed path 的 semantic planner。它返回
   `PlannerRoleResult`，其 prompt 明确要求 semantic task plan，而不是 workflow /
   DAG / route / tool。它适合保留为 semantic `PlanSource` 输入，但不是
   `ApprovedPlanBundle`。
2. `propose_plan()` 已经将结果类型写成 `PlanProposal`，并带有
   `on_failure` hints。它可以适配成 planner provider，但 policy approval 仍由
   `PlanNormalizationReceipt`、`PlanPolicyReport` 和 `ApprovedPlanBundle` 完成。

固定三角色 topology 不应依赖 LLM planner。`StaticRoleRecipeCompiler` 已是
provider-neutral fixed source；若为了复现旧 prompt 语义保留 planner，planner
只能补充 task-specific objective、input wiring 或 untrusted step candidates，不能
改变 `retriever → executor → summarizer` 的 frozen topology。

## 5. Current smoke path reconstruction

### PRE_RUNTIME_EXECUTION

按当前 source，`run_smoke()`（`smoke.py:2172`）在调用 `RuntimeDriver` 前完成：

```text
TaskCompiler.compile
  → LLMConfig.from_runtime
  → build_llm_client per role
  → RoleDispatchLLMClient
  → RolePathRunner
  → plan_workflow
  → planner_retrieval_objective
  → RetrieverFanoutPipeline / retrieval bundle
  → optional dense semantic State publish + subprocess consume
  → role prompt hydration / prefix layout
  → choose_retrieval_candidate
  → validate_execution_choice
  → optional run_logit_gate_attempt + executor re-call
  → CodeAct execution
  → summarize
  → output payload / output hash
  → workspace artifact materialization
  → validator reports / quality floor
  → MemoryIndexStore lookup/replay selection
  → MemoryCommit candidate construction
```

这里已经发生了实际 retrieval、execution、summary、State transport、Artifact
materialization 和 Memory decision。它们不是只读 preparation。

### RUNTIME_EXECUTION

随后 `smoke.py:3445` 构造 `RuntimeDriverInput` 调用 legacy
`RuntimeDriver().run()`（`driver.py:322`）。Driver 再自行：

```text
创建 legacy RuntimeSession
  → planner/retriever/executor/summarizer step control
  → 创建/激活 Attempt
  → ACK / run / heartbeat / trap / error / success control messages
  → executor retry / fallback / replan paths
  → RuntimeCommitGate / memory ledger / persistence
  → reload / settle
```

这是第二套 execution authority，不是 `AdaptiveMainlineRunner` / `AdaptiveRuntimeEngine`
的 canonical invocation。

### POST_RUNTIME_ASSEMBLY

Driver 返回后，smoke 继续把 expected facts、route/tool、artifact state、memory
replay class、metrics 和 audit 组装成 `SmokeResult`。这一步可以保留为 legacy
comparator 输出，但不能把它写回 canonical Attempt/Grant/State/Memory truth。

## 6. Canonical target call chain

```text
fixed case
  → RuntimeIdentity / TaskContractIdentity
  → StaticRoleRecipe
  → StaticRoleRecipeCompiler
  → PlanProposal
  → PlanNormalizationReceipt
  → PlanPolicyReport
  → ApprovedPlanBundle
  → AdaptiveMainlineRunner
  → AdaptiveRuntimeEngine
      READY retriever
        → Runtime-issued Attempt / Binding / BoundCapabilityGrant
        → RolePathRetrieverProvider
        → candidate evidence result
        → AttemptResultAdmissionReceipt / State admission as required
      READY executor
        → Runtime-issued Attempt / Binding / BoundCapabilityGrant
        → RolePathExecutorProvider
        → candidate Artifact
        → Runtime verification / result admission
      READY summarizer
        → Runtime-issued Attempt / Binding / BoundCapabilityGrant
        → RolePathSummarizerProvider
        → current result candidate
        → Runtime admission / completion
```

各 gap：

| Current source | Gap | Canonical target |
| --- | --- | --- |
| `run_smoke` 直接调用 `RolePathRunner` | role calls 早于 Attempt/Binding/Grant | provider adapter 只能由 `AdaptiveCapabilityDispatcher` 在 current Attempt 内调用 |
| `RetrieverFanoutPipeline` 先于 Engine | retrieval 与 step readiness 脱钩 | retriever capability 的 dispatcher handler / adapter |
| `CodeActRequest` 直接执行 | executor output 先成为 smoke artifact | executor provider 返回 candidate，Runtime verification 后才成为 truth |
| `current_memory_commit` 在 smoke 中构造 | bypass Memory admission/replay eligibility | Engine + Mainline Batch 4 path |
| `LLMConfig.roles[role].provider` | physical provider choice 在 role path | binding-selected physical implementation |
| `RuntimeDriver.run()` | legacy second authority | `AdaptiveMainlineRunner.run()` → `AdaptiveRuntimeEngine.run()` |
| `fixed_mainline.py` deterministic handlers | canonical wiring 尚无真实 role mechanism | 10A 将真实 role-local mechanisms 接入 one-step provider |

## 7. File-level migration map

| Current file / symbol | Current responsibility | Target owner | Action / category |
| --- | --- | --- | --- |
| `role_path.py::RolePathRunner._render_prompt`、role instructions、schema helpers | prompt construction | provider adapter / PlanSource | `REUSE` |
| `role_path.py::RolePathRunner.plan_workflow` | semantic planner completion | PlanSource / planner adapter | `ADAPT_AS_PROVIDER` |
| `role_path.py::RolePathRunner.propose_plan` | untrusted adaptive plan proposal | PlanSource | `ADAPT_AS_PROVIDER` |
| `role_path.py::build_evidence_request` | retriever request candidate | retriever provider | `ADAPT_AS_PROVIDER` |
| `role_path.py::choose_retrieval_candidate` | route/tool/candidate selection | retriever provider + Runtime binding boundary | `ADAPT_AS_PROVIDER`; physical binding `MOVE_TO_RUNTIME` |
| `role_path.py::validate_execution_choice` | executor decision / logit recheck | executor provider | `ADAPT_AS_PROVIDER`; retry control `MOVE_TO_RUNTIME` |
| `role_path.py::build_transform_program` | typed execution candidate | executor provider / dispatcher | `ADAPT_AS_PROVIDER` |
| `role_path.py::summarize`、`build_claim_set`、`repair_claim_citations` | summary / claim candidate | summarizer provider | `ADAPT_AS_PROVIDER` |
| `integrations/llm.py::extract_json_object`、`parse_tagged_json`、`tagged_json_block` | structured output parse | shared compatibility helper | `REUSE` |
| `role_path.py::rendered_request_audit` / prefix helpers | audit and prefix sideband | provider sideband | `REUSE` |
| `smoke.py::run_smoke` | full legacy orchestration and pre-runtime truth | canonical mainline only after future bridge; MRR-10 comparator | `KEEP_LEGACY_COMPARATOR_ONLY` |
| `smoke.py` direct State publication/consume | semantic State access | `RuntimeStateAccessAuthority` | `MOVE_TO_RUNTIME` |
| `smoke.py` direct Memory lookup / `MemoryCommit` | memory selection/commit | Engine + Batch 4 Mainline | `MOVE_TO_RUNTIME` |
| `smoke.py` output materialization / validator reports | artifact candidate and apparent quality truth | dispatcher candidate + Runtime verification | `ADAPT_AS_PROVIDER` for candidate; truth `MOVE_TO_RUNTIME` |
| `logit_gate.py::run_logit_gate_attempt`（由 `smoke.py` 调用） | direct logit State publish/transport/evaluation；smoke 决定是否 retry | legacy comparator；canonical sideband/control policy | direct State path `KEEP_LEGACY_COMPARATOR_ONLY`; retry action `MOVE_TO_RUNTIME` |
| `driver.py::RuntimeDriver.run` | legacy session, sequence, attempts, retries, commit | `AdaptiveRuntimeEngine` | `KEEP_LEGACY_COMPARATOR_ONLY`; authority logic `MOVE_TO_RUNTIME` |
| `driver.py::_run_non_executor_step` | planner/retriever/summarizer Attempt sequencing | `AdaptiveRuntimeEngine` READY-set | `MOVE_TO_RUNTIME` |
| `driver.py::_exchange_control_messages`、`_build_loopback_message` | legacy protocol/control | canonical runtime/dispatcher contracts | `KEEP_LEGACY_COMPARATOR_ONLY` |
| `driver.py::_persist_and_reload` | legacy persistence/reload | canonical Mainline manifests and settlement | `KEEP_LEGACY_COMPARATOR_ONLY` |
| `compiler.py::TaskCompiler` | strict canonical task compilation | TaskContract input | `REUSE` |
| `static_role_recipe.py::StaticRoleRecipeCompiler` / `compile_static_role_recipe_plan` | fixed plan proposal and approval assembly | canonical Plan authority | `REUSE` |
| `fixed_mainline.py::build_fixed_mainline_request` | fixed compatibility request and registry | canonical assembly bridge | `ADAPT_AS_PROVIDER` after replacing deterministic handlers with real adapters |
| `fixed_mainline.py::deterministic_*_handler` | fake/deterministic one-step handlers | 10A provider implementations | `DELETE_LATER_MRR13` only for obsolete fake path; not a Mechanism Gate substitute |
| `adaptive_mainline.py::AdaptiveMainlineRunner.run` / `_assemble_plan` | product assembly and plan authority | canonical product assembly | `MOVE_TO_RUNTIME` / retain as frozen authority |
| `adaptive_mainline.py::_commit_verified_memory` | verified memory admission | Batch 4 canonical path | `MOVE_TO_RUNTIME` / retain |
| `adaptive_runtime.py::AdaptiveRuntimeEngine.run` | session, READY-set, attempts, binding, grant, admission | canonical execution authority | `MOVE_TO_RUNTIME` / retain |
| `adaptive_runtime.py::RuntimeStateAccessAuthority` | StateAccessGrant / StatePin | canonical State authority | `MOVE_TO_RUNTIME` / retain |
| `adaptive_runtime.py::_bind_provider`, `_issue_grant`, `_select_memory_for_attempt`, `_verify_artifact_candidates` | binding/grant/memory/artifact authority | frozen Batch 1–4 authority | `MOVE_TO_RUNTIME` / retain |
| `adaptive_dispatcher.py::dispatch` and role handlers | one already-approved capability execution | provider/dispatcher seam | `ADAPT_AS_PROVIDER` + Runtime validation |
| `adaptive_dispatcher.py::_memory_inputs_for_step` | grant-scoped Memory consumption | MRR-09C | `MOVE_TO_RUNTIME` / retain |
| `integrations/llm.py::LLMConfig` | physical provider/model config | physical implementation config | `REUSE`, but not selection authority |
| `integrations/llm.py::RoleDispatchLLMClient` | role→client dispatch | binding-aware adapter | `ADAPT_AS_PROVIDER`; no canonical role selection |
| `integrations/llm.py::OpenAICompatibleLLMClient.complete` | request construction and role-config provider lookup | bound physical provider implementation | request helper `REUSE`; provider lookup `MOVE_TO_RUNTIME` |
| `integrations/llm.py::_create_completion_with_retry` | network/transport retry | same invocation provider helper | `REUSE` only for transport retry; Attempt retry `MOVE_TO_RUNTIME` |
| `benchmark/fixed_answer_runner.py::run_fixed_answer_benchmark_family` | legacy caller of `run_smoke` | MRR-11 benchmark entry migration | read-only boundary in MRR-10 |
| `benchmark/fixed_answer_runner.py::run_fixed_answer_internal_carrier_compare_suite` | internal comparator | downstream comparator | read-only boundary in MRR-10 |

## 8. Authority migration map

| Current authority | Target authority |
| --- | --- |
| Role sequencing / next role | `ApprovedPlanBundle` dependencies + `AdaptiveRuntimeEngine` READY-set |
| Attempt creation | `RuntimeTaskSession` / `AdaptiveRuntimeEngine` |
| Retry / fallback / repair / replan | Runtime failure policy, bounded by envelope and plan step policy |
| Provider selection | `ProviderEligibilityProjection` + `ExecutionBindingReceipt` |
| Physical provider endpoint/model | binding-selected physical implementation using `LLMConfig` as configuration only |
| State publication/read | `RuntimeStateAccessAuthority` + `StateAccessGrant` / `StatePin` |
| Memory selection | Engine `_select_memory_for_attempt` + `ReplayEligibilityReceipt` |
| Memory consumption | `BoundCapabilityGrant.memory_ref_ids` + dispatcher MRR-09C path |
| Memory admission / write | `AdaptiveMainlineRunner._commit_verified_memory` + `MemoryAdmissionReceipt` |
| Artifact candidate | provider/dispatcher candidate output |
| Artifact verification | RuntimeArtifactVerificationAuthority + `ArtifactVerificationReceipt` |
| Result admission / commit | `AttemptResultAdmissionReceipt` and attempt settlement |
| Final adoption | separate downstream truth; not RolePath or comparator |

## 9. `run_smoke` and benchmark boundary

MRR-10 的阶段性定位：

```text
MRR-10 current run_smoke = LEGACY_COMPARATOR
future fixed compatibility entry = possible MRR-11 facade
canonical execution truth = never run_smoke
```

`fixed_answer_runner.py` 当前调用 `run_smoke`，并在其返回后进行 expected facts、
route/tool 和 internal carrier comparison。MRR-10 只记录这个 legacy caller 与
canonical target，不改变 benchmark ownership，不设计 MRR-11 migration。

| Boundary | Recorded call chain | MRR-10 action |
| --- | --- | --- |
| Legacy caller | `fixed_answer_runner.py::run_fixed_answer_benchmark_family()` → `run_smoke()` → legacy RolePath/Driver | read-only / comparator only |
| Canonical caller target | fixed case → `FixedMainlineRequest` → `build_fixed_mainline_request()` → `AdaptiveMainlineRunner` → `AdaptiveRuntimeEngine` | runtime target recorded；caller switch不在 MRR-10 |
| Internal comparator | `run_fixed_answer_internal_carrier_compare_suite()` → fixed-answer family → `run_smoke()` | read-only；不能授权 canonical run |

## 10. Final source decision

```text
RolePath as Runtime: REJECTED
RolePath as Plan/Prompt/Provider Compatibility Source: ACCEPTED
Canonical Execution Authority: AdaptiveRuntimeEngine
Static Fixed Plan: StaticRoleRecipe / ApprovedPlanBundle
Provider Adapter Extraction: REQUIRED
Compatibility Facade: REQUIRED, but authority-free
run_smoke: LEGACY_COMPARATOR in MRR-10
Competition Gate: UNVALIDATED
```
