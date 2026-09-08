# MRR-10B — Fixed Compatibility Facade / Parity Slice Spec

## Dependency

MRR-10A accepted。10B 不得通过临时 fake provider 绕过该依赖。

## Objective

让 fixed compatibility entry 使用 `StaticRoleRecipe` / `ApprovedPlanBundle`，由
一个 `AdaptiveMainlineRunner` 和一个 `AdaptiveRuntimeEngine` 运行真实三角色链；
legacy RolePath/smoke 只保留为隔离 comparator。

## Canonical facade

复用并演进现有：

```text
FixedMainlineRequest
  → build_fixed_mainline_request
  → AdaptiveMainlineRequest
  → AdaptiveMainlineRunner
  → AdaptiveRuntimeEngine
```

`RolePathRunner` 不成为 canonical facade。它最终采用 option B：抽出 helpers/
providers 后只服务 legacy comparator，未来 cleanup 留给 MRR-13。

## In scope

- fixed task identity/contract → static recipe/bundle request construction；
- frozen `retriever → executor → summarizer` topology；
- canonical capability descriptors and Runtime provider binding；
- 10A real adapters wired into existing dispatcher；
- one representative fixed full-graph integration；
- isolated legacy-vs-canonical semantic parity；
- authority-free compatibility output projection if a caller needs legacy-shaped
  diagnostics。

## Out of scope

```text
fixed_answer_runner caller switch
benchmark ownership
run_smoke removal
Competition E2E
MRR-11
deprecation/cleanup
new Runtime abstraction
new provider registry or plan topology
```

## Facade invariants

Facade 可以构造 identity、task contract、envelope、recipe/bundle、registry 和
bindings。Facade 不得：

- 调用 planner/retriever/executor/summarizer method chain；
- 先运行 retrieval/CodeAct/summary；
- 创建 Attempt、Binding、Grant；
- 查询/commit Memory；
- publish/read State；
- materialize authoritative Artifact；
- verify or settle result。

所有 actual work 从 `AdaptiveRuntimeEngine` 创建第一 READY Attempt 后开始。

## Full-graph Gate

一个 representative fixed task 应产生：

| Step | Required authority evidence |
| --- | --- |
| retriever | current Attempt A、Binding A、Grant A、admitted evidence ref |
| executor | current Attempt B、Binding B、Grant B、input ref 来自 A、candidate Artifact + Runtime verification |
| summarizer | current Attempt C、Binding C、Grant C、verified Artifact/Evidence inputs、admitted final candidate |

共同断言：

```text
one RuntimeTaskID
one RuntimeTaskSession lineage
three distinct Attempt IDs
three Runtime-issued ExecutionBindingReceipts
three Runtime-issued BoundCapabilityGrants
one AdaptiveRuntimeEngine authority
zero canonical calls to run_smoke / legacy RuntimeDriver.run
```

## Parity Gate

在隔离 roots 中以同一 logical input 分别运行 legacy comparator 与 canonical
fixed facade。Gate 比较：

- logical role order；
- role-local semantic decision/output class；
- route/tool semantics（若 task relevant）；
- Artifact verification outcome class；
- Memory outcome class；
- final semantic answer class。

Byte-for-byte telemetry、UUID、path、timing、prefix/logit bytes 不比较。legacy
输出不能给 canonical run 提供 current IDs、refs 或 authorization。

## Test budget

```text
Primary 1: canonical fixed full-graph integration
Primary 2: legacy-vs-canonical semantic parity
Adjacent regression: at most one, only if MRR-10A did not cover helper compatibility
```

## Exit criteria

```text
RolePath compatibility facade authority = 0
Canonical full graph = PASS
Semantic parity = PASS
Structural parity = PASS
Authority parity = PASS
Benchmark entry = UNCHANGED
Competition Gate = UNVALIDATED
```

