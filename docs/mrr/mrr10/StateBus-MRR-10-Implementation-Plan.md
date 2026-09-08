# StateBus MRR-10 — Implementation Plan

> 这是后续 implementation 的 blueprint。本轮没有执行其中任何修改或测试。

## 1. Delivery order

```text
MRR-10A
Role Provider Authority Convergence
  ↓ Gate acceptance
MRR-10B
Fixed Compatibility Facade + Canonical Full-Graph Parity
  ↓
STOP before benchmark entry migration
```

10A 先关闭 provider 自行 sequencing/select/retry/commit 风险；10B 才允许 fixed
facade 使用这些 adapters。不能先把 legacy `run_smoke` 包在 Mainline 外层再补
authority，因为那只是事后签名。

## 2. MRR-10A work packages

### 2.1 Separate reusable role-local logic

从 `RolePathRunner` 的 legacy orchestration surface 中抽出或直接复用无 authority
逻辑：

- prompt instructions、prompt renderer、prefix layout；
- structured output schemas/parsers；
- EvidenceRequest / TransformProgram / ClaimSet candidate builders；
- request audit、usage、confidence、logit sideband formatting；
- deterministic role-local candidate normalization。

迁移不得改变 prompt semantics，除非 targeted parity test 证明变更是修复现有
authority leakage 所必需。`RolePathRunner` 保持 legacy comparator callable，
但 canonical imports 不得依赖它。

### 2.2 Add three concrete binding-aware provider adapters

在 runtime provider integration 层实现 concrete retriever/executor/summarizer
adapters。每个公开 execute seam 必须包含：

```text
PlanStepProposal
BoundCapabilityGrant
RuntimeIdentity/current Attempt context
attempt workspace
authorized typed refs
```

不必新增 generic provider framework；优先使用现有
`AdaptiveMainlineBindings` / `AdaptiveDispatchContext` / dispatcher execution
kinds。若需要 wiring map，它只能按
`ExecutionBindingReceipt.selected_provider_id` 解析已经被 Runtime 选中的 adapter，
不能重新排序、filter 或 fallback providers。

### 2.3 Close current plain-Grant callback gap

当前 dispatcher outer seam 校验 `BoundCapabilityGrant`，但 role factories/
`BuiltinHandler` 多数只收到 `CapabilityGrant`。implementation 应让 real provider
entry 收到完整 binding witness。可以在 dispatcher 内保留 plain grant 用于
既有 validator/typed operations，但不能只给 provider plain grant。

验收重点是 source/runtime evidence，不是 callback 类型名字。

### 2.4 Bind physical LLM client to Runtime selection

保留 `LLMConfig`/`ProviderConfig` 的 endpoint、credentials、model 和 request
settings。添加或调整 client resolution，使输入是 bound provider identity。

Canonical adapter 不得：

- 使用 `role_config.provider` 覆盖 binding；
- 在 provider failure 后换 model/provider；
- 在 malformed JSON、logit rejection 或 provider error 后重新完成 role call。

当前 `_complete_json_role()` 和 `_create_completion_with_retry()` 的 repeated
completion behavior 只可留在 legacy comparator，或拆为 single-call helper。
canonical provider 应返回 `AdaptiveStepResult.error_code/retryable` 和既有
non-authoritative diagnostic evidence，交给 Engine 的 fresh Attempt policy。

### 2.5 Reuse existing canonical mechanism seams

- Retriever：`AdaptiveRetrievalAdapter`、coverage verification、
  `RuntimeStateAccessAuthority`；
- Executor：`TRANSFORM_DSL` / `LLM_BOUNDED_PYTHON` 的 existing dispatcher path、
  capability validators、candidate Artifact；
- Summarizer：verified Artifact/Evidence input check、ClaimSet factory/validator；
- Memory：只使用 `grant.memory_ref_ids` 和 `_memory_inputs_for_step()`。

不要把 `run_smoke` 的 direct State store、Memory store、workspace materialization
或 `RuntimeCommitGate` 拷入 provider。

### 2.6 MRR-10A verification

只实现并运行 blueprint 中的 primary one-step provider authority test 和必要的
prompt/parser adjacent regression。10A 不跑 full fixed benchmark 或 Competition
E2E。

## 3. MRR-10B work packages

### 3.1 Evolve existing fixed facade

目标 facade 是现有：

```text
FixedMainlineRequest
  → build_fixed_mainline_request
  → AdaptiveMainlineRequest
  → AdaptiveMainlineRunner
```

