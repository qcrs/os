# StateBus MRR-10 — RolePath Compatibility Deep Design

## 1. Design invariant

MRR-10 的唯一方向是把 RolePath 中可复用的 recipe、prompt、parser、physical
provider integration 和 role-local mechanism 放到 canonical Runtime 的既有
seam 后面：

```text
StaticRoleRecipe
  → PlanProposal
  → PlanPolicy
  → ApprovedPlanBundle
  → AdaptiveMainlineRunner
  → AdaptiveRuntimeEngine
  → Attempt / ExecutionBindingReceipt / BoundCapabilityGrant
  → exactly one role-local provider execution
  → candidate AdaptiveStepResult
  → Runtime admission / verification / commit
```

Compatibility code 可以 `adapt`、`translate`、`delegate`、`compare`，但不能
`authorize`、`schedule` 或 `commit`。本设计不引入 `RoleRuntime`、
`FixedRuntime`、`RolePathRuntime` 或 `CompatibilityRuntime`。

## 2. Provider adapter boundary

### 2.1 Common one-step contract

每个 RolePath provider adapter 必须接收由 Engine 为当前 Attempt 发出的
`BoundCapabilityGrant`，并遵循：

```text
Input:
  current RuntimeIdentity
  current approved Plan step
  current StepAttemptRecord identity
  current BoundCapabilityGrant
  only Grant-authorized input_ref_ids / memory_ref_ids
  attempt workspace supplied by Runtime

May:
  render deterministic role-local prompt
  invoke the provider selected by ExecutionBindingReceipt
  parse/validate a structured role-local candidate
  emit request audit, confidence, logit and prefix sideband
  return one candidate AdaptiveStepResult

Must not:
  create or activate Attempt
  invoke another role
  choose a physical provider/model independent of the binding
  issue or widen a Grant
  query Memory outside grant.memory_ref_ids
  publish/read State without StateAccessGrant
  mark Artifact VERIFIED
  admit Memory
  settle or commit a result
  retry/rebind/replan/fallback on its own
```

当前 `AdaptiveCapabilityDispatcher.dispatch()` 已要求 outer input 是
`BoundCapabilityGrant`，并在 `_validate_dispatch()` 验证 binding；但是现有
`RetrievalRequestFactory`、`TransformProgramFactory`、`ClaimSetFactory` 和
`BuiltinHandler` 多数只接收降级后的 plain `CapabilityGrant`。MRR-10A 必须闭合
这个 seam：真实 RolePath provider entry 应可核验并接收完整
`BoundCapabilityGrant`，而不是把 provider identity 只留在 dispatcher 外层。
这是 source-confirmed gap，不是重新设计 MRR-04。

### 2.2 Retriever provider

建议名称：`RolePathRetrieverProvider`，但命名不是新 authority。

它复用：

- retriever prompt/schema 和 `RolePromptSlice` formatting；
- `build_evidence_request()` 的 bounded query candidate；
- `choose_retrieval_candidate()` 的 visible surface parser/validation；
- `AdaptiveRetrievalAdapter` 作为实际 registered retrieval mechanism。

它只执行当前 retriever Step。`route`、`tool_name`、`candidate_rank` 是 candidate
diagnostic；actual logical capability 已由 approved step 指定，physical provider
已由 binding 指定。provider 不能借这些字段改写 capability 或选择下一角色。

输出应投影为：

```text
AdaptiveStepResult
  success / error_code / retryable
  current attempt_id
  current grant_hash
  canonical evidence candidate ref
  evidence coverage report hashes
  diagnostic metadata
```

Evidence coverage 和 State publication 仍由 dispatcher/Runtime authority
验证。provider 不产生 authoritative evidence completion，也不直接 publish
semantic State。

### 2.3 Executor provider

建议名称：`RolePathExecutorProvider`。

它复用：

- executor prompt/schema；
- `validate_execution_choice()` 的 role-local decision parsing；
- `build_transform_program()` 的 typed candidate generation；
- 必要时现有 CodeAct prompt/code-source helper。

