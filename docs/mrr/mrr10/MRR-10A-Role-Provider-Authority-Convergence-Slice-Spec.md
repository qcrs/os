# MRR-10A — Role Provider Authority Convergence Slice Spec

## Objective

把现有 RolePath retriever、executor、summarizer 的真实 role-local behavior 放入
Runtime-issued current Attempt/Binding/Grant 边界，且不引入新的 Runtime
authority。

## In scope

- extract/reuse prompt、schema、parser、request audit、deterministic formatting；
- concrete retriever/executor/summarizer provider adapters；
- adapter entry 接收 `BoundCapabilityGrant`；
- bound provider identity → physical LLM config/client resolution；
- current dispatcher retrieval/transform/CodeAct/summarizer mechanism integration；
- provider failure 投影到 `AdaptiveStepResult.error_code/retryable`，detail 使用
  既有 non-authoritative telemetry/data-plane evidence；
- prefix/logit/usage telemetry sideband。

## Out of scope

```text
fixed benchmark entry migration
run_smoke deletion/rewrite
full compatibility facade caller switch
MRR-11
competition E2E
provider registry redesign
plan topology change
State/Artifact/Memory contract redesign
```

## Provider invariants

对每个 provider：

1. input witness 是 current `BoundCapabilityGrant`；
2. `task_id/session_id/step_id/attempt_id/capability_id` 与 binding/grant 一致；
3. physical client 只由 `selected_provider_id/version` 解析；
4. input refs 是 `grant.input_ref_ids`，Memory 是 `grant.memory_ref_ids`；
5. State access only via `StateAccessGrant`；
6. exactly one logical Step execution；
7. 不创建 Attempt，不调用 next role，不自行 retry/rebind/replan/fallback；
8. 返回 candidate `AdaptiveStepResult`；
9. 不验证/commit Artifact truth，不 admission Memory，不 settle result。

## Mechanism mappings

| Provider | Real current mechanism to preserve | Runtime-owned enforcement |
| --- | --- | --- |
| Retriever | RolePath retrieval prompt/candidate/EvidenceRequest + registered retrieval callable | Binding/Grant、coverage、State access/admission、result admission |
| Executor | RolePath executor choice + TransformProgram or bounded CodeAct source | execution kind, sandbox/workspace, validators, candidate Artifact, verification |
| Summarizer | RolePath summary/ClaimSet/citation repair | verified refs, ClaimSet validation, candidate Artifact, result admission |

## Retry rule

一次 provider invocation 产生一次 success/failure candidate。malformed JSON、
logit rejection、model error 不在 provider 内发起新的 semantic completion；返回
`error_code`、`retryable` 和 diagnostic。只有 Engine 可以创建 fresh Attempt。

## Gate

Primary targeted test：真实三个 adapter 各执行一次，捕获
`BoundCapabilityGrant`，并以 spy/observable state 证明：

```text
Attempt creation count in providers = 0
next-role calls = 0
provider override/fallback count = 0
direct State/Memory/Artifact commit count = 0
candidate result count per invocation = 1
```

Mechanism Gate 必须看到实际 retrieval、executor mechanism、summarizer mechanism，
不能只返回 synthetic `fixed-compatibility:*` refs。

## Exit criteria

```text
Provider Adapter Extraction = COMPLETE
Single-Step Authority = PASS
Physical Binding Enforcement = PASS
Provider-owned Retry/Replan/Commit = ABSENT
Benchmark Entry = UNCHANGED
Competition Gate = UNVALIDATED
```