`RuntimeDriver.run_mode("strict_fixed", fixed_request=...)` 当前已经 delegate 到
`run_adaptive_mainline()`，且不需要调用 legacy `RuntimeDriver.run()`。保留这个
delegate shape；不要把 `RolePathRunner` 改造成另一个 full-run facade。

### 3.2 Replace fake compatibility bindings

`fixed_mainline.py::_compatibility_result()` 和三个 `deterministic_*_handler`
当前只返回 synthetic refs。MRR-10B 必须让 canonical fixed bindings 改为指向
10A 的真实 adapters 和现有 dispatcher mechanisms；本 slice 不以 cleanup 为
目的，旧 handler definitions 的删除仍留给 MRR-13。

Capability descriptors 应复用当前 canonical domain-pack/capability registry
semantics，而不是在 facade 中创造 RolePath-specific logical capabilities 或
第二 provider registry。固定 recipe 的 capability IDs/topology 不变。

### 3.3 Build current task inputs without pre-execution

facade 可以完成：

- `RuntimeIdentity` / `TaskContractIdentity` validation；
- `CanonicalTaskSpec` / envelope construction；
- `StaticRoleRecipe` / `ApprovedPlanBundle` selection；
- registered provider/config/binding inputs；
- corpus/config refs 和 initial current inputs；
- authority-free prompt/provider adapter wiring。

facade 不得预先运行 retrieval、CodeAct、summarizer、Memory lookup、State publish、
Artifact materialization 或 validator commit。

### 3.4 Preserve legacy comparator isolation

MRR-10B 不改 `fixed_answer_runner.py`，不删除 `run_smoke`，不把 legacy outputs
传给 canonical request。Parity test 自己创建两个隔离 runtime roots，以相同
logical task input 分别运行 legacy comparator 和 canonical facade。

### 3.5 MRR-10B verification

运行：

- primary canonical fixed full-graph integration；
- primary semantic parity；
- 如果 10A 后未覆盖，则最多一个 adjacent prompt/parser regression。

禁止扩大到 Competition E2E 或正式 benchmark entry migration。

## 4. Planned file impact

精确文件名可由 implementation 按当前 module boundaries 决定，但 authority
归属必须遵循：

| File / area | Planned responsibility | Forbidden change |
| --- | --- | --- |
| `statebus/runtime/role_path.py` or a narrow role-provider helper module | pure prompt/parser/candidate helpers；legacy wrapper remains | full graph execution、Attempt/commit authority |
| `statebus/runtime/adaptive_dispatcher.py` | binding-aware one-step provider invocation；existing validation/State/Artifact/Memory gates | provider selection or plan sequencing |
| `statebus/runtime/adaptive_mainline.py` | wire selected role provider implementations into existing context | new fixed runtime or duplicate commit path |
| `statebus/runtime/fixed_mainline.py` | authority-free fixed request facade；real adapter bindings | direct role execution or fake success refs as Mechanism Gate |
| `statebus/integrations/llm.py` | bound-provider client resolution and single-call request helper | role-based provider override/fallback |
| targeted tests | Source/Mechanism/Integration/Parity assertions | benchmark migration or dozens of duplicative tests |
| `statebus/runtime/smoke.py` | no MRR-10 change unless a minimal comparator-only import separation is strictly required | canonical entry rewrite, sequencing cleanup, deletion |
| `statebus/benchmark/fixed_answer_runner.py` | no MRR-10 change | MRR-11 work |

如果实现发现必须修改 `AdaptiveMainlineBindings`，应只增加/收紧 provider
execution wiring；不得增加新的 scheduler、session、plan、memory 或 commit
abstraction。

## 5. Implementation stop conditions

立即停止并要求 architecture review，如果出现：

- 必须修改 frozen Plan topology 或 PlanPolicy contract 才能接入；
- 必须让 provider 自行选择 physical provider/model；
- 必须让 compatibility facade 创建 Attempt 或循环 steps；
- 必须绕过 `StateAccessGrant`、Artifact verification 或 Memory admission；
- 必须从 legacy comparator 复制 current IDs/refs 才能达到 parity；
- benchmark entry migration 才能证明 MRR-10（这说明 slice scope 已混入 MRR-11）。

## 6. Completion criteria

MRR-10 只有同时满足以下条件才可在未来 implementation review 中关闭：

```text
10A Source Gate PASS
10A Mechanism Gate PASS
10B Integration Gate PASS
10B Parity Gate PASS

RolePath canonical authority count = 0
Canonical Runtime engine count per fixed run = 1
Competition Gate = UNVALIDATED
```