它不直接执行 `run_smoke` 中 procedural CodeAct chain。实际 execution 必须走
当前 dispatcher 的 registered execution kind：`TRANSFORM_DSL`、
`LLM_BOUNDED_PYTHON` 或经 registry 明确绑定的 handler。provider 返回 program/
code/decision candidate；dispatcher 在 current Attempt、Grant、workspace 和
validator scope 内执行。

executor output 是 candidate Artifact。`ExecutionArtifactRef` 即便被创建，也
不能自行带 authoritative `VERIFIED` truth；Engine 的
`_verify_artifact_candidates()` 和 `ArtifactVerificationReceipt` 才是 truth root。

### 2.4 Summarizer provider

建议名称：`RolePathSummarizerProvider`。

它复用：

- `summarize()` 的 prompt semantics；
- `build_claim_set()` 的 structured ClaimSet candidate；
- `repair_claim_citations()` 的 citation-only candidate repair；
- deterministic formatting、tags、request audit。

它只能读取 `BoundCapabilityGrant.input_ref_ids` 中、已通过 Runtime verification
的 Artifact/Evidence refs，以及 `grant.memory_ref_ids` 中当前允许的 Memory。
当前 `_dispatch_summarizer()` 已对 verified artifact、single evidence pack、
scope 和 ClaimSet validator 做检查；MRR-10 应复用这条 authority path。

summary text、ClaimSet、confidence 和 reusable steps 都是 candidate/sideband。
最终 adopted answer 不是 provider truth。

## 3. Planner boundary

### 3.1 Static fixed topology

fixed path 的 plan source 是 `default_fixed_role_recipe()` / `StaticRoleRecipe`：

```text
retrieve  → retrieve_semantic_evidence_v1
execute   → extract_metric_series_v1
summarize → compose_cited_report_v1
```

`StaticRoleRecipeCompiler.compile()` 只生成 `PlanProposal`；
`compile_static_role_recipe_plan()` 经 normalization/policy 形成
`ApprovedPlanBundle` 并停止在 Runtime 之前。该边界已经符合 frozen plan
authority，MRR-10 不更改 topology。

### 3.2 RolePath planner compatibility

`plan_workflow()` 和 `propose_plan()` 必须采用不同迁移语义：

| Current method | Kept meaning | Prohibited meaning |
| --- | --- | --- |
| `plan_workflow()` | semantic goal/query/objective candidate，供 fixed recipe 的 prompt/input construction 使用 | workflow topology、role order、Attempt 或 retry authority |
| `propose_plan()` | untrusted `PlanProposal` source，可用于 adaptive planner lane | `ApprovedPlanBundle`、policy approval、provider binding、Grant |

`propose_plan()` 当前给 step 写入 `on_failure` hints。这些只能是 policy input；
Runtime 是否 retry/replan/fallback 必须根据 approved step、envelope budget 和当前
failure receipt 决定。

## 4. Sequencing, retry, fallback

### 4.1 Sequencing

Role order 唯一来自：

```text
ApprovedPlanBundle.approved_plan dependencies
  +
AdaptiveRuntimeEngine READY-set
```

Role provider 不持有 `next_role`，不接收下一角色 callable，也不把 output 直接
传给下一角色。它只返回 ref candidate，由 Runtime admission 后作为 dependency
output 进入下一 READY Step 的 Grant。

### 4.2 Retry taxonomy

当前 source 有三类重复执行：

| Current behavior | Fact | Target decision |
| --- | --- | --- |
| `_complete_json_role()` malformed JSON retry | 会再次调用 model，最多 `json_response_max_attempts` | 不得留在 provider authority；单次 provider execution 失败并返回 parse diagnostic / `retryable`，由 Runtime 决定新 Attempt |
| retriever/executor selection retry | `choose_retrieval_candidate()` / `validate_execution_choice()` 对 invisible/inconsistent selection 再发 `_selection_retry_prompt()` | 不得由 canonical provider 自循环；返回 bounded validation failure，Runtime 决定 fresh Attempt |
| deterministic candidate normalization | `_normalize_candidate_selection()` 可在不发新请求时规范 candidate fields；assisted correction 还能替换选择 | 纯格式/一致性 normalization 可 `REUSE`；改变 route/tool/candidate 的 assisted correction 必须显式成为 candidate diagnostic，不得静默授权 |
| `OpenAICompatibleLLMClient._create_completion_with_retry()` | 会对 provider request 重发，且可能做 context-window adjustment | current helper 可供 legacy comparator；canonical adapter 不得自行发起新的 semantic completion。仅不产生新 completion 的底层连接恢复可视为 transport detail |
| smoke logit `retry_once` | 明确再次调用 `validate_execution_choice()` 并可能替换 executor decision | 必须迁到 Runtime failure/policy hook；telemetry mode 可保留 sideband但不得影响 control |
| transform/code/claim repair candidate | dispatcher 已有 transform/code repair hooks；`repair_claim_citations()` 会再调用 summarizer LLM | repair 只能由既有 Runtime/dispatcher bounded hook 发起；provider 可提供 repair callable/candidate，但不能自行决定或循环。无现有 hook 时 fail closed |
| Driver executor retry/fallback/replan | 创建 legacy attempts 并推进 fallback DAG | 由 `AdaptiveRuntimeEngine` 的 fresh Attempt / bounded fallback / replan authority 取代 |

provider 最多返回：

```text
success = false
error_code
retryable
structured diagnostic through existing non-authoritative telemetry/data-plane evidence
```

当前 `AdaptiveStepResult` 已有 `error_code`、`retryable`、`metrics` 和
`data_plane_events`，MRR-10 不为 retry 另造 authoritative result contract。

Runtime 可以据此创建 fresh Attempt、重新 binding 并签发 fresh Grant。provider
不能重用 Attempt、静默换 model、静默修复 route 或直接调用 fallback role。
当前 source 没有发现独立的 alternate-model list；风险来自 role-config/provider
override 和 request retry。后续实现不得为“兼容”新增 fallback model。

## 5. Provider and model selection

### 5.1 Current fact

`LLMConfig.roles[role]` 当前含 `provider`、`model`；
`RoleDispatchLLMClient` 根据 role 找预建 client；
`OpenAICompatibleLLMClient.complete()` 再从 role config 查 provider endpoint、
credentials 和 model。这在 legacy path 中实际上同时承担 role-to-physical
provider/model selection。

### 5.2 Compatibility boundary

保留 `LLMConfig`、`ProviderConfig`、request builder 和 structured-response
schema，作为 physical implementation configuration。canonical adapter 的解析
顺序应是：

```text
ExecutionBindingReceipt.selected_provider_id/version
  → existing ExecutionProviderRegistry descriptor
  → preconfigured client/config keyed by bound provider identity
  → exactly one role-local invocation
```

`ExecutionBindingReceipt` 不需要新增 model/endpoint 字段。被选 provider identity
可以指向一个已经固定 model/endpoint 的 implementation config；这样不修改
MRR-04 contract。role name 只能用于 prompt semantics，不能再覆盖 binding。

下列方案被拒绝：

- adapter 先看 `LLMConfig.roles[role].provider` 再声称符合 binding；
- binding 一个 provider 后由 adapter fallback 到另一个 provider/model；
- 在 RolePath 中新增 second provider registry；
- 将 route/tool candidate 等同于 physical provider identity。

## 6. State compatibility

### 6.1 Current bypass

`run_smoke` 直接创建 `LayeredStateStore` 使用面，publish dense semantic state，
生成/传送 ref，并让 subprocess 读取，然后把结果交给后续 RolePath decision。
这些动作发生在 canonical Attempt/Binding/Grant 之前。

这不是 KV-cache tensor transfer。现有 prefix/KV 叙述必须继续限定为
engine-local serving optimization；State ref 是显式 semantic/data reference。

### 6.2 Target

```text
retriever provider result candidate
  → RuntimeStateAccessAuthority.publish_dense_semantic_state
  → attempt-bound StateAccessGrant
  → StatePin / lifetime record
  → authorized consumer read
  → settlement / release
```

provider 接收 current Grant，不接收 raw store authority。需要 State 时，通过
Runtime 提供的 access seam 取得 `StateAccessGrant`；不能保存跨 Attempt 的裸
handle，不能自行 extend lifetime，也不能把 State ref 写入 Memory 当作 replay
authority。

## 7. Artifact compatibility

### 7.1 Current bypass

smoke 在 Driver 前形成 executor payload、summary JSON、artifact manifest、
materialized files、validator reports 和 quality floor。legacy Driver 再通过
`RuntimeCommitGate` 处理这些已经存在的输出。

### 7.2 Target

```text
RolePath Executor/Summarizer provider
  → candidate output / candidate Artifact ref
  → AdaptiveStepResult
  → AttemptResultAdmissionReceipt
  → RuntimeArtifactVerificationAuthority
  → ArtifactVerificationReceipt
  → eligible committed/consumed Artifact truth
```

Provider 可以声称 `candidate`, `confidence`, `validation_hint`，不能写
`VERIFIED` authority。summarizer 只能消费 Runtime 已验证且在 current Grant
input scope 中的 Artifact。

## 8. Memory compatibility

### 8.1 Current bypass

smoke 自行建立 query embedding、调用 Memory store lookup、决定 replay path，
构造 `MemoryRef` / `MemoryCommit`，并在 metadata 中写 `replay_ready`、
`execution_recipe`、State/Artifact refs。它发生在 canonical Engine memory
selection 之前。

### 8.2 Target

```text
historical admitted Memory
  → Engine candidate lookup
  → MemoryProjectionBinding / current compatibility checks
  → ReplayEligibilityReceipt
  → CapabilityGrant.memory_ref_ids
  → Dispatcher _memory_inputs_for_step
  → MemoryConsumptionRecord
  → current verified result
  → Mainline MemoryAdmissionReceipt
```

Role provider 不调用 `MemoryIndexStore.lookup_*`，不解释 `replay_ready` 为 truth，
不自行选择 historical artifact，不写 Memory。它只消费 Runtime 已放入
`grant.memory_ref_ids` 的 projection；缺少 authorization 时输入集合必须为空或
明确失败，而不是 fallback 到 legacy lookup。

## 9. Prefix, logit and telemetry

| Mechanism | Current effect | Target classification |
| --- | --- | --- |
| prefix layout / shared prefix | 改变 prompt packaging；采集 vLLM prefix metrics | provider request formatting + sideband，`REUSE` |
| engine-local prefix caching | serving engine 内优化 | telemetry only；不等同 hidden-state/KV tensor transfer |
| logit extraction / candidate surface | 记录 token/logprob/confidence evidence | provider sideband，`REUSE` |
| `run_logit_gate_attempt()` direct State transport | 独立 store 上 publish/read/release logit State，未走 current `RuntimeStateAccessAuthority`；该 authority 当前只明确允许受限 retrieval dense semantic State | `KEEP_LEGACY_COMPARATOR_ONLY`；canonical path 以内联 sideband携带 logit evidence |
| logit telemetry mode | 记录 accept/retry-recommended | benchmark/runtime diagnostic；不得改变 Attempt/Binding/commit |
| logit `retry_once` | 再调用 executor并替换 decision | `MOVE_TO_RUNTIME` |
| `rendered_request_audit` | runner 内 mutable audit list | 改为 per-invocation/per-attempt sideband，不能成为 global sequencing state |

只有 canonical Runtime 已有明确 hook 且 hook 仍受 current Attempt budget、binding
和 admission fencing 约束时，logit policy 才能影响执行。当前 source 没有
canonical logit StateAccessGrant hook，因此 MRR-10 不迁移 direct logit State
transport；canonical role provider 只返回 inline diagnostic evidence。

## 10. Result projection

现有 role-local schemas 可以无损投影到 `AdaptiveStepResult`，但要区分
authoritative fields 与 sideband：

| Role output | Canonical projection |
| --- | --- |
| retriever route/tool/candidate reason | telemetry / decision surface hash |
| EvidenceRequest / evidence result | candidate canonical evidence ref + coverage report hashes |
| executor action contract/program/code | registered execution input candidate + audit hashes |
| executor materialized output | candidate `execution_artifact` ref |
| summarizer ClaimSet/summary/confidence/tags | candidate cited-report ref + claim validation hashes + sideband |
| model/token/byte/latency/logit/prefix fields | metrics / telemetry only |
| parse or model failure | `success=false`, `error_code`, `retryable`；diagnostic 走既有非 authoritative telemetry/data-plane evidence |

不会丢失的语义包括 prompt output、route/tool candidate、reusable steps、confidence、
model usage 和 logit evidence；只是这些不再决定 canonical authority。

## 11. Compatibility facade decision

对 `RolePathRunner` 的最终选择是：

```text
B. 拆成 reusable helpers / one-step providers，RolePathRunner legacy-only
```

理由：

- A（保留 class 并内部 facade 到 canonical runtime）会继续让名称和 object
  lifetime 暗示 runner authority，而且现有 method surface 是逐角色方法，不是
  canonical fixed-entry request；
- B 可以让 prompt/parser/mechanism 共享，同时阻止 canonical path 依赖 legacy
  sequencing class；
- compatibility facade 由现有 `FixedMainlineRequest` /
  `build_fixed_mainline_request()` 演进，内部只构造 `AdaptiveMainlineRequest` 并
  delegate 到 `AdaptiveMainlineRunner`，不新增 Runtime abstraction；
- `RolePathRunner` 在 MRR-10/MRR-11 期间仅为 legacy comparator 保留，未来 cleanup
  才属于 MRR-13。

Compatibility Bridge First 的含义不是保留第二套 authority，而是先提供
authority-free fixed request translation，再切换 caller。

## 12. `run_smoke` positioning

阶段性结论：

```text
MRR-10: run_smoke = LEGACY_COMPARATOR
canonical fixed entry adapter = FixedMainlineRequest/build_fixed_mainline_request
benchmark caller switch = outside MRR-10
```

因此 MRR-10 不删除或改写 `run_smoke`。它可以继续生成 legacy comparison data，
但其 task/attempt/grant/state/artifact/memory identifiers 不能注入 canonical run。
如果后续保留同名 CLI/facade，必须由后续入口迁移明确处理；本设计不预先决定
MRR-11 benchmark ownership。

## 13. Fixed behavior parity contract

### Semantic parity — Gate required

- same current input meaning / task contract；
- same prompt semantics where those prompts are part of fixed behavior；
- same role-local structured decision class；
- same selected route/tool semantics when relevant；
- same Artifact truth outcome class；
- same Memory outcome class under the same approved Memory policy；固定 recipe 为
  `requested_memory_policy="none"` 时，两条 parity lane 都应观察为未授权/未提交，
  不能为了对齐 legacy cache behavior 扩大 plan policy；
- same final semantic answer class。

### Structural parity — Gate required

- logical role topology remains retriever→executor→summarizer；
- input/output ref kinds remain compatible；
- each role maps to the same logical capability intent；
- canonical run has one RuntimeTaskID and distinct current Attempts；
- every provider call has Runtime-issued Binding and Grant。

### Authority parity — Gate required and stronger than legacy parity

- legacy result cannot authorize canonical execution；
- only Engine creates Attempt/Binding/Grant；
- only Runtime admits result, verifies Artifact and commits Memory/State truth；
- comparator outputs never provide current Attempt ID or Grant。

### Byte-for-byte parity — Not required

Prompt serialization、timing、token counts、prefix cache counters、logit byte layout、
workspace file order 和 telemetry event bytes 不作为 Gate，除非一个现有 public
contract 明确把某个 digest 定为语义身份。要求这些字节相等会把 legacy
instrumentation 误升格为 truth。

## 14. Legacy comparator isolation

legacy `RolePathRunner` / `run_smoke` 可以：

- 独立运行并产生 comparator record；
- 计算 semantic/structural parity；
- 暴露 diagnostics 解释差异。

它们不能：

- 给 canonical run 提供 Attempt ID、Binding、Grant 或 admission receipt；
- 把 legacy State/Memory/Artifact refs 当作 current authorized refs；
- 让 legacy success 覆盖 canonical failure；
- 把 comparator equality 当作 Runtime authorization。
